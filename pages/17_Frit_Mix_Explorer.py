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

from i18n import (
    join_list,
    render_app_sidebar,
    t,
    translate_element_name,
    translate_family_name,
    translate_mode_name,
)

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
    },
    "Fine": {
        "factor": 0.35,
    },
    "Medium": {
        "factor": 0.65,
    },
    "Coarse": {
        "factor": 1.0,
    },
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

st.set_page_config(page_title=t("frit.title", "Frit Mix Explorer"), layout="wide")
render_app_sidebar()
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


def db_cache_token() -> tuple[int, int]:
    if not DB_PATH.exists():
        return (0, 0)
    stat = DB_PATH.stat()
    return (stat.st_mtime_ns, stat.st_size)


@st.cache_data
def load_families(_db_token: tuple[int, int]) -> pd.DataFrame:
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
def load_catalog(_db_token: tuple[int, int]) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql_query(
            """
            SELECT
                c.cat_id AS glass_id,
                c.color_name,
                c.glass_family,
                COALESCE(f.name, c.glass_family) AS family_name,
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
def load_measurements(_db_token: tuple[int, int]) -> pd.DataFrame:
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


def reactive_pairings(left_row: pd.Series, right_row: pd.Series) -> list[str]:
    pairings: list[str] = []
    left_elements = element_labels(left_row)
    right_elements = element_labels(right_row)

    for source_elements, target_elements in ((left_elements, right_elements), (right_elements, left_elements)):
        for source in source_elements:
            for reactive in REACTION_RULES.get(source, []):
                if reactive in target_elements:
                    label = f"{translate_element_name(source).lower()}/{translate_element_name(reactive).lower()}"
                    if label not in pairings:
                        pairings.append(label)
    return pairings


def component_reactive_details(components: list[dict[str, object]]) -> list[str]:
    details: list[str] = []
    for left_index, left_component in enumerate(components):
        for right_component in components[left_index + 1 :]:
            pairings = reactive_pairings(left_component["catalog_row"], right_component["catalog_row"])
            if pairings:
                details.append(
                    t(
                        "frit.summary.reactive.detail_pair",
                        "{left} with {right}: {pairings}",
                        left=left_component["slot"],
                        right=right_component["slot"],
                        pairings=join_phrases(pairings),
                    )
                )
    return details


def base_reactive_details(components: list[dict[str, object]], base_row: pd.Series) -> list[str]:
    details: list[str] = []
    for component in components:
        pairings = reactive_pairings(component["catalog_row"], base_row)
        if pairings:
            details.append(
                t(
                    "frit.summary.reactive.detail_base",
                    "{slot}: {pairings}",
                    slot=component["slot"],
                    pairings=join_phrases(pairings),
                )
            )
    return details


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


def mix_fraction_from_amounts(primary_amount: float, modifier_amount: float) -> float:
    total = max(float(primary_amount) + float(modifier_amount), 0.0)
    if total <= 0:
        return 0.0
    return float(np.clip(float(modifier_amount) / total, 0.0, 1.0))


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
        return t("frit.contrast.low", "Low local separation")
    if distance < 110:
        return t("frit.contrast.medium", "Moderate local separation")
    return t("frit.contrast.high", "High local separation")


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


def frit_size_label(size: str) -> str:
    labels = {
        "Powdered": t("frit.size.powdered", "Powdered"),
        "Fine": t("frit.size.fine", "Fine"),
        "Medium": t("frit.size.medium", "Medium"),
        "Coarse": t("frit.size.coarse", "Coarse"),
    }
    return labels.get(size, size)


def frit_behaviour_label(size: str) -> str:
    labels = {
        "Powdered": t("frit.behaviour.powdered", "Powdered glass should integrate most smoothly, but bubble control matters more before firing."),
        "Fine": t("frit.behaviour.fine", "Fine frit should integrate more softly and visually average more quickly."),
        "Medium": t("frit.behaviour.medium", "Medium frit keeps some local contrast while still reading as a blended field."),
        "Coarse": t("frit.behaviour.coarse", "Coarse frit is more likely to keep individual colour pockets visible."),
    }
    return labels.get(size, size)


def layered_mix_summary_lines(
    base_label: str,
    base_hsb: tuple[int, int, int],
    mix_filter_hsb: tuple[int, int, int],
    result_hsb: tuple[int, int, int],
    depth_mm: float,
) -> list[str]:
    lines = [
        t(
            "frit.summary.layered.path",
            "Over {base_label}, the frit field is treated as a transmitted filter with a {path_length:.2f} mm round trip through the mix.",
            base_label=base_label,
            path_length=depth_mm * 2.0,
        )
    ]

    qualities = []
    brightness_phrase = describe_change(
        result_hsb[2] - base_hsb[2],
        t("predictor.summary.brighter", "brighter"),
        t("predictor.summary.darker", "darker"),
    )
    saturation_phrase = describe_change(
        result_hsb[1] - base_hsb[1],
        t("predictor.summary.more_saturated", "more saturated"),
        t("predictor.summary.less_saturated", "less saturated"),
    )
    if brightness_phrase:
        qualities.append(brightness_phrase)
    if saturation_phrase:
        qualities.append(saturation_phrase)
    if qualities:
        lines.append(
            t(
                "frit.summary.layered.compared_with_base",
                "Compared with the base by itself, the layered read looks {qualities}.",
                qualities=join_phrases(qualities),
            )
        )

    if result_hsb[2] <= mix_filter_hsb[2] - 5:
        lines.append(
            t(
                "frit.summary.layered.darker_than_filter",
                "Compared with the frit field on its own bright scan backing, the layered result comes back darker because the base is limiting the return light.",
            )
        )

    lines.append(
        t(
            "frit.summary.layered.first_pass",
            "This is a first-pass reflected stack estimate: the frit mix is modeled as a filter over the chosen light base rather than as a full melt blend.",
        )
    )
    return lines


def mix_summary_lines(
    components: list[dict[str, object]],
    result_hsb: tuple[int, int, int],
    weighted_b: float,
    depth_mm: float,
    frit_size: str,
    local_separation_label: str,
    mix_reactive_notes: list[str],
    base_label: str,
    base_reactive_notes: list[str],
) -> list[str]:
    active_components = [component for component in components if float(component["mm"]) > 0]
    total_mm = sum(float(component["mm"]) for component in active_components)
    component_phrases = [
        f"{float(component['mm']):.1f} mm of {component['label']}" for component in active_components
    ]
    weighted_terms = [
        f"{component['hsb'][2]} × {float(component['mm']):.1f}" for component in active_components
    ]

    lines = [
        t(
            "frit.summary.mix.components",
            "This estimate treats the mix as {components} through {depth:.2f} mm of depth.",
            components=join_phrases(component_phrases),
            depth=depth_mm,
        )
    ]
    lines.append(
        t(
            "frit.summary.mix.weighted_b",
            "Weighted B calculation: ({terms}) / {total:.1f} = {weighted_b:.1f}.",
            terms=" + ".join(weighted_terms),
            total=total_mm,
            weighted_b=weighted_b,
        )
    )

    reference_component = active_components[0]
    reference_hsb = reference_component["hsb"]
    qualities = []
    brightness_phrase = describe_change(
        result_hsb[2] - reference_hsb[2],
        t("predictor.summary.brighter", "brighter"),
        t("predictor.summary.darker", "darker"),
    )
    saturation_phrase = describe_change(
        result_hsb[1] - reference_hsb[1],
        t("predictor.summary.more_saturated", "more saturated"),
        t("predictor.summary.less_saturated", "less saturated"),
    )
    if brightness_phrase:
        qualities.append(brightness_phrase)
    if saturation_phrase:
        qualities.append(saturation_phrase)
    if qualities:
        lines.append(
            t(
                "frit.summary.mix.reference_compare",
                "Compared with {slot} by itself at this depth, the mixed read looks {qualities}.",
                slot=reference_component["slot"],
                qualities=join_phrases(qualities),
            )
        )

    if len(active_components) == 1:
        lines.append(
            t(
                "frit.summary.mix.single_component",
                "Only {slot} is active right now, so the predicted read matches that frit.",
                slot=reference_component["slot"],
            )
        )
    else:
        dominant_component = max(active_components, key=lambda component: float(component["mm"]))
        dominant_share_pct = int(round((float(dominant_component["mm"]) / total_mm) * 100.0))
        if dominant_share_pct >= 60:
            lines.append(
                t(
                    "frit.summary.mix.dominant_strong",
                    "{slot} is doing most of the visual work here, so the result should lean strongly toward that colour family.",
                    slot=dominant_component["slot"],
                )
            )
        elif dominant_share_pct >= 40:
            lines.append(
                t(
                    "frit.summary.mix.dominant_moderate",
                    "{slot} is leading the mix, but the other frits should still be visibly shaping the result.",
                    slot=dominant_component["slot"],
                )
            )
        else:
            lines.append(t("frit.summary.mix.balanced", "No single frit is dominating outright, so the result should read as a more balanced field."))

    if len(active_components) > 1:
        if mix_reactive_notes:
            lines.append(
                t(
                    "frit.summary.mix.reactive_yes",
                    "Reactive potential across the active frits: {details}.",
                    details=join_phrases(mix_reactive_notes),
                )
            )
        else:
            lines.append(
                t(
                    "frit.summary.mix.reactive_no",
                    "Reactive potential across the active frits: no obvious reactive pairing appeared in the current mix.",
                )
            )

    if base_reactive_notes:
        lines.append(
            t(
                "frit.summary.base.reactive_yes",
                "Reactive potential against {base_label}: {details}.",
                base_label=base_label,
                details=join_phrases(base_reactive_notes),
            )
        )
    else:
        lines.append(
            t(
                "frit.summary.base.reactive_no",
                "Reactive potential against {base_label}: no obvious reactive pairing appeared between the active frits and the chosen base.",
                base_label=base_label,
            )
        )

    lines.append(f"{local_separation_label}. {frit_behaviour_label(frit_size)}")
    lines.append(
        t(
            "frit.summary.mix.heuristic",
            "This page is still a heuristic: it uses optical averaging of the visible read rather than assuming the frit fully homogenizes during firing.",
        )
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
            component_weights.append(float(component["mm"]))
        mixed_rgb = weighted_rgb(component_rgbs, component_weights)
        mixed_brightness.append(rgb_to_hsb(mixed_rgb)[2])

    figure = go.Figure()
    for index, component in enumerate(components):
        figure.add_trace(
            go.Scatter(
                x=depth_values,
                y=component_brightness[str(component["slot"])],
                mode="lines",
                name=t("frit.figure.slot_brightness", "{slot} brightness", slot=component["slot"]),
                line=dict(color=line_colors[index % len(line_colors)], width=2.2),
            )
        )
    figure.add_trace(
        go.Scatter(
            x=depth_values,
            y=mixed_brightness,
            mode="lines",
            name=t("frit.figure.mixed_brightness", "Mixed brightness"),
            line=dict(color="#2f6a40", width=3),
        )
    )
    figure.add_vline(x=depth_selected, line_dash="dash", line_color="gray")
    figure.update_layout(
        title=t("frit.figure.brightness", "Brightness Across Depth"),
        xaxis_title=t("frit.figure.depth_axis", "Depth (mm)"),
        yaxis_title=t("frit.figure.brightness_axis", "Brightness (B)"),
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
        component_weights = [float(component["mm"]) for component in components]
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
        title=t("frit.figure.mixed_rgb", "Predicted Mixed RGB Across Depth"),
        xaxis_title=t("frit.figure.depth_axis", "Depth (mm)"),
        yaxis_title=t("frit.figure.channel_value", "Channel value"),
        yaxis=dict(range=[0, 260]),
        xaxis=dict(range=[0, max_depth]),
        legend=dict(orientation="h", y=1.08),
        height=320,
        margin=dict(l=30, r=10, t=48, b=30),
    )
    return figure


db_token = db_cache_token()
families = load_families(db_token).copy()
catalog = load_catalog(db_token).copy()
measurements = load_measurements(db_token).copy()

families["name"] = families["name"].astype(str)
catalog["glass_id"] = catalog["glass_id"].astype(str)
catalog["glass_family"] = catalog["glass_family"].astype(str)
catalog["family_name"] = catalog["family_name"].astype(str)
measurements["glass_id"] = measurements["glass_id"].astype(str)
measurements["mode"] = measurements["mode"].astype(str).str.upper()

if catalog.empty or measurements.empty:
    st.error(t("frit.messages.missing_data", "Glass catalog or measurement data is missing."))
    st.stop()

family_options = ["All"] + families["name"].tolist()
transparent_family_matches = families[families["code"].astype(str).str.strip() == "2"]
if not transparent_family_matches.empty:
    transparent_family_name = str(transparent_family_matches.iloc[0]["name"])
elif "Transparent" in family_options:
    transparent_family_name = "Transparent"
else:
    transparent_family_name = family_options[0]

st.sidebar.header(t("frit.sidebar.mix_setup", "Mix Setup"))
mode = st.sidebar.radio(
    t("frit.fields.reference_measurements", "Reference measurements"),
    ["T", "R"],
    index=1,
    format_func=translate_mode_name,
)

st.sidebar.header(t("frit.sidebar.light_base", "Light Base"))
base_family_default = family_options.index("Opalescent") if "Opalescent" in family_options else 0
base_family = st.sidebar.selectbox(
    t("frit.fields.base_family", "Base family"),
    family_options,
    index=base_family_default,
    format_func=lambda value: translate_family_name(None, value),
)
base_candidates = filter_catalog_by_family(catalog, base_family)
if base_candidates.empty:
    st.error(t("frit.messages.no_base_matches", "No glass samples match the current base family filter."))
    st.stop()

base_default_id = default_sample_id(base_candidates, ["French Vanilla", "Almond", "White"])
base_labels = sample_labels(base_candidates)
base_index = base_candidates["glass_id"].tolist().index(base_default_id)
base_id = st.sidebar.selectbox(
    t("frit.fields.base_glass", "Base glass"),
    base_candidates["glass_id"].tolist(),
    index=base_index,
    format_func=lambda glass_id: base_labels.get(glass_id, glass_id),
)
base_catalog_row = base_candidates[base_candidates["glass_id"] == base_id].iloc[0]
base_row_r = measurement_row(measurements, base_id, "R")
if base_row_r is None:
    st.error(
        t(
            "frit.messages.base_missing_reflected",
            "{label} is missing reflected data.",
            label=base_labels.get(base_id, base_id),
        )
    )
    st.stop()

frit_setup = [
    ("Frit 1", transparent_family_name, "001122", ["Red Transparent"], 2.0),
    ("Frit 2", transparent_family_name, "001426", ["Spring Green"], 2.0),
    ("Frit 3", transparent_family_name, "001464", ["True Blue"], 2.0),
]


def select_frit_component(
    slot_label: str,
    default_family_name: str,
    default_glass_id: str,
    preferred_terms: list[str],
    default_mm: float,
) -> dict[str, object]:
    family_default_index = family_options.index(default_family_name) if default_family_name in family_options else 0
    family_name = st.sidebar.selectbox(
        t("frit.fields.slot_family", "{slot} family", slot=slot_label),
        family_options,
        index=family_default_index,
        format_func=lambda value: translate_family_name(None, value),
    )
    candidates = filter_catalog_by_family(catalog, family_name)
    if candidates.empty:
        st.error(
            t(
                "frit.messages.no_slot_matches",
                "No glass samples match the current filter for {slot}.",
                slot=slot_label,
            )
        )
        st.stop()

    labels = sample_labels(candidates)
    glass_ids = candidates["glass_id"].tolist()
    default_id = default_glass_id if default_glass_id in glass_ids else default_sample_id(candidates, preferred_terms)
    default_index = glass_ids.index(default_id)
    glass_id = st.sidebar.selectbox(
        slot_label,
        glass_ids,
        index=default_index,
        format_func=lambda candidate_id: labels.get(candidate_id, candidate_id),
    )
    mm = st.sidebar.number_input(
        t("frit.fields.mm", "{slot} height (mm)", slot=slot_label),
        min_value=0.0,
        max_value=6.0,
        value=float(np.clip(default_mm, 0.0, 6.0)),
        step=0.1,
        format="%.1f",
    )

    catalog_row = candidates[candidates["glass_id"] == glass_id].iloc[0]
    measurement = measurement_row(measurements, glass_id, mode)
    if measurement is None and mm > 0:
        st.error(
            t(
                "frit.messages.slot_missing_mode",
                "{label} is missing {mode} data.",
                label=labels.get(glass_id, glass_id),
                mode=translate_mode_name(mode).lower(),
            )
        )
        st.stop()

    return {
        "slot": slot_label,
        "glass_id": glass_id,
        "label": labels.get(glass_id, glass_id),
        "mm": mm,
        "catalog_row": catalog_row,
        "row": measurement,
        "row_t": measurement_row(measurements, glass_id, "T"),
        "row_r": measurement_row(measurements, glass_id, "R"),
    }


components = []
st.sidebar.divider()
for index, (slot_label, default_family_name, default_glass_id, preferred_terms, default_mm) in enumerate(frit_setup):
    if index > 0:
        st.sidebar.divider()
    components.append(
        select_frit_component(slot_label, default_family_name, default_glass_id, preferred_terms, default_mm)
    )

frit_options = list(FRIT_BEHAVIOUR.keys())
default_frit_index = frit_options.index("Powdered")
frit_size = st.sidebar.selectbox(
    t("frit.fields.frit_size", "Frit size"),
    frit_options,
    index=default_frit_index,
    format_func=frit_size_label,
)

active_components = [component for component in components if float(component["mm"]) > 0]
total_mm = sum(float(component["mm"]) for component in active_components)
if total_mm <= 0:
    st.error(t("frit.messages.enter_grams", "Enter at least some frit height so the mix can be estimated."))
    st.stop()

for component in components:
    row = component["row"]
    if row is not None:
        component["rgb"] = modeled_rgb(row, total_mm)
        component["hsb"] = rgb_to_hsb(component["rgb"])
    else:
        component["rgb"] = (0, 0, 0)
        component["hsb"] = (0, 0, 0)
    component["prefix"] = row_prefix(component["catalog_row"])
    component["icon"] = first_existing_icon(component["glass_id"], component["prefix"], mode)

mixed_rgb = weighted_rgb(
    [component["rgb"] for component in active_components],
    [float(component["mm"]) for component in active_components],
)
mixed_hsb = rgb_to_hsb(mixed_rgb)
weighted_b = weighted_brightness(
    [component["hsb"][2] for component in active_components],
    [float(component["mm"]) for component in active_components],
)

pair_scores = []
pair_weights = []
for left_index, left_component in enumerate(active_components):
    for right_component in active_components[left_index + 1 :]:
        pair_scores.append(colour_distance(left_component["rgb"], right_component["rgb"]))
        pair_weights.append(float(left_component["mm"]) * float(right_component["mm"]))
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
mix_reactive_notes = component_reactive_details(active_components)
base_reactive_notes = base_reactive_details(active_components, base_catalog_row)

layering_ready = all(component["row_t"] is not None for component in active_components)
if layering_ready:
    # One-way depth = sum of all frit heights entered by the user
    frit_total_depth = total_mm

    def _mixed_filter(path: float) -> tuple:
        return weighted_rgb(
            [modeled_rgb(component["row_t"], path) for component in active_components],
            [float(component["mm"]) for component in active_components],
        )

    mixed_filter_single_rgb = _mixed_filter(frit_total_depth)
    mixed_filter_double_rgb = _mixed_filter(frit_total_depth * 2.0)
    mixed_filter_single_hsb = rgb_to_hsb(mixed_filter_single_rgb)
    layered_mix_rgb = layered_result_from_filter(base_rgb, mixed_filter_double_rgb)
    layered_mix_hsb = rgb_to_hsb(layered_mix_rgb)

    layered_lines = layered_mix_summary_lines(
        base_labels.get(base_id, base_id),
        base_hsb,
        mixed_filter_single_hsb,
        layered_mix_hsb,
        frit_total_depth,
    )
else:
    missing_layer_ids = [str(component["glass_id"]) for component in active_components if component["row_t"] is None]
    layered_lines = []

summary_lines = mix_summary_lines(
    active_components,
    mixed_hsb,
    weighted_b,
    total_mm,
    frit_size,
    local_separation_label,
    mix_reactive_notes,
    base_labels.get(base_id, base_id),
    base_reactive_notes,
)

st.title(t("frit.title", "Frit Mix Explorer"))
st.caption(
    t(
        "frit.caption.intro",
        "First-pass frit heuristic: the visible read is estimated as optical averaging across depth, with frit size affecting how much local colour separation is likely to remain.",
    )
)

st.markdown(
    '<div class="mix-summary">'
    + "".join(f"<p>{html.escape(line)}</p>" for line in summary_lines)
    + "</div>",
    unsafe_allow_html=True,
)
if mix_reactive_notes or base_reactive_notes:
    st.caption(
        t(
            "predictor.caption.reactive",
            "Reactive potential indicates a possible chemistry interaction. The visible result still depends on firing conditions like temperature, soak, thickness, and kiln atmosphere.",
        )
    )

badge_markup = "".join(
    [
        f'<span class="mix-badge">{t("color_wheel.fields.mode", "Mode")}: {html.escape(translate_mode_name(mode))}</span>',
        *[
            f'<span class="mix-badge">{html.escape(str(component["slot"]))}: {float(component["mm"]):.1f} mm</span>'
            for component in components
        ],
        f'<span class="mix-badge">{t("worksheet.labels.total", "Total")}: {total_mm:.1f} mm</span>',
        f'<span class="mix-badge">Weighted B: {weighted_b:.1f}</span>',
        f'<span class="mix-badge">{t("frit.fields.frit_size", "Frit size")}: {html.escape(frit_size_label(frit_size))}</span>',
        f'<span class="mix-badge">{html.escape(local_separation_label)}</span>',
    ]
)
st.markdown(badge_markup, unsafe_allow_html=True)

# ── Weight estimate (1 cm² area, glass density 2.5 g/cm³) ──────────────────
GLASS_DENSITY = 2.5          # g/cm³
AREA_CM2      = 1.0          # 1 cm × 1 cm

def mm_to_weight(mm: float) -> float:
    """Weight in grams for a 1 cm² column of glass at the given depth in mm."""
    return (mm / 10.0) * AREA_CM2 * GLASS_DENSITY

weight_rows = "".join(
    f"<tr>"
    f"<td style='padding:4px 12px 4px 0;'><strong>{html.escape(str(component['slot']))}</strong> — {html.escape(component['label'])}</td>"
    f"<td style='padding:4px 0;text-align:right;'>{float(component['mm']):.1f} mm</td>"
    f"<td style='padding:4px 0 4px 16px;text-align:right;'>{mm_to_weight(float(component['mm'])):.3f} g</td>"
    f"</tr>"
    for component in components
)
total_weight = mm_to_weight(total_mm)
weight_html = f"""
<div style='margin:0.75rem 0 1.25rem 0;padding:0.75rem 1rem;border:1px solid #e0e0e0;border-radius:8px;display:inline-block;min-width:360px;'>
  <div style='font-size:0.75rem;font-weight:700;letter-spacing:0.08em;color:#666;margin-bottom:0.5rem;'>
    {html.escape(t("frit.weight.title", "MIX WEIGHT ESTIMATE — 1 cm² area · 2.5 g/cm³"))}
  </div>
  <table style='border-collapse:collapse;font-size:0.9rem;'>
    {weight_rows}
    <tr style='border-top:1px solid #ccc;'>
      <td style='padding:6px 12px 2px 0;'><strong>{html.escape(t("worksheet.labels.total", "Total"))}</strong></td>
      <td style='padding:6px 0 2px 0;text-align:right;'><strong>{total_mm:.1f} mm</strong></td>
      <td style='padding:6px 0 2px 16px;text-align:right;'><strong>{total_weight:.3f} g</strong></td>
    </tr>
  </table>
  <div style='font-size:0.75rem;color:#888;margin-top:0.4rem;'>
    {html.escape(t("frit.weight.note", "Formula: (height mm ÷ 10) × 1 cm² × 2.5 g/cm³"))}
  </div>
</div>
"""
st.markdown(weight_html, unsafe_allow_html=True)

# ── Mold volume calculator ───────────────────────────────────────────────────
st.markdown(f"#### {t('frit.weight.mold_title', 'Mold volume calculator')}")
st.caption(t("frit.weight.mold_caption", "Enter the void volume of your mold to get the gram weight of each frit needed to fill it."))

vol_col1, vol_col2 = st.columns([1, 3], gap="medium")
with vol_col1:
    vol_unit = st.radio(
        t("frit.weight.vol_unit", "Volume unit"),
        options=["cm³", "mm³"],
        horizontal=True,
    )
    mold_volume_raw = st.number_input(
        t("frit.weight.mold_volume", "Mold void volume"),
        min_value=0.0,
        value=9.0 if vol_unit == "cm³" else 9000.0,
        step=0.1 if vol_unit == "cm³" else 1.0,
        format="%.2f" if vol_unit == "cm³" else "%.0f",
    )
    mold_volume_cm3 = mold_volume_raw if vol_unit == "cm³" else mold_volume_raw / 1000.0

with vol_col2:
    total_mold_weight = mold_volume_cm3 * GLASS_DENSITY
    mold_rows = "".join(
        f"<tr>"
        f"<td style='padding:4px 12px 4px 0;'><strong>{html.escape(str(component['slot']))}</strong> — {html.escape(component['label'])}</td>"
        f"<td style='padding:4px 8px;text-align:right;'>{float(component['mm']):.1f} mm</td>"
        f"<td style='padding:4px 8px;text-align:right;'>{(float(component['mm']) / total_mm * 100):.1f}%</td>"
        f"<td style='padding:4px 0 4px 8px;text-align:right;'><strong>{(float(component['mm']) / total_mm * total_mold_weight):.3f} g</strong></td>"
        f"</tr>"
        for component in active_components
    )
    mold_html = f"""
<div style='margin:0.25rem 0 1rem 0;padding:0.75rem 1rem;border:1px solid #e0e0e0;border-radius:8px;display:inline-block;min-width:420px;'>
  <div style='font-size:0.75rem;font-weight:700;letter-spacing:0.08em;color:#666;margin-bottom:0.5rem;'>
    {html.escape(t("frit.weight.mold_result_title", "FRIT WEIGHTS FOR {vol:.2f} {unit} VOID", vol=mold_volume_raw, unit=vol_unit))}
  </div>
  <table style='border-collapse:collapse;font-size:0.9rem;width:100%;'>
    <tr style='font-size:0.75rem;color:#888;'>
      <td style='padding:2px 12px 6px 0;'>{html.escape(t("frit.weight.col_frit", "Frit"))}</td>
      <td style='padding:2px 8px 6px 8px;text-align:right;'>{html.escape(t("frit.weight.col_height", "Height"))}</td>
      <td style='padding:2px 8px 6px 8px;text-align:right;'>{html.escape(t("frit.weight.col_share", "Share"))}</td>
      <td style='padding:2px 0 6px 8px;text-align:right;'>{html.escape(t("frit.weight.col_weight", "Weight"))}</td>
    </tr>
    {mold_rows}
    <tr style='border-top:1px solid #ccc;'>
      <td style='padding:6px 12px 2px 0;'><strong>{html.escape(t("worksheet.labels.total", "Total"))}</strong></td>
      <td style='padding:6px 8px 2px 8px;text-align:right;'><strong>{total_mm:.1f} mm</strong></td>
      <td style='padding:6px 8px 2px 8px;text-align:right;'><strong>100%</strong></td>
      <td style='padding:6px 0 2px 8px;text-align:right;'><strong>{total_mold_weight:.3f} g</strong></td>
    </tr>
  </table>
  <div style='font-size:0.75rem;color:#888;margin-top:0.5rem;'>
    {html.escape(t("frit.weight.mold_note", "Formula: volume ({vol:.4f} cm³) × 2.5 g/cm³ = {total:.3f} g total · each frit scaled by its mm share", vol=mold_volume_cm3, total=total_mold_weight))}
  </div>
</div>
"""
    st.markdown(mold_html, unsafe_allow_html=True)

st.divider()

card_cols = st.columns(4, gap="medium")
for column, component in zip(card_cols[:3], components):
    with column:
        st.markdown(f"### {component['label']}")
        st.caption(t("frit.cards.slot_caption", "{slot} at the selected depth.", slot=component["slot"]))
        if component["icon"] is not None:
            st.image(str(component["icon"]), width="content")
        elif MISSING_ICON.exists():
            st.image(str(MISSING_ICON), width="content")

        contribution_note = t("frit.cards.note_default", "Modeled from the selected measurement mode over the chosen depth.")
        if component["slot"] == "Frit 2":
            contribution_note = t("frit.cards.note_frit2", "Useful as a second colour body or as a nudge, depending on the selected height in mm.")
        if component["slot"] == "Frit 3":
            contribution_note = t("frit.cards.note_frit3", "Optional third frit for nudging the turn-to-black point or helping a difficult mix fit.")
        if float(component["mm"]) <= 0:
            contribution_note = t("frit.cards.note_zero", "Currently parked at 0.0 mm, so it is ready for use without changing the current mix.")

        mm_val = float(component["mm"])
        if mm_val <= 0:
            display_rgb = (255, 255, 255)
            display_hsb = (0, 0, 100)
        elif mm_val < 2.0:
            t_interp = mm_val / 2.0
            display_rgb = tuple(
                int(round(255 + (component["rgb"][i] - 255) * t_interp))
                for i in range(3)
            )
            display_hsb = rgb_to_hsb(display_rgb)
        else:
            display_rgb = component["rgb"]
            display_hsb = component["hsb"]
        st.markdown(
            swatch_markup(
                t("frit.cards.slot_title", "{slot} contribution", slot=component["slot"]),
                t("frit.cards.slot_subtitle", "{mm:.1f} mm height in the mix", mm=mm_val),
                display_rgb,
                display_hsb,
                contribution_note,
            ),
            unsafe_allow_html=True,
        )

with card_cols[3]:
    st.markdown(f"### {t('frit.sections.predicted_mix', 'Predicted mixed read')}")
    st.caption(t("frit.cards.mix_caption", "Optically averaged result at the selected depth."))
    st.markdown(
        swatch_markup(
            t("frit.cards.mix_title", "Predicted mixed result"),
            t("frit.cards.mix_subtitle", "Weighted visual read from {total:.1f} mm total height", total=total_mm),
            mixed_rgb,
            mixed_hsb,
            t("frit.cards.mix_note", "This is not a full melt blend. It is a first-pass estimate of how the mixed frit field may read. Weighted B = {weighted_b:.1f}.", weighted_b=weighted_b),
        ),
        unsafe_allow_html=True,
    )

if layering_ready:
    st.markdown(f"### {t('frit.sections.layered_base', 'Layered over light base')}")
    st.caption(
        t(
            "frit.cards.layered_caption",
            "This section uses the selected frit mix as a transmitted filter over the chosen light base, with a round-trip path through the frit field. The 3 mm and 6 mm columns show fixed-depth reference previews.",
        )
    )
    st.markdown(
        '<div class="mix-summary">'
        + "".join(f"<p>{html.escape(line)}</p>" for line in layered_lines)
        + "</div>",
        unsafe_allow_html=True,
    )

    layered_cols = st.columns(2, gap="medium")
    with layered_cols[0]:
        st.markdown(f"### {base_labels.get(base_id, base_id)}")
        st.caption(t("frit.cards.base_caption", "Light base used as the reflected return source."))
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
                t("frit.cards.base_note", "This is the return light from the base before the frit field filters it."),
            ),
            unsafe_allow_html=True,
        )

    with layered_cols[1]:
        st.markdown(f"### {t('frit.sections.predicted_layered', 'Predicted layered read')}")
        st.caption(t("frit.cards.layered_result_caption", f"Round-trip at your mix total: {frit_total_depth:.1f} mm one-way."))
        st.markdown(
            swatch_markup(
                t("predictor.cards.result_title", "Predicted reflected result"),
                t("frit.cards.layered_result_subtitle", "Round trip through {depth:.1f} mm × 2 = {trip:.1f} mm", depth=frit_total_depth, trip=frit_total_depth * 2.0),
                layered_mix_rgb,
                layered_mix_hsb,
                t("frit.cards.layered_result_note", "Result = base filtered through the frit field down and back at your current mix height."),
            ),
            unsafe_allow_html=True,
        )

else:
    st.info(
        t(
            "frit.messages.layered_unavailable",
            "Layered-over-base preview is unavailable for the current mix because transmitted data is missing for: {items}",
            items=", ".join(missing_layer_ids),
        )
    )

chart_left, chart_right = st.columns(2, gap="large")
with chart_left:
    st.plotly_chart(
        brightness_depth_figure(active_components, total_mm),
        config={"displaylogo": False},
    )
with chart_right:
    st.plotly_chart(
        mixed_rgb_depth_figure(active_components, total_mm),
        config={"displaylogo": False},
    )

st.markdown(f"### {t('frit.sections.model_notes', 'Model Notes')}")
st.markdown(
    "\n".join(
        [
            f"- {t('frit.notes.exploratory', 'This page is exploratory rather than prescriptive. It gives a studio-friendly estimate of the visible read.')}",
            f"- {t('library.notes.datum', 'Library colors are based on measurements taken from each physical sample at its recorded thickness under broad daylight-balanced illumination. Changes in thickness, lighting, and batch variation can shift the visible read away from this reference.')}",
            f"- {t('frit.notes.frit_size', 'Frit size does not change the weighted average colour directly here; it changes the expected amount of local colour separation that may still be visible.')}",
            f"- {t('frit.notes.powdered', 'Powdered glass is treated here as the smoothest-integrating option, but in practice trapped air and bubbles still need to be addressed before firing.')}",
            f"- {t('frit.notes.homogenization', 'The page does not assume complete homogenization during firing.')}",
            f"- {t('frit.notes.brightness_chart', 'The brightness chart is there because brightness is often the easiest depth signal to use when you are building a transition through a thicker frit field.')}",
        ]
    )
)
