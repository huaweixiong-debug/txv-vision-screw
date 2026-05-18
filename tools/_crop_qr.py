"""Crop QR region from image using YOLO, then decode/OCR"""
import paramiko, time

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)

# Kill HMI
c.exec_command("taskkill /F /IM python.exe 2>nul", timeout=5)
time.sleep(3)

# Save QR crop
script = r'''
import cv2, os
os.environ["PATH"] = r"C:\Python314\Lib\site-packages\pyzbar;" + os.environ["PATH"]

img = cv2.imread(r"C:\Users\A\expansion_valve_hmi\data\images\NEW-004\2026-05-17\20260517_161205_NEW-004_NOQR.jpg")

from ultralytics import YOLO
model = YOLO("D:/ultralytics-main/best.pt")
results = model.predict(img, conf=0.3, iou=0.3, verbose=False)

for r in results:
    if r.boxes is not None:
        for i, box in enumerate(r.boxes):
            cls_id = int(box.cls[0])
            name = model.names[cls_id]
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(img.shape[1], x2), min(img.shape[0], y2)
            crop = img[y1:y2, x1:x2]
            fn = rf"C:\Users\A\expansion_valve_hmi\_crop_{name}_{i}.png"
            cv2.imwrite(fn, crop)
            print(f"Saved: {name} ({x1},{y1})-({x2},{y2}) -> {fn}")
'''

sftp = c.open_sftp()
with sftp.file(r"C:\Users\A\expansion_valve_hmi\_crop_qr.py", "w") as f:
    f.write(script)
sftp.close()

i, o, e = c.exec_command(r'python C:\Users\A\expansion_valve_hmi\_crop_qr.py', timeout=40)
time.sleep(12)
print(o.read().decode("gbk", errors="ignore"))
err = e.read().decode("gbk", errors="ignore")
if err:
    print("STDERR:", err[:500])

c.close()
