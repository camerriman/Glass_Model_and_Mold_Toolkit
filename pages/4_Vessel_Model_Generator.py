"""
4_Vessel_Model_Generator.py
Wrap a heightmap image around a user-defined vessel profile.
- Profile defined by base radius, top radius, height + optional midpoints
- Heightmap wraps once around the full circumference as surface displacement
- Output: solid printable STL (inner shell + outer displaced shell + caps)
"""

import io
import json
import hashlib
import struct
import zipfile
from datetime import date
from pathlib import Path
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from PIL import Image
from scipy.interpolate import CubicSpline
from i18n import render_app_sidebar, t as tr

st.set_page_config(page_title=tr("page.vessel.title", "Vessel Model Generator"), layout="wide")
render_app_sidebar()
st.title(tr("page.vessel.title", "Vessel Model Generator"))
st.caption(tr("page.vessel.caption", "Define a vessel profile, upload a heightmap image, and generate a wrapped printable STL."))

APP_ROOT = Path(__file__).resolve().parents[1]

# ─────────────────────────────────────────
# STL writer
# ─────────────────────────────────────────
def write_stl(triangles: np.ndarray) -> bytes:
    """triangles: (N, 3, 3) float32 — each row is 3 vertices."""
    buf = io.BytesIO()
    buf.write(b"\x00" * 80)
    n = len(triangles)
    buf.write(struct.pack("<I", n))
    for tri in triangles:
        v0, v1, v2 = tri
        normal = np.cross(v1 - v0, v2 - v0)
        nlen   = np.linalg.norm(normal)
        normal = normal / nlen if nlen > 0 else normal
        buf.write(normal.astype(np.float32).tobytes())
        buf.write(v0.astype(np.float32).tobytes())
        buf.write(v1.astype(np.float32).tobytes())
        buf.write(v2.astype(np.float32).tobytes())
        buf.write(b"\x00\x00")
    return buf.getvalue()


def quad_tris(a, b, c, d):
    """Split quad (a,b,c,d) into 2 triangles (CCW)."""
    return [np.array([a, b, c]), np.array([a, c, d])]


def format_vessel_settings(settings: dict) -> str:
    lines = [
        "Vessel Mold Model Generator Settings",
        "",
        "Profile",
        f"Cross-section: {cross_section_label(settings['cross_section'])}",
    ]
    if settings["cross_section"] == "Oval":
        lines.extend(
            [
                f"Oval width scale: {settings['oval_x_scale']:.2f}",
                f"Oval depth scale: {settings['oval_y_scale']:.2f}",
            ]
        )
    if polygon_sides_for_cross_section(settings["cross_section"]):
        lines.append(f"Sides: {polygon_sides_for_cross_section(settings['cross_section'])}")
    lines.extend(
        [
        f"Base radius (mm): {settings['base_r']:.1f}",
        f"Top radius (mm): {settings['top_r']:.1f}",
        f"Profile height (mm): {settings['height']:.1f}",
        f"Base border: {'Yes' if settings['add_base_border'] else 'No'}",
        f"Base Z (mm): {settings['base_z']:.1f}",
        f"Output height (mm): {settings['output_height']:.1f}",
        f"Demold clearance cut: {'Yes' if settings['demold_cut_enabled'] else 'No'}",
        f"Demold cutter radius (mm): {settings['demold_cut_radius']:.1f}",
        f"Demold cutter diameter (mm): {settings['demold_cut_radius'] * 2.0:.1f}",
        f"Demold apply to: {settings['demold_cut_apply']}",
        f"Demold cutter shape: {settings['demold_cut_shape']}",
        "",
        "Midpoints",
        ]
    )
    if settings["midpoints"]:
        for idx, (z_frac, radius) in enumerate(settings["midpoints"], start=1):
            lines.append(
                f"Midpoint {idx}: height {(z_frac * settings['height']):.1f} mm, radius {radius:.1f} mm"
            )
    else:
        lines.append("None")

    lines.extend(
        [
            "",
            "Wall And Relief",
            f"Min thickness (mm): {settings['wall_mm']:.1f}",
            f"Max thickness (mm): {(settings['wall_mm'] + settings['displacement']):.1f}",
            f"Relief (mm): {settings['displacement']:.1f}",
            f"Relief placement: {settings['placement_label']}",
            f"Tone mapping: {settings['tone_mapping']}",
            f"Image orientation: {settings['image_orientation']}",
            f"Fit mode: {settings['fit_mode']}",
            f"Tile same image around vessel: {'Yes' if settings['tile_enabled'] else 'No'}",
            f"Tiles around vessel: {settings['tile_count']}",
            f"Mirror alternate tiles: {'Yes' if settings['mirror_tiles'] else 'No'}",
            "",
            "Rim Relief Channel",
            f"Enabled: {'Yes' if settings['add_rim_channel'] else 'No'}",
            f"Channel radius (mm): {settings['rim_radius']:.1f}",
            f"Channel smoothness: {settings['n_rim']}",
            "",
            "Resolution",
            f"Quality preset: {settings['quality_label']}",
            f"Manual override: {'Yes' if settings['override'] else 'No'}",
            f"Angular segments: {settings['n_theta']}",
            f"Vertical segments: {settings['n_z']}",
            f"Vertical spacing (mm per ring): {settings['mm_per_ring']:.3f}",
            "",
            "Output",
            f"Triangle count: {settings['triangle_count']:,}",
        ]
    )
    if settings["bore_volume_mm3"] is not None:
        lines.append(f"Estimated internal bore volume: {settings['bore_volume_mm3'] / 1000.0:,.2f} cm³")
    lines.extend(
        [
            f"Source image: {settings['source_image_name']}",
            "",
        ]
    )
    return "\n".join(lines)


def vessel_quality_label(value: str) -> str:
    labels = {
        "Draft  (fast preview)": tr("page.vessel.quality.draft", "Draft (fast preview)"),
        "Standard": tr("page.vessel.quality.standard", "Standard"),
        "High": tr("page.vessel.quality.high", "High"),
        "Ultra  (fine detail)": tr("page.vessel.quality.ultra", "Ultra (fine detail)"),
    }
    return labels.get(value, value)


def vessel_placement_label(value: str) -> str:
    labels = {
        "Outside — relief on exterior": tr("page.vessel.placement.outside", "Outside - relief on exterior"),
        "Inside — carved interior": tr("page.vessel.placement.inside", "Inside - carved interior"),
    }
    return labels.get(value, value)


def build_vessel_bundle(
    stl_bytes: bytes,
    stl_name: str,
    settings_text: str,
    settings_json: bytes,
    source_name: str,
    source_bytes: bytes,
) -> bytes:
    bundle = io.BytesIO()
    stl_member_name = Path(stl_name).name if stl_name else "vessel_model.stl"
    source_member_name = Path(source_name).name if source_name else "source_heightmap.bin"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(stl_member_name, stl_bytes)
        zf.writestr("vessel_settings.txt", settings_text)
        zf.writestr("vessel_settings.json", settings_json)
        if source_bytes:
            zf.writestr(source_member_name, source_bytes)
    return bundle.getvalue()


# ─────────────────────────────────────────
# Profile spline
# ─────────────────────────────────────────
def build_profile(base_r, top_r, height, midpoints):
    """
    Returns a CubicSpline r(z) from base to top.
    midpoints: list of (z_frac, r) where z_frac in (0,1)
    """
    zs = [0.0] + [mp[0] * height for mp in midpoints] + [height]
    rs = [base_r] + [mp[1] for mp in midpoints] + [top_r]
    # Ensure strictly increasing z
    zs_clean, rs_clean = [zs[0]], [rs[0]]
    for z, r in zip(zs[1:], rs[1:]):
        if z > zs_clean[-1] + 1e-6:
            zs_clean.append(z)
            rs_clean.append(r)
    if len(zs_clean) < 2:
        zs_clean = [0.0, height]
        rs_clean = [base_r, top_r]
    return CubicSpline(zs_clean, rs_clean, bc_type="clamped")


def add_base_border_to_profile(profile_fn, base_r: float, profile_height: float, base_z: float):
    """Return a profile function with a smooth vertical base section below the vessel."""
    base_z = float(max(0.0, base_z))
    profile_height = float(profile_height)
    base_r = float(base_r)
    if base_z <= 0.0:
        return profile_fn

    def profile_with_border(z):
        z_np = np.asarray(z, dtype=np.float64)
        shifted = np.clip(z_np - base_z, 0.0, profile_height)
        radius = np.where(z_np < base_z, base_r, profile_fn(shifted))
        if np.isscalar(z):
            return float(radius)
        return radius

    return profile_with_border


POLYGON_CROSS_SECTIONS = {
    "3 sides": 3,
    "4 sides": 4,
    "5 sides": 5,
    "6 sides": 6,
}


def cross_section_options() -> list[str]:
    return ["Circle", "Oval", *POLYGON_CROSS_SECTIONS.keys()]


def cross_section_label(value: str) -> str:
    labels = {
        "Circle": tr("page.vessel.cross_section.circle", "Circle"),
        "Oval": tr("page.vessel.cross_section.oval", "Oval"),
        "3 sides": tr("page.vessel.cross_section.triangle", "3 sides - triangle"),
        "4 sides": tr("page.vessel.cross_section.square", "4 sides - square"),
        "5 sides": tr("page.vessel.cross_section.pentagon", "5 sides"),
        "6 sides": tr("page.vessel.cross_section.hexagon", "6 sides"),
    }
    return labels.get(value, str(value))


def polygon_sides_for_cross_section(cross_section: str | None) -> int | None:
    return POLYGON_CROSS_SECTIONS.get(str(cross_section or "").strip())


def polygon_radius_scale(theta_value, sides: int):
    theta_np = np.asarray(theta_value, dtype=np.float64)
    sector = 2.0 * np.pi / float(sides)
    delta = ((theta_np + sector / 2.0) % sector) - sector / 2.0
    scale = np.cos(np.pi / float(sides)) / np.maximum(np.cos(delta), 1e-6)
    if np.isscalar(theta_value):
        return float(scale)
    return scale


def cross_section_radius_scale(theta_value, cross_section: str | None, oval_x_scale=1.0, oval_y_scale=1.0):
    sides = polygon_sides_for_cross_section(cross_section)
    if sides:
        return polygon_radius_scale(theta_value, sides)
    if str(cross_section or "") == "Oval":
        theta_np = np.asarray(theta_value, dtype=np.float64)
        scale = np.sqrt((float(oval_x_scale) * np.cos(theta_np)) ** 2 + (float(oval_y_scale) * np.sin(theta_np)) ** 2)
        if np.isscalar(theta_value):
            return float(scale)
        return scale
    if np.isscalar(theta_value):
        return 1.0
    return np.ones_like(np.asarray(theta_value, dtype=np.float64))


def cross_section_area_factor(cross_section: str | None, oval_x_scale=1.0, oval_y_scale=1.0) -> float:
    sides = polygon_sides_for_cross_section(cross_section)
    if sides:
        return float(sides * np.sin(2.0 * np.pi / sides) / (2.0 * np.pi))
    return float(oval_x_scale) * float(oval_y_scale)


def estimate_internal_bore_volume_mm3(
    profile_fn,
    height,
    wall_mm,
    displacement,
    placement="outside",
    n_theta=180,
    n_z=120,
    heightmap=None,
    cross_section="Circle",
    oval_x_scale=1.0,
    oval_y_scale=1.0,
    base_z=0.0,
    demold_cut_enabled=False,
    demold_cut_radius=0.0,
    demold_cut_apply="Base transition",
    demold_cut_shape="Match vessel cross-section",
):
    """
    Estimate open bore volume in mm^3 from bottom to top.
    For outside relief, the bore follows the smooth profile.
    For inside relief, the bore follows the carved inner wall and requires a heightmap.
    """
    z_arr = np.linspace(0.0, float(height), int(n_z), dtype=np.float64)
    r_base = np.clip(profile_fn(z_arr), 1.0, None).astype(np.float64)
    base_z = float(max(0.0, base_z))
    demold_cut_enabled = bool(demold_cut_enabled)
    demold_cut_radius = float(max(0.0, demold_cut_radius))

    if placement == "inside" and heightmap is not None:
        hmap = np.asarray(heightmap, dtype=np.float64)
        inner_r = np.maximum(
            1.0,
            r_base[:, None] - hmap * float(displacement),
        )
        if demold_cut_enabled and demold_cut_radius > 0:
            if demold_cut_apply == "Full height":
                cut_mask = np.ones_like(z_arr, dtype=bool)
            elif demold_cut_apply == "Base border only":
                cut_mask = z_arr < base_z
            else:
                meets = np.where(r_base >= demold_cut_radius)[0]
                transition_cut_top_z = float(z_arr[meets[0]]) if len(meets) else float(height)
                cut_mask = z_arr <= max(base_z, transition_cut_top_z)

            if demold_cut_shape == "Circular cutter":
                theta = np.linspace(0, 2 * np.pi, inner_r.shape[1], endpoint=False)
                scale = cross_section_radius_scale(theta, cross_section, oval_x_scale, oval_y_scale)
                cutter = demold_cut_radius / np.maximum(scale, 1e-6)
            else:
                cutter = np.full(inner_r.shape[1], demold_cut_radius, dtype=np.float64)
            inner_r[cut_mask, :] = np.maximum(inner_r[cut_mask, :], cutter[None, :])
        area_mm2 = np.pi * np.mean(inner_r ** 2, axis=1)
    else:
        inner_r = np.maximum(1.0, r_base - float(wall_mm))
        area_mm2 = np.pi * (inner_r ** 2)

    area_mm2 = area_mm2 * cross_section_area_factor(cross_section, oval_x_scale, oval_y_scale)
    return float(np.trapz(area_mm2, z_arr))


# ─────────────────────────────────────────
# Heightmap loader
# ─────────────────────────────────────────
def blend_heightmap_wrap(img: np.ndarray) -> np.ndarray:
    """Cosine-blend left/right edges so a heightmap wraps cleanly."""
    img = np.array(img, dtype=np.float32, copy=True)
    blend_w = max(1, int(img.shape[1] * 0.05))
    fade = np.linspace(0.0, 1.0, blend_w, dtype=np.float32)
    for i in range(blend_w):
        t = fade[i]
        img[:, i] = img[:, i] * t + img[:, -(blend_w - i)] * (1 - t)
    for i in range(blend_w):
        t = fade[i]
        img[:, -(i + 1)] = img[:, -(i + 1)] * t + img[:, blend_w - i - 1] * (1 - t)
    return img


def resize_heightmap(img: np.ndarray, target_rows: int, target_cols: int, fit_mode: str) -> np.ndarray:
    """Resize to a tile canvas while keeping relief aligned to vessel height."""
    from scipy.ndimage import zoom

    fit_mode = fit_mode or "Stretch to tile"
    if fit_mode == "Stretch to tile":
        return zoom(img, (target_rows / img.shape[0], target_cols / img.shape[1]), order=3)

    scale_h = target_rows / img.shape[0]
    scale_w = target_cols / img.shape[1]
    if fit_mode == "Fit inside tile":
        # Preserve aspect ratio, but always fill vessel height so relief starts at
        # the base and reaches the rim. Only the angular direction may pad/crop.
        scale = scale_h
    else:
        scale = max(scale_h, scale_w)
    resized = zoom(img, (scale, scale), order=3)
    edge_value = float(np.mean(
        [
            resized[0, :].mean(),
            resized[-1, :].mean(),
            resized[:, 0].mean(),
            resized[:, -1].mean(),
        ]
    ))
    out = np.full((target_rows, target_cols), edge_value, dtype=np.float32)

    if resized.shape[0] >= target_rows:
        src_y0 = (resized.shape[0] - target_rows) // 2
        dst_y0 = 0
        copy_rows = target_rows
    else:
        src_y0 = 0
        dst_y0 = (target_rows - resized.shape[0]) // 2
        copy_rows = resized.shape[0]

    if resized.shape[1] >= target_cols:
        src_x0 = (resized.shape[1] - target_cols) // 2
        dst_x0 = 0
        copy_cols = target_cols
    else:
        src_x0 = 0
        dst_x0 = (target_cols - resized.shape[1]) // 2
        copy_cols = resized.shape[1]

    out[dst_y0 : dst_y0 + copy_rows, dst_x0 : dst_x0 + copy_cols] = resized[
        src_y0 : src_y0 + copy_rows,
        src_x0 : src_x0 + copy_cols,
    ]
    if dst_x0 > 0:
        out[dst_y0 : dst_y0 + copy_rows, :dst_x0] = out[dst_y0 : dst_y0 + copy_rows, dst_x0 : dst_x0 + 1]
    if dst_x0 + copy_cols < target_cols:
        out[dst_y0 : dst_y0 + copy_rows, dst_x0 + copy_cols :] = out[
            dst_y0 : dst_y0 + copy_rows,
            dst_x0 + copy_cols - 1 : dst_x0 + copy_cols,
        ]
    if dst_y0 > 0:
        out[:dst_y0, :] = out[dst_y0 : dst_y0 + 1, :]
    if dst_y0 + copy_rows < target_rows:
        out[dst_y0 + copy_rows :, :] = out[dst_y0 + copy_rows - 1 : dst_y0 + copy_rows, :]
    return out


def load_heightmap(
    uploaded_file,
    n_theta: int,
    n_z: int,
    tile_count: int = 1,
    orientation: str = "Upright",
    fit_mode: str = "Stretch to tile",
    mirror_tiles: bool = False,
) -> np.ndarray:
    """
    Returns (n_z, n_theta) float array in [0, 1].
    Rows = Z slices (bottom to top), Cols = angle slices.
    tile_count > 1 repeats the same uploaded image around the circumference.
    mirror_tiles alternates normal/mirrored copies and works best with even tile counts.
    orientation controls whether image top maps to vessel top or bottom.
    fit_mode controls stretch/contain/cover behavior inside each tile.
    Uses Pillow + scipy — no cv2 required.
    """
    if isinstance(uploaded_file, (bytes, bytearray)):
        uploaded_file = io.BytesIO(uploaded_file)
    else:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass

    img = Image.open(uploaded_file).convert("L")
    img = np.asarray(img, dtype=np.float32) / 255.0

    tile_count = max(1, int(tile_count))
    tile_cols = n_theta if tile_count == 1 else int(np.ceil(n_theta / tile_count))

    img = resize_heightmap(img, n_z, tile_cols, fit_mode)

    if orientation == "Upright":
        # Mesh row 0 is vessel bottom, so flip to make image top map to vessel top.
        img = img[::-1, :]
    if not (mirror_tiles and tile_count > 1 and tile_count % 2 == 0):
        img = blend_heightmap_wrap(img)

    if tile_count > 1:
        if mirror_tiles and tile_count % 2 == 0:
            mirrored = img[:, ::-1]
            tiles = [img if idx % 2 == 0 else mirrored for idx in range(tile_count)]
            img = np.concatenate(tiles, axis=1)[:, :n_theta]
        else:
            img = np.tile(img, (1, tile_count))[:, :n_theta]

    return np.clip(img, 0.0, 1.0)


@st.cache_data(show_spinner=False)
def load_heightmap_cached(
    file_bytes: bytes,
    n_theta: int,
    n_z: int,
    tile_count: int = 1,
    orientation: str = "Upright",
    fit_mode: str = "Stretch to tile",
    mirror_tiles: bool = False,
) -> np.ndarray:
    return load_heightmap(file_bytes, n_theta, n_z, tile_count, orientation, fit_mode, mirror_tiles)


def load_heightmap_for_output(
    file_bytes: bytes,
    n_theta: int,
    profile_n_z: int,
    base_n_z: int,
    orientation: str,
    fit_mode: str,
    tile_count: int,
    mirror_tiles: bool,
    invert_relief: bool,
) -> np.ndarray:
    """Load relief for the profiled vessel area and prepend blank rows for a base border."""
    hmap = load_heightmap_cached(file_bytes, n_theta, profile_n_z, tile_count, orientation, fit_mode, mirror_tiles)
    if invert_relief:
        hmap = 1.0 - hmap
    if base_n_z > 0:
        blank = np.zeros((int(base_n_z), int(n_theta)), dtype=np.float32)
        hmap = np.vstack([blank, hmap])
    return np.clip(hmap, 0.0, 1.0)


# ─────────────────────────────────────────
# Mesh builder
# ─────────────────────────────────────────
def build_vase_mesh(
    profile_fn,
    height,
    displacement,
    heightmap,
    n_theta,
    n_z,
    wall_mm,
    placement="outside",
    add_rim_channel=False,
    rim_radius=0.0,
    n_rim=24,
    cross_section="Circle",
    oval_x_scale=1.0,
    oval_y_scale=1.0,
    base_z=0.0,
    demold_cut_enabled=False,
    demold_cut_radius=0.0,
    demold_cut_apply="Base transition",
    demold_cut_shape="Match vessel cross-section",
):
    """
    Build solid open-ended mold tube mesh.
    placement="outside": heightmap displaces outward from outer wall (relief on exterior)
    placement="inside":  heightmap displaces inward from inner wall (carved interior)
    - The relief-bearing surface stays fixed when base thickness changes.
    - Base thickness adds structure on the smooth opposite side.
    - Optional rim channel cuts a quarter-round clearance into the top corner on
      the relief-bearing side.
    Returns array of (3,3) triangle arrays.
    """
    theta = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)
    z_arr = np.linspace(0.0, float(height), int(n_z), dtype=np.float64)
    r_base = np.clip(profile_fn(z_arr), 1.0, None)
    heightmap = np.asarray(heightmap, dtype=np.float64)
    smooth_top_radius = float(r_base[-1])
    oval_x_scale = float(oval_x_scale)
    oval_y_scale = float(oval_y_scale)
    base_z = float(max(0.0, base_z))
    demold_cut_enabled = bool(demold_cut_enabled)
    demold_cut_radius = float(max(0.0, demold_cut_radius))
    demold_cut_apply = demold_cut_apply or "Base transition"
    demold_cut_shape = demold_cut_shape or "Match vessel cross-section"
    transition_cut_top_z = 0.0
    if demold_cut_enabled and demold_cut_apply == "Base transition" and demold_cut_radius > 0:
        meets = np.where(r_base >= demold_cut_radius)[0]
        transition_cut_top_z = float(z_arr[meets[0]]) if len(meets) else float(height)

    def point_from_radius(r, t, z):
        if polygon_sides_for_cross_section(cross_section):
            scale = cross_section_radius_scale(t, cross_section, oval_x_scale, oval_y_scale)
            return np.array([r * scale * np.cos(t), r * scale * np.sin(t), z], dtype=np.float32)
        return np.array([r * oval_x_scale * np.cos(t), r * oval_y_scale * np.sin(t), z], dtype=np.float32)

    def demold_radius_for_theta(t):
        if demold_cut_shape == "Circular cutter":
            scale = cross_section_radius_scale(t, cross_section, oval_x_scale, oval_y_scale)
            return demold_cut_radius / max(float(scale), 1e-6)
        return demold_cut_radius

    def demold_cut_active(iz):
        if not demold_cut_enabled or demold_cut_radius <= 0:
            return False
        if demold_cut_apply == "Full height":
            return True
        if demold_cut_apply == "Base border only":
            return z_arr[iz] < base_z
        return z_arr[iz] <= max(base_z, transition_cut_top_z)

    tris = []
    rim_radius = float(max(0.0, rim_radius))
    rim_active = bool(add_rim_channel and rim_radius > 0.0 and n_rim >= 2)
    if rim_active:
        rim_radius = min(rim_radius, float(wall_mm), float(height) - 0.1)
        rim_wall_z = float(height) - rim_radius
        rim_arc = np.linspace(0.0, np.pi / 2.0, int(n_rim) + 1, dtype=np.float64)
        rim_base_idx = max(0, int(np.searchsorted(z_arr, rim_wall_z, side="left")) - 1)
    else:
        rim_wall_z = float(height)
        rim_arc = None
        rim_base_idx = len(z_arr) - 2

    if placement == "outside":
        # Outer relief surface stays fixed. Base thickness adds inward.
        def inner_v(iz, it):
            r = max(1.0, r_base[iz] - wall_mm)
            t = theta[it]
            return point_from_radius(r, t, z_arr[iz])

        def outer_v(iz, it):
            r = r_base[iz] + heightmap[iz, it % n_theta] * displacement
            t = theta[it]
            return point_from_radius(r, t, z_arr[iz])

        def inner_top_radius(_it):
            return float(max(1.0, r_base[-1] - wall_mm))

        def outer_top_radius(it):
            return float(r_base[-1] + heightmap[-1, it % n_theta] * displacement)
    else:
        # Inner relief surface stays fixed. Base thickness adds outward.
        def inner_v(iz, it):
            if z_arr[iz] < base_z:
                r = max(1.0, r_base[iz] - displacement)
            else:
                r = max(1.0, r_base[iz] - heightmap[iz, it % n_theta] * displacement)
            if demold_cut_active(iz):
                r = max(r, demold_radius_for_theta(theta[it]))
            t = theta[it]
            return point_from_radius(r, t, z_arr[iz])

        def outer_v(iz, it):
            r = r_base[iz] + wall_mm
            t = theta[it]
            return point_from_radius(r, t, z_arr[iz])

        def outer_top_radius(_it):
            return float(r_base[-1] + wall_mm)

        def inner_top_radius(it):
            return float(max(1.0, r_base[-1] - heightmap[-1, it % n_theta] * displacement))

    if rim_active:
        if placement == "outside":
            rim_edge_radius = smooth_top_radius + rim_radius
            clean_top_inner_radius = max(1.0, smooth_top_radius - wall_mm)
            clean_top_outer_radius = smooth_top_radius
        else:
            rim_edge_radius = max(1.0, smooth_top_radius - rim_radius)
            clean_top_inner_radius = smooth_top_radius
            clean_top_outer_radius = smooth_top_radius + wall_mm
    else:
        rim_edge_radius = None
        clean_top_inner_radius = None
        clean_top_outer_radius = None

    # ── Outer surface ──
    outer_stop = rim_base_idx if rim_active and placement == "outside" else len(z_arr) - 1
    for iz in range(outer_stop):
        for it in range(n_theta):
            it1 = (it + 1) % n_theta
            a = outer_v(iz,     it)
            b = outer_v(iz,     it1)
            c = outer_v(iz + 1, it1)
            d = outer_v(iz + 1, it)
            tris.extend(quad_tris(a, b, c, d))

    if rim_active and placement == "outside":
        iz = rim_base_idx
        for it in range(n_theta):
            it1 = (it + 1) % n_theta

            def wall_end(theta_idx):
                r = rim_edge_radius
                t = theta[theta_idx]
                return point_from_radius(r, t, rim_wall_z)

            a = outer_v(iz, it)
            b = outer_v(iz, it1)
            c = wall_end(it1)
            d = wall_end(it)
            tris.extend(quad_tris(a, b, c, d))

    # ── Inner surface (reversed winding) ──
    inner_stop = rim_base_idx if rim_active and placement == "inside" else len(z_arr) - 1
    for iz in range(inner_stop):
        for it in range(n_theta):
            it1 = (it + 1) % n_theta
            a = inner_v(iz,     it)
            b = inner_v(iz,     it1)
            c = inner_v(iz + 1, it1)
            d = inner_v(iz + 1, it)
            tris.extend(quad_tris(d, c, b, a))   # reversed

    if rim_active and placement == "inside":
        iz = rim_base_idx
        for it in range(n_theta):
            it1 = (it + 1) % n_theta

            def wall_end(theta_idx):
                r = rim_edge_radius
                t = theta[theta_idx]
                return point_from_radius(r, t, rim_wall_z)

            a = inner_v(iz, it)
            b = inner_v(iz, it1)
            c = wall_end(it1)
            d = wall_end(it)
            tris.extend(quad_tris(d, c, b, a))

    # ── Bottom annulus — normal points downward ──
    iz = 0
    for it in range(n_theta):
        it1 = (it + 1) % n_theta
        a = inner_v(iz, it)
        b = inner_v(iz, it1)
        c = outer_v(iz, it1)
        d = outer_v(iz, it)
        tris.extend(quad_tris(a, b, c, d))

    # ── Top cap — reversed winding so normal points upward ──
    iz = len(z_arr) - 1
    for it in range(n_theta):
        it1 = (it + 1) % n_theta
        if rim_active and placement == "outside":
            t1 = theta[it1]
            t0 = theta[it]
            a = point_from_radius(clean_top_inner_radius, t0, height)
            b = point_from_radius(clean_top_inner_radius, t1, height)
            c = point_from_radius(clean_top_outer_radius, t1, height)
            d = point_from_radius(clean_top_outer_radius, t0, height)
        elif rim_active and placement == "inside":
            t0 = theta[it]
            t1 = theta[it1]
            a = point_from_radius(clean_top_inner_radius, t0, height)
            b = point_from_radius(clean_top_inner_radius, t1, height)
            c = point_from_radius(clean_top_outer_radius, t1, height)
            d = point_from_radius(clean_top_outer_radius, t0, height)
        else:
            a = inner_v(iz, it)
            b = inner_v(iz, it1)
            c = outer_v(iz, it1)
            d = outer_v(iz, it)
        tris.extend(quad_tris(d, c, b, a))

    if rim_active:
        for it in range(n_theta):
            it1 = (it + 1) % n_theta
            for ia in range(len(rim_arc) - 1):
                phi0 = rim_arc[ia]
                phi1 = rim_arc[ia + 1]

                if placement == "outside":
                    def groove_v(theta_idx, phi):
                        t = theta[theta_idx]
                        center_r = smooth_top_radius + rim_radius
                        r = center_r - rim_radius * np.cos(phi)
                        z = height - rim_radius * np.sin(phi)
                        return point_from_radius(r, t, z)

                    a = groove_v(it, phi0)
                    b = groove_v(it1, phi0)
                    c = groove_v(it1, phi1)
                    d = groove_v(it, phi1)
                    tris.extend(quad_tris(d, c, b, a))
                else:
                    def groove_v(theta_idx, phi):
                        t = theta[theta_idx]
                        center_r = smooth_top_radius - rim_radius
                        r = center_r + rim_radius * np.cos(phi)
                        z = height - rim_radius * np.sin(phi)
                        return point_from_radius(r, t, z)

                    a = groove_v(it, phi0)
                    b = groove_v(it1, phi0)
                    c = groove_v(it1, phi1)
                    d = groove_v(it, phi1)
                    tris.extend(quad_tris(a, b, c, d))

    return np.array(tris, dtype=np.float32)


# ─────────────────────────────────────────
# Plotly preview (subsampled outer surface)
# ─────────────────────────────────────────
def make_preview(tris: np.ndarray) -> go.Figure:
    MAX_TRIS = 20_000
    if len(tris) > MAX_TRIS:
        idx  = np.random.choice(len(tris), MAX_TRIS, replace=False)
        tris = tris[idx]

    verts  = tris.reshape(-1, 3)
    t_idx  = np.arange(len(tris) * 3).reshape(-1, 3)

    fig = go.Figure(go.Mesh3d(
        x=verts[:, 0], y=verts[:, 1], z=verts[:, 2],
        i=t_idx[:, 0], j=t_idx[:, 1], k=t_idx[:, 2],
        color="#b5651d", opacity=0.9,
        flatshading=False,
        lighting=dict(ambient=0.5, diffuse=0.8, specular=0.3, roughness=0.5),
        lightposition=dict(x=100, y=200, z=300),
    ))
    fig.update_layout(
        scene=dict(
            aspectmode="data",
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            zaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            bgcolor="#f5f5f0",
        ),
        paper_bgcolor="#ffffff",
        font_color="#333333",
        margin=dict(l=0, r=0, t=0, b=0),
        height=500,
    )
    return fig


# ─────────────────────────────────────────
# Profile preview (2D cross-section)
# ─────────────────────────────────────────
def make_profile_preview(profile_fn, height, wall_mm,
                         displacement, placement="outside",
                         midpoints=None, n_z=200, base_z=0.0, profile_height=None,
                         demold_cut_enabled=False, demold_cut_radius=0.0,
                         demold_cut_apply="Base transition") -> go.Figure:
    z      = np.linspace(0, height, n_z)
    r_base = np.clip(profile_fn(z), 1.0, None)
    avg_d  = displacement * 0.5   # average relief for preview
    relief_preview = np.where(z < float(base_z), 0.0, avg_d)

    # Fixed reference axes match print bed: 300mm wide, 300mm tall
    # Profile scales visually within this window — axes never move
    FIXED_R = 150.0    # half of 300mm bed width
    FIXED_H = 200.0    # 200mm max height
    x_range = [-FIXED_R, FIXED_R]
    y_range = [0, FIXED_H]

    if placement == "outside":
        r_inner = np.maximum(1.0, r_base - wall_mm)
        r_outer = r_base + relief_preview
        inner_label = "Interior surface (smooth)"
        outer_label = "Exterior surface (avg relief)"
    else:
        border_relief = np.where(z < float(base_z), displacement, relief_preview)
        r_inner = np.maximum(1.0, r_base - border_relief)
        if demold_cut_enabled and demold_cut_radius > 0:
            if demold_cut_apply == "Full height":
                cut_mask = np.ones_like(z, dtype=bool)
            elif demold_cut_apply == "Base border only":
                cut_mask = z < float(base_z)
            else:
                meets = np.where(r_base >= float(demold_cut_radius))[0]
                transition_cut_top_z = float(z[meets[0]]) if len(meets) else float(height)
                cut_mask = z <= max(float(base_z), transition_cut_top_z)
            r_inner = np.where(cut_mask, np.maximum(r_inner, float(demold_cut_radius)), r_inner)
        r_outer = r_base + wall_mm
        inner_label = "Interior surface (avg relief)"
        outer_label = "Exterior surface (smooth)"

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=np.concatenate([r_outer, -r_outer[::-1]]),
        y=np.concatenate([z, z[::-1]]),
        fill="toself", fillcolor="rgba(181,101,29,0.08)",
        line=dict(color="#c87941", width=1.5, dash="dash"),
        name=outer_label,
    ))
    fig.add_trace(go.Scatter(
        x=np.concatenate([r_inner, -r_inner[::-1]]),
        y=np.concatenate([z, z[::-1]]),
        fill="toself", fillcolor="rgba(181,101,29,0.15)",
        line=dict(color="#b5651d", width=2),
        name=inner_label,
    ))

    # Draw midpoint reference lines
    if midpoints:
        for i, (z_frac, r_mid) in enumerate(midpoints):
            z_pos = float(base_z) + z_frac * float(profile_height or height)
            fig.add_hline(y=z_pos,
                          line=dict(color="#6699cc", width=1, dash="dot"),
                          annotation_text=f"  MP{i+1}  {z_pos:.0f}mm  r={r_mid:.0f}mm",
                          annotation_position="right",
                          annotation_font=dict(size=10, color="#6699cc"))

    if base_z > 0:
        fig.add_hline(
            y=float(base_z),
            line=dict(color="#888888", width=1, dash="dash"),
            annotation_text=f"  Base border {base_z:.0f}mm",
            annotation_position="left",
            annotation_font=dict(size=10, color="#666666"),
        )
    if placement == "inside" and demold_cut_enabled and demold_cut_radius > 0:
        fig.add_vline(
            x=float(demold_cut_radius),
            line=dict(color="#cc5555", width=1, dash="dash"),
            annotation_text=f"  cutter r={demold_cut_radius:.0f}mm",
            annotation_position="top right",
            annotation_font=dict(size=10, color="#aa3333"),
        )
        fig.add_vline(
            x=-float(demold_cut_radius),
            line=dict(color="#cc5555", width=1, dash="dash"),
        )

    fig.update_layout(
        title="Profile cross-section",
        xaxis=dict(title="Radius (mm)", zeroline=True, range=x_range),
        yaxis=dict(title="Height (mm)", zeroline=False, range=y_range),
        plot_bgcolor="#f8f8f4",
        paper_bgcolor="#ffffff",
        font_color="#333333",
        width=420,
        height=500,
        showlegend=True,
        legend=dict(bgcolor="rgba(255,255,255,0.8)", bordercolor="#cccccc", borderwidth=1),
    )
    return fig


# ─────────────────────────────────────────
# UI
# ─────────────────────────────────────────
st.session_state.setdefault("stl_bytes", None)
st.session_state.setdefault("stl_tri_count", 0)
st.session_state.setdefault("vessel_stl_name", "vessel_model.stl")
st.session_state.setdefault("vessel_zip_bytes", None)
st.session_state.setdefault("vessel_zip_name", "vessel_model_bundle.zip")
st.session_state.setdefault("vessel_settings_text", "")
st.session_state.setdefault("vessel_upload_nonce", 0)
st.session_state.setdefault("vessel_is_building", False)
st.session_state.setdefault("vessel_reset_pending", False)
st.session_state.setdefault("vessel_generated_signature", None)
st.session_state.setdefault("vessel_loaded_heightmap_bytes", None)
st.session_state.setdefault("vessel_loaded_heightmap_name", "")

VESSEL_DEFAULTS = {
    "vessel_title": "",
    "vessel_job_date": date.today(),
    "vessel_base_r": 20.0,
    "vessel_top_r": 50.0,
    "vessel_height": 60.0,
    "vessel_cross_section": "Circle",
    "vessel_oval_x_scale": 1.0,
    "vessel_oval_y_scale": 1.0,
    "vessel_add_base_border": False,
    "vessel_base_border_mode": "No border",
    "vessel_base_z": 0.0,
    "vessel_demold_cut_enabled": False,
    "vessel_demold_cut_radius": 0.0,
    "vessel_demold_cut_apply": "Base transition",
    "vessel_demold_cut_shape": "Match vessel cross-section",
    "vessel_n_mid": 1,
    "vessel_wall_mm": 3.0,
    "vessel_displacement": 2.0,
    "vessel_max_thickness": 5.0,
    "vessel_placement": "Outside — relief on exterior",
    "vessel_invert_relief": False,
    "vessel_tone_mapping": "Positive",
    "vessel_image_orientation": "Upright",
    "vessel_fit_mode": "Stretch to tile",
    "vessel_tile_enabled": False,
    "vessel_tile_count": 4,
    "vessel_mirror_tiles": False,
    "vessel_add_lip": False,
    "vessel_lip_radius": 1.5,
    "vessel_n_lip": 24,
    "vessel_quality": "Standard",
    "vessel_override": False,
    "vessel_ov_theta": 180,
    "vessel_ov_z": 0.5,
    "vessel_source_image_name": "",
    "vessel_notes": "",
}

for key, value in VESSEL_DEFAULTS.items():
    st.session_state.setdefault(key, value)


def reset_vessel_defaults() -> None:
    for key, value in VESSEL_DEFAULTS.items():
        st.session_state[key] = value
    for idx in range(4):
        st.session_state.pop(f"vessel_zf_{idx}", None)
        st.session_state.pop(f"vessel_rm_{idx}", None)
    st.session_state["vessel_upload_nonce"] = st.session_state.get("vessel_upload_nonce", 0) + 1
    st.session_state["stl_bytes"] = None
    st.session_state["stl_tri_count"] = 0
    st.session_state["vessel_stl_name"] = "vessel_model.stl"
    st.session_state["vessel_zip_bytes"] = None
    st.session_state["vessel_zip_name"] = "vessel_model_bundle.zip"
    st.session_state["vessel_settings_text"] = ""
    st.session_state["vessel_is_building"] = False
    st.session_state["vessel_reset_pending"] = False
    st.session_state["vessel_generated_signature"] = None
    st.session_state["vessel_loaded_heightmap_bytes"] = None
    st.session_state["vessel_loaded_heightmap_name"] = ""


def clear_vessel_outputs() -> None:
    st.session_state["stl_bytes"] = None
    st.session_state["stl_tri_count"] = 0
    st.session_state["vessel_stl_name"] = "vessel_model.stl"
    st.session_state["vessel_zip_bytes"] = None
    st.session_state["vessel_zip_name"] = "vessel_model_bundle.zip"
    st.session_state["vessel_settings_text"] = ""
    st.session_state["vessel_is_building"] = False
    st.session_state["vessel_generated_signature"] = None


def serialize_vessel_value(value):
    if isinstance(value, date):
        return value.isoformat()
    return value


def build_vessel_setup_payload(
    source_image_name: str,
    midpoints: list[tuple[float, float]],
    bore_volume_mm3: float,
) -> dict:
    values = {
        key: serialize_vessel_value(st.session_state.get(key, default))
        for key, default in VESSEL_DEFAULTS.items()
    }
    values["vessel_source_image_name"] = source_image_name or values.get("vessel_source_image_name", "")
    values["vessel_bore_volume_mm3"] = float(bore_volume_mm3)
    values["vessel_bore_volume_cm3"] = float(bore_volume_mm3) / 1000.0
    return {
        "schema": "glass-toolkit.vessel-setup",
        "version": 1,
        "values": values,
        "midpoints": [
            {"z_frac": float(z_frac), "radius": float(radius)}
            for z_frac, radius in midpoints
        ],
    }


def build_vessel_setup_json(
    source_image_name: str,
    midpoints: list[tuple[float, float]],
    bore_volume_mm3: float,
) -> bytes:
    payload = build_vessel_setup_payload(source_image_name, midpoints, bore_volume_mm3)
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


def load_vessel_setup_into_state(payload: dict, source_bytes: bytes | None = None, source_name: str = "") -> None:
    if not payload:
        return
    values = payload.get("values", payload)
    for key, default in VESSEL_DEFAULTS.items():
        if key not in values:
            continue
        value = values[key]
        if key == "vessel_job_date" and isinstance(value, str):
            try:
                value = date.fromisoformat(value)
            except ValueError:
                value = default
        st.session_state[key] = value

    if not isinstance(st.session_state.get("vessel_job_date"), date):
        try:
            st.session_state["vessel_job_date"] = date.fromisoformat(str(st.session_state["vessel_job_date"]))
        except (TypeError, ValueError):
            st.session_state["vessel_job_date"] = date.today()
    st.session_state["vessel_base_border_mode"] = (
        "Add base border"
        if st.session_state.get("vessel_add_base_border", False)
        else "No border"
    )
    if not st.session_state.get("vessel_tone_mapping"):
        st.session_state["vessel_tone_mapping"] = "Negative" if st.session_state["vessel_invert_relief"] else "Positive"
    st.session_state["vessel_invert_relief"] = st.session_state["vessel_tone_mapping"] == "Negative"
    st.session_state["vessel_max_thickness"] = float(st.session_state["vessel_wall_mm"]) + float(st.session_state["vessel_displacement"])
    st.session_state["vessel_tile_count"] = int(st.session_state.get("vessel_tile_count") or VESSEL_DEFAULTS["vessel_tile_count"])

    for idx in range(4):
        st.session_state.pop(f"vessel_zf_{idx}", None)
        st.session_state.pop(f"vessel_rm_{idx}", None)
    midpoints_saved = payload.get("midpoints", [])
    st.session_state["vessel_n_mid"] = min(4, len(midpoints_saved))
    height_value = float(st.session_state["vessel_height"] or VESSEL_DEFAULTS["vessel_height"])
    for idx, item in enumerate(midpoints_saved[:4]):
        z_frac = float(item.get("z_frac", 0.0))
        radius = float(item.get("radius", st.session_state["vessel_base_r"]))
        st.session_state[f"vessel_zf_{idx}"] = max(1.0, min(height_value - 1, z_frac * height_value))
        st.session_state[f"vessel_rm_{idx}"] = radius

    if source_bytes:
        st.session_state["vessel_loaded_heightmap_bytes"] = source_bytes
        st.session_state["vessel_loaded_heightmap_name"] = source_name or st.session_state.get("vessel_source_image_name", "")
        st.session_state["vessel_source_image_name"] = st.session_state["vessel_loaded_heightmap_name"]
        st.session_state["vessel_upload_nonce"] = st.session_state.get("vessel_upload_nonce", 0) + 1
    else:
        st.session_state["vessel_loaded_heightmap_bytes"] = None
        st.session_state["vessel_loaded_heightmap_name"] = ""
    clear_vessel_outputs()


def extract_vessel_setup_upload(uploaded_file) -> tuple[dict, bytes | None, str]:
    file_bytes = uploaded_file.getvalue()
    file_name = uploaded_file.name or ""
    if file_name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            try:
                payload = json.loads(zf.read("vessel_settings.json").decode("utf-8"))
            except KeyError as exc:
                raise ValueError("Build bundle does not contain vessel_settings.json.") from exc
            source_bytes = None
            source_name = ""
            for name in zf.namelist():
                lower = name.lower()
                if lower.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff")):
                    source_name = Path(name).name
                    source_bytes = zf.read(name)
                    break
            return payload, source_bytes, source_name
    return json.loads(file_bytes.decode("utf-8")), None, ""


def vessel_generation_signature(
    *,
    base_r,
    top_r,
    height,
    cross_section,
    oval_x_scale,
    oval_y_scale,
    add_base_border,
    base_z,
    demold_cut_enabled,
    demold_cut_radius,
    demold_cut_apply,
    demold_cut_shape,
    midpoints,
    wall_mm,
    displacement,
    placement_key,
    tone_mapping,
    image_orientation,
    fit_mode,
    tile_enabled,
    tile_count,
    mirror_tiles,
    add_lip,
    lip_radius,
    n_lip,
    n_theta,
    n_z,
    mm_per_ring,
    uploaded_bytes,
) -> str:
    uploaded_hash = hashlib.sha256(uploaded_bytes).hexdigest() if uploaded_bytes else ""
    payload = {
        "base_r": round(float(base_r), 4),
        "top_r": round(float(top_r), 4),
        "height": round(float(height), 4),
        "cross_section": cross_section,
        "oval_x_scale": round(float(oval_x_scale), 4),
        "oval_y_scale": round(float(oval_y_scale), 4),
        "add_base_border": bool(add_base_border),
        "base_z": round(float(base_z), 4),
        "demold_cut_enabled": bool(demold_cut_enabled),
        "demold_cut_radius": round(float(demold_cut_radius), 4),
        "demold_cut_apply": demold_cut_apply,
        "demold_cut_shape": demold_cut_shape,
        "midpoints": [(round(float(z), 6), round(float(r), 4)) for z, r in midpoints],
        "wall_mm": round(float(wall_mm), 4),
        "displacement": round(float(displacement), 4),
        "placement_key": placement_key,
        "tone_mapping": tone_mapping,
        "image_orientation": image_orientation,
        "fit_mode": fit_mode,
        "tile_enabled": bool(tile_enabled),
        "tile_count": int(tile_count),
        "mirror_tiles": bool(mirror_tiles),
        "add_lip": bool(add_lip),
        "lip_radius": round(float(lip_radius), 4),
        "n_lip": int(n_lip),
        "n_theta": int(n_theta),
        "n_z": int(n_z),
        "mm_per_ring": round(float(mm_per_ring), 6),
        "uploaded_hash": uploaded_hash,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


if st.session_state.get("vessel_reset_pending"):
    reset_vessel_defaults()

tool_left, tool_right = st.columns([1, 1], gap="large")
with tool_left:
    with st.expander(tr("page.vessel.files.load_title", "Load Vessel Setup File"), expanded=False):
        setup_upload = st.file_uploader(
            tr("page.vessel.fields.upload_setup", "Upload vessel_settings.json or a prior build ZIP"),
            type=["json", "zip"],
            key="vessel_setup_file_upload",
        )
        if st.button(
            tr("page.vessel.actions.load_setup_file", "Load Setup File"),
            key="vessel_load_setup_file",
            width="stretch",
            disabled=setup_upload is None,
        ):
            try:
                setup_payload, setup_source_bytes, setup_source_name = extract_vessel_setup_upload(setup_upload)
                load_vessel_setup_into_state(setup_payload, setup_source_bytes, setup_source_name)
                st.success(tr("page.vessel.messages.setup_file_loaded", "Setup file loaded."))
                st.rerun()
            except Exception as exc:
                st.error(tr("page.vessel.errors.setup_file_failed", "Could not load setup file: {error}", error=exc))

with tool_right:
    with st.expander(tr("page.vessel.files.actions_title", "Setup Actions"), expanded=False):
        st.caption(
            tr(
                "page.vessel.files.public_storage_note",
                "Setups are stored in your downloaded files, not in a shared server database.",
            )
        )
        st.divider()
        bc1, bc2 = st.columns(2)
        with bc1:
            if st.button(tr("worksheet.actions.new", "+ New"), key="vessel_new_setup", width="stretch"):
                reset_vessel_defaults()
                st.rerun()
        with bc2:
            if st.button(tr("worksheet.actions.reset", "Reset"), key="vessel_reset_setup", width="stretch"):
                reset_vessel_defaults()
                st.rerun()

st.divider()

left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader(tr("page.vessel.sections.setup", "Setup"))
    setup_a, setup_b = st.columns([2, 1])
    with setup_a:
        st.text_input(
            tr("worksheet.fields.title", "Title"),
            key="vessel_title",
            placeholder=tr("page.vessel.fields.title_placeholder", "e.g. Vessel texture test #1"),
        )
    with setup_b:
        st.date_input(tr("worksheet.fields.date", "Date"), key="vessel_job_date")

    st.divider()
    st.subheader(tr("page.vessel.sections.profile", "Profile"))

    c1, c2, c3 = st.columns(3)
    with c1:
        base_r = st.number_input(
            tr("page.vessel.fields.base_radius", "Base radius (mm)"),
            min_value=1.0,
            max_value=150.0,
            step=1.0,
            key="vessel_base_r",
        )
    with c2:
        top_r = st.number_input(
            tr("page.vessel.fields.top_radius", "Top radius (mm)"),
            min_value=1.0,
            max_value=150.0,
            step=1.0,
            key="vessel_top_r",
        )
    with c3:
        height = st.number_input(
            tr("page.vessel.fields.height", "Height (mm)"),
            min_value=10.0,
            max_value=200.0,
            step=5.0,
            key="vessel_height",
        )

    if st.session_state.get("vessel_cross_section") not in cross_section_options():
        st.session_state["vessel_cross_section"] = "Circle"
    cross_section = st.selectbox(
        tr("page.vessel.fields.cross_section", "Cross-section"),
        cross_section_options(),
        key="vessel_cross_section",
        format_func=cross_section_label,
        help=tr("page.vessel.help.cross_section", "Choose a round/oval section, or select a regular polygon by number of sides."),
    )
    if cross_section == "Oval":
        oval_cols = st.columns(2)
        with oval_cols[0]:
            oval_x_scale = st.number_input(
                tr("page.vessel.fields.oval_width_scale", "Oval width scale"),
                min_value=0.25,
                max_value=3.0,
                step=0.05,
                key="vessel_oval_x_scale",
                help=tr("page.vessel.help.oval_width_scale", "Scales the X/width axis of the circular profile."),
            )
        with oval_cols[1]:
            oval_y_scale = st.number_input(
                tr("page.vessel.fields.oval_depth_scale", "Oval depth scale"),
                min_value=0.25,
                max_value=3.0,
                step=0.05,
                key="vessel_oval_y_scale",
                help=tr("page.vessel.help.oval_depth_scale", "Scales the Y/depth axis of the circular profile."),
            )
    else:
        oval_x_scale = 1.0
        oval_y_scale = 1.0
        st.session_state["vessel_oval_x_scale"] = 1.0
        st.session_state["vessel_oval_y_scale"] = 1.0

    base_border_mode = st.radio(
        tr("page.vessel.fields.base_border", "Base border"),
        ["No border", "Add base border"],
        horizontal=True,
        key="vessel_base_border_mode",
        help=tr(
            "page.vessel.help.base_border",
            "Adds a blank vertical section below the vessel profile at the base radius.",
        ),
    )
    add_base_border = base_border_mode == "Add base border"
    st.session_state["vessel_add_base_border"] = add_base_border
    if add_base_border:
        base_z = st.number_input(
            tr("page.vessel.fields.base_z", "Base Z amount (mm)"),
            min_value=0.0,
            max_value=30.0,
            step=1.0,
            key="vessel_base_z",
            help=tr("page.vessel.help.base_z", "Length of the blank vertical base section below the profile."),
        )
    else:
        base_z = 0.0
        st.session_state["vessel_base_z"] = 0.0
    output_height = float(height) + float(base_z)

    st.caption(tr("page.vessel.caption.midpoints", "Add midpoints to curve the profile (optional)"))
    n_mid = st.slider(tr("page.vessel.fields.num_midpoints", "Number of midpoints"), 0, 4, key="vessel_n_mid")
    midpoints = []
    # Collect midpoints in visual order (top to bottom = highest to lowest Z)
    # then reverse so internal list is bottom-to-top for the spline
    mid_inputs = []
    for i in range(n_mid):
        # Display index: 0 = top midpoint (highest Z), n_mid-1 = bottom
        display_i = i          # shown to user top-down
        spline_i  = n_mid - 1 - i  # internal index bottom-up
        default_z_mm = round(height * (spline_i + 1) / (n_mid + 1), 1)
        z_key = f"vessel_zf_{spline_i}"
        r_key = f"vessel_rm_{spline_i}"
        if z_key not in st.session_state:
            st.session_state[z_key] = float(min(default_z_mm, height - 1))
        else:
            st.session_state[z_key] = float(min(max(st.session_state[z_key], 1.0), height - 1))
        if r_key not in st.session_state:
            st.session_state[r_key] = float(round(
                base_r + (top_r - base_r) * (spline_i + 1) / (n_mid + 1), 1
            ))
        else:
            st.session_state[r_key] = float(min(max(st.session_state[r_key], 1.0), 150.0))
        mc1, mc2 = st.columns(2)
        with mc1:
            z_mm = st.number_input(
                tr("page.vessel.fields.midpoint_height", "Midpoint {index} - Height (mm)", index=n_mid - i),
                min_value=1.0,
                max_value=float(height - 1),
                step=1.0,
                key=z_key,
                help=tr("page.vessel.help.midpoint_height", "Distance from base - 0 is bottom, {height} mm is top.", height=f"{height:.0f}"))
        with mc2:
            r_mid = st.number_input(
                tr("page.vessel.fields.midpoint_radius", "Midpoint {index} - Radius (mm)", index=n_mid - i),
                min_value=1.0,
                max_value=150.0,
                step=1.0,
                key=r_key)
        mid_inputs.append((spline_i, z_mm / height, r_mid))

    # Sort by spline index (bottom to top) for build_profile
    midpoints = [(z_frac, r_mid) for _, z_frac, r_mid in sorted(mid_inputs)]

    st.divider()
    st.subheader(tr("page.vessel.sections.wall_relief", "Thickness & Image Mapping"))
    current_min = float(st.session_state.get("vessel_wall_mm", 3.0))
    current_max = max(
        current_min + 0.1,
        float(st.session_state.get("vessel_max_thickness", current_min + st.session_state.get("vessel_displacement", 2.0))),
    )
    st.session_state["vessel_max_thickness"] = current_max
    wc1, wc2 = st.columns(2)
    with wc1:
        wall_mm = st.number_input(
            tr("page.vessel.fields.min_thickness", "Min thickness (mm)"),
            min_value=0.5,
            step=0.5,
            help=tr("page.vessel.help.min_thickness", "Thinnest wall thickness. This is the base wall behind the lightest relief value."),
            key="vessel_wall_mm",
        )
    if float(st.session_state.get("vessel_max_thickness", wall_mm + 0.1)) <= float(wall_mm):
        st.session_state["vessel_max_thickness"] = float(wall_mm) + 0.1
    with wc2:
        max_thickness = st.number_input(
            tr("page.vessel.fields.max_thickness", "Max thickness (mm)"),
            min_value=float(wall_mm + 0.1),
            step=0.1,
            help=tr("page.vessel.help.max_thickness", "Thickest wall thickness. Relief depth is Max thickness minus Min thickness."),
            key="vessel_max_thickness",
        )
    displacement = round(max(0.1, float(max_thickness) - float(wall_mm)), 3)
    st.session_state["vessel_displacement"] = displacement

    placement = st.radio(
        tr("page.vessel.fields.placement", "Relief placement"),
        ["Outside — relief on exterior", "Inside — carved interior"],
        horizontal=True,
        key="vessel_placement",
        format_func=vessel_placement_label,
    )
    placement_key = "outside" if placement.startswith("Outside") else "inside"
    demold_cut_enabled = st.checkbox(
        tr("page.vessel.fields.demold_cut", "Demold clearance cut"),
        key="vessel_demold_cut_enabled",
        disabled=placement_key != "inside",
        help=tr(
            "page.vessel.help.demold_cut",
            "For carved interiors, keeps the void at or beyond a cutter radius to reduce undercuts for alginate demolding.",
        ),
    )
    if placement_key != "inside":
        demold_cut_enabled = False

    if demold_cut_enabled:
        demold_cols = st.columns(3)
        with demold_cols[0]:
            demold_cut_diameter = st.number_input(
                tr("page.vessel.fields.demold_cut_diameter", "Cutter diameter (mm)"),
                min_value=1.0,
                max_value=300.0,
                step=1.0,
                value=max(1.0, float(st.session_state.get("vessel_demold_cut_radius", base_r)) * 2.0),
                help=tr("page.vessel.help.demold_cut_diameter", "Diameter of the cylinder or oval used as the minimum demolding void."),
            )
            demold_cut_radius = demold_cut_diameter / 2.0
            st.session_state["vessel_demold_cut_radius"] = demold_cut_radius
        with demold_cols[1]:
            demold_cut_apply = st.selectbox(
                tr("page.vessel.fields.demold_cut_apply", "Apply to"),
                ["Base transition", "Base border only", "Full height"],
                key="vessel_demold_cut_apply",
                help=tr("page.vessel.help.demold_cut_apply", "Controls how far the cutter envelope is applied upward."),
            )
        with demold_cols[2]:
            demold_cut_shape = st.selectbox(
                tr("page.vessel.fields.demold_cut_shape", "Cutter shape"),
                ["Match vessel cross-section", "Circular cutter"],
                key="vessel_demold_cut_shape",
                help=tr("page.vessel.help.demold_cut_shape", "For oval vessels, match the oval profile or use a true circular cutter."),
            )
    else:
        demold_cut_radius = 0.0
        demold_cut_apply = st.session_state.get("vessel_demold_cut_apply", "Base transition")
        demold_cut_shape = st.session_state.get("vessel_demold_cut_shape", "Match vessel cross-section")

    tone_mapping = st.radio(
        tr("page.vessel.fields.tone_mapping", "Tone mapping"),
        ["Positive", "Negative"],
        horizontal=True,
        key="vessel_tone_mapping",
        help=tr("page.vessel.help.tone_mapping", "Positive uses the image as-is. Negative swaps peaks and valleys."),
    )
    invert_relief = tone_mapping == "Negative"
    st.session_state["vessel_invert_relief"] = invert_relief

    map_a, map_b = st.columns(2)
    with map_a:
        image_orientation = st.radio(
            tr("page.vessel.fields.image_orientation", "Image orientation"),
            ["Upright", "Inverted"],
            horizontal=True,
            key="vessel_image_orientation",
            help=tr("page.vessel.help.image_orientation", "Upright maps the image top to the vessel top. Inverted flips it vertically."),
        )
    with map_b:
        fit_mode = st.selectbox(
            tr("page.vessel.fields.fit_mode", "Fit mode"),
            ["Stretch to tile", "Fit inside tile", "Crop to fill tile"],
            key="vessel_fit_mode",
            help=tr("page.vessel.help.fit_mode", "Controls how the image is resized before wrapping or tiling."),
        )
    st.caption(
        tr(
            "page.vessel.caption.relief_depth",
            "Relief depth: {value} mm",
            value=f"{displacement:.1f}",
        )
    )
    tile_enabled = st.checkbox(
        tr("page.vessel.fields.tile_same_image", "Tile same image around vessel"),
        help=tr("page.vessel.help.tile_same_image", "Repeat the uploaded heightmap around the vessel instead of stretching it once around the full circumference."),
        key="vessel_tile_enabled",
    )
    if tile_enabled:
        tile_count = st.slider(
            tr("page.vessel.fields.tile_count", "Tiles around vessel"),
            min_value=2,
            max_value=24,
            value=int(st.session_state.get("vessel_tile_count", 4)),
            step=1,
            help=tr("page.vessel.help.tile_count", "Number of repeated copies around the circumference."),
            key="vessel_tile_count",
        )
        mirror_tiles = st.checkbox(
            tr("page.vessel.fields.mirror_tiles", "Mirror alternate tiles"),
            value=bool(st.session_state.get("vessel_mirror_tiles", False)),
            disabled=tile_count % 2 != 0,
            help=tr("page.vessel.help.mirror_tiles", "Alternates normal and mirrored copies so neighboring tile ends match. Requires an even tile count."),
            key="vessel_mirror_tiles",
        )
        if tile_count % 2 != 0:
            mirror_tiles = False
            st.caption(tr("page.vessel.caption.mirror_even_only", "Mirror tiles requires an even number of tiles."))
    else:
        tile_count = 1
        mirror_tiles = False
        st.session_state["vessel_mirror_tiles"] = False

    st.divider()
    st.subheader(tr("page.vessel.sections.rim", "Rim"))
    add_lip = st.checkbox(
        tr("page.vessel.fields.add_rim", "Add top rim"),
        help=tr("page.vessel.help.add_rim", "Cuts a quarter-round channel from the clean top radius down into the relief side so you have space to build up a rim."),
        key="vessel_add_lip",
    )
    if add_lip:
        lip_max = max(0.5, float(wall_mm))
        st.session_state["vessel_lip_radius"] = min(
            float(st.session_state.get("vessel_lip_radius", min(displacement, lip_max))),
            lip_max,
        )
        lip_radius = st.slider(tr("page.vessel.fields.rim_radius", "Rim radius"),
                                min_value=0.5,
                                max_value=lip_max,
                                step=0.1,
                                help=tr("page.vessel.help.rim_radius", "Radius of the quarter-round cut measured from the clean top edge into the relief side. Matching this to the relief amount reproduces the 1/4-circle layout."),
                                key="vessel_lip_radius")
        n_lip = st.slider(tr("page.vessel.fields.rim_smoothness", "Rim smoothness"), 8, 48, step=4,
                           help=tr("page.vessel.help.rim_smoothness", "Arc segments used to round the rim channel"),
                           key="vessel_n_lip")
    else:
        lip_radius = 0.0
        n_lip = 24

    st.divider()
    st.subheader(tr("page.vessel.sections.heightmap", "Heightmap Image"))
    uploaded = st.file_uploader(tr("page.vessel.fields.upload_image", "Upload image (PNG, JPG, TIFF)"),
                                 type=["png", "jpg", "jpeg", "tif", "tiff"],
                                 key=f"vessel_upload_{st.session_state['vessel_upload_nonce']}")
    if uploaded:
        st.image(uploaded, caption=tr("page.vessel.caption.heightmap_preview", "Heightmap preview"), width="content")
        uploaded_bytes = uploaded.getvalue()
        st.session_state["vessel_source_image_name"] = uploaded.name
        st.session_state["vessel_loaded_heightmap_bytes"] = None
        st.session_state["vessel_loaded_heightmap_name"] = ""
    elif st.session_state.get("vessel_loaded_heightmap_bytes"):
        uploaded_bytes = st.session_state["vessel_loaded_heightmap_bytes"]
        loaded_name = st.session_state.get("vessel_loaded_heightmap_name", "loaded_heightmap")
        st.image(io.BytesIO(uploaded_bytes), caption=tr("page.vessel.caption.loaded_heightmap_preview", "Loaded heightmap: {name}", name=loaded_name), width="content")
        st.session_state["vessel_source_image_name"] = loaded_name
    else:
        uploaded_bytes = None

    st.divider()
    st.subheader(tr("page.vessel.sections.resolution", "Resolution"))
    st.caption(tr("page.vessel.caption.vertical_segments", "Vertical segments scale with height."))

    # Angular segments: fixed per quality level (circumference detail)
    # Vertical segments: calculated as height / mm_per_ring so taller = more rings
    QUALITY_PRESETS = {
        "Draft  (fast preview)":  (72,  1.0),
        "Standard":               (180, 0.5),
        "High":                   (360, 0.25),
        "Ultra  (fine detail)":   (720, 0.125),
    }
    quality = st.select_slider(
        tr("page.vessel.fields.quality", "Quality"),
        options=list(QUALITY_PRESETS.keys()),
        key="vessel_quality",
        format_func=vessel_quality_label,
    )
    n_theta, mm_per_ring = QUALITY_PRESETS[quality]
    n_z = max(20, int(round(output_height / mm_per_ring)))
    profile_n_z = max(20, int(round(height / mm_per_ring)))
    base_n_z = max(0, n_z - profile_n_z)

    st.caption(
        tr(
            "page.vessel.caption.triangle_estimate",
            "-> {theta} angular x {vertical} vertical | ~{triangles}k triangles",
            theta=n_theta,
            vertical=n_z,
            triangles=n_theta * n_z * 4 // 1000,
        )
    )

    override = st.checkbox(tr("page.vessel.fields.override_segments", "Override segments manually"), key="vessel_override")
    if override:
        rc1, rc2 = st.columns(2)
        with rc1:
            n_theta = st.slider(tr("page.vessel.fields.angular_segments", "Angular segments"), 36, 720, step=12,
                                 help=tr("page.vessel.help.angular_segments", "Segments around the circumference"),
                                 key="vessel_ov_theta")
        with rc2:
            mm_per_ring = st.number_input(tr("page.vessel.fields.vertical_spacing", "Vertical spacing (mm per ring)"),
                                           min_value=0.1, max_value=10.0,
                                           step=0.1,
                                           help=tr("page.vessel.help.vertical_spacing", "Smaller = more rings = finer vertical detail"),
                                           key="vessel_ov_z")
            n_z = max(20, int(round(output_height / mm_per_ring)))
            profile_n_z = max(20, int(round(height / mm_per_ring)))
            base_n_z = max(0, n_z - profile_n_z)

    current_signature = vessel_generation_signature(
        base_r=base_r,
        top_r=top_r,
        height=height,
        cross_section=cross_section,
        oval_x_scale=oval_x_scale,
        oval_y_scale=oval_y_scale,
        add_base_border=add_base_border,
        base_z=base_z,
        demold_cut_enabled=demold_cut_enabled,
        demold_cut_radius=demold_cut_radius,
        demold_cut_apply=demold_cut_apply,
        demold_cut_shape=demold_cut_shape,
        midpoints=midpoints,
        wall_mm=wall_mm,
        displacement=displacement,
        placement_key=placement_key,
        tone_mapping=tone_mapping,
        image_orientation=image_orientation,
        fit_mode=fit_mode,
        tile_enabled=tile_enabled,
        tile_count=tile_count,
        mirror_tiles=mirror_tiles,
        add_lip=add_lip,
        lip_radius=lip_radius,
        n_lip=n_lip,
        n_theta=n_theta,
        n_z=n_z,
        mm_per_ring=mm_per_ring,
        uploaded_bytes=uploaded_bytes,
    )
    if st.session_state["stl_bytes"] and st.session_state.get("vessel_generated_signature") != current_signature:
        clear_vessel_outputs()
        st.info(tr("page.vessel.messages.settings_changed", "Settings changed. Generate again to update the STL and downloads."))

    st.divider()
    st.text_area(
        tr("worksheet.sections.notes", "Notes"),
        key="vessel_notes",
        height=80,
        placeholder=tr("page.vessel.fields.notes_placeholder", "Setup notes, source image notes, or firing/mold reminders..."),
    )

    downloads_ready = bool(st.session_state["stl_bytes"]) and st.session_state.get("vessel_generated_signature") == current_signature
    action_col1, action_col2 = st.columns(2)
    is_building = False
    if downloads_ready:
        generate = False
        action_col1.download_button(
            f"⬇️ {tr('page.vessel.actions.download_bundle', 'Download Build Bundle')}",
            data=st.session_state["vessel_zip_bytes"] or b"",
            file_name=st.session_state["vessel_zip_name"],
            mime="application/zip",
            width="stretch",
            type="primary",
            disabled=not bool(st.session_state["vessel_zip_bytes"]),
            key="vessel_download_bundle_primary",
        )
    else:
        generate = action_col1.button(
            f"⚙️ {tr('page.vessel.actions.generate', 'Generate')}",
            width="stretch",
            type="primary",
            disabled=is_building,
            key="vessel_generate_mesh",
        )
    reset = action_col2.button(
        tr("page.vessel.actions.reset", "Reset Defaults"),
        width="stretch",
        disabled=is_building,
        key="vessel_reset_defaults_action",
    )
    if reset:
        st.session_state["vessel_reset_pending"] = True
        st.rerun()
    if generate:
        clear_vessel_outputs()

    build_feedback = action_col1.empty()
    if generate:
        build_feedback.info(tr("page.vessel.messages.generating_standby", "Generating mesh... please stand by."))

    st.divider()
    if downloads_ready:
        st.success(tr("page.vessel.messages.mesh_ready", "Mesh ready | {count} triangles", count=f"{st.session_state['stl_tri_count']:,}"))
        st.caption(tr("page.vessel.caption.bundle_contents", "Build bundle includes the STL, vessel settings, and source heightmap image."))
    else:
        st.caption(tr("page.vessel.help.generate_first", "Click Generate first"))

with right:
    # Always show profile preview
    profile_fn = build_profile(base_r, top_r, height, midpoints)
    output_profile_fn = add_base_border_to_profile(profile_fn, base_r, height, base_z)
    st.plotly_chart(
        make_profile_preview(
            output_profile_fn,
            output_height,
            wall_mm,
            displacement,
            placement_key,
            midpoints,
            base_z=base_z,
            profile_height=height,
            demold_cut_enabled=demold_cut_enabled,
            demold_cut_radius=demold_cut_radius,
            demold_cut_apply=demold_cut_apply,
        ),
        width="stretch",
    )

    bore_volume_mm3 = None
    bore_note = None
    if placement_key == "outside":
        bore_volume_mm3 = estimate_internal_bore_volume_mm3(
            output_profile_fn,
            output_height,
            wall_mm,
            displacement,
            placement=placement_key,
            n_theta=n_theta,
            n_z=n_z,
            cross_section=cross_section,
            oval_x_scale=oval_x_scale,
            oval_y_scale=oval_y_scale,
            base_z=base_z,
            demold_cut_enabled=demold_cut_enabled,
            demold_cut_radius=demold_cut_radius,
            demold_cut_apply=demold_cut_apply,
            demold_cut_shape=demold_cut_shape,
        )
    elif uploaded_bytes is not None:
        hmap_for_volume = load_heightmap_for_output(
            uploaded_bytes,
            n_theta,
            profile_n_z,
            base_n_z,
            image_orientation,
            fit_mode,
            tile_count,
            mirror_tiles,
            invert_relief,
        )
        bore_volume_mm3 = estimate_internal_bore_volume_mm3(
            output_profile_fn,
            output_height,
            wall_mm,
            displacement,
            placement=placement_key,
            n_theta=n_theta,
            n_z=n_z,
            heightmap=hmap_for_volume,
            cross_section=cross_section,
            oval_x_scale=oval_x_scale,
            oval_y_scale=oval_y_scale,
            base_z=base_z,
            demold_cut_enabled=demold_cut_enabled,
            demold_cut_radius=demold_cut_radius,
            demold_cut_apply=demold_cut_apply,
            demold_cut_shape=demold_cut_shape,
        )
    else:
        bore_note = tr("page.vessel.messages.bore_note", "Upload a heightmap image to calculate internal bore volume for carved interior.")

    metric_cols = st.columns(2)
    with metric_cols[0]:
        st.metric(tr("page.vessel.metrics.output_height", "Output height"), f"{output_height:.1f} mm")
    with metric_cols[1]:
        if bore_volume_mm3 is not None:
            st.metric(tr("page.vessel.metrics.bore_volume", "Internal bore volume"), f"{bore_volume_mm3 / 1000.0:,.2f} cm³")
            st.caption(tr("page.vessel.caption.bore_ml", "Equivalent to approximately {value} mL.", value=f"{bore_volume_mm3 / 1000.0:,.2f}"))
        elif bore_note:
            st.info(bore_note)

    if generate:
        if not uploaded:
            build_feedback.warning(tr("page.vessel.messages.upload_heightmap_first", "Upload a heightmap image first."))
            st.warning(tr("page.vessel.messages.upload_heightmap_first", "Upload a heightmap image first."))
        else:
            try:
                build_feedback.info(tr("page.vessel.messages.loading_heightmap", "Loading heightmap..."))
                hmap = load_heightmap_for_output(
                    uploaded_bytes,
                    n_theta,
                    profile_n_z,
                    base_n_z,
                    image_orientation,
                    fit_mode,
                    tile_count,
                    mirror_tiles,
                    invert_relief,
                )

                build_feedback.info(
                    tr(
                        "page.vessel.messages.building_segments",
                        "Building mesh ({theta}x{vertical} segments)...",
                        theta=n_theta,
                        vertical=n_z,
                    )
                )
                tris = build_vase_mesh(
                    output_profile_fn, output_height, displacement,
                    hmap,
                    n_theta,
                    n_z,
                    wall_mm,
                    placement_key,
                    add_rim_channel=add_lip,
                    rim_radius=lip_radius,
                    n_rim=n_lip,
                    cross_section=cross_section,
                    oval_x_scale=oval_x_scale,
                    oval_y_scale=oval_y_scale,
                    base_z=base_z,
                    demold_cut_enabled=demold_cut_enabled,
                    demold_cut_radius=demold_cut_radius,
                    demold_cut_apply=demold_cut_apply,
                    demold_cut_shape=demold_cut_shape,
                )

                generated_bore_volume_mm3 = estimate_internal_bore_volume_mm3(
                    output_profile_fn,
                    output_height,
                    wall_mm,
                    displacement,
                    placement=placement_key,
                    n_theta=n_theta,
                    n_z=n_z,
                    heightmap=hmap if placement_key == "inside" else None,
                    cross_section=cross_section,
                    oval_x_scale=oval_x_scale,
                    oval_y_scale=oval_y_scale,
                    base_z=base_z,
                    demold_cut_enabled=demold_cut_enabled,
                    demold_cut_radius=demold_cut_radius,
                    demold_cut_apply=demold_cut_apply,
                    demold_cut_shape=demold_cut_shape,
                )
                stl_bytes = write_stl(tris)
                source_image_name = uploaded.name if uploaded is not None else "source_heightmap"
                if uploaded is None:
                    source_image_name = st.session_state.get("vessel_source_image_name", source_image_name) or source_image_name
                settings_json = build_vessel_setup_json(source_image_name, midpoints, generated_bore_volume_mm3)
                settings_text = format_vessel_settings(
                    {
                        "base_r": float(base_r),
                        "top_r": float(top_r),
                        "height": float(height),
                        "output_height": float(output_height),
                        "cross_section": cross_section,
                        "oval_x_scale": float(oval_x_scale),
                        "oval_y_scale": float(oval_y_scale),
                        "add_base_border": bool(add_base_border),
                        "base_z": float(base_z),
                        "demold_cut_enabled": bool(demold_cut_enabled),
                        "demold_cut_radius": float(demold_cut_radius),
                        "demold_cut_apply": demold_cut_apply,
                        "demold_cut_shape": demold_cut_shape,
                        "midpoints": [(float(z_frac), float(radius)) for z_frac, radius in midpoints],
                        "wall_mm": float(wall_mm),
                        "displacement": float(displacement),
                        "placement_label": placement,
                        "tone_mapping": tone_mapping,
                        "image_orientation": image_orientation,
                        "fit_mode": fit_mode,
                        "tile_enabled": bool(tile_enabled),
                        "tile_count": int(tile_count),
                        "mirror_tiles": bool(mirror_tiles),
                        "add_rim_channel": bool(add_lip),
                        "rim_radius": float(lip_radius),
                        "n_rim": int(n_lip),
                        "quality_label": quality,
                        "override": bool(override),
                        "n_theta": int(n_theta),
                        "n_z": int(n_z),
                        "mm_per_ring": float(mm_per_ring),
                        "triangle_count": int(len(tris)),
                        "bore_volume_mm3": float(generated_bore_volume_mm3),
                        "source_image_name": source_image_name,
                    }
                )
                stem = Path(source_image_name).stem or "vessel_model"
                stl_name = f"{stem}_vessel.stl"
                bundle_name = f"{stem}_vessel_bundle.zip"

                st.session_state["stl_bytes"] = stl_bytes
                st.session_state["stl_tri_count"] = len(tris)
                st.session_state["vessel_stl_name"] = stl_name
                st.session_state["vessel_settings_text"] = settings_text
                st.session_state["vessel_zip_bytes"] = build_vessel_bundle(
                    stl_bytes,
                    stl_name,
                    settings_text,
                    settings_json,
                    source_image_name,
                    uploaded_bytes,
                )
                st.session_state["vessel_zip_name"] = bundle_name
                st.session_state["vessel_generated_signature"] = current_signature
                st.rerun()
            except Exception:
                raise
