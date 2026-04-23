# ─────────────────────────────────────────────────────────────────────────────
# Home.py  —  Dashboard / entry point for the Streamlit app
#
# What this page shows (read-only, no forms):
#   Row 1 — Four st.metric() summary cards (live DB counts)
#   Row 2 — "Recent Visits" table with star ratings
#   Row 3 — Next Planned Trip  |  Next F1 Race Weekend (Jolpica schedule)
# ─────────────────────────────────────────────────────────────────────────────

import streamlit as st
from datetime import date
from db    import get_connection
from utils import (
    star_rating_html,
    get_next_race,
    fetch_wikipedia_summary,
    LAP_LENGTHS,
    _race_gp_name,
    _race_city,
    _race_country,
    _race_circuit_name,
    _parse_race_date,
)


st.set_page_config(
    page_title="F1 Circuit Journal",
    page_icon="🏎️",
    layout="wide",
)


# ── DB helpers ─────────────────────────────────────────────────────────────────
def fetch_scalar(sql: str, params: tuple = ()):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    cur.close(); conn.close()
    return row[0] if row and row[0] is not None else 0

def fetch_rows(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


# ── SQL ────────────────────────────────────────────────────────────────────────
TOTAL_VISITED_SQL = "SELECT COUNT(*) FROM circuit_visits WHERE attended = true;"
TOTAL_TRIPS_SQL   = "SELECT COUNT(*) FROM trips;"
BUCKET_COUNT_SQL  = "SELECT COUNT(*) FROM bucket_list;"
BEST_CIRCUIT_SQL  = """
    SELECT c.name FROM circuit_visits cv
    JOIN circuits c ON c.id = cv.circuit_id
    WHERE cv.personal_rating IS NOT NULL
    GROUP BY c.id, c.name
    ORDER BY AVG(cv.personal_rating) DESC LIMIT 1;
"""
RECENT_VISITS_SQL = """
    SELECT c.name AS circuit, t.trip_name AS trip,
           cv.race_year AS year, cv.personal_rating AS rating, cv.attended AS attended
    FROM circuit_visits cv
    JOIN circuits c ON c.id = cv.circuit_id
    JOIN trips    t ON t.id = cv.trip_id
    ORDER BY cv.created_at DESC LIMIT 5;
"""
NEXT_TRIP_SQL = """
    SELECT trip_name, start_date, end_date, status, notes
    FROM trips
    WHERE status = 'planned' AND start_date >= CURRENT_DATE
    ORDER BY start_date ASC LIMIT 1;
"""


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

st.title("🏎️ F1 Circuit Journal")
st.caption("Your personal Formula 1 travel tracker — circuits visited, trips planned, dreams catalogued.")
st.divider()


# ── Section 1: Summary metrics ────────────────────────────────────────────────
st.subheader("📊 Your Journey at a Glance")
col1, col2, col3, col4 = st.columns(4)

total_visited = fetch_scalar(TOTAL_VISITED_SQL)
col1.metric("Circuits Visited", total_visited, help="Circuit visits marked 'Attended'")

total_trips = fetch_scalar(TOTAL_TRIPS_SQL)
col2.metric("Trips Logged", total_trips)

bucket_count = fetch_scalar(BUCKET_COUNT_SQL)
col3.metric("On Bucket List", bucket_count)

best = fetch_scalar(BEST_CIRCUIT_SQL)
col4.metric("Highest-Rated Circuit", best if best else "—")

st.divider()


# ── Section 2: Recent visits with star ratings ────────────────────────────────
st.subheader("🕐 Recently Logged Visits")

recent = fetch_rows(RECENT_VISITS_SQL)

if not recent:
    st.info("No visits logged yet. Head to **Log a Visit** to add your first one!")
else:
    h1, h2, h3, h4, h5 = st.columns([3, 3, 1, 2, 1.5])
    h1.markdown("**Circuit**"); h2.markdown("**Trip**")
    h3.markdown("**Year**");    h4.markdown("**Rating**"); h5.markdown("**Attended**")
    st.markdown("---")

    for r in recent:
        c1, c2, c3, c4, c5 = st.columns([3, 3, 1, 2, 1.5])
        c1.write(r["circuit"])
        c2.write(r["trip"])
        c3.write(str(r["year"]))
        with c4:
            st.markdown(star_rating_html(r["rating"]), unsafe_allow_html=True)
        c5.write("✅" if r["attended"] else "📋 Planned")

st.divider()


# ── Section 3: Next planned trip + upcoming races ─────────────────────────────
left_col, right_col = st.columns(2)

# — Next planned trip —
with left_col:
    st.subheader("🗓️ Next Planned Trip")
    trips = fetch_rows(NEXT_TRIP_SQL)
    if not trips:
        st.info("No upcoming trips planned. Go to **My Trips** to plan one!")
    else:
        t = trips[0]
        st.markdown(f"### {t['trip_name']}")
        s = t["start_date"].strftime("%B %d, %Y") if t["start_date"] else "—"
        e = t["end_date"].strftime("%B %d, %Y")   if t["end_date"]   else "TBD"
        st.markdown(f"**Dates:** {s} → {e}")
        st.markdown(f"**Status:** {t['status'].capitalize()}")
        if t["notes"]:
            st.caption(t["notes"])

# — Next F1 race weekend (Jolpica schedule) —
with right_col:
    st.subheader("🏁 Next F1 Race Weekend")

    next_race = get_next_race()

    if next_race is None:
        st.info("Race schedule unavailable right now. Try again shortly.")
    else:
        gp_name      = _race_gp_name(next_race)
        city         = _race_city(next_race)
        country      = _race_country(next_race)
        circuit_name = _race_circuit_name(next_race)
        race_date    = _parse_race_date(next_race)

        wiki = fetch_wikipedia_summary(gp_name or circuit_name)

        if wiki.get("thumbnail_url"):
            try:
                st.image(wiki["thumbnail_url"], caption=circuit_name or gp_name,
                         use_container_width=True)
            except Exception:
                pass

        st.markdown(f"### {gp_name}")
        if circuit_name:
            st.markdown(f"**🏟️ Circuit:** {circuit_name}")
        st.markdown(f"**📍 Location:** {city}, {country}")

        if race_date:
            days_away = (race_date - date.today()).days
            st.markdown(f"**📅 Date:** {race_date.strftime('%B %d, %Y')}")
            if days_away == 0:
                st.success("🏁 Race day is TODAY!")
            elif days_away > 0:
                st.info(f"⏳ {days_away} days away")

        city_l = city.lower()
        lap_km = LAP_LENGTHS.get(city_l) or next(
            (v for k, v in LAP_LENGTHS.items() if city_l in k or k in city_l), None
        )
        if lap_km:
            st.caption(f"📏 Lap length: {lap_km} km")

        if wiki.get("extract"):
            sentences = wiki["extract"].split(". ")
            snippet = ". ".join(sentences[:2]) + ("." if len(sentences) > 2 else "")
            st.caption(snippet)

        if wiki.get("page_url"):
            st.markdown(f"[🔗 Wikipedia]({wiki['page_url']})")
