# F1 Circuit Journal & Travel Planner


**F1 Circuit Journal & Travel Planner** is a personal tracking app that lets a user:

- **Log circuits they have visited** — with ratings, seating notes, ticket types, and personal memories
- **Plan upcoming race-weekend trips** — with date auto-fill from the F1 calendar, status tracking, and travel notes
- **Maintain a bucket list** of dream circuits — ranked by priority (Dream, Likely, Someday)
- **Explore all F1 circuits** — with color-coded status cards, Wikipedia enrichment, and Google search links for tourist and hotel planning

The app is backed by a PostgreSQL database with four tables and full CRUD support on every entity.

---

## Live App

[**→ Open the F1 Circuit Journal on Streamlit Community Cloud**](https://homepy-gvvusxvvcnecnwjomqdrvu.streamlit.app/)

---

## ERD

![ERD](/Users/anle/Documents/Gonzaga/Spring 26/MIS-444/Project 1/F1 Circuit Planner ERD.png)

---

## Table Descriptions

### `circuits` — The circuit catalogue

Every F1 circuit the user can interact with lives here. Circuits are seeded automatically from the OpenF1 API (marked `source = 'api'`) and are protected from deletion. Users can also add their own fictional or future circuits (`source = 'custom'`), which can be fully edited and deleted.

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL | Primary key |
| `name` | VARCHAR(100) | Circuit or Grand Prix name — required |
| `country` | VARCHAR(60) | Host country — required |
| `city` | VARCHAR(60) | Host city used for race-date lookup and explore links |
| `lap_length_km` | DECIMAL(5,3) | Lap length in km — sourced from hard-coded F1 data |
| `first_gp_year` | INTEGER | First year a Grand Prix was held at this circuit |
| `source` | VARCHAR(10) | `'api'` (seeded, protected) or `'custom'` (user-created) |
| `created_at` | TIMESTAMP | Row creation time |

---

### `trips` — Race-weekend travel plans

A trip is a user-created travel plan tied to one or more circuit visits. It has a name, date range, status, and optional notes. Trips are the top-level planning unit — circuits are linked to trips through the `circuit_visits` junction table.

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL | Primary key |
| `trip_name` | VARCHAR(120) | Descriptive name (e.g., "Monaco 2025 Weekend") — required |
| `start_date` | DATE | Trip start date — required |
| `end_date` | DATE | Trip end date — optional |
| `status` | VARCHAR(20) | `'planned'`, `'completed'`, or `'cancelled'` |
| `notes` | TEXT | Freeform travel notes (hotels, flights, tips) |
| `created_at` | TIMESTAMP | Row creation time |

---

### `circuit_visits` — Junction table (many-to-many)

This is the **junction table** connecting `trips` and `circuits` in a many-to-many relationship. A single trip can cover multiple circuits (e.g., a Europe trip visiting Monaco, Monza, and Spa). A single circuit can appear on multiple trips across different years (e.g., Monaco visited in 2023, 2024, and 2025). Beyond linking the two tables, this table also stores personal visit details — making it more than a pure bridge table.

Deleting a trip automatically deletes all of its visit rows (`ON DELETE CASCADE`).

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL | Primary key |
| `trip_id` | INTEGER FK | References `trips(id)` — cascades on delete |
| `circuit_id` | INTEGER FK | References `circuits(id)` |
| `race_year` | INTEGER | Year the race was (or will be) attended — required |
| `ticket_type` | VARCHAR(60) | e.g., General Admission, Grandstand T1 |
| `seating_section` | VARCHAR(80) | Specific seating area or section name |
| `personal_rating` | INTEGER | User rating 1–5 |
| `personal_notes` | TEXT | Memories, highlights, and tips for next time |
| `attended` | BOOLEAN | Whether the visit was physically attended (vs. planned) |
| `created_at` | TIMESTAMP | Row creation time |
| UNIQUE | — | `(trip_id, circuit_id, race_year)` — prevents duplicate entries |

---

### `bucket_list` — Dream circuits

A simple wish list of circuits the user has not visited yet but wants to. Each circuit can appear at most once (`UNIQUE(circuit_id)`). Entries are ranked by priority. Deleting a circuit from the catalogue automatically removes its bucket list entry (`ON DELETE CASCADE`).

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL | Primary key |
| `circuit_id` | INTEGER FK | References `circuits(id)` — cascades on delete |
| `priority` | VARCHAR(20) | `'dream'`, `'likely'`, or `'someday'` |
| `added_notes` | TEXT | Why this circuit is on the list |
| `created_at` | TIMESTAMP | Row creation time |
| UNIQUE | — | `(circuit_id)` — one entry per circuit |

---

## How to Run Locally

### Prerequisites
- Python 3.9 or higher
- Access to a PostgreSQL database (the app uses [Retool DB](https://retool.com/products/database) but any PostgreSQL instance works)

### Steps

**1. Clone the repository**
```bash
git clone https://github.com/your-username/your-repo-name.git
cd your-repo-name
```

**2. Create and activate a virtual environment**
```bash
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
.venv\Scripts\activate         # Windows
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

**4. Set up secrets**

Create the file `.streamlit/secrets.toml` in the project root. This file is listed in `.gitignore` and must never be committed to GitHub.

```toml
DB_URL      = "postgresql://user:password@host:port/dbname?sslmode=require"
RAPIDAPI_KEY = "your-rapidapi-key-here"
```

- `DB_URL` — your PostgreSQL connection string
- `RAPIDAPI_KEY` — from [RapidAPI](https://rapidapi.com) (used for the F1 race schedule endpoint)

**5. Seed the database** *(first run only)*
```bash
python seed_db.py
```
This creates all four tables and populates the `circuits` table with real F1 circuits from the OpenF1 API (2023–2025 seasons).

**6. Launch the app**
```bash
streamlit run Home.py
```
The app will open at `http://localhost:8501`.
