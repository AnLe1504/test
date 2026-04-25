# F1 Circuit Journal

A personal Formula 1 travel-planning CRUD app — log circuits you've visited, plan upcoming race-weekend trips, and curate a bucket list of dream tracks. Originally built in Streamlit, then converted to a production **Django** app and deployed on **Railway** with multi-user authentication and per-user data isolation.

## Live demo

**[→ web-production-3e212.up.railway.app](https://web-production-3e212.up.railway.app/)**

Create an account at `/register/` or sign in at `/login/`.

---

## Features

- **🏠 Home dashboard** — at-a-glance metrics (circuits visited, trips logged, bucket list size, top-rated circuit), recent visits, next planned trip, and the next F1 race weekend pulled live from the Jolpica F1 API with a Wikipedia-sourced circuit image.
- **🗓️ Trip planner** — add, edit, and delete race-weekend trips with status (Planned / Completed / Cancelled). The Add form auto-fills race weekend dates when you pick a circuit, using the Jolpica F1 calendar (Thursday → Sunday).
- **🗺️ Circuit Explorer** — every circuit on a status-coded card grid (visited / planned / custom / bucket / not-visited). Filter by name, country, year, status; sort by upcoming race or rating. Clicking a card slides in a detail panel with Wikipedia summary + image, race countdown, summary metrics, and full visit history.
- **📍 Visit logger** — log a visit against a trip with race year, attendance flag, ticket type, seating section, 1–5 ⭐ rating, and personal notes. Star ratings render in color-coded gradient (red → green) using a custom Django template tag.
- **⭐ Bucket list** — circuits grouped into 🏆 Dream / 🎯 Likely / 📅 Someday tiers with notes, "already visited" badges, and Booking.com + Expedia deep links for travel planning.
- **🏟️ Manage circuits** — search, edit, or add fictional/future circuits. API-imported circuits are read-only (🔒 deletion blocked at the database level via `WHERE source = 'custom'`).
- **🔐 Multi-user with Django auth** — register, login, logout. Each user only sees their own trips, visits, and bucket entries; the circuits catalog is shared. Anonymous visitors can browse the read-only views but are redirected to login on any write.

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│   Browser (Bootstrap 5 templates + vanilla JS)   │
└────────────────────┬─────────────────────────────┘
                     │ HTTPS (CSRF-protected)
┌────────────────────▼─────────────────────────────┐
│   Railway → Gunicorn → Django 4.2                │
│                                                  │
│   ├─ core/views.py      raw SQL via              │
│   │                     django.db.connection     │
│   │                                              │
│   ├─ core/models.py     managed=False mappings   │
│   │                     (no migrations applied)  │
│   │                                              │
│   ├─ Whitenoise         static files             │
│   └─ Django auth        login_required, etc.     │
└────────────────────┬─────────────────────────────┘
                     │
       ┌─────────────▼─────────────┐    ┌──────────────────────┐
       │   PostgreSQL (Retool)     │    │  External APIs       │
       │                           │    │  ─ Jolpica F1        │
       │   trips, circuits,        │    │    (race calendar)   │
       │   circuit_visits,         │    │  ─ Wikipedia REST    │
       │   bucket_list             │    │    (images + bios)   │
       │   + Django auth tables    │    │                      │
       └───────────────────────────┘    └──────────────────────┘
```

### Tech stack

| Layer | Choice | Why |
|---|---|---|
| Framework | Django 4.2 | Mature, batteries-included auth + admin |
| Templates | Django + Bootstrap 5 (CDN) | Clean, no build step |
| Database | PostgreSQL (Retool-hosted) | Existing schema preserved as-is |
| ORM | `managed=False` + raw SQL | Coexist with the legacy schema; verbatim port from Streamlit |
| Static files | Whitenoise (`CompressedManifestStaticFilesStorage`) | Serve from Gunicorn, no separate CDN |
| WSGI server | Gunicorn | Standard for Django on Railway |
| Hosting | Railway (Dockerfile builder) | One-click GitHub auto-deploys |
| Config | python-decouple + `.env` | Twelve-factor env separation |
| Auth | Django built-in (`auth_user`) | `LoginView`, `LogoutView`, `UserCreationForm`, `@login_required` |

### Data model

Four user-facing tables (all `managed=False` so Django doesn't claim ownership):

- **`circuits`** — shared catalog (API-imported + user-added). `source IN ('api', 'custom')`.
- **`trips`** — owned by user. `user_id` FK to `auth_user`.
- **`circuit_visits`** — owned by user. FK to `trips` and `circuits`. UNIQUE(trip_id, circuit_id, race_year).
- **`bucket_list`** — owned by user. FK to `circuits`. UNIQUE(user_id, circuit_id).

Per-user isolation is enforced in every SQL query via `WHERE <table>.user_id = %s`. Deletes use `WHERE id = %s AND user_id = %s` so a user can't delete another user's row even by guessing the id.

ERD lives at [`F1 Circuit Planner ERD.pdf`](F1%20Circuit%20Planner%20ERD.pdf).

---

## Local development setup

Prerequisites: Python 3.9+, PostgreSQL access (any host — Retool, local, AWS RDS, etc.).

```bash
# 1. Clone
git clone https://github.com/AnLe1504/test.git f1-circuit-journal
cd f1-circuit-journal

# 2. Virtual env
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# 3. Install
pip install -r requirements.txt

# 4. Environment variables
cp .env.example .env
# Edit .env: paste your DB credentials and generate a DJANGO_SECRET_KEY:
#   python -c "import secrets; print(secrets.token_urlsafe(50))"

# 5. Apply Django's built-in auth/admin/sessions migrations
python manage.py migrate

# 6. Add user_id columns to the user-owned tables (one-time, idempotent)
python manage.py dbshell < core/migrations/add_user_columns.sql

# 7. Create your first user
python manage.py createsuperuser

# 8. Run!
python manage.py runserver
# → http://127.0.0.1:8000
```

If `dbshell` fails because `psql` isn't on your PATH, run the SQL through Django's connection instead:

```bash
python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1journal.settings')
django.setup()
from django.db import connection
sql = open('core/migrations/add_user_columns.sql').read()
with connection.cursor() as cur:
    cur.execute(sql)
print('Migration applied.')
"
```

---

## Deployment notes (Railway)

Pushing to `main` triggers an auto-redeploy. Things worth knowing:

- **`Procfile`** binds gunicorn to `0.0.0.0:$PORT`. Don't override it via `railway.json` with `startCommand` — Railway runs that in exec form and `$PORT` won't expand.
- **`Dockerfile`** is the canonical builder; its `CMD` is shell-form so env vars expand correctly. The Procfile is a fallback.
- **Required env vars** in Railway → Variables:
  - `DJANGO_SECRET_KEY` (50 random chars; **not** the same as your dev one)
  - `ALLOWED_HOSTS` — your `*.up.railway.app` domain, comma-separated if multiple
  - `DEBUG=False` (or leave unset; settings default is `False` in prod)
  - `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- **First-time DB setup** — run `python manage.py migrate` (creates Django auth tables) and the `add_user_columns.sql` script once against the production Postgres. After that, Django's built-in `migrate` runs idempotently on each deploy if you ever wire it into the Procfile.
- **Static files** are collected at container start (`collectstatic --noinput` in the Dockerfile `CMD`) and served by Whitenoise — no S3 / CDN needed.
- **CSRF** in production needs `CSRF_TRUSTED_ORIGINS = ['https://<your-railway-host>']` (auto-derived from `ALLOWED_HOSTS` in `settings.py`).

---

## Reflection

### How I worked through the process

I converted a working Streamlit prototype into a production Django app and deployed it to Railway with login and multi-user data isolation. The Streamlit version was a single-user CRUD app on Postgres with four tables. I rebuilt it page by page (Home → My Trips → Circuit Explorer → Log a Visit → Bucket List → Manage Circuits), keeping the database schema untouched via Django's `managed=False`, so the database was never the risk during the conversion. After the six pages worked, I deployed to Railway, fixed the production-only bugs that don't surface in `manage.py runserver`, and then layered Django auth and per-user data isolation on top.

### What took the most time

The production-only bugs were the time sink. The `'$PORT' is not a valid port number` error from `railway.json` overriding the Dockerfile's `CMD` with exec form took three commits to diagnose and resolve. A duplicate `f1journal/f1journal/settings.py` left over from an early `django-admin startproject` misstep meant every fix to CSRF and DEBUG was landing on a dead file Django wasn't loading — two hours of "why isn't my change applying?" before I realized there were two settings files. The Circuit Explorer slide-in panel involved refactoring a server-rendered detail block into a JavaScript-fetched HTML fragment with Bootstrap modals that still work after dynamic injection. Per-user data isolation touched roughly fourteen raw-SQL queries, each needing `WHERE user_id = %s` plus `user_id` added to every INSERT.

### What I learned about Django

`managed=False` is the killer feature for converting legacy apps — Django coexists with the existing schema without claiming ownership. Raw SQL through `django.db.connection.cursor()` was the right tool for porting from a raw-SQL Streamlit codebase; the ORM isn't mandatory. Custom template tags (`star_rating`, `star_color_class`) handled display logic templates can't express inline. Django auth is genuinely batteries-included — `LoginView`, `LogoutView`, `UserCreationForm`, and `@login_required` together replaced what would have been hundreds of lines of session and CSRF code.

### What I learned about Railway

Railway auto-detects Dockerfile / Procfile / Nixpacks in that order, but `railway.json` can override the start command — and when it does, it runs in **exec form** with no shell, so `$PORT` doesn't expand. Pick one deploy config and delete the others. Environment variables are the deploy contract: typos like `ALLOWED_HOST` vs `ALLOWED_HOSTS` silently fall through to the default and break the site without an error. CSRF in production needs `CSRF_TRUSTED_ORIGINS` for HTTPS POSTs — easy to miss in dev because Django doesn't enforce it on `localhost`.

### Thoughts on this project

Streamlit is great for "does this idea work?"; Django is what you'd actually deploy. The 10× more code paid for real URLs, real auth, real users, real CSRF, and a real static-file pipeline. The hardest bugs were configuration, not logic — every code bug was caught in 10 minutes; every config bug took an hour. Next time I'd start with the production deploy on day one, not day six, and iterate against Railway from the beginning so config bugs surface early instead of all at once at the end.

---

## Credits

- Race calendar data: **[Jolpica F1 API](https://api.jolpi.ca/)** (free, no auth, Ergast-compatible)
- Circuit images and summaries: **[Wikipedia REST API](https://en.wikipedia.org/api/rest_v1/)**
- UI: **[Bootstrap 5](https://getbootstrap.com/)**
- Hosting: **[Railway](https://railway.app/)**
- Database hosting: **[Retool](https://retool.com/)** (PostgreSQL)
