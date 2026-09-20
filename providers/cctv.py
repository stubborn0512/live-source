"""CCTV URL provider.

The official CCTV web player currently exposes the live HLS manifest through
its browser network requests. The workflow resolves those URLs with Chrome
and stores them in data/resolved.json for the probe/generator stage.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESOLVED = ROOT / "data" / "resolved.json"


def resolve(channel_id: str, timeout: int = 20) -> str | None:
    if not RESOLVED.exists():
        raise RuntimeError("official browser resolver did not produce data/resolved.json")
    try:
        data = json.loads(RESOLVED.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("data/resolved.json is invalid") from exc
    url = data.get(channel_id)
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        return url
    return None
