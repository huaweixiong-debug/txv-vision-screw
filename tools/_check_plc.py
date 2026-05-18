"""Check PLC connection detail on remote machine"""
import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("100.79.19.71", username="a", password="0000", timeout=10)

# 1. Check if python-snap7 is installed
print("=== python-snap7 check ===")
i, o, e = c.exec_command("python -c \"import snap7; print('snap7 OK, version:', snap7.__version__)\"", timeout=5)
print(o.read().decode("gbk", errors="ignore").strip())
err = e.read().decode("gbk", errors="ignore").strip()
if err:
    print("STDERR:", err[:300])

# 2. Check PLC API status
print("\n=== PLC /api/plc/status ===")
test = """
import urllib.request, json
try:
    resp = urllib.request.urlopen("http://127.0.0.1:8010/api/plc/status", timeout=10)
    data = json.loads(resp.read().decode())
    for k, v in data.items():
        print(f"  {k}: {v}")
except Exception as e:
    print(f"Error: {e}")
"""
sftp = c.open_sftp()
with sftp.file(r"C:\Users\A\expansion_valve_hmi\check_plc.py", "w") as f:
    f.write(test)
sftp.close()
i, o, e = c.exec_command(r'python C:\Users\A\expansion_valve_hmi\check_plc.py', timeout=10)
print(o.read().decode("gbk", errors="ignore").strip())

# 3. Try PLC connect
print("\n=== Attempt PLC connect ===")
connect_test = """
import urllib.request, json
try:
    resp = urllib.request.urlopen("http://127.0.0.1:8010/api/plc/connect", timeout=10,
        data=b"{}",
        headers={"Content-Type": "application/json"})
    data = json.loads(resp.read().decode())
    for k, v in data.items():
        print(f"  {k}: {v}")
except Exception as e:
    print(f"Error: {e}")
"""
sftp2 = c.open_sftp()
with sftp2.file(r"C:\Users\A\expansion_valve_hmi\connect_plc.py", "w") as f:
    f.write(connect_test)
sftp2.close()
i, o, e = c.exec_command(r'python C:\Users\A\expansion_valve_hmi\connect_plc.py', timeout=15)
print(o.read().decode("gbk", errors="ignore").strip())

# 4. Check PLC ping
print("\n=== Ping PLC ===")
i, o, e = c.exec_command("ping -n 2 192.168.0.10", timeout=10)
print(o.read().decode("gbk", errors="ignore").strip())

c.close()
