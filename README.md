# ShopeeCheck 🛡️ — Fake Review Detector for Shopee Malaysia

> Paste product name, price and reviews → get an instant verdict: **Likely Fake / Suspicious / Likely Genuine**, with a 0–100 score, reasons, and actionable next steps in BM or English.

Built for the **IBM Hackathon** — 30-minute buildable, 100% offline-capable demo.

---

## Why this exists

Shopee Malaysia is flooded with fake products — the classic example being a **"1TB pendrive" for RM18.90** backed by ten glowing 5-star reviews like *"barang baik fast delivery recommended"*. Those reviews say nothing about the actual product; they're generic, templated, and often paid.

Students, B40 buyers and elderly users can't tell genuine from fake. ShopeeCheck does it for them in seconds.

## How it works

Two independent analysis layers:

1. **Rules engine (always on, offline)** — pure Python heuristics:
   - **Impossible price detection** — 1TB pendrive < RM80, 512GB < RM45, 1TB SSD < RM150, AirPods < RM50 (+40)
   - **5-star burst** — ≥85% five-star with zero critical reviews (+20)
   - **Generic phrase ratio** — "fast delivery", "barang baik", "good seller" with no product detail (+15)
   - **Near-duplicate reviews** — fuzzy matching via `SequenceMatcher` > 0.75 similarity → template/paid review signal (+15)
   - **Shallow reviews** — half the reviews under 4 words (+10)
   - **Zero usage detail** — nobody mentions testing, capacity, warranty, photos (+5)
2. **LLM analyst (optional)** — any OpenAI-compatible API (Groq, OpenAI, Gemini, or **IBM watsonx.ai Granite** by swapping the URL/model). Returns a structured JSON verdict with reasons and advice in your chosen language.

**If the LLM fails or you have no key/WiFi, the app silently falls back to the rules engine — the demo never dies on stage.**

Verdict thresholds: score ≥65 → **Likely Fake**, ≥35 → **Suspicious**, else → **Likely Genuine**.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Opens at `http://localhost:8501`.

### Optional LLM

Set env vars before launching (or fill the sidebar form):

```bash
export LLM_API_URL="https://api.groq.com/openai/v1/chat/completions"
export LLM_API_KEY="your-key"
export LLM_MODEL="llama-3.1-8b-instant"
```

For IBM watsonx.ai Granite, point `LLM_API_URL` at your watsonx OpenAI-compatible inference endpoint.

## 3-minute demo script

| Step | Action | Expected |
|---|---|---|
| 1 | Click **📦 Load Fake Pendrive demo** → Analyze | 🔴 Likely Fake 80/100 — impossible price + generic 5-star burst |
| 2 | Click **🖱️ Load Genuine Mouse demo** → Analyze | 🟢 Likely Genuine 0/100 — mixed ratings, real usage detail, photos |
| 3 | Paste any review from a live audience | Verdict updates instantly |

Closing line: *"Protects 30M+ MY Shopee users, KPDN-aligned, Granite-ready, deployable to IBM Cloud Code Engine."*

## Project structure

```
app.py           # Streamlit app: form + rules engine + LLM call + verdict UI
examples.json    # Two pre-loaded demo datasets (fake pendrive, genuine Logitech mouse)
requirements.txt # streamlit, requests — nothing else
PLANS.md         # Full hackathon plan, timeline, risks, judging angles
```

## Design decisions

- **No Shopee scraping** — anti-bot and ToS risk would sink the live demo; paste-in keeps it safe and honest
- **Single file, zero infra** — no DB, no auth, no build step; built in the 30-min hackathon window
- **Bilingual (BM/EN)** — toggle in sidebar; LLM reasons generated in the selected language
- **Rules-first, LLM-second** — deterministic offline baseline guarantees demo reliability

## Future work

- Browser extension with OCR of review screenshots
- watsonx.ai Granite hosted on IBM Cloud Code Engine
- Auto-generated KPDN / Shopee complaint reports
- SemakMule & NSRC 997 integration for payment-scam cross-checks

## License

MIT — hackathon project, use freely.
