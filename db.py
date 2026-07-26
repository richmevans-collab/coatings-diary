"""SQLite helpers: schema creation and seed data for the Coatings Diary app."""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "coatings_diary.db"

# jobs.area is nullable: Coatings Diary entries use it (e.g. "Topsides"), but
# jobs created via the Request Work module represent a whole job rather than
# one paintable area, so they leave it blank and rely on job_title instead.
SCHEMA = """
CREATE TABLE IF NOT EXISTS vessels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vessel_id INTEGER NOT NULL,
    job_number TEXT NOT NULL,
    area TEXT,
    job_title TEXT,
    scope TEXT,
    status TEXT NOT NULL DEFAULT 'Open',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (vessel_id) REFERENCES vessels(id)
);

CREATE TABLE IF NOT EXISTS coating_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    humidity REAL,
    air_temp REAL,
    surface_temp REAL,
    dew_point REAL,
    product_name TEXT,
    wft REAL,
    tin_photo_filename TEXT,
    coat_number INTEGER,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS work_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vessel_id INTEGER NOT NULL,
    request_type TEXT NOT NULL,
    job_id INTEGER,
    job_title TEXT,
    description TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    requested_by_contact TEXT,
    reason TEXT NOT NULL,
    estimated_cost REAL,
    status TEXT NOT NULL DEFAULT 'Pending',
    pm_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    reviewed_at TEXT,
    FOREIGN KEY (vessel_id) REFERENCES vessels(id),
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS boat_builder_estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    vessel_id INTEGER NOT NULL,
    description TEXT,
    materials_cost REAL,
    total_cost REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'Submitted',
    submitted_by TEXT NOT NULL,
    submitted_date TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    reviewed_by TEXT,
    review_notes TEXT,
    review_date TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id),
    FOREIGN KEY (vessel_id) REFERENCES vessels(id)
);

CREATE TABLE IF NOT EXISTS boat_builder_labor_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    estimate_id INTEGER NOT NULL,
    trade_role TEXT NOT NULL,
    num_workers INTEGER NOT NULL,
    num_days INTEGER NOT NULL,
    worker_days INTEGER NOT NULL,
    FOREIGN KEY (estimate_id) REFERENCES boat_builder_estimates(id)
);

CREATE TABLE IF NOT EXISTS equipment_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit TEXT NOT NULL,
    standard_rate REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

-- equipment_name is a denormalized copy of the catalog name at the time of
-- logging (not a FK) so history stays accurate even if catalog rates/names
-- change later.
CREATE TABLE IF NOT EXISTS consumables_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vessel_id INTEGER NOT NULL,
    equipment_name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT,
    quantity REAL NOT NULL DEFAULT 1,
    unit TEXT,
    cost_per_unit REAL NOT NULL,
    total_cost REAL NOT NULL,
    notes TEXT,
    logged_by TEXT,
    logged_date TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (vessel_id) REFERENCES vessels(id)
);
"""

REQUEST_REASONS = ["New Work", "Design Change", "Damage Found", "Clarification", "Other"]
TRADE_ROLES = ["Boat Builder", "Apprentice", "Fabricator", "Finisher", "Other"]

SEED_VESSELS = ["Pangaea", "Fidelis", "Aegle", "Bundalong"]

# A couple of test jobs per vessel so the app has something to select on first run.
SEED_JOBS = [
    ("Pangaea", "24-0123", "Topsides"),
    ("Pangaea", "24-0123", "Transducers"),
    ("Fidelis", "24-0456", "Underwater Hull"),
    ("Aegle", "24-0789", "Topsides"),
]

# Standard rates are placeholders (NZD) - editable by admin once a real rate
# card exists; nothing here is load-bearing except unit/category grouping.
SEED_EQUIPMENT = [
    ("Scissor Lift", "Daily Rentals", "day", 180.0),
    ("Forklift", "Daily Rentals", "day", 220.0),
    ("Scaffolding", "Daily Rentals", "day", 150.0),
    ("Confined Space Equipment", "Daily Rentals", "day", 120.0),
    ("On-Site Storage", "Storage", "sqm/day", 5.0),
    ("Off-Site Storage", "Storage", "sqm/day", 8.0),
    ("Electrical Box Rental", "Electrical & Power", "day", 45.0),
    ("Power Lead Rental", "Electrical & Power", "day", 15.0),
    ("Generator", "Electrical & Power", "day", 95.0),
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate_jobs_table(conn):
    """Upgrade an existing (pre-Request-Work-module) jobs table in place.

    The original Coatings Diary schema had jobs(id, vessel_id, job_number,
    area NOT NULL). Request Work needs job_title/scope/status/timestamps and
    area to be nullable (a job created from a work request has no single
    "area" until a painter logs against it), so on an old DB we rebuild the
    table and copy rows across rather than editing the live one.
    """
    columns = [row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    if not columns or "job_title" in columns:
        return  # fresh DB (SCHEMA below will create it) or already migrated

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("ALTER TABLE jobs RENAME TO jobs_old")
    conn.executescript("""
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vessel_id INTEGER NOT NULL,
            job_number TEXT NOT NULL,
            area TEXT,
            job_title TEXT,
            scope TEXT,
            status TEXT NOT NULL DEFAULT 'Open',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (vessel_id) REFERENCES vessels(id)
        );
    """)
    conn.execute("""
        INSERT INTO jobs (id, vessel_id, job_number, area)
        SELECT id, vessel_id, job_number, area FROM jobs_old
    """)
    conn.execute("DROP TABLE jobs_old")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()


def init_db():
    conn = get_db()
    migrate_jobs_table(conn)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def generate_job_number(conn, year=None):
    """Next sequential JOB-YYYY-NNN for the given (default: current) year."""
    year = year or datetime.now().year
    prefix = f"JOB-{year}-"
    rows = conn.execute(
        "SELECT job_number FROM jobs WHERE job_number LIKE ?", (f"{prefix}%",)
    ).fetchall()
    max_n = 0
    for row in rows:
        suffix = row["job_number"][len(prefix):]
        if suffix.isdigit():
            max_n = max(max_n, int(suffix))
    return f"{prefix}{max_n + 1:03d}"


def seed_db():
    """Only seeds if the vessels table is empty, so re-runs are safe."""
    conn = get_db()
    existing = conn.execute("SELECT COUNT(*) FROM vessels").fetchone()[0]
    if existing == 0:
        vessel_ids = {}
        for name in SEED_VESSELS:
            cur = conn.execute("INSERT INTO vessels (name) VALUES (?)", (name,))
            vessel_ids[name] = cur.lastrowid
        for vessel_name, job_number, area in SEED_JOBS:
            conn.execute(
                "INSERT INTO jobs (vessel_id, job_number, area) VALUES (?, ?, ?)",
                (vessel_ids[vessel_name], job_number, area),
            )
        conn.commit()
    conn.close()


def seed_equipment_catalog():
    """Only seeds if the catalog is empty, so re-runs are safe."""
    conn = get_db()
    existing = conn.execute("SELECT COUNT(*) FROM equipment_catalog").fetchone()[0]
    if existing == 0:
        for equipment_name, category, unit, standard_rate in SEED_EQUIPMENT:
            conn.execute(
                """INSERT INTO equipment_catalog (equipment_name, category, unit, standard_rate)
                   VALUES (?, ?, ?, ?)""",
                (equipment_name, category, unit, standard_rate),
            )
        conn.commit()
    conn.close()


def setup():
    """Called on app startup - safe to call every time."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    init_db()
    seed_db()
    seed_equipment_catalog()
