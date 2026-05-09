"""
svg_tiler_app.py  (v3)
----------------------
Streamlit app: upload an SVG, optionally pre-process with vpype
(filter --min-length + linesort), preview tile grid, download zip.

Run:
    streamlit run svg_tiler_app.py

Dependencies:
    pip install streamlit lxml vpype
"""

import base64, io, os, re, shutil, string, subprocess, sys
import tempfile, zipfile
from copy import deepcopy
from lxml import etree
import streamlit as st
from i18n import render_app_sidebar, t as tr

# ── page config ───────────────────────────────────────────────
st.set_page_config(
    page_title=tr("page.svg_tiles.title", "SVG Tiler"),
    page_icon="✂️"

)
render_app_sidebar()

SVG_NS = "http://www.w3.org/2000/svg"
XLINK  = "http://www.w3.org/1999/xlink"

def tag(name):
    return f"{{{SVG_NS}}}{name}"

UNIT_PX = {"px": 1, "pt": 1.3333, "mm": 3.7795, "cm": 37.795,
           "in": 96, "pc": 16, "em": 16}

def to_px(value_str, dpi=96):
    s = value_str.strip()
    for unit, factor in UNIT_PX.items():
        if s.endswith(unit):
            try:
                v = float(s[:-len(unit)])
                return v * dpi if unit == "in" else v * factor
            except ValueError:
                pass
    try:
        return float(s)
    except ValueError:
        return 0.0

def get_canvas(root, dpi=96):
    w  = root.get("width",   "")
    h  = root.get("height",  "")
    vb = root.get("viewBox", "")
    wpx = to_px(w, dpi) if w else 0
    hpx = to_px(h, dpi) if h else 0
    if vb:
        parts = re.split(r"[\s,]+", vb.strip())
        if len(parts) == 4:
            vbw, vbh = float(parts[2]), float(parts[3])
            if not wpx: wpx = vbw
            if not hpx: hpx = vbh
            return wpx, hpx, vb
    if wpx and hpx:
        return wpx, hpx, f"0 0 {wpx} {hpx}"
    return 744.09, 1052.36, "0 0 744.09 1052.36"

def col_letter(c):
    result = ""
    c += 1
    while c:
        c, rem = divmod(c - 1, 26)
        result = string.ascii_uppercase[rem] + result
    return result

def tile_label(row, col):
    return f"{col_letter(col)}{row + 1}"

# ── vpype ─────────────────────────────────────────────────────
def find_vpype():
    """Return path to vpype executable or None."""
    # check explicit venv first, then PATH
    candidates = [
        os.path.join(sys.prefix, "bin", "vpype"),
        os.path.join(sys.prefix, "Scripts", "vpype.exe"),  # Windows
        shutil.which("vpype"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None

VPYPE_BIN = find_vpype()

def vpype_version():
    if not VPYPE_BIN:
        return None
    try:
        r = subprocess.run([VPYPE_BIN, "--version"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or r.stderr.strip()
    except Exception:
        return None

def run_vpype(svg_bytes: bytes, min_length_mm: float,
              do_linesort: bool,
              linemerge_tol_mm: float = 0.0) -> tuple[bytes, str]:
    """
    Run vpype on svg_bytes.
    Returns (processed_svg_bytes, command_string).
    Raises RuntimeError on failure.
    Order: linemerge -> filter -> linesort (recommended by vpype docs)
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "input.svg")
        dst = os.path.join(tmp, "output.svg")

        with open(src, "wb") as f:
            f.write(svg_bytes)

        cmd = [VPYPE_BIN, "read", src]
        if linemerge_tol_mm > 0:
            cmd += ["linemerge", "--tolerance", f"{linemerge_tol_mm:.2f}mm"]
        if min_length_mm > 0:
            cmd += ["filter", "--min-length", f"{min_length_mm:.2f}mm"]
        if do_linesort:
            cmd += ["linesort"]
        cmd += ["write", dst]

        # build a pretty command string for display (uses filename, not path)
        pretty = ["vpype", "read", os.path.basename(src)]
        if linemerge_tol_mm > 0:
            pretty += ["linemerge", "--tolerance", f"{linemerge_tol_mm:.2f}mm"]
        if min_length_mm > 0:
            pretty += ["filter", "--min-length", f"{min_length_mm:.2f}mm"]
        if do_linesort:
            pretty += ["linesort"]
        pretty += ["write", os.path.basename(dst)]
        cmd_str = " ".join(pretty)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            raise RuntimeError(
                f"vpype exited {result.returncode}:\n"
                f"{result.stderr or result.stdout}"
            )
        if not os.path.exists(dst):
            raise RuntimeError("vpype ran but produced no output file.")

        with open(dst, "rb") as f:
            return f.read(), cmd_str

# ── SVG helpers ───────────────────────────────────────────────
def normalise_source(root, canvas_w, canvas_h, vb_str):
    nsmap = {None: SVG_NS, "xlink": XLINK}
    out = etree.Element(tag("svg"), nsmap=nsmap)
    out.set("width",   f"{canvas_w:.4f}")
    out.set("height",  f"{canvas_h:.4f}")
    out.set("viewBox", vb_str)
    src_defs = root.find(tag("defs"))
    if src_defs is not None:
        defs = etree.SubElement(out, tag("defs"))
        for child in src_defs:
            defs.append(deepcopy(child))
    for child in root:
        if child.tag == tag("defs"):
            continue
        out.append(deepcopy(child))
    return out

def build_overlay_svg(norm_root, canvas_w, canvas_h, rows, cols):
    out = deepcopy(norm_root)
    tw  = canvas_w / cols
    th  = canvas_h / rows
    grid = etree.SubElement(out, tag("g"), id="grid-overlay")
    for c in range(1, cols):
        x = c * tw
        etree.SubElement(grid, tag("line"),
                         x1=f"{x:.2f}", y1="0",
                         x2=f"{x:.2f}", y2=f"{canvas_h:.2f}",
                         stroke="#e63946",
                         **{"stroke-width": "1.5", "stroke-dasharray": "6,4"})
    for r in range(1, rows):
        y = r * th
        etree.SubElement(grid, tag("line"),
                         x1="0", y1=f"{y:.2f}",
                         x2=f"{canvas_w:.2f}", y2=f"{y:.2f}",
                         stroke="#e63946",
                         **{"stroke-width": "1.5", "stroke-dasharray": "6,4"})
    etree.SubElement(grid, tag("rect"),
                     x="1", y="1",
                     width=f"{canvas_w-2:.2f}", height=f"{canvas_h-2:.2f}",
                     fill="none", stroke="#e63946", **{"stroke-width": "2"})
    font_size = max(10, min(min(tw, th) * 0.12, 36))
    pad = font_size * 0.5
    for r in range(rows):
        for c in range(cols):
            lbl = etree.SubElement(grid, tag("text"),
                                   x=f"{c*tw+pad:.2f}",
                                   y=f"{r*th+font_size+pad:.2f}",
                                   fill="#e63946",
                                   **{"font-family": "monospace",
                                      "font-size": f"{font_size:.1f}",
                                      "font-weight": "bold",
                                      "opacity": "0.85"})
            lbl.text = tile_label(r, c)
    return etree.tostring(out, pretty_print=True,
                          xml_declaration=True, encoding="UTF-8")

def make_tile(norm_root, canvas_w, canvas_h,
              row, col, rows, cols, label_size=12, show_border=True):
    tw = canvas_w / cols
    th = canvas_h / rows
    x0 = col * tw
    y0 = row * th
    label   = tile_label(row, col)
    clip_id = "tile_clip"
    nsmap = {None: SVG_NS, "xlink": XLINK}
    tile = etree.Element(tag("svg"), nsmap=nsmap)
    tile.set("xmlns",   SVG_NS)
    tile.set("width",   f"{tw:.4f}px")
    tile.set("height",  f"{th:.4f}px")
    tile.set("viewBox", f"0 0 {tw:.4f} {th:.4f}")
    defs = etree.SubElement(tile, tag("defs"))
    cp   = etree.SubElement(defs, tag("clipPath"), id=clip_id)
    etree.SubElement(cp, tag("rect"), x="0", y="0",
                     width=f"{tw:.4f}", height=f"{th:.4f}")
    src_defs = norm_root.find(tag("defs"))
    if src_defs is not None:
        for child in src_defs:
            defs.append(deepcopy(child))
    clip_g  = etree.SubElement(tile, tag("g"),
                                **{"clip-path": f"url(#{clip_id})"})
    trans_g = etree.SubElement(clip_g, tag("g"),
                                transform=f"translate({-x0:.4f},{-y0:.4f})")
    for child in norm_root:
        if child.tag == tag("defs"):
            continue
        trans_g.append(deepcopy(child))
    if show_border:
        etree.SubElement(tile, tag("rect"),
                         x="0.5", y="0.5",
                         width=f"{tw-1:.4f}", height=f"{th-1:.4f}",
                         fill="none", stroke="#cccccc",
                         **{"stroke-width": "0.75", "stroke-dasharray": "4,3"})
    pad = label_size * 0.4
    lbl = etree.SubElement(tile, tag("text"),
                           x=f"{pad:.2f}", y=f"{label_size+pad:.2f}",
                           fill="#aaaaaa",
                           **{"font-family": "monospace",
                              "font-size": str(label_size),
                              "font-weight": "bold"})
    lbl.text = label
    return etree.tostring(tile, pretty_print=True,
                          xml_declaration=True, encoding="UTF-8")

def build_zip(norm_root, canvas_w, canvas_h, rows, cols,
              base_name, label_size, show_border):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in range(rows):
            for c in range(cols):
                lbl = tile_label(r, c)
                svg_data = make_tile(norm_root, canvas_w, canvas_h,
                                     r, c, rows, cols, label_size, show_border)
                zf.writestr(f"{base_name}_{lbl}.svg", svg_data)
    buf.seek(0)
    return buf

def svg_to_b64_img(svg_bytes):
    b64 = base64.b64encode(svg_bytes).decode()
    return (
        f'<div style="max-width:100%;overflow:auto;'
        f'border:1px solid #444;border-radius:6px;background:#fff;">'
        f'<img src="data:image/svg+xml;base64,{b64}" '
        f'style="display:block;width:auto;height:auto;max-width:100%;">'
        f'</div>'
    )

# ═══════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════
st.title(f"✂️ {tr('page.svg_tiles.title', 'SVG Tiler')}")
st.caption(tr("page.svg_tiles.caption", "Upload | pre-process with vpype | preview grid | download tiles."))

col_ctrl, col_prev = st.columns([1, 2], gap="large")

# ── LEFT: controls ────────────────────────────────────────────
with col_ctrl:

    uploaded = st.file_uploader(tr("page.svg_tiles.fields.upload_svg", "Upload SVG"), type=["svg"])
    st.divider()

    # ── vpype section ──
    st.markdown(f"**{tr('page.svg_tiles.sections.vpype', 'vpype pre-processing')}**")

    ver = vpype_version()
    if VPYPE_BIN and ver:
        st.success(tr("page.svg_tiles.messages.vpype_found", "vpype found: {version}", version=ver))
    else:
        st.warning(tr("page.svg_tiles.messages.vpype_missing", "vpype not found - install with `pip install vpype`"))

    use_vpype = st.checkbox(
        tr("page.svg_tiles.fields.run_vpype", "Run vpype before tiling"),
        value=bool(VPYPE_BIN),
        disabled=not bool(VPYPE_BIN),
    )

    linemerge_tol = st.slider(
        tr("page.svg_tiles.fields.linemerge_tol", "linemerge --tolerance (mm)"),
        min_value=0.0, max_value=2.0, value=0.0, step=0.05,
        help=tr("page.svg_tiles.help.linemerge_tol", "Join paths whose endpoints are within this distance. 0 = disabled."),
        disabled=not use_vpype,
    )
    min_length = st.slider(
        tr("page.svg_tiles.fields.min_length", "filter --min-length (mm)"),
        min_value=0.0, max_value=20.0, value=2.0, step=0.5,
        help=tr("page.svg_tiles.help.min_length", "Remove paths shorter than this. 0 = disabled."),
        disabled=not use_vpype,
    )
    do_linesort = st.checkbox(
        tr("page.svg_tiles.fields.linesort", "linesort (minimise pen travel)"),
        value=True,
        disabled=not use_vpype,
    )

    st.divider()

    # ── tiling section ──
    st.markdown(f"**{tr('page.svg_tiles.sections.tiling', 'Tiling')}**")
    rows        = st.slider(tr("page.svg_tiles.fields.rows", "Rows"),    1, 10, 2)
    cols        = st.slider(tr("page.svg_tiles.fields.columns", "Columns"), 1, 10, 2)

    st.divider()

    st.markdown(f"**{tr('page.svg_tiles.sections.output', 'Output')}**")
    dpi         = st.number_input(tr("page.svg_tiles.fields.dpi", "DPI"), min_value=72, max_value=300,
                                  value=96, step=1)
    label_size  = st.slider(tr("page.svg_tiles.fields.label_size", "Label font size (px)"), 6, 48, 12)
    show_border = st.checkbox(tr("page.svg_tiles.fields.show_border", "Show tile border"), value=True)

# ── RIGHT: preview + download ─────────────────────────────────
with col_prev:

    if uploaded is None:
        st.info(tr("page.svg_tiles.messages.upload_to_start", "Upload an SVG on the left to get started."))
        st.stop()

    raw       = uploaded.read()
    base_name = os.path.splitext(uploaded.name)[0]

    # ── vpype pass ──
    processed_raw = raw
    if use_vpype and VPYPE_BIN:
        if linemerge_tol > 0 or min_length > 0 or do_linesort:
            with st.spinner(tr("page.svg_tiles.messages.running_vpype", "Running vpype...")):
                try:
                    processed_raw, cmd_str = run_vpype(
                        raw, min_length, do_linesort, linemerge_tol
                    )
                    with st.expander(tr("page.svg_tiles.sections.vpype_command", "vpype command"), expanded=False):
                        st.code(cmd_str, language="bash")
                    st.success(tr("page.svg_tiles.messages.vpype_completed", "vpype completed."))
                except RuntimeError as e:
                    st.error(tr("page.svg_tiles.errors.vpype_failed", "vpype failed:\n\n{error}", error=e))
                    st.stop()
        else:
            st.info(tr("page.svg_tiles.messages.vpype_skipped", "vpype enabled but all operations are off - skipping."))

    # ── parse SVG ──
    try:
        parser = etree.XMLParser(remove_comments=False)
        root   = etree.fromstring(processed_raw, parser)
    except etree.XMLSyntaxError as e:
        st.error(tr("page.svg_tiles.errors.parse_svg", "Could not parse SVG: {error}", error=e))
        st.stop()

    canvas_w, canvas_h, vb_str = get_canvas(root, dpi)
    norm_root = normalise_source(root, canvas_w, canvas_h, vb_str)

    tw = canvas_w / cols
    th = canvas_h / rows

    # ── canvas info ──
    st.markdown(
        f"""
**{tr('page.svg_tiles.labels.source_canvas', 'Source canvas: {width:.0f} x {height:.0f} px | {inch_width:.3f}" x {inch_height:.3f}"', width=canvas_w, height=canvas_h, inch_width=canvas_w/dpi, inch_height=canvas_h/dpi)}**

**{tr('page.svg_tiles.labels.tile_size', 'Tile size: {width:.0f} x {height:.0f} px | {inch_width:.3f}" x {inch_height:.3f}" | {count} tiles total', width=tw, height=th, inch_width=tw/dpi, inch_height=th/dpi, count=rows * cols)}**
        """
    )

    # ── overlay preview ──
    overlay = build_overlay_svg(norm_root, canvas_w, canvas_h, rows, cols)
    st.markdown(svg_to_b64_img(overlay), unsafe_allow_html=True)

    st.divider()

    # ── tile map ──
    st.markdown(f"**{tr('page.svg_tiles.sections.tile_map', 'Tile map')}**")
    header  = "| " + " | ".join(col_letter(c) for c in range(cols)) + " |"
    sep     = "| " + " | ".join(["---"] * cols) + " |"
    rows_md = ["| " + " | ".join(
                   tile_label(r, c) for c in range(cols)) + " |"
               for r in range(rows)]
    st.markdown("\n".join([header, sep] + rows_md))

    st.divider()

    # ── download ──
    zip_buf = build_zip(norm_root, canvas_w, canvas_h,
                        rows, cols, base_name, label_size, show_border)
    st.download_button(
        label=f"⬇️ {tr('page.svg_tiles.actions.download_all', 'Download all {count} tiles (.zip)', count=rows * cols)}",
        data=zip_buf,
        file_name=f"{base_name}_tiles_{rows}x{cols}.zip",
        mime="application/zip",
        use_container_width=True,
    )
