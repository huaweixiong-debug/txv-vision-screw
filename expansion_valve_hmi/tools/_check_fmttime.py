import paramiko, sys

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("100.79.19.71", username="a", password="0000", timeout=10)

script = """with open(r"C:\\Users\\A\\expansion_valve_hmi\\web\\app.js", "r", encoding="utf-8") as f:
    lines = f.readlines()
for i, line in enumerate(lines, 1):
    if "function fmtTime" in line:
        for j in range(i, i+6):
            if j <= len(lines):
                print(f"{j}: {lines[j-1]}", end="")
        break
"""

sftp = c.open_sftp()
with sftp.file(r"C:\Users\A\expansion_valve_hmi\_check_js.py", "w") as f:
    f.write(script)
sftp.close()

i, o, e = c.exec_command(r"python C:\Users\A\expansion_valve_hmi\_check_js.py", timeout=10)
sys.stdout.buffer.write(b"--- Remote fmtTime ---\n")
sys.stdout.buffer.write(o.read())
sys.stdout.buffer.write(b"\n--- stderr ---\n")
sys.stdout.buffer.write(e.read())

c.close()
