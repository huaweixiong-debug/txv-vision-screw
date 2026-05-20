import paramiko, sys

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("100.79.19.71", username="a", password="0000", timeout=10)

# Check C: drive workflow.py for key patterns
script = r"""import os
path = r"C:\Users\A\expansion_valve_hmi\app\workflow.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()
print(f"workflow.py: {len(lines)} lines")

# Check for SKIP NG (should NOT exist after revert)
for i, line in enumerate(lines, 1):
    if "SKIP NG" in line:
        print(f"  SKIP NG found at line {i}")
    if "result == \"NG\"" in line and "SKIP" in line:
        print(f"  NG skip at line {i}")

# Also check app.js
js_path = r"C:\Users\A\expansion_valve_hmi\web\app.js"
with open(js_path, "r", encoding="utf-8") as f:
    js = f.read()
print(f"\napp.js: {len(js)} bytes")

# Check for the broken pattern
import re
broken = re.findall(r'operator: \.value', js)
print(f"Broken '.value' patterns: {len(broken)}")
"""

sftp = c.open_sftp()
with sftp.file(r"C:\Users\A\expansion_valve_hmi\_check_code.py", "w") as f:
    f.write(script)
sftp.close()

i, o, e = c.exec_command(r"python C:\Users\A\expansion_valve_hmi\_check_code.py", timeout=15)
sys.stdout.buffer.write(b"--- Code check ---\n")
sys.stdout.buffer.write(o.read())
sys.stdout.buffer.write(b"\n--- stderr ---\n")
sys.stdout.buffer.write(e.read())

c.close()
