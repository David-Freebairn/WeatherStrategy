"""
Menu.py — WeatherStrat entrypoint
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Thin router, ported unchanged from Weather Explorer's Menu.py — see that
file for the reasoning on object-based st.Page routing.

Run locally with:  streamlit run Menu.py
Deploy main file:   Menu.py
"""

from pathlib import Path
import streamlit as st

_ICON_PATH = Path(__file__).resolve().parent / "assets" / "ws_icon.png"

st.set_page_config(
    page_title="WeatherStrat",
    page_icon=str(_ICON_PATH) if _ICON_PATH.exists() else "\U0001F326\uFE0F",
    layout="wide",
)

from core.nav import SECTIONS  # noqa: E402  (must follow set_page_config)

pg = st.navigation(SECTIONS, position="hidden")

with st.sidebar:
    for section_label, pages in SECTIONS.items():
        if section_label:
            st.markdown(f"**{section_label}**")
        for p in pages:
            st.page_link(p)
        st.write("")

pg.run()
