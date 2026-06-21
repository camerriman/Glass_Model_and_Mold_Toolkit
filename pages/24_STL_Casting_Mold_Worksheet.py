"""
24_STL_Casting_Mold_Worksheet.py
Material planning worksheet for casting molds made from STL stand-in models.
"""

from __future__ import annotations

import io
import json
import re
from datetime import date

import streamlit as st
import trimesh

from i18n import render_app_sidebar, t


st.set_page_config(page_title=t("page.stl_casting.title", "STL Casting Mold Worksheet"), layout="wide")
render_app_sidebar()


def fmt_cm2(value: float) -> str:
    return f"{value:,.1f} cm^2"


def fmt_cm3(value: float) -> str:
    return f"{value:,.1f} cm^3"


def fmt_g(value: float) -> str:
    return f"{value:,.1f} g"


def expanded_surface_area_cm2(surface_area_cm2: float, offset_mm: float) -> float:
    if surface_area_cm2 <= 0:
        return 0.0
    radius_cm = (surface_area_cm2 / (4.0 * 3.141592653589793)) ** 0.5
    offset_cm = offset_mm / 10.0
    return surface_area_cm2 * ((radius_cm + offset_cm) / radius_cm) ** 2


def load_stl_mesh(uploaded_file) -> trimesh.Trimesh:
    file_bytes = uploaded_file.getvalue()
    mesh = trimesh.load(io.BytesIO(file_bytes), file_type="stl", force="mesh")
    if isinstance(mesh, trimesh.Scene):
        geometries = tuple(mesh.geometry.values())
        if not geometries:
            raise ValueError("STL file did not contain mesh geometry.")
        mesh = trimesh.util.concatenate(geometries)
    if mesh.is_empty or len(mesh.faces) == 0:
        raise ValueError("STL file did not contain usable faces.")
    return mesh


def mesh_info(mesh: trimesh.Trimesh, unit_scale: float) -> dict:
    scaled_area_mm2 = float(mesh.area) * (unit_scale**2)
    scaled_volume_mm3 = abs(float(mesh.volume)) * (unit_scale**3) if mesh.is_watertight else None
    scaled_extents_mm = [float(value) * unit_scale for value in mesh.extents]
    return {
        "surface_area_cm2": scaled_area_mm2 / 100.0,
        "model_volume_cm3": scaled_volume_mm3 / 1000.0 if scaled_volume_mm3 is not None else None,
        "is_watertight": bool(mesh.is_watertight),
        "triangles": int(len(mesh.faces)),
        "extents_mm": scaled_extents_mm,
    }


def material_rows_for_face(batch_cm3: float) -> list[tuple[str, str]]:
    batch_weight_g = batch_cm3
    dry_mix_g = batch_weight_g * (2.0 / 3.0)
    water_g = batch_weight_g * (1.0 / 3.0)
    return [
        ("Casting plaster", fmt_g(dry_mix_g / 2.0)),
        ("295 mesh silica flour", fmt_g(dry_mix_g / 2.0)),
        ("Water", fmt_g(water_g)),
    ]


def material_rows_for_jacket(batch_cm3: float, stiffener: str) -> list[tuple[str, str]]:
    batch_weight_g = batch_cm3
    if stiffener == "Fiberglass strips":
        dry_mix_g = batch_weight_g * (2.0 / 3.0)
        water_g = batch_weight_g * (1.0 / 3.0)
        return [
            ("Casting plaster", fmt_g(dry_mix_g / 2.0)),
            ("295 mesh silica flour", fmt_g(dry_mix_g / 2.0)),
            ("Water", fmt_g(water_g)),
            ("Fiberglass strips", "cut to fit"),
        ]

    investment_g = batch_weight_g * (2.0 / 4.0)
    grog_mix_g = batch_weight_g * (1.0 / 4.0)
    water_g = batch_weight_g * (1.0 / 4.0)
    each_grog_g = grog_mix_g / 3.0
    return [
        ("Casting plaster", fmt_g(investment_g / 2.0)),
        ("295 mesh silica flour", fmt_g(investment_g / 2.0)),
        ("Grog - 50 mesh", fmt_g(each_grog_g)),
        ("Grog - 60 mesh", fmt_g(each_grog_g)),
        ("Grog - 100 mesh", fmt_g(each_grog_g)),
        ("Water", fmt_g(water_g)),
    ]


def rows_to_table(rows: list[tuple[str, str]]) -> dict:
    return {"Material": [row[0] for row in rows], "Weight": [row[1] for row in rows]}


st.title(t("page.stl_casting.title", "STL Casting Mold Worksheet"))
st.caption(
    t(
        "page.stl_casting.caption",
        "Estimate face coat and jacket coat material from an uploaded STL used as a wax or model stand-in.",
    )
)

st.divider()

project_col, date_col = st.columns([2, 1])
with project_col:
    project_title = st.text_input("Project title", placeholder="e.g. Bust casting mold")
with date_col:
    project_date = st.date_input("Date", value=date.today(), format="YYYY/MM/DD")

with st.expander("Upload STL model", expanded=True):
    uploaded_stl = st.file_uploader("Upload STL", type=["stl"])
    st.caption(
        "The worksheet treats STL units as millimeters by default. Adjust the unit scale if the model was exported in inches or another unit."
    )

st.subheader("STL Geometry")
settings_col, metrics_col = st.columns([1, 2])
with settings_col:
    unit_scale = st.number_input(
        "STL unit scale to millimeters",
        min_value=0.0001,
        value=1.0,
        step=0.1,
        help="Use 1.0 when the STL is already in millimeters. Use 25.4 if one STL unit equals one inch.",
    )
    coverage_pct = st.number_input(
        "Surface coverage (%)",
        min_value=0.0,
        max_value=200.0,
        value=100.0,
        step=5.0,
        help="Use less than 100% if the model sits on a base or parting plane that should not be coated.",
    )

mesh_summary = None
if uploaded_stl is not None:
    try:
        mesh_summary = mesh_info(load_stl_mesh(uploaded_stl), unit_scale)
    except (OSError, TypeError, ValueError) as exc:
        st.error(f"Could not read that STL file: {exc}")

with metrics_col:
    if mesh_summary:
        extents = mesh_summary["extents_mm"]
        metric_cols = st.columns(4)
        metric_cols[0].metric("Surface area", fmt_cm2(mesh_summary["surface_area_cm2"]))
        metric_cols[1].metric("Model volume", fmt_cm3(mesh_summary["model_volume_cm3"]) if mesh_summary["model_volume_cm3"] is not None else "open mesh")
        metric_cols[2].metric("Triangles", f"{mesh_summary['triangles']:,}")
        metric_cols[3].metric("Watertight", "Yes" if mesh_summary["is_watertight"] else "No")
        st.caption(f"Bounding box: {extents[0]:.1f} x {extents[1]:.1f} x {extents[2]:.1f} mm")
        if not mesh_summary["is_watertight"]:
            st.warning("This mesh is not watertight. Surface-area estimates can still be used, but model volume is not reliable.")
    else:
        st.info("Upload an STL to calculate surface area and material estimates.")

st.subheader("Volume Estimate")
vol_cols = st.columns(4)
with vol_cols[0]:
    effective_area_cm2 = (mesh_summary["surface_area_cm2"] if mesh_summary else 0.0) * (coverage_pct / 100.0)
    st.metric("Planning surface area", fmt_cm2(effective_area_cm2))
with vol_cols[1]:
    face_thickness_mm = st.number_input("Face coat thickness (mm)", min_value=0.0, value=15.0, step=1.0)
with vol_cols[2]:
    jacket_thickness_mm = st.number_input("Jacket coat thickness (mm)", min_value=0.0, value=15.0, step=1.0)
with vol_cols[3]:
    overage_pct = st.number_input("Overage (%)", min_value=0.0, value=15.0, step=5.0)

face_volume_cm3 = effective_area_cm2 * (face_thickness_mm / 10.0)
jacket_area_cm2 = expanded_surface_area_cm2(effective_area_cm2, face_thickness_mm)
jacket_volume_cm3 = jacket_area_cm2 * (jacket_thickness_mm / 10.0)
overage_multiplier = 1.0 + (overage_pct / 100.0)
face_batch_cm3 = face_volume_cm3 * overage_multiplier
jacket_batch_cm3 = jacket_volume_cm3 * overage_multiplier
total_batch_cm3 = face_batch_cm3 + jacket_batch_cm3

st.caption(
    "Estimate basis: face coat uses STL surface area; jacket coat uses an expanded surface-area approximation after the face coat. This is a planning estimate, not a geometric offset shell."
)

summary_cols = st.columns(4)
summary_cols[0].metric("Face coat", fmt_cm3(face_volume_cm3))
summary_cols[1].metric("Jacket coat", fmt_cm3(jacket_volume_cm3))
summary_cols[2].metric("Face batch", fmt_cm3(face_batch_cm3))
summary_cols[3].metric("Batch total", fmt_cm3(total_batch_cm3))
st.caption(f"Jacket planning surface area: {fmt_cm2(jacket_area_cm2)}")

st.subheader("Material Planning")
st.caption("Batch weights use the planning equivalence 1 cm^3 = 1 g before recipe ratios are applied.")
face_col, jacket_col = st.columns(2)
with face_col:
    with st.container(border=True):
        st.markdown("### Face Coat")
        face_rows = material_rows_for_face(face_batch_cm3)
        st.write("Estimated coat volume", f"**{fmt_cm3(face_volume_cm3)}**")
        st.write("Batch volume with overage", f"**{fmt_cm3(face_batch_cm3)}**")
        st.write("Estimated batch weight", f"**{fmt_g(face_batch_cm3)}**")
        st.table(rows_to_table(face_rows))
        st.caption(
            "Face coat formula: 1 part casting plaster + 1 part 295 mesh silica flour by weight. Mix 2 parts dry investment to 1 part water by weight."
        )

with jacket_col:
    with st.container(border=True):
        st.markdown("### Jacket Coat")
        jacket_stiffener = st.radio("Stiffener", ["Grog mix", "Fiberglass strips"], horizontal=True)
        jacket_rows = material_rows_for_jacket(jacket_batch_cm3, jacket_stiffener)
        st.write("Estimated coat volume", f"**{fmt_cm3(jacket_volume_cm3)}**")
        st.write("Batch volume with overage", f"**{fmt_cm3(jacket_batch_cm3)}**")
        st.write("Estimated batch weight", f"**{fmt_g(jacket_batch_cm3)}**")
        st.table(rows_to_table(jacket_rows))
        if jacket_stiffener == "Fiberglass strips":
            st.caption(
                "Fiberglass jacket formula: soak cut-to-fit fiberglass strips with investment slurry. Slurry is equal parts casting plaster and silica flour, mixed 2 parts dry investment to 1 part water."
            )
        else:
            st.caption(
                "Jacket coat formula: 2 parts dry investment mix, 1 part grog mix, and 1 part water by weight. Dry investment is equal parts casting plaster and 295 mesh silica flour."
            )

st.subheader("Notes")
notes = st.text_area(
    "Notes",
    placeholder="Capture model prep, wax thickness, parting method, release, jacket reinforcement, or material source notes...",
    height=150,
)

payload = {
    "schema": "glass-toolkit.stl-casting-mold-worksheet",
    "version": 1,
    "project_title": project_title,
    "project_date": project_date.isoformat(),
    "stl_file": uploaded_stl.name if uploaded_stl else "",
    "geometry": mesh_summary or {},
    "settings": {
        "unit_scale_to_mm": unit_scale,
        "surface_coverage_pct": coverage_pct,
        "face_thickness_mm": face_thickness_mm,
        "jacket_thickness_mm": jacket_thickness_mm,
        "overage_pct": overage_pct,
        "jacket_stiffener": jacket_stiffener if uploaded_stl else "Grog mix",
    },
    "estimates": {
        "effective_area_cm2": effective_area_cm2,
        "jacket_area_cm2": jacket_area_cm2,
        "face_volume_cm3": face_volume_cm3,
        "jacket_volume_cm3": jacket_volume_cm3,
        "face_batch_cm3": face_batch_cm3,
        "jacket_batch_cm3": jacket_batch_cm3,
        "total_batch_cm3": total_batch_cm3,
    },
    "notes": notes,
}

safe_filename = re.sub(r"[^A-Za-z0-9_-]+", "_", project_title).strip("_") or "stl_casting_mold"
st.download_button(
    "Download Casting Mold JSON",
    data=json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"),
    file_name=f"{safe_filename}_casting_mold_settings.json",
    mime="application/json",
    type="primary",
    width="stretch",
)
