from __future__ import annotations

import socketserver
import threading
import time
from collections.abc import Callable

import serial
from serial.tools import list_ports


class ScannerTcpHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server: ScannerTcpServer = self.server  # type: ignore[assignment]
        buffer = b""
        while not server.should_stop:
            data = self.request.recv(1024)
            if not data:
                break
            buffer += data
            while b"\n" in buffer or b"\r" in buffer:
                split_positions = [pos for pos in (buffer.find(b"\n"), buffer.find(b"\r")) if pos >= 0]
                split_at = min(split_positions)
                raw = buffer[:split_at]
                buffer = buffer[split_at + 1 :]
                code = raw.decode("utf-8", errors="ignore").strip()
                if code:
                    server.on_scan(code)
        code = buffer.decode("utf-8", errors="ignore").strip()
        if code:
            server.on_scan(code)


class ScannerTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, host: str, port: int, on_scan: Callable[[str], None]) -> None:
        super().__init__((host, port), ScannerTcpHandler)
        self.on_scan = on_scan
        self.should_stop = False
        self._thread: threading.Thread | None = None

    def start_background(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.serve_forever, name="scanner-tcp", daemon=True)
        self._thread.start()

    def stop_background(self) -> None:
        self.should_stop = True
        self.shutdown()
        self.server_close()


class SerialScanner:
    """Read barcode data from a serial COM port (USB virtual COM)."""

    TRIGGER_START = bytes.fromhex("16 54 0D")
    TRIGGER_STOP = bytes.fromhex("16 55 0D")

    def __init__(
        self,
        com_port: str,
        baudrate: int = 115200,
        on_scan: Callable[[str], None] | None = None,
    ) -> None:
        self.com_port = com_port
        self.baudrate = baudrate
        self.on_scan = on_scan
        self._ser: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self.should_stop = False
        self._retry_delay_s = 2.0
        self._retry_delay_max_s = 15.0
        self._last_connect_error = ""
        self._write_lock = threading.Lock()

    def connect(self) -> bool:
        try:
            self._ser = serial.Serial(
                port=self.com_port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.5,
                dsrdtr=False,
                rtscts=False,
                xonxoff=False,
            )
            # Toggle DTR to wake up scanner (some scanners need this)
            self._ser.dtr = False
            time.sleep(0.05)
            self._ser.dtr = True
            # Discard any stale bytes in buffer
            self._ser.reset_input_buffer()
            self._retry_delay_s = 2.0
            self._last_connect_error = ""
            print(f"[Scanner] Serial connected: {self.com_port} @ {self.baudrate}")
            return True
        except Exception as exc:
            message = f"[Scanner] Serial open failed ({self.com_port}), retry in {self._retry_delay_s:.0f}s: {exc}"
            if message != self._last_connect_error:
                print(message)
                self._last_connect_error = message
            self._ser = None
            return False

    @property
    def connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def status_dict(self) -> dict[str, object]:
        return {
            "mode": "serial",
            "connected": self.connected,
            "com_port": self.com_port,
            "baudrate": self.baudrate,
            "last_error": self._last_connect_error,
        }

    def _ensure_connected(self) -> None:
        if self.connected:
            return
        if not self.connect():
            raise RuntimeError(f"Scanner not connected on {self.com_port}")

    def send_trigger(self, command: bytes) -> dict[str, object]:
        self._ensure_connected()
        assert self._ser is not None
        with self._write_lock:
            self._ser.write(command)
            self._ser.flush()
        print(f"[Scanner] TX {command.hex(' ')} -> {self.com_port}", flush=True)
        return {
            "ok": True,
            "connected": self.connected,
            "com_port": self.com_port,
            "baudrate": self.baudrate,
            "command_hex": command.hex(" ").upper(),
        }

    def trigger_start(self) -> dict[str, object]:
        return self.send_trigger(self.TRIGGER_START)

    def trigger_stop(self) -> dict[str, object]:
        return self.send_trigger(self.TRIGGER_STOP)

    @staticmethod
    def available_ports() -> list[str]:
        return sorted(port.device for port in list_ports.comports() if port.device)

    def _read_loop(self) -> None:
        buffer = b""
        last_data_time = 0.0
        last_heartbeat = 0.0
        loop_count = 0
        print(f"[Scanner] _read_loop started (thread={threading.current_thread().name})", flush=True)
        while not self.should_stop:
            try:
                # ---- reconnect ----
                if self._ser is None or not self._ser.is_open:
                    time.sleep(self._retry_delay_s)
                    ok = self.connect()
                    if not ok:
                        self._retry_delay_s = min(self._retry_delay_s * 2.0, self._retry_delay_max_s)
                    buffer = b""
                    last_heartbeat = 0.0
                    continue

                # ---- read: blocking read first, then drain remaining ----
                # Some USB CDC drivers don't report in_waiting correctly,
                # so we use a short blocking read as the primary trigger.
                waiting = self._ser.in_waiting
                if waiting > 0:
                    # Data already waiting — read it all
                    chunk = self._ser.read(waiting)
                    if chunk:
                        print(f"[Scanner] RAW rx {len(chunk)} bytes: {chunk[:40].hex()}...", flush=True)
                        buffer += chunk
                        last_data_time = time.monotonic()
                else:
                    # No data reported — try a short blocking read
                    # This catches data from drivers that don't update in_waiting promptly
                    byte = self._ser.read(1)
                    if byte:
                        buffer += byte
                        last_data_time = time.monotonic()
                        # Drain any remaining bytes
                        extra = b""
                        w = self._ser.in_waiting
                        if w > 0:
                            extra = self._ser.read(w)
                            buffer += extra
                        print(f"[Scanner] RAW rx {1 + len(extra)} bytes (blocking): {(byte + extra)[:40].hex()}...", flush=True)
                    else:
                        # No data — brief sleep
                        time.sleep(0.01)

                # ---- heartbeat: confirm thread is alive ----
                loop_count += 1
                now_hb = time.monotonic()
                if now_hb - last_heartbeat > 5.0:
                    print(f"[Scanner] heartbeat: alive, loops={loop_count}, in_waiting={waiting}, "
                          f"buf={len(buffer)}B, ser_open={self._ser.is_open if self._ser else False}", flush=True)
                    last_heartbeat = now_hb

                # ---- extract complete lines ----
                # Terminators: \r\n, \r, \n
                lines_found = False
                while True:
                    r_pos = buffer.find(b"\r")
                    n_pos = buffer.find(b"\n")
                    candidates = [(p, 1) for p in (r_pos, n_pos) if p >= 0]
                    if not candidates:
                        break
                    split_at, term_len = min(candidates, key=lambda x: x[0])
                    if buffer[split_at:split_at + 2] == b"\r\n":
                        term_len = 2
                    raw = buffer[:split_at]
                    buffer = buffer[split_at + term_len:]
                    code = raw.decode("utf-8", errors="ignore").strip()
                    if code:
                        lines_found = True
                        if self.on_scan:
                            try:
                                self.on_scan(code)
                            except Exception as exc:
                                print(f"[Scanner] on_scan error: {exc}", flush=True)

                # ---- timeout: flush buffer without terminator ----
                # If data arrived > 300ms ago and no terminator seen, treat
                # everything in the buffer as a single scan (some scanners
                # send raw data without CR/LF).
                if buffer and not lines_found and last_data_time > 0:
                    if time.monotonic() - last_data_time > 0.3:
                        code = buffer.decode("utf-8", errors="ignore").strip()
                        buffer = b""
                        last_data_time = 0.0
                        if code and self.on_scan:
                            try:
                                self.on_scan(code)
                            except Exception as exc:
                                print(f"[Scanner] on_scan error: {exc}", flush=True)

            except (OSError, serial.SerialException) as exc:
                print(f"[Scanner] read error: {exc}", flush=True)
                try:
                    if self._ser:
                        self._ser.close()
                except Exception:
                    pass
                self._ser = None
                buffer = b""
                time.sleep(2.0)
            except Exception as exc:
                # Catch-all — prevent thread death from unexpected errors
                print(f"[Scanner] unexpected error: {exc}", flush=True)
                time.sleep(1.0)

    def start_background(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.connect()
        self._thread = threading.Thread(target=self._read_loop, name="scanner-serial", daemon=True)
        self._thread.start()

    def stop_background(self) -> None:
        self.should_stop = True
        if self._ser and self._ser.is_open:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
