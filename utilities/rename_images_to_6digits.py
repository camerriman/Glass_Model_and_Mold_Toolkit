#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

# Adjust if you use additional image extensions
IMG_EXTS = {".tiff", ".tif", ".jpg", ".jpeg", ".png", ".webp"}

NUMERIC_RE = re.compile(r"^\d+$")  # only rename stems that are all digits

def zfill6(stem: str) -> str:
    # Handle "224.0" style stems just in case
    if stem.endswith(".0"):
        stem = stem[:-2]
    return stem.zfill(6)

def plan_renames(folder: Path):
    renames = []
    if not folder.exists():
        return renames

    for p in sorted(folder.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMG_EXTS:
            continue

        stem = p.stem.strip()

        # Only rename purely numeric stems (e.g., "24" -> "000024")
        if not NUMERIC_RE.match(stem):
            continue

        new_stem = zfill6(stem)

        if new_stem == stem:
            continue  # already correct

        new_path = p.with_name(new_stem + p.suffix.lower())
        renames.append((p, new_path))
    return renames

def apply_renames(renames, dry_run: bool):
    # collision check
    collisions = [(src, dst) for (src, dst) in renames if dst.exists() and dst != src]
    if collisions:
        print("\n⚠️  Collisions detected (destination already exists). Aborting.")
        for src, dst in collisions[:50]:
            print(f"  {src} -> {dst} (DEST EXISTS)")
        if len(collisions) > 50:
            print(f"  ... and {len(collisions) - 50} more")
        return False

    for src, dst in renames:
        rel = f"{src} -> {dst}"
        if dry_run:
            print("DRY:", rel)
        else:
            print("REN:", rel)
            src.rename(dst)
    return True

def main():
    ap = argparse.ArgumentParser(description="Zero-pad numeric image filenames to 6 digits (incl. icons/).")
    ap.add_argument("--root", default="images", help="Images root folder (default: images)")
    ap.add_argument("--apply", action="store_true", help="Actually rename files (otherwise dry-run)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Not a folder: {root}")

    dry_run = not args.apply

    print(f"Root: {root}")
    print("Mode:", "DRY-RUN (no changes)" if dry_run else "APPLY (will rename files)")
    print()

    total = 0

    # Walk view folders
    for view_dir in sorted([d for d in root.iterdir() if d.is_dir()]):
        if view_dir.name.startswith("."):
            continue

        # Full images in the view folder
        ren_full = plan_renames(view_dir)
        # Icons folder (if present)
        icons_dir = view_dir / "icons"
        ren_icons = plan_renames(icons_dir) if icons_dir.exists() and icons_dir.is_dir() else []

        if not ren_full and not ren_icons:
            continue

        print(f"== {view_dir.name} ==")
        ok1 = apply_renames(ren_full, dry_run=dry_run)
        ok2 = apply_renames(ren_icons, dry_run=dry_run)
        if not (ok1 and ok2):
            raise SystemExit("Aborted due to collisions; fix those and rerun.")

        total += len(ren_full) + len(ren_icons)
        print()

    print(f"Done. Planned/processed renames: {total}")

if __name__ == "__main__":
    main()
