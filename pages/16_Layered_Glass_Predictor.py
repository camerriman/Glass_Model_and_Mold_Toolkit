from __future__ import annotations

import colorsys
import html
import math
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from i18n import join_list, render_app_sidebar, t, translate_element_name, translate_family_name

APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "glass_library.sqlite"
IMG_ROOT = APP_ROOT / "images"
MISSING_ICON = IMG_ROOT / "_placeholders" / "missing_icon.jpg"

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

st.set_page_config(page_title=t("predictor.title", "Layered Glass Predictor"), layout="wide")
render_app_sidebar()
st.markdown(
    """
    <style>
    .layer-swatch {
        border: 1px solid #d7dbe4;
        border-radius: 16px;
        padding: 0.9rem 1rem;
        margin-top: 0.45rem;
        font-family: sans-serif;
    }
    .layer-swatch__title {
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        opacity: 0.78;
        margin-bottom: 0.35rem;
    }
    .layer-swatch__subtitle {
        font-size: 0.88rem;
        line-height: 1.25;
        margin-bottom: 0.65rem;
        opacity: 0.92;
    }
    .layer-swatch__chip {
        height: 106px;
        border-radius: 12px;
        border: 1px solid rgba(0, 0, 0, 0.10);
        margin-bottom: 0.7rem;
    }
    .layer-swatch__metrics {
        font-size: 0.86rem;
        line-height: 1.45;
        color: #1f2330;
    }
    .layer-summary {
        background: #f6f8fb;
        border: 1px solid #dde2ec;
        border-radius: 16px;
        padding: 0.9rem 1rem;
        margin: 0.75rem 0 1rem 0;
        font-family: sans-serif;
    }
    .layer-summary p {
        margin: 0 0 0.45rem 0;
        line-height: 1.35;
    }
    .layer-summary p:last-child {
        margin-bottom: 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if pd.isna(value):
            return default
        text = str(value).strip()
        if text == "" or text.lower() == "nan":
            return default
        return float(text)
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


def row_prefix(row: pd.Series) -> str:
    code = row.get("glass_family")
    name = row.get("family_name") or row.get("glass_family")
    return family_prefix(str(code or ""), str(name or ""))


def icon_path(cat_id: str, prefix: str, mode: str) -> Path:
    return IMG_ROOT / "icons" / f"{prefix}_{mode}_{cat_id}.jpg"


def first_existing_icon(cat_id: str, prefix: str, preferred_mode: str) -> Path | None:
    for mode in (preferred_mode, "T" if preferred_mode == "R" else "R"):
        candidate = icon_path(cat_id, prefix, mode)
        if candidate.exists():
            return candidate
    return None


@st.cache_data
def load_families() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql_query(
            """
            SELECT code, name
            FROM glass_families
            ORDER BY CAST(code AS INTEGER);
            """,
            con,
        )


@st.cache_data
def load_catalog() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql_query(
            """
            SELECT
                c.cat_id AS glass_id,
                c.color_name,
                c.glass_family,
                COALESCE(f.name, c.glass_family) AS family_name,
                c.is_striker,
                c.se,
                c.su,
                c.cu,
                c.pb,
                c.ag,
                c.au
            FROM glass_catalog c
            LEFT JOIN glass_families f
                ON f.code = c.glass_family
            ORDER BY c.cat_id;
            """,
            con,
        )


@st.cache_data
def load_measurements() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
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
            WHERE mode IN ('R', 'T')
            ORDER BY cat_id, mode;
            """,
            con,
        )


def measurement_row(measurements: pd.DataFrame, glass_id: str, mode: str) -> pd.Series | None:
    matches = measurements[
        (measurements["glass_id"].astype(str) == str(glass_id))
        & (measurements["mode"].astype(str).str.upper() == mode)
    ]
    if matches.empty:
        return None
    return matches.iloc[0]


def filter_catalog_by_family(catalog: pd.DataFrame, family_name: str) -> pd.DataFrame:
    if family_name == "All":
        return catalog.copy()
    return catalog[catalog["family_name"] == family_name].copy()


def default_sample_id(catalog_slice: pd.DataFrame, preferred_terms: list[str]) -> str:
    if catalog_slice.empty:
        return ""
    names = catalog_slice["color_name"].fillna("").astype(str).str.lower()
    for term in preferred_terms:
        matches = catalog_slice[names.str.contains(term.lower())]
        if not matches.empty:
            return str(matches.iloc[0]["glass_id"])
    return str(catalog_slice.iloc[0]["glass_id"])


def sample_labels(catalog_slice: pd.DataFrame) -> dict[str, str]:
    labels = {}
    for row in catalog_slice.itertuples(index=False):
        glass_id = str(row.glass_id)
        title = str(row.color_name or "").strip()
        labels[glass_id] = f"{glass_id} {title}".strip()
    return labels


def element_labels(row: pd.Series) -> list[str]:
    labels = []
    for label, column in ELEMENT_MAP.items():
        if safe_int(row.get(column), 0) == 1:
            labels.append(label)
    return labels


def reactive_pairings(base_row: pd.Series, top_row: pd.Series) -> list[str]:
    pairings: list[str] = []
    base_elements = element_labels(base_row)
    top_elements = element_labels(top_row)

    for source_elements, target_elements in ((base_elements, top_elements), (top_elements, base_elements)):
        for source in source_elements:
            for reactive in REACTION_RULES.get(source, []):
                if reactive in target_elements:
                    label = f"{translate_element_name(source).lower()}/{translate_element_name(reactive).lower()}"
                    if label not in pairings:
                        pairings.append(label)
    return pairings


def channel_after_path(reference_channel: float, reference_thickness: float, path_mm: float) -> float:
    channel_value = max(min(float(reference_channel), 255.0), 0.1)
    ref_thickness = max(float(reference_thickness), 0.01)
    alpha = -math.log(channel_value / 255.0) / ref_thickness
    return float(np.clip(255.0 * math.exp(-alpha * max(path_mm, 0.0)), 0.0, 255.0))


def modeled_filter_rgb(top_row_t: pd.Series, thickness_mm: float, path_multiplier: float = 1.0) -> tuple[int, int, int]:
    ref_thickness = max(safe_float(top_row_t.get("thickness_mm"), 2.0), 0.01)
    path_mm = max(thickness_mm, 0.0) * path_multiplier
    rgb = []
    for field in ("r", "g", "b"):
        rgb.append(int(round(channel_after_path(safe_int(top_row_t.get(field)), ref_thickness, path_mm))))
    return tuple(rgb)


def opal_scatter_alpha(top_row_r: pd.Series, thickness_mm: float) -> float:
    ref_thickness = max(safe_float(top_row_r.get("thickness_mm"), 2.0), 0.01)
    return float(np.clip(1.0 - math.exp(-1.6 * max(thickness_mm, 0.0) / ref_thickness), 0.0, 1.0))


def layered_result_rgb(
    base_row_r: pd.Series,
    top_measurement_row: pd.Series,
    thickness_mm: float,
    model_kind: str = "transparent_filter",
) -> tuple[int, int, int]:
    if model_kind == "opal_reflected_overlay":
        alpha = opal_scatter_alpha(top_measurement_row, thickness_mm)
        rgb = []
        for base_value, top_value in zip(
            [safe_int(base_row_r.get(field)) for field in ("r", "g", "b")],
            [safe_int(top_measurement_row.get(field)) for field in ("r", "g", "b")],
        ):
            rgb.append(int(round(np.clip((base_value * (1.0 - alpha)) + (top_value * alpha), 0.0, 255.0))))
        return tuple(rgb)

    double_pass_rgb = modeled_filter_rgb(top_measurement_row, thickness_mm, path_multiplier=2.0)
    rgb = []
    for base_value, filter_value in zip(
        [safe_int(base_row_r.get(field)) for field in ("r", "g", "b")],
        double_pass_rgb,
    ):
        rgb.append(int(round(np.clip(base_value * (filter_value / 255.0), 0.0, 255.0))))
    return tuple(rgb)


def rgb_to_hsb(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    red, green, blue = [channel / 255.0 for channel in rgb]
    hue, saturation, brightness = colorsys.rgb_to_hsv(red, green, blue)
    hue_deg = int(round(hue * 360.0)) % 360 if brightness > 0 else 0
    sat_pct = int(round(saturation * 100.0))
    bri_pct = int(round(brightness * 100.0))
    return hue_deg, sat_pct, bri_pct


def rgb_css(rgb: tuple[int, int, int]) -> str:
    return f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"


def swatch_markup(
    title: str,
    subtitle: str,
    rgb: tuple[int, int, int],
    hsb: tuple[int, int, int],
    note: str,
) -> str:
    return f"""
    <div class="layer-swatch">
      <div class="layer-swatch__title">{html.escape(title)}</div>
      <div class="layer-swatch__subtitle">{html.escape(subtitle)}</div>
      <div class="layer-swatch__chip" style="background:{rgb_css(rgb)};"></div>
      <div class="layer-swatch__metrics">
        <strong>RGB:</strong> {rgb[0]}, {rgb[1]}, {rgb[2]}<br>
        <strong>HSB:</strong> {hsb[0]}, {hsb[1]}, {hsb[2]}
      </div>
      <div class="layer-swatch__metrics" style="margin-top:0.55rem; color:#5e6678;">
        {html.escape(note)}
      </div>
    </div>
    """


def circular_hue_delta(reference_hue: int, compare_hue: int) -> float:
    return ((float(compare_hue) - float(reference_hue) + 180.0) % 360.0) - 180.0


def join_phrases(parts: list[str]) -> str:
    return join_list(parts)


def describe_change(
    delta: float,
    positive_text: str,
    negative_text: str,
    *,
    slight_threshold: float = 4.0,
    strong_threshold: float = 12.0,
) -> str | None:
    if abs(delta) < slight_threshold:
        return None
    qualifier = t("shared.qualifier.slightly", "slightly ") if abs(delta) < strong_threshold else ""
    return f"{qualifier}{positive_text if delta > 0 else negative_text}"


def layered_summary_lines(
    base_catalog_row: pd.Series,
    top_catalog_row: pd.Series,
    base_rgb: tuple[int, int, int],
    base_hsb: tuple[int, int, int],
    top_single_rgb: tuple[int, int, int],
    top_single_hsb: tuple[int, int, int],
    result_rgb: tuple[int, int, int],
    result_hsb: tuple[int, int, int],
    top_thickness: float,
    model_kind: str,
) -> list[str]:
    if model_kind == "opal_reflected_overlay":
        lines = [
            t(
                "predictor.summary.opal_overlay",
                "At {top_thickness:.2f} mm of opalescent top glass, the result is modeled as reflected surface/scatter color over the reflected base.",
                top_thickness=top_thickness,
            )
        ]
    else:
        lines = [
            t(
                "predictor.summary.path_length",
                "At {top_thickness:.2f} mm of top glass, the light makes a {path_length:.2f} mm round trip through that layer before it returns from the base.",
                top_thickness=top_thickness,
                path_length=top_thickness * 2.0,
            )
        ]

    base_quality = []
    brightness_phrase = describe_change(result_hsb[2] - base_hsb[2], t("predictor.summary.brighter", "brighter"), t("predictor.summary.darker", "darker"))
    saturation_phrase = describe_change(
        result_hsb[1] - base_hsb[1],
        t("predictor.summary.more_saturated", "more saturated"),
        t("predictor.summary.less_saturated", "less saturated"),
    )
    if brightness_phrase:
        base_quality.append(brightness_phrase)
    if saturation_phrase:
        base_quality.append(saturation_phrase)
    if base_quality:
        lines.append(
            t(
                "predictor.summary.compared_with_base",
                "Compared with the base by itself, the layered result reads {qualities}.",
                qualities=join_phrases(base_quality),
            )
        )

    hue_delta = circular_hue_delta(base_hsb[0], result_hsb[0])
    if abs(hue_delta) >= 8:
        lines.append(
            t(
                "predictor.summary.hue_shift",
                "The base hue shifts by about {degrees:.0f} deg once the top layer is added.",
                degrees=abs(hue_delta),
            )
        )

    if model_kind != "opal_reflected_overlay" and result_hsb[2] <= top_single_hsb[2] - 5:
        lines.append(
            t(
                "predictor.summary.darker_than_top",
                "Compared with the top glass on its own bright scan backing, the layered result comes back darker because the base is limiting the return light.",
            )
        )

    avg_result = sum(result_rgb) / 3.0
    avg_base = sum(base_rgb) / 3.0
    if avg_base > 0 and avg_result / avg_base < 0.72:
        lines.append(
            t(
                "predictor.summary.quieter_stack",
                "This stack is likely to feel noticeably quieter and more muted than the base alone.",
            )
        )

    pairings = reactive_pairings(base_catalog_row, top_catalog_row)
    if pairings:
        lines.append(
            t(
                "predictor.summary.reactive_yes",
                "Reactive potential: Possible {pairings} reaction.",
                pairings="; ".join(pairings),
            )
        )
    else:
        lines.append(t("predictor.summary.reactive_no", "Reactive potential: No obvious reactive pairing surfaced."))

    return lines


def predicted_rgb_curve_figure(
    base_row_r: pd.Series,
    top_measurement_row: pd.Series,
    selected_thickness: float,
    model_kind: str = "transparent_filter",
) -> go.Figure:
    reference_thickness = max(safe_float(top_measurement_row.get("thickness_mm"), 2.0), 0.01)
    max_thickness = max(8.0, selected_thickness * 4.0, reference_thickness * 4.0)
    thickness_values = np.linspace(0.0, max_thickness, 180)
    figure = go.Figure()

    base_channels = {field: safe_int(base_row_r.get(field)) for field in ("r", "g", "b")}
    colours = {"r": "red", "g": "green", "b": "blue"}
    labels = {"r": "R", "g": "G", "b": "B"}

    for field in ("r", "g", "b"):
        values = []
        for thickness in thickness_values:
            if model_kind == "opal_reflected_overlay":
                alpha = opal_scatter_alpha(top_measurement_row, float(thickness))
                values.append(
                    (base_channels[field] * (1.0 - alpha))
                    + (safe_int(top_measurement_row.get(field)) * alpha)
                )
            else:
                double_pass = channel_after_path(
                    safe_int(top_measurement_row.get(field)),
                    reference_thickness,
                    thickness * 2.0,
                )
                values.append(base_channels[field] * (double_pass / 255.0))
        figure.add_trace(
            go.Scatter(
                x=thickness_values,
                y=values,
                mode="lines",
                name=labels[field],
                line=dict(color=colours[field], width=2.4),
            )
        )

    figure.add_vline(x=selected_thickness, line_dash="dash", line_color="gray")
    figure.update_layout(
        title=t("predictor.figure.rgb", "Predicted Reflected RGB"),
        xaxis_title=t("predictor.figure.thickness_axis", "Top thickness (mm)"),
        yaxis_title=t("predictor.figure.channel_value", "Channel value"),
        yaxis=dict(range=[0, 260]),
        xaxis=dict(range=[0, max_thickness]),
        legend=dict(orientation="h", y=1.08),
        height=320,
        margin=dict(l=30, r=10, t=48, b=30),
    )
    return figure


def predicted_hsb_curve_figure(
    base_row_r: pd.Series,
    top_measurement_row: pd.Series,
    selected_thickness: float,
    model_kind: str = "transparent_filter",
) -> go.Figure:
    reference_thickness = max(safe_float(top_measurement_row.get("thickness_mm"), 2.0), 0.01)
    max_thickness = max(8.0, selected_thickness * 4.0, reference_thickness * 4.0)
    thickness_values = np.linspace(0.0, max_thickness, 180)
    brightness_values = []
    saturation_values = []

    for thickness in thickness_values:
        rgb = layered_result_rgb(base_row_r, top_measurement_row, float(thickness), model_kind)
        _, saturation, brightness = rgb_to_hsb(rgb)
        brightness_values.append(brightness)
        saturation_values.append(saturation)

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=thickness_values,
            y=brightness_values,
            mode="lines",
            name=t("editor.fields.brightness", "Brightness (B)").replace(" (B)", ""),
            line=dict(color="cornflowerblue", width=2.4),
        )
    )
    figure.add_trace(
        go.Scatter(
            x=thickness_values,
            y=saturation_values,
            mode="lines",
            name=t("editor.fields.saturation", "Saturation (S)").replace(" (S)", ""),
            line=dict(color="limegreen", width=2.4),
        )
    )
    figure.add_vline(x=selected_thickness, line_dash="dash", line_color="gray")
    figure.update_layout(
        title=t("predictor.figure.hsb", "Predicted Brightness & Saturation"),
        xaxis_title=t("predictor.figure.thickness_axis", "Top thickness (mm)"),
        yaxis_title=t("predictor.figure.zero_to_hundred", "0-100"),
        yaxis=dict(range=[0, 105]),
        xaxis=dict(range=[0, max_thickness]),
        legend=dict(orientation="h", y=1.08),
        height=320,
        margin=dict(l=30, r=10, t=48, b=30),
    )
    return figure


families = load_families().copy()
catalog = load_catalog().copy()
measurements = load_measurements().copy()

families["name"] = families["name"].astype(str)
catalog["glass_id"] = catalog["glass_id"].astype(str)
catalog["glass_family"] = catalog["glass_family"].astype(str)
catalog["family_name"] = catalog["family_name"].astype(str)
measurements["glass_id"] = measurements["glass_id"].astype(str)
measurements["mode"] = measurements["mode"].astype(str).str.upper()

if catalog.empty or measurements.empty:
    st.error(t("predictor.messages.missing_data", "Glass catalog or measurement data is missing."))
    st.stop()

family_options = ["All"] + families["name"].tolist()
base_family_default = family_options.index("Opalescent") if "Opalescent" in family_options else 0
top_family_default = family_options.index("Transparent") if "Transparent" in family_options else 0

st.sidebar.header(t("predictor.sidebar.title", "Layer Setup"))
top_family = st.sidebar.selectbox(
    t("predictor.fields.top_family", "Top family"),
    family_options,
    index=top_family_default,
    format_func=lambda value: translate_family_name(None, value),
)

top_candidates = filter_catalog_by_family(catalog, top_family)

if top_candidates.empty:
    st.error(t("predictor.messages.no_family_matches", "No glass samples match the current family filters."))
    st.stop()

top_default_id = default_sample_id(top_candidates, ["Tan Transparent", "Tan"])
top_labels = sample_labels(top_candidates)
top_index = top_candidates["glass_id"].tolist().index(top_default_id)

top_id = st.sidebar.selectbox(
    t("predictor.fields.top_glass", "Top glass"),
    top_candidates["glass_id"].tolist(),
    index=top_index,
    format_func=lambda glass_id: top_labels.get(glass_id, glass_id),
)

base_family = st.sidebar.selectbox(
    t("predictor.fields.base_family", "Base family"),
    family_options,
    index=base_family_default,
    format_func=lambda value: translate_family_name(None, value),
)

base_candidates = filter_catalog_by_family(catalog, base_family)

if base_candidates.empty:
    st.error(t("predictor.messages.no_family_matches", "No glass samples match the current family filters."))
    st.stop()

base_default_id = default_sample_id(base_candidates, ["French Vanilla"])
base_labels = sample_labels(base_candidates)
base_index = base_candidates["glass_id"].tolist().index(base_default_id)

base_id = st.sidebar.selectbox(
    t("predictor.fields.base_glass", "Base glass"),
    base_candidates["glass_id"].tolist(),
    index=base_index,
    format_func=lambda glass_id: base_labels.get(glass_id, glass_id),
)

base_catalog_row = base_candidates[base_candidates["glass_id"] == base_id].iloc[0]
top_catalog_row = top_candidates[top_candidates["glass_id"] == top_id].iloc[0]
base_prefix = row_prefix(base_catalog_row)
top_prefix = row_prefix(top_catalog_row)
model_kind = "opal_reflected_overlay" if base_prefix == "opal" and top_prefix == "opal" else "transparent_filter"
top_mode = "R"
base_row_r = measurement_row(measurements, base_id, "R")
top_measurement_row = measurement_row(measurements, top_id, top_mode)

if base_row_r is None:
    st.error(
        t(
            "predictor.messages.base_missing_reflected",
            "{label} is missing reflected measurement data.",
            label=base_labels.get(base_id, base_id),
        )
    )
    st.stop()
if top_measurement_row is None:
    st.error(
        t(
            "predictor.messages.top_missing_measurement",
            "{label} is missing {mode} measurement data.",
            label=top_labels.get(top_id, top_id),
            mode=t("shared.mode.reflected", "reflected").lower(),
        )
    )
    st.stop()

reference_top_thickness = max(safe_float(top_measurement_row.get("thickness_mm"), 2.0), 0.01)
thickness_max = max(8.0, reference_top_thickness * 4.0)
top_thickness = st.sidebar.slider(
    t("predictor.fields.top_thickness", "Top thickness (mm)"),
    min_value=0.0,
    max_value=float(round(thickness_max, 1)),
    value=float(round(reference_top_thickness, 1)),
    step=0.1,
)
st.sidebar.caption(
    t("predictor.caption.path_length", "Round-trip path through top glass: {value} mm", value=f"{top_thickness * 2.0:.2f}")
)

base_rgb = tuple(safe_int(base_row_r.get(field)) for field in ("r", "g", "b"))
base_hsb = rgb_to_hsb(base_rgb)
top_single_rgb = tuple(safe_int(top_measurement_row.get(field)) for field in ("r", "g", "b"))
top_single_hsb = rgb_to_hsb(top_single_rgb)
result_rgb = layered_result_rgb(base_row_r, top_measurement_row, top_thickness, model_kind)
result_hsb = rgb_to_hsb(result_rgb)

base_icon = first_existing_icon(base_id, base_prefix, "R")
top_icon = first_existing_icon(top_id, top_prefix, top_mode)

st.title(t("predictor.title", "Layered Glass Predictor"))
st.caption(
    t(
        "predictor.caption.intro_opal_overlay" if model_kind == "opal_reflected_overlay" else "predictor.caption.intro_reflected_filter",
        "Opalescent-over-opalescent model: base reflected RGB blended toward the top glass reflected scan as thickness increases."
        if model_kind == "opal_reflected_overlay"
        else "First-pass reflected stacking model: base reflected RGB filtered through the top glass reflected measurement over a double pass through the selected thickness.",
    )
)

summary_lines = layered_summary_lines(
    base_catalog_row,
    top_catalog_row,
    base_rgb,
    base_hsb,
    top_single_rgb,
    top_single_hsb,
    result_rgb,
    result_hsb,
    top_thickness,
    model_kind,
)

st.markdown(
    '<div class="layer-summary">'
    + "".join(f"<p>{html.escape(line)}</p>" for line in summary_lines)
    + "</div>",
    unsafe_allow_html=True,
)
st.caption(
    t(
        "predictor.caption.reactive",
        "Reactive potential indicates a possible chemistry interaction. Visible results still depend on firing conditions such as temperature, hold time, thickness, and kiln atmosphere.",
    )
)

card_cols = st.columns(3, gap="large")

with card_cols[0]:
    st.markdown(f"### {base_labels.get(base_id, base_id)}")
    st.caption(t("predictor.cards.base_caption", "Base glass used as the reflected return source."))
    if base_icon is not None:
        st.image(str(base_icon), width="content")
    elif MISSING_ICON.exists():
        st.image(str(MISSING_ICON), width="content")
    st.markdown(
        swatch_markup(
            t("predictor.sections.base", "Base reflected source"),
            t("predictor.cards.base_subtitle", "Measured reflected scan"),
            base_rgb,
            base_hsb,
            t("predictor.cards.base_note", "This is the light coming back from the base before the top layer filters it."),
        ),
        unsafe_allow_html=True,
    )

with card_cols[1]:
    st.markdown(f"### {top_labels.get(top_id, top_id)}")
    st.caption(
        t(
            "predictor.cards.top_caption_opal_overlay" if model_kind == "opal_reflected_overlay" else "predictor.cards.top_caption_reflected_filter",
            "Top opalescent glass contributing reflected surface/scatter colour."
            if model_kind == "opal_reflected_overlay"
            else "Top glass acting as the reflected colour filter.",
        )
    )
    if top_icon is not None:
        st.image(str(top_icon), width="content")
    elif MISSING_ICON.exists():
        st.image(str(MISSING_ICON), width="content")
    st.markdown(
        swatch_markup(
            t(
                "predictor.sections.top_opal_overlay" if model_kind == "opal_reflected_overlay" else "predictor.sections.top_reflected_filter",
                "Top reflected source" if model_kind == "opal_reflected_overlay" else "Top reflected filter",
            ),
            t(
                "predictor.cards.top_subtitle_opal_overlay" if model_kind == "opal_reflected_overlay" else "predictor.cards.top_subtitle_reflected_filter",
                "Measured reflected scan",
                thickness=top_thickness,
            ),
            top_single_rgb,
            top_single_hsb,
            t(
                "predictor.cards.top_note_opal_overlay" if model_kind == "opal_reflected_overlay" else "predictor.cards.top_note_reflected_filter",
                "Reference reflected scan thickness: {thickness:.2f} mm."
                if model_kind == "opal_reflected_overlay"
                else "Reference reflected scan thickness: {thickness:.2f} mm.",
                thickness=reference_top_thickness,
            ),
        ),
        unsafe_allow_html=True,
    )

with card_cols[2]:
    st.markdown(f"### {t('predictor.sections.result', 'Predicted layered result')}")
    st.caption(t("predictor.cards.result_caption", "Double-pass prediction over the chosen base."))
    st.markdown(
        swatch_markup(
            t("predictor.cards.result_title", "Predicted reflected result"),
            t(
                "predictor.cards.result_subtitle_opal_overlay" if model_kind == "opal_reflected_overlay" else "predictor.cards.result_subtitle",
                "Reflected overlay at {thickness:.2f} mm of top glass"
                if model_kind == "opal_reflected_overlay"
                else "Round trip through {thickness:.2f} mm of top glass",
                thickness=top_thickness if model_kind == "opal_reflected_overlay" else top_thickness * 2.0,
            ),
            result_rgb,
            result_hsb,
            t("predictor.cards.result_note", "This is the first-pass estimate of what returns to the eye from the layered stack."),
        ),
        unsafe_allow_html=True,
    )

chart_left, chart_right = st.columns(2, gap="large")
with chart_left:
    st.plotly_chart(
        predicted_rgb_curve_figure(base_row_r, top_measurement_row, top_thickness, model_kind),
        config={"displaylogo": False},
    )
with chart_right:
    st.plotly_chart(
        predicted_hsb_curve_figure(base_row_r, top_measurement_row, top_thickness, model_kind),
        config={"displaylogo": False},
    )

st.markdown(f"### {t('predictor.sections.model_notes', 'Model Notes')}")
st.markdown(
    "\n".join(
        [
            f"- {t('predictor.notes.opal_overlay_model', 'When both glasses are opalescent, the top glass uses reflected data and is modeled as a scattering reflected overlay.')}"
            if model_kind == "opal_reflected_overlay"
            else f"- {t('predictor.notes.reflected_filter_model', 'The top glass is treated as a reflected-value filter using a Beer-Lambert-style attenuation model.')}",
            f"- {t('predictor.notes.opal_overlay_thickness', 'For opalescent overlays, increasing top thickness moves the predicted result toward the top glass reflected color.')}"
            if model_kind == "opal_reflected_overlay"
            else f"- {t('predictor.notes.double_pass', 'Reflected stacking uses a double pass through the top layer: once going down and once coming back.')}",
            f"- {t('predictor.notes.thickness_datum', 'The glass library uses each sample at its recorded thickness as its measured reference. Thickness changes in this predictor are modeled extrapolations from that reference, so moving away from the recorded thickness will skew the result rather than replace the measured sample data.')}",
            f"- {t('predictor.notes.lighting_variation', 'The library imagery is treated as a broad daylight-balanced reference. Real glass can read warmer, cooler, or shifted under artificial light sources, especially shift-tint glass under fluorescent or uneven-spectrum lighting.')}",
            f"- {t('predictor.notes.first_pass', 'This is a first-pass predictor. It does not yet model interface losses, surface texture scattering, or kiln-formed microstructure.')}",
        ]
    )
)
