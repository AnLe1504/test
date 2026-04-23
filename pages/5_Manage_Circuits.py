# ─────────────────────────────────────────────────────────────────────────────
# pages/5_Manage_Circuits.py  —  Add custom circuits and manage the circuit list
#
# Layout:
#   ① Add Circuit form  — name, country, city, lap length, first GP year
#                         source is automatically set to 'custom'
#   ② Search bar        — filter by name or country (ILIKE)
#   ③ Circuit table     — all circuits, source badge, Edit / Delete buttons
#                         Delete is DISABLED for source='api' rows
#   ④ Edit form         — pre-filled form shown when Edit is clicked
# ─────────────────────────────────────────────────────────────────────────────

import streamlit as st
import streamlit.components.v1 as components
from datetime import date

from db    import get_connection
from utils import enrich_circuits_from_rapidapi


st.set_page_config(page_title="Manage Circuits", page_icon="🏟️", layout="wide")
st.title("🏟️ Manage Circuits")
st.caption(
    "Add fictional or future circuits to your journal. "
    "API-imported circuits are read-only (protected from deletion)."
)
st.divider()


# ── Session state for edit and delete panels ───────────────────────────────────
if "editing_circuit_id"  not in st.session_state:
    st.session_state.editing_circuit_id  = None
if "deleting_circuit_id" not in st.session_state:
    st.session_state.deleting_circuit_id = None

# ── Auto-enrich: fill NULL lap_length_km / first_gp_year from RapidAPI ────────
# Runs silently on every page load; only updates rows where the field is NULL.
# Uses a session flag so it only fires once per browser session (not every rerun).
if "circuits_enriched" not in st.session_state:
    try:
        conn = get_connection()
        updated = enrich_circuits_from_rapidapi(conn)
        conn.close()
        st.session_state.circuits_enriched = True
        if updated > 0:
            st.toast(f"Updated {updated} circuit(s) with lap length data from the F1 calendar.", icon="🔄")
    except Exception:
        st.session_state.circuits_enriched = True   # don't retry on error


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — ADD CUSTOM CIRCUIT FORM
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("➕ Add a Custom Circuit")
st.caption("Custom circuits are user-created records — they will not be overwritten by the API seeder.")

with st.form("add_circuit_form", clear_on_submit=True):
    # Row 1: required fields
    col_name, col_country = st.columns(2)
    circuit_name = col_name.text_input("Circuit Name *", placeholder="e.g. Hanoi Street Circuit")
    country      = col_country.text_input("Country *",       placeholder="e.g. Vietnam")

    # Row 2: optional fields
    col_city, col_lap, col_year = st.columns(3)
    city          = col_city.text_input("City / Location", placeholder="e.g. Hanoi")
    lap_length    = col_lap.number_input(
        "Lap Length (km)",
        min_value=0.0,
        max_value=30.0,
        value=0.0,
        step=0.001,
        format="%.3f",
        help="Leave at 0 to store as blank (NULL)"
    )
    first_gp_year = col_year.number_input(
        "First GP Year",
        min_value=1950,
        max_value=date.today().year + 10,
        value=date.today().year,
        step=1,
        help="The year of the first Grand Prix held at this circuit"
    )

    submitted = st.form_submit_button("Add Custom Circuit")

    if submitted:
        # ── Validation ─────────────────────────────────────────────────────
        errors = []
        if not circuit_name.strip():
            errors.append("**Circuit Name** is required.")
        if not country.strip():
            errors.append("**Country** is required.")
        if lap_length < 0:
            errors.append("**Lap Length** must be a positive number.")

        if errors:
            for err in errors:
                st.error(err)
        else:
            # Store None for optional fields the user left blank / at zero
            lap_val  = float(lap_length) if lap_length > 0 else None
            year_val = int(first_gp_year) if first_gp_year > 0 else None

            try:
                conn = get_connection()
                cur  = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO circuits
                        (name, country, city, lap_length_km, first_gp_year, source)
                    VALUES (%s, %s, %s, %s, %s, 'custom');
                    """,
                    (
                        circuit_name.strip(),
                        country.strip(),
                        city.strip() or None,
                        lap_val,
                        year_val,
                    )
                )
                conn.commit()
                cur.close()
                conn.close()
                st.success(f"Circuit **{circuit_name.strip()}** added!")
                st.rerun()
            except Exception as e:
                st.error(f"Database error: {e}")

st.divider()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — SEARCH BAR
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("🔍 Circuit List")
search = st.text_input("Search by name or country", placeholder="e.g. Monaco, Italy, Silverstone…")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — CIRCUIT TABLE
# ═══════════════════════════════════════════════════════════════════════════════

# Build the query: apply search filter if the user typed something
conn = get_connection()
cur  = conn.cursor()

if search.strip():
    like_val = f"%{search.strip()}%"
    cur.execute(
        """
        SELECT id, name, country, city, lap_length_km, first_gp_year, source
        FROM circuits
        WHERE name ILIKE %s OR country ILIKE %s
        ORDER BY name;
        """,
        (like_val, like_val)
    )
else:
    cur.execute(
        """
        SELECT id, name, country, city, lap_length_km, first_gp_year, source
        FROM circuits
        ORDER BY name;
        """
    )

circuits = cur.fetchall()
cur.close()
conn.close()

if not circuits:
    st.info("No circuits found. Add one above or run seed_db.py to import from OpenF1.")
else:
    st.caption(f"{len(circuits)} circuit{'s' if len(circuits) != 1 else ''} found")

    # ── Column headers ──────────────────────────────────────────────────────
    h1, h2, h3, h4, h5, h6 = st.columns([3, 2, 2, 1.5, 1.5, 2])
    h1.markdown("**Circuit**")
    h2.markdown("**Country**")
    h3.markdown("**City**")
    h4.markdown("**Lap (km)**")
    h5.markdown("**First GP**")
    h6.markdown("**Actions**")
    st.markdown("---")

    for row in circuits:
        cid, cname, ccountry, ccity, clap, cfirst, csource = row

        c1, c2, c3, c4, c5, c6 = st.columns([3, 2, 2, 1.5, 1.5, 2])

        # Source badge: 🌐 API (imported, protected) vs ✏️ Custom (user-created)
        source_badge = "🌐 API" if csource == "api" else "✏️ Custom"
        c1.write(f"{cname}  `{source_badge}`")
        c2.write(ccountry)
        c3.write(ccity or "—")
        c4.write(f"{float(clap):.3f}" if clap else "—")
        c5.write(str(cfirst) if cfirst else "—")

        btn_edit, btn_del = c6.columns(2)

        # Edit button: available for all circuits (API and custom)
        if btn_edit.button("✏️", key=f"edit_c_{cid}", help="Edit this circuit"):
            st.session_state.editing_circuit_id = cid
            st.toast("✏️ Edit form ready — scroll down", icon="✏️")

        # Delete button: only for custom circuits — API rows are protected
        if csource == "custom":
            if btn_del.button("🗑️", key=f"del_c_{cid}", help="Delete this custom circuit"):
                st.session_state.deleting_circuit_id = cid
                st.session_state.editing_circuit_id  = None
        else:
            # Render a disabled placeholder so layout stays consistent
            btn_del.button(
                "🔒",
                key=f"nodl_c_{cid}",
                disabled=True,
                help="API-imported circuits cannot be deleted",
            )

        # Delete confirmation (shown inline below the row)
        if st.session_state.deleting_circuit_id == cid:
            st.warning(
                f"Delete circuit **{cname}**? "
                "This will also remove any visits or bucket list entries linked to it. "
                "This cannot be undone."
            )
            conf_col, cancel_col = st.columns(2)
            if conf_col.button("🗑️ Yes, delete", key=f"conf_del_c_{cid}"):
                try:
                    conn = get_connection()
                    cur  = conn.cursor()
                    cur.execute("DELETE FROM circuits WHERE id = %s AND source = 'custom';", (cid,))
                    conn.commit()
                    cur.close()
                    conn.close()
                    st.success(f"Circuit **{cname}** deleted.")
                    st.session_state.deleting_circuit_id = None
                    st.session_state.editing_circuit_id  = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Database error: {e}")
            if cancel_col.button("✖ Cancel", key=f"cancel_del_c_{cid}"):
                st.session_state.deleting_circuit_id = None
                st.rerun()

st.divider()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — EDIT FORM  (shown when an Edit button was clicked)
# ═══════════════════════════════════════════════════════════════════════════════

if st.session_state.editing_circuit_id is not None:
    edit_cid = st.session_state.editing_circuit_id

    components.html("""<script>
    setTimeout(function() {
        window.parent.document.querySelector('[data-testid="stMain"]')
            .scrollTo({top: 999999, behavior: 'smooth'});
    }, 120);
    </script>""", height=0)

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(
        "SELECT name, country, city, lap_length_km, first_gp_year, source FROM circuits WHERE id = %s;",
        (edit_cid,)
    )
    cdata = cur.fetchone()
    cur.close()
    conn.close()

    if cdata:
        e_name, e_country, e_city, e_lap, e_first, e_source = cdata

        st.subheader(f"✏️ Editing: {e_name}")
        if e_source == "api":
            st.info(
                "This is an API-imported circuit. You can edit the display fields, "
                "but it cannot be deleted. Only custom circuits can be removed.",
                icon="ℹ️",
            )

        with st.form("edit_circuit_form"):
            col_n, col_c = st.columns(2)
            new_name    = col_n.text_input("Circuit Name *", value=e_name)
            new_country = col_c.text_input("Country *", value=e_country)

            col_city2, col_lap2, col_yr2 = st.columns(3)
            new_city  = col_city2.text_input("City / Location", value=e_city or "")
            new_lap   = col_lap2.number_input(
                "Lap Length (km)",
                min_value=0.0, max_value=30.0,
                value=float(e_lap) if e_lap else 0.0,
                step=0.001, format="%.3f",
            )
            new_first = col_yr2.number_input(
                "First GP Year",
                min_value=1950, max_value=date.today().year + 10,
                value=int(e_first) if e_first else date.today().year,
                step=1,
            )

            save_col, cancel_col = st.columns(2)
            if save_col.form_submit_button("💾 Save Changes"):
                errors = []
                if not new_name.strip():
                    errors.append("**Circuit Name** is required.")
                if not new_country.strip():
                    errors.append("**Country** is required.")
                if new_lap < 0:
                    errors.append("**Lap Length** must be a positive number.")

                if errors:
                    for err in errors:
                        st.error(err)
                else:
                    lap_val2  = float(new_lap)  if new_lap > 0  else None
                    year_val2 = int(new_first) if new_first > 0 else None
                    try:
                        conn = get_connection()
                        cur  = conn.cursor()
                        cur.execute(
                            """
                            UPDATE circuits
                            SET name          = %s,
                                country       = %s,
                                city          = %s,
                                lap_length_km = %s,
                                first_gp_year = %s
                            WHERE id = %s;
                            """,
                            (
                                new_name.strip(),
                                new_country.strip(),
                                new_city.strip() or None,
                                lap_val2,
                                year_val2,
                                edit_cid,
                            )
                        )
                        conn.commit()
                        cur.close()
                        conn.close()
                        st.success("Circuit updated!")
                        st.session_state.editing_circuit_id = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Database error: {e}")

            if cancel_col.form_submit_button("✖ Cancel"):
                st.session_state.editing_circuit_id = None
                st.rerun()
