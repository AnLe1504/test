# ─────────────────────────────────────────────────────────────────────────────
# pages/2_Circuit_Explorer.py  —  Browse, filter, and explore circuits
#
# Layout:
#   Cards always stay in a 3-column grid.
#   When a card's "View Details" is clicked, that card's ROW expands:
#     Left  col (1/3) — the selected card
#     Right col (2/3) — inline detail panel (Wikipedia, stats, visit history)
#   Other cards in the same row drop to a new row below the expanded section.
#
# Card border colors:
#   teal  (#14b8a6) — visited
#   blue  (#3b82f6) — on a planned trip (not yet attended)
#   amber (#f59e0b) — custom circuit (user-added)
#   red   (#ef4444) — bucket list only
#   slate (#64748b) — unvisited API circuit
# ─────────────────────────────────────────────────────────────────────────────

import streamlit as st
import streamlit.components.v1 as components
from collections import Counter
from datetime import date

from db    import get_connection
from utils import (
    star_rating_html,
    sort_circuits_by_race_date,
    get_race_info_for_city,
    fetch_wikipedia_summary,
    LAP_LENGTHS,
)
import urllib.parse


st.set_page_config(page_title="Circuit Explorer", page_icon="🗺️", layout="wide")
st.title("🗺️ Circuit Explorer")
st.caption("Browse every circuit, check your history, and jump straight into logging.")
st.divider()


# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] {
        min-height: 280px;
    }
    .status-strip { height:4px; border-radius:3px; margin-bottom:8px; overflow:hidden;
                    transition:height 0.2s ease; display:flex; align-items:center;
                    justify-content:center; cursor:default; }
    .status-strip span { color:white; font-size:0; font-weight:600; white-space:nowrap;
                         transition:font-size 0.15s ease; }
    .status-strip:hover { height:24px; }
    .status-strip:hover span { font-size:0.72em; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Session state ─────────────────────────────────────────────────────────────
if "selected_circuit_id"   not in st.session_state:
    st.session_state.selected_circuit_id   = None
if "editing_visit_id_exp"  not in st.session_state:
    st.session_state.editing_visit_id_exp  = None
if "deleting_visit_id_exp" not in st.session_state:
    st.session_state.deleting_visit_id_exp = None
if "show_add_bl_form"      not in st.session_state:
    st.session_state.show_add_bl_form      = False


# ── Helpers ───────────────────────────────────────────────────────────────────
def card_color(visit_count, source, on_bucket_list, trip_planned) -> tuple[str, str]:
    if visit_count > 0:    return "#14b8a6", "Visited"
    if trip_planned:       return "#3b82f6", "Planned Trip"
    if source == "custom": return "#f59e0b", "Custom"
    if on_bucket_list:     return "#ef4444", "Bucket List"
    return "#64748b", "Not Visited"

def explore_buttons(city, country, month=None):
    if not city: return
    suffix = f" {month}" if month else ""
    c1, c2 = st.columns(2)
    c1.link_button(f"🗺️ Explore {city}{suffix}",
        f"https://www.google.com/search?q={urllib.parse.quote(f'{city} {country} tourist attractions{suffix}')}")
    c2.link_button(f"🏨 Hotels in {city}",
        f"https://www.google.com/search?q={urllib.parse.quote(f'hotels in {city} {country}')}")

PRIORITY_OPTS = {"🏆 Dream": "dream", "🎯 Likely": "likely", "📅 Someday": "someday"}
today    = date.today()
cur_year = today.year


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — FILTER BAR
# ═══════════════════════════════════════════════════════════════════════════════

conn = get_connection(); cur = conn.cursor()
cur.execute("SELECT DISTINCT country FROM circuits ORDER BY country;")
country_list = ["All Countries"] + [r[0] for r in cur.fetchall()]
cur.execute("SELECT DISTINCT race_year FROM circuit_visits ORDER BY race_year DESC;")
year_list = ["All Years"] + [str(r[0]) for r in cur.fetchall()]
cur.close(); conn.close()

col_s, col_c, col_y, col_sort = st.columns([3, 2, 1.5, 2])
search_term      = col_s.text_input("🔍 Search", placeholder="Name or country…", label_visibility="collapsed")
selected_country = col_c.selectbox("Country", country_list, label_visibility="collapsed")
selected_year    = col_y.selectbox("Year", year_list, label_visibility="collapsed")

SORT_OPTIONS = {
    "Sort: Upcoming Race": "upcoming",
    "Sort: Country":       "c.country, c.name",
    "Sort: Name":          "c.name",
    "Sort: Avg Rating":    "avg_rating DESC NULLS LAST",
    "Sort: Date Added":    "c.created_at DESC",
}
sort_selection = col_sort.selectbox("Sort", list(SORT_OPTIONS.keys()), label_visibility="collapsed")

STATUS_OPTS = ["All", "Visited", "Not Visited", "On Bucket List", "Planned Trip", "Custom"]
status_filter = st.radio("Status", STATUS_OPTS, horizontal=True, label_visibility="collapsed")
st.divider()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — QUERY
# ═══════════════════════════════════════════════════════════════════════════════

conditions, params = [], []
if search_term.strip():
    conditions.append("(c.name ILIKE %s OR c.country ILIKE %s)")
    params += [f"%{search_term.strip()}%"] * 2
if selected_country != "All Countries":
    conditions.append("c.country = %s"); params.append(selected_country)
if selected_year != "All Years":
    conditions.append("cv.race_year = %s"); params.append(int(selected_year))

where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
sql_order = SORT_OPTIONS.get(sort_selection, "c.name")
if sql_order == "upcoming": sql_order = "c.name"

main_sql = f"""
    SELECT c.id, c.name, c.country, c.city, c.lap_length_km, c.first_gp_year, c.source,
           COUNT(DISTINCT cv.id) FILTER (WHERE cv.attended = true)    AS visit_count,
           ROUND(AVG(cv.personal_rating), 1)                           AS avg_rating,
           MAX(CASE WHEN bl.circuit_id IS NOT NULL THEN 1 ELSE 0 END)  AS on_bucket_list,
           MAX(CASE WHEN t.status = 'planned' AND cv.attended = false THEN 1 ELSE 0 END) AS trip_planned
    FROM circuits c
    LEFT JOIN circuit_visits cv ON cv.circuit_id = c.id
    LEFT JOIN trips          t  ON cv.trip_id    = t.id
    LEFT JOIN bucket_list    bl ON bl.circuit_id = c.id
    {where_clause}
    GROUP BY c.id
    ORDER BY {sql_order};
"""

conn = get_connection(); cur = conn.cursor()
cur.execute(main_sql, tuple(params))
col_names = [d[0] for d in cur.description]
all_rows  = [dict(zip(col_names, row)) for row in cur.fetchall()]
cur.close(); conn.close()

status_map = {
    "Visited":       lambda r: r["visit_count"] > 0,
    "Not Visited":   lambda r: r["visit_count"] == 0,
    "On Bucket List":lambda r: r["on_bucket_list"],
    "Planned Trip":  lambda r: r["trip_planned"],
    "Custom":        lambda r: r["source"] == "custom",
}
circuits = [r for r in all_rows if status_map[status_filter](r)] \
           if status_filter != "All" else all_rows

if sort_selection == "Sort: Upcoming Race":
    circuits = sort_circuits_by_race_date(circuits)

st.markdown(f"**{len(circuits)} circuit{'s' if len(circuits) != 1 else ''} found**")
st.markdown(
    '<div style="display:flex;gap:16px;flex-wrap:wrap;font-size:0.8em;margin-bottom:4px;">'
    '<span><span style="display:inline-block;width:12px;height:12px;background:#14b8a6;border-radius:2px;"></span> Visited</span>'
    '<span><span style="display:inline-block;width:12px;height:12px;background:#3b82f6;border-radius:2px;"></span> Planned Trip</span>'
    '<span><span style="display:inline-block;width:12px;height:12px;background:#f59e0b;border-radius:2px;"></span> Custom</span>'
    '<span><span style="display:inline-block;width:12px;height:12px;background:#ef4444;border-radius:2px;"></span> Bucket List</span>'
    '<span><span style="display:inline-block;width:12px;height:12px;background:#64748b;border-radius:2px;"></span> Not Visited</span>'
    '</div>',
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — CARD GRID WITH INLINE DETAIL EXPANSION
#
# Cards are always shown in a 3-column grid.
# When a card is selected:
#   • Its row renders as [card (1/3)] | [detail panel (2/3)]
#   • The other 1-2 cards from that row flow into a new row below.
# ═══════════════════════════════════════════════════════════════════════════════

sel_id = st.session_state.selected_circuit_id


def render_card(c: dict):
    color, status_label = card_color(
        c["visit_count"], c["source"], c["on_bucket_list"], c["trip_planned"]
    )
    race_info = get_race_info_for_city(c.get("city") or "", cur_year)
    is_sel    = sel_id == c["id"]

    with st.container(border=True):
        st.markdown(
            f'<div class="status-strip" style="background:{color};">'
            f'<span>{status_label}</span></div>',
            unsafe_allow_html=True,
        )
        city_str = f"{c['city']}, " if c["city"] else ""
        st.markdown(f"**{c['name']}**")
        st.caption(f"📍 {city_str}{c['country']}")

        if race_info and race_info.get("date"):
            rd = race_info["date"]
            if rd >= today:
                days = (rd - today).days
                st.caption(f"🏁 {rd.strftime('%b %d, %Y')} · {days}d away" if days > 0
                           else f"🏁 {rd.strftime('%b %d, %Y')} · **TODAY**")
            else:
                st.caption(f"🏁 {rd.strftime('%b %d, %Y')} (past)")

        stat1, stat2 = st.columns(2)
        stat1.metric("Visits", c["visit_count"])
        with stat2:
            st.caption("Avg Rating")
            st.markdown(star_rating_html(c["avg_rating"]), unsafe_allow_html=True)

        btn_label = "🔼 Close Details" if is_sel else "📋 View Details"
        if st.button(btn_label, key=f"det_{c['id']}", use_container_width=True):
            if is_sel:
                st.session_state.selected_circuit_id   = None
                st.session_state.editing_visit_id_exp  = None
                st.session_state.deleting_visit_id_exp = None
                st.session_state.show_add_bl_form      = False
            else:
                st.session_state.selected_circuit_id   = c["id"]
                st.session_state.editing_visit_id_exp  = None
                st.session_state.deleting_visit_id_exp = None
                st.session_state.show_add_bl_form      = False
            st.rerun()


def render_detail_panel(circuit_id: int):
    """Render the full detail panel for a circuit (Wikipedia, stats, visits)."""
    conn = get_connection(); cur = conn.cursor()
    cur.execute(
        "SELECT id, name, country, city, lap_length_km, first_gp_year, source "
        "FROM circuits WHERE id = %s;", (circuit_id,)
    )
    cinfo = cur.fetchone()

    cur.execute(
        """
        SELECT cv.id AS visit_id, cv.race_year, t.trip_name, cv.ticket_type,
               cv.seating_section, cv.personal_rating, cv.personal_notes,
               cv.attended, cv.trip_id, cv.circuit_id
        FROM circuit_visits cv
        JOIN trips t ON t.id = cv.trip_id
        WHERE cv.circuit_id = %s
        ORDER BY cv.race_year DESC;
        """, (circuit_id,)
    )
    vcols  = [d[0] for d in cur.description]
    visits = [dict(zip(vcols, r)) for r in cur.fetchall()]

    cur.execute("SELECT id FROM bucket_list WHERE circuit_id = %s;", (circuit_id,))
    already_on_bl = cur.fetchone() is not None
    cur.close(); conn.close()

    if not cinfo:
        st.warning("Circuit not found.")
        st.session_state.selected_circuit_id = None
        return

    _, c_name, c_country, c_city, c_lap, c_first, c_source = cinfo

    race_info   = get_race_info_for_city(c_city or "", cur_year)
    city_l      = (c_city or "").lower()
    display_lap = float(c_lap) if c_lap else (
        LAP_LENGTHS.get(city_l) or
        next((v for k, v in LAP_LENGTHS.items() if city_l in k or k in city_l), None)
    )
    wiki = fetch_wikipedia_summary(c_name)

    # ── Header ────────────────────────────────────────────────────────────────
    hdr_l, hdr_r = st.columns([3, 2])
    with hdr_l:
        st.subheader(f"📍 {c_name}")
        city_display = f"{c_city}, " if c_city else ""
        st.caption(f"{city_display}{c_country}")
        meta = []
        if display_lap: meta.append(f"Lap: {display_lap:.3f} km")
        if c_first:     meta.append(f"First GP: {c_first}")
        if meta:        st.caption("  ·  ".join(meta))
        if c_source == "custom": st.caption("✏️ Custom circuit")

    with hdr_r:
        act1, act2 = st.columns(2)
        if act1.button("📍 Log a Visit", key="dp_log", use_container_width=True):
            st.session_state["prefill_circuit_id"] = circuit_id
            st.switch_page("pages/3_Log_a_Visit.py")
        if already_on_bl:
            act2.button("⭐ On Bucket List", key="dp_bl",
                        disabled=True, use_container_width=True)
        else:
            if act2.button("⭐ Add to List", key="dp_bl", use_container_width=True):
                st.session_state.show_add_bl_form = not st.session_state.show_add_bl_form

    # ── Wikipedia image + extract ─────────────────────────────────────────────
    if wiki.get("thumbnail_url") or wiki.get("extract"):
        w_img, w_txt = st.columns([1, 2])
        if wiki.get("thumbnail_url"):
            try:
                w_img.image(wiki["thumbnail_url"], caption=c_name, use_container_width=True)
            except Exception:
                pass
        with w_txt:
            if race_info and race_info.get("date"):
                rd   = race_info["date"]
                days = (rd - today).days
                if days >= 0:
                    st.info(f"🏁 Next race: **{rd.strftime('%B %d, %Y')}** ({days} days away)")
                else:
                    st.caption(f"🏁 Last held: {rd.strftime('%B %d, %Y')}")
            if wiki.get("extract"):
                sentences = wiki["extract"].split(". ")
                st.markdown(". ".join(sentences[:3]) + ("." if len(sentences) > 3 else ""))
            if wiki.get("page_url"):
                st.markdown(f"[📖 Wikipedia]({wiki['page_url']})")
            if c_city:
                month = race_info["date"].strftime("%B") \
                        if race_info and race_info.get("date") else None
                explore_buttons(c_city, c_country, month)
    else:
        if race_info and race_info.get("date"):
            rd   = race_info["date"]
            days = (rd - today).days
            if days >= 0:
                st.info(f"🏁 Next race: **{rd.strftime('%B %d, %Y')}** ({days} days away)")
            else:
                st.caption(f"🏁 Last held: {rd.strftime('%B %d, %Y')}")
        if c_city:
            month = race_info["date"].strftime("%B") \
                    if race_info and race_info.get("date") else None
            explore_buttons(c_city, c_country, month)

    # ── Bucket list form ──────────────────────────────────────────────────────
    if st.session_state.show_add_bl_form and not already_on_bl:
        with st.form("dp_bl_form"):
            st.markdown("**Add to Bucket List**")
            priority_label = st.selectbox("Priority", list(PRIORITY_OPTS.keys()))
            bl_notes       = st.text_input("Notes (optional)")
            sv, cv_ = st.columns(2)
            if sv.form_submit_button("Add"):
                try:
                    conn = get_connection(); cur = conn.cursor()
                    cur.execute("SELECT id FROM bucket_list WHERE circuit_id=%s;", (circuit_id,))
                    if cur.fetchone():
                        st.error("Already on your bucket list!")
                    else:
                        cur.execute(
                            "INSERT INTO bucket_list (circuit_id, priority, added_notes) "
                            "VALUES (%s, %s, %s);",
                            (circuit_id, PRIORITY_OPTS[priority_label], bl_notes.strip() or None)
                        )
                        conn.commit()
                        st.success(f"**{c_name}** added to your bucket list!")
                        st.session_state.show_add_bl_form = False
                    cur.close(); conn.close()
                    st.rerun()
                except Exception as e:
                    st.error(f"Database error: {e}")
            if cv_.form_submit_button("Cancel"):
                st.session_state.show_add_bl_form = False
                st.rerun()

    st.markdown("---")

    # ── Summary metrics ───────────────────────────────────────────────────────
    attended_visits = [v for v in visits if v["attended"]]
    rated_visits    = [v for v in visits if v["personal_rating"]]
    sections = [v["seating_section"] for v in visits if v["seating_section"]]
    tickets  = [v["ticket_type"]     for v in visits if v["ticket_type"]]
    avg_r   = round(sum(v["personal_rating"] for v in rated_visits) / len(rated_visits), 1) \
              if rated_visits else None
    top_sec = Counter(sections).most_common(1)[0][0] if sections else "—"
    top_tkt = Counter(tickets).most_common(1)[0][0]  if tickets  else "—"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Times Attended", len(attended_visits))
    with m2:
        st.caption("Avg Rating")
        st.markdown(star_rating_html(avg_r), unsafe_allow_html=True)
    m3.metric("Fav Seat",   top_sec)
    m4.metric("Fav Ticket", top_tkt)

    st.markdown("---")

    # ── Visit history ─────────────────────────────────────────────────────────
    st.markdown("**Your Visits**")
    if not visits:
        st.info("No visits logged for this circuit yet.")
    else:
        h_yr, h_trip, h_tkt, h_seat, h_rat, h_att, h_act = \
            st.columns([1, 2.5, 2, 2, 2, 1, 2])
        h_yr.markdown("**Year**"); h_trip.markdown("**Trip**")
        h_tkt.markdown("**Ticket**"); h_seat.markdown("**Seat**")
        h_rat.markdown("**Rating**"); h_att.markdown("**Att.**")
        h_act.markdown("**Actions**")
        st.markdown("---")

        for v in visits:
            c_yr, c_trip, c_tkt, c_seat, c_rat, c_att, c_act = \
                st.columns([1, 2.5, 2, 2, 2, 1, 2])
            c_yr.write(str(v["race_year"]))
            c_trip.write(v["trip_name"])
            c_tkt.write(v["ticket_type"] or "—")
            c_seat.write(v["seating_section"] or "—")
            with c_rat:
                st.markdown(star_rating_html(v["personal_rating"]),
                            unsafe_allow_html=True)
            c_att.write("✅" if v["attended"] else "📋")

            be, bd = c_act.columns(2)
            if be.button("✏️", key=f"exp_e_{v['visit_id']}"):
                st.session_state.editing_visit_id_exp  = v["visit_id"]
                st.session_state.deleting_visit_id_exp = None
                st.rerun()
            if bd.button("🗑️", key=f"exp_d_{v['visit_id']}"):
                st.session_state.deleting_visit_id_exp = v["visit_id"]
                st.session_state.editing_visit_id_exp  = None
                st.rerun()

            if v["personal_notes"]:
                st.caption(f"📝 {v['personal_notes']}")

            if st.session_state.deleting_visit_id_exp == v["visit_id"]:
                st.warning(f"Delete your **{v['race_year']} {c_name}** visit? "
                           "This cannot be undone.")
                cc, sc = st.columns(2)
                if cc.button("🗑️ Yes, delete", key=f"cd_{v['visit_id']}"):
                    try:
                        conn = get_connection(); cur = conn.cursor()
                        cur.execute("DELETE FROM circuit_visits WHERE id=%s;",
                                    (v["visit_id"],))
                        conn.commit(); cur.close(); conn.close()
                        st.success("Visit deleted.")
                        st.session_state.deleting_visit_id_exp = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Database error: {e}")
                if sc.button("✖ Cancel", key=f"cs_{v['visit_id']}"):
                    st.session_state.deleting_visit_id_exp = None
                    st.rerun()


# ── Main grid loop ────────────────────────────────────────────────────────────
if not circuits:
    st.info("No circuits match your filters.")
else:
    for i in range(0, len(circuits), 3):
        row = circuits[i : i + 3]
        sel_card = next((c for c in row if c["id"] == sel_id), None)
        others   = [c for c in row if c["id"] != sel_id]

        if sel_card is not None and sel_id is not None:
            # Expanded row: selected card on left, detail panel on right
            card_col, detail_col = st.columns([1, 2], gap="large")
            with card_col:
                render_card(sel_card)
            with detail_col:
                render_detail_panel(sel_id)

            # Other 0-2 cards from this row drop into a new row below
            if others:
                extra_cols = st.columns(3)
                for j, c in enumerate(others):
                    with extra_cols[j]:
                        render_card(c)
        else:
            cols = st.columns(3)
            for j, c in enumerate(row):
                with cols[j]:
                    render_card(c)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — INLINE EDIT FORM  (always at bottom, outside columns context)
# ═══════════════════════════════════════════════════════════════════════════════

if st.session_state.editing_visit_id_exp is not None:
    edit_vid = st.session_state.editing_visit_id_exp

    conn = get_connection(); cur = conn.cursor()
    cur.execute(
        "SELECT trip_id, circuit_id, race_year, ticket_type, seating_section, "
        "personal_rating, personal_notes, attended FROM circuit_visits WHERE id=%s;",
        (edit_vid,)
    )
    vdata = cur.fetchone()
    cur.execute("SELECT id, trip_name, start_date FROM trips ORDER BY start_date DESC;")
    trips_map = {f"{r[1]} ({r[2].strftime('%b %d, %Y')})": r[0] for r in cur.fetchall()}
    cur.execute("SELECT id, name, country FROM circuits ORDER BY name;")
    circuits_map = {f"{r[1]} ({r[2]})": r[0] for r in cur.fetchall()}
    cur.close(); conn.close()

    if vdata:
        e_tid, e_cid, e_year, e_ticket, e_seat, e_rating, e_notes, e_attended = vdata
        trip_labels = list(trips_map.keys()); trip_ids = list(trips_map.values())
        cir_labels  = list(circuits_map.keys()); cir_ids = list(circuits_map.values())
        def_trip = trip_labels[trip_ids.index(e_tid)] if e_tid in trip_ids else trip_labels[0]
        def_cir  = cir_labels[cir_ids.index(e_cid)]  if e_cid in cir_ids  else cir_labels[0]
        RATING_OPTS = ["— (no rating)", "1 ⭐", "2 ⭐⭐", "3 ⭐⭐⭐", "4 ⭐⭐⭐⭐", "5 ⭐⭐⭐⭐⭐"]

        st.divider()
        st.subheader("✏️ Edit Visit")
        components.html(
            """<script>
            setTimeout(function() {
                window.parent.document.querySelector('[data-testid="stMain"]')
                    .scrollTo({top: 999999, behavior: 'smooth'});
            }, 120);
            </script>""",
            height=0,
        )

        with st.form("explorer_edit_visit"):
            ct, cc_ = st.columns(2)
            new_trip = ct.selectbox("Trip *", trip_labels, index=trip_labels.index(def_trip))
            new_cir  = cc_.selectbox("Circuit *", cir_labels, index=cir_labels.index(def_cir))
            cy, ca, ctk = st.columns([1, 1, 2])
            new_year     = cy.number_input("Year *", min_value=1950,
                                           max_value=date.today().year + 2, value=int(e_year))
            new_attended = ca.checkbox("Attended?", value=bool(e_attended))
            new_ticket   = ctk.text_input("Ticket", value=e_ticket or "")
            cs2, cr2 = st.columns(2)
            new_seat   = cs2.text_input("Seat", value=e_seat or "")
            new_rating = cr2.selectbox("Rating", RATING_OPTS, index=e_rating if e_rating else 0)
            new_notes  = st.text_area("Notes", value=e_notes or "", height=80)
            sv2, cv2 = st.columns(2)
            if sv2.form_submit_button("💾 Save"):
                new_tid  = trips_map[new_trip]; new_cid2 = circuits_map[new_cir]
                new_rval = None if new_rating.startswith("—") else int(new_rating[0])
                conn = get_connection(); cur = conn.cursor()
                cur.execute(
                    "SELECT id FROM circuit_visits "
                    "WHERE trip_id=%s AND circuit_id=%s AND race_year=%s AND id!=%s;",
                    (new_tid, new_cid2, int(new_year), edit_vid)
                )
                if cur.fetchone():
                    st.error("Duplicate visit already exists.")
                else:
                    cur.execute(
                        "UPDATE circuit_visits SET trip_id=%s, circuit_id=%s, race_year=%s, "
                        "ticket_type=%s, seating_section=%s, personal_rating=%s, "
                        "personal_notes=%s, attended=%s WHERE id=%s;",
                        (new_tid, new_cid2, int(new_year), new_ticket.strip() or None,
                         new_seat.strip() or None, new_rval,
                         new_notes.strip() or None, new_attended, edit_vid)
                    )
                    conn.commit()
                    st.success("Visit updated!")
                    st.session_state.editing_visit_id_exp = None
                    st.rerun()
                cur.close(); conn.close()
            if cv2.form_submit_button("✖ Cancel"):
                st.session_state.editing_visit_id_exp = None
                st.rerun()
