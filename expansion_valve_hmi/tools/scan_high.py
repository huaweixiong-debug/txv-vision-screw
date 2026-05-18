"""Scan high register ranges to find parameter storage"""
import urllib.request, json

def api(path, body=None):
    url = "http://127.0.0.1:8090" + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method="POST",
        headers={"Content-Type": "application/json"} if body else {})
    resp = urllib.request.urlopen(req, timeout=120)
    return json.loads(resp.read().decode())

# Scan 10000+ for any non-zero registers
ranges = [(10000, 12000), (12000, 15000), (15000, 18000), (18000, 20000)]
for start, end in ranges:
    r = api("/api/scan", {"start": start, "end": end})
    regs = r.get("registers", {})
    if regs:
        print("=== %d-%d (%d non-zero) ===" % (start, end, len(regs)))
        for k in sorted(regs.keys(), key=int)[:30]:
            v = regs[k]
            print("  [%s] = %d (0x%04X)" % (k, v, v))
        if len(regs) > 30:
            print("  ... %d more" % (len(regs) - 30))
    else:
        print("=== %d-%d: all zeros ===" % (start, end))
