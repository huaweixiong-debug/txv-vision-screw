"""持续监听 COM3 — 记录所有收到的原始字节，循环检测多个波特率"""
import serial
import time
import os
import datetime

COM_PORT = "COM3"
LOG_FILE = r"C:\Users\A\expansion_valve_hmi\scan_raw.log"

# Common baud rates to try
BAUD_RATES = [9600, 19200, 38400, 57600, 115200]
TEST_SECONDS = 8  # seconds per baud rate

with open(LOG_FILE, "w", encoding="utf-8") as log:
    log.write(f"=== COM3 原始数据监听 ===\n")
    log.write(f"开始: {datetime.datetime.now()}\n")
    log.write(f"扫描枪: Vuquest 3310 Area-Imaging Scanner\n\n")

    # List ports
    try:
        import serial.tools.list_ports
        for p in serial.tools.list_ports.comports():
            log.write(f"  {p.device}: {p.description}\n")
            log.write(f"    vid={p.vid}, pid={p.pid}, mfg={p.manufacturer}\n")
    except Exception as e:
        log.write(f"列表失败: {e}\n")

    for baud in BAUD_RATES:
        log.write(f"\n{'='*60}\n")
        log.write(f">>> 测试波特率: {baud} ({TEST_SECONDS}秒窗口)\n")
        log.write(f">>> 请扫描条码...\n")
        log.flush()

        ser = None
        total_bytes = 0
        try:
            ser = serial.Serial(
                port=COM_PORT, baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.05,
            )
            log.write(f"    [OK] COM3 @ {baud} 打开成功\n")
            log.flush()
        except Exception as exc:
            log.write(f"    [FAIL] {exc}\n")
            log.flush()
            continue

        buffer = b""
        deadline = time.time() + TEST_SECONDS
        try:
            while time.time() < deadline:
                waiting = ser.in_waiting
                if waiting > 0:
                    chunk = ser.read(waiting)
                    buffer += chunk
                    total_bytes += len(chunk)
                    # Parse lines immediately
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
                        code = raw.decode("ascii", errors="replace").strip()
                        if code:
                            hex_str = " ".join(f"{b:02X}" for b in raw)
                            log.write(f"\n    !! 收到数据: {code}\n")
                            log.write(f"       HEX: {hex_str}\n")
                            log.write(f"       长度: {len(code)}\n")
                            log.flush()
                else:
                    time.sleep(0.03)
        except Exception as exc:
            log.write(f"    读取异常: {exc}\n")

        ser.close()
        if total_bytes == 0 and not buffer:
            log.write(f"    结果: 无任何数据\n")
        elif buffer:
            hex_str = " ".join(f"{b:02X}" for b in buffer[:200])
            log.write(f"    剩余未解析字节 ({len(buffer)} bytes): {hex_str}\n")
        log.write(f"    总收到: {total_bytes} 字节\n")
        log.flush()

    log.write(f"\n=== 测试结束 ===\n")
    log.write(f"结束: {datetime.datetime.now()}\n")
    log.write(f"\n提示：如果所有波特率都无数据，扫码枪可能仍处于 USB HID 键盘模式，\n")
    log.write(f"需要扫描配置码切换到 USB Serial (虚拟COM口) 模式。\n")
    log.write(f"Honeywell Vuquest 3310 切换串口模式需扫描手册中的 USB CDC 配置码。\n")
