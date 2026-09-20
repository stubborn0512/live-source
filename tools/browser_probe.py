import json
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

options = Options()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1440,900")
options.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})

driver = webdriver.Chrome(options=options)
try:
    driver.get("https://tv.cctv.com/live/cctv1/index.shtml")
    time.sleep(15)
    print("PAGE_TITLE:", driver.title)
    print("CURRENT_URL:", driver.current_url)
    logs = driver.get_log("performance")
    seen = set()
    for item in logs:
        try:
            msg = json.loads(item["message"])["message"]
        except Exception:
            continue
        if msg.get("method") != "Network.requestWillBeSent":
            continue
        url = msg.get("params", {}).get("request", {}).get("url", "")
        if any(k in url.lower() for k in ("ysp.cctv.cn", "yangshipin", "bklive", "m3u8", "liveurl", "cctv.cn")):
            if url not in seen:
                seen.add(url)
                print("NETWORK:", url)
    for item in driver.get_log("browser"):
        print("BROWSER:", item.get("level"), item.get("message"))
finally:
    driver.quit()
