"""2-second stationary O-ring stability detector.

Tracks consecutive YOLO inference results to determine whether a product
with the correct number of O-rings is stationary for a minimum duration.
"""
from __future__ import annotations

from collections import deque
from typing import Any


class StabilityDetector:
    """Detects stable O-ring presence in YOLO inference stream.

    Algorithm:
    1. Each update() receives O-ring detections from YOLO
    2. Centroids are compared frame-to-frame using greedy nearest-neighbour
    3. If max displacement < position_threshold AND count == required_count
       for all frames within stable_duration_s → 'stable_ok'
    """

    def __init__(
        self,
        required_count: int = 2,
        stable_duration_s: float = 2.0,
        position_threshold_px: float = 30.0,
    ) -> None:
        self.required_count = required_count
        self.stable_duration_s = max(stable_duration_s, 0.1)
        self.position_threshold_px = max(position_threshold_px, 1.0)

        # Each entry: (timestamp_s, o_ring_count, [(cx, cy), ...])
        self._history: deque[tuple[float, int, list[tuple[float, float]]]] = deque()
        self._stable_since: float | None = None  # timestamp when stability began

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        timestamp_s: float,
        detections: list[dict[str, Any]],
    ) -> str:
        """Feed YOLO detections for this tick. Returns status string.

        Returns:
            'stable_ok'   – stationary with correct O-ring count for required duration
            'unstable'    – moving or insufficient history
            'wrong_count' – wrong number of O-rings detected
        """
        # Extract O-ring detections
        o_rings = [d for d in detections if d.get("class_name") in ("o_ring", "O_Ring")]
        count = len(o_rings)

        # Compute centroids
        centroids: list[tuple[float, float]] = []
        for det in o_rings:
            cx = float(det.get("cx", 0))
            cy = float(det.get("cy", 0))
            centroids.append((cx, cy))

        # Compute max displacement vs previous frame
        max_disp = float("inf")
        if self._history:
            prev_count, prev_centroids = self._history[-1][1], self._history[-1][2]
            if count == prev_count and count > 0:
                max_disp = self._max_displacement(prev_centroids, centroids)

        # Store frame
        self._history.append((timestamp_s, count, centroids))

        # Prune old entries (keep > 2× stable_duration for safety margin)
        cutoff = timestamp_s - self.stable_duration_s * 2.0
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

        # Check stability
        return self._evaluate(timestamp_s)

    def is_stable_ok(self) -> bool:
        """Quick check: are we in stable_ok state?"""
        return self._stable_since is not None

    def stability_progress(self, now_s: float) -> tuple[float, float]:
        """Return (elapsed_s, required_s) for UI progress bar."""
        if self._stable_since is None:
            # Find how long current stable streak has lasted (may be < required)
            if len(self._history) >= 2:
                window = self._get_window()
                if window:
                    elapsed = window[-1][0] - window[0][0]
                    return (elapsed, self.stable_duration_s)
            return (0.0, self.stable_duration_s)
        elapsed = now_s - self._stable_since
        return (min(elapsed, self.stable_duration_s), self.stable_duration_s)

    def reset(self) -> None:
        """Clear history for new product cycle."""
        self._history.clear()
        self._stable_since = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evaluate(self, now_s: float) -> str:
        window = self._get_window()
        if not window:
            self._stable_since = None
            return "unstable"

        # All frames in window must have correct count
        for _, cnt, _ in window:
            if cnt != self.required_count:
                self._stable_since = None
                return "wrong_count"

        # All adjacent pairs must be within position threshold
        for i in range(1, len(window)):
            _, prev_cnt, prev_c = window[i - 1]
            _, cur_cnt, cur_c = window[i]
            if prev_cnt == cur_cnt and prev_cnt > 0:
                disp = self._max_displacement(prev_c, cur_c)
                if disp > self.position_threshold_px:
                    self._stable_since = None
                    return "unstable"

        if self._stable_since is None:
            self._stable_since = now_s
        return "stable_ok"

    def _get_window(self) -> list[tuple[float, int, list[tuple[float, float]]]]:
        """Return frames within stable_duration_s from the most recent frame."""
        if not self._history:
            return []
        newest = self._history[-1][0]
        window: list[tuple[float, int, list[tuple[float, float]]]] = []
        for entry in self._history:
            if newest - entry[0] <= self.stable_duration_s + 0.05:  # small epsilon
                window.append(entry)
        return window

    @staticmethod
    def _max_displacement(
        prev: list[tuple[float, float]],
        cur: list[tuple[float, float]],
    ) -> float:
        """Greedy nearest-neighbour max displacement between two centroid sets."""
        if not prev or not cur:
            return float("inf")
        # Greedy pairing: for each current centroid, find nearest previous
        used = [False] * len(prev)
        max_d = 0.0
        for cx, cy in cur:
            best_d = float("inf")
            best_idx = -1
            for i, (px, py) in enumerate(prev):
                if used[i]:
                    continue
                d = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
                if d < best_d:
                    best_d = d
                    best_idx = i
            if best_idx >= 0:
                used[best_idx] = True
                max_d = max(max_d, best_d)
        return max_d
