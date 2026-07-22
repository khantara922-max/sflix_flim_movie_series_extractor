"""
SFlix Movie-Series Browser Extractor
======================================
Loads https://sflix.film/movie-series in a headless Chrome browser (Selenium),
scrolls / clicks "See More" to trigger lazy-loading, intercepts every API call
to  /wefeed-h5api-bff/subject/filter  via the Chrome DevTools Protocol (CDP)
Network domain, and collects all movie detail URLs.

Saves results to  full_movie_urls.txt

Requirements:
    pip install selenium

Usage:
    python sflix_scraper.py
    python sflix_scraper.py --start 15 --end 26
    python sflix_scraper.py --out my_movies.txt
"""

import argparse
import json
import sys
import time
import threading
from collections import OrderedDict
from typing import Optional

# ── Selenium / CDP imports ────────────────────────────────────────────────────
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# ── Configuration ─────────────────────────────────────────────────────────────
TARGET_URL     = "https://sflix.film/movie-series"
BASE_URL       = "https://sflix.film"
API_FILTER     = "/wefeed-h5api-bff/subject/filter"
DEFAULT_OUT    = "full_movie_urls.txt"
DEFAULT_START  = 1
DEFAULT_END    = 250
SCROLL_PAUSE   = 1.5
CLICK_PAUSE    = 2.5
PAGE_LOAD_WAIT = 15
BODY_RETRY     = 3
BODY_RETRY_DELAY = 0.5


# ── CDP network interceptor ────────────────────────────────────────────────────

class NetworkCapture:
    def __init__(self, driver: webdriver.Chrome, keyword: str):
        self.driver  = driver
        self.keyword = keyword
        self._pending: list = []
        self._processed_ids: set = set()
        self._lock = threading.Lock()

    def start(self):
        self.driver.execute_cdp_cmd("Network.enable", {})

    def drain_pending(self) -> list:
        with self._lock:
            items = list(self._pending)
            self._pending.clear()
        return items

    def mark_processed(self, request_id: str):
        with self._lock:
            self._processed_ids.add(request_id)

    def poll(self):
        try:
            logs = self.driver.get_log("performance")
        except Exception:
            return
        for entry in logs:
            try:
                msg = json.loads(entry["message"])["message"]
            except Exception:
                continue
            method = msg.get("method", "")
            params = msg.get("params", {})
            if method == "Network.responseReceived":
                url = params.get("response", {}).get("url", "")
                if self.keyword in url:
                    req_id = params.get("requestId")
                    with self._lock:
                        if req_id and req_id not in self._processed_ids:
                            self._pending.append({
                                "requestId": req_id,
                                "url"      : url,
                                "status"   : params.get("response", {}).get("status", 0),
                            })


# ── URL extraction helpers ────────────────────────────────────────────────────

def fetch_response_body(driver: webdriver.Chrome, request_id: str) -> Optional[dict]:
    for attempt in range(BODY_RETRY):
        try:
            result = driver.execute_cdp_cmd(
                "Network.getResponseBody", {"requestId": request_id}
            )
            body = result.get("body", "")
            return json.loads(body)
        except json.JSONDecodeError:
            return None
        except Exception:
            if attempt < BODY_RETRY - 1:
                time.sleep(BODY_RETRY_DELAY)
    return None


def parse_items_from_page(data: dict) -> list:
    urls = []
    items = (
        data.get("data", {}).get("items", [])
        or data.get("data", {}).get("subjectList", {}).get("items", [])
    )
    for item in items:
        path = item.get("detailPath") or item.get("detailpath", "")
        if not path:
            continue
        if path.startswith("http"):
            urls.append(path)
        else:
            if not path.startswith("/"):
                path = "/detail/" + path
            urls.append(BASE_URL + path)
    return urls


def extract_urls_from_dom(driver: webdriver.Chrome) -> list:
    anchors = driver.find_elements(By.CSS_SELECTOR, "a[href*='/detail/']")
    urls = []
    for a in anchors:
        href = a.get_attribute("href") or ""
        if "/detail/" in href:
            urls.append(href.split("?")[0])
    return urls


# ── "See More" button clicker / scroller ─────────────────────────────────────

def click_see_more_or_scroll(driver: webdriver.Chrome) -> bool:
    lc = "translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')"
    selectors = [
        f"//div[contains({lc},'see more')]",
        "//div[contains(@class,'see-more')]",
        f"//button[contains({lc},'see more')]",
        f"//span[contains({lc},'see more')]",
    ]
    for sel in selectors:
        try:
            btn = driver.find_element(By.XPATH, sel)
            driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            time.sleep(0.4)
            driver.execute_script("arguments[0].click();", btn)
            return True
        except Exception:
            pass

    old_height = driver.execute_script("return document.body.scrollHeight")
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(SCROLL_PAUSE)
    new_height = driver.execute_script("return document.body.scrollHeight")
    return new_height != old_height


# ── Browser setup ─────────────────────────────────────────────────────────────

def build_driver() -> webdriver.Chrome:
    opts = Options()
    # Headless mode for GitHub Actions / CI environments
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1440,900")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--remote-debugging-port=9222")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    try:
        driver = webdriver.Chrome(options=opts)
    except Exception as e:
        print(f"[!] Could not start Chrome: {e}", file=sys.stderr)
        print("    Make sure chromedriver is installed.", file=sys.stderr)
        sys.exit(1)
    return driver


# ── Main extraction logic ──────────────────────────────────────────────────────

def run(start: int, end: int, out: str):
    total_pages = end - start + 1
    all_urls: OrderedDict = OrderedDict()

    print("SFlix Browser Movie Extractor")
    print(f"  Mode      : headless (GitHub Actions)")
    print(f"  Pages     : {start} -> {end}  ({total_pages} pages)")
    print(f"  Output    : {out}")
    print()

    driver = build_driver()
    capture = NetworkCapture(driver, API_FILTER)
    capture.start()

    try:
        print(f"  [1/{total_pages}] Loading {TARGET_URL} ...", end=" ", flush=True)
        driver.get(TARGET_URL)

        try:
            WebDriverWait(driver, PAGE_LOAD_WAIT).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "a[href*='/detail/']")
                )
            )
        except TimeoutException:
            print("timeout waiting for page to load!")

        time.sleep(2)

        if start == 1:
            dom_urls = extract_urls_from_dom(driver)
            for u in dom_urls:
                if u not in all_urls:
                    all_urls[u] = True
            print(f"DOM scrape -> {len(dom_urls)} URLs  (total: {len(all_urls)})")

        current_api_page = max(start, 2)
        pages_done       = 1 if start == 1 else 0

        while pages_done < total_pages:
            capture.poll()

            for resp in capture.drain_pending():
                capture.mark_processed(resp["requestId"])
                body = fetch_response_body(driver, resp["requestId"])
                if not body:
                    continue
                urls = parse_items_from_page(body)
                new_count = 0
                for u in urls:
                    if u not in all_urls:
                        all_urls[u] = True
                        new_count += 1
                if urls:
                    pg_label = pages_done + 1
                    print(
                        f"  [{pg_label}/{total_pages}] "
                        f"API page {current_api_page} -> "
                        f"{len(urls)} items (+{new_count} new)  "
                        f"total: {len(all_urls)}"
                    )
                    current_api_page += 1
                    pages_done += 1
                    if pages_done >= total_pages:
                        break

            if pages_done >= total_pages:
                break

            action = click_see_more_or_scroll(driver)
            time.sleep(CLICK_PAUSE if action else SCROLL_PAUSE)

        # final poll
        time.sleep(1.5)
        capture.poll()
        for resp in capture.drain_pending():
            capture.mark_processed(resp["requestId"])
            body = fetch_response_body(driver, resp["requestId"])
            if not body:
                continue
            for u in parse_items_from_page(body):
                if u not in all_urls:
                    all_urls[u] = True

    except KeyboardInterrupt:
        print("\n[!] Interrupted by user.")
    except WebDriverException as e:
        print(f"\n[!] Browser error: {e}", file=sys.stderr)
    finally:
        driver.quit()

    url_list = list(all_urls.keys())
    with open(out, "w", encoding="utf-8") as f:
        for u in url_list:
            f.write(u + "\n")

    print()
    print(f"Done. {len(url_list)} unique movie URLs saved to '{out}'.")
    return url_list


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Extract SFlix movie URLs using headless Chrome (Selenium + CDP)."
    )
    p.add_argument("--start", type=int, default=DEFAULT_START,
                   help=f"First page (default: {DEFAULT_START})")
    p.add_argument("--end",   type=int, default=DEFAULT_END,
                   help=f"Last page inclusive (default: {DEFAULT_END})")
    p.add_argument("--out",   type=str, default=DEFAULT_OUT,
                   help=f"Output file (default: {DEFAULT_OUT})")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.start > args.end:
        print("Error: --start must be <= --end", file=sys.stderr)
        sys.exit(1)
    run(args.start, args.end, args.out)
