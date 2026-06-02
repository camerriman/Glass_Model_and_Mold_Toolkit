# 9_Opalescent_Reference.py
# Printable reference sheet — Opalescent glass family
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from i18n import render_app_sidebar, t as tr, translate_family_name

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.append(str(APP_ROOT))

from utilities.reference_pdf import build_reference_pdf

DB_PATH  = APP_ROOT / "data" / "glass_library.sqlite"

FAMILY_CODE  = "3"
FAMILY_NAME  = "Tint"
FAMILY_DISPLAY = translate_family_name(FAMILY_CODE, FAMILY_NAME)
CURRENT_PAGE_PATH = f"pages/{Path(__file__).name}"
RETURN_LABEL = tr("page.reference.return_label", "{family} Reference", family=FAMILY_DISPLAY)
DETAIL_PAGE_URL = "Glass_Detail"

ELEMENT_COLS = [
    ("se", "Se"),
    ("su", "S"),
    ("cu", "Cu"),
    ("pb", "Pb"),
    ("ag", "Ag"),
    ("au", "Au"),
]

ELEMENT_COLOURS = {
    "Se": "#e8a020", "S":  "#e8d020", "Cu": "#20a0e8",
    "Pb": "#909090", "Ag": "#c0c0c0", "Au": "#d4a020",
}
REACTIVE_BADGE_COLOUR = "#c83c32"

REACTION_COLS = {
    "se": {"cu", "pb", "ag"},
    "su": {"cu", "pb", "ag"},
    "cu": {"se", "su", "ag"},
    "pb": {"se", "su"},
    "ag": {"se", "su", "cu"},
    "au": set(),
}

SORT_OPTIONS = [
    ("cat_id", "Product ID"),
    ("color_name", "Color name"),
    ("r", "R value"),
    ("g", "G value"),
    ("b", "B value"),
    ("h", "Hue (H)"),
    ("s", "Saturation (S)"),
    ("v", "Brightness (HSB B)"),
    ("is_striker", "Striker"),
    ("se", "Selenium (Se)"),
    ("su", "Sulfur (S)"),
    ("cu", "Copper (Cu)"),
    ("pb", "Lead (Pb)"),
    ("ag", "Silver (Ag)"),
    ("au", "Gold (Au)"),
]

NUMERIC_SORT_FIELDS = {"r", "g", "b", "h", "s", "v"}
FLAG_SORT_FIELDS = {"is_striker", "se", "su", "cu", "pb", "ag", "au"}

st.set_page_config(page_title=tr("page.reference.return_label", "{family} Reference", family=FAMILY_DISPLAY), layout="wide")
render_app_sidebar()

PRINT_ROOT_ID = f"reference-print-root-{FAMILY_CODE}"
PRINT_WINDOW_CSS = """
body {
    margin: 0.35in;
    color: #000;
    font-family: sans-serif;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}
.print-title {
    font-size: 12pt;
    font-weight: 700;
    margin: 0 0 0.04in 0;
}
.print-meta {
    font-size: 7.8pt;
    color: #444;
    margin: 0 0 0.12in 0;
}
.reference-wrap {
    width: 100%;
}
.reference-table {
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
    font-family: sans-serif;
    font-size: 7.4pt;
}
.reference-table th,
.reference-table td {
    border: 1px solid #d8d8d8;
    vertical-align: middle;
}
.reference-table thead {
    display: table-header-group;
}
.reference-table tbody tr {
    page-break-inside: avoid;
    break-inside: avoid;
}
.reference-table thead th {
    background: #4a4a4a !important;
    color: #fff !important;
    font-weight: 700;
    line-height: 1.15;
    white-space: nowrap;
    word-break: keep-all;
    overflow-wrap: normal;
    font-size: 7.2pt;
    padding: 3px 4px;
}
.reference-table td {
    font-size: 7.2pt;
    padding: 3px 4px;
}
.reference-table .col-id { width: 64px; }
.reference-table .col-swatch { width: 34px; }
.reference-table .col-num { width: 34px; }
.reference-table .col-elem { width: 30px; }
.reference-table .id-cell {
    font-family: monospace;
    white-space: nowrap;
}
.reference-table .color-cell {
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
}
.reference-table .num-cell,
.reference-table .swatch-cell,
.reference-table .badge-cell {
    text-align: center;
    white-space: nowrap;
    word-break: keep-all;
    overflow-wrap: normal;
}
.reference-table .cell-center {
    min-height: 1.35rem;
    display: flex;
    align-items: center;
    justify-content: center;
}
.reference-table .swatch-chip {
    width: 24px;
    height: 16px;
    margin: 0 auto;
    border: 1px solid #aaa;
    border-radius: 2px;
}
.reference-legend {
    font-family: sans-serif;
    font-size: 7.8pt;
    margin-bottom: 0.12in;
    padding: 6px 8px;
    background: #f5f5f5;
    border-radius: 4px;
    border: 1px solid #ddd;
    line-height: 1.6;
}
.reference-section {
    margin-top: 0.18in;
}
.reference-section h3 {
    margin: 0 0 0.08in 0;
    font-size: 9pt;
}
.reference-badge {
    display: inline-block;
    color: white;
    font-size: 7pt;
    font-weight: 700;
    padding: 1px 4px;
    border-radius: 2px;
}
@page {
    size: Letter portrait;
    margin: 0.35in;
}
"""

# ---------------------------------------------------------------------------
# Print CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
.reference-wrap {
    width: 100%;
    overflow-x: auto;
}

.reference-table {
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
    font-family: sans-serif;
    font-size: 0.88rem;
}

.reference-table th,
.reference-table td {
    border: 1px solid #d8d8d8;
    vertical-align: middle;
}

.reference-table thead th {
    background: #4a4a4a !important;
    color: #ffffff !important;
    font-weight: 700;
    line-height: 1.15;
    white-space: nowrap;
    word-break: keep-all;
    overflow-wrap: normal;
}

.reference-table .col-id {
    width: 72px;
}

.reference-table .col-swatch {
    width: 40px;
}

.reference-table .col-num {
    width: 42px;
}

.reference-table .col-elem {
    width: 34px;
}

.reference-table .id-cell {
    font-family: monospace;
    white-space: nowrap;
}

.reference-table .color-cell {
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
}

.reference-table .num-cell,
.reference-table .swatch-cell,
.reference-table .badge-cell {
    text-align: center;
    white-space: nowrap;
    word-break: keep-all;
    overflow-wrap: normal;
}

.reference-table .cell-center {
    min-height: 1.35rem;
    display: flex;
    align-items: center;
    justify-content: center;
}

.reference-table .swatch-chip {
    width: 26px;
    height: 18px;
    margin: 0 auto;
    border: 1px solid #aaa;
    border-radius: 2px;
}

.reference-legend {
    font-family: sans-serif;
    font-size: 11px;
    margin-bottom: 10px;
    padding: 8px 12px;
    background: #f5f5f5;
    border-radius: 4px;
    border: 1px solid #ddd;
    line-height: 1.7;
}

.reference-section {
    margin-top: 1.25rem;
}

.reference-section h3 {
    margin: 0 0 0.45rem 0;
    font-size: 0.98rem;
}

.reference-badge {
    display: inline-block;
    color: white;
    font-size: 9px;
    font-weight: bold;
    padding: 1px 5px;
    border-radius: 2px;
}

@media print {
    [data-testid="stSidebar"],
    [data-testid="stSidebarNav"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    [data-testid="stStatusWidget"],
    footer, header, #MainMenu,
    .stDeployButton, .stButton { display: none !important; }

    [data-testid="stAppViewContainer"],
    [data-testid="block-container"],
    .main .block-container {
        max-width: 100% !important;
        padding: 0.5rem 1rem !important;
        margin: 0 !important;
    }

    iframe {
        width: 100% !important;
        height: auto !important;
        min-height: 10px !important;
        overflow: visible !important;
        border: none !important;
    }

    body {
        color: #000 !important;
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
    }

    body, p { font-size: 8pt !important; color: #000 !important; }
    h1 { font-size: 12pt !important; }
    h3 { font-size: 9.5pt !important; }

    .reference-wrap {
        overflow: visible !important;
    }

    .reference-section {
        margin-top: 0.18in !important;
    }

    .reference-section h3 {
        font-size: 9pt !important;
        margin: 0 0 0.08in 0 !important;
    }

    .reference-table {
        font-size: 7.4pt !important;
    }

    .reference-table thead {
        display: table-header-group;
    }

    .reference-table tbody tr {
        page-break-inside: avoid;
        break-inside: avoid;
    }

    .reference-table thead th {
        color: #fff !important;
        background: #4a4a4a !important;
        font-size: 7.2pt !important;
        padding: 3px 4px !important;
    }

    .reference-table td {
        font-size: 7.2pt !important;
        padding: 3px 4px !important;
    }

    .reference-table .col-id { width: 64px !important; }
    .reference-table .col-swatch { width: 34px !important; }
    .reference-table .col-num { width: 34px !important; }
    .reference-table .col-elem { width: 30px !important; }

    .reference-table .swatch-chip {
        width: 24px !important;
        height: 16px !important;
    }

    .reference-legend {
        font-size: 7.8pt !important;
        padding: 6px 8px !important;
    }

    .reference-badge {
        font-size: 7pt !important;
        padding: 1px 4px !important;
    }

    @page { size: Letter portrait; margin: 0.35in; }
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
        s = str(x).strip()
        if s == "" or s.lower() == "nan":
            return default
        return int(float(s))
    except Exception:
        return default

@st.cache_data
def load_data() -> pd.DataFrame:
    if not DB_PATH.exists():
        st.error(tr("errors.editor.db_missing", "Missing database: {path}", path=DB_PATH))
        st.stop()
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql_query("""
            SELECT
                c.cat_id, c.color_name, c.glass_family, c.is_striker,
                c.se, c.su, c.cu, c.pb, c.ag, c.au,
                mT.R AS r_t, mT.G AS g_t, mT.B AS b_t,
                mT.H AS h_t, mT.S AS s_t, mT.V AS v_t,
                mR.R AS r_r, mR.G AS g_r, mR.B AS b_r,
                mR.H AS h_r, mR.S AS s_r, mR.V AS v_r,
                mT.thickness_mm AS thickness
            FROM glass_catalog c
            LEFT JOIN glass_measurements mT
                ON mT.cat_id = c.cat_id AND mT.mode = 'T'
            LEFT JOIN glass_measurements mR
                ON mR.cat_id = c.cat_id AND mR.mode = 'R'
            ORDER BY c.cat_id
        """, con)

def swatch_html(r, g, b) -> str:
    if r is None or str(r).strip() in ("", "nan"):
        return '<td class="swatch-cell col-swatch"><div class="cell-center"></div></td>'
    r, g, b = safe_int(r), safe_int(g), safe_int(b)
    return (
        f'<td class="swatch-cell col-swatch" style="background:rgb({r},{g},{b});">'
        f'<div class="cell-center"></div></td>'
    )

def val_or_dash(x) -> str:
    if x is None or str(x).strip() in ("", "nan"):
        return "—"
    return str(safe_int(x))


def sort_field_label(value: str) -> str:
    return dict(SORT_OPTIONS).get(value, value)


def sort_reference_rows(rows: pd.DataFrame, sort_field: str, value_mode: str, ascending: bool) -> pd.DataFrame:
    sorted_rows = rows.copy()
    if sort_field in NUMERIC_SORT_FIELDS:
        sort_col = f"{sort_field}_{'t' if value_mode == 'T' else 'r'}"
        sorted_rows["_sort_value"] = pd.to_numeric(sorted_rows[sort_col], errors="coerce")
        return sorted_rows.sort_values(
            ["_sort_value", "cat_id"],
            ascending=[ascending, True],
            na_position="last",
            kind="mergesort",
        ).drop(columns=["_sort_value"])

    if sort_field in FLAG_SORT_FIELDS:
        sorted_rows["_sort_value"] = sorted_rows[sort_field].map(lambda value: safe_int(value, 0))
        return sorted_rows.sort_values(
            ["_sort_value", "cat_id"],
            ascending=[ascending, True],
            kind="mergesort",
        ).drop(columns=["_sort_value"])

    if sort_field == "color_name":
        sorted_rows["_sort_value"] = sorted_rows["color_name"].fillna("").astype(str).str.lower()
        return sorted_rows.sort_values(
            ["_sort_value", "cat_id"],
            ascending=[ascending, True],
            kind="mergesort",
        ).drop(columns=["_sort_value"])

    return sorted_rows.sort_values("cat_id", ascending=ascending, kind="mergesort")


def detail_href(cat_id: str) -> str:
    return (
        f"{DETAIL_PAGE_URL}?"
        f"{urlencode({'cat_id': str(cat_id), 'return_page': CURRENT_PAGE_PATH, 'return_label': RETURN_LABEL})}"
    )


def detail_id_html(cat_id: str) -> str:
    return (
        f'<a href="{detail_href(cat_id)}" target="_self" '
        f'style="color:inherit;text-decoration:none;font:inherit;">{cat_id}</a>'
    )

def element_cell(val, col_label, is_reactive=False) -> str:
    v = safe_int(val, 0)
    if v == 1:
        bg = ELEMENT_COLOURS.get(col_label, "#cccccc")
        return (
            f'<td class="badge-cell col-elem">'
            f'<div class="cell-center"><span class="reference-badge" style="background:{bg};">'
            f'{col_label}</span></div></td>'
        )
    elif is_reactive:
        return (
            f'<td class="badge-cell col-elem">'
            f'<div class="cell-center"><span class="reference-badge" style="background:{REACTIVE_BADGE_COLOUR};">R</span></div></td>'
        )
    return '<td class="badge-cell col-elem"><div class="cell-center"></div></td>'


def reactive_cols_for_row(row) -> set[str]:
    present_cols = {
        col for col, _ in ELEMENT_COLS
        if safe_int(getattr(row, col), 0) == 1
    }
    reactive_cols = set()
    for col in present_cols:
        reactive_cols.update(REACTION_COLS.get(col, set()))
    return reactive_cols - present_cols

def build_table(rows: pd.DataFrame, mode: str) -> str:
    mode_name = "Transmitted" if mode == "T" else "Reflected"
    suffix = "t" if mode == "T" else "r"
    el_headers = "".join(
        f'<th class="col-elem" style="padding:3px 4px;text-align:center;">{label}</th>'
        for _, label in ELEMENT_COLS
    )
    header = f"""
    <tr>
        <th class="col-id" style="padding:3px 8px;text-align:left;">No.</th>
        <th style="padding:3px 8px;text-align:left;">Color</th>
        <th class="col-swatch" style="padding:3px 4px;text-align:center;"></th>
        <th class="col-num" style="padding:3px 4px;text-align:center;">R</th>
        <th class="col-num" style="padding:3px 4px;text-align:center;">G</th>
        <th class="col-num" style="padding:3px 4px;text-align:center;">B</th>
        <th class="col-num" style="padding:3px 4px;text-align:center;border-left:3px solid #d8d8d8;">H</th>
        <th class="col-num" style="padding:3px 4px;text-align:center;">S</th>
        <th class="col-num" style="padding:3px 4px;text-align:center;">B</th>
        {el_headers}
    </tr>"""

    body = ""
    for i, row in enumerate(rows.itertuples(index=False)):
        bg = "#f9f9f9" if i % 2 == 0 else "white"
        striker = " ●" if safe_int(row.is_striker) == 1 else ""
        reactive_cols = reactive_cols_for_row(row)
        el_cells = "".join(
            element_cell(getattr(row, col), label, col in reactive_cols)
            for col, label in ELEMENT_COLS
        )
        body += f"""
        <tr style="background:{bg};">
            <td class="id-cell col-id" style="padding:2px 8px;">{detail_id_html(row.cat_id)}</td>
            <td class="color-cell" style="padding:2px 8px;">{row.color_name or ""}{striker}</td>
            {swatch_html(getattr(row, f"r_{suffix}"), getattr(row, f"g_{suffix}"), getattr(row, f"b_{suffix}"))}
            <td class="num-cell col-num" style="padding:2px 5px;">{val_or_dash(getattr(row, f"r_{suffix}"))}</td>
            <td class="num-cell col-num" style="padding:2px 5px;">{val_or_dash(getattr(row, f"g_{suffix}"))}</td>
            <td class="num-cell col-num" style="padding:2px 5px;">{val_or_dash(getattr(row, f"b_{suffix}"))}</td>
            <td class="num-cell col-num" style="padding:2px 5px;border-left:3px solid #a8a8a8;">{val_or_dash(getattr(row, f"h_{suffix}"))}</td>
            <td class="num-cell col-num" style="padding:2px 5px;">{val_or_dash(getattr(row, f"s_{suffix}"))}</td>
            <td class="num-cell col-num" style="padding:2px 5px;">{val_or_dash(getattr(row, f"v_{suffix}"))}</td>
            {el_cells}
        </tr>"""

    return (
        f'<div class="reference-section"><h3>{mode_name} Values</h3>'
        f'<div class="reference-wrap"><table class="reference-table">'
        f'<thead>{header}</thead><tbody>{body}</tbody></table></div>'
        f'</div>'
    )


def print_button_html(root_id: str, title: str, meta: str) -> str:
    return f"""
    <button id="reference-print-button" type="button"
        style="margin-top:1.2rem;padding:0.4rem 0.8rem;background:#4a4a4a;
        color:white;border:none;border-radius:4px;cursor:pointer;font-size:14px;">
        🖨 Print
    </button>
    <script>
    const rootId = {root_id!r};
    const docTitle = {title!r};
    const metaText = {meta!r};
    const printCss = {PRINT_WINDOW_CSS!r};
    const button = document.getElementById("reference-print-button");

    button.addEventListener("click", () => {{
        const parentDoc = window.parent && window.parent.document ? window.parent.document : document;
        const root = parentDoc.getElementById(rootId);
        if (!root) {{
            window.alert("Printable reference content is not ready yet.");
            return;
        }}

        const printWindow = window.open("", "_blank", "noopener,noreferrer,width=1100,height=900");
        if (!printWindow) {{
            window.alert("Please allow pop-ups for printing.");
            return;
        }}

        const html = [
            "<!doctype html><html><head><meta charset='utf-8'>",
            "<title>", docTitle, "</title>",
            "<style>", printCss, "</style>",
            "</head><body>",
            "<div class='print-title'>", docTitle, "</div>",
            "<div class='print-meta'>", metaText, "</div>",
            root.innerHTML,
            "</body></html>"
        ].join("");

        printWindow.document.open();
        printWindow.document.write(html);
        printWindow.document.close();
        printWindow.focus();
        printWindow.addEventListener("afterprint", () => printWindow.close(), {{ once: true }});

        const firePrint = () => window.setTimeout(() => printWindow.print(), 150);
        if (printWindow.document.readyState === "complete") {{
            firePrint();
        }} else {{
            printWindow.addEventListener("load", firePrint, {{ once: true }});
        }}
    }});
    </script>
    """

# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
hdr_col, print_col = st.columns([0.9, 0.1])
with hdr_col:
    st.title(tr("page.reference.title", "{family} Glass Reference", family=FAMILY_DISPLAY))
    st.caption(tr("page.reference.caption", "Transmitted (T) and Reflected (R) reference values"))
print_slot = print_col.empty()

st.divider()

df = load_data()
df["glass_family"] = df["glass_family"].astype(str).str.strip()
subset = df[df["glass_family"] == FAMILY_CODE].copy()

if subset.empty:
    st.warning(tr("page.reference.empty", "No {family} glass found in the database.", family=FAMILY_DISPLAY))
else:
    thickness_val = "2.0"
    thickness_series = subset["thickness"].dropna()
    if not thickness_series.empty:
        thickness_val = str(round(float(thickness_series.iloc[0]), 1))

    st.caption(tr("page.reference.summary", "{count} glasses | reference thickness {thickness} mm", count=len(subset), thickness=thickness_val))

    sort_col, value_mode_col, direction_col = st.columns([0.46, 0.30, 0.24])
    with sort_col:
        sort_field = st.selectbox(
            tr("page.reference.sort.field", "Sort by"),
            [value for value, _ in SORT_OPTIONS],
            index=0,
            format_func=sort_field_label,
        )
    with value_mode_col:
        value_mode = st.segmented_control(
            tr("page.reference.sort.measurement", "Measurement values"),
            options=["T", "R"],
            default="T",
            format_func=lambda value: tr("shared.mode.transmitted", "Transmitted") if value == "T" else tr("shared.mode.reflected", "Reflected"),
            disabled=sort_field not in NUMERIC_SORT_FIELDS,
        )
        value_mode = value_mode or "T"
    with direction_col:
        sort_direction = st.segmented_control(
            tr("page.reference.sort.direction", "Direction"),
            options=["asc", "desc"],
            default="asc",
            format_func=lambda value: tr("shared.sort.ascending", "Ascending") if value == "asc" else tr("shared.sort.descending", "Descending"),
        )
        sort_direction = sort_direction or "asc"

    subset = sort_reference_rows(subset, sort_field, value_mode, sort_direction == "asc")

    # Legend
    el_legend_items = "".join(
        f'<span style="margin-right:12px;">'
        f'<span class="reference-badge" style="background:{ELEMENT_COLOURS[label]};">{label}</span>'
        f' = {full_name}</span>'
        for label, full_name in [
            ("Se", "Selenium"), ("S", "Sulfur"), ("Cu", "Copper"),
            ("Pb", "Lead"),     ("Ag", "Silver"), ("Au", "Gold"),
        ]
    )
    legend_html = f"""
    <div class="reference-legend">
        <strong>Legend</strong>&nbsp;&nbsp;
        <span style="margin-right:16px;">
            <strong>●</strong> = Striker glass
        </span>
        <span style="margin-right:16px;">
            <span class="reference-badge" style="background:{REACTIVE_BADGE_COLOUR};">R</span>
            = May react with selected element
        </span>
        &nbsp;|&nbsp;&nbsp;
        <strong>Elements:</strong>&nbsp;&nbsp;
        {el_legend_items}
    </div>
    """
    meta_text = tr("page.reference.summary", "{count} glasses | reference thickness {thickness} mm", count=len(subset), thickness=thickness_val)
    pdf_bytes = build_reference_pdf(
        FAMILY_NAME,
        meta_text,
        subset.to_dict("records"),
        ELEMENT_COLS,
        ELEMENT_COLOURS,
        REACTION_COLS,
        REACTIVE_BADGE_COLOUR,
    )
    with print_slot:
        st.download_button(
            tr("detail.actions.download_pdf", "Download PDF"),
            data=pdf_bytes,
            file_name=f"{FAMILY_NAME.lower()}_glass_reference.pdf",
            mime="application/pdf",
        )

    printable_html = (
        f'<div id="{PRINT_ROOT_ID}">'
        f"{legend_html}"
        f"{build_table(subset, 'T')}"
        f"{build_table(subset, 'R')}"
        f"</div>"
    )
    st.markdown(printable_html, unsafe_allow_html=True)
