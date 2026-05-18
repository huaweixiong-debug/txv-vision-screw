"""Hikvision MVS SDK camera adapter — real device + mock for dev"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any


class MockCameraDevice:
    """Placeholder camera for development without hardware."""

    def __init__(self) -> None:
        self.connected = False
        self._latest_jpeg: bytes | None = None
        self._frame_lock = threading.Lock()

    def connect(self) -> bool:
        self.connected = True
        self._generate_placeholder()
        return True

    def disconnect(self) -> None:
        self.connected = False
        with self._frame_lock:
            self._latest_jpeg = None

    def get_latest_jpeg(self) -> bytes | None:
        with self._frame_lock:
            return self._latest_jpeg

    def get_latest_raw_jpeg(self) -> bytes | None:
        return self.get_latest_jpeg()  # mock: same as normal jpeg

    def set_inference(self, vision_inference: Any, interval: float = 0.5) -> None:
        pass  # mock — no-op

    def get_latest_inference(self) -> dict[str, Any] | None:
        return None

    def get_exposure(self) -> float | None:
        return getattr(self, "_mock_exposure_us", None)

    def set_exposure(self, value_us: float) -> bool:
        self._mock_exposure_us = value_us
        return True

    def _generate_placeholder(self) -> None:
        try:
            import cv2
            import numpy as np

            img = np.full((480, 640, 3), (42, 48, 52), dtype=np.uint8)
            cv2.putText(
                img, "CAMERA OFFLINE", (100, 240),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (180, 190, 200), 2,
            )
            cv2.putText(
                img, "Mock Device", (200, 280),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (120, 130, 140), 1,
            )
            _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
            with self._frame_lock:
                self._latest_jpeg = buf.tobytes()
        except Exception as exc:
            print(f"[MockCamera] generate placeholder failed: {exc}")


class MvsCameraDevice:
    """Hikvision GigE camera accessed through MVS SDK Python bindings.

    The MVS SDK provides a ctypes-based Python wrapper (MvCameraControl_class)
    installed alongside the driver. This class runs a daemon grabbing thread
    that continuously pulls frames and stores the latest JPEG for HTTP polling.
    """

    def __init__(self, camera_ip: str, mvs_import_path: str) -> None:
        self._camera_ip = camera_ip
        self._mvs_import_path = mvs_import_path
        self.connected = False
        self._handle = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._latest_jpeg: bytes | None = None
        self._latest_raw_jpeg: bytes | None = None
        self._frame_lock = threading.Lock()
        self._cam = None
        self._MvCamera = None
        # YOLO inference (optional)
        self._vision_inference: Any = None
        self._inference_interval: float = 0.5
        self._last_infer_time: float = 0.0
        self._latest_inference: dict[str, Any] | None = None
        self._infer_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        if self.connected:
            return True
        try:
            self._import_sdk()
            self._init_and_enum()
            self._create_and_open()
            self._configure_gige()
            self._start_grabbing()
            self.connected = True
            print(f"[Camera] Connected to {self._camera_ip}")
            return True
        except Exception as exc:
            print(f"[Camera] connect failed: {exc}")
            self._cleanup()
            return False

    def disconnect(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._stop_grabbing()
        self._cleanup()
        self.connected = False
        with self._frame_lock:
            self._latest_jpeg = None
        print("[Camera] Disconnected")

    def get_latest_jpeg(self) -> bytes | None:
        with self._frame_lock:
            return self._latest_jpeg

    def get_latest_raw_jpeg(self) -> bytes | None:
        with self._frame_lock:
            return self._latest_raw_jpeg

    def set_inference(self, vision_inference: Any, interval: float = 0.5) -> None:
        """Attach a VisionInference instance for real-time YOLO overlay."""
        self._vision_inference = vision_inference
        self._inference_interval = interval

    def get_latest_inference(self) -> dict[str, Any] | None:
        with self._infer_lock:
            return dict(self._latest_inference) if self._latest_inference else None

    # ------------------------------------------------------------------
    # Exposure control
    # ------------------------------------------------------------------

    def get_exposure(self) -> float | None:
        if not self.connected or self._cam is None:
            return None
        try:
            mv = self._MvCamera
            value = mv.MVCC_FLOATVALUE()
            ret = self._cam.MV_CC_GetFloatValue("ExposureTime", value)
            if ret == mv.MV_OK:
                return round(value.fCurValue, 1)
        except Exception as exc:
            print(f"[Camera] get_exposure failed: {exc}")
        return None

    def set_exposure(self, value_us: float) -> bool:
        if not self.connected or self._cam is None:
            return False
        try:
            mv = self._MvCamera
            ret = self._cam.MV_CC_SetFloatValue("ExposureTime", float(value_us))
            if ret == mv.MV_OK:
                return True
            print(f"[Camera] set_exposure failed: 0x{ret:X}")
        except Exception as exc:
            print(f"[Camera] set_exposure error: {exc}")
        return False

    # ------------------------------------------------------------------
    # MVS SDK internals
    # ------------------------------------------------------------------

    def _import_sdk(self) -> None:
        mvs_path = Path(self._mvs_import_path)
        if not mvs_path.exists():
            raise FileNotFoundError(f"MVS SDK not found at: {self._mvs_import_path}")
        mvs_str = str(mvs_path)
        if mvs_str not in sys.path:
            sys.path.insert(0, mvs_str)
        import MvCameraControl_class as mv
        self._MvCamera = mv

    def _init_and_enum(self) -> None:
        import ctypes

        mv = self._MvCamera

        # Initialize SDK
        ret = mv.MvCamera.MV_CC_Initialize()
        if ret != mv.MV_OK:
            raise RuntimeError(f"MV_CC_Initialize failed: 0x{ret:X}")

        # Enumerate GigE devices
        device_list = mv.MV_CC_DEVICE_INFO_LIST()
        ret = mv.MvCamera.MV_CC_EnumDevices(
            mv.MV_GIGE_DEVICE | mv.MV_USB_DEVICE, device_list
        )
        if ret != mv.MV_OK:
            raise RuntimeError(f"MV_CC_EnumDevices failed: 0x{ret:X}")

        if device_list.nDeviceNum == 0:
            raise RuntimeError("No MVS devices found")

        # Cast pDeviceInfo to proper struct array for iteration.
        # The pDeviceInfo field contains LP_ pointers; we copy each entry
        # into a concrete MV_CC_DEVICE_INFO via memmove.
        st_dev = mv.MV_CC_DEVICE_INFO()
        dev_info_size = ctypes.sizeof(mv.MV_CC_DEVICE_INFO)

        # Find device by IP
        found_index = -1
        found_st_dev = mv.MV_CC_DEVICE_INFO()
        for i in range(device_list.nDeviceNum):
            ctypes.memmove(
                ctypes.byref(st_dev),
                device_list.pDeviceInfo[i],
                dev_info_size,
            )
            if st_dev.nTLayerType == mv.MV_GIGE_DEVICE:
                gigE_info = st_dev.SpecialInfo.stGigEInfo
                # Current IP is stored as 4 bytes in nCurrentIp (uint32)
                nip = gigE_info.nCurrentIp
                ip_str = ".".join([
                    str((nip >> 24) & 0xFF),
                    str((nip >> 16) & 0xFF),
                    str((nip >> 8) & 0xFF),
                    str(nip & 0xFF),
                ])
                print(f"[Camera] Found GigE device [{i}]: IP={ip_str}")
                if ip_str == self._camera_ip:
                    found_index = i
                    ctypes.memmove(
                        ctypes.byref(found_st_dev),
                        device_list.pDeviceInfo[i],
                        dev_info_size,
                    )
                    break

        if found_index < 0:
            raise RuntimeError(f"Camera {self._camera_ip} not found in device list")

        # Create handle with the discovered device info
        self._cam = mv.MvCamera()
        ret = self._cam.MV_CC_CreateHandle(found_st_dev)
        if ret != mv.MV_OK:
            raise RuntimeError(f"MV_CC_CreateHandle failed: 0x{ret:X}")
        self._handle = self._cam

    def _create_and_open(self) -> None:
        mv = self._MvCamera
        ret = self._cam.MV_CC_OpenDevice(mv.MV_ACCESS_Exclusive, 0)
        if ret != mv.MV_OK:
            raise RuntimeError(f"MV_CC_OpenDevice failed: 0x{ret:X}")

    def _configure_gige(self) -> None:
        mv = self._MvCamera

        # Set optimal packet size for GigE (instance method)
        packet_size = self._cam.MV_CC_GetOptimalPacketSize()
        if packet_size > 0:
            self._cam.MV_CC_SetIntValue("GevSCPSPacketSize", packet_size)

        # Set continuous acquisition (trigger off)
        self._cam.MV_CC_SetEnumValue("TriggerMode", mv.MV_TRIGGER_MODE_OFF)

        # Set pixel format if available
        # MV-CU060-10GM is monochrome; try RGB8 if color, Mono8 if mono
        try:
            self._cam.MV_CC_SetEnumValue("PixelFormat", mv.PixelType_Gvsp_Mono8)
        except Exception:
            pass  # keep default

    def _start_grabbing(self) -> None:
        mv = self._MvCamera

        ret = self._cam.MV_CC_StartGrabbing()
        if ret != mv.MV_OK:
            raise RuntimeError(f"MV_CC_StartGrabbing failed: 0x{ret:X}")

        self._running = True
        self._thread = threading.Thread(target=self._grab_loop, daemon=True, name="cam-grab")
        self._thread.start()

    def _grab_loop(self) -> None:
        """Pull frames continuously using MV_FRAME_OUT (which wraps data ptr + info).

        Per MVS SDK sample code, MV_CC_GetImageBuffer populates an MV_FRAME_OUT
        struct whose pBufAddr field points to the raw pixel buffer, and whose
        stFrameInfo sub-struct carries width / height / pixel-type / length.
        """
        mv = self._MvCamera
        import ctypes

        # Pre-allocate convert buffer for fallback path
        payload_size = mv.MVCC_INTVALUE()
        ret = self._cam.MV_CC_GetIntValue("PayloadSize", payload_size)
        if ret != mv.MV_OK:
            payload_size.nCurValue = 3072 * 2048  # 6 MP worst-case
        data_buf = (ctypes.c_ubyte * payload_size.nCurValue)()

        st_frame = mv.MV_FRAME_OUT()

        while self._running:
            try:
                ctypes.memset(ctypes.byref(st_frame), 0, ctypes.sizeof(st_frame))
                ret = self._cam.MV_CC_GetImageBuffer(st_frame, 1000)
                if ret != mv.MV_OK or not st_frame.pBufAddr:
                    continue

                self._process_frame(data_buf, st_frame)

                self._cam.MV_CC_FreeImageBuffer(st_frame)
            except Exception as exc:
                if self._running:
                    print(f"[Camera] grab loop error: {exc}")

    def _process_frame(self, data_buf, st_frame) -> None:
        """Convert raw frame → BGR, optionally run YOLO, JPEG-encode, store."""
        import ctypes
        import time as _time
        import numpy as np

        mv = self._MvCamera
        info = st_frame.stFrameInfo

        frame_len = info.nFrameLen
        pixel_format = info.enPixelType
        width = info.nWidth
        height = info.nHeight

        frame_ptr = ctypes.cast(
            st_frame.pBufAddr,
            ctypes.POINTER(ctypes.c_ubyte * frame_len),
        )
        raw_bytes = np.ctypeslib.as_array(frame_ptr.contents, shape=(frame_len,))

        try:
            # --- pixel conversion → BGR ---
            if pixel_format == mv.PixelType_Gvsp_Mono8:
                import cv2
                img = raw_bytes.reshape((height, width))
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            elif pixel_format in (
                mv.PixelType_Gvsp_BayerRG8, mv.PixelType_Gvsp_BayerGB8,
                mv.PixelType_Gvsp_BayerGR8, mv.PixelType_Gvsp_BayerBG8,
            ):
                import cv2
                img = raw_bytes.reshape((height, width))
                conversions = {
                    mv.PixelType_Gvsp_BayerRG8: cv2.COLOR_BayerRG2BGR,
                    mv.PixelType_Gvsp_BayerGB8: cv2.COLOR_BayerGB2BGR,
                    mv.PixelType_Gvsp_BayerGR8: cv2.COLOR_BayerGR2BGR,
                    mv.PixelType_Gvsp_BayerBG8: cv2.COLOR_BayerBG2BGR,
                }
                img = cv2.cvtColor(img, conversions.get(pixel_format, cv2.COLOR_BayerRG2BGR))
            elif pixel_format == mv.PixelType_Gvsp_RGB8_Packed:
                import cv2
                img = raw_bytes.reshape((height, width, 3))
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            else:
                import cv2
                conv = mv.MV_CC_PIXEL_CONVERT_PARAM()
                ctypes.memset(ctypes.byref(conv), 0, ctypes.sizeof(conv))
                conv.pSrcData = st_frame.pBufAddr
                conv.nSrcDataLen = frame_len
                conv.nSrcWidth = width
                conv.nSrcHeight = height
                conv.enSrcPixelType = pixel_format
                conv.enDstPixelType = mv.PixelType_Gvsp_BGR8_Packed
                out_size = width * height * 3
                conv.pDstBuffer = ctypes.cast(data_buf, ctypes.c_void_p)
                conv.nDstBufferSize = out_size
                ret = self._cam.MV_CC_ConvertPixelType(conv)
                if ret != mv.MV_OK:
                    return
                img = np.ctypeslib.as_array(
                    (ctypes.c_ubyte * out_size).from_address(ctypes.addressof(data_buf)),
                    shape=(out_size,),
                ).reshape((height, width, 3))

            # --- Save raw JPEG (before inference overlay) ---
            import cv2
            _, raw_buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            with self._frame_lock:
                self._latest_raw_jpeg = raw_buf.tobytes()

            # --- YOLO inference (throttled) ---
            if self._vision_inference is not None and getattr(self._vision_inference, 'model', None) is not None:
                now = _time.monotonic()
                if now - self._last_infer_time >= self._inference_interval:
                    try:
                        infer_result = self._vision_inference.infer(img)
                        with self._infer_lock:
                            self._latest_inference = infer_result
                        if infer_result.get("detections"):
                            img = self._vision_inference.draw_results(img, infer_result)
                        self._last_infer_time = now
                    except Exception as exc:
                        print(f"[Camera] YOLO inference error: {exc}")

            # --- JPEG encode (inference overlay) ---
            _, jpeg_buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            with self._frame_lock:
                self._latest_jpeg = jpeg_buf.tobytes()
        except Exception as exc:
            if self._running:
                print(f"[Camera] frame processing error: {exc}")

    def _stop_grabbing(self) -> None:
        if self._cam is not None:
            try:
                self._cam.MV_CC_StopGrabbing()
            except Exception:
                pass

    def _cleanup(self) -> None:
        if self._cam is not None:
            try:
                self._cam.MV_CC_CloseDevice()
            except Exception:
                pass
            try:
                self._cam.MV_CC_DestroyHandle()
            except Exception:
                pass
            self._cam = None
            self._handle = None
        if self._MvCamera is not None:
            try:
                self._MvCamera.MvCamera.MV_CC_Finalize()
            except Exception:
                pass
            self._MvCamera = None
