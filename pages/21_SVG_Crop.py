"""
21_SVG_Crop.py
--------------
Streamlit page: upload an SVG, define a rectangle crop region,
preview the crop overlay, optionally run vpype filter + linesort,
then download the cropped SVG.

Part of the Glass Toolkit app — lives in pages/ alongside 20_SVG_Tiles.py

Dependencies:
    pip install streamlit lxml vpype
"""

import base64, io, os, re, shutil, string, subprocess, sys
import tempfile, zipfile
from copy import deepcopy
from lxml import etree
import streamlit as st
from i18n import render_app_sidebar, t as tr

st.set_page_config(page_title=tr("page.svg_crop.title", "SVG Crop"), page_icon="✂️")
render_app_sidebar()

SVG_NS = "http://www.w3.org/2000/svg"
XLINK  = "http://www.w3.org/1999/xlink"
CSS_DPI = 96.0

def tag(name):
    return f"{{{SVG_NS}}}{name}"

UNIT_PX = {"px": 1, "pt": 1.3333, "mm": 3.7795, "cm": 37.795,
           "in": 96, "pc": 16, "em": 16}

def to_px(value_str, dpi=CSS_DPI):
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

def get_canvas(root, dpi=CSS_DPI):
    """Return (canvas_w, canvas_h, vb_str, vb_w, vb_h, vb_x, vb_y).
    canvas_w/h are in px (for display).
    vb_* are the raw viewBox values in the SVG native coordinate space.
    These may differ when the SVG uses mm/pt units (e.g. Inkscape mm docs).
    Crop math must use vb_* coords, not px coords."""
    w  = root.get("width",   "")
    h  = root.get("height",  "")
    vb = root.get("viewBox", "")
    wpx = to_px(w, dpi) if w else 0
    hpx = to_px(h, dpi) if h else 0
    if vb:
        parts = re.split(r"[\s,]+", vb.strip())
        if len(parts) == 4:
            vb_x, vb_y, vbw, vbh = (float(p) for p in parts)
            if vbw > 0 and vbh > 0:
                if not wpx: wpx = vbw
                if not hpx: hpx = vbh
                return wpx, hpx, vb, vbw, vbh, vb_x, vb_y
    if wpx and hpx:
        return wpx, hpx, f"0 0 {wpx} {hpx}", wpx, hpx, 0.0, 0.0
    return 744.09, 1052.36, "0 0 744.09 1052.36", 744.09, 1052.36, 0.0, 0.0

def detect_native_unit(root):
    """Detect the native unit of the SVG coordinate space.
    Returns (unit_name, px_per_unit) so we can convert user input correctly."""
    w = root.get("width", "")
    vb = root.get("viewBox", "")
    if not w or not vb:
        return "px", 1.0
    # Extract unit from width attribute
    for unit, factor in UNIT_PX.items():
        if w.strip().endswith(unit) and unit != "":
            try:
                w_val = float(w.strip()[:-len(unit)])
                parts = re.split(r"[\s,]+", vb.strip()) if vb else []
                if len(parts) == 4:
                    vb_w = float(parts[2])
                    # vb coords are in native units if width matches viewBox width
                    if vb_w > 0 and abs(w_val - vb_w) < 0.01:
                        return unit, factor
                # If width/height carry units but the viewBox is missing or unusable,
                # prefer the declared width unit instead of falling back to px.
                return unit, factor
            except ValueError:
                pass
    return "px", 1.0

def normalise_source(root, canvas_w, canvas_h, vb_str, dpi=CSS_DPI):
    """Re-parent source content preserving the ORIGINAL width/height/viewBox
    exactly. We must not change units here — the viewBox coordinate space
    must be preserved verbatim so crop coordinates are valid."""
    nsmap = {None: SVG_NS, "xlink": XLINK}
    out = etree.Element(tag("svg"), nsmap=nsmap)
    # Preserve original width/height/viewBox exactly as the source had them
    src_w = root.get("width",   f"{canvas_w:.4f}px")
    src_h = root.get("height",  f"{canvas_h:.4f}px")
    out.set("width",   src_w)
    out.set("height",  src_h)
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

# ── vpype ─────────────────────────────────────────────────────
def find_vpype():
    candidates = [
        os.path.join(sys.prefix, "bin", "vpype"),
        os.path.join(sys.prefix, "Scripts", "vpype.exe"),
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

def run_vpype(svg_bytes, min_length_mm, do_linesort, linemerge_tol_mm=0.0):
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
            raise RuntimeError(f"vpype exited {result.returncode}:\n{result.stderr or result.stdout}")
        if not os.path.exists(dst):
            raise RuntimeError("vpype ran but produced no output file.")
        with open(dst, "rb") as f:
            return f.read(), cmd_str

# ── crop SVG ──────────────────────────────────────────────────
def crop_svg(norm_root, canvas_w, canvas_h,
             crop_x, crop_y, crop_w, crop_h,
             native_unit="mm"):
    """
    Crop by setting viewBox to (crop_x, crop_y, crop_w, crop_h) in the
    SVG native coordinate space. width/height are expressed in the same
    native unit so the output opens at 1:1 scale in Inkscape — drop it
    on the source and no scaling is needed.
    """
    nsmap = {None: SVG_NS, "xlink": XLINK}
    out = etree.Element(tag("svg"), nsmap=nsmap)

    # width/height in native units — matches source coordinate space
    out.set("width",   f"{crop_w:.6f}{native_unit}")
    out.set("height",  f"{crop_h:.6f}{native_unit}")

    # viewBox defines the crop window in native coordinate space — no scaling
    out.set("viewBox", f"{crop_x:.6f} {crop_y:.6f} {crop_w:.6f} {crop_h:.6f}")

    # Copy defs
    src_defs = norm_root.find(tag("defs"))
    if src_defs is not None:
        defs = etree.SubElement(out, tag("defs"))
        for child in src_defs:
            defs.append(deepcopy(child))

    # Copy all content — viewBox is the crop, no transform needed
    for child in norm_root:
        if child.tag == tag("defs"):
            continue
        out.append(deepcopy(child))

    return etree.tostring(out, pretty_print=True,
                          xml_declaration=True, encoding="UTF-8")

# ── overlay preview ───────────────────────────────────────────
def build_crop_overlay(norm_root, canvas_w, canvas_h,
                       crop_x, crop_y, crop_w, crop_h,
                       label_unit="mm"):
    """Source SVG with a red crop rectangle overlaid."""
    out = deepcopy(norm_root)

    # semi-transparent masks outside crop region — four rects
    # top, bottom, left, right
    mask_style = {"fill": "#000000", "opacity": "0.35"}

    regions = [
        # top
        (0,                  0,                  canvas_w,             crop_y),
        # bottom
        (0,                  crop_y + crop_h,    canvas_w,             canvas_h - crop_y - crop_h),
        # left
        (0,                  crop_y,             crop_x,               crop_h),
        # right
        (crop_x + crop_w,    crop_y,             canvas_w - crop_x - crop_w, crop_h),
    ]
    for (rx, ry, rw, rh) in regions:
        if rw > 0 and rh > 0:
            etree.SubElement(out, tag("rect"),
                             x=f"{rx:.2f}", y=f"{ry:.2f}",
                             width=f"{rw:.2f}", height=f"{rh:.2f}",
                             **mask_style)

    # scale overlay elements relative to canvas so they're visible on any size file
    sw    = max(1, min(canvas_w, canvas_h) * 0.003)   # stroke width
    tick  = min(canvas_w, canvas_h) * 0.02            # corner tick length
    font_size = max(12, min(canvas_w, canvas_h) * 0.025)
    pad   = font_size * 0.5

    # crop border
    etree.SubElement(out, tag("rect"),
                     x=f"{crop_x:.2f}", y=f"{crop_y:.2f}",
                     width=f"{crop_w:.2f}", height=f"{crop_h:.2f}",
                     fill="none", stroke="#e63946",
                     **{"stroke-width": f"{sw:.2f}"})

    # corner ticks
    corners = [
        (crop_x, crop_y),
        (crop_x + crop_w, crop_y),
        (crop_x, crop_y + crop_h),
        (crop_x + crop_w, crop_y + crop_h),
    ]
    for cx, cy in corners:
        etree.SubElement(out, tag("line"),
                         x1=f"{cx - tick:.2f}", y1=f"{cy:.2f}",
                         x2=f"{cx + tick:.2f}", y2=f"{cy:.2f}",
                         stroke="#e63946", **{"stroke-width": f"{sw*1.5:.2f}"})
        etree.SubElement(out, tag("line"),
                         x1=f"{cx:.2f}", y1=f"{cy - tick:.2f}",
                         x2=f"{cx:.2f}", y2=f"{cy + tick:.2f}",
                         stroke="#e63946", **{"stroke-width": f"{sw*1.5:.2f}"})

    # dimensions label — shown in SVG/native units
    etree.SubElement(out, tag("text"),
                     x=f"{crop_x + pad:.2f}",
                     y=f"{max(crop_y - pad, font_size + pad):.2f}",
                     fill="#e63946",
                     **{"font-family": "monospace",
                        "font-size": f"{font_size:.1f}",
                        "font-weight": "bold"}).text = (
        f"{crop_w:.2f} x {crop_h:.2f} {label_unit}"
    )

    return etree.tostring(out, pretty_print=True,
                          xml_declaration=True, encoding="UTF-8")

def svg_to_b64_img(svg_bytes, canvas_w=None, canvas_h=None, max_h=700):
    """Render SVG at true proportions inside a fixed-height scrollable container.
    No scaling is applied — width:100% is intentionally removed so the crop
    rectangle sits in the correct position relative to the artwork."""
    b64 = base64.b64encode(svg_bytes).decode()
    # Let the SVG define its own size; container scrolls if needed.
    return (
        f'<div style="max-height:{max_h}px;overflow:auto;' 
        f'border:1px solid #444;border-radius:6px;background:#fff;">' 
        f'<img src="data:image/svg+xml;base64,{b64}" ' 
        f'style="display:block;max-width:none;">' 
        f'</div>'
    )

# ═══════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════
st.title(f"✂️ {tr('page.svg_crop.title', 'SVG Crop')}")
st.caption(tr("page.svg_crop.caption", "Upload an SVG | define a crop rectangle | preview | optionally run vpype | download."))

SVG_CROP_DEFAULTS = {
    "svg_crop_unit_choice": "mm",
    "svg_crop_x": 0.0,
    "svg_crop_y": 0.0,
    "svg_crop_w": 4.0,
    "svg_crop_h": 4.0,
    "svg_crop_use_vpype": bool(VPYPE_BIN),
    "svg_crop_linemerge_tol": 0.0,
    "svg_crop_min_length": 2.0,
    "svg_crop_do_linesort": True,
}

st.session_state.setdefault("svg_crop_reset_pending", False)
st.session_state.setdefault("svg_crop_last_upload_sig", None)
for key, value in SVG_CROP_DEFAULTS.items():
    st.session_state.setdefault(key, value)

if st.session_state.get("svg_crop_reset_pending"):
    for key, value in SVG_CROP_DEFAULTS.items():
        st.session_state[key] = value
    st.session_state["svg_crop_reset_pending"] = False

col_ctrl, col_prev = st.columns([1, 2], gap="large")

# ── LEFT: controls ────────────────────────────────────────────
with col_ctrl:

    uploaded = st.file_uploader(tr("page.svg_crop.fields.upload_svg", "Upload SVG"), type=["svg"])
    if uploaded is not None:
        upload_sig = (uploaded.name, uploaded.size)
        if st.session_state.get("svg_crop_last_upload_sig") != upload_sig:
            preferred_unit = "px"
            try:
                parser = etree.XMLParser(remove_comments=False)
                unit_root = etree.fromstring(uploaded.getvalue(), parser)
                detected_unit, _ = detect_native_unit(unit_root)
                preferred_unit = {
                    "mm": "mm",
                    "cm": "mm",
                    "in": "mm",
                }.get(detected_unit, "px")
            except Exception:
                preferred_unit = "px"
            st.session_state["svg_crop_unit_choice"] = preferred_unit
            st.session_state["svg_crop_last_upload_sig"] = upload_sig
    if st.button(tr("page.svg_crop.reset_defaults", "Reset Defaults")):
        st.session_state["svg_crop_reset_pending"] = True
        st.session_state["svg_crop_last_upload_sig"] = None
        st.rerun()
    st.divider()

    st.markdown(f"**{tr('page.svg_crop.crop_region', 'Crop region')}**")
    unit_choice = st.radio(
        tr("page.svg_crop.input_units", "Input units"),
        ["mm", "px"],
        horizontal=True,
        key="svg_crop_unit_choice",
    )
    st.caption(tr("page.svg_crop.origin", "Origin (0, 0) is top-left of the SVG canvas."))

    col_a, col_b = st.columns(2)
    with col_a:
        crop_x_u = st.number_input(
            tr("page.svg_crop.fields.x_offset", "X offset"),
            min_value=0.0,
            step=0.1,
            format="%.3f",
            key="svg_crop_x",
        )
        crop_w_u = st.number_input(
            tr("page.svg_crop.fields.width", "Width"),
            min_value=0.1,
            step=0.1,
            format="%.3f",
            key="svg_crop_w",
        )
    with col_b:
        crop_y_u = st.number_input(
            tr("page.svg_crop.fields.y_offset", "Y offset"),
            min_value=0.0,
            step=0.1,
            format="%.3f",
            key="svg_crop_y",
        )
        crop_h_u = st.number_input(
            tr("page.svg_crop.fields.height", "Height"),
            min_value=0.1,
            step=0.1,
            format="%.3f",
            key="svg_crop_h",
        )

    # convert input units → px
    def u2px(v):
        if unit_choice == "mm":     return v * 3.7795
        return v

    crop_x = u2px(crop_x_u)
    crop_y = u2px(crop_y_u)
    crop_w = u2px(crop_w_u)
    crop_h = u2px(crop_h_u)

    st.divider()

    # ── vpype section ──
    st.markdown(f"**{tr('page.svg_crop.sections.vpype', 'vpype post-processing')}**")
    ver = vpype_version()
    if VPYPE_BIN and ver:
        st.success(tr("page.svg_crop.messages.vpype_found", "vpype found: {version}", version=ver))
    else:
        st.warning(tr("page.svg_crop.messages.vpype_missing", "vpype not found - install with `pip install vpype`"))

    use_vpype = st.checkbox(
        tr("page.svg_crop.fields.run_vpype", "Run vpype after crop"),
        disabled=not bool(VPYPE_BIN),
        key="svg_crop_use_vpype",
    )
    linemerge_tol = st.slider(
        tr("page.svg_crop.fields.linemerge_tol", "linemerge --tolerance (mm)"),
        min_value=0.0, max_value=2.0, step=0.05,
        help=tr("page.svg_crop.help.linemerge_tol", "Join paths whose endpoints are within this distance. 0 = disabled."),
        disabled=not use_vpype,
        key="svg_crop_linemerge_tol",
    )
    min_length = st.slider(
        tr("page.svg_crop.fields.min_length", "filter --min-length (mm)"),
        min_value=0.0, max_value=20.0, step=0.5,
        help=tr("page.svg_crop.help.min_length", "Remove paths shorter than this. 0 = disabled."),
        disabled=not use_vpype,
        key="svg_crop_min_length",
    )
    do_linesort = st.checkbox(
        tr("page.svg_crop.fields.linesort", "linesort (minimise pen travel)"),
        disabled=not use_vpype,
        key="svg_crop_do_linesort",
    )

# ── RIGHT: preview + download ─────────────────────────────────
with col_prev:

    if uploaded is None:
        st.info(tr("page.svg_crop.messages.upload_to_start", "Upload an SVG on the left to get started."))
        st.stop()

    raw       = uploaded.getvalue()
    base_name = os.path.splitext(uploaded.name)[0]

    # parse
    try:
        parser = etree.XMLParser(remove_comments=False)
        root   = etree.fromstring(raw, parser)
    except etree.XMLSyntaxError as e:
        st.error(tr("page.svg_crop.errors.parse_svg", "Could not parse SVG: {error}", error=e))
        st.stop()

    canvas_w, canvas_h, vb_str, vb_w, vb_h, vb_x, vb_y = get_canvas(root, CSS_DPI)
    native_unit, px_per_native = detect_native_unit(root)
    norm_root = normalise_source(root, canvas_w, canvas_h, vb_str, dpi=CSS_DPI)

    # ── convert user crop inputs to native SVG coordinate space ──
    # User inputs are in their chosen unit (mm or px).
    # We must convert to the SVG native unit (e.g. mm for Inkscape docs).
    def user_to_native(v):
        """Convert user input value to SVG native coordinate units."""
        # First convert user input to px
        if unit_choice == "mm":     v_px = v * 3.7795
        else:                       v_px = v
        # Then convert px to native SVG units
        if native_unit == "in":     return v_px / CSS_DPI
        elif native_unit == "mm":   return v_px / 3.7795
        elif native_unit == "cm":   return v_px / 37.795
        elif native_unit == "pt":   return v_px / 1.3333
        else:                       return v_px  # px

    crop_x_n = user_to_native(crop_x_u)
    crop_y_n = user_to_native(crop_y_u)
    crop_w_n = user_to_native(crop_w_u)
    crop_h_n = user_to_native(crop_h_u)

    # clamp to viewBox bounds
    crop_x_n = max(vb_x, min(crop_x_n, vb_x + vb_w))
    crop_y_n = max(vb_y, min(crop_y_n, vb_y + vb_h))
    crop_w_n = min(crop_w_n, vb_w - (crop_x_n - vb_x))
    crop_h_n = min(crop_h_n, vb_h - (crop_y_n - vb_y))

    # ── canvas + crop info ──
    st.markdown(
        f"**{tr('page.svg_crop.labels.source_canvas', 'Source canvas: {width:.2f} x {height:.2f} {unit}', width=vb_w, height=vb_h, unit=native_unit)}**"
    )
    st.markdown(
        f"**{tr('page.svg_crop.labels.crop_region', 'Crop region: {width:.3f} x {height:.3f} {unit} at ({x:.3f}, {y:.3f}) {unit}', width=crop_w_n, height=crop_h_n, unit=native_unit, x=crop_x_n, y=crop_y_n)}**"
    )

    with st.expander(tr("page.svg_crop.sections.debug", "SVG coordinate debug"), expanded=False):
        st.code(
            "\n".join([
                "Source SVG attributes:",
                "  width   = " + root.get("width",   "(not set)"),
                "  height  = " + root.get("height",  "(not set)"),
                "  viewBox = " + root.get("viewBox", "(not set)"),
                "",
                "Detected native unit : " + native_unit,
                "px per native unit   : " + str(round(px_per_native, 4)),
                "viewBox origin       : " + str(round(vb_x,4)) + ", " + str(round(vb_y,4)),
                "viewBox size         : " + str(round(vb_w,4)) + " x " + str(round(vb_h,4)),
                "",
                "Crop in native units : x=" + str(round(crop_x_n,4))
                    + " y=" + str(round(crop_y_n,4))
                    + " w=" + str(round(crop_w_n,4))
                    + " h=" + str(round(crop_h_n,4)),
            ]),
            language="text"
        )

    # ── overlay preview — use native coords for overlay ──
    overlay = build_crop_overlay(norm_root, vb_w, vb_h,
                                 crop_x_n, crop_y_n, crop_w_n, crop_h_n,
                                 label_unit=native_unit)
    st.markdown(svg_to_b64_img(overlay), unsafe_allow_html=True)

    st.divider()

    # ── crop + optional vpype + download ──
    cropped_svg = crop_svg(norm_root, vb_w, vb_h,
                           crop_x_n, crop_y_n, crop_w_n, crop_h_n,
                           native_unit=native_unit)

    if use_vpype and VPYPE_BIN and (linemerge_tol > 0 or min_length > 0 or do_linesort):
        with st.spinner(tr("page.svg_crop.messages.running_vpype", "Running vpype...")):
            try:
                cropped_svg, cmd_str = run_vpype(cropped_svg,
                                                 min_length, do_linesort, linemerge_tol)
                with st.expander(tr("page.svg_crop.sections.vpype_command", "vpype command"), expanded=False):
                    st.code(cmd_str, language="bash")
                st.success(tr("page.svg_crop.messages.vpype_completed", "vpype completed."))
            except RuntimeError as e:
                st.error(tr("page.svg_crop.errors.vpype_failed", "vpype failed:\n\n{error}", error=e))
                st.stop()

    out_name = f"{base_name}_crop.svg"
    st.download_button(
        label=f"⬇️ {tr('page.svg_crop.actions.download', 'Download cropped SVG')}",
        data=cropped_svg,
        file_name=out_name,
        mime="image/svg+xml",
        use_container_width=True,
    )

    st.caption(tr("page.svg_crop.tip", "Tip: after cropping, use the SVG Tiler page to split into tiles."))
