from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "glass_library.sqlite"
TINT_FAMILY_CODE = "3"


def normalize_cat_id(raw: str) -> str:
    value = str(raw or "").strip()
    if value.isdigit():
        return value.zfill(6)
    return value


def load_thicknesses(csv_path: Path) -> tuple[dict[str, float], dict[str, list[float]]]:
    values: dict[str, list[float]] = defaultdict(list)
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for row_number, row in enumerate(csv.reader(handle), start=1):
            if len(row) < 2 or not row[0].strip() or not row[1].strip():
                continue
            cat_id = normalize_cat_id(row[0])
            if not cat_id.isdigit() or len(cat_id) != 6:
                raise ValueError(f"Row {row_number}: product_id must be numeric")
            try:
                thickness_mm = float(row[1])
            except ValueError as exc:
                raise ValueError(f"Row {row_number}: thickness must be numeric") from exc
            if thickness_mm <= 0:
                raise ValueError(f"Row {row_number}: thickness must be greater than 0")
            values[cat_id].append(thickness_mm)

    averaged = {
        cat_id: round(sum(measurements) / len(measurements), 3)
        for cat_id, measurements in values.items()
    }
    duplicates = {
        cat_id: measurements
        for cat_id, measurements in values.items()
        if len(measurements) > 1
    }
    return averaged, duplicates


def import_thicknesses(csv_path: Path, db_path: Path, dry_run: bool) -> tuple[int, int, dict[str, list[float]]]:
    thicknesses, duplicates = load_thicknesses(csv_path)
    if not thicknesses:
        raise ValueError("No product_id/thickness rows found.")

    with sqlite3.connect(db_path) as con:
        con.execute("PRAGMA foreign_keys = ON;")
        catalog_ids = {
            row[0]
            for row in con.execute(
                "SELECT cat_id FROM glass_catalog WHERE glass_family = ?",
                (TINT_FAMILY_CODE,),
            ).fetchall()
        }
        missing = sorted(set(thicknesses) - catalog_ids)
        if missing:
            raise ValueError(f"CSV contains product IDs that are not tint catalog rows: {', '.join(missing)}")

        before = con.total_changes
        for cat_id, thickness_mm in sorted(thicknesses.items()):
            for mode in ("T", "R"):
                con.execute(
                    """
                    INSERT INTO glass_measurements (cat_id, mode, thickness_mm)
                    VALUES (?, ?, ?)
                    ON CONFLICT(cat_id, mode) DO UPDATE SET
                        thickness_mm = excluded.thickness_mm;
                    """,
                    (cat_id, mode, thickness_mm),
                )

        changed = con.total_changes - before
        if dry_run:
            con.rollback()
        else:
            con.commit()

    return len(thicknesses), changed, duplicates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import tint product thicknesses into glass_library.sqlite.")
    parser.add_argument("csv_path", type=Path, help="CSV with product_id, thickness_mm columns.")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to glass_library.sqlite.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without committing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows, changed, duplicates = import_thicknesses(args.csv_path, args.db, args.dry_run)
    action = "Validated" if args.dry_run else "Imported"
    print(f"{action} {rows} tint products; measurement rows touched: {changed}.")
    if duplicates:
        for cat_id, values in sorted(duplicates.items()):
            average = round(sum(values) / len(values), 3)
            joined = ", ".join(f"{value:g}" for value in values)
            print(f"Duplicate {cat_id}: averaged {joined} -> {average:g} mm")


if __name__ == "__main__":
    main()
