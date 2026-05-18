"""Deploy updated scanner.py and restart HMI"""
import paramiko
import time

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"
TARGET = r"C:\Users\A\expansion_valve_hmi"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)
print("SSH connected")

# 1. Kill HMI
print("Kill HMI...")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(3)

# 2. Upload scanner.py
print("Upload scanner.py...")
sftp = c.open_sftp()
sftp.put(
    r"S:\expansion_valve_hmi\app\hardware\scanner.py",
    rf"{TARGET}\app\hardware\scanner.py",
)
sftp.close()
print("  OK")

# 3. Restart HMI
print("Restart HMI...")
launcher = (
    'import subprocess, sys, os\r\n'
    rf'os.chdir(r"{TARGET}")' + '\r\n'
    'flags = 0x01000000 | 0x00000008\r\n'
    'with open("stdout.log", "w") as out, open("stderr.log", "w") as err:\r\n'
    '    p = subprocess.Popen([sys.executable, "-u", "run.py", "--host", "0.0.0.0", "--port", "8010"],\r\n'
    '        stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=flags)\r\n'
    '    print("PID=" + str(p.pid))\r\n'
)
sftp2 = c.open_sftp()
with sftp2.file(rf"{TARGET}\launch.py", "w") as f:
    f.write(launcher)
sftp2.close()

i, o, e = c.exec_command(rf'python "{TARGET}\launch.py"', timeout=10)
time.sleep(1)
print("PID:", o.read().decode("gbk", errors="ignore").strip())

time.sleep(8)

# 4. Verify
i, o, e = c.exec_command("netstat -ano | findstr 8010", timeout=5)
out = o.read().decode("gbk", errors="ignore")
if "LISTENING" in out:
    print("HMI running on port 8010")
else:
    print("Port 8010 status:", out.strip()[:80])

# 5. Show stdout
time.sleep(2)
i, o, e = c.exec_command(rf'type "{TARGET}\stdout.log"', timeout=5)
lines = o.read().decode("gbk", errors="ignore").strip().split("\n")
print("\n=== HMI stdout (last 30 lines) ===")
for line in lines[-30:]:
    print(line)

c.close()
print("\nDone. Scanner test page: http://192.168.0.99:8010/scanner-test.html")
