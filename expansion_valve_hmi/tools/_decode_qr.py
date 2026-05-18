"""Decode QR code from detected region and whole image"""
import paramiko, time

HOST = "100.79.19.71"
USER = "a"
PASS = "0000"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)

script = r'''
import cv2

img_path = r"C:\Users\A\expansion_valve_hmi\data\images\NEW-004\2026-05-17\20260517_161205_NEW-004_NOQR.jpg"
img = cv2.imread(img_path)
print(f"Image: {img.shape}")

# Method 1: OpenCV QRCodeDetector
detector = cv2.QRCodeDetector()
data, points, _ = detector.detectAndDecode(img)
if data:
    print(f"QR Code (full image): {data}")
else:
    print("QR Code (full image): NOT FOUND")

# Method 2: Try on YOLO-detected QR region
# QR was detected at ~93% confidence — crop the middle area where QR typically is
from ultralytics import YOLO
model = YOLO("D:/ultralytics-main/best.pt")
results = model.predict(img, conf=0.3, iou=0.3, verbose=False)
for r in results:
    if r.boxes is not None:
        for box in r.boxes:
            cls_id = int(box.cls[0])
            if model.names[cls_id] == "QR":
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                x1, y1 = max(0, x1-5), max(0, y1-5)
                x2, y2 = min(img.shape[1], x2+5), min(img.shape[0], y2+5)
                crop = img[y1:y2, x1:x2]
                print(f"QR region: {x1},{y1} - {x2},{y2} size={crop.shape}")
                data2, _, _ = detector.detectAndDecode(crop)
                if data2:
                    print(f"QR Code (cropped): {data2}")
                else:
                    print("QR Code (cropped): NOT FOUND — trying enhanced...")
                    # Try grayscale + threshold
                    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                    data3, _, _ = detector.detectAndDecode(thresh)
                    if data3:
                        print(f"QR Code (enhanced): {data3}")
                    else:
                        print("QR Code (enhanced): STILL NOT FOUND")
'''

sftp = c.open_sftp()
with sftp.file(r"C:\Users\A\expansion_valve_hmi\_decode_qr.py", "w") as f:
    f.write(script)
sftp.close()

i, o, e = c.exec_command(r'python C:\Users\A\expansion_valve_hmi\_decode_qr.py', timeout=30)
time.sleep(10)
print(o.read().decode("gbk", errors="ignore"))
err = e.read().decode("gbk", errors="ignore")
if err:
    print("STDERR:", err[:500])

c.close()
