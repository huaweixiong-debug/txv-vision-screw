"""QR Decoder — multi-scale, multi-preprocess, zxing + OpenCV fallback"""
from __future__ import annotations

import time
from collections import deque
from typing import Any

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Format validation — industrial serial numbers
# ---------------------------------------------------------------------------

# Accept: ~31-char uppercase alphanumeric strings
# e.g. FTHB11H1405520260330A001000282
_QR_PATTERN_MIN_LEN = 20
_QR_PATTERN_MAX_LEN = 50
_QR_PATTERN_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


def _valid_qr_data(text: str) -> str | None:
    """Return cleaned text if it looks like a valid serial number, else None."""
    text = text.strip()
    if _QR_PATTERN_MIN_LEN <= len(text) <= _QR_PATTERN_MAX_LEN:
        if set(text).issubset(_QR_PATTERN_CHARS):
            return text
    # Also accept shorter codes if they're purely alphanumeric
    if 10 <= len(text) <= _QR_PATTERN_MAX_LEN and set(text).issubset(_QR_PATTERN_CHARS):
        return text
    return None


# ---------------------------------------------------------------------------
# Preprocessing pipeline
# ---------------------------------------------------------------------------


def _preprocess(roi: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """Generate preprocessed variants of the ROI."""
    variants: list[tuple[str, np.ndarray]] = []

    if len(roi.shape) == 3:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    else:
        gray = roi.copy()

    variants.append(("gray", gray))

    # CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    variants.append(("clahe", clahe.apply(gray)))

    # OTSU
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(("otsu", otsu))

    # Adaptive threshold
    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    variants.append(("adaptive", adaptive))

    # Sharpen
    kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
    sharp = cv2.filter2D(gray, -1, kernel)
    variants.append(("sharpen", sharp))

    return variants


def _decode_zxing(image: np.ndarray) -> list[str]:
    """Decode all barcodes in image using zxing-cpp.

    zxing-cpp accepts numpy arrays directly and has built-in:
    - try_rotate (search all 4 orientations)
    - try_downscale (scan multiple resolutions)
    - try_invert (light-on-dark and dark-on-light)
    """
    try:
        import zxingcpp as zx
    except ImportError:
        return []

    results = []
    try:
        # zxing-cpp accepts numpy BGR/gray arrays directly
        barcodes = zx.read_barcodes(
            image,
            try_rotate=True,
            try_downscale=True,
            try_invert=True,
        )
        for b in barcodes:
            if b.text and b.text.strip():
                results.append(b.text.strip())
    except Exception:
        pass
    return results


def _decode_opencv(image: np.ndarray) -> list[str]:
    """Decode QR codes using OpenCV QRCodeDetector."""
    detector = cv2.QRCodeDetector()
    results = []
    try:
        data, _, _ = detector.detectAndDecode(image)
        if data and data.strip():
            results.append(data.strip())
    except Exception:
        pass
    return results


# ---------------------------------------------------------------------------
# Main decode — zxing with its own multi-scale + OpenCV fallback
# ---------------------------------------------------------------------------


def decode_qr(
    roi: np.ndarray,
    *,
    scales: list[int] | None = None,
    short_timeout: float = 0.5,
) -> str | None:
    """Decode QR code from ROI. Uses zxing-cpp (with built-in multi-scale/rotate/invert)
    first, then falls back to OpenCV QRCodeDetector with manual preprocessing."""
    if scales is None:
        scales = [1, 2, 4, 6, 8]
    h, w = roi.shape[:2]
    deadline = time.monotonic() + short_timeout

    # Fast path: zxing-cpp directly on the ROI (handles scale/rotate/invert internally)
    for text in _decode_zxing(roi):
        valid = _valid_qr_data(text)
        if valid:
            return valid

    # Manual multi-scale search for OpenCV and for cases zxing misses
    for scale in scales:
        if time.monotonic() > deadline:
            break
        if scale == 1:
            scaled = roi
        else:
            scaled = cv2.resize(roi, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)

        variants = _preprocess(scaled)
        for _label, var in variants:
            if time.monotonic() > deadline:
                break
            # zxing on preprocessed variant
            for text in _decode_zxing(var):
                valid = _valid_qr_data(text)
                if valid:
                    return valid
            # OpenCV fallback
            for text in _decode_opencv(var):
                valid = _valid_qr_data(text)
                if valid:
                    return valid

    return None


# ---------------------------------------------------------------------------
# Real-time buffered decode (for live camera feed)
# ---------------------------------------------------------------------------

class QrDecoder:
    """Buffered QR decoder for live streaming."""

    def __init__(self, buffer_size: int = 10) -> None:
        self._buffer: deque[tuple[np.ndarray, float]] = deque(maxlen=buffer_size)
        self._last_result: str | None = None
        self._last_result_time: float = 0.0
        self._cooldown: float = 2.0

    def feed(self, roi: np.ndarray) -> str | None:
        now = time.monotonic()
        if self._last_result and (now - self._last_result_time) < self._cooldown:
            return None
        score = _sharpness(roi)
        self._buffer.append((roi.copy(), score))
        frames = sorted(list(self._buffer), key=lambda x: x[1], reverse=True)[:3]
        for frame, _ in frames:
            result = decode_qr(frame, short_timeout=1.0)
            if result and result != self._last_result:
                self._last_result = result
                self._last_result_time = now
                return result
        return None

    def reset(self) -> None:
        self._buffer.clear()
        self._last_result = None


def _sharpness(image: np.ndarray) -> float:
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


# ---------------------------------------------------------------------------
# YOLO-based full-image decode
# ---------------------------------------------------------------------------


def decode_from_image(
    image: np.ndarray,
    model: Any,
    *,
    expand_ratio: float = 0.3,
) -> str | None:
    """YOLO-detect QR ROI -> crop + expand -> decode."""
    results = model.predict(image, conf=0.3, iou=0.3, verbose=False)
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes:
            cls_id = int(box.cls[0])
            if model.names.get(cls_id) != "QR":
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            pad_x = int((x2 - x1) * expand_ratio)
            pad_y = int((y2 - y1) * expand_ratio)
            x1 = max(0, x1 - pad_x)
            y1 = max(0, y1 - pad_y)
            x2 = min(image.shape[1], x2 + pad_x)
            y2 = min(image.shape[0], y2 + pad_y)
            roi = image[y1:y2, x1:x2]
            result = decode_qr(roi, short_timeout=2.0)
            if result:
                return result
    return None
