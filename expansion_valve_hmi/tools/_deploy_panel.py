"""Deploy, restart, and verify Kilews test panel on target PC"""
import paramiko, json, time

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)
print("SSH connected")

# Upload latest panel
sftp = c.open_sftp()
sftp.put(
    r"S:\expansion_valve_hmi\tools\kilews_test_panel.py",
    r"C:\Users\A\kilews_panel\panel.py"
)
sftp.close()
print("Panel synced")

# Kill old panel process
print("Restarting panel...")
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(1)

# Start new panel
launcher = (
    'import subprocess, sys, os\r\n'
    'os.chdir(r"C:\\Users\\A\\kilews_panel")\r\n'
    'flags = 0x01000000 | 0x00000008\r\n'
    'with open("stdout.log", "w") as out, open("stderr.log", "w") as err:\r\n'
    '    p = subprocess.Popen([sys.executable, "panel.py"], stdout=out, stderr=err,\r\n'
    '        stdin=subprocess.DEVNULL, creationflags=flags)\r\n'
    '    print("PID=" + str(p.pid))\r\n'
)
sftp2 = c.open_sftp()
with sftp2.file(r"C:\Users\A\kilews_panel\launch.py", "w") as f:
    f.write(launcher)
sftp2.close()

i, o, e = c.exec_command(r'python "C:\Users\A\kilews_panel\launch.py"', timeout=10)
print("Launch:", o.read().decode("gbk", errors="ignore").strip())
time.sleep(3)

# Verify
i, o, e = c.exec_command("netstat -ano | findstr 8090", timeout=5)
port = o.read().decode("gbk", errors="ignore")
if not port.strip():
    print("ERROR: Panel failed to start")
    i, o, e = c.exec_command("type C:\\Users\\A\\kilews_panel\\stderr.log 2>&1", timeout=5)
    print(o.read().decode("gbk", errors="ignore")[:500])
    c.close()
    exit(1)

print("Panel started on port 8090")

# Test APIs
api_test = r"""
import urllib.request, json, time

def api(method, path, body=None):
    url = 'http://127.0.0.1:8090' + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={'Content-Type': 'application/json'} if body else {})
    resp = urllib.request.urlopen(req, timeout=5)
    return json.loads(resp.read().decode())

print('=== API Tests (KL-NTCS-M7) ===')
print()

# Connect
r = api('POST', '/api/connect', {'ip': '192.168.0.105', 'port': 502, 'unit_id': 1})
print('[Connect] ok=%s' % r['ok'])

time.sleep(1)

# Status
s = api('GET', '/api/status')
print('[Status]')
print('  connected:', s['connected'])
print('  enabled:', s['enabled'], '| running:', s['running'])
print('  job:', s['currentJob'], '| seq:', s['currentSeq'], '| step:', s['currentStep'])
print('  toolMode:', s['toolMode'])
print('  torqueRaw:', s['torqueRaw'], '| angleRaw:', s['angleRaw'])
print('  resultCode:', s['resultCode'])
print('  serialNo:', s['serialNo'])
print('  barcode:', s.get('barcode', '')[:50])
print('  lastUpdate:', s['lastUpdate'])
print()

# Check register blocks (M7 format)
for key in ['regStatus', 'regResult', 'regRtc']:
    block = s.get(key, {})
    if block:
        print('[%s] %d registers' % (key, len(block)))
        for addr in sorted(block.keys(), key=int)[:8]:
            print('  [%s] = %s' % (addr, block[addr]))
        print()

# Raw register read test
print('[Registers] Direct read test:')
r = api('POST', '/api/registers', {'start': 4305, 'count': 10})
if r.get('ok'):
    for i, v in enumerate(r['values']):
        print('  [%d] = %d' % (r['start'] + i, v))

print()
print('=== Tests complete ===')
"""
sftp3 = c.open_sftp()
with sftp3.file(r"C:\Users\A\kilews_panel\api_test.py", "w") as f:
    f.write(api_test)
sftp3.close()

print("\nRunning API tests...")
print("=" * 60)
i, o, e = c.exec_command(r'python "C:\Users\A\kilews_panel\api_test.py"', timeout=30)
print(o.read().decode("gbk", errors="ignore"))
err = e.read().decode("gbk", errors="ignore")
if err:
    print("STDERR:", err[:300])
print("=" * 60)

print("\nPanel URLs:")
print("  Local:  http://127.0.0.1:8090")
print("  LAN:    http://192.168.0.99:8090")

c.close()
