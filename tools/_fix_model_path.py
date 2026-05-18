"""Fix model path to use forward slashes and restart HMI"""
import paramiko
import time
import json

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"
TARGET = r"C:\Users\A\expansion_valve_hmi"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)

# Kill HMI
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(3)

# Fix settings with forward slashes
fix_script = r'''
import json
with open(r"C:\Users\A\expansion_valve_hmi\runtime\settings.json", "r", encoding="utf-8") as f:
    s = json.load(f)
s["vision"]["model_path"] = "D:/Camera Screw Project/best.pt"
s["vision"]["model_version"] = "best.pt"
with open(r"C:\Users\A\expansion_valve_hmi\runtime\settings.json", "w", encoding="utf-8") as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
print("OK")
'''

sftp = c.open_sftp()
with sftp.file(rf"{TARGET}\_fix_model.py", "w") as f:
    f.write(fix_script)
sftp.close()

i, o, e = c.exec_command(rf'python "{TARGET}\_fix_model.py"', timeout=8)
time.sleep(1)
print("Fix:", o.read().decode("gbk", errors="ignore").strip())

# Verify
i, o, e = c.exec_command(rf'type "{TARGET}\runtime\settings.json"', timeout=5)
time.sleep(1)
s = json.loads(o.read().decode("utf-8", errors="ignore"))
print("Path:", s.get("vision", {}).get("model_path"))

# Restart HMI
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

# Check stdout
i, o, e = c.exec_command(rf'type "{TARGET}\stdout.log"', timeout=5)
lines = o.read().decode("gbk", errors="ignore").strip().split("\n")
print("\n=== HMI stdout ===")
for line in lines:
    print(line)

c.close()
