#!/usr/bin/env python3
"""
Flatten legacy glass image folders into:
  images/full/
  images/icons/

Naming:
  <family>_<mode>_<catid>.<ext>
Examples:
  opal_T_000024.tiff
  opal_T_000024.jpg

Dry-run by default. Use --apply to actually copy.

Run from vs-code-app root:
  python3 flatten_images.py
  python3 flatten_images.py --apply
"""

import argparse
import re
import shutil
from pathlib import Path

TIFF_EXTS = {".tif", ".tiff"}
JPG_EXTS = {".jpg", ".jpeg"}

# Folders under images/ that we do NOT treat as legacy view folders
SKIP_DIRS = {"full", "icons", "_placeholders"}

# Map legacy folder names -> (family, mode)
# Add/edit keys here to match your real folder names.
FOLDER_MAP = {
    "opal_transmitted": ("opal", "T"),
    "opal_reflected": ("opal", "R"),
    "transparent_transmitted": ("transparent", "T"),
    "transparent_reflected": ("transparent", "R"),
}

ID_RE = re.compile(r"(\d{1,6})")  # pulls first 1-6 digit run from filename


def z6(s: str) -> str:
    return s.zfill(6)


def parse_cat_id(stem: str) -> str | None:
    m = ID_RE.search(stem)
    if not m:
        return None
    return z6(m.group(1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-dir", default="images", help="Images directory (default: images)")
    ap.add_argument("--apply", action="store_true", help="Actually copy files (default is dry-run)")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite if destination exists")
    args = ap.parse_args()

    images_dir = Path(args.images_dir).resolve()
    if not images_dir.exists():
        raise SystemExit(f"Not found: {images_dir}")

    out_full = images_dir / "full"
    out_icons = images_dir / "icons"
    out_full.mkdir(parents=True, exist_ok=True)
    out_icons.mkdir(parents=True, exist_ok=True)

    legacy_dirs = [p for p in images_dir.iterdir() if p.is_dir() and p.name not in SKIP_DIRS]

    print(f"Images dir: {images_dir}")
    print(f"Output full:  {out_full}")
    print(f"Output icons: {out_icons}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print()

    unknown = []
    copied = 0
    skipped = 0
    bad_id = 0

    for d in sorted(legacy_dirs, key=lambda p: p.name.lower()):
        if d.name not in FOLDER_MAP:
            unknown.append(d.name)
            continue

        family, mode = FOLDER_MAP[d.name]
        icons_sub = d / "icons"

        # Full TIFFs live in the folder root (per your current structure)
        full_files = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in TIFF_EXTS]

        # Icons are JPGs inside /icons
        icon_files = []
        if icons_sub.exists() and icons_sub.is_dir():
            icon_files = [p for p in icons_sub.iterdir() if p.is_file() and p.suffix.lower() in JPG_EXTS]

        # Process full tiffs
        for src in sorted(full_files, key=lambda p: p.name.lower()):
            cat_id = parse_cat_id(src.stem)
            if not cat_id:
                bad_id += 1
                print(f"BADID full: {d.name}/{src.name}")
                continue

            dst = out_full / f"{family}_{mode}_{cat_id}{src.suffix.lower()}"
            if dst.exists() and not args.overwrite:
                skipped += 1
                continue

            if args.apply:
                shutil.copy2(src, dst)
            copied += 1

        # Process icons
        for src in sorted(icon_files, key=lambda p: p.name.lower()):
            cat_id = parse_cat_id(src.stem)
            if not cat_id:
                bad_id += 1
                print(f"BADID icon: {d.name}/icons/{src.name}")
                continue

            dst = out_icons / f"{family}_{mode}_{cat_id}.jpg"
            if dst.exists() and not args.overwrite:
                skipped += 1
                continue

            if args.apply:
                shutil.copy2(src, dst)
            copied += 1

    if unknown:
        print("\nFolders found that are NOT in FOLDER_MAP (no action taken):")
        for name in unknown:
            print(f"  - {name}")
        print("\nAdd them to FOLDER_MAP at the top of the script.")

    print("\nSummary")
    print(f"  copied/planned: {copied}")
    print(f"  skipped(existing): {skipped}")
    print(f"  bad_id: {bad_id}")


if __name__ == "__main__":
    main()