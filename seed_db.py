# ─────────────────────────────────────────────────────────────────────────────
# seed_db.py  —  One-time setup script (run from terminal, NOT from Streamlit)
#
# What this script does:
#   1. Creates all four database tables if they don't already exist.
#   2. Calls the OpenF1 /meetings endpoint for years 2023–2025 to pull real
#      F1 circuit names, countries, and cities.
#   3. Deduplicates circuits by circuit_short_name and inserts them into the
#      circuits table with source = 'api'.
#
# How to run (from inside the Project 1 directory):
#   python seed_db.py
#
# The script reads DB_URL from .streamlit/secrets.toml via a tiny manual
# parser (since st.secrets only works inside a running Streamlit app).
# ─────────────────────────────────────────────────────────────────────────────

import psycopg2
import requests
import re
from urllib.parse import urlparse


# ── 1. Read DB_URL from secrets.toml without Streamlit running ────────────────
# secrets.toml format:  DB_URL = "postgresql://..."
# We parse it with a simple regex so this script can run as a plain Python
# script in the terminal before Streamlit is even launched.

def load_db_url(path=".streamlit/secrets.toml"):
    """Parse DB_URL out of secrets.toml manually (no Streamlit required)."""
    with open(path) as f:
        contents = f.read()
    match = re.search(r'DB_URL\s*=\s*"([^"]+)"', contents)
    if not match:
        raise ValueError("DB_URL not found in secrets.toml")
    return match.group(1)


DB_URL = load_db_url()


# ── 2. SQL: CREATE TABLE statements (all idempotent via IF NOT EXISTS) ─────────

CREATE_CIRCUITS = """
CREATE TABLE IF NOT EXISTS circuits (
    id             SERIAL PRIMARY KEY,
    name           VARCHAR(100) NOT NULL,
    country        VARCHAR(60)  NOT NULL,
    city           VARCHAR(60),
    lap_length_km  DECIMAL(5,3),
    first_gp_year  INTEGER,
    source         VARCHAR(10)  DEFAULT 'api'
                   CHECK (source IN ('api','custom')),
    created_at     TIMESTAMP    DEFAULT NOW()
);
"""
# circuits.source distinguishes rows pulled from OpenF1 ('api') from rows
# added manually by the user ('custom').  Manage Circuits page uses this flag
# to decide whether the Delete button is enabled.

CREATE_TRIPS = """
CREATE TABLE IF NOT EXISTS trips (
    id          SERIAL PRIMARY KEY,
    trip_name   VARCHAR(120) NOT NULL,
    start_date  DATE         NOT NULL,
    end_date    DATE,
    status      VARCHAR(20)  DEFAULT 'planned'
                CHECK (status IN ('planned','completed','cancelled')),
    notes       TEXT,
    created_at  TIMESTAMP    DEFAULT NOW()
);
"""

CREATE_CIRCUIT_VISITS = """
CREATE TABLE IF NOT EXISTS circuit_visits (
    id               SERIAL PRIMARY KEY,
    trip_id          INTEGER REFERENCES trips(id) ON DELETE CASCADE,
    circuit_id       INTEGER REFERENCES circuits(id),
    race_year        INTEGER NOT NULL,
    ticket_type      VARCHAR(60),
    seating_section  VARCHAR(80),
    personal_rating  INTEGER CHECK (personal_rating BETWEEN 1 AND 5),
    personal_notes   TEXT,
    attended         BOOLEAN   DEFAULT false,
    created_at       TIMESTAMP DEFAULT NOW(),
    UNIQUE(trip_id, circuit_id, race_year)
);
"""
# ON DELETE CASCADE: deleting a trip automatically removes all its visit rows.
# UNIQUE(trip_id, circuit_id, race_year): prevents logging the same circuit
# on the same trip in the same year more than once.

CREATE_BUCKET_LIST = """
CREATE TABLE IF NOT EXISTS bucket_list (
    id           SERIAL PRIMARY KEY,
    circuit_id   INTEGER REFERENCES circuits(id) ON DELETE CASCADE,
    priority     VARCHAR(20) DEFAULT 'someday'
                 CHECK (priority IN ('dream','likely','someday')),
    added_notes  TEXT,
    created_at   TIMESTAMP DEFAULT NOW(),
    UNIQUE(circuit_id)
);
"""
# UNIQUE(circuit_id): each circuit can appear at most once on the bucket list.


# ── 3. OpenF1 API helpers ──────────────────────────────────────────────────────

OPENF1_BASE = "https://api.openf1.org/v1"

def fetch_meetings(year: int) -> list[dict]:
    """
    Call OpenF1 /meetings?year=YYYY and return the JSON list.
    Each item contains: meeting_name, country_name, location,
    circuit_short_name, circuit_key, year, etc.
    """
    url = f"{OPENF1_BASE}/meetings"
    resp = requests.get(url, params={"year": year}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def collect_unique_circuits(years: list[int]) -> list[dict]:
    """
    Fetch meetings for multiple years, deduplicate by circuit_short_name,
    and return a list of dicts ready to INSERT into the circuits table.
    """
    seen = set()          # tracks circuit_short_name values already processed
    circuits = []

    for year in years:
        print(f"  Fetching meetings for {year}...")
        meetings = fetch_meetings(year)

        for m in meetings:
            short_name = m.get("circuit_short_name", "").strip()
            if not short_name or short_name in seen:
                continue              # skip duplicates across years

            seen.add(short_name)
            circuits.append({
                "name":    m.get("meeting_name", short_name).strip(),
                # meeting_name is the full official GP name (e.g.
                # "Formula 1 Gulf Air Bahrain Grand Prix 2024").
                # We use circuit_short_name as the dedup key and store
                # meeting_name as the display name.  Users can rename
                # custom circuits later via Manage Circuits.
                "country": m.get("country_name", "Unknown").strip(),
                "city":    m.get("location", "").strip(),
            })

    return circuits


# ── 4. Main: create tables + seed circuits ─────────────────────────────────────

def make_connection(db_url: str):
    """
    Parse DB_URL and connect with explicit keyword arguments.
    Avoids OSError: [Errno 81] Need authenticator on macOS — caused when
    psycopg2 parses sslmode out of a URL string on certain SSL library versions.
    """
    parsed = urlparse(db_url)
    return psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        dbname=parsed.path.lstrip("/"),
        sslmode="require",
        connect_timeout=10,
    )


def main():
    conn = make_connection(DB_URL)
    cur  = conn.cursor()

    # — Create tables —
    print("Creating tables...")
    for sql in [CREATE_CIRCUITS, CREATE_TRIPS, CREATE_CIRCUIT_VISITS, CREATE_BUCKET_LIST]:
        cur.execute(sql)
    conn.commit()
    print("  Tables created (or already existed).")

    # — Fetch circuits from OpenF1 —
    print("Fetching circuits from OpenF1 API (2023–2025)...")
    circuits = collect_unique_circuits([2023, 2024, 2025])
    print(f"  Found {len(circuits)} unique circuits.")

    # — Insert circuits (skip if name already exists) —
    # We use INSERT ... ON CONFLICT DO NOTHING so re-running the script is safe.
    # There is no UNIQUE constraint on name in the table definition, but we
    # simulate idempotency by checking existence before inserting.
    inserted = 0
    for c in circuits:
        cur.execute(
            "SELECT id FROM circuits WHERE name = %s AND source = 'api';",
            (c["name"],)
        )
        if cur.fetchone() is None:
            cur.execute(
                """
                INSERT INTO circuits (name, country, city, source)
                VALUES (%s, %s, %s, 'api');
                """,
                (c["name"], c["country"], c["city"])
            )
            inserted += 1

    conn.commit()
    print(f"  Inserted {inserted} new circuits ({len(circuits) - inserted} already existed).")

    cur.close()
    conn.close()
    print("Done! Your database is ready.")


if __name__ == "__main__":
    main()
