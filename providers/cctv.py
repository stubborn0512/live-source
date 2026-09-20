"""Resolve CCTV live HLS URLs from the public CNTV live API.

This provider deliberately uses a public endpoint rather than storing
time-sensitive CDN URLs in the repository.
"""

from __future__ import annotations

import json
import re
import socket
from typing import Any

import requests

API_URL = "https://vdn.live.cntv.cn/api2/liveHtml5.do"


def _local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _parse_json(text: str) -> dict[str, Any]:
    # The endpoint may wrap JSON in a callback/prefix/suffix.
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise ValueError("API response did not contain a JSON object")
    return json.loads(match.group(0))


def resolve(channel_id: str, timeout: int = 12) -> str | None:
    # Keep the channel identifier configurable. The public API uses the
    # cctv_p2p_hd* naming convention used by existing open-source clients.
    live_id = f"cctv_p2p_hd{channel_id}"

    params = {
        "channel": f"pa://{live_id}",
        "client": "html5",
        "ip": _local_ip(),
    }

    response = requests.get(
        API_URL,
        params=params,
        headers={
            "User-Agent": "Mozilla/5.0 live-source",
            "Cache-Control": "max-age=-1, public",
        },
        timeout=timeout,
    )
    response.raise_for_status()

    data = _parse_json(response.text)

    hls = data.get("hls_url")
    if isinstance(hls, dict):
        # Prefer the higher-quality HLS variant exposed by the API.
        for key in ("hls2", "hls1", "hls"):
            url = hls.get(key)
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                return url
    elif isinstance(hls, str) and hls.startswith(("http://", "https://")):
        return hls

    return None
