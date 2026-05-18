"""Test MVS SDK enumeration on target PC"""
import sys
sys.path.insert(0, r"C:\Program Files (x86)\MVS\Development\Samples\Python\MvImport")

import ctypes
import MvCameraControl_class as mv

print("MVS SDK imported OK")
print("MV_OK =", mv.MV_OK)
print("MV_GIGE_DEVICE =", mv.MV_GIGE_DEVICE)

# Initialize
ret = mv.MvCamera.MV_CC_Initialize()
print(f"MV_CC_Initialize: 0x{ret:X} ({'OK' if ret == mv.MV_OK else 'FAIL'})")

# Enumerate
device_list = mv.MV_CC_DEVICE_INFO_LIST()
ret = mv.MvCamera.MV_CC_EnumDevices(mv.MV_GIGE_DEVICE | mv.MV_USB_DEVICE, device_list)
print(f"MV_CC_EnumDevices: 0x{ret:X} nDeviceNum={device_list.nDeviceNum}")

if device_list.nDeviceNum == 0:
    print("NO DEVICES FOUND")
    mv.MvCamera.MV_CC_Finalize()
    sys.exit(1)

# Try copying device info with memmove
st_dev = mv.MV_CC_DEVICE_INFO()
dev_info_size = ctypes.sizeof(mv.MV_CC_DEVICE_INFO)
print(f"sizeof(MV_CC_DEVICE_INFO) = {dev_info_size}")

for i in range(device_list.nDeviceNum):
    ctypes.memmove(ctypes.byref(st_dev), device_list.pDeviceInfo[i], dev_info_size)
    print(f"\nDevice [{i}]:")
    print(f"  nTLayerType = {st_dev.nTLayerType}")
    print(f"  nMajorVer = {st_dev.nMajorVer}")

    if st_dev.nTLayerType == mv.MV_GIGE_DEVICE:
        gigE_info = st_dev.SpecialInfo.stGigEInfo
        nip = gigE_info.nCurrentIp
        ip_str = ".".join([
            str((nip >> 24) & 0xFF),
            str((nip >> 16) & 0xFF),
            str((nip >> 8) & 0xFF),
            str(nip & 0xFF),
        ])
        print(f"  IP = {ip_str}")
        print(f"  nCurrentIp raw = {nip} (0x{nip:08X})")

        # Also try getting as array elements
        try:
            # Some SDK versions expose IP as array
            print(f"  chManufacturerName = {gigE_info.chManufacturerName}")
        except Exception as e:
            print(f"  (chManufacturerName not accessible: {e})")

mv.MvCamera.MV_CC_Finalize()
print("\nDone")
