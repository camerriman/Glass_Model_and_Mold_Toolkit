from __future__ import annotations

import argparse
import colorsys
import csv
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageStat


APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "glass_library.sqlite"
FULL_DIR = APP_ROOT / "images" / "full"


@dataclass(frozen=True)
class Measurement:
    cat_id: str
    mode: str
    source_file: str
    crop_box: tuple[int, int, int, int]
    r: int
    g: int
    b: int
    h: int
    s: int
    v: int


def hsv_from_rgb(r: int, g: int, b: int) -> tuple[int, int, int]:
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return int(round(h * 360)) % 360, int(round(s * 100)), int(round(v * 100))


def center_crop_box(width: int, height: int, fraction: float) -> tuple[int, int, int, int]:
    crop_width = max(1, int(round(width * fraction)))
    crop_height = max(1, int(round(height * fraction)))
    left = (width - crop_width) // 2
    top = (height - crop_height) // 2
    return left, top, left + crop_width, top + crop_height


def measure_image(path: Path, fraction: float) -> Measurement | None:
    match = re.fullmatch(r"tint_([TR])_(\d{6})\.tiff", path.name)
    if not match:
        return None

    mode, cat_id = match.groups()
    with Image.open(path) as image:
        rgb_image = image.convert("RGB")
        crop_box = center_crop_box(rgb_image.width, rgb_image.height, fraction)
        crop = rgb_image.crop(crop_box)
        mean = ImageStat.Stat(crop).mean

    r, g, b = (int(round(value)) for value in mean[:3])
    h, s, v = hsv_from_rgb(r, g, b)
    return Measurement(
        cat_id=cat_id,
        mode=mode,
        source_file=path.name,
        crop_box=crop_box,
        r=r,
        g=g,
        b=b,
        h=h,
        s=s,
        v=v,
    )


def collect_measurements(image_dir: Path, fraction: float) -> list[Measurement]:
    measurements = [
        measurement
        for path in sorted(image_dir.glob("tint_[TR]_*.tiff"))
        if (measurement := measure_image(path, fraction)) is not None
    ]
    seen: set[tuple[str, str]] = set()
    duplicates: list[str] = []
    for measurement in measurements:
        key = (measurement.cat_id, measurement.mode)
        if key in seen:
            duplicates.append(f"{measurement.cat_id} {measurement.mode}")
        seen.add(key)
    if duplicates:
        raise ValueError(f"Duplicate image measurements found: {', '.join(duplicates)}")
    return measurements


def write_report(measurements: list[Measurement], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["cat_id", "mode", "source_file", "crop_box", "R", "G", "B", "H", "S", "V"])
        for measurement in measurements:
            writer.writerow(
                [
                    measurement.cat_id,
                    measurement.mode,
                    measurement.source_file,
                    " ".join(str(value) for value in measurement.crop_box),
                    measurement.r,
                    measurement.g,
                    measurement.b,
                    measurement.h,
                    measurement.s,
                    measurement.v,
                ]
            )


def update_database(measurements: list[Measurement], db_path: Path, dry_run: bool) -> int:
    with sqlite3.connect(db_path) as con:
        con.execute("PRAGMA foreign_keys = ON;")
        before = con.total_changes
        for measurement in measurements:
            con.execute(
                """
                INSERT INTO glass_measurements (cat_id, mode, R, G, B, H, S, V, thickness_mm)
                VALUES (:cat_id, :mode, :r, :g, :b, :h, :s, :v, 2.0)
                ON CONFLICT(cat_id, mode) DO UPDATE SET
                    R = excluded.R,
                    G = excluded.G,
                    B = excluded.B,
                    H = excluded.H,
                    S = excluded.S,
                    V = excluded.V;
                """,
                {
                    "cat_id": measurement.cat_id,
                    "mode": measurement.mode,
                    "r": measurement.r,
                    "g": measurement.g,
                    "b": measurement.b,
                    "h": measurement.h,
                    "s": measurement.s,
                    "v": measurement.v,
                },
            )
        changed = con.total_changes - before
        if dry_run:
            con.rollback()
        else:
            con.commit()
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure tint sample colors from the center of full TIFF scans.")
    parser.add_argument("--image-dir", type=Path, default=FULL_DIR)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--fraction", type=float, default=0.10, help="Centered image fraction to sample on each axis.")
    parser.add_argument("--report", type=Path, default=APP_ROOT / "data" / "tint_image_measurements.csv")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 0 < args.fraction <= 1:
        raise ValueError("--fraction must be greater than 0 and no more than 1")

    measurements = collect_measurements(args.image_dir, args.fraction)
    write_report(measurements, args.report)
    changed = update_database(measurements, args.db, args.dry_run)
    action = "Validated" if args.dry_run else "Measured"
    print(f"{action} {len(measurements)} tint image measurements; database rows touched: {changed}.")
    print(f"Report: {args.report}")


if __name__ == "__main__":
    main()
