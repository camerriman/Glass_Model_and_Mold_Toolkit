# triptych_slicer_app.py
# Streamlit "Triptych / Panel Slicer" — matches your current Mold Maker style:
# - left column: overview + uploader
# - right column: settings
# - build button generates panels + zip (STLs + settings txt)
#
# Notes on booleans:
# This uses trimesh boolean intersection between the source mesh and panel "boxes".
# For reliable booleans, install a boolean engine. Best modern option is usually:
#   pip install manifold3d
# If booleans fail, the app will tell you exactly what happened.

import io
import json
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime

import numpy as np
import streamlit as st
import trimesh


# ----------------------------
# Page
# ----------------------------
st.set_page_config(page_title="Model Mesh Slicer (STL)", layout="wide")
st.title("Model Mesh Slicer (STL)")


# ----------------------------
# Settings model
# ----------------------------
@dataclass
class SliceSettings:
    # Mode
    mode: str  # "panels" or "tiles"

    # Panels mode
    n_panels: int
    split_axis: str                 # "X" or "Y"
    gap_mm: float                   # spacing between panels (optional, for printing)
    slice_mode: str = "equal"       # "equal" or "percents"
    split_percents: list[float] | None = None  # panel width %s, e.g. [40, 60] -> 2 panels; [20, 30, 50] -> 3 panels

    # Tiles mode
    tiles_x: int = 2
    tiles_y: int = 2
    tile_gap_mm: float = 0.0        # gap between tiles (shrinks each tile area)
    overlap_mm: float = 0.0         # expands each tile area (useful for seams)
    margin_mm: float = 0.0          # shrink overall tiling region in from bounds

    # Shared
    extra_margin_mm: float = 0.5    # expand cutter boxes in non-split axes + Z for robustness
    engine: str = "manifold"        # "manifold" | "blender" | "scad" | "auto"
    export_zip: bool = True
    include_source: bool = False
def now_stamp() -> str:
    return datetime.now().strftime("%Y_%m_%d_%H_%M_%S")


def safe_base_name(filename: str) -> str:
    if not filename:
        return f"mesh_{now_stamp()}"
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    base = base.rsplit(".", 1)[0]
    return base or f"mesh_{now_stamp()}"


def fingerprint(filename: str, settings: SliceSettings) -> str:
    payload = {
        "filename": filename or "",
        "settings": asdict(settings),
    }
    return json.dumps(payload, sort_keys=True)


# ----------------------------
# Geometry helpers
# ----------------------------
def load_mesh(uploaded_file) -> trimesh.Trimesh:
    """
    Load an uploaded mesh. Supports .stl/.obj/.ply/.off (whatever trimesh can read).
    """
    data = uploaded_file.getvalue()
    name = uploaded_file.name.lower()
    file_type = name.rsplit(".", 1)[-1] if "." in name else None

    mesh = trimesh.load(io.BytesIO(data), file_type=file_type, force="mesh")
    if isinstance(mesh, trimesh.Scene):
        # flatten scene into a single mesh
        mesh = trimesh.util.concatenate(tuple(mesh.dump()))
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError("Upload did not load as a mesh.")
    if mesh.vertices.shape[0] < 3 or mesh.faces.shape[0] < 1:
        raise ValueError("Mesh appears empty.")
    return mesh


def make_panel_boxes(
    bounds: np.ndarray,
    n: int,
    axis: str,
    gap_mm: float,
    extra_margin_mm: float,
    mode: str = "equal",
    split_percents: list[float] | None = None,
):
    """
    Build N axis-aligned "boxes" that cover the mesh bounding box in the other axes,
    and slice it into N spans along `axis`.

    Modes:
      - mode="equal": N equal-width panels (existing behavior)
      - mode="percents": panels defined by cut percentages in split_percents
            Example: split_percents=[20, 30, 50] => 3 panels with widths 20%, 30%, 50%
            Percents are interpreted along the usable length AFTER subtracting total gaps.

    bounds: (2,3) array [[minx,miny,minz],[maxx,maxy,maxz]]
    axis: "X" or "Y"
    """
    bmin = bounds[0].astype(float)
    bmax = bounds[1].astype(float)

    # Expand non-split axes a bit so booleans don't "miss" triangles on the edges.
    bmin_exp = bmin.copy()
    bmax_exp = bmax.copy()

    axis = axis.upper().strip()
    if axis not in ("X", "Y"):
        raise ValueError("split_axis must be 'X' or 'Y'.")

    ax_i = 0 if axis == "X" else 1

    # Expand the OTHER axes (and Z) by margin
    for i in range(3):
        if i != ax_i:
            bmin_exp[i] -= float(extra_margin_mm)
            bmax_exp[i] += float(extra_margin_mm)

    total_len = bmax[ax_i] - bmin[ax_i]
    if total_len <= 0:
        raise ValueError("Mesh has zero size along the chosen split axis.")

    n = int(n)

    # total "gaps" occupy (n-1)*gap; panels shrink accordingly
    gap_total = max(0.0, float(gap_mm)) * max(0, n - 1)
    usable_len = total_len - gap_total
    if usable_len <= 0:
        raise ValueError("Gap is too large for the mesh size / number of panels.")

    mode = (mode or "equal").strip().lower()

    # Determine panel lengths (along axis) in mm
    seg_lengths: list[float] = []

    if mode == "percents":
        # `split_percents` are *panel width percentages* (not cut positions).
        # Examples:
        #   40,60 -> 2 panels (40% then 60%)
        #   20,30,50 -> 3 panels
        widths = [float(p) for p in (split_percents or [])]
        widths = [w for w in widths if w > 0]
        if len(widths) < 1:
            raise ValueError("Provide at least one positive percent (e.g. 40,60).")

        # Normalize if they don't sum to exactly 100
        total_pct = float(sum(widths))
        if total_pct <= 0:
            raise ValueError("Percent list sums to 0.")
        widths = [w / total_pct * 100.0 for w in widths]

        n = len(widths)
        gap_total = max(0.0, float(gap_mm)) * max(0, n - 1)
        usable_len = total_len - gap_total
        if usable_len <= 0:
            raise ValueError("Gap is too large for the mesh size / number of panels.")

        seg_lengths = [usable_len * (w / 100.0) for w in widths]
        # Ensure exact closure on the last segment to avoid float drift
        seg_lengths[-1] = usable_len - float(sum(seg_lengths[:-1]))

        cur = bmin[ax_i]
        for seg_len in seg_lengths:
            a = cur
            b = a + float(seg_len)
            cur = b + float(gap_mm)

            bmin_k = bmin_exp.copy()
            bmax_k = bmax_exp.copy()
            bmin_k[ax_i] = a
            bmax_k[ax_i] = b

            extents = bmax_k - bmin_k
            center = (bmax_k + bmin_k) / 2.0
            T = np.eye(4, dtype=float)
            T[:3, 3] = center
            box = trimesh.creation.box(extents=extents, transform=T)
            boxes.append(box)
            starts.append((a, b))

    else:
        # equal
        panel_len = usable_len / float(n)
        if panel_len <= 0:
            raise ValueError("Invalid panel length.")
        seg_lengths = [panel_len] * n

    boxes = []
    intervals = []

    cur = bmin[ax_i]
    for k in range(n):
        a = cur
        b = a + float(seg_lengths[k])
        cur = b + float(gap_mm)

        bmin_k = bmin_exp.copy()
        bmax_k = bmax_exp.copy()
        bmin_k[ax_i] = a
        bmax_k[ax_i] = b

        extents = bmax_k - bmin_k
        center = (bmax_k + bmin_k) / 2.0
        T = np.eye(4, dtype=float)
        T[:3, 3] = center

        box = trimesh.creation.box(extents=extents, transform=T)
        boxes.append(box)
        intervals.append((a, b))

    return boxes, intervals
def make_tile_boxes(bounds: np.ndarray, tiles_x: int, tiles_y: int,
                    gap_mm: float, overlap_mm: float, margin_mm: float,
                    extra_margin_mm: float):
    """
    Build tiles_x * tiles_y axis-aligned boxes that cover the mesh in Z,
    and partition the mesh bbox in X/Y into a grid.

    gap_mm: shrinks each tile by gap/2 on each side (creates a visible gap between tiles)
    overlap_mm: expands each tile (useful if you want overlap at seams)
    margin_mm: shrinks overall tiling region inward from the mesh bounds
    extra_margin_mm: expands Z and non-sliced axes so booleans don't miss boundary triangles
    """
    bmin = bounds[0].astype(float).copy()
    bmax = bounds[1].astype(float).copy()

    # Overall margin in X/Y only
    bmin[0] += float(margin_mm)
    bmin[1] += float(margin_mm)
    bmax[0] -= float(margin_mm)
    bmax[1] -= float(margin_mm)

    if bmax[0] <= bmin[0] or bmax[1] <= bmin[1]:
        raise ValueError("Tiling region collapsed (check margin).")

    # Expand Z (and slightly X/Y too) for robustness, using extra_margin_mm
    bmin_exp = bmin.copy()
    bmax_exp = bmax.copy()
    bmin_exp[0] -= float(extra_margin_mm)
    bmin_exp[1] -= float(extra_margin_mm)
    bmin_exp[2] -= float(extra_margin_mm)
    bmax_exp[0] += float(extra_margin_mm)
    bmax_exp[1] += float(extra_margin_mm)
    bmax_exp[2] += float(extra_margin_mm)

    total_w = bmax[0] - bmin[0]
    total_h = bmax[1] - bmin[1]
    if total_w <= 0 or total_h <= 0:
        raise ValueError("Mesh has zero X/Y span after margin.")

    pitch_x = total_w / float(tiles_x)
    pitch_y = total_h / float(tiles_y)

    boxes = []
    meta = []

    for iy in range(int(tiles_y)):
        for ix in range(int(tiles_x)):
            x0 = bmin[0] + ix * pitch_x
            x1 = bmin[0] + (ix + 1) * pitch_x
            y0 = bmin[1] + iy * pitch_y
            y1 = bmin[1] + (iy + 1) * pitch_y

            # Apply gap by shrinking each tile (creates spacing)
            g = float(gap_mm)
            if g > 0:
                x0 += g / 2.0
                x1 -= g / 2.0
                y0 += g / 2.0
                y1 -= g / 2.0

            # Apply overlap by expanding each tile
            o = float(overlap_mm)
            if o > 0:
                x0 -= o
                x1 += o
                y0 -= o
                y1 += o

            # Build box
            bmin_k = bmin_exp.copy()
            bmax_k = bmax_exp.copy()
            bmin_k[0], bmax_k[0] = x0, x1
            bmin_k[1], bmax_k[1] = y0, y1

            extents = bmax_k - bmin_k
            if np.any(extents <= 0):
                continue

            center = (bmax_k + bmin_k) / 2.0
            T = np.eye(4, dtype=float)
            T[:3, 3] = center

            box = trimesh.creation.box(extents=extents, transform=T)
            boxes.append(box)
            meta.append({
                "tile": f"x{ix+1:02d}_y{iy+1:02d}",
                "ix": ix + 1,
                "iy": iy + 1,
                "x0": float(x0), "x1": float(x1),
                "y0": float(y0), "y1": float(y1),
            })

    if not boxes:
        raise ValueError("No tile boxes produced (check gap/overlap/margin).")

    return boxes, meta

def pick_engine(engine: str):
    """
    Trimesh boolean engine selection.
    - "auto": let trimesh decide (can work, can be opaque)
    - otherwise: pass through if recognized by your trimesh build
    """
    e = (engine or "").strip().lower()
    if e in ("auto", ""):
        return None
    return e


def slice_mesh_into_panels(mesh: trimesh.Trimesh, settings: SliceSettings):
    """
    Slice mesh into N panels using boolean intersections with boxes.
    Returns list[Trimesh], plus metadata.
    """
    # Work on a copy; do not mutate the input
    src = mesh.copy()

    # Light sanity cleanup WITHOUT needing networkx:
    # (If you want more aggressive repair, do it upstream or in your slicer.)
    try:
        src.remove_unreferenced_vertices()
    except Exception:
        pass

    bounds = src.bounds
    boxes, intervals = make_panel_boxes(
        bounds=bounds,
        n=settings.n_panels,
        axis=settings.split_axis,
        gap_mm=settings.gap_mm,
        extra_margin_mm=settings.extra_margin_mm,
    )

    eng = pick_engine(settings.engine)

    panels = []
    for i, box in enumerate(boxes, start=1):
        # Boolean intersection: keep only what lies inside this box
        try:
            part = trimesh.boolean.intersection([src, box], engine=eng)
        except Exception as ex:
            raise RuntimeError(
                f"Boolean failed on panel {i}/{settings.n_panels}.\n\n"
                f"Engine: {settings.engine!r}\n"
                f"Error: {type(ex).__name__}: {ex}\n\n"
                f"Tip: install a robust boolean engine (e.g. 'manifold3d') "
                f"or switch engine in Settings."
            )

        if part is None:
            # some engines return None on failure
            raise RuntimeError(
                f"Boolean returned None on panel {i}/{settings.n_panels}.\n"
                f"Try a different engine."
            )

        # trimesh may return a Scene; flatten
        if isinstance(part, trimesh.Scene):
            part = trimesh.util.concatenate(tuple(part.dump()))

        if not isinstance(part, trimesh.Trimesh) or part.faces.shape[0] == 0:
            # It's possible (rare) a panel ends up empty due to weird bounds/gap.
            part = trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=np.int64), process=False)

        # Ensure normals/outwardness is at least consistent for slicers
        try:
            part.process(validate=True)
        except Exception:
            pass

        # If watertight but inverted, correct
        try:
            if part.is_watertight and part.volume < 0:
                part.invert()
        except Exception:
            pass

        panels.append(part)

    meta = {
        "source_bounds_mm": bounds.tolist(),
        "panel_intervals": [{"panel": i + 1, "a": float(a), "b": float(b)} for i, (a, b) in enumerate(intervals)],
    }
    return panels, meta

def slice_mesh_into_tiles(mesh: trimesh.Trimesh, settings: SliceSettings):
    src = mesh.copy()
    try:
        src.remove_unreferenced_vertices()
    except Exception:
        pass

    bounds = src.bounds
    boxes, tile_meta = make_tile_boxes(
        bounds=bounds,
        tiles_x=settings.tiles_x,
        tiles_y=settings.tiles_y,
        gap_mm=settings.tile_gap_mm,
        overlap_mm=settings.overlap_mm,
        margin_mm=settings.margin_mm,
        extra_margin_mm=settings.extra_margin_mm,
    )

    eng = pick_engine(settings.engine)

    tiles = []
    for i, box in enumerate(boxes, start=1):
        try:
            part = trimesh.boolean.intersection([src, box], engine=eng)
        except Exception as ex:
            raise RuntimeError(
                f"Boolean failed on tile {i}/{len(boxes)}.\n\n"
                f"Engine: {settings.engine!r}\n"
                f"Error: {type(ex).__name__}: {ex}"
            )

        if part is None:
            raise RuntimeError(f"Boolean returned None on tile {i}/{len(boxes)}. Try another engine.")

        if isinstance(part, trimesh.Scene):
            part = trimesh.util.concatenate(tuple(part.dump()))

        if not isinstance(part, trimesh.Trimesh) or part.faces.shape[0] == 0:
            part = trimesh.Trimesh(vertices=np.zeros((0, 3)),
                                   faces=np.zeros((0, 3), dtype=np.int64),
                                   process=False)

        try:
            part.process(validate=True)
        except Exception:
            pass

        try:
            if part.is_watertight and part.volume < 0:
                part.invert()
        except Exception:
            pass

        tiles.append(part)

    meta = {
        "source_bounds_mm": bounds.tolist(),
        "tiles": tile_meta,
    }
    return tiles, meta

def mesh_stats(mesh: trimesh.Trimesh) -> dict:
    out = {
        "vertices": int(mesh.vertices.shape[0]),
        "faces": int(mesh.faces.shape[0]),
    }
    try:
        out["watertight"] = bool(mesh.is_watertight)
    except Exception:
        out["watertight"] = None
    try:
        out["volume_mm3"] = float(mesh.volume) if out["watertight"] else None
    except Exception:
        out["volume_mm3"] = None
    try:
        b = mesh.bounds
        out["bbox_mm"] = [float(b[1, 0] - b[0, 0]), float(b[1, 1] - b[0, 1]), float(b[1, 2] - b[0, 2])]
    except Exception:
        out["bbox_mm"] = None
    return out


def build_zip(base: str, panels, settings: SliceSettings, meta: dict, source_file=None) -> bytes:
    """
    Create a zip with:
      <base>/
        <base>_settings.txt
        <base>_panel_01.stl
        <base>_panel_02.stl
        ...
        (optional) original mesh
    """
    folder = f"{base}/"

    # Settings report (human-readable, spreadsheet-friendly-ish)
    lines = []
    lines.append("Panel Slicer Settings")
    lines.append(f"timestamp: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"base_name: {base}")
    lines.append("")
    for k, v in asdict(settings).items():
        lines.append(f"{k}: {v}")
    lines.append("")
    lines.append("Source bounds (mm):")
    lines.append(json.dumps(meta.get("source_bounds_mm", None)))
    lines.append("")
    lines.append("Panel intervals:")
    lines.append(json.dumps(meta.get("panel_intervals", []), indent=2))
    lines.append("")
    lines.append("Panel stats:")
    for i, m in enumerate(panels, start=1):
        lines.append(f"panel_{i:02d}: {json.dumps(mesh_stats(m))}")

    report = "\n".join(lines) + "\n"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(folder, "")
        z.writestr(f"{folder}{base}_settings.txt", report.encode("utf-8"))

        for i, m in enumerate(panels, start=1):
            stl = m.export(file_type="stl")
            if isinstance(stl, str):
                stl = stl.encode("utf-8")
            elif not isinstance(stl, bytes):
                stl = bytes(stl)
            z.writestr(f"{folder}{base}_panel_{i:02d}.stl", stl)

        if settings.include_source and source_file is not None:
            src_bytes = source_file.getvalue()
            src_name = source_file.name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            z.writestr(f"{folder}{src_name}", src_bytes)

    buf.seek(0)
    return buf.getvalue()


# ----------------------------
# Session defaults
# ----------------------------
if "built_fingerprint" not in st.session_state:
    st.session_state["built_fingerprint"] = None
if "zip_bytes" not in st.session_state:
    st.session_state["zip_bytes"] = None
if "zip_name" not in st.session_state:
    st.session_state["zip_name"] = None


# ----------------------------
# ----------------------------
# UI
# ----------------------------
col1, col2 = st.columns([1, 1])

with col1:
    st.caption(
        "Upload a mesh and slice it into panels (triptych by default), or into a tile grid. "
        "Slicing happens only when you click **Build**."
    )
    up = st.file_uploader("Upload mesh", type=["stl", "obj", "ply", "off"])

    with st.expander("What this does"):
        st.markdown(
            "- **Panels:** splits the mesh into N panels along X or Y\n"
            "- **Tiles:** splits the mesh into a grid (tiles_x × tiles_y)\n"
            "- Exports a ZIP containing STL(s) + a settings text file\n"
            "- Optional: include the original uploaded mesh in the ZIP\n"
        )

with col2:
    st.subheader("Settings")

    mode_key = st.radio("Slice mode", ["panels", "tiles"], horizontal=True, key="mode")

    # ---- Panels mode ----
    split_percents = None
    slice_mode = "equal"
    n_panels = 3
    split_axis = "X"
    gap_mm = 0.0

    # We'll use this to disable Build when the UI is invalid.
    ui_ok = True

    if mode_key == "panels":
        split_axis = st.radio("Split axis", ["X", "Y"], horizontal=True, key="split_axis")

    slice_mode_ui = st.radio(
        "Panel sizing",
        ["equal", "percents"],
        format_func=lambda v: "Equal panels" if v == "equal" else "Custom panel width percents",
        horizontal=True,
        help="Equal = N panels of equal width. Custom = enter panel width percentages like 40,60 or 20,30,50.",
    )

    split_percents = None
    if slice_mode_ui == "equal":
        n_panels = st.slider("Number of panels", 2, 8, 3, 1, key="n_panels")
    else:
        raw = st.text_input(
            "Panel width percents (comma-separated)",
            value="40,60",
            help="Panel widths in %, left→right (or low→high). Examples: 40,60 -> 2 panels; 20,30,50 -> 3 panels. Values are normalized if they don’t sum to 100.",
            key="panel_width_percents_text",
        ).strip()
        try:
            vals = [float(p.strip()) for p in raw.split(",") if p.strip() != ""]
        except Exception:
            vals = []
        vals = [v for v in vals if v > 0]
        if len(vals) < 2:
            st.error("Enter at least two positive percents, e.g. 40,60 or 20,30,50.")
            st.stop()
        split_percents = vals
        n_panels = len(vals)

    st.caption(f"Panels to be generated: {n_panels}")

    # ---- Tiles mode ----
    tiles_x = 2
    tiles_y = 2
    tile_gap_mm = 0.0
    overlap_mm = 0.0
    margin_mm = 0.0

    if mode_key == "tiles":
        tiles_x = st.slider("Tiles (X)", 1, 10, 2, 1, key="tiles_x")
        tiles_y = st.slider("Tiles (Y)", 1, 10, 2, 1, key="tiles_y")
        tile_gap_mm = st.slider("Gap between tiles (mm)", 0.0, 10.0, 0.0, 0.1, key="tile_gap_mm")
        overlap_mm = st.slider("Overlap (mm)", 0.0, 10.0, 0.0, 0.1, key="overlap_mm")
        margin_mm = st.slider("Margin in from bounds (mm)", 0.0, 50.0, 0.0, 0.5, key="margin_mm")

    # ---- Shared ----
    extra_margin_mm = st.slider("Boolean box margin (mm)", 0.0, 5.0, 0.5, 0.1, key="extra_margin_mm")

    engine = st.selectbox(
        "Boolean engine",
        ["manifold", "auto", "blender", "scad"],
        index=0,
        help="If slicing fails, try 'auto' or install a robust engine (e.g., manifold3d).",
        key="engine",
    )

    export_zip = st.checkbox("Export as ZIP (STLs + settings)", value=True, key="export_zip")
    include_source = st.checkbox("Include original upload in ZIP", value=False, key="include_source")

    if not ui_ok:
        st.warning("Fix the settings above before building.")
if up is None:
    st.info("Upload a mesh to begin.")
    st.stop()


# Load mesh (do this once per run; it’s cheap compared to booleans)
try:
    src_mesh = load_mesh(up)
except Exception as e:
    st.error(f"Could not load mesh: {type(e).__name__}: {e}")
    st.stop()

base = safe_base_name(up.name)

settings = SliceSettings(
    mode=mode_key,

    # Panels
    n_panels=int(n_panels) if mode_key == "panels" else 0,
    split_axis=str(split_axis) if mode_key == "panels" else "X",
    gap_mm=float(gap_mm) if mode_key == "panels" else 0.0,
    slice_mode=str(slice_mode) if mode_key == "panels" else "equal",
    split_percents=split_percents if (mode_key == "panels" and slice_mode == "percents") else None,

    # Tiles
    tiles_x=int(tiles_x) if mode_key == "tiles" else 1,
    tiles_y=int(tiles_y) if mode_key == "tiles" else 1,
    tile_gap_mm=float(tile_gap_mm) if mode_key == "tiles" else 0.0,
    overlap_mm=float(overlap_mm) if mode_key == "tiles" else 0.0,
    margin_mm=float(margin_mm) if mode_key == "tiles" else 0.0,

    # Shared
    extra_margin_mm=float(extra_margin_mm),
    engine=str(engine),
    export_zip=bool(export_zip),
    include_source=bool(include_source),
)

current_fp = fingerprint(up.name, settings)

# Simple "dirty" indicator
dirty = (st.session_state["built_fingerprint"] != current_fp)

st.divider()
left, right = st.columns([1, 1])

with left:
    st.subheader("Build")
    st.write(f"**Source:** {up.name}")
    st.write(f"**Source stats:** {mesh_stats(src_mesh)}")
    if dirty:
        st.warning("Settings changed since last build. Click **Build** again before exporting.")

    build = st.button("Build", type="primary", disabled=not ui_ok)

with right:
    st.subheader("Export")
    if st.session_state["zip_bytes"] is None:
        st.caption("Build first to enable export.")
    else:
        st.caption("Ready.")
    st.download_button(
        "Download ZIP",
        data=st.session_state["zip_bytes"] if st.session_state["zip_bytes"] else b"",
        file_name=st.session_state["zip_name"] if st.session_state["zip_name"] else f"{base}_slices.zip",
        mime="application/zip",
        disabled=(st.session_state["zip_bytes"] is None) or dirty,
    )
# Build action
if build:
    with st.spinner("Slicing mesh into panels…"):
        try:
            if getattr(settings, "mode", "panels") == "tiles":
                panels, meta = slice_mesh_into_tiles(src_mesh, settings)
            else:
                panels, meta = slice_mesh_into_panels(src_mesh, settings)

        except Exception as e:
            st.session_state["zip_bytes"] = None
            st.session_state["zip_name"] = None
            st.session_state["built_fingerprint"] = None
            st.error(str(e))
            st.stop()

        # Show stats (compact)
        label = "tile(s)" if getattr(settings, "mode", "panels") == "tiles" else "panel(s)"
        st.success(f"Built {len(panels)} {label}.")

        for i, m in enumerate(panels, start=1):
            if getattr(settings, "mode", "panels") == "tiles" and meta and "tiles" in meta:
                t = meta["tiles"][i - 1]
                st.write(f"**tile_x{t['ix']:02d}_y{t['iy']:02d}** — {mesh_stats(m)}")
            else:
                st.write(f"**panel_{i:02d}** — {mesh_stats(m)}")

        if settings.export_zip:
            zip_bytes = build_zip(base, panels, settings, meta, source_file=up)
            st.session_state["zip_bytes"] = zip_bytes
            suffix = "tiles" if getattr(settings, "mode", "panels") == "tiles" else "panels"
            st.session_state["zip_name"] = f"{base}_{suffix}_{now_stamp()}.zip"
            st.session_state["built_fingerprint"] = current_fp
        else:
            st.warning("ZIP export disabled. (Enable it to download.)")
            st.session_state["zip_bytes"] = None
            st.session_state["zip_name"] = None
            st.session_state["built_fingerprint"] = current_fp