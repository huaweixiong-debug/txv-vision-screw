"""扫码枪最终测试 — 写到文件，确保可靠运行"""
import serial
import time
import os
import datetime

COM_PORT = "COM3"
BAUDRATE = 115200
RESULT_FILE = r"C:\Users\A\expansion_valve_hmi\scan_result.txt"

# Write start marker
with open(RESULT_FILE, "w", encoding="utf-8") as f:
    f.write(f"START {datetime.datetime.now()}\n")
    f.write(f"PORT={COM_PORT} BAUD={BAUDRATE}\n")

    # List ports
    try:
        import serial.tools.list_ports
        for p in serial.tools.list_ports.comports():
            f.write(f"PORT: {p.device} — {p.description}\n")
    except Exception as e:
        f.write(f"LIST_ERROR: {e}\n")

    # Open COM3
    ser = None
    try:
        ser = serial.Serial(
            port=COM_PORT, baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE, timeout=0.05,
        )
        f.write(f"OPEN_OK\n")
        f.flush()
    except Exception as exc:
        f.write(f"OPEN_FAIL: {exc}\n")
        f.flush()
        return

    # Read loop — 30 seconds
    buffer = b""
    count = 0
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            waiting = ser.in_waiting
            if waiting > 0:
                chunk = ser.read(waiting)
                buffer += chunk
                # Parse lines
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
                        count += 1
                        hex_str = " ".join(f"{b:02X}" for b in raw)
                        f.write(f"\nSCAN#{count}: {code}\n")
                        f.write(f"HEX: {hex_str}\n")
                        f.write(f"LEN: {len(code)}\n")
                        f.flush()
            else:
                time.sleep(0.03)
        except Exception as exc:
            f.write(f"READ_ERROR: {exc}\n")
            f.flush()
            break

    ser.close()
    f.write(f"\nEND count={count} time={datetime.datetime.now()}\n")
