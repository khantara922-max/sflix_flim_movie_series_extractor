"""
SFlix Movie-Series HTML Scraper
=================================
Scrapes movie detail URLs directly from the SSR HTML pages at
https://sflix.film/movie-series using requests + BeautifulSoup.

The page renders all <a href="/detail/..."> links server-side, so no
browser or internal API access is needed. We paginate by appending
?page=N to the URL.

Saves results to  full_movie_urls.txt

Requirements:
    pip install requests beautifulsoup4

Usage:
    python sflix_scraper.py
    python sflix_scraper.py --start 1 --end 50
    python sflix_scraper.py --out my_movies.txt
"""

import argparse
import re
import sys
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_URL    = "https://sflix.film"
LIST_URL    = "https://sflix.film/movie-series"
DEFAULT_OUT = "full_movie_urls.txt"
DELAY       = 1.5   # seconds between page requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://sflix.film/",
}


# ── Scraping helpers ──────────────────────────────────────────────────────────

def fetch_page_html(session: requests.Session, page: int) -> Optional[str]:
    """Fetch raw HTML for a given page number."""
    url = LIST_URL if page == 1 else f"{LIST_URL}?page={page}"
    try:
        resp = session.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as e:
        print(f"    [!] Request error on page {page}: {e}", file=sys.stderr)
        return None


def parse_movie_urls(html: str) -> list:
    """
    Extract all /detail/... href values from the page HTML.
    Works on both BeautifulSoup parsing and regex fallback.
    """
    urls = []
    seen = set()

    # Primary: BeautifulSoup
    try:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=re.compile(r"/detail/")):
            href = a.get("href", "")
            # strip query params and fragments
            path = href.split("?")[0].split("#")[0]
            if path and path not in seen:
                seen.add(path)
                full = path if path.startswith("http") else BASE_URL + path
                urls.append(full)
    except Exception:
        pass

    # Fallback: regex if BS4 finds nothing
    if not urls:
        for match in re.finditer(r'href="(/detail/[^"?#]+)', html):
            path = match.group(1)
            if path not in seen:
                seen.add(path)
                urls.append(BASE_URL + path)

    return urls


def has_next_page(html: str, current_page: int) -> bool:
    """
    Check if there is a next page by looking for a page=N+1 link
    or a 'see more' / pagination element in the HTML.
    """
    next_page = current_page + 1
    return (
        f"page={next_page}" in html
        or "see more" in html.lower()
        or "see-more" in html.lower()
        or "loadmore" in html.lower()
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def run(start: int, end: Optional[int], out: str):
    all_urls: dict = {}   # {url: True} — ordered + deduplicated

    print("SFlix HTML Movie Scraper  (requests + BeautifulSoup)")
    print(f"  Source   : {LIST_URL}")
    print(f"  Output   : {out}")
    print()

    session = requests.Session()
    page    = start
    consecutive_empty = 0

    while True:
        # stop at user-supplied end page
        if end is not None and page > end:
            break

        print(f"  Page {page} ...", end=" ", flush=True)

        html = fetch_page_html(session, page)

        if html is None:
            print("fetch failed — skipping")
            consecutive_empty += 1
            if consecutive_empty >= 3:
                print("  3 consecutive failures — stopping.")
                break
            page += 1
            time.sleep(DELAY)
            continue

        urls = parse_movie_urls(html)

        if not urls:
            print("no URLs found — stopping.")
            consecutive_empty += 1
            if consecutive_empty >= 2:
                break
            page += 1
            time.sleep(DELAY)
            continue

        consecutive_empty = 0
        new = 0
        for u in urls:
            if u not in all_urls:
                all_urls[u] = True
                new += 1

        print(f"{len(urls)} found (+{new} new)  total: {len(all_urls)}")

        # stop if no more pages
        if not has_next_page(html, page):
            print("  No next page detected — done.")
            break

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
        description="Scrape SFlix movie URLs from HTML pages (no browser needed)."
    )
    p.add_argument("--start", type=int, default=1,
                   help="First page (default: 1)")
    p.add_argument("--end",   type=int, default=None,
                   help="Last page inclusive (default: auto-detect)")
    p.add_argument("--out",   type=str, default=DEFAULT_OUT,
                   help=f"Output file (default: {DEFAULT_OUT})")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.end is not None and args.start > args.end:
        print("Error: --start must be <= --end", file=sys.stderr)
        sys.exit(1)
    run(args.start, args.end, args.out)
