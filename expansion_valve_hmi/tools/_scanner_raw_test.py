"""Raw COM3 diagnostic — read ALL bytes, try multiple baud rates"""
import paramiko
import time

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("100.79.19.71", username="a", password="0000", timeout=10)

# Kill HMI to free COM3
print("Killing HMI...")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(2)

# Test at multiple baud rates
results = {}
for baud in [9600, 19200, 38400, 57600, 115200]:
    code = f"""
import serial, time
try:
    s = serial.Serial('COM3', {baud}, timeout=0.05)
    print(f'OPEN@{baud}')
    buf = b''
    deadline = time.time() + 5
    while time.time() < deadline:
        w = s.in_waiting
        if w:
            buf += s.read(w)
    s.close()
    if buf:
        hex_str = ' '.join(f'{{b:02X}}' for b in buf)
        print(f'DATA: {{len(buf)}} bytes: {{hex_str[:200]}}')
        print(f'ASCII: {{buf.decode("latin-1", errors="replace")[:100]}}')
    else:
        print('NO_DATA')
except Exception as e:
    print(f'ERR: {{e}}')
"""
    sftp = c.open_sftp()
    with sftp.file(rf"C:\Users\A\expansion_valve_hmi\raw_{baud}.py", "w") as f:
        f.write(code)
    sftp.close()

print(f"\n{'='*50}")
print(f"Testing baud={baud} — please scan NOW...")
i, o, e = c.exec_command(rf'python C:\Users\A\expansion_valve_hmi\raw_{baud}.py', timeout=10)
out = o.read().decode("utf-8", errors="ignore").strip()
print(out)
results[baud] = out

print(f"\n{'='*50}")
print("SUMMARY:")
for b, r in results.items():
    print(f"  {b}: {r}")

# Restart HMI
print("\nRestart HMI...")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(2)
launcher = (
    'import subprocess, sys, os\r\n'
    r'os.chdir(r"C:\Users\A\expansion_valve_hmi")' + '\r\n'
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
i, o, e = c.exec_command(r'python C:\Users\A\expansion_valve_hmi\launch.py', timeout=10)
time.sleep(6)
i, o, e = c.exec_command("netstat -ano | findstr 8010", timeout=5)
if "LISTENING" in o.read().decode("gbk", errors="ignore"):
    print("HMI restarted OK")

c.close()
