"""Deploy all files to remote and restart HMI"""
import paramiko, time, os

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"
TARGET = r"C:\Users\A\expansion_valve_hmi"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)

c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(3)

SRC = r"S:\expansion_valve_hmi"
files = [
    "app/main.py", "app/workflow.py", "app/vision.py", "app/config.py", "app/storage.py",
    "app/hardware/camera.py", "app/hardware/plc.py", "app/hardware/snap7_plc.py",
    "app/hardware/kilews.py", "app/hardware/scanner.py",
    "app/hardware/stability_detector.py", "app/hardware/coverage_detector.py",
    "app/hardware/qr_decoder.py",
    "web/index.html", "web/app.js", "web/styles.css",
    "web/scanner-test.html", "web/kilews-test.html",
    "config/default_settings.json", "requirements.txt",
]

sftp = c.open_sftp()
for f in files:
    src_path = os.path.join(SRC, f)
    dst_path = TARGET + "\\" + f.replace("/", "\\")
    sftp.put(src_path, dst_path)
    print("  " + f)
sftp.close()

launcher = (
    'import subprocess, sys, os\r\n'
    'os.chdir(r"' + TARGET + '")\r\n'
    'flags = 0x01000000 | 0x00000008\r\n'
    'with open("stdout.log", "w") as out, open("stderr.log", "w") as err:\r\n'
    '    p = subprocess.Popen([sys.executable, "-u", "run.py", "--host", "0.0.0.0", "--port", "8010"],\r\n'
    '        stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=flags)\r\n'
    '    print("PID=" + str(p.pid))\r\n'
)
sftp = c.open_sftp()
with sftp.file(TARGET + "\\launch.py", "w") as f:
    f.write(launcher)
sftp.close()
i, o, e = c.exec_command('python "' + TARGET + '\\launch.py"', timeout=10)
time.sleep(10)
print("HMI restarted")
c.close()
