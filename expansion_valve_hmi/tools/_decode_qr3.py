"""Decode QR with pyzbar - fixed"""
import paramiko, time

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)

script = r'''
import os
os.environ["PATH"] = r"C:\Python314\Lib\site-packages\pyzbar;" + os.environ.get("PATH", "")

import cv2
from pyzbar.pyzbar import decode

img_path = r"C:\Users\A\expansion_valve_hmi\data\images\NEW-004\2026-05-17\20260517_161205_NEW-004_NOQR.jpg"
img = cv2.imread(img_path)
print(f"Image: {img.shape}")

# Full image decode
codes = decode(img)
for c in codes:
    print(f"Full: type={c.type} data={c.data.decode('utf-8')}")
if not codes:
    print("Full image: no QR found")

# Crop from YOLO detection
from ultralytics import YOLO
model = YOLO("D:/ultralytics-main/best.pt")
results = model.predict(img, conf=0.3, iou=0.3, verbose=False)
for r in results:
    if r.boxes is not None:
        for box in r.boxes:
            cls_id = int(box.cls[0])
            if model.names[cls_id] == "QR":
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                x1, y1 = max(0, x1-10), max(0, y1-10)
                x2, y2 = min(img.shape[1], x2+10), min(img.shape[0], y2+10)
                crop = img[y1:y2, x1:x2]
                print(f"QR crop: {x1},{y1} - {x2},{y2}")
                codes2 = decode(crop)
                for c2 in codes2:
                    print(f"  Decoded: {c2.data.decode('utf-8')}")
                if not codes2:
                    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    codes3 = decode(gray)
                    for c3 in codes3:
                        print(f"  Gray: {c3.data.decode('utf-8')}")
                    if not codes3:
                        print("  Cannot decode QR")
'''

sftp = c.open_sftp()
with sftp.file(r"C:\Users\A\expansion_valve_hmi\_decode_qr3.py", "w") as f:
    f.write(script)
sftp.close()

i, o, e = c.exec_command(r'python C:\Users\A\expansion_valve_hmi\_decode_qr3.py', timeout=40)
time.sleep(12)
out = o.read().decode("gbk", errors="ignore")
print(out)
err = e.read().decode("gbk", errors="ignore")
if err:
    print("STDERR:", err[:500])

c.close()
