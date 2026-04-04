from __future__ import annotations

import io
import math
import re
from html import unescape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

PAGE_WIDTH = 1650
PAGE_HEIGHT = 2200
MARGIN = 70
CONTENT_WIDTH = PAGE_WIDTH - (MARGIN * 2)

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRID = (216, 216, 216)
PANEL_BG = (250, 250, 250)
SECTION_BG = (245, 245, 245)
MUTED = (90, 90, 90)
SWATCH_BORDER = (170, 170, 170)

ELEMENT_COLOURS = {
    "Selenium": "#e8a020",
    "Sulfur": "#e8d020",
    "Copper": "#20a0e8",
    "Lead": "#909090",
    "Silver": "#c0c0c0",
    "Gold": "#d4a020",
}

FONT_ROOT = Path("/System/Library/Fonts/Supplemental")


def build_glass_detail_pdf(
    glass_id: str,
    color_name: str,
    family_name: str,
    thickness_mm: float,
    catalog: dict,
    meas_r: dict,
    meas_t: dict,
    reflected_image: Path | None,
    transmitted_image: Path | None,
) -> bytes:
    title_font = _load_font(42, bold=True)
    meta_font = _load_font(22)
    section_font = _load_font(24, bold=True)
    body_font = _load_font(19)
    small_font = _load_font(17)
    badge_font = _load_font(17, bold=True)

    pages: list[Image.Image] = []
    page, draw = _new_page()
    y = MARGIN

    title = f"{glass_id}  {color_name}".strip()
    draw.text((MARGIN, y), title, fill=BLACK, font=title_font)
    y += _text_height(draw, title, title_font) + 12

    meta = f"Family: {family_name}  ·  Reference thickness: {thickness_mm:.1f} mm"
    draw.text((MARGIN, y), meta, fill=MUTED, font=meta_font)
    y += _text_height(draw, meta, meta_font) + 18

    contains, reacts = _contains_and_reacts(catalog)
    y = _draw_badges(draw, y, badge_font, small_font, catalog, contains, reacts)
    y += 18

    panel_gap = 24
    panel_width = (CONTENT_WIDTH - panel_gap) // 2
    panel_height = 690
    _draw_mode_panel(
        page,
        draw,
        MARGIN,
        y,
        panel_width,
        panel_height,
        "Reflected Light",
        reflected_image,
        meas_r,
        section_font,
        body_font,
        small_font,
    )
    _draw_mode_panel(
        page,
        draw,
        MARGIN + panel_width + panel_gap,
        y,
        panel_width,
        panel_height,
        "Transmitted Light",
        transmitted_image,
        meas_t,
        section_font,
        body_font,
        small_font,
    )
    y += panel_height + 28

    max_thickness = max(thickness_mm * 4.0, thickness_mm)
    if meas_r or meas_t:
        curve_height = _curve_section_height(meas_r, meas_t)
        if y + curve_height > PAGE_HEIGHT - MARGIN:
            pages.append(page)
            page, draw = _new_page()
            y = MARGIN

        y = _draw_curves_section(
            draw,
            y,
            thickness_mm,
            max_thickness,
            meas_r,
            meas_t,
            section_font,
            body_font,
            small_font,
        )
        y += 18

    cold_text = _note_to_text(catalog.get("cold_characteristics"))
    work_text = _note_to_text(catalog.get("working_notes"))
    note_sections = [
        ("Cold Characteristics", cold_text),
        ("Working Notes", work_text),
    ]

    for heading, text in note_sections:
        if not text.strip():
            continue
        line_height = _text_height(draw, "Ag", body_font) + 6
        paragraphs = _note_paragraphs(draw, text, body_font, CONTENT_WIDTH - 12)

        if y + 70 > PAGE_HEIGHT - MARGIN:
            pages.append(page)
            page, draw = _new_page()
            y = MARGIN

        y = _draw_notes_heading(draw, y, heading, section_font)

        for paragraph_index, lines in enumerate(paragraphs):
            needed = max(1, len(lines)) * line_height + 6
            if y + needed > PAGE_HEIGHT - MARGIN:
                pages.append(page)
                page, draw = _new_page()
                y = MARGIN
                continued_heading = heading if paragraph_index == 0 else f"{heading} (cont.)"
                y = _draw_notes_heading(draw, y, continued_heading, section_font)

            for line in lines:
                draw.text((MARGIN + 4, y), line, fill=BLACK, font=body_font)
                y += line_height
            y += 6
        y += 18

    pages.append(page)

    buffer = io.BytesIO()
    first, *rest = pages
    first.save(buffer, format="PDF", save_all=True, append_images=rest, resolution=200.0)
    return buffer.getvalue()


def _new_page() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), WHITE)
    return image, ImageDraw.Draw(image)


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                FONT_ROOT / "Arial Bold.ttf",
                "Arial Bold.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                FONT_ROOT / "Arial.ttf",
                "Arial.ttf",
            ]
        )

    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _text_height(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    _, top, _, bottom = draw.textbbox((0, 0), text, font=font)
    return bottom - top


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return default
        text = str(value).strip()
        if text == "" or text.lower() == "nan":
            return default
        return int(float(text))
    except Exception:
        return default


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    clean = value.lstrip("#")
    return tuple(int(clean[i : i + 2], 16) for i in (0, 2, 4))


def _contains_and_reacts(catalog: dict) -> tuple[list[str], list[str]]:
    element_map = {
        "Selenium": "se",
        "Sulfur": "su",
        "Copper": "cu",
        "Lead": "pb",
        "Silver": "ag",
        "Gold": "au",
    }
    reaction_rules = {
        "Selenium": ["Copper", "Lead", "Silver"],
        "Sulfur": ["Copper", "Lead", "Silver"],
        "Copper": ["Selenium", "Sulfur", "Silver"],
        "Lead": ["Selenium", "Sulfur"],
        "Silver": ["Selenium", "Sulfur", "Copper"],
        "Gold": [],
    }
    contains = [label for label, col in element_map.items() if _safe_int(catalog.get(col)) == 1]
    reacts: list[str] = []
    for label in contains:
        for reactive in reaction_rules.get(label, []):
            if reactive not in reacts:
                reacts.append(reactive)
    return contains, reacts


def _draw_badges(
    draw: ImageDraw.ImageDraw,
    y: int,
    badge_font: ImageFont.ImageFont,
    label_font: ImageFont.ImageFont,
    catalog: dict,
    contains: list[str],
    reacts: list[str],
) -> int:
    x = MARGIN
    line_height = 34

    if _safe_int(catalog.get("is_striker")) == 1:
        x = _draw_badge(draw, x, y, "STRIKER", "#e05020", badge_font, min_width=110) + 16

    if contains:
        draw.text((x, y + 6), "Contains:", fill=MUTED, font=label_font)
        x += _text_width(draw, "Contains:", label_font) + 12
        for label in contains:
            x = _draw_badge(draw, x, y, label, ELEMENT_COLOURS.get(label, "#888888"), badge_font) + 8

    if reacts:
        y += line_height
        x = MARGIN
        draw.text((x, y + 6), "May react with:", fill=MUTED, font=label_font)
        x += _text_width(draw, "May react with:", label_font) + 12
        for label in reacts:
            x = _draw_badge(draw, x, y, label, ELEMENT_COLOURS.get(label, "#888888"), badge_font, alpha=0.72) + 8

    return y + line_height


def _draw_badge(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    colour: str,
    font: ImageFont.ImageFont,
    min_width: int = 0,
    alpha: float = 1.0,
) -> int:
    bg = _hex_to_rgb(colour)
    bg = tuple(int(WHITE[idx] + ((bg[idx] - WHITE[idx]) * alpha)) for idx in range(3))
    width = max(min_width, _text_width(draw, label, font) + 20)
    height = 26
    draw.rounded_rectangle((x, y, x + width, y + height), radius=4, fill=bg)
    draw.text(
        (x + (width - _text_width(draw, label, font)) / 2, y + 3),
        label,
        fill=WHITE,
        font=font,
    )
    return x + width


def _draw_mode_panel(
    page: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    title: str,
    image_path: Path | None,
    meas: dict,
    title_font: ImageFont.ImageFont,
    body_font: ImageFont.ImageFont,
    small_font: ImageFont.ImageFont,
) -> None:
    draw.rounded_rectangle((x, y, x + width, y + height), radius=10, outline=GRID, width=1, fill=PANEL_BG)
    draw.text((x + 18, y + 14), title, fill=BLACK, font=title_font)

    image_top = y + 54
    image_height = 360
    _paste_sample_image(page, image_path, x + 18, image_top, width - 36, image_height)

    table_top = image_top + image_height + 16
    _draw_measurement_summary(draw, x + 18, table_top, width - 36, meas, body_font, small_font)


def _paste_sample_image(
    page: Image.Image,
    image_path: Path | None,
    x: int,
    y: int,
    width: int,
    height: int,
) -> None:
    placeholder = Image.new("RGB", (width, height), (248, 248, 248))
    ImageDraw.Draw(placeholder).rounded_rectangle((0, 0, width - 1, height - 1), radius=8, outline=GRID, width=1)
    source = None
    if image_path and image_path.exists():
        try:
            source = Image.open(image_path).convert("RGB")
        except Exception:
            source = None
    if source is None:
        page.paste(placeholder, (x, y))
        return

    fitted = ImageOps.contain(source, (width, height))
    background = Image.new("RGB", (width, height), WHITE)
    left = (width - fitted.width) // 2
    top = (height - fitted.height) // 2
    background.paste(fitted, (left, top))
    border = ImageDraw.Draw(background)
    border.rounded_rectangle((0, 0, width - 1, height - 1), radius=8, outline=GRID, width=1)
    page.paste(background, (x, y))


def _draw_measurement_summary(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    meas: dict,
    body_font: ImageFont.ImageFont,
    small_font: ImageFont.ImageFont,
) -> None:
    headers = ["", "R", "G", "B"]
    values = {
        "RGB": [_safe_int(meas.get("R")), _safe_int(meas.get("G")), _safe_int(meas.get("B"))],
        "HSB": [_safe_int(meas.get("H")), _safe_int(meas.get("S")), _safe_int(meas.get("V"))],
        "η": [
            f"{(_safe_int(meas.get('R')) / 255.0) * 100:.1f}%",
            f"{(_safe_int(meas.get('G')) / 255.0) * 100:.1f}%",
            f"{(_safe_int(meas.get('B')) / 255.0) * 100:.1f}%",
        ],
    }
    col_widths = [90, (width - 90) // 3, (width - 90) // 3, width - 90 - (2 * ((width - 90) // 3))]
    row_height = 42

    cursor_x = x
    for col_index, header in enumerate(headers):
        draw.rectangle((cursor_x, y, cursor_x + col_widths[col_index], y + row_height), fill=SECTION_BG, outline=GRID, width=1)
        if header:
            _draw_centered_text(draw, cursor_x, y, col_widths[col_index], row_height, header, body_font)
        cursor_x += col_widths[col_index]

    row_y = y + row_height
    for row_label, row_values in values.items():
        cursor_x = x
        draw.rectangle((cursor_x, row_y, cursor_x + col_widths[0], row_y + row_height), fill=WHITE, outline=GRID, width=1)
        draw.text((cursor_x + 10, row_y + 9), row_label, fill=BLACK, font=body_font)
        cursor_x += col_widths[0]
        for idx, value in enumerate(row_values):
            draw.rectangle((cursor_x, row_y, cursor_x + col_widths[idx + 1], row_y + row_height), fill=WHITE, outline=GRID, width=1)
            _draw_centered_text(draw, cursor_x, row_y, col_widths[idx + 1], row_height, str(value), small_font)
            cursor_x += col_widths[idx + 1]
        row_y += row_height


def _curve_section_height(meas_r: dict, meas_t: dict) -> int:
    chart_count = 0
    if meas_r:
        chart_count += 2
    if meas_t:
        chart_count += 2
    if chart_count == 0:
        return 0
    rows = (chart_count + 1) // 2
    return 90 + (rows * 400) + ((rows - 1) * 24)


def _draw_curves_section(
    draw: ImageDraw.ImageDraw,
    y: int,
    thickness_mm: float,
    max_thickness: float,
    meas_r: dict,
    meas_t: dict,
    heading_font: ImageFont.ImageFont,
    title_font: ImageFont.ImageFont,
    label_font: ImageFont.ImageFont,
) -> int:
    draw.text((MARGIN, y), "Optical Response Curves", fill=BLACK, font=heading_font)
    y += _text_height(draw, "Optical Response Curves", heading_font) + 6
    subtitle = (
        f"Beer-Lambert extrapolation from reference measurement at {thickness_mm:.1f} mm"
        f"  ·  range: 0 – {max_thickness:.1f} mm"
    )
    draw.text((MARGIN, y), subtitle, fill=MUTED, font=label_font)
    y += _text_height(draw, subtitle, label_font) + 18

    chart_specs = []
    if meas_r:
        chart_specs.append(
            (
                "Reflected Color Shift",
                _rgb_curve_series(meas_r, thickness_mm, max_thickness),
                255.0,
                [0, 64, 128, 192, 255],
            )
        )
        chart_specs.append(
            (
                "Reflected Brightness & Saturation",
                _bs_curve_series(meas_r, thickness_mm, max_thickness),
                100.0,
                [0, 25, 50, 75, 100],
            )
        )
    if meas_t:
        chart_specs.append(
            (
                "Transmitted Color Shift",
                _rgb_curve_series(meas_t, thickness_mm, max_thickness),
                255.0,
                [0, 64, 128, 192, 255],
            )
        )
        chart_specs.append(
            (
                "Transmitted Brightness & Saturation",
                _bs_curve_series(meas_t, thickness_mm, max_thickness),
                100.0,
                [0, 25, 50, 75, 100],
            )
        )

    panel_gap = 24
    panel_width = (CONTENT_WIDTH - panel_gap) // 2
    panel_height = 400

    for idx, (title, series, y_max, y_ticks) in enumerate(chart_specs):
        row = idx // 2
        col = idx % 2
        panel_x = MARGIN + (col * (panel_width + panel_gap))
        panel_y = y + (row * (panel_height + panel_gap))
        _draw_chart_panel(
            draw,
            panel_x,
            panel_y,
            panel_width,
            panel_height,
            title,
            series,
            max_thickness,
            thickness_mm,
            y_max,
            y_ticks,
            title_font,
            label_font,
        )

    rows = (len(chart_specs) + 1) // 2
    return y + (rows * panel_height) + ((rows - 1) * panel_gap)


def _rgb_curve_series(meas: dict, thickness_mm: float, max_thickness: float) -> list[dict]:
    t_values, r_values = _beer_lambert_curve(_safe_int(meas.get("R")), thickness_mm, max_thickness)
    _, g_values = _beer_lambert_curve(_safe_int(meas.get("G")), thickness_mm, max_thickness)
    _, b_values = _beer_lambert_curve(_safe_int(meas.get("B")), thickness_mm, max_thickness)
    return [
        {"label": "R", "color": (214, 48, 49), "t": t_values, "values": r_values},
        {"label": "G", "color": (39, 174, 96), "t": t_values, "values": g_values},
        {"label": "B", "color": (52, 152, 219), "t": t_values, "values": b_values},
    ]


def _bs_curve_series(meas: dict, thickness_mm: float, max_thickness: float) -> list[dict]:
    t_values, brightness = _brightness_curve(_safe_int(meas.get("V")), thickness_mm, max_thickness)
    _, saturation = _saturation_curve(
        _safe_int(meas.get("R")),
        _safe_int(meas.get("G")),
        _safe_int(meas.get("B")),
        thickness_mm,
        max_thickness,
    )
    return [
        {"label": "Brightness", "color": (100, 149, 237), "t": t_values, "values": brightness},
        {"label": "Saturation", "color": (46, 204, 113), "t": t_values, "values": saturation},
    ]


def _beer_lambert_curve(channel_value: float, ref_thickness: float, max_thickness: float, points: int = 120) -> tuple[list[float], list[float]]:
    i0 = 255.0
    cv = max(float(channel_value), 1.0)
    rt = max(float(ref_thickness), 0.01)
    alpha = -math.log(cv / i0) / rt
    t_values = [(max_thickness * idx) / (points - 1) for idx in range(points)]
    values = [max(0.0, min(255.0, i0 * math.exp(-alpha * t_val))) for t_val in t_values]
    return t_values, values


def _brightness_curve(v_value: float, ref_thickness: float, max_thickness: float, points: int = 120) -> tuple[list[float], list[float]]:
    i0 = 100.0
    cv = max(float(v_value), 0.1)
    rt = max(float(ref_thickness), 0.01)
    alpha = -math.log(cv / i0) / rt
    t_values = [(max_thickness * idx) / (points - 1) for idx in range(points)]
    values = [max(0.0, min(100.0, i0 * math.exp(-alpha * t_val))) for t_val in t_values]
    return t_values, values


def _saturation_curve(
    r_value: float,
    g_value: float,
    b_value: float,
    ref_thickness: float,
    max_thickness: float,
    points: int = 120,
) -> tuple[list[float], list[float]]:
    t_values, r_values = _beer_lambert_curve(r_value, ref_thickness, max_thickness, points)
    _, g_values = _beer_lambert_curve(g_value, ref_thickness, max_thickness, points)
    _, b_values = _beer_lambert_curve(b_value, ref_thickness, max_thickness, points)
    saturation: list[float] = []
    for r_val, g_val, b_val in zip(r_values, g_values, b_values):
        cmax = max(r_val, g_val, b_val)
        cmin = min(r_val, g_val, b_val)
        sat = ((cmax - cmin) / cmax * 100.0) if cmax > 0 else 0.0
        saturation.append(max(0.0, min(100.0, sat)))
    return t_values, saturation


def _draw_chart_panel(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    title: str,
    series: list[dict],
    max_thickness: float,
    thickness_mm: float,
    y_max: float,
    y_ticks: list[float],
    title_font: ImageFont.ImageFont,
    label_font: ImageFont.ImageFont,
) -> None:
    draw.rounded_rectangle((x, y, x + width, y + height), radius=10, outline=GRID, width=1, fill=PANEL_BG)
    draw.text((x + 16, y + 14), title, fill=BLACK, font=title_font)

    legend_x = x + 16
    legend_y = y + 48
    for item in series:
        draw.line((legend_x, legend_y + 8, legend_x + 20, legend_y + 8), fill=item["color"], width=4)
        draw.text((legend_x + 28, legend_y), item["label"], fill=BLACK, font=label_font)
        legend_x += 28 + _text_width(draw, item["label"], label_font) + 24

    plot_left = x + 58
    plot_right = x + width - 18
    plot_top = y + 84
    plot_bottom = y + height - 42

    draw.rectangle((plot_left, plot_top, plot_right, plot_bottom), fill=WHITE, outline=GRID, width=1)

    for tick in y_ticks:
        py = _map_y(tick, plot_top, plot_bottom, y_max)
        draw.line((plot_left, py, plot_right, py), fill=(235, 235, 235), width=1)
        label = str(int(tick))
        draw.text((plot_left - _text_width(draw, label, label_font) - 10, py - 8), label, fill=MUTED, font=label_font)

    x_ticks = [0.0, round(max_thickness / 2.0, 1), round(max_thickness, 1)]
    for tick in x_ticks:
        px = _map_x(tick, plot_left, plot_right, max_thickness)
        draw.line((px, plot_top, px, plot_bottom), fill=(240, 240, 240), width=1)
        label = f"{tick:g}"
        draw.text((px - (_text_width(draw, label, label_font) / 2), plot_bottom + 8), label, fill=MUTED, font=label_font)

    ref_x = _map_x(thickness_mm, plot_left, plot_right, max_thickness)
    _draw_dashed_line(draw, ref_x, plot_top, plot_bottom, (150, 150, 150))
    ref_label = f"ref {thickness_mm:.1f}mm"
    draw.text((min(ref_x + 6, plot_right - _text_width(draw, ref_label, label_font)), plot_top + 4), ref_label, fill=MUTED, font=label_font)

    for item in series:
        points = [
            (
                _map_x(t_val, plot_left, plot_right, max_thickness),
                _map_y(val, plot_top, plot_bottom, y_max),
            )
            for t_val, val in zip(item["t"], item["values"])
        ]
        draw.line(points, fill=item["color"], width=3)


def _map_x(value: float, left: int, right: int, x_max: float) -> int:
    if x_max <= 0:
        return left
    return int(left + ((value / x_max) * (right - left)))


def _map_y(value: float, top: int, bottom: int, y_max: float) -> int:
    if y_max <= 0:
        return bottom
    return int(bottom - ((value / y_max) * (bottom - top)))


def _draw_dashed_line(draw: ImageDraw.ImageDraw, x: int, top: int, bottom: int, colour: tuple[int, int, int]) -> None:
    dash = 10
    gap = 6
    current = top
    while current < bottom:
        end = min(current + dash, bottom)
        draw.line((x, current, x, end), fill=colour, width=2)
        current = end + gap


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    text: str,
    font: ImageFont.ImageFont,
) -> None:
    label = text or ""
    draw.text(
        (
            x + (width - _text_width(draw, label, font)) / 2,
            y + (height - _text_height(draw, label, font)) / 2 - 1,
        ),
        label,
        fill=BLACK,
        font=font,
    )


def _note_to_text(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?i)<li\s*>", "• ", text)
    text = re.sub(r"(?i)</li\s*>", "\n", text)
    text = re.sub(r"(?i)<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        probe = f"{current} {word}"
        if _text_width(draw, probe, font) <= max_width:
            current = probe
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_notes_heading(
    draw: ImageDraw.ImageDraw,
    y: int,
    heading: str,
    heading_font: ImageFont.ImageFont,
) -> int:
    draw.text((MARGIN, y), heading, fill=BLACK, font=heading_font)
    return y + _text_height(draw, heading, heading_font) + 10


def _note_paragraphs(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[list[str]]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return [_wrap_text(draw, paragraph.replace("\n", " "), font, max_width) for paragraph in paragraphs]
