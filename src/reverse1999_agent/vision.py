from __future__ import annotations

import hashlib
import io
import re

import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel


class OcrItem(BaseModel):
    text: str
    confidence: float
    center_x: int
    center_y: int


class OcrReader:
    """Lazy optional OCR. The rest of the agent still works when OCR is unavailable."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._engine = None

    def _get_engine(self):
        if not self.enabled:
            return None
        if self._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError:
                self.enabled = False
                return None
            self._engine = RapidOCR()
        return self._engine

    def read(self, image: Image.Image) -> list[OcrItem]:
        engine = self._get_engine()
        if engine is None:
            return []
        result, _elapsed = engine(np.asarray(image.convert("RGB")))
        items: list[OcrItem] = []
        for entry in result or []:
            box, text, confidence = entry
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            items.append(
                OcrItem(
                    text=str(text),
                    confidence=float(confidence),
                    center_x=round(sum(xs) / len(xs)),
                    center_y=round(sum(ys) / len(ys)),
                )
            )
        return items

    def read_region(
        self,
        image: Image.Image,
        box: tuple[int, int, int, int],
        scale: int = 2,
    ) -> list[OcrItem]:
        """OCR a small UI region at higher resolution and map centers to screen coordinates."""
        left, top, right, bottom = box
        crop = image.crop(box)
        if scale > 1:
            crop = crop.resize((crop.width * scale, crop.height * scale), Image.Resampling.LANCZOS)
        items = self.read(crop)
        return [
            item.model_copy(
                update={
                    "center_x": left + round(item.center_x / scale),
                    "center_y": top + round(item.center_y / scale),
                }
            )
            for item in items
        ]


def format_ocr(items: list[OcrItem], minimum_confidence: float = 0.55) -> str:
    visible = [
        f"{item.text} @({item.center_x},{item.center_y}) conf={item.confidence:.2f}"
        for item in items
        if item.confidence >= minimum_confidence
    ]
    return "\n".join(visible)


def deficient_ratios(items: list[OcrItem]) -> list[tuple[OcrItem, int, int]]:
    shortages: list[tuple[OcrItem, int, int]] = []
    for item in items:
        match = re.fullmatch(r"\s*(\d*)\s*/\s*(\d+)\s*", item.text)
        if not match:
            continue
        available_text, required_text = match.groups()
        available = int(available_text) if available_text else 0
        required = int(required_text)
        if available < required:
            shortages.append((item, available, required))
    return shortages


def orange_action_center(image: Image.Image, minimum_area: int = 5000) -> tuple[int, int] | None:
    """Locate a large orange action panel used by map-side-story overlays."""
    rgb = np.asarray(image.convert("RGB"))
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, np.array([3, 120, 120]), np.array([20, 255, 255]))
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    height, width = rgb.shape[:2]
    candidates: list[tuple[int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if (
            area >= minimum_area
            and width * 0.08 <= w <= width * 0.45
            and height * 0.04 <= h <= height * 0.22
            and 1.4 <= w / max(h, 1) <= 6.5
            and width * 0.35 <= x + w / 2 <= width * 0.9
            and height * 0.25 <= y + h / 2 <= height * 0.85
        ):
            candidates.append((area, round(x + w / 2), round(y + h / 2)))
    if not candidates:
        return None
    _area, center_x, center_y = max(candidates)
    return center_x, center_y


def image_digest(image: Image.Image) -> str:
    thumb = image.convert("L").resize((64, 64))
    return hashlib.sha256(thumb.tobytes()).hexdigest()


def screen_change_ratio(before: Image.Image, after: Image.Image) -> float:
    first = cv2.cvtColor(np.asarray(before.convert("RGB")), cv2.COLOR_RGB2GRAY)
    second = cv2.cvtColor(np.asarray(after.convert("RGB")), cv2.COLOR_RGB2GRAY)
    if first.shape != second.shape:
        return 1.0
    first = cv2.resize(first, (320, 180))
    second = cv2.resize(second, (320, 180))
    difference = cv2.absdiff(first, second)
    return float(np.mean(difference > 12))


def encode_jpeg(image: Image.Image, max_side: int = 1280, quality: int = 78) -> str:
    import base64

    converted = image.convert("RGB")
    converted.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    converted.save(buffer, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")
