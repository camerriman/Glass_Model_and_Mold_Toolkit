from __future__ import annotations

import html
import json
import re
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "glass_library.sqlite"
IMG_ROOT = APP_ROOT / "images"
MISSING_FULL = IMG_ROOT / "_placeholders" / "missing_full.tiff"
MISSING_ICON = IMG_ROOT / "_placeholders" / "missing_icon.jpg"
DETAIL_PAGE = "pages/8_Glass_Detail.py"

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

MODE_LABELS = {
    "R": "Reflected",
    "T": "Transmitted",
}

st.set_page_config(page_title="Glass Library", layout="wide")


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


def current_detail_target() -> str | None:
    candidate = APP_ROOT / DETAIL_PAGE
    return DETAIL_PAGE if candidate.exists() else None


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


@st.cache_data
def load_catalog() -> pd.DataFrame:
    if not DB_PATH.exists():
        st.error(f"Missing database: {DB_PATH}")
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
            st.error(f"Failed to load catalog data: {exc}")
            st.stop()


@st.cache_data
def load_measurements() -> pd.DataFrame:
    if not DB_PATH.exists():
        st.error(f"Missing database: {DB_PATH}")
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
            st.error(f"Failed to load measurement data: {exc}")
            st.stop()


@st.cache_data
def load_families() -> pd.DataFrame:
    if not DB_PATH.exists():
        st.error(f"Missing database: {DB_PATH}")
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
            st.error(f"Failed to load family data: {exc}")
            st.stop()


def measurement_row(measurements: pd.DataFrame, glass_id: str, mode: str) -> pd.Series | None:
    matches = measurements[
        (measurements["glass_id"].astype(str) == str(glass_id))
        & (measurements["mode"].astype(str).str.upper() == mode)
    ]
    if matches.empty:
        return None
    return matches.iloc[0]


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
        text = f"* {label}" if muted else label
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
        "STRIKER</span></div>"
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


def render_detail_panel(
    base_row: pd.Series,
    row_r: pd.Series | None,
    row_t: pd.Series | None,
    selected_glass_id: str,
    family_name: str,
    selected_prefix: str,
) -> None:
    title = str(base_row.get("color_name") or "").strip()
    st.subheader(
        f"{selected_glass_id}  {title}" if title else str(selected_glass_id)
    )

    st.markdown(
        striker_badge_markup(safe_int(base_row.get("is_striker"), 0) == 1),
        unsafe_allow_html=True,
    )

    if current_detail_target():
        if st.button(
            "Open full datasheet",
            key=f"open_datasheet_{selected_glass_id}",
            width="content",
        ):
            st.session_state["detail_glass_id"] = str(selected_glass_id)
            st.session_state["detail_return_page"] = "pages/6_Glass_Library.py"
            st.session_state["detail_return_label"] = "Glass Library"
            st.session_state["detail_return_family"] = family_name
            if not switch_to_page(DETAIL_PAGE):
                st.warning("Could not navigate to the full datasheet page.")

    image_cols = st.columns(2, gap="large")
    for column, mode in zip(image_cols, ("R", "T")):
        measurement = row_r if mode == "R" else row_t
        with column:
            st.markdown(f"### {MODE_LABELS[mode]}")
            image = full_path(str(selected_glass_id), selected_prefix, mode)
            if image is not None:
                st.image(str(image), width="content")
            elif MISSING_FULL.exists():
                st.image(str(MISSING_FULL), width="content")
            elif MISSING_ICON.exists():
                st.image(str(MISSING_ICON), width="content")

            if measurement is None:
                st.write("No measurement data for this mode.")
            else:
                st.markdown(
                    "\n".join(
                        [
                            f"**RGB:** ({measurement.get('r')}, {measurement.get('g')}, {measurement.get('b')})  ",
                            f"**HSB:** ({measurement.get('h')}, {measurement.get('s')}, {measurement.get('v')})  ",
                            f"**Thickness:** {measurement.get('thickness_mm') or '-'} mm",
                        ]
                    )
                )

    st.markdown("### Elements Present")
    st.markdown(
        badge_markup(element_labels(base_row)),
        unsafe_allow_html=True,
    )

    st.markdown("### Reactive Potential")
    st.markdown(
        badge_markup(reactive_labels(base_row), muted=True),
        unsafe_allow_html=True,
    )

    render_notes("Cold Characteristics", base_row.get("cold_characteristics"))
    render_notes("Working Notes", base_row.get("working_notes"))


def scroll_to_row(anchor_id: str, offset: int = 90) -> None:
    components.html(
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
        height=0,
    )


families = load_families().copy()
catalog = load_catalog().copy()
measurements = load_measurements().copy()

if families.empty:
    st.error("The glass_families table is empty.")
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

st.sidebar.header("Browse")

return_family = st.session_state.pop("detail_return_family", None)
family_names = families["name"].tolist()
default_index = family_names.index(return_family) if return_family in family_names else 0
family_name = st.sidebar.selectbox("Family", family_names, index=default_index)

family_row = families[families["name"] == family_name].iloc[0]
selected_family_code = str(family_row["code"])
selected_prefix = str(family_row["prefix"])

preview_label = st.sidebar.radio("Preview Mode", ["Reflected", "Transmitted"], index=0)
preview_mode = "R" if preview_label == "Reflected" else "T"
sort_label = st.sidebar.selectbox(
    "Sort by",
    ["Hue (H)", "Product ID", "Color name"],
    index=0,
)

q = st.sidebar.text_input("Search (id or color)", "")
only_strikers = st.sidebar.checkbox("Striking only", value=False)
interaction_label = st.sidebar.radio("Interaction", ["Contains", "May react with"], index=0)

selected_element_cols = []
for label, column in ELEMENT_MAP.items():
    if st.sidebar.checkbox(label, value=False, key=f"elem_{column}"):
        selected_element_cols.append(column)

cols_per_row = st.sidebar.slider("Grid columns", 3, 5, 4)

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
    if interaction_label == "Contains":
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

st.title("Glass Library")
st.caption(
    f"{len(filtered)} items ({family_name}, preview: {preview_label.lower()}, sorted by: {sort_label.lower()})"
)

if filtered.empty:
    st.info("No glass samples match the current filters.")
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

selected_row = filtered[filtered["glass_id"] == str(selected_glass_id)]
if selected_row.empty:
    st.info("Select a glass sample to see details.")
    st.stop()

base_row = selected_row.iloc[0]
row_r = measurement_row(measurements, selected_glass_id, "R")
row_t = measurement_row(measurements, selected_glass_id, "T")
pending_scroll_id = st.session_state.pop("_library_scroll_to", None)

for start in range(0, len(filtered), cols_per_row):
    row_slice = filtered.iloc[start : start + cols_per_row]
    row_ids = row_slice["glass_id"].astype(str).tolist()
    show_detail = str(selected_glass_id) in row_ids
    row_anchor_id = f"library-row-{start}"

    if show_detail:
        st.markdown(
            f'<div id="{row_anchor_id}" style="height:1px;"></div>',
            unsafe_allow_html=True,
        )
        if pending_scroll_id == str(selected_glass_id):
            scroll_to_row(row_anchor_id)

    left, right = st.columns([0.58, 0.42], gap="large")
    with left:
        cols = st.columns(cols_per_row)
        for idx, row in enumerate(row_slice.itertuples(index=False)):
            glass_id = str(row.glass_id)
            with cols[idx]:
                with st.container(border=True):
                    icon = first_existing_icon(glass_id, selected_prefix, preview_mode)
                    if icon is not None:
                        st.image(str(icon), width="content")
                    elif MISSING_ICON.exists():
                        st.image(str(MISSING_ICON), width="content")

                    st.caption((row.color_name or "").strip() or "Unnamed sample")
                    button_type = "primary" if glass_id == selected_glass_id else "secondary"
                    if st.button(
                        glass_id,
                        key=f"pick_{selected_family_code}_{preview_mode}_{glass_id}",
                        width="content",
                        type=button_type,
                    ):
                        st.session_state["selected_glass_id"] = glass_id
                        st.session_state["_library_scroll_to"] = glass_id
                        st.rerun()

    with right:
        if show_detail:
            render_detail_panel(
                base_row=base_row,
                row_r=row_r,
                row_t=row_t,
                selected_glass_id=str(selected_glass_id),
                family_name=family_name,
                selected_prefix=selected_prefix,
            )
