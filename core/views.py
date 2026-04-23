from __future__ import annotations

from datetime import date
from django.db import connection, transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST

import urllib.parse
from collections import Counter

from .utils import (
    get_race_weekend_dates,
    get_race_info_for_city,
    fetch_wikipedia_summary,
    sort_circuits_by_race_date,
)


STATUS_OPTIONS = ["planned", "completed", "cancelled"]


def _fetchall(sql, params=()):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _fetchone(sql, params=()):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else None


def _fetchone_row(sql, params=()):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


# ─────────────────────────────────────────────────────────────────────────────
# HOME
# ─────────────────────────────────────────────────────────────────────────────
def home_view(request):
    total_visited = _fetchone(
        "SELECT COUNT(*) FROM circuit_visits WHERE attended = true;"
    ) or 0
    total_trips = _fetchone("SELECT COUNT(*) FROM trips;") or 0
    bucket_count = _fetchone("SELECT COUNT(*) FROM bucket_list;") or 0
    best_circuit = _fetchone("""
        SELECT c.name FROM circuit_visits cv
        JOIN circuits c ON c.id = cv.circuit_id
        WHERE cv.personal_rating IS NOT NULL
        GROUP BY c.id, c.name
        ORDER BY AVG(cv.personal_rating) DESC LIMIT 1;
    """)

    recent_visits = _fetchall("""
        SELECT c.name AS circuit, t.trip_name AS trip,
               cv.race_year AS year, cv.personal_rating AS rating,
               cv.attended AS attended
        FROM circuit_visits cv
        JOIN circuits c ON c.id = cv.circuit_id
        JOIN trips    t ON t.id = cv.trip_id
        ORDER BY cv.created_at DESC LIMIT 5;
    """)
    for r in recent_visits:
        r['rating_pct'] = int((r['rating'] or 0) * 20)

    next_trip_rows = _fetchall("""
        SELECT trip_name, start_date, end_date, status, notes
        FROM trips
        WHERE status = 'planned' AND start_date >= CURRENT_DATE
        ORDER BY start_date ASC LIMIT 1;
    """)
    next_trip = next_trip_rows[0] if next_trip_rows else None

    return render(request, 'core/home.html', {
        'total_visited': total_visited,
        'total_trips': total_trips,
        'bucket_count': bucket_count,
        'best_circuit': best_circuit or '—',
        'recent_visits': recent_visits,
        'next_trip': next_trip,
        'today': date.today(),
    })


# ─────────────────────────────────────────────────────────────────────────────
# TRIPS — list + add
# ─────────────────────────────────────────────────────────────────────────────
def trips_list(request):
    if request.method == "POST":
        return _trip_add(request)

    circuits = _fetchall("SELECT id, name, city, country FROM circuits ORDER BY name;")

    trips = _fetchall("""
        SELECT
            t.id, t.trip_name, t.start_date, t.end_date, t.status, t.notes,
            COUNT(cv.id) AS visit_count,
            MIN(c.city)    AS first_city,
            MIN(c.country) AS first_country
        FROM trips t
        LEFT JOIN circuit_visits cv ON cv.trip_id  = t.id
        LEFT JOIN circuits       c  ON c.id        = cv.circuit_id
        GROUP BY t.id
        ORDER BY t.start_date DESC NULLS LAST;
    """)

    import urllib.parse
    for t in trips:
        if t.get('first_city'):
            q_attractions = urllib.parse.quote(f"{t['first_city']} tourist attractions")
            q_hotels = urllib.parse.quote(f"hotels in {t['first_city']}")
            t['attractions_url'] = f"https://www.google.com/search?q={q_attractions}"
            t['hotels_url'] = f"https://www.google.com/search?q={q_hotels}"

    return render(request, 'core/trips.html', {
        'circuits': circuits,
        'trips': trips,
        'status_options': STATUS_OPTIONS,
        'today': date.today(),
    })


def _parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _trip_add(request):
    trip_name = (request.POST.get('trip_name') or '').strip()
    start_date = _parse_date(request.POST.get('start_date'))
    end_date = _parse_date(request.POST.get('end_date'))
    status = request.POST.get('status') or 'planned'
    notes = (request.POST.get('notes') or '').strip() or None
    circuit_id = request.POST.get('circuit_id') or None

    if not trip_name:
        messages.error(request, "Trip Name is required.")
        return redirect('trips_list')
    if not start_date:
        messages.error(request, "Start Date is required.")
        return redirect('trips_list')
    if end_date and end_date < start_date:
        messages.error(request, "End Date must be on or after Start Date.")
        return redirect('trips_list')
    if status not in STATUS_OPTIONS:
        return HttpResponseBadRequest("Invalid status.")

    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(
                "INSERT INTO trips (trip_name, start_date, end_date, status, notes) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id;",
                (trip_name, start_date, end_date, status, notes),
            )
            new_trip_id = cur.fetchone()[0]
            if circuit_id:
                cur.execute(
                    """
                    INSERT INTO circuit_visits (trip_id, circuit_id, race_year, attended)
                    VALUES (%s, %s, %s, false)
                    ON CONFLICT (trip_id, circuit_id, race_year) DO NOTHING;
                    """,
                    (new_trip_id, int(circuit_id), start_date.year),
                )
        messages.success(request, f"Trip '{trip_name}' added!")
    except Exception as e:
        messages.error(request, f"Database error: {e}")
    return redirect('trips_list')


@require_POST
def trip_edit(request, trip_id):
    trip_name = (request.POST.get('trip_name') or '').strip()
    start_date = _parse_date(request.POST.get('start_date'))
    end_date = _parse_date(request.POST.get('end_date'))
    status = request.POST.get('status') or 'planned'
    notes = (request.POST.get('notes') or '').strip() or None
    circuit_id = request.POST.get('circuit_id') or None

    if not trip_name:
        messages.error(request, "Trip Name is required.")
        return redirect('trips_list')
    if not start_date:
        messages.error(request, "Start Date is required.")
        return redirect('trips_list')
    if end_date and end_date < start_date:
        messages.error(request, "End Date must be on or after Start Date.")
        return redirect('trips_list')
    if status not in STATUS_OPTIONS:
        return HttpResponseBadRequest("Invalid status.")

    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(
                "UPDATE trips SET trip_name=%s, start_date=%s, end_date=%s, "
                "status=%s, notes=%s WHERE id=%s;",
                (trip_name, start_date, end_date, status, notes, trip_id),
            )
            if circuit_id:
                cur.execute(
                    """
                    INSERT INTO circuit_visits (trip_id, circuit_id, race_year, attended)
                    VALUES (%s, %s, %s, false)
                    ON CONFLICT (trip_id, circuit_id, race_year) DO NOTHING;
                    """,
                    (trip_id, int(circuit_id), start_date.year),
                )
        messages.success(request, "Trip updated!")
    except Exception as e:
        messages.error(request, f"Database error: {e}")
    return redirect('trips_list')


@require_POST
def trip_delete(request, trip_id):
    try:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM trips WHERE id = %s;", (trip_id,))
        messages.success(request, "Trip deleted.")
    except Exception as e:
        messages.error(request, f"Database error: {e}")
    return redirect('trips_list')


def race_dates_api(request):
    """JSON endpoint: given a circuit city, return race-weekend (start, end)."""
    city = request.GET.get('city', '')
    start, end = get_race_weekend_dates(city)
    return JsonResponse({
        'start': start.isoformat() if start else None,
        'end': end.isoformat() if end else None,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# CIRCUIT EXPLORER
# ═══════════════════════════════════════════════════════════════════════════════

SORT_OPTIONS = {
    "upcoming":   ("Upcoming Race",  "c.name"),
    "country":    ("Country",        "c.country, c.name"),
    "name":       ("Name",           "c.name"),
    "avg_rating": ("Avg Rating",     "avg_rating DESC NULLS LAST"),
    "date_added": ("Date Added",     "c.created_at DESC"),
}

STATUS_FILTERS = ["All", "Visited", "Not Visited", "On Bucket List", "Planned Trip", "Custom"]

PRIORITY_OPTS = [("dream", "🏆 Dream"), ("likely", "🎯 Likely"), ("someday", "📅 Someday")]


def _card_color(row: dict) -> tuple[str, str]:
    if (row.get("visit_count") or 0) > 0:     return "#14b8a6", "Visited"
    if row.get("trip_planned"):               return "#3b82f6", "Planned Trip"
    if row.get("source") == "custom":         return "#f59e0b", "Custom"
    if row.get("on_bucket_list"):             return "#ef4444", "Bucket List"
    return "#64748b", "Not Visited"


def circuit_list(request):
    today = date.today()

    search = (request.GET.get("q") or "").strip()
    country = request.GET.get("country") or "All Countries"
    year = request.GET.get("year") or "All Years"
    sort = request.GET.get("sort") or "name"
    status = request.GET.get("status") or "All"
    selected_id = request.GET.get("circuit")
    try:
        selected_id = int(selected_id) if selected_id else None
    except ValueError:
        selected_id = None

    # Filter option data
    countries = ["All Countries"] + [
        r["country"] for r in _fetchall(
            "SELECT DISTINCT country FROM circuits ORDER BY country;"
        )
    ]
    years = ["All Years"] + [
        str(r["race_year"]) for r in _fetchall(
            "SELECT DISTINCT race_year FROM circuit_visits "
            "WHERE race_year IS NOT NULL ORDER BY race_year DESC;"
        )
    ]

    # Build main query
    conditions, params = [], []
    if search:
        conditions.append("(c.name ILIKE %s OR c.country ILIKE %s)")
        params += [f"%{search}%"] * 2
    if country != "All Countries":
        conditions.append("c.country = %s")
        params.append(country)
    if year != "All Years":
        conditions.append("cv.race_year = %s")
        try:
            params.append(int(year))
        except ValueError:
            pass

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sort_sql = SORT_OPTIONS.get(sort, SORT_OPTIONS["name"])[1]
    if sort == "upcoming":
        sort_sql = "c.name"

    sql = f"""
        SELECT c.id, c.name, c.country, c.city, c.lap_length_km,
               c.first_gp_year, c.source, c.created_at,
               COUNT(DISTINCT cv.id) FILTER (WHERE cv.attended = true) AS visit_count,
               ROUND(AVG(cv.personal_rating), 1)                       AS avg_rating,
               MAX(CASE WHEN bl.circuit_id IS NOT NULL THEN 1 ELSE 0 END)                         AS on_bucket_list,
               MAX(CASE WHEN t.status = 'planned' AND cv.attended = false THEN 1 ELSE 0 END)      AS trip_planned
        FROM circuits c
        LEFT JOIN circuit_visits cv ON cv.circuit_id = c.id
        LEFT JOIN trips          t  ON cv.trip_id    = t.id
        LEFT JOIN bucket_list    bl ON bl.circuit_id = c.id
        {where_clause}
        GROUP BY c.id
        ORDER BY {sort_sql};
    """
    rows = _fetchall(sql, tuple(params))

    # Status filter (post-query)
    status_pred = {
        "Visited":        lambda r: (r["visit_count"] or 0) > 0,
        "Not Visited":    lambda r: (r["visit_count"] or 0) == 0,
        "On Bucket List": lambda r: bool(r["on_bucket_list"]),
        "Planned Trip":   lambda r: bool(r["trip_planned"]),
        "Custom":         lambda r: r["source"] == "custom",
    }
    if status in status_pred:
        rows = [r for r in rows if status_pred[status](r)]

    if sort == "upcoming":
        rows = sort_circuits_by_race_date(rows)

    # Enrich each card with color + race info
    for r in rows:
        color, label = _card_color(r)
        r["color"] = color
        r["status_label"] = label
        info = get_race_info_for_city(r.get("city") or "", today.year)
        if info and info.get("date"):
            rd = info["date"]
            r["race_date"] = rd
            delta = (rd - today).days
            if delta > 0:
                r["race_countdown"] = f"🏁 {rd.strftime('%b %d, %Y')} · {delta}d away"
            elif delta == 0:
                r["race_countdown"] = f"🏁 {rd.strftime('%b %d, %Y')} · TODAY"
            else:
                r["race_countdown"] = f"🏁 {rd.strftime('%b %d, %Y')} (past)"
        r["avg_rating_pct"] = int((float(r["avg_rating"]) if r["avg_rating"] else 0) * 20)

    # Detail panel data
    detail = None
    if selected_id:
        detail = _build_detail(selected_id, today)

    ctx = {
        "today": today,
        "countries": countries,
        "years": years,
        "sort_options": [(k, v[0]) for k, v in SORT_OPTIONS.items()],
        "status_filters": STATUS_FILTERS,
        "circuits": rows,
        "count": len(rows),
        "filters": {
            "q": search, "country": country, "year": year,
            "sort": sort, "status": status,
        },
        "selected_id": selected_id,
        "detail": detail,
        "priority_opts": PRIORITY_OPTS,
    }
    return render(request, "core/circuits.html", ctx)


def _build_detail(circuit_id: int, today: date) -> dict | None:
    cinfo = _fetchone_row(
        "SELECT id, name, country, city, lap_length_km, first_gp_year, source "
        "FROM circuits WHERE id = %s;", (circuit_id,)
    )
    if not cinfo:
        return None

    visits = _fetchall(
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
    for v in visits:
        v["rating_pct"] = int((v["personal_rating"] or 0) * 20)

    on_bucket = _fetchone(
        "SELECT 1 FROM bucket_list WHERE circuit_id = %s LIMIT 1;", (circuit_id,)
    ) is not None

    wiki = fetch_wikipedia_summary(cinfo["name"])
    # Trim extract to 3 sentences
    if wiki.get("extract"):
        parts = wiki["extract"].split(". ")
        wiki = dict(wiki)
        wiki["extract"] = ". ".join(parts[:3]) + ("." if len(parts) > 3 else "")

    race_info = get_race_info_for_city(cinfo.get("city") or "", today.year)
    next_race = None
    if race_info and race_info.get("date"):
        rd = race_info["date"]
        delta = (rd - today).days
        next_race = {
            "date": rd, "days": delta, "upcoming": delta >= 0,
            "label": rd.strftime("%B %d, %Y"),
        }

    attended = [v for v in visits if v["attended"]]
    rated = [v for v in visits if v["personal_rating"]]
    seats = [v["seating_section"] for v in visits if v["seating_section"]]
    tickets = [v["ticket_type"] for v in visits if v["ticket_type"]]
    avg_r = round(sum(v["personal_rating"] for v in rated) / len(rated), 1) if rated else None

    summary = {
        "attended": len(attended),
        "avg_rating": avg_r,
        "avg_rating_pct": int((avg_r or 0) * 20),
        "fav_seat": Counter(seats).most_common(1)[0][0] if seats else "—",
        "fav_ticket": Counter(tickets).most_common(1)[0][0] if tickets else "—",
    }

    city = cinfo.get("city") or ""
    country = cinfo.get("country") or ""
    explore = None
    if city:
        q_att = urllib.parse.quote(f"{city} {country} tourist attractions")
        q_ht = urllib.parse.quote(f"hotels in {city} {country}")
        explore = {
            "attractions_url": f"https://www.google.com/search?q={q_att}",
            "hotels_url": f"https://www.google.com/search?q={q_ht}",
        }

    # Data for the visit edit modal selects
    all_trips = _fetchall(
        "SELECT id, trip_name, start_date FROM trips ORDER BY start_date DESC;"
    )
    all_circuits = _fetchall("SELECT id, name, country FROM circuits ORDER BY name;")

    return {
        "circuit": cinfo,
        "visits": visits,
        "on_bucket": on_bucket,
        "wiki": wiki,
        "next_race": next_race,
        "summary": summary,
        "explore": explore,
        "all_trips": all_trips,
        "all_circuits": all_circuits,
    }


@require_POST
def bucket_add(request):
    circuit_id = request.POST.get("circuit_id")
    priority = request.POST.get("priority") or "someday"
    notes = (request.POST.get("notes") or "").strip() or None
    if not circuit_id:
        return HttpResponseBadRequest("Missing circuit_id.")
    valid = {p[0] for p in PRIORITY_OPTS}
    if priority not in valid:
        return HttpResponseBadRequest("Invalid priority.")
    try:
        exists = _fetchone(
            "SELECT 1 FROM bucket_list WHERE circuit_id = %s LIMIT 1;", (circuit_id,)
        )
        if exists:
            messages.error(request, "This circuit is already on your bucket list!")
        else:
            with connection.cursor() as cur:
                cur.execute(
                    "INSERT INTO bucket_list (circuit_id, priority, added_notes) "
                    "VALUES (%s, %s, %s);",
                    (int(circuit_id), priority, notes),
                )
            messages.success(request, "Added to bucket list!")
    except Exception as e:
        messages.error(request, f"Database error: {e}")
    nxt = request.POST.get("next") or ""
    if nxt.startswith("/"):
        return redirect(nxt)
    return redirect(f"/circuits/?circuit={circuit_id}")


def _visit_redirect(request, circuit_id):
    nxt = request.POST.get("next") or ""
    if nxt.startswith("/"):
        return redirect(nxt)
    if circuit_id:
        return redirect(f"/circuits/?circuit={circuit_id}")
    return redirect("/circuits/")


@require_POST
def visit_edit(request, visit_id):
    trip_id = request.POST.get("trip_id")
    circuit_id = request.POST.get("circuit_id")
    race_year = request.POST.get("race_year")
    ticket = (request.POST.get("ticket_type") or "").strip() or None
    seat = (request.POST.get("seating_section") or "").strip() or None
    rating_raw = request.POST.get("personal_rating") or ""
    notes = (request.POST.get("personal_notes") or "").strip() or None
    attended = request.POST.get("attended") == "on"

    try:
        rating = int(rating_raw) if rating_raw else None
        if rating is not None and (rating < 1 or rating > 5):
            rating = None
        year_i = int(race_year)
    except (ValueError, TypeError):
        messages.error(request, "Year and rating must be numeric.")
        return _visit_redirect(request, circuit_id)

    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT id FROM circuit_visits "
                "WHERE trip_id=%s AND circuit_id=%s AND race_year=%s AND id != %s;",
                (trip_id, circuit_id, year_i, visit_id),
            )
            if cur.fetchone():
                messages.error(request, "A duplicate visit already exists.")
            else:
                cur.execute(
                    "UPDATE circuit_visits SET trip_id=%s, circuit_id=%s, race_year=%s, "
                    "ticket_type=%s, seating_section=%s, personal_rating=%s, "
                    "personal_notes=%s, attended=%s WHERE id=%s;",
                    (trip_id, circuit_id, year_i, ticket, seat,
                     rating, notes, attended, visit_id),
                )
                messages.success(request, "Visit updated!")
    except Exception as e:
        messages.error(request, f"Database error: {e}")
    return _visit_redirect(request, circuit_id)


@require_POST
def visit_delete(request, visit_id):
    circuit_id = request.POST.get("circuit_id") or ""
    try:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM circuit_visits WHERE id = %s;", (visit_id,))
        messages.success(request, "Visit deleted.")
    except Exception as e:
        messages.error(request, f"Database error: {e}")
    return _visit_redirect(request, circuit_id)


# ═══════════════════════════════════════════════════════════════════════════════
# LOG A VISIT
# ═══════════════════════════════════════════════════════════════════════════════
def visits_list(request):
    if request.method == "POST":
        return _visit_add(request)

    trips = _fetchall(
        "SELECT id, trip_name, start_date FROM trips ORDER BY start_date DESC;"
    )
    circuits = _fetchall(
        "SELECT id, name, country, city FROM circuits ORDER BY name;"
    )

    prefill_cid = None
    try:
        if request.GET.get("circuit_id"):
            prefill_cid = int(request.GET["circuit_id"])
    except ValueError:
        prefill_cid = None

    visits = _fetchall("""
        SELECT cv.id, c.name AS circuit, c.city, c.country,
               t.trip_name AS trip, t.start_date AS trip_date,
               cv.trip_id, cv.circuit_id,
               cv.race_year, cv.ticket_type, cv.seating_section,
               cv.personal_rating, cv.attended, cv.personal_notes
        FROM circuit_visits cv
        JOIN circuits c ON c.id = cv.circuit_id
        JOIN trips    t ON t.id = cv.trip_id
        ORDER BY cv.race_year DESC, c.name;
    """)
    for v in visits:
        v["rating_pct"] = int((v["personal_rating"] or 0) * 20)

    return render(request, "core/log_visit.html", {
        "trips": trips,
        "circuits": circuits,
        "visits": visits,
        "prefill_cid": prefill_cid,
        "today": date.today(),
        "current_year": date.today().year,
    })


def _visit_add(request):
    trip_id = request.POST.get("trip_id")
    circuit_id = request.POST.get("circuit_id")
    race_year = request.POST.get("race_year")
    ticket = (request.POST.get("ticket_type") or "").strip() or None
    seat = (request.POST.get("seating_section") or "").strip() or None
    rating_raw = request.POST.get("personal_rating") or ""
    notes = (request.POST.get("personal_notes") or "").strip() or None
    attended = request.POST.get("attended") == "on"

    try:
        year_i = int(race_year)
        rating = int(rating_raw) if rating_raw else None
        if rating is not None and (rating < 1 or rating > 5):
            rating = None
    except (ValueError, TypeError):
        messages.error(request, "Year and rating must be numeric.")
        return redirect("visits_list")

    current_year = date.today().year
    if not trip_id or not circuit_id:
        messages.error(request, "Trip and Circuit are required.")
        return redirect("visits_list")
    if year_i < 1950 or year_i > current_year + 2:
        messages.error(request, f"Race Year must be between 1950 and {current_year + 2}.")
        return redirect("visits_list")

    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT id FROM circuit_visits "
                "WHERE trip_id=%s AND circuit_id=%s AND race_year=%s;",
                (trip_id, circuit_id, year_i),
            )
            if cur.fetchone():
                messages.error(
                    request,
                    "You already logged this circuit + trip + year. "
                    "Use Edit below to update it.",
                )
                return redirect("visits_list")
            cur.execute(
                """
                INSERT INTO circuit_visits
                    (trip_id, circuit_id, race_year, ticket_type,
                     seating_section, personal_rating, personal_notes, attended)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (trip_id, circuit_id, year_i, ticket, seat, rating, notes, attended),
            )
        messages.success(request, "Visit logged!")
    except Exception as e:
        messages.error(request, f"Database error: {e}")
    return redirect("visits_list")


def bucket_list(request):
    available = _fetchall("""
        SELECT id, name, country FROM circuits
        WHERE id NOT IN (SELECT circuit_id FROM bucket_list)
        ORDER BY name;
    """)
    rows = _fetchall("""
        SELECT
            bl.id AS bl_id,
            bl.priority,
            bl.added_notes,
            bl.created_at,
            c.id AS circuit_id,
            c.name AS circuit_name,
            c.country,
            c.city,
            EXISTS (
                SELECT 1 FROM circuit_visits cv
                WHERE cv.circuit_id = c.id AND cv.attended = true
            ) AS already_visited
        FROM bucket_list bl
        JOIN circuits c ON c.id = bl.circuit_id
        ORDER BY
            CASE bl.priority
                WHEN 'dream' THEN 1
                WHEN 'likely' THEN 2
                WHEN 'someday' THEN 3
            END,
            bl.created_at ASC;
    """)

    tiers = [
        ("dream", "🏆 Dream", []),
        ("likely", "🎯 Likely", []),
        ("someday", "📅 Someday", []),
    ]
    tier_map = {t[0]: t[2] for t in tiers}
    for r in rows:
        city = r.get("city") or ""
        country = r.get("country") or ""
        if city:
            q_attr = urllib.parse.quote(f"{city} {country} attractions")
            q_hot = urllib.parse.quote(f"hotels in {city} {country}")
            r["attractions_url"] = f"https://www.google.com/search?q={q_attr}"
            r["hotels_url"] = f"https://www.google.com/search?q={q_hot}"
        else:
            r["attractions_url"] = ""
            r["hotels_url"] = ""
        tier_map.get(r["priority"], []).append(r)

    return render(request, "core/bucket_list.html", {
        "available": available,
        "tiers": tiers,
        "has_entries": bool(rows),
        "priority_opts": PRIORITY_OPTS,
    })


@require_POST
def bucket_remove(request, bl_id):
    try:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM bucket_list WHERE id = %s;", (bl_id,))
        messages.success(request, "Removed from bucket list.")
    except Exception as e:
        messages.error(request, f"Database error: {e}")
    return redirect("bucket_list")


def _validate_circuit_form(post):
    name = (post.get("name") or "").strip()
    country = (post.get("country") or "").strip()
    city = (post.get("city") or "").strip() or None
    lap_raw = (post.get("lap_length_km") or "").strip()
    year_raw = (post.get("first_gp_year") or "").strip()
    errors = []
    if not name:
        errors.append("Circuit Name is required.")
    if not country:
        errors.append("Country is required.")
    lap_val = None
    if lap_raw:
        try:
            lap_f = float(lap_raw)
            if lap_f < 0:
                errors.append("Lap Length must be a positive number.")
            elif lap_f > 0:
                lap_val = lap_f
        except ValueError:
            errors.append("Lap Length must be a number.")
    year_val = None
    if year_raw:
        try:
            year_i = int(year_raw)
            if year_i > 0:
                year_val = year_i
        except ValueError:
            errors.append("First GP Year must be a number.")
    return name, country, city, lap_val, year_val, errors


def circuit_manage(request):
    if request.method == "POST":
        name, country, city, lap_val, year_val, errors = _validate_circuit_form(request.POST)
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            try:
                with connection.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO circuits
                            (name, country, city, lap_length_km, first_gp_year, source)
                        VALUES (%s, %s, %s, %s, %s, 'custom');
                        """,
                        (name, country, city, lap_val, year_val),
                    )
                messages.success(request, f"Circuit {name} added!")
            except Exception as e:
                messages.error(request, f"Database error: {e}")
        return redirect("circuit_manage")

    search = (request.GET.get("q") or "").strip()
    if search:
        like = f"%{search}%"
        rows = _fetchall(
            """
            SELECT id, name, country, city, lap_length_km, first_gp_year, source
            FROM circuits
            WHERE name ILIKE %s OR country ILIKE %s
            ORDER BY name;
            """,
            (like, like),
        )
    else:
        rows = _fetchall(
            """
            SELECT id, name, country, city, lap_length_km, first_gp_year, source
            FROM circuits ORDER BY name;
            """
        )
    for r in rows:
        r["is_custom"] = r["source"] == "custom"
        r["lap_display"] = f"{float(r['lap_length_km']):.3f}" if r.get("lap_length_km") else "—"
        r["first_gp_display"] = str(r["first_gp_year"]) if r.get("first_gp_year") else "—"
        r["lap_input"] = f"{float(r['lap_length_km']):.3f}" if r.get("lap_length_km") else ""
    return render(request, "core/manage_circuits.html", {
        "circuits": rows,
        "search": search,
        "count": len(rows),
        "current_year": date.today().year,
    })


@require_POST
def circuit_edit(request, circuit_id):
    name, country, city, lap_val, year_val, errors = _validate_circuit_form(request.POST)
    if errors:
        for e in errors:
            messages.error(request, e)
    else:
        try:
            with connection.cursor() as cur:
                cur.execute(
                    """
                    UPDATE circuits
                    SET name = %s, country = %s, city = %s,
                        lap_length_km = %s, first_gp_year = %s
                    WHERE id = %s;
                    """,
                    (name, country, city, lap_val, year_val, circuit_id),
                )
            messages.success(request, "Circuit updated!")
        except Exception as e:
            messages.error(request, f"Database error: {e}")
    return redirect("circuit_manage")


@require_POST
def circuit_delete(request, circuit_id):
    try:
        with connection.cursor() as cur:
            cur.execute(
                "DELETE FROM circuits WHERE id = %s AND source = 'custom';",
                (circuit_id,),
            )
            deleted = cur.rowcount
        if deleted:
            messages.success(request, "Circuit deleted.")
        else:
            messages.error(request, "Cannot delete — API circuits are protected.")
    except Exception as e:
        messages.error(request, f"Database error: {e}")
    return redirect("circuit_manage")
