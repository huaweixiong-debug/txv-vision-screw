"""Run inference on a specific image on remote"""
import paramiko, time

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)

script = r'''
from ultralytics import YOLO
model = YOLO("D:/ultralytics-main/best.pt")
print("Classes:", model.names)
img = r"C:\Users\A\expansion_valve_hmi\data\images\NEW-004\2026-05-17\20260517_161205_NEW-004_NOQR.jpg"
results = model.predict(source=img, conf=0.15, iou=0.3, verbose=True, save=True)
for r in results:
    if r.boxes is not None:
        for box in r.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            print(f"DETECTED: {model.names[cls_id]} conf={conf:.4f}")
    else:
        print("No detections")
'''

sftp = c.open_sftp()
with sftp.file(r"C:\Users\A\expansion_valve_hmi\_infer_qr.py", "w") as f:
    f.write(script)
sftp.close()

i, o, e = c.exec_command(r'python C:\Users\A\expansion_valve_hmi\_infer_qr.py', timeout=30)
time.sleep(8)
print(o.read().decode("gbk", errors="ignore"))
err = e.read().decode("gbk", errors="ignore")
if err:
    print("STDERR:", err[:500])

c.close()
