"""Lightweight visual identity check for CCTV streams.

Only rejects a candidate when OCR positively identifies a different CCTV
channel. Unknown OCR is non-fatal so transient OCR failures do not remove a
working source.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path


def _expected(channel_id: str) -> tuple[str, bool]:
    if channel_id == "cctv5plus":
        return "5", True
    return channel_id.replace("cctv", ""), False


def _detected(text: str) -> set[tuple[str, bool]]:
    low = text.lower().replace(" ", "")
    found: set[tuple[str, bool]] = set()
    for token in re.findall(r"cctv[-_]?([0-9]{1,2})(\+|plus|p)?", low):
        num, suffix = token
        found.add((num, bool(suffix)))
    return found


def identify_cctv(url: str, channel_id: str, timeout: int = 15) -> dict:
    """Grab one frame and OCR it; reject only explicit wrong CCTV branding."""
    if not channel_id.startswith("cctv"):
        return {"identity": "unknown", "ocr": ""}

    try:
        with tempfile.TemporaryDirectory() as tmp:
            frame = Path(tmp) / "frame.jpg"
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-rw_timeout", str(timeout * 1_000_000),
                "-i", url, "-frames:v", "1", "-q:v", "3", str(frame),
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout + 5, check=False,
            )
            if result.returncode != 0 or not frame.exists():
                return {"identity": "unknown", "ocr": ""}

            # Tesseract sees the channel logo much more reliably when the
            # upper-left quarter is inspected, while the full frame helps
            # when a relay moves the logo slightly.
            outputs = []
            for image in (frame,):
                p = subprocess.run(
                    ["tesseract", str(image), "stdout", "-l", "eng+chi_sim", "--psm", "11"],
                    capture_output=True, text=True,
                    timeout=8, check=False,
                )
                outputs.append(p.stdout or "")
            ocr = "\n".join(outputs)
    except (OSError, subprocess.TimeoutExpired):
        return {"identity": "unknown", "ocr": ""}

    expected_num, expected_plus = _expected(channel_id)
    detected = _detected(ocr)
    wrong = [
        (num, plus) for num, plus in detected
        if num != expected_num or plus != expected_plus
    ]
    if wrong:
        return {"identity": "wrong", "ocr": ocr[:1000], "detected": wrong}

    if any(num == expected_num and plus == expected_plus for num, plus in detected):
        return {"identity": "match", "ocr": ocr[:1000]}

    return {"identity": "unknown", "ocr": ocr[:1000]}
