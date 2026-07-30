from __future__ import annotations

import argparse
import re
from pathlib import Path


def rename_mode(source_dir: Path, mode: str) -> tuple[int, list[str]]:
    renamed = 0
    skipped: list[str] = []
    for source in sorted(source_dir.glob("*.tiff")):
        match = re.fullmatch(r"(\d{4})\.tiff", source.name)
        if not match:
            skipped.append(source.name)
            continue

        cat_id = match.group(1).zfill(6)
        destination = source.with_name(f"tint_{mode}_{cat_id}.tiff")
        if destination.exists():
            skipped.append(f"{source.name} -> {destination.name} already exists")
            continue
        source.rename(destination)
        renamed += 1
    return renamed, skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rename four-digit tint TIFF files in their source scan folders.")
    parser.add_argument("--transmitted-dir", type=Path, required=True)
    parser.add_argument("--reflected-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    transmitted, skipped_t = rename_mode(args.transmitted_dir, "T")
    reflected, skipped_r = rename_mode(args.reflected_dir, "R")
    print(f"Renamed {transmitted} transmitted source files.")
    print(f"Renamed {reflected} reflected source files.")
    if skipped_t:
        print("Skipped transmitted:", ", ".join(skipped_t))
    if skipped_r:
        print("Skipped reflected:", ", ".join(skipped_r))


if __name__ == "__main__":
    main()
