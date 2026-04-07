"""
7_Mesh_Crop.py
Terrain STL — raster proxy workflow.
1. Upload STL → render once to a PNG proxy (matplotlib, no Pillow needed)
2. Rotate the proxy image, recompute transform
3. Draw crop box on Plotly image overlay, click Confirm
4. Map pixel coords back to mesh coords, crop STL, download
STL only loaded at upload and download — image ops in between.
"""

import io
import struct
import math
import numpy as np
import streamlit as st
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import plotly.graph_objects as go
from i18n import render_app_sidebar, t as tr

st.set_page_config(page_title=tr("page.mesh_crop.title", "Mesh Crop"), layout="wide")
render_app_sidebar()
st.title(tr("page.mesh_crop.title", "Mesh Crop"))
st.caption(tr("page.mesh_crop.caption", "Upload STL | rotate proxy image | draw crop box | download."))

# ─────────────────────────────────────────
# Constants
# ─────────────────────────────────────────
IMG_W, IMG_H   = 800, 600     # proxy image size (pixels)
PLOTLY_W       = 900          # plotly figure width (px)
PLOTLY_H       = int(PLOTLY_W * IMG_H / IMG_W)

# ─────────────────────────────────────────
# STL parser
# ─────────────────────────────────────────
def parse_stl(data: bytes):
    if len(data) > 84:
        try:
            n_tri = struct.unpack_from("<I", data, 80)[0]
            if n_tri > 0 and abs(len(data) - (84 + n_tri * 50)) <= 2:
                dtype = np.dtype([("normal", np.float32, (3,)),
                                   ("v0", np.float32, (3,)),
                                   ("v1", np.float32, (3,)),
                                   ("v2", np.float32, (3,)),
                                   ("attr", np.uint16)])
                rec   = np.frombuffer(data, dtype=dtype, count=n_tri, offset=84)
                verts = np.concatenate([rec["v0"], rec["v1"], rec["v2"]]
                                       ).reshape(n_tri * 3, 3).astype(np.float32)
                tris  = np.arange(n_tri * 3, dtype=np.int32).reshape(n_tri, 3)
                valid = np.all(np.isfinite(verts), axis=1)
                keep  = np.all(valid[tris], axis=1)
                tris  = tris[keep]
                used  = np.unique(tris)
                remap = np.zeros(n_tri * 3, dtype=np.int32)
                remap[used] = np.arange(len(used))
                return verts[used], remap[tris]
        except Exception as e:
            st.warning(tr("page.mesh_crop.messages.parse_ascii_fallback", "Binary parse issue ({error}); trying ASCII...", error=e))
    text = data.decode("utf-8", errors="replace")
    verts, tris, buf = [], [], []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("vertex"):
            p = line.split()
            try:
                buf.append([float(p[1]), float(p[2]), float(p[3])])
            except (ValueError, IndexError):
                continue
            if len(buf) == 3:
                idx = len(verts)
                verts.extend(buf); tris.append([idx, idx+1, idx+2]); buf = []
    return np.array(verts, dtype=np.float32), np.array(tris, dtype=np.int32)


def write_stl_binary(verts, tris) -> bytes:
    buf = io.BytesIO()
    buf.write(b"\x00" * 80)
    buf.write(struct.pack("<I", len(tris)))
    zero = np.zeros(3, dtype=np.float32)
    for tri in tris:
        buf.write(zero.tobytes())
        for idx in tri:
            buf.write(verts[idx].astype(np.float32).tobytes())
        buf.write(b"\x00\x00")
    return buf.getvalue()


def crop_mesh_xy(verts, tris, xmin, xmax, ymin, ymax):
    inside = ((verts[:, 0] >= xmin) & (verts[:, 0] <= xmax) &
              (verts[:, 1] >= ymin) & (verts[:, 1] <= ymax))
    keep  = np.all(inside[tris], axis=1)
    new_t = tris[keep]
    if len(new_t) == 0:
        return verts, np.empty((0, 3), dtype=np.int32), 0
    used  = np.unique(new_t)
    remap = np.zeros(len(verts), dtype=np.int32)
    remap[used] = np.arange(len(used))
    return verts[used], remap[new_t], int(keep.sum())


# ─────────────────────────────────────────
# Raster proxy — render verts to PNG bytes
# Returns: (png_bytes, transform)
# transform = (x_min, x_max, y_min, y_max) in mesh coords
# so pixel (px, py) → mesh x = x_min + px/IMG_W*(x_max-x_min)
#                      mesh y = y_max - py/IMG_H*(y_max-y_min)  [y flipped]
# ─────────────────────────────────────────
def render_proxy(verts: np.ndarray, deg: float = 0.0):
    """Rotate verts by deg around Z, render Z-height map to PNG bytes."""
    r  = math.radians(deg)
    cr, sr = math.cos(r), math.sin(r)
    x =  cr * verts[:, 0] - sr * verts[:, 1]
    y =  sr * verts[:, 0] + cr * verts[:, 1]
    z =  verts[:, 2]

    xmin, xmax = float(x.min()), float(x.max())
    ymin, ymax = float(y.min()), float(y.max())

    # Z-height heatmap — mean Z per pixel bin, no subsampling needed
    heatmap, xedges, yedges = np.histogram2d(
        x, y, bins=[IMG_W, IMG_H], weights=z)
    counts, _, _ = np.histogram2d(x, y, bins=[IMG_W, IMG_H])
    with np.errstate(invalid="ignore"):
        heatmap = np.where(counts > 0, heatmap / counts, np.nan)

    fig, ax = plt.subplots(figsize=(IMG_W / 100, IMG_H / 100), dpi=100)
    fig.patch.set_facecolor("#000000")
    ax.set_facecolor("#000000")
    ax.imshow(heatmap.T, origin="lower",
              extent=[xmin, xmax, ymin, ymax],
              cmap="gray", aspect="equal", interpolation="bilinear")
    ax.axis("off")
    plt.tight_layout(pad=0)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100,
                facecolor="#000000", bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return buf.read(), (xmin, xmax, ymin, ymax)


def pixels_to_mesh(px0, px1, py0, py1, transform, img_w, img_h):
    """Map pixel crop box to mesh coordinate box.
    go.Image: pixel (0,0) = top-left, y increases downward.
    Mesh Y: ymin=bottom, ymax=top — so py=0 → mesh ymax, py=img_h → mesh ymin.
    """
    xmin_m, xmax_m, ymin_m, ymax_m = transform
    mx0 = xmin_m + (px0 / img_w) * (xmax_m - xmin_m)
    mx1 = xmin_m + (px1 / img_w) * (xmax_m - xmin_m)
    my0 = ymax_m - (py0 / img_h) * (ymax_m - ymin_m)
    my1 = ymax_m - (py1 / img_h) * (ymax_m - ymin_m)
    return min(mx0, mx1), max(mx0, mx1), min(my0, my1), max(my0, my1)


# ─────────────────────────────────────────
# Plotly figure with image + optional rect
# ─────────────────────────────────────────
def make_fig(png_bytes, sel=None):
    """Render PNG via go.Image trace — no axes, no grid bleed, box-select works."""
    import cv2

    # Decode PNG bytes to numpy RGB array for go.Image
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = img.shape[:2]

    fig = go.Figure()
    fig.add_trace(go.Image(z=img, hoverinfo="skip"))

    # go.Image pixel coords: x=0..w-1, y=0..h-1, y increases downward
    fig.update_layout(
        xaxis=dict(range=[0, w], showgrid=False, zeroline=False,
                   showticklabels=False, fixedrange=True),
        yaxis=dict(range=[h, 0], showgrid=False, zeroline=False,
                   showticklabels=False, fixedrange=True),
        dragmode="select",
        plot_bgcolor="black",
        paper_bgcolor="#111",
        margin=dict(l=0, r=0, t=0, b=0),
        width=PLOTLY_W,
        height=PLOTLY_H,
        showlegend=False,
    )

    # Draw confirmed selection rect (pixel coords, y down)
    if sel:
        px0, px1, py0, py1 = sel
        fig.add_shape(type="rect",
                      x0=px0, x1=px1, y0=py0, y1=py1,
                      line=dict(color="#ff4444", width=2),
                      fillcolor="rgba(255,68,68,0.08)")

    return fig


# ─────────────────────────────────────────
# Session state
# ─────────────────────────────────────────
defaults = {
    "raw_verts": None, "raw_tris": None, "filename": "",
    "proxy_png": None, "proxy_transform": None,
    "proxy_deg": 0,
    "sel_px": None,   # (px0, px1, py0, py1) in pixel coords
}
for k, v in defaults.items():
    st.session_state.setdefault(k, v)

# ─────────────────────────────────────────
# Upload
# ─────────────────────────────────────────
uploaded = st.file_uploader(tr("page.mesh_crop.fields.upload_stl", "Upload STL"), type=["stl"])
if uploaded and uploaded.name != st.session_state["filename"]:
    with st.spinner(tr("page.mesh_crop.messages.parsing", "Parsing STL...")):
        v, t = parse_stl(uploaded.read())
    with st.spinner(tr("page.mesh_crop.messages.rendering_proxy", "Rendering proxy...")):
        png, transform = render_proxy(v, deg=0)
    st.session_state.update({
        "raw_verts": v, "raw_tris": t,
        "filename": uploaded.name,
        "proxy_png": png, "proxy_transform": transform,
        "proxy_deg": 0, "sel_px": None,
    })
    st.success(tr("page.mesh_crop.messages.file_loaded", "**{name}** | {triangles} triangles", name=uploaded.name, triangles=f"{len(t):,}"))

if st.session_state["raw_verts"] is None:
    st.info(tr("page.mesh_crop.messages.upload_to_start", "Upload an STL to get started."))
    st.stop()

st.divider()

# ─────────────────────────────────────────
# Layout
# ─────────────────────────────────────────
left, right = st.columns([1, 3], gap="large")

with left:
    st.subheader(tr("page.mesh_crop.sections.rotation", "Rotation"))
    deg = st.slider(tr("page.mesh_crop.fields.rotate_z", "Rotate Z degrees"), -180, 180,
                    value=st.session_state["proxy_deg"], key="rot_slider")

    if st.button(tr("page.mesh_crop.actions.apply_rotation", "Apply rotation"), use_container_width=True):
        with st.spinner(tr("page.mesh_crop.messages.rerendering", "Re-rendering...")):
            png, transform = render_proxy(st.session_state["raw_verts"], deg)
        st.session_state.update({
            "proxy_png": png,
            "proxy_transform": transform,
            "proxy_deg": deg,
            "sel_px": None,
        })
        st.rerun()

    st.divider()
    st.subheader(tr("page.mesh_crop.sections.crop", "Crop"))

    sel = st.session_state["sel_px"]

    if sel:
        transform = st.session_state["proxy_transform"]
        mx0, mx1, my0, my1 = pixels_to_mesh(*sel, transform, IMG_W, IMG_H)
        st.markdown(f"**{tr('page.mesh_crop.labels.selection_coords', 'Selection (mesh coords)')}**")
        st.caption(tr("page.mesh_crop.labels.selection_x", "X: {start} -> {end}", start=f"{mx0:.1f}", end=f"{mx1:.1f}"))
        st.caption(tr("page.mesh_crop.labels.selection_y", "Y: {start} -> {end}", start=f"{my0:.1f}", end=f"{my1:.1f}"))
        st.divider()

        raw_v = st.session_state["raw_verts"]
        raw_t = st.session_state["raw_tris"]
        deg_saved = st.session_state["proxy_deg"]

        # Apply same rotation to original verts for crop
        r  = math.radians(deg_saved)
        cr, sr = math.cos(r), math.sin(r)
        rv = raw_v.copy()
        rx =  cr * rv[:, 0] - sr * rv[:, 1]
        ry =  sr * rv[:, 0] + cr * rv[:, 1]
        rotated = np.column_stack([rx, ry, rv[:, 2]])

        c_verts, c_tris, n_kept = crop_mesh_xy(
            rotated, raw_t, mx0, mx1, my0, my1)

        st.metric(tr("page.mesh_crop.metrics.triangles_in_crop", "Triangles in crop"), f"{n_kept:,}")

        if n_kept > 0:
            stl_bytes = write_stl_binary(c_verts, c_tris)
            stem = st.session_state["filename"].rsplit(".", 1)[0]
            st.download_button(
                f"⬇️ {tr('page.mesh_crop.actions.download_cropped_stl', 'Download cropped STL')}",
                data=stl_bytes,
                file_name=f"{stem}_cropped.stl",
                mime="application/octet-stream",
                use_container_width=True,
                type="primary",
            )
        else:
            st.warning(tr("page.mesh_crop.messages.no_triangles", "No triangles in selection - try a larger box."))

        if st.button(f"✕ {tr('page.mesh_crop.actions.clear_selection', 'Clear selection')}", use_container_width=True):
            st.session_state["sel_px"] = None
            st.rerun()
    else:
        st.caption(tr("page.mesh_crop.caption.draw_box", "Draw a box on the image to create the crop selection."))

# ─────────────────────────────────────────
# Preview
# ─────────────────────────────────────────
with right:
    fig = make_fig(st.session_state["proxy_png"],
                   sel=st.session_state["sel_px"])

    event = st.plotly_chart(fig, width='content',
                            on_select="rerun", key="crop_chart")

    # Read box from event — fires on mouse-release
    def _read_box(ev):
        for src in [ev, st.session_state.get("crop_chart")]:
            if src is None:
                continue
            sel_data = getattr(src, "selection", None) or (
                src.get("selection") if isinstance(src, dict) else None)
            if not sel_data:
                continue
            for key in ("box", "range"):
                boxes = sel_data.get(key, [])
                if boxes:
                    b  = boxes[0]
                    xs = b.get("x", [])
                    ys = b.get("y", [])
                    if len(xs) >= 2 and len(ys) >= 2:
                        # go.Image: y=0 is top, increases downward — no flip needed
                        return (float(min(xs)), float(max(xs)),
                                float(min(ys)), float(max(ys)))
        return None

    found = _read_box(event)
    if found and found != st.session_state["sel_px"]:
        st.session_state["sel_px"] = found
        st.rerun()
