from __future__ import annotations

import html
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.append(str(APP_ROOT))

from i18n import render_app_sidebar, t, translate_family_name, translate_mode_name
from utilities.glass_detail_pdf import calculate_black_point_mm, rgb_at_depth

DB_PATH = APP_ROOT / "data" / "glass_library.sqlite"
BLACK_POINT_THRESHOLD = 1.0
PROFILE_DISPLAY_DEPTH_MM = 12.0


st.set_page_config(page_title=t("depth_view.title", "Glass Depth Side View"), layout="wide")
render_app_sidebar()


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        text = str(value).strip()
        if not text or text.lower() == "nan":
            return default
        return float(text)
    except Exception:
        return default


def optional_float(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(str(value).strip())
    except Exception:
        return None


def safe_int(value: object, default: int = 0) -> int:
    return int(round(safe_float(value, float(default))))


@st.cache_data
def load_depth_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not DB_PATH.exists():
        st.error(t("errors.editor.db_missing", "Missing database: {path}", path=DB_PATH))
        st.stop()

    with sqlite3.connect(DB_PATH) as con:
        catalog = pd.read_sql_query(
            """
            SELECT cat_id, color_name, glass_family
            FROM glass_catalog
            ORDER BY cat_id
            """,
            con,
        )
        measurements = pd.read_sql_query(
            """
            SELECT cat_id, mode, R, G, B, H, S, V, thickness_mm
            FROM glass_measurements
            ORDER BY cat_id, mode
            """,
            con,
        )
        families = pd.read_sql_query(
            """
            SELECT code, name
            FROM glass_families
            ORDER BY id
            """,
            con,
        )
    return catalog, measurements, families


def mode_display(mode: str) -> str:
    return translate_mode_name(mode)


def family_display(code: str) -> str:
    if code == "all":
        return t("shared.family.all_families", "All families")
    return translate_family_name(code, code)


def measurement_dict(row: pd.Series) -> dict[str, int]:
    return {
        "R": safe_int(row.get("R")),
        "G": safe_int(row.get("G")),
        "B": safe_int(row.get("B")),
    }


def gradient_css(meas: dict[str, int], thickness_mm: float, max_depth: float, stops: int = 32) -> str:
    parts: list[str] = []
    for idx in range(stops):
        depth = max_depth * idx / max(stops - 1, 1)
        r, g, b = rgb_at_depth(meas, thickness_mm, depth)
        pct = depth / max(max_depth, 0.001) * 100.0
        parts.append(f"rgb({r},{g},{b}) {pct:.2f}%")
    return "linear-gradient(to bottom, " + ", ".join(parts) + ")"


def display_glass_id(value: object) -> str:
    text = str(value or "").strip()
    trimmed = text.lstrip("0")
    return trimmed or text


def depth_ticks(max_depth: float) -> list[float]:
    if max_depth <= 0:
        return [0.0]
    target_intervals = 4 if max_depth <= 48 else 5
    raw_step = max_depth / target_intervals
    nice_steps = [1, 2, 4, 8, 16, 24, 32, 48, 64, 96, 128, 192, 256]
    step = next((value for value in nice_steps if value >= raw_step), None)
    if step is None:
        step = nice_steps[-1]
        while step < raw_step:
            step *= 2
    ticks = [0.0]
    current = step
    while current < max_depth:
        ticks.append(current)
        current += step
    if abs(ticks[-1] - max_depth) > 0.05:
        ticks.append(round(max_depth, 1))
    return ticks


def black_point_label(value: float | None) -> str:
    if value is None:
        return t("depth_view.black_point_missing_short", "not reached")
    return f"{value:.1f} mm"


def bar_markup(
    row: pd.Series,
    max_depth: float,
    black_point: float | None,
    show_depth_scale: bool,
) -> str:
    raw_glass_id = str(row["cat_id"])
    glass_id = html.escape(display_glass_id(raw_glass_id))
    color_name = html.escape(str(row.get("color_name") or ""))
    thickness_mm = safe_float(row.get("thickness_mm"), 2.0)
    meas = measurement_dict(row)
    black_point = optional_float(black_point)
    bar_depth = max_depth
    gradient = gradient_css(meas, thickness_mm, bar_depth)
    black_label = black_point_label(black_point)
    title = html.escape(f"{display_glass_id(raw_glass_id)} {color_name} | black point {black_label} | scale 0-{bar_depth:.1f} mm | ref {thickness_mm:.1f} mm")

    marker = ""
    if black_point is not None and 0 <= black_point <= bar_depth:
        marker_pct = black_point / max(bar_depth, 0.001) * 100.0
        marker = f'<span class="black-marker" style="top:{marker_pct:.2f}%"></span>'

    ref_pct = min(100.0, thickness_mm / max(bar_depth, 0.001) * 100.0)
    ref_marker = f'<span class="ref-marker" style="top:{ref_pct:.2f}%"></span>'
    axis = ""
    if show_depth_scale:
        ticks = "\n".join(
            f'<span class="depth-tick" style="top:{tick / max(bar_depth, 0.001) * 100.0:.2f}%"><span>{tick:g} mm</span></span>'
            for tick in depth_ticks(bar_depth)
        )
        axis = f"""
        <div class="depth-axis" aria-hidden="true">
          {ticks}
        </div>
        """

    scale_class = "is-scaled" if show_depth_scale else "is-compact"
    detail_href = (
        f"/Glass_Detail?cat_id={quote(raw_glass_id)}"
        f"&return_page={quote('pages/18_Glass_Depth_Side_View.py')}"
        f"&return_label={quote(t('depth_view.title', 'Glass Depth Side View'))}"
    )
    return f"""
    <a class="depth-card-link" href="{html.escape(detail_href)}" title="{title}">
      <div class="depth-card {scale_class}">
        <div class="depth-visual">
          <div class="depth-bar" style="background:{gradient};">
            {ref_marker}
            {marker}
            <div class="glass-id">{glass_id}</div>
            <div class="black-point-value">{html.escape(black_label)}</div>
          </div>
          {axis}
        </div>
      </div>
    </a>
    """


catalog, measurements, families = load_depth_data()

st.title(t("depth_view.title", "Glass Depth Side View"))
st.caption(
    t(
        "depth_view.caption",
        "Vertical Beer-Lambert side views showing how each measured glass darkens as thickness increases.",
    )
)
st.caption(
    t(
        "library.notes.datum",
        "Library colors are anchored to the measured 2 mm sample datum under broad daylight-balanced illumination. Thickness changes, lighting changes, and batch variation can shift the visible read away from this reference.",
    )
)

with st.sidebar:
    st.header(t("depth_view.sidebar.title", "Depth View"))
    family_codes = ["all"] + [str(value) for value in families["code"].tolist()]
    selected_family = st.selectbox(
        t("depth_view.fields.family", "Family"),
        family_codes,
        index=0,
        format_func=family_display,
    )
    mode = st.radio(
        t("depth_view.fields.mode", "Measurement"),
        ["T", "R"],
        index=1,
        format_func=mode_display,
        horizontal=True,
    )
    sort_mode = st.selectbox(
        t("depth_view.fields.sort", "Sort"),
        ["Hue", "Product ID", "Black point"],
        index=2,
        format_func=lambda value: {
            "Hue": t("shared.sort.hue", "Hue (H)"),
            "Product ID": t("shared.sort.product_id", "Product ID"),
            "Black point": t("depth_view.sort.black_point", "Black point"),
        }.get(value, value),
    )
    query = st.text_input(t("depth_view.fields.search", "Search"), "")
    columns = st.slider(t("depth_view.fields.columns", "Columns"), 6, 12, 8)
    show_depth_scale = st.checkbox(t("depth_view.fields.show_depth_scale", "Show depth scales"), value=True)


mode_rows = measurements[measurements["mode"].astype(str).str.upper() == mode].copy()
merged = catalog.merge(mode_rows, on="cat_id", how="inner")
if selected_family != "all":
    merged = merged[merged["glass_family"].astype(str) == selected_family]
if query.strip():
    needle = query.strip().lower()
    merged = merged[
        merged["cat_id"].astype(str).str.lower().str.contains(needle)
        | merged["color_name"].fillna("").astype(str).str.lower().str.contains(needle)
    ]

merged["_black_point"] = merged.apply(
    lambda row: calculate_black_point_mm(measurement_dict(row), safe_float(row.get("thickness_mm"), 2.0), threshold=BLACK_POINT_THRESHOLD),
    axis=1,
)
if sort_mode == "Product ID":
    merged = merged.sort_values(["cat_id", "color_name"])
elif sort_mode == "Black point":
    merged = merged.sort_values(["_black_point", "cat_id"], na_position="last")
elif sort_mode == "Hue":
    merged = merged.sort_values(["H", "S", "V", "cat_id"], na_position="last")
else:
    raise ValueError(f"Unknown sort mode: {sort_mode}")

visible = merged
max_depth = PROFILE_DISPLAY_DEPTH_MM
summary_depth = f"0-{max_depth:g} mm"

st.caption(
    t(
        "depth_view.summary",
        "{count} glasses | {mode} | modeled depth {depth_range} | black threshold RGB <= {threshold:g}",
        count=len(visible),
        mode=mode_display(mode),
        depth_range=summary_depth,
        threshold=BLACK_POINT_THRESHOLD,
    )
)

if visible.empty:
    st.info(t("depth_view.empty", "No measured glasses match the current filters."))
    st.stop()

cards = "\n".join(
    bar_markup(
        row,
        max_depth,
        row.get("_black_point"),
        show_depth_scale,
    )
    for _, row in visible.iterrows()
)
st.html(
    f"""
    <style>
      .depth-grid {{
        --depth-columns: {columns};
        display: grid;
        grid-template-columns: repeat(var(--depth-columns), minmax(104px, 1fr));
        gap: 42px 26px;
        align-items: end;
        padding: 18px 4px 44px;
      }}
      .depth-card {{
        display: flex;
        flex-direction: column;
        align-items: center;
        min-width: 0;
      }}
      .depth-card-link {{
        display: block;
        color: inherit;
        text-decoration: none;
        border-radius: 6px;
      }}
      .depth-card-link:hover .depth-bar {{
        box-shadow:
          inset 0 0 0 1px rgba(0,0,0,0.08),
          0 0 0 3px rgba(255, 74, 80, 0.16);
      }}
      .depth-card-link:focus-visible {{
        outline: 3px solid rgba(255, 74, 80, 0.65);
        outline-offset: 8px;
      }}
      .depth-visual {{
        display: flex;
        align-items: stretch;
        justify-content: center;
        gap: 10px;
        width: 100%;
      }}
      .depth-card.is-compact .depth-visual {{
        gap: 0;
      }}
      .depth-bar {{
        position: relative;
        width: 62px;
        height: 320px;
        box-shadow: inset 0 0 0 1px rgba(0,0,0,0.06);
        overflow: visible;
      }}
      .glass-id {{
        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        height: 30px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: #151515;
        color: #fff;
        font: 800 18px/1 Arial, sans-serif;
        letter-spacing: 0;
      }}
      .black-point-value {{
        position: absolute;
        left: calc(100% + 8px);
        bottom: 8px;
        font: 700 11px/1 Arial, sans-serif;
        color: #4b5563;
        white-space: nowrap;
        background: rgba(255,255,255,0.86);
        padding: 1px 2px;
        z-index: 4;
      }}
      .black-marker {{
        position: absolute;
        left: -8px;
        right: -8px;
        height: 3px;
        background: #e11d2e;
        box-shadow: 0 0 0 1px rgba(255,255,255,0.7);
        z-index: 3;
      }}
      .ref-marker {{
        position: absolute;
        left: -8px;
        right: -8px;
        height: 2px;
        border-top: 2px dashed rgba(100,100,100,0.75);
        z-index: 2;
      }}
      .depth-axis {{
        position: relative;
        width: 58px;
        height: 320px;
        border-left: 2px solid #777;
        color: #6b7280;
        font: 500 11px/1 Arial, sans-serif;
      }}
      .depth-tick {{
        position: absolute;
        left: -6px;
        width: 11px;
        border-top: 2px solid #777;
      }}
      .depth-tick span {{
        position: absolute;
        left: 15px;
        top: -7px;
        white-space: nowrap;
        background: rgba(255,255,255,0.86);
        padding-right: 2px;
      }}
      @media (max-width: 900px) {{
        .depth-grid {{
          --depth-columns: 5;
          gap: 28px 16px;
        }}
        .depth-bar {{
          width: 56px;
          height: 250px;
        }}
        .depth-axis {{
          height: 250px;
          width: 50px;
          font-size: 10px;
        }}
        .glass-id {{
          font-size: 15px;
        }}
        .black-point-value {{
          font-size: 9px;
        }}
      }}
      @media print {{
        .depth-grid {{
          --depth-columns: 8;
          gap: 30px 18px;
          break-inside: avoid;
        }}
        .depth-bar {{
          width: 48px;
          height: 255px;
        }}
        .depth-axis {{
          height: 255px;
          width: 48px;
          font-size: 9px;
        }}
        .glass-id {{
          height: 24px;
          font-size: 13px;
        }}
        .black-point-value {{
          font-size: 8px;
        }}
      }}
    </style>
    <div class="depth-grid">
      {cards}
    </div>
    """
)
