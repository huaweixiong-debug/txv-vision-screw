"""扫码枪测试 — 部署到目标机运行，验证 COM3 串口数据"""
import serial
import time
import sys

COM_PORT = "COM3"
BAUDRATE = 115200

def main():
    print(f"=== 扫码枪测试 ===")
    print(f"端口: {COM_PORT}, 波特率: {BAUDRATE}")
    print(f"请扫描条码，Ctrl+C 退出\n")

    # 先列出所有串口
    try:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            print(f"  发现: {p.device} — {p.description}")
    except Exception:
        pass

    ser = None
    try:
        ser = serial.Serial(
            port=COM_PORT,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
        )
        print(f"[OK] COM3 打开成功\n")
    except Exception as exc:
        print(f"[FAIL] 无法打开 COM3: {exc}")
        print("可能是 HMI 或其他程序占用了端口。先关闭 HMI 再测试。")
        return

    buffer = b""
    scan_count = 0
    try:
        while True:
            waiting = ser.in_waiting
            if waiting > 0:
                chunk = ser.read(waiting)
                buffer += chunk
                # 按行切分
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
                        print(f"[#{scan_count}] 文本: {code}")
                        print(f"        HEX: {hex_str}")
                        print(f"        长度: {len(code)} 字符\n")
            else:
                time.sleep(0.03)
    except KeyboardInterrupt:
        print(f"\n测试结束。共扫描 {scan_count} 条。")
    finally:
        if ser and ser.is_open:
            ser.close()
            print("COM3 已关闭")

if __name__ == "__main__":
    main()
