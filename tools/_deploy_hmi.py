"""Deploy the main HMI to target PC and start it"""
import paramiko, time, os, json

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"
TARGET_DIR = r"C:\Users\A\expansion_valve_hmi"
SOURCE_DIR = r"S:\expansion_valve_hmi"

# Files to deploy (source relative path -> target relative path)
FILES = [
    "run.py",
    "requirements.txt",
    "app/__init__.py",
    "app/config.py",
    "app/main.py",
    "app/storage.py",
    "app/vision.py",
    "app/workflow.py",
    "app/hardware/__init__.py",
    "app/hardware/camera.py",
    "app/hardware/coverage_detector.py",
    "app/hardware/kilews.py",
    "app/hardware/plc.py",
    "app/hardware/scanner.py",
    "app/hardware/snap7_plc.py",
    "app/hardware/stability_detector.py",
    "web/index.html",
    "web/styles.css",
    "web/app.js",
    "config/default_settings.json",
]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)
print("SSH connected")

# Kill existing python
print("Killing existing python...")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(1)

# Create directories on target
print("Creating directories...")
for d in ["app", "app/hardware", "web", "config"]:
    c.exec_command(f'mkdir "{TARGET_DIR}\\{d}" 2>nul', timeout=5)

# Upload files
sftp = c.open_sftp()
for f in FILES:
    src = os.path.join(SOURCE_DIR, f)
    dst = f"{TARGET_DIR}\\{f.replace('/', '\\')}"
    try:
        sftp.put(src, dst)
        print(f"  OK: {f}")
    except Exception as e:
        print(f"  FAIL: {f} - {e}")
sftp.close()
print("All files uploaded")

# Start HMI server
print("\nStarting HMI server...")
launcher = (
    'import subprocess, sys, os\r\n'
    f'os.chdir(r"{TARGET_DIR}")\r\n'
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

i, o, e = c.exec_command(r'python "C:\Users\A\expansion_valve_hmi\launch.py"', timeout=10)
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
    print("NOT LISTENING - checking stderr.log...")
    i, o, e = c.exec_command(f"type {TARGET_DIR}\\stderr.log 2>&1", timeout=5)
    err = o.read().decode("gbk", errors="ignore")
    print(err[:2000] if err.strip() else "(empty)")

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
with sftp3.file(r"C:\Users\A\expansion_valve_hmi\test_api.py", "w") as f:
    f.write(test_code)
sftp3.close()

i, o, e = c.exec_command(r'python "C:\Users\A\expansion_valve_hmi\test_api.py"', timeout=10)
print(o.read().decode("gbk", errors="ignore"))
err_out = e.read().decode("gbk", errors="ignore").strip()
if err_out:
    print("STDERR:", err_out[:500])

print("\nDone! HMI should be at:")
print("  http://192.168.0.99:8010")
print("  http://100.79.19.71:8010")
c.close()
