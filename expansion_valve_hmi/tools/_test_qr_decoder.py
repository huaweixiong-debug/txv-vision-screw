"""Test QR decoder on target image"""
import paramiko, time

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)

script = r'''
import sys, time
sys.path.insert(0, r"C:\Users\A\expansion_valve_hmi")

import cv2
from app.hardware.qr_decoder import decode_from_image
from ultralytics import YOLO

img_path = r"C:\Users\A\expansion_valve_hmi\data\images\NEW-004\2026-05-17\20260517_161205_NEW-004_NOQR.jpg"

model = YOLO("D:/ultralytics-main/best.pt")
img = cv2.imread(img_path)
print(f"Image: {img.shape}")

t0 = time.time()
result = decode_from_image(img, model, expand_ratio=0.3)
elapsed = time.time() - t0

if result:
    print(f"DECODED [{elapsed:.1f}s]: {result}")
else:
    print(f"NO DECODE [{elapsed:.1f}s]")

# Also test direct decode on just the ROI
from app.hardware.qr_decoder import decode_qr
roi = img[1114:1457, 1749:2284]
print(f"\nDirect ROI: {roi.shape}")
t1 = time.time()
r2 = decode_qr(roi, short_timeout=3.0)
print(f"Direct [{time.time()-t1:.1f}s]: {r2 or 'NO DECODE'}")
'''

sftp = c.open_sftp()
sftp.put(r"S:\expansion_valve_hmi\app\hardware\qr_decoder.py", r"C:\Users\A\expansion_valve_hmi\app\hardware\qr_decoder.py")
with sftp.file(r"C:\Users\A\expansion_valve_hmi\_test_qrd.py", "w") as f:
    f.write(script)
sftp.close()

i, o, e = c.exec_command(r'python C:\Users\A\expansion_valve_hmi\_test_qrd.py', timeout=60)
time.sleep(20)
print(o.read().decode("gbk", errors="ignore"))
err = e.read().decode("gbk", errors="ignore")
if err:
    print("STDERR:", err[:600])

c.close()
