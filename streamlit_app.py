# -*- coding: utf-8 -*-
import os, sys, json, importlib
import streamlit as st

# اقرأ الأسرار قبل أي import لـ fd_predictor
if "FOOTBALL_DATA_API_KEY" in st.secrets:
    os.environ.setdefault("FOOTBALL_DATA_API_KEY", st.secrets["FOOTBALL_DATA_API_KEY"])
# (اختياري) تحكّم في تباعد الطلبات لتقليل 429 من خلال Secrets
if "FD_MIN_INTERVAL_SEC" in st.secrets:
    os.environ.setdefault("FD_MIN_INTERVAL_SEC", str(st.secrets["FD_MIN_INTERVAL_SEC"]))

st.set_page_config(page_title="FD Predictor (Mobile)", page_icon="⚽", layout="wide")

COMP_CHOICES = ["", "CL","PD","PL","SA","BL1","FL1","DED","PPL","BSA","ELC"]

def import_fd():
    # إعادة الاستيراد بعد ضبط المفتاح (مهم لتفادي RuntimeError عند الاستيراد)
    if "fd_predictor" in sys.modules:
        del sys.modules["fd_predictor"]
    return importlib.import_module("fd_predictor")

st.title("توقع مباريات كرة القدم — واجهة تعمل على الجوال 📱")

with st.expander("إعداد مفتاح API (Football-Data.org) — ضروري للتشغيل", expanded=True):
    current_key = os.getenv("FOOTBALL_DATA_API_KEY", "")
    api_key_in = st.text_input(
        "FOOTBALL_DATA_API_KEY",
        value=current_key,
        type="password",
        help="ضع مفتاحك هنا إن لم تضبطه في Secrets أو متغيرات النظام",
    )
    colk1, colk2 = st.columns([1,1])
    with colk1:
        if api_key_in and api_key_in != current_key:
            os.environ["FOOTBALL_DATA_API_KEY"] = api_key_in
            st.success("تم ضبط المفتاح في هذه الجلسة.")
    with colk2:
        st.caption("تلميح: على Streamlit Cloud ضع المفتاح في Settings → Secrets.")

with st.form("predict_form"):
    col1, col2 = st.columns(2)
    with col1:
        team1 = st.text_input("الفريق 1 (قد يكون صاحب الأرض)", "Real Sociedad")
        team1_home = st.checkbox("هل الفريق 1 صاحب الأرض؟", value=True)
        comp_code = st.selectbox("كود المسابقة (اختياري)", options=COMP_CHOICES, index=1)
    with col2:
        team2 = st.text_input("الفريق 2", "Real Madrid")
        max_goals = st.text_input("حجم شبكة الأهداف (فارغ = ديناميكي)", value="")

    with st.expander("خيارات عرض البيانات الإضافية"):
        c1, c2, c3, c4 = st.columns(4)
        with c1: show_players = st.checkbox("إظهار السكواد", value=False)
        with c2: show_recent = st.checkbox("إظهار آخر المباريات", value=True)
        with c3: show_scorers = st.checkbox("إظهار هدّافي المسابقة", value=False)
        with c4: show_upcoming = st.checkbox("إظهار المباريات القادمة", value=False)
        r1, r2, r3, r4 = st.columns(4)
        with r1: recent_days = st.number_input("عدد الأيام للمباريات الأخيرة", min_value=30, max_value=720, value=180)
        with r2: recent_limit = st.number_input("عدد المباريات الأخيرة", min_value=1, max_value=20, value=5)
        with r3: recent_all_comps = st.checkbox("من كل المسابقات", value=False)
        with r4: scorers_limit = st.number_input("عدد الهدّافين", min_value=5, max_value=100, value=20)

    with st.expander("إعدادات متقدمة"):
        odds_json = st.text_area("أودز (JSON) لحساب كيللي", height=90,
                                 placeholder='{"1x2":{"home":2.1,"draw":3.4,"away":3.2}}')
        extras_json = st.text_area("Extras (JSON) مثل التشكيلات/الطقس/الإصابات", height=120,
                                   placeholder='{"formations":{"home":"4-3-3","away":"4-2-3-1"},"context":{"weather":"rain"}}')

    submitted = st.form_submit_button("توقّع")

if submitted:
    # تحقق من المفتاح قبل الاستيراد
    if not os.getenv("FOOTBALL_DATA_API_KEY"):
        st.error("يجب ضبط FOOTBALL_DATA_API_KEY قبل التوقّع. أضِفه في Secrets أو الحقل أعلاه.")
        st.stop()

    # استيراد السكربت الرئيسي بعد ضبط المفتاح
    try:
        fd = import_fd()
    except Exception as e:
        st.exception(e)
        st.stop()

    # معالجة مدخلات متقدمة
    mg = None
    try:
        mg = int(max_goals) if str(max_goals).strip() else None
    except Exception:
        mg = None

    try:
        odds = json.loads(odds_json) if str(odds_json).strip() else None
    except Exception as e:
        st.warning(f"خطأ في odds JSON: {e}")
        odds = None

    try:
        extras = json.loads(extras_json) if str(extras_json).strip() else None
    except Exception as e:
        st.warning(f"خطأ في extras JSON: {e}")
        extras = None

    comp = comp_code if comp_code else None

    with st.spinner("جارِ الحساب وجلب البيانات (قد يستغرق بعض الثواني لتفادي 429)..."):
        try:
            res = fd.predict_match(
                team1, team2,
                team1_is_home=team1_home,
                competition_code_override=comp,
                odds=odds,
                max_goals=mg,
                extras=extras,
                scorers_limit=int(scorers_limit or fd.SCORERS_LIMIT_DEFAULT)
            )
            if any([show_players, show_recent, show_scorers, show_upcoming]):
                res = fd.enrich_with_free_stats(
                    res,
                    include_players=show_players,
                    include_recent=show_recent,
                    include_scorers=show_scorers,
                    include_upcoming=show_upcoming,
                    recent_days=int(recent_days or 180),
                    recent_limit=int(recent_limit or 5),
                    recent_all_comps=recent_all_comps,
                    scorers_limit=int(scorers_limit or fd.SCORERS_LIMIT_DEFAULT),
                )
        except Exception as e:
            st.exception(e)
            st.stop()

    probs = res.get("probabilities", {}).get("1x2", {})
    lamb = res.get("lambdas", {})
    meta = res.get("meta", {})
    top = res.get("probabilities", {}).get("top_scorelines", [])

    st.subheader("احتمالات 1×2")
    cc1, cc2, cc3, cc4 = st.columns(4)
    cc1.metric("صاحب الأرض", f"{probs.get('home','?')}%")
    cc2.metric("التعادل", f"{probs.get('draw','?')}%")
    cc3.metric("الضيف", f"{probs.get('away','?')}%")
    cc4.write(f"DC rho: {meta.get('dc_rho')} | شبكة: {meta.get('max_goals_grid')}")

    st.subheader("معدل الأهداف (λ)")
    c1, c2 = st.columns(2)
    c1.write(f"المنزل: {lamb.get('home_final')} (الأساس {lamb.get('home_base')})")
    c2.write(f"الضيف: {lamb.get('away_final')} (الأساس {lamb.get('away_base')})")

    st.subheader("أعلى النتايج المتوقعة")
    if top:
        st.table(top)
    else:
        st.info("لا توجد نتائج عالية مرجّحة ضمن الشبكة.")

    with st.expander("الأسواق الإضافية"):
        mkts = res.get("probabilities", {}).get("markets", {})
        st.json(mkts)

    with st.expander("اقتراحات كيللي (إن تم تمرير أودز)"):
        st.json(res.get("kelly", {}))

    with st.expander("الإخراج الكامل (JSON)"):
        st.json(res)