import os
import sqlite3

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "prompts.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schemas", "sqlite.sql")


def get_connection(db_path=None):
    db_path = db_path or DEFAULT_DB_PATH
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Keep the repository database self-contained. WAL mode can leave committed
    # writes in sidecar files that are intentionally ignored by Git.
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize(db_path=None):
    conn = get_connection(db_path)
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


def reset(db_path=None):
    db_path = db_path or DEFAULT_DB_PATH
    if os.path.exists(db_path):
        os.remove(db_path)
    return initialize(db_path)
