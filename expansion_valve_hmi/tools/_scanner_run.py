"""Run scanner test reliably on remote machine"""
import paramiko
import time

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"
TARGET = r"C:\Users\A\expansion_valve_hmi"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)

# 1. Kill HMI
print("Killing HMI...")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(2)

# 2. Upload test script
print("Uploading test script...")
sftp = c.open_sftp()
sftp.put(
    r"S:\expansion_valve_hmi\tools\_scanner_final_test.py",
    rf"{TARGET}\scanner_final_test.py",
)
sftp.close()

# 3. Run via launcher pattern (same as HMI — it works)
print("Launching scanner test (30s)...")
launcher = (
    'import subprocess, sys, os\r\n'
    rf'os.chdir(r"{TARGET}")' + '\r\n'
    'flags = 0x01000000 | 0x00000008\r\n'
    'p = subprocess.Popen([sys.executable, "scanner_final_test.py"],\r\n'
    '    stdin=subprocess.DEVNULL, creationflags=flags)\r\n'
    'print("PID=" + str(p.pid))\r\n'
)
sftp2 = c.open_sftp()
with sftp2.file(rf"{TARGET}\launch_scan.py", "w") as f:
    f.write(launcher)
sftp2.close()

i, o, e = c.exec_command(rf'python "{TARGET}\launch_scan.py"', timeout=10)
launch_out = o.read().decode("gbk", errors="ignore").strip()
print(f"Launch: {launch_out}")
time.sleep(35)  # Wait for 30s test + buffer

# 4. Read result file
print("\n=== RESULT ===")
try:
    sftp3 = c.open_sftp()
    with sftp3.file(rf"{TARGET}\scan_result.txt", "r") as f:
        data = f.read().decode("utf-8", errors="ignore")
    sftp3.close()
    print(data.strip())
except Exception as exc:
    print(f"SFTP read failed: {exc}")
    # Try exec_command
    i2, o2, e2 = c.exec_command(rf'type "{TARGET}\scan_result.txt"', timeout=5)
    raw = o2.read()
    print(raw.decode("utf-8", errors="ignore").strip() or "(empty)")

# 5. Restart HMI
print("\n=== Restarting HMI ===")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(2)

launcher_hmi = (
    'import subprocess, sys, os\r\n'
    rf'os.chdir(r"{TARGET}")' + '\r\n'
    'flags = 0x01000000 | 0x00000008\r\n'
    'with open("stdout.log", "w") as out, open("stderr.log", "w") as err:\r\n'
    '    p = subprocess.Popen([sys.executable, "run.py", "--host", "0.0.0.0", "--port", "8010"],\r\n'
    '        stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=flags)\r\n'
    '    print("PID=" + str(p.pid))\r\n'
)
sftp4 = c.open_sftp()
with sftp4.file(rf"{TARGET}\launch.py", "w") as f:
    f.write(launcher_hmi)
sftp4.close()

i, o, e = c.exec_command(rf'python "{TARGET}\launch.py"', timeout=10)
print(o.read().decode("gbk", errors="ignore").strip())
time.sleep(6)

i, o, e = c.exec_command("netstat -ano | findstr 8010", timeout=5)
if "LISTENING" in o.read().decode("gbk", errors="ignore"):
    print("HMI OK on port 8010")

c.close()
