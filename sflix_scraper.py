"""
SFlix Movie-Series API Extractor
==================================
Calls the SFlix internal REST API directly with requests — no browser needed.

Endpoint:
  GET https://sflix.film/wefeed-h5api-bff/subject/filter
  ?subjectType=MOVIE&pageNum={page}&pageSize=36&sortField=LATEST

Saves results to  full_movie_urls.txt

Requirements:
    pip install requests

Usage:
    python sflix_scraper.py                        # all pages (auto-stops when empty)
    python sflix_scraper.py --start 1 --end 50
    python sflix_scraper.py --out my_movies.txt
"""

import argparse
import sys
import time
from typing import Optional

import requests

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_URL    = "https://sflix.film"
API_URL     = "https://sflix.film/wefeed-h5api-bff/subject/filter"
DEFAULT_OUT = "full_movie_urls.txt"
PAGE_SIZE   = 36
DELAY       = 1.0   # seconds between requests — be polite

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://sflix.film/movie-series",
    "Origin":          "https://sflix.film",
}


# ── API helpers ───────────────────────────────────────────────────────────────

def fetch_page(session: requests.Session, page: int) -> Optional[dict]:
    """Fetch one page from the filter API. Returns parsed JSON or None on error."""
    params = {
        "subjectType": "MOVIE",
        "pageNum":     page,
        "pageSize":    PAGE_SIZE,
        "sortField":   "LATEST",
    }
    try:
        resp = session.get(API_URL, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(f"    [!] Request error on page {page}: {e}", file=sys.stderr)
        return None
    except ValueError:
        print(f"    [!] JSON decode error on page {page}", file=sys.stderr)
        return None


def parse_urls(data: dict) -> list:
    """Extract full movie detail URLs from an API response."""
    urls = []
    # try both known response shapes
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


def get_total_pages(data: dict) -> Optional[int]:
    """Try to read total page count from the API pager info."""
    pager = data.get("data", {}).get("pager", {})
    total_items = pager.get("total") or pager.get("totalCount")
    if total_items:
        return (int(total_items) + PAGE_SIZE - 1) // PAGE_SIZE
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def run(start: int, end: Optional[int], out: str):
    all_urls: dict = {}   # {url: True} — ordered, deduplicated

    print("SFlix API Movie Extractor  (no browser needed)")
    print(f"  Endpoint : {API_URL}")
    print(f"  Output   : {out}")
    print()

    session = requests.Session()
    page    = start
    total   = None   # discovered from first response

    while True:
        # stop if we've hit the user-supplied end page
        if end is not None and page > end:
            break

        print(f"  Page {page}", end="", flush=True)
        if total:
            print(f"/{total}", end="", flush=True)
        print(" ...", end=" ", flush=True)

        data = fetch_page(session, page)

        if data is None:
            print("error — skipping")
            page += 1
            time.sleep(DELAY)
            continue

        # discover total pages from first successful response
        if total is None:
            total = get_total_pages(data)
            if total:
                print(f"(total pages: {total}) ", end="", flush=True)
                # cap end to actual total if not user-supplied
                if end is None:
                    end = total

        urls = parse_urls(data)

        if not urls:
            print("empty — stopping.")
            break

        new = 0
        for u in urls:
            if u not in all_urls:
                all_urls[u] = True
                new += 1

        print(f"{len(urls)} items (+{new} new)  total: {len(all_urls)}")

        page += 1
        time.sleep(DELAY)

    # ── Save ──────────────────────────────────────────────────────────────────
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
        description="Extract SFlix movie URLs via direct API calls (no browser)."
    )
    p.add_argument(
        "--start", type=int, default=1,
        help="First page to fetch (default: 1)"
    )
    p.add_argument(
        "--end", type=int, default=None,
        help="Last page to fetch inclusive (default: auto — stops when API returns empty)"
    )
    p.add_argument(
        "--out", type=str, default=DEFAULT_OUT,
        help=f"Output file (default: {DEFAULT_OUT})"
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.end is not None and args.start > args.end:
        print("Error: --start must be <= --end", file=sys.stderr)
        sys.exit(1)
    run(args.start, args.end, args.out)
