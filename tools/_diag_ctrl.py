import paramiko
HOST='100.79.19.71'; USER='a'; PASS='0000'
c=paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST,username=USER,password=PASS,timeout=10)

code='''
import urllib.request, json, time
def api(p,b=None):
    u='http://127.0.0.1:8090'+p
    d=json.dumps(b).encode() if b else None
    r=urllib.request.Request(u,data=d,method='POST',headers={'Content-Type':'application/json'} if b else {})
    return json.loads(urllib.request.urlopen(r,timeout=10).read().decode())

api('/api/connect',{'ip':'192.168.0.105','port':502,'unit_id':1})
time.sleep(0.5)

# Check all control-related registers
print('=== Control Registers ===')
addrs = [256, 264, 265, 267, 268, 456, 457, 458, 459, 460, 461, 463, 464]
r = api('/api/watch', {'addrs': addrs})
for a in addrs:
    v = r['registers'].get(str(a))
    print(f'  [{a}] = {v}')

# Test start command directly
print()
print('=== Test Start (456=1) ===')
r = api('/api/write', {'addr': 456, 'value': 1})
print('  write result:', r.get('ok'))
time.sleep(0.5)
r = api('/api/watch', {'addrs': [456, 267, 268]})
for a in [456, 267, 268]:
    print(f'  [{a}] = {r["registers"].get(str(a))}')

# Test stop
print()
print('=== Test Stop (456=0) ===')
r = api('/api/write', {'addr': 456, 'value': 0})
print('  write result:', r.get('ok'))
time.sleep(0.3)
r = api('/api/watch', {'addrs': [456, 267, 268]})
for a in [456, 267, 268]:
    print(f'  [{a}] = {r["registers"].get(str(a))}')

# Check if register 256 (mode) is correct for remote control
print()
print('=== Register 256 (mode) ===')
r = api('/api/watch', {'addrs': [256]})
v = r['registers'].get('256')
print(f'  [256] = {v}')
if v == 1:
    print('  Mode appears to be remote/network')
elif v == 0:
    print('  Mode is LOCAL - needs to be set to remote!')

# Check what start/stop via the API endpoint returns
print()
print('=== Test /api/start endpoint ===')
r = api('/api/start', {})
print('  ok:', r.get('ok'))
print('  message:', r.get('message'))
print('  resultCode:', r.get('resultCode'))

# Check if there's any error
print()
print('=== Status check ===')
r = api('/api/status')
print('  enabled:', r.get('enabled'))
print('  running:', r.get('running'))
print('  currentJob:', r.get('currentJob'))
print('  currentStep:', r.get('currentStep'))
'''

sftp=c.open_sftp()
with sftp.file(r'C:\Users\A\kilews_panel\diag_ctrl.py','w') as f: f.write(code)
sftp.close()
i,o,e=c.exec_command(r'python C:\Users\A\kilews_panel\diag_ctrl.py',timeout=30)
print(o.read().decode('gbk',errors='ignore'))
err=e.read().decode('gbk',errors='ignore')
if err: print('STDERR:',err[:500])
c.close()
