#!/usr/bin/env python3
"""
Zero‑pad numeric JPG filenames in a chosen folder to 6 digits.

Examples:
  0123.jpg -> 000123.jpg
  24.jpg   -> 000024.jpg

Usage:
  python pad_jpg_ids.py            # opens folder picker
  python pad_jpg_ids.py --apply    # actually rename (default is dry-run)
"""

from pathlib import Path
import argparse
import re
import sys

try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:
    tk = None

NUMERIC = re.compile(r"^\d+$")
EXTS = {".jpg", ".jpeg"}


def pick_folder() -> Path:
    if tk is None:
        raise SystemExit("tkinter not available. Use --root PATH instead.")
    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Select folder containing JPG icons")
    if not folder:
        raise SystemExit("No folder selected.")
    return Path(folder)


def plan(folder: Path):
    renames = []
    for p in folder.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in EXTS:
            continue

        stem = p.stem.strip()
        if not NUMERIC.match(stem):
            continue

        new_stem = stem.zfill(6)
        if new_stem == stem:
            continue

        dst = p.with_name(new_stem + p.suffix.lower())
        renames.append((p, dst))
    return renames


def apply(renames, dry_run: bool):
    # collision check
    collisions = [(s, d) for s, d in renames if d.exists() and d != s]
    if collisions:
        print("⚠️  Collision detected. Aborting.")
        for s, d in collisions[:20]:
            print("  ", s.name, "->", d.name)
        return False

    for s, d in renames:
        if dry_run:
            print("DRY:", s.name, "->", d.name)
        else:
            print("REN:", s.name, "->", d.name)
            s.rename(d)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", help="Folder path (optional; picker used if omitted)")
    ap.add_argument("--apply", action="store_true", help="Actually rename files")
    args = ap.parse_args()

    folder = Path(args.root).resolve() if args.root else pick_folder()
    if not folder.exists():
        raise SystemExit(f"Folder not found: {folder}")

    print("Folder:", folder)
    print("Mode:", "APPLY" if args.apply else "DRY-RUN")
    print()

    renames = plan(folder)
    if not renames:
        print("Nothing to rename.")
        return

    ok = apply(renames, dry_run=not args.apply)
    if ok:
        print(f"\nDone. Files processed: {len(renames)}")


if __name__ == "__main__":
    main()
