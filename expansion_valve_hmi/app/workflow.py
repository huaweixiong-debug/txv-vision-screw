from __future__ import annotations

import re
import threading
import time as _time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .config import resolve_path
from .hardware.camera import MockCameraDevice, MvsCameraDevice
from .hardware.coverage_detector import CoverageDetector
from .hardware.kilews import (
    KilewsDevice,
    MockKilewsClient,
    ModbusClient,
    TighteningResult,
)
from .hardware.plc import MockPLCClient, PlcState
from .hardware.stability_detector import StabilityDetector
from .storage import ProductionStorage, now_text
from .vision import VisionInference


STATE_LABELS = {
    "idle": "待开始",
    "vision_wait_stable": "O型圈稳定性检测",
    "vision_check_cover": "膨胀阀覆盖检测",
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
        self.plc = MockPLCClient()
        self.camera: MockCameraDevice | MvsCameraDevice | None = None
        self._init_kilews(settings)
        self._init_camera(settings)
        self._init_plc(settings)
        self.state = "idle"
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
        if self.camera is not None:
            try:
                self.camera.disconnect()
            except Exception:
                pass
        try:
            self.camera = MvsCameraDevice(camera_ip, mvs_path)
            ok = self.camera.connect()
            if not ok:
                print("[Camera] MVS connect failed, using mock")
                self.camera = MockCameraDevice()
                self.camera.connect()
        except Exception as exc:
            print(f"[Camera] MVS init failed, using mock: {exc}")
            self.camera = MockCameraDevice()
            self.camera.connect()

        if vcfg.get("inference_enabled", True):
            try:
                vision_infer = VisionInference(
                    model_path=resolve_path(vcfg.get("model_path", "yolo26s.pt")),
                    confidence_threshold=float(vcfg.get("confidence_threshold", 0.3)),
                    iou_threshold=float(vcfg.get("iou_threshold", 0.3)),
                    dedup_overlap=float(vcfg.get("dedup_overlap", 0.7)),
                    yolo_classes=list(vcfg.get("yolo_classes", ["NG", "O_Ring_L", "O_Ring_S", "QR", "TXV"])),
                    inference_size=int(vcfg.get("inference_size", 1024)),
                )
                interval_s = float(vcfg.get("inference_interval_ms", 500)) / 1000.0
                self.camera.set_inference(vision_infer, interval_s)
                print(f"[Camera] YOLO inference wired (interval={interval_s}s)")
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

    def write_kilews_params(self, product_model: str | None = None) -> dict[str, Any]:
        product_cfg = self.product_config(product_model)
        if not isinstance(self.kilews, KilewsDevice):
            return {"ok": False, "error": "Mock 模式下不支持写入控制器"}
        speed = int(self.settings.get("kilews", {}).get("speed_rpm", 500))
        result = self.kilews.write_all_flow(
            torque_target=float(product_cfg.get("torque_target_nm", 4.5)),
            torque_min=float(product_cfg.get("torque_min_nm", 4.0)),
            torque_max=float(product_cfg.get("torque_max_nm", 5.0)),
            angle_target=float(product_cfg.get("angle_target_deg", 90.0)),
            angle_min=float(product_cfg.get("angle_min_deg", 70.0)),
            angle_max=float(product_cfg.get("angle_max_deg", 120.0)),
            speed=speed,
            target_type=2,
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
        tick = 0.25  # seconds between loop iterations

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

            if status == "stable_ok" and o_ring_ok:
                self._on_stability_ok()

        # ---- State: vision_check_cover ----
        elif self.state == "vision_check_cover":
            has_txv = any(d.get("class_name") == "TXV" for d in detections)
            if has_txv:
                elapsed = self._automation_status.get("txv_stable_since", 0)
                if elapsed == 0:
                    self._automation_status["txv_stable_since"] = now
                else:
                    duration = now - elapsed
                    self._automation_status["coverage_status"] = f"detecting {duration:.1f}s"
                    if duration >= 1.5:
                        self._on_valve_covered()
            else:
                self._automation_status["txv_stable_since"] = 0
                self._automation_status["coverage_status"] = "waiting"

        # ---- State: plc_handshake ----
        elif self.state == "plc_handshake":
            plc_state = self.plc.read_state()
            self._automation_status["coverage_status"] = "plc_waiting"

            if plc_state.m_plc_ready:
                self.state = "tightening_wait"
                self._automation_status["tightening_progress"] = "PLC 已就绪，等待拧紧完成..."
                self.storage.add_event(
                    self.current_record_id, "plc.handshake", "PLC 已就绪"
                )
                self.write_plc_outputs()
                # Reset bolt state + clear old Kilews results
                self.bolts = [BoltView(i + 1) for i in range(len(self.bolts))]
                if isinstance(self.kilews, KilewsDevice):
                    self.kilews.last_result_code = None

        # ---- State: tightening_wait ----
        elif self.state == "tightening_wait":
            # Poll Kilews for tightening results
            self._poll_kilews_results()

        # ---- State: tightening_eval ----
        elif self.state == "tightening_eval":
            self._finalize_tightening()

        # ---- State: pending_scan (automation: signal PLC) ----
        elif self.state == "pending_scan":
            # Check if QR has been scanned
            if self.current_record and self.current_record.get("qr_bind_status") == "BOUND":
                self._signal_plc_scan_complete()

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
            self.storage.update_record(
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
        """Called when expansion valve covers both O-rings."""
        self.state = "plc_handshake"
        self._automation_status["coverage_status"] = "plc_handshake"

        # Write M0.0 = 1 (product ready)
        self.plc.write_outputs({"product_ready": True})

        # Compute minimum IoA as coverage confidence
        ratios = self._automation_status.get("coverage_ratios", [])
        min_ioa = min((r.get("ioa", 0.0) for r in ratios), default=0.0) if ratios else 0.0

        self.storage.add_event(
            self.current_record_id, "vision.coverage_ok",
            f"膨胀阀覆盖检测通过 → PLC M0.0=1 (最低IoA={min_ioa:.3f})"
        )
        if self.current_record_id is not None:
            self.storage.update_record(
                self.current_record_id,
                expansion_valve_detected=1,
                plc_product_ready_sent=1,
                coverage_confidence=round(min_ioa, 4),
            )
        self._auto_capture("valve_covered")
        self.write_plc_outputs()
        print("[Automation] Valve coverage OK → PLC M0.0=1, waiting for PLC ready")

    def _poll_kilews_results(self) -> None:
        """Poll Kilews Modbus registers for tightening results.

        Reads only the result register block (4155-4164, 10 regs) instead of
        a full refresh to keep loop latency low (~1 MODBUS round-trip).
        """
        if not isinstance(self.kilews, KilewsDevice):
            self._mock_kilews_results()
            return

        try:
            # Lightweight read: only result registers
            vals = self.kilews.modbus.read_registers(4155, 10)
            if not vals or len(vals) < 10:
                return

            torque_raw = (vals[0] << 16) | vals[1]
            angle_raw = (vals[4] << 16) | vals[5]
            result_code = vals[9]

            # Update Kilews device state in-place
            self.kilews.torque_raw = torque_raw
            self.kilews.angle_raw = angle_raw
            self.kilews.result_code = result_code

            # Skip if same result_code already processed (stale data)
            last_code = getattr(self.kilews, "last_result_code", None)
            if result_code == last_code:
                return

            if result_code in (4, 5, 6, 7, 8):  # a result is available
                self.kilews.last_result_code = result_code
                torque = self.kilews._decode_torque(torque_raw)
                angle = self.kilews._decode_angle(angle_raw)
                result = "OK" if result_code == 4 else "NG"

                bolt_no = self.next_bolt_no()
                if 1 <= bolt_no <= len(self.bolts):
                    bolt = self.bolts[bolt_no - 1]
                    if bolt.result == "WAIT":
                        bolt.torque_nm = torque
                        bolt.angle_deg = angle
                        bolt.result = result
                        self._automation_status["tightening_progress"] = (
                            f"螺栓 {bolt_no}: {torque:.2f} Nm / {angle:.1f}° / {result}"
                        )
                        self.storage.add_event(
                            self.current_record_id,
                            "tightening.result",
                            f"螺栓{bolt_no}: {torque:.2f} Nm / {angle:.1f}° / {result}",
                        )
                        self.write_plc_outputs(current_bolt_no=bolt_no)

            # Check if all bolts done
            if all(b.result in {"OK", "NG"} for b in self.bolts):
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

        # Write M0.1 (1=OK, 0=NG)
        self.plc.write_outputs({"tightening_ok": (final == "OK")})

        if self.current_record_id is not None:
            self.storage.update_record(
                self.current_record_id,
                plc_tightening_ok_sent=1,
            )

        if final == "NG":
            self.state = "ng_wait_rework"
            self.alarm = Alarm("PART_NG", "拧紧结果 NG，请在 PLC 侧选择返修/放行")
        else:
            self.state = "pending_scan"
            self.alarm = Alarm()

        self.current_record = self.storage.update_record(
            self.current_record_id,
            final_result=final,
            status="WAIT_QR" if final == "OK" else "NG_WAIT_REWORK",
            qr_bind_status="WAIT",
            completed_at=now_text(),
            alarm_code=self.alarm.code,
            alarm_message=self.alarm.message,
        )
        self.storage.add_event(
            self.current_record_id, "part.final", f"整件结果：{final} → PLC M0.1={'1' if final == 'OK' else '0'}"
        )
        self._auto_capture("tightening_done")
        self.write_plc_outputs()
        print(f"[Automation] Tightening final: {final} → PLC M0.1={'1' if final == 'OK' else '0'}")

    def _signal_plc_scan_complete(self) -> None:
        """Write M0.2 = 1 to PLC after QR scan."""
        self.plc.write_outputs({"scan_complete": True})
        if self.current_record_id is not None:
            self.storage.update_record(
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
        if ready:
            self.state = "tightening"
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
        if not all(bolt.result in {"OK", "NG"} for bolt in self.bolts):
            return
        final = "OK" if all(bolt.result == "OK" for bolt in self.bolts) else "NG"
        if final == "NG":
            self.state = "ng_wait_rework"
            self.alarm = Alarm("PART_NG", "拧紧结果 NG，请在 PLC 侧选择返修/放行")
        else:
            self.state = "pending_scan"
            self.alarm = Alarm()
        self.current_record = self.storage.update_record(
            self.current_record_id,
            final_result=final,
            status="WAIT_QR" if final == "OK" else "NG_WAIT_REWORK",
            qr_bind_status="WAIT",
            completed_at=now_text(),
            alarm_code=self.alarm.code,
            alarm_message=self.alarm.message,
        )
        self.storage.add_event(self.current_record_id, "part.final", f"整件结果：{final}")

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
            status="WAIT_QR",
            qr_bind_status="WAIT",
        )
        self.state = "pending_scan"
        self.alarm = Alarm()
        self.storage.add_event(self.current_record_id, "rework.choice", f"PLC返修选择：{normalized}")
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
        if not re.fullmatch(rule, code):
            self.current_record = self.storage.update_record(
                self.current_record_id,
                qr_bind_status="RULE_NG",
                alarm_code="QR_RULE_NG",
                alarm_message="二维码不符合当前规则",
            )
            self.alarm = Alarm("QR_RULE_NG", "二维码不符合当前规则")
            self.write_plc_outputs()
            return self.snapshot()
        try:
            self.current_record = self.storage.bind_qr(self.current_record_id, code)
        except ValueError as exc:
            self.alarm = Alarm("QR_DUP", str(exc))
            self.write_plc_outputs()
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
            "data_saved": self.current_record is not None,
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
        }
        # M-bit automation signals
        if self.state == "plc_handshake":
            outputs["product_ready"] = True
        if self.state == "complete":
            outputs["scan_complete"] = True
        self.plc.write_outputs(outputs)
        self.updated_at = now_text()

    def next_bolt_no(self) -> int:
        for bolt in self.bolts:
            if bolt.result == "WAIT":
                return bolt.bolt_no
        return len(self.bolts)

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
        self.write_plc_outputs()
        # Update vision with latest inference (also works outside automation)
        if self.camera is not None:
            inference = self.camera.get_latest_inference()
            if inference:
                self.vision["detections"] = inference.get("detections", [])
                self.vision["o_ring_count"] = inference.get("o_ring_count", 0)
                self.vision["o_ring_ok"] = inference.get("o_ring_ok", False)
                self.vision["confidence"] = inference.get("confidence", 0.0)
        plc_state: PlcState = self.plc.read_state()
        if self.current_record_id is not None:
            self.current_record = self.storage.get_record(self.current_record_id)
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
            "kilews": self.kilews.status_dict(),
            "automation": dict(self._automation_status),
            "settings_summary": {
                "product_model": product_cfg["product_model"],
                "recipe_no": product_cfg["recipe_no"],
                "torque": f'{product_cfg["torque_min_nm"]:.2f}-{product_cfg["torque_max_nm"]:.2f} Nm',
                "angle": f'{product_cfg["angle_min_deg"]:.2f}-{product_cfg["angle_max_deg"]:.2f}°',
                "plc_timeout_ms": self.settings["plc"]["heartbeat_timeout_ms"],
            },
        }
