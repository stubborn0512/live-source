from __future__ import annotations
import os, subprocess, threading, time
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
APP = FastAPI(title="live-source failover gateway")
# Deployment smoke marker: this file lives under Render root directory `gateway`.
STATUS_URL = os.getenv("STATUS_URL", "https://raw.githubusercontent.com/stubborn0512/live-source/main/output/status.json")
CACHE_TTL = int(os.getenv("STATUS_CACHE_TTL", "300"))
_cache = {"at": 0.0, "data": None}; _lock = threading.Lock()

def _load_status():
    now = time.time()
    with _lock:
        if _cache["data"] is not None and now - _cache["at"] < CACHE_TTL:
            return _cache["data"]
    import requests
    r = requests.get(STATUS_URL, timeout=15); r.raise_for_status(); d = r.json()
    if not isinstance(d.get("channels"), list):
        raise RuntimeError("invalid status.json")
    with _lock: _cache.update(at=now, data=d)
    return d

def _channel(cid):
    for x in _load_status()["channels"]:
        if x.get("id") == cid: return x
    raise HTTPException(404, "channel not found")

def _sources(x):
    a = [s.get("url") for s in x.get("sources", []) if s.get("url")]
    if not a and x.get("url"): a = [x["url"]]
    return list(dict.fromkeys(a))

def _ffmpeg(url):
    return subprocess.Popen(
        ["ffmpeg","-hide_banner","-loglevel","error","-rw_timeout","15000000",
         "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","5",
         "-i",url,"-map","0:v:0?","-map","0:a:0?","-c","copy","-f","mpegts","pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)

def _stream(x):
    for url in _sources(x):
        p = None
        try:
            p = _ffmpeg(url)
            while True:
                chunk = p.stdout.read(188 * 32)
                if not chunk: break
                yield chunk
        except GeneratorExit:
            return
        except Exception:
            pass
        finally:
            if p and p.poll() is None:
                p.terminate()
                try: p.wait(timeout=3)
                except Exception: p.kill()

@APP.get("/health")
def health():
    return {
        "ok": True,
        "channels": int(_load_status().get("count", 0)),
        "git_commit": os.getenv("RENDER_GIT_COMMIT", "local"),
    }

@APP.get("/playlist.m3u", response_class=PlainTextResponse)
def playlist(request: Request):
    lines = ["#EXTM3U"]
    for x in _load_status()["channels"]:
        cid = x["id"]
        group = "CCTV" if cid.startswith("cctv") else "卫视"
        lines.append('#EXTINF:-1 tvg-id="' + cid + '" tvg-name="' + x["name"] + '" group-title="' + group + '",' + x["name"])
        lines.append(str(request.base_url).rstrip("/") + "/stream/" + cid)
    return "\n".join(lines) + "\n"

@APP.get("/stream/{channel_id}")
def stream(channel_id: str):
    x = _channel(channel_id)
    return StreamingResponse(
        _stream(x), media_type="video/mp2t",
        headers={"Cache-Control":"no-store","X-Live-Source-Channel":channel_id})
