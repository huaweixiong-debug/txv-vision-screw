"""Stop HMI, run scanner test, capture output"""
import paramiko
import time
import sys

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)
print("SSH connected")

# 1. Kill HMI
print("Stopping HMI...")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(2)
print("HMI stopped\n")

# 2. Upload test script
sftp = c.open_sftp()
sftp.put(
    r"S:\expansion_valve_hmi\tools\_scanner_test.py",
    r"C:\Users\A\expansion_valve_hmi\scanner_test.py",
)
sftp.close()
print("Test script uploaded")

# 3. Verify COM3 is free
i, o, e = c.exec_command(
    r'python -c "import serial; s=serial.Serial(\"COM3\", 115200, timeout=0.05); print(\"COM3 OK\"); s.close()"',
    timeout=5,
)
print("COM3 check:", o.read().decode("gbk", errors="ignore").strip())
err = e.read().decode("gbk", errors="ignore").strip()
if err:
    print("COM3 ERR:", err[:200])

# 4. Run scanner test (10 seconds)
print("\n=== 扫码测试开始（10秒窗口）===")
print("请现在扫描条码...\n")

# Use exec_command with get_pty for interactive-ish output
i, o, e = c.exec_command(
    r'python C:\Users\A\expansion_valve_hmi\scanner_test.py',
    timeout=15,
)
time.sleep(10)  # Wait for user to scan

# Try to read what we got
try:
    out = o.read().decode("gbk", errors="ignore")
    if out.strip():
        print(out.strip())
    else:
        print("(无扫码数据 — 请尝试扫描条码)")
except Exception as exc:
    print(f"Read error: {exc}")

err_out = e.read().decode("gbk", errors="ignore").strip()
if err_out:
    print("STDERR:", err_out[:500])

# 5. Restart HMI
print("\n--- 重启 HMI ---")
launcher = (
    'import subprocess, sys, os\r\n'
    r'os.chdir(r"C:\Users\A\expansion_valve_hmi")' + '\r\n'
    'flags = 0x01000000 | 0x00000008\r\n'
    'with open("stdout.log", "w") as out, open("stderr.log", "w") as err:\r\n'
    '    p = subprocess.Popen([sys.executable, "run.py", "--host", "0.0.0.0", "--port", "8010"],\r\n'
    '        stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=flags)\r\n'
    '    print("PID=" + str(p.pid))\r\n'
)
sftp2 = c.open_sftp()
with sftp2.file(r"C:\Users\A\expansion_valve_hmi\launch.py", "w") as f:
    f.write(launcher)
sftp2.close()

c.exec_command(r'python C:\Users\A\expansion_valve_hmi\launch.py', timeout=10)
time.sleep(5)

# Verify
i, o, e = c.exec_command("netstat -ano | findstr 8010", timeout=5)
port_out = o.read().decode("gbk", errors="ignore")
if "LISTENING" in port_out:
    print("HMI restarted OK (port 8010)")
else:
    print("HMI may still be starting...")

c.close()
