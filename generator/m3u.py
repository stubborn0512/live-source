"""Generate standard M3U playlists."""

from __future__ import annotations

from typing import Iterable


def generate(items: Iterable[dict]) -> str:
    lines = ["#EXTM3U"]

    for item in items:
        sources = item.get("sources") or [{"url": item["url"]}]
        for index, source in enumerate(sources, start=1):
            label = item["name"] if len(sources) == 1 else f'{item["name"]} [线路{index}]'
            lines.append(
                f'#EXTINF:-1 tvg-id="{item["id"]}" '
                f'tvg-name="{item["name"]}" '
                f'group-title="CCTV",{label}'
            )
            lines.append(source["url"])

    return "\n".join(lines) + "\n"
