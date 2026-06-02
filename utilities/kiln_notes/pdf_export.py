from __future__ import annotations

import html
import math
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any


DEPENDENCY_MESSAGE = "PDF export needs the reportlab package. Install the updated requirements to enable it."
MM_TO_POINTS = 72 / 25.4
PRINT_MARGIN_POINTS = 25 * MM_TO_POINTS
STUDIO_BASE_SIDE_MARGIN = 14
STUDIO_BASE_TOP_MARGIN = 14
STUDIO_BASE_BOTTOM_MARGIN = 18
STUDIO_MAIN_LEFT_WIDTH = 258
STUDIO_SHELF_RELEASE_SHIFT = 9
STUDIO_TITLE_BAR_FONT_SIZE = 9.6
STUDIO_SECTION_TITLE_FONT_SIZE = 9.0
STUDIO_LABEL_FONT_SIZE = 7.3
STUDIO_VALUE_FONT_SIZE = 7.1
STUDIO_SMALL_VALUE_FONT_SIZE = 6.5
STUDIO_BOX_TITLE_FONT_SIZE = 7.4
STUDIO_GLASS_HELPER_FONT_SIZE = 6.4
STUDIO_GLASS_ROW_FONT_SIZE = 6.6
STUDIO_SCHEDULE_VALUE_FONT_SIZE = 6.8
STUDIO_NOTE_HELPER_FONT_SIZE = 6.3
STUDIO_NOTE_BODY_FONT_SIZE = 7.2
STUDIO_CHECKBOX_FONT_SIZE = 6.7


@lru_cache(maxsize=1)
def _pdf_font_names() -> dict[str, str]:
    fallback = {
        "regular": "Helvetica",
        "bold": "Helvetica-Bold",
        "italic": "Helvetica-Oblique",
        "bold_italic": "Helvetica-BoldOblique",
    }

    try:
        import reportlab
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ModuleNotFoundError:
        return fallback

    reportlab_font_dir = Path(reportlab.__file__).resolve().parent / "fonts"
    candidates = [
        (
            "KilnPDFArial",
            {
                "regular": Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
                "bold": Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
                "italic": Path("/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
                "bold_italic": Path("/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf"),
            },
        ),
        (
            "KilnPDFDejaVu",
            {
                "regular": Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                "bold": Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                "italic": Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
                "bold_italic": Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf"),
            },
        ),
        (
            "KilnPDFVera",
            {
                "regular": reportlab_font_dir / "Vera.ttf",
                "bold": reportlab_font_dir / "VeraBd.ttf",
                "italic": reportlab_font_dir / "VeraIt.ttf",
                "bold_italic": reportlab_font_dir / "VeraBI.ttf",
            },
        ),
    ]

    for family_name, font_paths in candidates:
        if not all(path.exists() for path in font_paths.values()):
            continue

        font_names = {
            "regular": f"{family_name}-Regular",
            "bold": f"{family_name}-Bold",
            "italic": f"{family_name}-Italic",
            "bold_italic": f"{family_name}-BoldItalic",
        }

        try:
            registered = set(pdfmetrics.getRegisteredFontNames())
            for role, font_name in font_names.items():
                if font_name not in registered:
                    pdfmetrics.registerFont(TTFont(font_name, str(font_paths[role])))
            return font_names
        except Exception:
            continue

    return fallback


def _pdf_font_regular() -> str:
    return _pdf_font_names()["regular"]


def _pdf_font_bold() -> str:
    return _pdf_font_names()["bold"]


def _pdf_font_italic() -> str:
    return _pdf_font_names()["italic"]


def pdf_export_available() -> bool:
    try:
        from reportlab.pdfgen import canvas as _canvas  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def pdf_dependency_message() -> str:
    return DEPENDENCY_MESSAGE


def build_studio_sheet_pdf(document: dict[str, Any]) -> bytes:
    return _build_studio_sheet_portrait(document)


def build_full_record_pdf(document: dict[str, Any]) -> bytes:
    return _build_pdf(document, include_review=True, include_notes=True, include_photos=True, portrait=True)


def _build_studio_sheet_portrait(document: dict[str, Any]) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.lib.utils import ImageReader, simpleSplit
        from reportlab.pdfgen import canvas
        from reportlab.platypus import Paragraph, Table, TableStyle
    except ModuleNotFoundError as exc:
        raise RuntimeError(DEPENDENCY_MESSAGE) from exc

    buffer = BytesIO()
    page_width, page_height = letter
    pdf = canvas.Canvas(buffer, pagesize=letter)

    sample_styles = getSampleStyleSheet()
    styles = {
        "cell_label": ParagraphStyle(
            "StudioCellLabel",
            parent=sample_styles["Normal"],
            fontName=_pdf_font_bold(),
            fontSize=STUDIO_LABEL_FONT_SIZE,
            leading=STUDIO_LABEL_FONT_SIZE + 0.9,
            textColor=colors.black,
        ),
        "cell_value": ParagraphStyle(
            "StudioCellValue",
            parent=sample_styles["Normal"],
            fontName=_pdf_font_bold(),
            fontSize=STUDIO_VALUE_FONT_SIZE + 0.3,
            leading=STUDIO_VALUE_FONT_SIZE + 1.2,
            textColor=colors.black,
        ),
        "small_value": ParagraphStyle(
            "StudioSmallValue",
            parent=sample_styles["Normal"],
            fontName=_pdf_font_regular(),
            fontSize=STUDIO_SMALL_VALUE_FONT_SIZE,
            leading=STUDIO_SMALL_VALUE_FONT_SIZE + 1.0,
            textColor=colors.black,
        ),
        "box_title": ParagraphStyle(
            "StudioBoxTitle",
            parent=sample_styles["Normal"],
            fontName=_pdf_font_bold(),
            fontSize=STUDIO_BOX_TITLE_FONT_SIZE,
            leading=STUDIO_BOX_TITLE_FONT_SIZE + 1.0,
            textColor=colors.black,
        ),
    }

    palette = {
        "border": colors.HexColor("#9ba7b4"),
        "header_fill": colors.HexColor("#d7e7f5"),
        "title_fill": colors.HexColor("#d0d0d0"),
        "schedule_fill": colors.HexColor("#eef8ea"),
        "lookup_fill": colors.HexColor("#e5f7d8"),
        "muted_fill": colors.HexColor("#f8f9fb"),
        "alert": colors.HexColor("#d63c30"),
    }

    left_margin = STUDIO_BASE_SIDE_MARGIN
    content_width = page_width - (left_margin * 2)
    y_top = page_height - STUDIO_BASE_TOP_MARGIN

    original_content_width = page_width - (STUDIO_BASE_SIDE_MARGIN * 2)
    target_content_width = page_width - (PRINT_MARGIN_POINTS * 2)
    scale = target_content_width / original_content_width
    translate_x = PRINT_MARGIN_POINTS - (STUDIO_BASE_SIDE_MARGIN * scale)
    translate_y = (page_height - PRINT_MARGIN_POINTS) - ((page_height - STUDIO_BASE_TOP_MARGIN) * scale)

    pdf.saveState()
    pdf.translate(translate_x, translate_y)
    pdf.scale(scale, scale)

    y_top = _draw_studio_title_bar(pdf, left_margin, y_top, content_width, 18, document, palette)
    y_top -= 4

    main_block_height = 216
    y_top = _draw_studio_main_block(
        pdf,
        document,
        left_margin,
        y_top,
        content_width,
        main_block_height,
        palette,
        colors,
        styles,
        Table,
        TableStyle,
        Paragraph,
    )
    y_top -= 4

    options_height = 70
    y_top = _draw_studio_options_block(pdf, document, left_margin, y_top, content_width, options_height, palette)
    y_top -= 4

    photo_height = 228
    y_top = _draw_studio_photo_box(
        pdf,
        document,
        left_margin,
        y_top,
        content_width,
        photo_height,
        palette,
        ImageReader,
        simpleSplit,
    )
    y_top -= 4

    notes_height = max(80, y_top - STUDIO_BASE_BOTTOM_MARGIN)
    _draw_studio_notes_box(pdf, document, left_margin, y_top, content_width, notes_height, palette, simpleSplit)
    pdf.restoreState()

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _draw_studio_title_bar(
    pdf: Any,
    x: float,
    y_top: float,
    width: float,
    height: float,
    document: dict[str, Any],
    palette: dict[str, Any],
) -> float:
    title_text = _text_value(document.get("studio_title_bar_text") or document.get("title"), empty="Kiln Glass Project Notes")
    if " - " in title_text:
        title_text = title_text.split(" - ", 1)[0]
    glass_profile_text = _text_value(document.get("studio_glass_profile_text"), empty="")
    pdf.setStrokeColor(palette["border"])
    pdf.setFillColor(palette["title_fill"])
    pdf.rect(x, y_top - height, width, height, fill=1, stroke=1)
    pdf.setFillColorRGB(0, 0, 0)
    bold_font = _pdf_font_bold()
    title_y = y_top - height + 5
    pdf.setFont(bold_font, STUDIO_TITLE_BAR_FONT_SIZE)
    pdf.drawString(x + 4, title_y, title_text)
    if glass_profile_text:
        pdf.drawRightString(x + width - 4, title_y, glass_profile_text)
    return y_top - height


def _studio_info_table_data(document: dict[str, Any], styles: dict[str, Any]) -> list[list[Any]]:
    metadata_rows = document.get("metadata_rows") or []
    labels = [row[0] for row in metadata_rows]

    def label(index: int, fallback: str) -> str:
        if index < len(labels):
            return _text_value(labels[index], empty=fallback)
        return fallback

    return [
        [
            _paragraph(label(2, "Record date"), styles["cell_label"]),
            _paragraph(document.get("record_date_text"), styles["cell_value"]),
            _paragraph(label(0, "Project"), styles["cell_label"]),
            _paragraph(document.get("project_text"), styles["cell_value"]),
        ],
        [
            _paragraph(label(3, "Date fired"), styles["cell_label"]),
            _paragraph(document.get("date_fired_text"), styles["cell_value"]),
            _paragraph(label(5, "Process"), styles["cell_label"]),
            _paragraph(document.get("process_text"), styles["cell_value"]),
        ],
        [
            _paragraph(label(4, "Firing #"), styles["cell_label"]),
            _paragraph(document.get("firing_number_text"), styles["cell_value"]),
            _paragraph(label(11, "Delay"), styles["cell_label"]),
            _paragraph(document.get("delay_text"), styles["cell_value"]),
        ],
        [
            _paragraph(label(7, "Target dimensions"), styles["cell_label"]),
            _paragraph(document.get("target_dimensions_text"), styles["cell_value"]),
            _paragraph(label(12, "Start time"), styles["cell_label"]),
            _paragraph(document.get("start_time_text"), styles["cell_value"]),
        ],
        [
            _paragraph(label(8, "Actual dimensions"), styles["cell_label"]),
            _paragraph(document.get("actual_dimensions_text"), styles["cell_value"]),
            _paragraph(label(13, "Start temp"), styles["cell_label"]),
            _paragraph(document.get("start_temp_text"), styles["cell_value"]),
        ],
        [
            _paragraph(label(14, "Kiln opened / turned off at"), styles["cell_label"]),
            _paragraph(document.get("finish_time_text"), styles["cell_value"]),
            _paragraph(label(15, "Open / shutoff temp"), styles["cell_label"]),
            _paragraph(document.get("finish_temp_text"), styles["cell_value"]),
        ],
        [
            _paragraph(label(16, "Observed run time"), styles["cell_label"]),
            _paragraph(document.get("observed_runtime_text", "-"), styles["cell_value"]),
            _paragraph(document.get("schedule_end_label", "Schedule End"), styles["cell_label"]),
            _paragraph(document.get("schedule_end_text"), styles["cell_value"]),
        ],
    ]


def _paragraph(text: Any, style: Any) -> Any:
    from reportlab.platypus import Paragraph

    return Paragraph(_escape_text(text, preserve_breaks=True), style)


def _draw_table_on_canvas(pdf: Any, table: Any, x: float, y_top: float, available_width: float) -> float:
    table.wrapOn(pdf, available_width, 0)
    _, table_height = table.wrap(available_width, 0)
    table.drawOn(pdf, x, y_top - table_height)
    return y_top - table_height


def _draw_studio_main_block(
    pdf: Any,
    document: dict[str, Any],
    x: float,
    y_top: float,
    width: float,
    height: float,
    palette: dict[str, Any],
    colors_mod: Any,
    styles: dict[str, Any],
    table_cls: Any,
    table_style_cls: Any,
    paragraph_cls: Any,
) -> float:
    bottom = y_top - height
    left_width = STUDIO_MAIN_LEFT_WIDTH
    right_width = width - left_width
    schedule_x = x + left_width
    row_date_height = 17
    row_title_height = 18
    row_meta_height = 17
    row_header_height = 15
    row_schedule_height = (height - row_date_height - row_title_height - row_meta_height - row_header_height) / 10

    row_1_bottom = y_top - row_date_height
    row_2_bottom = row_1_bottom - row_title_height
    row_3_bottom = row_2_bottom - row_meta_height
    row_4_bottom = row_3_bottom - row_header_height

    pdf.setStrokeColor(palette["border"])
    pdf.setFillColorRGB(1, 1, 1)
    pdf.rect(x, bottom, width, height, fill=1, stroke=1)
    pdf.line(schedule_x, bottom, schedule_x, y_top)
    pdf.line(x, row_1_bottom, x + width, row_1_bottom)
    pdf.line(x, row_2_bottom, x + width, row_2_bottom)
    pdf.line(x, row_3_bottom, x + width, row_3_bottom)
    pdf.line(x, row_4_bottom, x + width, row_4_bottom)

    left_mid = x + (left_width / 2)
    right_mid = schedule_x + (right_width / 2)
    glass_divider_x = x + 68
    pdf.line(left_mid, row_2_bottom, left_mid, row_3_bottom)
    pdf.line(right_mid, row_2_bottom, right_mid, row_3_bottom)

    pdf.setFillColorRGB(0, 0, 0)
    bold_font = _pdf_font_bold()
    italic_font = _pdf_font_italic()
    pdf.setFont(bold_font, STUDIO_LABEL_FONT_SIZE)
    record_date_label = f"{_text_value(document.get('studio_date_label'), empty='Date')}:"
    project_label = f"{_text_value(document.get('studio_project_label'), empty='Project')}:"
    pdf.drawString(x + 4, row_1_bottom + 4, record_date_label)
    pdf.drawString(schedule_x + 4, row_1_bottom + 4, project_label)
    pdf.setFont(bold_font, STUDIO_VALUE_FONT_SIZE)
    pdf.drawString(x + 4 + pdf.stringWidth(record_date_label, bold_font, STUDIO_LABEL_FONT_SIZE) + 4, row_1_bottom + 4, _text_value(document.get("record_date_text"), empty="-"))
    pdf.drawString(schedule_x + 4 + pdf.stringWidth(project_label, bold_font, STUDIO_LABEL_FONT_SIZE) + 4, row_1_bottom + 4, _text_value(document.get("project_text"), empty="-"))

    pdf.setFont(bold_font, STUDIO_SECTION_TITLE_FONT_SIZE)
    pdf.drawCentredString(x + (left_width / 2), row_2_bottom + 5.5, _text_value(document.get("studio_description_title"), empty="Description"))
    pdf.line(right_mid, row_1_bottom, right_mid, row_2_bottom)
    pdf.setFont(bold_font, STUDIO_LABEL_FONT_SIZE)
    delay_band_label = f"{_text_value(document.get('studio_delay_label'), empty='Delay')}:"
    start_temp_band_label = f"{_text_value(document.get('studio_start_temp_label'), empty='Start Temp')}:"
    pdf.drawString(schedule_x + 4, row_2_bottom + 4, delay_band_label)
    pdf.drawString(right_mid + 4, row_2_bottom + 4, start_temp_band_label)
    pdf.setFont(bold_font, STUDIO_VALUE_FONT_SIZE)
    pdf.drawString(
        schedule_x + 4 + pdf.stringWidth(delay_band_label, bold_font, STUDIO_LABEL_FONT_SIZE) + 4,
        row_2_bottom + 4,
        _text_value(document.get("delay_text"), empty="-"),
    )
    pdf.drawString(
        right_mid + 4 + pdf.stringWidth(start_temp_band_label, bold_font, STUDIO_LABEL_FONT_SIZE) + 4,
        row_2_bottom + 4,
        _text_value(document.get("start_temp_text"), empty="-"),
    )

    pdf.setFont(bold_font, STUDIO_LABEL_FONT_SIZE)
    date_fired_label = f"{_text_value(document.get('studio_date_fired_label'), empty='Date Fired')}:"
    firing_number_label = f"{_text_value(document.get('studio_firing_number_label'), empty='Firing #')}"
    process_label = f"{_text_value(document.get('studio_process_label'), empty='Process')}:"
    start_time_label = f"{_text_value(document.get('studio_start_time_label'), empty='Start Time')}:"
    pdf.drawString(x + 4, row_3_bottom + 4, date_fired_label)
    pdf.drawString(left_mid + 4, row_3_bottom + 4, firing_number_label)
    pdf.drawString(schedule_x + 4, row_3_bottom + 4, process_label)
    pdf.drawString(right_mid + 4, row_3_bottom + 4, start_time_label)
    pdf.setFont(bold_font, STUDIO_VALUE_FONT_SIZE)
    pdf.drawString(x + 4 + pdf.stringWidth(date_fired_label, bold_font, STUDIO_LABEL_FONT_SIZE) + 4, row_3_bottom + 4, _text_value(document.get("date_fired_text"), empty="-"))
    pdf.drawString(left_mid + 4 + pdf.stringWidth(firing_number_label, bold_font, STUDIO_LABEL_FONT_SIZE) + 4, row_3_bottom + 4, _text_value(document.get("firing_number_text"), empty="-"))
    pdf.drawString(schedule_x + 4 + pdf.stringWidth(process_label, bold_font, STUDIO_LABEL_FONT_SIZE) + 4, row_3_bottom + 4, _text_value(document.get("process_text"), empty="-"))
    pdf.drawString(right_mid + 4 + pdf.stringWidth(start_time_label, bold_font, STUDIO_LABEL_FONT_SIZE) + 4, row_3_bottom + 4, _text_value(document.get("start_time_text"), empty="-"))

    pdf.setFont(bold_font, STUDIO_LABEL_FONT_SIZE)
    target_dimensions_label_text = f"{_text_value(document.get('studio_target_dimensions_label'), empty='Target Dimensions')}:"
    pdf.drawString(x + 4, row_4_bottom + 4, target_dimensions_label_text)
    pdf.setFont(bold_font, STUDIO_VALUE_FONT_SIZE)
    target_dimensions_x = x + 4 + pdf.stringWidth(target_dimensions_label_text, bold_font, STUDIO_LABEL_FONT_SIZE) + 6
    pdf.drawString(target_dimensions_x, row_4_bottom + 4, _text_value(document.get("target_dimensions_text"), empty="-"))

    index_width = 26
    time_width = 56
    fill_width = right_width - index_width - time_width
    blue_column_width = fill_width / 3
    blue_start_x = schedule_x + index_width
    time_x = blue_start_x + fill_width

    pdf.setFillColor(palette["header_fill"])
    pdf.rect(blue_start_x, bottom, fill_width, row_3_bottom - bottom, fill=1, stroke=0)
    pdf.setFillColorRGB(0, 0, 0)

    pdf.line(schedule_x + index_width, row_3_bottom, schedule_x + index_width, bottom)
    pdf.line(blue_start_x + blue_column_width, row_3_bottom, blue_start_x + blue_column_width, bottom)
    pdf.line(blue_start_x + (blue_column_width * 2), row_3_bottom, blue_start_x + (blue_column_width * 2), bottom)
    pdf.line(time_x, row_3_bottom, time_x, bottom)
    pdf.line(schedule_x, row_4_bottom, x + width, row_4_bottom)

    pdf.setFont(bold_font, STUDIO_LABEL_FONT_SIZE)
    pdf.drawCentredString(blue_start_x + (blue_column_width / 2), row_4_bottom + 4, _text_value(document.get("studio_rate_label"), empty="Rate"))
    pdf.drawCentredString(
        blue_start_x + blue_column_width + (blue_column_width / 2),
        row_4_bottom + 4,
        _text_value(document.get("studio_temperature_label"), empty="Temperature"),
    )
    pdf.drawCentredString(
        blue_start_x + (blue_column_width * 2) + (blue_column_width / 2),
        row_4_bottom + 4,
        _text_value(document.get("studio_hold_time_label"), empty="Hold Time"),
    )
    pdf.drawCentredString(time_x + (time_width / 2), row_4_bottom + 4, _text_value(document.get("studio_time_label"), empty="Time"))

    glass_rows = [row if isinstance(row, (list, tuple)) else ["", ""] for row in document.get("glass_rows", [])]
    while len(glass_rows) < 9:
        glass_rows.append(["", ""])

    schedule_rows = list(document.get("studio_schedule_rows") or [])
    while len(schedule_rows) < 10:
        schedule_rows.append({"segment": str(len(schedule_rows) + 1), "rate": "", "temperature": "", "hold": "", "end": ""})

    glass_helper_row_top = row_4_bottom - row_schedule_height
    pdf.setFont(bold_font, STUDIO_LABEL_FONT_SIZE)
    glass_label_text = _text_value(document.get("studio_glass_label"), empty="Glass Used:")
    pdf.drawString(x + 4, glass_helper_row_top + 4, glass_label_text)
    helper_x = x + 4 + pdf.stringWidth(glass_label_text, bold_font, STUDIO_LABEL_FONT_SIZE) + 4
    pdf.setFont(italic_font, STUDIO_GLASS_HELPER_FONT_SIZE)
    pdf.drawString(helper_x, glass_helper_row_top + 4, _text_value(document.get("studio_glass_helper_text"), empty=""))
    pdf.setFont(bold_font, STUDIO_GLASS_ROW_FONT_SIZE)
    glass_code_width = max(0, glass_divider_x - x - 8)
    glass_details_x = glass_divider_x + 4
    glass_details_width = max(0, schedule_x - glass_details_x - 4)
    for index, row in enumerate(glass_rows[:9], start=1):
        y_row_top = row_4_bottom - (row_schedule_height * index)
        pdf.line(x, y_row_top, schedule_x, y_row_top)
        glass_code = _text_value(row[0], empty="")
        glass_details = _text_value(row[1], empty="")
        if glass_code:
            wrapped_code = _studio_wrap_lines(glass_code, STUDIO_GLASS_ROW_FONT_SIZE, glass_code_width, 1)
            pdf.drawString(x + 4, y_row_top - row_schedule_height + 4, wrapped_code[0])
        if glass_details:
            wrapped_details = _studio_wrap_lines(glass_details, STUDIO_GLASS_ROW_FONT_SIZE, glass_details_width, 1)
            pdf.drawString(glass_details_x, y_row_top - row_schedule_height + 4, wrapped_details[0])

    current_schedule_top = row_4_bottom
    for row in schedule_rows[:10]:
        next_y = current_schedule_top - row_schedule_height
        pdf.line(schedule_x, next_y, x + width, next_y)
        pdf.setFont(bold_font, STUDIO_LABEL_FONT_SIZE)
        pdf.drawCentredString(schedule_x + (index_width / 2), next_y + 4, _text_value(row.get("segment"), empty="-"))
        pdf.setFont(bold_font, STUDIO_SCHEDULE_VALUE_FONT_SIZE)
        pdf.drawCentredString(blue_start_x + (blue_column_width / 2), next_y + 4, _text_value(row.get("rate"), empty=""))
        pdf.drawCentredString(
            blue_start_x + blue_column_width + (blue_column_width / 2),
            next_y + 4,
            _text_value(row.get("temperature"), empty=""),
        )
        pdf.drawCentredString(
            blue_start_x + (blue_column_width * 2) + (blue_column_width / 2),
            next_y + 4,
            _text_value(row.get("hold"), empty=""),
        )
        pdf.drawCentredString(time_x + (time_width / 2), next_y + 4, _text_value(row.get("end"), empty=""))
        current_schedule_top = next_y

    return bottom


def _studio_glass_table(
    document: dict[str, Any],
    content_width: float,
    styles: dict[str, Any],
    palette: dict[str, Any],
    colors_mod: Any,
    table_cls: Any,
    table_style_cls: Any,
    paragraph_cls: Any,
) -> Any:
    glass_text = _text_value(document.get("glass_text"), empty="-")
    wrapped_lines = _studio_wrap_lines(glass_text, 6.3, content_width - 80, 2)
    if not wrapped_lines:
        wrapped_lines = ["-"]

    rows = [
        [
            paragraph_cls(_escape_text(document.get("glass_title")), styles["cell_label"]),
            paragraph_cls(_escape_text(wrapped_lines[0]), styles["small_value"]),
        ]
    ]
    if len(wrapped_lines) > 1:
        rows.append(
            [
                paragraph_cls("", styles["small_value"]),
                paragraph_cls(_escape_text(wrapped_lines[1]), styles["small_value"]),
            ]
        )

    glass_table = table_cls(
        rows,
        colWidths=[80, content_width - 80],
        rowHeights=[12] * len(rows),
        hAlign="LEFT",
    )
    glass_table.setStyle(
        table_style_cls(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, palette["border"]),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, palette["border"]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("BACKGROUND", (0, 0), (0, -1), colors_mod.HexColor("#f8fafc")),
                ("BACKGROUND", (1, 0), (-1, -1), colors_mod.white),
            ]
        )
    )
    return glass_table


def _studio_schedule_table(
    document: dict[str, Any],
    content_width: float,
    styles: dict[str, Any],
    palette: dict[str, Any],
    colors_mod: Any,
    table_cls: Any,
    table_style_cls: Any,
    paragraph_cls: Any,
) -> Any:
    headers = [
        _text_value(document.get("summary_headers", ["Segment"])[0]),
        _text_value(document.get("schedule_headers", ["", "Rate / hr"])[1]),
        _text_value(document.get("schedule_headers", ["", "", "Target Temp"])[2]),
        _text_value(document.get("schedule_headers", ["", "", "", "Hold Time"])[3]),
        _text_value(document.get("summary_headers", ["", "", "", "", "", "", "", "Hold End"])[7]),
    ]
    schedule_rows = list(document.get("studio_schedule_rows") or [])
    while len(schedule_rows) < 10:
        schedule_rows.append({"segment": str(len(schedule_rows) + 1), "rate": "", "temperature": "", "hold": "", "end": ""})

    data: list[list[Any]] = [
        [paragraph_cls(_escape_text(header), styles["cell_label"]) for header in headers]
    ]
    for row in schedule_rows[:10]:
        data.append(
            [
                paragraph_cls(_escape_text(row.get("segment")), styles["cell_value"]),
                paragraph_cls(_escape_text(row.get("rate")), styles["cell_value"]),
                paragraph_cls(_escape_text(row.get("temperature")), styles["cell_value"]),
                paragraph_cls(_escape_text(row.get("hold")), styles["cell_value"]),
                paragraph_cls(_escape_text(row.get("end")), styles["cell_value"]),
            ]
        )

    col_widths = [44, 112, 112, 112, content_width - 380]
    schedule_table = table_cls(
        data,
        colWidths=col_widths,
        rowHeights=[14] + ([13] * 10),
        hAlign="LEFT",
    )
    schedule_table.setStyle(
        table_style_cls(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, palette["border"]),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, palette["border"]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("BACKGROUND", (0, 0), (0, 0), colors_mod.HexColor("#f8fafc")),
                ("BACKGROUND", (1, 0), (-1, 0), palette["header_fill"]),
                ("BACKGROUND", (1, 1), (-1, -1), palette["schedule_fill"]),
                ("BACKGROUND", (0, 1), (0, -1), colors_mod.white),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (1, 1), (4, -1), "CENTER"),
            ]
        )
    )
    return schedule_table


def _draw_studio_options_block(
    pdf: Any,
    document: dict[str, Any],
    x: float,
    y_top: float,
    width: float,
    height: float,
    palette: dict[str, Any],
) -> float:
    bottom = y_top - height
    pdf.setStrokeColor(palette["border"])
    pdf.setFillColorRGB(1, 1, 1)
    pdf.rect(x, bottom, width, height, fill=1, stroke=1)

    top_section_height = 42
    top_bottom = y_top - top_section_height
    options_divider_x = x + STUDIO_MAIN_LEFT_WIDTH
    info_width = options_divider_x - x
    review_x = options_divider_x
    review_width = width - info_width
    pdf.line(x, top_bottom, x + width, top_bottom)
    pdf.line(review_x, top_bottom, review_x, y_top)

    info_mid_y = y_top - (top_section_height / 2)
    pdf.line(x, info_mid_y, review_x, info_mid_y)
    _draw_studio_value_row(
        pdf,
        x + 4,
        y_top - 6,
        info_width - 8,
        _text_value(document.get("studio_mold_type_label"), empty="Mold type"),
        _text_value(document.get("mold_type_text"), empty="-"),
    )
    _draw_studio_value_row(
        pdf,
        x + 4,
        info_mid_y - 1,
        info_width - 8,
        _text_value(document.get("studio_kiln_label"), empty="Kiln"),
        _text_value(document.get("kiln_text"), empty="-"),
    )

    review_title = _text_value(document.get("studio_double_check_title"), empty="Double Check")
    pdf.setFont(_pdf_font_bold(), STUDIO_LABEL_FONT_SIZE)
    pdf.setFillColorRGB(0, 0, 0)
    pdf.drawCentredString(review_x + (review_width / 2), y_top - 9, review_title)
    review_items = document.get("studio_review_rows") or document.get("review_rows") or []
    left_review_x = review_x + 12
    right_review_x = review_x + (review_width / 2) + 10
    review_row_top = y_top - 19
    if len(review_items) > 0:
        checked = _text_value(review_items[0][1]).lower() not in {"no", "-", ""}
        _draw_checkbox_line(pdf, left_review_x, review_row_top, review_items[0][0], checked)
    if len(review_items) > 1:
        checked = _text_value(review_items[1][1]).lower() not in {"no", "-", ""}
        _draw_checkbox_line(pdf, right_review_x, review_row_top, review_items[1][0], checked)
    if len(review_items) > 2:
        checked = _text_value(review_items[2][1]).lower() not in {"no", "-", ""}
        _draw_checkbox_line(pdf, left_review_x, review_row_top - 12, review_items[2][0], checked)
    if len(review_items) > 3:
        checked = _text_value(review_items[3][1]).lower() not in {"no", "-", ""}
        _draw_checkbox_line(pdf, right_review_x, review_row_top - 12, review_items[3][0], checked)

    lower_mid_x = options_divider_x
    pdf.line(lower_mid_x, bottom, lower_mid_x, top_bottom)

    bottom_title_y = top_bottom - 10
    pdf.setFont(_pdf_font_bold(), STUDIO_BOX_TITLE_FONT_SIZE)
    pdf.drawCentredString(x + ((lower_mid_x - x) / 2), bottom_title_y, _text_value(document.get("studio_shelf_title"), empty="Shelf"))
    pdf.drawCentredString(
        lower_mid_x + ((x + width - lower_mid_x) / 2),
        bottom_title_y,
        _text_value(document.get("studio_shelf_release_title"), empty="Shelf Release"),
    )

    material_options = ["Other", "Mullite", "Fiberboard"]
    selected_material = _text_value(document.get("shelf_material_value"), empty="")
    material_positions = [x + 8, x + 66, x + 128]
    for option_x, option in zip(material_positions, material_options):
        _draw_checkbox_line(pdf, option_x, top_bottom - 18, option, selected_material == option)

    release_options = ["Primer", "Fiber", "ThinFire", "Other"]
    selected_release = _text_value(document.get("shelf_release_value"), empty="")
    release_positions = [
        lower_mid_x + 2 + STUDIO_SHELF_RELEASE_SHIFT,
        lower_mid_x + 60 + STUDIO_SHELF_RELEASE_SHIFT,
        lower_mid_x + 120 + STUDIO_SHELF_RELEASE_SHIFT,
        lower_mid_x + 182 + STUDIO_SHELF_RELEASE_SHIFT,
    ]
    for option_x, option in zip(release_positions, release_options):
        _draw_checkbox_line(pdf, option_x, top_bottom - 18, option, selected_release == option)

    return bottom


def _draw_studio_value_row(pdf: Any, x: float, y_top: float, width: float, label: str, value: str) -> None:
    label_width = min(52, width * 0.42)
    value_x = x + label_width + 3
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont(_pdf_font_bold(), STUDIO_LABEL_FONT_SIZE)
    pdf.drawString(x, y_top - 6, f"{label}:")
    pdf.setFont(_pdf_font_regular(), STUDIO_VALUE_FONT_SIZE)
    pdf.drawString(value_x, y_top - 6, value)


def _draw_studio_photo_box(
    pdf: Any,
    document: dict[str, Any],
    x: float,
    y_top: float,
    width: float,
    height: float,
    palette: dict[str, Any],
    image_reader_cls: Any,
    simple_split: Any,
) -> float:
    header_height = 14
    bottom = y_top - height
    pdf.setStrokeColor(palette["border"])
    pdf.setFillColor(palette["header_fill"])
    pdf.rect(x, y_top - header_height, width, header_height, fill=1, stroke=1)
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont(_pdf_font_bold(), STUDIO_LABEL_FONT_SIZE)
    pdf.drawString(x + 4, y_top - header_height + 4, _text_value(document.get("sketch_photo_title"), empty="Sketch or Photo"))
    pdf.setFillColorRGB(1, 1, 1)
    pdf.rect(x, bottom, width, height - header_height, fill=1, stroke=1)

    photo = document.get("studio_photo") or {}
    photo_bytes = photo.get("bytes")
    image_box_x = x + 8
    image_box_y = bottom + 8
    image_box_w = width - 16
    image_box_h = height - header_height - 16
    if photo_bytes:
        _draw_scaled_image(pdf, photo_bytes, image_box_x, image_box_y, image_box_w, image_box_h, image_reader_cls)
        if photo.get("label"):
            pdf.setFont(_pdf_font_regular(), STUDIO_CHECKBOX_FONT_SIZE)
            pdf.setFillColorRGB(0, 0, 0)
            pdf.drawString(x + 6, bottom + 3, _text_value(photo.get("label"), empty=""))

    return bottom


def _draw_studio_notes_box(
    pdf: Any,
    document: dict[str, Any],
    x: float,
    y_top: float,
    width: float,
    height: float,
    palette: dict[str, Any],
    simple_split: Any,
) -> float:
    header_height = 14
    bottom = y_top - height
    pdf.setStrokeColor(palette["border"])
    pdf.setFillColor(palette["header_fill"])
    pdf.rect(x, y_top - header_height, width, header_height, fill=1, stroke=1)
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont(_pdf_font_bold(), STUDIO_LABEL_FONT_SIZE)
    pdf.drawString(x + 4, y_top - header_height + 4, _text_value(document.get("notes_title"), empty="Notes"))

    body_height = height - header_height
    pdf.setFillColorRGB(1, 1, 1)
    pdf.rect(x, bottom, width, body_height, fill=1, stroke=1)
    text_x = x + 6
    text_y = y_top - header_height - 10

    pdf.setFillColorRGB(0, 0, 0)
    regular_font = _pdf_font_regular()
    pdf.setFont(regular_font, STUDIO_NOTE_HELPER_FONT_SIZE)
    helper_text = _text_value(document.get("studio_notes_helper_text"), empty="")
    helper_lines = simple_split(helper_text, regular_font, STUDIO_NOTE_HELPER_FONT_SIZE, width - 12)
    for line in helper_lines[:2]:
        pdf.drawString(text_x, text_y, line)
        text_y -= 7
    if helper_lines:
        text_y -= 2

    notes_parts = []
    if _text_value(document.get("materials_text"), empty=""):
        notes_parts.append(_text_value(document.get("materials_title"), empty="Materials") + ": " + _text_value(document.get("materials_text"), empty=""))
    if _text_value(document.get("notes_text"), empty=""):
        notes_parts.append(_text_value(document.get("notes_text"), empty=""))
    if notes_parts:
        notes_lines = simple_split("\n\n".join(notes_parts), regular_font, STUDIO_NOTE_BODY_FONT_SIZE, width - 12)
        pdf.setFont(regular_font, STUDIO_NOTE_BODY_FONT_SIZE)
        for line in notes_lines[: max(1, int((text_y - bottom - 6) / 8))]:
            pdf.drawString(text_x, text_y, line)
            text_y -= 8

    return bottom


def _draw_checkbox_line(pdf: Any, x: float, y_top: float, label: Any, checked: bool) -> None:
    box_size = 7
    box_y = y_top - box_size
    pdf.setStrokeColorRGB(0.5, 0.5, 0.5)
    pdf.setFillColorRGB(1, 1, 1)
    pdf.rect(x, box_y, box_size, box_size, fill=1, stroke=1)
    if checked:
        pdf.setStrokeColorRGB(0.1, 0.1, 0.1)
        pdf.line(x + 1.5, box_y + 3.5, x + 3, box_y + 1.5)
        pdf.line(x + 3, box_y + 1.5, x + 6, box_y + 6)
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont(_pdf_font_bold() if checked else _pdf_font_regular(), STUDIO_CHECKBOX_FONT_SIZE)
    pdf.drawString(x + box_size + 4, y_top - 5.5, _text_value(label))


def _draw_scaled_image(
    pdf: Any,
    image_bytes: bytes,
    x: float,
    y: float,
    width: float,
    height: float,
    image_reader_cls: Any,
) -> None:
    try:
        reader = image_reader_cls(BytesIO(image_bytes))
        original_width, original_height = reader.getSize()
        scale = min(width / original_width, height / original_height, 1.0)
        draw_width = original_width * scale
        draw_height = original_height * scale
        draw_x = x + ((width - draw_width) / 2)
        draw_y = y + ((height - draw_height) / 2)
        pdf.drawImage(reader, draw_x, draw_y, width=draw_width, height=draw_height, preserveAspectRatio=True, mask="auto")
    except Exception:
        pdf.setFont(_pdf_font_regular(), 6.5)
        pdf.setFillColorRGB(0.4, 0.4, 0.4)
        pdf.drawCentredString(x + (width / 2), y + (height / 2), "Image unavailable")


def _studio_wrap_lines(text: str, font_size: float, width: float, max_lines: int) -> list[str]:
    from reportlab.lib.utils import simpleSplit

    lines = simpleSplit(text, _pdf_font_regular(), font_size, width)
    if len(lines) <= max_lines:
        return lines

    clipped = lines[:max_lines]
    clipped[-1] = clipped[-1].rstrip(". ") + "..."
    return clipped


def _build_pdf(
    document: dict[str, Any],
    *,
    include_review: bool,
    include_notes: bool,
    include_photos: bool,
    portrait: bool = False,
) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ModuleNotFoundError as exc:
        raise RuntimeError(DEPENDENCY_MESSAGE) from exc

    page_size = letter if portrait else landscape(letter)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=PRINT_MARGIN_POINTS,
        rightMargin=PRINT_MARGIN_POINTS,
        topMargin=PRINT_MARGIN_POINTS,
        bottomMargin=0.55 * inch,
    )

    sample_styles = getSampleStyleSheet()
    title_size = 16 if portrait else 19
    subtitle_size = 8 if portrait else 9
    section_size = 10 if portrait else 11
    label_size = 7.2 if portrait else 8
    body_size = 7.2 if portrait else 8
    note_size = 8 if portrait else 9
    compact_size = 6.5 if portrait else 7
    styles = {
        "title": ParagraphStyle(
            "KilnTitle",
            parent=sample_styles["Title"],
            fontName=_pdf_font_bold(),
            fontSize=title_size,
            leading=title_size + 3,
            textColor=colors.HexColor("#243447"),
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "KilnSubtitle",
            parent=sample_styles["Normal"],
            fontName=_pdf_font_regular(),
            fontSize=subtitle_size,
            leading=subtitle_size + 3,
            textColor=colors.HexColor("#5b6777"),
            spaceAfter=10,
        ),
        "section": ParagraphStyle(
            "KilnSection",
            parent=sample_styles["Heading2"],
            fontName=_pdf_font_bold(),
            fontSize=section_size,
            leading=section_size + 2,
            textColor=colors.HexColor("#243447"),
            spaceBefore=6,
            spaceAfter=6,
        ),
        "label": ParagraphStyle(
            "KilnLabel",
            parent=sample_styles["Normal"],
            fontName=_pdf_font_bold(),
            fontSize=label_size,
            leading=label_size + 2,
            textColor=colors.HexColor("#243447"),
        ),
        "cell": ParagraphStyle(
            "KilnCell",
            parent=sample_styles["Normal"],
            fontName=_pdf_font_regular(),
            fontSize=body_size,
            leading=body_size + 2,
            textColor=colors.HexColor("#243447"),
        ),
        "cell_bold": ParagraphStyle(
            "KilnCellBold",
            parent=sample_styles["Normal"],
            fontName=_pdf_font_bold(),
            fontSize=body_size,
            leading=body_size + 2,
            textColor=colors.HexColor("#243447"),
        ),
        "cell_compact": ParagraphStyle(
            "KilnCellCompact",
            parent=sample_styles["Normal"],
            fontName=_pdf_font_regular(),
            fontSize=compact_size,
            leading=compact_size + 1.6,
            textColor=colors.HexColor("#243447"),
        ),
        "cell_bold_compact": ParagraphStyle(
            "KilnCellBoldCompact",
            parent=sample_styles["Normal"],
            fontName=_pdf_font_bold(),
            fontSize=compact_size,
            leading=compact_size + 1.6,
            textColor=colors.HexColor("#243447"),
        ),
        "note": ParagraphStyle(
            "KilnNote",
            parent=sample_styles["Normal"],
            fontName=_pdf_font_regular(),
            fontSize=note_size,
            leading=note_size + 3,
            textColor=colors.HexColor("#243447"),
        ),
        "muted": ParagraphStyle(
            "KilnMuted",
            parent=sample_styles["Normal"],
            fontName=_pdf_font_regular(),
            fontSize=label_size,
            leading=label_size + 2,
            textColor=colors.HexColor("#6b7280"),
        ),
    }

    content_width = doc.width
    story: list[Any] = []

    story.append(Paragraph(_escape_text(document.get("title")), styles["title"]))
    subtitle = _text_value(document.get("subtitle"), empty="")
    if subtitle:
        story.append(Paragraph(_escape_text(subtitle), styles["subtitle"]))

    metadata_rows = document.get("metadata_rows") or []
    if metadata_rows:
        story.append(_metadata_table(metadata_rows, content_width, styles, colors, compact=portrait))
        story.append(Spacer(1, 0.12 * inch))

    story.extend(
        _section_table(
            title=document.get("glass_title"),
            headers=document.get("glass_headers"),
            rows=document.get("glass_rows"),
            content_width=content_width,
            styles=styles,
            colors=colors,
            compact=portrait,
        )
    )
    story.extend(
        _section_table(
            title=document.get("schedule_title"),
            headers=document.get("schedule_headers"),
            rows=document.get("schedule_rows"),
            content_width=content_width,
            styles=styles,
            colors=colors,
            compact=portrait,
        )
    )

    summary_title = _text_value(document.get("summary_title"), empty="")
    if summary_title:
        story.append(Paragraph(_escape_text(summary_title), styles["section"]))

    summary_message = _text_value(document.get("summary_message"), empty="")
    if summary_message:
        story.append(Paragraph(_escape_text(summary_message), styles["note"]))
        story.append(Spacer(1, 0.08 * inch))

    summary_warnings = [warning for warning in document.get("summary_warnings", []) if _text_value(warning, empty="")]
    for warning in summary_warnings:
        story.append(Paragraph(_escape_text(warning), styles["muted"]))
    if summary_warnings:
        story.append(Spacer(1, 0.08 * inch))

    summary_metrics = document.get("summary_metrics") or []
    if summary_metrics:
        story.append(_metadata_table(summary_metrics, content_width, styles, colors, compact=portrait))
        story.append(Spacer(1, 0.12 * inch))

    if document.get("summary_headers"):
        story.extend(
            _section_table(
                title="",
                headers=document.get("summary_headers"),
                rows=document.get("summary_rows"),
                content_width=content_width,
                styles=styles,
                colors=colors,
                compact=portrait,
                column_width_weights=(
                    [0.75, 1.15, 0.95, 1.0, 1.15, 1.0, 1.15, 1.0, 1.15]
                    if portrait and len(document.get("summary_headers") or []) == 9
                    else None
                ),
            )
        )

    chart_elements = _firing_chart_section(
        document=document,
        content_width=content_width,
        colors=colors,
        inch=inch,
        portrait=portrait,
    )
    if chart_elements:
        story.extend(chart_elements)

    if include_review:
        story.extend(
            _section_table(
                title=document.get("review_title"),
                headers=document.get("review_headers"),
                rows=document.get("review_rows"),
                content_width=content_width,
                styles=styles,
                colors=colors,
                compact=portrait,
            )
        )

    materials_text = _text_value(document.get("materials_text"), empty="")
    if materials_text:
        story.extend(_text_section(document.get("materials_title"), materials_text, styles, inch))

    if include_notes:
        notes_text = _text_value(document.get("notes_text"), empty="")
        if notes_text:
            story.extend(_text_section(document.get("notes_title"), notes_text, styles, inch))

    if include_photos:
        photo_elements = _photo_section(
            document.get("photos_title"),
            document.get("photos") or [],
            styles,
            colors,
            Image,
            ImageReader,
            content_width,
            inch,
        )
        if photo_elements:
            story.append(PageBreak())
            story.extend(photo_elements)

    footer_title = _text_value(document.get("title"), empty="Kiln Glass Project Notes")

    def draw_footer(canvas: Any, _doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(_pdf_font_regular(), 8)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawString(doc.leftMargin, 0.35 * inch, footer_title)
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 0.35 * inch, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buffer.getvalue()


def _metadata_table(
    rows: list[tuple[str, str]],
    content_width: float,
    styles: dict[str, Any],
    colors: Any,
    *,
    compact: bool = False,
) -> Any:
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    normalized = [(label, value) for label, value in rows if _text_value(label, empty="")]
    if not normalized:
        return Spacer(1, 0)

    table_rows: list[list[Any]] = []
    pending_row: list[Any] = []
    for label, value in normalized:
        pending_row.extend(
            [
                Paragraph(_escape_text(label), styles["label"]),
                Paragraph(_escape_text(_text_value(value)), styles["cell"]),
            ]
        )
        if len(pending_row) == 4:
            table_rows.append(pending_row)
            pending_row = []

    if pending_row:
        while len(pending_row) < 4:
            pending_row.extend([Paragraph("", styles["cell"]), Paragraph("", styles["cell"])])
        table_rows.append(pending_row)

    col_widths = [
        content_width * 0.15,
        content_width * 0.35,
        content_width * 0.15,
        content_width * 0.35,
    ]
    table = Table(table_rows, colWidths=col_widths, hAlign="LEFT")
    horizontal_padding = 4 if compact else 6
    vertical_padding = 4 if compact else 5
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f7f9fc"), colors.white]),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d7dee6")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e3e8ee")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), horizontal_padding),
                ("RIGHTPADDING", (0, 0), (-1, -1), horizontal_padding),
                ("TOPPADDING", (0, 0), (-1, -1), vertical_padding),
                ("BOTTOMPADDING", (0, 0), (-1, -1), vertical_padding),
            ]
        )
    )
    return table


def _section_table(
    *,
    title: Any,
    headers: Any,
    rows: Any,
    content_width: float,
    styles: dict[str, Any],
    colors: Any,
    compact: bool = False,
    column_width_weights: list[float] | None = None,
) -> list[Any]:
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    normalized_headers = [str(header) for header in (headers or []) if str(header).strip()]
    if not normalized_headers:
        return []

    normalized_rows = rows or []
    if not normalized_rows:
        normalized_rows = [["-"] * len(normalized_headers)]

    elements: list[Any] = []
    section_title = _text_value(title, empty="")
    if section_title:
        elements.append(Paragraph(_escape_text(section_title), styles["section"]))

    use_compact_cells = compact or len(normalized_headers) >= 6
    header_style = styles["cell_bold_compact"] if use_compact_cells else styles["cell_bold"]
    cell_style = styles["cell_compact"] if use_compact_cells else styles["cell"]
    header_row = [Paragraph(_escape_text(header), header_style) for header in normalized_headers]
    data_rows: list[list[Any]] = [header_row]
    for row in normalized_rows:
        padded_row = list(row)
        if len(padded_row) < len(normalized_headers):
            padded_row.extend([""] * (len(normalized_headers) - len(padded_row)))
        data_rows.append([Paragraph(_escape_text(_text_value(cell)), cell_style) for cell in padded_row[: len(normalized_headers)]])

    if column_width_weights and len(column_width_weights) == len(normalized_headers):
        total_weight = sum(column_width_weights) or len(normalized_headers)
        col_widths = [(content_width * width_weight) / total_weight for width_weight in column_width_weights]
    else:
        col_widths = [content_width / len(normalized_headers)] * len(normalized_headers)

    horizontal_padding = 3 if use_compact_cells else 5
    vertical_padding = 3 if use_compact_cells else 5
    table = Table(data_rows, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9eef5")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#243447")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d7dee6")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e3e8ee")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), horizontal_padding),
                ("RIGHTPADDING", (0, 0), (-1, -1), horizontal_padding),
                ("TOPPADDING", (0, 0), (-1, -1), vertical_padding),
                ("BOTTOMPADDING", (0, 0), (-1, -1), vertical_padding),
            ]
        )
    )
    elements.append(table)
    elements.append(Spacer(1, 10))
    return elements


def _text_section(title: Any, text: str, styles: dict[str, Any], inch: Any) -> list[Any]:
    from reportlab.platypus import Paragraph, Spacer

    section_title = _text_value(title, empty="")
    if not section_title:
        return []

    return [
        Paragraph(_escape_text(section_title), styles["section"]),
        Paragraph(_escape_text(text, preserve_breaks=True), styles["note"]),
        Spacer(1, 0.12 * inch),
    ]


def _photo_section(
    title: Any,
    photos: list[dict[str, Any]],
    styles: dict[str, Any],
    colors: Any,
    image_cls: Any,
    image_reader_cls: Any,
    content_width: float,
    inch: Any,
) -> list[Any]:
    from reportlab.platypus import Paragraph, Spacer

    usable_photos = [photo for photo in photos if photo.get("bytes")]
    if not usable_photos:
        return []

    elements: list[Any] = []
    section_title = _text_value(title, empty="")
    if section_title:
        elements.append(Paragraph(_escape_text(section_title), styles["section"]))

    max_width = content_width
    max_height = 3.2 * inch
    for photo in usable_photos:
        photo_label = _text_value(photo.get("label"), empty="")
        if photo_label:
            elements.append(Paragraph(_escape_text(photo_label), styles["cell_bold"]))

        pdf_image = _flowable_image(photo.get("bytes"), image_cls, image_reader_cls, max_width, max_height)
        if pdf_image is not None:
            elements.append(pdf_image)
        else:
            elements.append(Paragraph(_escape_text(_text_value(photo.get("name"))), styles["muted"]))
        elements.append(Spacer(1, 0.18 * inch))

    return elements


def _firing_chart_section(
    *,
    document: dict[str, Any],
    content_width: float,
    colors: Any,
    inch: Any,
    portrait: bool,
) -> list[Any]:
    from reportlab.platypus import Flowable, Spacer

    chart_points = document.get("chart_points") or []
    if len(chart_points) < 2:
        return []

    chart_height = 2.7 * inch if portrait else 2.9 * inch

    class FiringChartFlowable(Flowable):
        def __init__(self) -> None:
            super().__init__()
            self.width = content_width
            self.height = chart_height

        def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
            return self.width, self.height

        def draw(self) -> None:
            canvas = self.canv
            plot_left = 52
            plot_right = 12
            plot_top = 12
            plot_bottom = 38
            plot_width = max(120, self.width - plot_left - plot_right)
            plot_height = max(90, self.height - plot_top - plot_bottom)
            plot_x = plot_left
            plot_y = plot_bottom

            prepared_points = _prepared_chart_points(chart_points)
            if len(prepared_points) < 2:
                return

            x_min = prepared_points[0]["timestamp"]
            x_max = prepared_points[-1]["timestamp"]
            x_span_seconds = max((x_max - x_min).total_seconds(), 1.0)

            temperature_values = [point["temperature"] for point in prepared_points]
            y_min, y_max, y_ticks = _chart_y_scale(temperature_values)

            canvas.setFillColor(colors.white)
            canvas.setStrokeColor(colors.HexColor("#d7dee6"))
            canvas.rect(0, 0, self.width, self.height, stroke=0, fill=1)

            canvas.setStrokeColor(colors.HexColor("#dfe6ef"))
            canvas.setLineWidth(0.7)
            for tick in y_ticks:
                y_position = plot_y + (((tick - y_min) / max(y_max - y_min, 1.0)) * plot_height)
                canvas.line(plot_x, y_position, plot_x + plot_width, y_position)

            canvas.setStrokeColor(colors.HexColor("#9fb1c5"))
            canvas.setLineWidth(0.9)
            canvas.line(plot_x, plot_y, plot_x + plot_width, plot_y)
            canvas.line(plot_x, plot_y, plot_x, plot_y + plot_height)

            canvas.setFont(_pdf_font_regular(), 6.5)
            canvas.setFillColor(colors.HexColor("#667085"))
            for tick in y_ticks:
                y_position = plot_y + (((tick - y_min) / max(y_max - y_min, 1.0)) * plot_height)
                canvas.drawRightString(plot_x - 6, y_position - 2, _chart_tick_label(tick))

            tick_indices = _chart_label_indices(len(prepared_points), 7)
            for index in tick_indices:
                point = prepared_points[index]
                x_position = plot_x + (((point["timestamp"] - x_min).total_seconds() / x_span_seconds) * plot_width)
                canvas.setStrokeColor(colors.HexColor("#d7dee6"))
                canvas.setLineWidth(0.5)
                canvas.line(x_position, plot_y, x_position, plot_y - 4)
                canvas.setFillColor(colors.HexColor("#667085"))
                canvas.setFont(_pdf_font_regular(), 6.2)
                canvas.drawCentredString(x_position, plot_y - 15, point["time_label"])

            path = canvas.beginPath()
            for index, point in enumerate(prepared_points):
                x_position = plot_x + (((point["timestamp"] - x_min).total_seconds() / x_span_seconds) * plot_width)
                y_position = plot_y + (((point["temperature"] - y_min) / max(y_max - y_min, 1.0)) * plot_height)
                if index == 0:
                    path.moveTo(x_position, y_position)
                else:
                    path.lineTo(x_position, y_position)

            canvas.setStrokeColor(colors.HexColor("#2f6fd5"))
            canvas.setLineWidth(2.1)
            canvas.drawPath(path, stroke=1, fill=0)

            canvas.setFillColor(colors.HexColor("#5a94e6"))
            canvas.setStrokeColor(colors.HexColor("#2f6fd5"))
            canvas.setLineWidth(1)
            for point in prepared_points:
                x_position = plot_x + (((point["timestamp"] - x_min).total_seconds() / x_span_seconds) * plot_width)
                y_position = plot_y + (((point["temperature"] - y_min) / max(y_max - y_min, 1.0)) * plot_height)
                canvas.circle(x_position, y_position, 3.1, stroke=1, fill=1)

            canvas.setFillColor(colors.HexColor("#667085"))
            canvas.setFont(_pdf_font_regular(), 7.2)
            canvas.drawCentredString(plot_x + (plot_width / 2), 8, _text_value(document.get("chart_x_label"), empty="Time"))

            canvas.saveState()
            canvas.translate(10, plot_y + (plot_height / 2))
            canvas.rotate(90)
            canvas.drawCentredString(0, 0, _text_value(document.get("chart_y_label"), empty="Temperature"))
            canvas.restoreState()

    return [Spacer(1, 0.02 * inch), FiringChartFlowable(), Spacer(1, 0.14 * inch)]


def _prepared_chart_points(chart_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for point in chart_points:
        timestamp = _chart_timestamp(point.get("timestamp"))
        if timestamp is None:
            continue
        prepared.append(
            {
                "timestamp": timestamp,
                "time_label": _text_value(point.get("time_label"), empty=timestamp.strftime("%H:%M")),
                "temperature": float(point.get("temperature") or 0.0),
            }
        )

    prepared.sort(key=lambda point: point["timestamp"])
    return prepared


def _chart_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in ("", None):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _chart_y_scale(values: list[float]) -> tuple[float, float, list[float]]:
    if not values:
        return 0.0, 100.0, [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]

    min_value = min(values)
    max_value = max(values)
    if max_value <= min_value:
        max_value = min_value + 100.0

    lower_bound = 0.0 if min_value >= 0 else min_value
    step = _nice_tick_step(max_value - lower_bound)
    y_min = math.floor(lower_bound / step) * step if lower_bound < 0 else 0.0
    y_max = math.ceil(max_value / step) * step
    if y_max <= y_min:
        y_max = y_min + step

    ticks: list[float] = []
    current = y_min
    while current <= (y_max + (step / 10)):
        ticks.append(round(current, 6))
        current += step

    return y_min, y_max, ticks


def _nice_tick_step(value_range: float, target_ticks: int = 6) -> float:
    if value_range <= 0:
        return 100.0

    rough_step = value_range / max(target_ticks - 1, 1)
    magnitude = 10 ** math.floor(math.log10(rough_step))
    residual = rough_step / magnitude
    if residual <= 1:
        nice = 1
    elif residual <= 2:
        nice = 2
    elif residual <= 5:
        nice = 5
    else:
        nice = 10
    return nice * magnitude


def _chart_tick_label(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.1f}"


def _chart_label_indices(point_count: int, max_labels: int) -> list[int]:
    if point_count <= 0:
        return []
    if point_count <= max_labels:
        return list(range(point_count))

    step = (point_count - 1) / max(max_labels - 1, 1)
    indices = {0, point_count - 1}
    for label_index in range(1, max_labels - 1):
        indices.add(int(round(label_index * step)))
    return sorted(indices)


def _flowable_image(
    image_bytes: bytes | None,
    image_cls: Any,
    image_reader_cls: Any,
    max_width: float,
    max_height: float,
) -> Any:
    if not image_bytes:
        return None

    try:
        reader = image_reader_cls(BytesIO(image_bytes))
        width, height = reader.getSize()
        scale = min(max_width / width, max_height / height, 1.0)
        image_stream = BytesIO(image_bytes)
        return image_cls(image_stream, width=width * scale, height=height * scale)
    except Exception:
        return None


def _text_value(value: Any, *, empty: str = "-") -> str:
    if value is None:
        return empty
    text = str(value).strip()
    return text or empty


def _escape_text(value: Any, *, preserve_breaks: bool = False) -> str:
    escaped = html.escape(_text_value(value))
    if preserve_breaks:
        return escaped.replace("\n", "<br/>")
    return escaped
