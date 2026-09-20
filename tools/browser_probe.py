import json
import time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

ROOT = Path(__file__).resolve().parent.parent
CHANNELS = [
    "cctv1", "cctv2", "cctv3", "cctv4", "cctv5", "cctv5plus", "cctv6",
    "cctv7", "cctv8", "cctv9", "cctv10", "cctv11", "cctv12", "cctv13",
    "cctv14", "cctv15", "cctv16", "cctv17",
]

options = Options()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1440,900")
options.add_argument("--autoplay-policy=no-user-gesture-required")
options.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})

driver = webdriver.Chrome(options=options)
resolved = {}
try:
    for channel in CHANNELS:
        # Discard requests from the previous channel before navigation.
        try:
            driver.get_log("performance")
        except Exception:
            pass
        page = f"https://tv.cctv.com/live/{channel}/index.shtml"
        print(f"[browser] {channel} -> {page}", flush=True)
        try:
            driver.get(page)
            time.sleep(10)
            logs = driver.get_log("performance")
            candidates = []
            for item in logs:
                try:
                    msg = json.loads(item["message"])["message"]
                except Exception:
                    continue
                if msg.get("method") != "Network.requestWillBeSent":
                    continue
                url = msg.get("params", {}).get("request", {}).get("url", "")
                low = url.lower()
                if ".m3u8" not in low:
                    continue
                candidates.append(url)
            # Prefer the player manifest with the normal bandwidth range.
            candidates = list(dict.fromkeys(candidates))
            candidates = [u for u in candidates if "kcdnvip.com" in u.lower() or "cntv" in u.lower()]
            candidates.sort(key=lambda u: ("b=200-2100" not in u, "BR=td" in u, len(u)))
            if candidates:
                resolved[channel] = candidates[0]
                print(f"[browser] FOUND {channel}: {candidates[0]}", flush=True)
            else:
                print(f"[browser] NO M3U8 {channel}", flush=True)
        except Exception as exc:
            print(f"[browser] ERROR {channel}: {exc}", flush=True)
finally:
    driver.quit()

out = ROOT / "data" / "resolved.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(resolved, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[browser] resolved {len(resolved)}/{len(CHANNELS)} channels", flush=True)
