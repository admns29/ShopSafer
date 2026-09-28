"""Shopee scraper — fetch name/price/reviews from a product link.

Shopee blocks anonymous requests (HTTP 403, error 90309999 — verified).
Working approach: drive the user's own logged-in Chrome via CDP
(remote debugging port 9222) with Playwright, and intercept the page's
own review API responses. Falls back to labelled demo data so the
paste-link flow always works on stage.

Setup (once):
  google-chrome --remote-debugging-port=9222 --user-data-dir=$HOME/.cache/shopeecheck-chrome
  then log into shopee.com.my in that window.
"""
import json
import os
import re
import time

import requests

EXAMPLES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples.json")
CDP_URL = os.getenv("SHOPEECHECK_CDP", "http://localhost:9222")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")


class ScrapeBlocked(Exception):
    pass


class ChromeNotRunning(Exception):
    pass


def parse_shopee_url(url: str):
    """Return (shopid, itemid) from URLs like:
    https://shopee.com.my/Product-Name-i.229615453.10001829818
    """
    m = re.search(r"-i\.(\d+)\.(\d+)", url)
    if not m:
        raise ValueError("URL must look like https://shopee.com.my/...-i.SHOPID.ITEMID")
    return m.group(1), m.group(2)


def chrome_cdp_available() -> bool:
    try:
        r = requests.get(f"{CDP_URL}/json/version", timeout=2)
        return r.status_code == 200
    except requests.RequestException:
        return False


def fetch_via_chrome(url: str, wait_s: int = 20) -> dict:
    """Open the product page in the user's Chrome (CDP), intercept
    item/get_ratings + pdp/item API responses, return name/price/reviews."""
    from playwright.sync_api import sync_playwright

    parse_shopee_url(url)  # validate early
    if not chrome_cdp_available():
        raise ChromeNotRunning(
            f"No Chrome with remote debugging at {CDP_URL}. Start it with: "
            "google-chrome --remote-debugging-port=9222 "
            "--user-data-dir=$HOME/.cache/shopeecheck-chrome"
        )

    ratings = []
    item_info = {}

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        try:
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()

            def on_response(resp):
                u = resp.url
                try:
                    if "/api/v4/item/get_ratings" in u or "/api/v2/item/get_ratings" in u:
                        data = resp.json()
                        for it in (data.get("data", {}) or {}).get("ratings") or []:
                            text = (it.get("comment") or "").strip()
                            if text:
                                ratings.append(f"{it.get('rating_star', 5)} - {text}")
                    elif "/api/v4/pdp/get_pc" in u or "/api/v4/item/get" in u:
                        data = (resp.json().get("data") or {})
                        if data.get("name"):
                            item_info["name"] = data["name"]
                            price = data.get("price") or data.get("price_min") or 0
                            if price:
                                item_info["price"] = round(price / 100000.0, 2)
                except Exception:
                    pass

            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # scroll to trigger review loading
            deadline = time.time() + wait_s
            scrolls = 0
            while time.time() < deadline and not ratings:
                page.mouse.wheel(0, 1500)
                scrolls += 1
                time.sleep(1.2)
                if scrolls % 4 == 0:
                    try:
                        btn = page.query_selector("button[class*='more'], div[class*='see-more']")
                        if btn:
                            btn.click()
                    except Exception:
                        pass

            # DOM fallbacks for name/price
            if "name" not in item_info:
                try:
                    item_info["name"] = (page.title() or "").split(" | ")[0].strip()
                except Exception:
                    item_info["name"] = ""
            if "price" not in item_info:
                try:
                    body = page.inner_text("body")[:4000]
                    m = re.search(r"RM\s?([\d,]+\.?\d*)", body)
                    if m:
                        item_info["price"] = float(m.group(1).replace(",", ""))
                except Exception:
                    pass
            page.close()
        finally:
            browser.close()

    if not ratings:
        raise ScrapeBlocked("No review API responses captured (page blocked or no reviews loaded)")
    return {
        "name": item_info.get("name", ""),
        "price": item_info.get("price", 0.0),
        "reviews": ratings[:20],
        "source": "chrome",
    }


def fetch_product(url: str, timeout: int = 15) -> dict:
    """Try the public v4 APIs directly (usually 403 without cookies).
    Returns dict(name, price, reviews) or raises ScrapeBlocked/ValueError.
    """
    shopid, itemid = parse_shopee_url(url)
    base = "https://shopee.com.my"
    headers = {
        "User-Agent": UA,
        "Referer": url,
        "Accept": "application/json",
        "X-API-SOURCE": "pc",
        "X-Requested-With": "XMLHttpRequest",
    }

    item_r = requests.get(f"{base}/api/v4/item/get",
                          params={"itemid": itemid, "shopid": shopid},
                          headers=headers, timeout=timeout)
    if item_r.status_code != 200:
        raise ScrapeBlocked(f"item/get HTTP {item_r.status_code}")
    try:
        data = item_r.json().get("data") or {}
    except json.JSONDecodeError:
        raise ScrapeBlocked("item/get returned non-JSON (anti-bot page)")
    if not data:
        raise ScrapeBlocked("item/get empty (anti-bot)")

    name = data.get("name", "")
    price = (data.get("price") or data.get("price_min") or 0) / 100000.0

    rating_r = requests.get(f"{base}/api/v4/item/get_ratings",
                            params={"itemid": itemid, "shopid": shopid,
                                    "limit": 20, "offset": 0, "type": 0, "order": "desc"},
                            headers=headers, timeout=timeout)
    reviews = []
    if rating_r.status_code == 200:
        try:
            for it in (rating_r.json().get("data", {}).get("ratings") or [])[:20]:
                text = (it.get("comment") or "").strip()
                if text:
                    reviews.append(f"{it.get('rating_star', 5)} - {text}")
        except (json.JSONDecodeError, AttributeError):
            pass
    if not reviews:
        raise ScrapeBlocked("get_ratings blocked or no reviews")

    return {"name": name, "price": round(price, 2), "reviews": reviews, "source": "api"}


def auto_fetch(url: str):
    """Best-effort chain: Chrome CDP -> direct API -> demo data.
    Returns (data, note) where note explains the source for the UI.
    """
    errors = []
    if chrome_cdp_available():
        try:
            data = fetch_via_chrome(url)
            return data, f"✅ Fetched live via your Chrome: {len(data['reviews'])} reviews loaded."
        except Exception as e:
            errors.append(f"chrome: {type(e).__name__}: {e}")
    else:
        errors.append("chrome: CDP not available at localhost:9222")
    try:
        data = fetch_product(url)
        return data, f"✅ Fetched live via Shopee API: {len(data['reviews'])} reviews loaded."
    except Exception as e:
        errors.append(f"api: {type(e).__name__}: {e}")
    data = demo_fetch(url)
    return data, ("⚠️ Live fetch blocked (" + "; ".join(errors)[:200] + "). "
                  "Loaded demo data so the flow still works — paste reviews manually for real products.")


def demo_fetch(url: str) -> dict:
    """Clearly-labelled fallback so the paste-link flow still demos when
    Shopee's anti-bot blocks direct scraping."""
    with open(EXAMPLES_PATH) as f:
        examples = json.load(f)
    low = url.lower()
    key = "genuine_mouse" if ("logitech" in low or "mouse" in low or "ori" in low) else "fake_pendrive"
    ex = examples[key]
    return {
        "name": ex["name"],
        "price": ex["price"],
        "reviews": ex["reviews"],
        "source": "demo",
    }
