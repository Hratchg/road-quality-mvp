from __future__ import annotations
import hashlib
import random
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Detection:
    severity: str  # "moderate" or "severe"
    confidence: float  # 0.0-1.0


class PotholeDetector(Protocol):
    def detect(self, image_path: str) -> list[Detection]: ...


class StubDetector:
    """Deterministic fake detector for MVP testing."""

    def __init__(self, seed: int = 42):
        self.seed = seed

    def detect(self, image_path: str) -> list[Detection]:
        path_hash = int(hashlib.md5(image_path.encode()).hexdigest()[:8], 16)
        rng = random.Random(self.seed + path_hash)

        num_detections = rng.randint(0, 4)
        detections = []
        for _ in range(num_detections):
            score_severe = rng.random()
            score_moderate = rng.random()

            if score_severe >= 0.5:
                severity = "severe"
            elif score_moderate >= 0.5:
                severity = "moderate"
            else:
                continue  # Not reported

            confidence = max(score_severe, score_moderate)
            detections.append(Detection(severity=severity, confidence=round(confidence, 3)))

        return detections
