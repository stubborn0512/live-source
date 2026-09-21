from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from checker.health import check
from generator.m3u import generate
from providers.cctv import resolve_candidates

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def process_channel(channel: dict, checker: dict) -> tuple[dict, dict | None]:
    channel_id = channel["id"]
    name = channel["name"]
    try:
        candidates = resolve_candidates(
            channel_id, timeout=checker["timeout_seconds"], channel_name=name
        )
    except Exception as exc:
        return {
            "id": channel_id, "name": name, "ok": False, "1080p": False,
            "error": str(exc),
        }, None

    if not candidates:
        return {
            "id": channel_id, "name": name, "ok": False, "1080p": False,
            "error": "no HLS candidate returned",
        }, None

    results = []
    with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
        futures = {
            pool.submit(
                check,
                url,
                timeout=checker["probe_seconds"],
                min_width=checker["min_width"],
                min_height=checker["min_height"],
            ): url
            for url in candidates
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"ok": False, "1080p": False, "error": str(exc)}
            results.append((url, result))

    result_by_url = {url: result for url, result in results}

    # Keep up to two distinct, independently verified 1080p sources for each
    # channel. The candidate order already reflects provider/fresh-source
    # priority, so the first two verified URLs become primary + backup.
    verified = [
        (url, result_by_url[url])
        for url in candidates
        if url in result_by_url
        and result_by_url[url].get("ok")
        and result_by_url[url].get("1080p")
    ][:2]

    if verified:
        sources = [
            {"url": url, **result}
            for url, result in verified
        ]
        primary_url = verified[0][0]
        status = {
            "id": channel_id,
            "name": name,
            "url": primary_url,
            "sources": sources,
            "source_count": len(sources),
            **verified[0][1],
        }
        return status, {
            "id": channel_id,
            "name": name,
            "sources": sources,
        }

    url, result = max(
        results,
        key=lambda item: (
            int(item[1].get("ok", False)),
            int(item[1].get("width") or 0) * int(item[1].get("height") or 0),
        ),
    )
    return {"id": channel_id, "name": name, "url": url, **result}, None


def main() -> None:
    channels = CONFIG["cctv"]["channels"] + CONFIG.get("weishi", {}).get("channels", [])
    checker = CONFIG["checker"]

    statuses_by_id = {}
    playlist_items_by_id = {}

    with ThreadPoolExecutor(max_workers=len(channels)) as pool:
        futures = {
            pool.submit(process_channel, channel, checker): channel
            for channel in channels
        }
        for future in as_completed(futures):
            channel = futures[future]
            try:
                status, item = future.result()
            except Exception as exc:
                status = {
                    "id": channel["id"], "name": channel["name"],
                    "ok": False, "1080p": False, "error": str(exc),
                }
                item = None

            statuses_by_id[channel["id"]] = status
            if item:
                playlist_items_by_id[item["id"]] = item
                print(
                    f'[OK] {channel["id"]}: '
                    f'{status.get("width")}x{status.get("height")} '
                    f'({status.get("source_count", 1)} sources)',
                    flush=True,
                )
            else:
                print(
                    f'[NO] {channel["id"]}: '
                    f'{status.get("width")}x{status.get("height")} '
                    f'{status.get("error", "")}',
                    flush=True,
                )

    ordered_statuses = [
        statuses_by_id[channel["id"]]
        for channel in channels
    ]
    playlist_items = [
        playlist_items_by_id[channel["id"]]
        for channel in channels
        if channel["id"] in playlist_items_by_id
    ]

    output = ROOT / "output"
    output.mkdir(exist_ok=True)
    (output / "1080p.m3u").write_text(
        generate(playlist_items), encoding="utf-8"
    )
    (output / "status.json").write_text(
        json.dumps(
            {
                "generated_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
                "count": len(playlist_items),
                "channels": ordered_statuses,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"Generated {len(playlist_items)} verified 1080p channels.",
        flush=True,
    )


if __name__ == "__main__":
    main()
