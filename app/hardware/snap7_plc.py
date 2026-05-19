"""Snap7 client wrapper for Siemens S7-200 Smart PLC communication.

Provides M-bit read/write (handshake signals) and V-area read/write
(data exchange). Auto-reconnect with configurable retry interval.
"""
from __future__ import annotations

import threading
import time as _time
from typing import Any


# ---------------------------------------------------------------------------
# M-bit address table — automation handshake signals
# ---------------------------------------------------------------------------

# PC -> PLC outputs
M_BITS_OUT: dict[str, tuple[int, int, str]] = {
    #  M-addr    -> (byte_offset, bit_index, label)
    "M0.0": (0, 0, "product_ready"),       # O型圈+膨胀阀合格
    "M0.1": (0, 1, "tightening_ok"),        # 拧紧合格
    "M0.2": (0, 2, "scan_complete"),        # 扫码合格
    "M0.7": (0, 7, "disable_scan"),         # 屏蔽扫码
    "M1.0": (1, 0, "tightening_ng"),        # 拧紧不合格
}

# PLC -> PC inputs
M_BITS_IN: dict[str, tuple[int, int, str]] = {
    "M0.3": (0, 3, "manual_mode"),       # 1=手动, 0=自动
    "M0.4": (0, 4, "plc_estop"),         # 急停
    "M0.5": (0, 5, "plc_ready"),         # 1s脉冲/1s间隔
    "M0.6": (0, 6, "plc_reset"),         # PLC复位
    "M10.2": (10, 2, "plc_tightening_done"),
}

# M bytes range needed for bulk read (bytes 0..11 covers M0.0-M11.7)
M_READ_START = 0
M_READ_SIZE = 12   # 12 bytes = M0.0 through M11.7


class Snap7Client:
    """Thin wrapper around python-snap7 Client with connection management.

    Uses ``mb_read`` / ``mb_write`` for M area and ``db_read`` / ``db_write``
    for V area (S7-200 SMART maps V memory to DB1).
    """

    def __init__(
        self,
        ip: str,
        rack: int = 0,
        slot: int = 1,
        timeout: float = 2.0,
        reconnect_interval: float = 5.0,
    ) -> None:
        self._ip = ip
        self._rack = rack
        self._slot = slot
        self._timeout = timeout
        self._reconnect_interval = reconnect_interval
        self._client: Any = None
        self._lock = threading.RLock()
        self._connected = False

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Establish connection to PLC. Returns True on success."""
        with self._lock:
            return self._connect_locked()

    def _connect_locked(self) -> bool:
        if self._connected and self._client is not None:
            try:
                if self._client.get_connected():
                    return True
            except Exception:
                self._connected = False

        try:
            import snap7.client as _client
            self._client = _client.Client()
            self._client.set_connection_params(
                self._ip, self._rack, self._slot
            )
            self._client.set_param(0, int(self._timeout * 1000))  # Connect timeout ms
            self._client.connect(self._ip, self._rack, self._slot)
            self._connected = True
            print(f"[Snap7] Connected to {self._ip} (rack={self._rack}, slot={self._slot})")
            return True
        except Exception as exc:
            print(f"[Snap7] Connect failed ({self._ip}): {exc}")
            self._connected = False
            self._client = None
            return False

    def disconnect(self) -> None:
        """Gracefully disconnect from PLC."""
        with self._lock:
            if self._client is not None:
                try:
                    self._client.disconnect()
                except Exception:
                    pass
                try:
                    self._client.destroy()
                except Exception:
                    pass
                self._client = None
            self._connected = False

    def ensure_connected(self) -> bool:
        """Check connection; attempt reconnect if down and interval elapsed."""
        with self._lock:
            if self._check_alive_locked():
                return True
        # Reconnect attempt
        print(f"[Snap7] Connection lost, reconnecting to {self._ip}...")
        self.disconnect()
        _time.sleep(0.5)
        return self.connect()

    def _check_alive_locked(self) -> bool:
        if self._client is None or not self._connected:
            return False
        try:
            return self._client.get_connected()
        except Exception:
            self._connected = False
            return False

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._check_alive_locked()

    # ------------------------------------------------------------------
    # M-bit read / write
    # ------------------------------------------------------------------

    def read_m_byte(self, byte_offset: int) -> int:
        """Read a single M byte (M{byte_offset}.0 - M{byte_offset}.7)."""
        with self._lock:
            data = self._client.mb_read(byte_offset, 1)
            return data[0]

    def read_m_bits(self, start_byte: int = M_READ_START, size: int = M_READ_SIZE) -> bytearray:
        """Bulk-read M area bytes. Returns bytearray of length *size*."""
        with self._lock:
            return bytearray(self._client.mb_read(start_byte, size))

    def read_m_bit(self, byte_offset: int, bit_index: int) -> bool:
        """Read a single M bit (e.g. M10.2 → byte_offset=10, bit_index=2)."""
        b = self.read_m_byte(byte_offset)
        return bool((b >> bit_index) & 1)

    def write_m_bit(self, byte_offset: int, bit_index: int, value: bool) -> None:
        """Write a single M bit using read-modify-write."""
        with self._lock:
            current = self.read_m_byte(byte_offset)
            if value:
                new_val = current | (1 << bit_index)
            else:
                new_val = current & ~(1 << bit_index)
            if new_val != current:
                self._client.mb_write(byte_offset, 1, bytearray([new_val]))

    def read_all_m_inputs(self) -> dict[str, bool]:
        """Read all M_BITS_IN signals in one bulk read. Returns {label: value}."""
        data = self.read_m_bits(M_READ_START, M_READ_SIZE)
        result: dict[str, bool] = {}
        for _, (bo, bi, label) in M_BITS_IN.items():
            result[label] = bool((data[bo] >> bi) & 1)
        return result

    def write_all_m_outputs(self, signals: dict[str, bool]) -> None:
        """Write M_BITS_OUT signals. *signals* maps label→value."""
        with self._lock:
            # Group by byte to minimize writes and keep read-modify-write atomic.
            byte_changes: dict[int, int] = {}
            for _, (bo, bi, label) in M_BITS_OUT.items():
                val = signals.get(label)
                if val is None:
                    continue
                if bo not in byte_changes:
                    byte_changes[bo] = self.read_m_byte(bo)
                if val:
                    byte_changes[bo] |= (1 << bi)
                else:
                    byte_changes[bo] &= ~(1 << bi)

            for bo, new_val in byte_changes.items():
                self._client.mb_write(bo, 1, bytearray([new_val]))

    # ------------------------------------------------------------------
    # V-area read / write (S7-200 SMART: V == DB1)
    # ------------------------------------------------------------------

    V_AREA_DB = 1  # S7-200 Smart maps V memory to DB1

    def read_v_bytes(self, start: int, size: int) -> bytearray:
        """Read *size* bytes from V area starting at *start*."""
        with self._lock:
            return bytearray(self._client.db_read(self.V_AREA_DB, start, size))

    def write_v_bytes(self, start: int, data: bytes) -> None:
        """Write bytes to V area starting at *start*."""
        with self._lock:
            self._client.db_write(self.V_AREA_DB, start, data)

    def read_v_word(self, start: int) -> int:
        """Read a 16-bit word from VW{start} (big-endian, unsigned)."""
        data = self.read_v_bytes(start, 2)
        return (data[0] << 8) | data[1]

    def write_v_word(self, start: int, value: int) -> None:
        """Write a 16-bit word to VW{start}."""
        self.write_v_bytes(start, bytes([(value >> 8) & 0xFF, value & 0xFF]))

    def read_v_dword(self, start: int) -> int:
        """Read a 32-bit double word from VD{start}."""
        data = self.read_v_bytes(start, 4)
        return (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]

    def write_v_dword(self, start: int, value: int) -> None:
        """Write a 32-bit double word to VD{start}."""
        self.write_v_bytes(
            start,
            bytes([
                (value >> 24) & 0xFF,
                (value >> 16) & 0xFF,
                (value >> 8) & 0xFF,
                value & 0xFF,
            ]),
        )
