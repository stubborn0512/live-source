#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "output" / "status.json"
POOL = ROOT / "output" / "source-pool.json"
METRICS = ROOT / "output" / "region-metrics.json"
OUT = ROOT / "output" / "best.m3u"


def sid(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def metric_score(stats):
    if not isinstance(stats, dict):
        return None

    startup = stats.get("startup_ewma_ms")
    probe = stats.get("probe_ewma_ms")
    latency = startup if startup is not None else probe
    if latency is None:
        return None

    samples = int(stats.get("samples", 0) or 0) + int(stats.get("probe_samples", 0) or 0)
    successes = int(stats.get("successes", 0) or 0) + int(stats.get("probe_successes", 0) or 0)
    failures = int(stats.get("startup_failures", 0) or 0) + int(stats.get("errors", 0) or 0)
    probe_failures = int(stats.get("probe_failures", 0) or 0)

    failure_penalty = min(30000.0, 6000.0 * failures / max(1, samples))
    probe_failure_penalty = min(20000.0, 10000.0 * probe_failures / max(1, int(stats.get("probe_samples", 0) or 0)))
    success_bonus = 0.0 if successes > 0 else 2000.0
    return float(latency) + failure_penalty + probe_failure_penalty + success_bonus


def main():
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    metrics = json.loads(METRICS.read_text(encoding="utf-8")) if METRICS.exists() else {}

    pool_channels = pool.get("channels", {}) if isinstance(pool, dict) else {}
    metric_channels = metrics.get("channels", {}) if isinstance(metrics, dict) else {}

    lines = ["#EXTM3U"]

    for channel in status.get("channels", []):
        cid = str(channel.get("id") or "").strip()
        name = str(channel.get("name") or cid).strip()
        if not cid:
            continue

        candidates = {}
        for item in channel.get("sources", []):
            if isinstance(item, dict) and item.get("url"):
                candidates[str(item["url"])] = item

        for item in pool_channels.get(cid, []):
            if isinstance(item, dict) and item.get("url"):
                candidates.setdefault(str(item["url"]), item)

        ranked = []
        for url, item in candidates.items():
            if not bool(item.get("available", item.get("ok", True))):
                continue

            static = float(item.get("response_seconds") or (item.get("last_result") or {}).get("response_seconds") or 9999)
            source_sid = sid(url)

            scores = []
            channel_metrics = []
            for region_map in metric_channels.values():
                if not isinstance(region_map, dict):
                    continue
                cm = region_map.get(cid, {})
                if not isinstance(cm, dict):
                    continue
                stat = cm.get(source_sid)
                if isinstance(stat, dict):
                    score = metric_score(stat)
                    if score is not None:
                        samples = int(stat.get("samples", 0) or 0) + int(stat.get("probe_samples", 0) or 0)
                        channel_metrics.append((score, max(1, samples)))

            if channel_metrics:
                weighted = sum(score * weight for score, weight in channel_metrics) / sum(weight for _, weight in channel_metrics)
                score = weighted
            else:
                score = static * 1000.0

            ranked.append((score, static, url))

        if not ranked:
            continue

        ranked.sort(key=lambda row: (row[0], row[1], row[2]))
        selected = ranked[0][2]
        group = "CCTV" if cid.startswith("cctv") else "卫视"

        lines.append(f'#EXTINF:-1 tvg-id="{cid}" tvg-name="{name}" group-title="{group}",{name}')
        lines.append(selected)

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"generated {OUT}")


if __name__ == "__main__":
    main()
