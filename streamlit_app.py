# -*- coding: utf-8 -*-
import os
import json
from datetime import datetime

import streamlit as st

from odds_math import (
    implied_from_decimal,
    normalize_proportional,
    shin_fair_probs,
    overround,
    kelly_suggestions,
    aggregate_prices,
)
from odds_provider_theoddsapi import (
    list_soccer_sports,
    fetch_odds_for_sport,
    extract_h2h_prices,
    extract_totals_lines,
)
from gemini_helper import analyze_with_gemini


# ==========================================================
# 📌 مفاتيح API من Secrets (لا تُعرض)
# ==========================================================
if "ODDS_API_KEY" in st.secrets and st.secrets["ODDS_API_KEY"]:
    os.environ["ODDS_API_KEY"] = st.secrets["ODDS_API_KEY"]

if "GEMINI_API_KEY" in st.secrets and st.secrets["GEMINI_API_KEY"]:
    os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]


# ==========================================================
# 📌 إعداد واجهة Streamlit
# ==========================================================
st.set_page_config(
    page_title="Market Predictor — Odds + Gemini",
    page_icon="🎯",
    layout="wide",
)

if "ui_theme" not in st.session_state:
    st.session_state.ui_theme = "فاتح"


def inject_css(theme="فاتح"):
    """إضافة CSS مخصص حسب الثيم المختار"""
    if theme == "فاتح":
        css = """<style> ... (CSS الخاص بالثيم الفاتح) ... </style>"""
    else:
        css = """<style> ... (CSS الخاص بالثيم الداكن) ... </style>"""
    st.markdown(css, unsafe_allow_html=True)


inject_css(st.session_state.ui_theme)


# ==========================================================
# 📌 رأس الصفحة + اختيار الثيم
# ==========================================================
l, r = st.columns([3, 1])
with l:
    st.markdown("<h1>Market Predictor — Odds + Gemini 🎯</h1>", unsafe_allow_html=True)

with r:
    theme = st.selectbox(
        "المظهر", ["فاتح", "داكن"],
        index=(0 if st.session_state.ui_theme == "فاتح" else 1)
    )
    if theme != st.session_state.ui_theme:
        st.session_state.ui_theme = theme
        inject_css(theme)


# ==========================================================
# 📌 عرض مفاتيح API وضبطها
# ==========================================================
with st.expander("مفاتيح API", expanded=True):
    st.write("ODDS_API_KEY:", "✅ مضبوط" if os.getenv("ODDS_API_KEY") else "❌ غير مضبوط")
    st.write("GEMINI_API_KEY:", "✅ مضبوط" if os.getenv("GEMINI_API_KEY") else "❌ غير مضبوط")

    c1, c2 = st.columns(2)

    with c1:
        ak = st.text_input(
            "ODDS_API_KEY (لن يُعرض أو يُحفظ)",
            value="", type="password",
            placeholder="ألصق المفتاح هنا"
        )
        if st.button("حفظ مفتاح الأودز للجلسة"):
            if ak.strip():
                os.environ["ODDS_API_KEY"] = ak.strip()
                st.success("تم حفظ مفتاح الأودز للجلسة.")
            else:
                st.warning("لم يتم إدخال مفتاح.")

    with c2:
        gk = st.text_input(
            "GEMINI_API_KEY (اختياري، لن يُعرض أو يُحفظ)",
            value="", type="password",
            placeholder="ألصق المفتاح هنا"
        )
        if st.button("حفظ مفتاح Gemini للجلسة"):
            if gk.strip():
                os.environ["GEMINI_API_KEY"] = gk.strip()
                st.success("تم حفظ مفتاح Gemini للجلسة.")
            else:
                st.warning("لم يتم إدخال مفتاح.")


# ==========================================================
# 📌 إعدادات السوق + جلب البيانات
# ==========================================================
st.markdown("<div class='card'>", unsafe_allow_html=True)
st.subheader("اختيار الدوري والمباراة وإعدادات التحليل")

left, right = st.columns([2, 1])

# --- يسار: اختيار الدوري والمباراة
with left:
    if not os.getenv("ODDS_API_KEY"):
        st.error("يرجى ضبط ODDS_API_KEY أولاً (Secrets أو الحقل أعلاه).")
        st.stop()

    with st.spinner("جلب الدوريات..."):
        try:
            sports = list_soccer_sports()
        except Exception as e:
            st.exception(e)
            st.stop()

    sport_options = {
        f"{s.get('group','')} — {s.get('title','')} ({s.get('key')})": s.get("key")
        for s in sports
    }
    sport_label = st.selectbox("اختر الدوري", options=list(sport_options.keys()))
    sport_key = sport_options[sport_label]

    regions = st.multiselect("مناطق الدفاتر (regions)", ["eu", "uk", "us", "au"], default=["eu", "uk"])
    markets_sel = st.multiselect("الأسواق", ["h2h", "totals"], default=["h2h", "totals"])

    if st.button("جلب المباريات والأودز"):
        st.session_state["events_data"] = None
        with st.spinner("جارِ الجلب..."):
            try:
                events, meta = fetch_odds_for_sport(
                    sport_key,
                    regions=",".join(regions),
                    markets=",".join(markets_sel),
                )
                st.session_state["events_data"] = {
                    "events": events,
                    "meta": meta,
                    "regions": regions,
                    "markets": markets_sel,
                }
                st.success(f"تم الجلب. Requests remaining: {meta.get('remaining')}")
            except Exception as e:
                st.exception(e)

# --- يمين: إعدادات تحليل كيللي والتجميع
with right:
    bankroll = st.number_input("حجم المحفظة", min_value=10.0, value=100.0, step=10.0)
    kelly_scale = st.slider("Kelly scale", 0.05, 1.0, 0.25, 0.05)
    min_edge = st.slider("أدنى ميزة (edge)", 0.0, 0.1, 0.02, 0.005)
    agg_mode = st.selectbox("تجميع أسعار الدفاتر", ["median", "best", "mean"], index=0)
    fair_method = st.selectbox("طريقة إزالة الهامش", ["Proportional", "Shin"], index=1)

st.markdown("</div>", unsafe_allow_html=True)


# ==========================================================
# 📌 عرض المباريات والنتائج
# ==========================================================
events_data = st.session_state.get("events_data")
if events_data and events_data.get("events"):
    evs = events_data["events"]

    # --- قائمة المباريات
    options, idx_map = [], {}
    for i, ev in enumerate(evs):
        dt_iso = ev.get("commence_time")
        try:
            dt = datetime.fromisoformat(str(dt_iso).replace("Z", "+00:00"))
            dt_str = dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            dt_str = str(dt_iso)
        label = f"{ev.get('home_team')} vs {ev.get('away_team')} — {dt_str}"
        options.append(label)
        idx_map[label] = i

    match_label = st.selectbox("اختر مباراة", options=options, index=0)
    event = evs[idx_map[match_label]]

    # --- 1×2 تحليل السوق
    h2h_prices = extract_h2h_prices(event)
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("1×2 — إجماع السوق")

    have_h2h = any(h2h_prices.values())
    agg_odds = imps = fair = ov = sugg = None

    if have_h2h:
        agg_odds = {side: aggregate_prices(arr, mode=agg_mode) for side, arr in h2h_prices.items()}
        imps = implied_from_decimal(agg_odds)
        fair = shin_fair_probs(imps) if fair_method == "Shin" else normalize_proportional(imps)
        ov = overround(imps)

        # ... (العرض المرئي للأعمدة والاحتمالات + اقتراحات كيللي)

    else:
        st.info("لا توجد أسعار 1×2 متاحة لهذه المباراة.")

    st.markdown("</div>", unsafe_allow_html=True)

    # --- Totals تحليل Over/Under
    totals_lines = extract_totals_lines(event)
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("Over/Under — الخطوط المتاحة")

    if totals_lines:
        # ... (منطق اختيار الخطوط، الحسابات، والعرض)
        pass
    else:
        st.info("لا توجد خطوط Over/Under متاحة.")

    st.markdown("</div>", unsafe_allow_html=True)

    # --- حفظ وتحميل Snapshot JSON
    analysis_payload = {
        "context": {...},
        "match": {...},
        "h2h": {...},
        "totals": {...},
    }
    st.session_state["snapshot"] = analysis_payload
    st.download_button(
        "تنزيل البيانات (JSON)",
        data=json.dumps(analysis_payload, ensure_ascii=False, indent=2),
        file_name="odds_snapshot.json",
        mime="application/json",
    )

    # --- Gemini التحليل بالذكاء الاصطناعي
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("تحليل شامل بالذكاء الاصطناعي (Gemini)")

    # ... (إعدادات الموديل، درجة الإبداع، اللغة، وزر التحليل)

    st.markdown("</div>", unsafe_allow_html=True)

else:
    st.info("اختر الدوري واضغط “جلب المباريات والأودز” لعرض المباريات.")
