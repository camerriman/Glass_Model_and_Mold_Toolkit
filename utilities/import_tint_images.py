from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from PIL import Image, ImageOps


APP_ROOT = Path(__file__).resolve().parents[1]
FULL_DIR = APP_ROOT / "images" / "full"
ICONS_DIR = APP_ROOT / "images" / "icons"


def catalog_id_from_name(path: Path) -> str | None:
    match = re.fullmatch(r"(\d{4})\.tiff", path.name)
    if not match:
        return None
    return match.group(1).zfill(6)


def save_icon(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        icon = ImageOps.fit(image.convert("RGB"), (128, 128), method=Image.Resampling.LANCZOS)
        icon.save(destination, format="JPEG", quality=90, optimize=True)


def import_mode(source_dir: Path, mode: str) -> tuple[int, list[str]]:
    copied = 0
    skipped: list[str] = []
    for source in sorted(source_dir.glob("*.tiff")):
        cat_id = catalog_id_from_name(source)
        if cat_id is None:
            skipped.append(source.name)
            continue

        full_dest = FULL_DIR / f"tint_{mode}_{cat_id}.tiff"
        icon_dest = ICONS_DIR / f"tint_{mode}_{cat_id}.jpg"
        full_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, full_dest)
        save_icon(source, icon_dest)
        copied += 1

    return copied, skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import numbered tint TIFF scans into the app image naming scheme.")
    parser.add_argument("--transmitted-dir", type=Path, required=True)
    parser.add_argument("--reflected-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    transmitted, skipped_t = import_mode(args.transmitted_dir, "T")
    reflected, skipped_r = import_mode(args.reflected_dir, "R")
    print(f"Imported {transmitted} transmitted TIFFs and icons.")
    print(f"Imported {reflected} reflected TIFFs and icons.")
    if skipped_t:
        print("Skipped transmitted:", ", ".join(skipped_t))
    if skipped_r:
        print("Skipped reflected:", ", ".join(skipped_r))


if __name__ == "__main__":
    main()
