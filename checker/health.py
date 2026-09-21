"""Stream health checks: media validation, resolution, latency and freeze detection."""

from __future__ import annotations

import subprocess
import time
from typing import Any

from .probe import is_1080p, probe


def _is_static_stream(
    url: str,
    duration_seconds: int = 6,
    freeze_seconds: int = 4,
    noise: float = 0.001,
    timeout: int = 15,
) -> bool | None:
    """Return True for a frozen/static picture, False for moving video.

    None means the secondary static check itself timed out/failed; that is not
    treated as a bad stream so transient ffmpeg failures do not delete sources.
    """
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-i", url,
        "-t", str(duration_seconds),
        "-vf", f"freezedetect=n={noise}:d={freeze_seconds}",
        "-an",
        "-f", "null",
        "-",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    # freezedetect writes freeze_start to stderr. A non-zero ffmpeg exit can
    # still happen after enough frames were inspected, so only the freeze
    # marker is authoritative for this secondary test.
    return "freeze_start" in result.stderr


def check_static(
    url: str,
    duration_seconds: int = 6,
    freeze_seconds: int = 4,
) -> bool | None:
    """Run only the secondary freeze/static-frame test."""
    return _is_static_stream(
        url,
        duration_seconds=duration_seconds,
        freeze_seconds=freeze_seconds,
        timeout=max(15, duration_seconds + 8),
    )


def check(
    url: str,
    timeout: int,
    min_width: int,
    min_height: int,
    static_check: bool = False,
    static_duration: int = 6,
    freeze_seconds: int = 4,
) -> dict[str, Any]:
    started = time.monotonic()
    stream = probe(url, timeout=timeout)
    elapsed = round(time.monotonic() - started, 2)

    if not stream:
        return {
            "ok": False,
            "1080p": False,
            "response_seconds": elapsed,
            "static": None,
        }

    width = stream.get("width")
    height = stream.get("height")
    is_hd = is_1080p(stream, min_width, min_height)

    static = None
    if static_check and is_hd:
        static = _is_static_stream(
            url,
            duration_seconds=static_duration,
            freeze_seconds=freeze_seconds,
            timeout=max(15, static_duration + 8),
        )
        if static is True:
            return {
                "ok": False,
                "1080p": False,
                "response_seconds": elapsed,
                "width": width,
                "height": height,
                "codec": stream.get("codec_name"),
                "bit_rate": stream.get("bit_rate"),
                "fps": stream.get("r_frame_rate"),
                "static": True,
            }

    return {
        "ok": True,
        "1080p": is_hd,
        "response_seconds": elapsed,
        "width": width,
        "height": height,
        "codec": stream.get("codec_name"),
        "bit_rate": stream.get("bit_rate"),
        "fps": stream.get("r_frame_rate"),
        "static": static,
    }
