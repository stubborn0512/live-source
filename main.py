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

    verified = next(
        ((url, result) for url, result in results
         if result.get("ok") and result.get("1080p")),
        None,
    )

    if verified:
        url, result = verified
        status = {"id": channel_id, "name": name, "url": url, **result}
        return status, {"id": channel_id, "name": name, "url": url}

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
    playlist_items = []

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
                playlist_items.append(item)
                print(
                    f'[OK] {channel["id"]}: '
                    f'{status.get("width")}x{status.get("height")}',
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
