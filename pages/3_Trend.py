"""
pages/3_Trend.py — WeatherStrat
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"What trend?" — annual rainfall or annual mean temperature over the
record at this point, as:
  1. All years — a scatter of the annual value against year, with the
     overall long-term average and a single line of best fit (linear
     regression) across the whole record.
  2. Four periods — the same scatter, split into four roughly-equal
     historical periods, each with its own independently-fitted trend
     segment. This surfaces whether the trend has been stable across
     the record or has sped up/slowed/reversed in different eras — a
     single all-years slope can hide that.

Only full calendar years (>=350 days of record) count toward either
analysis, so a partial first or last year in the record doesn't skew
the annual totals/averages.

Ported from Weather Explorer's pages/7_Trend.py, reading from
core/agcd.py instead of core/silo.py. One AGCD-specific addition: the
temperature series is explicitly dropped of NaNs before fitting, since
AGCD's temperature record only starts in 1910 (SILO's starts in 1889,
before this app's own default record start, so the equivalent Weather
Explorer page never needed to worry about a mid-record gap).
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import numpy as np
import pandas as pd
import streamlit as st

from core.nav import HOME
from core.agcd import (ensure_climate_cached, AgcdUnavailableError, load_sample_data,
                        describe_grid_cell, grid_cell_warning)
from core.styles import apply_styles, load_station, change_station_button

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


def _shade_decades(ax, start_year, end_year):
    """Alternating yellow decade bands, aligned to round decades, for
    visual readability across a long year range (matches the other
    long-record charts in this app)."""
    decade0 = (start_year // 10) * 10
    shade = False
    y = decade0
    while y < end_year:
        if shade:
            ax.axvspan(y, min(y + 10, end_year), color="#f5e6a8", alpha=0.5, zorder=0)
        shade = not shade
        y += 10


st.markdown("## \U0001F4C8 Trend vs variability")
st.caption("Annual rainfall or temperature over the station's record — one overall trend vs four separate eras")

station = load_station()
if not station:
    st.info("No station selected yet.")
    st.page_link(HOME, label="\u2190 Back to select a station")
    st.stop()

sid = station.get("id") or station.get("number")
lat = station.get("lat")
lon = station.get("lon")

with st.spinner(f"Loading climate data for {station['name']}\u2026 (first load may take 30\u201360 seconds)"):
    try:
        full_df = ensure_climate_cached(sid, lat=lat, lon=lon, session_state=st.session_state)
        st.session_state["agcd_grid_note"] = describe_grid_cell(full_df)
        st.session_state["agcd_grid_warning"] = grid_cell_warning(full_df)
    except AgcdUnavailableError as e:
        _handle_agcd_down(e)
    except Exception as e:
        st.error(f"Data fetch failed: {e}")
        st.stop()

df = st.session_state["climate_df"].copy()

c1, c2 = st.columns([5, 1])
with c1:
    st.success(f"\U0001F4CD {station.get('label', station.get('name', ''))}")
with c2:
    change_station_button(HOME, key="trend_change_station")

_grid_note = st.session_state.get("agcd_grid_note")
if _grid_note:
    st.caption(_grid_note)
_grid_warning = st.session_state.get("agcd_grid_warning")
if _grid_warning:
    st.warning(_grid_warning, icon="\u26A0\uFE0F")

_TREND_OPTIONS = ["Annual rainfall", "Temperature (annual average)"]
_persisted_var = st.session_state.get("persist_trend_variable", _TREND_OPTIONS[0])
variable = st.selectbox(
    "Variable", _TREND_OPTIONS,
    index=_TREND_OPTIONS.index(_persisted_var) if _persisted_var in _TREND_OPTIONS else 0,
    key="trend_variable",
)
st.session_state["persist_trend_variable"] = variable

# ── Build the annual series, complete years only ────────────────────────────
day_counts = df.groupby("year").size()
complete_years = day_counts[day_counts >= 350].index

if variable == "Annual rainfall":
    annual = df[df["year"].isin(complete_years)].groupby("year")["rain"].sum()
    unit = "mm"
    y_label = "Annual rainfall (mm)"
else:
    tmean = (df["tmax"] + df["tmin"]) / 2.0
    annual = tmean.groupby(df["year"]).mean()
    annual = annual[annual.index.isin(complete_years)]
    unit = "\u00b0C"
    y_label = "Annual average temperature (\u00b0C)"

# AGCD temperature only starts in 1910 — drop the pre-1910 years here
# (all-NaN tmean) rather than let them break the polyfit below.
annual = annual.dropna().sort_index()
years = annual.index.values.astype(float)
values = annual.values.astype(float)

if len(years) < 8:
    st.warning("Not enough complete years of record at this station for a trend analysis.")
    st.stop()

start_year, end_year = int(years.min()), int(years.max())
overall_mean = float(values.mean())
slope_all, intercept_all = np.polyfit(years, values, 1)

# ── Chart 1 — All years ──────────────────────────────────────────────────────
st.markdown("### All years")

fig1, ax1 = plt.subplots(figsize=(12, 4.2))
_shade_decades(ax1, start_year, end_year)
ax1.scatter(years, values, s=22, color="#7fb3e8", alpha=0.75, zorder=2, edgecolor="none")
ax1.axhline(overall_mean, color="#333333", lw=1.3, zorder=3)
ax1.annotate(f"Average", xy=(start_year, overall_mean), xytext=(4, 5),
             textcoords="offset points", fontsize=9, color="#333333", va="bottom")
fit_line = slope_all * years + intercept_all
ax1.plot(years, fit_line, color="#c0392b", lw=1.8, zorder=3)

ax1.set_ylabel(y_label, fontsize=10)
ax1.set_xlim(start_year - 1, end_year + 1)
ax1.grid(axis="y", color="#e5e5e5", lw=0.6, zorder=0)
ax1.tick_params(labelsize=9)
for spine in ("top", "right"):
    ax1.spines[spine].set_visible(False)

st.pyplot(fig1, width="stretch")
plt.close(fig1)

sign = "+" if slope_all >= 0 else ""
st.caption(
    f"Trend slope = {sign}{slope_all:.3f} {unit}/yr  \u2014  "
    f"Average {overall_mean:.0f} {unit}  \u2014  {start_year}\u2013{end_year} "
    f"({len(years)} complete years)"
)

# ── Chart 2 — Four periods ───────────────────────────────────────────────────
st.markdown("### Four periods")

n_periods = 4
if len(years) < n_periods * 4:
    st.caption(
        "\u2139\uFE0F Not enough complete years of record to split into four "
        "meaningful periods here \u2014 showing the all-years trend above instead."
    )
else:
    bin_edges = np.linspace(0, len(years), n_periods + 1).round().astype(int)

    fig2, ax2 = plt.subplots(figsize=(12, 4.2))
    _shade_decades(ax2, start_year, end_year)
    ax2.scatter(years, values, s=22, color="#7fb3e8", alpha=0.75, zorder=2, edgecolor="none")

    period_rows = []
    for i in range(n_periods):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        py = years[lo:hi]
        pv = values[lo:hi]
        if len(py) < 3:
            continue
        pslope, pintercept = np.polyfit(py, pv, 1)
        pfit = pslope * py + pintercept
        ax2.plot(py, pfit, color="#c0392b", lw=2.2, zorder=4)
        ax2.scatter([py[0], py[-1]], [pfit[0], pfit[-1]], color="#2e7d32", s=45,
                    zorder=5, edgecolor="white", linewidth=0.8)
        label_y = max(pfit.max(), pv.max()) + (values.max() - values.min()) * 0.06
        psign = "+" if pslope >= 0 else ""
        ax2.annotate(
            f"{int(py[0])}\u2013{int(py[-1])}\n{psign}{pslope:.3f} {unit}/yr",
            xy=((py[0] + py[-1]) / 2, label_y), ha="center", va="bottom",
            fontsize=8.5, color="#333333",
        )
        period_rows.append({
            "Period": f"{int(py[0])}\u2013{int(py[-1])}",
            f"Trend ({unit}/yr)": round(pslope, 3),
            f"Average ({unit})": round(pv.mean(), 1),
        })

    ax2.set_ylabel(y_label, fontsize=10)
    ax2.set_xlim(start_year - 1, end_year + 1)
    ax2.set_ylim(top=values.max() + (values.max() - values.min()) * 0.22)
    ax2.grid(axis="y", color="#e5e5e5", lw=0.6, zorder=0)
    ax2.tick_params(labelsize=9)
    for spine in ("top", "right"):
        ax2.spines[spine].set_visible(False)

    st.pyplot(fig2, width="stretch")
    plt.close(fig2)

    if period_rows:
        st.dataframe(pd.DataFrame(period_rows), width="stretch", hide_index=True)
