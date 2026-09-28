# ShopeeCheck — Fake Review Detector 🇲🇾

Paste Shopee reviews (or auto-fetch them from a product link) → verdict card:
`Likely Fake / Suspicious / Likely Genuine` + 0-100 score + reasons (BM/EN).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Auto-fetch reviews from a product link (recommended)

Anonymous requests are blocked by Shopee's anti-fraud gate (HTTP 403, error
`90309999` — verified). The app therefore fetches through **your own logged-in
Chrome**, intercepting the page's own review API calls:

1. Launch Chrome with remote debugging (once):
   ```bash
   google-chrome --remote-debugging-port=9222 --user-data-dir=$HOME/.cache/shopeecheck-chrome
   ```
2. Log into `shopee.com.my` once in that window.
3. In the app: paste the product link → **🔗 Fetch from link**.
   Name, price and up to 20 reviews are filled in automatically — edit if
   needed, then click **Analyze Reviews** for the AI verdict.

Fallback chain (automatic): your Chrome via CDP → direct Shopee API
(best-effort) → clearly-labelled demo data, so the flow never dies on stage.
Set `SHOPEECHECK_CDP` to use a different debugging port.

Note: this drives your own account against public review data for personal /
demo use — not bulk scraping. Respect Shopee's Terms of Service.

## Manual mode

Product name + price + reviews textarea (one review per line,
`5 - text` format supported), BM/EN toggle, 2 demo buttons
(Fake Pendrive / Genuine Mouse). The offline rules engine always works
without network or API keys; the LLM sidebar entry is an optional
enhancement (OpenAI-compatible endpoint).
