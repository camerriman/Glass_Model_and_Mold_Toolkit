import streamlit as st


st.set_page_config(page_title="QR Landing Page", layout="wide")

# This page is intentionally excluded from the app's curated navigation.
# Hide Streamlit's automatic page list so the direct-link landing page stays blank.
st.markdown(
    """
    <style>
    [data-testid="stSidebarNav"] { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.page_link("pages/6_Glass_Library.py", label="Glass Library")
