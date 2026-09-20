"""Discover public CCTV HLS candidates and verify them with ffprobe."""
from __future__ import annotations
import json
import re
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

V1 = {k: v.replace("live.goodiptv.club", "live.v1.mk") for k, v in GOODIPTV.items()}
PUBLIC_LISTS = [
    "https://raw.githubusercontent.com/CCSH/IPTV/main/live.txt",
    "https://raw.githubusercontent.com/jura00/vms/main/hd.m3u8",
]

def _read_browser(channel_id: str) -> str | None:
    if not RESOLVED.exists():
        return None
    try:
        data = json.loads(RESOLVED.read_text(encoding="utf-8"))
    except Exception:
        return None
    url = data.get(channel_id)
    return url if isinstance(url, str) and url.startswith(("http://", "https://")) else None

def _discover_public_lists(channel_id: str, timeout: int) -> list[str]:
    num = channel_id.replace("cctv", "")
    labels = {f"cctv{num}", f"cctv-{num}", f"CCTV-{num}", f"CCTV{num}"}
    if channel_id == "cctv5plus":
        labels |= {"cctv5+", "cctv-5+", "CCTV5+", "CCTV-5+"}
    found = []
    for source in PUBLIC_LISTS:
        try:
            text = requests.get(
                source, timeout=min(timeout, 8),
                headers={"User-Agent": "Mozilla/5.0"},
            ).text
        except Exception:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "," in line:
                name, url = line.split(",", 1)
                if name.strip() in labels and url.strip().startswith(("http://", "https://")):
                    found.append(url.strip())
            if line.startswith("#EXTINF") and i + 1 < len(lines):
                low = line.lower()
                if any(label.lower() in low for label in labels):
                    url = lines[i + 1].strip()
                    if url.startswith(("http://", "https://")):
                        found.append(url)
    return found

def resolve_candidates(channel_id: str, timeout: int = 10) -> list[str]:
    discovered = _discover_public_lists(channel_id, timeout)
    candidates = discovered + [
        table[channel_id] for table in (GOODIPTV, V1) if channel_id in table
    ]
    browser = _read_browser(channel_id)
    if browser:
        candidates.append(browser)
    candidates = list(dict.fromkeys(candidates))
    def score(url: str) -> tuple[int, int]:
        low = url.lower()
        quality = int(any(k in low for k in ("1080", "4k", "hd", "4000", "6000", "8000000")))
        officialish = int("cctv" in low or "chinamobile" in low or "cmvideo" in low)
        return (quality, officialish)
    candidates.sort(key=score, reverse=True)
    return candidates[:8]

def resolve(channel_id: str, timeout: int = 10) -> str | None:
    candidates = resolve_candidates(channel_id, timeout)
    return candidates[0] if candidates else None
