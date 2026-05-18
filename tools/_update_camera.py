"""Update camera IP on remote machine and restart HMI"""
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
print("SSH connected")

# 1. Kill HMI
print("Kill HMI...")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(3)

# 2. Write runtime settings via remote Python script
write_script = r'''
import json
with open(r"C:\Users\A\expansion_valve_hmi\runtime\settings.json", "w", encoding="utf-8") as f:
    json.dump({"vision": {"camera_ip": "192.168.0.101"}}, f, ensure_ascii=False, indent=2)
print("OK")
'''

sftp = c.open_sftp()
with sftp.file(rf"{TARGET}\_write_cfg.py", "w") as f:
    f.write(write_script)
sftp.close()

i, o, e = c.exec_command(rf'python "{TARGET}\_write_cfg.py"', timeout=8)
time.sleep(1)
print("Write cfg:", o.read().decode("gbk", errors="ignore").strip())

# 3. Verify
i, o, e = c.exec_command(rf'type "{TARGET}\runtime\settings.json"', timeout=5)
time.sleep(0.5)
content = o.read().decode("utf-8", errors="ignore")
print("Settings:", content.strip()[:200])

# 4. Restart HMI
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

# 5. Show stdout
i, o, e = c.exec_command(rf'type "{TARGET}\stdout.log"', timeout=5)
lines = o.read().decode("gbk", errors="ignore").strip().split("\n")
print("\n=== HMI stdout ===")
for line in lines:
    print(line)

c.close()
