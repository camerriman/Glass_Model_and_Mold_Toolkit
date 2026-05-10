"""
4_Vessel_Model_Generator.py
Wrap a heightmap image around a user-defined vessel profile.
- Profile defined by base radius, top radius, height + optional midpoints
- Heightmap wraps once around the full circumference as surface displacement
- Output: solid printable STL (inner shell + outer displaced shell + caps)
"""

import io
import json
import sqlite3
import struct
import zipfile
from datetime import date, datetime
from pathlib import Path
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from PIL import Image
from scipy.interpolate import CubicSpline
from i18n import render_app_sidebar, t as tr

st.set_page_config(page_title=tr("page.vessel.title", "Vessel Mold Model Generator"), layout="wide")
render_app_sidebar()
st.title(tr("page.vessel.title", "Vessel Mold Model Generator"))
st.caption(tr("page.vessel.caption", "Define a vessel profile, upload a heightmap image, and generate a wrapped printable STL."))

APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "mold_records.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_vessel_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vessel_setups (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                title             TEXT NOT NULL,
                job_date          TEXT,
                created_at        TEXT NOT NULL,
                base_r            REAL,
                top_r             REAL,
                height            REAL,
                n_mid             INTEGER,
                midpoints_json    TEXT,
                wall_mm           REAL,
                displacement      REAL,
                placement         TEXT,
                invert_relief     INTEGER,
                tile_enabled      INTEGER,
                tile_count        INTEGER,
                add_lip           INTEGER,
                lip_radius        REAL,
                n_lip             INTEGER,
                quality           TEXT,
                override          INTEGER,
                ov_theta          INTEGER,
                ov_z              REAL,
                source_image_name TEXT,
                notes             TEXT
            )
            """
        )


init_vessel_db()


def save_vessel_record(rec: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO vessel_setups
                (title, job_date, created_at, base_r, top_r, height, n_mid, midpoints_json,
                 wall_mm, displacement, placement, invert_relief, tile_enabled, tile_count,
                 add_lip, lip_radius, n_lip, quality, override, ov_theta, ov_z,
                 source_image_name, notes)
            VALUES
                (:title, :job_date, :created_at, :base_r, :top_r, :height, :n_mid, :midpoints_json,
                 :wall_mm, :displacement, :placement, :invert_relief, :tile_enabled, :tile_count,
                 :add_lip, :lip_radius, :n_lip, :quality, :override, :ov_theta, :ov_z,
                 :source_image_name, :notes)
            """,
            rec,
        )
        return cur.lastrowid


def update_vessel_record(record_id: int, rec: dict) -> None:
    rec["id"] = record_id
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE vessel_setups SET
                title=:title, job_date=:job_date, base_r=:base_r, top_r=:top_r, height=:height,
                n_mid=:n_mid, midpoints_json=:midpoints_json, wall_mm=:wall_mm,
                displacement=:displacement, placement=:placement, invert_relief=:invert_relief,
                tile_enabled=:tile_enabled, tile_count=:tile_count, add_lip=:add_lip,
                lip_radius=:lip_radius, n_lip=:n_lip, quality=:quality, override=:override,
                ov_theta=:ov_theta, ov_z=:ov_z, source_image_name=:source_image_name,
                notes=:notes
            WHERE id=:id
            """,
            rec,
        )


def delete_vessel_record(record_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM vessel_setups WHERE id=?", (record_id,))


def list_vessel_records():
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, title, job_date, created_at, source_image_name FROM vessel_setups ORDER BY created_at DESC"
        ).fetchall()


def load_vessel_record(record_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM vessel_setups WHERE id=?", (record_id,)).fetchone()

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
        f"Base radius (mm): {settings['base_r']:.1f}",
        f"Top radius (mm): {settings['top_r']:.1f}",
        f"Height (mm): {settings['height']:.1f}",
        "",
        "Midpoints",
    ]
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
            f"Wall thickness (mm): {settings['wall_mm']:.1f}",
            f"Relief (mm): {settings['displacement']:.1f}",
            f"Relief placement: {settings['placement_label']}",
            f"Invert relief: {'Yes' if settings['invert_relief'] else 'No'}",
            f"Tile same image around vessel: {'Yes' if settings['tile_enabled'] else 'No'}",
            f"Tiles around vessel: {settings['tile_count']}",
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
        lines.append(f"Estimated internal bore volume: {settings['bore_volume_mm3'] / 1000.0:,.2f} cm3")
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
    source_name: str,
    source_bytes: bytes,
) -> bytes:
    bundle = io.BytesIO()
    stl_member_name = Path(stl_name).name if stl_name else "vessel_model.stl"
    source_member_name = Path(source_name).name if source_name else "source_heightmap.bin"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(stl_member_name, stl_bytes)
        zf.writestr("vessel_settings.txt", settings_text)
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


def estimate_internal_bore_volume_mm3(
    profile_fn,
    height,
    wall_mm,
    displacement,
    placement="outside",
    n_theta=180,
    n_z=120,
    heightmap=None,
):
    """
    Estimate open bore volume in mm^3 from bottom to top.
    For outside relief, the bore follows the smooth profile.
    For inside relief, the bore follows the carved inner wall and requires a heightmap.
    """
    z_arr = np.linspace(0.0, float(height), int(n_z), dtype=np.float64)
    r_base = np.clip(profile_fn(z_arr), 1.0, None).astype(np.float64)

    if placement == "inside" and heightmap is not None:
        hmap = np.asarray(heightmap, dtype=np.float64)
        inner_r = np.maximum(
            1.0,
            r_base[:, None] - hmap * float(displacement),
        )
        area_mm2 = np.pi * np.mean(inner_r ** 2, axis=1)
    else:
        inner_r = np.maximum(1.0, r_base - float(wall_mm))
        area_mm2 = np.pi * (inner_r ** 2)

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


def load_heightmap(uploaded_file, n_theta: int, n_z: int, tile_count: int = 1) -> np.ndarray:
    """
    Returns (n_z, n_theta) float array in [0, 1].
    Rows = Z slices (bottom to top), Cols = angle slices.
    tile_count > 1 repeats the same uploaded image around the circumference.
    Uses Pillow + scipy — no cv2 required.
    """
    from scipy.ndimage import zoom

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

    # Resize to (n_z rows, tile/full angular cols) via scipy zoom.
    zh = n_z / img.shape[0]
    zw = tile_cols / img.shape[1]
    img = zoom(img, (zh, zw), order=3)   # bicubic

    # Flip vertically so image top = vase top.
    img = img[::-1, :]
    img = blend_heightmap_wrap(img)

    if tile_count > 1:
        img = np.tile(img, (1, tile_count))[:, :n_theta]

    return np.clip(img, 0.0, 1.0)


@st.cache_data(show_spinner=False)
def load_heightmap_cached(file_bytes: bytes, n_theta: int, n_z: int, tile_count: int = 1) -> np.ndarray:
    return load_heightmap(file_bytes, n_theta, n_z, tile_count)


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
            return np.array([r * np.cos(t), r * np.sin(t), z_arr[iz]], dtype=np.float32)

        def outer_v(iz, it):
            r = r_base[iz] + heightmap[iz, it % n_theta] * displacement
            t = theta[it]
            return np.array([r * np.cos(t), r * np.sin(t), z_arr[iz]], dtype=np.float32)

        def inner_top_radius(_it):
            return float(max(1.0, r_base[-1] - wall_mm))

        def outer_top_radius(it):
            return float(r_base[-1] + heightmap[-1, it % n_theta] * displacement)
    else:
        # Inner relief surface stays fixed. Base thickness adds outward.
        def inner_v(iz, it):
            r = max(1.0, r_base[iz] - heightmap[iz, it % n_theta] * displacement)
            t = theta[it]
            return np.array([r * np.cos(t), r * np.sin(t), z_arr[iz]], dtype=np.float32)

        def outer_v(iz, it):
            r = r_base[iz] + wall_mm
            t = theta[it]
            return np.array([r * np.cos(t), r * np.sin(t), z_arr[iz]], dtype=np.float32)

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
                return np.array([r * np.cos(t), r * np.sin(t), rim_wall_z], dtype=np.float32)

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
                return np.array([r * np.cos(t), r * np.sin(t), rim_wall_z], dtype=np.float32)

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
            a = np.array([clean_top_inner_radius * np.cos(t0), clean_top_inner_radius * np.sin(t0), height], dtype=np.float32)
            b = np.array([clean_top_inner_radius * np.cos(t1), clean_top_inner_radius * np.sin(t1), height], dtype=np.float32)
            c = np.array([clean_top_outer_radius * np.cos(t1), clean_top_outer_radius * np.sin(t1), height], dtype=np.float32)
            d = np.array([clean_top_outer_radius * np.cos(t0), clean_top_outer_radius * np.sin(t0), height], dtype=np.float32)
        elif rim_active and placement == "inside":
            t0 = theta[it]
            t1 = theta[it1]
            a = np.array([clean_top_inner_radius * np.cos(t0), clean_top_inner_radius * np.sin(t0), height], dtype=np.float32)
            b = np.array([clean_top_inner_radius * np.cos(t1), clean_top_inner_radius * np.sin(t1), height], dtype=np.float32)
            c = np.array([clean_top_outer_radius * np.cos(t1), clean_top_outer_radius * np.sin(t1), height], dtype=np.float32)
            d = np.array([clean_top_outer_radius * np.cos(t0), clean_top_outer_radius * np.sin(t0), height], dtype=np.float32)
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
                        return np.array([r * np.cos(t), r * np.sin(t), z], dtype=np.float32)

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
                        return np.array([r * np.cos(t), r * np.sin(t), z], dtype=np.float32)

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
                         midpoints=None, n_z=200) -> go.Figure:
    z      = np.linspace(0, height, n_z)
    r_base = np.clip(profile_fn(z), 1.0, None)
    avg_d  = displacement * 0.5   # average relief for preview

    # Fixed reference axes match print bed: 300mm wide, 300mm tall
    # Profile scales visually within this window — axes never move
    FIXED_R = 150.0    # half of 300mm bed width
    FIXED_H = 200.0    # 200mm max height
    x_range = [-FIXED_R, FIXED_R]
    y_range = [0, FIXED_H]

    if placement == "outside":
        r_inner = np.maximum(1.0, r_base - wall_mm)
        r_outer = r_base + avg_d
        inner_label = "Interior surface (smooth)"
        outer_label = "Exterior surface (avg relief)"
    else:
        r_inner = np.maximum(1.0, r_base - avg_d)
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
            z_pos = z_frac * height
            fig.add_hline(y=z_pos,
                          line=dict(color="#6699cc", width=1, dash="dot"),
                          annotation_text=f"  MP{i+1}  {z_pos:.0f}mm  r={r_mid:.0f}mm",
                          annotation_position="right",
                          annotation_font=dict(size=10, color="#6699cc"))

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
st.session_state.setdefault("vessel_loaded_id", None)

VESSEL_DEFAULTS = {
    "vessel_title": "",
    "vessel_job_date": date.today(),
    "vessel_base_r": 20.0,
    "vessel_top_r": 50.0,
    "vessel_height": 60.0,
    "vessel_n_mid": 1,
    "vessel_wall_mm": 3.0,
    "vessel_displacement": 2.0,
    "vessel_placement": "Outside — relief on exterior",
    "vessel_invert_relief": False,
    "vessel_tile_enabled": False,
    "vessel_tile_count": 4,
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
    st.session_state["vessel_loaded_id"] = None


def clear_vessel_outputs() -> None:
    st.session_state["stl_bytes"] = None
    st.session_state["stl_tri_count"] = 0
    st.session_state["vessel_stl_name"] = "vessel_model.stl"
    st.session_state["vessel_zip_bytes"] = None
    st.session_state["vessel_zip_name"] = "vessel_model_bundle.zip"
    st.session_state["vessel_settings_text"] = ""
    st.session_state["vessel_is_building"] = False


def load_vessel_setup_into_state(row) -> None:
    if not row:
        return
    st.session_state["vessel_title"] = row["title"] or ""
    if row["job_date"]:
        try:
            st.session_state["vessel_job_date"] = date.fromisoformat(row["job_date"])
        except ValueError:
            st.session_state["vessel_job_date"] = date.today()
    else:
        st.session_state["vessel_job_date"] = date.today()

    mappings = {
        "base_r": "vessel_base_r",
        "top_r": "vessel_top_r",
        "height": "vessel_height",
        "n_mid": "vessel_n_mid",
        "wall_mm": "vessel_wall_mm",
        "displacement": "vessel_displacement",
        "placement": "vessel_placement",
        "lip_radius": "vessel_lip_radius",
        "n_lip": "vessel_n_lip",
        "quality": "vessel_quality",
        "ov_theta": "vessel_ov_theta",
        "ov_z": "vessel_ov_z",
        "notes": "vessel_notes",
    }
    for column, key in mappings.items():
        if column in row.keys() and row[column] is not None:
            st.session_state[key] = row[column]

    for column, key in {
        "invert_relief": "vessel_invert_relief",
        "tile_enabled": "vessel_tile_enabled",
        "add_lip": "vessel_add_lip",
        "override": "vessel_override",
    }.items():
        st.session_state[key] = bool(row[column]) if column in row.keys() and row[column] is not None else False
    st.session_state["vessel_tile_count"] = int(row["tile_count"] or VESSEL_DEFAULTS["vessel_tile_count"])
    st.session_state["vessel_source_image_name"] = row["source_image_name"] or ""

    for idx in range(4):
        st.session_state.pop(f"vessel_zf_{idx}", None)
        st.session_state.pop(f"vessel_rm_{idx}", None)
    try:
        midpoints_saved = json.loads(row["midpoints_json"] or "[]")
    except json.JSONDecodeError:
        midpoints_saved = []
    st.session_state["vessel_n_mid"] = min(4, len(midpoints_saved))
    height_value = float(st.session_state["vessel_height"] or VESSEL_DEFAULTS["vessel_height"])
    for idx, item in enumerate(midpoints_saved[:4]):
        z_frac = float(item.get("z_frac", 0.0))
        radius = float(item.get("radius", st.session_state["vessel_base_r"]))
        st.session_state[f"vessel_zf_{idx}"] = max(1.0, min(height_value - 1, z_frac * height_value))
        st.session_state[f"vessel_rm_{idx}"] = radius

    st.session_state["vessel_loaded_id"] = row["id"]
    clear_vessel_outputs()


if st.session_state.get("vessel_reset_pending"):
    reset_vessel_defaults()

tool_left, tool_right = st.columns([1, 1], gap="large")
with tool_right:
    with st.expander(tr("page.vessel.records.title", "Saved Vessel Setups"), expanded=False):
        records = list_vessel_records()
        if not records:
            st.info(tr("page.vessel.records.empty", "No saved vessel setups yet."))
        else:
            for row in records:
                saved_date = row["job_date"] or tr("page.vessel.records.no_date", "no date")
                source_note = f" · {row['source_image_name']}" if row["source_image_name"] else ""
                rc1, rc2, rc3 = st.columns([4, 1, 1])
                with rc1:
                    st.markdown(f"**{row['title']}** — {saved_date}{source_note}")
                    st.caption(f"Saved {row['created_at']}")
                with rc2:
                    if st.button(tr("worksheet.actions.load", "Load"), key=f"vessel_load_{row['id']}"):
                        load_vessel_setup_into_state(load_vessel_record(row["id"]))
                        st.rerun()
                with rc3:
                    if st.button(tr("worksheet.actions.delete_help", "Delete"), key=f"vessel_del_{row['id']}"):
                        delete_vessel_record(row["id"])
                        if st.session_state["vessel_loaded_id"] == row["id"]:
                            reset_vessel_defaults()
                        st.rerun()

        st.divider()
        bc1, bc2 = st.columns(2)
        with bc1:
            if st.button(tr("worksheet.actions.new", "+ New"), key="vessel_new_setup", use_container_width=True):
                reset_vessel_defaults()
                st.rerun()
        with bc2:
            if st.button(tr("worksheet.actions.reset", "Reset"), key="vessel_reset_setup", use_container_width=True):
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
    st.subheader(tr("page.vessel.sections.wall_relief", "Wall Thickness & Relief"))
    wc1, wc2 = st.columns(2)
    with wc1:
        wall_mm = st.number_input(
            tr("page.vessel.fields.wall_thickness", "Wall thickness (mm)"),
            min_value=0.5,
            step=0.5,
            help=tr("page.vessel.help.wall_thickness", "Thickness of the mold wall behind the uploaded relief. Changing this adds structure on the smooth opposite side instead of moving the relief-bearing surface."),
            key="vessel_wall_mm",
        )
    with wc2:
        displacement = st.number_input(
            tr("page.vessel.fields.relief", "Relief (mm)"),
            min_value=0.1,
            step=0.1,
            help=tr("page.vessel.help.relief", "Depth or height of the wrapped relief relative to the wall thickness."),
            key="vessel_displacement",
        )
    placement = st.radio(
        tr("page.vessel.fields.placement", "Relief placement"),
        ["Outside — relief on exterior", "Inside — carved interior"],
        horizontal=True,
        key="vessel_placement",
        format_func=vessel_placement_label,
    )
    placement_key = "outside" if placement.startswith("Outside") else "inside"
    invert_relief = st.checkbox(
        tr("page.vessel.fields.invert_relief", "Invert relief"),
        help=tr("page.vessel.help.invert_relief", "Swap peaks and valleys - dark areas become raised, light areas recessed"),
        key="vessel_invert_relief",
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
    else:
        tile_count = 1

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
    n_z = max(20, int(round(height / mm_per_ring)))

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
            n_z = max(20, int(round(height / mm_per_ring)))

    st.divider()
    st.text_area(
        tr("worksheet.sections.notes", "Notes"),
        key="vessel_notes",
        height=80,
        placeholder=tr("page.vessel.fields.notes_placeholder", "Setup notes, source image notes, or firing/mold reminders..."),
    )
    save_label = (
        tr("page.vessel.actions.update_setup", "Update Setup")
        if st.session_state.get("vessel_loaded_id")
        else tr("page.vessel.actions.save_setup", "Save Setup")
    )
    save_setup = st.button(save_label, key="vessel_save_setup", use_container_width=True, type="secondary")
    if save_setup:
        title = st.session_state["vessel_title"].strip()
        if not title:
            st.error(tr("errors.worksheet.title_required", "Please enter a title before saving."))
        else:
            job_date_val = st.session_state["vessel_job_date"]
            job_date_str = job_date_val.isoformat() if hasattr(job_date_val, "isoformat") else str(job_date_val)
            source_image_name = uploaded.name if uploaded is not None else st.session_state.get("vessel_source_image_name", "")
            rec = {
                "title": title,
                "job_date": job_date_str,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "base_r": float(base_r),
                "top_r": float(top_r),
                "height": float(height),
                "n_mid": int(n_mid),
                "midpoints_json": json.dumps([
                    {"z_frac": float(z_frac), "radius": float(radius)}
                    for z_frac, radius in midpoints
                ]),
                "wall_mm": float(wall_mm),
                "displacement": float(displacement),
                "placement": placement,
                "invert_relief": int(bool(invert_relief)),
                "tile_enabled": int(bool(tile_enabled)),
                "tile_count": int(tile_count),
                "add_lip": int(bool(add_lip)),
                "lip_radius": float(lip_radius),
                "n_lip": int(n_lip),
                "quality": quality,
                "override": int(bool(override)),
                "ov_theta": int(n_theta),
                "ov_z": float(mm_per_ring),
                "source_image_name": source_image_name,
                "notes": st.session_state["vessel_notes"],
            }
            if st.session_state.get("vessel_loaded_id"):
                update_vessel_record(st.session_state["vessel_loaded_id"], rec)
                st.success(tr("page.vessel.messages.setup_updated", "Setup updated: {title}", title=title))
            else:
                st.session_state["vessel_loaded_id"] = save_vessel_record(rec)
                st.success(tr("page.vessel.messages.setup_saved", "Setup saved: {title}", title=title))
            st.session_state["vessel_source_image_name"] = source_image_name

    action_col1, action_col2 = st.columns(2)
    is_building = st.session_state.get("vessel_is_building", False)
    generate = action_col1.button(
        f"⚙️ {tr('page.vessel.actions.generate', 'Generate')}",
        use_container_width=True,
        type="primary",
        disabled=is_building,
    )
    reset = action_col2.button(
        tr("page.vessel.actions.reset", "Reset Defaults"),
        use_container_width=True,
        disabled=is_building,
    )
    if reset:
        st.session_state["vessel_reset_pending"] = True
        st.rerun()
    if generate:
        st.session_state["vessel_is_building"] = True
        st.session_state["stl_bytes"] = None
        st.session_state["stl_tri_count"] = 0
        st.session_state["vessel_stl_name"] = "vessel_model.stl"
        st.session_state["vessel_zip_bytes"] = None
        st.session_state["vessel_zip_name"] = "vessel_model_bundle.zip"
        st.session_state["vessel_settings_text"] = ""

    build_feedback = st.empty()
    if st.session_state.get("vessel_is_building"):
        build_feedback.info(tr("page.vessel.messages.generating", "Generating mesh..."))

    st.divider()
    if st.session_state["stl_bytes"] and not st.session_state.get("vessel_is_building"):
        st.success(tr("page.vessel.messages.mesh_ready", "Mesh ready | {count} triangles", count=f"{st.session_state['stl_tri_count']:,}"))
        download_col1, download_col2 = st.columns(2)
        download_col1.download_button(
            f"⬇️ {tr('page.vessel.actions.download_stl', 'Download STL')}",
            data=st.session_state["stl_bytes"],
            file_name=st.session_state["vessel_stl_name"],
            mime="application/octet-stream",
            use_container_width=True,
            type="primary",
        )
        download_col2.download_button(
            f"⬇️ {tr('page.vessel.actions.download_bundle', 'Download Build Bundle')}",
            data=st.session_state["vessel_zip_bytes"],
            file_name=st.session_state["vessel_zip_name"],
            mime="application/zip",
            use_container_width=True,
            disabled=not bool(st.session_state["vessel_zip_bytes"]),
        )
    else:
        download_col1, download_col2 = st.columns(2)
        download_col1.button(f"⬇️ {tr('page.vessel.actions.download_stl', 'Download STL')}", use_container_width=True,
                             disabled=True, help=tr("page.vessel.help.generate_first", "Click Generate first"))
        download_col2.button(f"⬇️ {tr('page.vessel.actions.download_bundle', 'Download Build Bundle')}", use_container_width=True,
                             disabled=True, help=tr("page.vessel.help.generate_model_first", "Generate a model first"))

with right:
    # Always show profile preview
    profile_fn = build_profile(base_r, top_r, height, midpoints)
    st.plotly_chart(make_profile_preview(profile_fn, height, wall_mm,
                                          displacement, placement_key,
                                          midpoints),
)

    bore_volume_mm3 = None
    bore_note = None
    if placement_key == "outside":
        bore_volume_mm3 = estimate_internal_bore_volume_mm3(
            profile_fn,
            height,
            wall_mm,
            displacement,
            placement=placement_key,
            n_theta=n_theta,
            n_z=n_z,
        )
    elif uploaded_bytes is not None:
        hmap_for_volume = load_heightmap_cached(uploaded_bytes, n_theta, n_z, tile_count)
        if invert_relief:
            hmap_for_volume = 1.0 - hmap_for_volume
        bore_volume_mm3 = estimate_internal_bore_volume_mm3(
            profile_fn,
            height,
            wall_mm,
            displacement,
            placement=placement_key,
            n_theta=n_theta,
            n_z=n_z,
            heightmap=hmap_for_volume,
        )
    else:
        bore_note = tr("page.vessel.messages.bore_note", "Upload a heightmap image to calculate internal bore volume for carved interior.")

    metric_cols = st.columns(2)
    with metric_cols[0]:
        st.metric(tr("page.vessel.metrics.output_height", "Output height"), f"{height:.1f} mm")
    with metric_cols[1]:
        if bore_volume_mm3 is not None:
            st.metric(tr("page.vessel.metrics.bore_volume", "Internal bore volume"), f"{bore_volume_mm3 / 1000.0:,.2f} cm3")
            st.caption(tr("page.vessel.caption.bore_ml", "Equivalent to approximately {value} mL.", value=f"{bore_volume_mm3 / 1000.0:,.2f}"))
        elif bore_note:
            st.info(bore_note)

    if generate:
        if not uploaded:
            st.session_state["vessel_is_building"] = False
            build_feedback.warning(tr("page.vessel.messages.upload_heightmap_first", "Upload a heightmap image first."))
            st.warning(tr("page.vessel.messages.upload_heightmap_first", "Upload a heightmap image first."))
        else:
            try:
                with build_feedback.container():
                    with st.spinner(tr("page.vessel.messages.loading_heightmap", "Loading heightmap...")):
                        hmap = load_heightmap_cached(uploaded_bytes, n_theta, n_z, tile_count)

                with build_feedback.container():
                    with st.spinner(tr("page.vessel.messages.building_segments", "Building mesh ({theta}x{vertical} segments)...", theta=n_theta, vertical=n_z)):
                        if invert_relief:
                            hmap = 1.0 - hmap
                        tris = build_vase_mesh(
                            profile_fn, height, displacement,
                            hmap,
                            n_theta,
                            n_z,
                            wall_mm,
                            placement_key,
                            add_rim_channel=add_lip,
                            rim_radius=lip_radius,
                            n_rim=n_lip,
                        )

                generated_bore_volume_mm3 = estimate_internal_bore_volume_mm3(
                    profile_fn,
                    height,
                    wall_mm,
                    displacement,
                    placement=placement_key,
                    n_theta=n_theta,
                    n_z=n_z,
                    heightmap=hmap if placement_key == "inside" else None,
                )
                stl_bytes = write_stl(tris)
                source_image_name = uploaded.name if uploaded is not None else "source_heightmap"
                settings_text = format_vessel_settings(
                    {
                        "base_r": float(base_r),
                        "top_r": float(top_r),
                        "height": float(height),
                        "midpoints": [(float(z_frac), float(radius)) for z_frac, radius in midpoints],
                        "wall_mm": float(wall_mm),
                        "displacement": float(displacement),
                        "placement_label": placement,
                        "invert_relief": bool(invert_relief),
                        "tile_enabled": bool(tile_enabled),
                        "tile_count": int(tile_count),
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
                    source_image_name,
                    uploaded_bytes,
                )
                st.session_state["vessel_zip_name"] = bundle_name
                st.session_state["vessel_is_building"] = False
                st.rerun()
            except Exception:
                st.session_state["vessel_is_building"] = False
                raise
