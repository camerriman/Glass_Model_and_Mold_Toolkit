from pathlib import Path
import streamlit as st

st.set_page_config(page_title="Glass Toolkit & Library", layout="wide")

# Hide auto-generated sidebar page list
st.markdown("""
<style>
[data-testid="stSidebarNav"] { display: none; }
</style>
""", unsafe_allow_html=True)

st.title("Glass Model and Mold Toolkit & Library")
st.markdown("Use the links below to access model generation, mold design tools, and browse glass data.")

st.divider()

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("#### 🔧 Model & Mold Tools")
    if st.button("Cameo Model Generator", width='stretch'):
        st.switch_page("pages/1_Cameo_Model_Generator.py")
    if st.button("Vessel Model Generator", width='stretch'):
        st.switch_page("pages/4_Vessel_Model_Generator.py")
    if st.button("Model Tiles & Panels", width='stretch'):
        st.switch_page("pages/2_Model_Tiles_Panels.py")
    if st.button("Mold Worksheet", width='stretch'):
        st.switch_page("pages/3_Mold_Worksheet.py")

with col2:
    st.markdown("#### 🔬 Glass Library")
    if st.button("Glass Library", width='stretch'):
        st.switch_page("pages/6_Glass_Library.py")
    if st.button("Glass Color Wheel", width="stretch"):
        st.switch_page("pages/7_Glass_Color_Wheel.py")
    if st.button("Add Glass Sample", width='stretch'):
        st.switch_page("pages/12_Add_Glass_Sample.py")

    if st.button("Edit Glass Sample", width='stretch'):
        st.switch_page("pages/13_Edit_Glass_Sample.py")

    if st.button("Documentation", width='stretch'):
        st.switch_page("pages/14_Documentation.py")

with col3:
    st.markdown("#### 📋 Reference Sheets")
    if st.button("Opalescent Reference", width='stretch'):
        st.switch_page("pages/9_Opalescent_Reference.py")
    if st.button("Transparent Reference", width='stretch'):
        st.switch_page("pages/10_Transparent_Reference.py")
    if st.button("Tint Reference", width='stretch'):
        st.switch_page("pages/11_Tint_Reference.py")

st.divider()

col1, col2, col3 = st.columns(3)

with col2:
    st.markdown("#### ✂️ SVG Tools")
    if st.button("SVG Tiles", width='stretch'):
        st.switch_page("pages/20_SVG_Tiles.py")
    if st.button("SVG Crop", width='stretch'):
        st.switch_page("pages/21_SVG_Crop.py")

   
st.divider()
