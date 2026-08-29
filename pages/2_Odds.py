"""
pages/2_Odds.py — WeatherStrat
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"What are the odds?" — rainfall frequency analysis: how often has a
given amount of rain fallen within a given window, between two dates,
across the record at this point?

Ported unchanged from Weather Explorer's pages/5_Odds.py, aside from the
data-source import: this reads from core/agcd.py (AGCD tile archive)
instead of core/silo.py (live SILO API). The analysis, chart, and JPEG
export logic is identical — only "rain" is used, and both sources agree
on its shape, so nothing else needed to change. The "start record" year
control (how far back the analysis looks) is kept as a page-specific
input next to the confirmed-location banner.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch as _Patch
import plotly.graph_objects as go
import streamlit as st
from datetime import date

from core.nav import HOME
from core.agcd import (ensure_climate_cached, slice_climate, AgcdUnavailableError,
                        load_sample_data, describe_grid_cell, grid_cell_warning)
from core.styles import apply_styles, load_station, change_station_button

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

apply_styles()


def _handle_agcd_down(exc):
    st.warning(
        f"\u26A0\uFE0F AGCD tile archive is currently unavailable ({exc}). "
        "You can use the bundled sample dataset to explore the app, if one is bundled."
    )
    if st.button("\U0001F4C2  Use sample data", key="use_sample"):
        try:
            df, station_info = load_sample_data(session_state=st.session_state)
            st.session_state["we_station"] = station_info
            st.rerun()
        except FileNotFoundError as e:
            st.error(str(e))
    st.stop()


def parse_df(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure the rainfall DataFrame has year/month/day columns."""
    if "year" not in df.columns:
        df["year"] = df.index.year
    if "month" not in df.columns:
        df["month"] = df.index.month
    if "day" not in df.columns:
        df["day"] = df.index.day
    return df


def assign_season_year(df, sm, sd, em, ed):
    df = df.copy()
    mo = df.index.month if "month" not in df.columns else df["month"]
    dy = df.index.day   if "day"   not in df.columns else df["day"]
    yr = df.index.year  if "year"  not in df.columns else df["year"]

    crosses = (sm > em) or (sm == em and sd > ed)
    after_start = (mo > sm) | ((mo == sm) & (dy >= sd))
    before_end  = (mo < em) | ((mo == em) & (dy <= ed))
    mask = after_start & before_end if not crosses else after_start | before_end
    df = df[mask].copy()

    mo2 = df.index.month if "month" not in df.columns else df["month"]
    dy2 = df.index.day   if "day"   not in df.columns else df["day"]
    yr2 = df.index.year  if "year"  not in df.columns else df["year"]

    if crosses:
        after = (mo2 > sm) | ((mo2 == sm) & (dy2 >= sd))
        df["season_year"] = np.where(after, yr2, yr2 - 1)
    else:
        df["season_year"] = yr2
    return df


def season_label(sm, sd, em, ed):
    return f"{sd} {MONTHS[sm-1]} \u2013 {ed} {MONTHS[em-1]}"


# ── Header ────────────────────────────────────────────────────────────────────
st.title("\U0001F3B2 What chance?")
st.caption("*Rainfall frequency analysis \u2014 how often has it happened before?*")

station = load_station()
if not station:
    st.info("No station selected yet.")
    st.page_link(HOME, label="\u2190 Back to select a station")
    st.stop()

# ── Confirmed-station banner + start-record year ───────────────────────────────
c1, c2, c3, c4 = st.columns([3.5, 1.3, 1.3, 1.4])
with c1:
    st.success(f"\U0001F4CD {station.get('label', station.get('name', ''))}")
with c2:
    st.markdown('<div style="margin-top:8px; font-size:0.9rem; color:#555;">Start record</div>',
                unsafe_allow_html=True)
with c3:
    start_year = st.number_input(
        "start_year", label_visibility="collapsed",
        min_value=1900, max_value=2022,
        value=st.session_state.get("odds_start_year", 1900),
        step=1, key="odds_start_year_input",
    )
    st.session_state["odds_start_year"] = start_year
with c4:
    st.markdown('<div style="margin-top:4px">', unsafe_allow_html=True)
    change_station_button(HOME, key="odds_change_station")
    st.markdown('</div>', unsafe_allow_html=True)

start_date = date(int(st.session_state.get("odds_start_year", 1900)), 1, 1)

_grid_note = st.session_state.get("agcd_grid_note")
if _grid_note:
    st.caption(_grid_note)
_grid_warning = st.session_state.get("agcd_grid_warning")
if _grid_warning:
    st.warning(_grid_warning, icon="\u26A0\uFE0F")

# ── Panel 2 — Query ───────────────────────────────────────────────────────────
r1a, r1b, r1c, r1d, r1e = st.columns([2.5, 0.8, 1.2, 0.8, 0.6])
with r1a:
    st.markdown('<span style="font-size:1.1rem">Chances of getting</span>', unsafe_allow_html=True)
with r1b:
    threshold = st.number_input(
        "mm", label_visibility="collapsed", min_value=1, max_value=9999,
        value=int(st.session_state.get("persist_odds_threshold", 25)),
        step=5, key="odds_threshold")
    st.session_state["persist_odds_threshold"] = threshold
with r1c:
    st.markdown('<span style="font-size:1.1rem">mm rain in</span>', unsafe_allow_html=True)
with r1d:
    win_days = st.number_input(
        "days", label_visibility="collapsed", min_value=1, max_value=365,
        value=int(st.session_state.get("persist_odds_win_days", 5)),
        step=1, key="odds_win_days")
    st.session_state["persist_odds_win_days"] = win_days
with r1e:
    st.markdown('<span style="font-size:1.1rem">days</span>', unsafe_allow_html=True)

r2a, r2b, r2c, r2d, r2e, r2f, r2g = st.columns([1.4, 1.2, 0.7, 0.4, 1.2, 0.7, 0.3])
with r2a:
    st.markdown('<span style="font-size:1.1rem">Between</span>', unsafe_allow_html=True)
with r2b:
    _persisted_sm = st.session_state.get("persist_odds_start_mon", MONTHS[0])
    start_mon = st.selectbox(
        "sm", MONTHS, index=MONTHS.index(_persisted_sm) if _persisted_sm in MONTHS else 0,
        label_visibility="collapsed", key="odds_start_mon")
    st.session_state["persist_odds_start_mon"] = start_mon
with r2c:
    start_day = st.number_input(
        "sd", min_value=1, max_value=31,
        value=int(st.session_state.get("persist_odds_start_day", 1)),
        label_visibility="collapsed", key="odds_start_day")
    st.session_state["persist_odds_start_day"] = start_day
with r2d:
    st.markdown('<span style="font-size:1.1rem">and</span>', unsafe_allow_html=True)
with r2e:
    _persisted_em = st.session_state.get("persist_odds_end_mon", MONTHS[11])
    end_mon = st.selectbox(
        "em", MONTHS, index=MONTHS.index(_persisted_em) if _persisted_em in MONTHS else 11,
        label_visibility="collapsed", key="odds_end_mon")
    st.session_state["persist_odds_end_mon"] = end_mon
with r2f:
    end_day = st.number_input(
        "ed", min_value=1, max_value=31,
        value=int(st.session_state.get("persist_odds_end_day", 31)),
        label_visibility="collapsed", key="odds_end_day")
    st.session_state["persist_odds_end_day"] = end_day
with r2g:
    st.markdown('<span style="font-size:1.3rem">?</span>', unsafe_allow_html=True)

# ── Info expander ─────────────────────────────────────────────────────────────
with st.expander("\u2139\uFE0F About this analysis"):
    st.markdown("""

**What are the odds?** assesses the probability of receiving a specified amount of
rainfall (mm) within a specified period (days), between two dates.
Results are presented as:
- The probability of conditions met in the past (% of years).
- A time series chart showing hits and misses.

**Applications**
- Assess the chances of receiving rainfall for critical events such as: planting,
harvest, herbicide and nutrient activation, fallow rainfall and in-crop rain.
- Explore how sensitive your \u201crules\u201d are by changing inputs and see results immediately.
- Long-term rainfall records provide a rich and objective picture of a site\u2019s history
and stretch a new land managers experience.
- These estimates are based on what is often termed \u201cclimatology\u201d and do not consider
any seasonal forecasts.

A copy of the results can be downloaded as an image.

""")

# ── Fetch climate data ──────────────────────────────────────────────────────────
sid  = station.get("id") or station.get("number")
name = station["name"]
_lat = station.get("lat")
_lon = station.get("lon")

_input_key  = (f"{sid}_{start_year}_{threshold}_{win_days}_"
               f"{start_mon}_{start_day}_{end_mon}_{end_day}")
_has_result = st.session_state.get("odds_result") is not None

if _input_key != st.session_state.get("odds_input_key") or not _has_result:
    st.session_state["odds_input_key"] = _input_key

    with st.spinner(f"Loading {name}\u2026 (first load may take 30\u201360 seconds)"):
        try:
            full_df = ensure_climate_cached(sid, _lat, _lon,
                                            session_state=st.session_state)
            st.session_state["agcd_grid_note"] = describe_grid_cell(full_df)
            st.session_state["agcd_grid_warning"] = grid_cell_warning(full_df)
            df = slice_climate(full_df, start=start_date.strftime("%Y%m%d"))
            df = parse_df(df)
        except AgcdUnavailableError as e:
            _handle_agcd_down(e)
        except Exception as e:
            st.error(f"Data fetch failed: {e}")
            st.stop()

    st.session_state["odds_result"] = {"df": df, "name": name}

# ── Analysis ──────────────────────────────────────────────────────────────────
if st.session_state.get("odds_result"):
    res  = st.session_state["odds_result"]
    df   = res["df"]
    name = res["name"]

    years    = sorted(df["year"].unique())
    yr_from, yr_to = years[0], years[-1]
    ann_mean = round(df.groupby("year")["rain"].sum().mean())

    try:
        sm = MONTHS.index(start_mon) + 1
        em = MONTHS.index(end_mon)   + 1
        sd_i, ed_i = int(start_day), int(end_day)
        slabel = season_label(sm, sd_i, em, ed_i)

        sub = assign_season_year(df, sm, sd_i, em, ed_i)
        sub = sub[(sub["season_year"] >= yr_from) & (sub["season_year"] <= yr_to)]

        if sub.empty:
            st.warning("No data in that season/year range.")
            st.stop()

        results = []
        for sy, grp in sub.sort_values("season_year").groupby("season_year"):
            rolled = grp["rain"].rolling(window=int(win_days), min_periods=int(win_days)).sum()
            mx = rolled.max()
            if not np.isnan(mx):
                occasions = int((rolled >= threshold).sum())
                results.append({"season_year": sy, "max_roll_mm": mx,
                                 "met_criteria": int(mx >= threshold),
                                 "occasions": occasions})

        if not results:
            st.warning("Not enough days to compute rolling window.")
            st.stop()

        annual_max = pd.DataFrame(results)
        rain       = annual_max["max_roll_mm"].values
        n          = len(rain)
        n_exceed   = int(np.sum(rain >= threshold))
        pct        = n_exceed / n * 100
        pct_display = int(round(pct))
        ann_mean   = round(df.groupby("year")["rain"].sum().mean())

        # ── Probability analysis header ────────────────────────────────────
        st.markdown(f"""
<div style="background:#f0f6ff; border-radius:10px; padding:18px 22px 14px 22px; margin-bottom:4px;">
  <div style="font-size:1.45rem; font-weight:700; color:#1a3a5c; margin-bottom:6px;">
    Probability analysis
  </div>
  <div style="display:flex; align-items:baseline; gap:0; flex-wrap:wrap;">
    <span style="font-size:1.02rem; color:#444; font-weight:500;">Rainfall exceeded&nbsp;</span>
    <span style="font-size:1.02rem; color:#e06b00; font-weight:700;">{int(threshold)} mm</span>
    <span style="font-size:1.02rem; color:#444; font-weight:500;">&nbsp;in&nbsp;</span>
    <span style="font-size:1.02rem; color:#e06b00; font-weight:700;">{int(win_days)} days</span>
    <span style="font-size:1.02rem; color:#444; font-weight:500;">&nbsp;between&nbsp;</span>
    <span style="font-size:1.02rem; color:#2979c4; font-weight:600;">{sd_i} {MONTHS[sm-1]}</span>
    <span style="font-size:1.02rem; color:#444; font-weight:500;">&nbsp;and&nbsp;</span>
    <span style="font-size:1.02rem; color:#2979c4; font-weight:600;">{ed_i} {MONTHS[em-1]}</span>
    <span style="flex:1; min-width:20px;"></span>
    <span style="font-size:1.5rem; font-weight:800; color:#0b1f3a;">
      {pct_display}%&nbsp;<span style="font-size:1.02rem; font-weight:500; color:#444;">of years</span>
    </span>
  </div>
</div>
""", unsafe_allow_html=True)

        # ── Interactive Plotly chart ────────────────────────────────────────
        NAVY = "#0b1f3a"; BLUE = "#2979c4"; BRIGHT = "#4da6ff"
        MISS = "#b8cfe8"; BG = "#f7fafd"; GRID = "#dde5ee"

        colours      = [BRIGHT if r >= threshold else MISS for r in annual_max["max_roll_mm"]]
        edge_colours = [BLUE   if r >= threshold else MISS for r in annual_max["max_roll_mm"]]

        hover_text = [
            f"{int(row.season_year)},  {row.occasions} times"
            for _, row in annual_max.iterrows()
        ]

        fig_plotly = go.Figure()
        fig_plotly.add_trace(go.Bar(
            x=annual_max["season_year"],
            y=annual_max["max_roll_mm"],
            marker_color=colours,
            marker_line_color=edge_colours,
            marker_line_width=0.8,
            hovertext=hover_text,
            hoverinfo="text",
            hoverlabel=dict(bgcolor=NAVY, font_color="white", font_size=13,
                            bordercolor=BLUE),
            showlegend=False,
        ))
        fig_plotly.add_hline(
            y=threshold, line_dash="dash", line_color=NAVY, line_width=1.8,
            annotation_text=f"  {int(threshold)} mm",
            annotation_position="right",
            annotation_font=dict(color=NAVY, size=11, family="Arial"),
        )
        fig_plotly.add_trace(go.Bar(
            x=[None], y=[None], marker_color=BRIGHT,
            marker_line_color=BLUE, marker_line_width=0.8,
            name=f"\u2265 {int(threshold)} mm  ({n_exceed} yrs)",
        ))
        fig_plotly.add_trace(go.Bar(
            x=[None], y=[None], marker_color=MISS,
            name=f"< {int(threshold)} mm  ({n - n_exceed} yrs)",
        ))
        fig_plotly.update_layout(
            height=320,
            plot_bgcolor=BG, paper_bgcolor=BG,
            margin=dict(l=60, r=60, t=20, b=50),
            dragmode=False,
            xaxis=dict(
                title="Season year", title_font=dict(size=10, color="#3a5a7a"),
                tickfont=dict(size=9, color="#3a5a7a"),
                tickangle=45 if n > 30 else 0,
                gridcolor=GRID, showgrid=False, linecolor=GRID,
                fixedrange=True,
            ),
            yaxis=dict(
                title=f"Max {int(win_days)}-day rainfall (mm)",
                title_font=dict(size=10, color="#3a5a7a"),
                tickfont=dict(size=9, color="#3a5a7a"),
                gridcolor=GRID, showgrid=True, zeroline=False,
                fixedrange=True,
            ),
            legend=dict(
                orientation="h", x=0, y=1.02, xanchor="left", yanchor="bottom",
                font=dict(size=10), bgcolor="rgba(0,0,0,0)",
            ),
            bargap=0.28,
        )
        # Locked: no drag-zoom, scroll-zoom, or pinch-zoom — chart size/scale
        # is fixed regardless of touch input, only hover tooltips remain.
        st.plotly_chart(
            fig_plotly, width="stretch", key="odds_chart",
            config={"displayModeBar": False, "scrollZoom": False, "doubleClick": False,
                    "showAxisDragHandles": False, "staticPlot": False},
        )

        # ── Save JPEG before closing fig ───────────────────────────────────
        import io as _io
        import matplotlib.gridspec as _gs

        PANEL_H = 1.4
        CHART_H = 4.0
        DPI     = 150

        comp_fig = plt.figure(figsize=(14, PANEL_H + CHART_H), facecolor="white")
        spec = _gs.GridSpec(2, 1, figure=comp_fig,
                            height_ratios=[PANEL_H, CHART_H], hspace=0.0)

        hax = comp_fig.add_subplot(spec[0])
        hax.set_facecolor("#f0f6ff")
        hax.set_xlim(0, 1); hax.set_ylim(0, 1)
        hax.axis("off")
        hax.text(0.012, 0.95, f"Station: {name}",
                 ha="left", va="top", fontsize=9, fontweight="bold",
                 color="#0b1f3a", transform=hax.transAxes)
        hax.text(0.012, 0.78, f"{yr_from}-{yr_to} period",
                 ha="left", va="top", fontsize=8.5, color="#444",
                 transform=hax.transAxes)
        hax.text(0.012, 0.60, f"Annual mean {ann_mean} mm",
                 ha="left", va="top", fontsize=8.5, fontweight="bold",
                 color="#444", transform=hax.transAxes)
        hax.text(0.012, 0.36, "Probability analysis",
                 ha="left", va="top", fontsize=13, fontweight="bold",
                 color="#1a3a5c", transform=hax.transAxes)

        parts = [
            ("Rainfall exceeded ", "#444", False),
            (f"{int(threshold)} mm", "#e06b00", True),
            (" in ", "#444", False),
            (f"{int(win_days)} days", "#e06b00", True),
            (" between ", "#444", False),
            (f"{sd_i} {MONTHS[sm-1]}", "#2979c4", True),
            (" and ", "#444", False),
            (f"{ed_i} {MONTHS[em-1]}", "#2979c4", True),
        ]
        comp_fig.canvas.draw()
        renderer = comp_fig.canvas.get_renderer()
        ax_bbox  = hax.get_window_extent(renderer=renderer)
        x_cur = 0.012; y_row = 0.10
        for txt, col, bold in parts:
            t = hax.text(x_cur, y_row, txt, ha="left", va="top", fontsize=10,
                         fontweight="bold" if bold else "normal",
                         color=col, transform=hax.transAxes)
            comp_fig.canvas.draw()
            bb = t.get_window_extent(renderer=renderer)
            x_cur += bb.width / ax_bbox.width
        hax.text(0.988, 0.10, f"{pct_display}% of years",
                 ha="right", va="top", fontsize=13, fontweight="bold",
                 color="#0b1f3a", transform=hax.transAxes)

        cax = comp_fig.add_subplot(spec[1])
        cax.set_facecolor(BG)
        colours2 = [BRIGHT if r >= threshold else MISS for r in annual_max["max_roll_mm"]]
        bars2 = cax.bar(annual_max["season_year"], annual_max["max_roll_mm"],
                        color=colours2, width=0.72, zorder=3, linewidth=0, alpha=0.95)
        for bar, r in zip(bars2, annual_max["max_roll_mm"]):
            if r >= threshold:
                bar.set_edgecolor(BLUE); bar.set_linewidth(0.8)
        cax.axhline(threshold, color=NAVY, lw=1.8, ls="--", zorder=4)
        cax.annotate(f"{int(threshold)} mm",
                     xy=(annual_max["season_year"].max(), threshold),
                     xytext=(6, 4), textcoords="offset points",
                     fontsize=9, color=NAVY, fontweight="bold",
                     va="bottom", ha="left", annotation_clip=False)
        cax.set_xlabel("Season year", fontsize=9.5, color="#3a5a7a", labelpad=5)
        cax.set_ylabel(f"Max {int(win_days)}-day rainfall  (mm)",
                       fontsize=9.5, color="#3a5a7a", labelpad=5)
        cax.tick_params(colors="#3a5a7a", labelsize=8.5)
        if n > 30: cax.tick_params(axis="x", rotation=45)
        cax.grid(True, axis="y", color=GRID, lw=0.9, zorder=0)
        cax.set_axisbelow(True)
        for sp in ["top", "right", "left"]: cax.spines[sp].set_visible(False)
        cax.spines["bottom"].set_color(GRID)
        cax.legend(handles=[
            _Patch(facecolor=BRIGHT, edgecolor=BLUE, linewidth=0.8,
                   label=f"\u2265 {int(threshold)} mm  ({n_exceed} yrs)"),
            _Patch(facecolor=MISS, label=f"< {int(threshold)} mm  ({n - n_exceed} yrs)"),
        ], fontsize=8.5, loc="upper left", framealpha=0.95, edgecolor=GRID, fancybox=False)
        comp_fig.tight_layout(pad=0.8)

        jpeg_buf = _io.BytesIO()
        comp_fig.savefig(jpeg_buf, format="jpeg", dpi=DPI,
                         bbox_inches="tight", facecolor="white")
        jpeg_buf.seek(0)
        plt.close(comp_fig)

        col_l, col_c, col_r = st.columns([1, 2, 1])
        with col_c:
            st.download_button(
                "\U0001F4E5  Download chart (JPEG)",
                data=jpeg_buf,
                file_name=f"rain_summary_{name.replace(' ', '_')}.jpg",
                mime="image/jpeg",
                width="stretch",
            )

    except Exception as e:
        st.error(f"Analysis error: {e}")
