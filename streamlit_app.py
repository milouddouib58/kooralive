# -*- coding: utf-8 -*-
import os, sys, json, importlib
import streamlit as st

# اقرأ الأسرار قبل أي import لـ fd_predictor
if "FOOTBALL_DATA_API_KEY" in st.secrets:
    os.environ.setdefault("FOOTBALL_DATA_API_KEY", st.secrets["FOOTBALL_DATA_API_KEY"])
if "FD_MIN_INTERVAL_SEC" in st.secrets:
    os.environ.setdefault("FD_MIN_INTERVAL_SEC", str(st.secrets["FD_MIN_INTERVAL_SEC"]))

st.set_page_config(page_title="FD Predictor — Mobile", page_icon="⚽", layout="wide")

# تحسينات CSS — ثيم Neon Glass + بطاقات + أشرطة احتمالات + أزرار
st.markdown("""
<style>
/* حاوية وسطى أوسع */
.block-container { max-width: 1200px; }

/* خلفية متدرجة عميقة */
.stApp {
  background: radial-gradient(1200px at 15% 10%, #0c1624 0%, #0b1020 45%, #0a0e18 100%) !important;
}

/* عنوان بلمسة تدرّج */
h1, h2, h3 {
  letter-spacing: .3px;
}
[data-testid="stMarkdownContainer"] h1, .stMarkdown h1 {
  background: linear-gradient(90deg, #4fa3ff, #00d2d3, #c084fc);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

/* بطاقات زجاجية */
.neon-card {
  background: rgba(18, 26, 42, .72);
  border: 1px solid rgba(109, 116, 136, .18);
  box-shadow: 0 10px 30px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.02);
  border-radius: 14px;
  padding: 14px 16px;
  margin: 12px 0;
}

/* شارة صغيرة */
.chip {
  display: inline-flex; gap: 8px; align-items: center;
  background: rgba(79,163,255,.12);
  color: #cfe1ff;
  border: 1px solid rgba(79,163,255,.25);
  border-radius: 999px; padding: 6px 10px; margin: 4px 6px 0 0;
  font-size: .92em;
}

/* أشرطة الاحتمالات */
.prob {
  margin: 8px 0 12px;
}
.prob .lbl { margin-bottom: 6px; color: #a8b3c8; font-size: .95em }
.prob .bar {
  height: 12px; border-radius: 999px; overflow: hidden; background: rgba(255,255,255,.08);
  border: 1px solid rgba(255,255,255,.06);
}
.prob .fill { height: 100%; transition: width .5s ease }
.prob.home .fill { background: linear-gradient(90deg, #22c55e, #16a34a); }
.prob.draw .fill { background: linear-gradient(90deg, #f59e0b, #d97706); }
.prob.away .fill { background: linear-gradient(90deg, #ef4444, #b91c1c); }

/* تنسيق st.metric في بطاقات زجاجية */
[data-testid="metric-container"] {
  background: rgba(12, 18, 32, .7);
  border: 1px solid rgba(255,255,255,.06);
  box-shadow: 0 6px 16px rgba(0,0,0,.25);
  padding: 14px; border-radius: 14px;
}

/* أزرار */
.stButton>button {
  background: linear-gradient(135deg, #4fa3ff, #2563eb);
  border: 0; color: #fff;
  border-radius: 12px; padding: 10px 16px;
  box-shadow: 0 8px 20px rgba(37,99,235,.3);
}
.stButton>button:hover { filter: brightness(1.06) }

/* Expanders */
.streamlit-expanderHeader {
  font-weight: 700;
}

/* جداول أنيقة */
[data-testid="stTable"] table {
  border-radius: 12px; overflow: hidden;
  border: 1px solid rgba(255,255,255,.06);
}
</style>
""", unsafe_allow_html=True)

COMP_CHOICES = ["", "CL","PD","PL","SA","BL1","FL1","DED","PPL","BSA","ELC"]

def import_fd():
    # إعادة الاستيراد بعد ضبط المفتاح (مهم لتفادي RuntimeError عند الاستيراد)
    if "fd_predictor" in sys.modules:
        del sys.modules["fd_predictor"]
    return importlib.import_module("fd_predictor")

# Hero
st.title("توقّع مباريات كرة القدم — واجهة عصرية للجوال ⚽📱")
st.caption("Poisson + Dixon-Coles + ELO + عوامل قبل المباراة — مع مظهر زجاجي أنيق")

with st.expander("إعداد مفتاح API (Football-Data.org) — ضروري للتشغيل", expanded=True):
    current_key = os.getenv("FOOTBALL_DATA_API_KEY", "")
    api_key_in = st.text_input("FOOTBALL_DATA_API_KEY", value=current_key, type="password",
                               help="ضع مفتاحك هنا إن لم تضبطه في Secrets أو متغيرات النظام")
    cols = st.columns([1,1,2])
    with cols[0]:
        if api_key_in and api_key_in != current_key:
            os.environ["FOOTBALL_DATA_API_KEY"] = api_key_in
            st.success("تم ضبط المفتاح في هذه الجلسة ✅")
    with cols[1]:
        st.caption("تلميح: على Streamlit Cloud ضع المفتاح في Settings → Secrets.")

with st.form("predict_form"):
    ctop1, ctop2 = st.columns(2)
    with ctop1:
        st.markdown("<div class='neon-card'>", unsafe_allow_html=True)
        team1 = st.text_input("الفريق 1 (قد يكون صاحب الأرض)", "Real Sociedad")
        team1_home = st.checkbox("هل الفريق 1 صاحب الأرض؟", value=True)
        comp_code = st.selectbox("كود المسابقة (اختياري)", options=COMP_CHOICES, index=1)
        st.markdown("</div>", unsafe_allow_html=True)
    with ctop2:
        st.markdown("<div class='neon-card'>", unsafe_allow_html=True)
        team2 = st.text_input("الفريق 2", "Real Madrid")
        max_goals = st.text_input("حجم شبكة الأهداف (فارغ = ديناميكي)", value="")
        st.markdown("</div>", unsafe_allow_html=True)

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

    submitted = st.form_submit_button("⚡ توقّع الآن")

if not submitted:
    st.info("ضَع الفريقين واضغط توقّع. أول تشغيل قد يستغرق بضع ثوانٍ لتفادي Rate Limit.")

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
    mkts = res.get("probabilities", {}).get("markets", {})
    kelly = res.get("kelly", {}) or {}

    # بطاقة — احتمالات 1×2 (مع أشرطة جميلة)
    st.markdown("<div class='neon-card'>", unsafe_allow_html=True)
    st.subheader("احتمالات 1×2")
    colp1, colp2, colp3 = st.columns(3)
    def prob_block(label, val, kind):
        val = float(val or 0)
        html = f"""
        <div class='prob {kind}'>
            <div class='lbl'>{label} — <b>{val:.2f}%</b></div>
            <div class='bar'><div class='fill' style='width:{max(0,min(100,val))}%;'></div></div>
        </div>
        """
        st.markdown(html, unsafe_allow_html=True)
    with colp1:
        prob_block("صاحب الأرض", probs.get("home", 0), "home")
    with colp2:
        prob_block("التعادل", probs.get("draw", 0), "draw")
    with colp3:
        prob_block("الضيف", probs.get("away", 0), "away")
    st.markdown(f"<span class='chip'>DC rho: {meta.get('dc_rho')}</span> <span class='chip'>شبكة: {meta.get('max_goals_grid')}</span>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # بطاقة — معدلات الأهداف
    st.markdown("<div class='neon-card'>", unsafe_allow_html=True)
    st.subheader("معدل الأهداف (λ)")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("منزل — النهائي", lamb.get("home_final"))
    m2.metric("منزل — الأساس", lamb.get("home_base"))
    m3.metric("ضيف — النهائي", lamb.get("away_final"))
    m4.metric("ضيف — الأساس", lamb.get("away_base"))
    st.caption(f"المسابقة: {(meta.get('competition') or {}).get('code')} · العيّنة: {(meta.get('samples') or {}).get('matches_used')}")
    st.markdown("</div>", unsafe_allow_html=True)

    # بطاقة — أعلى النتائج
    st.markdown("<div class='neon-card'>", unsafe_allow_html=True)
    st.subheader("أعلى النتائج المتوقعة")
    if top:
        chips = " ".join([f"<span class='chip'>{t.get('score')} — {t.get('prob')}%</span>" for t in top])
        st.markdown(chips, unsafe_allow_html=True)
    else:
        st.info("لا توجد نتائج عالية مرجّحة ضمن الشبكة.")
    st.markdown("</div>", unsafe_allow_html=True)

    # الأسواق الإضافية + كيللي
    cL, cR = st.columns(2)
    with cL:
        st.markdown("<div class='neon-card'>", unsafe_allow_html=True)
        st.subheader("الأسواق الإضافية")
        st.write(mkts)
        st.markdown("</div>", unsafe_allow_html=True)
    with cR:
        st.markdown("<div class='neon-card'>", unsafe_allow_html=True)
        st.subheader("اقتراحات كيللي")
        st.write(kelly)
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("الإخراج الكامل (JSON)"):
        st.json(res)
