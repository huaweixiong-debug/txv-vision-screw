"""Deploy camera exposure + datasets page changes"""
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

# 2. Upload all changed files
sftp = c.open_sftp()
files = [
    (r"S:\expansion_valve_hmi\app\hardware\camera.py", rf"{TARGET}\app\hardware\camera.py"),
    (r"S:\expansion_valve_hmi\app\main.py", rf"{TARGET}\app\main.py"),
    (r"S:\expansion_valve_hmi\app\workflow.py", rf"{TARGET}\app\workflow.py"),
    (r"S:\expansion_valve_hmi\app\config.py", rf"{TARGET}\app\config.py"),
    (r"S:\expansion_valve_hmi\config\default_settings.json", rf"{TARGET}\config\default_settings.json"),
    (r"S:\expansion_valve_hmi\web\index.html", rf"{TARGET}\web\index.html"),
    (r"S:\expansion_valve_hmi\web\styles.css", rf"{TARGET}\web\styles.css"),
    (r"S:\expansion_valve_hmi\web\app.js", rf"{TARGET}\web\app.js"),
]
for src, dst in files:
    sftp.put(src, dst)
    print(f"  OK: {src.split(chr(92))[-1]}")
sftp.close()

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
print("Launch:", o.read().decode("gbk", errors="ignore").strip())

time.sleep(12)

# 4. Show stdout
i, o, e = c.exec_command(rf'type "{TARGET}\stdout.log"', timeout=5)
lines = o.read().decode("gbk", errors="ignore").strip().split("\n")
print("\n=== HMI stdout ===")
for line in lines:
    print(line)

c.close()
print("\nDone. http://192.168.0.99:8010/ → 训练数据")
