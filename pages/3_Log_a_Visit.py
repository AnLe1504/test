# ─────────────────────────────────────────────────────────────────────────────
# pages/3_Log_a_Visit.py  —  Log a circuit visit (INSERT into circuit_visits)
#                            and edit / delete existing visit records
#
# Layout:
#   ① Log Visit form       — trip dropdown, circuit dropdown, visit details
#   ② Existing visits list — all circuit_visits rows with Edit / Delete
#                            (gradient rating bar, no explore expanders here)
#   ③ Edit form            — pre-filled form for a selected visit
# ─────────────────────────────────────────────────────────────────────────────

import streamlit as st
import streamlit.components.v1 as components
from datetime import date

from db    import get_connection
from utils import star_rating_html


st.set_page_config(page_title="Log a Visit", page_icon="📍", layout="wide")
st.title("📍 Log a Visit")
st.caption("Record a circuit visit against a trip — or plan ahead for one you haven't attended yet.")
st.divider()


# ── Session state for edit panel ───────────────────────────────────────────────
if "editing_visit_id"  not in st.session_state:
    st.session_state.editing_visit_id  = None
if "deleting_visit_id" not in st.session_state:
    st.session_state.deleting_visit_id = None


# ─────────────────────────────────────────────────────────────────────────────
# FETCH DROPDOWN DATA FROM DB
# All dropdowns pull from the database — zero hard-coded options.
# ─────────────────────────────────────────────────────────────────────────────

conn = get_connection()
cur  = conn.cursor()

# Trips dropdown: show trip name + start date so user can tell them apart
cur.execute(
    "SELECT id, trip_name, start_date FROM trips ORDER BY start_date DESC;"
)
trips_raw = cur.fetchall()
# Build { "Monaco 2025 (Mar 20, 2025)": trip_id }
trips_map = {
    f"{r[1]} ({r[2].strftime('%b %d, %Y')})": r[0]
    for r in trips_raw
}

# Circuits dropdown: show name + country
cur.execute("SELECT id, name, country, city FROM circuits ORDER BY name;")
circuits_raw = cur.fetchall()
# Build { "Circuit de Monaco (Monaco, Monte Carlo)": circuit_id }
circuits_map = {}
circuits_city_map  = {}   # circuit_id -> city (for explore buttons)
circuits_country_map = {} # circuit_id -> country (for explore buttons)
for r in circuits_raw:
    cid, cname, country, city = r
    label = f"{cname} ({country})"
    circuits_map[label]         = cid
    circuits_city_map[cid]      = city or ""
    circuits_country_map[cid]   = country or ""

cur.close()
conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — LOG VISIT FORM
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("➕ Log a New Visit")

if not trips_map:
    st.warning("You need at least one trip before logging a visit. Go to **My Trips** first.")
elif not circuits_map:
    st.warning("No circuits in the database yet. Run **seed_db.py** first.")
else:
    # — Pre-fill circuit if navigated here from Circuit Explorer —
    # Circuit Explorer sets st.session_state["prefill_circuit_id"] before
    # calling st.switch_page().  We pop it (consume once) to find the right
    # index in the circuits selectbox so the user lands on the correct circuit.
    prefill_cid     = st.session_state.pop("prefill_circuit_id", None)
    circuit_ids_list = list(circuits_map.values())
    circuit_lbl_list = list(circuits_map.keys())
    default_circuit_idx = 0
    if prefill_cid is not None and prefill_cid in circuit_ids_list:
        default_circuit_idx = circuit_ids_list.index(prefill_cid)
        st.info(f"Circuit pre-selected from Explorer: **{circuit_lbl_list[default_circuit_idx]}**")

    with st.form("log_visit_form", clear_on_submit=True):
        # Row 1: Trip + Circuit dropdowns
        col_trip, col_circuit = st.columns(2)
        selected_trip_label    = col_trip.selectbox("Trip *", list(trips_map.keys()))
        selected_circuit_label = col_circuit.selectbox(
            "Circuit *",
            circuit_lbl_list,
            index=default_circuit_idx,   # pre-selected if coming from Explorer
        )

        # Row 2: Year + Attended checkbox
        col_year, col_att, col_ticket = st.columns([1, 1, 2])
        current_year = date.today().year
        race_year  = col_year.number_input(
            "Race Year *",
            min_value=1950,
            max_value=current_year + 2,   # allow near-future planning
            value=current_year,
            step=1,
        )
        attended     = col_att.checkbox("Attended?", value=False,
                                        help="Check if you physically attended this race.")
        ticket_type  = col_ticket.text_input("Ticket Type", placeholder="e.g. General Admission, Grandstand")

        # Row 3: Seating section + rating
        col_seat, col_rating = st.columns(2)
        seating_section = col_seat.text_input("Seating Section", placeholder="e.g. Tribune K, Turn 1")
        personal_rating = col_rating.selectbox(
            "Personal Rating",
            options=["— (no rating)", "1 ⭐", "2 ⭐⭐", "3 ⭐⭐⭐", "4 ⭐⭐⭐⭐", "5 ⭐⭐⭐⭐⭐"],
            index=0,
        )

        # Row 4: Personal notes
        personal_notes = st.text_area(
            "Personal Notes",
            placeholder="How was the atmosphere? Highlights? Things to know for next time…",
            height=100,
        )

        submitted = st.form_submit_button("Log Visit")

        if submitted:
            trip_id    = trips_map[selected_trip_label]
            circuit_id = circuits_map[selected_circuit_label]

            # Convert rating selection ("3 ⭐⭐⭐" → 3, or None)
            rating_val = None
            if not personal_rating.startswith("—"):
                rating_val = int(personal_rating[0])

            # ── Validation ─────────────────────────────────────────────────
            errors = []
            if not (1950 <= int(race_year) <= current_year + 2):
                errors.append(f"**Race Year** must be between 1950 and {current_year + 2}.")

            # ── Duplicate check before INSERT ─────────────────────────────
            # Prevents crashing on the UNIQUE(trip_id, circuit_id, race_year) constraint
            if not errors:
                conn = get_connection()
                cur  = conn.cursor()
                cur.execute(
                    """
                    SELECT id FROM circuit_visits
                    WHERE trip_id = %s AND circuit_id = %s AND race_year = %s;
                    """,
                    (trip_id, circuit_id, int(race_year))
                )
                existing = cur.fetchone()
                cur.close()
                conn.close()
                if existing:
                    errors.append(
                        "You already logged this circuit + trip + year combination. "
                        "Find it in the **Existing Visits** section below and use Edit to update it."
                    )

            if errors:
                for err in errors:
                    st.error(err)
            else:
                try:
                    conn = get_connection()
                    cur  = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO circuit_visits
                            (trip_id, circuit_id, race_year, ticket_type,
                             seating_section, personal_rating, personal_notes, attended)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                        """,
                        (
                            trip_id,
                            circuit_id,
                            int(race_year),
                            ticket_type.strip()      or None,
                            seating_section.strip()  or None,
                            rating_val,
                            personal_notes.strip()   or None,
                            attended,
                        )
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    st.success("Visit logged!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Database error: {e}")

st.divider()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — EXISTING VISITS
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("📋 Existing Visits")

conn = get_connection()
cur  = conn.cursor()
cur.execute(
    """
    SELECT
        cv.id,
        c.name        AS circuit,
        c.city        AS city,
        c.country     AS country,
        t.trip_name   AS trip,
        t.start_date  AS trip_date,
        cv.race_year,
        cv.ticket_type,
        cv.seating_section,
        cv.personal_rating,
        cv.attended,
        cv.personal_notes
    FROM circuit_visits cv
    JOIN circuits c ON c.id = cv.circuit_id
    JOIN trips    t ON t.id = cv.trip_id
    ORDER BY cv.race_year DESC, c.name;
    """
)
cols   = [d[0] for d in cur.description]
visits = [dict(zip(cols, row)) for row in cur.fetchall()]
cur.close()
conn.close()

if not visits:
    st.info("No visits logged yet.")
else:
    # Column headers
    h1, h2, h3, h4, h5, h6 = st.columns([3, 2, 1.5, 2, 1, 2])
    h1.markdown("**Circuit**"); h2.markdown("**Trip**")
    h3.markdown("**Date**");    h4.markdown("**Rating**")
    h5.markdown("**Attended**"); h6.markdown("**Actions**")
    st.markdown("---")

    for v in visits:
        c1, c2, c3, c4, c5, c6 = st.columns([3, 2, 1.5, 2, 1, 2])
        c1.write(v["circuit"])
        c2.write(v["trip"])
        # Show trip start date in MM/DD/YYYY; fall back to race year if NULL
        date_str = v["trip_date"].strftime("%m/%d/%Y") if v["trip_date"] else str(v["race_year"])
        c3.write(date_str)
        # Gradient rating bar (replaces truncated star string)
        with c4:
            st.markdown(star_rating_html(v["personal_rating"]), unsafe_allow_html=True)
        c5.write("✅" if v["attended"] else "📋")

        btn1, btn2 = c6.columns(2)
        if btn1.button("✏️", key=f"edit_v_{v['id']}", help="Edit this visit"):
            st.session_state.editing_visit_id  = v["id"]
            st.session_state.deleting_visit_id = None
            st.toast("✏️ Edit form ready — scroll down", icon="✏️")
        if btn2.button("🗑️", key=f"del_v_{v['id']}", help="Delete this visit"):
            st.session_state.deleting_visit_id = v["id"]
            st.session_state.editing_visit_id  = None

        # Delete confirmation
        if st.session_state.deleting_visit_id == v["id"]:
            st.warning(
                f"Delete your visit to **{v['circuit']}** (trip: {v['trip']})? "
                "This cannot be undone."
            )
            conf_col, cancel_col = st.columns(2)
            if conf_col.button("🗑️ Yes, delete", key=f"conf_del_v_{v['id']}"):
                try:
                    conn = get_connection()
                    cur  = conn.cursor()
                    cur.execute("DELETE FROM circuit_visits WHERE id = %s;", (v["id"],))
                    conn.commit()
                    cur.close()
                    conn.close()
                    st.success("Visit deleted.")
                    st.session_state.deleting_visit_id = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Database error: {e}")
            if cancel_col.button("✖ Cancel", key=f"cancel_del_v_{v['id']}"):
                st.session_state.deleting_visit_id = None
                st.rerun()

        if v["personal_notes"]:
            st.caption(f"  📝 {v['personal_notes']}")

st.divider()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — EDIT VISIT FORM
# ═══════════════════════════════════════════════════════════════════════════════

if st.session_state.editing_visit_id is not None:
    edit_vid = st.session_state.editing_visit_id

    components.html("""<script>
    setTimeout(function() {
        window.parent.document.querySelector('[data-testid="stMain"]')
            .scrollTo({top: 999999, behavior: 'smooth'});
    }, 120);
    </script>""", height=0)

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT trip_id, circuit_id, race_year, ticket_type, seating_section,
               personal_rating, personal_notes, attended
        FROM circuit_visits WHERE id = %s;
        """,
        (edit_vid,)
    )
    vdata = cur.fetchone()
    cur.close()
    conn.close()

    if vdata:
        (e_trip_id, e_circuit_id, e_race_year, e_ticket, e_seat,
         e_rating, e_notes, e_attended) = vdata

        st.subheader("✏️ Edit Visit")

        # Build reverse maps for selectbox defaults
        trip_labels    = list(trips_map.keys())
        trip_ids       = list(trips_map.values())
        circuit_labels = list(circuits_map.keys())
        circuit_ids    = list(circuits_map.values())

        default_trip    = trip_labels[trip_ids.index(e_trip_id)]       if e_trip_id    in trip_ids    else trip_labels[0]
        default_circuit = circuit_labels[circuit_ids.index(e_circuit_id)] if e_circuit_id in circuit_ids else circuit_labels[0]

        RATING_OPTS = ["— (no rating)", "1 ⭐", "2 ⭐⭐", "3 ⭐⭐⭐", "4 ⭐⭐⭐⭐", "5 ⭐⭐⭐⭐⭐"]
        default_rating_idx = e_rating if e_rating else 0   # index 0 = "— (no rating)"

        with st.form("edit_visit_form"):
            col_t, col_c = st.columns(2)
            new_trip_label    = col_t.selectbox("Trip *", trip_labels,
                                                index=trip_labels.index(default_trip))
            new_circuit_label = col_c.selectbox("Circuit *", circuit_labels,
                                                index=circuit_labels.index(default_circuit))

            col_yr, col_att, col_tk = st.columns([1, 1, 2])
            new_year     = col_yr.number_input("Race Year *", min_value=1950,
                                               max_value=date.today().year + 2,
                                               value=int(e_race_year))
            new_attended = col_att.checkbox("Attended?", value=bool(e_attended))
            new_ticket   = col_tk.text_input("Ticket Type", value=e_ticket or "")

            col_seat2, col_rat2 = st.columns(2)
            new_seat   = col_seat2.text_input("Seating Section", value=e_seat or "")
            new_rating = col_rat2.selectbox("Personal Rating", RATING_OPTS,
                                            index=default_rating_idx)

            new_notes = st.text_area("Personal Notes", value=e_notes or "", height=100)

            save_btn, cancel_btn = st.columns(2)
            if save_btn.form_submit_button("💾 Save Changes"):
                new_tid  = trips_map[new_trip_label]
                new_cid  = circuits_map[new_circuit_label]
                new_rval = None if new_rating.startswith("—") else int(new_rating[0])

                # Duplicate check: same combo as another record (excluding self)
                conn = get_connection()
                cur  = conn.cursor()
                cur.execute(
                    """
                    SELECT id FROM circuit_visits
                    WHERE trip_id = %s AND circuit_id = %s AND race_year = %s
                      AND id != %s;
                    """,
                    (new_tid, new_cid, int(new_year), edit_vid)
                )
                clash = cur.fetchone()
                cur.close()
                conn.close()

                if clash:
                    st.error("Another visit already exists for this trip + circuit + year combination.")
                else:
                    try:
                        conn = get_connection()
                        cur  = conn.cursor()
                        cur.execute(
                            """
                            UPDATE circuit_visits
                            SET trip_id         = %s,
                                circuit_id      = %s,
                                race_year       = %s,
                                ticket_type     = %s,
                                seating_section = %s,
                                personal_rating = %s,
                                personal_notes  = %s,
                                attended        = %s
                            WHERE id = %s;
                            """,
                            (
                                new_tid, new_cid, int(new_year),
                                new_ticket.strip() or None,
                                new_seat.strip()   or None,
                                new_rval,
                                new_notes.strip()  or None,
                                new_attended,
                                edit_vid,
                            )
                        )
                        conn.commit()
                        cur.close()
                        conn.close()
                        st.success("Visit updated!")
                        st.session_state.editing_visit_id = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Database error: {e}")

            if cancel_btn.form_submit_button("✖ Cancel"):
                st.session_state.editing_visit_id = None
                st.rerun()
