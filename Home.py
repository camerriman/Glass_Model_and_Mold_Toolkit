from pathlib import Path
import streamlit as st

from i18n import render_app_sidebar, t

st.set_page_config(page_title=t("home.title", "Glass Library & Model and Mold Toolkit"), layout="wide")

# Hide auto-generated sidebar page list
st.markdown("""
<style>
[data-testid="stSidebarNav"] { display: none; }
</style>
""", unsafe_allow_html=True)

render_app_sidebar(nav_expanded=True)

st.title(t("home.title", "Glass Library & Model and Mold Toolkit"))
st.markdown(t("home.subtitle", "Use the links below to access model generation, mold design tools, and browse glass data."))

st.divider()

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown(f"#### {t('home.sections.model_tools', 'Model & Mold Tools')}")
    if st.button(t("home.nav.cameo", "Cameo Model Generator"), width='stretch'):
        st.switch_page("pages/1_Cameo_Model_Generator.py")
    if st.button(t("home.nav.vessel", "Vessel Model Generator"), width='stretch'):
        st.switch_page("pages/4_Vessel_Model_Generator.py")
    if st.button(t("home.nav.tiles_panels", "Model Tiles & Panels"), width='stretch'):
        st.switch_page("pages/2_Model_Tiles_Panels.py")
    if st.button(t("home.nav.mold_worksheet", "Cameo Mold Worksheet"), width='stretch'):
        st.switch_page("pages/3_Mold_Worksheet.py")
    if st.button(t("home.nav.pate_mold_worksheet", "Vessel Mold Worksheet"), width='stretch'):
        st.switch_page("pages/19_Pate_de_verre_Mold_Worksheet.py")
    if st.button(t("home.nav.print_optional_frame", "Print Frame Fabrication"), width='stretch'):
        st.switch_page("pages/22_Print_Optional_Frame.py")

with col2:
    st.markdown(f"#### {t('home.sections.glass_library', 'Glass Library')}")
    if st.button(t("home.nav.glass_library", "Glass Library"), width='stretch'):
        st.switch_page("pages/6_Glass_Library.py")
    if st.button(t("home.nav.glass_color_wheel", "Glass Color Wheel"), width="stretch"):
        st.switch_page("pages/7_Glass_Color_Wheel.py")
    if st.button(t("home.nav.glass_depth_side_view", "Glass Depth Side View"), width="stretch"):
        st.switch_page("pages/18_Glass_Depth_Side_View.py")
    if st.button(t("home.nav.layered_predictor", "Layered Glass Predictor"), width='stretch'):
        st.switch_page("pages/16_Layered_Glass_Predictor.py")
    if st.button(t("home.nav.frit_mix_explorer", "Frit Mix Explorer"), width='stretch'):
        st.switch_page("pages/17_Frit_Mix_Explorer.py")
    if st.button(t("home.nav.add_glass_sample", "Add Glass Sample"), width='stretch'):
        st.switch_page("pages/12_Add_Glass_Sample.py")

    if st.button(t("home.nav.edit_glass_sample", "Edit Glass Sample"), width='stretch'):
        st.switch_page("pages/13_Edit_Glass_Sample.py")

    if st.button(t("home.nav.documentation", "Documentation"), width='stretch'):
        st.switch_page("pages/14_Documentation.py")
    st.link_button(
        t("home.nav.kiln_forming_notes", "Kiln Glass Project Notes"),
        "https://kilnformingnotes.streamlit.app",
        width="stretch",
    )

with col3:
    st.markdown(f"#### {t('home.sections.reference_sheets', 'Reference Sheets')}")
    if st.button(t("home.nav.opalescent_reference", "Opalescent Reference"), width='stretch'):
        st.switch_page("pages/9_Opalescent_Reference.py")
    if st.button(t("home.nav.transparent_reference", "Transparent Reference"), width='stretch'):
        st.switch_page("pages/10_Transparent_Reference.py")
    if st.button(t("home.nav.tint_reference", "Tint Reference"), width='stretch'):
        st.switch_page("pages/11_Tint_Reference.py")

st.divider()

col1, col2, col3 = st.columns(3)

with col2:
    st.markdown(f"#### {t('home.sections.svg_tools', 'SVG Tools')}")
    if st.button(t("home.nav.svg_tiles", "SVG Tiles"), width='stretch'):
        st.switch_page("pages/20_SVG_Tiles.py")
    if st.button(t("home.nav.svg_crop", "SVG Crop"), width='stretch'):
        st.switch_page("pages/21_SVG_Crop.py")

   
st.divider()
