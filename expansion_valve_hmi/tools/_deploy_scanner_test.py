"""Deploy scanner test files + restart HMI"""
import paramiko
import time

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"
TARGET = r"C:\Users\A\expansion_valve_hmi"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)
print("SSH OK")

# Kill
print("Kill python...")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(2)

# Upload changed files
sftp = c.open_sftp()
files = [
    (r"S:\expansion_valve_hmi\app\main.py", rf"{TARGET}\app\main.py"),
    (r"S:\expansion_valve_hmi\web\scanner-test.html", rf"{TARGET}\web\scanner-test.html"),
]
for src, dst in files:
    sftp.put(src, dst)
    print(f"  OK: {src.split(chr(92))[-1]}")
sftp.close()

# Restart HMI
print("Restart HMI...")
launcher = (
    'import subprocess, sys, os\r\n'
    rf'os.chdir(r"{TARGET}")' + '\r\n'
    'flags = 0x01000000 | 0x00000008\r\n'
    'with open("stdout.log", "w") as out, open("stderr.log", "w") as err:\r\n'
    '    p = subprocess.Popen([sys.executable, "run.py", "--host", "0.0.0.0", "--port", "8010"],\r\n'
    '        stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=flags)\r\n'
    '    print("PID=" + str(p.pid))\r\n'
)
sftp2 = c.open_sftp()
with sftp2.file(rf"{TARGET}\launch.py", "w") as f:
    f.write(launcher)
sftp2.close()

i, o, e = c.exec_command(rf'python "{TARGET}\launch.py"', timeout=10)
print("PID:", o.read().decode("gbk", errors="ignore").strip())
time.sleep(8)

# Verify
i, o, e = c.exec_command("netstat -ano | findstr 8010", timeout=5)
out = o.read().decode("gbk", errors="ignore")
if "LISTENING" in out:
    print("HMI running on port 8010")
else:
    print("HMI starting...")

# API test
import urllib.request, json
try:
    resp = urllib.request.urlopen("http://100.79.19.71:8010/api/health", timeout=5)
    print("Health:", json.loads(resp.read().decode()))
except Exception as ex:
    print(f"API check: {ex}")

c.close()
print("\n测试页: http://192.168.0.99:8010/scanner-test.html")
