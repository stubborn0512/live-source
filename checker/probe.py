"""FFprobe helpers for validating real media streams."""

from __future__ import annotations

import json
import subprocess
from typing import Any


def probe(url: str, timeout: int = 20) -> dict[str, Any] | None:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-rw_timeout", str(timeout * 1_000_000),
        "-select_streams", "v:0",
        "-show_entries",
        "stream=width,height,codec_name,bit_rate,r_frame_rate",
        "-of", "json",
        url,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    try:
        payload = json.loads(result.stdout)
        streams = payload.get("streams", [])
        return streams[0] if streams else None
    except (json.JSONDecodeError, IndexError):
        return None


def is_1080p(stream: dict[str, Any], min_width: int, min_height: int) -> bool:
    try:
        return (
            int(stream.get("width", 0)) >= min_width
            and int(stream.get("height", 0)) >= min_height
        )
    except (TypeError, ValueError):
        return False
