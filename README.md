# WeatherStrat

A test bed for one question: **is AGCD a workable fallback for SILO?**

WeatherStrat runs the same three "big picture" strategic analyses as
Weather Explorer's History section, but reads daily rainfall/temperature
from Ken Brook's **AGCD tile archive** instead of the live **SILO** API.
SILO is a Queensland Government service; AGCD is an independent,
Commonwealth-hosted dataset built from the same underlying Bureau of
Meteorology observations. If the two give the same strategic answers at
sites you know well, AGCD is a genuine insurance policy if SILO's future
ever becomes uncertain.

## Quick start

```bash
pip install -r requirements.txt
streamlit run Menu.py
```

Then: search for a location by name (top of the Menu page), pick a
station from the list or map, and open one of the three analyses.

**First-time note:** the first time you look at a *new* one-degree square
of the country, the app downloads that AGCD tile (~40 MB) from Ken's
Google Drive folder — expect a 10–30 second wait once. Every other point
in that same square (any farm within ~100 km) is then instant, forever —
the archive is frozen at 2022 and never changes, so nothing here ever
needs re-fetching once it's on disk.

## Analyses

1. **What chance?** — rainfall frequency analysis: how often has a given
   amount of rain fallen within a given window, across the record?
2. **Climate by month** — long-term monthly rainfall/temperature averages.
3. **Trend vs variability** — annual rainfall/temperature trend over
   time, both as one all-years fit and as four separate historical eras.

These three are otherwise unchanged from Weather Explorer — same charts,
same JPEG/CSV export, same query controls. Only the daily data underneath
them, and the location-picking mechanics, are different. See each page's
own docstring for specifics.

## How a location becomes a grid cell

There's no "AGCD station" — AGCD is a continuous 0.05° (~5 km) grid, not
a network of named sites. So:

1. You search by name, which queries **SILO's** station metadata (not its
   daily data) to get a station and its lat/lon — e.g. Dalby Airport,
   -27.18, 151.27.
2. `core/agcd.py` works out which 1°×1° tile covers that point (tile
   `S28E151` for Dalby) and fetches it if not already cached.
3. Inside that tile, `xarray` picks the **nearest** grid-cell centre to
   the station's coordinates (`method="nearest"`) — not an interpolation
   between cells.

Each page shows a caption naming the actual grid cell used and its
distance from the searched site (usually well under 5 km — half the
5 km cell width, at most). If a match resolves more than 8 km away, or
its rainfall analysis weight suggests it's landed over water, you'll see
a warning instead — both are sanity checks against a mistyped coordinate,
not signs of a real data problem.

**Because of this**, WeatherStrat's numbers at "the same site" as a SILO
extraction will be close but not identical to Weather Explorer's — one
is a station's own patched record, the other is a nearby grid cell's
analysis. Comparing the two is the whole point of this app.

## What's different from Weather Explorer, and why

| | SILO (Weather Explorer) | AGCD (WeatherStrat) |
|---|---|---|
| Coverage | 1889 → today, updates daily | 1900–2022 only, frozen |
| Temperature from | 1889 | 1910 (NaN before) |
| Evaporation | Yes (pan evap) | **No** — dropped from Climate by month |
| Vapour pressure / radiation | No | No |
| Location | Named station (point) | Nearest 0.05° grid cell (interpolated analysis) |
| Access | Live API call, ~24 h cache | Google Drive tile download, cached forever |

## Data source module: `core/agcd.py`

Mirrors `core/silo.py`'s public interface — `ensure_climate_cached`,
`slice_climate`, `load_sample_data` — so all three pages needed no logic
changes beyond the import line. Two extras specific to AGCD:
`describe_grid_cell(df)` and `grid_cell_warning(df)`, which the pages use
to show the caption/warning described above.

**Caching, three layers deep** (fastest to slowest):

1. `st.session_state` — instant, same browser session.
2. Disk cache — a small parquet file per extracted point
   (`.agcd_cache/points/`), plus a sidecar `.json` holding the grid-cell
   metadata (tile id, pixel centre, distance) — needed because pandas
   doesn't preserve `DataFrame.attrs` through a parquet round-trip, so
   without the sidecar a second session hitting the disk cache would
   otherwise lose the caption's data.
3. Tile download — from Google Drive, into `.agcd_cache/tiles/`, one
   `.nc` file per one-degree square, ~40 MB each. Never expires — the
   archive is frozen, unlike SILO's 24-hour cache.

**Tile delivery mechanics:** tiles live in a folder on Ken's Google Drive,
shared "anyone with the link". `core/agcd.py` calls the Drive API's
`files.list` to find a tile's file id by name, then streams it down from
`files/{id}?alt=media` — ported directly from Ken's own `agcd_point.py`.

**About the API key:** the app ships with Ken's own key (`_API_KEY` near
the top of `core/agcd.py`). It's a read-only credential against files
that are already public — not a password to his account — so it's fine
to use as-is short term. Two reasons to eventually swap in your own
(neither urgent): Google rate-limits per key, so you'd otherwise share
his allowance; and it's simply tidier for requests to be yours if this
becomes a regular tool or gets passed to clients. To do that: generate a
free key at console.cloud.google.com (enable the Google Drive API, no
billing needed — a ten-minute job, no OAuth consent screen, just
generate-and-copy), then replace the `_API_KEY` string. The `_FOLDER_ID`
line above it stays as-is — that's what points at Ken's shared archive.

## Troubleshooting

**"Data fetch failed: found the following matches with the input file
in xarray's IO backends... dependencies may not be installed"** — xarray
needs `netCDF4` or `h5netcdf` installed to actually open `.nc` tile
files; the file being found isn't enough. In practice:

- Run `python3 -c "import h5netcdf"` in the **exact same terminal/environment**
  you use for `streamlit run Menu.py`. If that fails, `pip install h5netcdf`
  there (it's in `requirements.txt`, but a `pip install -r requirements.txt`
  that also tries to install `netCDF4` can abort partway through on
  platforms without a prebuilt `netCDF4` wheel — e.g. Python 3.13 on
  macOS, at time of writing — silently skipping everything listed after
  it. `requirements.txt` here intentionally omits `netCDF4` and relies on
  `h5netcdf` alone, which reads the same HDF5-based files without that
  problem).
- If `python3 -c "import h5netcdf"` succeeds but the app still errors,
  **fully restart** Streamlit (Ctrl+C, then `streamlit run Menu.py`
  again) — a package installed after the server process started won't be
  picked up by a browser refresh alone.
- If you use both a plain Python and something like Anaconda, double
  check `pip install ...` and `streamlit run ...` are using the *same*
  one (`which python3`, `which streamlit`/`which pip` should agree).

**"AGCD tile archive is currently unavailable"** — either no internet
reachable, or the Google Drive folder/API key stopped working. Check the
error text shown for specifics; try the bundled sample dataset button if
one is present.

**A location is refused / no tile found** — the point is over ocean,
outside Australia, or the coordinates were mistyped (Australia is
roughly latitude -10 to -44, longitude 112 to 154 — note latitude is
negative).

## File map

```
weatherstrat/
├── Menu.py                    entrypoint / page router
├── home.py                    location search + map picker, analysis cards
├── requirements.txt
├── core/
│   ├── agcd.py                 AGCD data source — tiles, caching, grid-cell metadata
│   ├── silo.py                 SILO station name search only (no daily-data fetch)
│   ├── nav.py                  page definitions (st.Page objects)
│   ├── styles.py                shared CSS + last-selected-station persistence
│   └── reliability.py           SILO station reliability lookup (for the map)
├── pages/
│   ├── 1_Monthly_averages.py   "Climate by month"
│   ├── 2_Odds.py                "What chance?"
│   └── 3_Trend.py               "Trend vs variability"
├── data/silo_reliability.csv   station reliability data, for the picker's map
├── assets/ws_icon.png
└── .agcd_cache/                 tile + point cache, builds up as you use the app
    ├── tiles/                   downloaded .nc files, one per 1° square
    └── points/                  extracted per-point parquet + metadata json
```

## Known limitations

- No evaporation, radiation, or vapour pressure data in AGCD — Climate
  by month shows rainfall and temperature only.
- Frozen at 2022-12-31 — not suitable for anything tactical/in-season,
  only long-run/climatological analysis.
- Grid-cell values are an interpolated analysis, not a point measurement
  — expect small, usually immaterial differences from SILO's own record
  at "the same" site, more so in sparsely-gauged country than in the
  well-gauged sheep-wheat zone.
- `.agcd_cache/` will grow as you explore more locations (~40 MB per new
  one-degree square visited). It's safe to delete anytime — everything
  in it is a rebuildable cache, not source data.

## Credits

Weather data: Bureau of Meteorology's Australian Gridded Climate Data
(AGCD v1.0.1), packaged and hosted as an independent archive by Ken
Brook (Aug 2026), alongside the Queensland Government's SILO database
(used here only for location search). Built from
[Weather Explorer](../weather-explorer).
