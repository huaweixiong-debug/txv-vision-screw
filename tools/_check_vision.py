"""Quick camera/vision check on remote"""
import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("100.79.19.71", username="a", password="0000", timeout=10)

test = """
import urllib.request, json
try:
    resp = urllib.request.urlopen("http://127.0.0.1:8010/api/status", timeout=10)
    data = json.loads(resp.read().decode())
    vision = data.get("vision", {})
    print(f"Vision: {vision}")
    plc = data.get("plc", {})
    m_fields = {k:v for k,v in plc.items() if k.startswith("m_")}
    print(f"PLC M-bits: {m_fields}")
    kilews = data.get("kilews", {})
    print(f"Kilews: {kilews}")
    auto = data.get("automation", {})
    print(f"Automation: {auto}")
except Exception as e:
    print(f"Error: {e}")
"""
sftp = c.open_sftp()
with sftp.file(r"C:\Users\A\expansion_valve_hmi\check_vision.py", "w") as f:
    f.write(test)
sftp.close()
i, o, e = c.exec_command(r'python C:\Users\A\expansion_valve_hmi\check_vision.py', timeout=10)
print(o.read().decode("gbk", errors="ignore"))
c.close()
