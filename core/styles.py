"""
core/styles.py
===============
Small shared helpers for Weather Explorer:
  - apply_styles(): light global CSS tweaks
  - save_station()/load_station(): station selection shared across pages
    via st.session_state (kept alive across multipage navigation within
    the same browser session), backed by a small on-disk JSON file
    (.last_station.json) so the last-chosen station also survives a full
    app restart, not just page navigation.
"""

import json
from pathlib import Path

import streamlit as st

_LAST_STATION_PATH = Path(__file__).resolve().parent.parent / ".last_station.json"

# Shipped starting default before any station has ever been picked on this
# deployment — Dalby Airport (station 41522), 98.8% observed data per the
# bundled reliability CSV (the "DALBY POST OFFICE" station, by contrast, is
# ~0% observed / fully interpolated, so it's deliberately not used here).
_DEFAULT_STATION = {
    "id": 41522, "name": "DALBY AIRPORT",
    "label": "DALBY AIRPORT  [QLD]  (-27.160, 151.263)",
    "lat": -27.160, "lon": 151.263, "state": "QLD",
}

_CSS = """
<style>
.section-title {
    font-weight: 600;
    font-size: 0.95rem;
    color: #333;
    margin-bottom: 0.4rem;
}
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 10px;
}

/* Analysis cards on the Menu page (scoped to we_card_1 / _2 / _3 containers) */
[class*="st-key-we_card_"] {
    text-align: center;
}
[class*="st-key-we_card_"] [data-testid="stPageLink"] {
    display: flex;
    justify-content: center;
    margin-top: 0.8rem;
    padding-top: 0.6rem;
    border-top: 1px solid #eee;
}
[class*="st-key-we_card_"] [data-testid="stPageLink"] p {
    font-weight: 600;
    font-size: 1rem;
    color: #2979c4;
    margin: 0;
}
[class*="st-key-we_card_"] [data-testid="stPageLink"]:hover {
    background: #f5f8fa;
}

/* Card titles themselves — blue, to read as clickable alongside the
   "Open" link below them, not just plain section headers. */
[class*="st-key-we_card_"] h3 {
    color: #2979c4 !important;
}

/* Sidebar navigation links (custom-built, see Menu.py) — blue, same
   reasoning as the card titles above. */
section[data-testid="stSidebar"] [data-testid="stPageLink"] p,
section[data-testid="stSidebar"] [data-testid="stPageLink"] span {
    color: #2979c4 !important;
    font-weight: 500;
}

/* Leaflet/folium map attribution ("Leaflet | Tiles (C) Esri ...")
   — required by the tile provider's terms, so kept rather than removed,
   but shrunk and muted so it doesn't cover map content/controls on
   narrow screens (especially iPad/iPhone, where the map itself is short). */
.leaflet-control-attribution {
    font-size: 8px !important;
    line-height: 1.15 !important;
    max-width: 60vw;
    opacity: 0.6;
    padding: 0 4px !important;
}
.leaflet-control-attribution a {
    color: #666 !important;
}
</style>
"""


def apply_styles():
    st.markdown(_CSS, unsafe_allow_html=True)


def save_station(station: dict | None) -> None:
    """
    Store the selected station in session_state (shared by all pages this
    session) and also persist it to disk so it survives a full app restart.
    """
    st.session_state["we_station"] = station
    try:
        if station is None:
            _LAST_STATION_PATH.unlink(missing_ok=True)
        else:
            _LAST_STATION_PATH.write_text(json.dumps(station))
    except OSError:
        pass  # disk persistence is a convenience, not required


def load_station() -> dict | None:
    """
    Retrieve the currently selected station. Falls back to the last
    station saved on disk (from a previous run), then to a shipped
    default (Dalby Airport) if nothing has ever been picked yet.
    """
    if "we_station" in st.session_state:
        return st.session_state["we_station"]
    try:
        station = json.loads(_LAST_STATION_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        station = dict(_DEFAULT_STATION)
    st.session_state["we_station"] = station
    return station


def change_station_button(home_page, key: str = "change_station",
                           label: str = "Change station", width: str = "stretch") -> None:
    """
    A "Change station" control for the analysis pages that actually clears
    the current selection *before* navigating to Menu — unlike a plain
    st.page_link(home_page), which only navigates, leaving the previous
    station still marked "confirmed" on arrival and forcing a second
    click there to actually change it.
    """
    if st.button(label, key=key, width=width):
        st.session_state["we_reset"] = True
        st.switch_page(home_page)
