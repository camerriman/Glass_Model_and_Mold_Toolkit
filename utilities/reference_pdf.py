from __future__ import annotations

import io
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

PAGE_WIDTH = 1650
PAGE_HEIGHT = 2200
MARGIN = 70
TITLE_GAP = 16
LEGEND_GAP = 20
SECTION_GAP = 18
HEADER_HEIGHT = 42
ROW_HEIGHT = 46

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRID = (216, 216, 216)
HEADER_BG = (74, 74, 74)
ALT_ROW = (249, 249, 249)
LEGEND_BG = (245, 245, 245)
LEGEND_BORDER = (221, 221, 221)
SWATCH_BORDER = (170, 170, 170)
META_COLOUR = (68, 68, 68)
HEADER_GROUP_DIVIDER = (216, 216, 216)
ROW_GROUP_DIVIDER = (168, 168, 168)

FONT_ROOT = Path("/System/Library/Fonts/Supplemental")


def build_reference_pdf(
    family_name: str,
    meta_text: str,
    rows: Sequence[dict],
    element_cols: Sequence[tuple[str, str]],
    element_colours: dict[str, str],
    reaction_cols: dict[str, set[str]],
    reactive_badge_colour: str,
) -> bytes:
    title_font = _load_font(40, bold=True)
    meta_font = _load_font(20)
    legend_font = _load_font(18)
    section_font = _load_font(24, bold=True)
    header_font = _load_font(18, bold=True)
    cell_font = _load_font(18)
    badge_font = _load_font(17, bold=True)
    id_font = _load_font(18)

    pages: list[Image.Image] = []
    page, draw = _new_page()
    y = MARGIN

    title = f"{family_name} Glass Reference"
    draw.text((MARGIN, y), title, fill=BLACK, font=title_font)
    y += _text_height(draw, title, title_font) + TITLE_GAP
    draw.text((MARGIN, y), meta_text, fill=META_COLOUR, font=meta_font)
    y += _text_height(draw, meta_text, meta_font) + LEGEND_GAP
    y = _draw_legend(
        draw,
        y,
        legend_font,
        badge_font,
        element_colours,
        reactive_badge_colour,
    )
    y += SECTION_GAP

    inner_width = PAGE_WIDTH - (MARGIN * 2)
    id_width = 120
    swatch_width = 68
    num_width = 76
    elem_width = 58
    colour_width = inner_width - (id_width + swatch_width + (6 * num_width) + (6 * elem_width))
    column_widths = [
        id_width,
        colour_width,
        swatch_width,
        num_width,
        num_width,
        num_width,
        num_width,
        num_width,
        num_width,
        elem_width,
        elem_width,
        elem_width,
        elem_width,
        elem_width,
        elem_width,
    ]
    table_headers = ["No.", "Color", "", "R", "G", "B", "H", "S", "B"] + [
        label for _, label in element_cols
    ]

    def new_page() -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
        next_page, next_draw = _new_page()
        return next_page, next_draw, MARGIN

    def add_page(current_page: Image.Image) -> None:
        pages.append(current_page)

    def ensure_space(current_y: int, needed: int) -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
        nonlocal page, draw
        if current_y + needed <= PAGE_HEIGHT - MARGIN:
            return page, draw, current_y
        add_page(page)
        page, draw, current_y = new_page()
        return page, draw, current_y

    for mode_index, (mode_title, suffix) in enumerate((("Transmitted Values", "t"), ("Reflected Values", "r"))):
        if mode_index > 0:
            add_page(page)
            page, draw, y = new_page()
            y = _draw_legend(
                draw,
                y,
                legend_font,
                badge_font,
                element_colours,
                reactive_badge_colour,
            )
            y += SECTION_GAP

        page, draw, y = ensure_space(y, 40 + HEADER_HEIGHT + ROW_HEIGHT)
        draw.text((MARGIN, y), mode_title, fill=BLACK, font=section_font)
        y += _text_height(draw, mode_title, section_font) + 10
        y = _draw_table_header(draw, y, column_widths, table_headers, header_font)

        for index, row in enumerate(rows):
            page, draw, y = ensure_space(y, ROW_HEIGHT)
            if y == MARGIN:
                draw.text((MARGIN, y), mode_title, fill=BLACK, font=section_font)
                y += _text_height(draw, mode_title, section_font) + 10
                y = _draw_table_header(draw, y, column_widths, table_headers, header_font)

            reactive = _reactive_cols(row, element_cols, reaction_cols)
            y = _draw_row(
                draw,
                y,
                row,
                suffix,
                index,
                column_widths,
                element_cols,
                element_colours,
                reactive_badge_colour,
                reactive,
                id_font,
                cell_font,
                badge_font,
            )

        y += SECTION_GAP

    add_page(page)

    buffer = io.BytesIO()
    first, *rest = pages
    first.save(buffer, format="PDF", save_all=True, append_images=rest, resolution=200.0)
    return buffer.getvalue()


def _new_page() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    page = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), WHITE)
    return page, ImageDraw.Draw(page)


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                FONT_ROOT / "Arial Bold.ttf",
                "Arial Bold.ttf",
                FONT_ROOT / "HelveticaNeueDeskInterface.ttc",
            ]
        )
    else:
        candidates.extend(
            [
                FONT_ROOT / "Arial.ttf",
                "Arial.ttf",
                FONT_ROOT / "Helvetica.ttc",
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


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 2,
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
            continue
        lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break

    remaining_words = words[len(" ".join(lines + [current]).split()):]
    if remaining_words:
        current = f"{current} {' '.join(remaining_words)}".strip()

    while _text_width(draw, current, font) > max_width and len(current) > 1:
        current = current[:-2].rstrip() + "…"

    lines.append(current)
    return lines[:max_lines]


def _draw_legend(
    draw: ImageDraw.ImageDraw,
    y: int,
    legend_font: ImageFont.ImageFont,
    badge_font: ImageFont.ImageFont,
    element_colours: dict[str, str],
    reactive_badge_colour: str,
) -> int:
    box_height = 92
    box = (MARGIN, y, PAGE_WIDTH - MARGIN, y + box_height)
    draw.rounded_rectangle(box, radius=8, fill=LEGEND_BG, outline=LEGEND_BORDER, width=1)

    cursor_x = MARGIN + 18
    line_one_y = y + 16
    line_two_y = y + 52

    draw.text((cursor_x, line_one_y), "Legend", fill=BLACK, font=badge_font)
    cursor_x += _text_width(draw, "Legend", badge_font) + 24
    draw.text((cursor_x, line_one_y), "● = Striker glass", fill=BLACK, font=legend_font)
    cursor_x += _text_width(draw, "● = Striker glass", legend_font) + 28
    cursor_x = _draw_badge_with_text(
        draw,
        cursor_x,
        line_one_y - 4,
        "R",
        reactive_badge_colour,
        "May react with selected element",
        badge_font,
        legend_font,
    )

    cursor_x = MARGIN + 18
    draw.text((cursor_x, line_two_y), "Elements:", fill=BLACK, font=badge_font)
    cursor_x += _text_width(draw, "Elements:", badge_font) + 20

    for short_label, full_name in [
        ("Se", "Selenium"),
        ("S", "Sulfur"),
        ("Cu", "Copper"),
        ("Pb", "Lead"),
        ("Ag", "Silver"),
        ("Au", "Gold"),
    ]:
        cursor_x = _draw_badge_with_text(
            draw,
            cursor_x,
            line_two_y - 4,
            short_label,
            element_colours[short_label],
            full_name,
            badge_font,
            legend_font,
        )
        cursor_x += 12

    return y + box_height


def _draw_badge_with_text(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    colour: str,
    text: str,
    badge_font: ImageFont.ImageFont,
    text_font: ImageFont.ImageFont,
) -> int:
    badge_w = max(34, _text_width(draw, label, badge_font) + 18)
    badge_h = 24
    badge_rgb = _hex_to_rgb(colour)
    draw.rounded_rectangle((x, y, x + badge_w, y + badge_h), radius=4, fill=badge_rgb)
    badge_text_y = y + (badge_h - _text_height(draw, label, badge_font)) // 2 - 1
    draw.text((x + (badge_w - _text_width(draw, label, badge_font)) / 2, badge_text_y), label, fill=WHITE, font=badge_font)
    text_x = x + badge_w + 10
    draw.text((text_x, y + 1), f"= {text}", fill=BLACK, font=text_font)
    return text_x + _text_width(draw, f"= {text}", text_font)


def _draw_table_header(
    draw: ImageDraw.ImageDraw,
    y: int,
    column_widths: Sequence[int],
    headers: Sequence[str],
    font: ImageFont.ImageFont,
) -> int:
    x = MARGIN
    for width, label in zip(column_widths, headers):
        cell = (x, y, x + width, y + HEADER_HEIGHT)
        draw.rectangle(cell, fill=HEADER_BG, outline=GRID, width=1)
        text_w = _text_width(draw, label, font)
        text_h = _text_height(draw, label, font)
        draw.text(
            (x + (width - text_w) / 2, y + (HEADER_HEIGHT - text_h) / 2 - 1),
            label,
            fill=WHITE,
            font=font,
        )
        x += width
    divider_x = _group_divider_x(column_widths)
    draw.line((divider_x, y, divider_x, y + HEADER_HEIGHT), fill=HEADER_GROUP_DIVIDER, width=3)
    return y + HEADER_HEIGHT


def _draw_row(
    draw: ImageDraw.ImageDraw,
    y: int,
    row: dict,
    suffix: str,
    index: int,
    column_widths: Sequence[int],
    element_cols: Sequence[tuple[str, str]],
    element_colours: dict[str, str],
    reactive_badge_colour: str,
    reactive_cols: set[str],
    id_font: ImageFont.ImageFont,
    cell_font: ImageFont.ImageFont,
    badge_font: ImageFont.ImageFont,
) -> int:
    x = MARGIN
    row_fill = ALT_ROW if index % 2 == 0 else WHITE
    for width in column_widths:
        draw.rectangle((x, y, x + width, y + ROW_HEIGHT), fill=row_fill, outline=GRID, width=1)
        x += width

    values = [
        str(row.get("cat_id", "")),
        _colour_label(row),
        ("swatch", row.get(f"r_{suffix}"), row.get(f"g_{suffix}"), row.get(f"b_{suffix}")),
        str(_safe_int(row.get(f"r_{suffix}"), dash=True)),
        str(_safe_int(row.get(f"g_{suffix}"), dash=True)),
        str(_safe_int(row.get(f"b_{suffix}"), dash=True)),
        str(_safe_int(row.get(f"h_{suffix}"), dash=True)),
        str(_safe_int(row.get(f"s_{suffix}"), dash=True)),
        str(_safe_int(row.get(f"v_{suffix}"), dash=True)),
    ]

    x = MARGIN
    for column_index, (width, value) in enumerate(zip(column_widths[:9], values)):
        if column_index == 0:
            _draw_centered_text(draw, x, y, width, ROW_HEIGHT, value, id_font)
        elif column_index == 1:
            _draw_wrapped_cell(draw, x, y, width, ROW_HEIGHT, value, cell_font)
        elif column_index == 2:
            _draw_swatch(draw, x, y, width, ROW_HEIGHT, value[1], value[2], value[3])
        else:
            _draw_centered_text(draw, x, y, width, ROW_HEIGHT, value, cell_font)
        x += width

    for col_key, col_label in element_cols:
        width = column_widths[9 + list(element_cols).index((col_key, col_label))]
        present = _safe_int(row.get(col_key), dash=False) == 1
        badge_label = None
        badge_colour = None
        if present:
            badge_label = col_label
            badge_colour = element_colours[col_label]
        elif col_key in reactive_cols:
            badge_label = "R"
            badge_colour = reactive_badge_colour
        if badge_label:
            _draw_badge(draw, x, y, width, ROW_HEIGHT, badge_label, badge_colour, badge_font)
        x += width

    divider_x = _group_divider_x(column_widths)
    draw.line((divider_x, y, divider_x, y + ROW_HEIGHT), fill=ROW_GROUP_DIVIDER, width=3)

    return y + ROW_HEIGHT


def _group_divider_x(column_widths: Sequence[int]) -> int:
    return MARGIN + sum(column_widths[:6])


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
    text_w = _text_width(draw, label, font)
    text_h = _text_height(draw, label, font)
    draw.text(
        (x + (width - text_w) / 2, y + (height - text_h) / 2 - 1),
        label,
        fill=BLACK,
        font=font,
    )


def _draw_wrapped_cell(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    text: str,
    font: ImageFont.ImageFont,
) -> None:
    lines = _wrap_text(draw, text, font, width - 14, max_lines=2)
    line_height = _text_height(draw, "Ag", font) + 2
    total_height = len(lines) * line_height
    start_y = y + (height - total_height) / 2 - 1
    for idx, line in enumerate(lines):
        draw.text((x + 8, start_y + (idx * line_height)), line, fill=BLACK, font=font)


def _draw_swatch(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    r: object,
    g: object,
    b: object,
) -> None:
    if any(value is None or str(value).strip().lower() in {"", "nan"} for value in (r, g, b)):
        return
    fill = (_safe_int(r), _safe_int(g), _safe_int(b))
    draw.rectangle(
        (x + 1, y + 1, x + width - 1, y + height - 1),
        fill=fill,
    )


def _draw_badge(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    label: str,
    colour: str,
    font: ImageFont.ImageFont,
) -> None:
    badge_w = max(32, _text_width(draw, label, font) + 16)
    badge_h = 24
    left = x + (width - badge_w) / 2
    top = y + (height - badge_h) / 2
    draw.rounded_rectangle(
        (left, top, left + badge_w, top + badge_h),
        radius=4,
        fill=_hex_to_rgb(colour),
    )
    text_w = _text_width(draw, label, font)
    text_h = _text_height(draw, label, font)
    draw.text(
        (left + (badge_w - text_w) / 2, top + (badge_h - text_h) / 2 - 1),
        label,
        fill=WHITE,
        font=font,
    )


def _colour_label(row: dict) -> str:
    name = str(row.get("color_name", "") or "")
    if _safe_int(row.get("is_striker"), dash=False) == 1:
        return f"{name} ●"
    return name


def _reactive_cols(
    row: dict,
    element_cols: Sequence[tuple[str, str]],
    reaction_cols: dict[str, set[str]],
) -> set[str]:
    present = {col for col, _ in element_cols if _safe_int(row.get(col), dash=False) == 1}
    reactive: set[str] = set()
    for col in present:
        reactive.update(reaction_cols.get(col, set()))
    return reactive - present


def _safe_int(value: object, dash: bool = False) -> int | str:
    if value is None:
        return "—" if dash else 0
    text = str(value).strip()
    if text == "" or text.lower() == "nan":
        return "—" if dash else 0
    try:
        return int(float(text))
    except Exception:
        return "—" if dash else 0


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    clean = value.lstrip("#")
    return tuple(int(clean[i : i + 2], 16) for i in (0, 2, 4))
