"""Minimal scanner diagnostic — just test if Python + pyserial work"""
import paramiko
import time

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("100.79.19.71", username="a", password="0000", timeout=10)

# Kill HMI first to free COM3
print("Killing HMI...")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(2)

# Test 1: Can Python import serial?
print("=== Test 1: import serial ===")
i, o, e = c.exec_command('python -c "import serial; print(serial.__version__)"', timeout=5)
print("out:", o.read().decode("gbk", errors="ignore").strip())
print("err:", e.read().decode("gbk", errors="ignore").strip()[:200])

# Test 2: List COM ports
print("\n=== Test 2: list ports ===")
i, o, e = c.exec_command(
    'python -c "import serial.tools.list_ports; [print(p.device, p.description) for p in serial.tools.list_ports.comports()]"',
    timeout=5)
print("out:", o.read().decode("gbk", errors="ignore").strip())
print("err:", e.read().decode("gbk", errors="ignore").strip()[:200])

# Test 3: Open COM3, read one line, close
print("\n=== Test 3: read COM3 (10s) ===")
code = r"""
import serial, time
s = serial.Serial('COM3', 115200, timeout=0.05)
print('OPENED')
deadline = time.time() + 10
buf = b''
while time.time() < deadline:
    w = s.in_waiting
    if w:
        buf += s.read(w)
        if b'\r' in buf or b'\n' in buf:
            line = buf.split(b'\r')[0].split(b'\n')[0]
            print('GOT:', line.decode('utf-8','ignore').strip())
            break
    time.sleep(0.05)
s.close()
if not buf:
    print('NO DATA')
print('DONE')
"""
sftp = c.open_sftp()
with sftp.file(r"C:\Users\A\expansion_valve_hmi\scan_diag.py", "w") as f:
    f.write(code)
sftp.close()
i, o, e = c.exec_command(r'python C:\Users\A\expansion_valve_hmi\scan_diag.py', timeout=15)
print("out:", o.read().decode("gbk", errors="ignore").strip())
print("err:", e.read().decode("gbk", errors="ignore").strip()[:200])

c.close()
