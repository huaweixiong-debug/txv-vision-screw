"""Check scanner and general HMI state on remote"""
import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("100.79.19.71", username="a", password="0000", timeout=10)

# Check COM ports
print("=== COM Ports ===")
i, o, e = c.exec_command("python -c \"import serial.tools.list_ports; ports=list(serial.tools.list_ports.comports()); [print(f'{p.device}: {p.description}') for p in ports]\"", timeout=5)
print(o.read().decode("gbk", errors="ignore").strip())
err = e.read().decode("gbk", errors="ignore").strip()
if err:
    print("STDERR:", err[:300])

# Check HMI stdout for scanner/PLC messages
print("\n=== HMI stdout (last 30 lines) ===")
i, o, e = c.exec_command(r'powershell -Command "Get-Content C:\Users\A\expansion_valve_hmi\stdout.log -Tail 30"', timeout=5)
print(o.read().decode("gbk", errors="ignore").strip())

# Check the vision / camera status
print("\n=== Camera / Vision ===")
test = """
import urllib.request, json
try:
    resp = urllib.request.urlopen("http://127.0.0.1:8010/api/status", timeout=10)
    data = json.loads(resp.read().decode())
    vision = data.get("vision", {})
    print(f"Vision: {vision}")
    plc = data.get("plc", {})
    # Only show M-bit fields
    m_fields = {k:v for k,v in plc.items() if k.startswith('m_')}
    print(f"PLC M-bits: {m_fields}")
except Exception as e:
    print(f"Error: {e}")
"""
sftp = c.open_sftp()
with sftp.file(r"C:\Users\A\expansion_valve_hmi\check_vision.py", "w") as f:
    f.write(test)
sftp.close()
i, o, e = c.exec_command(r'python C:\Users\A\expansion_valve_hmi\check_vision.py', timeout=10)
print(o.read().decode("gbk", errors="ignore").strip())

c.close()
