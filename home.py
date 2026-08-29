"""
home.py — WeatherStrat
━━━━━━━━━━━━━━━━━━━━━━━
Landing page: pick a location, then choose an analysis.

  1. What chance?         — rainfall frequency analysis
  2. Climate by month     — long-term monthly rainfall/temperature averages
  3. Trend vs variability — annual rainfall/temperature trend over time

WeatherStrat is a test bed: same three "big picture" analyses as Weather
Explorer, but reading daily climate data from the AGCD tile archive
(core/agcd.py) instead of the live SILO API, to see whether an independent,
Commonwealth-hosted source is a viable fallback. Location picking still
uses SILO's station search purely as a name -> lat/lon lookup (and for the
reliability map's context) — the daily record itself comes from AGCD.

Record duration: 1900-2022 (frozen archive — see core/agcd.py).

Run via the router (Menu.py) — not directly.
"""

import base64
import io
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import folium
import numpy as np
import streamlit as st
from streamlit_folium import st_folium

from core.nav import ODDS, MONTHLY, TREND
from core.reliability import get_pct_observed, is_loaded, reliability_color, reliability_label
from core.silo import fetch_nearby_stations, search_stations
from core.styles import apply_styles, save_station, load_station

apply_styles()

_ICON_PATH = Path(__file__).resolve().parent / "assets" / "ws_icon.png"

# Basemap for both folium maps below. Carto retired free/anonymous access
# to its "positron"/"dark_matter" styles (they now serve an "API KEY
# REQUIRED" watermark instead of tiles), so this uses Esri's light-gray
# canvas basemap instead — free, no key, similarly minimal. Swap both the
# URL and attribution together if this provider ever changes too.
_MAP_TILES = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
              "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}")
_MAP_ATTR = "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ"

# Disables the gesture-based ways a map can rescale itself: mouse-wheel
# zoom, pinch-zoom, double-click/double-tap zoom, and drag-to-zoom-a-box.
# This is what was making the maps feel unstable on touch screens — a
# scroll or a stray two-finger touch was being read as a zoom gesture.
# Panning (drag) and the +/- zoom buttons stay on, since choosing a
# location still needs those; only *accidental* rescaling is blocked.
_MAP_LOCK = dict(scrollWheelZoom=False, touchZoom=False,
                  doubleClickZoom=False, boxZoom=False, keyboard=False)

ABOUT_TEXT = """
**To get started:**

- Select a location by name — press Enter, then pick from the list or click the map.
- Select an analysis from the menu.
    - What chance?
    - Climate by month
    - Trend vs variability
- Adjust each query to suit your situation (dates, thresholds, etc.).

**What this app is testing**

WeatherStrat is a companion to Weather Explorer, built to test whether the
AGCD tile archive — an independent, Commonwealth-hosted dataset built from
the same underlying Bureau of Meteorology observations as SILO — is a
workable fallback data source. It offers the same three "big picture"
analyses as Weather Explorer's History section, unchanged, but the daily
rainfall/temperature record behind them comes from AGCD instead of SILO.

**Two things worth knowing about AGCD, versus SILO:**
- The record runs 1900\u20132022 only (rainfall from 1900, temperature from
  1910) and does not update \u2014 it's for strategic/climatological analysis,
  not the current season.
- No evaporation data is available, so Climate by month shows rainfall and
  temperature only here.

**Acknowledgements**

Weather data: Bureau of Meteorology's Australian Gridded Climate Data
(AGCD v1-0-1), an independent archive from Ken Brook, alongside the
Queensland Government's SILO database (used here only for location search).

**Disclosure**

These analyses have been developed based on previous experience in
designing climate-focused decision support tools using Anthropic's Claude
AI software. This software was built to prototype new capabilities.
"""


def _station_picker_map(stations: list, chosen_label: str):
    """
    Render search results as clickable markers. Returns the label of the
    station whose marker was clicked this run, or None.
    """
    located = [s for s in stations if s.get("lat") is not None and s.get("lon") is not None]
    if not located:
        return None

    lats = [s["lat"] for s in located]
    lons = [s["lon"] for s in located]
    center = [sum(lats) / len(lats), sum(lons) / len(lons)]
    spread = max(max(lats) - min(lats), max(lons) - min(lons)) if len(located) > 1 else 0.1
    zoom = 9 if spread < 0.5 else (7 if spread < 2 else 5)

    m = folium.Map(location=center, zoom_start=zoom, tiles=_MAP_TILES,
                    attr=_MAP_ATTR, control_scale=True, **_MAP_LOCK)
    for s in located:
        is_chosen = s["label"] == chosen_label
        folium.CircleMarker(
            location=[s["lat"], s["lon"]],
            radius=14 if is_chosen else 11,
            tooltip=s["label"],
            popup=s["label"],
            color="#1a5276" if is_chosen else "#2980b9",
            fill=True,
            fill_color="#e8a33d" if is_chosen else "#2980b9",
            fill_opacity=0.9 if is_chosen else 0.75,
            weight=3 if is_chosen else 2,
        ).add_to(m)

    result = st_folium(
        m, height=320, use_container_width=True,
        returned_objects=["last_object_clicked_tooltip"],
        key="ws_station_map",
    )
    return result.get("last_object_clicked_tooltip") if result else None


def _reliability_map(station: dict, radius_km: int):
    """
    Map of `station` with a dashed radius circle and nearby SILO stations
    colour-coded by data reliability. This is SILO station density, used
    here only as a proxy for how well-gauged the area is (AGCD is built
    from the same underlying observations) — not a live query of AGCD
    itself, which has no per-station metadata.
    """
    try:
        nearby = fetch_nearby_stations(station["id"], radius_km=radius_km)
    except Exception as e:
        st.warning(f"Could not load nearby stations: {e}")
        return
    if not nearby:
        st.caption("No other SILO stations found in range.")
        return

    if not is_loaded():
        st.warning(
            "Reliability data file not found (`data/silo_reliability.csv`) — "
            "stations below are shown without colour coding.",
            icon="\u26a0\ufe0f",
        )

    m = folium.Map(location=[station["lat"], station["lon"]], zoom_start=9,
                    tiles=_MAP_TILES, attr=_MAP_ATTR, control_scale=True, **_MAP_LOCK)
    folium.Circle(
        location=[station["lat"], station["lon"]],
        radius=radius_km * 1000,
        color="#1a5276", weight=1.5, fill=False, dash_array="6,6",
    ).add_to(m)

    tooltip_lookup = {}
    for s in nearby:
        pct = get_pct_observed(s["id"])
        is_center = s["id"] == station["id"]
        tip = f'{s["name"]} — {reliability_label(pct)}'
        tooltip_lookup[tip] = s
        folium.CircleMarker(
            location=[s["lat"], s["lon"]],
            radius=16 if is_center else 12,
            tooltip=tip,
            color="#000000" if is_center else reliability_color(pct),
            weight=3 if is_center else 2,
            fill=True,
            fill_color=reliability_color(pct),
            fill_opacity=0.85,
        ).add_to(m)

    result = st_folium(
        m, height=380, use_container_width=True,
        returned_objects=["last_object_clicked_tooltip"],
        key="ws_reliability_map",
    )

    st.caption(
        "\U0001F7E2 \u226590% observed &nbsp;&nbsp; "
        "\U0001F7E0 50\u201389% &nbsp;&nbsp; "
        "\U0001F534 <50% &nbsp;&nbsp; "
        "\u26AA no data &nbsp;&nbsp;\u00b7&nbsp;&nbsp; "
        f"dashed circle = {radius_km} km radius (SILO station density, "
        "as a proxy for AGCD gauge density too) &nbsp;&nbsp;\u00b7&nbsp;&nbsp; "
        "click a dot to switch location",
        unsafe_allow_html=True,
    )

    clicked_tip = result.get("last_object_clicked_tooltip") if result else None
    clicked = tooltip_lookup.get(clicked_tip) if clicked_tip else None
    if clicked and clicked["id"] != station["id"]:
        label = clicked["name"]
        if clicked.get("state"):
            label += f'  [{clicked["state"]}]'
        if clicked.get("lat") is not None and clicked.get("lon") is not None:
            label += f'  ({clicked["lat"]:.3f}, {clicked["lon"]:.3f})'
        st.session_state["we_chosen"]    = label
        st.session_state["we_confirmed"] = True
        save_station({**clicked, "label": label})
        st.rerun()


def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


@st.cache_data
def _icon_odds_b64() -> str:
    """Small hit/miss threshold-bar preview, echoing the Odds page."""
    rng = np.random.default_rng(5)
    vals = rng.uniform(5, 60, 20)
    threshold = 30
    colors = ["#4da6ff" if v >= threshold else "#b8cfe8" for v in vals]

    fig, ax = plt.subplots(figsize=(2.5, 1.3), dpi=100)
    ax.bar(np.arange(20), vals, color=colors, width=0.7)
    ax.axhline(threshold, color="#0b1f3a", lw=1.3, ls="--")
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    return _fig_to_b64(fig)


@st.cache_data
def _icon_monthly_avg_b64() -> str:
    """Small bar + dual-line preview, echoing the Monthly averages page."""
    months = np.arange(12)
    rain = np.array([45, 42, 46, 44, 50, 58, 58, 52, 50, 52, 50, 53])
    tmax = np.array([30, 29.5, 27, 22, 17, 13, 12, 14, 18, 22.5, 26, 29.5])
    tmin = np.array([15, 15, 12.5, 8.5, 5, 3, 2, 3, 6, 9, 11.5, 14])

    fig, ax1 = plt.subplots(figsize=(2.5, 1.3), dpi=100)
    ax1.bar(months, rain, color="#1a5276", alpha=0.8, width=0.7)
    ax1.set_xticks([]); ax1.set_yticks([])
    for spine in ax1.spines.values():
        spine.set_visible(False)

    ax2 = ax1.twinx()
    ax2.plot(months, tmax, color="#c0392b", lw=1.6)
    ax2.plot(months, tmin, color="#e67e22", lw=1.6)
    ax2.set_xticks([]); ax2.set_yticks([])
    for spine in ax2.spines.values():
        spine.set_visible(False)

    return _fig_to_b64(fig)


@st.cache_data
def _icon_trend_b64() -> str:
    """Small scatter + best-fit-line preview, echoing the Trend page."""
    rng = np.random.default_rng(13)
    x = np.arange(60)
    y = 300 + 0.3 * x + rng.normal(0, 40, 60)
    slope, intercept = np.polyfit(x, y, 1)

    fig, ax = plt.subplots(figsize=(2.5, 1.3), dpi=100)
    ax.scatter(x, y, s=8, color="#7fb3e8", alpha=0.8, edgecolor="none")
    ax.plot(x, slope * x + intercept, color="#c0392b", lw=1.6)
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    return _fig_to_b64(fig)


title_col1, title_col2, title_col3 = st.columns([1, 8, 1], vertical_alignment="center")
with title_col1:
    if _ICON_PATH.exists():
        st.image(str(_ICON_PATH), width=64)
with title_col2:
    st.markdown("# WeatherStrat")
    st.caption("Strategic climate analyses \u2014 testing AGCD as an alternative to SILO")
with title_col3:
    with st.popover("\u2139\uFE0F About"):
        st.markdown(ABOUT_TEXT)

# ── Handle "Change" reset (must happen before widgets render) ─────────────────
if st.session_state.pop("we_reset", False):
    st.session_state["we_stations"]   = []
    st.session_state["we_confirmed"]  = False
    st.session_state["we_chosen"]     = None
    st.session_state["we_last_query"] = ""
    st.session_state["we_query"]      = ""
    st.session_state.pop("climate_df",  None)
    st.session_state.pop("climate_key", None)
    st.session_state.pop("agcd_grid_note", None)
    st.session_state.pop("agcd_grid_warning", None)
    save_station(None)

for k, v in [("we_stations", []), ("we_confirmed", False),
             ("we_chosen", None), ("we_last_query", "")]:
    if k not in st.session_state:
        st.session_state[k] = v

# Pre-populate from a location chosen earlier this session
_shared = load_station()
if _shared and not st.session_state.get("we_confirmed"):
    st.session_state["we_stations"]  = [_shared]
    st.session_state["we_confirmed"] = True
    st.session_state["we_chosen"]    = _shared.get("label") or _shared.get("name", "")

# ── Select a location ───────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown('<p class="section-title">Select a location (by SILO station name)</p>',
                unsafe_allow_html=True)

    confirmed = st.session_state.get("we_confirmed", False)

    if not confirmed:
        query = st.text_input(
            "station", label_visibility="collapsed",
            placeholder="e.g. Dalby — press Enter, then select from the list",
            key="we_query",
        )
        if query and len(query) >= 3:
            if st.session_state.get("we_last_query") != query:
                with st.spinner("Searching..."):
                    try:
                        st.session_state["we_stations"] = search_stations(query.strip())
                    except Exception as e:
                        st.error(f"Search failed: {e}")
                        st.session_state["we_stations"] = []
                st.session_state["we_last_query"] = query

            stations = st.session_state.get("we_stations", [])
            if stations:
                labels = [s["label"] for s in stations]
                chosen = st.session_state.get("we_chosen") or labels[0]
                if chosen not in labels:
                    chosen = labels[0]
                if len(labels) == 1:
                    st.session_state["we_chosen"]    = labels[0]
                    st.session_state["we_confirmed"] = True
                    save_station(stations[0])
                    st.rerun()
                else:
                    st.caption(f"**{len(labels)} stations found** — select one:")
                    rc1, rc2 = st.columns([5, 1])
                    with rc1:
                        chosen = st.radio(
                            "Station", options=labels,
                            index=labels.index(chosen) if chosen in labels else 0,
                            key="we_radio", label_visibility="collapsed",
                        )
                    with rc2:
                        st.markdown('<div style="margin-top:4px">', unsafe_allow_html=True)
                        if st.button("Select", key="we_select", width="stretch"):
                            st.session_state["we_chosen"]    = chosen
                            st.session_state["we_confirmed"] = True
                            save_station(next(s for s in stations if s["label"] == chosen))
                            st.rerun()
                        st.markdown('</div>', unsafe_allow_html=True)

                    st.caption("...or click a location on the map:")
                    clicked_label = _station_picker_map(stations, chosen)
                    if clicked_label and clicked_label in labels:
                        st.session_state["we_chosen"]    = clicked_label
                        st.session_state["we_confirmed"] = True
                        save_station(next(s for s in stations if s["label"] == clicked_label))
                        st.rerun()
            elif st.session_state.get("we_last_query"):
                st.warning("No stations found. Try a shorter search term.")
    else:
        chosen = st.session_state.get("we_chosen", "")
        c1, c2 = st.columns([5, 1])
        with c1:
            st.success(f"\U0001F4CD {chosen}")
        with c2:
            if st.button("Change", key="we_change", width="stretch"):
                st.session_state["we_reset"] = True
                st.rerun()

        _station = load_station()
        if _station and _station.get("lat") is not None and _station.get("lon") is not None:
            with st.expander("Show reliability map"):
                radius_km = st.slider(
                    "Radius (km)", min_value=10, max_value=200,
                    value=int(st.session_state.get("persist_we_radius", 50)),
                    step=10, key="we_radius",
                )
                st.session_state["persist_we_radius"] = radius_km
                _reliability_map(_station, radius_km=radius_km)

station = load_station()

st.write("")


def _render_cards(cards):
    cols = st.columns(len(cards))
    for col, (title, sub, icon_b64, target, key) in zip(cols, cards):
        with col:
            with st.container(border=True, key=key):
                st.markdown(
                    f'<div style="text-align:center;">'
                    f'<h3 style="margin:0.2rem 0 0.15rem 0;font-size:1.15rem;">{title}</h3>'
                    f'<p style="color:#666;font-size:0.85rem;margin:0 0 0.6rem 0;">{sub}</p>'
                    f'<img src="data:image/png;base64,{icon_b64}" '
                    f'style="width:100%;border:1px solid #e5e5e5;border-radius:6px;'
                    f'background:#fafafa;padding:4px;box-sizing:border-box;"/>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                st.page_link(target, label="Open", disabled=not station,
                             use_container_width=True)


st.markdown("**Analyses** \u2014 daily data sourced from AGCD, not SILO")
_render_cards([
    ("What chance?", "Rainfall frequency analysis", _icon_odds_b64(),
     ODDS, "we_card_odds"),
    ("Climate by month", "Rainfall & temperature", _icon_monthly_avg_b64(),
     MONTHLY, "we_card_monthly"),
    ("Trend vs variability", "Rainfall/temp trend over time", _icon_trend_b64(),
     TREND, "we_card_trend"),
])

if not station:
    st.caption("Select a location above to enable these.")
