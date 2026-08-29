"""
19_Vessel_Mold_Worksheet.py
Planning worksheet for vessel mold material estimates.
"""

from __future__ import annotations

import html
import hashlib
import io
import json
import math
import re
import zipfile
from datetime import date
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageFont

from i18n import format_date, render_app_sidebar, t


st.set_page_config(page_title=t("page.pate_mold.title", "Vessel Mold Worksheet"), layout="wide")
render_app_sidebar()
render_html_frame = getattr(st, "iframe", components.html)
NUMBER_PATTERN = r"([0-9][0-9,]*(?:\.[0-9]+)?)"


def parse_number_token(value: str) -> float:
    return float(value.replace(",", "").strip())


def parse_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    try:
        return parse_number_token(match.group(1))
    except (TypeError, ValueError):
        return None


def parse_vessel_settings(text: str) -> dict:
    base_radius = parse_float(rf"Base radius \(mm\):\s*{NUMBER_PATTERN}", text)
    top_radius = parse_float(rf"Top radius \(mm\):\s*{NUMBER_PATTERN}", text)
    height = parse_float(rf"Height \(mm\):\s*{NUMBER_PATTERN}", text)
    oval_x_scale = parse_float(rf"Oval width scale:\s*{NUMBER_PATTERN}", text) or 1.0
    oval_y_scale = parse_float(rf"Oval depth scale:\s*{NUMBER_PATTERN}", text) or 1.0
    base_z = parse_float(rf"Base Z \(mm\):\s*{NUMBER_PATTERN}", text) or 0.0
    bore_volume = parse_float(
        rf"Estimated internal bore volume:\s*{NUMBER_PATTERN}\s*cm(?:³|3|\^3)?",
        text,
    )
    source_match = re.search(r"Source image:\s*(.+)", text, re.IGNORECASE)
    source_image = source_match.group(1).strip() if source_match else ""

    points: list[tuple[float, float]] = []
    if base_radius is not None:
        points.append((0.0, base_radius))
        if base_z > 0:
            points.append((base_z, base_radius))
    for match in re.finditer(
        rf"Midpoint\s+\d+:\s*height\s*{NUMBER_PATTERN}\s*mm,\s*radius\s*{NUMBER_PATTERN}\s*mm",
        text,
        re.IGNORECASE,
    ):
        points.append((base_z + parse_number_token(match.group(1)), parse_number_token(match.group(2))))
    if height is not None and top_radius is not None:
        points.append((base_z + height, top_radius))

    points = sorted({(round(z, 4), round(r, 4)) for z, r in points})
    return {
        "base_radius": base_radius,
        "top_radius": top_radius,
        "height": height,
        "oval_x_scale": oval_x_scale,
        "oval_y_scale": oval_y_scale,
        "base_z": base_z,
        "bore_volume": bore_volume,
        "source_image": source_image,
        "points": points,
    }


def parse_vessel_setup_json(payload: dict) -> dict:
    values = payload.get("values", payload) if isinstance(payload, dict) else {}
    base_radius = values.get("vessel_base_r")
    top_radius = values.get("vessel_top_r")
    height = values.get("vessel_height")
    oval_x_scale = values.get("vessel_oval_x_scale") or 1.0
    oval_y_scale = values.get("vessel_oval_y_scale") or 1.0
    base_z = values.get("vessel_base_z") or 0.0
    source_image = values.get("vessel_source_image_name") or ""
    bore_volume = values.get("vessel_bore_volume_cm3")
    if bore_volume is None and values.get("vessel_bore_volume_mm3") is not None:
        bore_volume = float(values["vessel_bore_volume_mm3"]) / 1000.0
    if bore_volume is None:
        raise ValueError("Vessel settings JSON is missing vessel_bore_volume_cm3.")

    points: list[tuple[float, float]] = []
    if base_radius is not None:
        base_radius = float(base_radius)
        points.append((0.0, base_radius))
        if float(base_z) > 0:
            points.append((float(base_z), base_radius))
    for item in payload.get("midpoints", []):
        z_frac = float(item.get("z_frac", 0.0))
        radius = float(item.get("radius", base_radius or 0.0))
        if height is not None:
            points.append((float(base_z) + z_frac * float(height), radius))
    if height is not None and top_radius is not None:
        points.append((float(base_z) + float(height), float(top_radius)))

    points = sorted({(round(z, 4), round(r, 4)) for z, r in points})
    return {
        "base_radius": float(base_radius) if base_radius is not None else None,
        "top_radius": float(top_radius) if top_radius is not None else None,
        "height": float(height) if height is not None else None,
        "oval_x_scale": float(oval_x_scale),
        "oval_y_scale": float(oval_y_scale),
        "base_z": float(base_z),
        "bore_volume": float(bore_volume) if bore_volume is not None else None,
        "source_image": source_image,
        "points": points,
    }


def extract_vessel_generator_upload(uploaded_file) -> tuple[str, dict]:
    file_bytes = uploaded_file.getvalue()
    file_name = uploaded_file.name or ""
    lower_name = file_name.lower()
    if lower_name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            names = set(zf.namelist())
            if "vessel_settings.json" in names:
                payload = json.loads(zf.read("vessel_settings.json").decode("utf-8"))
                return "", parse_vessel_setup_json(payload)
            if "vessel_settings.txt" in names:
                text = zf.read("vessel_settings.txt").decode("utf-8", errors="replace")
                return text, parse_vessel_settings(text)
            raise ValueError("Build bundle does not contain vessel_settings.txt or vessel_settings.json.")
    if lower_name.endswith(".json"):
        payload = json.loads(file_bytes.decode("utf-8"))
        return "", parse_vessel_setup_json(payload)
    text = file_bytes.decode("utf-8", errors="replace")
    return text, parse_vessel_settings(text)


def frustum_profile_volume_cm3(
    points: list[tuple[float, float]],
    offset_mm: float = 0.0,
    oval_x_scale: float = 1.0,
    oval_y_scale: float = 1.0,
) -> float:
    if len(points) < 2:
        return 0.0
    volume_mm3 = 0.0
    for (z1, r1), (z2, r2) in zip(points, points[1:]):
        h = z2 - z1
        if h <= 0:
            continue
        radius_1 = max(0.0, r1 + offset_mm)
        radius_2 = max(0.0, r2 + offset_mm)
        volume_mm3 += math.pi * h * (radius_1**2 + radius_1 * radius_2 + radius_2**2) / 3.0
    return volume_mm3 * float(oval_x_scale) * float(oval_y_scale) / 1000.0


def fmt_cm3(value: float) -> str:
    return f"{value:,.1f} cm³"


def fmt_g(value: float) -> str:
    return f"{value:,.1f} g"


def _batch_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
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


def build_pate_print_html(title: str, job_date, sections: list[tuple[str, list[tuple[str, str]]]]) -> str:
    safe_title = html.escape(title.strip() or t("page.pate_mold.title", "Vessel Mold Worksheet"))
    safe_date = html.escape(format_date(job_date.isoformat() if hasattr(job_date, "isoformat") else str(job_date)))
    section_html = []
    for section_title, rows in sections:
        body = "".join(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{html.escape(value)}</td>"
            "</tr>"
            for label, value in rows
        )
        section_html.append(f"<section><h2>{html.escape(section_title)}</h2><table>{body}</table></section>")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{safe_title} - Batch Sheet</title>
<style>
  @page {{ size: letter portrait; margin: 0.42in; }}
  body {{
    color: #1f2937;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 11px;
    line-height: 1.2;
    margin: 18px;
  }}
  header {{ border-bottom: 2px solid #111827; margin-bottom: 12px; padding-bottom: 8px; }}
  h1 {{ font-size: 20px; line-height: 1.05; margin: 0 0 3px; }}
  .date {{ color: #4b5563; font-size: 10px; }}
  main {{ display: grid; gap: 10px 16px; grid-template-columns: 1fr 1fr; }}
  section {{ break-inside: avoid; margin: 0; }}
  h2 {{
    border-bottom: 1px solid #d1d5db;
    font-size: 10px;
    letter-spacing: .04em;
    margin: 0 0 4px;
    padding-bottom: 3px;
    text-transform: uppercase;
  }}
  table {{ border-collapse: collapse; width: 100%; }}
  td {{ border-bottom: 1px solid #e5e7eb; padding: 4px 0; vertical-align: top; }}
  td:last-child {{ font-weight: 700; text-align: right; white-space: nowrap; }}
  .actions {{ margin-bottom: 12px; }}
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
    body {{ font-size: 10px; margin: 0; }}
    .actions {{ display: none; }}
    h1 {{ font-size: 18px; }}
    h2 {{ font-size: 9px; }}
    td {{ padding: 3px 0; }}
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


def build_pate_batch_pdf(title: str, job_date, sections: list[tuple[str, list[tuple[str, str]]]]) -> bytes:
    # The PDF is a 200-DPI raster image, so 34 px prints at 12.24 pt.
    min_pdf_font_px = 34
    page_w, page_h = 1700, 2200
    margin = 70
    card_gap = 22
    page = Image.new("RGB", (page_w, page_h), "white")
    draw = ImageDraw.Draw(page)
    title_font = _batch_font(54, bold=True)
    date_font = _batch_font(min_pdf_font_px)
    section_font = _batch_font(42, bold=True)
    label_font = _batch_font(min_pdf_font_px)
    value_font = _batch_font(min_pdf_font_px, bold=True)
    grid = (205, 213, 223)
    colors = [
        ((248, 250, 252), (100, 116, 139), (71, 85, 105), (15, 23, 42)),
        ((240, 253, 244), (22, 163, 74), (22, 101, 52), (20, 83, 45)),
        ((255, 251, 235), (217, 119, 6), (146, 64, 14), (120, 53, 15)),
    ]

    safe_title = title.strip() or t("page.pate_mold.title", "Vessel Mold Worksheet")
    date_text = format_date(job_date.isoformat() if hasattr(job_date, "isoformat") else str(job_date))
    draw.text((margin, margin), safe_title, fill=(15, 23, 42), font=title_font)
    draw.text((margin, margin + 66), date_text, fill=(75, 85, 99), font=date_font)
    y = margin + 120
    card_w = page_w - (margin * 2)
    table_pad = 42
    row_h = 58

    for idx, (section_title, rows) in enumerate(sections):
        bg, accent, label_color, value_color = colors[min(idx, len(colors) - 1)]
        card_h = 24 + 58 + (len(rows) * row_h) + 26
        draw.rounded_rectangle((margin, y, margin + card_w, y + card_h), radius=8, fill=bg)
        draw.rectangle((margin, y, margin + 7, y + card_h), fill=accent)
        table_x = margin + table_pad
        table_w = card_w - (table_pad * 2)
        draw.text((table_x, y + 20), section_title.upper(), fill=accent, font=section_font)
        table_y = y + 82
        divider_x = table_x + int(table_w * 0.6)
        draw.rectangle((table_x, table_y, table_x + table_w, table_y + len(rows) * row_h), outline=grid, width=1)
        draw.line((divider_x, table_y, divider_x, table_y + len(rows) * row_h), fill=grid, width=1)
        for row_idx, (label, value) in enumerate(rows):
            row_y = table_y + row_idx * row_h
            if row_idx:
                draw.line((table_x, row_y, table_x + table_w, row_y), fill=grid, width=1)
            text_y = row_y + 10
            draw.text((table_x + 3, text_y), label, fill=label_color, font=label_font)
            value_w = _font_width(draw, value, value_font)
            draw.text((table_x + table_w - value_w - 3, text_y), value, fill=value_color, font=value_font)
        y += card_h + card_gap

    buffer = io.BytesIO()
    page.save(buffer, format="PDF", resolution=200.0)
    return buffer.getvalue()


def render_pate_batch_actions(title: str, job_date, sections: list[tuple[str, list[tuple[str, str]]]], enabled: bool = True) -> None:
    export_html = build_pate_print_html(title, job_date, sections)
    pdf_bytes = build_pate_batch_pdf(title, job_date, sections)
    safe_filename = re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_") or "vessel_mold"
    print_payload = html.escape(export_html, quote=True)
    disabled_attr = "" if enabled else "disabled"
    disabled_style = "" if enabled else "opacity: 0.45; cursor: not-allowed;"
    click_handler = (
        """
                const oldFrame = document.getElementById('vessel-mold-batch-sheet-print-frame');
                if (oldFrame) oldFrame.remove();
                const frame = document.createElement('iframe');
                frame.id = 'vessel-mold-batch-sheet-print-frame';
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
            onclick="{click_handler}"
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
        width="stretch",
        disabled=not enabled,
    )


PATE_DEFAULTS = {
    "pate_mold_project_title": "",
    "pate_mold_date": date.today(),
    "pate_settings_text": "",
    "pate_bore_volume_cm3": 0.0,
    "pate_face_thickness_mm": 15.0,
    "pate_jacket_thickness_mm": 15.0,
    "pate_overage_pct": 15.0,
    "pate_manual_face_volume_cm3": 0.0,
    "pate_manual_jacket_volume_cm3": 0.0,
    "pate_jacket_stiffener": "Grog mix",
    "pate_mold_notes": "",
    "pate_imported_vessel_json": {"points": []},
}

for key, value in PATE_DEFAULTS.items():
    st.session_state.setdefault(key, value)


def reset_pate_state() -> None:
    for key, value in PATE_DEFAULTS.items():
        st.session_state[key] = value
    st.session_state.pop("pate_bore_source_text", None)
    st.session_state.pop("pate_last_vessel_upload_signature", None)
    st.session_state["pate_mold_upload_nonce"] = st.session_state.get("pate_mold_upload_nonce", 0) + 1


def serialize_pate_value(value):
    if isinstance(value, date):
        return value.isoformat()
    return value


def current_pate_payload() -> dict:
    return {
        "schema": "glass-toolkit.vessel-mold-worksheet",
        "version": 1,
        "values": {
            key: serialize_pate_value(st.session_state.get(key, default))
            for key, default in PATE_DEFAULTS.items()
        },
    }


def current_pate_json_bytes() -> bytes:
    return json.dumps(current_pate_payload(), indent=2, sort_keys=True).encode("utf-8")


if st.session_state.pop("pate_pending_reset", False):
    reset_pate_state()


st.title(t("page.pate_mold.title", "Vessel Mold Worksheet"))
st.caption(
    t(
        "page.pate_mold.caption",
        "Plan vessel mold volume, face coat, and jacket coat material volumes.",
    )
)

st.divider()

st.subheader(t("page.pate_mold.sections.project", "Project"))
project_col, date_col = st.columns([2, 1])
with project_col:
    st.text_input(
        t("page.pate_mold.fields.project_title", "Project title"),
        placeholder=t("page.pate_mold.placeholders.project_title", "e.g. Vessel Mold"),
        key="pate_mold_project_title",
    )
with date_col:
    st.date_input(
        t("page.pate_mold.fields.date", "Date"),
        format="YYYY/MM/DD",
        key="pate_mold_date",
    )

with st.expander(t("page.pate_mold.sections.import", "Import Vessel Model Generator settings"), expanded=True):
    uploaded = st.file_uploader(
        t("page.pate_mold.fields.settings_file", "Upload vessel_settings.txt, vessel_settings.json, or a build ZIP"),
        type=["txt", "json", "zip"],
        key=f"pate_mold_settings_upload_{st.session_state.get('pate_mold_upload_nonce', 0)}",
    )
    st.caption(
        t(
            "page.pate_mold.files.public_storage_note",
            "Projects are stored in your downloaded files, not in a shared server database.",
        )
    )
    action_cols = st.columns(2)
    with action_cols[0]:
        if st.button(t("worksheet.actions.new", "+ New"), key="pate_new_project", width="stretch"):
            st.session_state["pate_pending_reset"] = True
            st.rerun()
    with action_cols[1]:
        if st.button(t("worksheet.actions.reset", "Reset"), key="pate_reset_project", width="stretch"):
            st.session_state["pate_pending_reset"] = True
            st.rerun()

if uploaded is not None:
    upload_bytes = uploaded.getvalue()
    upload_signature = hashlib.sha256(upload_bytes).hexdigest()
    settings_text, uploaded_parsed = extract_vessel_generator_upload(uploaded)
    if st.session_state.get("pate_last_vessel_upload_signature") != upload_signature:
        st.session_state["pate_last_vessel_upload_signature"] = upload_signature
        st.session_state["pate_settings_text"] = settings_text
        if uploaded_parsed["bore_volume"] is not None:
            st.session_state["pate_bore_volume_cm3"] = float(uploaded_parsed["bore_volume"])
            st.session_state["pate_bore_source_text"] = settings_text
        if settings_text:
            st.session_state["pate_imported_vessel_json"] = {"points": []}
        else:
            st.session_state["pate_bore_source_text"] = ""
            st.session_state["pate_imported_vessel_json"] = uploaded_parsed
        st.rerun()

parsed: dict = (
    parse_vessel_settings(st.session_state.get("pate_settings_text", ""))
    if st.session_state.get("pate_settings_text")
    else st.session_state.get("pate_imported_vessel_json", {"points": []})
)
settings_source = st.session_state.get("pate_settings_text", "")
if parsed.get("bore_volume") is not None and st.session_state.get("pate_bore_source_text") != settings_source:
    st.session_state["pate_bore_volume_cm3"] = float(parsed["bore_volume"])
    st.session_state["pate_bore_source_text"] = settings_source
if st.session_state.get("pate_settings_text"):
    if parsed["points"]:
        st.success(
            t(
                "page.pate_mold.messages.settings_loaded",
                "Loaded vessel profile with {count} radius points.",
                count=len(parsed["points"]),
            )
        )
    else:
        st.warning(
            t(
                "page.pate_mold.messages.settings_no_profile",
                "Settings file loaded, but no usable vessel profile was found.",
            )
        )

st.subheader(t("page.pate_mold.sections.workflow", "Workflow"))
st.markdown(
    t(
        "page.pate_mold.body.workflow",
        """
1. Cast the vessel bore in alginate.
2. Flip the alginate positive upside down.
3. Apply the face coat over the inverted alginate.
4. Apply the jacket coat over the face coat.
5. Demold and remove the alginate to create the vessel mold cavity.
""",
    )
)

st.subheader(t("page.pate_mold.sections.volume", "Volume Estimate"))
vol_cols = st.columns(4)
with vol_cols[0]:
    bore_volume_cm3 = st.number_input(
        t("page.pate_mold.fields.bore_volume", "Bore/model volume (cm³)"),
        min_value=0.0,
        step=1.0,
        key="pate_bore_volume_cm3",
        help=t("page.pate_mold.help.bore_volume", "Internal bore volume from the vessel generator. This is the alginate positive volume reference."),
    )
with vol_cols[1]:
    face_thickness_mm = st.number_input(
        t("page.pate_mold.fields.face_thickness", "Face coat thickness (mm)"),
        min_value=0.0,
        value=15.0,
        step=1.0,
        key="pate_face_thickness_mm",
    )
with vol_cols[2]:
    jacket_thickness_mm = st.number_input(
        t("page.pate_mold.fields.jacket_thickness", "Jacket coat thickness (mm)"),
        min_value=0.0,
        value=15.0,
        step=1.0,
        key="pate_jacket_thickness_mm",
    )
with vol_cols[3]:
    overage_pct = st.number_input(
        t("page.pate_mold.fields.overage", "Overage (%)"),
        min_value=0.0,
        value=15.0,
        step=5.0,
        key="pate_overage_pct",
    )

points = parsed.get("points") or []
if points:
    oval_x_scale = parsed.get("oval_x_scale", 1.0)
    oval_y_scale = parsed.get("oval_y_scale", 1.0)
    profile_volume_cm3 = frustum_profile_volume_cm3(points, 0.0, oval_x_scale, oval_y_scale)
    volume_at_face_cm3 = frustum_profile_volume_cm3(points, face_thickness_mm, oval_x_scale, oval_y_scale)
    volume_at_jacket_cm3 = frustum_profile_volume_cm3(points, face_thickness_mm + jacket_thickness_mm, oval_x_scale, oval_y_scale)
    face_volume_cm3 = max(0.0, volume_at_face_cm3 - profile_volume_cm3)
    jacket_volume_cm3 = max(0.0, volume_at_jacket_cm3 - volume_at_face_cm3)
    source_note = parsed.get("source_image") or t("page.pate_mold.labels.settings_file", "settings file")

    st.caption(
        t(
            "page.pate_mold.caption.profile_basis",
            "Estimate based on imported vessel profile from {source}. Bore volume is kept as the reference model volume.",
            source=source_note,
        )
    )
else:
    face_volume_cm3 = st.number_input(
        t("page.pate_mold.fields.manual_face_volume", "Manual face coat estimate (cm³)"),
        min_value=0.0,
        step=1.0,
        key="pate_manual_face_volume_cm3",
    )
    jacket_volume_cm3 = st.number_input(
        t("page.pate_mold.fields.manual_jacket_volume", "Manual jacket coat estimate (cm³)"),
        min_value=0.0,
        step=1.0,
        key="pate_manual_jacket_volume_cm3",
    )
    st.caption(
        t(
            "page.pate_mold.caption.manual_basis",
            "Upload vessel_settings.txt to calculate coat volumes from the vessel profile, or enter manual planning estimates.",
        )
    )

overage_multiplier = 1.0 + (overage_pct / 100.0)
face_batch_cm3 = face_volume_cm3 * overage_multiplier
jacket_batch_cm3 = jacket_volume_cm3 * overage_multiplier
total_batch_cm3 = face_batch_cm3 + jacket_batch_cm3

metric_cols = st.columns(4)
metric_cols[0].metric(t("page.pate_mold.metrics.bore", "Bore/model"), fmt_cm3(bore_volume_cm3))
metric_cols[1].metric(t("page.pate_mold.metrics.face", "Face coat"), fmt_cm3(face_volume_cm3))
metric_cols[2].metric(t("page.pate_mold.metrics.jacket", "Jacket coat"), fmt_cm3(jacket_volume_cm3))
metric_cols[3].metric(t("page.pate_mold.metrics.batch_total", "Batch total with overage"), fmt_cm3(total_batch_cm3))

summary_rows = [
    (t("page.pate_mold.metrics.bore", "Bore/model"), fmt_cm3(bore_volume_cm3)),
    (t("page.pate_mold.metrics.face", "Face coat"), fmt_cm3(face_volume_cm3)),
    (t("page.pate_mold.metrics.jacket", "Jacket coat"), fmt_cm3(jacket_volume_cm3)),
    (t("page.pate_mold.fields.face_thickness", "Face coat thickness (mm)"), f"{face_thickness_mm:.1f} mm"),
    (t("page.pate_mold.fields.jacket_thickness", "Jacket coat thickness (mm)"), f"{jacket_thickness_mm:.1f} mm"),
    (t("page.pate_mold.fields.overage", "Overage (%)"), f"{overage_pct:.1f}%"),
    (t("page.pate_mold.metrics.batch_total", "Batch total with overage"), fmt_cm3(total_batch_cm3)),
]

st.subheader(t("page.pate_mold.sections.materials", "Material Planning"))
st.caption(
    t(
        "page.pate_mold.caption.weight_basis",
        "Batch weights use the planning equivalence 1 cm³ = 1 g before recipe ratios are applied.",
    )
)
face_col, jacket_col = st.columns(2)
with face_col:
    with st.container(border=True):
        st.markdown(f"### {t('page.pate_mold.sections.face_coat', 'Face Coat')}")
        face_weight_g = face_batch_cm3
        face_dry_mix_g = face_weight_g * (2.0 / 3.0)
        face_water_g = face_weight_g * (1.0 / 3.0)
        face_plaster_g = face_dry_mix_g / 2.0
        face_silica_g = face_dry_mix_g / 2.0
        face_material_rows = [
            (t("page.pate_mold.labels.estimated_volume", "Estimated coat volume"), fmt_cm3(face_volume_cm3)),
            (t("page.pate_mold.labels.batch_volume", "Batch volume with overage"), fmt_cm3(face_batch_cm3)),
            (t("page.pate_mold.labels.batch_weight", "Estimated batch weight"), fmt_g(face_weight_g)),
            (t("page.pate_mold.materials.casting_plaster", "Casting plaster"), fmt_g(face_plaster_g)),
            (t("page.pate_mold.materials.silica_flour", "295 mesh silica flour"), fmt_g(face_silica_g)),
            (t("page.pate_mold.materials.water", "Water"), fmt_g(face_water_g)),
        ]
        st.write(t("page.pate_mold.labels.estimated_volume", "Estimated coat volume"), f"**{fmt_cm3(face_volume_cm3)}**")
        st.write(t("page.pate_mold.labels.batch_volume", "Batch volume with overage"), f"**{fmt_cm3(face_batch_cm3)}**")
        st.write(t("page.pate_mold.labels.batch_weight", "Estimated batch weight"), f"**{fmt_g(face_weight_g)}**")
        st.table(
            {
                t("page.pate_mold.labels.material", "Material"): [
                    face_material_rows[3][0],
                    face_material_rows[4][0],
                    face_material_rows[5][0],
                ],
                t("page.pate_mold.labels.weight", "Weight"): [
                    face_material_rows[3][1],
                    face_material_rows[4][1],
                    face_material_rows[5][1],
                ],
            }
        )
        st.caption(
            t(
                "page.pate_mold.caption.face_formula",
                "Face coat formula: 1 part casting plaster + 1 part 295 mesh silica flour by weight makes the dry investment mix. Use 2 parts dry investment mix to 1 part water by weight.",
            )
        )
with jacket_col:
    with st.container(border=True):
        st.markdown(f"### {t('page.pate_mold.sections.jacket_coat', 'Jacket Coat')}")
        jacket_stiffener = st.radio(
            t("page.pate_mold.fields.jacket_stiffener", "Stiffener"),
            [
                t("page.pate_mold.options.jacket_stiffener_grog", "Grog mix"),
                t("page.pate_mold.options.jacket_stiffener_fiberglass", "Fiberglass strips"),
            ],
            horizontal=True,
            key="pate_jacket_stiffener",
        )
        jacket_weight_g = jacket_batch_cm3
        st.write(t("page.pate_mold.labels.estimated_volume", "Estimated coat volume"), f"**{fmt_cm3(jacket_volume_cm3)}**")
        st.write(t("page.pate_mold.labels.batch_volume", "Batch volume with overage"), f"**{fmt_cm3(jacket_batch_cm3)}**")
        st.write(t("page.pate_mold.labels.batch_weight", "Estimated batch weight"), f"**{fmt_g(jacket_weight_g)}**")

        if jacket_stiffener == t("page.pate_mold.options.jacket_stiffener_fiberglass", "Fiberglass strips"):
            jacket_dry_mix_g = jacket_weight_g * (2.0 / 3.0)
            jacket_water_g = jacket_weight_g * (1.0 / 3.0)
            jacket_plaster_g = jacket_dry_mix_g / 2.0
            jacket_silica_g = jacket_dry_mix_g / 2.0
            jacket_material_rows = [
                (t("page.pate_mold.labels.estimated_volume", "Estimated coat volume"), fmt_cm3(jacket_volume_cm3)),
                (t("page.pate_mold.labels.batch_volume", "Batch volume with overage"), fmt_cm3(jacket_batch_cm3)),
                (t("page.pate_mold.labels.batch_weight", "Estimated batch weight"), fmt_g(jacket_weight_g)),
                (t("page.pate_mold.fields.jacket_stiffener", "Stiffener"), t("page.pate_mold.options.jacket_stiffener_fiberglass", "Fiberglass strips")),
                (t("page.pate_mold.materials.casting_plaster", "Casting plaster"), fmt_g(jacket_plaster_g)),
                (t("page.pate_mold.materials.silica_flour", "295 mesh silica flour"), fmt_g(jacket_silica_g)),
                (t("page.pate_mold.materials.water", "Water"), fmt_g(jacket_water_g)),
                (t("page.pate_mold.materials.fiberglass_strips", "Fiberglass strips"), t("page.pate_mold.labels.cut_to_fit", "cut to fit")),
            ]
            st.table(
                {
                    t("page.pate_mold.labels.material", "Material"): [
                        jacket_material_rows[4][0],
                        jacket_material_rows[5][0],
                        jacket_material_rows[6][0],
                        jacket_material_rows[7][0],
                    ],
                    t("page.pate_mold.labels.weight", "Weight"): [
                        jacket_material_rows[4][1],
                        jacket_material_rows[5][1],
                        jacket_material_rows[6][1],
                        jacket_material_rows[7][1],
                    ],
                }
            )
            st.caption(
                t(
                    "page.pate_mold.caption.jacket_fiberglass_formula",
                    "Fiberglass jacket formula: soak cut-to-fit fiberglass strips with investment slurry. Slurry is 1 part casting plaster + 1 part 295 mesh silica flour by weight, mixed as 2 parts dry investment to 1 part water.",
                )
            )
        else:
            jacket_investment_g = jacket_weight_g * (2.0 / 4.0)
            jacket_grog_mix_g = jacket_weight_g * (1.0 / 4.0)
            jacket_water_g = jacket_weight_g * (1.0 / 4.0)
            jacket_plaster_g = jacket_investment_g / 2.0
            jacket_silica_g = jacket_investment_g / 2.0
            jacket_each_grog_g = jacket_grog_mix_g / 3.0
            jacket_material_rows = [
                (t("page.pate_mold.labels.estimated_volume", "Estimated coat volume"), fmt_cm3(jacket_volume_cm3)),
                (t("page.pate_mold.labels.batch_volume", "Batch volume with overage"), fmt_cm3(jacket_batch_cm3)),
                (t("page.pate_mold.labels.batch_weight", "Estimated batch weight"), fmt_g(jacket_weight_g)),
                (t("page.pate_mold.fields.jacket_stiffener", "Stiffener"), t("page.pate_mold.options.jacket_stiffener_grog", "Grog mix")),
                (t("page.pate_mold.materials.casting_plaster", "Casting plaster"), fmt_g(jacket_plaster_g)),
                (t("page.pate_mold.materials.silica_flour", "295 mesh silica flour"), fmt_g(jacket_silica_g)),
                (t("page.pate_mold.materials.grog_50", "Grog - 50 mesh"), fmt_g(jacket_each_grog_g)),
                (t("page.pate_mold.materials.grog_60", "Grog - 60 mesh"), fmt_g(jacket_each_grog_g)),
                (t("page.pate_mold.materials.grog_100", "Grog - 100 mesh"), fmt_g(jacket_each_grog_g)),
                (t("page.pate_mold.materials.water", "Water"), fmt_g(jacket_water_g)),
            ]
            st.table(
                {
                    t("page.pate_mold.labels.material", "Material"): [
                        jacket_material_rows[4][0],
                        jacket_material_rows[5][0],
                        jacket_material_rows[6][0],
                        jacket_material_rows[7][0],
                        jacket_material_rows[8][0],
                        jacket_material_rows[9][0],
                    ],
                    t("page.pate_mold.labels.weight", "Weight"): [
                        jacket_material_rows[4][1],
                        jacket_material_rows[5][1],
                        jacket_material_rows[6][1],
                        jacket_material_rows[7][1],
                        jacket_material_rows[8][1],
                        jacket_material_rows[9][1],
                    ],
                }
            )
            st.caption(
                t(
                    "page.pate_mold.caption.jacket_formula",
                    "Jacket coat formula: 2 parts dry investment mix, 1 part grog mix, and 1 part water by weight. Dry investment is equal parts casting plaster and 295 mesh silica flour. Grog mix is split equally across 50, 60, and 100 mesh grog until a different ratio is specified.",
                )
            )

batch_sections = [
    (t("page.pate_mold.sections.volume", "Volume Estimate"), summary_rows),
    (t("page.pate_mold.sections.face_coat", "Face Coat"), face_material_rows),
    (t("page.pate_mold.sections.jacket_coat", "Jacket Coat"), jacket_material_rows),
]
batch_title = st.session_state["pate_mold_project_title"].strip() or t("page.pate_mold.title", "Vessel Mold Worksheet")
render_pate_batch_actions(batch_title, st.session_state["pate_mold_date"], batch_sections, enabled=True)

st.subheader(t("page.pate_mold.sections.notes", "Notes"))
st.text_area(
    t("page.pate_mold.fields.notes", "Notes"),
    placeholder=t(
        "page.pate_mold.placeholders.notes",
        "Capture face coat recipe, jacket coat recipe, firing notes, or material source notes...",
    ),
    key="pate_mold_notes",
    height=160,
)

st.divider()
action_col, status_col = st.columns([1, 2])
with action_col:
    setup_filename = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        st.session_state["pate_mold_project_title"].strip() or "vessel_mold",
    ).strip("_")
    st.download_button(
        t("page.pate_mold.actions.download_setup_json", "Download Vessel Mold JSON"),
        data=current_pate_json_bytes(),
        file_name=f"{setup_filename}_vessel_mold_settings.json",
        mime="application/json",
        type="primary",
        width="stretch",
        key="pate_download_project_json",
    )

with status_col:
    st.caption(
        t(
            "page.pate_mold.messages.local_file_storage",
            "Vessel mold projects are saved as local JSON files for public use.",
        )
    )
