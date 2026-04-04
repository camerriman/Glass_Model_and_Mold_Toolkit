#!/usr/bin/env python3
"""
migrate_to_two_table_schema_v2.py

Creates a two-table schema in an existing SQLite database and migrates data from an
existing "source" table.

- Creates:
    glass_catalog (one row per cat_id)
    glass_measurements (many rows per cat_id, mode)

- Does NOT delete or modify the source table.
- Auto-detects the source table name (glass_data or glass_samples) unless provided.

Run:
    python3 migrate_to_two_table_schema_v2.py --db data/glass_library.sqlite
Optional:
    python3 migrate_to_two_table_schema_v2.py --db data/glass_library.sqlite --src glass_samples
"""

import argparse
import sqlite3
from pathlib import Path

CANDIDATE_SRC_TABLES = ("glass_data", "glass_samples")

def qident(name: str) -> str:
    # Safe SQLite identifier quoting
    return '"' + name.replace('"', '""') + '"'

def get_tables(cur) -> list[str]:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    return [r[0] for r in cur.fetchall()]

def table_columns(cur, table: str) -> list[str]:
    cur.execute(f"PRAGMA table_info({qident(table)});")
    return [r[1] for r in cur.fetchall()]

def pick_first(cols: list[str], *options: str) -> str | None:
    lower = {c.lower(): c for c in cols}
    for opt in options:
        if opt.lower() in lower:
            return lower[opt.lower()]
    return None

def ensure_tables(cur):
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="Path to SQLite database")
    ap.add_argument("--src", help="Source table to migrate from (default: auto-detect)")
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys = ON;")

    tables = get_tables(cur)

    src = args.src
    if not src:
        for cand in CANDIDATE_SRC_TABLES:
            if cand in tables:
                src = cand
                break

    if not src:
        con.close()
        raise SystemExit(
            "Could not auto-detect a source table.\n"
            f"Tables found: {tables}\n"
            "Re-run with: --src <table_name>"
        )

    if src not in tables:
        con.close()
        raise SystemExit(f"Source table not found: {src}\nTables found: {tables}")

    cols = table_columns(cur, src)

    # Identify columns in source table
    id_col = pick_first(cols, "cat_id", "glass_id", "id")
    if not id_col:
        con.close()
        raise SystemExit(f"No id column found in {src}. Expected cat_id or glass_id.\nColumns: {cols}")

    color_col = pick_first(cols, "color_name", "color")
    family_col = pick_first(cols, "glass_family", "family")
    striker_col = pick_first(cols, "is_striker", "striker", "is_striking", "is_strike")
    has_opt_col = pick_first(cols, "has_optical_data", "hod")

    # Element columns
    se_col = pick_first(cols, "se")
    su_col = pick_first(cols, "su")
    cu_col = pick_first(cols, "cu")
    pb_col = pick_first(cols, "pb")
    ag_col = pick_first(cols, "ag")
    au_col = pick_first(cols, "au")

    # Measurement columns (case-insensitive)
    mode_col = pick_first(cols, "mode")
    r_col = pick_first(cols, "r")
    g_col = pick_first(cols, "g")
    b_col = pick_first(cols, "b")
    h_col = pick_first(cols, "h")
    s_col = pick_first(cols, "s")
    v_col = pick_first(cols, "v")

    print(f"Opening DB: {db_path}")
    print(f"Using source table: {src}")
    print(f"Source columns: {cols}")

    ensure_tables(cur)

    # --- Catalog insert ---
    # Build SELECT with MAX() to collapse duplicates across mode rows
    def sel_max(col: str | None, default_sql: str = "NULL") -> str:
        return f"MAX({qident(col)})" if col else default_sql

    # Force cat_id to 6-digit text if numeric in source:
    # printf('%06d', <id>) works if id is numeric; if already text, it will yield 000000 for non-numeric.
    # So: use CASE to keep text as-is when length>=6 or contains non-digits.
    cat_expr = f"""
    CASE
      WHEN typeof({qident(id_col)}) IN ('integer','real') THEN printf('%06d', CAST({qident(id_col)} AS INTEGER))
      ELSE
        CASE
          WHEN length(trim({qident(id_col)})) = 6 THEN trim({qident(id_col)})
          WHEN length(trim({qident(id_col)})) < 6 AND trim({qident(id_col)}) GLOB '[0-9]*' THEN printf('%06d', CAST(trim({qident(id_col)}) AS INTEGER))
          ELSE trim({qident(id_col)})
        END
    END
    """

    catalog_sql = f"""
    INSERT OR IGNORE INTO glass_catalog (
        cat_id, color_name, glass_family, is_striker,
        se, su, cu, pb, ag, au, has_optical_data
    )
    SELECT
        {cat_expr} AS cat_id,
        {sel_max(color_col)} AS color_name,
        {sel_max(family_col)} AS glass_family,
        COALESCE({sel_max(striker_col)}, 0) AS is_striker,
        {sel_max(se_col)} AS se,
        {sel_max(su_col)} AS su,
        {sel_max(cu_col)} AS cu,
        {sel_max(pb_col)} AS pb,
        {sel_max(ag_col)} AS ag,
        {sel_max(au_col)} AS au,
        COALESCE({sel_max(has_opt_col)}, 0) AS has_optical_data
    FROM {qident(src)}
    GROUP BY {cat_expr};
    """

    print("Migrating catalog…")
    cur.execute(catalog_sql)

    # --- Measurements insert (only if columns exist) ---
    if all([mode_col, r_col, g_col, b_col, h_col, s_col, v_col]):
        meas_sql = f"""
        INSERT INTO glass_measurements (cat_id, mode, R, G, B, H, S, V)
        SELECT
            {cat_expr} AS cat_id,
            UPPER(TRIM({qident(mode_col)})) AS mode,
            CAST({qident(r_col)} AS INTEGER) AS R,
            CAST({qident(g_col)} AS INTEGER) AS G,
            CAST({qident(b_col)} AS INTEGER) AS B,
            CAST({qident(h_col)} AS INTEGER) AS H,
            CAST({qident(s_col)} AS INTEGER) AS S,
            CAST({qident(v_col)} AS INTEGER) AS V
        FROM {qident(src)}
        WHERE {qident(mode_col)} IS NOT NULL AND TRIM({qident(mode_col)}) <> '';
        """
        print("Migrating measurements…")
        cur.execute(meas_sql)
    else:
        print("Skipping measurements migration (missing one or more of: mode,R,G,B,H,S,V in source).")

    con.commit()
    con.close()

    print("Done. Source table left unchanged.")
    print("New tables: glass_catalog, glass_measurements")

if __name__ == "__main__":
    main()
