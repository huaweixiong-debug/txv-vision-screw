"""Stop HMI, run scanner test (30s window), show results, restart HMI"""
import paramiko
import time

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"
TARGET = r"C:\Users\A\expansion_valve_hmi"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)
print("SSH connected\n")

# 1. Kill HMI
print("=== 停止 HMI ===")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(2)

# Verify COM3 free
i, o, e = c.exec_command(
    r'python -c "import serial; s=serial.Serial(\"COM3\", 115200, timeout=0.05); print(\"COM3 free\"); s.close()"',
    timeout=5,
)
com3_status = o.read().decode("gbk", errors="ignore").strip()
print(f"COM3: {com3_status}")

# 2. Upload test script v2
print("\n=== 上传测试脚本 ===")
sftp = c.open_sftp()
sftp.put(
    r"S:\expansion_valve_hmi\tools\_scanner_test_v2.py",
    rf"{TARGET}\scanner_test_v2.py",
)
sftp.close()
print("已上传")

# 3. Run test in background (30s window)
print("\n=== 启动扫码测试 (30秒窗口) ===")
print("请现在去目标机扫描条码...")
c.exec_command(
    rf'start /B python "{TARGET}\scanner_test_v2.py"',
    timeout=5,
)
print("测试脚本已在后台启动，等待30秒...")
time.sleep(32)  # give it 30s + 2s buffer

# 4. Read results
print("\n=== 测试结果 ===")
i, o, e = c.exec_command(
    rf'type "{TARGET}\scanner_test_result.txt"',
    timeout=5,
)
result = o.read().decode("utf-8", errors="ignore")
if result.strip():
    print(result.strip())
else:
    # Try reading directly via SFTP
    try:
        sftp2 = c.open_sftp()
        with sftp2.file(rf"{TARGET}\scanner_test_result.txt", "r") as f:
            result = f.read().decode("utf-8", errors="ignore")
        sftp2.close()
        print(result.strip())
    except Exception as exc:
        print(f"(无法读取结果: {exc})")
        # Try GBK
        i2, o2, e2 = c.exec_command(
            rf'type "{TARGET}\scanner_test_result.txt"',
            timeout=5,
        )
        raw = o2.read()  # raw bytes
        for enc in ["utf-8", "gbk", "gb2312", "latin-1"]:
            try:
                text = raw.decode(enc)
                print(f"[{enc}]: {text[:500]}")
                break
            except Exception:
                continue

# 5. Restart HMI
print("\n=== 重启 HMI ===")
launcher = (
    'import subprocess, sys, os\r\n'
    rf'os.chdir(r"{TARGET}")' + '\r\n'
    'flags = 0x01000000 | 0x00000008\r\n'
    'with open("stdout.log", "w") as out, open("stderr.log", "w") as err:\r\n'
    '    p = subprocess.Popen([sys.executable, "run.py", "--host", "0.0.0.0", "--port", "8010"],\r\n'
    '        stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=flags)\r\n'
    '    print("PID=" + str(p.pid))\r\n'
)
sftp3 = c.open_sftp()
with sftp3.file(rf"{TARGET}\launch.py", "w") as f:
    f.write(launcher)
sftp3.close()

i, o, e = c.exec_command(rf'python "{TARGET}\launch.py"', timeout=10)
print("启动:", o.read().decode("gbk", errors="ignore").strip())
time.sleep(6)

# Verify
i, o, e = c.exec_command("netstat -ano | findstr 8010", timeout=5)
port_out = o.read().decode("gbk", errors="ignore")
if "LISTENING" in port_out:
    print("HMI 已重启 (端口 8010)")
else:
    print("HMI 可能还在启动...")

c.close()
print("\n完成!")
