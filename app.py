"""ShopeeCheck — paste Shopee reviews, detect likely-fake products.

Run: pip install -r requirements.txt && streamlit run app.py
Design: rules engine always works offline; LLM is optional enhancement.
"""
import html
import json
import os
import re
from collections import Counter
from difflib import SequenceMatcher

import requests
import streamlit as st

import scraper

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
        "subtitle": "Paste Shopee reviews. Spot fake 5-star products in seconds.",
        "analyse": "Analyze Reviews",
        "advice_title": "What to do next",
        "why_title": "Why we think so",
        "product_info": "Product Info",
        "reviews_box": "Reviews",
        "flagged": "Show flagged reviews",
        "fetch": "🔗 Fetch from link",
        "fetch_ph": "https://shopee.com.my/Product-Name-i.SHOPID.ITEMID",
        "name_ph": "e.g. Pendrive USB 3.0 1TB High Speed Flash Drive",
        "reviews_ph": "One review per line, e.g.:\n5 - barang baik fast delivery\n5 - good seller fast shipping\n4 - size kecil sikit tapi ok",
        "verdict_labels": {"Likely Fake": "LIKELY FAKE", "Suspicious": "SUSPICIOUS", "Likely Genuine": "LIKELY GENUINE"},
    },
    "BM": {
        "subtitle": "Tampal review Shopee. Kesan produk palsu dalam beberapa saat.",
        "analyse": "Analisa Review",
        "advice_title": "Apa perlu buat",
        "why_title": "Kenapa kami kata begitu",
        "product_info": "Maklumat Produk",
        "reviews_box": "Review",
        "flagged": "Tunjuk review yang diragui",
        "fetch": "🔗 Ambil dari link",
        "fetch_ph": "https://shopee.com.my/Nama-Produk-i.SHOPID.ITEMID",
        "name_ph": "cth. Pendrive USB 3.0 1TB High Speed Flash Drive",
        "reviews_ph": "Satu review per baris, cth.:\n5 - barang baik fast delivery\n5 - good seller fast shipping\n4 - size kecil sikit tapi ok",
        "verdict_labels": {"Likely Fake": "KEMUNGKINAN PALSU", "Suspicious": "MENCURIGAKAN", "Likely Genuine": "KEMUNGKINAN ASLI"},
    },
}

VERDICT_STYLE = {
    "Likely Fake": ("#ee4d2d", "#fff0ec", "🚨"),
    "Suspicious": ("#f59e0b", "#fff8e6", "⚠️"),
    "Likely Genuine": ("#16a34a", "#edfaef", "✅"),
}

CSS = """
<style>
    .block-container { padding-top: 2rem; max-width: 1100px; }
    h1.brand { color: #ee4d2d; font-weight: 800; letter-spacing: -0.5px; margin: 0; }
    .brand-sub { color: #666; margin: 2px 0 14px 0; font-size: 0.95rem; }
    .section-card {
        background: #fff; border: 1px solid #f0e0da; border-radius: 14px;
        padding: 18px 20px; box-shadow: 0 2px 8px rgba(238,77,45,0.06);
    }
    .verdict-card {
        border-radius: 16px; padding: 24px 28px; display: flex;
        align-items: center; gap: 28px; border: 2px solid;
    }
    .verdict-emoji { font-size: 3.2rem; line-height: 1; }
    .verdict-label { font-size: 1.5rem; font-weight: 800; letter-spacing: 0.5px; }
    .verdict-score { font-size: 2.6rem; font-weight: 800; margin-left: auto; text-align: right; }
    .verdict-score small { font-size: 0.8rem; font-weight: 500; color: #777; display: block; }
    .badge-src {
        display: inline-block; font-size: 0.7rem; font-weight: 600; padding: 2px 10px;
        border-radius: 999px; background: #ee4d2d; color: #fff; margin-top: 6px;
    }
    .reason-item {
        background: #fafafa; border-left: 4px solid #ee4d2d; border-radius: 6px;
        padding: 10px 14px; margin: 8px 0; font-size: 0.92rem;
    }
    .star-row { display: flex; align-items: center; gap: 8px; margin: 3px 0; font-size: 0.8rem; }
    .star-bar-bg { flex: 1; background: #f0f0f0; border-radius: 999px; height: 8px; overflow: hidden; }
    .star-bar { background: #ffb400; height: 100%; border-radius: 999px; }
    .flagged-review {
        background: #fff5f2; border: 1px dashed #ee4d2d; border-radius: 8px;
        padding: 8px 12px; margin: 6px 0; font-size: 0.85rem; color: #8a2d17;
    }
    div[data-testid="stMetricValue"] { color: #ee4d2d; }
    div[data-testid="stButton"] button[kind="primary"] {
        background: #ee4d2d; border-color: #ee4d2d; font-weight: 700;
    }
</style>
"""


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


def flag_review(text: str):
    t = text.lower()
    flags = []
    if any(p in t for p in GENERIC_PHRASES):
        flags.append("generic")
    if len(t.split()) < 4 or len(t) < 20:
        flags.append("shallow")
    if not any(k in t for k in DETAIL_KEYWORDS):
        flags.append("no-detail")
    return flags


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


def render_stars(reviews):
    counts = Counter(r["rating"] for r in reviews)
    total = len(reviews) or 1
    rows = ""
    for star in (5, 4, 3, 2, 1):
        c = counts.get(star, 0)
        pct = c / total * 100
        rows += (
            f"<div class='star-row'><span>{star}★</span>"
            f"<div class='star-bar-bg'><div class='star-bar' style='width:{pct:.0f}%'></div></div>"
            f"<span>{c}</span></div>"
        )
    st.markdown(rows, unsafe_allow_html=True)


def render_verdict(verdict, score, source, n_reviews, s):
    color, bg, emoji = VERDICT_STYLE[verdict]
    label = s["verdict_labels"].get(verdict, verdict.upper())
    st.markdown(
        f"<div class='verdict-card' style='background:{bg};border-color:{color}'>"
        f"<div class='verdict-emoji'>{emoji}</div>"
        f"<div><div class='verdict-label' style='color:{color}'>{label}</div>"
        f"<span class='badge-src' style='background:{color}'>via {source} · {n_reviews} reviews</span></div>"
        f"<div class='verdict-score' style='color:{color}'>{score}<small>/100 risk score</small></div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def main():
    st.set_page_config(page_title="ShopeeCheck", page_icon="🛡️", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    # top bar: brand + language pill
    top_left, top_right = st.columns([4, 1])
    top_left.markdown(
        "<h1 class='brand'>🛡️ ShopeeCheck</h1>", unsafe_allow_html=True
    )
    lang = top_right.radio("Bahasa", ["EN", "BM"], horizontal=True, label_visibility="collapsed")
    s = STRINGS[lang]
    st.markdown(f"<div class='brand-sub'>{s['subtitle']}</div>", unsafe_allow_html=True)

    with open(EXAMPLES_PATH) as f:
        examples = json.load(f)

    # demo cards
    d1, d2, _ = st.columns([1, 1, 2])
    with d1.container(border=True):
        st.markdown("**📦 Demo: Fake Pendrive**")
        st.caption("1TB, RM18.90 — 8 generic 5-star reviews")
        if st.button("Load fake demo", use_container_width=True):
            st.session_state.update(
                name=examples["fake_pendrive"]["name"],
                price=examples["fake_pendrive"]["price"],
                url=examples["fake_pendrive"]["url"],
                raw="\n".join(examples["fake_pendrive"]["reviews"]),
            )
            st.rerun()
    with d2.container(border=True):
        st.markdown("**🖱️ Demo: Genuine Mouse**")
        st.caption("Logitech M331, RM79 — detailed mixed reviews")
        if st.button("Load genuine demo", use_container_width=True):
            st.session_state.update(
                name=examples["genuine_mouse"]["name"],
                price=examples["genuine_mouse"]["price"],
                url=examples["genuine_mouse"]["url"],
                raw="\n".join(examples["genuine_mouse"]["reviews"]),
            )
            st.rerun()

    st.markdown("<hr style='border:none;border-top:1px solid #f0e0da;margin:14px 0'>", unsafe_allow_html=True)

    # input: product info left, reviews right
    col_info, col_reviews = st.columns([1, 1.4], gap="large")
    with col_info:
        st.markdown(f"### 🏷️ {s['product_info']}")
        link = st.text_input("Shopee link", key="url", placeholder=s["fetch_ph"])
        if st.button(s["fetch"], use_container_width=True):
            if not link.strip():
                st.warning("Paste a Shopee product link first (…-i.SHOPID.ITEMID).")
            else:
                with st.spinner("Fetching from Shopee… (up to ~25s via your Chrome)"):
                    data, note = scraper.auto_fetch(link.strip())
                    st.session_state.update(
                        name=data["name"],
                        price=float(data["price"] or 0.0),
                        raw="\n".join(data["reviews"]),
                    )
                    st.session_state.fetch_note = note
                st.rerun()
        if st.session_state.get("fetch_note"):
            st.caption(st.session_state.pop("fetch_note"))
        name = st.text_input("Product name", key="name", value="Pendrive USB 3.0 1TB High Speed Flash Drive", placeholder=s["name_ph"])
        c1, c2 = st.columns(2)
        price = c1.number_input("Price (RM)", key="price", value=18.90, min_value=0.0, step=1.0)
        c2.text_input("Manual URL (optional)", placeholder="https://shopee.com.my/…")
        with st.expander("⚙️ LLM settings (optional — rules work offline)"):
            api_url = st.text_input("API URL", value=os.getenv("LLM_API_URL", "https://api.groq.com/openai/v1/chat/completions"))
            api_key = st.text_input("API Key", value=os.getenv("LLM_API_KEY", ""), type="password")
            model = st.text_input("Model", value=os.getenv("LLM_MODEL", "llama-3.1-8b-instant"))
            use_llm = st.checkbox("Use LLM if key present", value=True)
    with col_reviews:
        st.markdown(f"### 📝 {s['reviews_box']}")
        raw = st.text_area(
            "Paste reviews (one per line)",
            key="raw", height=210, placeholder=s["reviews_ph"], label_visibility="collapsed",
        )
        parsed_preview = parse_reviews(raw or "")
        if parsed_preview:
            render_stars(parsed_preview)
        analyse_clicked = st.button(f"🔍 {s['analyse']}", type="primary", use_container_width=True)

    if analyse_clicked:
        reviews = parse_reviews(raw or "")
        if not reviews:
            st.warning("Paste at least 1 review first.")
            return
        score, reasons, verdict = rule_score(name, price, reviews)
        source = "rules (offline)"
        advice_llm = ""
        if use_llm and api_key:
            try:
                out = llm_score(api_url, api_key, model, name, price, reviews, lang)
                score, verdict = int(out["score"]), out["verdict"]
                reasons = out.get("reasons", reasons)
                advice_llm = out.get("advice", "")
                source = f"AI · {model}"
            except Exception as e:
                st.caption(f"LLM failed ({e}) — used offline rules.")

        st.markdown("---")
        render_verdict(verdict, score, source, len(reviews), s)

        r_col, a_col = st.columns([1.2, 1], gap="large")
        with r_col:
            st.markdown(f"#### 🔎 {s['why_title']}")
            for r in reasons:
                st.markdown(f"<div class='reason-item'>{html.escape(str(r))}</div>", unsafe_allow_html=True)
            flagged = [(r, flag_review(r["text"])) for r in reviews]
            flagged = [(r, f) for r, f in flagged if f]
            if flagged:
                with st.expander(f"🚩 {s['flagged']} ({len(flagged)}/{len(reviews)})"):
                    for r, f in flagged:
                        st.markdown(
                            f"<div class='flagged-review'>{r['rating']}★ {html.escape(r['text'])}"
                            f"<br><small>flags: {', '.join(f)}</small></div>",
                            unsafe_allow_html=True,
                        )
        with a_col:
            st.markdown(f"#### 💡 {s['advice_title']}")
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
