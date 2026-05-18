"""扫码枪测试 v2 — 窗口持续30秒，结果写入文件，自动退出"""
import serial
import time
import os

COM_PORT = "COM3"
BAUDRATE = 115200
LOG_FILE = r"C:\Users\A\expansion_valve_hmi\scanner_test_result.txt"

def main():
    with open(LOG_FILE, "w", encoding="utf-8") as log:
        log.write(f"=== 扫码枪测试 ===\n")
        log.write(f"端口: {COM_PORT}, 波特率: {BAUDRATE}\n")

        # 列串口
        try:
            import serial.tools.list_ports
            for p in serial.tools.list_ports.comports():
                log.write(f"发现: {p.device} — {p.description}\n")
        except Exception as e:
            log.write(f"列串口失败: {e}\n")

        ser = None
        try:
            ser = serial.Serial(
                port=COM_PORT, baudrate=BAUDRATE,
                bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE, timeout=0.05,
            )
            log.write(f"[OK] COM3 打开成功\n")
            log.write(f"等待扫码 (30秒)...\n")
            log.flush()
        except Exception as exc:
            log.write(f"[FAIL] COM3: {exc}\n")
            return

        buffer = b""
        scan_count = 0
        deadline = time.time() + 30

        try:
            while time.time() < deadline:
                waiting = ser.in_waiting
                if waiting > 0:
                    chunk = ser.read(waiting)
                    buffer += chunk
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
                            scan_count += 1
                            hex_str = " ".join(f"{b:02X}" for b in raw)
                            log.write(f"\n[#{scan_count}] {code}\n")
                            log.write(f"HEX: {hex_str}\n")
                            log.write(f"长度: {len(code)} 字符\n")
                            log.flush()
                else:
                    time.sleep(0.03)
        except Exception as exc:
            log.write(f"读取异常: {exc}\n")
        finally:
            if ser and ser.is_open:
                ser.close()

        log.write(f"\n=== 测试结束，共 {scan_count} 条 ===\n")

if __name__ == "__main__":
    main()
