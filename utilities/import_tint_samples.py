from __future__ import annotations

import argparse
import colorsys
import csv
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "glass_library.sqlite"
FULL_DIR = APP_ROOT / "images" / "full"
ICONS_DIR = APP_ROOT / "images" / "icons"

TINT_FAMILY_CODE = "3"
TINT_PREFIX = "tint"
ELEMENT_COLUMNS = ("se", "su", "cu", "pb", "ag", "au")
MEASUREMENT_FIELDS = ("R", "G", "B", "H", "S", "V")


@dataclass(frozen=True)
class ImportResult:
    catalog_rows: int = 0
    measurement_rows: int = 0
    image_files: int = 0


def normalize_cat_id(raw: str | None) -> str:
    value = (raw or "").strip()
    if value.isdigit():
        return value.zfill(6)
    return value


def clean_text(raw: str | None) -> str | None:
    value = (raw or "").strip()
    return value or None


def int_flag(raw: str | None) -> int:
    value = (raw or "").strip().lower()
    return 1 if value in {"1", "true", "yes", "y", "x"} else 0


def int_or_none(raw: str | None) -> int | None:
    value = (raw or "").strip()
    if not value:
        return None
    return int(round(float(value)))


def float_or_default(raw: str | None, default: float) -> float:
    value = (raw or "").strip()
    return float(value) if value else default


def clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def derived_hsv(r: int, g: int, b: int) -> tuple[int, int, int]:
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return int(round(h * 360)) % 360, int(round(s * 100)), int(round(v * 100))


def read_measurement(row: dict[str, str], prefix: str, thickness_mm: float) -> dict[str, int | float | str] | None:
    values = {field: int_or_none(row.get(f"{prefix}_{field}")) for field in MEASUREMENT_FIELDS}
    rgb_present = all(values[field] is not None for field in ("R", "G", "B"))
    hsv_present = all(values[field] is not None for field in ("H", "S", "V"))

    if not rgb_present and not hsv_present:
        return None

    if not rgb_present:
        raise ValueError(f"{prefix} measurement needs R, G, and B values")

    r = clamp_int(int(values["R"]), 0, 255)
    g = clamp_int(int(values["G"]), 0, 255)
    b = clamp_int(int(values["B"]), 0, 255)

    if not hsv_present:
        h, s, v = derived_hsv(r, g, b)
    else:
        h = clamp_int(int(values["H"]), 0, 360)
        s = clamp_int(int(values["S"]), 0, 100)
        v = clamp_int(int(values["V"]), 0, 100)

    return {
        "mode": prefix,
        "R": r,
        "G": g,
        "B": b,
        "H": h,
        "S": s,
        "V": v,
        "thickness_mm": thickness_mm,
    }


def resolve_image_path(raw: str | None, csv_dir: Path, image_root: Path | None) -> Path | None:
    value = clean_text(raw)
    if value is None:
        return None

    candidate = Path(value).expanduser()
    candidates = [candidate]
    if not candidate.is_absolute():
        candidates.append(csv_dir / candidate)
        if image_root is not None:
            candidates.append(image_root / candidate)

    for path in candidates:
        if path.exists():
            return path

    raise FileNotFoundError(f"Image not found: {value}")


def save_full_and_icon(source: Path, cat_id: str, mode: str) -> int:
    full_dest = FULL_DIR / f"{TINT_PREFIX}_{mode}_{cat_id}.tiff"
    icon_dest = ICONS_DIR / f"{TINT_PREFIX}_{mode}_{cat_id}.jpg"
    full_dest.parent.mkdir(parents=True, exist_ok=True)
    icon_dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        img = Image.open(source)
        img.save(full_dest, format="TIFF")
        icon = img.convert("RGB").resize((72, 72), Image.Resampling.LANCZOS)
        icon.save(icon_dest, format="JPEG", quality=90, optimize=True)
    except Exception:
        shutil.copy2(source, full_dest)
        raise

    return 2


def ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("PRAGMA foreign_keys = ON;")
    con.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_measurements_cat_mode
        ON glass_measurements(cat_id, mode);
        """
    )


def upsert_catalog(con: sqlite3.Connection, row: dict[str, str], cat_id: str) -> None:
    payload = {
        "cat_id": cat_id,
        "color_name": clean_text(row.get("color_name")),
        "glass_family": TINT_FAMILY_CODE,
        "is_striker": int_flag(row.get("is_striker")),
        "cold_characteristics": clean_text(row.get("cold_characteristics")),
        "working_notes": clean_text(row.get("working_notes")),
    }
    for column in ELEMENT_COLUMNS:
        payload[column] = int_flag(row.get(column))

    con.execute(
        """
        INSERT INTO glass_catalog (
            cat_id, color_name, glass_family, is_striker,
            se, su, cu, pb, ag, au,
            cold_characteristics, working_notes
        ) VALUES (
            :cat_id, :color_name, :glass_family, :is_striker,
            :se, :su, :cu, :pb, :ag, :au,
            :cold_characteristics, :working_notes
        )
        ON CONFLICT(cat_id) DO UPDATE SET
            color_name = excluded.color_name,
            glass_family = excluded.glass_family,
            is_striker = excluded.is_striker,
            se = excluded.se,
            su = excluded.su,
            cu = excluded.cu,
            pb = excluded.pb,
            ag = excluded.ag,
            au = excluded.au,
            cold_characteristics = excluded.cold_characteristics,
            working_notes = excluded.working_notes;
        """,
        payload,
    )


def upsert_measurement(con: sqlite3.Connection, cat_id: str, measurement: dict[str, int | float | str]) -> None:
    payload = {"cat_id": cat_id, **measurement}
    con.execute(
        """
        INSERT INTO glass_measurements (cat_id, mode, R, G, B, H, S, V, thickness_mm)
        VALUES (:cat_id, :mode, :R, :G, :B, :H, :S, :V, :thickness_mm)
        ON CONFLICT(cat_id, mode) DO UPDATE SET
            R = excluded.R,
            G = excluded.G,
            B = excluded.B,
            H = excluded.H,
            S = excluded.S,
            V = excluded.V,
            thickness_mm = excluded.thickness_mm;
        """,
        payload,
    )


def import_csv(csv_path: Path, db_path: Path, image_root: Path | None, dry_run: bool = False) -> ImportResult:
    csv_path = csv_path.resolve()
    seen: set[str] = set()
    result = ImportResult()

    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    with sqlite3.connect(db_path) as con:
        ensure_schema(con)
        for row_number, row in enumerate(rows, start=2):
            cat_id = normalize_cat_id(row.get("cat_id"))
            if not cat_id or not cat_id.isdigit() or len(cat_id) != 6:
                raise ValueError(f"Row {row_number}: cat_id must be 6 digits")
            if cat_id in seen:
                raise ValueError(f"Row {row_number}: duplicate cat_id {cat_id}")
            seen.add(cat_id)

            thickness_mm = float_or_default(row.get("thickness_mm"), 2.0)
            measurements = [
                measurement
                for mode in ("T", "R")
                if (measurement := read_measurement(row, mode, thickness_mm)) is not None
            ]
            image_paths = [
                (mode, path)
                for mode in ("T", "R")
                if (path := resolve_image_path(row.get(f"{mode}_image"), csv_path.parent, image_root)) is not None
            ]

            if not dry_run:
                upsert_catalog(con, row, cat_id)
                for measurement in measurements:
                    upsert_measurement(con, cat_id, measurement)
                for mode, source_path in image_paths:
                    save_full_and_icon(source_path, cat_id, mode)

            result = ImportResult(
                catalog_rows=result.catalog_rows + 1,
                measurement_rows=result.measurement_rows + len(measurements),
                image_files=result.image_files + (len(image_paths) * 2),
            )

        if dry_run:
            con.rollback()
        else:
            con.commit()

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import tint glass samples from a CSV file.")
    parser.add_argument("csv_path", type=Path, help="CSV file containing tint sample rows.")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to glass_library.sqlite.")
    parser.add_argument(
        "--image-root",
        type=Path,
        default=None,
        help="Optional base directory for relative T_image and R_image values.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate the CSV without writing changes.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = import_csv(args.csv_path, args.db, args.image_root, args.dry_run)
    mode = "Validated" if args.dry_run else "Imported"
    print(
        f"{mode} {result.catalog_rows} catalog rows, "
        f"{result.measurement_rows} measurement rows, "
        f"{result.image_files} image files."
    )


if __name__ == "__main__":
    main()
