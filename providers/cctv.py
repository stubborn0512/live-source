"""Resolve CCTV live HLS URLs from the public CNTV live API.

The API response used by existing open-source clients is JavaScript that
contains a JSON object, rather than a bare JSON document.
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests

API_URL = "https://vdn.live.cntv.cn/api2/liveHtml5.do"


def _extract_payload(text: str) -> dict[str, Any]:
    # Typical response contains something like:
    # var vdata = '{...}';
    # Extract the JSON object first, then decode it.
    match = re.search(r"(\{.*\})", text, flags=re.S)
    if not match:
        raise ValueError("CNTV API response did not contain JSON")

    raw = match.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Some versions escape the JSON inside a JS string.
        unescaped = bytes(raw, "utf-8").decode("unicode_escape")
        return json.loads(unescaped)


def resolve(channel_id: str, timeout: int = 12) -> str | None:
    # Existing clients use pc:// and also provide channel_id.
    # The channel suffix is kept configurable by config.json.
    live_id = f"cctv_p2p_hd{channel_id}"

    params = {
        "channel": f"pc://{live_id}",
        "channel_id": channel_id,
    }

    response = requests.get(
        API_URL,
        params=params,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 9_1 like Mac OS X) "
                "AppleWebKit/601.1.46 (KHTML, like Gecko) "
                "Version/9.0 Mobile/13B143 Safari/601.1"
            ),
            "Referer": "https://tv.cctv.com/",
        },
        timeout=timeout,
    )
    response.raise_for_status()

    data = _extract_payload(response.text)
    hls = data.get("hls_url")

    if isinstance(hls, dict):
        # hls1 is the convention used by existing clients; fall back to
        # other variants if the service changes its response.
        for key in ("hls1", "hls2", "hls"):
            url = hls.get(key)
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                return url

    if isinstance(hls, str) and hls.startswith(("http://", "https://")):
        return hls

    return None
