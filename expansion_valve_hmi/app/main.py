from __future__ import annotations

import argparse
import copy
import json
import mimetypes
import signal
import sys
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import BASE_DIR, load_settings, save_settings
from .hardware.camera import MockCameraDevice
from .hardware.kilews import KilewsDevice
from .hardware.plc import S7200SmartClient
from .hardware.scanner import ScannerTcpServer, SerialScanner
from .storage import ProductionStorage, today_text
from .vision import capture_frame, export_yolo_dataset
from .workflow import StationWorkflow


WEB_DIR = BASE_DIR / "web"


class AppContext:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.storage = ProductionStorage(self.settings["data"]["database_path"])
        self.workflow = StationWorkflow(self.settings, self.storage)
        self.scanner: ScannerTcpServer | SerialScanner | None = None
        self.last_scanner_scan_at = ""
        self._status_cache_payload: dict[str, Any] | None = None
        self._status_cache_at = 0.0
        self._status_cache_ttl_s = 0.25
        self.workflow.set_scanner_callbacks(self.scanner_trigger_start, self.scanner_trigger_stop)
        self._init_scanner()

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        self.settings = save_settings(deep_merge(self.settings, patch))
        self.workflow.reload_settings(self.settings)
        self.invalidate_status_cache()
        return self.settings

    def invalidate_status_cache(self) -> None:
        self._status_cache_payload = None
        self._status_cache_at = 0.0

    def get_status_payload(self) -> dict[str, Any]:
        now = time.monotonic()
        if (
            self._status_cache_payload is not None
            and now - self._status_cache_at < self._status_cache_ttl_s
        ):
            return copy.deepcopy(self._status_cache_payload)

        payload = self.workflow.snapshot()
        today = today_text()
        today_records = self.storage.list_records(limit=500, date=today, status="COMPLETED")
        payload["recent_records"] = today_records
        product = payload.get("settings_summary", {}).get("product_model", "")
        today_product = [r for r in today_records if r.get("product_model") == product]
        payload["today_stats"] = {
            "total": len(today_records),
            "product_total": len(today_product),
            "product_ok": len([r for r in today_product if r.get("final_result") == "OK"]),
            "product_model": product,
        }
        self._status_cache_payload = payload
        self._status_cache_at = now
        return copy.deepcopy(payload)

    # ------------------------------------------------------------------
    # Scanner
    # ------------------------------------------------------------------

    def _init_scanner(self) -> None:
        scfg = self.settings.get("scanner", {})
        mode = scfg.get("mode", "serial")
        try:
            if mode == "tcp_server":
                self.scanner = ScannerTcpServer(
                    host=scfg.get("host", "0.0.0.0"),
                    port=int(scfg.get("port", 9100)),
                    on_scan=self._on_scanner_scan,
                )
                self.scanner.start_background()
                print(f"[Scanner] TCP server listening on {scfg['host']}:{scfg['port']}")
            elif mode == "serial":
                self.scanner = SerialScanner(
                    com_port=scfg.get("com_port", "COM3"),
                    baudrate=int(scfg.get("baudrate", 115200)),
                    on_scan=self._on_scanner_scan,
                )
                self.scanner.start_background()
                # Note: connect() already prints success/failure inside start_background()
            else:
                self.scanner = None
                print(f"[Scanner] Unknown mode '{mode}', scanner disabled")
        except Exception as exc:
            print(f"[Scanner] init failed: {exc}")
            self.scanner = None

    def _stop_scanner(self) -> None:
        if self.scanner is None:
            return
        try:
            self.scanner.stop_background()
        except Exception as exc:
            print(f"[Scanner] stop error: {exc}")
        self.scanner = None

    def _on_scanner_scan(self, code: str) -> None:
        """Callback from scanner — always update last_qr for test visibility."""
        self.workflow.last_qr = code.strip()
        self.last_scanner_scan_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.invalidate_status_cache()
        try:
            self.workflow.scan_qr(code)
            print(f"[Scanner] QR scanned: {code[:20]}...")
        except Exception as exc:
            print(f"[Scanner] scan error: {exc}")

    def scanner_status(self) -> dict[str, Any]:
        scfg = self.settings.get("scanner", {})
        payload: dict[str, Any] = {
            "mode": scfg.get("mode", "serial"),
            "configured_port": scfg.get("com_port", "COM3"),
            "configured_baudrate": int(scfg.get("baudrate", 115200)),
            "connected": False,
            "last_qr": self.workflow.last_qr,
            "last_scan_at": self.last_scanner_scan_at,
            "available_ports": SerialScanner.available_ports(),
        }
        if isinstance(self.scanner, SerialScanner):
            payload.update(self.scanner.status_dict())
        elif isinstance(self.scanner, ScannerTcpServer):
            payload.update({
                "mode": "tcp_server",
                "connected": True,
                "host": scfg.get("host", "0.0.0.0"),
                "port": int(scfg.get("port", 9100)),
            })
        else:
            payload["last_error"] = "Scanner not initialized"
        return payload

    def scanner_trigger_start(self) -> dict[str, Any]:
        if self.scanner is None:
            print("[Scanner] trigger start: scanner is None, re-initializing...", flush=True)
            self._init_scanner()
        if not isinstance(self.scanner, SerialScanner):
            scanner_type = type(self.scanner).__name__ if self.scanner is not None else "None"
            raise RuntimeError(f"Scanner trigger is only available in serial mode (got: {scanner_type})")
        result = self.scanner.trigger_start()
        self.invalidate_status_cache()
        return result

    def scanner_trigger_stop(self) -> dict[str, Any]:
        if self.scanner is None:
            self._init_scanner()
        if not isinstance(self.scanner, SerialScanner):
            scanner_type = type(self.scanner).__name__ if self.scanner is not None else "None"
            raise RuntimeError(f"Scanner trigger is only available in serial mode (got: {scanner_type})")
        result = self.scanner.trigger_stop()
        self.invalidate_status_cache()
        return result

    def scanner_reconnect(self, com_port: str | None = None, baudrate: int | None = None) -> dict[str, Any]:
        scanner_cfg = dict(self.settings.get("scanner", {}))
        if com_port:
            scanner_cfg["com_port"] = str(com_port).strip()
        if baudrate is not None:
            scanner_cfg["baudrate"] = int(baudrate)
        self.settings = save_settings(deep_merge(self.settings, {"scanner": scanner_cfg}))
        self._stop_scanner()
        self._init_scanner()
        self.invalidate_status_cache()
        return self.scanner_status()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Graceful shutdown: stop automation, camera, scanner, PLC, kilews."""
        print("[Shutdown] Stopping all connections...")
        try:
            self.workflow.disable_automation()
        except Exception as exc:
            print(f"[Shutdown] automation stop error: {exc}")
        try:
            if self.workflow.camera:
                self.workflow.camera.disconnect()
                print("[Shutdown] Camera disconnected")
        except Exception as exc:
            print(f"[Shutdown] camera stop error: {exc}")
        if self.scanner is not None:
            try:
                self._stop_scanner()
                print("[Shutdown] Scanner stopped")
            except Exception as exc:
                print(f"[Shutdown] scanner stop error: {exc}")
        try:
            self.workflow.disconnect_kilews()
        except Exception as exc:
            print(f"[Shutdown] kilews stop error: {exc}")
        try:
            self.workflow.plc.disconnect()
        except Exception:
            pass


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class HmiRequestHandler(BaseHTTPRequestHandler):
    context: AppContext

    server_version = "ExpansionValveHMI/0.2"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {format % args}")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                self.json_response({"ok": True, "app": "expansion-valve-hmi"})
                return
            if parsed.path == "/api/vision/latest-frame":
                camera = self.context.workflow.camera
                if camera and hasattr(camera, "mark_stream_requested"):
                    camera.mark_stream_requested()
                jpeg = camera.get_latest_jpeg() if camera else None
                if jpeg:
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                    self.send_header("Content-Length", str(len(jpeg)))
                    self.end_headers()
                    self.wfile.write(jpeg)
                else:
                    self.error_response("Camera not ready", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            if parsed.path == "/api/camera/exposure":
                camera = self.context.workflow.camera
                if camera is None:
                    self.error_response("Camera not ready", HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                exposure_us = camera.get_exposure()
                self.json_response({
                    "exposure_us": exposure_us,
                    "exposure_label": f"{exposure_us:.0f} us" if exposure_us is not None else "N/A",
                    "is_mock": isinstance(camera, MockCameraDevice),
                })
                return
            if parsed.path == "/api/image":
                params = parse_qs(parsed.query)
                img_path = params.get("path", [""])[0]
                if not img_path or ".." in img_path:
                    self.error_response("Invalid path", HTTPStatus.BAD_REQUEST)
                    return
                fp = Path(img_path)
                if not fp.exists() or not fp.is_file():
                    self.error_response("Image not found", HTTPStatus.NOT_FOUND)
                    return
                content = fp.read_bytes()
                content_type = mimetypes.guess_type(fp.name)[0] or "image/jpeg"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(content)
                return
            if parsed.path == "/api/status":
                self.json_response(self.context.get_status_payload())
                return
            if parsed.path == "/api/settings":
                self.json_response(self.context.settings)
                return
            if parsed.path == "/api/scanner/status":
                self.json_response(self.context.scanner_status())
                return
            if parsed.path == "/api/automation/status":
                wf = self.context.workflow
                self.json_response({
                    "automation": wf._automation_status,
                    "enabled": wf.automation_enabled,
                    "state": wf.state,
                    "state_label": wf.snapshot().get("state_label", wf.state),
                })
                return
            if parsed.path == "/api/plc/status":
                wf = self.context.workflow
                plc = wf.plc
                is_real = isinstance(plc, S7200SmartClient)
                self.json_response({
                    "client_type": type(plc).__name__,
                    "connected": plc.connected if is_real else True,
                    "is_real": is_real,
                    "ip": plc.ip if is_real else "mock",
                    "state": plc.read_state().to_dict(),
                })
                return
            if parsed.path == "/api/records":
                query = parse_qs(parsed.query)
                records = self.context.storage.list_records(
                    limit=int(query.get("limit", ["100"])[0]),
                    keyword=query.get("keyword", [""])[0],
                    status=query.get("status", [""])[0],
                    product_model=query.get("product_model", [""])[0],
                    date_start=query.get("date_start", [""])[0],
                    date_end=query.get("date_end", [""])[0],
                )
                self.json_response({"records": records})
                return
            self.serve_static(parsed.path)
        except Exception as exc:
            self.error_response(str(exc))

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            body = self.read_json()
            self.context.invalidate_status_cache()
            if parsed.path == "/api/login":
                self.json_response(self.context.workflow.login(body.get("operator", ""), body.get("shift", "")))
                return
            if parsed.path == "/api/cycle/start":
                self.json_response(
                    self.context.workflow.start_cycle(
                        product_model=body.get("product_model"),
                        recipe_no=body.get("recipe_no"),
                    )
                )
                return
            if parsed.path == "/api/automation/start":
                self.context.workflow.enable_automation()
                self.json_response({
                    "ok": True,
                    "automation": self.context.workflow._automation_status,
                })
                return
            if parsed.path == "/api/automation/stop":
                self.context.workflow.disable_automation()
                self.json_response({
                    "ok": True,
                    "automation": self.context.workflow._automation_status,
                })
                return
            if parsed.path == "/api/plc/connect":
                wf = self.context.workflow
                plc = wf.plc
                if isinstance(plc, S7200SmartClient):
                    ok = plc.connect()
                    self.json_response({"ok": ok, "connected": plc.connected, "ip": plc.ip})
                else:
                    self.json_response({"ok": True, "connected": True, "ip": "mock", "note": "Mock mode"})
                return
            if parsed.path == "/api/plc/disconnect":
                self.context.workflow.plc.disconnect()
                self.json_response({"ok": True})
                return
            if parsed.path == "/api/vision/simulate":
                self.json_response(
                    self.context.workflow.simulate_vision(
                        o_ring_count=int(body.get("o_ring_count", 2)),
                        confidence=float(body.get("confidence", 0.95)),
                    )
                )
                return
            if parsed.path == "/api/tightening/simulate":
                self.json_response(
                    self.context.workflow.simulate_tightening(
                        bolt_no=int(body.get("bolt_no", 1)),
                        torque_nm=float(body.get("torque_nm", 4.5)),
                        angle_deg=float(body.get("angle_deg", 90.0)),
                    )
                )
                return
            if parsed.path == "/api/rework":
                self.json_response(self.context.workflow.set_rework_choice(body.get("choice", "返修")))
                return
            if parsed.path == "/api/scan":
                self.json_response(self.context.workflow.scan_qr(body.get("qr_code", "")))
                return
            if parsed.path == "/api/scan/skip":
                self.json_response(self.context.workflow.skip_scan())
                return
            if parsed.path == "/api/scanner/trigger/start":
                self.json_response(self.context.scanner_trigger_start())
                return
            if parsed.path == "/api/scanner/trigger/stop":
                self.json_response(self.context.scanner_trigger_stop())
                return
            if parsed.path == "/api/scanner/reconnect":
                self.json_response(
                    self.context.scanner_reconnect(
                        com_port=body.get("com_port"),
                        baudrate=body.get("baudrate"),
                    )
                )
                return
            if parsed.path == "/api/kilews/connect":
                ok = self.context.workflow._connect_kilews()
                self.json_response({
                    "ok": ok,
                    "connected": isinstance(self.context.workflow.kilews, KilewsDevice)
                                  and self.context.workflow.kilews.modbus.connected,
                    "ip": self.context.settings.get("kilews", {}).get("ip", ""),
                })
                return
            if parsed.path == "/api/kilews/disconnect":
                self.context.workflow.disconnect_kilews()
                self.json_response({"ok": True})
                return
            if parsed.path == "/api/kilews/write-params":
                product_model = body.get("product_model") or self.context.settings["station"]["active_product_model"]
                result = self.context.workflow.write_kilews_params(product_model)
                self.json_response(result)
                return
            if parsed.path == "/api/kilews/write-all":
                if not isinstance(self.context.workflow.kilews, KilewsDevice):
                    self.error_response("Mock 模式下不支持写入控制器")
                    return
                result = self.context.workflow.kilews.write_all_flow(
                    torque_target=float(body.get("torque_target_nm", 4.5)),
                    torque_min=float(body.get("torque_min_nm", 4.0)),
                    torque_max=float(body.get("torque_max_nm", 5.0)),
                    angle_target=float(body.get("angle_target_deg", 90.0)),
                    angle_min=float(body.get("angle_min_deg", 70.0)),
                    angle_max=float(body.get("angle_max_deg", 120.0)),
                    speed=int(body.get("speed_rpm", 500)),
                    target_type=int(body.get("target_type", 2)),
                )
                self.json_response(result)
                return
            if parsed.path == "/api/plc/mock":
                self.json_response(self.context.workflow.update_plc_mock(body))
                return
            if parsed.path == "/api/settings":
                self.json_response(self.context.update_settings(body))
                return
            if parsed.path == "/api/image/capture":
                product = body.get("product_model") or self.context.settings["station"]["active_product_model"]
                qr = body.get("qr_code", "")
                transform = body.get("transform") or {}
                path = capture_frame(self.context.workflow.camera, self.context.settings, product, qr, transform=transform)
                snapshot = None
                if self.context.workflow.current_record_id is not None:
                    snapshot = self.context.workflow.attach_image(str(path))
                self.json_response({"image_path": str(path), "snapshot": snapshot})
                return
            if parsed.path == "/api/datasets/export":
                product = body.get("product_model") or self.context.settings["station"]["active_product_model"]
                path = export_yolo_dataset(self.context.settings, product)
                self.json_response({"dataset_path": str(path)})
                return
            if parsed.path == "/api/shutdown":
                self.context.shutdown()
                self.json_response({"ok": True, "message": "All connections closed"})
                return
            if parsed.path == "/api/camera/connect":
                wf = self.context.workflow
                wf._init_camera(wf.settings)
                self.json_response({
                    "ok": bool(wf.camera_status.get("connected")),
                    "connected": bool(wf.camera_status.get("connected")),
                    "is_mock": bool(wf.camera_status.get("is_mock")),
                    "backend": wf.camera_status.get("backend", ""),
                    "camera_ip": wf.camera_status.get("camera_ip", ""),
                    "error": wf.camera_status.get("error", ""),
                })
                return
            if parsed.path == "/api/camera/disconnect":
                wf = self.context.workflow
                if wf.camera:
                    wf.camera.disconnect()
                self.json_response({"ok": True})
                return
            if parsed.path == "/api/camera/exposure":
                value_us = float(body.get("exposure_us", 10000))
                camera = self.context.workflow.camera
                if camera is None:
                    self.error_response("Camera not ready", HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                ok = camera.set_exposure(value_us)
                new_val = camera.get_exposure()
                if ok:
                    self.context.update_settings({
                        "vision": {"camera_exposure_us": new_val}
                    })
                self.json_response({
                    "ok": ok,
                    "exposure_us": new_val,
                    "exposure_label": f"{new_val:.0f} us" if new_val is not None else "N/A",
                })
                return
            if parsed.path == "/api/export/daily":
                export_root = self.context.settings["data"]["export_root"]
                path = self.context.storage.export_filtered(
                    export_root,
                    date_start=body.get("date_start") or "",
                    date_end=body.get("date_end") or "",
                    keyword=body.get("keyword") or "",
                    status=body.get("status") or "",
                )
                self.context.workflow.plc.write_outputs({"excel_export_ok": True, "excel_export_failed": False})
                self.json_response({"export_path": str(path)})
                return
            self.error_response("API not found", HTTPStatus.NOT_FOUND)
        except Exception as exc:
            if parsed.path == "/api/export/daily":
                self.context.workflow.plc.write_outputs({"excel_export_ok": False, "excel_export_failed": True})
            self.error_response(str(exc))

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def json_response(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def error_response(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self.json_response({"ok": False, "error": message}, status)

    def serve_static(self, raw_path: str) -> None:
        request_path = "/index.html" if raw_path in {"", "/"} else raw_path
        file_path = (WEB_DIR / request_path.lstrip("/")).resolve()
        web_root = WEB_DIR.resolve()
        if web_root not in file_path.parents and file_path != web_root:
            self.error_response("Invalid path", HTTPStatus.FORBIDDEN)
            return
        if not file_path.exists() or not file_path.is_file():
            self.error_response("File not found", HTTPStatus.NOT_FOUND)
            return
        content = file_path.read_bytes()
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or file_path.suffix in {".js", ".css"}:
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if file_path.suffix in {".html", ".js", ".css"}:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Expansion valve tightening HMI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8010, type=int)
    args = parser.parse_args()

    context = AppContext()
    HmiRequestHandler.context = context
    server = ThreadingHTTPServer((args.host, args.port), HmiRequestHandler)

    def _shutdown(signum: int, frame: Any) -> None:
        print(f"\n[信号 {signum}] 正在安全关闭...")
        context.shutdown()
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    url = f"http://{args.host}:{args.port}"
    print(f"膨胀阀拧紧防错追溯 HMI 已启动：{url}")
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止 HMI...")
    finally:
        context.shutdown()
        server.server_close()
