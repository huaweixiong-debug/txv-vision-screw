"""Check camera-related stuff on target PC"""
import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('100.79.19.71', username='a', password='0000', timeout=10)

# Check MVS SDK files
for cmd in [
    r'dir /s /b C:\MVS 2>nul',
    r'dir /s /b "C:\Program Files\MVS" 2>nul',
    r'dir /s /b "C:\Program Files (x86)\MVS" 2>nul',
    r'dir /s /b C:\Users\A\*MVS* 2>nul',
    r'dir /s /b C:\Users\A\Downloads\*MVS* 2>nul',
]:
    i, o, e = c.exec_command(cmd, timeout=10)
    out = o.read().decode('gbk', errors='ignore').strip()
    if out:
        print(f'MVS: {out[:300]}')
        break
else:
    print('MVS SDK: NOT FOUND')

# Check installed Python packages
i, o, e = c.exec_command('python -m pip list 2>nul', timeout=15)
pkgs = o.read().decode('gbk', errors='ignore')
for pkg in ['opencv', 'numpy', 'ultralytics', 'PIL', 'Pillow']:
    if pkg.lower() in pkgs.lower():
        for line in pkgs.split('\n'):
            if pkg.lower() in line.lower():
                print(f'Package: {line.strip()}')
                break
    else:
        print(f'Package: {pkg} NOT FOUND')

# Check if GIGE filter driver exists
i, o, e = c.exec_command('sc query GigeFilter 2>nul & sc query MVGigeFilter 2>nul', timeout=5)
out = o.read().decode('gbk', errors='ignore').strip()
print(f'GigeFilter service: {out[:200] if out else "NOT FOUND"}')

# Check camera reachability
i, o, e = c.exec_command('ping -n 1 -w 200 192.168.0.111', timeout=5)
out = o.read().decode('gbk', errors='ignore')
print(f'Camera ping: {"OK" if "TTL" in out else "FAIL"}')

# Check if there's an open TCP port on camera (GigE Vision uses port 3956)
i, o, e = c.exec_command(r'python -c "import socket; s=socket.socket(); s.settimeout(2); r=s.connect_ex((\"192.168.0.111\",3956)); print(\"port 3956:\",\"OPEN\" if r==0 else \"CLOSED\"); s.close()"', timeout=5)
print('Camera GVCP:', o.read().decode('gbk', errors='ignore').strip())

c.close()
