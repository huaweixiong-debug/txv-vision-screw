import paramiko, sys

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("100.79.19.71", username="a", password="0000", timeout=10)

# Upload check script
script = r"""import urllib.request, json

# Health check
try:
    resp = urllib.request.urlopen("http://192.168.0.99:8010/api/health", timeout=5)
    print("HEALTH:", resp.read().decode())
except Exception as e:
    print("HEALTH ERROR:", e)

# Check settings
try:
    resp = urllib.request.urlopen("http://192.168.0.99:8010/api/settings", timeout=5)
    s = json.loads(resp.read().decode())
    d = s.get("data", {})
    print(f"image_root={d.get('image_root')}")
    print(f"dataset_root={d.get('dataset_root')}")
    print(f"database_path={d.get('database_path')}")
    print(f"export_root={d.get('export_root')}")
except Exception as e:
    print("SETTINGS ERROR:", e)
"""

sftp = c.open_sftp()
with sftp.file(r"D:\expansion_valve_hmi\_check.py", "w") as f:
    f.write(script)
sftp.close()

i, o, e = c.exec_command(r"python D:\expansion_valve_hmi\_check.py", timeout=15)
sys.stdout.buffer.write(b"--- Verify D: deployment ---\n")
sys.stdout.buffer.write(o.read())
sys.stdout.buffer.write(b"\n--- stderr ---\n")
sys.stdout.buffer.write(e.read())

# Check DB migration
i2, o2, e2 = c.exec_command(r"dir D:\expansion_valve_hmi\runtime\production.db", timeout=5)
sys.stdout.buffer.write(b"\n--- DB file ---\n")
sys.stdout.buffer.write(o2.read())

c.close()
