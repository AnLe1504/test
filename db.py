# ─────────────────────────────────────────────────────────────────────────────
# db.py  —  Shared database connection helper
#
# Every page imports get_connection() from here.
# Never put credentials directly in code — the DB_URL lives in
# .streamlit/secrets.toml (local) and in the Streamlit Cloud secrets dashboard
# (deployed).  psycopg2 uses %s placeholders for parameterized queries.
# ─────────────────────────────────────────────────────────────────────────────

import psycopg2
import streamlit as st
from urllib.parse import urlparse


def get_connection():
    """
    Opens and returns a new psycopg2 connection to the PostgreSQL database.

    We parse the DB_URL and pass parameters explicitly instead of handing the
    raw URL string to psycopg2.  This avoids OSError: [Errno 81] Need
    authenticator — a macOS SSL handshake failure that occurs when psycopg2
    tries to parse sslmode out of a URL string on certain macOS + OpenSSL
    version combinations.  Passing sslmode as a keyword argument bypasses the
    problematic code path.

    Usage pattern in every page:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("SELECT ...", (param,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    """
    url = urlparse(st.secrets["DB_URL"])
    return psycopg2.connect(
        host=url.hostname,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        dbname=url.path.lstrip("/"),
        sslmode="require",
        connect_timeout=10,
    )
