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
st.set_page_config(page_title="Model Tiles & Panels Generator", layout="wide")
st.title("Model Tiles & Panels Generator")


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

    # Optional non-uniform tiling along X (repeated for every Y row)
    tile_x_mode: str = "equal"      # "equal" or "percents"
    tile_x_percents: list[float] | None = None  # tile width %s along X (must sum to 100)

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
def make_tile_boxes(
    bounds: np.ndarray,
    tiles_x: int,
    tiles_y: int,
    gap_mm: float,
    overlap_mm: float,
    margin_mm: float,
    extra_margin_mm: float,
    x_width_fracs: list[float] | None = None,
):
    """
    Build a tiles_x * tiles_y grid of axis-aligned "boxes" that cover the mesh bounds.

    If x_width_fracs is provided, it defines non-uniform tile widths along X as fractions
    that sum to 1.0 (repeated for every Y row). In that case, tiles_x is inferred from
    len(x_width_fracs).
    """
    bmin = bounds[0].astype(float).copy()
    bmax = bounds[1].astype(float).copy()

    # Shrink region inward by margin_mm (XY only)
    bmin[0] += float(margin_mm)
    bmax[0] -= float(margin_mm)
    bmin[1] += float(margin_mm)
    bmax[1] -= float(margin_mm)
    if bmax[0] <= bmin[0] or bmax[1] <= bmin[1]:
        raise ValueError("Margin is too large; tiling region collapsed.")

    # Expand Z for robustness
    bmin_exp = bmin.copy()
    bmax_exp = bmax.copy()
    bmin_exp[2] -= float(extra_margin_mm)
    bmax_exp[2] += float(extra_margin_mm)

    W = bmax[0] - bmin[0]
    H = bmax[1] - bmin[1]

    gap = max(0.0, float(gap_mm))
    overlap = max(0.0, float(overlap_mm))

    # ---- X edges ----
    if x_width_fracs:
        fracs = [float(f) for f in x_width_fracs]
        if any(f <= 0 for f in fracs):
            raise ValueError("Tile X percents must be positive.")
        s = sum(fracs)
        if s <= 0:
            raise ValueError("Tile X percents sum to zero.")
        fracs = [f / s for f in fracs]
        tiles_x_eff = len(fracs)

        gap_total_x = gap * max(0, tiles_x_eff - 1)
        avail_w = W - gap_total_x
        if avail_w <= 0:
            raise ValueError("Tile gap is too large for the mesh width / number of tiles.")

        widths = [avail_w * f for f in fracs]
        x_edges = [bmin[0]]
        cur = bmin[0]
        for w in widths:
            cur += w
            x_edges.append(cur)
            cur += gap
    else:
        tiles_x_eff = int(tiles_x)
        if tiles_x_eff < 1:
            raise ValueError("Tiles (X) must be >= 1.")
        gap_total_x = gap * max(0, tiles_x_eff - 1)
        tile_w = (W - gap_total_x) / float(tiles_x_eff)
        if tile_w <= 0:
            raise ValueError("Tile gap is too large for the mesh width / number of tiles.")
        x_edges = [bmin[0] + i * (tile_w + gap) for i in range(tiles_x_eff)]
        x_edges.append(bmin[0] + tiles_x_eff * tile_w + (tiles_x_eff - 1) * gap)

    # ---- Y edges (equal only) ----
    tiles_y_eff = int(tiles_y)
    if tiles_y_eff < 1:
        raise ValueError("Tiles (Y) must be >= 1.")
    gap_total_y = gap * max(0, tiles_y_eff - 1)
    tile_h = (H - gap_total_y) / float(tiles_y_eff)
    if tile_h <= 0:
        raise ValueError("Tile gap is too large for the mesh height / number of tiles.")
    y_edges = [bmin[1] + j * (tile_h + gap) for j in range(tiles_y_eff)]
    y_edges.append(bmin[1] + tiles_y_eff * tile_h + (tiles_y_eff - 1) * gap)

    boxes = []
    tile_meta = []
    for j in range(tiles_y_eff):
        y0 = y_edges[j]
        y1 = y_edges[j + 1]
        for i in range(tiles_x_eff):
            x0 = x_edges[i]
            x1 = x_edges[i + 1]

            bmin_k = bmin_exp.copy()
            bmax_k = bmax_exp.copy()
            bmin_k[0] = x0 - overlap - float(extra_margin_mm)
            bmax_k[0] = x1 + overlap + float(extra_margin_mm)
            bmin_k[1] = y0 - overlap - float(extra_margin_mm)
            bmax_k[1] = y1 + overlap + float(extra_margin_mm)

            extents = bmax_k - bmin_k
            center = (bmax_k + bmin_k) / 2.0
            T = np.eye(4, dtype=float)
            T[:3, 3] = center

            box = trimesh.creation.box(extents=extents, transform=T)
            boxes.append(box)
            tile_meta.append(
                {
                    "tile_x": i + 1,
                    "tile_y": j + 1,
                    "xmin": float(x0),
                    "xmax": float(x1),
                    "ymin": float(y0),
                    "ymax": float(y1),
                }
            )

    meta = {
        "tiling_bounds_mm": [float(bmin[0]), float(bmin[1]), float(bmin[2]), float(bmax[0]), float(bmax[1]), float(bmax[2])],
        "tiles_x": int(tiles_x_eff),
        "tiles_y": int(tiles_y_eff),
        "tiles": tile_meta,
    }
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
        x_width_fracs=([p / 100.0 for p in settings.tile_x_percents] if settings.tile_x_mode == "percents" and settings.tile_x_percents else None),
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


# ----------------------------
# Slice preview helpers (2D)
# ----------------------------
def _parse_percent_widths(percent_widths):
    """
    Accept either:
      - list/tuple/ndarray of numbers: [60, 40]
      - string: "60,40"
    Values represent WIDTH percentages and must sum to 100.
    Returns list[float] or None if blank.
    """
    if percent_widths is None:
        return None

    # list/tuple/numpy array
    if isinstance(percent_widths, (list, tuple, np.ndarray)):
        vals = [float(v) for v in list(percent_widths)]
        if len(vals) == 0:
            return None
    else:
        s = str(percent_widths).strip()
        if not s:
            return None
        parts = [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
        vals = [float(p) for p in parts]

    if any(v <= 0 for v in vals):
        raise ValueError("Percent widths must all be > 0.")
    total = sum(vals)
    if abs(total - 100.0) > 1e-6:
        raise ValueError(f"Percent widths must sum to 100 (got {total:.3f}).")
    return vals



def _intervals_equal(total_len: float, n: int, gap: float):
    """Return list of (a,b) intervals along length with equal widths + gaps."""
    n = int(n)
    if n <= 0:
        return []
    gap = max(0.0, float(gap))
    gap_total = gap * max(0, n - 1)
    panel_len = (float(total_len) - gap_total) / float(n)
    if panel_len <= 0:
        raise ValueError("Gap is too large for the size / number of panels.")
    cur = 0.0
    out = []
    for _ in range(n):
        a = cur
        b = a + panel_len
        out.append((a, b))
        cur = b + gap
    return out


def _intervals_from_percent_widths(total_len: float, percent_widths, gap: float):
    """
    percent_widths are WIDTH percentages that sum to 100, e.g. [60,40]
    Returns list of intervals (a,b) length = len(percent_widths)
    """
    gap = max(0.0, float(gap))
    n = len(percent_widths)
    if n <= 0:
        return []
    gap_total = gap * max(0, n - 1)
    usable = float(total_len) - gap_total
    if usable <= 0:
        raise ValueError("Gap is too large for the size / number of panels.")
    widths = [usable * (p / 100.0) for p in percent_widths]
    cur = 0.0
    out = []
    for w in widths:
        a = cur
        b = a + w
        out.append((a, b))
        cur = b + gap
    return out


def slice_preview_svg(bounds: np.ndarray, mode: str, *,
                      # panels
                      split_axis: str = "X",
                      n_panels: int = 3,
                      gap_mm: float = 0.0,
                      percent_widths=None,
                      # tiles
                      tiles_x: int = 2,
                      tiles_y: int = 2,
                      tile_gap_mm: float = 0.0,
                      tile_x_percents=None,
                      tile_y_percents=None,
                      margin_mm: float = 0.0,
                      overlap_mm: float = 0.0):
    """
    Return an SVG string showing the slice plan as a 2D rectangle in XY.
    This is purely for visualization; it does not run booleans.

    bounds: src_mesh.bounds in mm (2,3)
    """
    bmin = bounds[0].astype(float).copy()
    bmax = bounds[1].astype(float).copy()

    # Apply tiling margin (shrink region) and overlap (expand tiles) visually
    # Margin shrinks the overall rectangle
    m = max(0.0, float(margin_mm))
    bmin[0] += m; bmin[1] += m
    bmax[0] -= m; bmax[1] -= m

    W = max(1e-6, float(bmax[0] - bmin[0]))
    H = max(1e-6, float(bmax[1] - bmin[1]))

    # Canvas size
    cw, ch = 520, 520
    pad = 12
    scale = min((cw - 2 * pad) / W, (ch - 2 * pad) / H)
    ox = pad
    oy = pad

    def sx(x_mm): return ox + (x_mm - bmin[0]) * scale
    def sy(y_mm): return oy + (y_mm - bmin[1]) * scale

    # Outer rect (overall)
    x0 = sx(bmin[0]); y0 = sy(bmin[1])
    x1 = sx(bmax[0]); y1 = sy(bmax[1])

    # Build cut lines in mm coords
    v_lines = []  # x positions in mm
    h_lines = []  # y positions in mm

    mode = (mode or "").strip().lower()

    if mode == "panels":
        axis = (split_axis or "X").upper().strip()
        use_custom = _parse_percent_widths(percent_widths) is not None
        if use_custom:
            perc = _parse_percent_widths(percent_widths)
            intervals = _intervals_from_percent_widths(W if axis == "X" else H, perc, gap_mm)
        else:
            intervals = _intervals_equal(W if axis == "X" else H, n_panels, gap_mm)

        # Convert intervals into cut lines (internal boundaries)
        for i in range(1, len(intervals)):
            cut_at = intervals[i][0]
            if axis == "X":
                v_lines.append(bmin[0] + cut_at)
            else:
                h_lines.append(bmin[1] + cut_at)

    elif mode == "tiles":
        # X widths: custom or equal
        x_custom = _parse_percent_widths(tile_x_percents) is not None
        y_custom = _parse_percent_widths(tile_y_percents) is not None

        if x_custom:
            px = _parse_percent_widths(tile_x_percents)
            x_intervals = _intervals_from_percent_widths(W, px, tile_gap_mm)
        else:
            x_intervals = _intervals_equal(W, tiles_x, tile_gap_mm)

        if y_custom:
            py = _parse_percent_widths(tile_y_percents)
            y_intervals = _intervals_from_percent_widths(H, py, tile_gap_mm)
        else:
            y_intervals = _intervals_equal(H, tiles_y, tile_gap_mm)

        for i in range(1, len(x_intervals)):
            v_lines.append(bmin[0] + x_intervals[i][0])
        for i in range(1, len(y_intervals)):
            h_lines.append(bmin[1] + y_intervals[i][0])

        # Overlap is a tile-local expansion; for preview we just note it (no geometry change)
        # (You can visualize overlap later by drawing thicker grid or offset lines.)

    else:
        # fallback: no cuts
        pass

    # SVG (simple, no rounded corners)
    svg = []
    svg.append(f'<svg width="{cw}" height="{ch}" viewBox="0 0 {cw} {ch}" xmlns="http://www.w3.org/2000/svg">')
    # background
    svg.append(f'<rect x="0" y="0" width="{cw}" height="{ch}" fill="white"/>')
    # outer
    svg.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{(x1-x0):.2f}" height="{(y1-y0):.2f}" fill="none" stroke="#444" stroke-width="2"/>')

    # cut lines
    for xm in v_lines:
        X = sx(xm)
        svg.append(f'<line x1="{X:.2f}" y1="{y0:.2f}" x2="{X:.2f}" y2="{y1:.2f}" stroke="#888" stroke-width="2"/>')
    for ym in h_lines:
        Y = sy(ym)
        svg.append(f'<line x1="{x0:.2f}" y1="{Y:.2f}" x2="{x1:.2f}" y2="{Y:.2f}" stroke="#888" stroke-width="2"/>')

    # label (W x H)
    svg.append(f'<text x="{pad}" y="{ch - pad}" font-size="12" fill="#444">XY region: {W:.1f} mm × {H:.1f} mm</text>')
    if mode == "tiles" and overlap_mm:
        svg.append(f'<text x="{pad}" y="{ch - pad - 16}" font-size="12" fill="#444">tile overlap: {float(overlap_mm):.2f} mm</text>')

    svg.append('</svg>')
    return "\n".join(svg)



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
    # Settings report (human-readable; easy to archive + paste into a spreadsheet)
    def _fmt_bool(v):
        return "yes" if v else "no"

    def _vol_cm3(m: trimesh.Trimesh):
        try:
            if m.is_watertight:
                return float(m.volume) / 1000.0
        except Exception:
            return None
        return None

    lines = []
    lines.append("Model Slicer Settings")
    lines.append(f"timestamp: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"base_name: {base}")
    lines.append("")

    # Echo inputs/settings
    for k, v in asdict(settings).items():
        lines.append(f"{k}: {v}")

    # Optional metadata (keep panel/tile ranges if present)
    if meta.get("panel_intervals") is not None:
        lines.append("")
        lines.append("Panel intervals (along split axis, mm):")
        for it in meta.get("panel_intervals", []):
            try:
                lines.append(f"panel_{int(it.get('panel', 0)):02d}: {float(it.get('a')):.3f} → {float(it.get('b')):.3f}")
            except Exception:
                lines.append(str(it))

    # Output summary
    lines.append("")
    lines.append("Outputs (volume in cm³):")
    total_cm3 = 0.0
    total_ok = True
    for i, m in enumerate(panels, start=1):
        name = f"panel_{i:02d}"
        v = _vol_cm3(m)
        try:
            wt = bool(m.is_watertight)
        except Exception:
            wt = False

        if v is None:
            lines.append(f"{name}: watertight={_fmt_bool(wt)}, volume_cm3=n/a")
            total_ok = False
        else:
            lines.append(f"{name}: watertight={_fmt_bool(wt)}, volume_cm3={v:.2f}")
            total_cm3 += v

    if total_ok:
        lines.append(f"total_volume_cm3: {total_cm3:.2f}")
    else:
        lines.append(f"total_volume_cm3: {total_cm3:.2f}  (partial; some panels not watertight)")

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

    with st.expander("What do these controls do?"):
        st.markdown(
            "- **Panels:** splits the mesh into N panels along X or Y\n"
            "- **Tiles:** splits the mesh into a grid (tiles_x × tiles_y)\n"
            "- Exports a ZIP containing STL(s) + a settings text file\n"
            "- Optional: include the original uploaded mesh in the ZIP\n"
        )


with col2:
    st.subheader("Settings")

    DEFAULTS = dict(
        mode="Panels",
        split_axis="X",
        slice_mode="equal",
        n_panels=3,
        gap_mm=0.0,
        perc_text="40,60",
        tiles_x=2,
        tiles_y=3,
        tile_x_mode="equal",
        tile_x_text="60,40",
        tile_gap_mm=0.0,
        overlap_mm=0.0,
        margin_mm=0.0,
        extra_margin_mm=0.5,
        engine="manifold",
        export_zip=True,
        include_source=False,
    )

    # Initialise session state keys on first run
    for k, v in DEFAULTS.items():
        st.session_state.setdefault(k, v)

    if st.button("Reset settings", use_container_width=True):
        for k, v in DEFAULTS.items():
            st.session_state[k] = v
        # Clear any stale build so the download button disables correctly
        st.session_state["built_fingerprint"] = None
        st.session_state["zip_bytes"] = None
        st.session_state["zip_name"] = None
        st.rerun()

    ui_ok = True
    mode_key = st.radio("Slice Mode", ["Panels", "Tiles"], horizontal=True, key="mode")

    # ---------------- Panels mode ----------------
    if mode_key == "Panels":
        split_axis = st.radio("Split Axis - X • Vertical | Y  • Horizontal", ["X", "Y"], horizontal=True, key="split_axis")

        slice_mode = st.radio(
            "Panel Sizing",
            ["equal", "percents"],
            horizontal=True,
            format_func=lambda x: "Equal Panels" if x == "equal" else "Panel Widths (percent)",
            key="slice_mode",
        )

        split_percents = None
        tile_x_percents = None
        tile_y_percents = None

        if slice_mode == "percents":
            perc_str = st.text_input(
                "Panel Width percents (comma-separated)",
                help="Widths that sum to 100. Example: 20,30,50 creates 3 panels.",
                key="perc_text",
            )
            raw = [p.strip() for p in perc_str.split(",") if p.strip()]
            try:
                vals = [float(p) for p in raw]
                if any(v <= 0 for v in vals):
                    raise ValueError("All percents must be > 0.")
                s = sum(vals)
                if abs(s - 100.0) > 1e-6:
                    raise ValueError(f"Percents must sum to 100 (got {s:.3f}).")
                split_percents = vals
                n_panels = len(vals)
            except Exception as e:
                ui_ok = False
                st.error(f"Invalid percents: {e}")
                n_panels = 0
        else:
            n_panels = st.slider("Number of panels", 2, 12, key="n_panels", step=1)

        gap_mm = st.slider("Gap between panels (mm)", 0.0, 10.0, key="gap_mm", step=0.1)
        st.caption(f"Panels to be generated: {int(n_panels) if n_panels else 0}")

        # tiles defaults (not used)
        tiles_x = 1
        tiles_y = 1
        tile_gap_mm = 0.0
        overlap_mm = 0.0
        margin_mm = 0.0
        tile_x_mode = "equal"
        tile_x_percents = None

    # ---------------- Tiles mode ----------------
    else:
        st.caption("Tiles are a grid. Panel sizing is ignored in this mode.")

        tile_x_mode = st.radio(
            "Tile Sizing Columns (X - Vertical Cuts)",
            ["equal", "percents"],
            horizontal=True,
            format_func=lambda x: "Equal tiles" if x == "equal" else "Panel Widths (percent)",
            key="tile_x_mode",
        )

        tile_x_percents = None
        tile_y_percents = None  # Y-axis percent tiling not yet implemented; default to None
        if tile_x_mode == "percents":
            tx = st.text_input(
                "Tile Width percents (X - Vertical Cuts - Left→Right, comma-separated)",
                help="Widths that sum to 100. Example: 60,40 makes 2 tiles across X with a 60/40 split.",
                key="tile_x_text",
            )
            raw = [p.strip() for p in tx.split(",") if p.strip()]
            try:
                vals = [float(p) for p in raw]
                if any(v <= 0 for v in vals):
                    raise ValueError("All percents must be > 0.")
                s = sum(vals)
                if abs(s - 100.0) > 1e-6:
                    raise ValueError(f"Percents must sum to 100 (got {s:.3f}).")
                tile_x_percents = vals
                tiles_x = len(vals)
            except Exception as e:
                ui_ok = False
                st.error(f"Invalid tile X percents: {e}")
                tiles_x = 0
        else:
            tiles_x = st.slider("Tiles (X Left→Right)", 1, 12, key="tiles_x", step=1)

        tiles_y = st.slider("Tiles Rows (Y - Horizontal Cuts)", 1, 12, key="tiles_y", step=1)
        tile_gap_mm = st.slider("Gap between tiles (mm)", 0.0, 10.0, key="tile_gap_mm", step=0.1)
        overlap_mm = st.slider("Overlap (mm)", 0.0, 20.0, key="overlap_mm", step=0.1)
        margin_mm = st.slider("Margin in from bounds (mm)", 0.0, 50.0, key="margin_mm", step=0.5)

        st.caption(f"Tiles to be generated: {max(0, int(tiles_x)) * int(tiles_y)}")

        # panels defaults (not used)
        split_axis = "X"
        n_panels = 0
        gap_mm = 0.0
        slice_mode = "equal"
        split_percents = None

    # Shared
    extra_margin_mm = st.slider("Boolean box margin (mm)", 0.0, 5.0, key="extra_margin_mm", step=0.1)

    engine = st.selectbox(
        "Boolean engine",
        ["manifold", "auto", "blender", "scad"],
        help="If slicing fails, try 'auto' or install a robust engine (e.g., manifold3d).",
        key="engine",
    )

    export_zip = st.checkbox("Export as ZIP (STLs + settings)", key="export_zip")
    include_source = st.checkbox("Include original upload in ZIP", key="include_source")

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
    mode=mode_key.lower(),

    # Panels
    n_panels=int(n_panels) if mode_key == "Panels" else 0,
    split_axis=str(split_axis),
    gap_mm=float(gap_mm),
    slice_mode=str(slice_mode) if mode_key == "Panels" else "equal",
    split_percents=split_percents if mode_key == "Panels" else None,

    # Tiles
    tiles_x=int(tiles_x) if mode_key == "Tiles" else 1,
    tiles_y=int(tiles_y) if mode_key == "Tiles" else 1,
    tile_gap_mm=float(tile_gap_mm) if mode_key == "Tiles" else 0.0,
    overlap_mm=float(overlap_mm) if mode_key == "Tiles" else 0.0,
    margin_mm=float(margin_mm) if mode_key == "Tiles" else 0.0,
    tile_x_mode=str(tile_x_mode) if mode_key == "Tiles" else "equal",
    tile_x_percents=tile_x_percents if mode_key == "Tiles" else None,

    # Shared
    extra_margin_mm=float(extra_margin_mm),
    engine=str(engine),
    export_zip=bool(export_zip),
    include_source=bool(include_source),
)

# --- fingerprint / dirty check ---
current_fp = fingerprint(up.name, settings)
dirty = st.session_state.get("built_fingerprint") != current_fp

# --- user feedback ---
if dirty and st.session_state.get("zip_bytes") is not None:
    st.info("Settings changed — rebuild to update the export.")


# --- SLICE PREVIEW (2D) ---
st.subheader("Slice preview")
try:
    svg = slice_preview_svg(
        bounds=src_mesh.bounds,
        mode=settings.mode,
        split_axis=settings.split_axis,
        n_panels=settings.n_panels,
        gap_mm=settings.gap_mm,
        percent_widths=split_percents if settings.slice_mode == "percent" else None,
        tiles_x=settings.tiles_x,
        tiles_y=settings.tiles_y,
        tile_gap_mm=settings.tile_gap_mm,
        tile_x_percents=tile_x_percents,
        tile_y_percents=tile_y_percents,
        margin_mm=settings.margin_mm,
        overlap_mm=settings.overlap_mm,
    )
    st.markdown(svg, unsafe_allow_html=True)
except Exception as e:
    st.warning(f"Preview unavailable: {type(e).__name__}: {e}")


# --- BUILD BUTTON ---
build = st.button(
    "Build mesh and enable download",
    type="primary"
)

# --- BUILD ACTION ---
if build:
    with st.spinner("Slicing mesh into panels…"):

        if settings.mode == "tiles":
            panels, meta = slice_mesh_into_tiles(src_mesh, settings)
        else:
            panels, meta = slice_mesh_into_panels(src_mesh, settings)

        # build zip
        zip_bytes = build_zip(base, panels, settings, meta, source_file=up)

        # commit to session state (this is the magic)
        st.session_state["zip_bytes"] = zip_bytes
        st.session_state["zip_name"] = f"{base}_panels_{now_stamp()}.zip"
        st.session_state["built_fingerprint"] = current_fp
        st.rerun()

# --- DOWNLOAD BUTTON ---
st.download_button(
    "Download ZIP (STL + settings)",
    data=st.session_state.get("zip_bytes") or b"",
    file_name=st.session_state.get("zip_name") or f"{base}_panels.zip",
    mime="application/zip",
    disabled=(st.session_state.get("zip_bytes") is None) or dirty,
)
