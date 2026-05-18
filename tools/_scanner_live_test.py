"""Live scanner test — run interactive test on remote, capture results"""
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
print("=== Step 1: Stop HMI ===")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(2)

# Verify COM3 free
i, o, e = c.exec_command(
    r'python -c "import serial; s=serial.Serial(\"COM3\", 115200, timeout=0.05); s.close(); print(\"FREE\")"',
    timeout=5,
)
print("COM3:", o.read().decode("gbk", errors="ignore").strip())

# 2. Upload
print("\n=== Step 2: Upload test script ===")
sftp = c.open_sftp()
sftp.put(
    r"S:\expansion_valve_hmi\tools\_scanner_continuous.py",
    rf"{TARGET}\scanner_continuous.py",
)
sftp.close()

# 3. Run it (40s total)
print("\n=== Step 3: Running 5 baud rates x 8s each ===")
print("PLEASE SCAN BARCODE DURING EACH WINDOW!")
print("波特率: 9600 → 19200 → 38400 → 57600 → 115200\n")

i, o, e = c.exec_command(rf'python "{TARGET}\scanner_continuous.py"', timeout=60)
out = o.read().decode("gbk", errors="ignore").strip()
print(out if out else "(no stdout)")
err = e.read().decode("gbk", errors="ignore").strip()
if err:
    print("STDERR:", err[:300])

# 4. Read log file
print("\n=== Step 4: Log file ===")
try:
    sftp2 = c.open_sftp()
    with sftp2.file(rf"{TARGET}\scan_raw.log", "r") as f:
        log_data = f.read().decode("utf-8", errors="ignore")
    sftp2.close()
    print(log_data.strip())
except Exception as exc:
    print(f"SFTP read failed: {exc}")
    i2, o2, e2 = c.exec_command(rf'type "{TARGET}\scan_raw.log"', timeout=5)
    log_data = o2.read().decode("utf-8", errors="ignore")
    print(log_data.strip() or "(empty)")

# 5. Restart HMI
print("\n=== Step 5: Restart HMI ===")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(2)

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
print(o.read().decode("gbk", errors="ignore").strip())
time.sleep(6)

i, o, e = c.exec_command("netstat -ano | findstr 8010", timeout=5)
if "LISTENING" in o.read().decode("gbk", errors="ignore"):
    print("HMI restarted OK")
else:
    print("HMI starting...")

c.close()
