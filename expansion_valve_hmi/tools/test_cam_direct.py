"""Direct test of camera.py on target PC"""
import sys
sys.path.insert(0, r"C:\Users\A\expansion_valve_hmi")
import time
from app.hardware.camera import MvsCameraDevice, MockCameraDevice

print("Import OK")
cam = MvsCameraDevice(
    "192.168.0.111",
    r"C:\Program Files (x86)\MVS\Development\Samples\Python\MvImport"
)
ok = cam.connect()
print("connect() =", ok)
if ok:
    time.sleep(1)
    jpeg = cam.get_latest_jpeg()
    print("JPEG size:", len(jpeg) if jpeg else "None")
cam.disconnect()
print("Done")
