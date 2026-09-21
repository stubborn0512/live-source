from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

APP = FastAPI(title="live-source failover gateway")
# Mini-program HLS relay deployment marker: 2026-09-21.

STATUS_URL = os.getenv(
    "STATUS_URL",
    "https://raw.githubusercontent.com/stubborn0512/live-source/main/output/status.json",
)
CACHE_TTL = int(os.getenv("STATUS_CACHE_TTL", "300"))
HLS_ROOT = Path(os.getenv("HLS_ROOT", "/tmp/live-source-hls"))
HLS_ROOT.mkdir(parents=True, exist_ok=True)

_cache = {"at": 0.0, "data": None}
_cache_lock = threading.Lock()
_hls = {}
_hls_lock = threading.Lock()


def _load_status():
    now = time.time()
    with _cache_lock:
        if _cache["data"] is not None and now - _cache["at"] < CACHE_TTL:
            return _cache["data"]

    import requests

    r = requests.get(STATUS_URL, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data.get("channels"), list):
        raise RuntimeError("invalid status.json")

    with _cache_lock:
        _cache.update(at=now, data=data)
    return data


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
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rw_timeout",
            "15000000",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
            "-i",
            url,
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-c",
            "copy",
            "-f",
            "mpegts",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
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


def _stop_hls(cid):
    state = _hls.pop(cid, None)
    if not state:
        return
    process = state.get("process")
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except Exception:
            process.kill()
    shutil.rmtree(state["dir"], ignore_errors=True)


def _hls_process_alive(state):
    process = state.get("process")
    return bool(process and process.poll() is None)


def _start_hls(cid, channel, start_index=0):
    urls = _sources(channel)
    if not urls:
        raise HTTPException(503, "no verified source")

    _stop_hls(cid)
    channel_dir = HLS_ROOT / cid
    channel_dir.mkdir(parents=True, exist_ok=True)

    for offset in range(len(urls)):
        index = (start_index + offset) % len(urls)
        url = urls[index]
        shutil.rmtree(channel_dir, ignore_errors=True)
        channel_dir.mkdir(parents=True, exist_ok=True)

        playlist = channel_dir / "index.m3u8"
        segment_pattern = str(channel_dir / "seg_%06d.ts")
        process = subprocess.Popen(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-rw_timeout",
                "15000000",
                "-reconnect",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                "5",
                "-i",
                url,
                "-map",
                "0:v:0?",
                "-map",
                "0:a:0?",
                "-c",
                "copy",
                "-f",
                "hls",
                "-hls_time",
                "2",
                "-hls_list_size",
                "6",
                "-hls_flags",
                "delete_segments+append_list+omit_endlist",
                "-hls_segment_filename",
                segment_pattern,
                str(playlist),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.time() + 15
        while time.time() < deadline:
            if playlist.exists():
                try:
                    text = playlist.read_text(encoding="utf-8")
                    if "#EXTM3U" in text and "#EXTINF:" in text:
                        with _hls_lock:
                            _hls[cid] = {
                                "process": process,
                                "dir": channel_dir,
                                "source_index": index,
                                "source_url": url,
                                "started_at": time.time(),
                            }
                        return
                except OSError:
                    pass
            if process.poll() is not None:
                break
            time.sleep(0.25)

        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except Exception:
                process.kill()

    shutil.rmtree(channel_dir, ignore_errors=True)
    raise HTTPException(503, "all verified sources failed to start")


def _ensure_hls(cid):
    channel = _channel(cid)
    with _hls_lock:
        state = _hls.get(cid)

    if state and _hls_process_alive(state):
        playlist = Path(state["dir"]) / "index.m3u8"
        if playlist.exists():
            return state

    next_index = 0
    if state:
        next_index = int(state.get("source_index", 0)) + 1

    with _hls_lock:
        state = _hls.get(cid)
        if state and _hls_process_alive(state):
            return state
        return _start_hls(cid, channel, next_index)


@APP.get("/health")
def health():
    return {
        "ok": True,
        "channels": int(_load_status().get("count", 0)),
        "git_commit": os.getenv("RENDER_GIT_COMMIT", "local"),
        "hls_sessions": sum(1 for state in _hls.values() if _hls_process_alive(state)),
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
    state = _ensure_hls(channel_id)
    return FileResponse(
        Path(state["dir"]) / "index.m3u8",
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@APP.get("/hls/{channel_id}/{segment}")
def hls_segment(channel_id: str, segment: str):
    if "/" in segment or segment in {".", ".."} or not segment.endswith(".ts"):
        raise HTTPException(400, "invalid segment")

    state = _ensure_hls(channel_id)
    path = Path(state["dir"]) / segment
    if not path.is_file():
        raise HTTPException(404, "segment not found")

    return FileResponse(
        path,
        media_type="video/mp2t",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
