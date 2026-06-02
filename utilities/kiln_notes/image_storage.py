from __future__ import annotations

import base64
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parent
IMAGES_DIR = APP_DIR / "images"
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def ensure_images_dir() -> Path:
    # Kept for compatibility with the standalone app. The integrated public
    # toolkit stores uploaded images in exported JSON packages instead of
    # writing persistent server-side image files.
    return IMAGES_DIR


def normalized_image_path(value: str | None) -> Path | None:
    if not value:
        return None
    if value.startswith("data:"):
        return None
    path = Path(value)
    if not path.is_absolute():
        path = APP_DIR / path
    return path


def storage_path_for_value(value: str | None) -> str | None:
    if value and value.startswith("data:"):
        return value

    path = normalized_image_path(value)
    if path is None:
        return None
    try:
        return str(path.relative_to(APP_DIR))
    except ValueError:
        return str(path)


def read_image_bytes(value: str | None) -> bytes | None:
    if value and value.startswith("data:"):
        try:
            _, encoded_bytes = value.split(",", 1)
            return base64.b64decode(encoded_bytes)
        except (ValueError, TypeError):
            return None

    path = normalized_image_path(value)
    if path is None or not path.exists():
        return None
    return path.read_bytes()


def delete_image(value: str | None) -> None:
    if value and value.startswith("data:"):
        return

    path = normalized_image_path(value)
    if path is None or not path.exists():
        return
    path.unlink()


def _safe_suffix(original_name: str | None) -> str:
    suffix = Path(original_name or "").suffix.lower()
    if suffix in ALLOWED_SUFFIXES:
        return suffix
    return ".png"


def save_image_bytes(
    image_bytes: bytes,
    original_name: str | None,
    prefix: str,
) -> str:
    suffix = _safe_suffix(original_name).lstrip(".")
    mime_type = "image/jpeg" if suffix in {"jpg", "jpeg"} else f"image/{suffix}"
    encoded_bytes = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded_bytes}"


def uploaded_file_value(uploaded_file: Any) -> tuple[str | None, bytes | None]:
    if uploaded_file is None:
        return None, None
    return uploaded_file.name, uploaded_file.getvalue()
