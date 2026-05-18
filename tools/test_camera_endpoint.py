import urllib.request

try:
    resp = urllib.request.urlopen("http://127.0.0.1:8010/api/vision/latest-frame", timeout=5)
    print("Status:", resp.status)
    ct = resp.headers.get("Content-Type", "?")
    print("Content-Type:", ct)
    data = resp.read()
    print("Size:", len(data))
    print("JPEG magic:", data[:4].hex())
except Exception as e:
    print("ERROR:", e)
