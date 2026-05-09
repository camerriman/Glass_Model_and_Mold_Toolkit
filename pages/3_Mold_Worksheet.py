"""
5_Mold_Worksheet.py
Mold Calculator & Record Keeper
- Parses settings.txt from the Cameo Mold Generator (App 1)
- Live worksheet: 3D Print → Mold Geometry → tabbed mold type
- Saves / loads records via local SQLite database
"""

import html
import re
import sqlite3
import io
from datetime import date, datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageFont
from i18n import format_date, format_datetime, render_app_sidebar, t

# ─────────────────────────────────────────
# Config
# ─────────────────────────────────────────
st.set_page_config(page_title=t("worksheet.title", "Mold Worksheet"), layout="wide")
render_app_sidebar()
st.title(t("worksheet.title", "Mold Worksheet"))
st.caption(
    t(
        "worksheet.caption",
        "Pre-fill from a settings.txt or enter values manually. Select the mold type tab to see its calculations.",
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

APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "mold_records.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────
# Database
# ─────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS molds (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                title         TEXT NOT NULL,
                job_date      TEXT,
                created_at    TEXT NOT NULL,
                mold_type     TEXT,
                width_mm      REAL,
                depth_mm      REAL,
                base_mm       REAL,
                height_mm     REAL,
                stl_volume    REAL,
                wall_mm       REAL,
                alg_adjust_zi REAL,
                alg_mix_ratio REAL,
                si_adjust_zi  REAL,
                si_mix_ratio  REAL,
                inv_adjust_zi REAL,
                notes         TEXT
            )
        """)
        existing = {r[1] for r in conn.execute("PRAGMA table_info(molds)").fetchall()}
        for col, dflt in [
            ("mold_type",     "'Alginate'"),
            ("alg_adjust_zi", "0.0"),
            ("alg_mix_ratio", "1.0"),
        ]:
            if col not in existing:
                col_type = "TEXT" if col == "mold_type" else "REAL"
                conn.execute(f"ALTER TABLE molds ADD COLUMN {col} {col_type} DEFAULT {dflt}")

init_db()

def save_record(rec: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO molds
                (title, job_date, created_at, mold_type,
                 width_mm, depth_mm, base_mm, height_mm, stl_volume,
                 wall_mm,
                 alg_adjust_zi, alg_mix_ratio,
                 si_adjust_zi,  si_mix_ratio,
                 inv_adjust_zi, notes)
            VALUES
                (:title, :job_date, :created_at, :mold_type,
                 :width_mm, :depth_mm, :base_mm, :height_mm, :stl_volume,
                 :wall_mm,
                 :alg_adjust_zi, :alg_mix_ratio,
                 :si_adjust_zi,  :si_mix_ratio,
                 :inv_adjust_zi, :notes)
        """, rec)
        return cur.lastrowid

def update_record(record_id: int, rec: dict):
    rec["id"] = record_id
    with get_conn() as conn:
        conn.execute("""
            UPDATE molds SET
                title=:title, job_date=:job_date, mold_type=:mold_type,
                width_mm=:width_mm, depth_mm=:depth_mm, base_mm=:base_mm,
                height_mm=:height_mm, stl_volume=:stl_volume,
                wall_mm=:wall_mm,
                alg_adjust_zi=:alg_adjust_zi, alg_mix_ratio=:alg_mix_ratio,
                si_adjust_zi=:si_adjust_zi,   si_mix_ratio=:si_mix_ratio,
                inv_adjust_zi=:inv_adjust_zi, notes=:notes
            WHERE id=:id
        """, rec)

def delete_record(record_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM molds WHERE id=?", (record_id,))

def list_records():
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, title, job_date, created_at, mold_type FROM molds ORDER BY created_at DESC"
        ).fetchall()

def load_record(record_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM molds WHERE id=?", (record_id,)).fetchone()

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
    Mold base is additional material below the print (variable, 0–30 mm).
    Mold material volume = box volume − STL volume + mold base volume.
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

def calc_alginate(w, d, mold_vol, max_z, wall, alg_zi, alg_ratio):
    """Alginate: box volume minus model, + optional Z extension.
    mold_vol = box_vol - stl_vol, already computed in calc_geometry.
    """
    zi_vol     = round(((w * d) / 1000) * alg_zi, 1)
    total_vol  = round(mold_vol + zi_vol, 1)
    water_g    = round(total_vol, 1)
    alginate_g = round(water_g / alg_ratio, 1) if alg_ratio > 0 else 0.0
    thickness  = round(max_z + alg_zi, 1)
    return {
        "alg_mold_vol":    total_vol,
        "alg_water_g":     water_g,
        "alg_alginate_g":  alginate_g,
        "alg_thickness":   thickness,
        "alg_total_thick": round(thickness + wall, 1),
    }

def calc_silicone(w, d, box_volume, model_volume, si_zi, si_ratio):
    """Silicone: fills box minus model, + optional Z extension.
    si_ratio splits total weight as part A : part B.
    """
    zi_vol    = round(((w * d) / 1000) * si_zi, 1)
    mold_vol  = round(box_volume - model_volume + zi_vol, 1)
    si_g      = round(mold_vol * 1.12, 1)
    part_a    = round(si_g * si_ratio / (si_ratio + 1), 1) if si_ratio > 0 else round(si_g / 2, 1)
    part_b    = round(si_g - part_a, 1)
    return {
        "si_zi_vol":      zi_vol,
        "mold_volume_si": mold_vol,
        "silicone_g":     si_g,
        "part_a":         part_a,
        "part_b":         part_b,
    }

def calc_investment(w, d, mold_vol, max_z, wall, inv_zi):
    """Investment: box volume minus model, + optional Z extension.
    mold_vol = box_vol - stl_vol, already computed in calc_geometry.
    """
    zi_vol  = round(((w * d) / 1000) * inv_zi, 1)
    inv_vol = round(mold_vol + zi_vol, 1)
    dry_inv = round(inv_vol * 1.25, 1)
    rr910   = round(inv_vol * 1.88, 1)
    return {
        "inv_vol":         inv_vol,
        "inv_total_thick": round(max_z + inv_zi + wall, 1),
        "dry_investment":  dry_inv,
        "plaster_g":       round(dry_inv / 2, 1),
        "silica_g":        round(dry_inv / 2, 1),
        "inv_water_g":     round(dry_inv / 1.75, 1),
        "rr910_g":         rr910,
        "rr910_water_g":   round(rr910 / (1.88 / 0.88), 1),
    }

# ─────────────────────────────────────────
# Session state defaults
# ─────────────────────────────────────────
FIELD_DEFAULTS = dict(
    title="", job_date=date.today(), mold_type="Alginate + Investment",
    width_mm=0.0, depth_mm=0.0, base_mm=0.0, height_mm=0.0, stl_volume=0.0,
    wall_mm=0.0,
    alg_adjust_zi=0.0, alg_mix_ratio=1.0,
    si_adjust_zi=0.0,  si_mix_ratio=1.0,
    inv_adjust_zi=0.0,
    notes="",
)
for k, v in FIELD_DEFAULTS.items():
    st.session_state.setdefault(f"ws_{k}", v)
st.session_state.setdefault("ws_loaded_id", None)


FLOAT_FIELDS = {k for k, v in FIELD_DEFAULTS.items() if isinstance(v, float)}

def _load_into_state(row):
    for k in FIELD_DEFAULTS:
        if k in row.keys() and row[k] is not None:
            val = row[k]
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
    st.session_state["ws_loaded_id"] = row["id"]


def _reset_state():
    for k, v in FIELD_DEFAULTS.items():
        st.session_state[f"ws_{k}"] = v
    st.session_state["ws_loaded_id"] = None


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


def build_print_export(title: str, job_date, sections: list[tuple[str, list[tuple[str, str]]]]) -> str:
    """Create a compact browser-printable HTML worksheet."""
    safe_title = html.escape(title.strip() or t("worksheet.title", "Mold Worksheet"))
    if hasattr(job_date, "isoformat"):
        safe_date = html.escape(format_date(job_date.isoformat()))
    else:
        safe_date = html.escape(format_date(str(job_date)))
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
<title>{safe_title} - Mold Worksheet</title>
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
  td {{
    border-bottom: 1px solid #e5e7eb;
    padding: 4px 0;
    vertical-align: top;
  }}
  td:last-child {{
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
<main>
{''.join(section_html)}
</main>
</body>
</html>
"""


def build_batch_sheet_pdf(title: str, job_date, sections: list[tuple[str, list[tuple[str, str]]]]) -> bytes:
    page_w, page_h = 1700, 2200
    margin = 86
    gap = 34
    white = (255, 255, 255)
    black = (24, 31, 42)
    muted = (86, 95, 109)
    grid = (218, 224, 232)
    header_bg = (244, 247, 251)

    page = Image.new("RGB", (page_w, page_h), white)
    draw = ImageDraw.Draw(page)
    title_font = _batch_sheet_font(42, bold=True)
    meta_font = _batch_sheet_font(22)
    section_font = _batch_sheet_font(21, bold=True)
    body_font = _batch_sheet_font(20)
    value_font = _batch_sheet_font(20, bold=True)

    safe_title = title.strip() or t("worksheet.title", "Mold Worksheet")
    if hasattr(job_date, "isoformat"):
        date_text = format_date(job_date.isoformat())
    else:
        date_text = format_date(str(job_date))

    y = margin
    draw.text((margin, y), safe_title, fill=black, font=title_font)
    y += _font_height(draw, safe_title, title_font) + 8
    draw.text((margin, y), date_text, fill=muted, font=meta_font)
    y += _font_height(draw, date_text, meta_font) + 22
    draw.line((margin, y, page_w - margin, y), fill=black, width=3)
    y += 26

    col_w = (page_w - (margin * 2) - gap) // 2
    row_h = 38
    header_h = 42
    section_gap = 26
    columns = [margin, margin + col_w + gap]
    col_y = [y, y]

    for idx, (section_title, rows) in enumerate(sections):
        col = idx % 2
        x = columns[col]
        needed = header_h + (len(rows) * row_h) + section_gap
        if col_y[col] + needed > page_h - margin:
            col = 1 if col == 0 else 0
            x = columns[col]
        y0 = col_y[col]

        draw.rounded_rectangle(
            (x, y0, x + col_w, y0 + header_h),
            radius=8,
            fill=header_bg,
            outline=grid,
            width=1,
        )
        draw.text((x + 14, y0 + 10), section_title.upper(), fill=black, font=section_font)
        y_row = y0 + header_h
        for label, value in rows:
            draw.rectangle((x, y_row, x + col_w, y_row + row_h), outline=grid, width=1)
            draw.text((x + 14, y_row + 9), label, fill=black, font=body_font)
            value_w = _font_width(draw, value, value_font)
            draw.text((x + col_w - value_w - 14, y_row + 9), value, fill=black, font=value_font)
            y_row += row_h
        col_y[col] = y_row + section_gap

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


def render_batch_sheet_actions(report_title: str, job_date, sections: list[tuple[str, list[tuple[str, str]]]]):
    export_html = build_print_export(report_title, job_date, sections)
    pdf_bytes = build_batch_sheet_pdf(report_title, job_date, sections)
    safe_filename = re.sub(r"[^A-Za-z0-9_-]+", "_", report_title).strip("_") or "mold_worksheet"
    print_payload = html.escape(export_html, quote=True)
    components.html(
        f"""
        <button
            type="button"
            style="
                width: 100%;
                border: 0;
                border-radius: 0.5rem;
                background: #111827;
                color: white;
                cursor: pointer;
                font: 600 16px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                padding: 0.72rem 1rem;
            "
            onclick="
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
                frame.onload = () => {{
                    frame.contentWindow.focus();
                    frame.contentWindow.print();
                }};
                document.body.appendChild(frame);
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
    )

# ─────────────────────────────────────────
# Worksheet controls
# ─────────────────────────────────────────
loaded_id = st.session_state.get("ws_loaded_id")
save_label = t("worksheet.actions.update", "Update") if loaded_id else t("worksheet.actions.save", "Save")
save_clicked = False

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
    with st.expander(t("worksheet.records.title", "Saved Records"), expanded=False):
        records = list_records()
        if not records:
            st.info(t("worksheet.records.empty", "No saved records yet."))
        else:
            for row in records:
                mold_label = f"  ·  {mold_type_label(row['mold_type'])}" if row["mold_type"] else ""
                job_date_text = format_date(row["job_date"]) if row["job_date"] else t("worksheet.records.no_date", "no date")
                rc1, rc2, rc3 = st.columns([4, 1, 1])
                with rc1:
                    st.markdown(f"**{row['title']}**{mold_label}  —  {job_date_text}")
                    st.caption(
                        t(
                            "worksheet.records.saved_at",
                            "Saved {value}",
                            value=format_datetime(row["created_at"]),
                        )
                    )
                with rc2:
                    if st.button(t("worksheet.actions.load", "Load"), key=f"load_{row['id']}"):
                        _load_into_state(load_record(row["id"]))
                        st.rerun()
                with rc3:
                    if st.button(t("worksheet.actions.delete_help", "Delete"), key=f"del_{row['id']}"):
                        delete_record(row["id"])
                        if st.session_state["ws_loaded_id"] == row["id"]:
                            _reset_state()
                        st.rerun()

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
        st.number_input(t("worksheet.fields.width", "Width X (mm)"), min_value=0.0, step=0.5, format="%.1f", key="ws_width_mm")
        st.number_input(t("worksheet.fields.base", "Base (mm)"), min_value=0.0, step=0.5, format="%.1f", key="ws_base_mm")
    with dim_b:
        st.number_input(t("worksheet.fields.depth", "Depth Y (mm)"), min_value=0.0, step=0.5, format="%.1f", key="ws_depth_mm")
        st.number_input(t("worksheet.fields.relief", "Relief (mm)"), min_value=0.0, step=0.1, format="%.1f", key="ws_height_mm")

    st.number_input(t("worksheet.fields.stl_volume", "STL Volume (cm³)"), min_value=0.0, step=1.0, format="%.1f", key="ws_stl_volume")

    st.divider()
    st.subheader(t("worksheet.sections.mold_geometry", "Mold Geometry"))
    st.caption(t("worksheet.geometry.caption", "Gap width between the print and the containment box walls."))
    st.number_input(t("worksheet.fields.gap_width", "Gap Width (mm)"), min_value=0.0, max_value=30.0, step=1.0, format="%.0f", key="ws_wall_mm")

    st.divider()
    st.subheader(t("worksheet.sections.mold_type", "Mold Type"))
    if st.session_state["ws_mold_type"] == "Silicone":
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
            st.number_input(t("worksheet.fields.adjust_base_z", "Adjust Base Z (mm)"), min_value=0.0, step=0.5, format="%.1f",
                            key="ws_alg_adjust_zi")
        with alg_b:
            st.number_input(t("worksheet.fields.alginate_ratio", "Mix Ratio (water : 1 alginate)"), min_value=1.0, max_value=20.0,
                            step=0.5, format="%.1f", key="ws_alg_mix_ratio",
                            help=t("worksheet.fields.alginate_ratio_help", "e.g. 5.5 = 5.5 parts water to 1 part alginate"))

        st.markdown(f"#### {t('worksheet.investment.title', 'Investment')}")
        st.number_input(t("worksheet.fields.adjust_base_z", "Adjust Base Z (mm)"), min_value=0.0, step=0.5, format="%.1f",
                        key="ws_inv_adjust_zi")
    else:
        st.markdown(f"#### {t('worksheet.silicone.title', 'Silicone')}")
        si_a, si_b = st.columns(2)
        with si_a:
            st.number_input(t("worksheet.fields.adjust_base_z", "Adjust Base Z (mm)"), min_value=0.0, step=0.5, format="%.1f",
                            key="ws_si_adjust_zi")
        with si_b:
            st.number_input(t("worksheet.fields.silicone_ratio", "Mix Ratio (x : 1)"), min_value=1.0, max_value=20.0,
                            step=0.5, format="%.1f", key="ws_si_mix_ratio")
        st.markdown(f"#### {t('worksheet.investment.title', 'Investment')}")
        st.number_input(t("worksheet.fields.adjust_base_z", "Adjust Base Z (mm)"), min_value=0.0, step=0.5, format="%.1f",
                        key="ws_inv_adjust_zi")

    st.divider()
    st.text_area(
        t("worksheet.sections.notes", "Notes"),
        key="ws_notes",
        height=100,
        placeholder=t("worksheet.fields.notes_placeholder", "Any observations, adjustments, or special instructions..."),
    )
    save_clicked = st.button(save_label, use_container_width=True, type="primary")

# ─── All inputs are now rendered — read session state and calculate ───
w   = st.session_state["ws_width_mm"]
d   = st.session_state["ws_depth_mm"]
zb  = st.session_state["ws_base_mm"]
za  = st.session_state["ws_height_mm"]
stl = st.session_state["ws_stl_volume"]

p = calc_print(w, d, zb, za, stl)
g = calc_geometry(w, d,
                  st.session_state["ws_wall_mm"],
                  p["max_z"],
                  stl)

with output_col:
    st.subheader(t("worksheet.labels.total", "Summary"))
    metric_cols = st.columns(3)
    metric_cols[0].metric(t("worksheet.labels.mold_volume", "Mold Volume"), f"{g['mold_vol']} cm³")
    metric_cols[1].metric(t("worksheet.labels.max_z_height", "Max Z Height"), f"{p['max_z']} mm")
    metric_cols[2].metric(t("worksheet.labels.box_wd", "Box W x D"), f"{g['box_w']:.0f}x{g['box_d']:.0f} mm")

    warnings = []
    if not all([w, d, za, stl]):
        warnings.append(t("worksheet.warnings.missing_values", "Enter print dimensions and STL volume to complete the worksheet."))
    if st.session_state["ws_wall_mm"] <= 0:
        warnings.append(t("worksheet.warnings.zero_gap", "Gap width is 0 mm, so the mold box has no side clearance."))
    if g["mold_vol"] < 0:
        warnings.append(t("worksheet.warnings.negative_mold_volume", "Mold volume is negative. Check STL volume, relief height, and box dimensions."))
    if p["actual_art_vol"] < 0:
        warnings.append(t("worksheet.warnings.negative_art_volume", "Actual art volume is negative. Check base thickness against STL volume."))
    for warning in warnings:
        st.warning(warning)

    card(t("worksheet.cards.print_calculations", "3D PRINT CALCULATIONS"), [
        (t("worksheet.labels.base_volume", "Base Volume"), f"{p['base_volume']} cm³"),
        (t("worksheet.labels.art_space_volume", "Art Space Volume"), f"{p['art_space_vol']} cm³"),
        (t("worksheet.labels.actual_art_volume", "Actual Art Volume"), f"{p['actual_art_vol']} cm³"),
        (t("worksheet.labels.volume_to_max_z", "Volume to Max Z"), f"{p['vol_to_max_z']} cm³"),
    ], bg="#f8fafc", border="#64748b", label_color="#475569", value_color="#0f172a")

    card(t("worksheet.cards.mold_box", "MOLD BOX"), [
        (t("worksheet.labels.box_wd", "Box W x D"), f"{g['box_w']:.0f} x {g['box_d']:.0f} mm"),
        (t("worksheet.labels.box_volume", "Box Volume"), f"{g['box_volume']} cm³"),
        (t("worksheet.labels.model_volume", "Model Volume"), f"{g['model_volume']} cm³"),
        (t("worksheet.labels.mold_volume", "Mold Volume"), f"{g['mold_vol']} cm³"),
    ], bg="#f8fafc", border="#64748b", label_color="#475569", value_color="#0f172a")

    mold_type = st.session_state["ws_mold_type"]
    if mold_type == "Alginate + Investment":
        a = calc_alginate(w, d, g["mold_vol"], p["max_z"],
                          st.session_state["ws_wall_mm"],
                          st.session_state["ws_alg_adjust_zi"],
                          st.session_state["ws_alg_mix_ratio"])
        i = calc_investment(w, d, g["mold_vol"], p["max_z"],
                            st.session_state["ws_wall_mm"],
                            st.session_state["ws_inv_adjust_zi"])

        batch_cols = st.columns(3)
        batch_cols[0].metric(t("worksheet.labels.water", "Water"), f"{a['alg_water_g']} g")
        batch_cols[1].metric(t("worksheet.labels.alginate", "Alginate"), f"{a['alg_alginate_g']} g")
        batch_cols[2].metric(t("worksheet.labels.dry_investment", "Dry Investment"), f"{i['dry_investment']} g")

        card(t("worksheet.cards.alginate", "ACCU-CAST ALGINATE 570 PGV · {ratio} : 1", ratio=f"{st.session_state['ws_alg_mix_ratio']:.1f}"), [
            (t("worksheet.labels.mold_volume_box_model_z", "Mold Volume (Box - Model + Z)"), f"{a['alg_mold_vol']} cm³"),
            (t("worksheet.labels.water", "Water"), f"{a['alg_water_g']} g"),
            (t("worksheet.labels.alginate", "Alginate"), f"{a['alg_alginate_g']} g"),
            (t("worksheet.labels.mold_thickness", "Mold Thickness"), f"{a['alg_thickness']} mm"),
            (t("worksheet.labels.total_thickness", "Total Thickness"), f"{a['alg_total_thick']} mm"),
        ], bg="#f0fdf4", border="#16a34a", label_color="#166534", value_color="#14532d")

        card(t("worksheet.cards.dry_investment", "DRY INVESTMENT / PLASTER + SILICA · Mold vol {volume} cm³", volume=f"{i['inv_vol']}"), [
            (t("worksheet.labels.mold_volume_box_model_z", "Mold Volume (Box - Model + Z)"), f"{i['inv_vol']} cm³"),
            (t("worksheet.labels.plaster", "Plaster"), f"{i['plaster_g']} g"),
            (t("worksheet.labels.silica_flour", "Silica Flour"), f"{i['silica_g']} g"),
            (t("worksheet.labels.water", "Water"), f"{i['inv_water_g']} g"),
            (t("worksheet.labels.total_thickness", "Total Thickness"), f"{i['inv_total_thick']} mm"),
        ], bg="#fffbeb", border="#d97706", label_color="#92400e", value_color="#78350f")

        card(t("worksheet.cards.rr910", "R&R 910 · Mold vol {volume} cm³ x 1.88", volume=f"{i['inv_vol']}"), [
            (t("worksheet.labels.rr910", "R&R 910"), f"{i['rr910_g']} g"),
            (t("worksheet.labels.water", "Water"), f"{i['rr910_water_g']} g"),
        ], bg="#faf5ff", border="#7c3aed", label_color="#6b21a8", value_color="#581c87")

        print_sections = [
            (
                t("worksheet.cards.print_calculations", "3D PRINT CALCULATIONS"),
                [
                    (t("worksheet.labels.base_volume", "Base Volume"), f"{p['base_volume']} cm³"),
                    (t("worksheet.labels.max_z_height", "Max Z Height"), f"{p['max_z']} mm"),
                    (t("worksheet.labels.art_space_volume", "Art Space Volume"), f"{p['art_space_vol']} cm³"),
                    (t("worksheet.labels.actual_art_volume", "Actual Art Volume"), f"{p['actual_art_vol']} cm³"),
                    (t("worksheet.labels.volume_to_max_z", "Volume to Max Z"), f"{p['vol_to_max_z']} cm³"),
                ],
            ),
            (
                t("worksheet.cards.alginate", "ACCU-CAST ALGINATE 570 PGV · {ratio} : 1", ratio=f"{st.session_state['ws_alg_mix_ratio']:.1f}"),
                [
                    (t("worksheet.labels.mold_volume_box_model_z", "Mold Volume (Box - Model + Z)"), f"{a['alg_mold_vol']} cm³"),
                    (t("worksheet.labels.water", "Water"), f"{a['alg_water_g']} g"),
                    (t("worksheet.labels.alginate", "Alginate"), f"{a['alg_alginate_g']} g"),
                    (t("worksheet.labels.mold_thickness", "Mold Thickness"), f"{a['alg_thickness']} mm"),
                    (t("worksheet.labels.total_thickness", "Total Thickness"), f"{a['alg_total_thick']} mm"),
                ],
            ),
            (
                t("worksheet.cards.dry_investment", "DRY INVESTMENT / PLASTER + SILICA · Mold vol {volume} cm³", volume=f"{i['inv_vol']}"),
                [
                    (t("worksheet.labels.mold_volume_box_model_z", "Mold Volume (Box - Model + Z)"), f"{i['inv_vol']} cm³"),
                    (t("worksheet.labels.dry_investment", "Dry Investment"), f"{i['dry_investment']} g"),
                    (t("worksheet.labels.plaster", "Plaster"), f"{i['plaster_g']} g"),
                    (t("worksheet.labels.silica_flour", "Silica Flour"), f"{i['silica_g']} g"),
                    (t("worksheet.labels.water", "Water"), f"{i['inv_water_g']} g"),
                    (t("worksheet.labels.total_thickness", "Total Thickness"), f"{i['inv_total_thick']} mm"),
                ],
            ),
            (
                t("worksheet.cards.rr910", "R&R 910 · Mold vol {volume} cm³ x 1.88", volume=f"{i['inv_vol']}"),
                [
                    (t("worksheet.labels.rr910", "R&R 910"), f"{i['rr910_g']} g"),
                    (t("worksheet.labels.water", "Water"), f"{i['rr910_water_g']} g"),
                ],
            ),
        ]
        report_title = st.session_state["ws_title"].strip() or t("worksheet.title", "Mold Worksheet")
        render_batch_sheet_actions(report_title, st.session_state["ws_job_date"], print_sections)

    elif mold_type == "Silicone + Investment":
        s = calc_silicone(w, d, g["box_volume"], g["model_volume"],
                          st.session_state["ws_si_adjust_zi"],
                          st.session_state["ws_si_mix_ratio"])
        i = calc_investment(w, d, g["mold_vol"], p["max_z"],
                            st.session_state["ws_wall_mm"],
                            st.session_state["ws_inv_adjust_zi"])
        batch_cols = st.columns(3)
        batch_cols[0].metric(t("worksheet.labels.total", "Total"), f"{s['silicone_g']} g")
        batch_cols[1].metric(t("worksheet.labels.part_a", "Part A"), f"{s['part_a']} g")
        batch_cols[2].metric(t("worksheet.labels.dry_investment", "Dry Investment"), f"{i['dry_investment']} g")

        card(t("worksheet.cards.silicone", "SIRATECH SILICONE · ratio {ratio} : 1", ratio=f"{st.session_state['ws_si_mix_ratio']:.1f}"), [
            (t("worksheet.labels.mold_volume_box_model_z", "Mold Volume (Box - Model + Z)"), f"{s['mold_volume_si']} cm³"),
            (t("worksheet.labels.total", "Total"), f"{s['silicone_g']} g"),
            (t("worksheet.labels.part_a", "Part A"), f"{s['part_a']} g"),
            (t("worksheet.labels.part_b", "Part B"), f"{s['part_b']} g"),
        ], bg="#eff6ff", border="#2563eb", label_color="#1e40af", value_color="#1e3a8a")

        card(t("worksheet.cards.dry_investment", "DRY INVESTMENT / PLASTER + SILICA · Mold vol {volume} cm³", volume=f"{i['inv_vol']}"), [
            (t("worksheet.labels.mold_volume_box_model_z", "Mold Volume (Box - Model + Z)"), f"{i['inv_vol']} cm³"),
            (t("worksheet.labels.plaster", "Plaster"), f"{i['plaster_g']} g"),
            (t("worksheet.labels.silica_flour", "Silica Flour"), f"{i['silica_g']} g"),
            (t("worksheet.labels.water", "Water"), f"{i['inv_water_g']} g"),
            (t("worksheet.labels.total_thickness", "Total Thickness"), f"{i['inv_total_thick']} mm"),
        ], bg="#fffbeb", border="#d97706", label_color="#92400e", value_color="#78350f")

        card(t("worksheet.cards.rr910", "R&R 910 · Mold vol {volume} cm³ x 1.88", volume=f"{i['inv_vol']}"), [
            (t("worksheet.labels.rr910", "R&R 910"), f"{i['rr910_g']} g"),
            (t("worksheet.labels.water", "Water"), f"{i['rr910_water_g']} g"),
        ], bg="#faf5ff", border="#7c3aed", label_color="#6b21a8", value_color="#581c87")

        print_sections = [
            (
                t("worksheet.cards.print_calculations", "3D PRINT CALCULATIONS"),
                [
                    (t("worksheet.labels.base_volume", "Base Volume"), f"{p['base_volume']} cm³"),
                    (t("worksheet.labels.max_z_height", "Max Z Height"), f"{p['max_z']} mm"),
                    (t("worksheet.labels.art_space_volume", "Art Space Volume"), f"{p['art_space_vol']} cm³"),
                    (t("worksheet.labels.actual_art_volume", "Actual Art Volume"), f"{p['actual_art_vol']} cm³"),
                    (t("worksheet.labels.volume_to_max_z", "Volume to Max Z"), f"{p['vol_to_max_z']} cm³"),
                ],
            ),
            (
                t("worksheet.cards.silicone", "SIRATECH SILICONE · ratio {ratio} : 1", ratio=f"{st.session_state['ws_si_mix_ratio']:.1f}"),
                [
                    (t("worksheet.labels.mold_volume_box_model_z", "Mold Volume (Box - Model + Z)"), f"{s['mold_volume_si']} cm³"),
                    (t("worksheet.labels.total", "Total"), f"{s['silicone_g']} g"),
                    (t("worksheet.labels.part_a", "Part A"), f"{s['part_a']} g"),
                    (t("worksheet.labels.part_b", "Part B"), f"{s['part_b']} g"),
                ],
            ),
            (
                t("worksheet.cards.dry_investment", "DRY INVESTMENT / PLASTER + SILICA · Mold vol {volume} cm³", volume=f"{i['inv_vol']}"),
                [
                    (t("worksheet.labels.mold_volume_box_model_z", "Mold Volume (Box - Model + Z)"), f"{i['inv_vol']} cm³"),
                    (t("worksheet.labels.dry_investment", "Dry Investment"), f"{i['dry_investment']} g"),
                    (t("worksheet.labels.plaster", "Plaster"), f"{i['plaster_g']} g"),
                    (t("worksheet.labels.silica_flour", "Silica Flour"), f"{i['silica_g']} g"),
                    (t("worksheet.labels.water", "Water"), f"{i['inv_water_g']} g"),
                    (t("worksheet.labels.total_thickness", "Total Thickness"), f"{i['inv_total_thick']} mm"),
                ],
            ),
            (
                t("worksheet.cards.rr910", "R&R 910 · Mold vol {volume} cm³ x 1.88", volume=f"{i['inv_vol']}"),
                [
                    (t("worksheet.labels.rr910", "R&R 910"), f"{i['rr910_g']} g"),
                    (t("worksheet.labels.water", "Water"), f"{i['rr910_water_g']} g"),
                ],
            ),
        ]
        report_title = st.session_state["ws_title"].strip() or t("worksheet.title", "Mold Worksheet")
        render_batch_sheet_actions(report_title, st.session_state["ws_job_date"], print_sections)

# ─────────────────────────────────────────
# Save
# ─────────────────────────────────────────
if save_clicked:
    title = st.session_state["ws_title"].strip()
    if not title:
        st.error(t("errors.worksheet.title_required", "Please enter a title before saving."))
    else:
        job_date_val = st.session_state["ws_job_date"]
        job_date_str = job_date_val.isoformat() if hasattr(job_date_val, "isoformat") else str(job_date_val)
        rec = dict(
            title         = title,
            job_date      = job_date_str,
            created_at    = datetime.now().isoformat(timespec="seconds"),
            mold_type     = st.session_state["ws_mold_type"],
            width_mm      = st.session_state["ws_width_mm"],
            depth_mm      = st.session_state["ws_depth_mm"],
            base_mm       = st.session_state["ws_base_mm"],
            height_mm     = st.session_state["ws_height_mm"],
            stl_volume    = st.session_state["ws_stl_volume"],
            wall_mm       = st.session_state["ws_wall_mm"],
            alg_adjust_zi = st.session_state["ws_alg_adjust_zi"],
            alg_mix_ratio = st.session_state["ws_alg_mix_ratio"],
            si_adjust_zi  = st.session_state["ws_si_adjust_zi"],
            si_mix_ratio  = st.session_state["ws_si_mix_ratio"],
            inv_adjust_zi = st.session_state["ws_inv_adjust_zi"],
            notes         = st.session_state["ws_notes"],
        )
        if loaded_id:
            update_record(loaded_id, rec)
            st.success(t("messages.worksheet.record_updated", "Record updated: {title}", title=title))
        else:
            new_id = save_record(rec)
            st.session_state["ws_loaded_id"] = new_id
            st.success(t("messages.worksheet.record_saved", "Record saved: {title}", title=title))
        st.rerun()
