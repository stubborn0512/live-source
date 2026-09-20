"""Generate standard M3U playlists."""

from __future__ import annotations

from typing import Iterable


def generate(items: Iterable[dict]) -> str:
    lines = ["#EXTM3U"]

    for item in items:
        lines.append(
            f'#EXTINF:-1 tvg-id="{item["id"]}" '
            f'group-title="CCTV",{item["name"]}'
        )
        lines.append(item["url"])

    return "\n".join(lines) + "\n"
