#!/usr/bin/env python3
"""
migrate_to_two_table_schema.py

Safe migration script for Craig's glass database.

What it does:
- Opens your existing SQLite DB
- Creates glass_catalog and glass_measurements if missing
- Migrates data from glass_data into the two-table design
- Does NOT delete your original table
- Uses INSERT OR IGNORE to avoid duplicates

Usage:
    python migrate_to_two_table_schema.py --db data/glass_library.sqlite
"""

import sqlite3
import argparse
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="Path to SQLite database")
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    print(f"Opening DB: {db_path}")
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # Enable FK enforcement
    cur.execute("PRAGMA foreign_keys = ON;")

    # --- Create catalog table ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS glass_catalog (
        cat_id TEXT PRIMARY KEY,
        color_name TEXT,
        glass_family TEXT,
        is_striker INTEGER,
        se INTEGER,
        su INTEGER,
        cu INTEGER,
        pb INTEGER,
        ag INTEGER,
        au INTEGER,
        has_optical_data INTEGER
    );
    """)

    # --- Create measurements table ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS glass_measurements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cat_id TEXT,
        mode TEXT,
        R INTEGER,
        G INTEGER,
        B INTEGER,
        H INTEGER,
        S INTEGER,
        V INTEGER,
        FOREIGN KEY (cat_id) REFERENCES glass_catalog(cat_id)
    );
    """)

    print("Tables ensured. Migrating catalog data…")

    # --- Populate catalog (one row per cat_id) ---
    cur.execute("""
    INSERT OR IGNORE INTO glass_catalog (
        cat_id, color_name, glass_family, is_striker,
        se, su, cu, pb, ag, au, has_optical_data
    )
    SELECT
        cat_id,
        MAX(color_name),
        MAX(glass_family),
        MAX(is_striker),
        MAX(se),
        MAX(su),
        MAX(cu),
        MAX(pb),
        MAX(ag),
        MAX(au),
        MAX(has_optical_data)
    FROM glass_data
    GROUP BY cat_id;
    """)

    print("Migrating measurement rows…")

    # --- Populate measurements ---
    cur.execute("""
    INSERT INTO glass_measurements (
        cat_id, mode, R, G, B, H, S, V
    )
    SELECT
        cat_id, mode, R, G, B, H, S, V
    FROM glass_data
    WHERE mode IS NOT NULL;
    """)

    con.commit()
    con.close()

    print("Migration complete.")
    print("Original table glass_data was NOT modified.")

if __name__ == "__main__":
    main()
