"""SQLite helpers: schema creation and seed data for the Coatings Diary app."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "coatings_diary.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS vessels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vessel_id INTEGER NOT NULL,
    job_number TEXT NOT NULL,
    area TEXT NOT NULL,
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
"""

SEED_VESSELS = ["Pangaea", "Fidelis", "Aegle", "Bundalong"]

# A couple of test jobs per vessel so the app has something to select on first run.
SEED_JOBS = [
    ("Pangaea", "24-0123", "Topsides"),
    ("Pangaea", "24-0123", "Transducers"),
    ("Fidelis", "24-0456", "Underwater Hull"),
    ("Aegle", "24-0789", "Topsides"),
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


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


def setup():
    """Called on app startup - safe to call every time."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    init_db()
    seed_db()
