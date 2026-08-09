from __future__ import annotations

import base64
import html
import json
import mimetypes
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from i18n import render_app_sidebar, t, translate_element_name, translate_family_name, translate_mode_name

APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "glass_library.sqlite"
IMG_ROOT = APP_ROOT / "images"
MISSING_FULL = IMG_ROOT / "_placeholders" / "missing_full.tiff"
MISSING_ICON = IMG_ROOT / "_placeholders" / "missing_icon.jpg"
DETAIL_PAGE = "pages/8_Glass_Detail.py"
COMPARE_PAGE = "pages/15_Glass_Compare.py"
MAX_COMPARE = 4
render_html_frame = getattr(st, "iframe", components.html)

FAMILY_PREFIX_BY_CODE = {
    "1": "opal",
    "2": "transparent",
    "3": "tint",
}

ELEMENT_MAP = {
    "Selenium": "se",
    "Sulfur": "su",
    "Copper": "cu",
    "Lead": "pb",
    "Silver": "ag",
    "Gold": "au",
}

REACTION_RULES = {
    "Selenium": ["Copper", "Lead", "Silver"],
    "Sulfur": ["Copper", "Lead", "Silver"],
    "Copper": ["Selenium", "Sulfur", "Silver"],
    "Lead": ["Selenium", "Sulfur"],
    "Silver": ["Selenium", "Sulfur", "Copper"],
    "Gold": [],
}

ELEMENT_COLOURS = {
    "Selenium": "#e8a020",
    "Sulfur": "#e8d020",
    "Copper": "#20a0e8",
    "Lead": "#909090",
    "Silver": "#c0c0c0",
    "Gold": "#d4a020",
}

st.set_page_config(page_title=t("library.title", "Glass Library"), layout="wide")
render_app_sidebar()

SORT_OPTIONS = ["Hue (H)", "Product ID", "Color name"]
INTERACTION_OPTIONS = ["Contains", "May react with"]


def mode_label(mode: str) -> str:
    return translate_mode_name(mode)


def sort_label_display(value: str) -> str:
    labels = {
        "Hue (H)": t("shared.sort.hue", "Hue (H)"),
        "Product ID": t("shared.sort.product_id", "Product ID"),
        "Color name": t("shared.sort.color_name", "Color name"),
    }
    return labels.get(value, value)


def interaction_label(value: str) -> str:
    labels = {
        "Contains": t("shared.interaction.contains", "Contains"),
        "May react with": t("shared.interaction.may_react_with", "May react with"),
    }
    return labels.get(value, value)


def safe_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if pd.isna(value):
            return default
        text = str(value).strip()
        if text == "" or text.lower() == "nan":
            return default
        return int(float(text))
    except Exception:
        return default


def family_prefix(code: str, name: str) -> str:
    prefix = FAMILY_PREFIX_BY_CODE.get(str(code))
    if prefix:
        return prefix

    label = str(name or "").strip().lower()
    if "opal" in label:
        return "opal"
    if "trans" in label:
        return "transparent"
    if "tint" in label:
        return "tint"
    return label.replace(" ", "_") or "other"


def row_prefix(row: pd.Series | object) -> str:
    if isinstance(row, pd.Series):
        code = row.get("glass_family")
        name = row.get("family_name") or row.get("glass_family")
    else:
        code = getattr(row, "glass_family", "")
        name = getattr(row, "family_name", "") or getattr(row, "glass_family", "")
    return family_prefix(str(code or ""), str(name or ""))


def icon_path(cat_id: str, prefix: str, mode: str) -> Path:
    return IMG_ROOT / "icons" / f"{prefix}_{mode}_{cat_id}.jpg"


def full_path(cat_id: str, prefix: str, mode: str) -> Path | None:
    for suffix in (".tiff", ".tif"):
        candidate = IMG_ROOT / "full" / f"{prefix}_{mode}_{cat_id}{suffix}"
        if candidate.exists():
            return candidate
    return None


def first_existing_icon(cat_id: str, prefix: str, preferred_mode: str) -> Path | None:
    for mode in (preferred_mode, "T" if preferred_mode == "R" else "R"):
        candidate = icon_path(cat_id, prefix, mode)
        if candidate.exists():
            return candidate
    return None


def image_data_uri(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def preview_image_markup(path: Path | None, alt: str) -> str:
    if path is None:
        return '<div class="library-preview-slot"></div>'
    src = image_data_uri(path)
    return (
        '<div class="library-preview-slot">'
        f'<img src="{src}" alt="{html.escape(alt, quote=True)}" loading="lazy">'
        '</div>'
    )


def current_detail_target() -> str | None:
    candidate = APP_ROOT / DETAIL_PAGE
    return DETAIL_PAGE if candidate.exists() else None


def current_compare_target() -> str | None:
    candidate = APP_ROOT / COMPARE_PAGE
    return COMPARE_PAGE if candidate.exists() else None


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


def datasheet_url(glass_id: str, family_name: str) -> str:
    return (
        "Glass_Detail"
        f"?cat_id={quote(str(glass_id), safe='')}"
        f"&return_page={quote('pages/6_Glass_Library.py', safe='')}"
        f"&return_label={quote(t('library.title', 'Glass Library'), safe='')}"
        f"&return_family={quote(str(family_name), safe='')}"
    )


def datasheet_link_markup(glass_id: str, family_name: str) -> str:
    return f"""
    <a class="glass-datasheet-link"
       href="{html.escape(datasheet_url(glass_id, family_name), quote=True)}"
       target="_self"
       title="{html.escape(t('library.detail.open_datasheet', 'Open full datasheet'), quote=True)}">
        {html.escape(str(glass_id))}
    </a>
    """


def db_cache_token() -> tuple[int, int]:
    if not DB_PATH.exists():
        return (0, 0)
    stat = DB_PATH.stat()
    return (stat.st_mtime_ns, stat.st_size)


@st.cache_data
def load_catalog(_db_token: tuple[int, int]) -> pd.DataFrame:
    if not DB_PATH.exists():
        st.error(t("errors.editor.db_missing", "Missing database: {path}", path=DB_PATH))
        st.stop()

    with sqlite3.connect(DB_PATH) as con:
        try:
            return pd.read_sql_query(
                """
                SELECT
                    cat_id AS glass_id,
                    color_name,
                    glass_family,
                    is_striker,
                    se,
                    su,
                    cu,
                    pb,
                    ag,
                    au,
                    cold_characteristics,
                    working_notes
                FROM glass_catalog
                ORDER BY cat_id;
                """,
                con,
            )
        except Exception as exc:
            st.error(t("library.errors.catalog_load", "Failed to load catalog data: {error}", error=exc))
            st.stop()


@st.cache_data
def load_measurements(_db_token: tuple[int, int]) -> pd.DataFrame:
    if not DB_PATH.exists():
        st.error(t("errors.editor.db_missing", "Missing database: {path}", path=DB_PATH))
        st.stop()

    with sqlite3.connect(DB_PATH) as con:
        try:
            return pd.read_sql_query(
                """
                SELECT
                    cat_id AS glass_id,
                    mode,
                    R AS r,
                    G AS g,
                    B AS b,
                    H AS h,
                    S AS s,
                    V AS v,
                    thickness_mm
                FROM glass_measurements
                ORDER BY cat_id, mode;
                """,
                con,
            )
        except Exception as exc:
            st.error(t("library.errors.measurement_load", "Failed to load measurement data: {error}", error=exc))
            st.stop()


@st.cache_data
def load_families(_db_token: tuple[int, int]) -> pd.DataFrame:
    if not DB_PATH.exists():
        st.error(t("errors.editor.db_missing", "Missing database: {path}", path=DB_PATH))
        st.stop()

    with sqlite3.connect(DB_PATH) as con:
        try:
            return pd.read_sql_query(
                """
                SELECT code, name
                FROM glass_families
                ORDER BY id;
                """,
                con,
            )
        except Exception as exc:
            st.error(t("library.errors.family_load", "Failed to load family data: {error}", error=exc))
            st.stop()


def measurement_row(measurements: pd.DataFrame, glass_id: str, mode: str) -> pd.Series | None:
    matches = measurements[
        (measurements["glass_id"].astype(str) == str(glass_id))
        & (measurements["mode"].astype(str).str.upper() == mode)
    ]
    if matches.empty:
        return None
    return matches.iloc[0]


def normalize_compare_ids(values) -> list[str]:
    if isinstance(values, str):
        values = [values]
    elif values is None:
        values = []

    normalized: list[str] = []
    for value in values:
        glass_id = str(value or "").strip()
        if not glass_id or glass_id in normalized:
            continue
        normalized.append(glass_id)
    return normalized[:MAX_COMPARE]


def toggle_compare_selection(glass_id: str, checkbox_key: str) -> None:
    compare_ids = normalize_compare_ids(st.session_state.get("compare_glass_ids", []))
    is_checked = bool(st.session_state.get(checkbox_key, False))

    if is_checked:
        if glass_id not in compare_ids:
            compare_ids.append(glass_id)
    else:
        compare_ids = [item for item in compare_ids if item != glass_id]

    st.session_state["compare_glass_ids"] = normalize_compare_ids(compare_ids)


def apply_sort(
    filtered: pd.DataFrame,
    measurements: pd.DataFrame,
    preview_mode: str,
    sort_label: str,
) -> pd.DataFrame:
    if filtered.empty:
        return filtered

    if sort_label == "Product ID":
        return filtered.sort_values(["glass_id", "color_name"], na_position="last")

    if sort_label == "Color name":
        return filtered.sort_values(["color_name", "glass_id"], na_position="last")

    primary = measurements[measurements["mode"] == preview_mode][["glass_id", "h", "s", "v"]].copy()
    primary = primary.rename(
        columns={"h": "_sort_h", "s": "_sort_s", "v": "_sort_v"}
    )

    fallback_mode = "T" if preview_mode == "R" else "R"
    fallback = measurements[measurements["mode"] == fallback_mode][["glass_id", "h", "s", "v"]].copy()
    fallback = fallback.rename(
        columns={"h": "_fallback_h", "s": "_fallback_s", "v": "_fallback_v"}
    )

    merged = filtered.merge(primary, on="glass_id", how="left")
    merged = merged.merge(fallback, on="glass_id", how="left")
    merged["_sort_h"] = merged["_sort_h"].fillna(merged["_fallback_h"])
    merged["_sort_s"] = merged["_sort_s"].fillna(merged["_fallback_s"])
    merged["_sort_v"] = merged["_sort_v"].fillna(merged["_fallback_v"])
    merged["_sort_missing_h"] = merged["_sort_h"].isna()

    merged = merged.sort_values(
        ["_sort_missing_h", "_sort_h", "_sort_s", "_sort_v", "color_name", "glass_id"],
        na_position="last",
    )

    return merged.drop(
        columns=[
            "_fallback_h",
            "_fallback_s",
            "_fallback_v",
            "_sort_missing_h",
        ],
        errors="ignore",
    )


def element_summary(row: pd.Series) -> str:
    labels = []
    for label, column in ELEMENT_MAP.items():
        if safe_int(row.get(column), 0) == 1:
            labels.append(label)
    return ", ".join(labels) if labels else "-"


def reactive_summary(row: pd.Series) -> str:
    reacts = []
    for label, column in ELEMENT_MAP.items():
        if safe_int(row.get(column), 0) != 1:
            continue
        for reactive_label in REACTION_RULES.get(label, []):
            if reactive_label not in reacts:
                reacts.append(reactive_label)
    return ", ".join(reacts) if reacts else "-"


def element_labels(row: pd.Series) -> list[str]:
    labels = []
    for label, column in ELEMENT_MAP.items():
        if safe_int(row.get(column), 0) == 1:
            labels.append(label)
    return labels


def reactive_labels(row: pd.Series) -> list[str]:
    reacts = []
    for label in element_labels(row):
        for reactive_label in REACTION_RULES.get(label, []):
            if reactive_label not in reacts:
                reacts.append(reactive_label)
    return reacts


def badge_markup(labels: list[str], *, muted: bool = False) -> str:
    if not labels:
        return '<div style="font-family:sans-serif;font-size:14px;color:#666;">-</div>'

    spans = []
    for label in labels:
        bg = ELEMENT_COLOURS.get(label, "#888")
        opacity = "opacity:0.7;" if muted else ""
        display_label = translate_element_name(label)
        text = f"* {display_label}" if muted else display_label
        spans.append(
            f'<span style="background:{bg};color:white;font-size:11px;'
            f'font-weight:bold;padding:2px 7px;border-radius:3px;margin-right:4px;'
            f'{opacity}">{html.escape(text)}</span>'
        )

    return (
        '<div style="font-family:sans-serif;margin-top:4px;line-height:2.2;">'
        + "".join(spans)
        + "</div>"
    )


def striker_badge_markup(is_striker: bool) -> str:
    if not is_striker:
        return ""

    return (
        '<div style="font-family:sans-serif;margin-top:4px;line-height:2.2;">'
        '<span style="background:#e05020;color:white;font-size:11px;'
        'font-weight:bold;padding:2px 8px;border-radius:3px;margin-right:8px;">'
        f"{t('compare.badge.striker', 'STRIKER')}</span></div>"
    )


def render_notes(title: str, html_text: str | None) -> None:
    markup = note_markup(html_text)
    if not markup:
        return
    st.markdown(f"### {title}")
    st.markdown(markup, unsafe_allow_html=True)


def note_markup(raw_text: str | None) -> str:
    text = (raw_text or "").strip()
    if not text:
        return ""

    if text.lstrip().startswith("<"):
        body = text
    else:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
        if not paragraphs:
            paragraphs = [normalized.strip()]
        body = "".join(
            f"<p>{html.escape(part).replace(chr(10), '<br>')}</p>"
            for part in paragraphs
        )

    return f"""
    <div style="font-family:sans-serif;font-size:14px;line-height:1.35;">
      <style>
        div[data-note-body] p {{ margin: 0 0 0.35em 0; }}
        div[data-note-body] p:last-child {{ margin-bottom: 0; }}
        div[data-note-body] ul, div[data-note-body] ol {{ margin: 0.2em 0 0.4em 1.2em; }}
        div[data-note-body] li {{ margin: 0 0 0.2em 0; }}
      </style>
      <div data-note-body="1">{body}</div>
    </div>
    """


def scroll_to_row(anchor_id: str, offset: int = 90) -> None:
    render_html_frame(
        f"""
        <script>
        const anchorId = {json.dumps(anchor_id)};
        const offset = {offset};
        const scrollNow = () => {{
          const anchor = window.parent.document.getElementById(anchorId);
          if (!anchor) return;
          const rect = anchor.getBoundingClientRect();
          const top = rect.top + window.parent.scrollY - offset;
          window.parent.scrollTo({{ top: Math.max(top, 0), behavior: "auto" }});
        }};
        window.parent.requestAnimationFrame(() => setTimeout(scrollNow, 40));
        </script>
        """,
        height=1,
    )


db_token = db_cache_token()
families = load_families(db_token).copy()
catalog = load_catalog(db_token).copy()
measurements = load_measurements(db_token).copy()

if families.empty:
    st.error(t("library.messages.family_table_empty", "The glass_families table is empty."))
    st.stop()

families["code"] = families["code"].astype(str)
families["name"] = families["name"].astype(str)
families["prefix"] = [
    family_prefix(code, name)
    for code, name in zip(families["code"], families["name"])
]

catalog["glass_id"] = catalog["glass_id"].astype(str)
catalog["glass_family"] = catalog["glass_family"].astype(str)
measurements["glass_id"] = measurements["glass_id"].astype(str)
measurements["mode"] = measurements["mode"].astype(str).str.upper()

st.sidebar.header(t("library.sidebar.title", "Browse"))

family_names = families["name"].tolist()
family_options = ["All"] + family_names
query_return_family = st.query_params.get("return_family")
return_family = query_return_family or st.session_state.pop("detail_return_family", None)
if query_return_family in family_options:
    st.session_state["library_family_name"] = str(query_return_family)
    st.query_params.clear()
    st.rerun()

default_index = family_options.index(return_family) if return_family in family_options else 0
if return_family in family_options:
    st.session_state["library_family_name"] = return_family
family_name = st.sidebar.selectbox(
    t("editor.fields.glass_family", "Glass family"),
    family_options,
    index=default_index,
    key="library_family_name",
    format_func=lambda value: translate_family_name(None, value),
)

if family_name == "All":
    selected_family_code = "all"
    family_label_value = t("shared.family.all_families", "All families")
else:
    family_row = families[families["name"] == family_name].iloc[0]
    selected_family_code = str(family_row["code"])
    family_label_value = translate_family_name(selected_family_code, family_name)

preview_mode = st.sidebar.radio(
    t("library.fields.preview_mode", "Preview Mode"),
    ["R", "T"],
    index=0,
    format_func=translate_mode_name,
)
sort_label = st.sidebar.selectbox(
    t("library.fields.sort_by", "Sort by"),
    SORT_OPTIONS,
    index=0,
    format_func=sort_label_display,
)

q = st.sidebar.text_input(t("library.fields.search", "Search (id or color)"), "")
only_strikers = st.sidebar.checkbox(t("library.fields.striking_only", "Striking only"), value=False)
interaction_selected = st.sidebar.radio(
    t("library.fields.interaction", "Interaction"),
    INTERACTION_OPTIONS,
    index=0,
    format_func=interaction_label,
)

selected_element_cols = []
for label, column in ELEMENT_MAP.items():
    if st.sidebar.checkbox(translate_element_name(label), value=False, key=f"elem_{column}"):
        selected_element_cols.append(column)

cols_per_row = st.sidebar.slider(t("library.fields.grid_columns", "Grid columns"), 3, 5, 4)

if family_name == "All":
    filtered = catalog.copy()
else:
    filtered = catalog[catalog["glass_family"] == selected_family_code].copy()

if q.strip():
    query = q.strip().lower()
    filtered = filtered[
        filtered["glass_id"].str.lower().str.contains(query)
        | filtered["color_name"].fillna("").astype(str).str.lower().str.contains(query)
    ]

if only_strikers:
    filtered = filtered[filtered["is_striker"].fillna(0).astype(int) == 1]

if selected_element_cols:
    mask = False
    if interaction_selected == "Contains":
        for column in selected_element_cols:
            mask = mask | (filtered[column].fillna(0).astype(int) == 1)
    else:
        reactive_columns = set()
        for selected_column in selected_element_cols:
            selected_label = next(
                (label for label, column in ELEMENT_MAP.items() if column == selected_column),
                None,
            )
            if not selected_label:
                continue
            for reactive_label in REACTION_RULES.get(selected_label, []):
                reactive_columns.add(ELEMENT_MAP[reactive_label])
        for column in reactive_columns:
            mask = mask | (filtered[column].fillna(0).astype(int) == 1)
    if not isinstance(mask, bool):
        filtered = filtered[mask]

filtered = apply_sort(filtered, measurements, preview_mode, sort_label)

st.title(t("library.title", "Glass Library"))
st.markdown(
    """
    <style>
      .glass-datasheet-link {
        align-items: center;
        border-radius: 0.5rem;
        border: 1px solid rgba(49, 51, 63, 0.2);
        display: inline-flex;
        font-family: sans-serif;
        font-size: 0.95rem;
        font-weight: 400;
        justify-content: center;
        line-height: 1.4;
        min-height: 2.35rem;
        padding: 0.38rem 0.75rem;
        text-decoration: none !important;
      }
      .glass-datasheet-link {
        background: #ffffff;
        color: #31333f !important;
      }
      .glass-datasheet-link:hover {
        border-color: rgba(49, 51, 63, 0.45);
        color: #31333f !important;
      }
      .library-preview-slot {
        align-items: center;
        background: #eeeeee;
        border-radius: 0.5rem;
        display: flex;
        flex: 0 0 128px;
        height: 128px !important;
        justify-content: center;
        margin-bottom: 0.75rem;
        overflow: hidden;
        width: 128px !important;
      }
      .library-preview-slot img {
        display: block !important;
        height: 128px !important;
        max-height: none !important;
        max-width: none !important;
        min-height: 128px !important;
        min-width: 128px !important;
        object-fit: cover !important;
        width: 128px !important;
      }
      .library-intro-text {
        color: #6b7280;
        font-size: 1rem;
        line-height: 1.55;
        margin: 0.2rem 0 1.05rem 0;
        max-width: 1180px;
      }
      .st-key-library_compare_bar {
        background: rgba(255, 255, 255, 0.96);
        border-radius: 0.5rem;
        box-shadow: 0 1px 6px rgba(49, 51, 63, 0.08);
        margin: 0.65rem 0 1rem 0;
        padding: 0.25rem 0.45rem 0.1rem 0.45rem;
      }
      [data-testid="stLayoutWrapper"]:has(.st-key-library_compare_bar) {
        position: sticky;
        top: 4.25rem;
        z-index: 999;
      }
      .st-key-library_compare_bar [data-testid="stCaptionContainer"] {
        padding-top: 0;
      }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    f"""
    <div class="library-intro-text">
      {html.escape(t(
        "library.text.imaging_basis",
        "The Glass Library uses carefully controlled digital imaging rather than laboratory spectrophotometry to characterize each glass sample. This approach was chosen to keep the project accessible while acknowledging the practical realities of working with handmade glass, where thickness, surface texture, bubbles, and even color can vary slightly from sheet to sheet and production run to production run. The resulting images and color measurements provide a consistent basis for comparing samples within the library, but they should be understood as approximations of visual appearance rather than precise spectral measurements. The library is intended as a practical design and exploration tool that helps artists navigate color relationships and predict trends with changing thickness, while recognizing that the appearance of any finished piece will ultimately depend on the unique characteristics of the individual glass and the conditions under which it is viewed.",
      ))}
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption(
    t(
        "library.caption.summary",
        "{count} items ({family}, preview: {preview}, sorted by: {sort})",
        count=len(filtered),
        family=family_label_value,
        preview=translate_mode_name(preview_mode).lower(),
        sort=sort_label_display(sort_label).lower(),
    )
)
st.caption(
    t(
        "library.notes.datum",
        "Library colors are based on measurements taken from each physical sample at its recorded thickness under broad daylight-balanced illumination. Changes in thickness, lighting, and batch variation can shift the visible read away from this reference.",
    )
)

compare_ids = normalize_compare_ids(st.session_state.get("compare_glass_ids", []))
if compare_ids != st.session_state.get("compare_glass_ids", []):
    st.session_state["compare_glass_ids"] = compare_ids

compare_target = current_compare_target()
with st.container(border=True, key="library_compare_bar"):
    compare_col, clear_col, note_col = st.columns([0.18, 0.16, 0.66], gap="small")
    with compare_col:
        if st.button(
            t("library.actions.compare_selected", "Compare selected"),
            key="library_compare_selected",
            width="content",
            disabled=len(compare_ids) < 2 or compare_target is None,
        ):
            if compare_target and switch_to_page(compare_target):
                st.stop()
            st.warning(t("library.messages.compare_navigation_failed", "Could not navigate to the compare page."))
    with clear_col:
        if st.button(
            t("library.actions.clear_compare", "Clear compare"),
            key="library_clear_compare",
            width="content",
            disabled=not compare_ids,
        ):
            st.session_state["compare_glass_ids"] = []
            st.rerun()
    with note_col:
        if compare_ids:
            st.caption(
                t(
                    "library.messages.compare_set",
                    "Compare set: {items}",
                    items=" · ".join(html.escape(glass_id) for glass_id in compare_ids),
                )
            )
        else:
            st.caption(t("library.messages.compare_hint", "Select 2-4 samples to compare on a dedicated page."))

    st.caption(
        t(
            "library.messages.detail_page_hint",
            "Click a catalog ID to open its full datasheet on a dedicated detail page.",
        )
    )

if filtered.empty:
    st.info(t("library.messages.empty", "No glass samples match the current filters."))
    st.stop()

valid_ids = filtered["glass_id"].tolist()
selected_glass_id = st.session_state.get("selected_glass_id")

library_state = (selected_family_code, preview_mode, q.strip(), bool(only_strikers))
previous_state = st.session_state.get("_library_state")
if previous_state != library_state:
    st.session_state["_library_state"] = library_state
    if selected_glass_id not in valid_ids:
        selected_glass_id = valid_ids[0]
        st.session_state["selected_glass_id"] = selected_glass_id
elif selected_glass_id not in valid_ids:
    selected_glass_id = valid_ids[0]
    st.session_state["selected_glass_id"] = selected_glass_id

pending_scroll_id = st.session_state.pop("_library_scroll_to", None)

for start in range(0, len(filtered), cols_per_row):
    row_slice = filtered.iloc[start : start + cols_per_row]
    row_ids = row_slice["glass_id"].astype(str).tolist()
    row_anchor_id = f"library-row-{start}"

    if str(selected_glass_id) in row_ids:
        st.markdown(
            f'<div id="{row_anchor_id}" style="height:1px;"></div>',
            unsafe_allow_html=True,
        )
        if pending_scroll_id == str(selected_glass_id):
            scroll_to_row(row_anchor_id)

    cols = st.columns(cols_per_row)
    for idx, row in enumerate(row_slice.itertuples(index=False)):
        glass_id = str(row.glass_id)
        is_comparing = glass_id in compare_ids
        compare_key = f"compare_{selected_family_code}_{preview_mode}_{glass_id}"
        with cols[idx]:
            with st.container(border=True):
                item_prefix = row_prefix(pd.Series(row._asdict()))
                icon = first_existing_icon(glass_id, item_prefix, preview_mode)
                if icon is None and MISSING_ICON.exists():
                    icon = MISSING_ICON
                st.markdown(
                    preview_image_markup(icon, f"{glass_id} {(row.color_name or '').strip()}"),
                    unsafe_allow_html=True,
                )

                st.caption((row.color_name or "").strip() or t("library.messages.unnamed_sample", "Unnamed sample"))
                st.markdown(
                    datasheet_link_markup(glass_id, family_name),
                    unsafe_allow_html=True,
                )

                if st.session_state.get(compare_key) != is_comparing:
                    st.session_state[compare_key] = is_comparing
                compare_toggle_col, compare_label_col = st.columns([0.22, 0.78], gap="small")
                with compare_toggle_col:
                    st.checkbox(
                        t("library.detail.compare", "Compare"),
                        key=compare_key,
                        label_visibility="collapsed",
                        disabled=(not is_comparing and len(compare_ids) >= MAX_COMPARE),
                        on_change=toggle_compare_selection,
                        args=(glass_id, compare_key),
                    )
                with compare_label_col:
                    st.markdown(
                        f"""
                        <div style="
                            font-family:sans-serif;
                            font-size:12px;
                            color:#555;
                            line-height:1.2;
                            padding-top:0.28rem;
                        ">
                            {html.escape(t("library.detail.compare", "Compare"))}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
