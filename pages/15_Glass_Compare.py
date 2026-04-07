from __future__ import annotations

import html
import math
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "glass_library.sqlite"
IMG_ROOT = APP_ROOT / "images"
MISSING_FULL = IMG_ROOT / "_placeholders" / "missing_full.tiff"
MISSING_ICON = IMG_ROOT / "_placeholders" / "missing_icon.jpg"
DETAIL_PAGE = "pages/8_Glass_Detail.py"
LIBRARY_PAGE = "pages/6_Glass_Library.py"
MAX_COMPARE = 4

FAMILY_PREFIX_BY_CODE = {
    "1": "opal",
    "2": "transparent",
    "3": "tint",
}

MODE_LABELS = {
    "R": "Reflected",
    "T": "Transmitted",
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

st.set_page_config(page_title="Glass Compare", layout="wide")
st.markdown(
    """
    <style>
    div[data-testid="stButton"] > button {
        padding: 0.28rem 0.62rem;
        min-height: 2.0rem;
        line-height: 1.08;
    }
    div[data-testid="stButton"] > button p {
        font-size: 0.82rem;
        line-height: 1.08;
    }
    .compare-chip-row {
        display:flex;
        flex-wrap:wrap;
        gap:0.32rem;
        margin:0.2rem 0 0.45rem 0;
    }
    .compare-chip {
        display:inline-flex;
        align-items:center;
        border-radius:999px;
        padding:0.18rem 0.5rem;
        font-family:sans-serif;
        font-size:0.72rem;
        font-weight:600;
        line-height:1.1;
        border:1px solid transparent;
    }
    .compare-chip--reference { background:#e8f1ff; color:#26415f; border-color:#c8daf6; }
    .compare-chip--pos { background:#e8f4ea; color:#2f6a40; border-color:#c8e2cf; }
    .compare-chip--neg { background:#f8e8e4; color:#8c4133; border-color:#efcfc7; }
    .compare-chip--chem { background:#f7f1e6; color:#7c5a22; border-color:#ead8b5; }
    .compare-chip--neutral { background:#eff1f5; color:#4b5568; border-color:#d9dde6; }
    .compare-summary {
        font-family:sans-serif;
        font-size:0.82rem;
        line-height:1.3;
        color:#666f82;
        margin:0.1rem 0 0.4rem 0;
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


def compare_title_markup(glass_id: str, title: str) -> str:
    heading = f"{glass_id} {title}".strip() if title else str(glass_id)
    return (
        '<div style="font-family:sans-serif;'
        'font-size:1.15rem;'
        'font-weight:700;'
        'line-height:1.12;'
        'color:#31364a;'
        'margin:0 0 0.55rem 0;">'
        f"{html.escape(heading)}"
        "</div>"
    )


def join_phrases(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def circular_hue_delta(reference_value, compare_value) -> float | None:
    reference_numeric = pd.to_numeric(reference_value, errors="coerce")
    compare_numeric = pd.to_numeric(compare_value, errors="coerce")
    if pd.isna(reference_numeric) or pd.isna(compare_numeric):
        return None
    delta = ((float(compare_numeric) - float(reference_numeric) + 180.0) % 360.0) - 180.0
    if abs(delta) < 1e-9:
        return 0.0
    return delta


def measurement_delta_value(
    reference_row: pd.Series | None,
    compare_row: pd.Series | None,
    field: str,
) -> float | None:
    if reference_row is None or compare_row is None:
        return None
    reference_value = pd.to_numeric(reference_row.get(field), errors="coerce")
    compare_value = pd.to_numeric(compare_row.get(field), errors="coerce")
    if pd.isna(reference_value) or pd.isna(compare_value):
        return None
    if field == "h":
        return circular_hue_delta(reference_value, compare_value)
    return float(compare_value) - float(reference_value)


def chip_row_markup(chips: list[tuple[str, str]], *, max_chips: int | None = None) -> str:
    if max_chips is not None:
        chips = chips[:max_chips]
    if not chips:
        chips = [("Close match", "neutral")]
    spans = []
    for label, tone in chips:
        tone_name = tone if tone in {"reference", "pos", "neg", "chem", "neutral"} else "neutral"
        spans.append(
            f'<span class="compare-chip compare-chip--{tone_name}">{html.escape(label)}</span>'
        )
    return '<div class="compare-chip-row">' + "".join(spans) + "</div>"


def comparison_delta_chips(
    reference_catalog: pd.Series,
    compare_catalog: pd.Series,
    reference_r: pd.Series | None,
    compare_r: pd.Series | None,
    reference_t: pd.Series | None,
    compare_t: pd.Series | None,
    *,
    is_reference: bool = False,
) -> list[tuple[str, str]]:
    if is_reference:
        return [("Reference sample", "reference")]

    chips: list[tuple[str, str]] = []
    for mode_short, reference_row, compare_row in (("R", reference_r, compare_r), ("T", reference_t, compare_t)):
        for field, label, suffix, threshold in (("h", "H", "°", 4.0), ("s", "S", "", 4.0), ("v", "B", "", 4.0)):
            delta = measurement_delta_value(reference_row, compare_row, field)
            if delta is None or abs(delta) < threshold:
                continue
            tone = "pos" if delta > 0 else "neg"
            chips.append((f"{mode_short} {label} {delta:+.0f}{suffix}", tone))

    reference_elements = set(element_labels(reference_catalog))
    compare_elements = set(element_labels(compare_catalog))
    added_elements = sorted(compare_elements - reference_elements)
    removed_elements = sorted(reference_elements - compare_elements)
    if added_elements:
        chips.append((f"+{added_elements[0]}", "chem"))
    if removed_elements:
        chips.append((f"-{removed_elements[0]}", "chem"))

    reference_striker = safe_int(reference_catalog.get("is_striker"), 0) == 1
    compare_striker = safe_int(compare_catalog.get("is_striker"), 0) == 1
    if reference_striker != compare_striker:
        chips.append((("Striker" if compare_striker else "Not striker"), "chem"))

    if not chips:
        chips.append(("Close match", "neutral"))
    return chips


def describe_change(
    delta: float | None,
    positive_text: str,
    negative_text: str,
    *,
    slight_threshold: float = 4.0,
    strong_threshold: float = 14.0,
) -> str | None:
    if delta is None or abs(delta) < slight_threshold:
        return None
    qualifier = "slightly " if abs(delta) < strong_threshold else ""
    return f"{qualifier}{positive_text if delta > 0 else negative_text}"


def describe_hue_shift(
    delta: float | None,
    *,
    slight_threshold: float = 8.0,
    strong_threshold: float = 20.0,
) -> str | None:
    if delta is None or abs(delta) < slight_threshold:
        return None
    qualifier = "slightly " if abs(delta) < strong_threshold else "noticeably "
    return f"{qualifier}shifted by {abs(delta):.0f}°"


def measurement_interpretation_lines(
    mode_label: str,
    reference_row: pd.Series | None,
    compare_row: pd.Series | None,
) -> list[str]:
    if reference_row is None or compare_row is None:
        return []

    lines: list[str] = []
    qualities: list[str] = []
    brightness_text = describe_change(
        measurement_delta_value(reference_row, compare_row, "v"),
        "brighter",
        "darker",
    )
    saturation_text = describe_change(
        measurement_delta_value(reference_row, compare_row, "s"),
        "more saturated",
        "less saturated",
    )
    if brightness_text:
        qualities.append(brightness_text)
    if saturation_text:
        qualities.append(saturation_text)
    if qualities:
        lines.append(f"In {mode_label}, it reads {join_phrases(qualities)} than the reference.")

    hue_text = describe_hue_shift(measurement_delta_value(reference_row, compare_row, "h"))
    if hue_text:
        lines.append(f"Its {mode_label} hue is {hue_text}.")

    return lines


def comparison_interpretation_lines(
    reference_catalog: pd.Series,
    compare_catalog: pd.Series,
    reference_r: pd.Series | None,
    compare_r: pd.Series | None,
    reference_t: pd.Series | None,
    compare_t: pd.Series | None,
) -> list[str]:
    lines: list[str] = []
    lines.extend(measurement_interpretation_lines("reflected light", reference_r, compare_r))
    lines.extend(measurement_interpretation_lines("transmission", reference_t, compare_t))

    reference_family = str(reference_catalog.get("family_name") or reference_catalog.get("glass_family") or "")
    compare_family = str(compare_catalog.get("family_name") or compare_catalog.get("glass_family") or "")
    if compare_family and reference_family and compare_family != reference_family:
        lines.append(f"It belongs to the {compare_family} family rather than {reference_family}.")

    reference_elements = set(element_labels(reference_catalog))
    compare_elements = set(element_labels(compare_catalog))
    added_elements = sorted(compare_elements - reference_elements)
    removed_elements = sorted(reference_elements - compare_elements)
    if added_elements or removed_elements:
        chemistry_bits: list[str] = []
        if added_elements:
            chemistry_bits.append(f"adds {join_labels(added_elements)}")
        if removed_elements:
            chemistry_bits.append(f"omits {join_labels(removed_elements)}")
        lines.append("Chemistry: it " + join_phrases(chemistry_bits) + ".")

    reference_reactive = set(reactive_labels(reference_catalog))
    compare_reactive = set(reactive_labels(compare_catalog))
    added_reactive = sorted(compare_reactive - reference_reactive)
    removed_reactive = sorted(reference_reactive - compare_reactive)
    if added_reactive or removed_reactive:
        reactive_bits: list[str] = []
        if added_reactive:
            reactive_bits.append(f"may react with {join_labels(added_reactive)}")
        if removed_reactive:
            reactive_bits.append(f"is less likely to react with {join_labels(removed_reactive)}")
        lines.append("Reactive potential: it " + join_phrases(reactive_bits) + ".")

    reference_striker = safe_int(reference_catalog.get("is_striker"), 0) == 1
    compare_striker = safe_int(compare_catalog.get("is_striker"), 0) == 1
    if reference_striker != compare_striker:
        if compare_striker:
            lines.append("It is a striker, unlike the reference.")
        else:
            lines.append("It is not a striker, unlike the reference.")

    if not lines:
        lines.append("It reads very close to the reference sample in the current summary.")

    return lines


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


def first_existing_icon(cat_id: str, prefix: str, preferred_mode: str = "R") -> Path | None:
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
                    c.au,
                    c.cold_characteristics,
                    c.working_notes
                FROM glass_catalog c
                LEFT JOIN glass_families f
                    ON f.code = c.glass_family
                ORDER BY c.cat_id;
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


def measurement_row(measurements: pd.DataFrame, glass_id: str, mode: str) -> pd.Series | None:
    matches = measurements[
        (measurements["glass_id"].astype(str) == str(glass_id))
        & (measurements["mode"].astype(str).str.upper() == mode)
    ]
    if matches.empty:
        return None
    return matches.iloc[0]


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


def render_notes(title: str, raw_text: str | None) -> None:
    markup = note_markup(raw_text)
    if not markup:
        st.caption(f"{title}: none")
        return
    with st.expander(title, expanded=False):
        st.markdown(markup, unsafe_allow_html=True)


def render_measurement_panel(glass_id: str, prefix: str, row: pd.Series | None, mode: str) -> None:
    image = full_path(str(glass_id), prefix, mode)
    if image is not None:
        st.image(str(image), width="content")
    elif MISSING_FULL.exists():
        st.image(str(MISSING_FULL), width="content")
    elif MISSING_ICON.exists():
        st.image(str(MISSING_ICON), width="content")

    if row is None:
        st.write("No measurement data for this mode.")
        return

    st.markdown(
        "\n".join(
            [
                f"**RGB:** ({row.get('r')}, {row.get('g')}, {row.get('b')})  ",
                f"**HSB:** ({row.get('h')}, {row.get('s')}, {row.get('v')})  ",
                f"**Thickness:** {row.get('thickness_mm') or '-'} mm",
            ]
        )
    )


def beer_lambert_curve(
    channel_value: float,
    ref_thickness: float,
    max_thickness: float,
    n_points: int = 160,
) -> tuple[np.ndarray, np.ndarray]:
    intensity_zero = 255.0
    cv = max(channel_value, 1.0)
    rt = max(ref_thickness, 0.01)
    alpha = -math.log(cv / intensity_zero) / rt
    thickness_values = np.linspace(0, max_thickness, n_points)
    channel_values = intensity_zero * np.exp(-alpha * thickness_values)
    channel_values = np.clip(channel_values, 0, 255)
    return thickness_values, channel_values


def hsv_brightness_curve(
    brightness_value: float,
    ref_thickness: float,
    max_thickness: float,
    n_points: int = 160,
) -> tuple[np.ndarray, np.ndarray]:
    intensity_zero = 100.0
    cv = max(brightness_value, 0.1)
    rt = max(ref_thickness, 0.01)
    alpha = -math.log(cv / intensity_zero) / rt
    thickness_values = np.linspace(0, max_thickness, n_points)
    brightness = intensity_zero * np.exp(-alpha * thickness_values)
    brightness = np.clip(brightness, 0, 100)
    return thickness_values, brightness


def hsv_saturation_curve(
    r_value: float,
    g_value: float,
    b_value: float,
    ref_thickness: float,
    max_thickness: float,
    n_points: int = 160,
) -> tuple[np.ndarray, np.ndarray]:
    rt = max(ref_thickness, 0.01)
    thickness_values = np.linspace(0, max_thickness, n_points)
    _, r_arr = beer_lambert_curve(r_value, rt, max_thickness, n_points)
    _, g_arr = beer_lambert_curve(g_value, rt, max_thickness, n_points)
    _, b_arr = beer_lambert_curve(b_value, rt, max_thickness, n_points)
    cmax = np.maximum(np.maximum(r_arr, g_arr), b_arr)
    cmin = np.minimum(np.minimum(r_arr, g_arr), b_arr)
    saturation = np.where(cmax > 0, (cmax - cmin) / cmax * 100.0, 0.0)
    saturation = np.clip(saturation, 0, 100)
    return thickness_values, saturation


def transmittance(rgb_value: float) -> str:
    return f"{(rgb_value / 255.0) * 100:.1f}%"


def measurement_table_html(meas: pd.Series | dict) -> str:
    r_value = safe_int(meas.get("r") if isinstance(meas, pd.Series) else meas.get("R"))
    g_value = safe_int(meas.get("g") if isinstance(meas, pd.Series) else meas.get("G"))
    b_value = safe_int(meas.get("b") if isinstance(meas, pd.Series) else meas.get("B"))
    h_value = safe_int(meas.get("h") if isinstance(meas, pd.Series) else meas.get("H"))
    s_value = safe_int(meas.get("s") if isinstance(meas, pd.Series) else meas.get("S"))
    v_value = safe_int(meas.get("v") if isinstance(meas, pd.Series) else meas.get("V"))

    return f"""
    <table style="border-collapse:collapse; width:100%; font-size:12px;">
      <tbody>
        <tr style="background:#f5f5f5;">
          <td style="padding:5px 10px; font-weight:bold; width:72px;">HSB</td>
          <td style="padding:5px 10px; text-align:center;">{h_value}</td>
          <td style="padding:5px 10px; text-align:center;">{s_value}</td>
          <td style="padding:5px 10px; text-align:center;">{v_value}</td>
        </tr>
        <tr>
          <td style="padding:5px 10px; font-weight:bold;">RGB</td>
          <td style="padding:5px 10px; text-align:center;">{r_value}</td>
          <td style="padding:5px 10px; text-align:center;">{g_value}</td>
          <td style="padding:5px 10px; text-align:center;">{b_value}</td>
        </tr>
        <tr style="background:#f5f5f5;">
          <td style="padding:5px 10px; font-weight:bold;">η</td>
          <td style="padding:5px 10px; text-align:center;">{transmittance(r_value)}</td>
          <td style="padding:5px 10px; text-align:center;">{transmittance(g_value)}</td>
          <td style="padding:5px 10px; text-align:center;">{transmittance(b_value)}</td>
        </tr>
      </tbody>
    </table>
    """


def rgb_curve_figure(meas: pd.Series, thickness: float, max_thickness: float, title: str) -> go.Figure:
    fig = go.Figure()
    for field, colour, label in (("r", "red", "R"), ("g", "green", "G"), ("b", "blue", "B")):
        thickness_values, channel_values = beer_lambert_curve(
            safe_int(meas.get(field)),
            thickness,
            max_thickness,
        )
        fig.add_trace(
            go.Scatter(
                x=thickness_values,
                y=channel_values,
                mode="lines",
                name=label,
                line=dict(color=colour, width=2),
            )
        )
    fig.add_vline(x=thickness, line_dash="dash", line_color="gray")
    fig.update_layout(
        title=title,
        xaxis_title="Thickness (mm)",
        yaxis_title="Channel Value",
        yaxis=dict(range=[0, 260]),
        xaxis=dict(range=[0, max_thickness]),
        legend=dict(orientation="h", y=1.08),
        height=240,
        margin=dict(l=30, r=10, t=48, b=30),
    )
    return fig


def bs_curve_figure(meas: pd.Series, thickness: float, max_thickness: float, title: str) -> go.Figure:
    fig = go.Figure()
    thickness_values, brightness = hsv_brightness_curve(
        safe_int(meas.get("v")),
        thickness,
        max_thickness,
    )
    _, saturation = hsv_saturation_curve(
        safe_int(meas.get("r")),
        safe_int(meas.get("g")),
        safe_int(meas.get("b")),
        thickness,
        max_thickness,
    )
    fig.add_trace(
        go.Scatter(
            x=thickness_values,
            y=brightness,
            mode="lines",
            name="Brightness",
            line=dict(color="cornflowerblue", width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=thickness_values,
            y=saturation,
            mode="lines",
            name="Saturation",
            line=dict(color="limegreen", width=2),
        )
    )
    fig.add_vline(x=thickness, line_dash="dash", line_color="gray")
    fig.update_layout(
        title=title,
        xaxis_title="Thickness (mm)",
        yaxis_title="0–100",
        yaxis=dict(range=[0, 105]),
        xaxis=dict(range=[0, max_thickness]),
        legend=dict(orientation="h", y=1.08),
        height=240,
        margin=dict(l=30, r=10, t=48, b=30),
    )
    return fig


def overlay_max_thickness(reference_row: pd.Series | None, compare_row: pd.Series | None) -> float:
    thicknesses = []
    for row in (reference_row, compare_row):
        if row is None:
            continue
        thicknesses.append(max(safe_float(row.get("thickness_mm"), default=2.0), 0.01))
    if not thicknesses:
        return 8.0
    return max(max(thicknesses) * 4.0, max(thicknesses))


def overlay_rgb_curve_figure(
    reference_row: pd.Series | None,
    compare_row: pd.Series | None,
    title: str,
) -> go.Figure | None:
    if reference_row is None or compare_row is None:
        return None

    reference_thickness = max(safe_float(reference_row.get("thickness_mm"), default=2.0), 0.01)
    compare_thickness = max(safe_float(compare_row.get("thickness_mm"), default=2.0), 0.01)
    max_thickness = overlay_max_thickness(reference_row, compare_row)
    fig = go.Figure()
    neutral = "rgba(110, 118, 132, 0.92)"
    channel_specs = (
        ("r", "R", "solid", "#df3b2f"),
        ("g", "G", "dash", "#2d9d63"),
        ("b", "B", "dot", "#2d63d8"),
    )
    for field, label, reference_dash, compare_colour in channel_specs:
        thickness_values, reference_curve = beer_lambert_curve(
            safe_int(reference_row.get(field)),
            reference_thickness,
            max_thickness,
        )
        compare_x, compare_curve = beer_lambert_curve(
            safe_int(compare_row.get(field)),
            compare_thickness,
            max_thickness,
        )
        fig.add_trace(
            go.Scatter(
                x=thickness_values,
                y=reference_curve,
                mode="lines",
                name=f"Ref {label}",
                line=dict(color=neutral, width=4, dash=reference_dash),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=compare_x,
                y=compare_curve,
                mode="lines",
                name=f"Sample {label}",
                line=dict(color=compare_colour, width=2.3),
            )
        )
    fig.add_vline(x=reference_thickness, line_dash="dash", line_color="#7f8796", opacity=0.45)
    fig.add_vline(x=compare_thickness, line_dash="dot", line_color="#31364a", opacity=0.35)
    fig.update_layout(
        title=title,
        xaxis_title="Thickness (mm)",
        yaxis_title="Channel Value",
        yaxis=dict(range=[0, 260]),
        xaxis=dict(range=[0, max_thickness]),
        legend=dict(orientation="h", y=1.12, x=0),
        height=250,
        margin=dict(l=30, r=10, t=52, b=30),
    )
    return fig


def overlay_bs_curve_figure(
    reference_row: pd.Series | None,
    compare_row: pd.Series | None,
    title: str,
) -> go.Figure | None:
    if reference_row is None or compare_row is None:
        return None

    reference_thickness = max(safe_float(reference_row.get("thickness_mm"), default=2.0), 0.01)
    compare_thickness = max(safe_float(compare_row.get("thickness_mm"), default=2.0), 0.01)
    max_thickness = overlay_max_thickness(reference_row, compare_row)
    fig = go.Figure()
    reference_x, reference_brightness = hsv_brightness_curve(
        safe_int(reference_row.get("v")),
        reference_thickness,
        max_thickness,
    )
    _, reference_saturation = hsv_saturation_curve(
        safe_int(reference_row.get("r")),
        safe_int(reference_row.get("g")),
        safe_int(reference_row.get("b")),
        reference_thickness,
        max_thickness,
    )
    compare_x, compare_brightness = hsv_brightness_curve(
        safe_int(compare_row.get("v")),
        compare_thickness,
        max_thickness,
    )
    _, compare_saturation = hsv_saturation_curve(
        safe_int(compare_row.get("r")),
        safe_int(compare_row.get("g")),
        safe_int(compare_row.get("b")),
        compare_thickness,
        max_thickness,
    )
    neutral = "rgba(110, 118, 132, 0.92)"
    fig.add_trace(
        go.Scatter(
            x=reference_x,
            y=reference_brightness,
            mode="lines",
            name="Ref Brightness",
            line=dict(color=neutral, width=4),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=reference_x,
            y=reference_saturation,
            mode="lines",
            name="Ref Saturation",
            line=dict(color=neutral, width=4, dash="dash"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=compare_x,
            y=compare_brightness,
            mode="lines",
            name="Sample Brightness",
            line=dict(color="cornflowerblue", width=2.3),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=compare_x,
            y=compare_saturation,
            mode="lines",
            name="Sample Saturation",
            line=dict(color="limegreen", width=2.3),
        )
    )
    fig.add_vline(x=reference_thickness, line_dash="dash", line_color="#7f8796", opacity=0.45)
    fig.add_vline(x=compare_thickness, line_dash="dot", line_color="#31364a", opacity=0.35)
    fig.update_layout(
        title=title,
        xaxis_title="Thickness (mm)",
        yaxis_title="0–100",
        yaxis=dict(range=[0, 105]),
        xaxis=dict(range=[0, max_thickness]),
        legend=dict(orientation="h", y=1.12, x=0),
        height=250,
        margin=dict(l=30, r=10, t=52, b=30),
    )
    return fig


def render_measurement_detail(glass_id: str, prefix: str, row: pd.Series | None, mode: str) -> None:
    image = full_path(str(glass_id), prefix, mode)
    if row is not None:
        components.html(measurement_table_html(row), height=110)
        st.caption(f"Thickness: {row.get('thickness_mm') or '-'} mm")
    else:
        st.write("No measurement data for this mode.")

    if image is not None:
        st.image(str(image), width="content")
    elif MISSING_FULL.exists():
        st.image(str(MISSING_FULL), width="content")
    elif MISSING_ICON.exists():
        st.image(str(MISSING_ICON), width="content")


def render_optical_detail(
    glass_id: str,
    prefix: str,
    row_r: pd.Series | None,
    row_t: pd.Series | None,
) -> None:
    available_rows = [row for row in (row_r, row_t) if row is not None]
    if not available_rows:
        st.caption("No optical response data available.")
        return

    thickness = safe_float(
        (row_r.get("thickness_mm") if row_r is not None else None)
        or (row_t.get("thickness_mm") if row_t is not None else None),
        default=2.0,
    )
    max_thickness = max(thickness * 4.0, thickness)

    if row_r is not None:
        reflected_icon = first_existing_icon(glass_id, prefix, "R")
        if reflected_icon is not None:
            st.image(str(reflected_icon), width=140)
        elif MISSING_ICON.exists():
            st.image(str(MISSING_ICON), width=140)
        st.markdown("#### Reflected optical response")
        st.plotly_chart(
            rgb_curve_figure(row_r, thickness, max_thickness, "Reflected Color Shift"),
            config={"displaylogo": False},
        )
        st.plotly_chart(
            bs_curve_figure(row_r, thickness, max_thickness, "Reflected Brightness & Saturation"),
            config={"displaylogo": False},
        )
    if row_t is not None:
        transmitted_icon = first_existing_icon(glass_id, prefix, "T")
        if transmitted_icon is not None:
            st.image(str(transmitted_icon), width=140)
        elif MISSING_ICON.exists():
            st.image(str(MISSING_ICON), width=140)
        st.markdown("#### Transmitted optical response")
        st.plotly_chart(
            rgb_curve_figure(row_t, thickness, max_thickness, "Transmitted Color Shift"),
            config={"displaylogo": False},
        )
        st.plotly_chart(
            bs_curve_figure(row_t, thickness, max_thickness, "Transmitted Brightness & Saturation"),
            config={"displaylogo": False},
        )


def join_labels(values: list[str]) -> str:
    return ", ".join(values) if values else "-"


def measurement_delta_lines(
    reference_row: pd.Series | None,
    compare_row: pd.Series | None,
    mode_label: str,
) -> list[str]:
    if reference_row is None and compare_row is None:
        return []
    if reference_row is None:
        return [f"{mode_label}: no reference measurement"]
    if compare_row is None:
        return [f"{mode_label}: no measurement"]

    lines = []
    for field, label in (
        ("r", "R"),
        ("g", "G"),
        ("b", "B"),
        ("h", "H"),
        ("s", "S"),
        ("v", "B"),
        ("thickness_mm", "Thickness"),
    ):
        reference_value = pd.to_numeric(reference_row.get(field), errors="coerce")
        compare_value = pd.to_numeric(compare_row.get(field), errors="coerce")
        if pd.isna(reference_value) or pd.isna(compare_value):
            continue
        delta = float(compare_value) - float(reference_value)
        if abs(delta) < 1e-9:
            continue
        if field == "thickness_mm":
            lines.append(f"{mode_label} thickness: {delta:+.2f} mm")
        elif field in {"h", "s", "v"}:
            lines.append(f"{mode_label} {label}: {delta:+.0f}")
        else:
            lines.append(f"{mode_label} {label}: {delta:+.0f}")
    return lines


def render_differences(
    selected: pd.DataFrame,
    measurements: pd.DataFrame,
) -> None:
    if len(selected) < 2:
        return

    reference = selected.iloc[0]
    reference_id = str(reference["glass_id"])
    reference_name = str(reference.get("color_name") or "").strip()
    reference_label = f"{reference_id} {reference_name}".strip()
    reference_r = measurement_row(measurements, reference_id, "R")
    reference_t = measurement_row(measurements, reference_id, "T")

    st.markdown("## Differences")
    st.caption(
        f"Reference sample: {reference_label}. Gray curves show the reference sample and colour curves show the compared glass."
    )

    for row in selected.iloc[1:].itertuples(index=False):
        glass_id = str(row.glass_id)
        color_name = str(row.color_name or "").strip()
        compare_label = f"{glass_id} {color_name}".strip()
        row_series = pd.Series(row._asdict())
        compare_r = measurement_row(measurements, glass_id, "R")
        compare_t = measurement_row(measurements, glass_id, "T")
        summary_lines = comparison_interpretation_lines(
            reference,
            row_series,
            reference_r,
            compare_r,
            reference_t,
            compare_t,
        )
        chip_markup = chip_row_markup(
            comparison_delta_chips(
                reference,
                row_series,
                reference_r,
                compare_r,
                reference_t,
                compare_t,
            ),
            max_chips=10,
        )

        with st.expander(f"{compare_label} vs {reference_label}", expanded=False):
            st.markdown("**Plain-language read**")
            for line in summary_lines:
                st.markdown(f"- {line}")

            st.markdown("**Quick deltas**")
            st.markdown(chip_markup, unsafe_allow_html=True)

            overlay_left, overlay_right = st.columns(2, gap="large")
            with overlay_left:
                st.markdown("**Reflected overlay**")
                reflected_rgb = overlay_rgb_curve_figure(
                    reference_r,
                    compare_r,
                    "Reflected Color Shift Overlay",
                )
                reflected_bs = overlay_bs_curve_figure(
                    reference_r,
                    compare_r,
                    "Reflected Brightness & Saturation Overlay",
                )
                if reflected_rgb is not None:
                    st.plotly_chart(reflected_rgb, config={"displaylogo": False})
                    st.plotly_chart(reflected_bs, config={"displaylogo": False})
                else:
                    st.caption("No reflected overlay data available.")

            with overlay_right:
                st.markdown("**Transmitted overlay**")
                transmitted_rgb = overlay_rgb_curve_figure(
                    reference_t,
                    compare_t,
                    "Transmitted Color Shift Overlay",
                )
                transmitted_bs = overlay_bs_curve_figure(
                    reference_t,
                    compare_t,
                    "Transmitted Brightness & Saturation Overlay",
                )
                if transmitted_rgb is not None:
                    st.plotly_chart(transmitted_rgb, config={"displaylogo": False})
                    st.plotly_chart(transmitted_bs, config={"displaylogo": False})
                else:
                    st.caption("No transmitted overlay data available.")

catalog = load_catalog().copy()
measurements = load_measurements().copy()
catalog["glass_id"] = catalog["glass_id"].astype(str)
catalog["glass_family"] = catalog["glass_family"].astype(str)
catalog["family_name"] = catalog["family_name"].astype(str)
measurements["glass_id"] = measurements["glass_id"].astype(str)
measurements["mode"] = measurements["mode"].astype(str).str.upper()

compare_ids = normalize_compare_ids(st.session_state.get("compare_glass_ids", []))
st.session_state["compare_glass_ids"] = compare_ids

header_left, header_mid, header_right = st.columns([0.18, 0.58, 0.24], gap="small")
with header_left:
    if st.button("← Glass Library", key="compare_back", width="content"):
        if not switch_to_page(LIBRARY_PAGE):
            st.warning("Could not return to the library.")
with header_mid:
    st.title("Glass Compare")
with header_right:
    if st.button(
        "Clear compare set",
        key="compare_clear",
        width="content",
        disabled=not compare_ids,
    ):
        st.session_state["compare_glass_ids"] = []
        if not switch_to_page(LIBRARY_PAGE):
            st.rerun()

if not compare_ids:
    st.info("Select 2-4 samples in the Glass Library, then open the compare page.")
    st.stop()

selected = catalog[catalog["glass_id"].isin(compare_ids)].copy()
selected["_order"] = selected["glass_id"].apply(
    lambda glass_id: compare_ids.index(str(glass_id)) if str(glass_id) in compare_ids else 999
)
selected = selected.sort_values(["_order", "glass_id"]).drop(columns=["_order"])

available_ids = selected["glass_id"].astype(str).tolist()
if available_ids != compare_ids:
    compare_ids = normalize_compare_ids(available_ids)
    st.session_state["compare_glass_ids"] = compare_ids

if len(compare_ids) < 2:
    st.info("Select at least two valid samples in the Glass Library to compare.")
    st.stop()

reference = selected.iloc[0].copy()
reference_id = str(reference["glass_id"])
reference_r = measurement_row(measurements, reference_id, "R")
reference_t = measurement_row(measurements, reference_id, "T")

st.caption(f"{len(compare_ids)} samples selected.")
render_differences(selected, measurements)

sample_columns = st.columns(len(compare_ids), gap="large")
for column, row in zip(sample_columns, selected.itertuples(index=False)):
    glass_id = str(row.glass_id)
    family_name = str(row.family_name or row.glass_family or "")
    prefix = family_prefix(str(row.glass_family or ""), family_name)
    row_r = measurement_row(measurements, glass_id, "R")
    row_t = measurement_row(measurements, glass_id, "T")
    row_series = pd.Series(row._asdict())
    is_reference_sample = glass_id == reference_id
    summary_lines = [] if is_reference_sample else comparison_interpretation_lines(
        reference,
        row_series,
        reference_r,
        row_r,
        reference_t,
        row_t,
    )
    chip_markup = chip_row_markup(
        comparison_delta_chips(
            reference,
            row_series,
            reference_r,
            row_r,
            reference_t,
            row_t,
            is_reference=is_reference_sample,
        ),
        max_chips=4,
    )

    with column:
        with st.container(border=True):
            title = str(row.color_name or "").strip()
            st.markdown(compare_title_markup(glass_id, title), unsafe_allow_html=True)
            st.caption(f"Family: {family_name}")
            st.markdown(
                striker_badge_markup(safe_int(getattr(row, "is_striker", 0), 0) == 1),
                unsafe_allow_html=True,
            )
            st.markdown(chip_markup, unsafe_allow_html=True)
            if is_reference_sample:
                st.markdown(
                    '<div class="compare-summary">Anchor sample for the difference summaries below.</div>',
                    unsafe_allow_html=True,
                )
            elif summary_lines:
                st.markdown(
                    f'<div class="compare-summary">{html.escape(summary_lines[0])}</div>',
                    unsafe_allow_html=True,
                )

            action_left, action_right = st.columns(2, gap="small")
            with action_left:
                if st.button(
                    "Open full datasheet",
                    key=f"compare_open_{glass_id}",
                    width="content",
                    disabled=current_detail_target() is None,
                ):
                    st.session_state["detail_glass_id"] = glass_id
                    st.session_state["detail_return_page"] = "pages/15_Glass_Compare.py"
                    st.session_state["detail_return_label"] = "Glass Compare"
                    if not switch_to_page(DETAIL_PAGE):
                        st.warning("Could not navigate to the full datasheet page.")
            with action_right:
                if st.button(
                    "Remove",
                    key=f"compare_remove_{glass_id}",
                    width="content",
                ):
                    st.session_state["compare_glass_ids"] = [
                        item for item in compare_ids if item != glass_id
                    ]
                    st.rerun()

            render_optical_detail(glass_id, prefix, row_r, row_t)
