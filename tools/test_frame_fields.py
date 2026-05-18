"""Check MV_FRAME_OUT_INFO_EX fields"""
import sys
sys.path.insert(0, r"C:\Users\A\expansion_valve_hmi")
sys.path.insert(0, r"C:\Program Files (x86)\MVS\Development\Samples\Python\MvImport")
import ctypes
import MvCameraControl_class as mv

# Show MV_FRAME_OUT_INFO_EX structure
print("MV_FRAME_OUT_INFO_EX fields:")
frame_info = mv.MV_FRAME_OUT_INFO_EX()
for name, _ in frame_info._fields_:
    print(f"  {name}")

# Connect to camera briefly
from app.hardware.camera import MvsCameraDevice
cam = MvsCameraDevice(
    "192.168.0.111",
    r"C:\Program Files (x86)\MVS\Development\Samples\Python\MvImport"
)
cam.connect()
import time
time.sleep(0.5)

# Check what pixel format the camera is actually using
mv_cam = cam._cam
mv_mod = cam._MvCamera

# Get current pixel format
pf = mv.MVCC_ENUMVALUE()
ret = mv_cam.MV_CC_GetEnumValue("PixelFormat", pf)
if ret == mv.MV_OK:
    print(f"\nCurrent PixelFormat: {pf.nCurValue}")

# Try getting a frame and inspecting the frame_info
fi = mv.MV_FRAME_OUT_INFO_EX()
ret = mv_cam.MV_CC_GetImageBuffer(fi, 1000)
if ret == mv.MV_OK:
    print(f"\nGot frame: len={fi.nFrameLen}, w={fi.nWidth}, h={fi.nHeight}, fmt={fi.enPixelType}")
    # Try different field names for buffer pointer
    for attr in ['pBufAddr', 'pBuf', 'pImageBuf', 'pData', 'pstFrameInfo']:
        try:
            val = getattr(fi, attr, 'N/A')
            print(f"  fi.{attr} = {val}")
        except Exception as e:
            print(f"  fi.{attr} -> ERROR: {e}")
    mv_cam.MV_CC_FreeImageBuffer(fi)
else:
    print(f"\nGetImageBuffer failed: 0x{ret:X}")

cam.disconnect()
