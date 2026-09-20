"""Resolve public CCTV live HLS URLs from the current Yangshipin API.

This uses the same public anonymous ticket flow currently used by open-source
clients: a fresh cKey is generated for each request, the official API returns
short-lived HLS URLs, and the actual media URL is then checked with ffprobe.
No login, DRM bypass, or access-control circumvention is used.
"""

from __future__ import annotations

import base64
import hashlib
import os
import struct
import time
import uuid
from typing import Any

import requests

API_URL = "https://bkliveinfo.ysp.cctv.cn/"

PLATFORM = 4330403
APP_VERSION = "V8.22.1035.3031"
CKEY_TEA_KEY = bytes.fromhex("59b2f7cf725ef43c34fdd7c123411ed3")
GUARD_TEA_KEY = bytes.fromhex("110DBEC10C23E7D2E56A1CAD6914EF1B")
CKEY_XOR = bytes([0x84, 0x2E, 0xED, 0x08, 0xF0, 0x66, 0xE6, 0xEA, 0x48, 0xB4, 0xCA, 0xA9, 0x91, 0xED, 0x6F, 0xF3])
GUARD_XOR = bytes([0xB3, 0xC9, 0x53, 0xA0, 0x69, 0x13, 0xAD, 0x4D])

# Current public-channel IDs and accepted anonymous definition.
CHANNELS = {
    "cctv1": ("2024078201", "600001859", "fhd"),
    "cctv2": ("2024075401", "600001800", "fhd"),
    "cctv3": ("2024068501", "600001801", "fhd"),
    "cctv4": ("2029797101", "600001814", "fhd"),
    "cctv5": ("2024078401", "600001818", "fhd"),
    "cctv5plus": ("2024078001", "600001817", "fhd"),
    "cctv6": ("2013693901", "600108442", "fhd"),
    "cctv7": ("2024072001", "600004092", "fhd"),
    "cctv8": ("2029793001", "600001803", "fhd"),
    "cctv9": ("2024078601", "600004078", "fhd"),
    "cctv10": ("2024078701", "600001805", "fhd"),
    "cctv11": ("2027248701", "600001806", "fhd"),
    "cctv12": ("2027248801", "600001807", "fhd"),
    "cctv13": ("2029797201", "600001811", "fhd"),
    "cctv14": ("2027248901", "600001809", "fhd"),
    "cctv15": ("2027249001", "600001815", "fhd"),
    "cctv16": ("2027249101", "600098637", "fhd"),
    "cctv17": ("2027249401", "600001810", "fhd"),
}


def _u32(value: int) -> int:
    return value & 0xFFFFFFFF


def _tea_block(block: bytes, key: bytes) -> bytes:
    y, z = struct.unpack(">II", block)
    k = struct.unpack(">IIII", key)
    total = 0
    for _ in range(16):
        total = _u32(total + 0x9E3779B9)
        y = _u32(y + (((z << 4) + k[0]) ^ (z + total) ^ ((z >> 5) + k[1])))
        z = _u32(z + (((y << 4) + k[2]) ^ (y + total) ^ ((y >> 5) + k[3])))
    return struct.pack(">II", y, z)


def _tea_packet(data: bytes, key: bytes) -> bytes:
    pad = (8 - ((len(data) + 10) % 8)) % 8
    first = bytes([(os.urandom(1)[0] & 0xF8) | pad])
    plain = first + os.urandom(pad) + os.urandom(2) + data + bytes(7)
    out: list[bytes] = []
    previous_plain = bytes(8)
    previous_cipher = bytes(8)
    for offset in range(0, len(plain), 8):
        source = plain[offset:offset + 8]
        mixed = bytes(a ^ b for a, b in zip(source, previous_cipher))
        encrypted = _tea_block(mixed, key)
        cipher = bytes(a ^ b for a, b in zip(encrypted, previous_plain))
        out.append(cipher)
        previous_plain = mixed
        previous_cipher = cipher
    return b"".join(out)


def _checksum(data: bytes) -> int:
    value = 0
    for byte in data:
        value = (0x83 * value + byte) & 0x7FFFFFFF
    return value


def _lp(value: Any) -> bytes:
    data = value if isinstance(value, bytes) else str(value).encode()
    return struct.pack(">H", len(data)) + data


def _guard(timestamp: int, guid: str) -> str:
    body = struct.pack(">I", timestamp)
    body += _lp(str(guid)[-5:])
    body += _lp("null"[-5:])
    body += _lp("null"[-5:])
    body += _lp("-1")
    plain = _lp(body)
    encrypted = _tea_packet(plain, GUARD_TEA_KEY) + struct.pack(">I", _checksum(plain))
    encrypted = bytes(v ^ GUARD_XOR[i % 8] for i, v in enumerate(encrypted))
    return encrypted.hex().upper()


def _custom_b64(data: bytes) -> str:
    return base64.b64encode(data).decode().replace("+", "_").replace("/", "-").rstrip("=")


def _make_ckey(channel_id: str) -> tuple[str, str, int, str]:
    timestamp = int(time.time())
    guid = uuid.uuid4().hex
    guard = _guard(timestamp, guid)
    uid = os.urandom(4).hex().upper()

    body = bytes.fromhex("0000004200000004000004d2")
    body += struct.pack(">II", PLATFORM, 0)
    body += struct.pack(">I", timestamp)
    for value in (
        "dcgh",
        "_zj1A5Gh6QYcxWjIUGos2w==",
        APP_VERSION,
        channel_id,
        guid,
    ):
        body += _lp(value)
    body += struct.pack(">II", 1, 1)
    for value in (
        uid,
        "nil",
        "57eab0c4-2c58-44c6-8ae9-dd2757525dc5",
        "nil",
        "v0.1.000",
        "com.cctv.yangshipin.app.iphone",
        str(PLATFORM),
        "ex_json_bus",
        "ex_json_vs",
        guard,
    ):
        body += _lp(value)

    packet = struct.pack(">H", len(body)) + body
    packet = bytearray(packet)
    struct.pack_into(">I", packet, 18, _checksum(packet))
    encrypted = _tea_packet(bytes(packet), CKEY_TEA_KEY) + struct.pack(">I", _checksum(bytes(packet)))
    encrypted = bytes(v ^ CKEY_XOR[i % 16] for i, v in enumerate(encrypted))
    return f"--01{_custom_b64(encrypted)}", guid, timestamp, f"{str(uuid.uuid4()).upper()}_{PLATFORM}"


def _extract_urls(payload: dict[str, Any]) -> list[str]:
    values: list[str] = [payload.get("playurl", "")]
    backups = payload.get("backurl_list", payload.get("backurl"))
    if isinstance(backups, list):
        for item in backups:
            values.append(item if isinstance(item, str) else (item or {}).get("url") or (item or {}).get("playurl"))
    elif isinstance(backups, str):
        values.extend(backups.replace(";", ",").split(","))

    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.startswith("https://"):
            continue
        host = value.split("/", 3)[2].lower()
        if host == "cctv.cn" or host.endswith(".cctv.cn") or host == "ysp.cctv.cn" or host.endswith(".ysp.cctv.cn") or host == "cctv.com" or host.endswith(".cctv.com"):
            if value not in result:
                result.append(value)
    return result


def _manifest_url(url: str, timeout: int) -> str:
    response = requests.get(
        url,
        headers={
            "Accept": "application/vnd.apple.mpegurl,application/json,*/*",
            "Referer": "https://live.cctv.cn/",
            "User-Agent": "qqlive",
        },
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()
    text = response.text
    if not text.lstrip().startswith("#EXTM3U"):
        raise ValueError("response is not an HLS manifest")
    # Resolve a master playlist to its first variant.
    lines = [line.strip() for line in text.splitlines()]
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            for candidate in lines[i + 1:]:
                if candidate and not candidate.startswith("#"):
                    from urllib.parse import urljoin
                    return urljoin(response.url or url, candidate)
    return response.url or url


def resolve(channel_id: str, timeout: int = 12) -> str | None:
    channel = CHANNELS.get(channel_id)
    if not channel:
        return None

    live_pid, cnlid, defn = channel
    ckey, guid, timestamp, flowid = _make_ckey(cnlid)
    capability = base64.b64encode(b"H(30:1080,60:1080|30:1080,60:1080)").decode()
    params = {
        "atime": "120",
        "livepid": live_pid,
        "cnlid": cnlid,
        "appVer": APP_VERSION,
        "app_version": "300090",
        "caplv": "1",
        "cmd": "2",
        "defn": defn,
        "device": "iPhone",
        "encryptVer": "4.2",
        "getpreviewinfo": "0",
        "hevclv": "0",
        "lang": "zh-Hans_CN",
        "livequeue": "0",
        "logintype": "1",
        "nettype": "1",
        "newnettype": "1",
        "newplatform": str(PLATFORM),
        "platform": str(PLATFORM),
        "sdtfrom": "v3021",
        "spacode": "23",
        "spaudio": "1",
        "spdemuxer": "6",
        "spdrm": "2",
        "spdynamicrange": "1",
        "spflv": "1",
        "spflvaudio": "1",
        "sphdrfps": "60",
        "sphttps": "1",
        "spvcode": capability,
        "spvideo": "4",
        "stream": "1",
        "system": "1",
        "sysver": "ios18.2.1",
        "uhd_flag": "0",
        "cKey": ckey,
        "guid": guid,
        "fntick": str(timestamp),
        "flowid": flowid,
        "playbacktime": "0",
    }

    response = requests.get(
        API_URL,
        params=params,
        headers={"User-Agent": "qqlive", "Accept": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if int(payload.get("iretcode", -1)) != 0:
        raise ValueError(payload.get("errinfo") or f"official API returned {payload.get('iretcode')}")

    urls = _extract_urls(payload)
    if not urls:
        raise ValueError("official API returned no usable HLS URL")

    last_error: Exception | None = None
    for url in urls:
        try:
            return _manifest_url(url, timeout)
        except Exception as exc:
            last_error = exc

    raise ValueError(f"official HLS manifest unavailable: {last_error}")
