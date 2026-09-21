"""Discover public CCTV HLS candidates and verify them with ffprobe."""
from __future__ import annotations
import json
import re
from pathlib import Path
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

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
GITHUB_LISTS = [
    # Existing high-value sources.
    "https://raw.githubusercontent.com/best-fan/iptv-sources/main/cn_all.m3u8",
    "https://raw.githubusercontent.com/best-fan/iptv-sources/main/cn_all_status.m3u8",
    "https://raw.githubusercontent.com/Lightconer/TVBox-Sources/main/output/live.m3u",
    "https://raw.githubusercontent.com/CCSH/IPTV/main/live.txt",
    "https://raw.githubusercontent.com/jura00/vms/main/hd.m3u8",
    "https://raw.githubusercontent.com/kaige-cai/live/main/live.m3u",
    "https://raw.githubusercontent.com/T00700/TVBoxSE/master/live.txt",
    "https://raw.githubusercontent.com/TCatCloud/IPTV/Files/CCTV.m3u",

    # Additional public lists used by cs3306/IPTV-Sources and related projects.
    "https://iptv-org.github.io/iptv/countries/cn.m3u",
    "https://tv.iill.top/m3u/Gather",
    "https://raw.githubusercontent.com/YanG-1989/m3u/main/Gather.m3u",
    "https://live.zbds.top/tv/iptv4.m3u",
    "https://raw.githubusercontent.com/alienlu/iptv/master/iptv.m3u",
    "https://live.iptv365.org/live.m3u",
    "https://raw.githubusercontent.com/zwc456baby/iptv_alive/master/live.txt",
    "https://raw.githubusercontent.com/Guovin/TV/gd/output/result.m3u",
    "https://raw.githubusercontent.com/qwerttvv/Beijing-IPTV/master/IPTV-Unicom.m3u",
    "https://raw.githubusercontent.com/iceyheart/IPTV/main/iptv.m3u",
    "https://raw.githubusercontent.com/joevess/IPTV/main/iptv.m3u8",
    "https://raw.githubusercontent.com/wwb521/live/main/tv.m3u",
    "https://raw.githubusercontent.com/cairong/iptv-yuan/main/jsyd.m3u",
    "https://raw.githubusercontent.com/jisoypub/iptv/master/cn_all.m3u",
    "https://raw.githubusercontent.com/zbefine/iptv/main/iptv.m3u",
    "https://raw.githubusercontent.com/BigBigGrandG/IPTV-URL/release/Gather.m3u",
]
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

# Gitee fallback is intentionally lower priority than actively maintained GitHub lists.
GITEE_FALLBACK_LISTS = [
    "https://gitee.com/ZJHT0/tv-source/raw/master/iptv/iptv.m3u8",
    "https://gitee.com/myitgit/iptv-sources/raw/gh-pages/txt/ycl_iptv.txt",
    "https://gitee.com/user_0628/iptv/raw/master/CCTV.m3u8",
]

SOURCE_CACHE: dict[str, str] = {}
SOURCE_ORDER_CACHE: list[str] | None = None
SOURCE_INDEX_CACHE: dict[str, list[str]] | None = None
SOURCE_LOCK = Lock()
SOURCE_BUILD_LOCK = Lock()
URL_RE = re.compile(r'''https?://[^\s<>"]+''')
SOURCE_FETCH_WORKERS = 10


def _github_repo(source: str) -> str | None:
    if urlparse(source).netloc.lower() != "raw.githubusercontent.com":
        return None
    parts = urlparse(source).path.strip("/").split("/")
    if len(parts) < 2:
        return None
    return f"{parts[0]}/{parts[1]}"


def _github_pushed_at(repo: str, timeout: int) -> str:
    try:
        response = requests.get(
            f"https://api.github.com/repos/{repo}",
            timeout=min(timeout, 5),
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "live-source/1.0",
            },
        )
        if response.ok:
            return response.json().get("pushed_at") or ""
    except Exception:
        pass
    return ""


def _ordered_sources(timeout: int) -> list[str]:
    global SOURCE_ORDER_CACHE
    with SOURCE_LOCK:
        if SOURCE_ORDER_CACHE is not None:
            return SOURCE_ORDER_CACHE[:]

    ranked = []
    github_tasks = []
    with ThreadPoolExecutor(max_workers=SOURCE_FETCH_WORKERS) as pool:
        futures = {}
        for index, source in enumerate(GITHUB_LISTS):
            repo = _github_repo(source)
            if repo:
                futures[pool.submit(_github_pushed_at, repo, timeout)] = (index, source)
            else:
                ranked.append(("", index, source))
        for future in futures:
            index, source = futures[future]
            try:
                pushed_at = future.result()
            except Exception:
                pushed_at = ""
            ranked.append((pushed_at, index, source))

    ranked.sort(key=lambda item: (bool(item[0]), item[0], -item[1]), reverse=True)
    ordered = [source for _, _, source in ranked] + GITEE_FALLBACK_LISTS

    with SOURCE_LOCK:
        SOURCE_ORDER_CACHE = ordered
    return ordered[:]


def _load_source(source: str, timeout: int) -> str:
    with SOURCE_LOCK:
        if source in SOURCE_CACHE:
            return SOURCE_CACHE[source]

    try:
        response = requests.get(
            source,
            timeout=min(timeout, 10),
            headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"},
        )
        response.raise_for_status()
        text = response.text
    except Exception:
        text = ""

    with SOURCE_LOCK:
        SOURCE_CACHE[source] = text
    return text


def _read_browser(channel_id: str) -> str | None:
    if not RESOLVED.exists():
        return None
    try:
        data = json.loads(RESOLVED.read_text(encoding="utf-8"))
    except Exception:
        return None
    url = data.get(channel_id)
    return url if isinstance(url, str) and url.startswith(("http://", "https://")) else None


def _extract_urls(text: str) -> list[str]:
    urls = []
    for match in URL_RE.findall(text):
        url = match.rstrip("'\"),;]")
        if url.startswith(("http://", "https://")):
            urls.append(url)
    return urls


def _label_matches(line: str, labels: set[str], cctv: bool) -> bool:
    low = re.sub(r"\s+", "", line.lower())
    for label in labels:
        normalized = re.sub(r"\s+", "", label.lower()).replace("-", "")
        if cctv:
            if re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![0-9+])", low):
                return True
        elif normalized in low:
            return True
    return False


def _channel_labels() -> dict[str, tuple[set[str], bool]]:
    labels: dict[str, tuple[set[str], bool]] = {}
    for channel_id in GOODIPTV:
        num = channel_id.replace("cctv", "")
        values = {f"cctv{num}", f"cctv-{num}", f"CCTV{num}", f"CCTV-{num}"}
        if channel_id == "cctv5plus":
            values |= {"cctv5+", "cctv-5+", "CCTV5+", "CCTV-5+"}
        labels[channel_id] = (values, True)
    for channel_id, values in WEISHI_LABELS.items():
        labels[channel_id] = (set(values), False)
    return labels


def _build_source_index(timeout: int) -> dict[str, list[str]]:
    global SOURCE_INDEX_CACHE

    # Only one channel worker builds the shared index. Other channel workers
    # wait for the same cache instead of downloading every source list again.
    with SOURCE_BUILD_LOCK:
        with SOURCE_LOCK:
            if SOURCE_INDEX_CACHE is not None:
                return {key: value[:] for key, value in SOURCE_INDEX_CACHE.items()}

        index = {channel_id: [] for channel_id in _channel_labels()}
        label_map = _channel_labels()
        sources = _ordered_sources(timeout)

        # Fetch source lists concurrently once, then index them once. This
        # avoids rescanning every giant M3U file separately for every channel.
        with ThreadPoolExecutor(max_workers=SOURCE_FETCH_WORKERS) as pool:
            futures = {
                pool.submit(_load_source, source, timeout): source
                for source in sources
            }
            loaded = [(futures[future], future.result()) for future in futures]

        for source, text in loaded:
            if not text:
                continue
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if not line.strip():
                    continue
                matched_ids = [
                    channel_id
                    for channel_id, (labels, is_cctv) in label_map.items()
                    if _label_matches(line, labels, is_cctv)
                ]
                if not matched_ids:
                    continue

                nearby = "\n".join(lines[i:min(i + 4, len(lines))])
                urls = _extract_urls(nearby)
                if not urls:
                    urls = _extract_urls(line)
                if not urls:
                    continue
                for channel_id in matched_ids:
                    index[channel_id].extend(urls)

        index = {key: list(dict.fromkeys(value)) for key, value in index.items()}
        with SOURCE_LOCK:
            SOURCE_INDEX_CACHE = index
        return {key: value[:] for key, value in index.items()}


def _discover_public_lists(
    channel_id: str, timeout: int, channel_name: str | None = None
) -> list[str]:
    # Public lists are indexed once for the whole run.
    index = _build_source_index(timeout)
    found = index.get(channel_id, [])[:]

    # Preserve exact configured name matching for unusual satellite/local lists.
    if channel_name and channel_id not in index:
        found.extend(index.get(channel_name, []))
    return list(dict.fromkeys(found))


def resolve_candidates(
    channel_id: str, timeout: int = 10, channel_name: str | None = None
) -> list[str]:
    discovered = _discover_public_lists(channel_id, timeout, channel_name)

    fallbacks = [
        table[channel_id] for table in (GOODIPTV, V1) if channel_id in table
    ]
    browser = _read_browser(channel_id)
    if browser:
        fallbacks.append(browser)

    discovered = list(dict.fromkeys(discovered))
    fallbacks = list(dict.fromkeys(fallbacks))
    candidates = fallbacks + [url for url in discovered if url not in fallbacks]

    def score(url: str) -> tuple[int, int, int, int]:
        low = url.lower()
        quality = (
            5 if any(k in low for k in ("4k", "2160", "15000000", "8000000"))
            else 4 if any(k in low for k in ("1080", "1080p"))
            else 3 if any(k in low for k in ("8m", "6000", "4000"))
            else 2 if "hd" in low
            else 1
        )
        direct = int(low.endswith(".m3u8") or ".m3u8?" in low)
        return (quality, direct, -len(url), 0)

    # Rank the public candidates by advertised quality first. ffprobe remains
    # authoritative; labels such as [1080] are only candidate hints.
    discovered.sort(key=score, reverse=True)

    # Keep enough candidates for two independent verified sources without
    # exploding the number of ffprobe processes.
    return list(dict.fromkeys(
        fallbacks + discovered[: max(0, 12 - len(fallbacks))]
    ))[:12]


def resolve(channel_id: str, timeout: int = 10) -> str | None:
    candidates = resolve_candidates(channel_id, timeout)
    return candidates[0] if candidates else None
