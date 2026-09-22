from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse

APP = FastAPI(title="live-source failover gateway")
# Mini-program HLS relay deployment marker: 2026-09-21-2.

STATUS_URL = os.getenv(
    "STATUS_URL",
    "https://raw.githubusercontent.com/stubborn0512/live-source/main/output/status.json",
)
CACHE_TTL = int(os.getenv("STATUS_CACHE_TTL", "300"))
HLS_TIMEOUT = float(os.getenv("HLS_TIMEOUT", "8"))
HLS_MAP_TTL = int(os.getenv("HLS_MAP_TTL", "30"))
EPG_URL = os.getenv("EPG_URL", "https://live.fanmingming.com/e.xml")
EPG_CACHE_TTL = int(os.getenv("EPG_CACHE_TTL", "600"))
_epg_cache = {"at": 0.0, "data": None}
_epg_lock = threading.Lock()

_cache = {"at": 0.0, "data": None}
_cache_lock = threading.Lock()
_hls = {}
_hls_lock = threading.Lock()


def _load_status():
    now = time.time()
    with _cache_lock:
        if _cache["data"] is not None and now - _cache["at"] < CACHE_TTL:
            return _cache["data"]

    r = requests.get(STATUS_URL, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data.get("channels"), list):
        raise RuntimeError("invalid status.json")

    with _cache_lock:
        _cache.update(at=now, data=data)
    return data



def _norm_name(value: str) -> str:
    return "".join(ch.lower() for ch in str(value) if ch.isalnum())


def _channel_aliases(channel_id: str, name: str):
    aliases = {name, channel_id}
    if channel_id.startswith("cctv"):
        n = channel_id[4:]
        aliases.update({f"CCTV{n}", f"CCTV-{n}", f"CCTV-{n} 综合"})
        if n == "5plus":
            aliases.update({"CCTV5+", "CCTV-5+", "CCTV-5+ 体育赛事"})
    return {_norm_name(x) for x in aliases if x}


def _parse_epg_xml(content: bytes):
    root = ET.fromstring(content)
    programs = {}
    for item in root.findall(".//programme"):
        start = item.attrib.get("start", "")
        stop = item.attrib.get("stop", "")
        channel = _norm_name(item.attrib.get("channel", ""))
        title_node = item.find("title")
        if not channel or title_node is None or not (title_node.text or "").strip():
            continue
        try:
            start_dt = _parse_xmltv_time(start)
            stop_dt = _parse_xmltv_time(stop) if stop else start_dt
        except Exception:
            continue
        programs.setdefault(channel, []).append({
            "title": (title_node.text or "").strip(),
            "start": start_dt,
            "stop": stop_dt,
        })
    for items in programs.values():
        items.sort(key=lambda x: x["start"])
    return programs


def _parse_xmltv_time(value: str):
    value = value.strip()
    if not value:
        raise ValueError("empty time")
    # XMLTV usually uses YYYYMMDDHHMMSS +0800.
    base = value[:14]
    offset = value[15:20] if len(value) >= 20 and value[14] == " " else "+0000"
    dt = datetime.strptime(base, "%Y%m%d%H%M%S")
    sign = 1 if offset[0] == "+" else -1
    hours = int(offset[1:3])
    minutes = int(offset[3:5])
    tz = timezone(sign * timedelta(hours=hours, minutes=minutes))
    return dt.replace(tzinfo=tz).astimezone(timezone(timedelta(hours=8)))


def _load_epg():
    now = time.time()
    with _epg_lock:
        if _epg_cache["data"] is not None and now - _epg_cache["at"] < EPG_CACHE_TTL:
            return _epg_cache["data"]
    r = requests.get(
        EPG_URL,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    r.raise_for_status()
    data = _parse_epg_xml(r.content)
    with _epg_lock:
        _epg_cache.update(at=now, data=data)
    return data


def _format_time(dt):
    return dt.strftime("%H:%M")


def _epg_for_channel(channel_id: str, name: str, limit: int = 8):
    try:
        programs = _load_epg()
    except Exception:
        return {"current": None, "next": None, "schedule": [], "available": False}
    aliases = _channel_aliases(channel_id, name)
    matched = []
    for key, items in programs.items():
        if key in aliases:
            matched.extend(items)
    # De-duplicate identical entries from multiple aliases.
    unique = {}
    for item in matched:
        unique[(item["start"], item["stop"], item["title"])] = item
    matched = sorted(unique.values(), key=lambda x: x["start"])
    now = datetime.now(timezone(timedelta(hours=8)))
    current = None
    future = []
    for item in matched:
        if item["start"] <= now < item["stop"]:
            current = item
        elif item["start"] > now:
            future.append(item)
    schedule = [current] if current else []
    schedule.extend(future[:limit - len(schedule)])
    def public(item):
        if not item:
            return None
        total = max(1, int((item["stop"] - item["start"]).total_seconds()))
        elapsed = max(0, min(total, int((now - item["start"]).total_seconds())))
        return {
            "title": item["title"],
            "start": _format_time(item["start"]),
            "stop": _format_time(item["stop"]),
            "start_ts": int(item["start"].timestamp()),
            "stop_ts": int(item["stop"].timestamp()),
            "progress": round(elapsed * 100 / total, 1),
        }
    return {
        "current": public(current),
        "next": public(future[0] if future else None),
        "schedule": [public(x) for x in schedule if x],
        "available": bool(matched),
    }


def _all_epg(channels, ids=None):
    wanted = set(ids or [])
    result = []
    for channel in channels:
        cid = str(channel.get("id", ""))
        if wanted and cid not in wanted:
            continue
        item = _epg_for_channel(cid, str(channel.get("name", "")))
        result.append({"id": cid, "name": channel.get("name"), **item})
    return result


def _channel(cid):
    for channel in _load_status()["channels"]:
        if channel.get("id") == cid:
            return channel
    raise HTTPException(404, "channel not found")


def _sources(channel):
    urls = [s.get("url") for s in channel.get("sources", []) if s.get("url")]
    if not urls and channel.get("url"):
        urls = [channel["url"]]
    return list(dict.fromkeys(urls))


def _ffmpeg(url):
    return subprocess.Popen(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-rw_timeout", "15000000",
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
            "-i", url, "-map", "0:v:0?", "-map", "0:a:0?",
            "-c", "copy", "-f", "mpegts", "pipe:1",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
    )


def _stream(channel):
    for url in _sources(channel):
        process = None
        try:
            process = _ffmpeg(url)
            while True:
                chunk = process.stdout.read(188 * 32)
                if not chunk:
                    break
                yield chunk
        except GeneratorExit:
            return
        except Exception:
            pass
        finally:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except Exception:
                    process.kill()


def _kill_process(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except Exception:
            process.kill()



def _valid_upstream_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def _token_for(kind: str, url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return f"{kind}_{digest}"


def _state(cid):
    with _hls_lock:
        return _hls.setdefault(
            cid,
            {"source_index": 0, "maps": {}, "updated_at": 0.0},
        )


def _remember_url(cid: str, token: str, url: str, source_index: int | None = None):
    state = _state(cid)
    with _hls_lock:
        now = time.time()
        state["maps"][token] = (url, now, source_index)
        cutoff = now - HLS_MAP_TTL
        state["maps"] = {
            k: v for k, v in state["maps"].items() if v[1] >= cutoff
        }


def _lookup_url(cid: str, token: str) -> str | None:
    with _hls_lock:
        state = _hls.get(cid)
        if not state:
            return None
        item = state.get("maps", {}).get(token)
        if not item:
            return None
        if time.time() - item[1] > HLS_MAP_TTL:
            state["maps"].pop(token, None)
            return None
        return item[0]


def _rewrite_playlist(cid: str, base_url: str, text: str, source_index: int | None = None) -> str:
    lines = text.splitlines()
    out = []
    expect_uri_kind = None

    for raw in lines:
        line = raw.strip()
        if not line:
            out.append("")
            continue

        if line.startswith("#EXT-X-KEY:") and 'URI="' in line:
            prefix, rest = line.split('URI="', 1)
            uri, suffix = rest.split('"', 1)
            upstream = urljoin(base_url, uri)
            if _valid_upstream_url(upstream):
                token = _token_for("key", upstream)
                _remember_url(cid, token, upstream, source_index)
                line = prefix + 'URI="/hls/' + cid + '/' + token + '.key"' + suffix
            out.append(line)
            continue

        if line.startswith("#EXT-X-MAP:") and 'URI="' in line:
            prefix, rest = line.split('URI="', 1)
            uri, suffix = rest.split('"', 1)
            upstream = urljoin(base_url, uri)
            if _valid_upstream_url(upstream):
                token = _token_for("seg", upstream)
                _remember_url(cid, token, upstream, source_index)
                line = prefix + 'URI="/hls/' + cid + '/' + token + '.bin"' + suffix
            out.append(line)
            continue

        if line.startswith("#EXT-X-STREAM-INF:"):
            expect_uri_kind = "playlist"
            out.append(line)
            continue

        if line.startswith("#"):
            out.append(line)
            continue

        upstream = urljoin(base_url, line)
        if not _valid_upstream_url(upstream):
            raise ValueError("unsupported HLS URI")

        if expect_uri_kind == "playlist" or urlparse(upstream).path.lower().endswith(".m3u8"):
            token = _token_for("pl", upstream)
            local = f"/hls/{cid}/{token}.m3u8"
        else:
            token = _token_for("seg", upstream)
            local = f"/hls/{cid}/{token}.ts"

        _remember_url(cid, token, upstream, source_index)
        out.append(local)
        expect_uri_kind = None

    return "\n".join(out) + "\n"


def _fetch_playlist(cid: str, channel):
    urls = _sources(channel)
    if not urls:
        raise HTTPException(502, "no live source")

    state = _state(cid)
    with _hls_lock:
        start = int(state.get("source_index", 0)) % len(urls)

    last_error = None
    for offset in range(len(urls)):
        index = (start + offset) % len(urls)
        source = urls[index]
        try:
            r = requests.get(
                source,
                timeout=HLS_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153.0 Safari/537.36"},
            )
            r.raise_for_status()
            text = r.text
            if "#EXTM3U" not in text:
                raise ValueError("upstream is not an HLS playlist")
            if "#EXTINF:" not in text and "#EXT-X-STREAM-INF" not in text:
                raise ValueError("HLS playlist has no media entries")
            rewritten = _rewrite_playlist(cid, r.url, text, index)
            with _hls_lock:
                state["source_index"] = index
                state["updated_at"] = time.time()
                state["source_url"] = source
            return rewritten
        except Exception as exc:
            last_error = exc
            continue

    raise HTTPException(502, f"all live sources failed: {last_error}")


def _proxy_bytes(cid: str, token: str, suffix: str):
    upstream = _lookup_url(cid, token)
    if not upstream:
        raise HTTPException(404, "segment expired")

    try:
        r = requests.get(
            upstream,
            stream=True,
            timeout=(HLS_TIMEOUT, 15),
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153.0 Safari/537.36"},
        )
        r.raise_for_status()
    except Exception as exc:
        # If an HLS segment fails, advance this channel to the next source.
        # The next playlist refresh then rebuilds against the fallback source.
        with _hls_lock:
            state = _hls.get(cid)
            item = state.get("maps", {}).get(token) if state else None
            if state and item and len(item) >= 3 and item[2] is not None:
                source_index = int(item[2])
                urls = _sources(_channel(cid))
                if urls and state.get("source_index") == source_index:
                    state["source_index"] = (source_index + 1) % len(urls)
                    state["updated_at"] = time.time()
        raise HTTPException(502, f"upstream segment failed: {exc}")

    media_type = (
        "application/vnd.apple.mpegurl"
        if suffix == ".m3u8"
        else "application/octet-stream"
        if suffix in {".key", ".bin"}
        else "video/mp2t"
    )

    def body():
        try:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            r.close()

    return StreamingResponse(
        body(),
        media_type=media_type,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@APP.get("/health")
def health():
    return {
        "ok": True,
        "channels": int(_load_status().get("count", 0)),
        "git_commit": os.getenv("RENDER_GIT_COMMIT", "local"),
        "hls_sessions": len(_hls),
        "hls_mode": "playlist-proxy",
    }


@APP.get("/channels.json")
def channels():
    data = _load_status()
    return {
        "count": int(data.get("count", 0)),
        "updated_at": data.get("updated_at"),
        "channels": [
            {
                "id": x.get("id"),
                "name": x.get("name"),
                "group": "CCTV" if str(x.get("id", "")).startswith("cctv") else "卫视",
                "width": x.get("width"),
                "height": x.get("height"),
                "source_count": x.get("source_count", 0),
                "ok": bool(x.get("ok")),
                "1080p": bool(x.get("1080p")),
            }
            for x in data["channels"]
            if x.get("id") and x.get("name") and x.get("ok") and x.get("1080p")
        ],
    }


@APP.get("/playlist.m3u", response_class=PlainTextResponse)
def playlist(request: Request):
    lines = ["#EXTM3U"]
    for x in _load_status()["channels"]:
        cid = x["id"]
        group = "CCTV" if cid.startswith("cctv") else "卫视"
        lines.append(
            '#EXTINF:-1 tvg-id="' + cid + '" tvg-name="' + x["name"]
            + '" group-title="' + group + '",' + x["name"]
        )
        lines.append(str(request.base_url).rstrip("/") + "/stream/" + cid)
    return "\n".join(lines) + "\n"


@APP.get("/epg.json")
def epg(ids: str | None = None):
    data = _load_status()
    wanted = [x.strip() for x in (ids or "").split(",") if x.strip()]
    return {
        "source": "cached XMLTV",
        "updated_at": int(_epg_cache.get("at", 0)),
        "channels": _all_epg(data["channels"], wanted),
    }



@APP.get("/stream/{channel_id}")
def stream(channel_id: str):
    channel = _channel(channel_id)
    return StreamingResponse(
        _stream(channel),
        media_type="video/mp2t",
        headers={"Cache-Control": "no-store", "X-Live-Source-Channel": channel_id},
    )


@APP.get("/hls/{channel_id}/index.m3u8")
def hls_playlist(channel_id: str):
    text = _fetch_playlist(channel_id, _channel(channel_id))
    return PlainTextResponse(
        text,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@APP.get("/hls/{channel_id}/{token}.m3u8")
def hls_nested_playlist(channel_id: str, token: str):
    upstream = _lookup_url(channel_id, token)
    if not upstream:
        raise HTTPException(404, "playlist expired")
    try:
        r = requests.get(
            upstream,
            timeout=HLS_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153.0 Safari/537.36"},
        )
        r.raise_for_status()
        text = _rewrite_playlist(channel_id, r.url, r.text, None)
    except Exception as exc:
        raise HTTPException(502, f"upstream playlist failed: {exc}")
    return PlainTextResponse(
        text,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@APP.get("/hls/{channel_id}/{token}.ts")
def hls_segment(channel_id: str, token: str):
    return _proxy_bytes(channel_id, token, ".ts")


@APP.get("/hls/{channel_id}/{token}.key")
def hls_key(channel_id: str, token: str):
    return _proxy_bytes(channel_id, token, ".key")


@APP.get("/hls/{channel_id}/{token}.bin")
def hls_binary_segment(channel_id: str, token: str):
    return _proxy_bytes(channel_id, token, ".bin")
