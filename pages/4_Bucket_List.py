# ─────────────────────────────────────────────────────────────────────────────
# pages/4_Bucket_List.py  —  Dream circuits you want to attend someday
#
# Layout:
#   ① Add to Bucket List form  — circuit dropdown (only circuits NOT already
#                                on the list), priority selector, notes
#   ② Bucket list display      — grouped by priority tier:
#                                  🏆 Dream  →  🎯 Likely  →  📅 Someday
#      Each entry shows: circuit name, country, notes, date added,
#      "Visited!" notice if an attended visit exists, Explore buttons,
#      and a Delete (from bucket list only) button.
# ─────────────────────────────────────────────────────────────────────────────

import streamlit as st
import urllib.parse

from db import get_connection


st.set_page_config(page_title="Bucket List", page_icon="⭐", layout="wide")
st.title("⭐ My F1 Bucket List")
st.caption("Every circuit you dream of attending — ranked by how likely you are to actually make it.")
st.divider()

if "deleting_bl_id" not in st.session_state:
    st.session_state.deleting_bl_id = None


def explore_buttons(city: str, country: str):
    """Booking.com hotel search + Expedia flight search for a destination."""
    if not city: return
    # TODO: append &aid=YOUR_BOOKING_AID once Booking.com affiliate is approved
    booking_url = (
        "https://www.booking.com/searchresults.html"
        f"?ss={urllib.parse.quote(f'{city} {country}')}"
    )
    # TODO: replace with Expedia affiliate URL once approved
    expedia_url = (
        "https://www.expedia.com/Flights-Search"
        f"?leg1=to:{urllib.parse.quote(f'{city}+{country}')}&passengers=adults:1&trip=oneway&mode=search"
    )
    col1, col2 = st.columns(2)
    col1.link_button(f"🏨 Book Hotels in {city}", booking_url)
    col2.link_button(f"✈️ Search Flights to {city}", expedia_url)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — ADD TO BUCKET LIST FORM
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("➕ Add a Circuit to Your Bucket List")

# Fetch only circuits NOT already on the bucket list (so the dropdown only
# shows circuits the user hasn't added yet — dynamic, no hard-coded options).
conn = get_connection()
cur  = conn.cursor()
cur.execute(
    """
    SELECT id, name, country
    FROM circuits
    WHERE id NOT IN (SELECT circuit_id FROM bucket_list)
    ORDER BY name;
    """
)
available_circuits = cur.fetchall()
cur.close()
conn.close()

# Priority options — matches the CHECK constraint in bucket_list table
PRIORITY_OPTIONS = {
    "🏆 Dream  — I will make this happen":    "dream",
    "🎯 Likely — On my radar for the next few years": "likely",
    "📅 Someday — Would love it if the stars align":  "someday",
}

if not available_circuits:
    st.info("Every circuit is already on your bucket list! Nothing left to add.")
else:
    circuit_add_map = {f"{r[1]} ({r[2]})": r[0] for r in available_circuits}

    with st.form("add_bucket_form", clear_on_submit=True):
        selected_circuit_label = st.selectbox(
            "Circuit *",
            list(circuit_add_map.keys()),
        )
        selected_priority_label = st.selectbox(
            "Priority *",
            list(PRIORITY_OPTIONS.keys()),
        )
        added_notes = st.text_area(
            "Notes",
            placeholder="Why this circuit? Any specific race year in mind? Dream seats?",
            height=80,
        )

        submitted = st.form_submit_button("Add to Bucket List")

        if submitted:
            circuit_id    = circuit_add_map[selected_circuit_label]
            priority_val  = PRIORITY_OPTIONS[selected_priority_label]

            # ── Duplicate guard: check before INSERT to give a friendly message
            # rather than crashing on the UNIQUE(circuit_id) constraint.
            conn = get_connection()
            cur  = conn.cursor()
            cur.execute(
                "SELECT id FROM bucket_list WHERE circuit_id = %s;",
                (circuit_id,)
            )
            already_exists = cur.fetchone()
            cur.close()
            conn.close()

            if already_exists:
                st.error("This circuit is already on your bucket list!")
            else:
                try:
                    conn = get_connection()
                    cur  = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO bucket_list (circuit_id, priority, added_notes)
                        VALUES (%s, %s, %s);
                        """,
                        (circuit_id, priority_val, added_notes.strip() or None)
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    st.success(f"**{selected_circuit_label.split(' (')[0]}** added to your bucket list!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Database error: {e}")

st.divider()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — BUCKET LIST DISPLAY  (grouped by priority tier)
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("📋 Your Bucket List")

# Fetch bucket list joined to circuits + check if an attended visit exists
conn = get_connection()
cur  = conn.cursor()
cur.execute(
    """
    SELECT
        bl.id           AS bl_id,
        bl.priority,
        bl.added_notes,
        bl.created_at,
        c.id            AS circuit_id,
        c.name          AS circuit_name,
        c.country,
        c.city,
        -- True if at least one circuit_visit is attended for this circuit
        EXISTS (
            SELECT 1 FROM circuit_visits cv
            WHERE cv.circuit_id = c.id AND cv.attended = true
        )                AS already_visited
    FROM bucket_list bl
    JOIN circuits c ON c.id = bl.circuit_id
    ORDER BY
        CASE bl.priority
            WHEN 'dream'   THEN 1
            WHEN 'likely'  THEN 2
            WHEN 'someday' THEN 3
        END,
        bl.created_at ASC;
    """
)
cols     = [d[0] for d in cur.description]
bl_rows  = [dict(zip(cols, row)) for row in cur.fetchall()]
cur.close()
conn.close()

if not bl_rows:
    st.info("Your bucket list is empty — add a circuit above to start dreaming!")
else:
    # Group by priority tier for display
    tiers = {
        "dream":   ("🏆 Dream",   []),
        "likely":  ("🎯 Likely",  []),
        "someday": ("📅 Someday", []),
    }
    for row in bl_rows:
        tiers[row["priority"]][1].append(row)

    for tier_key, (tier_label, entries) in tiers.items():
        if not entries:
            continue

        st.markdown(f"### {tier_label}")

        for entry in entries:
            with st.container(border=True):
                # ── Header row: circuit name + country + visited badge ─────
                left, right = st.columns([5, 1])

                with left:
                    visited_badge = " · ✅ **Already Visited!**" if entry["already_visited"] else ""
                    st.markdown(f"#### {entry['circuit_name']}{visited_badge}")
                    city_str = f"{entry['city']}, " if entry["city"] else ""
                    st.markdown(f"📍 {city_str}{entry['country']}")

                    if entry["already_visited"]:
                        st.info(
                            "You've attended this circuit! Consider removing it from your "
                            "bucket list, or keep it if you'd love to go again.",
                            icon="ℹ️",
                        )

                    added_date = entry["created_at"].strftime("%B %d, %Y") \
                                 if entry["created_at"] else "—"
                    st.caption(f"Added: {added_date}")

                    if entry["added_notes"]:
                        st.markdown(f"*{entry['added_notes']}*")

                # ── Delete button (removes from bucket list only, not circuits) ──
                with right:
                    if st.button("🗑️ Remove", key=f"del_bl_{entry['bl_id']}",
                                 help="Remove from bucket list (circuit itself is kept)"):
                        st.session_state.deleting_bl_id = entry["bl_id"]

                    if st.session_state.deleting_bl_id == entry["bl_id"]:
                        st.warning(
                            f"Remove **{entry['circuit_name']}** from your bucket list? "
                            "The circuit itself is kept — only the bucket list entry is removed."
                        )
                        conf_c, cancel_c = st.columns(2)
                        if conf_c.button("🗑️ Yes, remove", key=f"conf_bl_{entry['bl_id']}"):
                            try:
                                conn = get_connection()
                                cur  = conn.cursor()
                                cur.execute(
                                    "DELETE FROM bucket_list WHERE id = %s;",
                                    (entry["bl_id"],)
                                )
                                conn.commit()
                                cur.close()
                                conn.close()
                                st.success(f"Removed **{entry['circuit_name']}** from bucket list.")
                                st.session_state.deleting_bl_id = None
                                st.rerun()
                            except Exception as e:
                                st.error(f"Database error: {e}")
                        if cancel_c.button("✖ Cancel", key=f"cancel_bl_{entry['bl_id']}"):
                            st.session_state.deleting_bl_id = None
                            st.rerun()

                # ── Explore buttons ───────────────────────────────────────────
                city    = entry.get("city", "") or ""
                country = entry.get("country", "") or ""
                if city:
                    explore_buttons(city, country)

        st.markdown("")   # spacing between tiers
