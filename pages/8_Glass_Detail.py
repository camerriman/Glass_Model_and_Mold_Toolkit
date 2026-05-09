# 8_Glass_Detail.py
# Full datasheet view for a single glass sample.
# Launched from the Glass Library grid (click icon → sets session state → switch_page here).
from __future__ import annotations

import html
import math
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from i18n import render_app_sidebar, t, translate_element_name, translate_family_name

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
APP_ROOT  = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.append(str(APP_ROOT))

from utilities.glass_detail_pdf import build_glass_detail_pdf

DB_PATH   = APP_ROOT / "data" / "glass_library.sqlite"
IMG_ROOT  = APP_ROOT / "images"
ICONS_DIR = IMG_ROOT / "icons"
FULL_DIR  = IMG_ROOT / "full"
MISSING_FULL = IMG_ROOT / "_placeholders" / "missing_full.tiff"
MISSING_ICON = IMG_ROOT / "_placeholders" / "missing_icon.jpg"

FAMILY_CODE_TO_PREFIX = {"1": "opal", "2": "transparent", "3": "tint"}
FAMILY_CODE_TO_NAME = {"1": "Opalescent", "2": "Transparent", "3": "Tint"}

VIEW_MAP = {
    "opal_transmitted":        ("opal",        "T"),
    "opal_reflected":          ("opal",        "R"),
    "transparent_transmitted": ("transparent", "T"),
    "transparent_reflected":   ("transparent", "R"),
    "tint_transmitted":        ("tint",        "T"),
    "tint_reflected":          ("tint",        "R"),
}

ELEMENT_MAP = {
    "Selenium": "se",
    "Sulfur":   "su",
    "Copper":   "cu",
    "Lead":     "pb",
    "Silver":   "ag",
    "Gold":     "au",
}

REACTION_RULES = {
    "Selenium": ["Copper", "Lead", "Silver"],
    "Sulfur":   ["Copper", "Lead", "Silver"],
    "Copper":   ["Selenium", "Sulfur", "Silver"],
    "Lead":     ["Selenium", "Sulfur"],
    "Silver":   ["Selenium", "Sulfur", "Copper"],
    "Gold":     [],
}

_early_cat_id = st.query_params.get("cat_id", "")
st.set_page_config(
    page_title=f"{t('detail.title', 'Glass Detail')} | {_early_cat_id}" if _early_cat_id else t("detail.title", "Glass Detail"),
    layout="wide",
)
render_app_sidebar()

# ---------------------------------------------------------------------------
# Print stylesheet — hides sidebar, expands content, fixes iframe tables
# ---------------------------------------------------------------------------
st.markdown("""
<style>
@media print {
    /* Hide Streamlit chrome */
    [data-testid="stSidebar"],
    [data-testid="stSidebarNav"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    [data-testid="stStatusWidget"],
    footer,
    header,
    #MainMenu,
    .stDeployButton,
    .stButton { display: none !important; }

    /* Full width content */
    [data-testid="stAppViewContainer"],
    [data-testid="block-container"],
    .main .block-container {
        max-width: 100% !important;
        padding: 0.5rem 1rem !important;
        margin: 0 !important;
    }

    /* Expand iframe tables to full content height */
    iframe {
        width: 100% !important;
        min-height: 400px !important;
        height: auto !important;
        overflow: visible !important;
        border: none !important;
    }

    /* Plotly charts — ensure they render */
    .js-plotly-plot, .plotly {
        width: 100% !important;
        page-break-inside: avoid;
    }

    /* Prevent awkward page breaks mid-section */
    [data-testid="stVerticalBlock"] > div {
        page-break-inside: avoid;
    }

    /* Columns: allow side by side on print */
    [data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-wrap: wrap;
    }

    /* Typography */
    body, p, td, th {
        font-size: 11pt !important;
        color: #000 !important;
    }

    h1 { font-size: 18pt !important; }
    h2 { font-size: 15pt !important; }
    h3 { font-size: 13pt !important; }
    h4 { font-size: 12pt !important; }

    /* Page setup */
    @page {
        size: A4 portrait;
        margin: 1.5cm;
    }
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_int(x, default=0):
    try:
        if x is None:
            return default
        try:
            import pandas as _pd
            if _pd.isna(x):
                return default
        except Exception:
            pass
        s = str(x).strip()
        if s == "" or s.lower() == "nan":
            return default
        return int(float(s))
    except Exception:
        return default

def safe_float(x, default=0.0):
    try:
        if x is None:
            return default
        s = str(x).strip()
        if s == "" or s.lower() == "nan":
            return default
        return float(s)
    except Exception:
        return default


def render_html_block(markup: str, *, max_height: int | None = None) -> None:
    if max_height is None:
        st.html(markup)
        return

    st.html(
        f"""
        <div style="max-height:{max_height}px;overflow:auto;">
          {markup}
        </div>
        """
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

def get_con():
    return sqlite3.connect(DB_PATH)

def fetch_catalog(cat_id: str) -> dict | None:
    with get_con() as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM glass_catalog WHERE cat_id = ?", (cat_id,)
        ).fetchone()
        return dict(row) if row else None

def fetch_meas(cat_id: str, mode: str) -> dict | None:
    with get_con() as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM glass_measurements WHERE cat_id = ? AND mode = ?",
            (cat_id, mode.upper()),
        ).fetchone()
        return dict(row) if row else None

def full_image_path(cat_id: str, prefix: str, mode: str) -> Path | None:
    for ext in (".tiff", ".tif"):
        p = FULL_DIR / f"{prefix}_{mode}_{cat_id}{ext}"
        if p.exists():
            return p
    return None

def icon_image_path(cat_id: str, prefix: str, mode: str) -> Path | None:
    p = ICONS_DIR / f"{prefix}_{mode}_{cat_id}.jpg"
    return p if p.exists() else None


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

# ---------------------------------------------------------------------------
# Beer-Lambert curve calculation
# ---------------------------------------------------------------------------
def beer_lambert_curve(
    channel_value: float,
    ref_thickness: float,
    max_thickness: float,
    n_points: int = 200,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Given a measured RGB channel value at ref_thickness (mm),
    derive the absorption coefficient α and extrapolate over 0..max_thickness.

    Beer-Lambert:  I = I₀ · exp(-α · t)
    At t=0:        I = 255  (unattenuated)
    At t=ref:      I = channel_value
    → α = -ln(channel_value / 255) / ref_thickness
    """
    I0 = 255.0
    cv = max(channel_value, 1.0)          # avoid log(0)
    rt = max(ref_thickness, 0.01)         # avoid div/0

    alpha = -math.log(cv / I0) / rt

    t = np.linspace(0, max_thickness, n_points)
    I = I0 * np.exp(-alpha * t)
    I = np.clip(I, 0, 255)
    return t, I

def hsv_brightness_curve(
    v_value: float,
    ref_thickness: float,
    max_thickness: float,
    n_points: int = 200,
) -> tuple[np.ndarray, np.ndarray]:
    """Brightness (V) Beer-Lambert curve, scaled 0-100."""
    I0 = 100.0
    cv = max(v_value, 0.1)
    rt = max(ref_thickness, 0.01)
    alpha = -math.log(cv / I0) / rt
    t = np.linspace(0, max_thickness, n_points)
    V = I0 * np.exp(-alpha * t)
    V = np.clip(V, 0, 100)
    return t, V

def hsv_saturation_curve(
    r_val: float,
    g_val: float,
    b_val: float,
    ref_thickness: float,
    max_thickness: float,
    n_points: int = 200,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Derive saturation at each thickness from the Beer-Lambert RGB curves.
    S = (max(R,G,B) - min(R,G,B)) / max(R,G,B) * 100
    This avoids the degenerate case where stored S=100 makes alpha=0.
    """
    rt = max(ref_thickness, 0.01)
    t = np.linspace(0, max_thickness, n_points)

    _, R_arr = beer_lambert_curve(r_val, rt, max_thickness, n_points)
    _, G_arr = beer_lambert_curve(g_val, rt, max_thickness, n_points)
    _, B_arr = beer_lambert_curve(b_val, rt, max_thickness, n_points)

    cmax = np.maximum(np.maximum(R_arr, G_arr), B_arr)
    cmin = np.minimum(np.minimum(R_arr, G_arr), B_arr)

    S = np.where(cmax > 0, (cmax - cmin) / cmax * 100.0, 0.0)
    S = np.clip(S, 0, 100)
    return t, S

def transmittance(rgb_value: float) -> str:
    return f"{(rgb_value / 255.0) * 100:.1f}%"

# ---------------------------------------------------------------------------
# Navigation — glass_id from query param (?cat_id=001122) or session state
# ---------------------------------------------------------------------------
glass_id = st.query_params.get("cat_id") or st.session_state.get("detail_glass_id")
query_return_page = st.query_params.get("return_page")
query_return_label = st.query_params.get("return_label")

if query_return_page:
    st.session_state["detail_return_page"] = str(query_return_page)
if query_return_label:
    st.session_state["detail_return_label"] = str(query_return_label)

if not glass_id:
    st.info(
        t(
            "detail.messages.no_glass_selected",
            'No glass selected. Open this page from the Glass Library or Color Wheel by clicking "Open full datasheet".',
        )
    )
    st.stop()

# On first load via URL, Streamlit needs one rerun to fully resolve
# image paths and render all components correctly.
if not st.session_state.get("_detail_loaded"):
    st.session_state["_detail_loaded"] = True
    st.rerun()

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
catalog = fetch_catalog(str(glass_id))
if not catalog:
    st.error(t("detail.messages.not_found", "No catalog entry found for {glass_id}.", glass_id=glass_id))
    st.stop()

meas_r = fetch_meas(str(glass_id), "R") or {}
meas_t = fetch_meas(str(glass_id), "T") or {}

family_code = str(catalog.get("glass_family") or "1")
prefix = FAMILY_CODE_TO_PREFIX.get(family_code, "opal")
family_name = translate_family_name(family_code, FAMILY_CODE_TO_NAME.get(family_code, "Glass"))
thickness = safe_float(
    meas_r.get("thickness_mm") or meas_t.get("thickness_mm"), default=2.0
)
max_t = thickness * 4.0
reflected_full_image = full_image_path(glass_id, prefix, "R")
transmitted_full_image = full_image_path(glass_id, prefix, "T")
if reflected_full_image is None and MISSING_FULL.exists():
    reflected_full_image = MISSING_FULL
if transmitted_full_image is None and MISSING_FULL.exists():
    transmitted_full_image = MISSING_FULL

pdf_bytes = build_glass_detail_pdf(
    glass_id=str(glass_id),
    color_name=(catalog.get("color_name") or "").strip(),
    family_name=family_name,
    thickness_mm=thickness,
    catalog=catalog,
    meas_r=meas_r,
    meas_t=meas_t,
    reflected_image=reflected_full_image,
    transmitted_image=transmitted_full_image,
)

color_name = (catalog.get("color_name") or "").strip()
if color_name:
    st.html(f"<title>{glass_id} {color_name}</title>")

detail_return_page = st.session_state.get("detail_return_page") or query_return_page
detail_return_label_key = st.session_state.get("detail_return_label_key")
detail_return_label = (
    t(detail_return_label_key, query_return_label or "Back")
    if detail_return_label_key
    else st.session_state.get("detail_return_label") or query_return_label or t("shared.actions.back", "Back")
)

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
col_back, col_title, col_print = st.columns([0.16, 0.74, 0.10])
with col_back:
    st.markdown("&nbsp;", unsafe_allow_html=True)
    if st.button(f"\u2190 {detail_return_label}", key="detail_back", width="content"):
        target = detail_return_page or "pages/6_Glass_Library.py"
        if not switch_to_page(target):
            st.warning(t("detail.messages.return_failed", "Could not return to the previous page."))
with col_title:
    st.title(f"{glass_id}  {color_name}")

    # Build contains/reacts lists
    contains = []
    for label, col in ELEMENT_MAP.items():
        if safe_int(catalog.get(col)) == 1:
            contains.append(label)
    reacts = []
    for el in contains:
        for r_el in REACTION_RULES.get(el, []):
            if r_el not in reacts:
                reacts.append(r_el)

    ELEMENT_COLOURS = {
        "Selenium": "#e8a020", "Sulfur": "#e8d020", "Copper": "#20a0e8",
        "Lead": "#909090", "Silver": "#c0c0c0", "Gold": "#d4a020",
    }

    badge_html = '<div style="font-family:sans-serif;margin-top:4px;line-height:2.2;">'

    # Striker badge
    if safe_int(catalog.get("is_striker")) == 1:
        badge_html += (
            '<span style="background:#e05020;color:white;font-size:11px;'
            'font-weight:bold;padding:2px 8px;border-radius:3px;margin-right:8px;">'
            f"{t('compare.badge.striker', 'STRIKER')}</span>"
        )

    # Contains badges
    if contains:
        badge_html += (
            '<span style="font-size:12px;color:#555;margin-right:6px;font-weight:bold;">'
            f"{t('detail.labels.contains', 'Contains:')}"
            "</span>"
        )
        for el in contains:
            bg = ELEMENT_COLOURS.get(el, "#888")
            badge_html += (
                f'<span style="background:{bg};color:white;font-size:11px;'
                f'font-weight:bold;padding:2px 7px;border-radius:3px;margin-right:4px;">'
                f'{translate_element_name(el)}</span>'
            )

    # Reacts with badges
    if reacts:
        badge_html += (
            '<span style="font-size:12px;color:#555;margin-left:10px;margin-right:6px;font-weight:bold;">'
            f"{t('detail.labels.may_react_with', 'May react with:')}"
            "</span>"
        )
        for el in reacts:
            bg = ELEMENT_COLOURS.get(el, "#888")
            badge_html += (
                f'<span style="background:{bg};color:white;font-size:11px;'
                f'font-weight:bold;padding:2px 7px;border-radius:3px;margin-right:4px;'
                f'opacity:0.7;">* {translate_element_name(el)}</span>'
            )

    badge_html += '</div>'
    st.markdown(badge_html, unsafe_allow_html=True)
with col_print:
    st.download_button(
        t("detail.actions.download_pdf", "Download PDF"),
        data=pdf_bytes,
        file_name=f"{glass_id}_glass_detail.pdf",
        mime="application/pdf",
        width="content",
    )

st.divider()

# ---------------------------------------------------------------------------
# Layout: top section — tables + images
# ---------------------------------------------------------------------------
def measurement_table(meas: dict):
    """Render HSV / RGB / η table for one mode."""
    r  = safe_int(meas.get("R"))
    g  = safe_int(meas.get("G"))
    b  = safe_int(meas.get("B"))
    h  = safe_int(meas.get("H"))
    s  = safe_int(meas.get("S"))
    v  = safe_int(meas.get("V"))

    table_html = f"""
    <table style="border-collapse:collapse; width:100%; font-size:13px;">
      <tbody>
        <tr style="background:#f5f5f5;">
          <td style="padding:5px 10px; font-weight:bold; width:80px;">HSB</td>
          <td style="padding:5px 10px; text-align:center;">{h}</td>
          <td style="padding:5px 10px; text-align:center;">{s}</td>
          <td style="padding:5px 10px; text-align:center;">{v}</td>
        </tr>
        <tr>
          <td style="padding:5px 10px; font-weight:bold;">RGB</td>
          <td style="padding:5px 10px; text-align:center;">{r}</td>
          <td style="padding:5px 10px; text-align:center;">{g}</td>
          <td style="padding:5px 10px; text-align:center;">{b}</td>
        </tr>
        <tr style="background:#f5f5f5;">
          <td style="padding:5px 10px; font-weight:bold;">η</td>
          <td style="padding:5px 10px; text-align:center;">{transmittance(r)}</td>
          <td style="padding:5px 10px; text-align:center;">{transmittance(g)}</td>
          <td style="padding:5px 10px; text-align:center;">{transmittance(b)}</td>
        </tr>
      </tbody>
    </table>
    """
    render_html_block(table_html)

# ---------------------------------------------------------------------------
# Beer-Lambert curves + data tables
# ---------------------------------------------------------------------------
def color_shift_table_html(meas: dict, thickness: float, max_t: float, title: str) -> str:
    """Build an HTML table of RGB values at 1mm increments with a color swatch column."""
    steps = int(max_t) + 1
    rows_html = ""
    for t_step in range(steps):
        r_val = safe_int(meas.get("R"))
        g_val = safe_int(meas.get("G"))
        b_val = safe_int(meas.get("B"))
        _, r_arr = beer_lambert_curve(r_val, thickness, float(t_step) if t_step > 0 else 0.001)
        _, g_arr = beer_lambert_curve(g_val, thickness, float(t_step) if t_step > 0 else 0.001)
        _, b_arr = beer_lambert_curve(b_val, thickness, float(t_step) if t_step > 0 else 0.001)
        r_at = int(np.clip(r_arr[-1], 0, 255))
        g_at = int(np.clip(g_arr[-1], 0, 255))
        b_at = int(np.clip(b_arr[-1], 0, 255))
        swatch = f"rgb({r_at},{g_at},{b_at})"
        bg = "#f5f5f5" if t_step % 2 == 0 else "white"
        rows_html += f"""
        <tr style="background:{bg};">
          <td style="padding:4px 10px; font-weight:bold;">{t_step}mm</td>
          <td style="padding:4px 10px; text-align:center;">{r_at}</td>
          <td style="padding:4px 10px; text-align:center;">{g_at}</td>
          <td style="padding:4px 10px; text-align:center;">{b_at}</td>
          <td style="padding:4px 6px; width:40px;">
            <div style="background:{swatch}; width:32px; height:16px; border-radius:2px; border:1px solid #ccc;"></div>
          </td>
        </tr>"""
    return f"""
    <table style="border-collapse:collapse; width:100%; font-size:12px;">
      <thead>
        <tr style="background:#4a4a4a; color:white;">
          <th colspan="5" style="padding:6px 10px; text-align:center;">{title}</th>
        </tr>
        <tr style="background:#666; color:white;">
          <th style="padding:4px 10px; text-align:left;">mm</th>
          <th style="padding:4px 10px; text-align:center;">R</th>
          <th style="padding:4px 10px; text-align:center;">G</th>
          <th style="padding:4px 10px; text-align:center;">B</th>
          <th style="padding:4px 10px; text-align:center;">{t('detail.table.color', 'Color')}</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>"""

def bs_table_html(meas: dict, thickness: float, max_t: float, title: str) -> str:
    """Build an HTML table of Brightness and Saturation at 1mm increments."""
    steps = int(max_t) + 1
    v_val = safe_int(meas.get("V"))
    r_val = safe_int(meas.get("R"))
    g_val = safe_int(meas.get("G"))
    b_val = safe_int(meas.get("B"))
    rows_html = ""
    for t_step in range(steps):
        t_f = float(t_step) if t_step > 0 else 0.001
        _, V_arr = hsv_brightness_curve(v_val, thickness, t_f)
        _, S_arr = hsv_saturation_curve(r_val, g_val, b_val, thickness, t_f)
        v_at = round(float(np.clip(V_arr[-1], 0, 100)), 1)
        s_at = round(float(np.clip(S_arr[-1], 0, 100)), 1)
        bg = "#f5f5f5" if t_step % 2 == 0 else "white"
        rows_html += f"""
        <tr style="background:{bg};">
          <td style="padding:4px 10px; font-weight:bold;">{t_step}mm</td>
          <td style="padding:4px 10px; text-align:center;">{v_at}</td>
          <td style="padding:4px 10px; text-align:center;">{s_at}</td>
        </tr>"""
    return f"""
    <table style="border-collapse:collapse; width:100%; font-size:12px;">
      <thead>
        <tr style="background:#4a4a4a; color:white;">
          <th colspan="3" style="padding:6px 10px; text-align:center;">{title}</th>
        </tr>
        <tr style="background:#666; color:white;">
          <th style="padding:4px 10px; text-align:left;">mm</th>
          <th style="padding:4px 10px; text-align:center;">{t('detail.table.brightness', 'Brightness')}</th>
          <th style="padding:4px 10px; text-align:center;">{t('detail.table.saturation', 'Saturation')}</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>"""

def rgb_curve_figure(meas: dict, thickness: float, max_t: float, title: str) -> go.Figure:
    fig = go.Figure()
    for channel, color, label in [("R", "red", "R"), ("G", "green", "G"), ("B", "blue", "B")]:
        val = safe_int(meas.get(channel))
        t_arr, I_arr = beer_lambert_curve(val, thickness, max_t)
        fig.add_trace(go.Scatter(x=t_arr, y=I_arr, mode="lines", name=label,
                                  line=dict(color=color, width=2)))
    fig.add_vline(x=thickness, line_dash="dash", line_color="gray",
                  annotation_text=t("detail.figure.ref_marker", "ref {thickness} mm", thickness=thickness), annotation_position="top right")
    fig.update_layout(title=title, xaxis_title=t("editor.fields.thickness", "Thickness (mm)"),
                      yaxis_title=t("detail.figure.channel_value", "Channel Value (0-255)"),
                      yaxis=dict(range=[0, 260]), xaxis=dict(range=[0, max_t]),
                      legend=dict(orientation="h", y=1.1), height=350,
                      margin=dict(l=40, r=20, t=60, b=40))
    return fig

def bs_curve_figure(meas: dict, thickness: float, max_t: float, title: str) -> go.Figure:
    fig = go.Figure()
    v_val = safe_int(meas.get("V"))
    r_val = safe_int(meas.get("R"))
    g_val = safe_int(meas.get("G"))
    b_val = safe_int(meas.get("B"))
    t_arr, V_arr = hsv_brightness_curve(v_val, thickness, max_t)
    t_arr, S_arr = hsv_saturation_curve(r_val, g_val, b_val, thickness, max_t)
    fig.add_trace(go.Scatter(x=t_arr, y=V_arr, mode="lines", name=t("detail.table.brightness", "Brightness"),
                              line=dict(color="cornflowerblue", width=2)))
    fig.add_trace(go.Scatter(x=t_arr, y=S_arr, mode="lines", name=t("detail.table.saturation", "Saturation"),
                              line=dict(color="limegreen", width=2)))
    fig.add_vline(x=thickness, line_dash="dash", line_color="gray",
                  annotation_text=t("detail.figure.ref_marker", "ref {thickness} mm", thickness=thickness), annotation_position="top right")
    fig.update_layout(title=title, xaxis_title=t("editor.fields.thickness", "Thickness (mm)"),
                      yaxis_title=t("detail.figure.brightness_axis", "Brightness (0-100)"),
                      yaxis=dict(range=[0, 105]), xaxis=dict(range=[0, max_t]),
                      legend=dict(orientation="h", y=1.1), height=350,
                      margin=dict(l=40, r=20, t=60, b=40))
    return fig

table_rows = int(max_t) + 1
table_height = 60 + (table_rows * 26)

def render_light_overview(
    title: str,
    missing_message: str,
    measurement: dict | None,
    image_path: Path | None,
    *,
    show_thickness: bool,
) -> None:
    table_col, image_col, note_col = st.columns([0.4, 0.2, 0.4])
    with table_col:
        st.markdown(f"#### {title}")
        if measurement:
            measurement_table(measurement)
        else:
            st.write(missing_message)
    with image_col:
        if image_path:
            st.image(str(image_path), width=300)
        elif MISSING_FULL.exists():
            st.image(str(MISSING_FULL), width=300)
    with note_col:
        if show_thickness:
            st.markdown(t("detail.messages.thickness_ref", "**Thickness (ref):** {thickness} mm", thickness=thickness))


def render_optical_response_caption() -> None:
    st.markdown(f"### {t('detail.sections.optical_curves', 'Optical Response Curves')}")
    st.caption(
        t(
            "detail.caption.optical_curves",
            "Beer-Lambert extrapolation from reference measurement at {thickness} mm · Range: 0 - {max_thickness} mm",
            thickness=thickness,
            max_thickness=f"{max_t:.1f}",
        )
    )


def render_curve_tables(
    section_title: str,
    measurement: dict,
    color_shift_title: str,
    brightness_title: str,
) -> None:
    st.markdown(f"#### {section_title}")
    chart_col, bs_col = st.columns(2)
    with chart_col:
        st.plotly_chart(
            rgb_curve_figure(measurement, thickness, max_t, color_shift_title),
            width="stretch",
        )
        render_html_block(color_shift_table_html(measurement, thickness, max_t, color_shift_title))
    with bs_col:
        st.plotly_chart(
            bs_curve_figure(measurement, thickness, max_t, brightness_title),
            width="stretch",
        )
        render_html_block(bs_table_html(measurement, thickness, max_t, brightness_title))


render_light_overview(
    t("detail.sections.reflected_light", "Reflected Light"),
    t("detail.messages.no_reflected_data", "No reflected measurement data."),
    meas_r,
    reflected_full_image,
    show_thickness=True,
)

if meas_r:
    render_optical_response_caption()
    render_curve_tables(
        t("detail.sections.reflected", "Reflected"),
        meas_r,
        t("detail.figure.color_shift.reflected", "Reflected Color Shift"),
        t("detail.figure.bs.reflected", "Reflected Brightness & Saturation"),
    )

st.divider()

render_light_overview(
    t("detail.sections.transmitted_light", "Transmitted Light"),
    t("detail.messages.no_transmitted_data", "No transmitted measurement data."),
    meas_t,
    transmitted_full_image,
    show_thickness=False,
)

if meas_t:
    render_curve_tables(
        t("detail.sections.transmitted", "Transmitted"),
        meas_t,
        t("detail.figure.color_shift.transmitted", "Transmitted Color Shift"),
        t("detail.figure.bs.transmitted", "Transmitted Brightness & Saturation"),
    )

st.divider()

# ---------------------------------------------------------------------------
# Cold Characteristics + Working Notes
# ---------------------------------------------------------------------------
notes_col1, notes_col2 = st.columns(2)

cold = (catalog.get("cold_characteristics") or "").strip()
work = (catalog.get("working_notes") or "").strip()

with notes_col1:
    if cold:
        st.markdown(f"### {t('shared.sections.cold_characteristics', 'Cold Characteristics')}")
        cold_height = min(max(100, len(cold) // 2), 1000)
        render_html_block(note_markup(cold), max_height=cold_height)

with notes_col2:
    if work:
        st.markdown(f"### {t('shared.sections.working_notes', 'Working Notes')}")
        work_height = min(max(100, len(work) // 2), 1000)
        render_html_block(note_markup(work), max_height=work_height)
