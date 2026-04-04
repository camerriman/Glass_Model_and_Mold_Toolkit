"""
5_Mold_Worksheet.py
Mold Calculator & Record Keeper
- Parses settings.txt from the Cameo Mold Generator (App 1)
- Live worksheet: 3D Print → Mold Geometry → tabbed mold type
- Saves / loads records via local SQLite database
"""

import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

import streamlit as st

# ─────────────────────────────────────────
# Config
# ─────────────────────────────────────────
st.set_page_config(page_title="Mold Worksheet", layout="wide")
st.title("Mold Worksheet")
st.caption("Pre-fill from a settings.txt or enter values manually. Select the mold type tab to see its calculations.")

APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "mold_records.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────
# Database
# ─────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS molds (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                title         TEXT NOT NULL,
                job_date      TEXT,
                created_at    TEXT NOT NULL,
                mold_type     TEXT,
                width_mm      REAL,
                depth_mm      REAL,
                base_mm       REAL,
                height_mm     REAL,
                stl_volume    REAL,
                wall_mm       REAL,
                alg_adjust_zi REAL,
                alg_mix_ratio REAL,
                si_adjust_zi  REAL,
                si_mix_ratio  REAL,
                inv_adjust_zi REAL,
                notes         TEXT
            )
        """)
        existing = {r[1] for r in conn.execute("PRAGMA table_info(molds)").fetchall()}
        for col, dflt in [
            ("mold_type",     "'Alginate'"),
            ("alg_adjust_zi", "0.0"),
            ("alg_mix_ratio", "1.0"),
        ]:
            if col not in existing:
                col_type = "TEXT" if col == "mold_type" else "REAL"
                conn.execute(f"ALTER TABLE molds ADD COLUMN {col} {col_type} DEFAULT {dflt}")

init_db()

def save_record(rec: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO molds
                (title, job_date, created_at, mold_type,
                 width_mm, depth_mm, base_mm, height_mm, stl_volume,
                 wall_mm,
                 alg_adjust_zi, alg_mix_ratio,
                 si_adjust_zi,  si_mix_ratio,
                 inv_adjust_zi, notes)
            VALUES
                (:title, :job_date, :created_at, :mold_type,
                 :width_mm, :depth_mm, :base_mm, :height_mm, :stl_volume,
                 :wall_mm,
                 :alg_adjust_zi, :alg_mix_ratio,
                 :si_adjust_zi,  :si_mix_ratio,
                 :inv_adjust_zi, :notes)
        """, rec)
        return cur.lastrowid

def update_record(record_id: int, rec: dict):
    rec["id"] = record_id
    with get_conn() as conn:
        conn.execute("""
            UPDATE molds SET
                title=:title, job_date=:job_date, mold_type=:mold_type,
                width_mm=:width_mm, depth_mm=:depth_mm, base_mm=:base_mm,
                height_mm=:height_mm, stl_volume=:stl_volume,
                wall_mm=:wall_mm,
                alg_adjust_zi=:alg_adjust_zi, alg_mix_ratio=:alg_mix_ratio,
                si_adjust_zi=:si_adjust_zi,   si_mix_ratio=:si_mix_ratio,
                inv_adjust_zi=:inv_adjust_zi, notes=:notes
            WHERE id=:id
        """, rec)

def delete_record(record_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM molds WHERE id=?", (record_id,))

def list_records():
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, title, job_date, created_at, mold_type FROM molds ORDER BY created_at DESC"
        ).fetchall()

def load_record(record_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM molds WHERE id=?", (record_id,)).fetchone()

# ─────────────────────────────────────────
# Settings.txt parser
# ─────────────────────────────────────────
def parse_settings_txt(text: str) -> dict:
    out = {}
    patterns = {
        "width_mm":    r"Target width \(mm\):\s*([\d.]+)",
        "base_mm":     r"Base backing thickness \(mm\):\s*([\d.]+)",
        "stl_volume":  r"Total volume \(cm\^3\):\s*([\d.,]+)",
        "output_size": r"Output size \(mm\):\s*([\d.]+)\s*x\s*([\d.]+)\s*x\s*([\d.]+)",
        "image_name":  r"Image:\s*(.+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            if key == "output_size":
                out["width_mm"] = float(m.group(1))
                out["depth_mm"] = float(m.group(2))
                out["max_z_mm"] = float(m.group(3))
            elif key == "stl_volume":
                out[key] = float(m.group(1).replace(",", ""))
            elif key == "image_name":
                out[key] = m.group(1).strip()
            else:
                out[key] = float(m.group(1))
    if "max_z_mm" in out and "base_mm" in out:
        out["height_mm"] = round(out["max_z_mm"] - out["base_mm"], 3)
    return out

# ─────────────────────────────────────────
# Calculation engine — separated by concern
# ─────────────────────────────────────────
def calc_print(w, d, zb, za, stl_vol):
    """3D print derived values."""
    base_vol    = round((w * d * zb) / 1000, 1)
    max_z       = round(zb + za, 2)
    art_space   = round((w * d * za) / 1000, 1)
    actual_art  = round(stl_vol - base_vol, 1)
    vol_to_max  = round(art_space - actual_art, 1)
    return {
        "base_volume":    base_vol,
        "max_z":          max_z,
        "art_space_vol":  art_space,
        "actual_art_vol": actual_art,
        "vol_to_max_z":   vol_to_max,
    }

def calc_geometry(w, d, wall, box_h, stl_vol):
    """Shared mold box dimensions.
    Gap surrounds print on 5 sides: W + 2×gap, D + 2×gap.
    Mold base is additional material below the print (variable, 0–30 mm).
    Mold material volume = box volume − STL volume + mold base volume.
    """
    box_w      = w + 2 * wall
    box_d      = d + 2 * wall
    box_vol    = round((box_w * box_d * box_h) / 1000, 1)
    model_vol  = round(stl_vol, 1)
    mold_vol   = round(box_vol - model_vol, 1)
    return {
        "box_w":        box_w,
        "box_d":        box_d,
        "box_volume":   box_vol,
        "model_volume": model_vol,
        "mold_vol":     mold_vol,
    }

def calc_alginate(w, d, mold_vol, max_z, wall, alg_zi, alg_ratio):
    """Alginate: box volume minus model, + optional Z extension.
    mold_vol = box_vol - stl_vol, already computed in calc_geometry.
    """
    zi_vol     = round(((w * d) / 1000) * alg_zi, 1)
    total_vol  = round(mold_vol + zi_vol, 1)
    water_g    = round(total_vol, 1)
    alginate_g = round(water_g / alg_ratio, 1) if alg_ratio > 0 else 0.0
    thickness  = round(max_z + alg_zi, 1)
    return {
        "alg_mold_vol":    total_vol,
        "alg_water_g":     water_g,
        "alg_alginate_g":  alginate_g,
        "alg_thickness":   thickness,
        "alg_total_thick": round(thickness + wall, 1),
    }

def calc_silicone(w, d, box_volume, model_volume, si_zi, si_ratio):
    """Silicone: fills box minus model, + optional Z extension.
    si_ratio splits total weight as part A : part B.
    """
    zi_vol    = round(((w * d) / 1000) * si_zi, 1)
    mold_vol  = round(box_volume - model_volume + zi_vol, 1)
    si_g      = round(mold_vol * 1.12, 1)
    part_a    = round(si_g * si_ratio / (si_ratio + 1), 1) if si_ratio > 0 else round(si_g / 2, 1)
    part_b    = round(si_g - part_a, 1)
    return {
        "si_zi_vol":      zi_vol,
        "mold_volume_si": mold_vol,
        "silicone_g":     si_g,
        "part_a":         part_a,
        "part_b":         part_b,
    }

def calc_investment(w, d, mold_vol, max_z, wall, inv_zi):
    """Investment: box volume minus model, + optional Z extension.
    mold_vol = box_vol - stl_vol, already computed in calc_geometry.
    """
    zi_vol  = round(((w * d) / 1000) * inv_zi, 1)
    inv_vol = round(mold_vol + zi_vol, 1)
    dry_inv = round(inv_vol * 1.25, 1)
    rr910   = round(inv_vol * 1.88, 1)
    return {
        "inv_vol":         inv_vol,
        "inv_total_thick": round(max_z + inv_zi + wall, 1),
        "dry_investment":  dry_inv,
        "plaster_g":       round(dry_inv / 2, 1),
        "silica_g":        round(dry_inv / 2, 1),
        "inv_water_g":     round(dry_inv / 1.75, 1),
        "rr910_g":         rr910,
        "rr910_water_g":   round(rr910 / (1.88 / 0.88), 1),
    }

# ─────────────────────────────────────────
# Session state defaults
# ─────────────────────────────────────────
FIELD_DEFAULTS = dict(
    title="", job_date=date.today(), mold_type="Alginate + Investment",
    width_mm=0.0, depth_mm=0.0, base_mm=0.0, height_mm=0.0, stl_volume=0.0,
    wall_mm=0.0,
    alg_adjust_zi=0.0, alg_mix_ratio=1.0,
    si_adjust_zi=0.0,  si_mix_ratio=1.0,
    inv_adjust_zi=0.0,
    notes="",
)
for k, v in FIELD_DEFAULTS.items():
    st.session_state.setdefault(f"ws_{k}", v)
st.session_state.setdefault("ws_loaded_id", None)


FLOAT_FIELDS = {k for k, v in FIELD_DEFAULTS.items() if isinstance(v, float)}

def _load_into_state(row):
    for k in FIELD_DEFAULTS:
        if k in row.keys() and row[k] is not None:
            val = row[k]
            if k == "job_date" and isinstance(val, str):
                try:
                    val = date.fromisoformat(val)
                except ValueError:
                    val = date.today()
            elif k in FLOAT_FIELDS:
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    val = FIELD_DEFAULTS[k]
            st.session_state[f"ws_{k}"] = val
    st.session_state["ws_loaded_id"] = row["id"]


def _reset_state():
    for k, v in FIELD_DEFAULTS.items():
        st.session_state[f"ws_{k}"] = v
    st.session_state["ws_loaded_id"] = None


# ─────────────────────────────────────────
# UI card helper
# ─────────────────────────────────────────
def card(title: str, rows: list,
         bg: str, border: str, label_color: str, value_color: str):
    trs = "".join(
        f'<tr>'
        f'<td style="padding:6px 0;color:{label_color};font-size:0.9rem;width:60%">{lbl}</td>'
        f'<td style="padding:6px 0;text-align:right;font-size:1rem;font-weight:700;'
        f'color:{value_color};white-space:nowrap">{val}</td>'
        f'</tr>'
        for lbl, val in rows
    )
    st.markdown(
        f'<div style="background:{bg};border-left:4px solid {border};'
        f'border-radius:0 8px 8px 0;padding:14px 18px;margin:8px 0 16px 0">'
        f'<div style="font-size:0.75rem;font-weight:700;color:{border};'
        f'letter-spacing:.06em;margin-bottom:8px">{title}</div>'
        f'<table style="width:100%;border-collapse:collapse">{trs}</table>'
        f'</div>',
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────
# TOP ROW: Import | Saved Records
# ─────────────────────────────────────────
top_left, top_right = st.columns([1, 1], gap="large")

with top_left:
    with st.expander("📄 Import from settings.txt", expanded=False):
        uploaded = st.file_uploader("Drop a settings.txt here", type=["txt"], key="settings_upload")
        paste    = st.text_area("…or paste the contents", height=120, key="settings_paste")
        if st.button("Parse & pre-fill", use_container_width=True):
            raw = ""
            if uploaded:
                raw = uploaded.read().decode("utf-8", errors="replace")
            elif paste.strip():
                raw = paste.strip()
            if raw:
                parsed = parse_settings_txt(raw)
                mapping = {
                    "width_mm":   "ws_width_mm",
                    "depth_mm":   "ws_depth_mm",
                    "base_mm":    "ws_base_mm",
                    "height_mm":  "ws_height_mm",
                    "stl_volume": "ws_stl_volume",
                }
                filled = []
                for src_k, state_k in mapping.items():
                    if src_k in parsed:
                        st.session_state[state_k] = parsed[src_k]
                        filled.append(src_k)
                if not st.session_state["ws_title"] and "image_name" in parsed:
                    st.session_state["ws_title"] = parsed["image_name"].rsplit(".", 1)[0]
                if filled:
                    st.success(f"Pre-filled: {', '.join(filled)}")
                else:
                    st.warning("No recognised fields found.")
            else:
                st.warning("Nothing to parse.")

with top_right:
    st.subheader("Saved Records")
    records = list_records()
    if not records:
        st.info("No saved records yet.")
    else:
        for row in records:
            mold_label = f"  ·  {row['mold_type']}" if row["mold_type"] else ""
            rc1, rc2, rc3 = st.columns([4, 1, 1])
            with rc1:
                st.markdown(f"**{row['title']}**{mold_label}  —  {row['job_date'] or 'no date'}")
                st.caption(f"Saved {row['created_at'][:16]}")
            with rc2:
                if st.button("Load", key=f"load_{row['id']}"):
                    _load_into_state(load_record(row["id"]))
                    st.rerun()
            with rc3:
                if st.button("🗑️", key=f"del_{row['id']}", help="Delete"):
                    delete_record(row["id"])
                    if st.session_state["ws_loaded_id"] == row["id"]:
                        _reset_state()
                    st.rerun()

    st.divider()
    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        if st.button("＋ New", use_container_width=True):
            _reset_state()
            st.rerun()
    with bc2:
        if st.button("↺ Reset", use_container_width=True):
            _reset_state()
            st.rerun()
    with bc3:
        loaded_id    = st.session_state.get("ws_loaded_id")
        save_label   = "💾 Update" if loaded_id else "💾 Save"
        save_clicked = st.button(save_label, use_container_width=True, type="primary")

st.divider()

# ─────────────────────────────────────────
# FULL-WIDTH WORKSHEET
# ─────────────────────────────────────────

# ── Title / date ──
hc1, hc2 = st.columns([3, 1])
with hc1:
    st.text_input("Title", key="ws_title", placeholder="e.g. Astrid #1")
with hc2:
    st.date_input("Date", key="ws_job_date")

st.divider()

# ── 3D Print Dimensions (inputs) ──
st.subheader("3D Print Dimensions")
dc1, dc2, dc3, dc4, dc5 = st.columns(5)
with dc1:
    st.number_input("Width X (mm)",       min_value=0.0, step=0.5, format="%.1f", key="ws_width_mm")
with dc2:
    st.number_input("Depth Y (mm)",       min_value=0.0, step=0.5, format="%.1f", key="ws_depth_mm")
with dc3:
    st.number_input("Base (mm)",       min_value=0.0, step=0.5, format="%.1f", key="ws_base_mm")
with dc4:
    st.number_input("Relief (mm)", min_value=0.0, step=0.1, format="%.1f", key="ws_height_mm")
with dc5:
    st.number_input("STL Volume (cm³)",   min_value=0.0, step=1.0, format="%.1f", key="ws_stl_volume")

st.divider()

# ── Mold Geometry (inputs) ──
st.subheader("Mold Geometry")
st.caption("Gap width between the print and the containment box walls.")
st.number_input("Gap Width (mm)", min_value=0.0, max_value=30.0, step=1.0, format="%.0f", key="ws_wall_mm")

st.divider()

# ── Mold type selector ──
st.subheader("Mold Type")
st.selectbox("Mold workflow", ["Alginate + Investment", "Silicone"],
             key="ws_mold_type")

st.divider()

# ─── All inputs are now rendered — read session state and calculate ───
w   = st.session_state["ws_width_mm"]
d   = st.session_state["ws_depth_mm"]
zb  = st.session_state["ws_base_mm"]
za  = st.session_state["ws_height_mm"]
stl = st.session_state["ws_stl_volume"]

p = calc_print(w, d, zb, za, stl)
g = calc_geometry(w, d,
                  st.session_state["ws_wall_mm"],
                  p["max_z"],
                  stl)

# ── 3D Print results ──
card("3D PRINT CALCULATIONS", [
    ("Base Volume",       f"{p['base_volume']} cm³"),
    ("Max Z Height",      f"{p['max_z']} mm"),
    ("Art Space Volume",  f"{p['art_space_vol']} cm³"),
    ("Actual Art Volume", f"{p['actual_art_vol']} cm³"),
    ("Volume to Max Z",   f"{p['vol_to_max_z']} cm³"),
], bg="#f0f2f6", border="#888", label_color="#444", value_color="#111")

# ── Mold geometry results ──
card("MOLD BOX", [
    ("Box W × D",       f"{g['box_w']:.0f} × {g['box_d']:.0f} mm"),
    ("Box Volume",      f"{g['box_volume']} cm³"),
    ("Model Volume",    f"{g['model_volume']} cm³"),
    ("Mold Volume",     f"{g['mold_vol']} cm³"),
], bg="#f0f2f6", border="#888", label_color="#444", value_color="#111")

# ── Mold-type-specific inputs + results ──
mold_type = st.session_state["ws_mold_type"]

if mold_type == "Alginate + Investment":
    # ── Alginate inputs ──
    st.subheader("Alginate")
    st.number_input("Adjust Base Z (mm)", min_value=0.0, step=0.5, format="%.1f",
                    key="ws_alg_adjust_zi")
    st.number_input("Mix Ratio (water : 1 alginate)", min_value=1.0, max_value=20.0,
                    step=0.5, format="%.1f", key="ws_alg_mix_ratio",
                    help="e.g. 5.5 = 5.5 parts water to 1 part alginate")
    a = calc_alginate(w, d, g["mold_vol"], p["max_z"],
                      st.session_state["ws_wall_mm"],
                      st.session_state["ws_alg_adjust_zi"],
                      st.session_state["ws_alg_mix_ratio"])
    card(f"ACCU-CAST ALGINATE 570 PGV  ·  {st.session_state['ws_alg_mix_ratio']:.1f} : 1", [
        ("Mold Volume  (Box − Model + Z)", f"{a['alg_mold_vol']} cm³"),
        ("Water",                              f"{a['alg_water_g']} g"),
        ("Alginate",                           f"{a['alg_alginate_g']} g"),
        ("Mold Thickness",                     f"{a['alg_thickness']} mm"),
        ("Total Thickness",                    f"{a['alg_total_thick']} mm"),
    ], bg="#dcfce7", border="#22c55e", label_color="#166534", value_color="#14532d")

    st.divider()

    # ── Investment inputs ──
    st.subheader("Investment")
    st.number_input("Adjust Base Z (mm)", min_value=0.0, step=0.5, format="%.1f",
                    key="ws_inv_adjust_zi")
    i = calc_investment(w, d, g["mold_vol"], p["max_z"],
                        st.session_state["ws_wall_mm"],
                        st.session_state["ws_inv_adjust_zi"])
    card(f"DRY INVESTMENT / PLASTER + SILICA  ·  Mold vol {i['inv_vol']} cm³", [
        ("Mold Volume  (Box − Model + Z)", f"{i['inv_vol']} cm³"),
        ("Dry Investment",                     f"{i['dry_investment']} g"),
        ("Plaster",                            f"{i['plaster_g']} g"),
        ("Silica Flour",                       f"{i['silica_g']} g"),
        ("Water",                              f"{i['inv_water_g']} g"),
        ("Total Thickness",                    f"{i['inv_total_thick']} mm"),
    ], bg="#fef9c3", border="#eab308", label_color="#92400e", value_color="#78350f")
    card(f"R&R 910  ·  Mold vol {i['inv_vol']} cm³ × 1.88", [
        ("R&R 910", f"{i['rr910_g']} g"),
        ("Water",   f"{i['rr910_water_g']} g"),
    ], bg="#f3e8ff", border="#a855f7", label_color="#6b21a8", value_color="#581c87")

elif mold_type == "Silicone":
    st.number_input("Adjust Base Z (mm)", min_value=0.0, step=0.5, format="%.1f",
                    key="ws_si_adjust_zi")
    st.number_input("Mix Ratio (x : 1)", min_value=1.0, max_value=20.0,
                    step=0.5, format="%.1f", key="ws_si_mix_ratio")
    s = calc_silicone(w, d, g["box_volume"], g["model_volume"],
                      st.session_state["ws_si_adjust_zi"],
                      st.session_state["ws_si_mix_ratio"])
    card(f"SIRATECH SILICONE  ·  ratio {st.session_state['ws_si_mix_ratio']:.1f} : 1", [
        ("Mold Volume  (Box − Model + Z)", f"{s['mold_volume_si']} cm³"),
        ("Total  (× 1.12)",                  f"{s['silicone_g']} g"),
        ("Part A",                              f"{s['part_a']} g"),
        ("Part B",                              f"{s['part_b']} g"),
    ], bg="#dbeafe", border="#3b82f6", label_color="#1e40af", value_color="#1e3a8a")

st.divider()
st.text_area("Notes", key="ws_notes", height=80,
             placeholder="Any observations, adjustments, or special instructions…")

# ─────────────────────────────────────────
# Save
# ─────────────────────────────────────────
if save_clicked:
    title = st.session_state["ws_title"].strip()
    if not title:
        st.error("Please enter a title before saving.")
    else:
        job_date_val = st.session_state["ws_job_date"]
        job_date_str = job_date_val.isoformat() if hasattr(job_date_val, "isoformat") else str(job_date_val)
        rec = dict(
            title         = title,
            job_date      = job_date_str,
            created_at    = datetime.now().isoformat(timespec="seconds"),
            mold_type     = st.session_state["ws_mold_type"],
            width_mm      = st.session_state["ws_width_mm"],
            depth_mm      = st.session_state["ws_depth_mm"],
            base_mm       = st.session_state["ws_base_mm"],
            height_mm     = st.session_state["ws_height_mm"],
            stl_volume    = st.session_state["ws_stl_volume"],
            wall_mm       = st.session_state["ws_wall_mm"],
            alg_adjust_zi = st.session_state["ws_alg_adjust_zi"],
            alg_mix_ratio = st.session_state["ws_alg_mix_ratio"],
            si_adjust_zi  = st.session_state["ws_si_adjust_zi"],
            si_mix_ratio  = st.session_state["ws_si_mix_ratio"],
            inv_adjust_zi = st.session_state["ws_inv_adjust_zi"],
            notes         = st.session_state["ws_notes"],
        )
        if loaded_id:
            update_record(loaded_id, rec)
            st.success(f"Record updated: {title}")
        else:
            new_id = save_record(rec)
            st.session_state["ws_loaded_id"] = new_id
            st.success(f"Record saved: {title}")
        st.rerun()
