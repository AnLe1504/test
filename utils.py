# ─────────────────────────────────────────────────────────────────────────────
# utils.py  —  Shared helpers used across all Streamlit pages
#
# Provides:
#   • F1 schedule fetch via f1-race-schedule RapidAPI (static doc endpoint)
#   • Race-date lookup by city     (for My Trips date autofill + Explorer sort)
#   • LAP_LENGTHS hard-coded dict  (24 current F1 circuits, stable known values)
#   • Wikipedia REST API           (circuit thumbnail + extract, free/no auth)
#   • Jolpica F1 API               (first_gp_year per circuit, free/no auth)
#   • Circuit detail enrichment    (lap_length_km, first_gp_year → DB update)
#   • rating_bar_html()            (gradient bar used everywhere ratings appear)
# ─────────────────────────────────────────────────────────────────────────────

import requests
import streamlit as st
from datetime import date, datetime, timedelta


# ── RapidAPI credentials ───────────────────────────────────────────────────────
# Key is read from st.secrets (never hard-coded).
# Local: .streamlit/secrets.toml  →  RAPIDAPI_KEY = "..."
# Cloud: set in Streamlit Cloud secrets dashboard before deploying.

RAPIDAPI_HOST    = "f1-race-schedule.p.rapidapi.com"
RAPIDAPI_DOC_URL = "https://f1-race-schedule.p.rapidapi.com/api/6141c76615d27e0de553b9d7"


def _rapidapi_headers() -> dict:
    return {
        "x-rapidapi-key":  st.secrets["RAPIDAPI_KEY"],
        "x-rapidapi-host": RAPIDAPI_HOST,
        "Content-Type":    "application/json",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PART 0 — LAP LENGTHS  (hard-coded, stable known values for all 24 current circuits)
# ═══════════════════════════════════════════════════════════════════════════════

# Keys: city name lowercased (matches circuit.city in DB and API location fields)
LAP_LENGTHS: dict[str, float] = {
    "melbourne":        5.278,
    "shanghai":         5.451,
    "suzuka":           5.807,
    "sakhir":           5.412,
    "jeddah":           6.174,
    "miami":            5.412,
    "imola":            4.909,
    "monte-carlo":      3.337,
    "monaco":           3.337,
    "montreal":         4.361,
    "barcelona":        4.657,
    "spielberg":        4.318,
    "silverstone":      5.891,
    "budapest":         4.381,
    "spa":              7.004,
    "zandvoort":        4.259,
    "monza":            5.793,
    "baku":             6.003,
    "singapore":        4.940,
    "austin":           5.513,
    "mexico city":      4.304,
    "são paulo":        4.309,
    "sao paulo":        4.309,
    "las vegas":        6.201,
    "lusail":           5.380,
    "doha":             5.380,
    "abu dhabi":        5.281,
    "yas island":       5.281,
}


# ═══════════════════════════════════════════════════════════════════════════════
# PART 1 — F1 RACE SCHEDULE  (Jolpica Ergast API — free, no auth required)
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600)
def fetch_f1_schedule() -> list[dict]:
    """
    Fetch the current season's F1 race schedule from the Jolpica Ergast API.
    Returns a list of race dicts. Falls back to [] if the API is unreachable.

    Response structure: MRData → RaceTable → Races (list)
    Each race dict contains:
      race["raceName"]                          → GP name
      race["Circuit"]["circuitName"]            → circuit name
      race["Circuit"]["Location"]["locality"]   → city
      race["Circuit"]["Location"]["country"]    → country
      race["date"]                              → "YYYY-MM-DD"
      race["round"]                             → round number (string)
    """
    year = date.today().year
    try:
        resp = requests.get(
            f"https://api.jolpi.ca/ergast/f1/{year}/races.json",
            params={"limit": 30},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        races = (
            data.get("MRData", {})
                .get("RaceTable", {})
                .get("Races", [])
        )
        return races
    except Exception:
        return []


def _parse_race_date(race: dict) -> date | None:
    """Extract and parse the race date from a schedule race dict."""
    raw = (race.get("date") or "")[:10]
    try:
        if len(raw) >= 10:
            return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        pass
    return None


def _race_city(race: dict) -> str:
    """Extract city from a schedule race dict (handles multiple response shapes)."""
    # Shape A: race["Circuit"]["Location"]["locality"]
    circuit = race.get("Circuit") or race.get("circuit") or {}
    location = circuit.get("Location") or circuit.get("location") or {}
    city = location.get("locality") or location.get("city") or ""
    if city:
        return city.strip()
    # Shape B: flat keys
    return (race.get("city") or race.get("locality") or "").strip()


def _race_country(race: dict) -> str:
    """Extract country from a schedule race dict."""
    circuit = race.get("Circuit") or race.get("circuit") or {}
    location = circuit.get("Location") or circuit.get("location") or {}
    country = location.get("country") or ""
    if country:
        return country.strip()
    return (race.get("country") or "").strip()


def _race_gp_name(race: dict) -> str:
    """Extract GP name from a schedule race dict."""
    return (
        race.get("raceName")
        or race.get("name")
        or race.get("race_name")
        or ""
    ).strip()


def _race_circuit_name(race: dict) -> str:
    """Extract circuit name from a schedule race dict."""
    circuit = race.get("Circuit") or race.get("circuit") or {}
    return (
        circuit.get("circuitName")
        or circuit.get("name")
        or race.get("circuitName")
        or ""
    ).strip()


# ── Build a city → race dict lookup from the schedule ─────────────────────────

@st.cache_data(ttl=3600)
def build_race_lookup(_year: int | None = None) -> dict[str, dict]:
    """
    Returns a dict keyed by city (lowercased):
        { "melbourne": {date, gp_name, circuit_name, lap_length_km, status,
                        country, round} }

    The _year param is accepted for API-compatibility but the schedule endpoint
    is a static document (single season); the year param is ignored in the fetch.
    Lap lengths come from the LAP_LENGTHS hard-coded dict.
    """
    races = fetch_f1_schedule()
    lookup: dict[str, dict] = {}
    for r in races:
        city = _race_city(r)
        if not city:
            continue

        race_date = _parse_race_date(r)

        # Lap length from hard-coded dict (keyed by city lowercase)
        city_l = city.lower()
        lap_length = LAP_LENGTHS.get(city_l)

        lookup[city_l] = {
            "date":          race_date,
            "lap_length_km": lap_length,
            "gp_name":       _race_gp_name(r),
            "circuit_name":  _race_circuit_name(r),
            "status":        r.get("status", "Scheduled"),
            "country":       _race_country(r),
            "round":         int(r.get("round") or 0),
        }
    return lookup


def get_race_info_for_city(city: str, year: int | None = None) -> dict | None:
    """
    Look up a city's race info (date, lap_length, etc.).
    Tries exact match first, then a case-insensitive substring match.
    Returns None if no match found.
    """
    if not city:
        return None
    lookup = build_race_lookup(year)
    city_l = city.lower()
    if city_l in lookup:
        return lookup[city_l]
    for k, v in lookup.items():
        if city_l in k or k in city_l:
            return v
    return None


# ── Sort a list of circuits by upcoming race date ────────────────────────────

def sort_circuits_by_race_date(circuits: list[dict]) -> list[dict]:
    """
    Re-order a list of circuit dicts so that:
      1. Circuits whose next race is upcoming (date >= today) come first,
         sorted ascending by race date.
      2. Circuits whose race has already passed come next,
         sorted by projected next occurrence.
      3. Circuits not on the F1 calendar come last, sorted alphabetically.

    Each dict must have at least a 'city' key.
    """
    today  = date.today()
    lookup = build_race_lookup()

    def sort_key(c):
        city = (c.get("city") or "").lower()
        info = lookup.get(city)
        # Substring fallback
        if not info:
            for k, v in lookup.items():
                if city in k or k in city:
                    info = v
                    break
        if not info or not info.get("date"):
            return (3, 9999, c.get("name", ""))

        race_date = info["date"]
        if race_date >= today:
            delta = (race_date - today).days
            return (1, delta, c.get("name", ""))
        else:
            try:
                next_occ = race_date.replace(year=race_date.year + 1)
                delta = (next_occ - today).days
            except ValueError:
                delta = 9998
            return (2, delta, c.get("name", ""))

    return sorted(circuits, key=sort_key)


# ── Next single upcoming race ────────────────────────────────────────────────

def get_next_race() -> dict | None:
    """
    Return the single nearest upcoming race dict from the schedule.
    Returns None if the API is unavailable or all races are in the past.
    """
    today = date.today()
    races = fetch_f1_schedule()
    upcoming = []
    for r in races:
        d = _parse_race_date(r)
        if d and d >= today:
            upcoming.append((d, r))
    if not upcoming:
        return None
    upcoming.sort(key=lambda x: x[0])
    return upcoming[0][1]


# ── Get race weekend date range for a given circuit city ─────────────────────

def get_race_weekend_dates(city: str) -> tuple[date | None, date | None]:
    """
    Returns (start_date, end_date) for the race weekend of a circuit.
    Race weekends typically span Thursday → Sunday (4 days).
    Returns (None, None) if the city isn't found in the schedule.
    """
    today = date.today()
    info = get_race_info_for_city(city)
    if info and info.get("date"):
        race_date = info["date"]
        if race_date < today:
            # Estimate next year
            try:
                race_date = race_date.replace(year=race_date.year + 1)
            except ValueError:
                pass
        start = race_date - timedelta(days=3)
        return start, race_date
    return None, None


# ═══════════════════════════════════════════════════════════════════════════════
# PART 2 — WIKIPEDIA REST API  (free, no auth — circuit images + descriptions)
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=86400)   # cache 24 hours — Wikipedia content rarely changes
def fetch_wikipedia_summary(circuit_name: str) -> dict:
    """
    Fetch a Wikipedia page summary for a circuit.
    Returns a dict with keys:
      thumbnail_url  — best image URL (may be None)
      extract        — short text extract (2-4 sentences)
      page_url       — full Wikipedia page URL

    Falls back to empty strings/None if the page is not found.
    """
    empty = {"thumbnail_url": None, "extract": "", "page_url": ""}
    if not circuit_name:
        return empty

    # Try the circuit name directly, then with " Grand Prix Circuit" suffix
    names_to_try = [
        circuit_name,
        circuit_name.replace(" Grand Prix", ""),
        circuit_name + " racing circuit",
    ]

    for name in names_to_try:
        slug = name.replace(" ", "_")
        try:
            resp = requests.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}",
                headers={"User-Agent": "F1CircuitJournal/1.0 (Streamlit app)"},
                timeout=8,
            )
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("type") == "disambiguation":
                continue
            thumbnail = data.get("thumbnail") or data.get("originalimage") or {}
            return {
                "thumbnail_url": thumbnail.get("source"),
                "extract":       data.get("extract", ""),
                "page_url":      data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            }
        except Exception:
            continue

    return empty


# ═══════════════════════════════════════════════════════════════════════════════
# PART 3 — JOLPICA / ERGAST API  (free, no auth — historical circuit data)
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=86400)
def fetch_first_gp_years() -> dict[str, int]:
    """
    Fetch first GP year for each historical F1 circuit from Jolpica.
    Returns a dict keyed by city name (lowercased):
        { "melbourne": 1996, "monaco": 1929, ... }

    Uses the free Jolpica ergast-compatible endpoint — no auth required.
    """
    result: dict[str, int] = {}
    try:
        resp = requests.get(
            "https://api.jolpi.ca/ergast/f1/circuits.json",
            params={"limit": 200},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        circuits = (
            data.get("MRData", {})
                .get("CircuitTable", {})
                .get("Circuits", [])
        )
        for c in circuits:
            city = (c.get("Location", {}).get("locality") or "").strip().lower()
            if city:
                # Jolpica doesn't directly give first_gp_year in this endpoint;
                # We'll fall back to the seasons endpoint per circuit if needed.
                # For now store the circuitId for later enrichment.
                result[city] = c.get("circuitId", "")
    except Exception:
        pass
    return result


@st.cache_data(ttl=86400)
def fetch_first_gp_year_for_circuit(circuit_id: str) -> int | None:
    """
    For a given Ergast circuitId, fetch the earliest season that circuit hosted a race.
    Returns the year as an int, or None if unavailable.
    """
    if not circuit_id:
        return None
    try:
        resp = requests.get(
            f"https://api.jolpi.ca/ergast/f1/circuits/{circuit_id}/seasons.json",
            params={"limit": 1, "offset": 0},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        seasons = (
            data.get("MRData", {})
                .get("SeasonTable", {})
                .get("Seasons", [])
        )
        if seasons:
            return int(seasons[0].get("season", 0)) or None
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# PART 4 — CIRCUIT ENRICHMENT  (update DB with hard-coded + Jolpica data)
# ═══════════════════════════════════════════════════════════════════════════════

def enrich_circuits_from_rapidapi(conn) -> int:
    """
    For every circuit in the DB that is missing lap_length_km or first_gp_year,
    fill those fields using:
      - LAP_LENGTHS dict (for lap_length_km)
      - Jolpica ergast API (for first_gp_year)

    Returns the count of rows updated.
    conn: an open psycopg2 connection (caller is responsible for closing it).
    """
    updated = 0
    cur     = conn.cursor()

    # Fetch circuits missing one or both fields
    cur.execute(
        "SELECT id, name, city, lap_length_km, first_gp_year FROM circuits WHERE source = 'api';"
    )
    rows = cur.fetchall()

    # Pre-fetch Jolpica circuit ID map (city → circuitId string)
    circuit_id_map = fetch_first_gp_years()  # {city_lower: circuitId}

    for cid, cname, city, existing_lap, existing_year in rows:
        city_l = (city or "").strip().lower()

        # ── Lap length from LAP_LENGTHS dict ──────────────────────────────────
        if not existing_lap and city_l:
            new_lap = LAP_LENGTHS.get(city_l)
            if not new_lap:
                # Try substring match
                for k, v in LAP_LENGTHS.items():
                    if city_l in k or k in city_l:
                        new_lap = v
                        break
            if new_lap:
                cur.execute(
                    "UPDATE circuits SET lap_length_km = %s WHERE id = %s;",
                    (new_lap, cid)
                )
                updated += 1

        # ── First GP year from Jolpica ─────────────────────────────────────────
        if not existing_year and city_l:
            circuit_ergast_id = circuit_id_map.get(city_l)
            if not circuit_ergast_id:
                for k, v in circuit_id_map.items():
                    if city_l in k or k in city_l:
                        circuit_ergast_id = v
                        break
            if circuit_ergast_id:
                first_year = fetch_first_gp_year_for_circuit(circuit_ergast_id)
                if first_year:
                    cur.execute(
                        "UPDATE circuits SET first_gp_year = %s WHERE id = %s;",
                        (first_year, cid)
                    )
                    updated += 1

    conn.commit()
    cur.close()
    return updated


# ═══════════════════════════════════════════════════════════════════════════════
# PART 5 — CIRCUIT TRACK IMAGE  (Wikipedia, biased toward layout diagrams)
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=86400)
def fetch_circuit_track_image(circuit_name: str, city: str = "") -> dict:
    """
    Fetch a circuit track layout image from Wikipedia.
    Tries the exact circuit name first (Wikipedia circuit articles often use
    the track layout SVG as their lead image), then city-based fallbacks.
    Returns the same dict shape as fetch_wikipedia_summary().
    """
    names_to_try = [n for n in [
        circuit_name,
        (city.title() + " circuit") if city else None,
        circuit_name.replace(" Grand Prix", "") if "Grand Prix" in circuit_name else None,
    ] if n]

    for name in names_to_try:
        slug = name.strip().replace(" ", "_")
        try:
            resp = requests.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}",
                headers={"User-Agent": "F1CircuitJournal/1.0 (Streamlit app)"},
                timeout=8,
            )
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("type") == "disambiguation":
                continue
            thumbnail = data.get("thumbnail") or data.get("originalimage") or {}
            if thumbnail.get("source"):
                return {
                    "thumbnail_url": thumbnail.get("source"),
                    "extract":       data.get("extract", ""),
                    "page_url":      data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                }
        except Exception:
            continue

    return {"thumbnail_url": None, "extract": "", "page_url": ""}


# ═══════════════════════════════════════════════════════════════════════════════
# PART 6 — STAR RATING  (★★★☆☆ HTML, used everywhere ratings appear)
# ═══════════════════════════════════════════════════════════════════════════════

def star_rating_html(rating) -> str:
    """
    Returns an HTML string rendering a ★★★☆☆ star rating for a 1–5 score.

    Usage:
        st.markdown(star_rating_html(3.5), unsafe_allow_html=True)
    """
    if rating is None:
        return "<span style='color:#94a3b8;font-size:0.85em'>—</span>"

    r      = max(0.0, min(5.0, float(rating)))
    filled = round(r)
    empty  = 5 - filled
    stars  = "★" * filled + "☆" * empty

    return (
        f'<span style="color:#f59e0b;font-size:1.1em;letter-spacing:2px">{stars}</span>'
        f'<span style="color:#64748b;font-size:0.78em;margin-left:5px">{r:.1f}</span>'
    )
