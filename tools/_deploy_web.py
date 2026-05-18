"""Deploy web files (CSS + HTML) to target PC and restart HMI"""
import paramiko, time, os

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"
TARGET_DIR = r"C:\Users\A\expansion_valve_hmi"
SOURCE_DIR = r"S:\expansion_valve_hmi"

FILES = ["web/styles.css", "web/index.html", "web/app.js"]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)
print("SSH connected")

# Kill existing python
print("Killing existing python...")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(1)

# Upload files
sftp = c.open_sftp()
for f in FILES:
    src = os.path.join(SOURCE_DIR, f)
    dst = TARGET_DIR + "\\" + f.replace("/", "\\")
    try:
        sftp.put(src, dst)
        print(f"  OK: {f}")
    except Exception as e:
        print(f"  FAIL: {f} - {e}")
sftp.close()
print("Web files uploaded")

# Start HMI server
print("\nStarting HMI server...")
launcher = (
    'import subprocess, sys, os\r\n'
    'os.chdir(r"' + TARGET_DIR + '")\r\n'
    'flags = 0x01000000 | 0x00000008\r\n'
    'with open("stdout.log", "w") as out, open("stderr.log", "w") as err:\r\n'
    '    p = subprocess.Popen([sys.executable, "run.py", "--host", "0.0.0.0", "--port", "8010"],\r\n'
    '        stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=flags)\r\n'
    '    print("PID=" + str(p.pid))\r\n'
)
sftp2 = c.open_sftp()
launch_path = TARGET_DIR + "\\launch.py"
with sftp2.file(launch_path, "w") as f:
    f.write(launcher)
sftp2.close()

i, o, e = c.exec_command('python "' + TARGET_DIR + '\\launch.py"', timeout=10)
print("Launch:", o.read().decode("gbk", errors="ignore").strip())
err_out = e.read().decode("gbk", errors="ignore").strip()
if err_out:
    print("Launch stderr:", err_out[:500])
time.sleep(4)

# Check port
print("\n=== Port 8010 ===")
i, o, e = c.exec_command("netstat -ano | findstr 8010", timeout=5)
port_out = o.read().decode("gbk", errors="ignore")
if port_out.strip():
    print(port_out.strip())
else:
    print("NOT LISTENING")

# API test
print("\n=== API Test ===")
test_code = (
    "import urllib.request, json\n"
    "try:\n"
    "    resp = urllib.request.urlopen('http://127.0.0.1:8010/api/health', timeout=5)\n"
    "    data = json.loads(resp.read().decode())\n"
    "    print('Health:', data)\n"
    "except Exception as e:\n"
    "    print('Health FAIL:', e)\n"
    "\n"
    "try:\n"
    "    resp = urllib.request.urlopen('http://127.0.0.1:8010/', timeout=5)\n"
    "    html = resp.read().decode()\n"
    "    print('HTML size:', len(html), '| has title:', '扩张阀' in html)\n"
    "except Exception as e:\n"
    "    print('HTML FAIL:', e)\n"
)
sftp3 = c.open_sftp()
test_path = TARGET_DIR + "\\test_api.py"
with sftp3.file(test_path, "w") as f:
    f.write(test_code)
sftp3.close()

i, o, e = c.exec_command('python "' + TARGET_DIR + '\\test_api.py"', timeout=10)
print(o.read().decode("gbk", errors="ignore"))
err_out = e.read().decode("gbk", errors="ignore").strip()
if err_out:
    print("STDERR:", err_out[:500])

print("\nDone! HMI at:")
print("  http://192.168.0.99:8010")
print("  http://100.79.19.71:8010")
c.close()
