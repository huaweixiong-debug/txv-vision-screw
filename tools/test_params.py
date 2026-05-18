"""Test parameter writing via JOB 201 switch mechanism on ntcs_7"""
import urllib.request, json, time

def api(path, body=None):
    url = "http://127.0.0.1:8090" + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method="POST",
        headers={"Content-Type": "application/json"} if body else {})
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read().decode())

def read_multi(addrs):
    """Read multiple single registers via /api/watch"""
    r = api("/api/watch", {"addrs": addrs})
    return r.get("registers", {})

def write_reg(addr, val):
    r = api("/api/write", {"addr": addr, "value": val})
    return r.get("ok", False)

print("=== Parameter Discovery Test (ntcs_7) ===\n")

# 0. Connect to MODBUS device
print("--- 0. Connect to 192.168.0.105 ---")
r = api("/api/connect", {"ip": "192.168.0.105", "port": 502, "unit_id": 1})
print("  Connected: %s" % r.get("ok"))
if not r.get("ok"):
    print("  FAILED to connect, aborting")
    exit(1)
time.sleep(0.5)

# 1. Baseline: read control area and parameter area
print("--- 1. Baseline registers ---")
control_addrs = [456, 457, 459, 461, 463, 464, 769]
param_addrs = [890, 891, 892, 893, 894, 895]
result_addrs = [4155, 4156, 4160, 4161, 4162, 4164]

for label, addrs in [("Control", control_addrs), ("Param(890+)", param_addrs), ("Result", result_addrs)]:
    regs = read_multi(addrs)
    print("  %s:" % label)
    for a in addrs:
        v = regs.get(str(a))
        print("    [%d] = %s" % (a, v if v is not None else "N/A"))

# 2. Try JOB 201 switch via 769
print("\n--- 2. Switch to JOB 201 (write 201 to 769) ---")
ok = write_reg(769, 201)
print("  write 769=201: %s" % ("OK" if ok else "FAIL"))
time.sleep(0.1)

# 3. Read parameter area after switch
print("\n--- 3. Parameter area after JOB switch ---")
regs = read_multi(param_addrs + [769])
for a in param_addrs + [769]:
    v = regs.get(str(a))
    print("  [%d] = %s" % (a, v if v is not None else "N/A"))

# 4. Try writing target torque 0.700 Nm (=700) to 890-891
print("\n--- 4. Write target torque 0.700 Nm to 890-891 ---")
torque_val = 700  # Nm x 1000
torque_hi = (torque_val >> 16) & 0xFFFF
torque_lo = torque_val & 0xFFFF
print("  32-bit value=%d, hi=%d, lo=%d" % (torque_val, torque_hi, torque_lo))
r = api("/api/write", {"addr": 890, "value": torque_hi})
print("  write [890]=%d: %s" % (torque_hi, "OK" if r.get("ok") else "FAIL"))
time.sleep(0.03)
r = api("/api/write", {"addr": 891, "value": torque_lo})
print("  write [891]=%d: %s" % (torque_lo, "OK" if r.get("ok") else "FAIL"))

# 5. Write target angle 0 to 892-893
print("\n--- 5. Write target angle 0 to 892-893 ---")
r = api("/api/write", {"addr": 892, "value": 0})
print("  write [892]=0: %s" % ("OK" if r.get("ok") else "FAIL"))
r = api("/api/write", {"addr": 893, "value": 0})
print("  write [893]=0: %s" % ("OK" if r.get("ok") else "FAIL"))

# 6. Re-apply JOB 201
print("\n--- 6. Re-apply JOB 201 ---")
ok = write_reg(769, 201)
print("  write 769=201: %s" % ("OK" if ok else "FAIL"))
time.sleep(0.1)

# 7. Verify parameter area
print("\n--- 7. Verify parameter area ---")
regs = read_multi(param_addrs + [769])
for a in param_addrs + [769]:
    v = regs.get(str(a))
    print("  [%d] = %s" % (a, v if v is not None else "N/A"))

# 8. Scan wider area 850-950 for any non-zero
print("\n--- 8. Scan 850-950 ---")
r = api("/api/scan", {"start": 850, "end": 950})
nz = r.get("nonZero", 0)
print("  Non-zero registers: %d" % nz)
if nz > 0:
    regs = r.get("registers", {})
    for k in sorted(regs.keys(), key=int):
        print("  [%s] = %s (0x%04X)" % (k, regs[k], regs[k]))

# 9. Also scan 1000-1200 in case params are there
print("\n--- 9. Scan 1000-1200 ---")
r = api("/api/scan", {"start": 1000, "end": 1200})
nz = r.get("nonZero", 0)
print("  Non-zero registers: %d" % nz)
if nz > 0:
    regs = r.get("registers", {})
    for k in sorted(regs.keys(), key=int):
        print("  [%s] = %s (0x%04X)" % (k, regs[k], regs[k]))

print("\n=== Test complete ===")
