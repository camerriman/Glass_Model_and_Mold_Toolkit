from PIL import Image
from pathlib import Path
import re

jobs = [
    ("transparent_reflected",   "transparent_R"),
    ("transparent_transmitted", "transparent_T"),
]

pattern = re.compile(r'(\d{6})')

for folder_name, prefix in jobs:
    src = Path(folder_name)
    dst = Path(f"{folder_name}_128")
    dst.mkdir(exist_ok=True)

    for file in sorted(src.glob("*.tif*")):
        try:
            m = pattern.search(file.stem)
            if not m:
                print(f"⚠️ No index in {file.name}")
                continue

            index = m.group(1)
            new_name = f"{prefix}_{index}.jpg"
            out_path = dst / new_name

            with Image.open(file) as img:
                img = img.convert("RGB")

                if img.size != (128,128):
                    img = img.resize((128,128), Image.LANCZOS)

                img.save(out_path,
                         "JPEG",
                         quality=95,
                         subsampling=0,   # ← critical for your color work
                         optimize=False,
                         progressive=False,
                         dpi=(72,72))

            print(f"✓ {file.name} → {new_name}")

        except Exception as e:
            print(f"✗ Skipped {file.name}: {e}")