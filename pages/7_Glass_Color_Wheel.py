from __future__ import annotations

import colorsys
import html
import math
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from i18n import join_list, render_app_sidebar, t, translate_element_name, translate_family_name, translate_mode_name

APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "glass_library.sqlite"
IMG_ROOT = APP_ROOT / "images"
MISSING_ICON = IMG_ROOT / "_placeholders" / "missing_icon.jpg"
DETAIL_PAGE = "pages/8_Glass_Detail.py"

FAMILY_PREFIX_BY_CODE = {
    "1": "opal",
    "2": "transparent",
    "3": "tint",
}

FAMILY_SYMBOLS = {
    "Opalescent": "circle",
    "Transparent": "diamond",
    "Tint": "square",
}

HARMONY_SCHEMES = {
    "None": [],
    "Complementary": [
        {"short": "C", "label": "Complementary", "offset": 180.0},
    ],
    "Analogous": [
        {"short": "A-", "label": "Analogous -30", "offset": -30.0},
        {"short": "A+", "label": "Analogous +30", "offset": 30.0},
    ],
    "Split Complementary": [
        {"short": "SC-", "label": "Split -150", "offset": -150.0},
        {"short": "SC+", "label": "Split +150", "offset": 150.0},
    ],
    "Triadic": [
        {"short": "T1", "label": "Triadic +120", "offset": 120.0},
        {"short": "T2", "label": "Triadic -120", "offset": -120.0},
    ],
    "Square": [
        {"short": "S1", "label": "Square +90", "offset": 90.0},
        {"short": "S2", "label": "Square +180", "offset": 180.0},
        {"short": "S3", "label": "Square +270", "offset": 270.0},
    ],
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

st.set_page_config(page_title=t("color_wheel.title", "Glass Color Wheel"), layout="wide")
render_app_sidebar()


def mode_label(mode: str) -> str:
    return translate_mode_name(mode)


def harmony_scheme_label(value: str) -> str:
    labels = {
        "None": t("color_wheel.harmony.none", "None"),
        "Complementary": t("color_wheel.harmony.complementary", "Complementary"),
        "Analogous": t("color_wheel.harmony.analogous", "Analogous"),
        "Split Complementary": t("color_wheel.harmony.split_complementary", "Split Complementary"),
        "Triadic": t("color_wheel.harmony.triadic", "Triadic"),
        "Square": t("color_wheel.harmony.square", "Square"),
    }
    return labels.get(value, value)


def view_mode_label(value: str) -> str:
    labels = {
        "2d": t("color_wheel.view.2d", "2D Wheel"),
        "3d": t("color_wheel.view.3d", "3D Wheel"),
    }
    return labels.get(value, value)


def harmony_target_label(value: str) -> str:
    labels = {
        "Complementary": t("color_wheel.target.complementary", "Complementary"),
        "Analogous -30": t("color_wheel.target.analogous_minus", "Analogous -30"),
        "Analogous +30": t("color_wheel.target.analogous_plus", "Analogous +30"),
        "Split -150": t("color_wheel.target.split_minus", "Split -150"),
        "Split +150": t("color_wheel.target.split_plus", "Split +150"),
        "Triadic +120": t("color_wheel.target.triadic_plus", "Triadic +120"),
        "Triadic -120": t("color_wheel.target.triadic_minus", "Triadic -120"),
        "Square +90": t("color_wheel.target.square_90", "Square +90"),
        "Square +180": t("color_wheel.target.square_180", "Square +180"),
        "Square +270": t("color_wheel.target.square_270", "Square +270"),
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


def icon_path(cat_id: str, prefix: str, mode: str) -> Path:
    return IMG_ROOT / "icons" / f"{prefix}_{mode}_{cat_id}.jpg"


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


def event_mapping(value) -> dict:
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return value.__dict__
    try:
        return dict(value)
    except Exception:
        return {}


@st.cache_data
def load_wheel_data() -> pd.DataFrame:
    if not DB_PATH.exists():
        st.error(t("errors.editor.db_missing", "Missing database: {path}", path=DB_PATH))
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
                    m.mode,
                    m.R AS r,
                    m.G AS g,
                    m.B AS b,
                    m.H AS h,
                    m.S AS s,
                    m.V AS v,
                    m.thickness_mm
                FROM glass_catalog c
                JOIN glass_measurements m
                    ON m.cat_id = c.cat_id
                LEFT JOIN glass_families f
                    ON f.code = c.glass_family
                WHERE m.mode IN ('R', 'T')
                ORDER BY c.cat_id, m.mode;
                """,
                con,
            )
        except Exception as exc:
            st.error(t("color_wheel.errors.load", "Failed to load color-wheel data: {error}", error=exc))
            st.stop()


def measurement_row(data: pd.DataFrame, glass_id: str, mode: str) -> pd.Series | None:
    matches = data[
        (data["glass_id"].astype(str) == str(glass_id))
        & (data["mode"].astype(str).str.upper() == mode)
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
        display_label = translate_element_name(label)
        text = f"R {display_label}" if muted else display_label
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


def rgb_string(row: pd.Series) -> str:
    rgb_values = [safe_int(row.get(channel), 180) for channel in ("r", "g", "b")]
    return f"rgb({rgb_values[0]}, {rgb_values[1]}, {rgb_values[2]})"


def wheel_xy(hue: float, value: float) -> tuple[float, float]:
    angle = math.radians(float(hue))
    radius = float(value)
    x = radius * math.sin(angle)
    y = radius * math.cos(angle)
    return x, y


def normalize_hue(hue: float) -> float:
    return float(hue) % 360.0


def hue_distance(a: float, b: float) -> float:
    diff = abs(normalize_hue(a) - normalize_hue(b))
    return min(diff, 360.0 - diff)


def harmony_colour(hue: float) -> str:
    red, green, blue = colorsys.hsv_to_rgb(normalize_hue(hue) / 360.0, 0.72, 0.92)
    return f"rgb({int(red * 255)}, {int(green * 255)}, {int(blue * 255)})"


def harmony_targets(base_hue: float, scheme_name: str) -> list[dict]:
    targets = []
    for spec in HARMONY_SCHEMES.get(scheme_name, []):
        target_hue = normalize_hue(base_hue + float(spec["offset"]))
        targets.append(
            {
                "short": str(spec["short"]),
                "label": harmony_target_label(str(spec["label"])),
                "target_hue": target_hue,
                "colour": harmony_colour(target_hue),
            }
        )
    return targets


def harmony_matches(
    visible: pd.DataFrame,
    selected_glass_id: str,
    scheme_name: str,
) -> list[dict]:
    selected_rows = visible[visible["glass_id"].astype(str) == str(selected_glass_id)]
    if selected_rows.empty or scheme_name == "None":
        return []

    selected = selected_rows.iloc[0]
    targets = harmony_targets(float(selected["h"]), scheme_name)
    candidates = visible[visible["glass_id"].astype(str) != str(selected_glass_id)].copy()
    if candidates.empty:
        return targets

    current_s = safe_int(selected.get("s"))
    current_v = safe_int(selected.get("v"))
    used_ids: set[str] = set()
    matches = []

    for target in targets:
        available = candidates[
            ~candidates["glass_id"].astype(str).isin(used_ids)
        ].copy()
        if available.empty:
            available = candidates.copy()

        available["hue_delta"] = available["h"].apply(
            lambda value: hue_distance(float(value), float(target["target_hue"]))
        )
        available["sv_delta"] = (
            (available["s"].fillna(current_s) - current_s).abs()
            + (available["v"].fillna(current_v) - current_v).abs()
        )
        available = available.sort_values(
            ["hue_delta", "sv_delta", "glass_id"],
            na_position="last",
        )
        if available.empty:
            matches.append(target)
            continue

        match = available.iloc[0]
        match_info = dict(target)
        match_info.update(
            {
                "glass_id": str(match["glass_id"]),
                "color_name": str(match.get("color_name") or ""),
                "family_name": translate_family_name(str(match.get("glass_family") or ""), str(match.get("family_name") or "")),
                "h": safe_int(match.get("h")),
                "s": safe_int(match.get("s")),
                "v": safe_int(match.get("v")),
                "r": safe_int(match.get("r")),
                "g": safe_int(match.get("g")),
                "b": safe_int(match.get("b")),
                "match_rgb": rgb_string(match),
                "hue_delta": float(match["hue_delta"]),
            }
        )
        matches.append(match_info)
        used_ids.add(str(match["glass_id"]))

    return matches


def selected_glass_id_from_chart_state() -> str | None:
    state = st.session_state.get("glass_color_wheel_chart")
    selection = getattr(state, "selection", None) or event_mapping(state).get("selection")
    if not selection:
        return None

    points = getattr(selection, "points", None) or event_mapping(selection).get("points") or []
    for point in points:
        point_data = event_mapping(point)
        if point_data.get("id"):
            return str(point_data["id"])
        customdata = point_data.get("customdata")
        if isinstance(customdata, (list, tuple)) and customdata:
            return str(customdata[0])
        if isinstance(customdata, str):
            return customdata
    return None


def build_wheel_figure(
    visible: pd.DataFrame,
    selected_glass_id: str,
    mode_label: str,
    harmony_overlay: list[dict] | None = None,
) -> go.Figure:
    fig = go.Figure()
    plotted = visible.copy()
    coords = plotted.apply(
        lambda row: wheel_xy(row["h"], row["v"]),
        axis=1,
        result_type="expand",
    )
    plotted[["x", "y"]] = coords

    family_order = [name for name in FAMILY_SYMBOLS if name in plotted["family_name"].tolist()]
    family_order.extend(
        name
        for name in plotted["family_name"].dropna().unique().tolist()
        if name not in family_order
    )

    for radius in (25, 50, 75, 100):
        fig.add_shape(
            type="circle",
            xref="x",
            yref="y",
            x0=-radius,
            y0=-radius,
            x1=radius,
            y1=radius,
            line=dict(color="rgba(0, 0, 0, 0.12)", width=1),
            fillcolor="rgba(0, 0, 0, 0)",
            layer="below",
        )

    for hue in (0, 60, 120, 180, 240, 300):
        spoke_x, spoke_y = wheel_xy(hue, 100)
        fig.add_shape(
            type="line",
            xref="x",
            yref="y",
            x0=0,
            y0=0,
            x1=spoke_x,
            y1=spoke_y,
            line=dict(color="rgba(0, 0, 0, 0.08)", width=1),
            layer="below",
        )

    axis_labels = [
        (t("color_wheel.axis.red", "Red"), 0),
        (t("color_wheel.axis.yellow", "Yellow"), 60),
        (t("color_wheel.axis.green", "Green"), 120),
        (t("color_wheel.axis.cyan", "Cyan"), 180),
        (t("color_wheel.axis.blue", "Blue"), 240),
        (t("color_wheel.axis.magenta", "Magenta"), 300),
    ]
    for label, hue in axis_labels:
        label_x, label_y = wheel_xy(hue, 110)
        fig.add_annotation(
            x=label_x,
            y=label_y,
            text=label,
            showarrow=False,
            font=dict(size=12, color="#6f7890"),
            xanchor="center",
            yanchor="middle",
        )

    for radius in (0, 25, 50, 75, 100):
        fig.add_annotation(
            x=radius if radius > 0 else 0,
            y=0,
            text=str(radius),
            showarrow=False,
            font=dict(size=10, color="#7a7a7a"),
            xanchor="left" if radius > 0 else "center",
            yanchor="bottom",
            yshift=4,
        )

    if harmony_overlay:
        for item in harmony_overlay:
            target_x, target_y = wheel_xy(item["target_hue"], 100)
            label_x, label_y = wheel_xy(item["target_hue"], 108)
            fig.add_shape(
                type="line",
                xref="x",
                yref="y",
                x0=0,
                y0=0,
                x1=target_x,
                y1=target_y,
                line=dict(color=item["colour"], width=2, dash="dot"),
                layer="below",
            )
            fig.add_annotation(
                x=label_x,
                y=label_y,
                text=item["short"],
                showarrow=False,
                font=dict(size=10, color="#444"),
                bgcolor="rgba(255,255,255,0.82)",
                bordercolor=item["colour"],
                borderwidth=1,
                borderpad=2,
                xanchor="center",
                yanchor="middle",
            )

        fig.add_trace(
            go.Scatter(
                x=[wheel_xy(item["target_hue"], 100)[0] for item in harmony_overlay],
                y=[wheel_xy(item["target_hue"], 100)[1] for item in harmony_overlay],
                mode="markers",
                name=t("color_wheel.figure.harmony_targets", "Harmony targets"),
                marker=dict(
                    size=10,
                    color=[item["colour"] for item in harmony_overlay],
                    symbol="x",
                    line=dict(color="#222", width=1),
                ),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    f"{t('color_wheel.figure.target_hue', 'Target hue')}: "
                    "%{customdata[1]} deg"
                    "<extra></extra>"
                ),
                customdata=[
                    [item["label"], safe_int(item["target_hue"])] for item in harmony_overlay
                ],
            )
        )

    for family_name in family_order:
        family_rows = plotted[plotted["family_name"] == family_name].copy()
        if family_rows.empty:
            continue
        family_rows["family_name_display"] = [
            translate_family_name(str(row.get("glass_family") or ""), str(row.get("family_name") or ""))
            for _, row in family_rows.iterrows()
        ]

        customdata = family_rows[
            ["glass_id", "color_name", "family_name_display", "h", "s", "v", "r", "g", "b"]
        ].fillna("").values

        fig.add_trace(
            go.Scatter(
                x=family_rows["x"].tolist(),
                y=family_rows["y"].tolist(),
                mode="markers",
                name=str(family_name),
                ids=family_rows["glass_id"].astype(str).tolist(),
                customdata=customdata,
                marker=dict(
                    size=16,
                    color=[rgb_string(row) for _, row in family_rows.iterrows()],
                    symbol=FAMILY_SYMBOLS.get(str(family_name), "circle"),
                    line=dict(color="rgba(32, 32, 32, 0.55)", width=1),
                    opacity=0.96,
                ),
                hovertemplate=(
                    "<b>%{customdata[0]}</b> %{customdata[1]}<br>"
                    f"{t('color_wheel.figure.family', 'Family')}: "
                    "%{customdata[2]}<br>"
                    "HSB: (%{customdata[3]}, %{customdata[4]}, %{customdata[5]})<br>"
                    "RGB: (%{customdata[6]}, %{customdata[7]}, %{customdata[8]})"
                    "<extra></extra>"
                ),
            )
        )

    selected_rows = plotted[plotted["glass_id"].astype(str) == str(selected_glass_id)]
    if not selected_rows.empty:
        selected = selected_rows.iloc[0]
        fig.add_trace(
            go.Scatter(
                x=[selected["x"]],
                y=[selected["y"]],
                mode="markers+text",
                showlegend=False,
                text=[str(selected["glass_id"])],
                textposition="top center",
                textfont=dict(size=12, color="#111111"),
                marker=dict(
                    size=27,
                    color=[rgb_string(selected)],
                    line=dict(color="#111111", width=3),
                    symbol="circle",
                ),
                hovertemplate="<extra></extra>",
            )
        )

    matched_points = [
        item for item in (harmony_overlay or []) if item.get("glass_id") and item.get("match_rgb")
    ]
    if matched_points:
        fig.add_trace(
            go.Scatter(
                x=[
                    wheel_xy(item["h"], item["v"])[0]
                    for item in matched_points
                ],
                y=[
                    wheel_xy(item["h"], item["v"])[1]
                    for item in matched_points
                ],
                mode="markers+text",
                name=t("color_wheel.figure.harmony_matches", "Harmony matches"),
                ids=[item["glass_id"] for item in matched_points],
                text=[item["short"] for item in matched_points],
                textposition="middle center",
                textfont=dict(size=10, color="#111111"),
                customdata=[
                    [
                        item["glass_id"],
                        item["color_name"],
                        item["family_name"],
                        item["h"],
                        item["s"],
                        item["v"],
                        item["r"],
                        item["g"],
                        item["b"],
                        item["label"],
                    ]
                    for item in matched_points
                ],
                marker=dict(
                    size=30,
                    color=[item["match_rgb"] for item in matched_points],
                    symbol="circle-open",
                    line=dict(color="#111111", width=3),
                ),
                hovertemplate=(
                    "<b>%{customdata[0]}</b> %{customdata[1]}<br>"
                    f"{t('color_wheel.figure.family', 'Family')}: "
                    "%{customdata[2]}<br>"
                    "HSB: (%{customdata[3]}, %{customdata[4]}, %{customdata[5]})<br>"
                    "RGB: (%{customdata[6]}, %{customdata[7]}, %{customdata[8]})<br>"
                    f"{t('color_wheel.figure.harmony', 'Harmony')}: "
                    "%{customdata[9]}"
                    "<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        title=dict(text=f"{translate_mode_name(mode_label)} {t('color_wheel.title', 'Glass Color Wheel')}", x=0.5),
        template="plotly_white",
        width=780,
        height=780,
        clickmode="event+select",
        margin=dict(l=40, r=40, t=72, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.03, x=0.0),
        paper_bgcolor="white",
        plot_bgcolor="#fbfbfb",
        xaxis=dict(
            visible=False,
            range=[-118, 118],
            showgrid=False,
            zeroline=False,
            constrain="domain",
        ),
        yaxis=dict(
            visible=False,
            range=[-118, 118],
            showgrid=False,
            zeroline=False,
            scaleanchor="x",
            scaleratio=1,
        ),
    )

    return fig


def build_wheel_3d_figure(
    visible: pd.DataFrame,
    selected_glass_id: str,
    mode_label: str,
    harmony_overlay: list[dict] | None = None,
) -> go.Figure:
    fig = go.Figure()
    plotted = visible.copy()
    coords = plotted.apply(
        lambda row: wheel_xy(row["h"], row["s"]),
        axis=1,
        result_type="expand",
    )
    plotted[["x", "y"]] = coords
    plotted["z"] = plotted["v"].astype(float)

    family_order = [name for name in FAMILY_SYMBOLS if name in plotted["family_name"].tolist()]
    family_order.extend(
        name
        for name in plotted["family_name"].dropna().unique().tolist()
        if name not in family_order
    )

    theta_values = [math.radians(angle) for angle in range(0, 361, 4)]
    for radius in (25, 50, 75, 100):
        fig.add_trace(
            go.Scatter3d(
                x=[radius * math.sin(theta) for theta in theta_values],
                y=[radius * math.cos(theta) for theta in theta_values],
                z=[0.0] * len(theta_values),
                mode="lines",
                showlegend=False,
                hoverinfo="skip",
                line=dict(color="rgba(0, 0, 0, 0.14)", width=2),
            )
        )

    for hue in (0, 60, 120, 180, 240, 300):
        spoke_x, spoke_y = wheel_xy(hue, 100)
        fig.add_trace(
            go.Scatter3d(
                x=[0.0, spoke_x],
                y=[0.0, spoke_y],
                z=[0.0, 0.0],
                mode="lines",
                showlegend=False,
                hoverinfo="skip",
                line=dict(color="rgba(0, 0, 0, 0.1)", width=2),
            )
        )

    axis_labels = [
        (t("color_wheel.axis.red", "Red"), 0),
        (t("color_wheel.axis.yellow", "Yellow"), 60),
        (t("color_wheel.axis.green", "Green"), 120),
        (t("color_wheel.axis.cyan", "Cyan"), 180),
        (t("color_wheel.axis.blue", "Blue"), 240),
        (t("color_wheel.axis.magenta", "Magenta"), 300),
    ]
    for label, hue in axis_labels:
        label_x, label_y = wheel_xy(hue, 108)
        fig.add_trace(
            go.Scatter3d(
                x=[label_x],
                y=[label_y],
                z=[0.0],
                mode="text",
                text=[label],
                textfont=dict(size=11, color="#6f7890"),
                showlegend=False,
                hoverinfo="skip",
            )
        )

    if harmony_overlay:
        for item in harmony_overlay:
            target_x, target_y = wheel_xy(item["target_hue"], 100)
            fig.add_trace(
                go.Scatter3d(
                    x=[0.0, target_x],
                    y=[0.0, target_y],
                    z=[0.0, 0.0],
                    mode="lines",
                    showlegend=False,
                    hoverinfo="skip",
                    line=dict(color=item["colour"], width=3, dash="dot"),
                )
            )

        fig.add_trace(
            go.Scatter3d(
                x=[wheel_xy(item["target_hue"], 100)[0] for item in harmony_overlay],
                y=[wheel_xy(item["target_hue"], 100)[1] for item in harmony_overlay],
                z=[0.0 for _ in harmony_overlay],
                mode="markers+text",
                name=t("color_wheel.figure.harmony_targets", "Harmony targets"),
                text=[item["short"] for item in harmony_overlay],
                textposition="top center",
                textfont=dict(size=10, color="#444"),
                marker=dict(
                    size=5,
                    color=[item["colour"] for item in harmony_overlay],
                    symbol="diamond",
                    line=dict(color="#222", width=1),
                ),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    f"{t('color_wheel.figure.target_hue', 'Target hue')}: "
                    "%{customdata[1]} deg"
                    "<extra></extra>"
                ),
                customdata=[
                    [item["label"], safe_int(item["target_hue"])] for item in harmony_overlay
                ],
            )
        )

    for family_name in family_order:
        family_rows = plotted[plotted["family_name"] == family_name].copy()
        if family_rows.empty:
            continue
        family_rows["family_name_display"] = [
            translate_family_name(str(row.get("glass_family") or ""), str(row.get("family_name") or ""))
            for _, row in family_rows.iterrows()
        ]

        customdata = family_rows[
            ["glass_id", "color_name", "family_name_display", "h", "s", "v", "r", "g", "b"]
        ].fillna("").values

        fig.add_trace(
            go.Scatter3d(
                x=family_rows["x"].tolist(),
                y=family_rows["y"].tolist(),
                z=family_rows["z"].tolist(),
                mode="markers",
                name=str(family_name),
                ids=family_rows["glass_id"].astype(str).tolist(),
                customdata=customdata,
                marker=dict(
                    size=7,
                    color=[rgb_string(row) for _, row in family_rows.iterrows()],
                    symbol=FAMILY_SYMBOLS.get(str(family_name), "circle"),
                    line=dict(color="rgba(32, 32, 32, 0.55)", width=1),
                    opacity=0.96,
                ),
                hovertemplate=(
                    "<b>%{customdata[0]}</b> %{customdata[1]}<br>"
                    f"{t('color_wheel.figure.family', 'Family')}: "
                    "%{customdata[2]}<br>"
                    "HSB: (%{customdata[3]}, %{customdata[4]}, %{customdata[5]})<br>"
                    "RGB: (%{customdata[6]}, %{customdata[7]}, %{customdata[8]})"
                    "<extra></extra>"
                ),
            )
        )

    selected_rows = plotted[plotted["glass_id"].astype(str) == str(selected_glass_id)]
    if not selected_rows.empty:
        selected = selected_rows.iloc[0]
        fig.add_trace(
            go.Scatter3d(
                x=[selected["x"]],
                y=[selected["y"]],
                z=[selected["z"]],
                mode="markers+text",
                showlegend=False,
                text=[str(selected["glass_id"])],
                textposition="top center",
                textfont=dict(size=12, color="#111111"),
                marker=dict(
                    size=12,
                    color=[rgb_string(selected)],
                    line=dict(color="#111111", width=3),
                    symbol="circle",
                ),
                hovertemplate="<extra></extra>",
            )
        )

    matched_points = [
        item for item in (harmony_overlay or []) if item.get("glass_id") and item.get("match_rgb")
    ]
    if matched_points:
        fig.add_trace(
            go.Scatter3d(
                x=[wheel_xy(item["h"], item["s"])[0] for item in matched_points],
                y=[wheel_xy(item["h"], item["s"])[1] for item in matched_points],
                z=[item["v"] for item in matched_points],
                mode="markers+text",
                name=t("color_wheel.figure.harmony_matches", "Harmony matches"),
                ids=[item["glass_id"] for item in matched_points],
                text=[item["short"] for item in matched_points],
                textposition="top center",
                textfont=dict(size=10, color="#111111"),
                customdata=[
                    [
                        item["glass_id"],
                        item["color_name"],
                        item["family_name"],
                        item["h"],
                        item["s"],
                        item["v"],
                        item["r"],
                        item["g"],
                        item["b"],
                        item["label"],
                    ]
                    for item in matched_points
                ],
                marker=dict(
                    size=10,
                    color=[item["match_rgb"] for item in matched_points],
                    symbol="circle-open",
                    line=dict(color="#111111", width=3),
                ),
                hovertemplate=(
                    "<b>%{customdata[0]}</b> %{customdata[1]}<br>"
                    f"{t('color_wheel.figure.family', 'Family')}: "
                    "%{customdata[2]}<br>"
                    "HSB: (%{customdata[3]}, %{customdata[4]}, %{customdata[5]})<br>"
                    "RGB: (%{customdata[6]}, %{customdata[7]}, %{customdata[8]})<br>"
                    f"{t('color_wheel.figure.harmony', 'Harmony')}: "
                    "%{customdata[9]}"
                    "<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        title=dict(text=f"{translate_mode_name(mode_label)} HSB {view_mode_label('3d')}", x=0.5),
        template="plotly_white",
        width=780,
        height=780,
        clickmode="event+select",
        margin=dict(l=10, r=10, t=72, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.03, x=0.0),
        paper_bgcolor="white",
        scene=dict(
            xaxis=dict(
                visible=False,
                range=[-118, 118],
                showbackground=False,
                showgrid=False,
                zeroline=False,
            ),
            yaxis=dict(
                visible=False,
                range=[-118, 118],
                showbackground=False,
                showgrid=False,
                zeroline=False,
            ),
            zaxis=dict(
                title=t("editor.fields.brightness", "Brightness (B)"),
                range=[0, 100],
                tickmode="array",
                tickvals=[0, 25, 50, 75, 100],
                gridcolor="rgba(0, 0, 0, 0.12)",
                zeroline=False,
                showbackground=False,
            ),
            aspectmode="manual",
            aspectratio=dict(x=1, y=1, z=0.72),
            camera=dict(eye=dict(x=1.55, y=1.55, z=0.95)),
            bgcolor="#fbfbfb",
        ),
    )

    return fig


def render_measurement_card(data: pd.DataFrame, glass_id: str, prefix: str, mode: str) -> None:
    row = measurement_row(data, glass_id, mode)
    st.markdown(f"### {mode_label(mode)}")

    preview = icon_path(glass_id, prefix, mode)
    if preview.exists():
        st.image(str(preview), width="content")
    elif MISSING_ICON.exists():
        st.image(str(MISSING_ICON), width="content")

    if row is None:
        st.write(t("library.messages.no_measurement_mode", "No measurement data for this mode."))
        return

    swatch = rgb_string(row)
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:10px;margin:4px 0 10px 0;">
          <div style="width:28px;height:28px;border-radius:4px;border:1px solid #aaa;background:{swatch};"></div>
          <div style="font-family:sans-serif;font-size:13px;color:#333;">{t('color_wheel.labels.measured_color', 'Measured color')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        "\n".join(
            [
                f"**RGB:** ({safe_int(row.get('r'))}, {safe_int(row.get('g'))}, {safe_int(row.get('b'))})  ",
                f"**HSB:** ({safe_int(row.get('h'))}, {safe_int(row.get('s'))}, {safe_int(row.get('v'))})  ",
                f"**{t('editor.fields.thickness', 'Thickness (mm)').replace(' (mm)', '')}:** {row.get('thickness_mm') or '-'} mm",
            ]
        )
    )


def glass_display_label(glass_id: str, color_name: str, family_name: str) -> str:
    parts = [str(glass_id).strip()]
    title = str(color_name or "").strip()
    family = str(family_name or "").strip()
    if title:
        parts.append(title)
    if family and family.lower() not in title.lower():
        parts.append(family)
    return " ".join(parts)


def harmony_overlay_rows(harmony_overlay: list[dict]) -> list[str]:
    rows = []
    for item in harmony_overlay:
        if item.get("glass_id"):
            label = glass_display_label(
                str(item.get("glass_id") or ""),
                str(item.get("color_name") or ""),
                str(item.get("family_name") or ""),
            )
            rows.append(
                (
                    f"<strong>{html.escape(item['label'])}</strong>: "
                    f"{t('color_wheel.figure.target_hue', 'Target hue').lower()} {safe_int(item['target_hue'])} deg -> "
                    f"{html.escape(label)} (ΔH {item['hue_delta']:.1f})"
                )
            )
        else:
            rows.append(
                f"<strong>{html.escape(item['label'])}</strong>: "
                f"{t('color_wheel.figure.target_hue', 'Target hue').lower()} {safe_int(item['target_hue'])} deg"
            )
    return rows


def render_harmony_match_card(data: pd.DataFrame, item: dict, current_mode: str) -> None:
    glass_id = str(item.get("glass_id") or "")
    if not glass_id:
        return

    rows = data[data["glass_id"].astype(str) == glass_id]
    if rows.empty:
        return

    base_row = rows.iloc[0]
    family_name = str(base_row.get("family_name") or base_row.get("glass_family") or "")
    prefix = family_prefix(str(base_row.get("glass_family") or ""), family_name)
    title = str(base_row.get("color_name") or item.get("color_name") or "").strip()
    display_title = glass_display_label(
        glass_id,
        title,
        translate_family_name(str(base_row.get("glass_family") or ""), family_name),
    )

    st.markdown(f"#### {display_title}")
    if current_detail_target():
        if st.button(
            t("library.detail.open_datasheet", "Open full datasheet"),
            key=f"open_harmony_match_{item.get('short', 'target')}_{glass_id}",
            width="content",
        ):
            st.session_state["detail_glass_id"] = glass_id
            st.session_state["detail_return_page"] = "pages/7_Glass_Color_Wheel.py"
            st.session_state["detail_return_label_key"] = "color_wheel.title"
            if not switch_to_page(DETAIL_PAGE):
                st.warning(t("color_wheel.messages.open_datasheet_failed", "Could not navigate to the full datasheet page."))

    image_cols = st.columns(2, gap="medium")
    for column, mode_value in zip(image_cols, ("R", "T")):
        with column:
            st.markdown(f"**{mode_label(mode_value)}**")
            preview = icon_path(glass_id, prefix, mode_value)
            if preview.exists():
                st.image(str(preview), width="content")
            elif MISSING_ICON.exists():
                st.image(str(MISSING_ICON), width="content")

            measurement = measurement_row(data, glass_id, mode_value)
            if measurement is not None:
                st.markdown(
                    "\n".join(
                        [
                            f"**RGB:** ({safe_int(measurement.get('r'))}, {safe_int(measurement.get('g'))}, {safe_int(measurement.get('b'))})  ",
                            f"**HSB:** ({safe_int(measurement.get('h'))}, {safe_int(measurement.get('s'))}, {safe_int(measurement.get('v'))})  ",
                            f"**{t('editor.fields.thickness', 'Thickness (mm)').replace(' (mm)', '')}:** {measurement.get('thickness_mm') or '-'} mm",
                        ]
                    )
                )


def render_harmony_overlay_block(
    data: pd.DataFrame,
    current_mode: str,
    harmony_scheme: str,
    harmony_overlay: list[dict],
) -> None:
    if harmony_scheme == "None":
        return

    st.markdown(f"## {t('color_wheel.labels.harmony_overlay', 'Harmony Overlay')}")
    if not harmony_overlay:
        st.info(t("color_wheel.messages.no_harmony", "No harmony targets are available for the current selection."))
        return

    rows = harmony_overlay_rows(harmony_overlay)
    st.markdown(
        (
            '<div style="font-family:sans-serif;font-size:13px;line-height:1.7;'
            'margin:6px 0 20px 0;padding:10px 12px;border:1px solid #ddd;'
            'border-radius:8px;background:#fafafa;">'
            + "<br>".join(rows)
            + "</div>"
        ),
        unsafe_allow_html=True,
    )

    matched_items = [item for item in harmony_overlay if item.get("glass_id")]
    if not matched_items:
        return

    match_columns = st.columns(min(len(matched_items), 2), gap="large")
    for index, item in enumerate(matched_items):
        with match_columns[index % len(match_columns)]:
            render_harmony_match_card(data, item, current_mode)


def render_selected_sample(
    data: pd.DataFrame,
    selected_glass_id: str,
    current_mode: str,
    view_mode: str,
) -> None:
    current = data[data["glass_id"].astype(str) == str(selected_glass_id)]
    if current.empty:
        st.info(t("color_wheel.messages.select_point", "Select a visible point to inspect a sample."))
        return

    base_row = current.iloc[0]
    family_name = str(base_row.get("family_name") or base_row.get("glass_family") or "")
    prefix = family_prefix(str(base_row.get("glass_family") or ""), family_name)
    current_row = measurement_row(data, selected_glass_id, current_mode)

    title = str(base_row.get("color_name") or "").strip()
    st.subheader(f"{selected_glass_id}  {title}" if title else str(selected_glass_id))
    st.caption(t("color_wheel.labels.family", "Family: {family}", family=translate_family_name(str(base_row.get("glass_family") or ""), family_name)))

    st.markdown(
        striker_badge_markup(safe_int(base_row.get("is_striker"), 0) == 1),
        unsafe_allow_html=True,
    )

    position_col, chemistry_col, reflected_col, transmitted_col = st.columns(
        [0.23, 0.22, 0.25, 0.25],
        gap="large",
    )

    with position_col:
        if current_row is not None:
            if view_mode == "3d":
                position_lines = [
                    t("color_wheel.position.mode", "Mode: {mode}", mode=html.escape(mode_label(current_mode))),
                    t("color_wheel.position.hue", "H: {value} deg", value=safe_int(current_row.get("h"))),
                    t("color_wheel.position.radius_s", "Radius (S): {value}", value=safe_int(current_row.get("s"))),
                    t("color_wheel.position.z_b", "Z (B): {value}", value=safe_int(current_row.get("v"))),
                    t("color_wheel.position.brightness_b", "B: {value}", value=safe_int(current_row.get("v"))),
                ]
            else:
                position_lines = [
                    t("color_wheel.position.mode", "Mode: {mode}", mode=html.escape(mode_label(current_mode))),
                    t("color_wheel.position.hue", "H: {value} deg", value=safe_int(current_row.get("h"))),
                    t("color_wheel.position.radius_b", "Radius (B): {value}", value=safe_int(current_row.get("v"))),
                    t("color_wheel.position.saturation_s", "S: {value}", value=safe_int(current_row.get("s"))),
                    t("color_wheel.position.brightness_b", "B: {value}", value=safe_int(current_row.get("v"))),
                ]
            st.markdown(
                f"""
                <div style="font-family:sans-serif;font-size:14px;margin:8px 0 12px 0;
                            padding:10px 12px;border:1px solid #ddd;border-radius:8px;background:#fafafa;">
                  <strong>{t('color_wheel.labels.wheel_position', 'Wheel position')}</strong><br>
                  {'<br>'.join(position_lines)}
                </div>
                """,
                unsafe_allow_html=True,
            )

        if current_detail_target():
            if st.button(
                t("library.detail.open_datasheet", "Open full datasheet"),
                key=f"open_datasheet_wheel_{selected_glass_id}",
                width="content",
            ):
                st.session_state["detail_glass_id"] = str(selected_glass_id)
                st.session_state["detail_return_page"] = "pages/7_Glass_Color_Wheel.py"
                st.session_state["detail_return_label_key"] = "color_wheel.title"
                if not switch_to_page(DETAIL_PAGE):
                    st.warning(t("color_wheel.messages.open_datasheet_failed", "Could not navigate to the full datasheet page."))

    with chemistry_col:
        st.markdown(f"### {t('shared.sections.elements_present', 'Elements Present')}")
        st.markdown(badge_markup(element_labels(base_row)), unsafe_allow_html=True)

        st.markdown(f"### {t('shared.sections.reactive_potential', 'Reactive Potential')}")
        st.markdown(badge_markup(reactive_labels(base_row), muted=True), unsafe_allow_html=True)

    with reflected_col:
        render_measurement_card(data, selected_glass_id, prefix, "R")

    with transmitted_col:
        render_measurement_card(data, selected_glass_id, prefix, "T")


wheel_data = load_wheel_data().copy()
wheel_data["glass_id"] = wheel_data["glass_id"].astype(str)
wheel_data["glass_family"] = wheel_data["glass_family"].astype(str)
wheel_data["family_name"] = wheel_data["family_name"].astype(str)
wheel_data["mode"] = wheel_data["mode"].astype(str).str.upper()

for column in ["r", "g", "b", "h", "s", "v", "thickness_mm"]:
    wheel_data[column] = pd.to_numeric(wheel_data[column], errors="coerce")

st.sidebar.header(t("color_wheel.sidebar.title", "Color Wheel"))

family_options = ["All"]
family_options.extend(
    family for family in ["Opalescent", "Transparent", "Tint"]
    if family in wheel_data["family_name"].dropna().unique().tolist()
)
family_options.extend(
    family
    for family in wheel_data["family_name"].dropna().unique().tolist()
    if family not in family_options
)

selected_family = st.sidebar.selectbox(
    t("editor.fields.glass_family", "Glass family"),
    family_options,
    index=0,
    format_func=lambda value: translate_family_name(None, value),
)
view_mode = st.sidebar.radio(
    t("color_wheel.fields.view", "View"),
    ["2d", "3d"],
    index=0,
    format_func=view_mode_label,
)
mode = st.sidebar.radio(
    t("color_wheel.fields.mode", "Mode"),
    ["R", "T"],
    index=0,
    format_func=mode_label,
)
harmony_scheme = st.sidebar.selectbox(
    t("color_wheel.fields.harmony", "Harmony Overlay"),
    list(HARMONY_SCHEMES.keys()),
    index=0,
    format_func=harmony_scheme_label,
)
query = st.sidebar.text_input(t("color_wheel.fields.search", "Search (id or color)"), "")
only_strikers = st.sidebar.checkbox(t("color_wheel.fields.striking_only", "Striking only"), value=False)

visible = wheel_data[wheel_data["mode"] == mode].copy()
if selected_family != "All":
    visible = visible[visible["family_name"] == selected_family]

if query.strip():
    text = query.strip().lower()
    visible = visible[
        visible["glass_id"].str.lower().str.contains(text)
        | visible["color_name"].fillna("").astype(str).str.lower().str.contains(text)
    ]

if only_strikers:
    visible = visible[visible["is_striker"].fillna(0).astype(int) == 1]

visible = visible.dropna(subset=["h", "s", "v"]).copy()
visible = visible.sort_values(["h", "v", "s", "glass_id"], na_position="last")

st.title(t("color_wheel.title", "Glass Color Wheel"))
if view_mode == "3d":
    caption = t(
        "color_wheel.caption.summary_3d",
        "{count} samples on wheel | angle = H | radius = S | z = B | mode: {mode}",
        count=len(visible),
        mode=translate_mode_name(mode).lower(),
    )
else:
    caption = t(
        "color_wheel.caption.summary_2d",
        "{count} samples on wheel | angle = H | radius = B | mode: {mode}",
        count=len(visible),
        mode=translate_mode_name(mode).lower(),
    )

if harmony_scheme != "None":
    caption += t(
        "color_wheel.caption.harmony",
        " | harmony: {harmony}",
        harmony=harmony_scheme_label(harmony_scheme).lower(),
    )

st.caption(caption)
st.caption(
    t(
        "library.notes.datum",
        "Library colors are anchored to the measured 2 mm sample datum under broad daylight-balanced illumination. Thickness changes, lighting changes, and batch variation can shift the visible read away from this reference.",
    )
)

if visible.empty:
    st.info(t("color_wheel.messages.empty", "No glass samples match the current filters."))
    st.stop()

selected_from_chart = selected_glass_id_from_chart_state()
if selected_from_chart:
    st.session_state["color_wheel_selected_glass_id"] = selected_from_chart

selected_glass_id = st.session_state.get("color_wheel_selected_glass_id")
valid_ids = visible["glass_id"].astype(str).tolist()
if selected_glass_id not in valid_ids:
    selected_glass_id = valid_ids[0]
    st.session_state["color_wheel_selected_glass_id"] = selected_glass_id

harmony_overlay = harmony_matches(visible, str(selected_glass_id), harmony_scheme)

if view_mode == "3d":
    st.caption(t("color_wheel.caption.click_3d", "Click a point to inspect a sample. Drag to orbit the 3D view."))
    figure = build_wheel_3d_figure(
        visible,
        str(selected_glass_id),
        mode,
        harmony_overlay,
    )
else:
    st.caption(t("color_wheel.caption.click_2d", "Click a point to inspect a sample."))
    figure = build_wheel_figure(
        visible,
        str(selected_glass_id),
        mode,
        harmony_overlay,
    )

st.plotly_chart(
    figure,
    key="glass_color_wheel_chart",
    on_select="rerun",
    selection_mode="points",
    width="content",
    config={
        "displaylogo": False,
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    },
)
render_harmony_overlay_block(
    wheel_data,
    mode,
    harmony_scheme,
    harmony_overlay,
)

st.divider()
render_selected_sample(
    wheel_data,
    str(selected_glass_id),
    mode,
    view_mode,
)
