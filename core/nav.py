"""
core/nav.py
============
Central definition of WeatherStrat's pages as StreamlitPage objects.

Same object-reference pattern as Weather Explorer's core/nav.py (see that
file's docstring for why: filename-string page_link/switch_page is fragile
across OSes/working directories). WeatherStrat deliberately ships with only
three analyses while it tests AGCD as an alternative to SILO — see
home.py/README for the reasoning.
"""

import streamlit as st

HOME    = st.Page("home.py", title="Menu", icon="\U0001F3E0", default=True)
MONTHLY = st.Page("pages/1_Monthly_averages.py", title="Climate by month")
ODDS    = st.Page("pages/2_Odds.py", title="What chance?")
TREND   = st.Page("pages/3_Trend.py", title="Trend vs variability")

ALL_PAGES = [HOME, ODDS, MONTHLY, TREND]

SECTIONS = {
    "": [HOME],
    "Analyses": [ODDS, MONTHLY, TREND],
}
