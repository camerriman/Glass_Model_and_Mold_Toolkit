"""
5_Mold_Worksheet.py
Mold Calculator & Record Keeper
- Parses settings.txt from the Cameo Mold Generator (App 1)
- Live worksheet: 3D Print → Mold Geometry → tabbed mold type
- Saves / loads worksheet setup files locally
"""

import html
import json
import re
import io
from datetime import date
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageFont
from i18n import format_date, render_app_sidebar, t

# ─────────────────────────────────────────
# Config
# ─────────────────────────────────────────
st.set_page_config(page_title=t("worksheet.title", "Cameo Mold Worksheet"), layout="wide")
render_app_sidebar()
st.title(t("worksheet.title", "Cameo Mold Worksheet"))
render_html_frame = getattr(st, "iframe", components.html)
st.caption(
    t(
        "worksheet.caption",
        "Pre-fill from a settings.txt or enter values manually. Select the mold workflow to see its calculations.",
    )
)
st.markdown(
    """
    <style>
    [data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-size: clamp(1.25rem, 1.9vw, 1.75rem);
        line-height: 1.15;
        overflow-wrap: anywhere;
        white-space: normal;
    }
    [data-testid="stMetric"] [data-testid="stMetricLabel"] {
        font-size: 0.86rem;
        line-height: 1.2;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────
# Settings.txt parser
# ─────────────────────────────────────────
def parse_settings_txt(text: str) -> dict:
    out = {}
    patterns = {
        "width_mm":    r"Target width \(mm\):\s*([\d.]+)",
        "base_mm":     r"Base backing thickness \(mm\):\s*([\d.]+)",
        "stl_volume":  r"Total volume \(cm\^3\):\s*([\d.,]+)",
        "output_size": r"Output size \(mm\):\s*([\d.]+)\s*x\s*([\d.]+)\s*x\s*([\d.]+)",
        "image_name":  r"Image:\s*(.+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            if key == "output_size":
                out["width_mm"] = float(m.group(1))
                out["depth_mm"] = float(m.group(2))
                out["max_z_mm"] = float(m.group(3))
            elif key == "stl_volume":
                out[key] = float(m.group(1).replace(",", ""))
            elif key == "image_name":
                out[key] = m.group(1).strip()
            else:
                out[key] = float(m.group(1))
    if "max_z_mm" in out and "base_mm" in out:
        out["height_mm"] = round(out["max_z_mm"] - out["base_mm"], 3)
    return out

# ─────────────────────────────────────────
# Calculation engine — separated by concern
# ─────────────────────────────────────────
def calc_print(w, d, zb, za, stl_vol):
    """3D print derived values."""
    base_vol    = round((w * d * zb) / 1000, 1)
    max_z       = round(zb + za, 2)
    art_space   = round((w * d * za) / 1000, 1)
    actual_art  = round(stl_vol - base_vol, 1)
    vol_to_max  = round(art_space - actual_art, 1)
    return {
        "base_volume":    base_vol,
        "max_z":          max_z,
        "art_space_vol":  art_space,
        "actual_art_vol": actual_art,
        "vol_to_max_z":   vol_to_max,
    }

def calc_geometry(w, d, wall, box_h, stl_vol):
    """Shared mold box dimensions.
    Gap surrounds print on 5 sides: W + 2×gap, D + 2×gap.
    Mold box free volume is separate from duplicate material volume.
    """
    box_w      = w + 2 * wall
    box_d      = d + 2 * wall
    box_vol    = round((box_w * box_d * box_h) / 1000, 1)
    model_vol  = round(stl_vol, 1)
    mold_vol   = round(box_vol - model_vol, 1)
    return {
        "box_w":        box_w,
        "box_d":        box_d,
        "box_volume":   box_vol,
        "model_volume": model_vol,
        "mold_vol":     mold_vol,
    }

def calc_duplicate_volume(w, d, wall, model_vol, max_z, adjust_z):
    """Duplicate volume plus side gap and optional base Z extension."""
    box_w = w + 2 * wall
    box_d = d + 2 * wall
    footprint = w * d
    box_footprint = box_w * box_d
    side_gap_vol = max(0.0, round(((box_footprint - footprint) * max_z) / 1000, 1))
    base_z_vol = round((box_footprint * adjust_z) / 1000, 1)
    total_vol = round(model_vol + side_gap_vol + base_z_vol, 1)
    return {
        "duplicate_vol": total_vol,
        "side_gap_vol": side_gap_vol,
        "base_z_vol": base_z_vol,
    }


def calc_alginate(w, d, wall, model_vol, max_z, alg_zi, alg_ratio):
    """Alginate duplicate: STL/model volume plus side gap and optional base Z."""
    duplicate = calc_duplicate_volume(w, d, wall, model_vol, max_z, alg_zi)
    total_vol  = duplicate["duplicate_vol"]
    water_g    = round(total_vol, 1)
    alginate_g = round(water_g / alg_ratio, 1) if alg_ratio > 0 else 0.0
    thickness  = round(max_z + alg_zi, 1)
    return {
        "alg_mold_vol":    total_vol,
        "alg_side_gap_vol": duplicate["side_gap_vol"],
        "alg_base_z_vol":   duplicate["base_z_vol"],
        "alg_water_g":     water_g,
        "alg_alginate_g":  alginate_g,
        "alg_thickness":   thickness,
        "alg_total_thick": thickness,
    }

def calc_silicone(w, d, wall, model_volume, max_z, si_zi, si_ratio):
    """Silicone duplicate: STL/model volume plus side gap and optional base Z.
    si_ratio splits total weight as part A : part B.
    """
    duplicate = calc_duplicate_volume(w, d, wall, model_volume, max_z, si_zi)
    mold_vol  = duplicate["duplicate_vol"]
    si_g      = round(mold_vol * 1.12, 1)
    part_a    = round(si_g * si_ratio / (si_ratio + 1), 1) if si_ratio > 0 else round(si_g / 2, 1)
    part_b    = round(si_g - part_a, 1)
    return {
        "si_zi_vol":      duplicate["base_z_vol"],
        "si_side_gap_vol": duplicate["side_gap_vol"],
        "mold_volume_si": mold_vol,
        "silicone_g":     si_g,
        "part_a":         part_a,
        "part_b":         part_b,
        "si_total_thick": round(max_z + si_zi, 1),
    }

def calc_investment(w, d, wall, model_vol, max_z, inv_zi):
    """Investment duplicate: STL/model volume plus side gap and optional base Z.
    R&R uses the same duplicate volume with its own material multiplier.
    """
    duplicate = calc_duplicate_volume(w, d, wall, model_vol, max_z, inv_zi)
    inv_vol = duplicate["duplicate_vol"]
    dry_inv = round(inv_vol * 1.25, 1)
    rr910_mixed = round(inv_vol * 1.88, 1)
    rr910_powder = round(rr910_mixed * (100 / 128), 1)
    rr910_water = round(rr910_powder * 0.28, 1)
    return {
        "inv_vol":         inv_vol,
        "inv_side_gap_vol": duplicate["side_gap_vol"],
        "inv_base_z_vol":   duplicate["base_z_vol"],
        "inv_total_thick": round(max_z + inv_zi, 1),
        "dry_investment":  dry_inv,
        "plaster_g":       round(dry_inv / 2, 1),
        "silica_g":        round(dry_inv / 2, 1),
        "inv_water_g":     round(dry_inv / 1.75, 1),
        "rr910_total_g":   rr910_mixed,
        "rr910_g":         rr910_powder,
        "rr910_water_g":   rr910_water,
    }

# ─────────────────────────────────────────
# Session state defaults
# ─────────────────────────────────────────
FIELD_DEFAULTS = dict(
    title="", job_date=date.today(), mold_type="Alginate + Investment",
    width_mm=0.0, depth_mm=0.0, base_mm=0.0, height_mm=0.0, stl_volume=0.0,
    wall_mm=0.0, alg_si_gap_mm=0.0, inv_gap_mm=0.0,
    alg_adjust_zi=0.0, alg_mix_ratio=1.0,
    si_adjust_zi=0.0,  si_mix_ratio=1.0,
    inv_adjust_zi=0.0,
    notes="",
)
had_alg_si_gap = "ws_alg_si_gap_mm" in st.session_state
had_inv_gap = "ws_inv_gap_mm" in st.session_state
legacy_session_gap = st.session_state.get("ws_wall_mm", 0.0)
for k, v in FIELD_DEFAULTS.items():
    st.session_state.setdefault(f"ws_{k}", v)
if not had_alg_si_gap:
    st.session_state["ws_alg_si_gap_mm"] = legacy_session_gap
if not had_inv_gap:
    st.session_state["ws_inv_gap_mm"] = legacy_session_gap


FLOAT_FIELDS = {k for k, v in FIELD_DEFAULTS.items() if isinstance(v, float)}

def _serialize_field_value(value):
    if isinstance(value, date):
        return value.isoformat()
    return value


def _current_worksheet_payload() -> dict:
    return {
        "schema": "glass-toolkit.mold-worksheet",
        "version": 1,
        "values": {
            key: _serialize_field_value(st.session_state.get(f"ws_{key}", default))
            for key, default in FIELD_DEFAULTS.items()
        },
    }


def _worksheet_json_bytes() -> bytes:
    return json.dumps(_current_worksheet_payload(), indent=2, sort_keys=True).encode("utf-8")


def _load_into_state(payload):
    values = payload.get("values", payload) if isinstance(payload, dict) else {}
    for k in FIELD_DEFAULTS:
        if k in values and values[k] is not None:
            val = values[k]
            if k == "job_date" and isinstance(val, str):
                try:
                    val = date.fromisoformat(val)
                except ValueError:
                    val = date.today()
            elif k in FLOAT_FIELDS:
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    val = FIELD_DEFAULTS[k]
            st.session_state[f"ws_{k}"] = val
    legacy_gap = float(values.get("wall_mm") or 0.0)
    if values.get("alg_si_gap_mm") is None:
        st.session_state["ws_alg_si_gap_mm"] = legacy_gap
    if values.get("inv_gap_mm") is None:
        st.session_state["ws_inv_gap_mm"] = legacy_gap
    if st.session_state["ws_mold_type"] == "Alginate":
        st.session_state["ws_mold_type"] = "Alginate + Investment"
    elif st.session_state["ws_mold_type"] == "Silicone":
        st.session_state["ws_mold_type"] = "Silicone + Investment"
    if st.session_state["ws_mold_type"] == "Alginate + Investment":
        st.session_state["ws_si_adjust_zi"] = FIELD_DEFAULTS["si_adjust_zi"]
        st.session_state["ws_si_mix_ratio"] = FIELD_DEFAULTS["si_mix_ratio"]
    elif st.session_state["ws_mold_type"] == "Silicone + Investment":
        st.session_state["ws_alg_adjust_zi"] = FIELD_DEFAULTS["alg_adjust_zi"]
        st.session_state["ws_alg_mix_ratio"] = FIELD_DEFAULTS["alg_mix_ratio"]


def _reset_state():
    for k, v in FIELD_DEFAULTS.items():
        st.session_state[f"ws_{k}"] = v


def mold_type_label(value: str) -> str:
    labels = {
        "Alginate + Investment": t("worksheet.mold.alginate_investment", "Alginate + Investment"),
        "Silicone": t("worksheet.mold.silicone_investment", "Silicone + Investment"),
        "Silicone + Investment": t("worksheet.mold.silicone_investment", "Silicone + Investment"),
    }
    return labels.get(value, value)


# ─────────────────────────────────────────
# UI card helper
# ─────────────────────────────────────────
def card(title: str, rows: list,
         bg: str, border: str, label_color: str, value_color: str):
    trs = "".join(
        f'<tr>'
        f'<td style="padding:6px 0;color:{label_color};font-size:0.9rem;width:60%">{lbl}</td>'
        f'<td style="padding:6px 0;text-align:right;font-size:1rem;font-weight:700;'
        f'color:{value_color};white-space:nowrap">{val}</td>'
        f'</tr>'
        for lbl, val in rows
    )
    st.markdown(
        f'<div style="background:{bg};border-left:4px solid {border};'
        f'border-radius:0 8px 8px 0;padding:14px 18px;margin:8px 0 16px 0">'
        f'<div style="font-size:0.75rem;font-weight:700;color:{border};'
        f'letter-spacing:.06em;margin-bottom:8px">{title}</div>'
        f'<table style="width:100%;border-collapse:collapse">{trs}</table>'
        f'</div>',
        unsafe_allow_html=True,
    )


def build_print_export(
    title: str,
    job_date,
    sections: list[tuple[str, list[tuple[str, str]]]],
    header_rows: list[tuple[str, str, str, str]] | None = None,
) -> str:
    """Create a compact browser-printable HTML worksheet."""
    safe_title = html.escape(title.strip() or t("worksheet.title", "Cameo Mold Worksheet"))
    if hasattr(job_date, "isoformat"):
        safe_date = html.escape(format_date(job_date.isoformat()))
    else:
        safe_date = html.escape(format_date(str(job_date)))
    header_html = ""
    if header_rows:
        header_body = "".join(
            "<tr>"
            f"<td><strong>{html.escape(left_label)}</strong><br>{html.escape(left_value)}</td>"
            f"<td><strong>{html.escape(right_label)}</strong><br>{html.escape(right_value)}</td>"
            "</tr>"
            for left_label, left_value, right_label, right_value in header_rows
        )
        header_html = f'<section class="batch-meta"><table>{header_body}</table></section>'
    section_html = []
    for section_title, rows in sections:
        body = "".join(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{html.escape(value)}</td>"
            "</tr>"
            for label, value in rows
        )
        section_html.append(
            "<section>"
            f"<h2>{html.escape(section_title)}</h2>"
            f"<table>{body}</table>"
            "</section>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{safe_title} - Cameo Mold Worksheet</title>
<style>
  @page {{
    size: letter portrait;
    margin: 0.42in;
  }}
  body {{
    color: #1f2937;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 12px;
    line-height: 1.2;
    margin: 18px;
  }}
  header {{
    border-bottom: 2px solid #111827;
    margin-bottom: 12px;
    padding-bottom: 8px;
  }}
  h1 {{
    font-size: 22px;
    line-height: 1.05;
    margin: 0 0 3px;
  }}
  .date {{
    color: #4b5563;
    font-size: 11px;
  }}
  main {{
    display: grid;
    gap: 10px 16px;
    grid-template-columns: 1fr 1fr;
  }}
  section {{
    break-inside: avoid;
    margin: 0;
  }}
  h2 {{
    border-bottom: 1px solid #d1d5db;
    font-size: 11px;
    letter-spacing: .04em;
    line-height: 1.15;
    margin: 0 0 4px;
    padding-bottom: 3px;
    text-transform: uppercase;
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
  }}
  .batch-meta {{
    border: 1px solid #d1d5db;
    margin-bottom: 10px;
    padding: 8px 10px;
  }}
  .batch-meta td {{
    border-bottom: 1px solid #e5e7eb;
    font-size: 10px;
    line-height: 1.25;
    padding: 4px 10px 4px 0;
    text-align: left;
    width: 50%;
  }}
  .batch-meta tr:last-child td {{
    border-bottom: 0;
  }}
  td {{
    border-bottom: 1px solid #e5e7eb;
    padding: 4px 0;
    vertical-align: top;
  }}
  section:not(.batch-meta) td:last-child {{
    font-weight: 700;
    text-align: right;
    white-space: nowrap;
  }}
  .actions {{
    margin-bottom: 12px;
  }}
  button {{
    background: #111827;
    border: 0;
    border-radius: 6px;
    color: white;
    cursor: pointer;
    font: inherit;
    padding: 8px 14px;
  }}
  @media print {{
    body {{
      font-size: 10.5px;
      margin: 0;
    }}
    .actions {{ display: none; }}
    header {{
      margin-bottom: 9px;
      padding-bottom: 6px;
    }}
    h1 {{ font-size: 18px; }}
    h2 {{ font-size: 9.5px; }}
    td {{ padding: 2.8px 0; }}
  }}
</style>
</head>
<body>
<div class="actions"><button onclick="window.print()">Print</button></div>
<header>
  <h1>{safe_title}</h1>
  <div class="date">{safe_date}</div>
</header>
{header_html}
<main>
{''.join(section_html)}
</main>
</body>
</html>
"""


def build_batch_sheet_pdf(
    title: str,
    job_date,
    sections: list[tuple[str, list[tuple[str, str]]]],
    header_rows: list[tuple[str, str, str, str]] | None = None,
) -> bytes:
    page_w, page_h = 1700, 2200
    margin = 68
    card_gap = 22
    white = (255, 255, 255)
    grid = (205, 213, 223)

    page = Image.new("RGB", (page_w, page_h), white)
    draw = ImageDraw.Draw(page)
    header_title_font = _batch_sheet_font(24, bold=True)
    header_label_font = _batch_sheet_font(11, bold=True)
    header_value_font = _batch_sheet_font(13)
    title_font = _batch_sheet_font(14, bold=True)
    body_font = _batch_sheet_font(16)
    value_font = _batch_sheet_font(16, bold=True)
    card_w = page_w - (margin * 2)
    table_pad_x = 44
    header_h = 168 if header_rows else 0
    header_gap = card_gap if header_rows else 0
    title_h = 36
    card_pad_top = 24
    card_pad_bottom = 24
    total_rows = max(1, sum(len(rows) for _, rows in sections))
    row_space = page_h - (margin * 2) - header_h - header_gap - (card_gap * max(0, len(sections) - 1)) - (
        (title_h + card_pad_top + card_pad_bottom) * len(sections)
    )
    row_h = max(30, min(46, row_space // total_rows))

    def rgb(hex_value: str) -> tuple[int, int, int]:
        hex_value = hex_value.lstrip("#")
        return tuple(int(hex_value[i : i + 2], 16) for i in (0, 2, 4))

    def style_for(section_title: str) -> dict[str, tuple[int, int, int]]:
        upper = section_title.upper()
        if "R&R" in upper or "GLASS-CAST" in upper:
            return {"bg": rgb("#faf5ff"), "accent": rgb("#7c3aed"), "label": rgb("#6b21a8"), "value": rgb("#581c87")}
        if "DRY" in upper or "PLASTER" in upper or "SILICA" in upper or "INVEST" in upper:
            return {"bg": rgb("#fffbeb"), "accent": rgb("#d97706"), "label": rgb("#92400e"), "value": rgb("#78350f")}
        if "SIRAYA" in upper or "DEFIANT" in upper or "SILICONE" in upper:
            return {"bg": rgb("#eff6ff"), "accent": rgb("#2563eb"), "label": rgb("#1e40af"), "value": rgb("#1e3a8a")}
        if "ACCU" in upper or "ALGINATE" in upper:
            return {"bg": rgb("#f0fdf4"), "accent": rgb("#16a34a"), "label": rgb("#166534"), "value": rgb("#14532d")}
        return {"bg": rgb("#f8fafc"), "accent": rgb("#64748b"), "label": rgb("#475569"), "value": rgb("#0f172a")}

    def draw_fitted_text(x: int, y: int, text: str, fill, font, max_w: int, min_size: int = 18, bold: bool = False) -> None:
        fit_font = font
        size = getattr(font, "size", min_size)
        while size > min_size and _font_width(draw, text, fit_font) > max_w:
            size -= 1
            fit_font = _batch_sheet_font(size, bold=bold)
        draw.text((x, y), text, fill=fill, font=fit_font)

    y = margin
    if header_rows:
        safe_title = title.strip() or t("worksheet.title", "Cameo Mold Worksheet")
        date_text = format_date(job_date.isoformat() if hasattr(job_date, "isoformat") else str(job_date))
        header_bg = rgb("#f8fafc")
        header_border = rgb("#64748b")
        header_text = rgb("#0f172a")
        header_muted = rgb("#475569")
        draw.rounded_rectangle((margin, y, margin + card_w, y + header_h), radius=8, fill=header_bg)
        draw.rectangle((margin, y, margin + 6, y + header_h), fill=header_border)
        header_x = margin + table_pad_x
        header_w = card_w - (table_pad_x * 2)
        draw_fitted_text(header_x, y + 22, safe_title, header_text, header_title_font, header_w - 180, min_size=15, bold=True)
        date_w = _font_width(draw, date_text, header_value_font)
        draw.text((margin + card_w - table_pad_x - date_w, y + 28), date_text, fill=header_muted, font=header_value_font)

        meta_y = y + 66
        meta_row_h = 30
        col_gap = 34
        col_w = (header_w - col_gap) // 2
        for idx, (left_label, left_value, right_label, right_value) in enumerate(header_rows):
            row_y = meta_y + (idx * meta_row_h)
            for col_x, label, value in (
                (header_x, left_label, left_value),
                (header_x + col_w + col_gap, right_label, right_value),
            ):
                label_text = f"{label}: "
                label_w = _font_width(draw, label_text, header_label_font)
                draw_fitted_text(col_x, row_y, label_text, header_muted, header_label_font, col_w, min_size=8, bold=True)
                draw_fitted_text(col_x + label_w, row_y, value, header_text, header_value_font, col_w - label_w, min_size=8)
        y += header_h + header_gap

    for section_title, rows in sections:
        style = style_for(section_title)
        card_h = card_pad_top + title_h + (len(rows) * row_h) + card_pad_bottom
        draw.rounded_rectangle(
            (margin, y, margin + card_w, y + card_h),
            radius=8,
            fill=style["bg"],
        )
        draw.rectangle((margin, y, margin + 6, y + card_h), fill=style["accent"])

        table_x = margin + table_pad_x
        table_w = card_w - (table_pad_x * 2)
        title_y = y + card_pad_top
        draw_fitted_text(
            table_x,
            title_y,
            section_title.upper(),
            style["accent"],
            title_font,
            table_w,
            min_size=10,
            bold=True,
        )

        table_y = title_y + title_h
        divider_x = table_x + int(table_w * 0.60)
        draw.rectangle((table_x, table_y, table_x + table_w, table_y + (len(rows) * row_h)), outline=grid, width=1)
        draw.line((divider_x, table_y, divider_x, table_y + (len(rows) * row_h)), fill=grid, width=1)

        for idx, (label, value) in enumerate(rows):
            row_y = table_y + (idx * row_h)
            if idx:
                draw.line((table_x, row_y, table_x + table_w, row_y), fill=grid, width=1)
            text_y = row_y + max(0, (row_h - _font_height(draw, label, body_font)) // 2) - 2
            draw_fitted_text(table_x + 2, text_y, label, style["label"], body_font, divider_x - table_x - 20, min_size=11)
            value_w = _font_width(draw, value, value_font)
            value_x = table_x + table_w - value_w - 2
            if value_x < divider_x + 16:
                draw_fitted_text(divider_x + 16, text_y, value, style["value"], value_font, table_x + table_w - divider_x - 18, min_size=11, bold=True)
            else:
                draw.text((value_x, text_y), value, fill=style["value"], font=value_font)

        y += card_h + card_gap

    buffer = io.BytesIO()
    page.save(buffer, format="PDF", resolution=200.0)
    return buffer.getvalue()


def _batch_sheet_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    font_root = Path("/System/Library/Fonts/Supplemental")
    candidates = [
        font_root / ("Arial Bold.ttf" if bold else "Arial.ttf"),
        "Arial Bold.ttf" if bold else "Arial.ttf",
        font_root / "Helvetica.ttc",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _font_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _font_height(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    _, top, _, bottom = draw.textbbox((0, 0), text, font=font)
    return bottom - top


def render_batch_sheet_actions(
    report_title: str,
    job_date,
    sections: list[tuple[str, list[tuple[str, str]]]],
    header_rows: list[tuple[str, str, str, str]] | None = None,
    enabled: bool = True,
):
    export_html = build_print_export(report_title, job_date, sections, header_rows)
    pdf_bytes = build_batch_sheet_pdf(report_title, job_date, sections, header_rows)
    safe_filename = re.sub(r"[^A-Za-z0-9_-]+", "_", report_title).strip("_") or "mold_worksheet"
    print_payload = html.escape(export_html, quote=True)
    disabled_attr = "" if enabled else "disabled"
    disabled_style = "" if enabled else "opacity: 0.45; cursor: not-allowed;"
    click_handler = (
        """
                const oldFrame = document.getElementById('batch-sheet-print-frame');
                if (oldFrame) oldFrame.remove();
                const frame = document.createElement('iframe');
                frame.id = 'batch-sheet-print-frame';
                frame.style.position = 'fixed';
                frame.style.right = '0';
                frame.style.bottom = '0';
                frame.style.width = '0';
                frame.style.height = '0';
                frame.style.border = '0';
                frame.srcdoc = this.dataset.sheet;
                frame.onload = () => {
                    frame.contentWindow.focus();
                    frame.contentWindow.print();
                };
                document.body.appendChild(frame);
        """
        if enabled
        else ""
    )
    render_html_frame(
        f"""
        <button
            type="button"
            {disabled_attr}
            style="
                width: 100%;
                border: 0;
                border-radius: 0.5rem;
                background: #111827;
                color: white;
                cursor: pointer;
                font: 600 16px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                padding: 0.72rem 1rem;
                {disabled_style}
            "
            onclick="
                {click_handler}
            "
            data-sheet="{print_payload}"
        >
            Print Batch Sheet
        </button>
        """,
        height=58,
    )
    st.download_button(
        t("worksheet.actions.download_batch_sheet", "Download Batch Sheet PDF"),
        data=pdf_bytes,
        file_name=f"{safe_filename}_batch_sheet.pdf",
        mime="application/pdf",
        use_container_width=True,
        disabled=not enabled,
    )
    if not enabled:
        st.caption(t("worksheet.actions.batch_sheet_disabled", "Enter print dimensions and STL volume to enable batch sheet export."))

# ─────────────────────────────────────────
tool_left, tool_right = st.columns([1, 1], gap="large")

with tool_left:
    with st.expander(t("worksheet.import.title", "Import from settings.txt"), expanded=False):
        uploaded = st.file_uploader(
            t("worksheet.import.upload", "Drop a settings.txt here"),
            type=["txt"],
            key="settings_upload",
        )
        paste = st.text_area(
            t("worksheet.import.paste", "...or paste the contents"),
            height=120,
            key="settings_paste",
        )
        if st.button(t("worksheet.import.parse", "Parse & pre-fill"), use_container_width=True):
            raw = ""
            if uploaded:
                raw = uploaded.read().decode("utf-8", errors="replace")
            elif paste.strip():
                raw = paste.strip()
            if raw:
                parsed = parse_settings_txt(raw)
                mapping = {
                    "width_mm":   "ws_width_mm",
                    "depth_mm":   "ws_depth_mm",
                    "base_mm":    "ws_base_mm",
                    "height_mm":  "ws_height_mm",
                    "stl_volume": "ws_stl_volume",
                }
                filled = []
                for src_k, state_k in mapping.items():
                    if src_k in parsed:
                        st.session_state[state_k] = parsed[src_k]
                        filled.append(src_k)
                if not st.session_state["ws_title"] and "image_name" in parsed:
                    st.session_state["ws_title"] = parsed["image_name"].rsplit(".", 1)[0]
                if filled:
                    st.success(
                        t(
                            "worksheet.import.prefilled",
                            "Pre-filled: {fields}",
                            fields=", ".join(filled),
                        )
                    )
                else:
                    st.warning(t("worksheet.import.none_found", "No recognised fields found."))
            else:
                st.warning(t("worksheet.import.empty", "Nothing to parse."))

with tool_right:
    with st.expander(t("worksheet.files.title", "Worksheet Files"), expanded=False):
        setup_upload = st.file_uploader(
            t("worksheet.files.upload", "Upload worksheet_settings.json"),
            type=["json"],
            key="worksheet_setup_upload",
        )
        if st.button(
            t("worksheet.files.load", "Load Worksheet File"),
            use_container_width=True,
            disabled=setup_upload is None,
            key="worksheet_load_setup_file",
        ):
            try:
                payload = json.loads(setup_upload.getvalue().decode("utf-8"))
                _load_into_state(payload)
                st.success(t("worksheet.files.loaded", "Worksheet file loaded."))
                st.rerun()
            except Exception as exc:
                st.error(t("worksheet.files.load_failed", "Could not load worksheet file: {error}", error=exc))
        st.caption(
            t(
                "worksheet.files.public_storage_note",
                "Worksheets are stored in your downloaded files, not in a shared server database.",
            )
        )
        st.divider()
        bc1, bc2 = st.columns(2)
        with bc1:
            if st.button(t("worksheet.actions.new", "+ New"), use_container_width=True):
                _reset_state()
                st.rerun()
        with bc2:
            if st.button(t("worksheet.actions.reset", "Reset"), use_container_width=True):
                _reset_state()
                st.rerun()

st.divider()

# ─────────────────────────────────────────
# Active worksheet
# ─────────────────────────────────────────
input_col, output_col = st.columns([0.42, 0.58], gap="large")
silicone_mix_ratio = float(st.session_state.get("ws_si_mix_ratio", FIELD_DEFAULTS["si_mix_ratio"]) or FIELD_DEFAULTS["si_mix_ratio"])

with input_col:
    st.subheader(t("worksheet.sections.print_dimensions", "3D Print Dimensions"))
    st.text_input(
        t("worksheet.fields.title", "Title"),
        key="ws_title",
        placeholder=t("worksheet.fields.title_placeholder", "e.g. Astrid #1"),
    )
    st.date_input(t("worksheet.fields.date", "Date"), key="ws_job_date")

    dim_a, dim_b = st.columns(2)
    with dim_a:
        st.number_input(
            t("worksheet.fields.width", "Width X (mm)"),
            min_value=0.0,
            step=0.5,
            format="%.1f",
            key="ws_width_mm",
            help=t("worksheet.help.width", "Print/model width in millimeters. Used with depth, height, and gap to build the mold box footprint."),
        )
        st.number_input(
            t("worksheet.fields.base", "Base (mm)"),
            min_value=0.0,
            step=0.5,
            format="%.1f",
            key="ws_base_mm",
            help=t("worksheet.help.base", "Base thickness from the 3D print. Base + Relief = Max Z Height."),
        )
    with dim_b:
        st.number_input(
            t("worksheet.fields.depth", "Depth Y (mm)"),
            min_value=0.0,
            step=0.5,
            format="%.1f",
            key="ws_depth_mm",
            help=t("worksheet.help.depth", "Print/model depth in millimeters. Used with width, height, and gap to build the mold box footprint."),
        )
        st.number_input(
            t("worksheet.fields.relief", "Relief (mm)"),
            min_value=0.0,
            step=0.1,
            format="%.1f",
            key="ws_height_mm",
            help=t("worksheet.help.relief", "Relief height above the base. Base + Relief = Max Z Height."),
        )

    st.number_input(
        t("worksheet.fields.stl_volume", "STL Volume (cm³)"),
        min_value=0.0,
        step=1.0,
        format="%.1f",
        key="ws_stl_volume",
        help=t("worksheet.help.stl_volume", "The model volume from the generator or slicer. The worksheet treats 1 cm³ as 1 g for volume-to-weight estimates before material multipliers."),
    )

    st.divider()
    st.subheader(t("worksheet.sections.mold_geometry", "Mold Geometry"))
    st.caption(t("worksheet.geometry.caption", "Gap width between the print and the containment box walls."))
    gap_a, gap_b = st.columns(2)
    with gap_a:
        st.number_input(
            t("worksheet.fields.alg_si_gap_width", "Alginate / Silicone Gap Width (mm)"),
            min_value=0.0,
            max_value=30.0,
            step=1.0,
            format="%.0f",
            key="ws_alg_si_gap_mm",
            help=t("worksheet.help.alg_si_gap_width", "Side clearance used for alginate and silicone duplicate-volume calculations."),
        )
    with gap_b:
        st.number_input(
            t("worksheet.fields.investment_gap_width", "Investment Gap Width (mm)"),
            min_value=0.0,
            max_value=30.0,
            step=1.0,
            format="%.0f",
            key="ws_inv_gap_mm",
            help=t("worksheet.help.investment_gap_width", "Side clearance used for dry investment and R&R 910 calculations."),
        )

    st.divider()
    st.subheader(t("worksheet.sections.mold_type", "Mold Type"))
    if st.session_state["ws_mold_type"] == "Alginate":
        st.session_state["ws_mold_type"] = "Alginate + Investment"
    elif st.session_state["ws_mold_type"] == "Silicone":
        st.session_state["ws_mold_type"] = "Silicone + Investment"
    st.radio(
        t("worksheet.fields.workflow", "Mold workflow"),
        ["Alginate + Investment", "Silicone + Investment"],
        horizontal=True,
        format_func=mold_type_label,
        key="ws_mold_type",
    )

    mold_type = st.session_state["ws_mold_type"]
    if mold_type == "Alginate + Investment":
        st.markdown(f"#### {t('worksheet.alginate.title', 'Alginate')}")
        alg_a, alg_b = st.columns(2)
        with alg_a:
            st.number_input(
                t("worksheet.fields.adjust_base_z", "Adjust Base Z (mm)"),
                min_value=0.0,
                step=0.5,
                format="%.1f",
                key="ws_alg_adjust_zi",
                help=t("worksheet.help.adjust_base_z", "Adds material below the duplicate using the expanded footprint, including gap width."),
            )
        with alg_b:
            st.number_input(t("worksheet.fields.alginate_ratio", "Mix Ratio (water : 1 alginate)"), min_value=1.0, max_value=20.0,
                            step=0.5, format="%.1f", key="ws_alg_mix_ratio",
                            help=t("worksheet.fields.alginate_ratio_help", "e.g. 5.5 = 5.5 parts water to 1 part alginate"))

        st.markdown(f"#### {t('worksheet.investment.title', 'Investment')}")
        st.number_input(
            t("worksheet.fields.adjust_base_z", "Adjust Base Z (mm)"),
            min_value=0.0,
            step=0.5,
            format="%.1f",
            key="ws_inv_adjust_zi",
            help=t("worksheet.help.adjust_base_z", "Adds material below the duplicate using the expanded footprint, including gap width."),
        )
    else:
        st.markdown(f"#### {t('worksheet.silicone.title', 'Siraya Tech Defiant 25')}")
        si_a, si_b = st.columns(2)
        with si_a:
            st.number_input(
                t("worksheet.fields.adjust_base_z", "Adjust Base Z (mm)"),
                min_value=0.0,
                step=0.5,
                format="%.1f",
                key="ws_si_adjust_zi",
                help=t("worksheet.help.adjust_base_z", "Adds material below the duplicate using the expanded footprint, including gap width."),
            )
        with si_b:
            silicone_mix_ratio = st.number_input(
                t("worksheet.fields.silicone_ratio", "Mix Ratio (x : 1)"),
                min_value=1.0,
                max_value=20.0,
                step=0.5,
                format="%.1f",
                key="ws_si_mix_ratio",
                help=t("worksheet.help.silicone_ratio", "Part A : Part B. 1.0 means equal parts A and B; 6.0 means 6 parts A to 1 part B."),
            )
        st.markdown(f"#### {t('worksheet.investment.title', 'Investment')}")
        st.number_input(
            t("worksheet.fields.adjust_base_z", "Adjust Base Z (mm)"),
            min_value=0.0,
            step=0.5,
            format="%.1f",
            key="ws_inv_adjust_zi",
            help=t("worksheet.help.adjust_base_z", "Adds material below the duplicate using the expanded footprint, including gap width."),
        )

    st.divider()
    st.text_area(
        t("worksheet.sections.notes", "Notes"),
        key="ws_notes",
        height=100,
        placeholder=t("worksheet.fields.notes_placeholder", "Any observations, adjustments, or special instructions..."),
    )
    setup_filename = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        st.session_state["ws_title"].strip() or "mold_worksheet",
    ).strip("_")
    st.download_button(
        t("worksheet.actions.download_setup_json", "Download Worksheet JSON"),
        data=_worksheet_json_bytes(),
        file_name=f"{setup_filename}_worksheet_settings.json",
        mime="application/json",
        use_container_width=True,
        type="primary",
        key="worksheet_download_setup_json",
    )

# ─── All inputs are now rendered — read session state and calculate ───
w   = st.session_state["ws_width_mm"]
d   = st.session_state["ws_depth_mm"]
zb  = st.session_state["ws_base_mm"]
za  = st.session_state["ws_height_mm"]
stl = st.session_state["ws_stl_volume"]
alg_si_gap = st.session_state["ws_alg_si_gap_mm"]
inv_gap = st.session_state["ws_inv_gap_mm"]
st.session_state["ws_wall_mm"] = alg_si_gap

p = calc_print(w, d, zb, za, stl)
g = calc_geometry(w, d, alg_si_gap, p["max_z"], stl)
g_inv = calc_geometry(w, d, inv_gap, p["max_z"], stl)
worksheet_ready = all([w, d, za, stl])

with output_col:
    st.subheader(t("worksheet.labels.total", "Summary"))
    metric_cols = st.columns(3)
    metric_cols[0].metric(t("worksheet.labels.model_volume", "Model Volume"), f"{g['model_volume']} cm³")
    metric_cols[1].metric(t("worksheet.labels.max_z_height", "Max Z Height"), f"{p['max_z']} mm")
    metric_cols[2].metric(t("worksheet.labels.alg_si_box_wd", "Alginate / Silicone Box W x D"), f"{g['box_w']:.0f}x{g['box_d']:.0f} mm")

    warnings = []
    if not worksheet_ready:
        warnings.append(t("worksheet.warnings.missing_values", "Enter print dimensions and STL volume to complete the worksheet."))
    if worksheet_ready and alg_si_gap <= 0 and inv_gap <= 0:
        st.info(t("worksheet.warnings.zero_gap", "Gap width is 0 mm, so the mold box has no side clearance."))
    if worksheet_ready and g["mold_vol"] < 0:
        warnings.append(t("worksheet.warnings.negative_mold_volume", "Mold volume is negative. Check STL volume, relief height, and box dimensions."))
    if worksheet_ready and p["actual_art_vol"] < 0:
        warnings.append(t("worksheet.warnings.negative_art_volume", "Actual art volume is negative. Check base thickness against STL volume."))
    for warning in warnings:
        st.warning(warning)

    with st.expander(t("worksheet.formulas.title", "Formula Notes"), expanded=False):
        st.markdown(
            t(
                "worksheet.formulas.body",
                """
**Metric Volume / Water Equivalence**

All length, weight, and volume measurements in this worksheet use metric units. For water, 1 cm³ = 1 ml = 1 g. Example: a container interior measuring 20 x 20 x 2.5 cm has a volume of 1000 cm³, holds 1000 ml of water, and contains 1000 g of water.

**Duplicate Volume**

| Item | Formula |
| --- | --- |
| Duplicate Volume | Model Volume + Gap Volume + Base Z Volume |
| Gap Volume | ((Box W x Box D) - (Print W x Print D)) x Max Z / 1000 |
| Base Z Volume | Box W x Box D x Adjust Base Z / 1000 |

**Alginate**

| Item | Formula |
| --- | --- |
| Water | Duplicate Volume |
| Alginate | Water / Mix Ratio |

**Siraya Tech Defiant 25**

| Item | Formula / Value |
| --- | --- |
| Total | Duplicate Volume x 1.12 |
| Density | 1.12 g/cm³ |
| Mix Ratio | 1.0 : 1 by weight |
| Part A / Part B | Equal weights at 1.0 : 1 |

Pot life is about 15 minutes. Full cure is 4-6 hours at 25°C.

**Dry Investment**

| Item | Formula |
| --- | --- |
| Dry powder | Duplicate Volume x 1.25 |
| Water | Dry powder / 1.75 |

**R&R 910**

| Item | Formula / Value |
| --- | --- |
| Mixed Total | Duplicate Volume x 1.88 |
| Powder | Mixed Total x (100 / 128) |
| Water | Powder x 0.28 |
| Water/Powder Ratio | 28/100 by weight |

Mix for 2-3 minutes.

Pour time is 10-11 minutes. Set time is 14-17 minutes.

After set, let the mold sit at least 1 hour before pattern removal. For curing after pattern removal, hold at 300-350°F until water is removed, then raise at 150-200°F per hour.
                """,
            )
        )

    mold_box_title = t("worksheet.cards.mold_box", "MOLD BOX")
    mold_box_rows = [
        (t("worksheet.labels.alg_si_box_wd", "Alginate / Silicone Box W x D"), f"{g['box_w']:.0f} x {g['box_d']:.0f} mm"),
        (t("worksheet.labels.alg_si_box_volume", "Alginate / Silicone Box Volume"), f"{g['box_volume']} cm³"),
        (t("worksheet.labels.investment_box_wd", "Investment Box W x D"), f"{g_inv['box_w']:.0f} x {g_inv['box_d']:.0f} mm"),
        (t("worksheet.labels.investment_box_volume", "Investment Box Volume"), f"{g_inv['box_volume']} cm³"),
        (t("worksheet.labels.model_volume", "Model Volume"), f"{g['model_volume']} cm³"),
        (t("worksheet.labels.volume_to_max_z", "Volume to Max Z"), f"{p['vol_to_max_z']} cm³"),
    ]
    card(mold_box_title, mold_box_rows, bg="#f8fafc", border="#64748b", label_color="#475569", value_color="#0f172a")

    mold_type = st.session_state["ws_mold_type"]
    report_title = st.session_state["ws_title"].strip() or t("worksheet.title", "Cameo Mold Worksheet")
    dimensions_text = f"{w:.1f} x {d:.1f} x {p['max_z']} mm"
    workflow_label = mold_type_label(mold_type)

    def batch_header_rows(mix_summary: str) -> list[tuple[str, str, str, str]]:
        return [
            (
                t("worksheet.labels.dimensions", "Dimensions"),
                dimensions_text,
                t("worksheet.fields.stl_volume", "STL Volume"),
                f"{stl:.1f} cm³",
            ),
            (
                t("worksheet.fields.mold_type", "Mold workflow"),
                workflow_label,
                t("worksheet.labels.mix_ratios", "Mix Ratios"),
                mix_summary,
            ),
        ]

    if mold_type == "Alginate + Investment":
        a = calc_alginate(w, d, alg_si_gap, g["model_volume"], p["max_z"],
                          st.session_state["ws_alg_adjust_zi"],
                          st.session_state["ws_alg_mix_ratio"])
        i = calc_investment(w, d, inv_gap, g["model_volume"], p["max_z"],
                            st.session_state["ws_inv_adjust_zi"])

        card(t("worksheet.cards.alginate", "ACCU-CAST ALGINATE 570 PGV · {ratio} : 1", ratio=f"{st.session_state['ws_alg_mix_ratio']:.1f}"), [
            (t("worksheet.labels.duplicate_volume_model_z", "Volume (Model + Gap + Base Z)"), f"{a['alg_mold_vol']} cm³"),
            (t("worksheet.labels.water", "Water"), f"{a['alg_water_g']} g"),
            (t("worksheet.labels.alginate", "Alginate"), f"{a['alg_alginate_g']} g"),
            (t("worksheet.labels.total_thickness", "Total Thickness"), f"{a['alg_total_thick']} mm"),
        ], bg="#f0fdf4", border="#16a34a", label_color="#166534", value_color="#14532d")

        card(t("worksheet.cards.dry_investment", "DRY INVESTMENT / PLASTER + SILICA · Volume {volume} cm³", volume=f"{i['inv_vol']}"), [
            (t("worksheet.labels.duplicate_volume_model_z", "Volume (Model + Gap + Base Z)"), f"{i['inv_vol']} cm³"),
            (t("worksheet.labels.plaster", "Plaster"), f"{i['plaster_g']} g"),
            (t("worksheet.labels.silica_flour", "Silica Flour"), f"{i['silica_g']} g"),
            (t("worksheet.labels.water", "Water"), f"{i['inv_water_g']} g"),
            (t("worksheet.labels.total_thickness", "Total Thickness"), f"{i['inv_total_thick']} mm"),
        ], bg="#fffbeb", border="#d97706", label_color="#92400e", value_color="#78350f")

        card(t("worksheet.cards.rr910", "R&R 910 · Volume {volume} cm³ · density 1.88 g/ml", volume=f"{i['inv_vol']}"), [
            (t("worksheet.labels.rr910", "R&R 910 Powder"), f"{i['rr910_g']} g"),
            (t("worksheet.labels.water", "Water"), f"{i['rr910_water_g']} g"),
            (t("worksheet.labels.total_thickness", "Total Thickness"), f"{i['inv_total_thick']} mm"),
        ], bg="#faf5ff", border="#7c3aed", label_color="#6b21a8", value_color="#581c87")

        print_sections = [
            (mold_box_title, mold_box_rows),
            (
                t("worksheet.cards.alginate", "ACCU-CAST ALGINATE 570 PGV · {ratio} : 1", ratio=f"{st.session_state['ws_alg_mix_ratio']:.1f}"),
                [
                    (t("worksheet.labels.duplicate_volume_model_z", "Volume (Model + Gap + Base Z)"), f"{a['alg_mold_vol']} cm³"),
                    (t("worksheet.labels.water", "Water"), f"{a['alg_water_g']} g"),
                    (t("worksheet.labels.alginate", "Alginate"), f"{a['alg_alginate_g']} g"),
                    (t("worksheet.labels.total_thickness", "Total Thickness"), f"{a['alg_total_thick']} mm"),
                ],
            ),
            (
                t("worksheet.cards.dry_investment", "DRY INVESTMENT / PLASTER + SILICA · Volume {volume} cm³", volume=f"{i['inv_vol']}"),
                [
                    (t("worksheet.labels.duplicate_volume_model_z", "Volume (Model + Gap + Base Z)"), f"{i['inv_vol']} cm³"),
                    (t("worksheet.labels.plaster", "Plaster"), f"{i['plaster_g']} g"),
                    (t("worksheet.labels.silica_flour", "Silica Flour"), f"{i['silica_g']} g"),
                    (t("worksheet.labels.water", "Water"), f"{i['inv_water_g']} g"),
                    (t("worksheet.labels.total_thickness", "Total Thickness"), f"{i['inv_total_thick']} mm"),
                ],
            ),
            (
                t("worksheet.cards.rr910", "R&R 910 · Volume {volume} cm³ · density 1.88 g/ml", volume=f"{i['inv_vol']}"),
                [
                    (t("worksheet.labels.rr910", "R&R 910 Powder"), f"{i['rr910_g']} g"),
                    (t("worksheet.labels.water", "Water"), f"{i['rr910_water_g']} g"),
                    (t("worksheet.labels.total_thickness", "Total Thickness"), f"{i['inv_total_thick']} mm"),
                ],
            ),
        ]
        mix_summary = t(
            "worksheet.export.mix_ratios_alginate",
            "Accu-Cast {alginate}:1; Plaster/Silica 1:1; R&R 910 water/powder 28/100",
            alginate=f"{st.session_state['ws_alg_mix_ratio']:.1f}",
        )
        render_batch_sheet_actions(
            report_title,
            st.session_state["ws_job_date"],
            print_sections,
            header_rows=batch_header_rows(mix_summary),
            enabled=worksheet_ready,
        )

    elif mold_type == "Silicone + Investment":
        s = calc_silicone(w, d, alg_si_gap, g["model_volume"], p["max_z"],
                          st.session_state["ws_si_adjust_zi"],
                          silicone_mix_ratio)
        i = calc_investment(w, d, inv_gap, g["model_volume"], p["max_z"],
                            st.session_state["ws_inv_adjust_zi"])
        card(t("worksheet.cards.silicone", "Siraya Tech Defiant 25 · ratio {ratio} : 1", ratio=f"{silicone_mix_ratio:.1f}"), [
            (t("worksheet.labels.duplicate_volume_model_z", "Volume (Model + Gap + Base Z)"), f"{s['mold_volume_si']} cm³"),
            (t("worksheet.labels.total", "Total"), f"{s['silicone_g']} g"),
            (t("worksheet.labels.part_a", "Part A"), f"{s['part_a']} g"),
            (t("worksheet.labels.part_b", "Part B"), f"{s['part_b']} g"),
            (t("worksheet.labels.total_thickness", "Total Thickness"), f"{s['si_total_thick']} mm"),
        ], bg="#eff6ff", border="#2563eb", label_color="#1e40af", value_color="#1e3a8a")

        card(t("worksheet.cards.dry_investment", "DRY INVESTMENT / PLASTER + SILICA · Volume {volume} cm³", volume=f"{i['inv_vol']}"), [
            (t("worksheet.labels.duplicate_volume_model_z", "Volume (Model + Gap + Base Z)"), f"{i['inv_vol']} cm³"),
            (t("worksheet.labels.plaster", "Plaster"), f"{i['plaster_g']} g"),
            (t("worksheet.labels.silica_flour", "Silica Flour"), f"{i['silica_g']} g"),
            (t("worksheet.labels.water", "Water"), f"{i['inv_water_g']} g"),
            (t("worksheet.labels.total_thickness", "Total Thickness"), f"{i['inv_total_thick']} mm"),
        ], bg="#fffbeb", border="#d97706", label_color="#92400e", value_color="#78350f")

        card(t("worksheet.cards.rr910", "R&R 910 · Volume {volume} cm³ · density 1.88 g/ml", volume=f"{i['inv_vol']}"), [
            (t("worksheet.labels.rr910", "R&R 910 Powder"), f"{i['rr910_g']} g"),
            (t("worksheet.labels.water", "Water"), f"{i['rr910_water_g']} g"),
            (t("worksheet.labels.total_thickness", "Total Thickness"), f"{i['inv_total_thick']} mm"),
        ], bg="#faf5ff", border="#7c3aed", label_color="#6b21a8", value_color="#581c87")

        print_sections = [
            (mold_box_title, mold_box_rows),
            (
                t("worksheet.cards.silicone", "Siraya Tech Defiant 25 · ratio {ratio} : 1", ratio=f"{silicone_mix_ratio:.1f}"),
                [
                    (t("worksheet.labels.duplicate_volume_model_z", "Volume (Model + Gap + Base Z)"), f"{s['mold_volume_si']} cm³"),
                    (t("worksheet.labels.total", "Total"), f"{s['silicone_g']} g"),
                    (t("worksheet.labels.part_a", "Part A"), f"{s['part_a']} g"),
                    (t("worksheet.labels.part_b", "Part B"), f"{s['part_b']} g"),
                    (t("worksheet.labels.total_thickness", "Total Thickness"), f"{s['si_total_thick']} mm"),
                ],
            ),
            (
                t("worksheet.cards.dry_investment", "DRY INVESTMENT / PLASTER + SILICA · Volume {volume} cm³", volume=f"{i['inv_vol']}"),
                [
                    (t("worksheet.labels.duplicate_volume_model_z", "Volume (Model + Gap + Base Z)"), f"{i['inv_vol']} cm³"),
                    (t("worksheet.labels.plaster", "Plaster"), f"{i['plaster_g']} g"),
                    (t("worksheet.labels.silica_flour", "Silica Flour"), f"{i['silica_g']} g"),
                    (t("worksheet.labels.water", "Water"), f"{i['inv_water_g']} g"),
                    (t("worksheet.labels.total_thickness", "Total Thickness"), f"{i['inv_total_thick']} mm"),
                ],
            ),
            (
                t("worksheet.cards.rr910", "R&R 910 · Volume {volume} cm³ · density 1.88 g/ml", volume=f"{i['inv_vol']}"),
                [
                    (t("worksheet.labels.rr910", "R&R 910 Powder"), f"{i['rr910_g']} g"),
                    (t("worksheet.labels.water", "Water"), f"{i['rr910_water_g']} g"),
                    (t("worksheet.labels.total_thickness", "Total Thickness"), f"{i['inv_total_thick']} mm"),
                ],
            ),
        ]
        mix_summary = t(
            "worksheet.export.mix_ratios_silicone",
            "Defiant 25 {silicone}:1; Plaster/Silica 1:1; R&R 910 water/powder 28/100",
            silicone=f"{silicone_mix_ratio:.1f}",
        )
        render_batch_sheet_actions(
            report_title,
            st.session_state["ws_job_date"],
            print_sections,
            header_rows=batch_header_rows(mix_summary),
            enabled=worksheet_ready,
        )
