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

APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "glass_library.sqlite"
IMG_ROOT = APP_ROOT / "images"
MISSING_ICON = IMG_ROOT / "_placeholders" / "missing_icon.jpg"

FAMILY_PREFIX_BY_CODE = {
    "1": "opal",
    "2": "transparent",
    "3": "tint",
}

FRIT_BEHAVIOUR = {
    "Powdered": {
        "factor": 0.18,
        "label": "Powdered glass should integrate most smoothly, but bubble control matters more before firing.",
    },
    "Fine": {
        "factor": 0.35,
        "label": "Fine frit should integrate more softly and visually average more quickly.",
    },
    "Medium": {
        "factor": 0.65,
        "label": "Medium frit keeps some local contrast while still reading as a blended field.",
    },
    "Coarse": {
        "factor": 1.0,
        "label": "Coarse frit is more likely to keep individual colour pockets visible.",
    },
}

st.set_page_config(page_title="Frit Mix Explorer", layout="wide")
st.markdown(
    """
    <style>
    .mix-summary {
        background: #f6f8fb;
        border: 1px solid #dde2ec;
        border-radius: 16px;
        padding: 0.9rem 1rem;
        margin: 0.75rem 0 1rem 0;
        font-family: sans-serif;
    }
    .mix-summary p {
        margin: 0 0 0.45rem 0;
        line-height: 1.35;
    }
    .mix-summary p:last-child {
        margin-bottom: 0;
    }
    .mix-card {
        border: 1px solid #d7dbe4;
        border-radius: 16px;
        padding: 0.9rem 1rem;
        margin-top: 0.45rem;
        font-family: sans-serif;
    }
    .mix-card__title {
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        opacity: 0.78;
        margin-bottom: 0.35rem;
    }
    .mix-card__subtitle {
        font-size: 0.88rem;
        line-height: 1.25;
        margin-bottom: 0.65rem;
        opacity: 0.92;
    }
    .mix-card__chip {
        height: 110px;
        border-radius: 12px;
        border: 1px solid rgba(0, 0, 0, 0.10);
        margin-bottom: 0.7rem;
    }
    .mix-card__metrics {
        font-size: 0.86rem;
        line-height: 1.45;
        color: #5e6678;
    }
    .mix-badge {
        display: inline-flex;
        align-items: center;
        border-radius: 999px;
        padding: 0.18rem 0.5rem;
        font-family: sans-serif;
        font-size: 0.72rem;
        font-weight: 600;
        line-height: 1.1;
        background: #eff1f5;
        color: #4b5568;
        border: 1px solid #d9dde6;
        margin-right: 0.35rem;
        margin-bottom: 0.35rem;
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
                COALESCE(f.name, c.glass_family) AS family_name
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


def channel_after_path(reference_channel: float, reference_thickness: float, path_mm: float) -> float:
    channel_value = max(min(float(reference_channel), 255.0), 0.1)
    ref_thickness = max(float(reference_thickness), 0.01)
    alpha = -math.log(channel_value / 255.0) / ref_thickness
    return float(np.clip(255.0 * math.exp(-alpha * max(path_mm, 0.0)), 0.0, 255.0))


def modeled_rgb(measurement: pd.Series, depth_mm: float) -> tuple[int, int, int]:
    ref_thickness = max(safe_float(measurement.get("thickness_mm"), 2.0), 0.01)
    rgb = []
    for field in ("r", "g", "b"):
        rgb.append(int(round(channel_after_path(safe_int(measurement.get(field)), ref_thickness, depth_mm))))
    return tuple(rgb)


def weighted_rgb(rgb_values: list[tuple[int, int, int]], weights: list[float]) -> tuple[int, int, int]:
    total = sum(float(weight) for weight in weights)
    if total <= 0 or not rgb_values:
        return (0, 0, 0)

    normalized = [float(weight) / total for weight in weights]
    channels = []
    for index in range(3):
        channel_value = sum(rgb[index] * share for rgb, share in zip(rgb_values, normalized))
        channels.append(int(round(np.clip(channel_value, 0.0, 255.0))))
    return tuple(channels)


def mix_fraction_from_grams(primary_grams: float, modifier_grams: float) -> float:
    total = max(float(primary_grams) + float(modifier_grams), 0.0)
    if total <= 0:
        return 0.0
    return float(np.clip(float(modifier_grams) / total, 0.0, 1.0))


def weighted_brightness(brightness_values: list[float], weights: list[float]) -> float:
    total = sum(float(weight) for weight in weights)
    if total <= 0 or not brightness_values:
        return 0.0
    return sum(float(value) * float(weight) for value, weight in zip(brightness_values, weights)) / total


def rgb_to_hsb(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    red, green, blue = [channel / 255.0 for channel in rgb]
    hue, saturation, brightness = colorsys.rgb_to_hsv(red, green, blue)
    hue_deg = int(round(hue * 360.0)) % 360 if brightness > 0 else 0
    sat_pct = int(round(saturation * 100.0))
    bri_pct = int(round(brightness * 100.0))
    return hue_deg, sat_pct, bri_pct


def rgb_css(rgb: tuple[int, int, int]) -> str:
    return f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"


def layered_result_from_filter(base_rgb: tuple[int, int, int], filter_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(
        int(round(np.clip(base_value * (filter_value / 255.0), 0.0, 255.0)))
        for base_value, filter_value in zip(base_rgb, filter_rgb)
    )


def swatch_markup(
    title: str,
    subtitle: str,
    rgb: tuple[int, int, int],
    hsb: tuple[int, int, int],
    note: str,
) -> str:
    return f"""
    <div class="mix-card">
      <div class="mix-card__title">{html.escape(title)}</div>
      <div class="mix-card__subtitle">{html.escape(subtitle)}</div>
      <div class="mix-card__chip" style="background:{rgb_css(rgb)};"></div>
      <div class="mix-card__metrics">
        <strong>RGB:</strong> {rgb[0]}, {rgb[1]}, {rgb[2]}<br>
        <strong>HSB:</strong> {hsb[0]}, {hsb[1]}, {hsb[2]}
      </div>
      <div class="mix-card__metrics" style="margin-top:0.55rem;">
        {html.escape(note)}
      </div>
    </div>
    """


def colour_distance(rgb_a: tuple[int, int, int], rgb_b: tuple[int, int, int]) -> float:
    return float(math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(rgb_a, rgb_b))))


def contrast_label(distance: float) -> str:
    if distance < 50:
        return "Low local separation"
    if distance < 110:
        return "Moderate local separation"
    return "High local separation"


def join_phrases(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


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
    qualifier = "slightly " if abs(delta) < strong_threshold else ""
    return f"{qualifier}{positive_text if delta > 0 else negative_text}"


def layered_mix_summary_lines(
    base_label: str,
    base_hsb: tuple[int, int, int],
    mix_filter_hsb: tuple[int, int, int],
    result_hsb: tuple[int, int, int],
    depth_mm: float,
) -> list[str]:
    lines = [
        f"Over {base_label}, the frit field is treated as a transmitted filter with a {depth_mm * 2.0:.2f} mm round trip through the mix."
    ]

    qualities = []
    brightness_phrase = describe_change(
        result_hsb[2] - base_hsb[2],
        "brighter",
        "darker",
    )
    saturation_phrase = describe_change(
        result_hsb[1] - base_hsb[1],
        "more saturated",
        "less saturated",
    )
    if brightness_phrase:
        qualities.append(brightness_phrase)
    if saturation_phrase:
        qualities.append(saturation_phrase)
    if qualities:
        lines.append(f"Compared with the base by itself, the layered read looks {join_phrases(qualities)}.")

    if result_hsb[2] <= mix_filter_hsb[2] - 5:
        lines.append(
            "Compared with the frit field on its own bright scan backing, the layered result comes back darker because the base is limiting the return light."
        )

    lines.append(
        "This is a first-pass reflected stack estimate: the frit mix is modeled as a filter over the chosen light base rather than as a full melt blend."
    )
    return lines


def mix_summary_lines(
    components: list[dict[str, object]],
    result_hsb: tuple[int, int, int],
    weighted_b: float,
    depth_mm: float,
    frit_size: str,
    local_separation_label: str,
) -> list[str]:
    active_components = [component for component in components if float(component["grams"]) > 0]
    total_grams = sum(float(component["grams"]) for component in active_components)
    component_phrases = [
        f"{float(component['grams']):.2f} g of {component['label']}" for component in active_components
    ]
    weighted_terms = [
        f"{component['hsb'][2]} × {float(component['grams']):.2f}" for component in active_components
    ]

    lines = [
        f"This estimate treats the mix as {join_phrases(component_phrases)} through {depth_mm:.2f} mm of depth."
    ]
    lines.append(
        f"Weighted B calculation: ({' + '.join(weighted_terms)}) / {total_grams:.2f} = {weighted_b:.1f}."
    )

    reference_component = active_components[0]
    reference_hsb = reference_component["hsb"]
    qualities = []
    brightness_phrase = describe_change(
        result_hsb[2] - reference_hsb[2],
        "brighter",
        "darker",
    )
    saturation_phrase = describe_change(
        result_hsb[1] - reference_hsb[1],
        "more saturated",
        "less saturated",
    )
    if brightness_phrase:
        qualities.append(brightness_phrase)
    if saturation_phrase:
        qualities.append(saturation_phrase)
    if qualities:
        lines.append(
            f"Compared with {reference_component['slot']} by itself at this depth, the mixed read looks {join_phrases(qualities)}."
        )

    if len(active_components) == 1:
        lines.append(f"Only {reference_component['slot']} is active right now, so the predicted read matches that frit.")
    else:
        dominant_component = max(active_components, key=lambda component: float(component["grams"]))
        dominant_share_pct = int(round((float(dominant_component["grams"]) / total_grams) * 100.0))
        if dominant_share_pct >= 60:
            lines.append(
                f"{dominant_component['slot']} is doing most of the visual work here, so the result should lean strongly toward that colour family."
            )
        elif dominant_share_pct >= 40:
            lines.append(
                f"{dominant_component['slot']} is leading the mix, but the other frits should still be visibly shaping the result."
            )
        else:
            lines.append("No single frit is dominating outright, so the result should read as a more balanced field.")

    lines.append(f"{local_separation_label}. {FRIT_BEHAVIOUR[frit_size]['label']}")
    lines.append(
        "This page is still a heuristic: it uses optical averaging of the visible read rather than assuming the frit fully homogenizes during firing."
    )
    return lines


def brightness_depth_figure(
    components: list[dict[str, object]],
    depth_selected: float,
) -> go.Figure:
    max_depth = max(
        8.0,
        depth_selected * 1.6,
        *[safe_float(component["row"].get("thickness_mm"), 2.0) * 3.0 for component in components],
    )
    depth_values = np.linspace(0.0, max_depth, 180)
    component_brightness = {str(component["slot"]): [] for component in components}
    mixed_brightness = []
    line_colors = ["#5b7bd5", "#d17a1f", "#8a57c2"]

    for depth in depth_values:
        component_rgbs = []
        component_weights = []
        for component in components:
            rgb = modeled_rgb(component["row"], float(depth))
            component_brightness[str(component["slot"])].append(rgb_to_hsb(rgb)[2])
            component_rgbs.append(rgb)
            component_weights.append(float(component["grams"]))
        mixed_rgb = weighted_rgb(component_rgbs, component_weights)
        mixed_brightness.append(rgb_to_hsb(mixed_rgb)[2])

    figure = go.Figure()
    for index, component in enumerate(components):
        figure.add_trace(
            go.Scatter(
                x=depth_values,
                y=component_brightness[str(component["slot"])],
                mode="lines",
                name=f"{component['slot']} brightness",
                line=dict(color=line_colors[index % len(line_colors)], width=2.2),
            )
        )
    figure.add_trace(
        go.Scatter(
            x=depth_values,
            y=mixed_brightness,
            mode="lines",
            name="Mixed brightness",
            line=dict(color="#2f6a40", width=3),
        )
    )
    figure.add_vline(x=depth_selected, line_dash="dash", line_color="gray")
    figure.update_layout(
        title="Brightness Across Depth",
        xaxis_title="Depth (mm)",
        yaxis_title="Brightness (B)",
        yaxis=dict(range=[0, 105]),
        xaxis=dict(range=[0, max_depth]),
        legend=dict(orientation="h", y=1.08),
        height=320,
        margin=dict(l=30, r=10, t=48, b=30),
    )
    return figure


def mixed_rgb_depth_figure(
    components: list[dict[str, object]],
    depth_selected: float,
) -> go.Figure:
    max_depth = max(
        8.0,
        depth_selected * 1.6,
        *[safe_float(component["row"].get("thickness_mm"), 2.0) * 3.0 for component in components],
    )
    depth_values = np.linspace(0.0, max_depth, 180)
    channels = {"R": [], "G": [], "B": []}

    for depth in depth_values:
        component_rgbs = [modeled_rgb(component["row"], float(depth)) for component in components]
        component_weights = [float(component["grams"]) for component in components]
        mixed_rgb = weighted_rgb(component_rgbs, component_weights)
        channels["R"].append(mixed_rgb[0])
        channels["G"].append(mixed_rgb[1])
        channels["B"].append(mixed_rgb[2])

    figure = go.Figure()
    figure.add_trace(go.Scatter(x=depth_values, y=channels["R"], mode="lines", name="R", line=dict(color="red", width=2.2)))
    figure.add_trace(go.Scatter(x=depth_values, y=channels["G"], mode="lines", name="G", line=dict(color="green", width=2.2)))
    figure.add_trace(go.Scatter(x=depth_values, y=channels["B"], mode="lines", name="B", line=dict(color="blue", width=2.2)))
    figure.add_vline(x=depth_selected, line_dash="dash", line_color="gray")
    figure.update_layout(
        title="Predicted Mixed RGB Across Depth",
        xaxis_title="Depth (mm)",
        yaxis_title="Channel value",
        yaxis=dict(range=[0, 260]),
        xaxis=dict(range=[0, max_depth]),
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
    st.error("Glass catalog or measurement data is missing.")
    st.stop()

family_options = ["All"] + families["name"].tolist()

st.sidebar.header("Mix Setup")
mode_label = st.sidebar.radio("Reference measurements", ["Transmitted", "Reflected"], index=0)
mode = "T" if mode_label == "Transmitted" else "R"

st.sidebar.header("Light Base")
base_family_default = family_options.index("Opalescent") if "Opalescent" in family_options else 0
base_family = st.sidebar.selectbox("Base family", family_options, index=base_family_default)
base_candidates = filter_catalog_by_family(catalog, base_family)
if base_candidates.empty:
    st.error("No glass samples match the current base family filter.")
    st.stop()

base_default_id = default_sample_id(base_candidates, ["French Vanilla", "Almond", "White"])
base_labels = sample_labels(base_candidates)
base_index = base_candidates["glass_id"].tolist().index(base_default_id)
base_id = st.sidebar.selectbox(
    "Base glass",
    base_candidates["glass_id"].tolist(),
    index=base_index,
    format_func=lambda glass_id: base_labels.get(glass_id, glass_id),
)
base_catalog_row = base_candidates[base_candidates["glass_id"] == base_id].iloc[0]
base_row_r = measurement_row(measurements, base_id, "R")
if base_row_r is None:
    st.error(f"{base_labels.get(base_id, base_id)} is missing reflected data.")
    st.stop()

frit_setup = [
    ("Frit 1", ["French Vanilla", "Almond", "Clear"], 2.0),
    ("Frit 2", ["Tan Transparent", "Black", "Dark"], 1.0),
    ("Frit 3", ["Silver Gray", "Silver Grey", "Clear"], 0.0),
]


def select_frit_component(slot_label: str, preferred_terms: list[str], default_grams: float) -> dict[str, object]:
    family_name = st.sidebar.selectbox(f"{slot_label} family", family_options, index=0)
    candidates = filter_catalog_by_family(catalog, family_name)
    if candidates.empty:
        st.error(f"No glass samples match the current filter for {slot_label}.")
        st.stop()

    labels = sample_labels(candidates)
    default_id = default_sample_id(candidates, preferred_terms)
    glass_ids = candidates["glass_id"].tolist()
    default_index = glass_ids.index(default_id)
    glass_id = st.sidebar.selectbox(
        slot_label,
        glass_ids,
        index=default_index,
        format_func=lambda candidate_id: labels.get(candidate_id, candidate_id),
    )
    grams = st.sidebar.number_input(f"{slot_label} grams", min_value=0.0, value=default_grams, step=0.1, format="%.2f")

    catalog_row = candidates[candidates["glass_id"] == glass_id].iloc[0]
    measurement = measurement_row(measurements, glass_id, mode)
    if measurement is None and grams > 0:
        st.error(f"{labels.get(glass_id, glass_id)} is missing {mode_label.lower()} data.")
        st.stop()

    return {
        "slot": slot_label,
        "glass_id": glass_id,
        "label": labels.get(glass_id, glass_id),
        "grams": grams,
        "catalog_row": catalog_row,
        "row": measurement,
        "row_t": measurement_row(measurements, glass_id, "T"),
        "row_r": measurement_row(measurements, glass_id, "R"),
    }


components = []
st.sidebar.divider()
for index, (slot_label, preferred_terms, default_grams) in enumerate(frit_setup):
    if index > 0:
        st.sidebar.divider()
    components.append(select_frit_component(slot_label, preferred_terms, default_grams))

available_rows = [component["row"] for component in components if component["row"] is not None]
reference_depth = max(
    0.5,
    *[safe_float(row.get("thickness_mm"), 2.0) for row in available_rows],
)
depth_max = max(8.0, reference_depth * 3.0)
depth_mm = st.sidebar.slider(
    "Mix depth (mm)",
    min_value=0.0,
    max_value=float(round(depth_max, 1)),
    value=float(round(reference_depth, 1)),
    step=0.1,
)
frit_options = list(FRIT_BEHAVIOUR.keys())
default_frit_index = frit_options.index("Powdered")
frit_size = st.sidebar.selectbox("Frit size", frit_options, index=default_frit_index)

for component in components:
    row = component["row"]
    if row is not None:
        component["rgb"] = modeled_rgb(row, depth_mm)
        component["hsb"] = rgb_to_hsb(component["rgb"])
    else:
        component["rgb"] = (0, 0, 0)
        component["hsb"] = (0, 0, 0)
    component["prefix"] = row_prefix(component["catalog_row"])
    component["icon"] = first_existing_icon(component["glass_id"], component["prefix"], mode)

active_components = [component for component in components if float(component["grams"]) > 0]
total_grams = sum(float(component["grams"]) for component in active_components)
if total_grams <= 0:
    st.error("Enter at least some frit by weight so the mix can be estimated.")
    st.stop()

mixed_rgb = weighted_rgb(
    [component["rgb"] for component in active_components],
    [float(component["grams"]) for component in active_components],
)
mixed_hsb = rgb_to_hsb(mixed_rgb)
weighted_b = weighted_brightness(
    [component["hsb"][2] for component in active_components],
    [float(component["grams"]) for component in active_components],
)

pair_scores = []
pair_weights = []
for left_index, left_component in enumerate(active_components):
    for right_component in active_components[left_index + 1 :]:
        pair_scores.append(colour_distance(left_component["rgb"], right_component["rgb"]))
        pair_weights.append(float(left_component["grams"]) * float(right_component["grams"]))
if pair_scores and sum(pair_weights) > 0:
    raw_distance = float(np.average(pair_scores, weights=pair_weights))
else:
    raw_distance = 0.0
local_separation_score = raw_distance * FRIT_BEHAVIOUR[frit_size]["factor"]
local_separation_label = contrast_label(local_separation_score)

base_rgb = tuple(safe_int(base_row_r.get(field)) for field in ("r", "g", "b"))
base_hsb = rgb_to_hsb(base_rgb)
base_prefix = row_prefix(base_catalog_row)
base_icon = first_existing_icon(base_id, base_prefix, "R")

layering_ready = all(component["row_t"] is not None for component in active_components)
if layering_ready:
    mixed_filter_single_rgb = weighted_rgb(
        [modeled_rgb(component["row_t"], depth_mm) for component in active_components],
        [float(component["grams"]) for component in active_components],
    )
    mixed_filter_double_rgb = weighted_rgb(
        [modeled_rgb(component["row_t"], depth_mm * 2.0) for component in active_components],
        [float(component["grams"]) for component in active_components],
    )
    mixed_filter_single_hsb = rgb_to_hsb(mixed_filter_single_rgb)
    layered_mix_rgb = layered_result_from_filter(base_rgb, mixed_filter_double_rgb)
    layered_mix_hsb = rgb_to_hsb(layered_mix_rgb)
    layered_lines = layered_mix_summary_lines(
        base_labels.get(base_id, base_id),
        base_hsb,
        mixed_filter_single_hsb,
        layered_mix_hsb,
        depth_mm,
    )
else:
    missing_layer_ids = [str(component["glass_id"]) for component in active_components if component["row_t"] is None]
    layered_lines = []

summary_lines = mix_summary_lines(
    active_components,
    mixed_hsb,
    weighted_b,
    depth_mm,
    frit_size,
    local_separation_label,
)

st.title("Frit Mix Explorer")
st.caption(
    "First-pass frit heuristic: the visible read is estimated as optical averaging across depth, with frit size affecting how much local colour separation is likely to remain."
)

st.markdown(
    '<div class="mix-summary">'
    + "".join(f"<p>{html.escape(line)}</p>" for line in summary_lines)
    + "</div>",
    unsafe_allow_html=True,
)

badge_markup = "".join(
    [
        f'<span class="mix-badge">Mode: {html.escape(mode_label)}</span>',
        f'<span class="mix-badge">Depth: {depth_mm:.2f} mm</span>',
        *[
            f'<span class="mix-badge">{html.escape(str(component["slot"]))}: {float(component["grams"]):.2f} g</span>'
            for component in components
        ],
        f'<span class="mix-badge">Total: {total_grams:.2f} g</span>',
        f'<span class="mix-badge">Weighted B: {weighted_b:.1f}</span>',
        f'<span class="mix-badge">Frit size: {html.escape(frit_size)}</span>',
        f'<span class="mix-badge">{html.escape(local_separation_label)}</span>',
    ]
)
st.markdown(badge_markup, unsafe_allow_html=True)

card_cols = st.columns(4, gap="medium")
for column, component in zip(card_cols[:3], components):
    with column:
        st.markdown(f"### {component['label']}")
        st.caption(f"{component['slot']} at the selected depth.")
        if component["icon"] is not None:
            st.image(str(component["icon"]), width="content")
        elif MISSING_ICON.exists():
            st.image(str(MISSING_ICON), width="content")

        contribution_note = "Modeled from the selected measurement mode over the chosen depth."
        if component["slot"] == "Frit 2":
            contribution_note = "Useful as a second colour body or as a nudge, depending on the selected grams."
        if component["slot"] == "Frit 3":
            contribution_note = "Optional third frit for nudging the turn-to-black point or helping a difficult mix fit."
        if float(component["grams"]) <= 0:
            contribution_note = "Currently parked at 0.00 g, so it is ready for use without changing the current mix."

        st.markdown(
            swatch_markup(
                f"{component['slot']} contribution",
                f"{float(component['grams']):.2f} g in the mix",
                component["rgb"],
                component["hsb"],
                contribution_note,
            ),
            unsafe_allow_html=True,
        )

with card_cols[3]:
    st.markdown("### Predicted mixed read")
    st.caption("Optically averaged result at the selected depth.")
    st.markdown(
        swatch_markup(
            "Predicted mixed result",
            f"Weighted visual read from {total_grams:.2f} g total",
            mixed_rgb,
            mixed_hsb,
            f"This is not a full melt blend. It is a first-pass estimate of how the mixed frit field may read. Weighted B = {weighted_b:.1f}.",
        ),
        unsafe_allow_html=True,
    )

if layering_ready:
    st.markdown("### Layered over light base")
    st.caption(
        "This section uses the selected frit mix as a transmitted filter over the chosen light base, with a round-trip path through the frit field."
    )
    st.markdown(
        '<div class="mix-summary">'
        + "".join(f"<p>{html.escape(line)}</p>" for line in layered_lines)
        + "</div>",
        unsafe_allow_html=True,
    )

    layered_cols = st.columns(3, gap="large")
    with layered_cols[0]:
        st.markdown(f"### {base_labels.get(base_id, base_id)}")
        st.caption("Light base used as the reflected return source.")
        if base_icon is not None:
            st.image(str(base_icon), width="content")
        elif MISSING_ICON.exists():
            st.image(str(MISSING_ICON), width="content")
        st.markdown(
            swatch_markup(
                "Base reflected source",
                "Measured reflected scan",
                base_rgb,
                base_hsb,
                "This is the return light from the base before the frit field filters it.",
            ),
            unsafe_allow_html=True,
        )

    with layered_cols[1]:
        st.markdown("### Mixed frit field")
        st.caption("The selected frit mix treated as the top filter.")
        st.markdown(
            swatch_markup(
                "Mixed frit filter",
                f"One-way transmission through {depth_mm:.2f} mm",
                mixed_filter_single_rgb,
                mixed_filter_single_hsb,
                "This is the first-pass optical filter read of the mixed frit field before the reflected return from the base.",
            ),
            unsafe_allow_html=True,
        )

    with layered_cols[2]:
        st.markdown("### Predicted layered read")
        st.caption("Round-trip prediction over the chosen base.")
        st.markdown(
            swatch_markup(
                "Predicted reflected result",
                f"Round trip through {depth_mm * 2.0:.2f} mm of frit depth",
                layered_mix_rgb,
                layered_mix_hsb,
                "This is the first-pass estimate of what comes back from the base once the frit field filters the light down and back.",
            ),
            unsafe_allow_html=True,
        )
else:
    st.info(
        "Layered-over-base preview is unavailable for the current mix because transmitted data is missing for: "
        + ", ".join(missing_layer_ids)
    )

chart_left, chart_right = st.columns(2, gap="large")
with chart_left:
    st.plotly_chart(
        brightness_depth_figure(active_components, depth_mm),
        config={"displaylogo": False},
    )
with chart_right:
    st.plotly_chart(
        mixed_rgb_depth_figure(active_components, depth_mm),
        config={"displaylogo": False},
    )

st.markdown("### Model Notes")
st.markdown(
    "\n".join(
        [
            "- This page is exploratory rather than prescriptive. It gives a studio-friendly estimate of the visible read.",
            "- Frit size does not change the weighted average colour directly here; it changes the expected amount of local colour separation that may still be visible.",
            "- Powdered glass is treated here as the smoothest-integrating option, but in practice trapped air and bubbles still need to be addressed before firing.",
            "- The page does not assume complete homogenization during firing.",
            "- The brightness chart is there because brightness is often the easiest depth signal to use when you are building a transition through a thicker frit field.",
        ]
    )
)
