"""Expansion valve coverage detector.

After O-ring stability is confirmed, checks whether the expansion valve
fully covers both O-rings based on YOLO bounding-box overlap.
"""
from __future__ import annotations

from typing import Any


class CoverageDetector:
    """Detects expansion valve coverage over O-rings.

    Uses Intersection-over-Area (IoA): intersection_area / o_ring_area.
    All O-rings must achieve IoA >= threshold to be considered "covered".
    """

    def __init__(self, coverage_ratio_threshold: float = 0.85) -> None:
        self.coverage_ratio_threshold = max(0.0, min(coverage_ratio_threshold, 1.0))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, detections: list[dict[str, Any]]) -> bool:
        """Return True if expansion valve covers all O-rings.

        Args:
            detections: list of YOLO detection dicts, each with:
                class_name, cx, cy, width, height
        """
        o_rings = [d for d in detections if d.get("class_name") in ("o_ring", "O_Ring")]
        valves = [d for d in detections if d.get("class_name") == "TXV"]

        if not o_rings:
            return False
        if not valves:
            return False

        # Use the largest expansion valve bbox (primary valve)
        valve_bbox = self._largest_bbox(valves)

        for o_ring in o_rings:
            o_bbox = self._to_xyxy(o_ring)
            overlap = self._intersection_area(valve_bbox, o_bbox)
            o_area = self._bbox_area(o_bbox)
            if o_area <= 0:
                return False
            ioa = overlap / o_area
            if ioa < self.coverage_ratio_threshold:
                return False

        return True

    def coverage_ratios(
        self, detections: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Return per-O-ring coverage ratios for debugging / display.

        Returns list of {cx, cy, ioa, covered}.
        """
        o_rings = [d for d in detections if d.get("class_name") in ("o_ring", "O_Ring")]
        valves = [d for d in detections if d.get("class_name") == "TXV"]

        if not o_rings or not valves:
            return []

        valve_bbox = self._largest_bbox(valves)
        results: list[dict[str, Any]] = []
        for o_ring in o_rings:
            o_bbox = self._to_xyxy(o_ring)
            overlap = self._intersection_area(valve_bbox, o_bbox)
            o_area = self._bbox_area(o_bbox)
            ioa = overlap / o_area if o_area > 0 else 0.0
            results.append({
                "cx": o_ring.get("cx", 0),
                "cy": o_ring.get("cy", 0),
                "ioa": round(ioa, 4),
                "covered": ioa >= self.coverage_ratio_threshold,
            })
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_xyxy(det: dict[str, Any]) -> tuple[float, float, float, float]:
        """Convert center-wh detection to (x1, y1, x2, y2)."""
        cx = float(det.get("cx", 0))
        cy = float(det.get("cy", 0))
        w = float(det.get("width", 0))
        h = float(det.get("height", 0))
        return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

    @staticmethod
    def _bbox_area(bbox: tuple[float, float, float, float]) -> float:
        x1, y1, x2, y2 = bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    @staticmethod
    def _largest_bbox(
        dets: list[dict[str, Any]],
    ) -> tuple[float, float, float, float]:
        """Return the largest bbox among the detections."""
        best_area = -1.0
        best_bbox = (0.0, 0.0, 0.0, 0.0)
        for det in dets:
            bbox = CoverageDetector._to_xyxy(det)
            area = CoverageDetector._bbox_area(bbox)
            if area > best_area:
                best_area = area
                best_bbox = bbox
        return best_bbox

    @staticmethod
    def _intersection_area(
        a: tuple[float, float, float, float],
        b: tuple[float, float, float, float],
    ) -> float:
        x_overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        y_overlap = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        return x_overlap * y_overlap
