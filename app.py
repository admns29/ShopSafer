"""ShopeeCheck — paste Shopee reviews, detect likely-fake products.

Run: pip install -r requirements.txt && streamlit run app.py
Design: rules engine always works offline; LLM is optional enhancement.
"""
import json
import os
import re
from difflib import SequenceMatcher

import requests
import streamlit as st

EXAMPLES_PATH = os.path.join(os.path.dirname(__file__), "examples.json")

GENERIC_PHRASES = [
    "fast delivery", "fast shipping", "good seller", "barang baik",
    "item received", "recommended", "puas hati", "barang sampai",
    "thanks seller", "good packaging", "harga murah",
]

DETAIL_KEYWORDS = [
    "test", "h2testw", "crystal", "capacity", "format", "mb/s", "read",
    "write", "ori", "serial", "seal", "warranty", "waranti", "battery",
    "bateri", "click", "grip", "receiver", "bubble", "box", "kotak",
    "gambar", "photo", "resit", "guna", "pakai", "minggu", "bulan",
]

STRINGS = {
    "EN": {
        "title": "ShopeeCheck — Fake Review Detector 🇲🇾",
        "subtitle": "Paste Shopee reviews. Spot fake 5-star products (e.g. fake 1TB pendrive).",
        "analyse": "Analyze",
        "advice_title": "What to do next",
    },
    "BM": {
        "title": "ShopeeCheck — Pengesan Review Palsu 🇲🇾",
        "subtitle": "Tampal review Shopee. Kesan produk palsu (cth. pendrive 1TB tipu).",
        "analyse": "Analisa",
        "advice_title": "Apa perlu buat",
    },
}


def parse_reviews(raw: str):
    """One review per line. Optional leading rating: '5 - text' or '5|text'."""
    reviews = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^([1-5])\s*[\|\-:;,]\s*(.+)$", line)
        if m:
            reviews.append({"rating": int(m.group(1)), "text": m.group(2).strip()})
        else:
            reviews.append({"rating": 5, "text": line})
    return reviews


def price_check(name: str, price: float):
    n = name.lower()
    is_storage = any(k in n for k in ["pendrive", "usb", "flash drive", "otg", "thumbdrive", "sd card", "microsd"])
    hits = []
    penalty = 0
    if is_storage:
        if ("1tb" in n or "1 tb" in n) and price < 80:
            penalty = 40
            hits.append(f"1TB at RM{price:.2f} is impossible (real 1TB ≈ RM80+)")
        elif ("512gb" in n or "512 gb" in n) and price < 45:
            penalty = 40
            hits.append(f"512GB at RM{price:.2f} is impossible (real ≈ RM45+)")
        elif ("2tb" in n or "2 tb" in n) and price < 120:
            penalty = 40
            hits.append(f"2TB at RM{price:.2f} is impossible")
    if "airpod" in n and price < 50:
        penalty = max(penalty, 40)
        hits.append(f"AirPods at RM{price:.2f} — likely counterfeit")
    if "ssd" in n and ("1tb" in n) and price < 150:
        penalty = max(penalty, 35)
        hits.append(f"1TB SSD at RM{price:.2f} — far below market")
    return penalty, hits


def rule_score(name: str, price: float, reviews):
    reasons = []
    score = 0
    if not reviews:
        return 0, ["No reviews pasted."], "Suspicious"

    n = len(reviews)
    five = sum(1 for r in reviews if r["rating"] == 5)
    five_ratio = five / n

    texts = [r["text"].lower() for r in reviews]
    generic = sum(1 for t in texts if any(p in t for p in GENERIC_PHRASES))
    generic_ratio = generic / n
    short = sum(1 for t in texts if len(t.split()) < 4 or len(t) < 20)
    detailed = sum(1 for t in texts if any(k in t for k in DETAIL_KEYWORDS))

    # duplicates
    dup_pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            if SequenceMatcher(None, texts[i], texts[j]).ratio() > 0.75:
                dup_pairs += 1

    p_pen, p_hits = price_check(name, price)
    score += p_pen
    reasons += p_hits

    if five_ratio >= 0.85 and n >= 4:
        score += 20
        reasons.append(f"{five}/{n} are 5-star with zero critical review — unusual")
    if generic_ratio >= 0.6:
        score += 15
        reasons.append(f"{generic}/{n} use generic phrases ('fast delivery', 'barang baik') with no product detail")
    if dup_pairs > 0:
        score += 15
        reasons.append(f"{dup_pairs} near-duplicate review pairs — possible template / paid reviews")
    if short / n >= 0.5:
        score += 10
        reasons.append(f"{short}/{n} reviews are very short (<4 words) — low effort")
    if detailed == 0:
        score += 5
        reasons.append("No review mentions real usage, test, capacity, warranty or photos")

    score = max(0, min(100, score))
    verdict = "Likely Fake" if score >= 65 else ("Suspicious" if score >= 35 else "Likely Genuine")
    if not reasons:
        reasons = ["Mixed ratings with specific usage detail and photos mentioned — looks genuine."]
    return score, reasons[:4], verdict


def llm_score(api_url, api_key, model, name, price, reviews, lang):
    prompt = (
        f"You are a Shopee Malaysia fraud analyst. Product: {name}, Price RM{price}. "
        f"Reviews (rating|text):\n"
        + "\n".join(f"{r['rating']}|{r['text']}" for r in reviews[:12])
        + f"\nReply ONLY valid JSON: {{\"score\": 0-100 fake likelihood, "
        f"\"verdict\": \"Likely Fake|Suspicious|Likely Genuine\", "
        f"\"reasons\": [3 short strings in {lang}], "
        f"\"advice\": \"one line next step in {lang}\"}}"
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    r = requests.post(api_url, headers=headers, json=payload, timeout=25)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def main():
    st.set_page_config(page_title="ShopeeCheck", page_icon="🛡️")
    lang = st.sidebar.radio("Language / Bahasa", ["EN", "BM"])
    s = STRINGS[lang]
    st.title(s["title"])
    st.caption(s["subtitle"])

    with open(EXAMPLES_PATH) as f:
        examples = json.load(f)

    col_a, col_b = st.columns(2)
    if col_a.button("📦 Load Fake Pendrive demo"):
        st.session_state.update(
            name=examples["fake_pendrive"]["name"],
            price=examples["fake_pendrive"]["price"],
            url=examples["fake_pendrive"]["url"],
            raw="\n".join(f"{r}" for r in examples["fake_pendrive"]["reviews"]),
        )
    if col_b.button("🖱️ Load Genuine Mouse demo"):
        st.session_state.update(
            name=examples["genuine_mouse"]["name"],
            price=examples["genuine_mouse"]["price"],
            url=examples["genuine_mouse"]["url"],
            raw="\n".join(f"{r}" for r in examples["genuine_mouse"]["reviews"]),
        )

    name = st.text_input("Product name", key="name", value="Pendrive USB 3.0 1TB High Speed Flash Drive")
    price = st.number_input("Price (RM)", key="price", value=18.90, min_value=0.0, step=1.0)
    st.text_input("Shopee URL (optional)", key="url")
    raw = st.text_area(
        "Paste reviews (one per line, e.g. `5 - barang baik fast delivery`)",
        key="raw", height=180,
    )

    with st.sidebar.expander("LLM (optional — offline rules work without it)", expanded=False):
        api_url = st.text_input("API URL", value=os.getenv("LLM_API_URL", "https://api.groq.com/openai/v1/chat/completions"))
        api_key = st.text_input("API Key", value=os.getenv("LLM_API_KEY", ""), type="password")
        model = st.text_input("Model", value=os.getenv("LLM_MODEL", "llama-3.1-8b-instant"))
        use_llm = st.checkbox("Use LLM if key present", value=True)

    if st.button(f"🔍 {s['analyse']}", type="primary"):
        reviews = parse_reviews(raw or "")
        if not reviews:
            st.warning("Paste at least 1 review first.")
            return
        score, reasons, verdict = rule_score(name, price, reviews)
        source = "rules (offline)"
        if use_llm and api_key:
            try:
                out = llm_score(api_url, api_key, model, name, price, reviews, lang)
                score, verdict = int(out["score"]), out["verdict"]
                reasons = out.get("reasons", reasons)
                advice_llm = out.get("advice", "")
                source = f"LLM ({model})"
            except Exception as e:
                st.caption(f"LLM failed ({e}) — used offline rules.")
                advice_llm = ""
        else:
            advice_llm = ""

        color = "#e53935" if verdict == "Likely Fake" else ("#fb8c00" if verdict == "Suspicious" else "#43a047")
        st.markdown(
            f"<div style='padding:16px;border-radius:12px;background:{color}22;border:1px solid {color}'>"
            f"<h2 style='margin:0;color:{color}'>{verdict} — {score}/100</h2>"
            f"<small>via {source} · {len(reviews)} reviews analysed</small></div>",
            unsafe_allow_html=True,
        )
        st.progress(score / 100)
        st.subheader("Why / Kenapa")
        for r in reasons:
            st.write(f"- {r}")
        st.subheader(s["advice_title"])
        if verdict == "Likely Fake":
            st.write("- ❌ Don't buy. Price impossible + generic 5-stars = classic fake storage.")
            st.write("- 💬 Chat seller: 'boleh h2testw / CrystalDiskMark full capacity?' Fake sellers dodge.")
            st.write("- 🛡️ Only pay via Shopee Guarantee, keep unboxing video, report to Shopee + KPDN.")
        elif verdict == "Suspicious":
            st.write("- ⚠️ Risky. Ask for real capacity test photo/video before ordering.")
        else:
            st.write("- ✅ Looks genuine. Still check Shopee Mall / Preferred+ badge + return policy.")
        if advice_llm:
            st.info(f"AI: {advice_llm}")


if __name__ == "__main__":
    main()
