"""Stream health checks."""

from __future__ import annotations

import time
from typing import Any

from .probe import is_1080p, probe


def check(
    url: str,
    timeout: int,
    min_width: int,
    min_height: int,
) -> dict[str, Any]:
    started = time.monotonic()
    stream = probe(url, timeout=timeout)
    elapsed = round(time.monotonic() - started, 2)

    if not stream:
        return {
            "ok": False,
            "1080p": False,
            "response_seconds": elapsed,
        }

    return {
        "ok": True,
        "1080p": is_1080p(stream, min_width, min_height),
        "response_seconds": elapsed,
        "width": stream.get("width"),
        "height": stream.get("height"),
        "codec": stream.get("codec_name"),
        "bit_rate": stream.get("bit_rate"),
        "fps": stream.get("r_frame_rate"),
    }
