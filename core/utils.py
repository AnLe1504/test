from __future__ import annotations

import time
import requests
from datetime import date, datetime, timedelta


# ─────────────────────────────────────────────────────────────────────────────
# Jolpica F1 schedule — fetch per-year with simple in-memory TTL cache
# ─────────────────────────────────────────────────────────────────────────────
_SCHEDULE_CACHE: dict[int, tuple[float, list[dict]]] = {}
_SCHEDULE_TTL = 3600  # 1 hour


def _fetch_schedule(year: int) -> list[dict]:
    now = time.time()
    hit = _SCHEDULE_CACHE.get(year)
    if hit and (now - hit[0] < _SCHEDULE_TTL):
        return hit[1]
    try:
        resp = requests.get(
            f"https://api.jolpi.ca/ergast/f1/{year}/races.json",
            params={"limit": 30},
            timeout=10,
        )
        resp.raise_for_status()
        races = resp.json().get("MRData", {}).get("RaceTable", {}).get("Races", [])
    except Exception:
        races = []
    _SCHEDULE_CACHE[year] = (now, races)
    return races


def _race_date(r: dict) -> date | None:
    raw = (r.get("date") or "")[:10]
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _race_city(r: dict) -> str:
    loc = (r.get("Circuit") or {}).get("Location") or {}
    return (loc.get("locality") or "").strip()


def get_race_info_for_city(city: str, year: int | None = None) -> dict | None:
    """Return {'date': date, 'city': str} for the given city's race this year,
    or None. Substring match to handle 'Monte Carlo' vs 'Monaco' etc."""
    if not city:
        return None
    year = year or date.today().year
    city_l = city.strip().lower()
    races = _fetch_schedule(year)
    for r in races:
        r_city = _race_city(r).lower()
        if not r_city:
            continue
        if city_l == r_city or city_l in r_city or r_city in city_l:
            d = _race_date(r)
            if d:
                return {"date": d, "city": r_city}
    return None


def get_race_weekend_dates(city: str) -> tuple[date | None, date | None]:
    """Return (start, end) for the race weekend of a circuit's city.
    Race weekends span Thursday → Sunday. If this year's race already passed,
    try next year. Returns (None, None) if not found."""
    if not city:
        return None, None
    today = date.today()
    city_l = city.strip().lower()
    for year in (today.year, today.year + 1):
        for r in _fetch_schedule(year):
            r_city = _race_city(r).lower()
            if not r_city:
                continue
            if city_l == r_city or city_l in r_city or r_city in city_l:
                d = _race_date(r)
                if not d:
                    continue
                if d < today and year == today.year:
                    continue
                return d - timedelta(days=3), d
    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Wikipedia REST API — circuit thumbnail + extract (no auth, no key)
# ─────────────────────────────────────────────────────────────────────────────
_WIKI_CACHE: dict[str, tuple[float, dict]] = {}
_WIKI_TTL = 86400  # 24h


def fetch_wikipedia_summary(circuit_name: str) -> dict:
    """Return {'thumbnail_url', 'extract', 'page_url'} for a circuit; falls back
    to a progressively simpler title. Values may be empty strings / None."""
    empty = {"thumbnail_url": None, "extract": "", "page_url": ""}
    if not circuit_name:
        return empty

    now = time.time()
    key = circuit_name.strip().lower()
    hit = _WIKI_CACHE.get(key)
    if hit and (now - hit[0] < _WIKI_TTL):
        return hit[1]

    names_to_try = [
        circuit_name,
        circuit_name.replace(" Grand Prix", ""),
        circuit_name + " racing circuit",
    ]
    result = empty
    for name in names_to_try:
        slug = name.strip().replace(" ", "_")
        try:
            resp = requests.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}",
                headers={"User-Agent": "F1CircuitJournal/1.0 (Django app)"},
                timeout=8,
            )
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("type") == "disambiguation":
                continue
            thumb = data.get("thumbnail") or data.get("originalimage") or {}
            result = {
                "thumbnail_url": thumb.get("source"),
                "extract": data.get("extract", ""),
                "page_url": (data.get("content_urls", {})
                                 .get("desktop", {}).get("page", "")),
            }
            break
        except Exception:
            continue

    _WIKI_CACHE[key] = (now, result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Circuit sort by upcoming race date
# ─────────────────────────────────────────────────────────────────────────────
def sort_circuits_by_race_date(circuits: list[dict]) -> list[dict]:
    today = date.today()
    year = today.year
    races = _fetch_schedule(year)
    lookup = {}
    for r in races:
        c = _race_city(r).lower()
        d = _race_date(r)
        if c and d:
            lookup[c] = d

    def key(c):
        city_l = (c.get("city") or "").lower()
        d = lookup.get(city_l)
        if not d:
            for k, v in lookup.items():
                if city_l and (city_l in k or k in city_l):
                    d = v
                    break
        if not d:
            return (3, 9999, c.get("name", ""))
        if d >= today:
            return (1, (d - today).days, c.get("name", ""))
        try:
            next_occ = d.replace(year=d.year + 1)
            return (2, (next_occ - today).days, c.get("name", ""))
        except ValueError:
            return (2, 9998, c.get("name", ""))

    return sorted(circuits, key=key)
