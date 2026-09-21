from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

from checker.health import check, check_static
from checker.identity import identify_cctv
from generator.m3u import generate
from providers.cctv import resolve_candidates

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _verified_sort_key(item: tuple[str, dict, int]) -> tuple[int, float, int]:
    url, result, candidate_index = item
    width = int(result.get("width") or 0)
    height = int(result.get("height") or 0)
    area = width * height
    return (-area, float(result.get("response_seconds") or 9999), candidate_index)


def _pick_two_sources(
    candidates: list[str],
    result_by_url: dict[str, dict],
) -> list[tuple[str, dict]]:
    verified = []
    for index, url in enumerate(candidates):
        result = result_by_url.get(url)
        if result and result.get("ok") and result.get("1080p") and result.get("static") is not True:
            verified.append((url, result, index))

    verified.sort(key=_verified_sort_key)
    if not verified:
        return []

    # Prefer source diversity: the backup should live on a different host
    # when the public pool provides one.
    first = verified[0]
    selected = [first]
    first_host = _host(first[0])

    for candidate in verified[1:]:
        if _host(candidate[0]) != first_host:
            selected.append(candidate)
            break

    if len(selected) < 2:
        for candidate in verified[1:]:
            if candidate[0] != selected[0][0]:
                selected.append(candidate)
                break

    return [(url, result) for url, result, _ in selected[:2]]


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

    static_cfg = checker.get("static_check", {})
    max_workers = min(len(candidates), checker.get("max_probe_workers", 10))

    # Phase 1: cheap, authoritative media probe across the candidate pool.
    # Static-frame detection is intentionally deferred to only the best HD
    # candidates so a large public source pool does not multiply runtime.
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                check,
                url,
                timeout=checker["probe_seconds"],
                min_width=checker["min_width"],
                min_height=checker["min_height"],
                static_check=False,
            ): url
            for url in candidates
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "ok": False,
                    "1080p": False,
                    "static": None,
                    "error": str(exc),
                }
            results.append((url, result))

    result_by_url = {url: result for url, result in results}

    # Phase 2: static-image filtering only on the best four verified 1080p
    # candidates. A timeout/error in this secondary test is non-fatal.
    if static_cfg.get("enabled", False):
        hd_candidates = []
        for index, url in enumerate(candidates):
            result = result_by_url.get(url)
            if result and result.get("ok") and result.get("1080p"):
                hd_candidates.append((url, result, index))
        hd_candidates.sort(key=_verified_sort_key)
        top_hd = [(url, result) for url, result, _ in hd_candidates[:4]]
        if top_hd:
            with ThreadPoolExecutor(max_workers=min(len(top_hd), 4)) as pool:
                futures = {
                    pool.submit(
                        check_static,
                        url,
                        duration_seconds=int(static_cfg.get("duration_seconds", 6)),
                        freeze_seconds=int(static_cfg.get("freeze_seconds", 4)),
                    ): url
                    for url, _ in top_hd
                }
                for future in as_completed(futures):
                    url = futures[future]
                    try:
                        static = future.result()
                    except Exception:
                        static = None
                    result_by_url[url]["static"] = static
                    if static is True:
                        result_by_url[url]["ok"] = False
                        result_by_url[url]["1080p"] = False

    # Phase 3: visual identity check. Resolution alone is not enough:
    # public relays can serve another CCTV channel behind a misleading URL.
    if channel_id.startswith("cctv"):
        hd_for_identity = []
        for index, url in enumerate(candidates):
            result = result_by_url.get(url)
            if result and result.get("ok") and result.get("1080p") and result.get("static") is not True:
                hd_for_identity.append((url, result, index))
        hd_for_identity.sort(key=_verified_sort_key)
        for url, _, _ in hd_for_identity[:4]:
            identity = identify_cctv(url, channel_id, timeout=checker["probe_seconds"])
            result_by_url[url]["identity"] = identity.get("identity")
            result_by_url[url]["identity_ocr"] = identity.get("ocr", "")
            if identity.get("identity") == "wrong":
                result_by_url[url]["ok"] = False
                result_by_url[url]["1080p"] = False

    verified = _pick_two_sources(candidates, result_by_url)

    if verified:
        sources = [
            {
                "url": url,
                "host": _host(url),
                **result,
            }
            for url, result in verified
        ]
        primary_url = verified[0][0]
        status = {
            "id": channel_id,
            "name": name,
            "url": primary_url,
            "sources": sources,
            "source_count": len(sources),
            "source_hosts": [source["host"] for source in sources],
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
            -float(item[1].get("response_seconds") or 9999),
        ),
    )
    return {"id": channel_id, "name": name, "url": url, **result}, None


def main() -> None:
    channels = CONFIG["cctv"]["channels"] + CONFIG.get("weishi", {}).get("channels", [])
    checker = CONFIG["checker"]

    statuses_by_id = {}
    playlist_items_by_id = {}

    with ThreadPoolExecutor(max_workers=checker.get("channel_workers", 8)) as pool:
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
