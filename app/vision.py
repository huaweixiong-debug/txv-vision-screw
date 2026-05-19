"""YOLO vision utilities — capture, dataset export, real-time inference"""
from __future__ import annotations

import base64
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .config import resolve_path


TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


# ---------------------------------------------------------------------------
# VisionInference — real-time YOLO on camera frames
# ---------------------------------------------------------------------------


class VisionInference:
    """Loads a YOLO model once and provides real-time inference on camera frames.

    Gracefully handles missing model file — inference becomes a no-op.
    """

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = 0.3,
        iou_threshold: float = 0.3,
        dedup_overlap: float = 0.7,
        yolo_classes: list[str] | None = None,
        inference_size: int = 416,
    ) -> None:
        self.model = None
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.dedup_overlap = dedup_overlap
        self.yolo_classes = yolo_classes or ["NG", "O_Ring_L", "O_Ring_S", "QR", "TXV"]
        self.inference_size = max(320, min(int(inference_size), 416))

        resolved = Path(model_path)
        if not resolved.is_absolute():
            resolved = resolve_path(model_path)
        self.model_path = resolved

        if resolved.exists():
            try:
                from ultralytics import YOLO
                self.model = YOLO(str(resolved))
                model_names = getattr(self.model, "names", None)
                if isinstance(model_names, dict) and model_names:
                    self.yolo_classes = [str(model_names[idx]) for idx in sorted(model_names)]
                elif isinstance(model_names, (list, tuple)) and model_names:
                    self.yolo_classes = [str(name) for name in model_names]
                print(f"[Vision] Model loaded: {resolved}")
                print(f"[Vision] Classes: {self.yolo_classes}")
            except Exception as exc:
                print(f"[Vision] Model load failed: {exc}")
        else:
            print(f"[Vision] Model not found: {resolved} — inference disabled")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def infer(self, bgr_image: np.ndarray) -> dict[str, Any]:
        """Run YOLO on a full-res BGR frame (e.g. 3072x2048).

        Returns:
            {"o_ring_count": int, "detections": list[dict], "confidence": float}
        """
        if self.model is None:
            return {"o_ring_count": 0, "detections": [], "confidence": 0.0}

        # Center-crop + resize to inference_size × inference_size
        h, w = bgr_image.shape[:2]
        crop_size = min(h, w)
        y_start = (h - crop_size) // 2
        x_start = (w - crop_size) // 2
        crop = bgr_image[y_start:y_start + crop_size, x_start:x_start + crop_size]

        import cv2
        input_img = cv2.resize(
            crop,
            (self.inference_size, self.inference_size),
            interpolation=cv2.INTER_AREA,
        )

        # Run inference with IoU threshold
        results = self.model(input_img, verbose=False, iou=self.iou_threshold, conf=self.confidence_threshold)

        detections: list[dict[str, Any]] = []
        max_conf = 0.0
        o_ring_count = 0
        scale = crop_size / self.inference_size  # map back to crop coords

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                if cls_id >= len(self.yolo_classes):
                    continue
                cls_name = self.yolo_classes[cls_id]
                normalized_name = self._normalize_class_name(cls_name)
                xywhn = box.xywhn[0].tolist()

                # Map from inference-size normalized → crop pixel → full-res pixel
                cx = xywhn[0] * self.inference_size * scale + x_start
                cy = xywhn[1] * self.inference_size * scale + y_start
                bw = xywhn[2] * self.inference_size * scale
                bh = xywhn[3] * self.inference_size * scale

                detections.append({
                    "class_id": cls_id,
                    "class_name": normalized_name,
                    "confidence": round(conf, 4),
                    "cx": round(cx, 1),
                    "cy": round(cy, 1),
                    "width": round(bw, 1),
                    "height": round(bh, 1),
                })
                max_conf = max(max_conf, conf)
                if normalized_name == "O_Ring":
                    o_ring_count += 1

        # Dedup: per-class keep non-overlapping
        detections = _dedup_per_class(detections, self.dedup_overlap)
        detections = _dedup_ng_vs_oring(detections, 0.001)

        # Rule: TXV and O_Ring never coexist in same frame
        # O_Ring phase: 2+ O_Ring → remove TXV
        # TXV phase: TXV present → remove O_Ring (valve covers them)
        temp_oring = sum(1 for d in detections if d["class_name"] == "O_Ring")
        temp_txv = sum(1 for d in detections if d["class_name"] == "TXV")
        if temp_oring >= 2:
            detections = [d for d in detections if d["class_name"] != "TXV"]
        elif temp_txv >= 1:
            detections = [d for d in detections if d["class_name"] != "O_Ring"]

        # O型圈合格: exactly 2 O_Ring, no NG
        o_ring_count = sum(1 for d in detections if d["class_name"] == "O_Ring")
        has_ng = any(d["class_name"] == "NG" for d in detections)
        o_ring_ok = (o_ring_count == 2 and not has_ng)

        return {
            "o_ring_count": o_ring_count,
            "o_ring_ok": o_ring_ok,
            "detections": detections,
            "confidence": round(max_conf, 4),
        }

    def draw_results(self, bgr_image: np.ndarray, results: dict[str, Any]) -> np.ndarray:
        """Draw bounding boxes — only the highest-confidence detection per class."""
        import cv2

        color_map = {
            "NG": (0, 0, 255),       # 红色
            "O_Ring": (0, 255, 0),    # 绿色
            "QR": (0, 255, 255),     # 黄色
            "TXV": (0, 255, 0),      # 绿色
        }

        # Draw ALL deduplicated detections (O_Ring may have up to 2)
        detections = results.get("detections", [])

        for det in detections:
            x1 = int(det["cx"] - det["width"] / 2)
            y1 = int(det["cy"] - det["height"] / 2)
            x2 = int(det["cx"] + det["width"] / 2)
            y2 = int(det["cy"] + det["height"] / 2)
            color = color_map.get(det["class_name"], (200, 200, 200))
            cv2.rectangle(bgr_image, (x1, y1), (x2, y2), color, 5)
            label = f"{det['class_name']} {det['confidence']:.2f}"
            cv2.putText(bgr_image, label, (x1, max(y1 - 6, 16)),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 3)

        # Overlay O-ring count top-left
        o_ring_count = results.get("o_ring_count", 0)
        status = "OK" if o_ring_count == 2 else f"NG ({o_ring_count})"
        text_color = (0, 220, 0) if o_ring_count == 2 else (0, 0, 220)
        cv2.putText(bgr_image, f"O-Rings: {status}",
                    (16, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, text_color, 2)

        return bgr_image

    def _normalize_class_name(self, cls_name: str) -> str:
        raw = str(cls_name or "").strip()
        key = raw.lower().replace("-", "_").replace(" ", "_")
        mapping = {
            "o_ring": "O_Ring",
            "oring": "O_Ring",
            "o_ring_l": "O_Ring",
            "o_ring_s": "O_Ring",
            "expansion_valve": "TXV",
            "valve": "TXV",
            "txv": "TXV",
            "qr": "QR",
            "qrcode": "QR",
            "ng": "NG",
            "bolt": "Bolt",
        }
        return mapping.get(key, raw)


def _iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax1 = a["cx"] - a["width"] / 2
    ay1 = a["cy"] - a["height"] / 2
    ax2 = a["cx"] + a["width"] / 2
    ay2 = a["cy"] + a["height"] / 2
    bx1 = b["cx"] - b["width"] / 2
    by1 = b["cy"] - b["height"] / 2
    bx2 = b["cx"] + b["width"] / 2
    by2 = b["cy"] + b["height"] / 2
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix1 >= ix2 or iy1 >= iy2:
        return 0.0
    iarea = (ix2 - ix1) * (iy2 - iy1)
    aarea = (ax2 - ax1) * (ay2 - ay1)
    barea = (bx2 - bx1) * (by2 - by1)
    return iarea / max(aarea + barea - iarea, 1.0)


def _dedup_per_class(
    detections: list[dict[str, Any]], overlap_threshold: float
) -> list[dict[str, Any]]:
    """Per-class: keep non-overlapping detections sorted by confidence.
    NG: up to 2, O_Ring: up to 2, QR: 1, TXV: 1."""
    max_per_class = {"NG": 2, "O_Ring": 2, "QR": 1, "TXV": 1}
    result: list[dict[str, Any]] = []
    handled_classes: set[str] = set()
    for cls_name, limit in max_per_class.items():
        handled_classes.add(cls_name)
        items = sorted(
            [d for d in detections if d["class_name"] == cls_name],
            key=lambda d: d["confidence"], reverse=True,
        )
        kept: list[dict[str, Any]] = []
        for item in items:
            if len(kept) >= limit:
                break
            if any(_iou(item, k) > overlap_threshold for k in kept):
                continue
            kept.append(item)
        result.extend(kept)
    extras = sorted(
        [d for d in detections if d["class_name"] not in handled_classes],
        key=lambda d: d["confidence"], reverse=True,
    )
    result.extend(extras)
    return result


def _dedup_ng_vs_oring(
    detections: list[dict[str, Any]], overlap_threshold: float
) -> list[dict[str, Any]]:
    """NG vs O_Ring overlap → keep highest confidence one."""
    remove: set[int] = set()
    for i, a in enumerate(detections):
        for j, b in enumerate(detections):
            if i >= j or i in remove or j in remove:
                continue
            pair = {a["class_name"], b["class_name"]}
            if pair == {"NG", "O_Ring"} and _iou(a, b) > overlap_threshold:
                if a["confidence"] >= b["confidence"]:
                    remove.add(j)
                else:
                    remove.add(i)
    return [d for idx, d in enumerate(detections) if idx not in remove]


# ---------------------------------------------------------------------------
# Image capture
# ---------------------------------------------------------------------------


def capture_frame(
    camera: Any,
    settings: dict[str, Any],
    product_model: str,
    qr_code: str = "",
    transform: dict[str, float] | None = None,
) -> Path:
    """Save the latest camera JPEG as a JPEG in the image directory.

    Filename format: {YYYYMMDD_HHMMSS}_{product_model}_{qr_code}.jpg
    Falls back to a tiny placeholder if the camera has no frame yet.

    If transform is provided, applies {zoom, rotate, panX, panY} to match
    the on-screen display before saving.
    """
    root = resolve_path(settings["data"]["image_root"])
    date_folder = datetime.now().strftime("%Y-%m-%d")
    folder = root / product_model / date_folder
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    safe_qr = (qr_code or "NOQR").replace("/", "_").replace("\\", "_")[:40]
    filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{product_model}_{safe_qr}.jpg"
    output = folder / filename

    jpeg_bytes = None
    if camera is not None:
        try:
            jpeg_bytes = camera.get_latest_raw_jpeg() or camera.get_latest_jpeg()
        except Exception:
            pass

    if jpeg_bytes and len(jpeg_bytes) > 200:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            if transform:
                img = _apply_transform(img, transform)
            cv2.imwrite(str(output), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            return output

    # Fallback placeholder
    output.write_bytes(TINY_PNG)
    return output


def _apply_transform(img: Any, t: dict[str, float]) -> Any:
    """Apply screen-space transform (zoom, rotate, pan) to an OpenCV image."""
    import cv2
    import numpy as np

    h, w = img.shape[:2]
    zoom = float(t.get("zoom", 1.0))
    rotate = float(t.get("rotate", 0.0))
    pan_x = int(t.get("panX", 0))
    pan_y = int(t.get("panY", 0))

    # 1. Zoom: crop center, then resize back
    if zoom != 1.0 and zoom > 0:
        new_w = int(w / zoom)
        new_h = int(h / zoom)
        x1 = max(0, (w - new_w) // 2 - pan_x)
        y1 = max(0, (h - new_h) // 2 - pan_y)
        x1 = min(x1, w - new_w)
        y1 = min(y1, h - new_h)
        img = img[y1:y1 + new_h, x1:x1 + new_w]
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_LINEAR)
    elif pan_x != 0 or pan_y != 0:
        # Pan without zoom: shift the image
        M = np.float32([[1, 0, -pan_x], [0, 1, -pan_y]])
        img = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))

    # 2. Rotate around center
    if rotate != 0:
        center = (w // 2, h // 2)
        rot_mat = cv2.getRotationMatrix2D(center, -rotate, 1.0)  # negative: match CSS direction
        img = cv2.warpAffine(img, rot_mat, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))

    return img


# ---------------------------------------------------------------------------
# Dataset export (unchanged logic)
# ---------------------------------------------------------------------------


def export_yolo_dataset(settings: dict[str, Any], product_model: str) -> Path:
    image_root = resolve_path(settings["data"]["image_root"]) / product_model
    dataset_root = resolve_path(settings["data"]["dataset_root"]) / product_model / datetime.now().strftime("%Y%m%d_%H%M%S")
    yolo_classes = settings["vision"].get("yolo_classes", ["o_ring", "expansion_valve", "bolt"])

    splits = {
        "train": 0.80,
        "valid": 0.10,
        "test": 0.10,
    }
    for split_name in splits:
        (dataset_root / split_name / "images").mkdir(parents=True, exist_ok=True)
        (dataset_root / split_name / "labels").mkdir(parents=True, exist_ok=True)

    images = sorted(image_root.rglob("*.png")) if image_root.exists() else []
    if not images:
        return _finish_dataset(dataset_root, yolo_classes, copied=0, auto_labeled=False)

    model_path = settings["vision"].get("model_path", "yolo26.pt")
    resolved_model = resolve_path(model_path)
    auto_labeled = resolved_model.exists()

    if auto_labeled:
        _run_inference_and_label(images, dataset_root, splits, yolo_classes, resolved_model)
    else:
        _copy_with_empty_labels(images, dataset_root, splits, yolo_classes)

    return _finish_dataset(dataset_root, yolo_classes, copied=len(images), auto_labeled=auto_labeled)


def _run_inference_and_label(
    images: list[Path],
    dataset_root: Path,
    splits: dict[str, float],
    yolo_classes: list[str],
    model_path: Path,
) -> None:
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    total = len(images)
    train_cut = int(total * splits["train"])
    valid_cut = train_cut + int(total * splits["valid"])

    for index, src in enumerate(images):
        if index < train_cut:
            bucket = "train"
        elif index < valid_cut:
            bucket = "valid"
        else:
            bucket = "test"

        target_img = dataset_root / bucket / "images" / src.name
        label_path = dataset_root / bucket / "labels" / f"{target_img.stem}.txt"
        shutil.copy2(src, target_img)

        results = model(str(src), verbose=False)
        lines: list[str] = []
        for result in results:
            if result.boxes is not None:
                for box in result.boxes:
                    cls_id = int(box.cls[0])
                    if cls_id < len(yolo_classes):
                        xywhn = box.xywhn[0].tolist()
                        lines.append(f"{cls_id} {xywhn[0]:.6f} {xywhn[1]:.6f} {xywhn[2]:.6f} {xywhn[3]:.6f}")
        label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _copy_with_empty_labels(
    images: list[Path],
    dataset_root: Path,
    splits: dict[str, float],
    yolo_classes: list[str],
) -> None:
    total = len(images)
    train_cut = int(total * splits["train"])
    valid_cut = train_cut + int(total * splits["valid"])

    for index, src in enumerate(images):
        if index < train_cut:
            bucket = "train"
        elif index < valid_cut:
            bucket = "valid"
        else:
            bucket = "test"

        target_img = dataset_root / bucket / "images" / src.name
        label_path = dataset_root / bucket / "labels" / f"{target_img.stem}.txt"
        shutil.copy2(src, target_img)
        label_path.write_text("", encoding="utf-8")


def _finish_dataset(dataset_root: Path, yolo_classes: list[str], copied: int, auto_labeled: bool) -> Path:
    yaml_text = "\n".join(
        [
            f"path: {dataset_root.as_posix()}",
            "train: train/images",
            "val: valid/images",
            "test: test/images",
            f"nc: {len(yolo_classes)}",
            "names:",
            *[f"  {index}: {name}" for index, name in enumerate(yolo_classes)],
            "",
        ]
    )
    (dataset_root / "data.yaml").write_text(yaml_text, encoding="utf-8")

    mode = "YOLO 推理自动标注" if auto_labeled else "空标注（模型文件未找到，请先训练模型）"
    (dataset_root / "README.txt").write_text(
        "本地 datasets 已生成。请在 Roboflow 完成标注后，再导出训练所需的最终数据版本。\n"
        f"本次复制图片数量：{copied}\n"
        f"标注模式：{mode}\n",
        encoding="utf-8",
    )
    return dataset_root
