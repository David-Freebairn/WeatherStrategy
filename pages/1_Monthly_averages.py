"""
pages/1_Monthly_averages.py — WeatherStrat
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Big picture for rainfall and temperature — long-term monthly averages
for the selected location: rainfall (bars, left axis, mm) and min/max
temperature (lines, right axis, °C), computed over the full cached
record. Underneath, a summary table of annual rainfall totals (min /
max / avg across full years of record).

Ported from Weather Explorer's pages/2_Monthly_averages.py, reading from
core/agcd.py instead of core/silo.py. Evaporation is dropped throughout —
AGCD doesn't carry it (see core/agcd.py's docstring) — leaving rainfall
and temperature only.

Uses the shared AGCD full-record cache from core/agcd.py (1900-2022).
"""

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import pandas as pd
import streamlit as st

from core.nav import HOME
from core.agcd import (ensure_climate_cached, AgcdUnavailableError, load_sample_data,
                        describe_grid_cell, grid_cell_warning, describe_tile_fingerprint)
from core.styles import apply_styles, load_station, change_station_button

apply_styles()

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Minimum days of data for a year to count as "full" in the annual summary
_FULL_YEAR_DAYS = 360


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


st.markdown("## Climate by month")
st.caption("Big picture for rainfall and temperature. (AGCD has no evaporation data.)")

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
        st.session_state["agcd_tile_fingerprint"] = describe_tile_fingerprint(full_df)
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
    change_station_button(HOME, key="ma_change_station")

_grid_note = st.session_state.get("agcd_grid_note")
if _grid_note:
    st.caption(_grid_note)
_grid_warning = st.session_state.get("agcd_grid_warning")
if _grid_warning:
    st.warning(_grid_warning, icon="\u26A0\uFE0F")
_tile_fp = st.session_state.get("agcd_tile_fingerprint")
if _tile_fp:
    st.caption(f"`{_tile_fp}`")

start_year = int(df["year"].min())
end_year   = int(df["year"].max())
available  = sorted(df["year"].unique())

# ── Long-term monthly averages ─────────────────────────────────────────────────
monthly_rain = (df.groupby(["year", "month"])["rain"].sum()
                   .groupby("month").mean()
                   .reindex(range(1, 13), fill_value=0.0))
monthly_tmax = df.groupby("month")["tmax"].mean().reindex(range(1, 13))
monthly_tmin = df.groupby("month")["tmin"].mean().reindex(range(1, 13))

# ── Annual totals, restricted to full years of record ──────────────────────────
days_per_year = df.groupby("year").size()
full_years = days_per_year[days_per_year >= _FULL_YEAR_DAYS].index

annual_rain = df[df["year"].isin(full_years)].groupby("year")["rain"].sum()

summary = pd.DataFrame({
    "Variable": ["Rainfall"],
    "Min":  [annual_rain.min()],
    "Max":  [annual_rain.max()],
    "Avg":  [annual_rain.mean()],
})

# ═════════════════════════════════════════════════════════════════════════════
# Chart — Plotly, dual axis
# ═════════════════════════════════════════════════════════════════════════════
import plotly.graph_objects as go

TITLE_FONT = dict(size=18, color="#444")
AXIS_FONT  = dict(size=11)
GRID_COLOR = "rgba(0,0,0,0.07)"

fig = go.Figure()
fig.add_trace(go.Bar(
    x=MONTH_NAMES, y=monthly_rain.round(1), name="Rainfall",
    marker_color="rgba(26,82,118,0.75)", yaxis="y",
))
fig.add_trace(go.Scatter(
    x=MONTH_NAMES, y=monthly_tmax.round(1), name="Max temp",
    line=dict(color="rgba(192,57,43,0.9)", width=2), mode="lines+markers",
    marker=dict(size=5), yaxis="y2",
))
fig.add_trace(go.Scatter(
    x=MONTH_NAMES, y=monthly_tmin.round(1), name="Min temp",
    line=dict(color="rgba(243,156,18,0.95)", width=2), mode="lines+markers",
    marker=dict(size=5), yaxis="y2",
))

fig.update_layout(
    title=dict(
        text=f"Monthly average: rain, min/max temperature, "
             f"{station['name']}, ({start_year} to {end_year})",
        x=0.5, xanchor="center", font=TITLE_FONT,
    ),
    height=480, margin=dict(l=55, r=55, t=55, b=70),
    legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.14, font=AXIS_FONT),
    plot_bgcolor="white", paper_bgcolor="white",
    hovermode="x unified", bargap=0.25,
    dragmode=False,
    yaxis=dict(title="Rainfall (mm)", rangemode="tozero", fixedrange=True,
               gridcolor=GRID_COLOR, tickfont=AXIS_FONT, title_font=AXIS_FONT),
    yaxis2=dict(title="Temperature (\u00b0C)", overlaying="y", side="right",
                rangemode="tozero", showgrid=False, fixedrange=True,
                tickfont=AXIS_FONT, title_font=AXIS_FONT),
    xaxis=dict(showgrid=False, tickfont=AXIS_FONT, fixedrange=True),
)
# Locked: no drag-zoom, scroll-zoom, or pinch-zoom — chart size/scale is
# fixed regardless of touch input, only hover tooltips remain interactive.
st.plotly_chart(
    fig, width="stretch", key="monthly_avg_fig",
    config={"displayModeBar": False, "scrollZoom": False, "doubleClick": False,
            "showAxisDragHandles": False, "staticPlot": False},
)

# ═════════════════════════════════════════════════════════════════════════════
# Summary table
# ═════════════════════════════════════════════════════════════════════════════
row_style = "padding:8px 12px;text-align:center;font-size:0.9rem;color:white;"
label_style = "padding:8px 12px;text-align:left;font-size:0.9rem;font-weight:600;color:white;"
head_style = "padding:8px 12px;text-align:center;font-size:0.85rem;font-weight:600;color:white;background:#1a5276;"

html = ['<table style="border-collapse:collapse;width:100%;max-width:600px;">']
html.append(
    "<tr>"
    f'<th style="{head_style}text-align:left;">Variable</th>'
    f'<th style="{head_style}">Min</th>'
    f'<th style="{head_style}">Max</th>'
    f'<th style="{head_style}">Avg</th>'
    "</tr>"
)
row_colors = ["#2e86c1", "#5dade2"]
for i, r in summary.iterrows():
    bg = row_colors[i % len(row_colors)]
    html.append(
        "<tr>"
        f'<td style="{label_style}background:{bg};">{r["Variable"]}</td>'
        f'<td style="{row_style}background:{bg};">{r["Min"]:.0f}mm</td>'
        f'<td style="{row_style}background:{bg};">{r["Max"]:.0f}mm</td>'
        f'<td style="{row_style}background:{bg};">{r["Avg"]:.0f}mm</td>'
        "</tr>"
    )
html.append("</table>")
st.markdown("".join(html), unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# Yearly grid (collapsed by default — recent years, monthly totals)
# ═════════════════════════════════════════════════════════════════════════════
with st.expander("Yearly grid — monthly rainfall totals (recent years)"):
    max_years = min(30, len(available))
    default_years = min(25, max_years)
    _persisted_n = st.session_state.get("persist_myr_grid_years", default_years)
    _clamped_n = min(max(int(_persisted_n), min(5, max_years)), max_years)
    n_years = st.slider(
        "Years to show", min_value=min(5, max_years), max_value=max_years,
        value=_clamped_n, step=1, key="myr_grid_years",
    )
    st.session_state["persist_myr_grid_years"] = n_years
    recent_years = [y for y in available if y > end_year - n_years]

    grid = (df[df["year"].isin(recent_years)]
              .pivot_table(index="year", columns="month", values="rain", aggfunc="sum")
              .reindex(index=sorted(recent_years), columns=range(1, 13), fill_value=0.0)
              .fillna(0.0))

    vmax = float(grid.values.max()) if grid.size else 0.0
    _STOPS = [(0.00, (255, 255, 255)), (0.05, (222, 235, 247)), (0.15, (158, 202, 225)),
              (0.30, (66, 146, 198)), (0.55, (33, 102, 172)), (1.00, (8, 48, 107))]

    def _grid_color(v):
        if vmax <= 0 or v <= 0:
            return "#ffffff"
        frac = min(v / vmax, 1.0)
        for i in range(len(_STOPS) - 1):
            lo_f, lo_c = _STOPS[i]
            hi_f, hi_c = _STOPS[i + 1]
            if frac <= hi_f:
                t = (frac - lo_f) / (hi_f - lo_f) if hi_f > lo_f else 1.0
                rgb = tuple(int(lo_c[j] + t * (hi_c[j] - lo_c[j])) for j in range(3))
                return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
        return "#08306b"

    def _grid_text(bg_hex):
        r, g, b = int(bg_hex[1:3], 16), int(bg_hex[3:5], 16), int(bg_hex[5:7], 16)
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        return "#ffffff" if lum < 140 else "#333333"

    g_head = "padding:4px 6px;text-align:center;font-size:0.72rem;font-weight:600;background:#f5f5f5;border:1px solid #eee;"
    g_year = "padding:4px 6px;text-align:center;font-size:0.72rem;font-weight:600;background:#fafafa;color:#888;border:1px solid #eee;"
    g_cell = "padding:4px 6px;text-align:center;font-size:0.72rem;border:1px solid #eee;"

    ghtml = ['<table style="border-collapse:collapse;width:100%;">']
    ghtml.append(
        "<tr>" + f'<th style="{g_head}">Year</th>' +
        "".join(f'<th style="{g_head}">{m}</th>' for m in MONTH_NAMES) + "</tr>"
    )
    for yr in sorted(recent_years):
        row = [f'<td style="{g_year}">{yr}</td>']
        for m in range(1, 13):
            v = grid.loc[yr, m]
            bg = _grid_color(v)
            fg = _grid_text(bg)
            row.append(f'<td style="{g_cell}background:{bg};color:{fg};">{v:.0f}</td>')
        ghtml.append("<tr>" + "".join(row) + "</tr>")
    ghtml.append("</table>")

    st.caption(f"Monthly rainfall totals (mm) for {station['name']}, "
               f"{sorted(recent_years)[0]}\u2013{end_year}.")
    st.markdown("".join(ghtml), unsafe_allow_html=True)

    grid_csv = grid.copy()
    grid_csv.columns = MONTH_NAMES
    grid_csv.index.name = "Year"
    st.download_button(
        "\U0001F4E5  Download yearly grid (CSV)",
        data=grid_csv.to_csv().encode("utf-8"),
        file_name=f"{station['name'].replace(' ', '_')}_monthly_totals_grid.csv",
        mime="text/csv",
    )

# ═════════════════════════════════════════════════════════════════════════════
# Downloads
# ═════════════════════════════════════════════════════════════════════════════
csv_df = pd.DataFrame({
    "Month": MONTH_NAMES,
    "Rainfall_mm": monthly_rain.round(1).values,
    "MaxTemp_C": monthly_tmax.round(1).values,
    "MinTemp_C": monthly_tmin.round(1).values,
})
csv_bytes = csv_df.to_csv(index=False).encode("utf-8")

safe_name = station["name"].replace(" ", "_")


def _build_jpeg() -> io.BytesIO:
    fig_m, ax1 = plt.subplots(figsize=(11, 6), dpi=130)
    xi = range(12)
    ax1.bar(xi, monthly_rain.values, color="#1a5276", alpha=0.8, label="Rainfall", zorder=2)
    ax1.set_ylabel("Rainfall (mm)", fontsize=10)
    ax1.set_ylim(bottom=0)
    ax1.set_xticks(list(xi))
    ax1.set_xticklabels(MONTH_NAMES, fontsize=9)
    ax1.grid(axis="y", color="0.92", linewidth=0.7)
    ax1.spines[["top"]].set_visible(False)

    ax2 = ax1.twinx()
    ax2.plot(xi, monthly_tmax.values, color="#c0392b", lw=2, marker="o", ms=4, label="Max temp")
    ax2.plot(xi, monthly_tmin.values, color="#f39c12", lw=2, marker="o", ms=4, label="Min temp")
    ax2.set_ylabel("Temperature (\u00b0C)", fontsize=10)
    ax2.set_ylim(bottom=0)
    ax2.spines[["top"]].set_visible(False)

    fig_m.suptitle(
        f"Monthly average: rain, min/max temperature, {station['name']}, "
        f"({start_year} to {end_year})", fontsize=15, y=0.98,
    )
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    fig_m.legend(h1 + h2, l1 + l2, loc="lower center", ncol=4, fontsize=9,
                 frameon=False, bbox_to_anchor=(0.5, -0.02))
    fig_m.subplots_adjust(top=0.90, bottom=0.16)

    buf = io.BytesIO()
    fig_m.savefig(buf, format="jpeg", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig_m)
    buf.seek(0)
    return buf


dcol1, dcol2 = st.columns(2)
with dcol1:
    st.download_button(
        "\U0001F4E5  Download monthly averages (CSV)", data=csv_bytes,
        file_name=f"{safe_name}_monthly_averages.csv",
        mime="text/csv", width="stretch",
    )
with dcol2:
    with st.spinner("Generating image\u2026"):
        jpeg_buf = _build_jpeg()
    st.download_button(
        "\U0001F5BC\uFE0F  Download chart (JPEG)", data=jpeg_buf,
        file_name=f"{safe_name}_monthly_averages.jpg",
        mime="image/jpeg", width="stretch",
    )
