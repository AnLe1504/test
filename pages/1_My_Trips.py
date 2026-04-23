# ─────────────────────────────────────────────────────────────────────────────
# pages/1_My_Trips.py  —  Create, view, edit, and delete trips
#
# Layout:
#   ① Add Trip form   — trip name, circuit selector (autofills dates from RapidAPI),
#                       start/end date, status dropdown, notes
#   ② All Trips table — name, dates, status, circuit count, Explore buttons,
#                       Edit and Delete buttons
#   ③ Edit form       — pre-filled form shown when Edit is clicked
#   ④ Delete confirmation
#
# Circuit dropdown in Add Trip:
#   - Selecting a circuit auto-fills start/end date with the race weekend dates
#     (from RapidAPI).  If the race already passed this year, next year's date
#     is used instead.  The circuit selection itself is NOT saved — it's only
#     for UX date autofill.  The actual trip↔circuit link is created on
#     "Log a Visit".
#
# Explore buttons in All Trips:
#   - For each trip that has at least one circuit_visits row, show Google
#     search buttons for the first associated circuit's city.
# ─────────────────────────────────────────────────────────────────────────────

import streamlit as st
import streamlit.components.v1 as components
import urllib.parse
from datetime import date

from db    import get_connection
from utils import get_race_weekend_dates, get_race_info_for_city


st.set_page_config(page_title="My Trips", page_icon="🗓️", layout="wide")
st.title("🗓️ My Trips")
st.caption("Plan and manage your F1 race-weekend travel.")
st.divider()


STATUS_OPTIONS = ["planned", "completed", "cancelled"]

if "editing_trip_id"  not in st.session_state:
    st.session_state.editing_trip_id  = None
if "deleting_trip_id" not in st.session_state:
    st.session_state.deleting_trip_id = None


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: Explore buttons (same pattern as other pages)
# ─────────────────────────────────────────────────────────────────────────────
def explore_buttons(city: str, country: str, month: str | None = None):
    if not city: return
    # TODO: append &aid=YOUR_BOOKING_AID to booking_url once Booking.com affiliate is approved
    booking_url = (
        "https://www.booking.com/searchresults.html"
        f"?ss={urllib.parse.quote(f'{city} {country}')}"
    )
    # TODO: replace with Expedia affiliate URL once approved
    expedia_url = (
        "https://www.expedia.com/Flights-Search"
        f"?leg1=to:{urllib.parse.quote(f'{city}+{country}')}&passengers=adults:1&trip=oneway&mode=search"
    )
    c1, c2 = st.columns(2)
    c1.link_button(f"🏨 Book Hotels in {city}", booking_url)
    c2.link_button(f"✈️ Search Flights to {city}", expedia_url)


# ─────────────────────────────────────────────────────────────────────────────
# FETCH circuit list for the date-autofill dropdown
# ─────────────────────────────────────────────────────────────────────────────
conn = get_connection()
cur  = conn.cursor()
cur.execute("SELECT id, name, city, country FROM circuits ORDER BY name;")
circuits_raw = cur.fetchall()
cur.close()
conn.close()

# Map: label → (circuit_id, city, country)
circuit_date_map = {
    f"{r[1]} ({r[3]})": (r[0], r[2] or "", r[3] or "")   # (id, city, country)
    for r in circuits_raw
}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — ADD TRIP FORM
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("➕ Add a New Trip")

# ── Circuit selector OUTSIDE the form so changing it triggers a rerun ─────────
# Inside st.form(), widget changes are batched until submit — dates can't update.
# Placing this selectbox outside the form means Streamlit reruns immediately on
# change, letting us compute suggested dates before the form renders.
circuit_options = ["— No circuit (enter dates manually) —"] + list(circuit_date_map.keys())

# Reset the circuit selector after a successful form submission
if st.session_state.get("_reset_circuit_sel"):
    st.session_state["add_trip_circuit"] = circuit_options[0]
    st.session_state["_reset_circuit_sel"] = False

col_circ_lbl, col_circ_sel = st.columns([1, 3])
col_circ_lbl.markdown("**Choose Circuit:**")
selected_circuit_label = col_circ_sel.selectbox(
    "Circuit for date autofill",
    circuit_options,
    key="add_trip_circuit",
    label_visibility="collapsed",
    help="Select a circuit to auto-fill start/end date from the F1 race calendar.",
)

# Compute suggested dates (runs on every rerun, so changes immediately on circuit select)
suggested_start = date.today()
suggested_end   = None
if selected_circuit_label != circuit_options[0]:
    _, city, _ = circuit_date_map[selected_circuit_label]
    api_start, api_end = get_race_weekend_dates(city)
    if api_start:
        suggested_start = api_start
        suggested_end   = api_end
        end_str = api_end.strftime("%b %d, %Y") if api_end else "TBD"
        st.caption(f"📅 Dates filled: **{api_start.strftime('%b %d')} → {end_str}** "
                   f"(race weekend for {selected_circuit_label.split(' (')[0]})")
    else:
        st.caption("⚠️ No scheduled race found for this circuit — enter dates manually.")

with st.form("add_trip_form", clear_on_submit=True):
    trip_name = st.text_input(
        "Trip Name *",
        placeholder="e.g. Monaco 2025 Weekend",
    )

    # Row 2: dates (pre-filled from circuit selection above)
    col_start, col_end = st.columns(2)
    start_date = col_start.date_input("Start Date *", value=suggested_start)
    end_date   = col_end.date_input(
        "End Date",
        value=suggested_end,
        min_value=date(2000, 1, 1),
    )

    # Row 3: status + notes
    col_status, col_notes = st.columns([1, 2])
    status = col_status.selectbox("Status", STATUS_OPTIONS, index=0)
    notes  = col_notes.text_area(
        "Notes",
        placeholder="Ticket details, hotel, travel tips…",
        height=80,
    )

    submitted = st.form_submit_button("Add Trip")

    if submitted:
        errors = []
        if not trip_name.strip():
            errors.append("**Trip Name** is required.")
        if end_date is not None and end_date < start_date:
            errors.append("**End Date** must be on or after Start Date.")

        if errors:
            for err in errors:
                st.error(err)
        else:
            try:
                conn = get_connection()
                cur  = conn.cursor()
                cur.execute(
                    "INSERT INTO trips (trip_name, start_date, end_date, status, notes) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id;",
                    (
                        trip_name.strip(),
                        start_date,
                        end_date,
                        status,
                        notes.strip() or None,
                    )
                )
                new_trip_id = cur.fetchone()[0]

                # If a circuit was selected, auto-create a circuit_visits row
                # (attended=false) so Circuit Explorer can immediately show the link.
                if selected_circuit_label != circuit_options[0]:
                    linked_circuit_id = circuit_date_map[selected_circuit_label][0]
                    race_year = start_date.year
                    cur.execute(
                        """
                        INSERT INTO circuit_visits
                            (trip_id, circuit_id, race_year, attended)
                        VALUES (%s, %s, %s, false)
                        ON CONFLICT (trip_id, circuit_id, race_year) DO NOTHING;
                        """,
                        (new_trip_id, linked_circuit_id, race_year)
                    )

                conn.commit(); cur.close(); conn.close()
                st.success(f"Trip **{trip_name.strip()}** added!")
                st.session_state["_reset_circuit_sel"] = True
                st.rerun()
            except Exception as e:
                st.error(f"Database error: {e}")

st.divider()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — ALL TRIPS TABLE
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("📋 All Trips")

conn = get_connection()
cur  = conn.cursor()
cur.execute(
    """
    SELECT
        t.id,
        t.trip_name,
        t.start_date,
        t.end_date,
        t.status,
        t.notes,
        COUNT(cv.id) AS visit_count,
        -- First circuit city+country for explore buttons
        MIN(c.city)    AS first_city,
        MIN(c.country) AS first_country
    FROM trips t
    LEFT JOIN circuit_visits cv ON cv.trip_id   = t.id
    LEFT JOIN circuits       c  ON c.id         = cv.circuit_id
    GROUP BY t.id
    ORDER BY t.start_date DESC;
    """
)
trips = cur.fetchall()
cur.close(); conn.close()

if not trips:
    st.info("No trips yet — add your first one above!")
else:
    h_name, h_dates, h_status, h_visits, h_actions = st.columns([3, 3, 1.5, 1, 2])
    h_name.markdown("**Trip**");     h_dates.markdown("**Dates**")
    h_status.markdown("**Status**"); h_visits.markdown("**Circuits**")
    h_actions.markdown("**Actions**")
    st.markdown("---")

    for row in trips:
        trip_id, name, s_date, e_date, status, notes, visit_count, first_city, first_country = row

        s_str = s_date.strftime("%b %d, %Y") if s_date else "—"
        e_str = e_date.strftime("%b %d, %Y") if e_date else "TBD"

        badge = {
            "planned":   "🔵 Planned",
            "completed": "✅ Completed",
            "cancelled": "❌ Cancelled",
        }
        status_label = badge.get(status, status)

        col_name, col_dates, col_status, col_visits, col_actions = st.columns([3, 3, 1.5, 1, 2])
        col_name.write(f"**{name}**")
        col_dates.write(f"{s_str} → {e_str}")
        col_status.write(status_label)
        col_visits.write(str(visit_count))

        btn1, btn2 = col_actions.columns(2)
        if btn1.button("✏️ Edit", key=f"edit_{trip_id}"):
            st.session_state.editing_trip_id  = trip_id
            st.session_state.deleting_trip_id = None
            st.toast("✏️ Edit form ready — scroll down", icon="✏️")
        if btn2.button("🗑️ Delete", key=f"del_{trip_id}"):
            st.session_state.deleting_trip_id = trip_id
            st.session_state.editing_trip_id  = None

        # ── Explore buttons for this trip's destination ──────────────────────
        # Only shown if the trip has at least one circuit associated via circuit_visits
        if first_city:
            # Get the race month from RapidAPI for a richer search
            race_info = get_race_info_for_city(first_city, s_date.year if s_date else date.today().year)
            month     = race_info["date"].strftime("%B") if (race_info and race_info.get("date")) else None
            with st.expander(f"🌍 Explore {first_city}", expanded=False):
                explore_buttons(first_city, first_country or "", month)

st.divider()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — EDIT FORM
# ═══════════════════════════════════════════════════════════════════════════════

if st.session_state.editing_trip_id is not None:
    edit_id = st.session_state.editing_trip_id

    components.html("""<script>
    setTimeout(function() {
        window.parent.document.querySelector('[data-testid="stMain"]')
            .scrollTo({top: 999999, behavior: 'smooth'});
    }, 120);
    </script>""", height=0)

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(
        "SELECT trip_name, start_date, end_date, status, notes FROM trips WHERE id = %s;",
        (edit_id,)
    )
    trip_data = cur.fetchone()

    # Find currently linked circuit (first one) for pre-selection
    cur.execute(
        """
        SELECT cv.circuit_id, c.name, c.country
        FROM circuit_visits cv
        JOIN circuits c ON c.id = cv.circuit_id
        WHERE cv.trip_id = %s
        ORDER BY cv.id ASC LIMIT 1;
        """,
        (edit_id,)
    )
    linked_circuit_row = cur.fetchone()
    cur.close(); conn.close()

    if trip_data:
        e_name, e_start, e_end, e_status, e_notes = trip_data
        st.subheader(f"✏️ Editing: {e_name}")

        # Build current circuit selection label for pre-fill
        edit_circuit_options = ["— No circuit —"] + list(circuit_date_map.keys())
        current_circuit_label = "— No circuit —"
        if linked_circuit_row:
            linked_cid, linked_cname, linked_ccountry = linked_circuit_row
            match_label = f"{linked_cname} ({linked_ccountry})"
            if match_label in circuit_date_map:
                current_circuit_label = match_label
        edit_circuit_idx = edit_circuit_options.index(current_circuit_label)

        with st.form("edit_trip_form"):
            new_name = st.text_input("Trip Name *", value=e_name)

            # Circuit selector in edit form (updates/inserts circuit_visits link)
            new_circuit_label = st.selectbox(
                "Associated Circuit",
                edit_circuit_options,
                index=edit_circuit_idx,
                help="Changing this updates the circuit linked to this trip in Circuit Explorer.",
            )

            col_s, col_e = st.columns(2)
            new_start = col_s.date_input("Start Date *", value=e_start)
            new_end   = col_e.date_input("End Date", value=e_end)
            col_st, col_nt = st.columns([1, 2])
            status_idx = STATUS_OPTIONS.index(e_status) if e_status in STATUS_OPTIONS else 0
            new_status = col_st.selectbox("Status", STATUS_OPTIONS, index=status_idx)
            new_notes  = col_nt.text_area("Notes", value=e_notes or "", height=80)

            sv, cv_ = st.columns(2)
            save   = sv.form_submit_button("💾 Save Changes")
            cancel = cv_.form_submit_button("✖ Cancel")

            if cancel:
                st.session_state.editing_trip_id = None
                st.rerun()

            if save:
                errors = []
                if not new_name.strip():
                    errors.append("**Trip Name** is required.")
                if new_end is not None and new_end < new_start:
                    errors.append("**End Date** must be on or after Start Date.")
                if errors:
                    for err in errors:
                        st.error(err)
                else:
                    try:
                        conn = get_connection()
                        cur  = conn.cursor()
                        cur.execute(
                            "UPDATE trips SET trip_name=%s, start_date=%s, end_date=%s, "
                            "status=%s, notes=%s WHERE id=%s;",
                            (new_name.strip(), new_start, new_end, new_status,
                             new_notes.strip() or None, edit_id)
                        )
                        # Update circuit link if circuit selection changed
                        if new_circuit_label != "— No circuit —":
                            new_linked_id = circuit_date_map[new_circuit_label][0]
                            race_year = new_start.year
                            cur.execute(
                                """
                                INSERT INTO circuit_visits
                                    (trip_id, circuit_id, race_year, attended)
                                VALUES (%s, %s, %s, false)
                                ON CONFLICT (trip_id, circuit_id, race_year) DO NOTHING;
                                """,
                                (edit_id, new_linked_id, race_year)
                            )
                        conn.commit(); cur.close(); conn.close()
                        st.success("Trip updated!")
                        st.session_state.editing_trip_id = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Database error: {e}")

    st.divider()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — DELETE CONFIRMATION
# ═══════════════════════════════════════════════════════════════════════════════

if st.session_state.deleting_trip_id is not None:
    del_id = st.session_state.deleting_trip_id

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT trip_name FROM trips WHERE id = %s;", (del_id,))
    del_row = cur.fetchone()
    cur.close(); conn.close()

    if del_row:
        del_name = del_row[0]
        st.warning(
            f"**Delete \"{del_name}\"?**  "
            f"This will also delete all circuit visit records linked to this trip "
            f"(ON DELETE CASCADE). This cannot be undone."
        )
        conf_col, cancel_col = st.columns(2)
        if conf_col.button("🗑️ Yes, delete trip and all its visits", type="primary"):
            try:
                conn = get_connection()
                cur  = conn.cursor()
                cur.execute("DELETE FROM trips WHERE id = %s;", (del_id,))
                conn.commit(); cur.close(); conn.close()
                st.success(f"Trip **{del_name}** deleted.")
                st.session_state.deleting_trip_id = None
                st.rerun()
            except Exception as e:
                st.error(f"Database error: {e}")
        if cancel_col.button("✖ Cancel"):
            st.session_state.deleting_trip_id = None
            st.rerun()
