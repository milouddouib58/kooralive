# -*- coding: utf-8 -*-
import os
import sys
import math
import time
import random
import json
import argparse
import difflib
import traceback
import requests
import re
import threading
from functools import lru_cache
from datetime import datetime, timedelta
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

VERSION = "v4.6"

# ===========================
# إعدادات عامة وتهيئة
# ===========================

# يجب ضبط مفتاح API عبر متغير البيئة FOOTBALL_DATA_API_KEY
API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
if not API_KEY:
    raise RuntimeError("يرجى ضبط FOOTBALL_DATA_API_KEY في متغيرات البيئة.")

BASE_URL = "https://api.football-data.org/v4"
HEADERS = {
    "X-Auth-Token": API_KEY,
    "User-Agent": f"FD-Predictor/{VERSION} (+https://football-data.org)"
}

SESSION = requests.Session()
# تحسين الاعتمادية للشبكة: Retry على Session (بدون 429)
_retry = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[500, 502, 503, 504],  # أزلنا 429 لنعالجها يدوياً
    allowed_methods=frozenset(["GET"]),
    respect_retry_after_header=True,
)
SESSION.mount("https://", HTTPAdapter(max_retries=_retry))

# محدد معدل بسيط للطلبات (لتجنّب 429)
_MIN_INTERVAL_SEC = float(os.getenv("FD_MIN_INTERVAL_SEC", "6.5"))  # تباعد افتراضي بين الطلبات
_last_call_ts = 0.0
_last_call_lock = threading.Lock()

# حدود/إعدادات قابلة للتعديل عبر متغيرات البيئة
MATCHES_CHUNK_DAYS = int(os.getenv("FD_MATCHES_CHUNK_DAYS", "30"))  # شريحة /matches (رفعت من 10 → 30)
TEAM_MATCHES_CHUNK_DAYS = int(os.getenv("FD_TEAM_MATCHES_CHUNK_DAYS", "30"))  # شريحة /teams/{id}/matches (رفعت من 10 → 30)
MAX_CHUNKS = int(os.getenv("FD_MAX_CHUNKS", "120"))  # أقصى عدد شرائح
H2H_LOOKBACK_DAYS = int(os.getenv("FD_H2H_LOOKBACK_DAYS", "365"))  # سنة واحدة افتراضياً

# انكماش أقوى + EWMA أنعم
PRIOR_GAMES = int(os.getenv("FD_PRIOR_GAMES", "12"))  # كان 6 -> الآن 12
HALF_LIFE_DAYS = int(os.getenv("FD_HALF_LIFE_DAYS", "270"))  # كان 180 -> الآن 270
DC_RHO_MAX = float(os.getenv("FD_DC_RHO_MAX", "0.3"))  # حد |rho|

# قصّ λ النهائي (شبكة أمان)
LAM_CLAMP_MIN = float(os.getenv("FD_LAM_CLAMP_MIN", "0.1"))
LAM_CLAMP_MAX = float(os.getenv("FD_LAM_CLAMP_MAX", "3.0"))

# قصّ قوى الهجوم/الدفاع A/D — أضيق لتقليل التطرف
AD_CLAMP_MIN = float(os.getenv("FD_AD_CLAMP_MIN", "0.7"))  # كان 0.5
AD_CLAMP_MAX = float(os.getenv("FD_AD_CLAMP_MAX", "1.3"))  # كان 1.5

# ELO: حدود تأثيره على λ + مقياس التأثير
ELO_LAM_MIN = float(os.getenv("FD_ELO_LAM_MIN", "0.88"))  # كان 0.9 -> الآن 0.88
ELO_LAM_MAX = float(os.getenv("FD_ELO_LAM_MAX", "1.12"))  # كان 1.1 -> الآن 1.12
ELO_SCALE = float(os.getenv("FD_ELO_SCALE", "0.28"))  # كان 0.2 -> الآن 0.28 (قابل للضبط)

MAX_GOALS_GRID = int(os.getenv("FD_MAX_GOALS_GRID", "8"))  # شبكة حساب الاحتمالات (احتياطي)

# أولويات المسابقات عند تقاطع فريقين (رموز competitions)
COMPETITION_PRIORITY = [
    "CL", "PD", "PL", "SA", "BL1", "FL1", "DED", "PPL", "BSA", "ELC"
]

# مسابقات إضافية (للبحث عن الفرق خارج TIER_ONE عند الفشل)
EXTRA_COMP_CODES = [c.strip().upper() for c in os.getenv("FD_EXTRA_COMP_CODES", "ELC").split(",") if c.strip()]

# ===========================
# عوامل إضافية (Pre-match)
# ===========================
FORM_SOS_GAMMA = float(os.getenv("FD_FORM_SOS_GAMMA", "0.35"))  # وزن قوة الخصم في "الفورم"
FORMATION_MAX_BOOST = float(os.getenv("FD_FORMATION_MAX_BOOST", "0.06"))  # سقف تأثير الخطة ±6%
GOAL_RATE_MAX_BOOST = float(os.getenv("FD_GOAL_RATE_MAX_BOOST", "0.06"))  # سقف تأثير معدل التهديف الحديث ±6%
TABLE_K = float(os.getenv("FD_TABLE_K", "0.06"))  # حساسية عامل الترتيب

# إصابات/غيابات (هيوريستيك)
INJ_STARTER_ATK = float(os.getenv("FD_INJ_STARTER_ATK", "0.02"))
INJ_STARTER_DEF = float(os.getenv("FD_INJ_STARTER_DEF", "0.02"))
INJ_KEY_BONUS = float(os.getenv("FD_INJ_KEY_BONUS", "0.01"))
INJ_MAX_ATK_DROP = float(os.getenv("FD_INJ_MAX_ATK_DROP", "0.15"))
INJ_MAX_DEF_RISE = float(os.getenv("FD_INJ_MAX_DEF_RISE", "0.15"))

# Kelly
KELLY_SCALE = float(os.getenv("FD_KELLY_SCALE", "0.5"))  # نصف-كيللي افتراضياً
KELLY_MIN_EDGE = float(os.getenv("FD_KELLY_MIN_EDGE", "0.02"))
KELLY_MAX_FRAC = float(os.getenv("FD_KELLY_MAX_FRAC", "0.15"))

# تقويم مجموع الأهداف
LAM_TOTAL_SHRINK = float(os.getenv("FD_LAM_TOTAL_SHRINK", "0.35"))

# معايرة احتمالات 1×2 بدرجة حرارة
PROB_TEMP = float(os.getenv("FD_PROB_TEMP", "1.0"))  # <1 تفلط، >1 تشدّد

# TTL للكاش (ثوانٍ)
TTL_COMPETITIONS = int(os.getenv("FD_TTL_COMPETITIONS", str(6 * 3600)))  # 6 ساعات
TTL_TEAMS = int(os.getenv("FD_TTL_TEAMS", str(24 * 3600)))  # 24 ساعة (سكواد يتغير ببطء)

# ===========================
# تعزيزات إضافية (قابلة للضبط عبر Env)
# ===========================
# Squad
SQUAD_YOUNG_AGE = int(os.getenv("FD_SQUAD_YOUNG_AGE", "23"))
SQUAD_OLD_AGE = int(os.getenv("FD_SQUAD_OLD_AGE", "29"))
SQUAD_YOUNG_GF_BONUS = float(os.getenv("FD_SQUAD_YOUNG_GF_BONUS", "0.02"))
SQUAD_YOUNG_GA_PENALTY = float(os.getenv("FD_SQUAD_YOUNG_GA_PENALTY", "0.005"))
SQUAD_OLD_GF_DROP = float(os.getenv("FD_SQUAD_OLD_GF_DROP", "0.01"))
SQUAD_OLD_GA_BONUS = float(os.getenv("FD_SQUAD_OLD_GA_BONUS", "0.01"))

SQUAD_DEF_MIN_DEFENDERS = int(os.getenv("FD_SQUAD_DEF_MIN_DEFENDERS", "7"))
SQUAD_DEF_THIN_PENALTY_STEP = float(os.getenv("FD_SQUAD_DEF_THIN_PENALTY_STEP", "0.01"))
SQUAD_DEF_THIN_MAX_PENALTY = float(os.getenv("FD_SQUAD_DEF_THIN_MAX_PENALTY", "0.05"))

SQUAD_ATT_COUNT_THRESHOLD = int(os.getenv("FD_SQUAD_ATT_COUNT_THRESHOLD", "7"))
SQUAD_ATT_BONUS = float(os.getenv("FD_SQUAD_ATT_BONUS", "0.01"))

# Top Scorers
SCORERS_LIMIT_DEFAULT = int(os.getenv("FD_SCORERS_LIMIT_DEFAULT", "30"))
TOPSCORER_GOAL_WEIGHT = float(os.getenv("FD_TOPSCORER_GOAL_WEIGHT", "0.004"))
TOPSCORER_ASSIST_WEIGHT = float(os.getenv("FD_TOPSCORER_ASSIST_WEIGHT", "0.002"))
TOPSCORER_MAX_BOOST = float(os.getenv("FD_TOPSCORER_MAX_BOOST", "0.06"))

# Home/Away split
HOME_AWAY_SPLIT_TAKE = int(os.getenv("FD_HOME_AWAY_SPLIT_TAKE", "10"))
HOME_AWAY_SPLIT_ALPHA = float(os.getenv("FD_HOME_AWAY_SPLIT_ALPHA", "0.4"))
HOME_AWAY_SPLIT_MAX = float(os.getenv("FD_HOME_AWAY_SPLIT_MAX", "0.05"))

# Fatigue (ضغط المباريات)
FATIGUE_PAST_DAYS = int(os.getenv("FD_FATIGUE_PAST_DAYS", "7"))
FATIGUE_NEXT_DAYS = int(os.getenv("FD_FATIGUE_NEXT_DAYS", "7"))
FATIGUE_THRESHOLD = float(os.getenv("FD_FATIGUE_THRESHOLD", "2"))
FATIGUE_PAST_WEIGHT = float(os.getenv("FD_FATIGUE_PAST_WEIGHT", "1.0"))
FATIGUE_NEXT_WEIGHT = float(os.getenv("FD_FATIGUE_NEXT_WEIGHT", "0.8"))
FATIGUE_ATK_STEP = float(os.getenv("FD_FATIGUE_ATK_STEP", "0.02"))
FATIGUE_DEF_STEP = float(os.getenv("FD_FATIGUE_DEF_STEP", "0.02"))
FATIGUE_MAX = float(os.getenv("FD_FATIGUE_MAX", "0.06"))

# Comeback (HT → FT)
COMEBACK_TAKE = int(os.getenv("FD_COMEBACK_TAKE", "8"))
COMEBACK_MAX = float(os.getenv("FD_COMEBACK_MAX", "0.03"))

# ===========================
# أدوات مساعدة
# ===========================
def log(msg: str):
    print(msg, flush=True)

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def poisson_pmf(k, lam):
    # نسخة مستقرة عددياً باستخدام log-gamma
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(k * math.log(lam) - lam - math.lgamma(k + 1))

def backoff_sleep(attempt):
    # exponential backoff + jitter
    base = min(30, 2 ** attempt)
    jitter = random.uniform(0, 0.6)
    time.sleep(base + jitter)

def parse_date_safe(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def normalize_date_range(date_from: str, date_to: str):
    d1 = parse_date_safe(date_from)
    d2 = parse_date_safe(date_to)
    if d1 and d2 and d1 > d2:
        d1, d2 = d2, d1
    return (d1.isoformat() if d1 else date_from, (d2.isoformat() if d2 else date_to))

def chunked_date_ranges(date_from: str, date_to: str, chunk_days: int, max_chunks: int = None):
    df, dt = normalize_date_range(date_from, date_to)
    d1 = parse_date_safe(df)
    d2 = parse_date_safe(dt)
    if not d1 or not d2:
        return
    total_days = (d2 - d1).days + 1
    chunks_needed = (total_days + chunk_days - 1) // chunk_days
    if max_chunks and chunks_needed > max_chunks:
        allowed_days = chunk_days * max_chunks
        d1 = d2 - timedelta(days=allowed_days - 1)
    start = d1
    while start <= d2:
        end = min(start + timedelta(days=chunk_days - 1), d2)
        yield start.isoformat(), end.isoformat()
        start = end + timedelta(days=1)

def ewma_weight(match_date_iso: str, ref_date_iso: str, half_life_days=HALF_LIFE_DAYS):
    md = parse_date_safe(match_date_iso)
    rd = parse_date_safe(ref_date_iso)
    if not md or not rd:
        return 1.0
    age = max(0, (rd - md).days)
    if half_life_days <= 0:
        return 1.0
    return 0.5 ** (age / half_life_days)

def make_api_request(path, params=None, max_retries=4):
    global _last_call_ts
    url = f"{BASE_URL}{path}"
    for attempt in range(max_retries):
        try:
            # احترم التباعد بين الطلبات
            if _MIN_INTERVAL_SEC > 0:
                with _last_call_lock:
                    delta = time.time() - _last_call_ts
                    if delta < _MIN_INTERVAL_SEC:
                        time.sleep((_MIN_INTERVAL_SEC - delta) + random.uniform(0, 0.25))

            resp = SESSION.get(url, headers=HEADERS, params=params, timeout=20)

            # حدّث وقت آخر طلب فوراً بعد التنفيذ
            if _MIN_INTERVAL_SEC > 0:
                with _last_call_lock:
                    _last_call_ts = time.time()

            # 429: نعالجها يدوياً
            if resp.status_code == 429:
                ra = resp.headers.get("Retry-After")
                wait_sec = int(ra) if ra and str(ra).isdigit() else 60
                remain = resp.headers.get("X-RateLimit-Remaining") or "?"
                log(f"[{now_str()}] Rate limit hit (remain={remain}). Waiting {wait_sec}s...")
                time.sleep(wait_sec)
                continue

            # 401/403: مشاكل صلاحيات — ارمِ استثناء واضح
            if resp.status_code in (401, 403):
                raise RuntimeError(f"رفض الوصول (HTTP {resp.status_code}). تحقق من صحة FOOTBALL_DATA_API_KEY.")

            # 4xx أخرى (مثل 400): اطبع الرسالة وتوقّف (لا تعاود المحاولة)
            if 400 <= resp.status_code < 500:
                try:
                    body = resp.json()
                    msg = body.get("message") or body.get("error") or resp.text
                except Exception:
                    msg = resp.text
                log(f"[{now_str()}] HTTP {resp.status_code} for {url} params={params} — {msg}")
                return None

            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            log(f"[{now_str()}] Request error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                backoff_sleep(attempt)
    return None

# ===========================
# TTL Cache بسيط
# ===========================
class TTLCache:
    def __init__(self, ttl_seconds: int):
        self.ttl = ttl_seconds
        self.store = {}  # key -> (value, expires_at)
    def get(self, key):
        item = self.store.get(key)
        if not item:
            return None
        value, exp = item
        if time.time() > exp:
            self.store.pop(key, None)
            return None
        return value
    def set(self, key, value):
        self.store[key] = (value, time.time() + self.ttl)

COMPS_CACHE = TTLCache(TTL_COMPETITIONS)
COMPS_ALL_CACHE = TTLCache(TTL_COMPETITIONS)
COMP_TEAMS_CACHE = TTLCache(TTL_COMPETITIONS)
TEAM_DETAILS_CACHE = TTLCache(TTL_TEAMS)
SCORERS_CACHE = TTLCache(TTL_COMPETITIONS)

# ===========================
# جلب المسابقات والفرق
# ===========================
def get_competitions_map():
    key = "competitions_TIER_ONE"
    cached = COMPS_CACHE.get(key)
    if cached is not None:
        return cached
    data = make_api_request("/competitions", params={"plan": "TIER_ONE"})
    comps = {}
    if data and "competitions" in data:
        for c in data["competitions"]:
            comps[c["id"]] = c
    COMPS_CACHE.set(key, comps)
    return comps

def get_competitions_map_all():
    key = "competitions_ALL"
    cached = COMPS_ALL_CACHE.get(key)
    if cached is not None:
        return cached
    data = make_api_request("/competitions", params=None)  # كل المسابقات المتاحة
    comps = {}
    if data and "competitions" in data:
        for c in data["competitions"]:
            comps[c["id"]] = c
    COMPS_ALL_CACHE.set(key, comps)
    return comps

def get_competition_id_by_code(code: str):
    code = (code or "").strip().upper()
    if not code:
        return None
    # جرّب ضمن TIER_ONE أولاً
    comps = get_competitions_map()
    for cid, c in comps.items():
        if (c.get("code") or "").upper() == code:
            return cid
    # ثم جرّب ضمن جميع المسابقات
    comps_all = get_competitions_map_all()
    for cid, c in comps_all.items():
        if (c.get("code") or "").upper() == code:
            return cid
    return None

def get_competition_info(comp_id: int):
    data = make_api_request(f"/competitions/{comp_id}")
    return data or {}

def get_competition_teams(comp_id: int):
    cache_key = f"comp_teams_{comp_id}"
    cached = COMP_TEAMS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    data = make_api_request(f"/competitions/{comp_id}/teams")
    teams = (data.get("teams", []) if data else [])
    COMP_TEAMS_CACHE.set(cache_key, teams)
    return teams

def all_tier_one_teams():
    comps = get_competitions_map()
    teams = []
    seen_ids = set()
    for cid in comps.keys():
        tlist = get_competition_teams(cid)
        for t in tlist:
            if t["id"] in seen_ids:
                continue
            seen_ids.add(t["id"])
            names = {t.get("name", ""), t.get("shortName", ""), t.get("tla", "")}
            teams.append({"id": t["id"], "names": [n for n in names if n]})
    return teams

def all_teams_from_codes(codes):
    teams, seen = [], set()
    for code in codes or []:
        cid = get_competition_id_by_code(code)
        if not cid:
            continue
        for t in get_competition_teams(cid) or []:
            if t["id"] in seen:
                continue
            seen.add(t["id"])
            names = {t.get("name",""), t.get("shortName",""), t.get("tla","")}
            teams.append({"id": t["id"], "names": [n for n in names if n]})
    return teams

# (6) دعم أسماء الفرق بالعربية/المرادفات + transliteration مبسطة
ARABIC_SYNONYMS = {
    # أمثلة شائعة، يمكنك إضافة المزيد حسب الحاجة
    "ريال مدريد": "Real Madrid",
    "برشلونة": "Barcelona",
    "برشلونه": "Barcelona",
    "اتلتيكو مدريد": "Atletico Madrid",
    "أتلتيكو مدريد": "Atletico Madrid",
    "إشبيلية": "Sevilla",
    "اشبيلية": "Sevilla",
    "ريال سوسيداد": "Real Sociedad",
    "فالنسيا": "Valencia",
    "فياريال": "Villarreal",
    "أوساسونا": "Osasuna",
    "مانشستر سيتي": "Manchester City",
    "مان سيتي": "Manchester City",
    "مانشستر يونايتد": "Manchester United",
    "ليفربول": "Liverpool",
    "تشيلسي": "Chelsea",
    "توتنهام": "Tottenham Hotspur",
    "أرسنال": "Arsenal",
    "بايرن ميونخ": "Bayern Munich",
    "بايرن ميونيخ": "Bayern Munich",
    "بوروسيا دورتموند": "Borussia Dortmund",
    "باريس سان جيرمان": "Paris Saint-Germain",
    "مارسيليا": "Marseille",
    "يوفنتوس": "Juventus",
    "انتر ميلان": "Inter",
    "إنتر ميلان": "Inter",
    "ميلان": "AC Milan",
    "نابولي": "Napoli",
    "روما": "Roma",
    "بنفيكا": "Benfica",
    "بورتو": "FC Porto",
    "أياكس": "Ajax",
    "ايندهوفن": "PSV",
    "فنورد": "Feyenoord",
}

_AR_TO_LATIN = {
    "ا":"a","أ":"a","إ":"i","آ":"a","ؤ":"u","ئ":"i","ب":"b","ت":"t","ث":"th","ج":"j","ح":"h","خ":"kh",
    "د":"d","ذ":"dh","ر":"r","ز":"z","س":"s","ش":"sh","ص":"s","ض":"d","ط":"t","ظ":"z","ع":"a","غ":"gh",
    "ف":"f","ق":"q","ك":"k","ل":"l","م":"m","ن":"n","ه":"h","و":"w","ي":"y","ى":"a","ة":"a","ﻻ":"la","لا":"la",
    "ٌ":"", "ً":"", "ٍ":"", "َ":"", "ُ":"", "ِ":"", "ّ":"", "ْ":""
}

def transliterate_ar_to_en(s: str) -> str:
    if not s:
        return s
    out = []
    for ch in s:
        out.append(_AR_TO_LATIN.get(ch, ch))
    # cleanup spaces and punctuation
    txt = "".join(out).lower()
    txt = re.sub(r"[^a-z0-9\s]", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt

def _norm_ascii(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def find_team_id_by_name(team_name: str, prefer_codes=None):
    """
    بحث عن ID فريق بالاسم مع إمكانية تفضيل مسابقة/مسابقات محددة أولاً
    - prefer_codes: قائمة رموز مسابقات (مثل ["PD"]) لتقليل عدد الاتصالات
    - كما يمكن ضبط FD_LOOKUP_FIRST_CODES=PD,PL,... عبر البيئة
    """
    team_name = (team_name or "").strip()
    if not team_name:
        return None

    # مرادفات عربية مباشرة
    ar_key = team_name.replace("ي", "ي").replace("ة", "ه")  # small normalization
    if ar_key in ARABIC_SYNONYMS:
        team_name = ARABIC_SYNONYMS[ar_key]

    best_score, best_id = 0.0, None
    tname_norm = team_name.lower()

    def _update_best(target: str, tid: int, score_min=0.0):
        nonlocal best_score, best_id
        score = difflib.SequenceMatcher(None, tname_norm, target.lower()).ratio()
        if score > best_score and score >= score_min:
            best_score, best_id = score, tid

    def _search_in_code_list(codes, th=0.6, th_trans=0.55):
        nonlocal best_id, best_score
        if not codes:
            return False
        teams = all_teams_from_codes(codes)
        for c in teams:
            for nm in c["names"]:
                _update_best(nm, c["id"])
        if best_score >= th:
            return True
        tname_trans = transliterate_ar_to_en(team_name)
        if tname_trans and tname_trans != tname_norm:
            for c in teams:
                for nm in c["names"]:
                    _update_best(_norm_ascii(nm), c["id"])
            if best_score >= th_trans:
                return True
        return False

    # رموز مسابقات مفضلة من الدالة أو من البيئة
    pref_codes = [c.strip().upper() for c in (prefer_codes or []) if c]
    env_pref = [c.strip().upper() for c in (os.getenv("FD_LOOKUP_FIRST_CODES", "") or "").split(",") if c.strip()]
    if not pref_codes and env_pref:
        pref_codes = env_pref

    # 0) جرّب المسابقات المفضلة أولاً لتقليل الاتصالات
    if _search_in_code_list(pref_codes):
        return best_id

    # 1) جرّب TIER_ONE أولاً
    candidates = all_tier_one_teams()
    for c in candidates:
        for nm in c["names"]:
            _update_best(nm, c["id"])

    if best_score >= 0.6:
        return best_id

    # 2) transliteration محاولة ثانية
    tname_trans = transliterate_ar_to_en(team_name)
    if tname_trans and tname_trans != tname_norm:
        for c in candidates:
            for nm in c["names"]:
                _update_best(_norm_ascii(nm), c["id"], score_min=0.0)
        if best_score >= 0.55:
            return best_id

    # 3) fallback لمجموعات محددة
    fallback = all_teams_from_codes(EXTRA_COMP_CODES)
    for c in fallback:
        for nm in c["names"]:
            _update_best(nm, c["id"])
    if best_score >= 0.6:
        return best_id

    # 4) fallback translit على المجموعات الإضافية
    if tname_trans and tname_trans != tname_norm:
        for c in fallback:
            for nm in c["names"]:
                _update_best(_norm_ascii(nm), c["id"])
        if best_score >= 0.55:
            return best_id

    return None

def get_team_details(team_id: int, force: bool = False):
    key = f"team_details_{team_id}"
    if not force:
        cached = TEAM_DETAILS_CACHE.get(key)
        if cached is not None:
            return cached
    data = make_api_request(f"/teams/{team_id}")
    if data and isinstance(data, dict) and data.get("id"):
        TEAM_DETAILS_CACHE.set(key, data)
        return data
    # لو فشل الطلب، رجّع نسخة الكاش إن وجدت
    cached = TEAM_DETAILS_CACHE.get(key)
    return cached or {}

def get_team_running_competitions(team_id: int):
    data = get_team_details(team_id)
    return (data.get("runningCompetitions", []) if data else [])

def _sort_comps_by_priority(comp_pairs):
    return sorted(
        list(comp_pairs),
        key=lambda x: COMPETITION_PRIORITY.index(x[1]) if x[1] in COMPETITION_PRIORITY else 999
    )

def choose_best_competition(team1_id: int, team2_id: int):
    t1_comps = get_team_running_competitions(team1_id)
    t2_comps = get_team_running_competitions(team2_id)
    t1 = {(c["id"], c.get("code")) for c in t1_comps}
    t2 = {(c["id"], c.get("code")) for c in t2_comps}
    inter = t1.intersection(t2)
    today = datetime.now().date()

    def started(cid):
        s, _, _, _, _ = get_competition_current_season_dates(cid)
        ds = parse_date_safe(s)
        return (ds is not None) and (today >= ds)

    if inter:
        ordered = _sort_comps_by_priority(inter)
        started_list = [(cid, code) for (cid, code) in ordered if started(cid)]
        if started_list:
            return started_list[0][0]
        else:
            return ordered[0][0]
    if t1:
        return _sort_comps_by_priority(t1)[0][0]
    if t2:
        return _sort_comps_by_priority(t2)[0][0]
    return None

# ===========================
# الترتيب (Standings)
# ===========================
def get_standings_table(comp_id: int):
    data = make_api_request(f"/competitions/{comp_id}/standings")
    table = []
    if data and data.get("standings"):
        # الأفضل TOTAL، وفي الكؤوس قد لا يتوفر — نترك العامل 1.0 لاحقاً
        for st in data["standings"]:
            if st.get("type") == "TOTAL":
                table = st.get("table", [])
                break
    idx = {}
    N = len(table) if table else 20
    for row in table or []:
        tid = (row.get("team") or {}).get("id")
        if tid is None:
            continue
        idx[tid] = {
            "position": row.get("position"),
            "points": row.get("points"),
            "played": row.get("playedGames"),
            "gf": row.get("goalsFor"),
            "ga": row.get("goalsAgainst"),
            "N": N
        }
    return idx

def table_position_factors(home_id: int, away_id: int, comp_id: int, k: float = TABLE_K):
    st = get_standings_table(comp_id)
    if not st:
        return 1.0, 1.0
    N = next(iter(st.values())).get("N", 20)
    ph = st.get(home_id, {}).get("position")
    pa = st.get(away_id, {}).get("position")
    if not ph or not pa:
        return 1.0, 1.0  # في حال الكؤوس/عدم توفر TOTAL
    adv = (pa - ph) / max(1.0, float(N))  # موجب إذا المضيف ترتيبُه أفضل
    fH = clamp(1.0 + k * adv, 0.92, 1.08)
    fA = clamp(1.0 - k * adv, 0.92, 1.08)
    return fH, fA

# ===========================
# جلب المباريات (مع التقسيم)
# ===========================
def get_competition_current_season_dates(comp_id: int):
    info = get_competition_info(comp_id)
    season = info.get("currentSeason", {}) if info else {}
    start = season.get("startDate")
    end = season.get("endDate")
    if not start:
        start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    if not end:
        end = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    start, end = normalize_date_range(start, end)
    return start, end, info.get("name", ""), info.get("code", ""), info.get("id", comp_id)

def _fetch_matches_by_competition_chunked(comp_id: int, date_from: str, date_to: str, status: str = "FINISHED"):
    results = {}
    # سقف 10 أيام حسب قيود Football-Data لمسار /matches
    chunk_len = min(MATCHES_CHUNK_DAYS, 10)
    for df, dt in chunked_date_ranges(date_from, date_to, chunk_len, MAX_CHUNKS):
        params = {"competitions": comp_id, "dateFrom": df, "dateTo": dt, "status": status}
        data = make_api_request("/matches", params=params)
        if not data:
            continue
        for m in data.get("matches", []):
            mid = m.get("id")
            if mid is not None:
                results[mid] = m
    return list(results.values())

def _fetch_team_matches_chunked(team_id: int, comp_id: int, date_from: str, date_to: str, status: str = "FINISHED"):
    results = {}
    for df, dt in chunked_date_ranges(date_from, date_to, TEAM_MATCHES_CHUNK_DAYS, MAX_CHUNKS):
        params = {"status": status, "competitions": comp_id, "dateFrom": df, "dateTo": dt}
        data = make_api_request(f"/teams/{team_id}/matches", params=params)
        if not data:
            continue
        for m in data.get("matches", []):
            mid = m.get("id")
            if mid is not None:
                results[mid] = m
    return list(results.values())

def _fetch_team_matches_any_comp_chunked(team_id: int, date_from: str, date_to: str, status: str = "FINISHED"):
    results = {}
    for df, dt in chunked_date_ranges(date_from, date_to, TEAM_MATCHES_CHUNK_DAYS, MAX_CHUNKS):
        params = {"status": status, "dateFrom": df, "dateTo": dt}
        data = make_api_request(f"/teams/{team_id}/matches", params=params)
        if not data:
            continue
        for m in data.get("matches", []):
            mid = m.get("id")
            if mid is not None:
                results[mid] = m
    return list(results.values())

@lru_cache(maxsize=32)
def get_competition_matches(comp_id: int, date_from: str, date_to: str):
    df, dt = normalize_date_range(date_from, date_to)
    return _fetch_matches_by_competition_chunked(comp_id, df, dt, status="FINISHED")

def get_team_matches_in_comp(team_id: int, comp_id: int, date_from: str, date_to: str):
    df, dt = normalize_date_range(date_from, date_to)
    return _fetch_team_matches_chunked(team_id, comp_id, df, dt, status="FINISHED")

def get_h2h_matches(team1_id: int, team2_id: int, comp_id: int, since: str):
    today_str = datetime.now().strftime("%Y-%m-%d")
    df, dt = normalize_date_range(since, today_str)
    matches = _fetch_team_matches_chunked(team1_id, comp_id, df, dt, status="FINISHED")
    h2h = []
    for m in matches:
        h = m.get("homeTeam", {}).get("id")
        a = m.get("awayTeam", {}).get("id")
        if h == team2_id or a == team2_id:
            h2h.append(m)
    h2h.sort(key=lambda x: x.get("utcDate", ""), reverse=True)
    return h2h

def parse_score(match):
    score = match.get("score", {}).get("fullTime", {})
    hg = score.get("home", 0) or 0
    ag = score.get("away", 0) or 0
    return hg, ag

# ===========================
# متوسطات الدوري وقوى الفرق
# ===========================
def calc_league_averages(comp_id: int, date_from: str, date_to: str):
    matches = get_competition_matches(comp_id, date_from, date_to)
    hg_sum, ag_sum, cnt = 0, 0, 0
    for m in matches:
        hg, ag = parse_score(m)
        if hg is None or ag is None:
            continue
        hg_sum += hg
        ag_sum += ag
        cnt += 1
    if cnt == 0:
        return {
            "avg_home_goals": 1.4,
            "avg_away_goals": 1.1,
            "home_advantage": 1.4 / 1.1,
            "matches_count": 0,
        }
    avg_home = hg_sum / cnt
    avg_away = ag_sum / cnt
    return {
        "avg_home_goals": avg_home,
        "avg_away_goals": avg_away,
        "home_advantage": (avg_home / avg_away) if avg_away > 0 else 1.1,
        "matches_count": cnt,
    }

def build_iterative_team_factors(comp_id: int, date_from: str, date_to: str, league_avgs: dict, iters: int = 8):
    matches = get_competition_matches(comp_id, date_from, date_to)
    if not matches:
        return {}, {}, matches
    team_ids = set()
    for m in matches:
        h = m.get("homeTeam", {}).get("id")
        a = m.get("awayTeam", {}).get("id")
        if h:
            team_ids.add(h)
        if a:
            team_ids.add(a)

    A = {tid: 1.0 for tid in team_ids}  # هجوم
    D = {tid: 1.0 for tid in team_ids}  # دفاع

    matches_simple = []
    for m in matches:
        hg, ag = parse_score(m)
        h = m.get("homeTeam", {}).get("id")
        a = m.get("awayTeam", {}).get("id")
        d_iso = (m.get("utcDate", "") or "")[:10]
        w = ewma_weight(d_iso, date_to, HALF_LIFE_DAYS)
        if h and a:
            matches_simple.append({"h": h, "a": a, "hg": hg, "ag": ag, "w": w, "date": d_iso})

    if not matches_simple:
        return A, D, matches

    # (1) احصِ عدد مباريات كل فريق (للانكماش المبكر)
    match_counts = {tid: 0 for tid in team_ids}
    for m in matches_simple:
        match_counts[m["h"]] += 1
        match_counts[m["a"]] += 1

    prior_w = PRIOR_GAMES
    avg_home = league_avgs["avg_home_goals"]
    avg_away = league_avgs["avg_away_goals"]

    for _ in range(iters):
        # تحديث A
        newA = {}
        for i in team_ids:
            num = prior_w * 1.0
            den = prior_w * 1.0
            for m in matches_simple:
                if m["h"] == i:
                    base = max(1e-6, avg_home * D[m["a"]])
                    num += m["w"] * (m["hg"] / base)
                    den += m["w"]
                elif m["a"] == i:
                    base = max(1e-6, avg_away * D[m["h"]])
                    num += m["w"] * (m["ag"] / base)
                    den += m["w"]
            newA[i] = clamp(num / den, AD_CLAMP_MIN, AD_CLAMP_MAX)
        A = newA

        # تحديث D (قابلية الاستقبال)
        newD = {}
        for i in team_ids:
            num = prior_w * 1.0
            den = prior_w * 1.0
            for m in matches_simple:
                if m["h"] == i:
                    base = max(1e-6, avg_away * A[m["a"]])
                    num += m["w"] * (m["ag"] / base)
                    den += m["w"]
                elif m["a"] == i:
                    base = max(1e-6, avg_home * A[m["h"]])
                    num += m["w"] * (m["hg"] / base)
                    den += m["w"]
            newD[i] = clamp(num / den, AD_CLAMP_MIN, AD_CLAMP_MAX)
        D = newD

        # إعادة تطبيع
        meanA = sum(A.values()) / len(A) if A else 1.0
        meanD = sum(D.values()) / len(D) if D else 1.0
        if meanA > 0:
            for k in A:
                A[k] /= meanA
        if meanD > 0:
            for k in D:
                D[k] /= meanD

    # (1) انكماش مبكر لقوى الفرق A/D حسب حجم العينة
    M0 = 10.0  # عدد مباريات الهدف قبل الإطلاق الكامل
    for i in team_ids:
        w = min(1.0, match_counts.get(i, 0) / M0)
        A[i] = 1.0 + w * (A[i] - 1.0)
        D[i] = 1.0 + w * (D[i] - 1.0)

    return A, D, matches

# ===========================
# Dixon-Coles (MLE للـ rho)
# ===========================
def draw_prob_independent(lh, la, max_goals=MAX_GOALS_GRID):
    pX = [poisson_pmf(i, lh) for i in range(max_goals + 1)]
    pY = [poisson_pmf(j, la) for j in range(max_goals + 1)]
    return sum(pX[k] * pY[k] for k in range(max_goals + 1))

def _dc_tau(i, j, lh, la, rho):
    if i == 0 and j == 0:
        return max(1e-6, 1.0 - rho * lh * la)
    if i == 0 and j == 1:
        return max(1e-6, 1.0 + rho * lh)
    if i == 1 and j == 0:
        return max(1e-6, 1.0 + rho * la)
    if i == 1 and j == 1:
        return max(1e-6, 1.0 - rho)
    return 1.0

def _log_p_pois(k, lam):
    if lam <= 0:
        return 0.0 if k == 0 else -1e9
    return k * math.log(lam) - lam - math.lgamma(k + 1)

def fit_dc_rho_mle(matches, A, D, league_avgs, rho_min=-DC_RHO_MAX, rho_max=DC_RHO_MAX, step=0.01):
    """ معايرة rho بطريقة MLE عبر grid search بسيط. """
    if not matches or not A or not D:
        return 0.0
    avg_home = league_avgs["avg_home_goals"]
    avg_away = league_avgs["avg_away_goals"]

    def loglik(rho):
        ll = 0.0
        for m in matches:
            h = m.get("homeTeam", {}).get("id")
            a = m.get("awayTeam", {}).get("id")
            if not h or not a:
                continue
            hg, ag = parse_score(m)
            if hg is None or ag is None:
                continue
            lh = max(1e-6, avg_home * A.get(h, 1.0) * D.get(a, 1.0))
            la = max(1e-6, avg_away * A.get(a, 1.0) * D.get(h, 1.0))
            tau = _dc_tau(hg, ag, lh, la, rho)
            ll += _log_p_pois(hg, lh) + _log_p_pois(ag, la) + math.log(tau)
        return ll

    best_rho, best_ll = 0.0, -1e18
    r = rho_min
    while r <= rho_max + 1e-12:
        ll = loglik(r)
        if ll > best_ll:
            best_ll, best_rho = ll, r
        r += step
    return clamp(best_rho, rho_min, rho_max)

def poisson_matrix_dc(lh, la, rho=0.0, max_goals=MAX_GOALS_GRID):
    pX = [poisson_pmf(i, lh) for i in range(max_goals + 1)]
    pY = [poisson_pmf(j, la) for j in range(max_goals + 1)]
    M = [[pX[i] * pY[j] for j in range(max_goals + 1)] for i in range(max_goals + 1)]
    k00 = max(0.001, 1.0 - rho * lh * la)
    k01 = max(0.001, 1.0 + rho * lh)
    k10 = max(0.001, 1.0 + rho * la)
    k11 = max(0.001, 1.0 - rho)
    if max_goals >= 0:
        M[0][0] *= k00
    if max_goals >= 1:
        M[0][1] *= k01
        M[1][0] *= k10
        M[1][1] *= k11
    s = sum(sum(row) for row in M)
    if s > 0:
        for i in range(max_goals + 1):
            for j in range(max_goals + 1):
                M[i][j] /= s
    return M

def matrix_to_outcomes(M):
    n = len(M) - 1
    p_home = p_draw = p_away = 0.0
    top = []
    for i in range(n + 1):
        for j in range(n + 1):
            pij = M[i][j]
            if i > j:
                p_home += pij
            elif i == j:
                p_draw += pij
            else:
                p_away += pij
            top.append(((i, j), pij))
    top.sort(key=lambda x: x[1], reverse=True)
    top5 = [{"score": f"{s[0]}-{s[1]}", "prob": round(100 * p, 2)} for (s, p) in top[:5]]
    return p_home, p_draw, p_away, top5

def matrix_markets(M):
    n = len(M) - 1
    p_btts = 0.0
    p_clean_home = 0.0
    p_clean_away = 0.0
    for i in range(n + 1):
        for j in range(n + 1):
            pij = M[i][j]
            if i > 0 and j > 0:
                p_btts += pij
            if j == 0:
                p_clean_home += pij
            if i == 0:
                p_clean_away += pij
    p_total = {t: 0.0 for t in range(0, 2 * n + 1)}
    for i in range(n + 1):
        for j in range(n + 1):
            p_total[i + j] += M[i][j]

    def over_under(th):
        floor = int(math.floor(th))
        p_under = sum(p_total.get(k, 0.0) for k in range(0, floor + 1))
        p_over = 1.0 - p_under
        return p_over, p_under

    ou_lines = {}
    for line in [1.5, 2.5, 3.5]:
        o, u = over_under(line)
        ou_lines[str(line)] = {"over": round(100 * o, 1), "under": round(100 * u, 1)}
    return {
        "BTTS_yes": f"{round(100 * p_btts, 1)}%",
        "clean_sheet_home": f"{round(100 * p_clean_home, 1)}%",
        "clean_sheet_away": f"{round(100 * p_clean_away, 1)}%",
        "over_under": ou_lines,
    }

# ===========================
# تقويم مجموع الأهداف λ
# ===========================
def shrink_to_base_total(lh, la, base_h, base_a, gamma=LAM_TOTAL_SHRINK):
    tgt = base_h + base_a
    cur = lh + la
    if cur <= 0 or tgt <= 0:
        return lh, la
    t = (1 - gamma) + gamma * (tgt / cur)
    return lh * t, la * t

# ===========================
# ELO
# ===========================
@lru_cache(maxsize=32)
def build_elo_table(comp_id: int, date_from: str, date_to: str):
    matches = list(get_competition_matches(comp_id, date_from, date_to) or [])
    matches.sort(key=lambda x: x.get("utcDate", ""))
    ratings = {}
    K_base = 20.0
    H_adv = 50.0
    for m in matches:
        h = m.get("homeTeam", {}).get("id")
        a = m.get("awayTeam", {}).get("id")
        if not h or not a:
            continue
        hg, ag = parse_score(m)
        if hg is None or ag is None:
            continue
        Rh = ratings.get(h, 1500.0)
        Ra = ratings.get(a, 1500.0)
        Eh = 1.0 / (1.0 + 10 ** (-(((Rh + H_adv) - Ra) / 400.0)))
        Sh = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
        goal_diff = abs(hg - ag)
        K = K_base * (1.0 + math.log2(goal_diff + 1.0))
        Rh_new = Rh + K * (Sh - Eh)

        Ea = 1.0 - Eh
        Sa = 1.0 - Sh
        Ra_new = Ra + K * (Sa - Ea)
        ratings[h] = Rh_new
        ratings[a] = Ra_new
    return ratings

def elo_scales(Rh, Ra, elo_home_adv=50.0, scale=ELO_SCALE):
    Eh = 1.0 / (1.0 + 10 ** (-(((Rh + elo_home_adv) - Ra) / 400.0)))
    sH = clamp(1.0 + (Eh - 0.5) * scale, ELO_LAM_MIN, ELO_LAM_MAX)
    sA = clamp(1.0 - (Eh - 0.5) * scale, ELO_LAM_MIN, ELO_LAM_MAX)
    return sH, sA, Eh

# ===========================
# Kelly (حساب نسب الرهان المقترحة)
# ===========================
def _parse_odds_value(val):
    """ يحوّل قيمة أودز إلى عشري """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    try:
        # نسبة مئوية "50%"
        if s.endswith("%"):
            p = float(s[:-1]) / 100.0
            return (1.0 / p) if p > 0 else None
        # كسري "5/2"
        if "/" in s:
            a, b = s.split("/", 1)
            a = float(a.strip()); b = float(b.strip())
            return (a / b) + 1.0 if b != 0 else None
        # أمريكي "+150" أو "-120"
        if s.startswith("+") or s.startswith("-"):
            us = int(s)
            if us > 0:
                return 1.0 + (us / 100.0)
            else:
                return 1.0 + (100.0 / abs(us))
        # عشري
        return float(s)
    except Exception:
        return None

def _kelly_core(p, odds_dec, scale=KELLY_SCALE):
    """
    يحسب كيللي لفُرصة p وأودز عشرية odds_dec.
    مع حواجز محافظة: KELLY_MIN_EDGE + KELLY_MAX_FRAC
    """
    try:
        if p is None or odds_dec is None or odds_dec <= 1.0:
            return None
        b = odds_dec - 1.0
        implied = 1.0 / odds_dec
        edge = p - implied
        if edge < KELLY_MIN_EDGE:
            return None
        k_full = max(0.0, (p * odds_dec - 1.0) / b)
        k_full = min(k_full, KELLY_MAX_FRAC)
        ev = p * b - (1.0 - p)  # القيمة المتوقعة للوحدة
        return {
            "prob": round(p, 4),
            "odds": round(odds_dec, 4),
            "implied": round(implied, 4),
            "edge": round(edge, 4),
            "kelly_full": round(k_full, 4),
            "kelly_scaled": round(k_full * scale, 4),
            "EV_per_unit": round(ev, 4)
        }
    except Exception:
        return None

def _extract_1x2_odds(odds):
    """ يستخرج أودز 1X2 من هيكل odds """
    if not isinstance(odds, dict):
        return {}
    def _find_sub(d, keys):
        for k in d.keys():
            kl = str(k).strip().lower()
            if kl in keys:
                return d[k]
        return None
    sub = _find_sub(odds, {"1x2", "match_odds", "full_time_result"})
    src = sub if isinstance(sub, dict) else odds

    def _get_any(d, candidates):
        for k in d.keys():
            kl = str(k).strip().lower()
            kn = kl.replace(" ", "").replace("-", "_")
            if kl in candidates or kn in candidates:
                return d[k]
        return None

    out = {}
    out["home"] = _parse_odds_value(_get_any(src, {"home", "h", "1"}))
    out["draw"] = _parse_odds_value(_get_any(src, {"draw", "x", "d"}))
    out["away"] = _parse_odds_value(_get_any(src, {"away", "a", "2"}))
    if all(v is None for v in out.values()):
        return {}
    return out

def kelly_suggestions_1x2(p_home, p_draw, p_away, odds):
    """ يقترح نسب كيللي لأسواق 1X2 """
    try:
        o = _extract_1x2_odds(odds or {})
        if not o:
            return {}
        res = {}
        if o.get("home") is not None:
            res["home"] = _kelly_core(p_home, o["home"])
        if o.get("draw") is not None:
            res["draw"] = _kelly_core(p_draw, o["draw"])
        if o.get("away") is not None:
            res["away"] = _kelly_core(p_away, o["away"])
        return {k: v for k, v in res.items() if v is not None}
    except Exception:
        return {}

def _to_prob(val):
    """ يحوّل قيمة نسبة/احتمال من mkts إلى احتمال [0..1]. """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        x = float(val)
        if 0.0 <= x <= 1.0:
            return x
        if 0.0 <= x <= 100.0:
            return x / 100.0
        return None
    s = str(val).strip()
    try:
        if s.endswith("%"):
            return max(0.0, min(1.0, float(s[:-1]) / 100.0))
        x = float(s)
        if 0.0 <= x <= 1.0:
            return x
        if 0.0 <= x <= 100.0:
            return x / 100.0
    except Exception:
        pass
    return None

def _odds_lookup(odds, *keys, default=None):
    """ بحث مرن عن قيمة داخل dict """
    if not isinstance(odds, dict):
        return default
    norm = {str(k).strip().lower().replace(" ", "_").replace("-", "_"): v for k, v in odds.items()}
    for k in keys:
        kk = str(k).strip().lower().replace(" ", "_").replace("-", "_")
        if kk in norm:
            return norm[kk]
    return default

def kelly_suggestions_markets(mkts, odds):
    """ يقترح نسب كيللي لأسواق إضافية لو توفرت أودزها """
    suggestions = {}
    if not isinstance(odds, dict):
        return suggestions

    # BTTS_yes
    pb = _to_prob(mkts.get("BTTS_yes"))
    if pb is not None:
        btts_obj = _odds_lookup(odds, "btts_yes", "btts", "both_teams_to_score")
        btts_odds = None
        if isinstance(btts_obj, dict):
            btts_odds = _odds_lookup(btts_obj, "yes", "y", "true")
            btts_odds = _parse_odds_value(btts_odds)
        else:
            btts_odds = _parse_odds_value(btts_obj)
        if btts_odds:
            suggestions["BTTS_yes"] = _kelly_core(pb, btts_odds)

    # Clean sheets
    p_csh = _to_prob(mkts.get("clean_sheet_home"))
    p_csa = _to_prob(mkts.get("clean_sheet_away"))
    cs_obj = _odds_lookup(odds, "clean_sheet", "clean_sheets", "cs", default={})
    if isinstance(cs_obj, dict):
        csh_odds = _parse_odds_value(_odds_lookup(cs_obj, "home", "h"))
        csa_odds = _parse_odds_value(_odds_lookup(cs_obj, "away", "a"))
    else:
        csh_odds = _parse_odds_value(_odds_lookup(odds, "clean_sheet_home", "cs_home"))
        csa_odds = _parse_odds_value(_odds_lookup(odds, "clean_sheet_away", "cs_away"))
    if p_csh is not None and csh_odds:
        suggestions["clean_sheet_home"] = _kelly_core(p_csh, csh_odds)
    if p_csa is not None and csa_odds:
        suggestions["clean_sheet_away"] = _kelly_core(p_csa, csa_odds)

    # Over/Under
    ou = mkts.get("over_under") or {}
    if isinstance(ou, dict):
        ou_sugg = {}
        ou_odds_nested = _odds_lookup(odds, "over_under", "ou", default={})
        for line, vu in ou.items():
            try:
                key_line = str(line).strip()
                p_over = _to_prob((vu or {}).get("over"))
                p_under = _to_prob((vu or {}).get("under"))

                over_odds = None
                under_odds = None
                if isinstance(ou_odds_nested, dict):
                    sub = ou_odds_nested.get(key_line) or (ou_odds_nested.get(float(key_line)) if isinstance(line, (int, float)) else None)
                    if isinstance(sub, dict):
                        over_odds = _parse_odds_value(_odds_lookup(sub, "over", "o"))
                        under_odds = _parse_odds_value(_odds_lookup(sub, "under", "u"))
                if over_odds is None:
                    over_odds = _parse_odds_value(_odds_lookup(odds, f"over_{key_line}", f"o_{key_line}"))
                if under_odds is None:
                    under_odds = _parse_odds_value(_odds_lookup(odds, f"under_{key_line}", f"u_{key_line}"))

                line_out = {}
                if p_over is not None and over_odds:
                    line_out["over"] = _kelly_core(p_over, over_odds)
                if p_under is not None and under_odds:
                    line_out["under"] = _kelly_core(p_under, under_odds)
                if line_out:
                    ou_sugg[key_line] = line_out
            except Exception:
                continue
        if ou_sugg:
            suggestions["over_under"] = ou_sugg

    def _clean(x):
        if isinstance(x, dict):
            return {k: _clean(v) for k, v in x.items() if v is not None and _clean(v) != {}}
        return x

    return _clean(suggestions)

# ===========================
# عوامل إضافية: فورم + H2H
# ===========================
def get_recent_form_factor(team_id: int, comp_id: int, date_from: str, date_to: str, take=5):
    matches = get_team_matches_in_comp(team_id, comp_id, date_from, date_to)
    matches.sort(key=lambda x: x.get("utcDate", ""), reverse=True)
    recent = matches[:take]
    if not recent:
        return 1.0, 0, 0
    points = 0.0
    for i, m in enumerate(recent):
        weight = (take - i) / take
        h_id = m.get("homeTeam", {}).get("id")
        a_id = m.get("awayTeam", {}).get("id")
        hg, ag = parse_score(m)
        if h_id == team_id:
            if hg > ag:
                points += 3 * weight
            elif hg == ag:
                points += 1 * weight
        elif a_id == team_id:
            if ag > hg:
                points += 3 * weight
            elif ag == hg:
                points += 1 * weight
    ratio = clamp(points / 15.0, 0.0, 1.0)
    factor = 0.97 + 0.06 * ratio
    return factor, round(points, 2), len(recent)

def h2h_adjustment(team1_id: int, team2_id: int, comp_id: int, since: str):
    h2h = get_h2h_matches(team1_id, team2_id, comp_id, since)
    if not h2h:
        return 1.0, 1.0, 0
    take = min(6, len(h2h))
    recent = h2h[:take]
    t1wins = t2wins = 0
    for m in recent:
        h = m.get("homeTeam", {}).get("id")
        a = m.get("awayTeam", {}).get("id")
        hg, ag = parse_score(m)
        if hg != ag:
            winner_id = h if hg > ag else a
            if winner_id == team1_id:
                t1wins += 1
            elif winner_id == team2_id:
                t2wins += 1
    net = (t1wins - t2wins) / take
    f1 = 1.0 + 0.05 * net
    f2 = 1.0 - 0.05 * net
    return clamp(f1, 0.95, 1.05), clamp(f2, 0.95, 1.05), take

# فورم محسّن بجودة الخصوم (SoS)
def get_recent_form_factor_sos(team_id: int, comp_id: int, date_from: str, date_to: str, ratings: dict, take=5, gamma=FORM_SOS_GAMMA):
    matches = get_team_matches_in_comp(team_id, comp_id, date_from, date_to)
    matches.sort(key=lambda x: x.get("utcDate", ""), reverse=True)
    recent = matches[:take]
    if not recent:
        return 1.0, 0.0, 0
    mean_r = (sum(ratings.values()) / len(ratings)) if ratings else 1500.0
    wp, denom = 0.0, 0.0
    for i, m in enumerate(recent):
        h = m.get("homeTeam", {}).get("id")
        a = m.get("awayTeam", {}).get("id")
        hg, ag = parse_score(m)
        opp = a if h == team_id else h
        r_opp = ratings.get(opp, 1500.0) if ratings else 1500.0
        w_strength = clamp(1.0 + gamma * ((r_opp - mean_r) / 200.0), 0.85, 1.15)
        rec_w = (take - i) / take
        points = 0.0
        if h == team_id:
            if hg > ag: points = 3.0
            elif hg == ag: points = 1.0
        else:
            if ag > hg: points = 3.0
            elif ag == hg: points = 1.0
        wp += points * rec_w * w_strength
        denom += 3.0 * rec_w * w_strength
    if denom <= 0:
        return 1.0, 0.0, len(recent)
    ratio = clamp(wp / denom, 0.0, 1.0)
    factor = 0.97 + 0.06 * ratio
    return factor, round(wp, 2), len(recent)

# معدل التهديف الحديث مقابل المتوقع
def recent_goal_rate_factor(team_id: int, comp_id: int, A: dict, D: dict, league_avgs: dict, date_from: str, date_to: str, take=5):
    matches = get_team_matches_in_comp(team_id, comp_id, date_from, date_to)
    matches.sort(key=lambda x: x.get("utcDate", ""), reverse=True)
    recent = matches[:take]
    if not recent or not A or not D:
        return 1.0
    avg_home = league_avgs["avg_home_goals"]
    avg_away = league_avgs["avg_away_goals"]
    num = den = 0.0
    for i, m in enumerate(recent):
        h = m.get("homeTeam", {}).get("id")
        a = m.get("awayTeam", {}).get("id")
        if not h or not a:
            continue
        hg, ag = parse_score(m)
        w = (take - i) / take
        if team_id == h:
            lam = max(1e-6, avg_home * A.get(h, 1.0) * D.get(a, 1.0))
            gf = hg
        else:
            lam = max(1e-6, avg_away * A.get(a, 1.0) * D.get(h, 1.0))
            gf = ag
        num += w * gf
        den += w * lam
    if den <= 0:
        return 1.0
    ratio = num / den
    ratio = clamp(ratio, 1.0 - GOAL_RATE_MAX_BOOST, 1.0 + GOAL_RATE_MAX_BOOST)
    return ratio

# تشكيلات
FORMATION_FACTORS = {
    "4-3-3": {"gf": 1.02, "ga": 1.02},
    "4-2-3-1": {"gf": 1.01, "ga": 1.00},
    "4-4-2": {"gf": 1.00, "ga": 1.00},
    "3-5-2": {"gf": 1.03, "ga": 1.03},
    "3-4-3": {"gf": 1.04, "ga": 1.05},
    "5-4-1": {"gf": 0.96, "ga": 0.94},
    "5-3-2": {"gf": 0.98, "ga": 0.96},
    "4-5-1": {"gf": 0.97, "ga": 0.96},
}
def formation_factors(formation: str):
    if not formation:
        return 1.0, 1.0
    m = FORMATION_FACTORS.get(formation.strip(), {"gf": 1.0, "ga": 1.0})
    gf = clamp(m["gf"], 1.0 - FORMATION_MAX_BOOST, 1.0 + FORMATION_MAX_BOOST)
    ga = clamp(m["ga"], 1.0 - FORMATION_MAX_BOOST, 1.0 + FORMATION_MAX_BOOST)
    return gf, ga  # ga = ميل للاستقبال

# إصابات/غيابات (Hook اختياري)
def injuries_availability_factors(info: dict):
    if not info or not isinstance(info, dict):
        return 1.0, 1.0
    starters_out = int(info.get("starters_out", 0) or 0)
    key_out = int(info.get("key_out", 0) or 0)
    extra = info.get("players")
    impact_bonus = 0.0
    if isinstance(extra, list):
        impact_bonus = sum(max(0.0, min(1.0, (p.get("importance") or 0))) for p in extra)
    atk_drop = starters_out * INJ_STARTER_ATK + key_out * (INJ_STARTER_ATK + INJ_KEY_BONUS) + 0.01 * impact_bonus
    def_rise = starters_out * INJ_STARTER_DEF + key_out * (INJ_STARTER_DEF + INJ_KEY_BONUS) + 0.01 * impact_bonus
    atk_mult = clamp(1.0 - atk_drop, 1.0 - INJ_MAX_ATK_DROP, 1.05)
    conceded_mult_for_opp = clamp(1.0 + def_rise, 0.95, 1.0 + INJ_MAX_DEF_RISE)
    return atk_mult, conceded_mult_for_opp

# ===========================
# إضافات مجانية: سكواد + الهدافين + آخر/قادمة مباريات
# ===========================
def _age_years(dob_iso: str):
    try:
        if not dob_iso:
            return None
        date_part = dob_iso[:10]
        d = parse_date_safe(date_part)
        if not d:
            return None
        today = datetime.now().date()
        years = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
        return int(years)
    except Exception:
        return None

def _pos_norm_adv(position, detailed):
    txt = f"{(position or '')} {(detailed or '')}".lower().strip()
    if "keep" in txt or "gk" in txt or "goalkeep" in txt: return "G"
    if "wing-back" in txt or "wb" in txt: return "D"
    if any(k in txt for k in ["def", "back", "centre-back", "center-back", "cb", "rb", "lb", "rwb", "lwb"]): return "D"
    if any(k in txt for k in ["mid", "dm", "cm", "am", "pivot", "regista", "mezz"]): return "M"
    if any(k in txt for k in ["att", "forw", "strik", "wing", "lw", "rw", "cf", "ss", " 9"]): return "F"
    return "U"

def get_team_squad(team_id: int, limit=None):
    data = get_team_details(team_id) or {}
    squad = data.get("squad") or []
    if not squad:
        data = get_team_details(team_id, force=True) or {}
        squad = data.get("squad") or []
        if not squad:
            log(f"[squad] team {team_id}: no squad data after retry")
    out = []
    for p in squad:
        role = p.get("role")
        pos = p.get("position")
        det = p.get("detailedPosition")
        is_player = (role == "PLAYER") or bool(pos) or bool(det)
        if not is_player:
            continue
        dob = p.get("dateOfBirth")
        out.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "position": pos,
            "detailedPosition": det,
            "nationality": p.get("nationality"),
            "shirtNumber": p.get("shirtNumber"),
            "role": role or "PLAYER",
            "age": _age_years(dob)
        })
    pos_order = {"G":0,"D":1,"M":2,"F":3,"U":9}
    def _order_key(x):
        cat = _pos_norm_adv(x.get("position"), x.get("detailedPosition"))
        return (pos_order.get(cat, 9), (x.get("name") or ""))
    out.sort(key=_order_key)
    if limit and isinstance(limit, int) and limit > 0:
        out = out[:limit]
    return out

def get_competition_scorers(comp_id: int, limit: int = 20):
    cache_key = f"scorers_{comp_id}_{limit}"
    cached = SCORERS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    data = make_api_request(f"/competitions/{comp_id}/scorers", params={"limit": limit}) or {}
    items = []
    for idx, s in enumerate(data.get("scorers", []) or [], start=1):
        player = s.get("player", {}) or {}
        team = s.get("team", {}) or {}
        goals = s.get("goals") or s.get("numberOfGoals")
        items.append({
            "rank": idx,
            "playerId": player.get("id"),
            "player": player.get("name"),
            "teamId": team.get("id"),
            "team": team.get("name"),
            "goals": goals,
            "assists": s.get("assists"),
            "penalties": s.get("penalties"),
            "position": player.get("position"),
            "nationality": player.get("nationality")
        })
    SCORERS_CACHE.set(cache_key, items)
    return items

def _team_label_from_obj(team_obj):
    if not team_obj:
        return None
    return team_obj.get("shortName") or team_obj.get("name")

def _team_label(team_id: int):
    d = get_team_details(team_id) or {}
    return d.get("shortName") or d.get("name")

def summarize_match_for_team(m: dict, team_id: int):
    h = (m.get("homeTeam") or {}).get("id")
    a = (m.get("awayTeam") or {}).get("id")
    if not h or not a:
        return None
    side = "H" if team_id == h else "A"
    opp = a if team_id == h else h
    comp = (m.get("competition") or {})
    comp_code = comp.get("code") or comp.get("name")
    score = m.get("score") or {}
    ft = score.get("fullTime") or {}
    ht = score.get("halfTime") or {}
    et = score.get("extraTime") or {}
    pen = score.get("penalties") or {}
    hg, ag = ft.get("home") or 0, ft.get("away") or 0
    if side == "H":
        res = "W" if hg > ag else ("D" if hg == ag else "L")
    else:
        res = "W" if ag > hg else ("D" if ag == hg else "L")

    def _fmt_pair(p):
        if p is None or (p.get("home") is None and p.get("away") is None):
            return None
        return f"{p.get('home', 0)}-{p.get('away', 0)}"

    return {
        "date": (m.get("utcDate") or "")[:10],
        "competition": comp_code,
        "stage": m.get("stage"),
        "matchday": m.get("matchday"),
        "side": side,
        "opponent": {"id": opp, "name": _team_label_from_obj(m.get("awayTeam") if side == "H" else m.get("homeTeam")) or _team_label(opp)},
        "score": {
            "HT": _fmt_pair(ht),
            "FT": _fmt_pair(ft),
            "ET": _fmt_pair(et),
            "PEN": _fmt_pair(pen)
        },
        "result": res,
    }

def get_team_recent_matches_extended(team_id: int, comp_id: int = None, days: int = 180, limit: int = 5, all_competitions: bool = False):
    today = datetime.now().date()
    df = (today - timedelta(days=max(1, days))).isoformat()
    dt = today.isoformat()
    if all_competitions or not comp_id:
        matches = _fetch_team_matches_any_comp_chunked(team_id, df, dt, status="FINISHED")
    else:
        matches = _fetch_team_matches_chunked(team_id, comp_id, df, dt, status="FINISHED")
    matches.sort(key=lambda x: x.get("utcDate", ""), reverse=True)
    out = []
    for m in matches[:limit]:
        sm = summarize_match_for_team(m, team_id)
        if sm:
            out.append(sm)
    return out

def get_team_upcoming_matches(team_id: int, comp_id: int = None, days_ahead: int = 30, limit: int = 3, all_competitions: bool = False):
    today = datetime.now().date()
    df = today.isoformat()
    dt = (today + timedelta(days=max(1, days_ahead))).isoformat()
    if all_competitions or not comp_id:
        raw = _fetch_team_matches_any_comp_chunked(team_id, df, dt, status="SCHEDULED")
    else:
        raw = _fetch_team_matches_chunked(team_id, comp_id, df, dt, status="SCHEDULED")
    raw.sort(key=lambda x: x.get("utcDate", ""))
    out = []
    for m in raw[:limit]:
        h = (m.get("homeTeam") or {}).get("id")
        a = (m.get("awayTeam") or {}).get("id")
        side = "H" if team_id == h else ("A" if team_id == a else None)
        opp = a if team_id == h else h
        comp = (m.get("competition") or {})
        out.append({
            "dateTimeUTC": m.get("utcDate"),
            "competition": comp.get("code") or comp.get("name"),
            "matchday": m.get("matchday"),
            "side": side,
            "opponent": {"id": opp, "name": _team_label_from_obj(m.get("awayTeam") if side == "H" else m.get("homeTeam")) or _team_label(opp)},
        })
    return out

def enrich_with_free_stats(result: dict, include_players=True, include_recent=True, include_scorers=True, include_upcoming=False, recent_days=180, recent_limit=5, recent_all_comps=False, squad_limit=None, scorers_limit=20):
    """ يُثري مخرجات predict_match بمفتاح extra """
    try:
        home_id = ((result.get("teams") or {}).get("home") or {}).get("id")
        away_id = ((result.get("teams") or {}).get("away") or {}).get("id")
        comp_id = ((result.get("meta") or {}).get("competition") or {}).get("id")
        if not home_id or not away_id:
            return result

        extra = result.get("extra") or {}

        if include_players:
            hs = get_team_squad(home_id, limit=squad_limit)
            asq = get_team_squad(away_id, limit=squad_limit)
            # fallback scorers if no squad
            if (not hs) and comp_id:
                scorers = get_competition_scorers(comp_id, limit=scorers_limit) or []
                hs = [{
                    "id": s.get("playerId"),
                    "name": s.get("player"),
                    "position": None,
                    "detailedPosition": None,
                    "nationality": s.get("nationality"),
                    "shirtNumber": None,
                    "role": "PLAYER",
                    "age": None
                } for s in scorers if s.get("teamId") == home_id]
            if (not asq) and comp_id:
                scorers = get_competition_scorers(comp_id, limit=scorers_limit) or []
                asq = [{
                    "id": s.get("playerId"),
                    "name": s.get("player"),
                    "position": None,
                    "detailedPosition": None,
                    "nationality": s.get("nationality"),
                    "shirtNumber": None,
                    "role": "PLAYER",
                    "age": None
                } for s in scorers if s.get("teamId") == away_id]
            extra["players"] = {"home_squad": hs, "away_squad": asq}

        if include_recent:
            extra["recent_matches"] = {
                "home": get_team_recent_matches_extended(home_id, comp_id=comp_id, days=recent_days, limit=recent_limit, all_competitions=recent_all_comps),
                "away": get_team_recent_matches_extended(away_id, comp_id=comp_id, days=recent_days, limit=recent_limit, all_competitions=recent_all_comps),
            }

        if include_upcoming:
            extra["upcoming"] = {
                "home": get_team_upcoming_matches(home_id, comp_id=comp_id, all_competitions=recent_all_comps),
                "away": get_team_upcoming_matches(away_id, comp_id=comp_id, all_competitions=recent_all_comps),
            }

        if include_scorers and comp_id:
            scorers = get_competition_scorers(comp_id, limit=scorers_limit) or []
            home_top = [s for s in scorers if s.get("teamId") == home_id]
            away_top = [s for s in scorers if s.get("teamId") == away_id]
            extra["top_scorers"] = {
                "competition_top": scorers,
                "home_team_scorers": home_top,
                "away_team_scorers": away_top
            }

        extra["squad_metrics"] = {
            "home": compute_squad_metrics(home_id),
            "away": compute_squad_metrics(away_id)
        }

        fatigue = (((result.get("lambdas") or {}).get("factors") or {}).get("enhanced") or {}).get("fatigue")
        if fatigue:
            extra["fatigue"] = fatigue

        result["extra"] = extra
        return result
    except Exception as e:
        log(f"[enrich] فشل إثراء المخرجات: {e}")
        return result

# ===========================
# تعزيزات المعادلات: سكواد/هدافين/سبليت/إرهاق/كومباك
# ===========================
def _pos_norm(p):
    p = (p or "").lower()
    if "keep" in p or p == "gk": return "G"
    if "def" in p: return "D"
    if "mid" in p: return "M"
    if "att" in p or "forw" in p or "strik" in p or "wing" in p: return "F"
    return "U"

def compute_squad_metrics(team_id: int):
    squad = get_team_squad(team_id) or []
    ages = [p.get("age") for p in squad if isinstance(p.get("age"), int)]
    avg_age = sum(ages)/len(ages) if ages else None
    counts = {"G":0,"D":0,"M":0,"F":0,"U":0}
    for p in squad:
        cat = _pos_norm_adv(p.get("position"), p.get("detailedPosition"))
        counts[cat] += 1
    return {"avg_age": avg_age, "counts": counts, "total": len(squad)}

def squad_based_factors(team_id: int):
    m = compute_squad_metrics(team_id)
    gf_mult = 1.0
    opp_concede_mult = 1.0
    notes = {}
    if m["total"] == 0:
        notes["no_squad_data"] = True
        return 1.0, 1.0, {"squad": m, "notes": notes}

    if m["avg_age"] is not None:
        if m["avg_age"] <= SQUAD_YOUNG_AGE:
            gf_mult *= (1.0 + SQUAD_YOUNG_GF_BONUS)
            opp_concede_mult *= (1.0 + SQUAD_YOUNG_GA_PENALTY)
            notes["age_tag"] = "young"
        elif m["avg_age"] >= SQUAD_OLD_AGE:
            gf_mult *= (1.0 - SQUAD_OLD_GF_DROP)
            opp_concede_mult *= (1.0 - SQUAD_OLD_GA_BONUS)
            notes["age_tag"] = "old"
        else:
            notes["age_tag"] = "balanced"

    Dcnt = m["counts"]["D"]
    if Dcnt < SQUAD_DEF_MIN_DEFENDERS:
        short = SQUAD_DEF_MIN_DEFENDERS - Dcnt
        pen = clamp(short * SQUAD_DEF_THIN_PENALTY_STEP, 0.0, SQUAD_DEF_THIN_MAX_PENALTY)
        opp_concede_mult *= (1.0 + pen)
        notes["deficit_defenders"] = short

    Fcnt = m["counts"]["F"]
    if Fcnt >= SQUAD_ATT_COUNT_THRESHOLD:
        gf_mult *= (1.0 + SQUAD_ATT_BONUS)
        notes["deep_attack"] = True

    return clamp(gf_mult, 0.95, 1.07), clamp(opp_concede_mult, 0.93, 1.07), {"squad": m, "notes": notes}

def team_home_away_split_factors(team_id: int, is_home: bool, used_matches: list, league_avgs: dict, take: int = HOME_AWAY_SPLIT_TAKE, alpha: float = HOME_AWAY_SPLIT_ALPHA):
    filtered = []
    for m in used_matches or []:
        h = (m.get("homeTeam") or {}).get("id")
        a = (m.get("awayTeam") or {}).get("id")
        if not h or not a:
            continue
        if is_home and h == team_id:
            filtered.append(m)
        elif (not is_home) and a == team_id:
            filtered.append(m)
    filtered.sort(key=lambda x: x.get("utcDate",""), reverse=True)
    filtered = filtered[:take]
    if not filtered:
        return 1.0, 1.0, {"n": 0}

    gf, ga = 0, 0
    for m in filtered:
        ft = (m.get("score") or {}).get("fullTime") or {}
        hg, ag = ft.get("home") or 0, ft.get("away") or 0
        if is_home:
            gf += hg; ga += ag
        else:
            gf += ag; ga += hg
    n = len(filtered)
    gf_rate = gf / n
    ga_rate = ga / n
    base_gf = league_avgs["avg_home_goals"] if is_home else league_avgs["avg_away_goals"]
    base_ga = league_avgs["avg_away_goals"] if is_home else league_avgs["avg_home_goals"]
    off = 1.0 + alpha * (gf_rate / max(1e-9, base_gf) - 1.0)
    defc = 1.0 + alpha * (ga_rate / max(1e-9, base_ga) - 1.0)
    off = clamp(off, 1.0 - HOME_AWAY_SPLIT_MAX, 1.0 + HOME_AWAY_SPLIT_MAX)
    defc = clamp(defc, 1.0 - HOME_AWAY_SPLIT_MAX, 1.0 + HOME_AWAY_SPLIT_MAX)
    return off, defc, {"n": n, "gf_rate": round(gf_rate,3), "ga_rate": round(ga_rate,3)}

def top_scorers_offense_boost(team_id: int, comp_id: int, limit: int):
    scorers = get_competition_scorers(comp_id, limit=limit) or []
    goals = sum((s.get("goals") or 0) for s in scorers if s.get("teamId") == team_id)
    assists = sum((s.get("assists") or 0) for s in scorers if s.get("teamId") == team_id)
    boost = goals * TOPSCORER_GOAL_WEIGHT + (assists or 0) * TOPSCORER_ASSIST_WEIGHT
    boost = clamp(boost, 0.0, TOPSCORER_MAX_BOOST)
    return 1.0 + boost, {"goals": goals, "assists": assists, "boost": round(boost, 4)}

def _points_from_pair(side: str, pair: dict):
    if not pair or (pair.get("home") is None and pair.get("away") is None):
        return None
    h, a = pair.get("home") or 0, pair.get("away") or 0
    if side == "H":
        if h > a: return 3
        if h == a: return 1
        return 0
    else:
        if a > h: return 3
        if a == h: return 1
        return 0

def comeback_offense_factor(team_id: int, used_matches: list, take: int = COMEBACK_TAKE):
    recent = []
    for m in used_matches or []:
        h = (m.get("homeTeam") or {}).get("id")
        a = (m.get("awayTeam") or {}).get("id")
        if team_id in (h, a):
            recent.append(m)
    recent.sort(key=lambda x: x.get("utcDate",""), reverse=True)
    recent = recent[:take]
    if not recent:
        return 1.0, {"n": 0}
    deltas = []
    for m in recent:
        h = m.get("homeTeam") or {}
        hid = h.get("id")
        side = "H" if team_id == hid else "A"
        score = m.get("score") or {}
        ft = score.get("fullTime") or {}
        ht = score.get("halfTime") or {}
        p_ht = _points_from_pair(side, ht)
        p_ft = _points_from_pair(side, ft)
        if p_ht is None or p_ft is None:
            continue
        deltas.append(p_ft - p_ht)
    if not deltas:
        return 1.0, {"n": 0}
    avg_delta = sum(deltas) / len(deltas)  # -3..+3
    idx = clamp(avg_delta / 3.0, -1.0, 1.0)
    mult = clamp(1.0 + COMEBACK_MAX * idx, 1.0 - COMEBACK_MAX, 1.0 + COMEBACK_MAX)
    return mult, {"n": len(deltas), "avg_delta_pts": round(avg_delta, 3)}

def fatigue_factors(team_id: int, comp_id: int, used_matches: list, season_end_iso: str):
    today = parse_date_safe(season_end_iso) or datetime.now().date()
    past_since = today - timedelta(days=FATIGUE_PAST_DAYS)
    past_cnt = 0
    for m in used_matches or []:
        h = (m.get("homeTeam") or {}).get("id")
        a = (m.get("awayTeam") or {}).get("id")
        if team_id not in (h,a):
            continue
        d = parse_date_safe((m.get("utcDate","") or "")[:10])
        if not d:
            continue
        if past_since <= d <= today:
            past_cnt += 1
    upcoming = get_team_upcoming_matches(team_id, comp_id=comp_id, days_ahead=FATIGUE_NEXT_DAYS, limit=10, all_competitions=False) or []
    next_cnt = len(upcoming)
    load_index = FATIGUE_PAST_WEIGHT * past_cnt + FATIGUE_NEXT_WEIGHT * next_cnt
    over = max(0.0, load_index - FATIGUE_THRESHOLD)
    atk_pen = clamp(over * FATIGUE_ATK_STEP, 0.0, FATIGUE_MAX)
    def_rise = clamp(over * FATIGUE_DEF_STEP, 0.0, FATIGUE_MAX)
    atk_mult = 1.0 - atk_pen
    opp_concede_mult = 1.0 + def_rise
    return atk_mult, opp_concede_mult, {
        "past_cnt": past_cnt, "next_cnt": next_cnt, "load_index": load_index,
        "atk_pen": round(atk_pen, 4), "def_rise": round(def_rise, 4)
    }

# ===========================
# Hooks للطقس/الحَكَم عبر extras
# ===========================
def context_multipliers(extras):
    """
    extras.get("context") مثال:
    {"weather":"rain","referee_cards_per_game":5.2}
    يعيد: mult_home, mult_away, meta_dict
    """
    ctx = (extras or {}).get("context") if isinstance(extras, dict) else None
    if not isinstance(ctx, dict):
        return 1.0, 1.0, {}

    weather = (ctx.get("weather") or "").strip().lower()
    ref_cards = ctx.get("referee_cards_per_game")

    mult = 1.0
    meta = {"weather": weather, "referee_cards_per_game": ref_cards}

    # طقس: أمثلة بسيطة (±2–4%)
    if weather in {"rain", "snow"}:
        mult *= 0.96  # لعب أبطأ -> أهداف أقل
    elif weather in {"wind", "windy"}:
        mult *= 0.98
    elif weather in {"hot"}:
        mult *= 0.98

    # حكم كثير البطاقات -> لعب متقطع قليلاً
    try:
        if ref_cards is not None:
            delta = clamp((float(ref_cards) - 4.5) * -0.01, -0.02, 0.02)
            mult *= (1.0 + delta)
    except Exception:
        pass

    return mult, mult, meta

# ===========================
# شبكة أهداف ديناميكية
# ===========================
def dynamic_max_goals(lh, la):
    m = max(lh, la, 1e-6)
    return max(8, int(min(15, round(m + 6 * math.sqrt(m)))))

# ===========================
# معايرة 1×2 بدرجة حرارة
# ===========================
def calibrate_probs_temperature(pH, pX, pA, tau=PROB_TEMP):
    ps = [max(1e-6, pH), max(1e-6, pX), max(1e-6, pA)]
    ps = [p ** tau for p in ps]
    s = sum(ps)
    return (ps[0] / s, ps[1] / s, ps[2] / s)

# ===========================
# التوقع الرئيسي
# ===========================
def predict_match(team1_name: str, team2_name: str, team1_is_home: bool = True, competition_code_override: str = None, odds: dict = None, max_goals: int = MAX_GOALS_GRID, extras: dict = None, scorers_limit: int = SCORERS_LIMIT_DEFAULT):
    """ يتوقع نتيجة مباراة بين فريقين. """

    # 1) IDs للفرق — حاول أولاً عبر المسابقة المفضلة إن وُجدت
    prefer_codes = [competition_code_override.strip().upper()] if competition_code_override else []
    t1_id = find_team_id_by_name(team1_name, prefer_codes=prefer_codes) or find_team_id_by_name(team1_name)
    t2_id = find_team_id_by_name(team2_name, prefer_codes=prefer_codes) or find_team_id_by_name(team2_name)
    if not t1_id or not t2_id:
        raise ValueError(f"تعذر إيجاد الفريقين: '{team1_name}' و/أو '{team2_name}' ضمن قواعد البيانات المتاحة.")

    # 2) تحديد المسابقة
    comp_id = None
    comp_code_used = None
    if competition_code_override:
        comp_id = get_competition_id_by_code(competition_code_override)
        comp_code_used = competition_code_override.upper()
        if not comp_id:
            log(f"تحذير: لم يتم العثور على مسابقة بالكود {competition_code_override}. سيتم اختيار مسابقة مناسبة تلقائياً.")
            comp_id = None
    if not comp_id:
        comp_id = choose_best_competition(t1_id, t2_id)
        if not comp_id:
            raise RuntimeError("تعذر تحديد مسابقة نشِطة مشتركة بين الفريقين.")
    _, _, _, comp_code_used_auto, _ = get_competition_current_season_dates(comp_id)
    if not comp_code_used:
        comp_code_used = comp_code_used_auto

    # 3) نافذة الموسم الحالي
    season_start, season_end, comp_name, comp_code, comp_id_check = get_competition_current_season_dates(comp_id)
    today = datetime.now().date()
    end_for_data = min(parse_date_safe(season_end) or today, today).isoformat()
    start_for_data = season_start

    # 4) متوسطات الدوري
    league_avgs = calc_league_averages(comp_id, start_for_data, end_for_data)

    # 5) قوى الفرق A, D, used_matches
    A, D, used_matches = build_iterative_team_factors(comp_id, start_for_data, end_for_data, league_avgs, iters=8)

    # 6) معايرة rho (MLE)
    rho = fit_dc_rho_mle(used_matches, A, D, league_avgs)

    # 7) صاحب الأرض
    home_id = t1_id if team1_is_home else t2_id
    away_id = t2_id if team1_is_home else t1_id

    # 8) λ الأساسية
    avg_home = league_avgs["avg_home_goals"]
    avg_away = league_avgs["avg_away_goals"]
    Ah = A.get(home_id, 1.0); Dh = D.get(home_id, 1.0)
    Aa = A.get(away_id, 1.0); Da = D.get(away_id, 1.0)
    lam_home_base = avg_home * Ah * Da
    lam_away_base = avg_away * Aa * Dh

    # 9) ELO
    ratings_all = build_elo_table(comp_id, start_for_data, end_for_data)
    Rh = ratings_all.get(home_id, 1500.0)
    Ra = ratings_all.get(away_id, 1500.0)
    sH, sA, Eh = elo_scales(Rh, Ra, elo_home_adv=50.0, scale=ELO_SCALE)
    lam_home = lam_home_base * sH
    lam_away = lam_away_base * sA

    # 9b) ترتيب الدوري
    tfH, tfA = table_position_factors(home_id, away_id, comp_id, k=TABLE_K)
    lam_home *= tfH
    lam_away *= tfA

    # 9c) تشكيل/خطة (مدخل اختياري عبر extras)
    home_form_str = (extras or {}).get("formations", {}).get("home") if extras else None
    away_form_str = (extras or {}).get("formations", {}).get("away") if extras else None
    gfH, gaH = formation_factors(home_form_str)
    gfA, gaA = formation_factors(away_form_str)
    lam_home *= gfH * gaA  # هجوم المضيف × ميل خصمه للاستقبال
    lam_away *= gfA * gaH  # هجوم الضيف × ميل خصمه للاستقبال

    # 10) فورم محسّن بجودة الخصوم (SoS)
    f_home_form, home_form_points, home_form_count = get_recent_form_factor_sos(home_id, comp_id, start_for_data, end_for_data, ratings_all, take=5)
    f_away_form, away_form_points, away_form_count = get_recent_form_factor_sos(away_id, comp_id, start_for_data, end_for_data, ratings_all, take=5)
    lam_home *= f_home_form
    lam_away *= f_away_form

    # 10b) معدل التهديف الحديث مقابل المتوقع
    gr_home = recent_goal_rate_factor(home_id, comp_id, A, D, league_avgs, start_for_data, end_for_data, take=5)
    gr_away = recent_goal_rate_factor(away_id, comp_id, A, D, league_avgs, start_for_data, end_for_data, take=5)
    lam_home *= gr_home
    lam_away *= gr_away

    # 10c) الإصابات/الغيابات (مدخل اختياري)
    av_home = (extras or {}).get("availability", {}).get("home") if extras else None
    av_away = (extras or {}).get("availability", {}).get("away") if extras else None
    home_off_mult, home_conc_mult_to_opp = injuries_availability_factors(av_home)
    away_off_mult, away_conc_mult_to_opp = injuries_availability_factors(av_away)
    lam_home *= home_off_mult
    lam_away *= home_conc_mult_to_opp
    lam_away *= away_off_mult
    lam_home *= away_conc_mult_to_opp

    # 11) H2H
    since_h2h = (today - timedelta(days=H2H_LOOKBACK_DAYS)).isoformat()
    f1, f2, h2h_count = h2h_adjustment(t1_id, t2_id, comp_id, since=since_h2h)
    if team1_is_home:
        lam_home *= f1
        lam_away *= f2
    else:
        lam_home *= f2
        lam_away *= f1

    # === تعزيزات مبنية على البيانات المجانية (سكواد/سبليت/هدافين/إرهاق/كومباك) ===
    enh = {}

    # 3.1: انقسام داخل/خارج الأرض
    h_off_split, h_def_split, h_meta = team_home_away_split_factors(home_id, True, used_matches, league_avgs)
    a_off_split, a_def_split, a_meta = team_home_away_split_factors(away_id, False, used_matches, league_avgs)
    lam_home *= h_off_split
    lam_away *= h_def_split
    lam_away *= a_off_split
    lam_home *= a_def_split
    enh["home_away_split"] = {
        "home": {"off": round(h_off_split,3), "def_to_opp": round(h_def_split,3), **h_meta},
        "away": {"off": round(a_off_split,3), "def_to_opp": round(a_def_split,3), **a_meta}
    }

    # 3.2: سكواد (عمر/عمق دفاع/عمق هجوم)
    h_sq_off, h_sq_def_to_opp, h_sq_meta = squad_based_factors(home_id)
    a_sq_off, a_sq_def_to_opp, a_sq_meta = squad_based_factors(away_id)
    lam_home *= h_sq_off
    lam_away *= h_sq_def_to_opp
    lam_away *= a_sq_off
    lam_home *= a_sq_def_to_opp
    enh["squad"] = {
        "home": {"off": round(h_sq_off,3), "def_to_opp": round(h_sq_def_to_opp,3), **h_sq_meta},
        "away": {"off": round(a_sq_off,3), "def_to_opp": round(a_sq_def_to_opp,3), **a_sq_meta}
    }

    # 3.3: هدّافو المسابقة → دفعة هجومية
    sc_limit = scorers_limit
    h_sc_boost, h_sc_meta = top_scorers_offense_boost(home_id, comp_id, limit=sc_limit)
    a_sc_boost, a_sc_meta = top_scorers_offense_boost(away_id, comp_id, limit=sc_limit)
    lam_home *= h_sc_boost
    lam_away *= a_sc_boost
    enh["top_scorers"] = {"home": h_sc_meta, "away": a_sc_meta}

    # 3.4: Comeback (تحسن بعد الاستراحة)
    h_cb_mult, h_cb_meta = comeback_offense_factor(home_id, used_matches, take=COMEBACK_TAKE)
    a_cb_mult, a_cb_meta = comeback_offense_factor(away_id, used_matches, take=COMEBACK_TAKE)
    lam_home *= h_cb_mult
    lam_away *= a_cb_mult
    enh["comeback"] = {"home": {"mult": round(h_cb_mult,3), **h_cb_meta}, "away": {"mult": round(a_cb_mult,3), **a_cb_meta}}

    # 3.5: إرهاق/ضغط مباريات
    h_fat_atk, h_fat_def_to_opp, h_fat_meta = fatigue_factors(home_id, comp_id, used_matches, end_for_data)
    a_fat_atk, a_fat_def_to_opp, a_fat_meta = fatigue_factors(away_id, comp_id, used_matches, end_for_data)
    lam_home *= h_fat_atk
    lam_away *= h_fat_def_to_opp
    lam_away *= a_fat_atk
    lam_home *= a_fat_def_to_opp
    enh["fatigue"] = {
        "home": {"atk": round(h_fat_atk,3), "def_to_opp": round(h_fat_def_to_opp,3), **h_fat_meta},
        "away": {"atk": round(a_fat_atk,3), "def_to_opp": round(a_fat_def_to_opp,3), **a_fat_meta}
    }

    # عوامل السياق: الطقس/الحكم
    ctx_home_mult, ctx_away_mult, ctx_meta = context_multipliers(extras)
    lam_home *= ctx_home_mult
    lam_away *= ctx_away_mult
    enh["context"] = {"home_mult": round(ctx_home_mult,3), "away_mult": round(ctx_away_mult,3), **ctx_meta}

    # تقويم مجموع الأهداف نحو مجموع القاعدة
    lam_home, lam_away = shrink_to_base_total(lam_home, lam_away, lam_home_base, lam_away_base, gamma=LAM_TOTAL_SHRINK)

    # قص λ
    lam_home = clamp(lam_home, LAM_CLAMP_MIN, LAM_CLAMP_MAX)
    lam_away = clamp(lam_away, LAM_CLAMP_MIN, LAM_CLAMP_MAX)

    # شبكة أهداف ديناميكية
    dyn_max_goals = dynamic_max_goals(lam_home, lam_away)
    if max_goals is None:
        max_goals_used = dyn_max_goals
    else:
        # نضمن أن الشبكة لا تكون أصغر من الديناميكية
        max_goals_used = max(max_goals, dyn_max_goals)

    # مصفوفة بواسون مع DC
    M = poisson_matrix_dc(lam_home, lam_away, rho=rho, max_goals=max_goals_used)

    # 1X2 وأفضل النتائج
    p_home_raw, p_draw_raw, p_away_raw, top5 = matrix_to_outcomes(M)

    # معايرة حرارة الاحتمالات لــ 1×2
    p_home, p_draw, p_away = calibrate_probs_temperature(p_home_raw, p_draw_raw, p_away_raw, tau=PROB_TEMP)

    # أسواق إضافية
    mkts = matrix_markets(M)

    # أسماء الفرق
    t1d = get_team_details(t1_id) or {}
    t2d = get_team_details(t2_id) or {}
    team1_label = t1d.get("shortName") or t1d.get("name") or team1_name
    team2_label = t2d.get("shortName") or t2d.get("name") or team2_name
    home_label = team1_label if team1_is_home else team2_label
    away_label = team2_label if team1_is_home else team1_label

    # كيللي (اختياري) — باستخدام الاحتمالات المُعايرة
    kelly_1x2 = kelly_suggestions_1x2(p_home, p_draw, p_away, odds)
    kelly_extra = kelly_suggestions_markets(mkts, odds)

    # بناء النتيجة
    result = {
        "meta": {
            "version": VERSION,
            "competition": {"id": comp_id, "name": comp_name, "code": comp_code or comp_code_used},
            "season_window": {"from": start_for_data, "to": end_for_data},
            "league_averages": league_avgs,
            "dc_rho": round(rho, 4),
            "prob_temperature": PROB_TEMP,
            "max_goals_grid": max_goals_used,
            "samples": {
                "matches_used": len(used_matches or []),
                "home_form_count": home_form_count,
                "away_form_count": away_form_count,
                "h2h_count": h2h_count
            }
        },
        "teams": {
            "team1": {"id": t1_id, "name": team1_label},
            "team2": {"id": t2_id, "name": team2_label},
            "home": {"id": home_id, "name": home_label},
            "away": {"id": away_id, "name": away_label},
            "team1_is_home": team1_is_home
        },
        "lambdas": {
            "home_base": round(lam_home_base, 4),
            "away_base": round(lam_away_base, 4),
            "home_final": round(lam_home, 4),
            "away_final": round(lam_away, 4),
            "factors": {
                "elo": {"Rh": round(Rh, 1), "Ra": round(Ra, 1), "Eh_home": round(Eh, 3), "sH": round(sH, 3), "sA": round(sA, 3)},
                "table": {"home": round(tfH, 3), "away": round(tfA, 3)},
                "formation": {
                    "home": {"formation": home_form_str, "gf": round(gfH, 3)},
                    "away": {"formation": away_form_str, "gf": round(gfA, 3)},
                    "cross_effect": {"home_vs_away_ga": round(gaA, 3), "away_vs_home_ga": round(gaH, 3)}
                },
                "availability": {
                    "home_off": round(home_off_mult, 3), "home_def_to_opp": round(home_conc_mult_to_opp, 3),
                    "away_off": round(away_off_mult, 3), "away_def_to_opp": round(away_conc_mult_to_opp, 3)
                },
                "form_sos": {"home_factor": round(f_home_form, 3), "away_factor": round(f_away_form, 3), "home_points_w": home_form_points, "away_points_w": away_form_points},
                "recent_goals": {"home": round(gr_home, 3), "away": round(gr_away, 3)},
                "h2h": {"team1_factor": round(f1, 3), "team2_factor": round(f2, 3)},
                "enhanced": {**enh}
            }
        },
        "probabilities": {
            "1x2": {
                "home": round(100 * p_home, 2),
                "draw": round(100 * p_draw, 2),
                "away": round(100 * p_away, 2)
            },
            "top_scorelines": top5,
            "markets": mkts
        },
        "kelly": {
            "on_1x2": kelly_1x2,
            "on_markets": kelly_extra
        }
    }
    return result

# ===========================
# CLI بسيط
# ===========================
def main():
    parser = argparse.ArgumentParser(description=f"{VERSION}: توقع مباريات كرة القدم (Poisson + DC-MLE + Ratings + ELO + Pre-match factors + Free-Stats Enhancements + rate-limit tweaks)")
    parser.add_argument("--team1", type=str, required=True, help="اسم الفريق الأول")
    parser.add_argument("--team2", type=str, required=True, help="اسم الفريق الثاني")
    parser.add_argument("--team1_is_home", type=str, default="true", help="هل الفريق1 صاحب الأرض؟ true/false")
    parser.add_argument("--comp", type=str, default=None, help="كود مسابقة اختياري (مثلاً PD, PL, SA, BL1, FL1, CL, ELC)")
    parser.add_argument("--odds_json", type=str, default=None, help="JSON لأودز المراهنات لحساب كيللي (اختياري)")
    parser.add_argument("--extras_json", type=str, default=None, help="JSON للتشكيلات/الإصابات/السياق (اختياري)")
    parser.add_argument("--max_goals", type=int, default=None, help="حجم شبكة الأهداف لبواسون (إن تُرك None يستخدم الديناميكي)")
    # خيارات إظهار البيانات الإضافية
    parser.add_argument("--show_players", type=str, default="false", help="أدرج سكواد الفريقين ضمن المخرجات")
    parser.add_argument("--show_recent", type=str, default="false", help="أدرج ملخص آخر المباريات")
    parser.add_argument("--show_scorers", type=str, default="false", help="أدرج هدّافي المسابقة الحالية")
    parser.add_argument("--show_upcoming", type=str, default="false", help="أدرج المباريات القادمة")
    parser.add_argument("--recent_days", type=int, default=180, help="نطاق الأيام للبحث عن المباريات الأخيرة")
    parser.add_argument("--recent_limit", type=int, default=5, help="عدد آخر المباريات المعروضة")
    parser.add_argument("--recent_all_comps", type=str, default="false", help="لو true يجلب آخر المباريات من كل المسابقات")
    parser.add_argument("--squad_limit", type=int, default=0, help="حد أقصى لعدد اللاعبين المعروضين (0=بدون حد)")
    parser.add_argument("--scorers_limit", type=int, default=20, help="عدد هدّافي المسابقة المعروضين")
    args = parser.parse_args()

    t1 = args.team1.strip()
    t2 = args.team2.strip()
    t1h = (args.team1_is_home or "true").strip().lower() in ("true", "1", "yes", "y")

    # استخدم قيمة CLI إن وُجدت، وإلا None ليتم استخدام الديناميكي
    max_goals = int(args.max_goals) if args.max_goals not in (None, "") else None

    # استخدم قيمة CLI أو من متغيرات البيئة (FD_COMP أو COMP)
    env_comp = (os.getenv("FD_COMP") or os.getenv("COMP") or "").strip()
    comp = (args.comp or env_comp or "").strip().upper() or None

    odds = None
    if args.odds_json:
        try:
            odds = json.loads(args.odds_json)
        except Exception as e:
            log(f"تعذر قراءة odds_json: {e}")

    extras = None
    if args.extras_json:
        try:
            extras = json.loads(args.extras_json)
        except Exception as e:
            log(f"تعذر قراءة extras_json: {e}")

    try:
        out = predict_match(
            t1, t2,
            team1_is_home=t1h,
            competition_code_override=comp,
            odds=odds,
            max_goals=max_goals,  # قد يكون None -> ديناميكي
            extras=extras,
            scorers_limit=int(args.scorers_limit)
        )

        def _to_bool(x):
            return (str(x or "false").strip().lower() in ("true","1","yes","y"))

        show_players = _to_bool(args.show_players)
        show_recent = _to_bool(args.show_recent)
        show_scorers = _to_bool(args.show_scorers)
        show_upcoming = _to_bool(args.show_upcoming)
        recent_all_comps = _to_bool(args.recent_all_comps)

        if any([show_players, show_recent, show_scorers, show_upcoming]):
            out = enrich_with_free_stats(
                out,
                include_players=show_players,
                include_recent=show_recent,
                include_scorers=show_scorers,
                include_upcoming=show_upcoming,
                recent_days=int(args.recent_days),
                recent_limit=int(args.recent_limit),
                recent_all_comps=recent_all_comps,
                squad_limit=(int(args.squad_limit) if args.squad_limit else None),
                scorers_limit=int(args.scorers_limit),
            )

        print(json.dumps(out, ensure_ascii=False, indent=2))
    except Exception as e:
        traceback.print_exc()
        log(f"خطأ أثناء التوقع: {e}")
        sys.exit(1)

# ===========================
# تشغيل مباشر
# ===========================
if __name__ == "__main__":
    # إذا شُغّل مع باراميترات من CLI استخدم الوضع العادي
    if len(sys.argv) > 1:
        main()
    elif os.getenv("FD_RUN_EXAMPLE") == "1":
        # مثال تجريبي — يُشغّل فقط عند ضبط FD_RUN_EXAMPLE=1
        TEAM1 = "Real Sociedad"
        TEAM2 = "Real Madrid"
        TEAM1_IS_HOME = True
        try:
            out = predict_match(
                TEAM1, TEAM2,
                team1_is_home=TEAM1_IS_HOME,
                competition_code_override=os.getenv("FD_EXAMPLE_COMP", "PD"),
                extras=None,
                scorers_limit=20,
                max_goals=None  # None => ديناميكي
            )
            out = enrich_with_free_stats(
                out,
                include_players=True,
                include_recent=True,
                include_scorers=True,
                include_upcoming=True,
                recent_days=180,
                recent_limit=5,
                recent_all_comps=False,
                squad_limit=None,
                scorers_limit=20
            )
            print(json.dumps(out, ensure_ascii=False, indent=2))
        except Exception as e:
            traceback.print_exc()
            log(f"خطأ أثناء التوقع: {e}")
            sys.exit(1)
    else:
        log("Run via CLI. Example:\n  python script.py --team1 \"Real Sociedad\" --team2 \"Real Madrid\" --team1_is_home true --comp PD")