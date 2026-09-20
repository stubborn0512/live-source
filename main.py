from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from checker.health import check
from generator.m3u import generate
from providers.cctv import resolve_candidates

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def main() -> None:
    cctv = CONFIG["cctv"]["channels"]
    checker = CONFIG["checker"]

    playlist_items = []
    statuses = []

    for channel in cctv:
        channel_id = channel["id"]
        print(f"[resolve] {channel_id}")

        try:
            candidates = resolve_candidates(
                channel_id, timeout=checker["timeout_seconds"]
            )
            candidates = list(reversed(candidates))
        except Exception as exc:
            statuses.append({
                "id": channel_id,
                "name": channel["name"],
                "ok": False,
                "1080p": False,
                "error": str(exc),
            })
            print(f"  resolve failed: {exc}")
            continue

        if not candidates:
            statuses.append({
                "id": channel_id,
                "name": channel["name"],
                "ok": False,
                "1080p": False,
                "error": "no HLS URL returned",
            })
            print("  no HLS URL")
            continue

        def probe_one(candidate_url):
            return candidate_url, check(
                candidate_url,
                timeout=checker["probe_seconds"],
                min_width=checker["min_width"],
                min_height=checker["min_height"],
            )

        results = []
        with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
            futures = [pool.submit(probe_one, u) for u in candidates]
            for future in as_completed(futures):
                candidate_url, probe_result = future.result()
                print(
                    f"  probe: {candidate_url} -> "
                    f"{probe_result.get('width')}x{probe_result.get('height')} "
                    f"ok={probe_result.get('ok')}"
                )
                results.append((candidate_url, probe_result))

        chosen = next(
            ((u, r) for u, r in results if r.get("ok") and r.get("1080p")),
            None,
        )
        if chosen:
            url, result = chosen
        else:
            url, result = max(
                results,
                key=lambda item: (
                    int(item[1].get("ok", False)),
                    int(item[1].get("width") or 0) * int(item[1].get("height") or 0),
                ),
            )

        status = {
            "id": channel_id,
            "name": channel["name"],
            "url": url,
            **result,
        }
        statuses.append(status)

        if result["ok"] and result["1080p"]:
            playlist_items.append({
                "id": channel_id,
                "name": channel["name"],
                "url": url,
            })
            print(
                f'  OK {result.get("width")}x{result.get("height")} '
                f'{result.get("fps", "")}'
            )
        else:
            print(
                f'  rejected: ok={result["ok"]}, '
                f'resolution={result.get("width")}x{result.get("height")}'
            )

    output = ROOT / "output"
    output.mkdir(exist_ok=True)

    (output / "1080p.m3u").write_text(
        generate(playlist_items),
        encoding="utf-8",
    )

    (output / "status.json").write_text(
        json.dumps(
            {
                "generated_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
                "count": len(playlist_items),
                "channels": statuses,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Generated {len(playlist_items)} verified 1080p channels.")


if __name__ == "__main__":
    main()
