import paramiko, sys

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('100.79.19.71', username='a', password='0000', timeout=10)

# Check stderr.log
print('=== stderr.log ===')
i, o, e = c.exec_command(r'type C:\Users\A\expansion_valve_hmi\stderr.log', timeout=5)
out = o.read().decode('gbk', errors='ignore').strip()
print(out if out else '(empty)')

# Check stdout.log
print()
print('=== stdout.log tail ===')
i, o, e = c.exec_command(r'type C:\Users\A\expansion_valve_hmi\stdout.log', timeout=5)
content = o.read().decode('gbk', errors='ignore')
lines = [l for l in content.split('\n') if l.strip()] if content else []
for line in lines[-25:]:
    print(line)

# Test camera endpoint
print()
print('=== Camera endpoint ===')
test_code = (
    'import urllib.request\r\n'
    'try:\r\n'
    '    resp = urllib.request.urlopen("http://127.0.0.1:8010/api/vision/latest-frame", timeout=5)\r\n'
    '    data = resp.read()\r\n'
    '    print("Status:", resp.status, "Size:", len(data), "Magic:", data[:4].hex())\r\n'
    'except Exception as e:\r\n'
    '    print("ERROR:", e)\r\n'
)
sftp = c.open_sftp()
with sftp.file(r'C:\Users\A\expansion_valve_hmi\__cam_test.py', 'w') as f:
    f.write(test_code)
sftp.close()

i, o, e = c.exec_command(r'python C:\Users\A\expansion_valve_hmi\__cam_test.py', timeout=10)
print(o.read().decode('gbk', errors='ignore'))
err = e.read().decode('gbk', errors='ignore')
if err.strip():
    print('STDERR:', err[:500])

# Also check if we see camera messages in stdout
print()
print('=== Checking for [Camera] messages ===')
for line in lines:
    if 'Camera' in line or 'MVS' in line or 'GigE' in line or 'camera' in line.lower():
        print(line)

c.close()
