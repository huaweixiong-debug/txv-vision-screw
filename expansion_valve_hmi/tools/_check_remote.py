"""Check remote HMI status"""
import paramiko, time

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("100.79.19.71", username="a", password="0000", timeout=10)

test = """
import urllib.request, json
try:
    resp = urllib.request.urlopen("http://127.0.0.1:8010/api/status", timeout=10)
    data = json.loads(resp.read().decode())
    s = data.get("state", "?")
    sl = data.get("state_label", "?")
    plc = data.get("plc", {})
    auto = data.get("automation", {})
    print(f"State: {s} ({sl})")
    print(f"PLC connected: {auto.get('plc_connected', '?')}")
    print(f"Automation active: {auto.get('active', '?')}")
    print(f"Operator: {data.get('operator', '?')}")
    kilews = data.get("kilews", {})
    print(f"Kilews connected: {kilews.get('connected', '?')}")
    resp2 = urllib.request.urlopen("http://127.0.0.1:8010/api/settings", timeout=5)
    settings = json.loads(resp2.read().decode())
    sc = settings.get("scanner", {})
    print(f"Scanner mode: {sc.get('mode', '?')}, port: {sc.get('com_port', '?')}")
    pc = settings.get("plc", {})
    print(f"PLC settings: enabled={pc.get('enabled')}, ip={pc.get('ip')}")
except Exception as e:
    print(f"Error: {e}")
"""

sftp = c.open_sftp()
with sftp.file(r"C:\Users\A\expansion_valve_hmi\check_status.py", "w") as f:
    f.write(test)
sftp.close()

i, o, e = c.exec_command(r'python C:\Users\A\expansion_valve_hmi\check_status.py', timeout=15)
print(o.read().decode("gbk", errors="ignore"))
err = e.read().decode("gbk", errors="ignore").strip()
if err:
    print("STDERR:", err[:500])
c.close()
