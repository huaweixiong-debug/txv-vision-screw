from __future__ import annotations

import re
import threading
import time as _time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from .config import resolve_path
from .hardware.camera import MockCameraDevice, MvsCameraDevice
from .hardware.coverage_detector import CoverageDetector
from .hardware.kilews import (
    KilewsDevice,
    MockKilewsClient,
    ModbusClient,
    TARGET_TYPE_TORQUE,
    TighteningResult,
)
from .hardware.plc import MockPLCClient, PlcState
from .hardware.stability_detector import StabilityDetector
from .storage import ProductionStorage, now_text
from .vision import VisionInference


STATE_LABELS = {
    "idle": "待开始",
    "vision_wait_stable": "O型圈稳定性检测",
    "vision_check_cover": "二维码检测",
    "plc_handshake": "PLC握手中",
    "vision": "O型圈视觉检测",
    "preassemble": "允许预装",
    "tightening_wait": "等待拧紧完成",
    "tightening_eval": "拧紧结果判定",
    "tightening": "允许拧紧",
    "ng_wait_rework": "NG等待PLC返修选择",
    "pending_scan": "流程结束，待扫码绑定",
    "complete": "追溯完成",
}


@dataclass
class BoltView:
    bolt_no: int
    torque_nm: float | None = None
    angle_deg: float | None = None
    result: str = "WAIT"

    def to_dict(self) -> dict[str, Any]:
        return {
            "bolt_no": self.bolt_no,
            "torque_nm": self.torque_nm,
            "angle_deg": self.angle_deg,
            "result": self.result,
        }


@dataclass
class Alarm:
    code: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class StationWorkflow:
    def __init__(self, settings: dict[str, Any], storage: ProductionStorage) -> None:
        self.settings = settings
        self.storage = storage
        self.state = "idle"
        a_cfg = settings.get("automation", {})
        self.automation_enabled = bool(a_cfg.get("enabled", False))
        self._manual_inference_interval_s = 0.5
        self.plc = MockPLCClient()
        self.camera: MockCameraDevice | MvsCameraDevice | None = None
        self.camera_status: dict[str, Any] = {
            "connected": False,
            "is_mock": False,
            "backend": "",
            "camera_ip": "",
            "error": "",
        }
        self._init_kilews(settings)
        self._init_camera(settings)
        self._init_plc(settings)
        self.operator = settings["auth"]["default_operator"]
        self.shift = settings["auth"]["default_shift"]
        self.current_record_id: int | None = None
        self.current_record: dict[str, Any] | None = None
        self.bolts = [BoltView(1), BoltView(2)]
        self.vision = {"status": "WAIT", "o_ring_count": 0, "confidence": 0.0}
        self.last_qr = ""
        self.alarm = Alarm()
        self.started_at = ""
        self.updated_at = now_text()

        # Automation
        self.stability_detector = StabilityDetector(
            required_count=2,
            stable_duration_s=float(a_cfg.get("stability_duration_s", 2.0)),
            position_threshold_px=float(a_cfg.get("stability_position_threshold_px", 30)),
        )
        self.coverage_detector = CoverageDetector(
            coverage_ratio_threshold=float(a_cfg.get("coverage_ratio_threshold", 0.85)),
        )
        self._automation_thread: threading.Thread | None = None
        self._automation_running = False
        self._automation_lock = threading.Lock()
        self._tightening_poll_interval = float(a_cfg.get("tightening_poll_interval_ms", 300)) / 1000.0
        self._tightening_timeout_s = float(a_cfg.get("tightening_timeout_s", 30.0))
        self._automation_status: dict[str, Any] = {
            "active": False,
            "stability_progress": 0.0,
            "stability_target": 2.0,
            "stability_status": "unstable",
            "coverage_status": "waiting",
            "coverage_ratios": [],
            "plc_connected": False,
            "tightening_progress": "",
        }
        self._last_snapshot_output_at = 0.0
        self._snapshot_output_interval_s = 0.15
        self._tightening_started_at = 0.0
        self._tightening_last_progress_at = 0.0
        self._last_tightening_poll_at = 0.0
        self._last_kilews_signature: tuple[int, int, int, int, int] | None = None
        self._tightening_baseline_signature: tuple[int, int, int, int] | None = None
        self._tightening_baseline_count = 0
        self._plc_reset_latched = False
        self._scanner_start_callback: Callable[[], dict[str, Any]] | None = None
        self._scanner_stop_callback: Callable[[], dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def reload_settings(self, settings: dict[str, Any]) -> None:
        was_auto = self.automation_enabled
        self.disable_automation()
        self.settings = settings
        self._init_kilews(settings)
        self._init_camera(settings)
        self._init_plc(settings)
        a_cfg = settings.get("automation", {})
        self.automation_enabled = bool(a_cfg.get("enabled", False))
        self.stability_detector = StabilityDetector(
            required_count=2,
            stable_duration_s=float(a_cfg.get("stability_duration_s", 2.0)),
            position_threshold_px=float(a_cfg.get("stability_position_threshold_px", 30)),
        )
        self.coverage_detector = CoverageDetector(
            coverage_ratio_threshold=float(a_cfg.get("coverage_ratio_threshold", 0.85)),
        )
        self._tightening_poll_interval = float(a_cfg.get("tightening_poll_interval_ms", 300)) / 1000.0
        self._tightening_timeout_s = float(a_cfg.get("tightening_timeout_s", 30.0))
        if was_auto:
            self.enable_automation()

    def set_scanner_callbacks(
        self,
        start_callback: Callable[[], dict[str, Any]] | None,
        stop_callback: Callable[[], dict[str, Any]] | None,
    ) -> None:
        self._scanner_start_callback = start_callback
        self._scanner_stop_callback = stop_callback

    def product_config(self, product_model: str | None = None) -> dict[str, Any]:
        model = product_model
        if not model and self.current_record:
            model = self.current_record.get("product_model")
        if not model:
            model = self.settings["station"]["active_product_model"]
        for product in self.settings.get("products", []):
            if product.get("product_model") == model:
                return product
        fallback = dict(self.settings["recipe"])
        fallback["product_model"] = model or self.settings["station"]["active_product_model"]
        fallback["recipe_no"] = self.settings["station"]["active_recipe_no"]
        return fallback

    def _init_kilews(self, settings: dict[str, Any]) -> None:
        kcfg = settings.get("kilews", {})
        if kcfg.get("enabled"):
            modbus = ModbusClient(
                ip=kcfg.get("ip", "192.168.3.10"),
                port=int(kcfg.get("port", 502)),
                unit_id=int(kcfg.get("unit_id", 1)),
                timeout=2.0,
            )
            self.kilews = KilewsDevice(modbus)
            if kcfg.get("auto_connect"):
                self._connect_kilews()
        else:
            self.kilews = MockKilewsClient()

    def _init_camera(self, settings: dict[str, Any]) -> None:
        vcfg = settings.get("vision", {})
        camera_ip = vcfg.get("camera_ip", "192.168.0.111")
        mvs_path = vcfg.get("mvs_path", r"C:\Program Files (x86)\MVS\Development\Samples\Python\MvImport")
        self.camera_status = {
            "connected": False,
            "is_mock": False,
            "backend": "mvs",
            "camera_ip": camera_ip,
            "error": "",
        }
        if self.camera is not None:
            try:
                self.camera.disconnect()
            except Exception:
                pass
        try:
            self.camera = MvsCameraDevice(camera_ip, mvs_path)
            ok = self.camera.connect()
            if not ok:
                self.camera_status.update({
                    "connected": False,
                    "is_mock": True,
                    "backend": "mock",
                    "error": f"MVS connect failed for {camera_ip}",
                })
                print("[Camera] MVS connect failed, using mock")
                self.camera = MockCameraDevice()
                self.camera.connect()
            else:
                self.camera_status.update({
                    "connected": True,
                    "is_mock": False,
                    "backend": "mvs",
                    "error": "",
                })
        except Exception as exc:
            self.camera_status.update({
                "connected": False,
                "is_mock": True,
                "backend": "mock",
                "error": str(exc),
            })
            print(f"[Camera] MVS init failed, using mock: {exc}")
            self.camera = MockCameraDevice()
            self.camera.connect()
        if isinstance(self.camera, MockCameraDevice):
            self.camera_status["connected"] = False
            self.camera_status["is_mock"] = True
            self.camera_status["backend"] = "mock"

        frame_interval_s = float(vcfg.get("frame_interval_ms", 250)) / 1000.0
        if hasattr(self.camera, "set_frame_interval"):
            self.camera.set_frame_interval(frame_interval_s)

        if vcfg.get("inference_enabled", True):
            try:
                inference_size = int(vcfg.get("inference_size", 480))
                vision_infer = VisionInference(
                    model_path=resolve_path(vcfg.get("model_path", "yolo26s.pt")),
                    confidence_threshold=float(vcfg.get("confidence_threshold", 0.3)),
                    iou_threshold=float(vcfg.get("iou_threshold", 0.3)),
                    dedup_overlap=float(vcfg.get("dedup_overlap", 0.7)),
                    yolo_classes=list(vcfg.get("yolo_classes", ["NG", "O_Ring_L", "O_Ring_S", "QR", "TXV"])),
                    inference_size=min(max(inference_size, 320), 416),
                )
                interval_s = float(vcfg.get("inference_interval_ms", 300)) / 1000.0
                self.camera.set_inference(
                    vision_infer,
                    interval_s,
                    should_infer=self._should_run_inference,
                    interval_selector=self._inference_interval_s,
                )
                print(f"[Camera] YOLO inference wired (frame_interval={frame_interval_s}s, interval={interval_s}s)")
            except Exception as exc:
                print(f"[Camera] YOLO inference wiring failed: {exc}")

        # Restore saved exposure
        saved_exposure = vcfg.get("camera_exposure_us")
        if saved_exposure is not None:
            try:
                if self.camera.set_exposure(float(saved_exposure)):
                    print(f"[Camera] Exposure restored: {saved_exposure} us")
            except Exception as exc:
                print(f"[Camera] Exposure restore failed: {exc}")

    def _init_plc(self, settings: dict[str, Any]) -> None:
        """Create PLC client based on settings (mock or real Snap7)."""
        from .hardware.plc import create_plc_client
        try:
            self.plc = create_plc_client(settings)
            print(f"[PLC] Client type: {type(self.plc).__name__}")
        except Exception as exc:
            print(f"[PLC] Init failed, using mock: {exc}")
            self.plc = MockPLCClient()

    def _is_visual_inference_state(self) -> bool:
        return self.state in {
            "vision",
            "vision_wait_stable",
            "vision_check_cover",
            "preassemble",
        }

    def _should_run_inference(self) -> bool:
        if self.camera is None:
            return False
        if getattr(self, "automation_enabled", False) and self._is_visual_inference_state():
            return True
        return self.camera.has_recent_stream_request(3.0)

    def _inference_interval_s(self) -> float:
        base = float(self.settings.get("vision", {}).get("inference_interval_ms", 300)) / 1000.0
        if getattr(self, "automation_enabled", False) and self._is_visual_inference_state():
            return base
        return max(base, getattr(self, "_manual_inference_interval_s", 0.5))

    def _connect_kilews(self) -> bool:
        if not isinstance(self.kilews, KilewsDevice):
            return False
        kcfg = self.settings.get("kilews", {})
        ok = self.kilews.modbus.connect(
            ip=kcfg.get("ip", "192.168.3.10"),
            port=int(kcfg.get("port", 502)),
            unit_id=int(kcfg.get("unit_id", 1)),
        )
        if ok:
            self.kilews.refresh()
            self.storage.add_event(None, "kilews.connect", "控制器已连接")
        return ok

    def disconnect_kilews(self) -> None:
        if isinstance(self.kilews, KilewsDevice):
            self.kilews.modbus.disconnect()

    def _reset_tightening_tracking(self, started_at: float = 0.0) -> None:
        self._tightening_started_at = started_at
        self._tightening_last_progress_at = started_at
        self._last_tightening_poll_at = 0.0
        self._last_kilews_signature = None
        self._tightening_baseline_signature = None
        self._tightening_baseline_count = 0

    def _prime_tightening_baseline(self) -> None:
        if not isinstance(self.kilews, KilewsDevice):
            return
        try:
            self.kilews.refresh()
            baseline_signature = (
                int(self.kilews.result_code),
                int(self.kilews.torque_raw),
                int(self.kilews.angle_raw),
                int(self.kilews.tighten_time_ms),
            )
            self._tightening_baseline_signature = baseline_signature
            self._last_kilews_signature = baseline_signature
            self._tightening_baseline_count = int(self.kilews.current_count or 0)
        except Exception as exc:
            print(f"[Automation] Kilews baseline prime error: {exc}")

    def _reset_runtime_state(self, *, alarm: Alarm | None = None) -> None:
        bolt_count = max(len(self.bolts), 2)
        self.state = "idle"
        self.current_record_id = None
        self.current_record = None
        self.bolts = [BoltView(index + 1) for index in range(bolt_count)]
        self.vision = {
            "status": "WAIT",
            "o_ring_count": 0,
            "confidence": 0.0,
            "o_ring_ok": False,
            "detections": [],
        }
        self.last_qr = ""
        self.alarm = alarm or Alarm()
        self.stability_detector.reset()
        self._automation_status["stability_progress"] = 0.0
        self._automation_status["stability_status"] = "unstable"
        self._automation_status["coverage_status"] = "waiting"
        self._automation_status["coverage_ratios"] = []
        self._automation_status["txv_stable_since"] = 0
        self._automation_status["tightening_progress"] = ""
        self._reset_tightening_tracking()
        self._reset_kilews_live_view()

    def _handle_plc_reset(self) -> None:
        record_id = self.current_record_id
        self._trigger_scanner_stop("plc_reset")
        if record_id is not None and self.state not in {"idle", "complete"}:
            self.current_record = self.storage.update_record(
                record_id,
                status="RESET",
                alarm_code="PLC_RESET",
                alarm_message="PLC reset",
                completed_at=now_text(),
            )
            self.storage.add_event(record_id, "plc.reset", "PLC reset -> workflow reset to idle")

        self._reset_runtime_state(alarm=Alarm("PLC_RESET", "PLC reset"))
        self.write_plc_outputs()
        print("[Automation] PLC reset -> workflow idle")

    def _trigger_scanner_start(self, reason: str) -> None:
        if self._scanner_start_callback is None:
            return
        try:
            result = self._scanner_start_callback()
            command_hex = ""
            if isinstance(result, dict):
                command_hex = str(result.get("command_hex") or "")
            if self.current_record_id is not None:
                detail = reason if not command_hex else f"{reason} -> {command_hex}"
                self.storage.add_event(self.current_record_id, "scanner.trigger_start", detail)
            print(f"[Scanner] trigger start [{reason}]")
        except Exception as exc:
            if self.current_record_id is not None:
                self.storage.add_event(self.current_record_id, "scanner.trigger_start_failed", f"{reason}: {exc}")
            print(f"[Scanner] trigger start failed [{reason}]: {exc}")

    def _trigger_scanner_stop(self, reason: str) -> None:
        if self._scanner_stop_callback is None:
            return
        try:
            result = self._scanner_stop_callback()
            command_hex = ""
            if isinstance(result, dict):
                command_hex = str(result.get("command_hex") or "")
            if self.current_record_id is not None:
                detail = reason if not command_hex else f"{reason} -> {command_hex}"
                self.storage.add_event(self.current_record_id, "scanner.trigger_stop", detail)
            print(f"[Scanner] trigger stop [{reason}]")
        except Exception as exc:
            if self.current_record_id is not None:
                self.storage.add_event(self.current_record_id, "scanner.trigger_stop_failed", f"{reason}: {exc}")
            print(f"[Scanner] trigger stop failed [{reason}]: {exc}")

    def _qr_binding_required(self) -> bool:
        product_cfg = self.product_config()
        return bool(product_cfg.get("enable_qr_binding", True))

    def _complete_without_scan(self, reason: str) -> None:
        self.current_record = self.storage.update_record(
            self.current_record_id,
            qr_bind_status="SKIPPED",
            status="COMPLETED",
            scanned_at=now_text(),
            alarm_code="",
            alarm_message="",
        )
        self.storage.add_event(self.current_record_id, "qr.skipped", reason)
        self.state = "complete"
        self.alarm = Alarm()
        if self.automation_enabled:
            self._signal_plc_scan_complete()
        else:
            self.write_plc_outputs()

    def _reset_kilews_live_view(self) -> None:
        if not hasattr(self.kilews, "current_job"):
            return
        self.kilews.current_job = 0
        self.kilews.current_seq = 0
        self.kilews.current_step = 0
        self.kilews.current_count = 0
        self.kilews.running = False
        self.kilews.torque_raw = 0
        self.kilews.angle_raw = 0
        self.kilews.result_code = 0
        self.kilews.tighten_time_ms = 0

    def _kilews_snapshot(self) -> dict[str, Any]:
        payload = self.kilews.status_dict()
        if self.state not in {"tightening", "tightening_wait", "tightening_eval", "pending_scan", "ng_wait_rework", "complete"}:
            payload.update({
                "current_job": 0,
                "current_seq": 0,
                "current_step": 0,
                "current_count": 0,
                "running": False,
                "torque_raw": 0,
                "torque_nm": None,
                "angle_raw": 0,
                "angle_deg": None,
                "result_code": 0,
                "result_label": "",
                "tighten_time_ms": 0,
            })
        return payload

    def _all_bolts_have_results(self) -> bool:
        return all(
            bolt.result in {"OK", "NG"} and bolt.torque_nm is not None and bolt.angle_deg is not None
            for bolt in self.bolts
        )

    @staticmethod
    def _has_detection(detections: list[dict[str, Any]], *names: str) -> bool:
        wanted = {name.strip().upper() for name in names if name.strip()}
        for det in detections:
            label = str(det.get("class_name") or "").strip().upper()
            if label in wanted:
                return True
        return False

    def _auto_trigger_scanner(self, now: float) -> None:
        """Auto-trigger scanner every 2s when waiting for QR scan."""
        last_trigger = getattr(self, "_last_scanner_trigger", 0.0)
        if now - last_trigger < 2.0:
            return
        self._last_scanner_trigger = now
        self._trigger_scanner_start("auto_pending_scan")

    def _qr_ready_detected(self, detections: list[dict[str, Any]]) -> bool:
        # The current production model may expose QR directly instead of TXV.
        return (
            self._has_detection(detections, "QR", "TXV")
            or self.coverage_detector.check(detections)
        )

    def write_kilews_params(self, product_model: str | None = None) -> dict[str, Any]:
        product_cfg = self.product_config(product_model)
        if not isinstance(self.kilews, KilewsDevice):
            return {"ok": False, "error": "Mock 模式下不支持写入控制器"}
        speed = int(self.settings.get("kilews", {}).get("speed_rpm", 500))
        kilews_torque_target = float(product_cfg.get("kilews_torque_target_nm", 2.0))
        kilews_torque_min = float(product_cfg.get("kilews_torque_min_nm", 2.0))
        kilews_torque_max = float(product_cfg.get("kilews_torque_max_nm", 5.0))
        kilews_angle_target = float(
            product_cfg.get(
                "kilews_angle_target_deg",
                product_cfg.get("angle_target_deg", 90.0),
            )
        )
        kilews_angle_target_raw = int(product_cfg.get("kilews_angle_target_raw", 900))
        kilews_angle_min_raw = int(product_cfg.get("kilews_angle_min_raw", 700))
        kilews_angle_max_raw = int(product_cfg.get("kilews_angle_max_raw", 12000))
        result = self.kilews.write_all_flow(
            torque_target=kilews_torque_target,
            torque_min=kilews_torque_min,
            torque_max=kilews_torque_max,
            angle_target=kilews_angle_target,
            angle_target_raw=kilews_angle_target_raw,
            angle_min_raw=kilews_angle_min_raw,
            angle_max_raw=kilews_angle_max_raw,
            speed=speed,
            target_type=TARGET_TYPE_TORQUE,
        )
        self.storage.add_event(
            self.current_record_id,
            "kilews.write_params",
            f"产品 {product_cfg['product_model']} 参数已写入 (Job 221)",
        )
        return result

    # ------------------------------------------------------------------
    # Automation enable / disable
    # ------------------------------------------------------------------

    def enable_automation(self) -> None:
        """Start the background automation thread."""
        if self._automation_running:
            return
        from .hardware.plc import S7200SmartClient
        if isinstance(self.plc, S7200SmartClient) and not self.plc.connected:
            print("[Automation] PLC not connected, attempting connect...")
            self.plc.connect()
        self._automation_running = True
        self.automation_enabled = True
        self._automation_thread = threading.Thread(
            target=self._automation_loop, daemon=True, name="auto-loop"
        )
        self._automation_thread.start()
        self._automation_status["active"] = True
        print("[Automation] Enabled")

    def disable_automation(self) -> None:
        """Stop the background automation thread."""
        self._automation_running = False
        self.automation_enabled = False
        if self._automation_thread and self._automation_thread.is_alive():
            self._automation_thread.join(timeout=3.0)
        self._automation_thread = None
        self._automation_status["active"] = False
        self.stability_detector.reset()
        print("[Automation] Disabled")

    # ------------------------------------------------------------------
    # Automation background thread
    # ------------------------------------------------------------------

    def _automation_loop(self) -> None:
        """Main automation loop running in a background daemon thread.

        Monitors YOLO inference → stability → coverage → PLC handshake →
        tightening data collection → QR scan.
        """
        tick = 0.10  # seconds between loop iterations

        while self._automation_running:
            try:
                with self._automation_lock:
                    self._automation_tick()
            except Exception as exc:
                print(f"[Automation] loop error: {exc}")
            _time.sleep(tick)

    def _automation_tick(self) -> None:
        """Single tick of the automation state machine."""
        now = _time.monotonic()

        # ---- read latest YOLO inference ----
        if self.camera is None:
            return
        inference = self.camera.get_latest_inference()
        detections = inference.get("detections", []) if inference else []
        o_ring_count = inference.get("o_ring_count", 0) if inference else 0
        o_ring_ok = inference.get("o_ring_ok", False) if inference else False
        self.vision["detections"] = detections
        self.vision["o_ring_count"] = o_ring_count
        self.vision["o_ring_ok"] = o_ring_ok
        self.vision["confidence"] = inference.get("confidence", 0.0) if inference else 0.0

        # PLC keep-alive & status
        from .hardware.plc import S7200SmartClient
        if isinstance(self.plc, S7200SmartClient):
            if not self.plc.connected:
                self.plc.connect()
            self._automation_status["plc_connected"] = self.plc.connected
        else:
            self._automation_status["plc_connected"] = True

        # Kilews keep-alive
        if isinstance(self.kilews, KilewsDevice) and not self.kilews.modbus.connected:
            try:
                self._connect_kilews()
            except Exception:
                pass
            self._automation_status["plc_connected"] = True
        plc_state = self.plc.read_state()

        if plc_state.m_plc_reset:
            if not self._plc_reset_latched:
                self._plc_reset_latched = True
                self._handle_plc_reset()
            return
        self._plc_reset_latched = False

        # ---- State: idle → auto-start when automation runs ----
        if self.state == "idle":
            if not self.automation_enabled:
                return
            product = self.settings["station"]["active_product_model"]
            self.start_cycle(product)
            return

        # ---- State: vision_wait_stable ----
        if self.state == "vision_wait_stable":
            status = self.stability_detector.update(now, detections)
            self._automation_status["stability_status"] = status
            elapsed, target = self.stability_detector.stability_progress(now)
            self._automation_status["stability_progress"] = elapsed
            self._automation_status["stability_target"] = target

            if o_ring_ok:
                self._automation_status["stability_status"] = "stable_ok"
                self._automation_status["stability_progress"] = target
                self._on_stability_ok()

        # ---- State: vision_check_cover ----
        elif self.state == "vision_check_cover":
            self._automation_status["coverage_ratios"] = self.coverage_detector.coverage_ratios(detections)
            if self._qr_ready_detected(detections):
                self._automation_status["txv_stable_since"] = now
                self._automation_status["coverage_status"] = "detected"
                self._on_valve_covered()
            else:
                self._automation_status["txv_stable_since"] = 0
                self._automation_status["coverage_status"] = "waiting"

        # ---- State: plc_handshake ----
        elif self.state == "plc_handshake":
            self._automation_status["coverage_status"] = "plc_waiting"

            if plc_state.m_plc_ready:
                self.state = "tightening_wait"
                if self._tightening_baseline_signature is None:
                    self._reset_tightening_tracking(now)
                else:
                    self._tightening_started_at = now
                    self._tightening_last_progress_at = now
                    self._last_tightening_poll_at = 0.0
                self._automation_status["tightening_progress"] = "PLC 已就绪，等待拧紧完成..."
                self.storage.add_event(
                    self.current_record_id, "plc.handshake", "PLC 已就绪"
                )
                self.write_plc_outputs()
                if isinstance(self.kilews, KilewsDevice) and self._tightening_baseline_signature is None:
                    self._prime_tightening_baseline()

        # ---- State: tightening_wait ----
        elif self.state == "tightening_wait":
            # Poll Kilews for tightening results
            self._poll_kilews_results(now, plc_state)

        # ---- State: tightening_eval ----
        elif self.state == "tightening_eval":
            self._finalize_tightening()

        # ---- State: pending_scan (automation: signal PLC) ----
        elif self.state == "pending_scan":
            # Auto-trigger scanner if configured
            self._auto_trigger_scanner(now)
            # Check if QR has been scanned
            if self.current_record and self.current_record.get("qr_bind_status") == "BOUND":
                self._signal_plc_scan_complete()

        # ---- State: complete -> immediately prepare next auto cycle ----
        elif self.state == "complete":
            if self.automation_enabled:
                self._reset_runtime_state()
                self.write_plc_outputs()
                print("[Automation] Cycle complete -> next cycle ready")

    def _on_stability_ok(self) -> None:
        """Called when 2-second stability with 2 O-rings is achieved."""
        self.vision = {
            "status": "OK",
            "o_ring_count": 2,
            "confidence": 1.0,
        }
        self.state = "vision_check_cover"
        self._automation_status["coverage_status"] = "checking"

        # Compute actual stability duration in milliseconds
        stability_ms = 0
        now = _time.monotonic()
        elapsed, _ = self.stability_detector.stability_progress(now)
        stability_ms = int(elapsed * 1000)

        self.storage.add_event(
            self.current_record_id, "vision.stability_ok",
            f"O型圈稳定性检测通过（2 个，静止 {elapsed:.1f} 秒）"
        )
        if self.current_record_id is not None:
            self.current_record = self.storage.update_record(
                self.current_record_id,
                vision_status="OK",
                o_ring_count=2,
                stability_duration_ms=stability_ms,
            )
        self.write_plc_outputs()
        # Auto-capture image on stability OK
        self._auto_capture("vision_stable")
        print("[Automation] O-ring stability OK → checking valve coverage")

    def _on_valve_covered(self) -> None:
        """Called when the cycle-ready QR/TXV marker is detected."""
        self.state = "plc_handshake"
        self._automation_status["coverage_status"] = "plc_handshake"

        # Write M0.0 = 1 (product ready) + clear old Kilews data
        self.bolts = [BoltView(i + 1) for i in range(len(self.bolts))]
        if isinstance(self.kilews, KilewsDevice):
            self.kilews.last_result_code = None
        self.plc.write_outputs({"product_ready": True})

        # Compute minimum IoA as coverage confidence
        ratios = self._automation_status.get("coverage_ratios", [])
        min_ioa = min((r.get("ioa", 0.0) for r in ratios), default=0.0) if ratios else 0.0

        self.storage.add_event(
            self.current_record_id, "vision.coverage_ok",
            f"二维码检测通过 → PLC M0.0=1 (最低IoA={min_ioa:.3f})"
        )
        if self.current_record_id is not None:
            self.current_record = self.storage.update_record(
                self.current_record_id,
                expansion_valve_detected=1,
                plc_product_ready_sent=1,
                coverage_confidence=round(min_ioa, 4),
            )
        self._auto_capture("valve_covered")
        if isinstance(self.kilews, KilewsDevice):
            self._reset_tightening_tracking(_time.monotonic())
            self._prime_tightening_baseline()
        self.write_plc_outputs()
        print("[Automation] QR detected -> PLC M0.0=1, waiting for PLC ready")

    def _poll_kilews_results(self, now: float, plc_state: PlcState) -> None:
        """Poll Kilews Modbus registers for tightening results.

        Reads only the result register block (4155-4164, 10 regs) instead of
        a full refresh to keep loop latency low (~1 MODBUS round-trip).
        """
        def log_poll(message: str) -> None:
            print(f"[Automation] Kilews poll: {message}")

        if self._tightening_started_at <= 0:
            self._tightening_started_at = now
        if self._tightening_last_progress_at <= 0:
            self._tightening_last_progress_at = self._tightening_started_at
        if self._tightening_timeout_s > 0 and now - self._tightening_last_progress_at >= self._tightening_timeout_s:
            for bolt in self.bolts:
                if bolt.result == "WAIT":
                    bolt.result = "NG"
            self._automation_status["tightening_progress"] = "拧紧超时"
            self.storage.add_event(self.current_record_id, "tightening.timeout", "拧紧超时，按 NG 处理")
            self.state = "tightening_eval"
            return
        if self._last_tightening_poll_at and now - self._last_tightening_poll_at < self._tightening_poll_interval:
            return
        self._last_tightening_poll_at = now

        if not isinstance(self.kilews, KilewsDevice):
            self._mock_kilews_results()
            return

        try:
            # Lightweight read: only result registers
            vals = self.kilews.modbus.read_registers(4155, 10)
            if not vals or len(vals) < 10:
                print(f"[Kilews] poll: MODBUS read failed or short vals={vals}", flush=True)
                return

            torque_raw = (vals[0] << 16) | vals[1]
            tighten_time_ms = vals[3]
            angle_raw = (vals[4] << 16) | vals[5]
            result_code = vals[9]
            print(f"[Kilews] poll: code={result_code} torque_raw={torque_raw} angle_raw={angle_raw} "
                  f"time={tighten_time_ms}ms vals[0..9]={vals}", flush=True)
            status_vals = self.kilews.modbus.read_registers(4305, 4)
            current_count = None
            if status_vals and len(status_vals) >= 4:
                self.kilews.current_job = status_vals[0]
                self.kilews.current_seq = status_vals[1]
                self.kilews.current_step = status_vals[2]
                self.kilews.current_count = status_vals[3]
                current_count = int(status_vals[3])

            # Update Kilews device state in-place
            self.kilews.torque_raw = torque_raw
            self.kilews.angle_raw = angle_raw
            self.kilews.result_code = result_code
            self.kilews.tighten_time_ms = tighten_time_ms

            if result_code in (4, 5, 6, 7, 8):  # a result is available
                result_signature = (result_code, torque_raw, angle_raw, tighten_time_ms)
                count_delta = None
                if current_count is not None:
                    count_delta = current_count - self._tightening_baseline_count
                log_poll(
                    "result="
                    f"code={result_code} torque_raw={torque_raw} angle_raw={angle_raw} "
                    f"time_ms={tighten_time_ms} count={current_count} count_delta={count_delta} "
                    f"baseline={self._tightening_baseline_signature} last={self._last_kilews_signature}"
                )

                # Skip if this is the same old result we saw at baseline
                if self._tightening_baseline_signature is not None:
                    if result_signature == self._tightening_baseline_signature:
                        if count_delta is None or count_delta <= 0:
                            print(f"[Kilews] SKIP: matches baseline sig={self._tightening_baseline_signature} count_delta={count_delta}", flush=True)
                            return
                else:
                    # No baseline yet — set it now from this first reading
                    self._tightening_baseline_signature = result_signature
                    self._tightening_baseline_count = current_count if current_count is not None else 0
                    print(f"[Kilews] SET baseline: sig={self._tightening_baseline_signature} count={self._tightening_baseline_count}", flush=True)
                    return

                if result_signature == self._last_kilews_signature:
                    print(f"[Kilews] SKIP: duplicate last_sig={self._last_kilews_signature}", flush=True)
                    return
                torque = self.kilews._decode_torque(torque_raw)
                angle = self.kilews._decode_angle(angle_raw)
                result = "OK" if result_code in (4, 5, 6) else "NG"

                bolt_no = self.next_unrecorded_bolt_no()
                if count_delta is not None and 1 <= count_delta <= len(self.bolts):
                    bolt_no = count_delta
                print(f"[Kilews] bolt_no={bolt_no} count_delta={count_delta} next_waits={bolt_no}", flush=True)
                if 1 <= bolt_no <= len(self.bolts):
                    bolt = self.bolts[bolt_no - 1]
                    if bolt.result == "WAIT" or bolt.torque_nm is None or bolt.angle_deg is None:
                        self._last_kilews_signature = result_signature
                        self._tightening_last_progress_at = now
                        bolt.torque_nm = torque
                        bolt.angle_deg = angle
                        bolt.result = result
                        print(f"[Kilews] WROTE bolt{bolt_no}: torque={torque:.3f} angle={angle:.1f} result={result}", flush=True)
                        if self.current_record_id is not None:
                            self.current_record = self.storage.update_record(
                                self.current_record_id,
                                **{
                                    f"bolt{bolt_no}_torque": round(torque, 2),
                                    f"bolt{bolt_no}_angle": round(angle, 2),
                                    f"bolt{bolt_no}_result": result,
                                },
                            )
                        self._automation_status["tightening_progress"] = (
                            f"螺栓 {bolt_no}: {torque:.2f} Nm / {angle:.1f}° / {result}"
                        )
                        self.storage.add_event(
                            self.current_record_id,
                            "tightening.result",
                            f"螺栓{bolt_no}: {torque:.2f} Nm / {angle:.1f}° / {result}",
                        )
                        log_poll(
                            f"recorded bolt{bolt_no} torque={torque:.2f} angle={angle:.1f} result={result}"
                        )
                        self.write_plc_outputs(current_bolt_no=bolt_no)
                    else:
                        log_poll(
                            f"bolt{bolt_no} already recorded result={bolt.result} "
                            f"torque={bolt.torque_nm} angle={bolt.angle_deg}"
                        )
                else:
                    log_poll(f"computed invalid bolt_no={bolt_no}")

            # Check if all bolts done
            if self._all_bolts_have_results() or (
                plc_state.m_plc_tightening_done and self._all_bolts_have_results()
            ):
                self.state = "tightening_eval"

        except Exception as exc:
            print(f"[Automation] Kilews poll error: {exc}")

    def _mock_kilews_results(self) -> None:
        """Simulate tightening results for mock Kilews (development)."""
        for bolt in self.bolts:
            if bolt.result == "WAIT":
                bolt.torque_nm = 4.50
                bolt.angle_deg = 91.0
                bolt.result = "OK"
        self.state = "tightening_eval"

    def _finalize_tightening(self) -> None:
        """Evaluate all bolt results, write PLC M0.1, transition state."""
        final = "OK" if all(b.result == "OK" for b in self.bolts) else "NG"

        # Write M0.1 / M1.0
        self.plc.write_outputs({
            "tightening_ok": (final == "OK"),
            "tightening_ng": (final == "NG"),
        })

        if self.current_record_id is not None:
            self.current_record = self.storage.update_record(
                self.current_record_id,
                plc_tightening_ok_sent=1,
            )

        if final == "NG":
            self.state = "ng_wait_rework"
            self.alarm = Alarm("PART_NG", "拧紧结果 NG，请在 PLC 侧选择返修/放行")
        else:
            self.state = "pending_scan" if self._qr_binding_required() else "complete"
            self.alarm = Alarm()

        self.current_record = self.storage.update_record(
            self.current_record_id,
            final_result=final,
            status=(
                "WAIT_QR"
                if final == "OK" and self._qr_binding_required()
                else ("COMPLETED" if final == "OK" else "NG_WAIT_REWORK")
            ),
            qr_bind_status="WAIT" if self._qr_binding_required() else "SKIPPED",
            completed_at=now_text(),
            alarm_code=self.alarm.code,
            alarm_message=self.alarm.message,
        )
        self.storage.add_event(
            self.current_record_id, "part.final", f"整件结果：{final} → PLC M0.1={'1' if final == 'OK' else '0'}"
        )
        if final == "OK" and self._qr_binding_required():
            self._trigger_scanner_start("tightening_ok")
        elif final == "OK":
            self._complete_without_scan("QR binding disabled -> auto complete after tightening")
        self._auto_capture("tightening_done")
        self.write_plc_outputs()
        print(f"[Automation] Tightening final: {final} → PLC M0.1={'1' if final == 'OK' else '0'}")

    def _signal_plc_scan_complete(self) -> None:
        """Write M0.2 = 1 to PLC after QR scan."""
        self.plc.write_outputs({"scan_complete": True})
        if self.current_record_id is not None:
            self.current_record = self.storage.update_record(
                self.current_record_id,
                plc_scan_complete_sent=1,
            )
        self.state = "complete"
        self.write_plc_outputs()
        self.storage.add_event(
            self.current_record_id, "scan.plc_signal", "扫码完成 → PLC M0.2=1"
        )
        print("[Automation] QR scan complete → PLC M0.2=1")

    def _auto_capture(self, trigger: str) -> None:
        """Auto-save image on state transition if enabled."""
        if not self.settings.get("vision", {}).get("auto_capture_enabled", True):
            return
        try:
            from .vision import capture_frame
            product = self.current_record.get("product_model") if self.current_record else "UNKNOWN"
            qr = self.current_record.get("qr_code") if self.current_record else ""
            path = capture_frame(self.camera, self.settings, product, qr)
            if self.current_record_id is not None:
                self.storage.update_record(self.current_record_id, image_path=str(path))
                self.storage.add_event(self.current_record_id, f"image.capture.{trigger}", str(path))
            print(f"[Automation] Auto-capture [{trigger}]: {path}")
        except Exception as exc:
            print(f"[Automation] Auto-capture failed: {exc}")

    # ------------------------------------------------------------------
    # Manual workflow (preserved for non-automation mode)
    # ------------------------------------------------------------------

    def login(self, operator: str, shift: str) -> dict[str, Any]:
        self.operator = operator.strip() or self.settings["auth"]["default_operator"]
        self.shift = shift.strip() or self.settings["auth"]["default_shift"]
        self.storage.add_event(self.current_record_id, "operator.login", f"{self.operator} / {self.shift}")
        return self.snapshot()

    def start_cycle(self, product_model: str | None = None, recipe_no: int | None = None) -> dict[str, Any]:
        # Don't create duplicate if already running
        if self.current_record_id is not None and self.state not in ("idle", "complete"):
            return {"ok": True, "record_id": self.current_record_id, "skipped": True}
        product = product_model or self.settings["station"]["active_product_model"]
        product_cfg = self.product_config(product)
        recipe = int(recipe_no or product_cfg.get("recipe_no") or self.settings["station"]["active_recipe_no"])
        bolt_count = int(product_cfg["bolt_count"])
        self.current_record = self.storage.create_record(
            product_model=product,
            recipe_no=recipe,
            station_id=self.settings["station"]["station_id"],
            operator=self.operator,
            shift=self.shift,
            bolt_count=bolt_count,
            model_version=self.settings["vision"]["model_version"],
        )
        self.current_record_id = int(self.current_record["id"])
        self.bolts = [BoltView(index + 1) for index in range(bolt_count)]
        self.vision = {"status": "WAIT", "o_ring_count": 0, "confidence": 0.0}
        self.last_qr = ""
        self.alarm = Alarm()
        self.started_at = now_text()
        self.updated_at = self.started_at
        self._reset_kilews_live_view()

        # Reset detectors for new cycle
        self.stability_detector.reset()
        self._automation_status["stability_progress"] = 0.0
        self._automation_status["stability_status"] = "unstable"
        self._automation_status["coverage_status"] = "waiting"
        self._automation_status["coverage_ratios"] = []
        self._automation_status["txv_stable_since"] = 0
        self._automation_status["tightening_progress"] = ""

        # Choose start state based on automation
        if self.automation_enabled:
            self.state = "vision_wait_stable"
            print("[Workflow] Automation mode: start cycle → vision_wait_stable")
        else:
            self.state = "vision"

        # Write parameters to Kilews controller when enabled
        if isinstance(self.kilews, KilewsDevice) and self.kilews.modbus.connected:
            try:
                kw_result = self.write_kilews_params(product)
                if not kw_result.get("ok"):
                    print(f"[Kilews] 参数写入警告: {kw_result.get('error', '未知')}")
            except Exception as exc:
                print(f"[Kilews] 参数写入异常: {exc}")

        self.write_plc_outputs()
        return self.snapshot()

    def simulate_vision(self, o_ring_count: int, confidence: float = 0.95) -> dict[str, Any]:
        self.require_record()
        ok = int(o_ring_count) == 2
        self.vision = {
            "status": "OK" if ok else "NG",
            "o_ring_count": int(o_ring_count),
            "confidence": round(float(confidence), 3),
        }
        self.current_record = self.storage.update_record(
            self.current_record_id,
            vision_status=self.vision["status"],
            o_ring_count=self.vision["o_ring_count"],
            alarm_code="" if ok else "VISION_NG",
            alarm_message="" if ok else "O 型圈数量不等于 2",
        )
        if ok:
            self.state = "preassemble"
            self.alarm = Alarm()
        else:
            self.alarm = Alarm("VISION_NG", "O 型圈数量不等于 2，禁止拧紧")
        self.storage.add_event(self.current_record_id, "vision.result", f"O型圈数量：{o_ring_count}，结果：{self.vision['status']}")
        self.write_plc_outputs()
        return self.snapshot()

    def plc_ready(self) -> bool:
        return self.plc.read_state().is_ready_for_tightening()

    def refresh_tightening_permission(self) -> bool:
        if self.state not in {"preassemble", "tightening"}:
            return False
        product_cfg = self.product_config()
        vision_ok = self.vision["status"] == "OK" or not product_cfg["enable_vision_interlock"]
        ready = vision_ok and self.plc_ready() and self.kilews.connected
        if ready and self.state != "tightening":
            self.state = "tightening"
            if not self.automation_enabled and isinstance(self.kilews, KilewsDevice):
                now = _time.monotonic()
                self._reset_tightening_tracking(now)
                self._automation_status["tightening_progress"] = "拧紧许可已满足，等待拧紧完成..."
                self._prime_tightening_baseline()
        return ready

    def simulate_tightening(self, bolt_no: int, torque_nm: float, angle_deg: float) -> dict[str, Any]:
        self.require_record()
        self.refresh_tightening_permission()
        if self.state != "tightening":
            self.alarm = Alarm("NO_PERMISSION", "拧紧许可未满足，请检查视觉、PLC和奇力速状态")
            self.write_plc_outputs()
            return self.snapshot()

        bolt_no = int(bolt_no)
        if bolt_no < 1 or bolt_no > len(self.bolts):
            raise ValueError("螺丝序号无效")
        result = self.evaluate_tightening(torque_nm, angle_deg)
        bolt = self.bolts[bolt_no - 1]
        bolt.torque_nm = round(float(torque_nm), 2)
        bolt.angle_deg = round(float(angle_deg), 2)
        bolt.result = result

        update_fields: dict[str, Any] = {
            f"bolt{bolt_no}_torque": bolt.torque_nm,
            f"bolt{bolt_no}_angle": bolt.angle_deg,
            f"bolt{bolt_no}_result": result,
        }
        self.current_record = self.storage.update_record(self.current_record_id, **update_fields)
        self.storage.add_event(
            self.current_record_id,
            "tightening.result",
            f"螺丝{bolt_no}: {bolt.torque_nm:.2f} Nm / {bolt.angle_deg:.2f}° / {result}",
        )
        self.finish_if_all_bolts_done()
        self.write_plc_outputs(current_bolt_no=bolt_no)
        return self.snapshot()

    def evaluate_tightening(self, torque_nm: float, angle_deg: float) -> str:
        product_cfg = self.product_config()
        torque_ok = float(product_cfg["torque_min_nm"]) <= float(torque_nm) <= float(product_cfg["torque_max_nm"])
        angle_ok = float(product_cfg["angle_min_deg"]) <= float(angle_deg) <= float(product_cfg["angle_max_deg"])
        return "OK" if torque_ok and angle_ok else "NG"

    def finish_if_all_bolts_done(self) -> None:
        if not self._all_bolts_have_results():
            return
        final = "OK" if all(bolt.result == "OK" for bolt in self.bolts) else "NG"
        if final == "NG":
            self.state = "ng_wait_rework"
            self.alarm = Alarm("PART_NG", "拧紧结果 NG，请在 PLC 侧选择返修/放行")
        else:
            self.state = "pending_scan" if self._qr_binding_required() else "complete"
            self.alarm = Alarm()
        self.current_record = self.storage.update_record(
            self.current_record_id,
            final_result=final,
            status=(
                "WAIT_QR"
                if final == "OK" and self._qr_binding_required()
                else ("COMPLETED" if final == "OK" else "NG_WAIT_REWORK")
            ),
            qr_bind_status="WAIT" if self._qr_binding_required() else "SKIPPED",
            completed_at=now_text(),
            alarm_code=self.alarm.code,
            alarm_message=self.alarm.message,
        )
        self.storage.add_event(self.current_record_id, "part.final", f"整件结果：{final}")

        if final == "OK" and self._qr_binding_required():
            self._trigger_scanner_start("manual_finish_ok")
        elif final == "OK":
            self._complete_without_scan("QR binding disabled -> manual complete")

    def set_rework_choice(self, choice: str) -> dict[str, Any]:
        self.require_record()
        if self.state != "ng_wait_rework":
            self.alarm = Alarm("REWORK_NOT_REQUIRED", "当前不是 NG 返修选择状态")
            return self.snapshot()
        normalized = choice.strip() or "返修"
        record = self.current_record or {}
        count = int(record.get("rework_count") or 0) + 1
        self.current_record = self.storage.update_record(
            self.current_record_id,
            rework_choice=normalized,
            rework_count=count,
            status="WAIT_QR" if self._qr_binding_required() else "COMPLETED",
            qr_bind_status="WAIT" if self._qr_binding_required() else "SKIPPED",
        )
        self.state = "pending_scan" if self._qr_binding_required() else "complete"
        self.alarm = Alarm()
        self.storage.add_event(self.current_record_id, "rework.choice", f"PLC返修选择：{normalized}")
        self.write_plc_outputs()
        if self._qr_binding_required():
            self._trigger_scanner_start("rework_release")
        else:
            self._complete_without_scan("QR binding disabled -> rework release complete")
        return self.snapshot()

    def skip_scan(self) -> dict[str, Any]:
        self.require_record()
        if self.state != "pending_scan":
            self.alarm = Alarm("SCAN_NOT_ALLOWED", "扫码跳过只允许在待扫码阶段执行")
            self.write_plc_outputs()
            return self.snapshot()
        self.current_record = self.storage.update_record(
            self.current_record_id,
            qr_bind_status="SKIPPED",
            status="COMPLETED",
            scanned_at=now_text(),
            alarm_code="",
            alarm_message="",
        )
        self.storage.add_event(self.current_record_id, "qr.skipped", "扫码已跳过")
        self.state = "complete"
        self.alarm = Alarm()
        if self.automation_enabled:
            self._signal_plc_scan_complete()
        else:
            self.write_plc_outputs()
        return self.snapshot()

    def scan_qr(self, qr_code: str) -> dict[str, Any]:
        self.require_record()
        code = qr_code.strip()
        self.last_qr = code
        if self.state != "pending_scan":
            self.alarm = Alarm("SCAN_NOT_ALLOWED", "扫码只允许在流程结束后执行")
            self.write_plc_outputs()
            return self.snapshot()
        product_cfg = self.product_config()
        rule = product_cfg["qr_rule"]
        reject_duplicate_qr = bool(product_cfg.get("reject_duplicate_qr", True))
        if not re.fullmatch(rule, code):
            self.current_record = self.storage.update_record(
                self.current_record_id,
                qr_bind_status="RULE_NG",
                alarm_code="QR_RULE_NG",
                alarm_message="二维码不符合当前规则",
            )
            self.alarm = Alarm("QR_RULE_NG", "二维码不符合当前规则")
            self.write_plc_outputs()
            self._trigger_scanner_start("qr_rule_ng_retry")
            return self.snapshot()
        try:
            self.current_record = self.storage.bind_qr(
                self.current_record_id,
                code,
                reject_duplicate=reject_duplicate_qr,
            )
        except ValueError as exc:
            if self.current_record_id is not None:
                latest = self.storage.get_record(self.current_record_id)
                if latest is not None:
                    self.current_record = latest
            self.alarm = Alarm("QR_DUP", str(exc))
            self.storage.add_event(self.current_record_id, "qr.duplicate", code)
            self.write_plc_outputs()
            self._trigger_scanner_start("qr_duplicate_retry")
            return self.snapshot()
        self.state = "complete"
        self.alarm = Alarm()
        # If automation active, signal PLC scan complete
        if self.automation_enabled:
            self._signal_plc_scan_complete()
        self.write_plc_outputs()
        return self.snapshot()

    def update_plc_mock(self, updates: dict[str, Any]) -> dict[str, Any]:
        self.plc.update_mock_inputs(updates)
        self.refresh_tightening_permission()
        self.write_plc_outputs()
        return self.snapshot()

    def attach_image(self, image_path: str) -> dict[str, Any]:
        self.require_record()
        self.current_record = self.storage.update_record(self.current_record_id, image_path=image_path)
        self.storage.add_event(self.current_record_id, "image.capture", image_path)
        return self.snapshot()

    # ------------------------------------------------------------------
    # PLC outputs
    # ------------------------------------------------------------------

    def write_plc_outputs(self, current_bolt_no: int | None = None) -> None:
        plc_state = self.plc.read_state()
        product_cfg = self.product_config()
        final_result = self.current_record.get("final_result") if self.current_record else ""
        qr_bind_status = self.current_record.get("qr_bind_status") if self.current_record else ""
        outputs: dict[str, Any] = {
            "pc_online": True,
            "vision_ok": self.vision["status"] == "OK",
            "allow_preassemble": self.state in {"preassemble", "vision_check_cover", "plc_handshake", "tightening", "tightening_wait", "tightening_eval", "pending_scan", "complete"},
            "allow_tightening": self.state in {"tightening", "tightening_wait"} and plc_state.is_ready_for_tightening(),
            "bolt1_ok": len(self.bolts) >= 1 and self.bolts[0].result == "OK",
            "bolt2_ok": len(self.bolts) >= 2 and self.bolts[1].result == "OK",
            "part_ok": self.current_record is not None and self.current_record.get("final_result") == "OK",
            "part_ng": self.current_record is not None and self.current_record.get("final_result") == "NG",
            "qr_bound": self.current_record is not None and self.current_record.get("qr_bind_status") == "BOUND",
            "wait_qr_binding": self.state == "pending_scan",
            "data_saved": self.current_record is not None and self.current_record.get("status") == "COMPLETED",
            "current_bolt_no": current_bolt_no or self.next_bolt_no(),
            "bolt1_torque_x100": self.scaled(self.bolts[0].torque_nm) if len(self.bolts) > 0 else 0,
            "bolt1_angle_x100": self.scaled(self.bolts[0].angle_deg) if len(self.bolts) > 0 else 0,
            "bolt2_torque_x100": self.scaled(self.bolts[1].torque_nm) if len(self.bolts) > 1 else 0,
            "bolt2_angle_x100": self.scaled(self.bolts[1].angle_deg) if len(self.bolts) > 1 else 0,
            "torque_target_x100": self.scaled(product_cfg.get("torque_target_nm")),
            "torque_min_x100": self.scaled(product_cfg.get("torque_min_nm")),
            "torque_max_x100": self.scaled(product_cfg.get("torque_max_nm")),
            "angle_target_x100": self.scaled(product_cfg.get("angle_target_deg")),
            "angle_min_x100": self.scaled(product_cfg.get("angle_min_deg")),
            "angle_max_x100": self.scaled(product_cfg.get("angle_max_deg")),
            "product_ready": self.state in {"plc_handshake", "tightening_wait", "tightening_eval", "pending_scan", "ng_wait_rework", "complete"},
            "tightening_ok": final_result == "OK",
            "tightening_ng": final_result == "NG",
            "scan_complete": self.state == "complete",
            "disable_scan": qr_bind_status == "SKIPPED",
        }
        self.plc.write_outputs(outputs)
        self.updated_at = now_text()

    def next_bolt_no(self) -> int:
        for bolt in self.bolts:
            if bolt.result == "WAIT":
                return bolt.bolt_no
        return len(self.bolts)

    def next_unrecorded_bolt_no(self) -> int:
        for bolt in self.bolts:
            if bolt.torque_nm is None or bolt.angle_deg is None:
                return bolt.bolt_no
        return self.next_bolt_no()

    def _hydrate_bolts_from_record(self) -> None:
        if not self.current_record:
            return
        for bolt in self.bolts:
            idx = bolt.bolt_no
            torque = self.current_record.get(f"bolt{idx}_torque")
            angle = self.current_record.get(f"bolt{idx}_angle")
            result = self.current_record.get(f"bolt{idx}_result")
            if torque is None and angle is None and not result:
                continue
            if bolt.torque_nm is None and torque is not None:
                bolt.torque_nm = round(float(torque), 2)
            if bolt.angle_deg is None and angle is not None:
                bolt.angle_deg = round(float(angle), 2)
            if bolt.result == "WAIT" and result:
                bolt.result = str(result)

    def _apply_live_kilews_result_fallback(self, now: float) -> None:
        if not isinstance(self.kilews, KilewsDevice):
            return
        if self.current_record_id is None:
            return
        if self.state not in {"tightening", "tightening_wait", "tightening_eval", "pending_scan", "complete"}:
            return
        result_code = int(self.kilews.result_code or 0)
        if result_code not in (4, 5, 6, 7, 8):
            return
        result_signature = (
            int(self.kilews.result_code or 0),
            int(self.kilews.torque_raw or 0),
            int(self.kilews.angle_raw or 0),
            int(self.kilews.tighten_time_ms or 0),
        )
        if result_signature == self._last_kilews_signature:
            return
        if self._tightening_baseline_signature is not None and result_signature == self._tightening_baseline_signature:
            return

        bolt_no = self.next_unrecorded_bolt_no()
        if not (1 <= bolt_no <= len(self.bolts)):
            return
        bolt = self.bolts[bolt_no - 1]
        torque = self.kilews._decode_torque(int(self.kilews.torque_raw or 0))
        angle = self.kilews._decode_angle(int(self.kilews.angle_raw or 0))
        result = "OK" if result_code in (4, 5, 6) else "NG"

        bolt.torque_nm = round(float(torque), 2)
        bolt.angle_deg = round(float(angle), 2)
        bolt.result = result
        self._last_kilews_signature = result_signature
        self._tightening_last_progress_at = now
        self.current_record = self.storage.update_record(
            self.current_record_id,
            **{
                f"bolt{bolt_no}_torque": bolt.torque_nm,
                f"bolt{bolt_no}_angle": bolt.angle_deg,
                f"bolt{bolt_no}_result": result,
            },
        )
        self.storage.add_event(
            self.current_record_id,
            "tightening.result.fallback",
            f"螺栓{bolt_no}: {bolt.torque_nm:.2f} Nm / {bolt.angle_deg:.1f}° / {result}",
        )

    @staticmethod
    def scaled(value: float | None) -> int:
        if value is None:
            return 0
        return int(round(float(value) * 100))

    def require_record(self) -> None:
        if self.current_record_id is None:
            raise ValueError("请先开始生产流程")

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        self.refresh_tightening_permission()
        now = _time.monotonic()
        if now - self._last_snapshot_output_at >= self._snapshot_output_interval_s:
            self.write_plc_outputs()
            self._last_snapshot_output_at = now
        # Update vision with latest inference (also works outside automation)
        if self.camera is not None:
            inference = self.camera.get_latest_inference()
            if inference:
                self.vision["detections"] = inference.get("detections", [])
                self.vision["o_ring_count"] = inference.get("o_ring_count", 0)
                self.vision["o_ring_ok"] = inference.get("o_ring_ok", False)
                self.vision["confidence"] = inference.get("confidence", 0.0)
        plc_state: PlcState = self.plc.read_state()
        if not self.automation_enabled:
            if self.state in {"tightening", "tightening_wait"}:
                self._poll_kilews_results(now, plc_state)
            if self.state == "tightening_eval":
                self._finalize_tightening()
        if self.current_record_id is not None:
            self.current_record = self.storage.get_record(self.current_record_id)
            self._hydrate_bolts_from_record()
            self._apply_live_kilews_result_fallback(now)
            self._hydrate_bolts_from_record()
        product_cfg = self.product_config()
        return {
            "state": self.state,
            "state_label": STATE_LABELS.get(self.state, self.state),
            "operator": self.operator,
            "shift": self.shift,
            "current_record": self.current_record,
            "vision": self.vision,
            "bolts": [bolt.to_dict() for bolt in self.bolts],
            "plc": plc_state.to_dict(),
            "pc_outputs": dict(self.plc.pc_outputs),
            "alarm": self.alarm.to_dict(),
            "last_qr": self.last_qr,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "kilews": self._kilews_snapshot(),
            "automation": dict(self._automation_status),
            "camera": dict(self.camera_status),
            "settings_summary": {
                "product_model": product_cfg["product_model"],
                "recipe_no": product_cfg["recipe_no"],
                "torque": f'{product_cfg["torque_min_nm"]:.2f}-{product_cfg["torque_max_nm"]:.2f} Nm',
                "angle": f'{product_cfg["angle_min_deg"]:.2f}-{product_cfg["angle_max_deg"]:.2f}°',
                "plc_timeout_ms": self.settings["plc"]["heartbeat_timeout_ms"],
            },
        }
