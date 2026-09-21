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
    # Gitee public IPTV lists
    "https://gitee.com/ZJHT0/tv-source/raw/master/iptv/iptv.m3u8",
    "https://gitee.com/myitgit/iptv-sources/raw/gh-pages/txt/ycl_iptv.txt",
    "https://gitee.com/user_0628/iptv/raw/master/CCTV.m3u8",
    "https://raw.githubusercontent.com/CCSH/IPTV/main/live.txt",
    "https://raw.githubusercontent.com/jura00/vms/main/hd.m3u8",
    "https://raw.githubusercontent.com/kaige-cai/live/main/live.m3u",
    "https://raw.githubusercontent.com/T00700/TVBoxSE/master/live.txt",
    "https://raw.githubusercontent.com/TCatCloud/IPTV/Files/CCTV.m3u",
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

WEISHI_LABELS = {
    "beijing": {"北京卫视", "北京台"}, "dongfang": {"东方卫视", "东方台"},
    "hunan": {"湖南卫视", "湖南台"}, "zhejiang": {"浙江卫视", "浙江台"},
    "jiangsu": {"江苏卫视", "江苏台"}, "anhui": {"安徽卫视", "安徽台"},
    "shandong": {"山东卫视", "山东台"}, "liaoning": {"辽宁卫视", "辽宁台"},
    "heilongjiang": {"黑龙江卫视", "黑龙江台"}, "jilin": {"吉林卫视", "吉林台"},
    "tianjin": {"天津卫视", "天津台"}, "hebei": {"河北卫视", "河北台"},
    "shanxi": {"山西卫视", "山西台"}, "henan": {"河南卫视", "河南台"},
    "hubei": {"湖北卫视", "湖北台"}, "jiangxi": {"江西卫视", "江西台"},
    "fujian": {"东南卫视", "东南台"}, "guangdong": {"广东卫视", "广东台"},
    "shenzhen": {"深圳卫视", "深圳台"}, "guangxi": {"广西卫视", "广西台"},
    "hainan": {"海南卫视", "海南台"}, "sichuan": {"四川卫视", "四川台"},
    "chongqing": {"重庆卫视", "重庆台"}, "yunnan": {"云南卫视", "云南台"},
    "guizhou": {"贵州卫视", "贵州台"}, "xizang": {"西藏卫视", "西藏台"},
    "shaanxi": {"陕西卫视", "陕西台"}, "gansu": {"甘肃卫视", "甘肃台"},
    "qinghai": {"青海卫视", "青海台"}, "ningxia": {"宁夏卫视", "宁夏台"},
    "xinjiang": {"新疆卫视", "新疆台"}, "neimenggu": {"内蒙古卫视", "内蒙古台"},
}

def _discover_public_lists(channel_id: str, timeout: int, channel_name: str | None = None) -> list[str]:
    if channel_id.startswith("cctv"):
        num = channel_id.replace("cctv", "")
        labels = {f"cctv{num}", f"cctv-{num}", f"CCTV-{num}", f"CCTV{num}"}
        if channel_id == "cctv5plus":
            labels |= {"cctv5+", "cctv-5+", "CCTV5+", "CCTV-5+"}
    else:
        labels = set(WEISHI_LABELS.get(channel_id, set()))
        if channel_name:
            labels.add(channel_name)
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
                if any(label.lower() in name.strip().lower() for label in labels) and url.strip().startswith(("http://", "https://")):
                    found.append(url.strip())
            if line.startswith("#EXTINF") and i + 1 < len(lines):
                low = line.lower()
                if any(label.lower() in low for label in labels):
                    url = lines[i + 1].strip()
                    if url.startswith(("http://", "https://")):
                        found.append(url)
    return found

def resolve_candidates(channel_id: str, timeout: int = 10, channel_name: str | None = None) -> list[str]:
    discovered = _discover_public_lists(channel_id, timeout, channel_name)
    candidates = discovered + [
        table[channel_id] for table in (GOODIPTV, V1) if channel_id in table
    ]
    browser = _read_browser(channel_id)
    if browser:
        candidates.append(browser)
    candidates = list(dict.fromkeys(candidates))
    def score(url: str) -> tuple[int, int, int, int]:
        low = url.lower()
        quality = (
            5 if any(k in low for k in ("4k", "2160", "15000000", "8000000"))
            else 4 if any(k in low for k in ("1080", "1080p"))
            else 3 if any(k in low for k in ("8m", "6000", "4000"))
            else 2 if "hd" in low
            else 1
        )
        officialish = int("chinamobile" in low or "cmvideo" in low)
        direct = int(low.endswith(".m3u8") or ".m3u8?" in low)
        return (quality, officialish, direct, -len(url))

    candidates.sort(key=score, reverse=True)
    return candidates[:24]

def resolve(channel_id: str, timeout: int = 10) -> str | None:
    candidates = resolve_candidates(channel_id, timeout)
    return candidates[0] if candidates else None
