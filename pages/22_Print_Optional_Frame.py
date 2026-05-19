"""
22_Print_Optional_Frame.py
Fabrication setup for framed relief prints, backing glass, and fiber paper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
import re
import sqlite3
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
import streamlit as st

from i18n import render_app_sidebar, t


st.set_page_config(page_title=t("page.print_frame.title", "Print Frame Fabrication"), layout="wide")
render_app_sidebar()

st.markdown(
    """
    <style>
    table.worksheet-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.76rem;
        margin: 0.35rem 0 1.1rem;
        table-layout: fixed;
    }
    table.worksheet-table th:nth-child(1),
    table.worksheet-table td:nth-child(1) { width: 28%; }
    table.worksheet-table th:nth-child(2),
    table.worksheet-table td:nth-child(2) { width: 16%; }
    table.worksheet-table th:nth-child(3),
    table.worksheet-table td:nth-child(3) { width: 12%; }
    table.worksheet-table th:nth-child(4),
    table.worksheet-table td:nth-child(4) { width: 44%; }
    .worksheet-table th,
    .worksheet-table td {
        border: 1px solid rgba(49, 51, 63, 0.12);
        padding: 0.42rem 0.5rem;
        vertical-align: top;
        overflow-wrap: anywhere;
    }
    .worksheet-table th {
        background: #f6f7f9;
        color: rgba(49, 51, 63, 0.72);
        font-weight: 650;
        text-align: left !important;
    }
    .worksheet-table td:nth-child(2) {
        font-variant-numeric: tabular-nums;
        text-align: right;
        font-weight: 400;
    }
    .checklist-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.92rem;
        margin: 0.35rem 0 1.1rem;
    }
    .checklist-table th,
    .checklist-table td {
        border: 1px solid rgba(49, 51, 63, 0.12);
        padding: 0.42rem 0.5rem;
        vertical-align: top;
    }
    .checklist-table th {
        background: #f6f7f9;
        color: rgba(49, 51, 63, 0.72);
        font-weight: 650;
        text-align: left;
    }
    .checklist-table td:not(:first-child) {
        font-variant-numeric: tabular-nums;
    }
    .section-band {
        padding: 0.42rem 0.7rem;
        border: 1px solid rgba(49, 51, 63, 0.18);
        font-size: 0.9rem;
        font-weight: 650;
        margin: 0.8rem 0 0.25rem;
    }
    .band-purple { background: #d5a8f4; }
    .band-blue { background: #8ee6ee; }
    .band-green { background: #c6fb85; }
    .band-pink { background: #f58ab8; }
    .band-orange { background: #ffc16a; }
    </style>
    """,
    unsafe_allow_html=True,
)


GLASS_MANUFACTURERS = {
    "Bullseye Glass": 2.5,
    "Oceanside": 2.53,
    "Gaffer Casting": 3.6,
    "Custom": 2.5,
}
DEFAULT_GLASS_MANUFACTURER = "Bullseye Glass"
DEFAULT_GLASS_DENSITY_G_PER_CM3 = GLASS_MANUFACTURERS[DEFAULT_GLASS_MANUFACTURER]
MM_LAYER_TO_CM = 0.1
DEFAULT_FRAME_BORDER_MM = 10.0
SIDE_WALL_FIBER_ALLOWANCE_MM = 16.0
APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "fabrication_records.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
RECORD_FIELDS = (
    "title",
    "job_date",
    "max_mold_height_mm",
    "fiber_paper_thickness_mm",
    "fiber_paper_layers",
    "fiber_paper_height_mm",
    "mold_x_mm",
    "mold_y_mm",
    "frame_border_x_mm",
    "frame_border_y_mm",
    "relief_background_layer_mm",
    "backing_layer_mm",
    "relief_fill_g",
    "relief_fill_volume_cm3",
    "glass_manufacturer",
    "glass_density_g_per_cm3",
)


def parse_number(value: str) -> float:
    return float(value.replace(",", "").strip())


def selected_density() -> float:
    return float(st.session_state.get("pf_glass_density_g_per_cm3", DEFAULT_GLASS_DENSITY_G_PER_CM3) or DEFAULT_GLASS_DENSITY_G_PER_CM3)


def sync_relief_fill_volume_from_weight() -> None:
    density = selected_density()
    fill_g = float(st.session_state.get("pf_relief_fill_g", 0.0) or 0.0)
    st.session_state["pf_relief_fill_volume_cm3"] = fill_g / density if density else 0.0


def sync_relief_fill_weight_from_volume() -> None:
    volume = float(st.session_state.get("pf_relief_fill_volume_cm3", 0.0) or 0.0)
    st.session_state["pf_relief_fill_g"] = volume * selected_density()


def update_density_from_manufacturer() -> None:
    manufacturer = str(st.session_state.get("pf_glass_manufacturer", DEFAULT_GLASS_MANUFACTURER))
    if manufacturer in GLASS_MANUFACTURERS and manufacturer != "Custom":
        st.session_state["pf_glass_density_g_per_cm3"] = GLASS_MANUFACTURERS[manufacturer]
        sync_relief_fill_weight_from_volume()


def update_custom_density() -> None:
    st.session_state["pf_glass_manufacturer"] = "Custom"
    sync_relief_fill_weight_from_volume()


def parse_settings_txt(text: str, density_g_per_cm3: float) -> dict[str, float | str]:
    out: dict[str, float | str] = {}
    patterns = {
        "image_name": r"Image:\s*(.+)",
        "base_backing_mm": r"Base backing thickness \(mm\):\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        "total_volume_cm3": r"Total volume \(cm\^3\):\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        "output_size": (
            r"Output size \(mm\):\s*"
            r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*x\s*"
            r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*x\s*"
            r"([0-9][0-9,]*(?:\.[0-9]+)?)"
        ),
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        if key == "image_name":
            out[key] = match.group(1).strip()
        elif key == "output_size":
            out["mold_x_mm"] = parse_number(match.group(1))
            out["mold_y_mm"] = parse_number(match.group(2))
            out["max_mold_height_mm"] = parse_number(match.group(3))
        else:
            out[key] = parse_number(match.group(1))

    if {"mold_x_mm", "mold_y_mm", "max_mold_height_mm", "total_volume_cm3"} <= out.keys():
        mold_x = float(out["mold_x_mm"])
        mold_y = float(out["mold_y_mm"])
        max_z = float(out["max_mold_height_mm"])
        total_volume = float(out["total_volume_cm3"])
        full_rectangular_volume = mold_x * mold_y * max_z / 1000.0
        relief_fill_volume = clamp_nonnegative(full_rectangular_volume - total_volume)
        out["relief_fill_volume_cm3"] = relief_fill_volume
        out["relief_fill_g"] = relief_fill_volume * density_g_per_cm3
    return out


def apply_imported_settings(parsed: dict[str, float | str]) -> list[str]:
    filled: list[str] = []
    if image_name := str(parsed.get("image_name", "")).strip():
        st.session_state["pf_title"] = Path(image_name).stem
        filled.append("title")
    if "max_mold_height_mm" in parsed:
        st.session_state["pf_max_mold_height_mm"] = float(parsed["max_mold_height_mm"])
        filled.append("print Z length")
    if "mold_x_mm" in parsed:
        mold_x = float(parsed["mold_x_mm"])
        st.session_state["pf_mold_x_mm"] = mold_x
        st.session_state["pf_frame_border_x_mm"] = DEFAULT_FRAME_BORDER_MM
        filled.append("mold X")
    if "mold_y_mm" in parsed:
        mold_y = float(parsed["mold_y_mm"])
        st.session_state["pf_mold_y_mm"] = mold_y
        st.session_state["pf_frame_border_y_mm"] = DEFAULT_FRAME_BORDER_MM
        filled.append("mold Y")
    if "relief_fill_g" in parsed:
        st.session_state["pf_relief_fill_g"] = float(parsed["relief_fill_g"])
        filled.append("relief fill glass")
    if "relief_fill_volume_cm3" in parsed:
        st.session_state["pf_relief_fill_volume_cm3"] = float(parsed["relief_fill_volume_cm3"])
    return filled


@dataclass(frozen=True)
class FrameInputs:
    title: str
    job_date: date
    glass_manufacturer: str
    glass_density_g_per_cm3: float
    max_mold_height_mm: float
    fiber_paper_thickness_mm: float
    fiber_paper_layers: int
    fiber_paper_height_mm: float
    mold_x_mm: float
    mold_y_mm: float
    frame_border_x_mm: float
    frame_border_y_mm: float
    relief_background_layer_mm: float
    backing_layer_mm: float
    relief_fill_g: float


def clamp_nonnegative(value: float) -> float:
    return max(0.0, float(value))


def area_cm2(length_mm: float, width_mm: float) -> float:
    return clamp_nonnegative(length_mm) * clamp_nonnegative(width_mm) / 100.0


def glass_g_per_mm(area: float, density_g_per_cm3: float) -> float:
    return area * MM_LAYER_TO_CM * clamp_nonnegative(density_g_per_cm3)


def calc_frame(inputs: FrameInputs) -> dict[str, float]:
    density = clamp_nonnegative(inputs.glass_density_g_per_cm3)
    fiber_paper_layers = max(1, int(inputs.fiber_paper_layers or 1))
    fiber_paper_thickness = clamp_nonnegative(inputs.fiber_paper_thickness_mm)
    fiber_paper_displacement = clamp_nonnegative(fiber_paper_thickness * fiber_paper_layers)
    relief_frame_height = clamp_nonnegative(inputs.max_mold_height_mm - fiber_paper_displacement)
    relief_background_layer = clamp_nonnegative(inputs.relief_background_layer_mm)
    backing_layer = clamp_nonnegative(inputs.backing_layer_mm)
    frame_height = relief_frame_height + relief_background_layer
    mold_x = clamp_nonnegative(inputs.mold_x_mm)
    mold_y = clamp_nonnegative(inputs.mold_y_mm)
    frame_width_x = clamp_nonnegative(inputs.frame_border_x_mm)
    frame_width_y = clamp_nonnegative(inputs.frame_border_y_mm)
    side_x = mold_x + frame_width_x * 2.0
    side_y = mold_y + frame_width_y * 2.0

    fiber_x_length = clamp_nonnegative(side_x - frame_width_x)
    fiber_y_length = clamp_nonnegative(side_y - frame_width_y)

    x_area = area_cm2(fiber_x_length, frame_width_x)
    y_area = area_cm2(fiber_y_length, frame_width_y)
    x_g_per_mm = glass_g_per_mm(x_area, density)
    y_g_per_mm = glass_g_per_mm(y_area, density)
    side_x_g = x_g_per_mm * frame_height
    side_y_g = y_g_per_mm * frame_height
    total_frame_g = 2.0 * (side_x_g + side_y_g)

    mold_area = area_cm2(mold_x, mold_y)
    side_area = area_cm2(side_x, side_y)
    art_space_g_per_mm = glass_g_per_mm(mold_area, density)
    backing_g_per_mm = glass_g_per_mm(side_area, density)
    frame_g_per_mm = total_frame_g / frame_height if frame_height else 0.0
    relief_background_g = art_space_g_per_mm * relief_background_layer
    backing_g = backing_g_per_mm * backing_layer
    full_side_height = clamp_nonnegative(inputs.max_mold_height_mm) + relief_background_layer + backing_layer
    side_wall_fiber_x_length = side_x + SIDE_WALL_FIBER_ALLOWANCE_MM
    side_wall_fiber_y_length = side_y + SIDE_WALL_FIBER_ALLOWANCE_MM

    return {
        "max_mold_height_mm": clamp_nonnegative(inputs.max_mold_height_mm),
        "glass_manufacturer": inputs.glass_manufacturer,
        "glass_density_g_per_cm3": density,
        "fiber_paper_thickness_mm": fiber_paper_thickness,
        "fiber_paper_layers": float(fiber_paper_layers),
        "fiber_paper_height_mm": fiber_paper_displacement,
        "fiber_paper_displacement_mm": fiber_paper_displacement,
        "relief_frame_height_mm": relief_frame_height,
        "relief_background_layer_mm": relief_background_layer,
        "frame_height_mm": frame_height,
        "side_x_mm": side_x,
        "side_y_mm": side_y,
        "mold_x_mm": mold_x,
        "mold_y_mm": mold_y,
        "frame_width_x_mm": frame_width_x,
        "frame_width_y_mm": frame_width_y,
        "fiber_x_length_mm": fiber_x_length,
        "fiber_x_width_mm": frame_width_x,
        "fiber_y_length_mm": fiber_y_length,
        "fiber_y_width_mm": frame_width_y,
        "x_area_cm2": x_area,
        "x_g_per_mm": x_g_per_mm,
        "side_x_g": side_x_g,
        "total_side_x_g": side_x_g * 2.0,
        "y_area_cm2": y_area,
        "y_g_per_mm": y_g_per_mm,
        "side_y_g": side_y_g,
        "total_side_y_g": side_y_g * 2.0,
        "total_frame_g": total_frame_g,
        "mold_area_cm2": mold_area,
        "side_area_cm2": side_area,
        "art_space_g_per_mm": art_space_g_per_mm,
        "relief_fill_g": clamp_nonnegative(inputs.relief_fill_g),
        "relief_background_g": relief_background_g,
        "backing_g_per_mm": backing_g_per_mm,
        "frame_g_per_mm": frame_g_per_mm,
        "backing_layer_mm": backing_layer,
        "backing_g": backing_g,
        "backing_plus_relief_g": backing_g + relief_background_g + clamp_nonnegative(inputs.relief_fill_g),
        "full_side_height_mm": full_side_height,
        "side_wall_fiber_allowance_mm": SIDE_WALL_FIBER_ALLOWANCE_MM,
        "side_wall_fiber_x_length_mm": side_wall_fiber_x_length,
        "side_wall_fiber_y_length_mm": side_wall_fiber_y_length,
        "side_wall_fiber_height_mm": full_side_height,
        "total_thickness_z_mm": clamp_nonnegative(inputs.max_mold_height_mm - fiber_paper_thickness)
        + relief_background_layer
        + backing_layer,
        "fabrication_total_g": total_frame_g + relief_background_g + backing_g + clamp_nonnegative(inputs.relief_fill_g),
    }


def fmt(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}"


def worksheet_rows(c: dict[str, float]) -> list[dict[str, str]]:
    density = fmt(c["glass_density_g_per_cm3"], 2)
    return [
        {"Section": "Glass", "Item": "Manufacturer", "Value": str(c["glass_manufacturer"]), "Unit": "", "Formula": "Selected glass source"},
        {"Section": "Glass", "Item": "Specific gravity", "Value": density, "Unit": "g/cm³", "Formula": "Glass density used for weight calculations"},
        {"Section": "Frame Height", "Item": "Print Z length (height)", "Value": fmt(c["max_mold_height_mm"]), "Unit": "mm", "Formula": "Print Z"},
        {"Section": "Frame Height", "Item": "Fiber paper thickness", "Value": fmt(c["fiber_paper_thickness_mm"]), "Unit": "mm", "Formula": "Measured fiber paper sheet"},
        {"Section": "Frame Height", "Item": "Fiber paper layers", "Value": fmt(c["fiber_paper_layers"], 0), "Unit": "", "Formula": "1 layer, or 2 when doubled"},
        {"Section": "Frame Height", "Item": "Fiber paper glass displacement", "Value": fmt(c["fiber_paper_displacement_mm"]), "Unit": "mm", "Formula": "Thickness x layers"},
        {"Section": "Frame Height", "Item": "Relief frame height", "Value": fmt(c["relief_frame_height_mm"]), "Unit": "mm", "Formula": "Print Z length - fiber paper displacement"},
        {"Section": "Frame Height", "Item": "Relief background layer", "Value": fmt(c["relief_background_layer_mm"]), "Unit": "mm", "Formula": "Additional field layer over print"},
        {"Section": "Frame Height", "Item": "Frame glass height", "Value": fmt(c["frame_height_mm"]), "Unit": "mm", "Formula": "Relief frame height + relief background layer"},
        {"Section": "Side X", "Item": "Side X length", "Value": fmt(c["side_x_mm"]), "Unit": "mm", "Formula": "Outside X length"},
        {"Section": "Side X", "Item": "Print X length", "Value": fmt(c["mold_x_mm"]), "Unit": "mm", "Formula": "Known 3D print dimension"},
        {"Section": "Side X", "Item": "Frame width", "Value": fmt(c["frame_width_x_mm"]), "Unit": "mm", "Formula": "(Side X - Print X) / 2"},
        {"Section": "Side X", "Item": "Fiber paper length", "Value": fmt(c["fiber_x_length_mm"]), "Unit": "mm", "Formula": "Side X - frame width"},
        {"Section": "Side X", "Item": "Fiber paper width", "Value": fmt(c["fiber_x_width_mm"]), "Unit": "mm", "Formula": "Frame width"},
        {"Section": "Side X", "Item": "Side-wall fiber size", "Value": f"{fmt(c['side_wall_fiber_height_mm'])} x {fmt(c['side_wall_fiber_x_length_mm'])}", "Unit": "mm", "Formula": "Full side height x (outside X + 16)"},
        {"Section": "Side X", "Item": "Glass area", "Value": fmt(c["x_area_cm2"]), "Unit": "cm²", "Formula": "Length x width / 100"},
        {"Section": "Side X", "Item": "Glass per mm", "Value": fmt(c["x_g_per_mm"]), "Unit": "g/mm", "Formula": f"Area x 0.1 x {density}"},
        {"Section": "Side X", "Item": "One side", "Value": fmt(c["side_x_g"]), "Unit": "g", "Formula": "Glass per mm x frame height"},
        {"Section": "Side X", "Item": "Total side X", "Value": fmt(c["total_side_x_g"]), "Unit": "g", "Formula": "One side x 2"},
        {"Section": "Side Y", "Item": "Side Y length", "Value": fmt(c["side_y_mm"]), "Unit": "mm", "Formula": "Outside Y length"},
        {"Section": "Side Y", "Item": "Print Y length", "Value": fmt(c["mold_y_mm"]), "Unit": "mm", "Formula": "Known 3D print dimension"},
        {"Section": "Side Y", "Item": "Frame width", "Value": fmt(c["frame_width_y_mm"]), "Unit": "mm", "Formula": "(Side Y - Print Y) / 2"},
        {"Section": "Side Y", "Item": "Fiber paper length", "Value": fmt(c["fiber_y_length_mm"]), "Unit": "mm", "Formula": "Side Y - frame width"},
        {"Section": "Side Y", "Item": "Fiber paper width", "Value": fmt(c["fiber_y_width_mm"]), "Unit": "mm", "Formula": "Frame width"},
        {"Section": "Side Y", "Item": "Side-wall fiber size", "Value": f"{fmt(c['side_wall_fiber_height_mm'])} x {fmt(c['side_wall_fiber_y_length_mm'])}", "Unit": "mm", "Formula": "Full side height x (outside Y + 16)"},
        {"Section": "Side Y", "Item": "Glass area", "Value": fmt(c["y_area_cm2"]), "Unit": "cm²", "Formula": "Length x width / 100"},
        {"Section": "Side Y", "Item": "Glass per mm", "Value": fmt(c["y_g_per_mm"]), "Unit": "g/mm", "Formula": f"Area x 0.1 x {density}"},
        {"Section": "Side Y", "Item": "One side", "Value": fmt(c["side_y_g"]), "Unit": "g", "Formula": "Glass per mm x frame height"},
        {"Section": "Side Y", "Item": "Total side Y", "Value": fmt(c["total_side_y_g"]), "Unit": "g", "Formula": "One side x 2"},
        {"Section": "Frame", "Item": "Total frame", "Value": fmt(c["total_frame_g"]), "Unit": "g", "Formula": "Total side X + total side Y"},
        {"Section": "Relief Fill", "Item": "Relief fill glass", "Value": fmt(c["relief_fill_g"]), "Unit": "g", "Formula": "Rectangular output volume - exported model volume"},
        {"Section": "Relief Fill", "Item": "Print field fill rate", "Value": fmt(c["art_space_g_per_mm"]), "Unit": "g/mm", "Formula": f"Print X x Print Y / 1000 x {density}"},
        {"Section": "Relief Fill", "Item": "Relief background glass", "Value": fmt(c["relief_background_g"]), "Unit": "g", "Formula": "Print field fill rate x background layer"},
        {"Section": "Backing", "Item": "Backing area", "Value": fmt(c["side_area_cm2"]), "Unit": "cm²", "Formula": "Side X x Side Y / 100"},
        {"Section": "Backing", "Item": "Backing glass per mm", "Value": fmt(c["backing_g_per_mm"]), "Unit": "g/mm", "Formula": f"Backing area x 0.1 x {density}"},
        {"Section": "Backing", "Item": "Frame glass per mm", "Value": fmt(c["frame_g_per_mm"]), "Unit": "g/mm", "Formula": "Total frame / frame height"},
        {"Section": "Backing", "Item": "Backing layer", "Value": fmt(c["backing_layer_mm"]), "Unit": "mm", "Formula": "Additional full-footprint layer"},
        {"Section": "Backing", "Item": "Backing glass", "Value": fmt(c["backing_g"]), "Unit": "g", "Formula": "Backing glass per mm x backing layer"},
        {"Section": "Backing", "Item": "Backing + relief layers", "Value": fmt(c["backing_plus_relief_g"]), "Unit": "g", "Formula": "Backing + relief background + relief fill"},
        {"Section": "Backing", "Item": "Full side height", "Value": fmt(c["full_side_height_mm"]), "Unit": "mm", "Formula": "Print Z + relief background + backing layer"},
        {"Section": "Backing", "Item": "Total thickness Z", "Value": fmt(c["total_thickness_z_mm"]), "Unit": "mm", "Formula": "Print Z - fiber thickness + relief background + backing layer"},
    ]


def weight_summary_rows(c: dict[str, float]) -> list[dict[str, float | str]]:
    return [
        {
            "Region": "Relief fill",
            "Footprint": "Print field",
            "Area (cm²)": c["mold_area_cm2"],
            "Height (mm)": c["max_mold_height_mm"],
            "Glass (g)": c["relief_fill_g"],
        },
        {
            "Region": "Relief background",
            "Footprint": "Print field",
            "Area (cm²)": c["mold_area_cm2"],
            "Height (mm)": c["relief_background_layer_mm"],
            "Glass (g)": c["relief_background_g"],
        },
        {
            "Region": "X frame strips",
            "Footprint": "2 X strips",
            "Area (cm²)": c["x_area_cm2"] * 2.0,
            "Height (mm)": c["frame_height_mm"],
            "Glass (g)": c["total_side_x_g"],
        },
        {
            "Region": "Y frame strips",
            "Footprint": "2 Y strips",
            "Area (cm²)": c["y_area_cm2"] * 2.0,
            "Height (mm)": c["frame_height_mm"],
            "Glass (g)": c["total_side_y_g"],
        },
        {
            "Region": "Backing with frame",
            "Footprint": "Side X x Side Y",
            "Area (cm²)": c["side_area_cm2"],
            "Height (mm)": c["backing_layer_mm"],
            "Glass (g)": c["backing_g"],
        },
    ]


def top_view_svg(c: dict[str, float]) -> str:
    side_x = max(c["side_x_mm"], 1.0)
    side_y = max(c["side_y_mm"], 1.0)
    mold_x = min(c["mold_x_mm"], side_x)
    mold_y = min(c["mold_y_mm"], side_y)
    frame_x = max(c["frame_width_x_mm"], 0.0)
    frame_y = max(c["frame_width_y_mm"], 0.0)
    scale = min(430 / side_x, 330 / side_y)
    side_w = side_x * scale
    side_h = side_y * scale
    mold_w = mold_x * scale
    mold_h = mold_y * scale
    frame_x_px = frame_x * scale
    frame_y_px = frame_y * scale
    left = 110
    top = 92
    mold_left = left + frame_x_px
    mold_top = top + frame_y_px
    right = left + side_w
    bottom = top + side_h
    mold_right = mold_left + mold_w
    mold_bottom = mold_top + mold_h
    side_label_x = left - 38
    frame_dim_y = bottom + 34
    return f"""
    <svg viewBox="0 0 680 520" width="100%" role="img" aria-label="Top footprint preview">
      <defs>
        <marker id="topArrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" fill="#222"/>
        </marker>
      </defs>
      <style>
        .title {{ font: 700 20px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; fill:#111; }}
        .label {{ font: 17px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; fill:#202124; }}
        .small {{ font: 15px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; fill:#202124; }}
        .dim {{ stroke:#222; stroke-width:1.7; marker-start:url(#topArrow); marker-end:url(#topArrow); }}
        .guide {{ stroke:#222; stroke-width:2.2; stroke-dasharray:4 5; }}
      </style>
      <text x="340" y="32" text-anchor="middle" class="title">Top View</text>

      <rect x="{left:.1f}" y="{top:.1f}" width="{side_w - frame_x_px:.1f}" height="{frame_y_px:.1f}" fill="#8ee6ee" stroke="#222" stroke-width="2"/>
      <rect x="{left:.1f}" y="{mold_top:.1f}" width="{frame_x_px:.1f}" height="{side_h - frame_y_px:.1f}" fill="#c6fb85" stroke="#222" stroke-width="2"/>
      <rect x="{right - frame_x_px:.1f}" y="{top:.1f}" width="{frame_x_px:.1f}" height="{side_h - frame_y_px:.1f}" fill="#c6fb85" stroke="#222" stroke-width="2"/>
      <rect x="{mold_left:.1f}" y="{bottom - frame_y_px:.1f}" width="{side_w - frame_x_px:.1f}" height="{frame_y_px:.1f}" fill="#8ee6ee" stroke="#222" stroke-width="2"/>
      <rect x="{mold_left:.1f}" y="{mold_top:.1f}" width="{mold_w:.1f}" height="{mold_h:.1f}" fill="#e985b6" stroke="#222" stroke-width="2"/>

      <line x1="{left:.1f}" y1="{top - 14:.1f}" x2="{right:.1f}" y2="{top - 14:.1f}" class="dim"/>
      <text x="{left + side_w / 2:.1f}" y="{top - 27:.1f}" text-anchor="middle" class="label">Side X</text>
      <line x1="{left:.1f}" y1="{top - 58:.1f}" x2="{left:.1f}" y2="{top:.1f}" class="guide"/>
      <line x1="{right:.1f}" y1="{top - 58:.1f}" x2="{right:.1f}" y2="{top:.1f}" class="guide"/>

      <line x1="{left - 12:.1f}" y1="{top:.1f}" x2="{left - 12:.1f}" y2="{bottom:.1f}" class="dim"/>
      <text x="{side_label_x:.1f}" y="{top + side_h / 2:.1f}" transform="rotate(90 {side_label_x:.1f},{top + side_h / 2:.1f})" text-anchor="middle" class="label">Side Y</text>
      <line x1="{left - 58:.1f}" y1="{top:.1f}" x2="{left:.1f}" y2="{top:.1f}" class="guide"/>
      <line x1="{left - 58:.1f}" y1="{bottom:.1f}" x2="{left:.1f}" y2="{bottom:.1f}" class="guide"/>

      <line x1="{mold_left:.1f}" y1="{mold_top + 36:.1f}" x2="{mold_right:.1f}" y2="{mold_top + 36:.1f}" class="dim"/>
      <text x="{mold_left + mold_w / 2:.1f}" y="{mold_top + 25:.1f}" text-anchor="middle" class="label">Mold X Length</text>

      <line x1="{mold_left + 30:.1f}" y1="{mold_top:.1f}" x2="{mold_left + 30:.1f}" y2="{mold_bottom:.1f}" class="dim"/>
      <text x="{mold_left + 47:.1f}" y="{mold_top + mold_h / 2:.1f}" transform="rotate(90 {mold_left + 47:.1f},{mold_top + mold_h / 2:.1f})" text-anchor="middle" class="label">Mold Y Length</text>

      <line x1="{left:.1f}" y1="{frame_dim_y:.1f}" x2="{mold_left:.1f}" y2="{frame_dim_y:.1f}" class="dim"/>
      <text x="{mold_left + 24:.1f}" y="{frame_dim_y + 5:.1f}" class="label">Frame Width</text>
      <line x1="{left:.1f}" y1="{bottom:.1f}" x2="{left:.1f}" y2="{frame_dim_y + 22:.1f}" class="guide"/>
      <line x1="{mold_left:.1f}" y1="{mold_top:.1f}" x2="{mold_left:.1f}" y2="{frame_dim_y + 22:.1f}" class="guide"/>
    </svg>
    """


def profile_view_svg(c: dict[str, float]) -> str:
    side_x = max(c["side_x_mm"], 1.0)
    mold_x = min(c["mold_x_mm"], side_x)
    frame_w = max(c["frame_width_x_mm"], 0.0)
    fiber_h = max(c["fiber_paper_height_mm"], 0.0)
    print_h = max(c["max_mold_height_mm"], 0.0)
    relief_h = max(c["relief_frame_height_mm"], 0.0)
    relief_bg_h = max(c["relief_background_layer_mm"], 0.0)
    backing_h = max(c["backing_layer_mm"], 0.0)
    visual_h = max(c["full_side_height_mm"], 1.0)

    scale = min(500 / side_x, 190 / visual_h)
    side_w = side_x * scale
    frame_w_px = frame_w * scale
    mold_w_px = mold_x * scale
    fiber_h_px = fiber_h * scale
    print_h_px = print_h * scale
    frame_glass_h_px = (relief_h + relief_bg_h) * scale
    relief_bg_h_px = relief_bg_h * scale
    backing_h_px = backing_h * scale

    left = 70
    shelf_top = 300
    shelf_h = 18
    content_left = left + frame_w_px
    right = left + side_w
    content_right = content_left + mold_w_px
    right_frame_x = content_right
    mold_y = shelf_top - print_h_px
    relief_bg_y = mold_y - relief_bg_h_px
    backing_y = relief_bg_y - backing_h_px
    fiber_y = shelf_top - fiber_h_px
    frame_y = relief_bg_y
    profile_top = backing_y
    dim_x = right + 36

    def center_label(x: float, y: float, w: float, h: float, label: str) -> str:
        if w < 34 or h < 15:
            return ""
        return f'<text x="{x + w / 2:.1f}" y="{y + h / 2 + 4:.1f}" text-anchor="middle" class="layer-label">{label}</text>'

    def legend_item(x: float, y: float, fill: str, stroke: str, label: str) -> str:
        return (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="12" height="12" rx="1.5" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
            f'<text x="{x + 18:.1f}" y="{y + 10:.1f}" class="legend-label">{label}</text>'
        )

    return f"""
    <svg viewBox="0 0 680 400" width="100%" role="img" aria-label="Fabrication profile preview">
      <defs>
        <marker id="profileArrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" fill="#222"/>
        </marker>
      </defs>
      <style>
        .title {{ font: 700 20px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; fill:#111; }}
        .subtitle {{ font: 13px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; fill:#5f6368; }}
        .layer-label {{ font: 12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; fill:#202124; }}
        .legend-label {{ font: 11px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; fill:#303241; }}
        .small {{ font: 12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; fill:#202124; }}
        .dim {{ stroke:#222; stroke-width:1.5; marker-start:url(#profileArrow); marker-end:url(#profileArrow); }}
        .guide {{ stroke:#222; stroke-width:1.4; stroke-dasharray:4 5; }}
      </style>
      <text x="340" y="32" text-anchor="middle" class="title">Fabrication Profile</text>
      <text x="340" y="51" text-anchor="middle" class="subtitle">Side view across X - proportional scale</text>
      {legend_item(92, 76, "#f3aebe", "#222", "Frame/backing glass")}
      {legend_item(244, 76, "#fff6d8", "#222", "Relief background")}
      {legend_item(388, 76, "#e4e0f8", "#222", "Refractory mold")}
      {legend_item(218, 96, "#f1eeee", "#222", "Fiber paper")}
      {legend_item(330, 96, "#e9e2c6", "#8f8a78", "Kiln shelf")}

      <rect x="{left - 24:.1f}" y="{shelf_top:.1f}" width="{side_w + 48:.1f}" height="{shelf_h:.1f}" fill="#e9e2c6" stroke="#8f8a78" stroke-width="1.2"/>
      <text x="{left + side_w / 2:.1f}" y="{shelf_top + shelf_h / 2 + 4:.1f}" text-anchor="middle" class="small">Kiln shelf</text>

      <rect x="{content_left:.1f}" y="{mold_y:.1f}" width="{mold_w_px:.1f}" height="{print_h_px:.1f}" fill="#e4e0f8" stroke="#222" stroke-width="2"/>
      <rect x="{content_left:.1f}" y="{relief_bg_y:.1f}" width="{mold_w_px:.1f}" height="{relief_bg_h_px:.1f}" fill="#fff6d8" stroke="#222" stroke-width="2"/>
      <rect x="{left:.1f}" y="{fiber_y:.1f}" width="{frame_w_px:.1f}" height="{fiber_h_px:.1f}" fill="#f1eeee" stroke="#222" stroke-width="2"/>
      <rect x="{right_frame_x:.1f}" y="{fiber_y:.1f}" width="{frame_w_px:.1f}" height="{fiber_h_px:.1f}" fill="#f1eeee" stroke="#222" stroke-width="2"/>
      <rect x="{left:.1f}" y="{frame_y:.1f}" width="{frame_w_px:.1f}" height="{frame_glass_h_px:.1f}" fill="#f3aebe" stroke="#222" stroke-width="2"/>
      <rect x="{right_frame_x:.1f}" y="{frame_y:.1f}" width="{frame_w_px:.1f}" height="{frame_glass_h_px:.1f}" fill="#f3aebe" stroke="#222" stroke-width="2"/>
      <rect x="{left:.1f}" y="{backing_y:.1f}" width="{side_w:.1f}" height="{backing_h_px:.1f}" fill="#f3aebe" stroke="#222" stroke-width="2"/>

      {center_label(content_left, mold_y, mold_w_px, print_h_px, "Refractory mold")}

      <line x1="{dim_x:.1f}" y1="{profile_top:.1f}" x2="{dim_x:.1f}" y2="{shelf_top:.1f}" class="dim"/>
      <text x="{dim_x + 18:.1f}" y="{profile_top + (shelf_top - profile_top) / 2:.1f}" transform="rotate(90 {dim_x + 18:.1f},{profile_top + (shelf_top - profile_top) / 2:.1f})" text-anchor="middle" class="small">full side height {fmt(visual_h)} mm</text>
      <line x1="{right:.1f}" y1="{profile_top:.1f}" x2="{dim_x - 8:.1f}" y2="{profile_top:.1f}" class="guide"/>
      <line x1="{right:.1f}" y1="{shelf_top:.1f}" x2="{dim_x - 8:.1f}" y2="{shelf_top:.1f}" class="guide"/>

      <line x1="{left:.1f}" y1="{shelf_top + 38:.1f}" x2="{right:.1f}" y2="{shelf_top + 38:.1f}" class="dim"/>
      <text x="{left + side_w / 2:.1f}" y="{shelf_top + 62:.1f}" text-anchor="middle" class="small">Outside X {fmt(side_x)} mm</text>
      <line x1="{left:.1f}" y1="{shelf_top:.1f}" x2="{left:.1f}" y2="{shelf_top + 46:.1f}" class="guide"/>
      <line x1="{right:.1f}" y1="{shelf_top:.1f}" x2="{right:.1f}" y2="{shelf_top + 46:.1f}" class="guide"/>

      <line x1="{content_left:.1f}" y1="{shelf_top + 84:.1f}" x2="{content_right:.1f}" y2="{shelf_top + 84:.1f}" class="dim"/>
      <text x="{content_left + mold_w_px / 2:.1f}" y="{shelf_top + 108:.1f}" text-anchor="middle" class="small">Print X {fmt(mold_x)} mm</text>

      <text x="{left:.1f}" y="372" class="small">Frame glass {fmt(frame_w)} mm wide x {fmt(relief_h + relief_bg_h)} mm high | Fiber displacement {fmt(fiber_h)} mm | Relief background {fmt(relief_bg_h)} mm | Backing {fmt(backing_h)} mm</text>
    </svg>
    """


def render_svg(svg: str) -> None:
    st.markdown(svg, unsafe_allow_html=True)


def weight_summary_frame(c: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(weight_summary_rows(c)).loc[
        lambda df: df["Region"].isin(["Relief fill", "Relief background", "X frame strips", "Y frame strips", "Backing with frame"])
    ][["Region", "Glass (g)"]]


def checklist_frames(c: dict[str, float]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    glass_to_weigh_df = pd.DataFrame(
        [
            {
                "Task": "X frame glass",
                "Count": 2,
                "Size (mm)": f"{fmt(c['fiber_x_length_mm'])} x {fmt(c['fiber_x_width_mm'])}",
                "Each (g)": fmt(c["side_x_g"]),
                "Total (g)": fmt(c["total_side_x_g"]),
            },
            {
                "Task": "Y frame glass",
                "Count": 2,
                "Size (mm)": f"{fmt(c['fiber_y_length_mm'])} x {fmt(c['fiber_y_width_mm'])}",
                "Each (g)": fmt(c["side_y_g"]),
                "Total (g)": fmt(c["total_side_y_g"]),
            },
            {
                "Task": "Backing glass",
                "Count": 1,
                "Size (mm)": f"{fmt(c['side_x_mm'])} x {fmt(c['side_y_mm'])}",
                "Each (g)": fmt(c["backing_g"]),
                "Total (g)": fmt(c["backing_g"]),
            },
            {
                "Task": "Relief background glass",
                "Count": 1,
                "Size (mm)": f"{fmt(c['mold_x_mm'])} x {fmt(c['mold_y_mm'])}",
                "Each (g)": fmt(c["relief_background_g"]),
                "Total (g)": fmt(c["relief_background_g"]),
            },
            {
                "Task": "Relief fill glass",
                "Count": 1,
                "Size (mm)": f"{fmt(c['mold_x_mm'])} x {fmt(c['mold_y_mm'])}",
                "Each (g)": fmt(c["relief_fill_g"]),
                "Total (g)": fmt(c["relief_fill_g"]),
            },
        ]
    )
    fiber_paper_df = pd.DataFrame(
        [
            {
                "Strip": "X frame fiber",
                "Count": int(c["fiber_paper_layers"]) * 2,
                "Size (mm)": f"{fmt(c['fiber_x_length_mm'])} x {fmt(c['fiber_x_width_mm'])}",
                "Thickness (mm)": fmt(c["fiber_paper_thickness_mm"]),
            },
            {
                "Strip": "Y frame fiber",
                "Count": int(c["fiber_paper_layers"]) * 2,
                "Size (mm)": f"{fmt(c['fiber_y_length_mm'])} x {fmt(c['fiber_y_width_mm'])}",
                "Thickness (mm)": fmt(c["fiber_paper_thickness_mm"]),
            },
            {
                "Strip": "X side-wall fiber",
                "Count": 2,
                "Size (mm)": f"{fmt(c['side_wall_fiber_height_mm'])} x {fmt(c['side_wall_fiber_x_length_mm'])}",
                "Thickness (mm)": fmt(c["fiber_paper_thickness_mm"]),
            },
            {
                "Strip": "Y side-wall fiber",
                "Count": 2,
                "Size (mm)": f"{fmt(c['side_wall_fiber_height_mm'])} x {fmt(c['side_wall_fiber_y_length_mm'])}",
                "Thickness (mm)": fmt(c["fiber_paper_thickness_mm"]),
            },
        ]
    )
    setup_df = pd.DataFrame(
        [
            {"Item": "Glass manufacturer", "Value": str(c["glass_manufacturer"])},
            {"Item": "Specific gravity", "Value": f"{fmt(c['glass_density_g_per_cm3'], 2)} g/cm³"},
            {"Item": "Outside footprint", "Value": f"{fmt(c['side_x_mm'])} x {fmt(c['side_y_mm'])} mm"},
            {"Item": "Print field", "Value": f"{fmt(c['mold_x_mm'])} x {fmt(c['mold_y_mm'])} mm"},
            {"Item": "Frame border", "Value": f"{fmt(c['frame_width_x_mm'])} / {fmt(c['frame_width_y_mm'])} mm"},
            {"Item": "Fiber paper", "Value": f"{fmt(c['fiber_paper_thickness_mm'])} mm x {fmt(c['fiber_paper_layers'], 0)} layer(s)"},
            {"Item": "Fiber displacement", "Value": f"{fmt(c['fiber_paper_displacement_mm'])} mm"},
            {"Item": "Relief frame height", "Value": f"{fmt(c['relief_frame_height_mm'])} mm"},
            {"Item": "Relief background layer", "Value": f"{fmt(c['relief_background_layer_mm'])} mm"},
            {"Item": "Frame glass height", "Value": f"{fmt(c['frame_height_mm'])} mm"},
            {"Item": "Backing layer", "Value": f"{fmt(c['backing_layer_mm'])} mm"},
            {"Item": "Full side height", "Value": f"{fmt(c['full_side_height_mm'])} mm"},
            {"Item": "Fabrication stack height", "Value": f"{fmt(c['total_thickness_z_mm'])} mm"},
            {"Item": "Fabrication total", "Value": f"{fmt(c['fabrication_total_g'])} g"},
        ]
    )
    return glass_to_weigh_df, fiber_paper_df, setup_df


def pdf_table(df: pd.DataFrame, widths: list[float] | None = None) -> Table:
    data = [list(df.columns)] + df.astype(str).values.tolist()
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f5f7")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#303241")),
                ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#303241")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("LEADING", (0, 0), (-1, -1), 11),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c9ccd3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def checklist_pdf(inputs: FrameInputs, glass_df: pd.DataFrame, fiber_df: pd.DataFrame, setup_df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.45 * inch,
        leftMargin=0.45 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.fontSize = 18
    title_style.leading = 22
    title_style.spaceAfter = 2
    heading_style = styles["Heading2"]
    heading_style.fontSize = 14
    heading_style.leading = 18
    normal_style = styles["Normal"]
    title_text = escape(inputs.title.strip() or "Untitled")
    story = [
        Paragraph("Fabrication checklist", title_style),
        Paragraph(f"{title_text} | {inputs.job_date}", normal_style),
        Spacer(1, 0.18 * inch),
        Paragraph("Setup dimensions", heading_style),
        pdf_table(setup_df, [2.7 * inch, 2.7 * inch]),
        Spacer(1, 0.2 * inch),
        Paragraph("Glass to weigh", heading_style),
        pdf_table(glass_df, [2.15 * inch, 0.58 * inch, 1.25 * inch, 0.82 * inch, 0.88 * inch]),
        Spacer(1, 0.2 * inch),
        Paragraph("Fiber paper to cut", heading_style),
        pdf_table(fiber_df, [2.1 * inch, 0.6 * inch, 1.65 * inch, 1.05 * inch]),
    ]
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fabrication_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                job_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                max_mold_height_mm REAL,
                fiber_paper_thickness_mm REAL,
                fiber_paper_layers REAL,
                fiber_paper_height_mm REAL,
                mold_x_mm REAL,
                mold_y_mm REAL,
                frame_border_x_mm REAL,
                frame_border_y_mm REAL,
                relief_background_layer_mm REAL,
                backing_layer_mm REAL,
                relief_fill_g REAL,
                relief_fill_volume_cm3 REAL,
                glass_manufacturer TEXT,
                glass_density_g_per_cm3 REAL
            )
            """
        )
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(fabrication_records)").fetchall()
        }
        migrations = {
            "fiber_paper_thickness_mm": "ALTER TABLE fabrication_records ADD COLUMN fiber_paper_thickness_mm REAL",
            "fiber_paper_layers": "ALTER TABLE fabrication_records ADD COLUMN fiber_paper_layers REAL",
            "relief_fill_volume_cm3": "ALTER TABLE fabrication_records ADD COLUMN relief_fill_volume_cm3 REAL",
            "glass_manufacturer": "ALTER TABLE fabrication_records ADD COLUMN glass_manufacturer TEXT",
            "glass_density_g_per_cm3": "ALTER TABLE fabrication_records ADD COLUMN glass_density_g_per_cm3 REAL",
        }
        for column, statement in migrations.items():
            if column not in existing_columns:
                conn.execute(statement)


def save_record(rec: dict[str, float | str]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO fabrication_records
                (title, job_date, created_at, updated_at,
                 max_mold_height_mm, fiber_paper_thickness_mm, fiber_paper_layers, fiber_paper_height_mm,
                 mold_x_mm, mold_y_mm, frame_border_x_mm, frame_border_y_mm,
                 relief_background_layer_mm, backing_layer_mm, relief_fill_g,
                 relief_fill_volume_cm3, glass_manufacturer, glass_density_g_per_cm3)
            VALUES
                (:title, :job_date, :created_at, :updated_at,
                 :max_mold_height_mm, :fiber_paper_thickness_mm, :fiber_paper_layers, :fiber_paper_height_mm,
                 :mold_x_mm, :mold_y_mm, :frame_border_x_mm, :frame_border_y_mm,
                 :relief_background_layer_mm, :backing_layer_mm, :relief_fill_g,
                 :relief_fill_volume_cm3, :glass_manufacturer, :glass_density_g_per_cm3)
            """,
            rec,
        )
        return int(cur.lastrowid)


def update_record(record_id: int, rec: dict[str, float | str]) -> None:
    rec["id"] = record_id
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE fabrication_records SET
                title=:title,
                job_date=:job_date,
                updated_at=:updated_at,
                max_mold_height_mm=:max_mold_height_mm,
                fiber_paper_thickness_mm=:fiber_paper_thickness_mm,
                fiber_paper_layers=:fiber_paper_layers,
                fiber_paper_height_mm=:fiber_paper_height_mm,
                mold_x_mm=:mold_x_mm,
                mold_y_mm=:mold_y_mm,
                frame_border_x_mm=:frame_border_x_mm,
                frame_border_y_mm=:frame_border_y_mm,
                relief_background_layer_mm=:relief_background_layer_mm,
                backing_layer_mm=:backing_layer_mm,
                relief_fill_g=:relief_fill_g,
                relief_fill_volume_cm3=:relief_fill_volume_cm3,
                glass_manufacturer=:glass_manufacturer,
                glass_density_g_per_cm3=:glass_density_g_per_cm3
            WHERE id=:id
            """,
            rec,
        )


def delete_record(record_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM fabrication_records WHERE id=?", (record_id,))


def list_records() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, title, job_date, created_at, updated_at FROM fabrication_records ORDER BY updated_at DESC"
        ).fetchall()


def load_record(record_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM fabrication_records WHERE id=?", (record_id,)).fetchone()


def format_record_date(value: str | None) -> str:
    if not value:
        return "no date"
    try:
        return date.fromisoformat(value).strftime("%-m/%-d/%y")
    except ValueError:
        return value


def format_record_timestamp(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%-m/%-d/%y %-I:%M %p")
    except ValueError:
        return value


st.title(t("page.print_frame.title", "Print Frame Fabrication"))
st.caption(
    t(
        "page.print_frame.caption",
        "Start with a known 3D print, choose the intended frame border, and calculate fabrication glass and fiber paper needs.",
    )
)

FIELD_DEFAULTS = {
    "pf_title": "Mars 2580_A01 #1",
    "pf_job_date": date(2023, 8, 1),
    "pf_max_mold_height_mm": 13.0,
    "pf_fiber_paper_thickness_mm": 3.0,
    "pf_fiber_paper_layers": 1,
    "pf_fiber_paper_height_mm": 3.0,
    "pf_mold_x_mm": 150.0,
    "pf_mold_y_mm": 120.0,
    "pf_frame_border_x_mm": DEFAULT_FRAME_BORDER_MM,
    "pf_frame_border_y_mm": DEFAULT_FRAME_BORDER_MM,
    "pf_relief_background_layer_mm": 2.0,
    "pf_backing_layer_mm": 2.0,
    "pf_relief_fill_g": 48.0,
    "pf_relief_fill_volume_cm3": 48.0 / DEFAULT_GLASS_DENSITY_G_PER_CM3,
    "pf_glass_manufacturer": DEFAULT_GLASS_MANUFACTURER,
    "pf_glass_density_g_per_cm3": DEFAULT_GLASS_DENSITY_G_PER_CM3,
}
for field_key, default_value in FIELD_DEFAULTS.items():
    st.session_state.setdefault(field_key, default_value)
st.session_state.setdefault("pf_loaded_id", None)

init_db()


def record_payload() -> dict[str, float | str]:
    now = datetime.now().isoformat(timespec="seconds")
    title = str(st.session_state.get("pf_title", "")).strip() or "Untitled fabrication"
    job_date_value = st.session_state.get("pf_job_date", date.today())
    if isinstance(job_date_value, date):
        job_date_text = job_date_value.isoformat()
    else:
        job_date_text = str(job_date_value)
    return {
        "title": title,
        "job_date": job_date_text,
        "created_at": now,
        "updated_at": now,
        "max_mold_height_mm": float(st.session_state.get("pf_max_mold_height_mm", 0.0) or 0.0),
        "fiber_paper_thickness_mm": float(st.session_state.get("pf_fiber_paper_thickness_mm", 0.0) or 0.0),
        "fiber_paper_layers": float(st.session_state.get("pf_fiber_paper_layers", 1) or 1),
        "fiber_paper_height_mm": float(st.session_state.get("pf_fiber_paper_thickness_mm", 0.0) or 0.0)
        * float(st.session_state.get("pf_fiber_paper_layers", 1) or 1),
        "mold_x_mm": float(st.session_state.get("pf_mold_x_mm", 0.0) or 0.0),
        "mold_y_mm": float(st.session_state.get("pf_mold_y_mm", 0.0) or 0.0),
        "frame_border_x_mm": float(st.session_state.get("pf_frame_border_x_mm", 0.0) or 0.0),
        "frame_border_y_mm": float(st.session_state.get("pf_frame_border_y_mm", 0.0) or 0.0),
        "relief_background_layer_mm": float(st.session_state.get("pf_relief_background_layer_mm", 0.0) or 0.0),
        "backing_layer_mm": float(st.session_state.get("pf_backing_layer_mm", 0.0) or 0.0),
        "relief_fill_g": float(st.session_state.get("pf_relief_fill_g", 0.0) or 0.0),
        "relief_fill_volume_cm3": float(st.session_state.get("pf_relief_fill_volume_cm3", 0.0) or 0.0),
        "glass_manufacturer": str(st.session_state.get("pf_glass_manufacturer", DEFAULT_GLASS_MANUFACTURER)),
        "glass_density_g_per_cm3": float(st.session_state.get("pf_glass_density_g_per_cm3", DEFAULT_GLASS_DENSITY_G_PER_CM3) or DEFAULT_GLASS_DENSITY_G_PER_CM3),
    }


def load_record_into_state(row: sqlite3.Row | None) -> None:
    if row is None:
        return
    for field in RECORD_FIELDS:
        value = row[field]
        if value is None:
            continue
        if field == "job_date":
            try:
                value = date.fromisoformat(str(value))
            except ValueError:
                value = FIELD_DEFAULTS["pf_job_date"]
        elif field == "fiber_paper_layers":
            value = int(float(value))
        elif field not in {"title", "glass_manufacturer"}:
            value = float(value)
        st.session_state[f"pf_{field}"] = value
    if not row["fiber_paper_thickness_mm"]:
        st.session_state["pf_fiber_paper_thickness_mm"] = float(
            row["fiber_paper_height_mm"] or FIELD_DEFAULTS["pf_fiber_paper_thickness_mm"]
        )
        st.session_state["pf_fiber_paper_layers"] = 1
    st.session_state["pf_loaded_id"] = int(row["id"])


def reset_record_state() -> None:
    for field_key, default_value in FIELD_DEFAULTS.items():
        st.session_state[field_key] = default_value
    st.session_state["pf_loaded_id"] = None

with st.expander("Import from settings.txt", expanded=False):
    import_left, import_right = st.columns([1, 1.4])
    with import_left:
        uploaded_settings = st.file_uploader("Drop a .txt export", type=["txt"], key="pf_settings_upload")
    with import_right:
        pasted_settings = st.text_area("...or paste export text", height=120, key="pf_settings_paste")
    if st.button("Parse & pre-fill", width="stretch"):
        raw_settings = ""
        if uploaded_settings is not None:
            raw_settings = uploaded_settings.read().decode("utf-8", errors="replace")
        elif pasted_settings.strip():
            raw_settings = pasted_settings.strip()
        if raw_settings:
            imported = parse_settings_txt(raw_settings, selected_density())
            filled = apply_imported_settings(imported)
            if filled:
                st.success("Pre-filled: " + ", ".join(filled))
            else:
                st.warning("No recognized fields found in that export.")
        else:
            st.warning("Nothing to parse.")

with st.expander("Fabrication records", expanded=False):
    loaded_id = st.session_state.get("pf_loaded_id")
    save_label = "Update current record" if loaded_id else "Save current setup"
    action_cols = st.columns([1.2, 1])
    with action_cols[0]:
        if st.button(save_label, type="primary", width="stretch"):
            rec = record_payload()
            if loaded_id:
                update_record(int(loaded_id), rec)
                st.success(f"Updated record: {rec['title']}")
            else:
                st.session_state["pf_loaded_id"] = save_record(rec)
                st.success(f"Saved record: {rec['title']}")
    with action_cols[1]:
        if st.button("+ New setup", width="stretch"):
            reset_record_state()
            st.rerun()

    records = list_records()
    if not records:
        st.info("No saved fabrication records yet.")
    else:
        st.divider()
        for row in records:
            record_cols = st.columns([4, 1, 1])
            with record_cols[0]:
                active_marker = " (loaded)" if st.session_state.get("pf_loaded_id") == row["id"] else ""
                st.markdown(f"**{row['title']}**{active_marker} - {format_record_date(row['job_date'])}")
                st.caption(f"Updated {format_record_timestamp(row['updated_at'])}")
            with record_cols[1]:
                if st.button("Load", key=f"pf_load_{row['id']}", width="stretch"):
                    load_record_into_state(load_record(row["id"]))
                    st.rerun()
            with record_cols[2]:
                if st.button("Delete", key=f"pf_delete_{row['id']}", width="stretch"):
                    delete_record(int(row["id"]))
                    if st.session_state.get("pf_loaded_id") == row["id"]:
                        reset_record_state()
                    st.rerun()

st.markdown("### Fabrication Setup")
meta_col, print_col, frame_col, consumables_col = st.columns([1.05, 1.15, 1, 1])
with meta_col:
    title = st.text_input("Title", key="pf_title")
    job_date = st.date_input("Date", key="pf_job_date")
    st.markdown("**Glass source**")
    glass_manufacturer = st.selectbox(
        "Glass manufacturer",
        list(GLASS_MANUFACTURERS.keys()),
        key="pf_glass_manufacturer",
        on_change=update_density_from_manufacturer,
    )
    glass_density_g_per_cm3 = st.number_input(
        "Specific gravity (g/cm³)",
        min_value=0.01,
        step=0.01,
        format="%.2f",
        key="pf_glass_density_g_per_cm3",
        on_change=update_custom_density,
    )
with print_col:
    st.markdown("**3D print dimensions**")
    mold_x_mm = st.number_input(
        "Print X length (mm)",
        min_value=0.0,
        step=1.0,
        key="pf_mold_x_mm",
    )
    mold_y_mm = st.number_input(
        "Print Y length (mm)",
        min_value=0.0,
        step=1.0,
        key="pf_mold_y_mm",
    )
    max_mold_height_mm = st.number_input(
        "Print Z length (height) (mm)",
        min_value=0.0,
        step=0.5,
        key="pf_max_mold_height_mm",
    )
    relief_fill_g = st.number_input(
        "Relief fill glass (g)",
        min_value=0.0,
        step=1.0,
        key="pf_relief_fill_g",
        on_change=sync_relief_fill_volume_from_weight,
    )
with frame_col:
    st.markdown("**Intended frame**")
    frame_border_x_mm = st.number_input(
        "Frame border X (mm)",
        min_value=0.0,
        step=1.0,
        key="pf_frame_border_x_mm",
    )
    frame_border_y_mm = st.number_input(
        "Frame border Y (mm)",
        min_value=0.0,
        step=1.0,
        key="pf_frame_border_y_mm",
    )
with consumables_col:
    st.markdown("**Fabrication layers**")
    fiber_paper_thickness_mm = st.number_input(
        "Fiber paper thickness (mm)",
        min_value=0.5,
        max_value=5.0,
        step=0.5,
        key="pf_fiber_paper_thickness_mm",
    )
    fiber_paper_layers = st.selectbox(
        "Fiber paper strips",
        [1, 2],
        key="pf_fiber_paper_layers",
        format_func=lambda value: "Single layer" if value == 1 else "Double layer",
    )
    fiber_paper_height_mm = fiber_paper_thickness_mm * fiber_paper_layers
    st.caption(
        f"Glass displacement: {fmt(fiber_paper_height_mm)} mm. "
        f"Fabrication stack uses {fmt(fiber_paper_thickness_mm)} mm."
    )
    relief_background_layer_mm = st.number_input(
        "Relief background layer (mm)",
        min_value=0.0,
        step=0.5,
        key="pf_relief_background_layer_mm",
    )
    backing_layer_mm = st.number_input(
        "Backing layer (mm)",
        min_value=0.0,
        step=0.5,
        key="pf_backing_layer_mm",
    )

inputs = FrameInputs(
    title=title,
    job_date=job_date,
    glass_manufacturer=glass_manufacturer,
    glass_density_g_per_cm3=glass_density_g_per_cm3,
    max_mold_height_mm=max_mold_height_mm,
    fiber_paper_thickness_mm=fiber_paper_thickness_mm,
    fiber_paper_layers=fiber_paper_layers,
    fiber_paper_height_mm=fiber_paper_height_mm,
    mold_x_mm=mold_x_mm,
    mold_y_mm=mold_y_mm,
    frame_border_x_mm=frame_border_x_mm,
    frame_border_y_mm=frame_border_y_mm,
    relief_background_layer_mm=relief_background_layer_mm,
    backing_layer_mm=backing_layer_mm,
    relief_fill_g=relief_fill_g,
)
calc = calc_frame(inputs)

if fiber_paper_height_mm > max_mold_height_mm:
    st.warning("Fiber paper glass displacement is greater than print Z length, so relief frame height is clamped to 0 mm.")

tab_worksheet, tab_diagram, tab_export = st.tabs(["Worksheet", "Diagrams", "Download"])

with tab_worksheet:
    left, right = st.columns([1.35, 1])
    with left:
        rows = worksheet_rows(calc)
        df = pd.DataFrame(rows)
        for section, band_class in [
            ("Glass", "band-orange"),
            ("Frame Height", "band-purple"),
            ("Side X", "band-blue"),
            ("Side Y", "band-green"),
            ("Frame", "band-purple"),
            ("Relief Fill", "band-pink"),
            ("Backing", "band-orange"),
        ]:
            st.markdown(f'<div class="section-band {band_class}">{section}</div>', unsafe_allow_html=True)
            section_df = df[df["Section"] == section][["Item", "Value", "Unit", "Formula"]]
            st.markdown(
                section_df.to_html(index=False, classes="worksheet-table", border=0),
                unsafe_allow_html=True,
            )
    with right:
        st.subheader("Fabrication checklist")
        glass_to_weigh_df, fiber_paper_df, setup_df = checklist_frames(calc)
        st.markdown("**Setup dimensions**")
        st.markdown(setup_df.to_html(index=False, classes="checklist-table", border=0), unsafe_allow_html=True)
        st.markdown("**Glass to weigh**")
        st.markdown(glass_to_weigh_df.to_html(index=False, classes="checklist-table", border=0), unsafe_allow_html=True)
        st.markdown("**Fiber paper to cut**")
        st.markdown(fiber_paper_df.to_html(index=False, classes="checklist-table", border=0), unsafe_allow_html=True)

with tab_diagram:
    st.subheader("Pre-visualization")
    top_col, weight_col = st.columns([1.1, 1])
    with top_col:
        render_svg(top_view_svg(calc))
        render_svg(profile_view_svg(calc))
    with weight_col:
        st.markdown("#### Weight Summary")
        st.caption(f"{calc['glass_manufacturer']} specific gravity: {fmt(calc['glass_density_g_per_cm3'], 2)} g/cm³")
        weight_metric_cols = st.columns(2)
        weight_metric_cols[0].metric("Frame + layers", f"{fmt(calc['total_frame_g'] + calc['relief_background_g'] + calc['backing_g'])} g")
        weight_metric_cols[1].metric("Fabrication total", f"{fmt(calc['fabrication_total_g'])} g")
        chart_df = weight_summary_frame(calc)
        st.dataframe(
            chart_df.style.bar(subset=["Glass (g)"], color="#8ee6ee").format({"Glass (g)": "{:.1f}"}),
            hide_index=True,
            width="stretch",
            height=210,
        )

    st.subheader("Weight data")
    st.dataframe(
        pd.DataFrame(weight_summary_rows(calc)).style.format(
            {
                "Area (cm²)": "{:.1f}",
                "Height (mm)": "{:.1f}",
                "Glass (g)": "{:.1f}",
            }
        ),
        hide_index=True,
        width="stretch",
    )

with tab_export:
    glass_to_weigh_df, fiber_paper_df, setup_df = checklist_frames(calc)
    checklist_pdf_file = checklist_pdf(inputs, glass_to_weigh_df, fiber_paper_df, setup_df)
    st.subheader("Fabrication checklist")
    st.download_button(
        "Download printable checklist PDF",
        data=checklist_pdf_file,
        file_name=f"{inputs.title.replace(' ', '_')}_fabrication_checklist.pdf",
        mime="application/pdf",
        width="stretch",
    )
    st.markdown("**Setup dimensions**")
    st.markdown(setup_df.to_html(index=False, classes="checklist-table", border=0), unsafe_allow_html=True)
    st.markdown("**Glass to weigh**")
    st.markdown(glass_to_weigh_df.to_html(index=False, classes="checklist-table", border=0), unsafe_allow_html=True)
    st.markdown("**Fiber paper to cut**")
    st.markdown(fiber_paper_df.to_html(index=False, classes="checklist-table", border=0), unsafe_allow_html=True)
