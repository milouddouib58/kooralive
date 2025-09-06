# -*- coding: utf-8 -*-
import os
import time
import requests
from typing import Dict, Any, List, Tuple


# ==========================================================
# 📌 إعدادات أساسية
# ==========================================================
BASE = os.getenv("ODDS_API_BASE", "https://api.the-odds-api.com/v4")
API_KEY = os.getenv("ODDS_API_KEY", "")


# ==========================================================
# 📌 دالة أساسية لطلب البيانات من Odds API
# ==========================================================
def _get(path: str, params: Dict[str, Any] = None, timeout: int = 20):
    params = dict(params or {})
    apikey = params.pop("apiKey", None) or API_KEY
    if not apikey:
        raise RuntimeError("ODDS_API_KEY غير مضبوط. ضعه في Secrets أو البيئة.")

    url = f"{BASE}{path}"
    params["apiKey"] = apikey

    r = requests.get(url, params=params, timeout=timeout)
    if r.status_code == 429:
        ra = int(r.headers.get("Retry-After", "60"))
        time.sleep(ra)
        r = requests.get(url, params=params, timeout=timeout)

    r.raise_for_status()
    return r.json(), {
        "remaining": r.headers.get("x-requests-remaining"),
        "used": r.headers.get("x-requests-used"),
    }


# ==========================================================
# 📌 استرجاع قائمة الرياضات الخاصة بكرة القدم
# ==========================================================
def list_soccer_sports() -> List[Dict[str, Any]]:
    data, _ = _get("/sports")
    return [s for s in data if "soccer" in str(s.get("key", "")).lower()]


# ==========================================================
# 📌 جلب أسعار المراهنات لرياضة معينة
# ==========================================================
def fetch_odds_for_sport(
    sport_key: str,
    regions: str = "eu,uk",
    markets: str = "h2h,totals",
    oddsFormat: str = "decimal",
    dateFormat: str = "iso",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    data, meta = _get(
        f"/sports/{sport_key}/odds",
        params={
            "regions": regions,
            "markets": markets,
            "oddsFormat": oddsFormat,
            "dateFormat": dateFormat,
        },
    )
    return data, meta


# ==========================================================
# 📌 استخراج أسعار H2H (1X2)
# ==========================================================
def extract_h2h_prices(event: Dict[str, Any]) -> Dict[str, List[float]]:
    home, away = event.get("home_team"), event.get("away_team")
    out = {"home": [], "draw": [], "away": []}

    for bm in event.get("bookmakers", []):
        for m in bm.get("markets", []):
            if m.get("key") == "h2h":
                for o in m.get("outcomes", []):
                    n = o.get("name")
                    p = o.get("price")

                    if n == home:
                        out["home"].append(p)
                    elif n == away:
                        out["away"].append(p)
                    elif str(n).strip().lower() == "draw":
                        out["draw"].append(p)

    return {
        k: [x for x in v if isinstance(x, (int, float)) and float(x) > 1.0]
        for k, v in out.items()
    }


# ==========================================================
# 📌 استخراج خطوط المجموع (Totals Over/Under)
# ==========================================================
def extract_totals_lines(event: Dict[str, Any]) -> Dict[str, Dict[str, List[float]]]:
    lines: Dict[str, Dict[str, List[float]]] = {}

    for bm in event.get("bookmakers", []):
        for m in bm.get("markets", []):
            if m.get("key") == "totals":
                for o in m.get("outcomes", []):
                    point = str(o.get("point"))
                    name = str(o.get("name", "")).lower()
                    price = o.get("price")

                    if point not in lines:
                        lines[point] = {"over": [], "under": []}

                    if "over" in name:
                        lines[point]["over"].append(price)
                    elif "under" in name:
                        lines[point]["under"].append(price)

    # تنظيف
    for L in list(lines.keys()):
        lines[L]["over"] = [
            p for p in lines[L]["over"] if isinstance(p, (int, float)) and float(p) > 1.0
        ]
        lines[L]["under"] = [
            p for p in lines[L]["under"] if isinstance(p, (int, float)) and float(p) > 1.0
        ]

        if not lines[L]["over"] and not lines[L]["under"]:
            lines.pop(L, None)

    return lines
