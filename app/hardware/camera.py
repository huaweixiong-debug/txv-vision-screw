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

    def set_inference(
        self,
        vision_inference: Any,
        interval: float = 0.5,
        should_infer: Any = None,
        interval_selector: Any = None,
    ) -> None:
        pass  # mock — no-op

    def get_latest_inference(self) -> dict[str, Any] | None:
        return None

    def mark_stream_requested(self) -> None:
        pass

    def has_recent_stream_request(self, window_s: float = 3.0) -> bool:
        return self.connected

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
        self._latest_frame_bgr: Any = None
        self._latest_frame_version = 0
        self._latest_raw_jpeg_version = -1
        self._display_jpeg_quality = 55
        self._raw_jpeg_quality = 80
        self._display_max_width = 1280
        self._frame_interval = 0.25
        # YOLO inference (optional)
        self._vision_inference: Any = None
        self._inference_interval: float = 0.5
        self._last_infer_time: float = 0.0
        self._latest_inference: dict[str, Any] | None = None
        self._infer_lock = threading.Lock()
        self._should_infer: Any = None
        self._interval_selector: Any = None
        self._last_stream_request_at: float = 0.0

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
            self._latest_raw_jpeg = None
            self._latest_frame_bgr = None
        print("[Camera] Disconnected")

    def get_latest_jpeg(self) -> bytes | None:
        with self._frame_lock:
            return self._latest_jpeg

    def get_latest_raw_jpeg(self) -> bytes | None:
        with self._frame_lock:
            frame = self._latest_frame_bgr
            frame_version = self._latest_frame_version
            cached = self._latest_raw_jpeg
            cached_version = self._latest_raw_jpeg_version
        if cached is not None and cached_version == frame_version:
            return cached
        if frame is None:
            return cached
        try:
            import cv2

            ok, raw_buf = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, self._raw_jpeg_quality],
            )
            if not ok:
                return cached
            raw_jpeg = raw_buf.tobytes()
            with self._frame_lock:
                if self._latest_frame_version == frame_version:
                    self._latest_raw_jpeg = raw_jpeg
                    self._latest_raw_jpeg_version = frame_version
                return self._latest_raw_jpeg
        except Exception as exc:
            print(f"[Camera] raw jpeg encode failed: {exc}")
            return cached

    def set_inference(
        self,
        vision_inference: Any,
        interval: float = 0.5,
        should_infer: Any = None,
        interval_selector: Any = None,
    ) -> None:
        """Attach a VisionInference instance for real-time YOLO overlay."""
        self._vision_inference = vision_inference
        self._inference_interval = interval
        self._should_infer = should_infer
        self._interval_selector = interval_selector

    def set_frame_interval(self, interval_s: float) -> None:
        self._frame_interval = max(0.05, float(interval_s))

    def get_latest_inference(self) -> dict[str, Any] | None:
        with self._infer_lock:
            return dict(self._latest_inference) if self._latest_inference else None

    def mark_stream_requested(self) -> None:
        import time as _time

        self._last_stream_request_at = _time.monotonic()

    def has_recent_stream_request(self, window_s: float = 3.0) -> bool:
        import time as _time

        return (_time.monotonic() - self._last_stream_request_at) <= max(0.1, float(window_s))

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
            try:
                self._cam.MV_CC_SetEnumValue("ExposureAuto", 0)
            except Exception:
                pass
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
        self._set_enum_if_supported("ExposureAuto", 0)
        self._set_enum_if_supported("GainAuto", 0)

        # Set pixel format if available
        # MV-CU060-10GM is monochrome; try RGB8 if color, Mono8 if mono
        try:
            self._cam.MV_CC_SetEnumValue("PixelFormat", mv.PixelType_Gvsp_Mono8)
        except Exception:
            pass  # keep default

        self._set_int_if_supported("Width", 2048)
        self._set_int_if_supported("Height", 1536)

    def _set_int_if_supported(self, key: str, value: int) -> None:
        try:
            ret = self._cam.MV_CC_SetIntValue(key, int(value))
            if ret == self._MvCamera.MV_OK:
                print(f"[Camera] {key} set to {value}")
        except Exception as exc:
            print(f"[Camera] set {key} skipped: {exc}")

    def _set_enum_if_supported(self, key: str, value: int) -> None:
        try:
            ret = self._cam.MV_CC_SetEnumValue(key, int(value))
            if ret == self._MvCamera.MV_OK:
                print(f"[Camera] {key} set to {value}")
        except Exception as exc:
            print(f"[Camera] set {key} skipped: {exc}")

    def _start_grabbing(self) -> None:
        mv = self._MvCamera

        ret = self._cam.MV_CC_StartGrabbing()
        if ret != mv.MV_OK:
            raise RuntimeError(f"MV_CC_StartGrabbing failed: 0x{ret:X}")

        self._running = True
        self._thread = threading.Thread(target=self._grab_loop, daemon=True, name="cam-grab")
        self._thread.start()

    def _grab_loop(self) -> None:
        """Pull frames with throttling to limit CPU usage."""
        mv = self._MvCamera
        import time as _time
        import ctypes

        payload_size = mv.MVCC_INTVALUE()
        ret = self._cam.MV_CC_GetIntValue("PayloadSize", payload_size)
        if ret != mv.MV_OK:
            payload_size.nCurValue = 3072 * 2048
        data_buf = (ctypes.c_ubyte * payload_size.nCurValue)()

        st_frame = mv.MV_FRAME_OUT()
        _last_grab = 0.0

        while self._running:
            try:
                # Throttle acquisition to avoid a busy grab loop between frames.
                now = _time.monotonic()
                elapsed = now - _last_grab
                if elapsed < self._frame_interval:
                    _time.sleep(min(0.2, self._frame_interval - elapsed))
                    continue
                _last_grab = now

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
        import cv2

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
                img = raw_bytes.reshape((height, width))
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            elif pixel_format in (
                mv.PixelType_Gvsp_BayerRG8, mv.PixelType_Gvsp_BayerGB8,
                mv.PixelType_Gvsp_BayerGR8, mv.PixelType_Gvsp_BayerBG8,
            ):
                img = raw_bytes.reshape((height, width))
                conversions = {
                    mv.PixelType_Gvsp_BayerRG8: cv2.COLOR_BayerRG2BGR,
                    mv.PixelType_Gvsp_BayerGB8: cv2.COLOR_BayerGB2BGR,
                    mv.PixelType_Gvsp_BayerGR8: cv2.COLOR_BayerGR2BGR,
                    mv.PixelType_Gvsp_BayerBG8: cv2.COLOR_BayerBG2BGR,
                }
                img = cv2.cvtColor(img, conversions.get(pixel_format, cv2.COLOR_BayerRG2BGR))
            elif pixel_format == mv.PixelType_Gvsp_RGB8_Packed:
                img = raw_bytes.reshape((height, width, 3))
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            else:
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

            frame_bgr = np.ascontiguousarray(img).copy()
            with self._frame_lock:
                self._latest_frame_bgr = frame_bgr
                self._latest_frame_version += 1
                self._latest_raw_jpeg = None
                self._latest_raw_jpeg_version = -1

            # --- YOLO inference (throttled and state-aware) ---
            if (
                self._vision_inference is not None
                and getattr(self._vision_inference, "model", None) is not None
                and self._can_run_inference()
            ):
                now = _time.monotonic()
                if now - self._last_infer_time >= self._current_inference_interval():
                    try:
                        infer_result = self._vision_inference.infer(frame_bgr)
                        with self._infer_lock:
                            self._latest_inference = infer_result
                        self._last_infer_time = now
                    except Exception as exc:
                        print(f"[Camera] YOLO inference error: {exc}")

            with self._infer_lock:
                latest_inference = dict(self._latest_inference) if self._latest_inference else None

            display_img = frame_bgr
            if latest_inference and latest_inference.get("detections"):
                display_img = self._vision_inference.draw_results(frame_bgr.copy(), latest_inference)

            if display_img.shape[1] > self._display_max_width:
                preview_height = max(1, int(display_img.shape[0] * self._display_max_width / display_img.shape[1]))
                display_img = cv2.resize(
                    display_img,
                    (self._display_max_width, preview_height),
                    interpolation=cv2.INTER_AREA,
                )

            ok, jpeg_buf = cv2.imencode(
                ".jpg",
                display_img,
                [cv2.IMWRITE_JPEG_QUALITY, self._display_jpeg_quality],
            )
            if not ok:
                return
            with self._frame_lock:
                self._latest_jpeg = jpeg_buf.tobytes()
        except Exception as exc:
            if self._running:
                print(f"[Camera] frame processing error: {exc}")

    def _can_run_inference(self) -> bool:
        if self._should_infer is None:
            return True
        try:
            return bool(self._should_infer())
        except Exception as exc:
            print(f"[Camera] should_infer callback failed: {exc}")
            return True

    def _current_inference_interval(self) -> float:
        if self._interval_selector is None:
            return self._inference_interval
        try:
            return max(0.05, float(self._interval_selector()))
        except Exception as exc:
            print(f"[Camera] interval selector failed: {exc}")
            return self._inference_interval

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
