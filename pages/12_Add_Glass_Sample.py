import sqlite3
from pathlib import Path

import streamlit as st
from streamlit_quill import st_quill
from PIL import Image

from i18n import render_app_sidebar, t, translate_family_name

# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------
APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "glass_library.sqlite"
LIBRARY_PAGE = "pages/6_Glass_Library.py"

IMAGES_DIR = APP_ROOT / "images"
FULL_DIR = IMAGES_DIR / "full"
ICONS_DIR = IMAGES_DIR / "icons"

# Placeholders (optional)
PLACEHOLDER_DIR = IMAGES_DIR / "_placeholders"
PLACEHOLDER_ICON = PLACEHOLDER_DIR / "missing_icon.jpg"
PLACEHOLDER_FULL = PLACEHOLDER_DIR / "missing_full.tiff"  # ok if this doesn't exist

DEFAULT_FAMILIES = [
    ("1", "Opalescent"),
    ("2", "Transparent"),
    ("3", "Tint"),
]

# ------------------------------------------------------------
# DB helpers
# ------------------------------------------------------------
def open_db() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.execute("PRAGMA foreign_keys = ON;")
    return con


def ensure_tables() -> None:
    """Create the current schema used by the glass workflow pages."""
    con = open_db()
    cur = con.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS glass_catalog (
            cat_id TEXT PRIMARY KEY,
            color_name TEXT,
            glass_family TEXT,
            is_striker INTEGER,
            se INTEGER,
            su INTEGER,
            cu INTEGER,
            pb INTEGER,
            ag INTEGER,
            au INTEGER,
            cold_characteristics TEXT,
            working_notes TEXT
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS glass_measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cat_id TEXT,
            mode TEXT,          -- 'T' or 'R'
            R INTEGER,
            G INTEGER,
            B INTEGER,
            H INTEGER,
            S INTEGER,
            V INTEGER,
            thickness_mm REAL DEFAULT 2.0,
            FOREIGN KEY (cat_id) REFERENCES glass_catalog(cat_id) ON DELETE CASCADE
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS glass_families (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT NOT NULL
        );
        """
    )

    cur.execute("CREATE INDEX IF NOT EXISTS idx_meas_cat_mode ON glass_measurements(cat_id, mode);")
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_measurements_cat_mode
        ON glass_measurements(cat_id, mode);
        """
    )

    family_count = cur.execute("SELECT COUNT(*) FROM glass_families;").fetchone()[0]
    if family_count == 0:
        cur.executemany(
            "INSERT INTO glass_families (code, name) VALUES (?, ?);",
            DEFAULT_FAMILIES,
        )

    con.commit()
    con.close()


def list_families_from_db() -> list[tuple[str, str]]:
    """
    Read families from glass_families.
    Returns list of (code, name) e.g. [("1", "Opalescent"), ...]
    """
    try:
        with open_db() as con:
            rows = con.execute("SELECT code, name FROM glass_families ORDER BY id;").fetchall()
            return [(str(r[0]), str(r[1])) for r in rows]
    except Exception:
        return []


def cat_id_exists(cat_id: str) -> bool:
    with open_db() as con:
        row = con.execute("SELECT 1 FROM glass_catalog WHERE cat_id = ? LIMIT 1;", (cat_id,)).fetchone()
    return row is not None


# ------------------------------------------------------------
# Utils
# ------------------------------------------------------------
def normalize_cat_id(raw: str) -> str:
    raw = (raw or "").strip()
    if raw == "":
        return ""
    # Strip Unicode smart quotes and other lookalike punctuation that can
    # sneak in from macOS/iOS autocorrect or copy-paste from rich text apps
    UNICODE_QUOTES = (
        "\u2018\u2019"  # '' left/right single quotation marks
        "\u201C\u201D"  # "" left/right double quotation marks
        "\u2032\u2033"  # ′ ″ prime / double prime
        "\u0060\u00B4"  # ` ´ grave / acute accent
        "\u02BC"        # ʼ modifier letter apostrophe
    )
    raw = raw.strip(UNICODE_QUOTES).strip()
    if raw.isdigit():
        return raw.zfill(6)
    return raw


def is_valid_cat_id(cat_id: str) -> bool:
    return bool(cat_id) and cat_id.isdigit() and len(cat_id) == 6


# Map glass_family code to image prefix (matches VIEW_MAP in Glass Library)
FAMILY_CODE_TO_PREFIX = {
    "1": "opal",
    "2": "transparent",
    "3": "tint",
}

def image_paths(cat_id: str, family_code: str) -> dict:
    """Return icon and full image paths using the library's naming convention."""
    prefix = FAMILY_CODE_TO_PREFIX.get(str(family_code), "other")
    return {
        "icon_T": ICONS_DIR / f"{prefix}_T_{cat_id}.jpg",
        "icon_R": ICONS_DIR / f"{prefix}_R_{cat_id}.jpg",
        "full_T": FULL_DIR / f"{prefix}_T_{cat_id}.tiff",
        "full_R": FULL_DIR / f"{prefix}_R_{cat_id}.tiff",
    }


def pick_library_page() -> str | None:
    """Find the most likely Glass Library page in /pages for Cancel navigation."""
    candidates = ["6_Glass_Library.py", "5_Glass_Library.py"]
    for name in candidates:
        if (APP_ROOT / "pages" / name).exists():
            return f"pages/{name}"
    return None


def switch_to_page(target: str) -> bool:
    candidates = [target]
    if target.startswith("pages/"):
        candidates.append(target.split("/", 1)[1])

    for candidate in candidates:
        try:
            st.switch_page(candidate)
            return True
        except Exception:
            continue
    return False


def save_icon_72(uploaded_file, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(uploaded_file)
    img = img.convert("RGB")
    img = img.resize((72, 72), Image.Resampling.LANCZOS)
    img.save(dest, format="JPEG", quality=90, optimize=True)


def save_full_image(uploaded_file, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    suffix = dest.suffix.lower()
    img = Image.open(uploaded_file)
    if suffix in [".tif", ".tiff"]:
        img.save(dest, format="TIFF")
    elif suffix in [".jpg", ".jpeg"]:
        img.convert("RGB").save(dest, format="JPEG", quality=92, optimize=True)
    elif suffix == ".png":
        img.save(dest, format="PNG")
    else:
        img.save(dest.with_suffix(".tiff"), format="TIFF")


# ------------------------------------------------------------
# Page
# ------------------------------------------------------------
st.set_page_config(page_title=t("editor.add.title", "Add Glass Sample"), layout="wide")
ensure_tables()

render_app_sidebar()
st.title(t("editor.add.title", "Add Glass Sample"))


def family_label(code: str, name: str) -> str:
    return translate_family_name(code, name)


def element_full_label(key: str) -> str:
    labels = {
        "se": t("editor.element.se", "Se (Selenium)"),
        "su": t("editor.element.su", "S (Sulfur)"),
        "cu": t("editor.element.cu", "Cu (Copper)"),
        "pb": t("editor.element.pb", "Pb (Lead)"),
        "ag": t("editor.element.ag", "Ag (Silver)"),
        "au": t("editor.element.au", "Au (Gold)"),
    }
    return labels.get(key, key)

# ---- Inputs (top) ----
left, right = st.columns([3, 2])

with left:
    raw = st.text_input(
        t("editor.fields.cat_id", "cat_id (6 digits, e.g., 001234)"),
        value="",
        placeholder=t("editor.fields.cat_id_placeholder", "001234"),
    )
    cat_id = normalize_cat_id(raw)
    if raw and cat_id != raw:
        st.caption(t("editor.messages.normalized", "Normalized to: **{cat_id}**", cat_id=cat_id))

    color_name = st.text_input(t("editor.fields.color_name", "Color name"), value="")

    # Glass family dropdown sourced from DB
    fam_rows = list_families_from_db()
    if fam_rows:
        fam_names = [name for _, name in fam_rows]
        fam_codes = [code for code, _ in fam_rows]
        sel_index = st.selectbox(
            t("editor.fields.glass_family", "Glass family"),
            options=range(len(fam_names)),
            format_func=lambda i: family_label(fam_codes[i], fam_names[i]),
            index=0,
        )
        glass_family_code = fam_codes[sel_index]
    else:
        glass_family_code = None
        st.warning(
            t(
                "editor.warnings.families_missing",
                "glass_families table not found (or empty). Family selection disabled until it exists.",
            )
        )

# --- Elements contained (optional) ---
st.markdown(f"### {t('editor.sections.elements', 'Elements contained (optional)')}")
st.caption(
    t(
        "editor.sections.elements_caption",
        "Select what the glass contains. The app will derive a 'may react with' summary automatically.",
    )
)

ELEMENTS = [
    ("se", "Se (Selenium)"),
    ("su", "S (Sulfur)"),
    ("cu", "Cu (Copper)"),
    ("pb", "Pb (Lead)"),
    ("ag", "Ag (Silver)"),
    ("au", "Au (Gold)"),
]

# Reaction rules — kept in sync with REACTION_RULES in Glass Library
REACT_RULES = {
    "se": {"cu", "pb", "ag"},
    "su": {"cu", "pb", "ag"},
    "cu": {"se", "su", "ag"},
    "pb": {"se", "su"},
    "ag": {"se", "su", "cu"},
    "au": set(),
}

c_e1, c_e2, c_e3 = st.columns(3)
cols = [c_e1, c_e2, c_e3]

_contains = {}
for i, (k, label) in enumerate(ELEMENTS):
    with cols[i % 3]:
        _contains[k] = 1 if st.checkbox(element_full_label(k), value=False, key=f"contains_{k}") else 0

se = _contains["se"]
su = _contains["su"]
cu = _contains["cu"]
pb = _contains["pb"]
ag = _contains["ag"]
au = _contains["au"]

_reacts = {k: 0 for k, _ in ELEMENTS}
for k, present in _contains.items():
    if present == 1:
        for tgt in REACT_RULES.get(k, set()):
            _reacts[tgt] = 1

react_labels = [element_full_label(k) for (k, _) in ELEMENTS if _reacts.get(k, 0) == 1]
st.markdown(f"**{t('editor.sections.reacts', 'May react with (derived)')}**")
st.write(", ".join(react_labels) if react_labels else "-")

with right:
    is_striker = st.checkbox(t("editor.fields.striker", "Striker"), value=False)

# ---- Notes ----
n1, n2 = st.columns([2, 1])
with n1:
    st.markdown(f"**{t('editor.sections.cold', 'Cold characteristics (optional)')}**")
    cold_characteristics = st_quill(
        placeholder=t("editor.placeholders.cold", "Enter cold characteristics..."),
        html=True,
        toolbar=[{"size": ["8px", "10px", "12px", "14px", "18px", "24px"]},
                 "bold", "italic", "underline",
                 {"list": "ordered"}, {"list": "bullet"}],
        key="quill_cold",
    ) or ""
with n2:
    st.markdown(f"**{t('editor.sections.work', 'Working notes (optional)')}**")
    working_notes = st_quill(
        placeholder=t("editor.placeholders.work", "Enter working notes..."),
        html=True,
        toolbar=[{"size": ["8px", "10px", "12px", "14px", "18px", "24px"]},
                 "bold", "italic", "underline",
                 {"list": "ordered"}, {"list": "bullet"}],
        key="quill_work",
    ) or ""

# ---- Optical measurements + Images ----
left2, right2 = st.columns([1, 1], gap="large")

with left2:
    st.subheader(t("editor.sections.measurements", "Measurements (Reflected / Transmitted)"))

    thickness_mm = st.number_input(
        t("editor.fields.thickness", "Thickness (mm)"), min_value=0.0, max_value=25.0, value=2.0, step=0.1,
        format="%.1f", key="thickness_mm",
    )

    tabT, tabR = st.tabs(
        [
            t("editor.tabs.transmitted", "Transmitted"),
            t("editor.tabs.reflected", "Reflected"),
        ]
    )

    with tabT:
        RT = st.number_input(t("editor.fields.red", "Red (R)"), 0, 255, 0, key="RT")
        GT = st.number_input(t("editor.fields.green", "Green (G)"), 0, 255, 0, key="GT")
        BT = st.number_input(t("editor.fields.blue", "Blue (B)"), 0, 255, 0, key="BT")
        HT = st.number_input(t("editor.fields.hue", "Hue (H)"), 0, 360, 0, key="HT")
        ST_ = st.number_input(t("editor.fields.saturation", "Saturation (S)"), 0, 100, 0, key="ST")
        VT = st.number_input(t("editor.fields.brightness", "Brightness (B)"), 0, 100, 0, key="VT")

    with tabR:
        RR = st.number_input(t("editor.fields.red", "Red (R)"), 0, 255, 0, key="RR")
        GR = st.number_input(t("editor.fields.green", "Green (G)"), 0, 255, 0, key="GR")
        BR = st.number_input(t("editor.fields.blue", "Blue (B)"), 0, 255, 0, key="BR")
        HR = st.number_input(t("editor.fields.hue", "Hue (H)"), 0, 360, 0, key="HR")
        SR_ = st.number_input(t("editor.fields.saturation", "Saturation (S)"), 0, 100, 0, key="SR")
        VR = st.number_input(t("editor.fields.brightness", "Brightness (B)"), 0, 100, 0, key="VR")

with right2:
    st.subheader(t("editor.sections.images", "Images (optional)"))
    st.caption(
        t(
            "editor.images.caption_add",
            "Upload full-res images (T and/or R). Icons will be auto-generated (72x72 JPG) from the uploaded full image(s). If you skip uploads, the library will show placeholders.",
        )
    )

    full_up_T = st.file_uploader(
        t("editor.images.full_t", "Full image for Transmitted (T) (TIFF/JPG/PNG)"),
        type=["tif", "tiff", "jpg", "jpeg", "png"],
        key="full_T_upload",
    )

    full_up_R = st.file_uploader(
        t("editor.images.full_r", "Full image for Reflected (R) (TIFF/JPG/PNG)"),
        type=["tif", "tiff", "jpg", "jpeg", "png"],
        key="full_R_upload",
    )

    if cat_id:
        cat_id_norm = normalize_cat_id(cat_id)
        paths = image_paths(cat_id_norm, glass_family_code or "1")

        st.caption(t("editor.images.preview_now", "Preview (what the library will show if you saved right now)"))

        icon_preview_T = paths["icon_T"] if paths["icon_T"].exists() else PLACEHOLDER_ICON
        icon_preview_R = paths["icon_R"] if paths["icon_R"].exists() else PLACEHOLDER_ICON
        full_preview_T = paths["full_T"] if paths["full_T"].exists() else PLACEHOLDER_FULL
        full_preview_R = paths["full_R"] if paths["full_R"].exists() else PLACEHOLDER_FULL

        p1, p2, p3 = st.columns(3)
        with p1:
            st.text(t("editor.images.icons", "Icons"))
            st.caption(t("editor.images.icon_t_short", "Icon (T)"))
            st.image(str(icon_preview_T), width="stretch")
            st.caption(t("editor.images.icon_r_short", "Icon (R)"))
            st.image(str(icon_preview_R), width="stretch")
        with p2:
            st.text(t("editor.images.full_t_short", "Full (T)"))
            st.image(str(full_preview_T), width="stretch")
        with p3:
            st.text(t("editor.images.full_r_short", "Full (R)"))
            st.image(str(full_preview_R), width="stretch")
    else:
        st.info(t("editor.images.enter_cat_id", "Enter a cat_id to see destination filenames and previews."))

# ---- Bottom buttons ----
st.divider()

b1, b2 = st.columns([1, 1])
save_clicked = b1.button(t("editor.actions.save", "Save"), type="primary", use_container_width=True)
cancel_clicked = b2.button(t("editor.actions.cancel", "Cancel"), use_container_width=True)

if cancel_clicked:
    target = pick_library_page()
    if not target or not switch_to_page(target):
        st.warning(
            t(
                "editor.warnings.library_navigation_missing",
                "Could not find the Glass Library page in /pages. Please navigate from the sidebar.",
            )
        )

if save_clicked:
    cat_id_norm = (cat_id or "").strip()

    if not is_valid_cat_id(cat_id_norm):
        st.error(t("errors.editor.invalid_cat_id", "cat_id must be exactly 6 digits (e.g., 001234)."))
        st.stop()

    if cat_id_exists(cat_id_norm):
        st.error(
            t(
                "errors.editor.duplicate_cat_id",
                "cat_id {cat_id} already exists in glass_catalog. Choose a new id or edit the existing record.",
                cat_id=cat_id_norm,
            )
        )
        st.stop()

    # Always create both rows (T and R). Leave values at 0 if unknown.
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            cur = conn.cursor()

            cur.execute(
                """
                INSERT INTO glass_catalog
                (cat_id, color_name, glass_family, is_striker, se, su, cu, pb, ag, au, cold_characteristics, working_notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cat_id_norm,
                    (color_name or "").strip(),
                    glass_family_code,
                    int(is_striker),
                    int(se), int(su), int(cu), int(pb), int(ag), int(au),
                    (cold_characteristics or "").strip() or None,
                    (working_notes or "").strip() or None,
                ),
            )

            # Insert both measurement rows
            cur.execute(
                """
                INSERT INTO glass_measurements (cat_id, mode, r, g, b, h, s, v, thickness_mm)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cat_id_norm, "T", int(RT), int(GT), int(BT), int(HT), int(ST_), int(VT), float(thickness_mm)),
            )

            cur.execute(
                """
                INSERT INTO glass_measurements (cat_id, mode, r, g, b, h, s, v, thickness_mm)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cat_id_norm, "R", int(RR), int(GR), int(BR), int(HR), int(SR_), int(VR), float(thickness_mm)),
            )

            # Images (optional) — use correct naming convention for the library
            paths = image_paths(cat_id_norm, glass_family_code or "1")

            if full_up_T:
                save_full_image(full_up_T, paths["full_T"])
                save_icon_72(full_up_T, paths["icon_T"])

            if full_up_R:
                save_full_image(full_up_R, paths["full_R"])
                save_icon_72(full_up_R, paths["icon_R"])

            conn.commit()

        st.success(t("editor.messages.saved_with_id", "Saved {cat_id}.", cat_id=cat_id_norm))
        st.cache_data.clear()
        target = pick_library_page()
        if not target or not switch_to_page(target):
            st.info(
                t(
                    "editor.messages.saved_open_library",
                    "Saved {cat_id}. Open {page} to review it in the library.",
                    cat_id=cat_id_norm,
                    page=LIBRARY_PAGE,
                )
            )

    except Exception as e:
        st.error(t("errors.editor.save_failed", "Save failed: {error}", error=e))
