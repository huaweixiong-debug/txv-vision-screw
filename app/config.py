from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = BASE_DIR / "runtime"
DATA_DIR = BASE_DIR / "data"
DEFAULT_SETTINGS_PATH = BASE_DIR / "config" / "default_settings.json"
RUNTIME_SETTINGS_PATH = RUNTIME_DIR / "settings.json"
MAX_PRODUCTS = 255
MAX_PERSONNEL = 255


DEFAULT_PRODUCT: dict[str, Any] = {
    "enabled": True,
    "product_model": "HB11",
    "recipe_no": 1,
    "bolt_count": 2,
    "torque_target_nm": 4.50,
    "torque_min_nm": 4.00,
    "torque_max_nm": 5.00,
    "angle_target_deg": 90.00,
    "angle_min_deg": 70.00,
    "angle_max_deg": 120.00,
    "qr_rule": "^[A-Za-z0-9_.-]{6,80}$",
    "enable_vision_interlock": True,
    "enable_qr_binding": True,
    "reject_duplicate_qr": True,
}


DEFAULT_PERSON: dict[str, Any] = {
    "enabled": True,
    "employee_id": "OP001",
    "name": "默认操作员",
    "role": "操作员",
    "shift": "白班",
}


DEFAULT_SETTINGS: dict[str, Any] = {
    "station": {
        "station_id": "ST01",
        "line_name": "膨胀阀自动装配",
        "product_models": ["HB11", "E22H", "E211"],
        "active_product_model": "HB11",
        "active_recipe_no": 1,
    },
    "auth": {
        "operator_login_required": True,
        "default_operator": "OP001",
        "default_shift": "白班",
        "roles": ["管理员", "工艺员", "操作员"],
    },
    "recipe": {
        "bolt_count": 2,
        "torque_target_nm": 4.50,
        "torque_min_nm": 4.00,
        "torque_max_nm": 5.00,
        "angle_target_deg": 90.00,
        "angle_min_deg": 70.00,
        "angle_max_deg": 120.00,
        "qr_rule": "^[A-Za-z0-9_.-]{6,80}$",
        "enable_vision_interlock": True,
        "enable_qr_binding": True,
        "reject_duplicate_qr": True,
    },
    "products": [
        {
            **DEFAULT_PRODUCT,
            "product_model": "HB11",
            "recipe_no": 1,
        },
        {
            **DEFAULT_PRODUCT,
            "product_model": "E22H",
            "recipe_no": 2,
        },
        {
            **DEFAULT_PRODUCT,
            "product_model": "E211",
            "recipe_no": 3,
        },
    ],
    "personnel": [
        DEFAULT_PERSON,
    ],
    "vision": {
        "model_path": "D:\\Camera Screw Project\\yolo26s.pt",
        "model_version": "yolo26s.pt",
        "camera_ip": "192.168.0.111",
        "mvs_path": "C:/Program Files (x86)/MVS/Development/Samples/Python/MvImport",
        "confidence_threshold": 0.20,
        "iou_threshold": 0.30,
        "dedup_overlap": 0.70,
        "capture_mode": "manual",
        "yolo_classes": ["o_ring", "expansion_valve", "bolt"],
        "inference_enabled": True,
        "inference_interval_ms": 250,
        "inference_size": 640,
        "auto_capture_enabled": True,
        "camera_exposure_us": 10000,
    },
    "plc": {
        "enabled": True,
        "ip": "192.168.0.10",
        "port": 102,
        "rack": 0,
        "slot": 1,
        "timeout": 2.0,
        "reconnect_interval_s": 5.0,
        "auto_connect": True,
        "model": "S7-200 SMART 6ES7288-1SR20-0AA1",
        "area": "V",
        "heartbeat_timeout_ms": 1000,
        "address_table_version": "v0.6",
    },
    "automation": {
        "enabled": False,
        "stability_duration_s": 1.5,
        "stability_position_threshold_px": 30,
        "coverage_ratio_threshold": 0.85,
        "tightening_poll_interval_ms": 300,
        "tightening_timeout_s": 30.0,
    },
    "kilews": {
        "enabled": False,
        "ip": "192.168.3.10",
        "port": 502,
        "unit_id": 1,
        "auto_connect": True,
        "speed_rpm": 500,
    },
    "scanner": {
        "mode": "serial",
        "host": "0.0.0.0",
        "port": 9100,
        "com_port": "COM3",
        "baudrate": 115200,
        "terminator": "\\r\\n",
    },
    "data": {
        "database_path": str(RUNTIME_DIR / "production.db"),
        "export_root": "D:\\膨胀阀装配数据",
        "image_root": str(DATA_DIR / "images"),
        "dataset_root": str(DATA_DIR / "datasets"),
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_product(raw: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    base = copy.deepcopy(fallback or DEFAULT_PRODUCT)
    product = deep_merge(base, raw)
    product["product_model"] = str(product.get("product_model") or "未命名").strip()[:64]
    product["recipe_no"] = int(product.get("recipe_no") or 1)
    product["bolt_count"] = max(1, min(int(product.get("bolt_count") or 2), 2))
    product["kilews_job_no"] = int(product.get("kilews_job_no") or 0)
    for key in [
        "torque_target_nm",
        "torque_min_nm",
        "torque_max_nm",
        "angle_target_deg",
        "angle_min_deg",
        "angle_max_deg",
    ]:
        product[key] = round(float(product.get(key) or 0), 2)
    product["qr_rule"] = str(product.get("qr_rule") or DEFAULT_PRODUCT["qr_rule"])
    for key in ["enabled", "enable_vision_interlock", "enable_qr_binding", "reject_duplicate_qr"]:
        product[key] = bool(product.get(key))
    return product


def normalize_person(raw: dict[str, Any]) -> dict[str, Any]:
    person = deep_merge(DEFAULT_PERSON, raw)
    person["employee_id"] = str(person.get("employee_id") or "").strip()[:32]
    person["name"] = str(person.get("name") or person["employee_id"] or "未命名").strip()[:64]
    person["role"] = str(person.get("role") or "操作员").strip()[:32]
    person["shift"] = str(person.get("shift") or "白班").strip()[:32]
    person["enabled"] = bool(person.get("enabled"))
    return person


def normalize_settings(settings: dict[str, Any]) -> dict[str, Any]:
    recipe = deep_merge(DEFAULT_SETTINGS["recipe"], settings.get("recipe", {}))
    raw_products = settings.get("products") or []
    if not raw_products:
        raw_products = [
            {
                **recipe,
                "product_model": model,
                "recipe_no": index + 1,
            }
            for index, model in enumerate(settings.get("station", {}).get("product_models", ["HB11"]))
        ]

    products: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_product in raw_products[:MAX_PRODUCTS]:
        product = normalize_product(raw_product, recipe)
        if not product["product_model"] or product["product_model"] in seen:
            continue
        seen.add(product["product_model"])
        products.append(product)
    if not products:
        products.append(normalize_product(DEFAULT_PRODUCT, recipe))
    settings["products"] = products

    # Auto-assign Kilews job numbers for new products
    used_job_nos = {p["kilews_job_no"] for p in products if p.get("kilews_job_no", 0) > 0}
    next_job_no = 1
    for p in products:
        if p.get("kilews_job_no", 0) == 0:
            while next_job_no in used_job_nos:
                next_job_no += 1
            p["kilews_job_no"] = next_job_no
            used_job_nos.add(next_job_no)

    raw_personnel = settings.get("personnel") or [DEFAULT_PERSON]
    personnel: list[dict[str, Any]] = []
    seen_people: set[str] = set()
    for raw_person in raw_personnel[:MAX_PERSONNEL]:
        person = normalize_person(raw_person)
        if not person["employee_id"] or person["employee_id"] in seen_people:
            continue
        seen_people.add(person["employee_id"])
        personnel.append(person)
    if not personnel:
        personnel.append(normalize_person(DEFAULT_PERSON))
    settings["personnel"] = personnel

    enabled_models = [item["product_model"] for item in products if item.get("enabled")]
    if not enabled_models:
        enabled_models = [products[0]["product_model"]]
    settings["station"]["product_models"] = enabled_models
    if settings["station"].get("active_product_model") not in enabled_models:
        settings["station"]["active_product_model"] = enabled_models[0]

    active_product = next(
        (item for item in products if item["product_model"] == settings["station"]["active_product_model"]),
        products[0],
    )
    settings["station"]["active_recipe_no"] = int(active_product["recipe_no"])
    settings["recipe"] = {
        key: active_product[key]
        for key in [
            "bolt_count",
            "torque_target_nm",
            "torque_min_nm",
            "torque_max_nm",
            "angle_target_deg",
            "angle_min_deg",
            "angle_max_deg",
            "qr_rule",
            "enable_vision_interlock",
            "enable_qr_binding",
            "reject_duplicate_qr",
        ]
    }

    if not settings["auth"].get("default_operator"):
        settings["auth"]["default_operator"] = personnel[0]["employee_id"]
    if not settings["auth"].get("default_shift"):
        settings["auth"]["default_shift"] = personnel[0]["shift"]
    return settings


def ensure_default_config() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DEFAULT_SETTINGS_PATH.exists():
        DEFAULT_SETTINGS_PATH.write_text(
            json.dumps(DEFAULT_SETTINGS, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_settings() -> dict[str, Any]:
    ensure_default_config()
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    if DEFAULT_SETTINGS_PATH.exists():
        settings = deep_merge(settings, json.loads(DEFAULT_SETTINGS_PATH.read_text(encoding="utf-8")))
    if RUNTIME_SETTINGS_PATH.exists():
        settings = deep_merge(settings, json.loads(RUNTIME_SETTINGS_PATH.read_text(encoding="utf-8")))
    return normalize_settings(settings)


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    ensure_default_config()
    merged = normalize_settings(deep_merge(DEFAULT_SETTINGS, settings))
    RUNTIME_SETTINGS_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return merged


def resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return BASE_DIR / path
