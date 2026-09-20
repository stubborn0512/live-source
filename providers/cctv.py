"""Resolve CCTV streams from public providers, then let ffprobe decide quality."""
from __future__ import annotations
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
RESOLVED = ROOT / "data" / "resolved.json"

GOODIPTV = {
    "cctv1": "https://live.goodiptv.club/api/bestv.php?id=cctv1hd8m/8000000",
    "cctv2": "https://live.goodiptv.club/api/bestv.php?id=cctv2hd8m/8000000",
    "cctv3": "https://live.goodiptv.club/api/bestv.php?id=cctv38m/8000000",
    "cctv4": "https://live.goodiptv.club/api/bestv.php?id=cctv4hd8m/8000000",
    "cctv5": "https://live.goodiptv.club/api/bestv.php?id=cctv58m/8000000",
    "cctv5plus": "https://live.goodiptv.club/api/bestv.php?id=cctv5phd8m/8000000",
    "cctv6": "https://live.goodiptv.club/api/bestv.php?id=cctv6hd8m/8000000",
    "cctv7": "https://live.goodiptv.club/api/bestv.php?id=cctv7hd8m/8000000",
    "cctv8": "https://live.goodiptv.club/api/bestv.php?id=cctv8hd8m/8000000",
    "cctv9": "https://live.goodiptv.club/api/bestv.php?id=cctv9hd8m/8000000",
    "cctv10": "https://live.goodiptv.club/api/bestv.php?id=cctv10hd8m/8000000",
    "cctv11": "https://live.goodiptv.club/api/bestv.php?id=cctv11hd8m/8000000",
    "cctv12": "https://live.goodiptv.club/api/bestv.php?id=cctv12hd8m/8000000",
    "cctv13": "https://live.goodiptv.club/api/bestv.php?id=cctv13xwhd8m/8000000",
    "cctv14": "https://live.goodiptv.club/api/bestv.php?id=cctvsehd8m/8000000",
    "cctv15": "https://live.goodiptv.club/api/bestv.php?id=cctv15hd8m/8000000",
    "cctv16": "https://live.goodiptv.club/api/bestv.php?id=cctv16hd8m/8000000",
    "cctv17": "https://live.goodiptv.club/api/bestv.php?id=cctv17hd8m/8000000",
}

V1 = {
    k: v.replace("live.goodiptv.club", "live.v1.mk") for k, v in GOODIPTV.items()
}

def _read_browser(channel_id: str) -> str | None:
    if not RESOLVED.exists():
        return None
    try:
        data = json.loads(RESOLVED.read_text(encoding="utf-8"))
    except Exception:
        return None
    url = data.get(channel_id)
    return url if isinstance(url, str) and url.startswith(("http://", "https://")) else None

def _resolve_api(api_url: str, timeout: int) -> str | None:
    try:
        r = requests.get(
            api_url,
            timeout=min(timeout, 5),
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        text = r.text.strip()
        if text.startswith(("http://", "https://")):
            return text.splitlines()[0].strip()
        if "#EXTM3U" in text:
            return r.url
        return r.url if ".m3u8" in r.url else None
    except Exception:
        return None

def resolve_candidates(channel_id: str, timeout: int = 20) -> list[str]:
    candidates = []
    for table in (GOODIPTV, V1):
        api = table.get(channel_id)
        if api:
            # Keep the resolver endpoint itself as a probe candidate; ffprobe/curl
            # can follow redirects, and this avoids a slow discovery request.
            candidates.append(api)
    return list(dict.fromkeys(candidates))

def resolve(channel_id: str, timeout: int = 20) -> str | None:
    return next(iter(resolve_candidates(channel_id, timeout)), None)
