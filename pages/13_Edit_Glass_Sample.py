# pages/13_Edit_Glass_Sample.py
import sqlite3
from pathlib import Path
from PIL import Image
import streamlit as st
from streamlit_quill import st_quill

from i18n import render_app_sidebar, t, translate_family_name

APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "glass_library.sqlite"
LIBRARY_PAGE = "pages/6_Glass_Library.py"
IMG_ROOT = APP_ROOT / "images"
ICONS_DIR = IMG_ROOT / "icons"
FULL_DIR = IMG_ROOT / "full"

PLACEHOLDER_DIR = IMG_ROOT / "_placeholders"
PLACEHOLDER_ICON = PLACEHOLDER_DIR / "missing_icon.jpg"
PLACEHOLDER_FULL = PLACEHOLDER_DIR / "missing_full.tiff"

# FIX #8: correct prefix mapping (was using "trans" instead of "transparent")
FAMILY_CODE_TO_PREFIX = {
    "1": "opal",
    "2": "transparent",
    "3": "tint",
}

# FIX #9: synced REACT_RULES with canonical version (added Silver<->Copper)
REACT_RULES = {
    "se": {"cu", "pb", "ag"},
    "su": {"cu", "pb", "ag"},
    "cu": {"se", "su", "ag"},
    "pb": {"se", "su"},
    "ag": {"se", "su", "cu"},
    "au": set(),
}

ELEMENTS = [
    ("se", "Se (Selenium)"),
    ("su", "S (Sulfur)"),
    ("cu", "Cu (Copper)"),
    ("pb", "Pb (Lead)"),
    ("ag", "Ag (Silver)"),
    ("au", "Au (Gold)"),
]


# ------------------------------------------------------------
# DB helpers
# ------------------------------------------------------------

def get_con() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON;")
    return con


def ensure_unique_index():
    with get_con() as con:
        con.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_measurements_cat_mode
            ON glass_measurements(cat_id, mode);
        """)
        con.commit()


def norm_cat_id(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    # Strip Unicode smart quotes and lookalike punctuation
    UNICODE_QUOTES = (
        "\u2018\u2019"  # '' left/right single quotation marks
        "\u201C\u201D"  # "" left/right double quotation marks
        "\u2032\u2033"  # ′ ″ prime / double prime
        "\u0060\u00B4"  # ` ´ grave / acute accent
        "\u02BC"        # ʼ modifier letter apostrophe
    )
    raw = raw.strip(UNICODE_QUOTES).strip()
    if raw.isdigit() and len(raw) <= 6:
        return raw.zfill(6)
    return ""


# FIX #7: reads from glass_families table and returns (code, name) pairs
def list_glass_families() -> list[tuple[str, str]]:
    """Return (code, name) pairs from glass_families table for dropdowns."""
    try:
        with get_con() as con:
            rows = con.execute(
                "SELECT code, name FROM glass_families ORDER BY id;"
            ).fetchall()
        return [(str(r[0]), str(r[1])) for r in rows]
    except Exception:
        return []


# FIX #6: removed has_optical_data from SELECT (column doesn't exist)
def search_catalog(q: str):
    q = (q or "").strip()
    if not q:
        return []
    q_norm = norm_cat_id(q)
    with get_con() as con:
        if q_norm:
            rows = con.execute("""
                SELECT cat_id, color_name, glass_family, is_striker
                FROM glass_catalog
                WHERE cat_id = ?
                ORDER BY cat_id
                LIMIT 200
            """, (q_norm,)).fetchall()
        else:
            like = f"%{q.lower()}%"
            rows = con.execute("""
                SELECT cat_id, color_name, glass_family, is_striker
                FROM glass_catalog
                WHERE lower(color_name) LIKE ?
                ORDER BY cat_id
                LIMIT 200
            """, (like,)).fetchall()
    return [dict(r) for r in rows]


def fetch_catalog(cat_id: str):
    with get_con() as con:
        r = con.execute("SELECT * FROM glass_catalog WHERE cat_id = ?", (cat_id,)).fetchone()
        return dict(r) if r else None


def fetch_meas(cat_id: str, mode: str):
    with get_con() as con:
        r = con.execute(
            "SELECT * FROM glass_measurements WHERE cat_id = ? AND mode = ?",
            (cat_id, mode),
        ).fetchone()
        return dict(r) if r else None


# FIX #3: fixed SQL (removed has_optical_data, notes; use cold_characteristics/working_notes;
#          fixed trailing comma in VALUES)
def upsert_catalog(con: sqlite3.Connection, p: dict):
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
            color_name           = excluded.color_name,
            glass_family         = excluded.glass_family,
            is_striker           = excluded.is_striker,
            se                   = excluded.se,
            su                   = excluded.su,
            cu                   = excluded.cu,
            pb                   = excluded.pb,
            ag                   = excluded.ag,
            au                   = excluded.au,
            cold_characteristics = excluded.cold_characteristics,
            working_notes        = excluded.working_notes
        ;
        """,
        p,
    )


def upsert_meas(con: sqlite3.Connection, p: dict):
    con.execute(
        """
        INSERT INTO glass_measurements (cat_id, mode, R, G, B, H, S, V, thickness_mm)
        VALUES (:cat_id, :mode, :R, :G, :B, :H, :S, :V, :thickness_mm)
        ON CONFLICT(cat_id, mode) DO UPDATE SET
            R            = excluded.R,
            G            = excluded.G,
            B            = excluded.B,
            H            = excluded.H,
            S            = excluded.S,
            V            = excluded.V,
            thickness_mm = excluded.thickness_mm
        ;
        """,
        p,
    )


def save_full_image(uploaded_file, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(uploaded_file)
    suffix = dest.suffix.lower()
    if suffix in [".tif", ".tiff"]:
        img.save(dest, format="TIFF")
    elif suffix in [".jpg", ".jpeg"]:
        img.convert("RGB").save(dest, format="JPEG", quality=92, optimize=True)
    else:
        img.save(dest, format="PNG")


def save_icon_72(uploaded_file, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(uploaded_file).convert("RGB")
    img = img.resize((72, 72), Image.Resampling.LANCZOS)
    img.save(dest, format="JPEG", quality=90, optimize=True)


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
    for name in ("6_Glass_Library.py", "5_Glass_Library.py"):
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


def existing_asset(preferred: Path, fallback: Path | None = None) -> Path | None:
    if preferred.exists():
        return preferred
    if fallback is not None and fallback.exists():
        return fallback
    return None


def move_existing_assets(cat_id: str, old_family_code: str, new_family_code: str) -> list[str]:
    if str(old_family_code) == str(new_family_code):
        return []

    old_paths = image_paths(cat_id, old_family_code)
    new_paths = image_paths(cat_id, new_family_code)
    moved = []

    for key in ("icon_T", "icon_R", "full_T", "full_R"):
        old_path = old_paths[key]
        new_path = new_paths[key]
        if not old_path.exists() or new_path.exists():
            continue
        new_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.rename(new_path)
        moved.append(str(new_path.relative_to(APP_ROOT)))

    return moved


# ------------------------------------------------------------
# Page
# ------------------------------------------------------------
st.set_page_config(page_title=t("editor.edit.title", "Edit Glass"), layout="wide")
render_app_sidebar()
st.title(t("editor.edit.title", "Edit Glass Data"))


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

if not DB_PATH.exists():
    st.error(t("errors.editor.db_missing", "DB not found: {path}", path=DB_PATH))
    st.stop()

ensure_unique_index()

# FIX #7: build dropdown from glass_families table, show names, store codes
fam_rows = list_glass_families()
if not fam_rows:
    st.error(t("errors.editor.no_families", "No families found in the glass_families table."))
    st.stop()
fam_codes = [code for code, _ in fam_rows]
fam_names = [name for _, name in fam_rows]

q = st.text_input(
    t("editor.search.label", "Search by cat_id or color name"),
    placeholder=t("editor.search.placeholder", "e.g. 224 or Tomato Red"),
)
results = search_catalog(q)

if not results and q:
    st.info(t("editor.search.no_matches", "No matches."))
    st.stop()

if not q:
    st.caption(t("editor.search.help", "Type a cat_id (224) or a color name to search."))
    st.stop()

# Select a record
options = [f'{r["cat_id"]} — {r.get("color_name", "")}' for r in results]
sel = st.selectbox(t("editor.fields.select_record", "Select record"), options=options)
cat_id = sel.split(" — ", 1)[0].strip()

row = fetch_catalog(cat_id)
if not row:
    st.error(t("errors.editor.record_not_found", "Record not found in glass_catalog."))
    st.stop()

previous_selected_cat_id = st.session_state.get("_edit_selected_cat_id")
selection_token = int(st.session_state.get("_edit_selection_token", 0))
if previous_selected_cat_id != cat_id:
    selection_token += 1
    st.session_state["_edit_selected_cat_id"] = cat_id
    st.session_state["_edit_selection_token"] = selection_token

st.divider()

left, right = st.columns([1.1, 0.9], gap="large")

with st.form(key=f"edit_form_{selection_token}"):
    with left:
        st.subheader(t("editor.fields.catalog", "Catalog: {cat_id}", cat_id=cat_id))

        color_name = st.text_input(
            t("editor.fields.color_name", "Color name"),
            value=row.get("color_name") or "",
            key=f"color_name_{selection_token}",
        )

        # FIX #7: dropdown shows names, maps back to code for storage
        current_code = str(row.get("glass_family") or "1")
        fam_index = fam_codes.index(current_code) if current_code in fam_codes else 0
        sel_fam_index = st.selectbox(
            t("editor.fields.glass_family", "Glass family"),
            options=range(len(fam_names)),
            format_func=lambda i: family_label(fam_codes[i], fam_names[i]),
            index=fam_index,
            key=f"glass_family_{selection_token}",
        )
        glass_family_code = fam_codes[sel_fam_index]

        is_striker = st.checkbox(
            t("editor.fields.striker", "Striker"),
            value=bool(row.get("is_striker") or 0),
            key=f"is_striker_{selection_token}",
        )

        cold_quill_key = f"quill_cold_{selection_token}"
        work_quill_key = f"quill_work_{selection_token}"

        st.markdown(f"**{t('editor.sections.cold', 'Cold Characteristics')}**")
        cold_characteristics = st_quill(
            value=row.get("cold_characteristics") or "",
            html=True,
            toolbar=[{"size": ["8px", "10px", "12px", "14px", "18px", "24px"]},
                     "bold", "italic", "underline",
                     {"list": "ordered"}, {"list": "bullet"}],
            key=cold_quill_key,
        ) or ""

        st.markdown(f"**{t('editor.sections.work', 'Working Notes')}**")
        working_notes = st_quill(
            value=row.get("working_notes") or "",
            html=True,
            toolbar=[{"size": ["8px", "10px", "12px", "14px", "18px", "24px"]},
                     "bold", "italic", "underline",
                     {"list": "ordered"}, {"list": "bullet"}],
            key=work_quill_key,
        ) or ""

    st.caption(
        t(
            "editor.sections.elements_caption",
            "Elements contained. The app will derive a 'may react with' summary automatically.",
        )
    )

    def _as01(x):
        try:
            return int(x) == 1
        except Exception:
            return False

    # FIX #10: removed dead glass_samples legacy query
    _contains_prefill = {k: _as01(row.get(k, 0)) for k in ["se", "su", "cu", "pb", "ag", "au"]}

    e1, e2, e3 = st.columns(3)
    ecols = [e1, e2, e3]
    _contains = {}
    for i, (k, label) in enumerate(ELEMENTS):
        with ecols[i % 3]:
            _contains[k] = 1 if st.checkbox(
                element_full_label(k),
                value=_contains_prefill.get(k, False),
                key=f"edit_contains_{k}_{selection_token}",
            ) else 0

    se = _contains["se"]
    su = _contains["su"]
    cu = _contains["cu"]
    pb = _contains["pb"]
    ag = _contains["ag"]
    au = _contains["au"]

    # Derived "may react with" (display only)
    _reacts = {k: 0 for k, _ in ELEMENTS}
    for k, present in _contains.items():
        if present == 1:
            for tgt in REACT_RULES.get(k, set()):
                _reacts[tgt] = 1

    react_labels = [element_full_label(k) for (k, _) in ELEMENTS if _reacts.get(k, 0) == 1]
    st.markdown(f"**{t('editor.sections.reacts', 'May react with (derived)')}**")
    st.write(", ".join(react_labels) if react_labels else "-")

    st.subheader(t("editor.sections.images", "Images (optional)"))
    st.caption(
        t(
            "editor.images.caption_edit",
            "Upload new full-res TIFF/JPG/PNG for Transmitted (T) and/or Reflected (R). Icons are auto-generated (72x72 JPG) from the uploaded image. If you skip uploads, existing images are kept.",
        )
    )

    # FIX #8: use correct prefix via image_paths helper
    paths = image_paths(cat_id, glass_family_code)
    original_paths = image_paths(cat_id, current_code)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.caption(t("editor.images.icon_t_short", "Icon (T)"))
        icon_t = existing_asset(paths["icon_T"], original_paths["icon_T"]) or PLACEHOLDER_ICON
        st.image(str(icon_t), width="content")
    with c2:
        st.caption(t("editor.images.full_t_short", "Full (T)"))
        full_t = existing_asset(paths["full_T"], original_paths["full_T"]) or PLACEHOLDER_FULL
        st.image(str(full_t), width="content")
    with c3:
        st.caption(t("editor.images.icon_r_short", "Icon (R)"))
        icon_r = existing_asset(paths["icon_R"], original_paths["icon_R"]) or PLACEHOLDER_ICON
        st.image(str(icon_r), width="content")
    with c4:
        st.caption(t("editor.images.full_r_short", "Full (R)"))
        full_r = existing_asset(paths["full_R"], original_paths["full_R"]) or PLACEHOLDER_FULL
        st.image(str(full_r), width="content")

    st.markdown(f"**{t('editor.actions.upload_replacements', 'Upload replacements')}**")
    # FIX #4: defined both uploaders (icon_up_T and icon_up_R were missing)
    up_full_T = st.file_uploader(
        t("editor.images.replace_full_t", "Replace full image - Transmitted (T)"),
        type=["tif", "tiff", "png", "jpg", "jpeg"],
        key=f"replace_full_T_{selection_token}",
    )
    up_full_R = st.file_uploader(
        t("editor.images.replace_full_r", "Replace full image - Reflected (R)"),
        type=["tif", "tiff", "png", "jpg", "jpeg"],
        key=f"replace_full_R_{selection_token}",
    )

    st.divider()
    st.subheader(t("editor.sections.measurements", "Measurements (Reflected / Transmitted)"))

    # Thickness is a physical property of the sample — one shared value for both T and R
    _t_row = fetch_meas(cat_id, "R") or fetch_meas(cat_id, "T") or {}
    thickness_mm = st.number_input(
        t("editor.fields.thickness", "Thickness (mm)"), min_value=0.0, max_value=25.0,
        value=float(_t_row.get("thickness_mm") or 2.0),
        step=0.1, format="%.1f", key=f"thickness_mm_{selection_token}",
    )

    mcol1, mcol2 = st.columns(2, gap="large")

    MODE_LABELS = {
        "R": t("editor.tabs.reflected", "Reflected"),
        "T": t("editor.tabs.transmitted", "Transmitted"),
    }
    MEASUREMENT_LABELS = {
        "R": t("editor.fields.red", "Red (R)"),
        "G": t("editor.fields.green", "Green (G)"),
        "B": t("editor.fields.blue", "Blue (B)"),
        "H": t("editor.fields.hue", "Hue (H)"),
        "S": t("editor.fields.saturation", "Saturation (S)"),
        "V": t("editor.fields.brightness", "Brightness (B)"),
    }

    def meas_editor(mode: str, container):
        m = fetch_meas(cat_id, mode) or {}
        with container:
            st.markdown(f"**{MODE_LABELS.get(mode, mode)}**")
            R = st.number_input(
                MEASUREMENT_LABELS["R"], 0, 255, int(m.get("R") or 0), 1, key=f"{mode}_R_{selection_token}"
            )
            G = st.number_input(
                MEASUREMENT_LABELS["G"], 0, 255, int(m.get("G") or 0), 1, key=f"{mode}_G_{selection_token}"
            )
            B = st.number_input(
                MEASUREMENT_LABELS["B"], 0, 255, int(m.get("B") or 0), 1, key=f"{mode}_B_{selection_token}"
            )
            H = st.number_input(
                MEASUREMENT_LABELS["H"], 0, 360, int(m.get("H") or 0), 1, key=f"{mode}_H_{selection_token}"
            )
            S = st.number_input(
                MEASUREMENT_LABELS["S"], 0, 100, int(m.get("S") or 0), 1, key=f"{mode}_S_{selection_token}"
            )
            V = st.number_input(
                MEASUREMENT_LABELS["V"], 0, 100, int(m.get("V") or 0), 1, key=f"{mode}_V_{selection_token}"
            )
            return {
                "cat_id": cat_id,
                "mode": mode,
                "R": int(R), "G": int(G), "B": int(B),
                "H": int(H), "S": int(S), "V": int(V),
                "thickness_mm": float(thickness_mm),
            }

    mr = meas_editor("R", mcol1)
    mt = meas_editor("T", mcol2)

    st.divider()

    # --- Action Buttons ---
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        save = st.form_submit_button(t("editor.actions.save_changes", "Save Changes"), type="primary")
    with btn_col2:
        cancel = st.form_submit_button(t("editor.actions.cancel", "Cancel"))

if cancel:
    target = pick_library_page()
    if not target or not switch_to_page(target):
        st.warning(
            t(
                "editor.warnings.library_navigation_failed",
                "Could not navigate to the Glass Library page. Please use the sidebar.",
            )
        )

if save:
    try:
        with get_con() as con:
            # FIX #1 & #3: upsert_catalog now called with correct columns
            upsert_catalog(con, {
                "cat_id":               cat_id,
                "color_name":           (color_name or "").strip(),
                "glass_family":         glass_family_code,
                "is_striker":           int(is_striker),
                "se": se, "su": su, "cu": cu, "pb": pb, "ag": ag, "au": au,
                "cold_characteristics": (cold_characteristics or "").strip() or None,
                "working_notes":        (working_notes or "").strip() or None,
            })

            # FIX #2: upsert_meas now called with con as first argument
            upsert_meas(con, mr)
            upsert_meas(con, mt)

            con.commit()

        # FIX #5: images saved using correct naming convention via image_paths()
        saved_files = []
        moved_files = move_existing_assets(cat_id, current_code, glass_family_code)
        paths = image_paths(cat_id, glass_family_code)

        if up_full_T is not None:
            save_full_image(up_full_T, paths["full_T"])
            save_icon_72(up_full_T, paths["icon_T"])
            saved_files.append(str(paths["full_T"].relative_to(APP_ROOT)))
            saved_files.append(str(paths["icon_T"].relative_to(APP_ROOT)))

        if up_full_R is not None:
            save_full_image(up_full_R, paths["full_R"])
            save_icon_72(up_full_R, paths["icon_R"])
            saved_files.append(str(paths["full_R"].relative_to(APP_ROOT)))
            saved_files.append(str(paths["icon_R"].relative_to(APP_ROOT)))

        st.cache_data.clear()
        st.success(t("editor.messages.saved", "Saved."))
        if moved_files:
            st.info(
                t(
                    "editor.messages.moved_files",
                    "Moved existing files:\n- {items}",
                    items="\n- ".join(moved_files),
                )
            )
        if saved_files:
            st.info(
                t(
                    "editor.messages.saved_files",
                    "Saved files:\n- {items}",
                    items="\n- ".join(saved_files),
                )
            )

    except sqlite3.Error as e:
        st.error(t("errors.editor.sqlite", "SQLite error: {error}", error=e))
    except Exception as e:
        st.error(t("errors.editor.generic", "Error: {error}", error=e))

st.divider()
st.subheader(t("editor.danger.title", "Danger Zone"))

with st.container():
    st.markdown(f"**{t('editor.danger.delete_record', 'Delete record')}**")
    confirm = st.text_input(
        t("editor.danger.confirm", "Type cat_id to confirm delete"),
        key=f"delete_confirm_{selection_token}",
    )
    if st.button(t("editor.danger.delete_button", "Delete record")):
        if confirm.strip() != cat_id:
            st.error(t("editor.danger.confirm_mismatch", "Confirmation text does not match cat_id."))
        else:
            try:
                with get_con() as con:
                    con.execute("BEGIN;")
                    con.execute("DELETE FROM glass_measurements WHERE cat_id = ?", (cat_id,))
                    con.execute("DELETE FROM glass_catalog WHERE cat_id = ?", (cat_id,))
                    con.commit()
                st.cache_data.clear()
                st.success(t("messages.editor.deleted", "Deleted {cat_id}.", cat_id=cat_id))
                target = pick_library_page()
                if target:
                    switch_to_page(target)
            except Exception as e:
                st.error(t("errors.editor.delete_failed", "Delete failed: {error}", error=e))
