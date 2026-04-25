import io
import re
import zipfile

import numpy as np
import streamlit as st
import trimesh
from PIL import Image

from i18n import render_app_sidebar, t as tr

# Optional helpers (may not exist in every trimesh build)
try:
    import trimesh.repair as repair
except Exception:  # pragma: no cover
    repair = None

st.set_page_config(page_title=tr("page.cameo.title", "Cameo Mold Model Generator"), layout="wide")
render_app_sidebar()
st.title(tr("page.cameo.title", "Cameo Mold Model Generator"))
st.caption(
    tr(
        "page.cameo.caption",
        "Grayscale values are translated into a sculpted digital relief and inverted to form a mold, "
        "allowing the cameo image to emerge correctly in the finished glass. "
        "This page exports a slicer-ready solid model so hollowing, supports, drain holes, and final orientation can be handled in your slicer.",
    )
)


# ----------------------------
# Helpers
# ----------------------------
def image_to_heightmap(img: Image.Image, max_dim: int, invert: bool) -> np.ndarray:
    """Return float32 heightmap in [0,1], mirrored left-right to match STL orientation."""
    img = img.convert("L")

    w, h = img.size
    scale = min(1.0, float(max_dim) / float(max(w, h)))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    arr = np.asarray(img, dtype=np.float32) / 255.0  # 0=black, 1=white

    # Default convention: darker -> thicker (more blocking / more relief).
    if invert:
        arr = 1.0 - arr

    # Mirror preview/output left-right so STL matches what you see
    arr = np.fliplr(arr)

    return arr


def _safe_unique_faces(mesh: trimesh.Trimesh):
    """Return a boolean mask / indices for unique faces across trimesh versions."""
    if hasattr(mesh, "unique_faces") and callable(getattr(mesh, "unique_faces")):
        return mesh.unique_faces()
    try:
        return trimesh.grouping.unique_faces(mesh.faces)
    except Exception:
        return None


def build_mold_solid(
    height01: np.ndarray,
    width_mm: float,
    t_max: float,
    base_thickness: float,
) -> tuple[trimesh.Trimesh, float]:
    """
    Builds a watertight solid:
      - Bottom plane at z=0
      - Top surface at z=base_thickness + relief_thickness
      - Side walls

    Returns (mesh, height_mm)
    """
    thickness = height01 * float(t_max)
    rows, cols = thickness.shape

    px = float(width_mm) / float(cols - 1)
    height_mm = px * float(rows - 1)

    xs = np.linspace(0.0, float(width_mm), cols, dtype=np.float32)
    ys = np.linspace(0.0, float(height_mm), rows, dtype=np.float32)
    X, Y = np.meshgrid(xs, ys)

    z_top = float(base_thickness) + thickness
    z_bot = np.zeros_like(z_top)

    v_top = np.column_stack([X.ravel(), Y.ravel(), z_top.ravel()])
    v_bot = np.column_stack([X.ravel(), Y.ravel(), z_bot.ravel()])

    bot_offset = v_top.shape[0]

    r_idx, c_idx = np.mgrid[0 : rows - 1, 0 : cols - 1]
    a = (r_idx * cols + c_idx).ravel()
    b = (r_idx * cols + c_idx + 1).ravel()
    d = ((r_idx + 1) * cols + c_idx).ravel()
    e = ((r_idx + 1) * cols + c_idx + 1).ravel()

    top_faces = np.column_stack([
        np.concatenate([a, b]),
        np.concatenate([d, d]),
        np.concatenate([b, e]),
    ])

    ba, bb, bd, be = a + bot_offset, b + bot_offset, d + bot_offset, e + bot_offset
    bot_faces = np.column_stack([
        np.concatenate([ba, bb]),
        np.concatenate([bb, be]),
        np.concatenate([bd, bd]),
    ])

    def wall_faces(t0, t1, b0, b1):
        return np.column_stack([
            np.concatenate([t0, t0]),
            np.concatenate([b1, t1]),
            np.concatenate([b0, b1]),
        ])

    ri = np.arange(rows - 1)
    ci = np.arange(cols - 1)

    left = wall_faces(
        ri * cols,
        (ri + 1) * cols,
        bot_offset + ri * cols,
        bot_offset + (ri + 1) * cols,
    )

    right = wall_faces(
        ri * cols + (cols - 1),
        (ri + 1) * cols + (cols - 1),
        bot_offset + ri * cols + (cols - 1),
        bot_offset + (ri + 1) * cols + (cols - 1),
    )
    right = right[:, [0, 2, 1]]

    front = wall_faces(
        ci,
        ci + 1,
        bot_offset + ci,
        bot_offset + ci + 1,
    )
    front = front[:, [0, 2, 1]]

    base_r = (rows - 1) * cols
    back = wall_faces(
        base_r + ci,
        base_r + ci + 1,
        bot_offset + base_r + ci,
        bot_offset + base_r + ci + 1,
    )

    faces_arr = np.concatenate(
        [top_faces, bot_faces, left, right, front, back], axis=0
    ).astype(np.int64)

    vertices = np.vstack([v_top, v_bot]).astype(np.float32)

    vertices[:, 0] = float(width_mm) - vertices[:, 0]
    faces_arr = faces_arr[:, [0, 2, 1]]

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces_arr, process=False)

    try:
        mesh.process(validate=True)
    except Exception:
        pass

    if repair is not None:
        try:
            repair.fix_normals(mesh)
        except Exception:
            pass

    if mesh.is_watertight:
        try:
            if mesh.volume < 0:
                mesh.invert()
        except Exception:
            pass

    try:
        mesh.remove_unreferenced_vertices()
    except Exception:
        pass

    try:
        uf = _safe_unique_faces(mesh)
        if uf is not None:
            mesh.update_faces(uf)
            mesh.remove_unreferenced_vertices()
    except Exception:
        pass

    return mesh, float(height_mm)


# ----------------------------
# UI
# ----------------------------
col1, col2 = st.columns([1, 1])

with col1:
    up = st.file_uploader(
        tr("page.cameo.fields.upload_image", "Upload image"),
        type=["png", "jpg", "jpeg", "tif", "tiff", "bmp"],
    )
    with st.expander(tr("page.cameo.controls", "What do these controls do?"), expanded=False):
        st.markdown(
            tr(
                "page.cameo.controls.body",
                "- **Target width (mm):** Sets final model width; height follows the image aspect ratio.\n"
                "- **Relief Maximum (mm):** Sets the relief range from **0.00 mm** up to the chosen maximum.\n"
                "- **Base backing thickness (mm):** Adds a flat structural base under the relief.\n"
                "- **Invert relief:** Swaps the tone mapping so light areas become deeper (and vice versa). Leave checked for cameo.\n"
                "- **Resolution:** Max image dimension used for the heightmap; higher = more detail + slower.",
            ).strip()
        )

with col2:
    st.subheader(tr("page.cameo.settings", "Settings"))

    defaults = dict(
        width_mm=120.0,
        t_max=3.0,
        base_thickness=10.0,
        invert=True,
        max_dim=700,
    )

    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    if st.button(tr("page.cameo.actions.reset", "Reset settings"), use_container_width=True):
        for key, value in defaults.items():
            st.session_state[key] = value
        for key in ("mesh", "height_mm", "stl_bytes", "zip_bytes", "report_text", "last_sig"):
            st.session_state.pop(key, None)
        st.rerun()

    width_mm = st.slider(
        tr("page.cameo.fields.target_width", "Target Mold Width (mm)"),
        30.0,
        250.0,
        step=1.0,
        key="width_mm",
    )
    t_max = st.slider(
        tr("page.cameo.fields.relief_max", "Artwork relief maximum (mm)"),
        0.5,
        60.0,
        step=0.1,
        key="t_max",
    )
    base_thickness = st.slider(
        tr("page.cameo.fields.base_backing", "Base Backing Thickness (mm)"),
        0.0,
        20.0,
        step=0.5,
        key="base_thickness",
    )
    invert = st.checkbox(tr("page.cameo.fields.invert_relief", "Invert Relief"), key="invert")
    max_dim = st.slider(
        tr("page.cameo.fields.resolution", "Resolution"),
        200,
        1200,
        step=50,
        key="max_dim",
    )

    st.caption(tr("page.cameo.caption.resolution", "Higher = more detail + slower. 600-900 is a good sweet spot."))

if up is None:
    st.info(
        tr(
            "page.cameo.messages.upload_first",
            "Upload an image to preview the mirrored heightmap. Mesh is generated only when you export.",
        )
    )
    st.stop()

img = Image.open(up)

max_dim_preview = min(int(max_dim), 350)
height01_preview = image_to_heightmap(img, max_dim=max_dim_preview, invert=invert)
rows_p, cols_p = height01_preview.shape
px_p = float(width_mm) / float(cols_p - 1)
height_mm_est = px_p * float(rows_p - 1)
hm_preview = (np.clip(height01_preview, 0, 1) * 255).astype(np.uint8)
hm_img = Image.fromarray(hm_preview, mode="L")

pcol1, pcol2 = st.columns([1, 1])

with pcol1:
    st.subheader(tr("page.cameo.sections.input", "Input"))
    st.image(img, width="stretch")

with pcol2:
    st.subheader(tr("page.cameo.sections.preview", "Heightmap preview (mirrored)"))
    st.image(hm_img, width="stretch")


# ----------------------------
# Export (deferred mesh build)
# ----------------------------
st.divider()
st.subheader(tr("page.cameo.sections.export", "Export"))
st.caption(
    tr(
        "page.cameo.caption.slicer_ready",
        "Exports a slicer-ready solid model. Hollowing, supports, drain holes, and print orientation are best handled in your slicer.",
    )
)

current_sig = (
    getattr(up, "name", None),
    getattr(up, "size", None),
    float(width_mm),
    float(t_max),
    float(base_thickness),
    bool(invert),
    int(max_dim),
)

last_sig = st.session_state.get("last_sig")
dirty = last_sig != current_sig

if dirty and st.session_state.get("stl_bytes") is not None:
    st.info(tr("page.cameo.messages.rebuild", "Settings changed - rebuild the mesh to update the export."))

build = st.button(tr("page.cameo.actions.build", "Build mesh and enable download"), type="primary")

if build:
    st.session_state["mesh"] = None
    st.session_state["stl_bytes"] = None
    st.session_state["zip_bytes"] = None
    st.session_state["report_text"] = None
    st.session_state["height_mm"] = None

    with st.spinner(tr("page.cameo.messages.building", "Building mesh...")):
        height01_full = image_to_heightmap(img, max_dim=max_dim, invert=invert)
        mesh, height_mm = build_mold_solid(
            height01_full,
            width_mm=width_mm,
            t_max=t_max,
            base_thickness=base_thickness,
        )

        st.session_state["mesh"] = mesh
        st.session_state["height_mm"] = float(height_mm)
        st.session_state["last_sig"] = current_sig

        stl_bytes = mesh.export(file_type="stl")
        if isinstance(stl_bytes, str):
            stl_bytes = stl_bytes.encode("utf-8")
        elif not isinstance(stl_bytes, bytes):
            stl_bytes = bytes(stl_bytes)
        st.session_state["stl_bytes"] = stl_bytes

        base = re.sub(r"\s+", "_", up.name.rsplit(".", 1)[0].strip())
        base = re.sub(r"[^A-Za-z0-9_\-\.]+", "", base) or "mold"
        report = (
            f"Image: {up.name}\n"
            f"Model structure: Slicer-ready solid model\n"
            f"Target width (mm): {width_mm:g}\n"
            f"Relief depth max (mm): {t_max:g}\n"
            f"Base backing thickness (mm): {base_thickness:g}\n"
            f"Invert relief: {'Yes' if invert else 'No'}\n"
            f"Resolution (max dim px): {max_dim}\n"
            f"Output size (mm): {width_mm:.1f} x {height_mm:.1f} x {(base_thickness + t_max):.1f}\n"
            f"Watertight: {'Yes' if mesh.is_watertight else 'No'}\n"
        )
        if mesh.is_watertight:
            report += f"Total volume (cm^3): {mesh.volume/1000:,.2f}\n"
        st.session_state["report_text"] = report

        zip_buf = io.BytesIO()
        folder = f"{base}/"
        with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(folder, "")
            z.writestr(f"{folder}{base}_mold.stl", stl_bytes)
            z.writestr(f"{folder}{base}_settings.txt", report.encode("utf-8"))
            z.writestr(f"{folder}{up.name}", up.getvalue())
        zip_buf.seek(0)
        st.session_state["zip_bytes"] = zip_buf.getvalue()

mesh = st.session_state.get("mesh")
height_mm_built = st.session_state.get("height_mm")
zip_bytes = st.session_state.get("zip_bytes")

if (mesh is not None) and (zip_bytes is not None) and (st.session_state.get("last_sig") == current_sig):
    st.write(f"**{tr('page.cameo.labels.structure', 'Structure')}:** {tr('page.cameo.labels.solid_slicer_ready', 'Slicer-ready solid model')}")
    st.write(f"**{tr('page.cameo.labels.output_size', 'Output size')}:** {width_mm:.1f} mm x {height_mm_built:.1f} mm")
    st.write(f"**{tr('page.cameo.labels.watertight', 'Watertight')}:** {'✅' if mesh.is_watertight else '⚠️'}")

    if mesh.is_watertight:
        volume_mm3 = mesh.volume
        st.write(f"**{tr('page.cameo.labels.total_volume', 'Total volume')}:** {volume_mm3/1000:,.2f} cm3")
else:
    st.write(f"**{tr('page.cameo.labels.output_size', 'Output size')}:** {width_mm:.1f} mm x {height_mm_est:.1f} mm")

name = up.name.rsplit(".", 1)[0]
can_download = (zip_bytes is not None) and (st.session_state.get("last_sig") == current_sig)

st.download_button(
    tr("page.cameo.actions.download_zip", "Download ZIP (STL + settings)"),
    data=zip_bytes if can_download else b"",
    file_name=f"{name}_mold.zip",
    mime="application/zip",
    disabled=not can_download,
)
