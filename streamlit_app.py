# -*- coding: utf-8 -*-
import json
import importlib
import os
from datetime import datetime

import streamlit as st

# 1) حمّل المفاتيح من Secrets أولاً (قبل أي استيراد لمزوّد الأودز)
if "ODDS_API_KEY" in st.secrets and st.secrets["ODDS_API_KEY"]:
    os.environ["ODDS_API_KEY"] = str(st.secrets["ODDS_API_KEY"]).strip()
if "GEMINI_API_KEY" in st.secrets and st.secrets["GEMINI_API_KEY"]:
    os.environ["GEMINI_API_KEY"] = str(st.secrets["GEMINI_API_KEY"]).strip()

st.set_page_config(
    page_title="Market Predictor — Odds + Gemini", page_icon="🎯", layout="wide"
)

# 2) ثيم CSS (فاتح/داكن)
if "ui_theme" not in st.session_state:
    st.session_state.ui_theme = "فاتح"


def inject_css(theme="فاتح"):
    if theme == "فاتح":
        css = """
        <style>
        :root{--bg:#f7fafc;--fg:#0f172a;--muted:#475569;--card:#ffffff;--border:#e5e7eb;--primary:#2563eb}
        .stApp{background:radial-gradient(1200px at 10% -10%,#eef2ff 0%,#f7fafc 45%,#f7fafc 100%)!important}
        .block-container{max-width:1180px}
        .card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:14px 16px;box-shadow:0 6px 14px rgba(16,24,40,.06)}
        .chip{display:inline-flex;gap:8px;align-items:center;background:#f3f4f6;color:#111827;border:1px solid var(--border);border-radius:999px;padding:6px 10px;margin:4px 6px 0 0;font-size:.92em}
        .prob .lbl{color:var(--muted);font-size:.95em;margin-bottom:6px}
        .prob .bar{height:12px;border-radius:999px;overflow:hidden;background:#e5e7eb;border:1px solid #e2e8f0}
        .prob .fill{height:100%;transition:width .5s ease}
        .prob.home .fill{background:linear-gradient(90deg,#22c55e,#16a34a)}
        .prob.draw .fill{background:linear-gradient(90deg,#f59e0b,#d97706)}
        .prob.away .fill{background:linear-gradient(90deg,#ef4444,#b91c1c)}
        .stButton>button{background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#fff;border:0;border-radius:12px;padding:10px 16px}
        [data-testid="metric-container"]{background:#f8fafc;border:1px solid var(--border);border-radius:12px;padding:12px}
        </style>"""
    else:
        css = """
        <style>
        :root{--bg:#0b1020;--fg:#eaf2ff;--muted:#a3b1c6;--card:#121a2a;--border:#1e2a3b;--primary:#4fa3ff}
        .stApp{background:radial-gradient(1200px at 15% -10%,#0c1626 0%,#0b1020 45%,#0a0e18 100%)!important}
        .block-container{max-width:1180px}
        .card{background:rgba(18,26,42,.78);border:1px solid rgba(109,116,136,.22);border-radius:14px;padding:14px 16px;box-shadow:0 12px 28px rgba(0,0,0,.35)}
        .chip{display:inline-flex;gap:8px;align-items:center;background:#0f1626;color:#dfeaff;border:1px solid var(--border);border-radius:999px;padding:6px 10px;margin:4px 6px 0 0;font-size:.92em}
        .prob .lbl{color:var(--muted);font-size:.95em;margin-bottom:6px}
        .prob .bar{height:12px;border-radius:999px;overflow:hidden;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.08)}
        .prob .fill{height:100%;transition:width .5s ease}
        .prob.home .fill{background:linear-gradient(90deg,#22c55e,#16a34a)}
        .prob.draw .fill{background:linear-gradient(90deg,#f59e0b,#d97706)}
        .prob.away .fill{background:linear-gradient(90deg,#ef4444,#b91c1c)}
        .stButton>button{background:linear-gradient(135deg,#4fa3ff,#2563eb);color:#fff;border:0;border-radius:12px;padding:10px 16px}
        [data-testid="metric-container"]{background:rgba(12,18,32,.7);border:1px solid rgba(255,255,255,.06);border-radius:12px;padding:12px}
        </style>"""
    st.markdown(css, unsafe_allow_html=True)


inject_css(st.session_state.ui_theme)

# 3) استيراد الوحدات (بعد ضبط المفاتيح)
from odds_math import (
    aggregate_prices,
    implied_from_decimal,
    kelly_suggestions,
    normalize_proportional,
    overround,
    shin_fair_probs,
)
import odds_provider_theoddsapi as odds_api
from gemini_helper import analyze_with_gemini

# 4) دوال مساعدة لضمان المفتاح وترقيع المزوّد
def refresh_odds_provider() -> str:
    """يضمن وجود ODDS_API_KEY في البيئة، ويرقّع odds_api.API_KEY إن وُجد، ثم يعيد تحميل المزوّد."""
    key = os.getenv("ODDS_API_KEY")
    if not key and "ODDS_API_KEY" in st.secrets:
        key = str(st.secrets["ODDS_API_KEY"]).strip() or ""

    if key:
        os.environ["ODDS_API_KEY"] = key
        try:
            # ترقيع نسخ قديمة فيها API_KEY ثابت
            if hasattr(odds_api, "API_KEY"):
                odds_api.API_KEY = key
        except Exception:
            pass
        # إعادة تحميل المزوّد لالتقاط البيئة الجديدة
        importlib.reload(odds_api)
    return key or ""


# رأس الصفحة + تبديل المظهر
l, r = st.columns([3, 1])
with l:
    st.markdown("<h1>Market Predictor — Odds + Gemini 🎯</h1>", unsafe_allow_html=True)
with r:
    theme = st.selectbox(
        "المظهر", ["فاتح", "داكن"], index=(0 if st.session_state.ui_theme == "فاتح" else 1)
    )
    if theme != st.session_state.ui_theme:
        st.session_state.ui_theme = theme
        inject_css(theme)
        st.rerun()

# مفاتيح API
with st.expander("مفاتيح API", expanded=True):
    st.write("ODDS_API_KEY:", "✅ مضبوط" if os.getenv("ODDS_API_KEY") else "❌ غير مضبوط")
    st.write("GEMINI_API_KEY:", "✅ مضبوط" if os.getenv("GEMINI_API_KEY") else "❌ غير مضبوط")

    c1, c2 = st.columns(2)
    with c1:
        ak = st.text_input(
            "ODDS_API_KEY (لن يُعرض أو يُحفظ)",
            value="",
            type="password",
            placeholder="ألصق المفتاح هنا",
        )
        if st.button("حفظ مفتاح الأودز للجلسة"):
            if ak.strip():
                os.environ["ODDS_API_KEY"] = ak.strip()
                refresh_odds_provider()
                st.success("تم حفظ مفتاح الأودز للجلسة.")
                st.rerun()
            else:
                st.warning("لم يتم إدخال مفتاح.")
    with c2:
        gk = st.text_input(
            "GEMINI_API_KEY (اختياري، لن يُعرض أو يُحفظ)",
            value="",
            type="password",
            placeholder="ألصق المفتاح هنا",
        )
        if st.button("حفظ مفتاح Gemini للجلسة"):
            if gk.strip():
                os.environ["GEMINI_API_KEY"] = gk.strip()
                st.success("تم حفظ مفتاح Gemini للجلسة.")
                st.rerun()
            else:
                st.warning("لم يتم إدخال مفتاح.")

# إعدادات السوق والتحليل
st.markdown("<div class='card'>", unsafe_allow_html=True)
st.subheader("اختيار الدوري والمباراة وإعدادات التحليل")

left, right = st.columns([2, 1])
with left:
    # تأكيد المفتاح وإعادة تحميل المزوّد قبل أي نداء
    if not refresh_odds_provider():
        st.error("يرجى ضبط ODDS_API_KEY أولاً (Secrets أو الحقل أعلاه).")
        st.stop()

    with st.spinner("جلب الدوريات..."):
        try:
            sports = odds_api.list_soccer_sports()
        except Exception as e:
            st.exception(e)
            st.stop()

    sport_options = {
        f"{s.get('group', '')} — {s.get('title', '')} ({s.get('key')})": s.get("key")
        for s in sports
    }
    sport_label = st.selectbox("اختر الدوري", options=list(sport_options.keys()))
    sport_key = sport_options[sport_label]

    regions = st.multiselect(
        "مناطق الدفاتر (regions)", ["eu", "uk", "us", "au"], default=["eu", "uk"]
    )
    markets_sel = st.multiselect(
        "الأسواق", ["h2h", "totals"], default=["h2h", "totals"]
    )

    if st.button("جلب المباريات والأودز"):
        st.session_state["events_data"] = None
        with st.spinner("جارِ الجلب..."):
            try:
                # إعادة التأكيد قبل النداء الفعلي
                refresh_odds_provider()
                events, meta = odds_api.fetch_odds_for_sport(
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

with right:
    bankroll = st.number_input("حجم المحفظة", min_value=10.0, value=100.0, step=10.0)
    kelly_scale = st.slider("Kelly scale", 0.05, 1.0, 0.25, 0.05)
    min_edge = st.slider("أدنى ميزة (edge)", 0.0, 0.1, 0.02, 0.005)
    agg_mode = st.selectbox("تجميع أسعار الدفاتر", ["median", "best", "mean"], index=0)
    fair_method = st.selectbox(
        "طريقة إزالة الهامش", ["Proportional", "Shin"], index=1
    )

st.markdown("</div>", unsafe_allow_html=True)

# عرض المباريات والنتائج
events_data = st.session_state.get("events_data")
if events_data and events_data.get("events"):
    evs = events_data["events"]

    # قائمة المباريات
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

    # 1×2 (H2H)
    h2h_prices = odds_api.extract_h2h_prices(event)
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("1×2 — إجماع السوق")

    have_h2h = any(h2h_prices.values())
    agg_odds = imps = fair = ov = sugg = None

    if have_h2h:
        agg_odds = {
            side: aggregate_prices(arr, mode=agg_mode)
            for side, arr in h2h_prices.items()
        }
        st.write("أسعار مجمعة:", agg_odds)
        imps = implied_from_decimal(agg_odds)
        fair = (
            shin_fair_probs(imps)
            if fair_method == "Shin"
            else normalize_proportional(imps)
        )
        ov = overround(imps)

        c1, c2, c3 = st.columns(3)

        def bar_block(col, label, p):
            with col:
                try:
                    pct = float(p) * 100.0
                except (ValueError, TypeError):
                    pct = 0.0
                st.markdown(
                    f"""<div class='prob {"home" if "Home" in label else "away" if "Away" in label else "draw"}'>
                           <div class='lbl'>{label} — <b>{pct:.2f}%</b></div>
                           <div class='bar'><div class='fill' style='width:{max(0,min(100,pct))}%;'></div></div>
                       </div>""",
                    unsafe_allow_html=True,
                )

        bar_block(c1, "Home", fair.get("home", 0))
        bar_block(c2, "Draw", fair.get("draw", 0))
        bar_block(c3, "Away", fair.get("away", 0))

        st.markdown(
            f"<span class='chip'>Overround: {ov:.3f}</span> <span class='chip'>طريقة: {fair_method}</span>",
            unsafe_allow_html=True,
        )
        sugg = kelly_suggestions(
            fair, agg_odds, bankroll=bankroll, kelly_scale=kelly_scale, min_edge=min_edge
        )
        st.subheader("اقتراحات كيللي (1×2)")
        st.json(sugg if sugg else {"info": "لا اقتراحات ضمن شروط edge/Kelly"})
    else:
        st.info("لا توجد أسعار 1×2 متاحة لهذه المباراة.")
    st.markdown("</div>", unsafe_allow_html=True)

    # Totals
    totals_lines = odds_api.extract_totals_lines(event)
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("Over/Under — الخطوط المتاحة")

    line = None
    odds_ou = fair_ou = ov_ou = sugg_ou = None

    if totals_lines:
        lines_sorted = sorted(totals_lines.keys(), key=lambda x: float(x))
        line = st.selectbox("اختر خط المجموع", lines_sorted, index=0)
        odds_ou = {
            "over": aggregate_prices(totals_lines[line]["over"], mode=agg_mode),
            "under": aggregate_prices(totals_lines[line]["under"], mode=agg_mode),
        }
        st.write(f"أسعار مجمعة لخط {line}:", odds_ou)
        imps_ou = implied_from_decimal(odds_ou)
        fair_ou = (
            shin_fair_probs(imps_ou)
            if fair_method == "Shin"
            else normalize_proportional(imps_ou)
        )
        ov_ou = overround(imps_ou)
        c_ou1, c_ou2 = st.columns(2)

        def bar(col, label, p):
            with col:
                try:
                    pct = float(p) * 100.0
                except (ValueError, TypeError):
                    pct = 0.0
                st.markdown(
                    f"""<div class='prob {"home" if "Over" in label else "away"}'>
                           <div class='lbl'>{label} — <b>{pct:.2f}%</b></div>
                           <div class='bar'><div class='fill' style='width:{max(0,min(100,pct))}%;'></div></div>
                       </div>""",
                    unsafe_allow_html=True,
                )

        bar(c_ou1, f"Over {line}", fair_ou.get("over", 0))
        bar(c_ou2, f"Under {line}", fair_ou.get("under", 0))

        st.markdown(
            f"<span class='chip'>Overround: {ov_ou:.3f}</span>",
            unsafe_allow_html=True,
        )
        sugg_ou = kelly_suggestions(
            fair_ou,
            odds_ou,
            bankroll=bankroll,
            kelly_scale=kelly_scale,
            min_edge=min_edge,
        )
        st.subheader("اقتراحات كيللي (Over/Under)")
        st.json(sugg_ou if sugg_ou else {"info": "لا اقتراحات ضمن الشروط"})
    else:
        st.info("لا توجد خطوط Over/Under متاحة.")
    st.markdown("</div>", unsafe_allow_html=True)

    # لقطة JSON + تنزيل
    analysis_payload = {
        "context": {
            "sport_key": sport_key,
            "regions": events_data.get("regions"),
            "markets": events_data.get("markets"),
            "agg_mode": agg_mode,
            "fair_method": fair_method,
            "bankroll": bankroll,
            "kelly_scale": kelly_scale,
            "min_edge": min_edge,
        },
        "match": {
            "home_team": event.get("home_team"),
            "away_team": event.get("away_team"),
            "commence_time": event.get("commence_time"),
        },
        "h2h": {
            "book_prices": h2h_prices,
            "aggregated": agg_odds,
            "fair_probs": fair,
            "overround": ov,
            "kelly_suggestions": sugg,
        },
        "totals": {
            "all_lines": totals_lines,
            "selected_line": line,
            "selected_odds": odds_ou,
            "selected_fair": fair_ou,
            "selected_overround": ov_ou,
            "kelly_suggestions": sugg_ou,
        },
    }
    st.session_state["snapshot"] = analysis_payload
    st.download_button(
        "تنزيل البيانات (JSON)",
        data=json.dumps(analysis_payload, ensure_ascii=False, indent=2),
        file_name="odds_snapshot.json",
        mime="application/json",
    )

    # تحليل Gemini
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("تحليل شامل بالذكاء الاصطناعي (Gemini)")
    col_g1, col_g2, col_g3 = st.columns(3)
    with col_g1:
        gemini_model = st.selectbox(
            "الموديل", ["gemini-2.0-flash", "gemini-2.5-flash","gemini-flash-latest", "gemini-2.0-flash-lite", "gemini-2.5-flash-image" ], index=0
        )
    with col_g2:
        gemini_temp = st.slider("درجة الإبداع", 0.0, 1.0, 0.4, 0.05)
    with col_g3:
        lang = st.selectbox("اللغة", ["ar", "en"], index=0)

    if st.button("بدء التحليل الآن"):
        snap = st.session_state.get("snapshot")
        if not snap:
            st.warning("لا توجد لقطة بيانات لتحليلها. اجلب مباراة/أودز أولاً.")
        elif not os.getenv("GEMINI_API_KEY"):
            st.error("يرجى ضبط GEMINI_API_KEY (Secrets أو الحقل في الأعلى).")
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
                        style="مختصر وقابل للتنفيذ",
                    )
                    if analysis:
                        st.markdown(analysis)
                        st.download_button(
                            "تنزيل تقرير التحليل (TXT)",
                            data=analysis,
                            file_name="gemini_analysis.txt",
                            mime="text/plain",
                        )
                    else:
                        st.info("لم يُرجع Gemini نصاً. جرّب موديل/إعدادات مختلفة.")
                except Exception as e:
                    st.exception(e)
    st.markdown("</div>", unsafe_allow_html=True)
else:
    st.info("اختر الدوري واضغط “جلب المباريات والأودز” لعرض المباريات.")

