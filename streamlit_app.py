# -*- coding: utf-8 -*-
import os, json, importlib
import streamlit as st
from datetime import datetime

# ============================================================
# 1) تحميل مفاتيح API من Secrets (قبل استيراد المزوّدات)
# ============================================================
if "ODDS_API_KEY" in st.secrets and st.secrets["ODDS_API_KEY"]:
    os.environ["ODDS_API_KEY"] = st.secrets["ODDS_API_KEY"]

if "GEMINI_API_KEY" in st.secrets and st.secrets["GEMINI_API_KEY"]:
    os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]

st.set_page_config(
    page_title="Market Predictor — Odds + Gemini",
    page_icon="🎯",
    layout="wide"
)

# ============================================================
# 2) الثيمات (CSS) + حفظ حالة المظهر
# ============================================================
if "ui_theme" not in st.session_state:
    st.session_state.ui_theme = "فاتح"

def inject_css(theme="فاتح"):
    if theme == "فاتح":
        css = """ <style> ... (CSS الفاتح) ... </style>"""
    else:
        css = """ <style> ... (CSS الداكن) ... </style>"""
    st.markdown(css, unsafe_allow_html=True)

inject_css(st.session_state.ui_theme)

# ============================================================
# 3) استيراد الوحدات (بعد ضبط المفاتيح)
# ============================================================
from odds_math import (
    implied_from_decimal,
    normalize_proportional,
    shin_fair_probs,
    overround,
    kelly_suggestions,
    aggregate_prices
)
import odds_provider_theoddsapi as odds_api
from gemini_helper import analyze_with_gemini

# ============================================================
# 4) رأس الصفحة + تبديل المظهر
# ============================================================
l, r = st.columns([3,1])
with l:
    st.markdown("<h1>Market Predictor — Odds + Gemini 🎯</h1>", unsafe_allow_html=True)
with r:
    theme = st.selectbox("المظهر", ["فاتح","داكن"], index=(0 if st.session_state.ui_theme=="فاتح" else 1))
    if theme != st.session_state.ui_theme:
        st.session_state.ui_theme = theme
        inject_css(theme)

# ============================================================
# 5) لوحة مفاتيح API
# ============================================================
with st.expander("مفاتيح API", expanded=True):
    st.write("ODDS_API_KEY:", "✅ مضبوط" if os.getenv("ODDS_API_KEY") else "❌ غير مضبوط")
    st.write("GEMINI_API_KEY:", "✅ مضبوط" if os.getenv("GEMINI_API_KEY") else "❌ غير مضبوط")

    c1, c2 = st.columns(2)

    # مفتاح Odds
    with c1:
        ak = st.text_input("ODDS_API_KEY", value="", type="password", placeholder="ألصق المفتاح هنا")
        if st.button("حفظ مفتاح الأودز للجلسة"):
            if ak.strip():
                os.environ["ODDS_API_KEY"] = ak.strip()
                importlib.reload(odds_api)
                st.success("تم حفظ مفتاح الأودز للجلسة.")
            else:
                st.warning("لم يتم إدخال مفتاح.")

    # مفتاح Gemini
    with c2:
        gk = st.text_input("GEMINI_API_KEY", value="", type="password", placeholder="ألصق المفتاح هنا")
        if st.button("حفظ مفتاح Gemini للجلسة"):
            if gk.strip():
                os.environ["GEMINI_API_KEY"] = gk.strip()
                st.success("تم حفظ مفتاح Gemini للجلسة.")
            else:
                st.warning("لم يتم إدخال مفتاح.")

# ============================================================
# 6) إعدادات السوق وجلب المباريات
# ============================================================
st.markdown("<div class='card'>", unsafe_allow_html=True)
st.subheader("اختيار الدوري والمباراة وإعدادات التحليل")

left, right = st.columns([2,1])
with left:
    if not os.getenv("ODDS_API_KEY"):
        st.error("يرجى ضبط ODDS_API_KEY أولاً.")
        st.stop()

    with st.spinner("جلب الدوريات..."):
        try:
            sports = odds_api.list_soccer_sports()
        except Exception as e:
            st.exception(e)
            st.stop()

    sport_options = {
        f"{s.get('group','')} — {s.get('title','')} ({s.get('key')})": s.get("key")
        for s in sports
    }
    sport_label = st.selectbox("اختر الدوري", options=list(sport_options.keys()))
    sport_key = sport_options[sport_label]

    regions = st.multiselect("مناطق الدفاتر", ["eu","uk","us","au"], default=["eu","uk"])
    markets_sel = st.multiselect("الأسواق", ["h2h","totals"], default=["h2h","totals"])

    if st.button("جلب المباريات والأودز"):
        st.session_state["events_data"] = None
        with st.spinner("جارِ الجلب..."):
            try:
                events, meta = odds_api.fetch_odds_for_sport(
                    sport_key,
                    regions=",".join(regions),
                    markets=",".join(markets_sel)
                )
                st.session_state["events_data"] = {
                    "events": events,
                    "meta": meta,
                    "regions": regions,
                    "markets": markets_sel
                }
                st.success(f"تم الجلب. Requests remaining: {meta.get('remaining')}")
            except Exception as e:
                st.exception(e)

with right:
    bankroll = st.number_input("حجم المحفظة", min_value=10.0, value=100.0, step=10.0)
    kelly_scale = st.slider("Kelly scale", 0.05, 1.0, 0.25, 0.05)
    min_edge = st.slider("أدنى ميزة (edge)", 0.0, 0.1, 0.02, 0.005)
    agg_mode = st.selectbox("تجميع أسعار الدفاتر", ["median","best","mean"], index=0)
    fair_method = st.selectbox("طريقة إزالة الهامش", ["Proportional","Shin"], index=1)

st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# 7) عرض المباريات + حساب 1×2 وTotals
# ============================================================
# (نفس منطقك مع bar_block + اقتراحات كيللي ...)
# ============================================================

# ============================================================
# 8) حفظ JSON + زر تنزيل
# ============================================================
analysis_payload = {...}  # (كما هو عندك)
st.session_state["snapshot"] = analysis_payload
st.download_button(
    "تنزيل البيانات (JSON)",
    data=json.dumps(analysis_payload, ensure_ascii=False, indent=2),
    file_name="odds_snapshot.json",
    mime="application/json"
)

# ============================================================
# 9) تحليل Gemini
# ============================================================
st.markdown("<div class='card'>", unsafe_allow_html=True)
st.subheader("تحليل شامل بالذكاء الاصطناعي (Gemini)")

col_g1, col_g2, col_g3 = st.columns(3)
with col_g1:
    gemini_model = st.selectbox("الموديل", ["gemini-1.5-flash", "gemini-1.5-pro"], index=0)
with col_g2:
    gemini_temp = st.slider("درجة الإبداع", 0.0, 1.0, 0.4, 0.05)
with col_g3:
    lang = st.selectbox("اللغة", ["ar","en"], index=0)

if st.button("بدء التحليل الآن"):
    snap = st.session_state.get("snapshot")
    if not snap:
        st.warning("لا توجد بيانات لتحليلها.")
    elif not os.getenv("GEMINI_API_KEY"):
        st.error("يرجى ضبط GEMINI_API_KEY.")
    else:
        with st.spinner("يجري التحليل عبر Gemini..."):
            try:
                analysis = analyze_with_gemini(
                    payload=snap,
                    api_key=os.getenv("GEMINI_API_KEY"),
                    model_name=gemini_model,
                    temperature=gemini_temp,
                    max_output_tokens=1400,
                    language=lang,
                    style="مختصر وقابل للتنفيذ"
                )
                if analysis:
                    st.markdown(analysis)
                    st.download_button(
                        "تنزيل تقرير التحليل (TXT)",
                        data=analysis,
                        file_name="gemini_analysis.txt",
                        mime="text/plain"
                    )
                else:
                    st.info("لم يُرجع Gemini نصاً.")
            except Exception as e:
                st.exception(e)

st.markdown("</div>", unsafe_allow_html=True)
