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
   time, as one all-years fit (with a "whole period" row summarising it,
   above the four-period breakdown table), as four separate historical
   eras, and as an anomaly chart (departure from each variable's own
   mean — never median — shown for rainfall and temperature together,
   regardless of which variable the dropdown above it is set to).
   Rainfall anomaly bars are blue above the mean / brown below;
   temperature anomaly bars are red above / light blue below — a
   deliberately different palette per variable, not shared.

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

**Tile delivery mechanics:** tiles live in a Google Drive folder — currently
David's own copy (`_FOLDER_ID` in `core/agcd.py`; Ken remains the underlying
owner), shared "Anyone with the link". `core/agcd.py` calls the Drive API's
`files.list` to find a tile's file id by name, then streams it down from
`files/{id}?alt=media` — ported directly from Ken's own `agcd_point.py`.
If this ever needs to point at a different copy of the archive, that's the
one line to change — see "Testing/swapping the tile folder" below.

**About the API key:** the app ships with Ken's own key (`_API_KEY` near
the top of `core/agcd.py`). It's a read-only credential against files
that are already public — not a password to his account — so it's fine
to use as-is short term. Two reasons to eventually swap in your own
(neither urgent): Google rate-limits per key, so you'd otherwise share
his allowance; and it's simply tidier for requests to be yours if this
becomes a regular tool or gets passed to clients. To do that: generate a
free key at console.cloud.google.com (enable the Google Drive API, no
billing needed — a ten-minute job, no OAuth consent screen, just
generate-and-copy), then replace the `_API_KEY` string. `_FOLDER_ID` is
independent of the key — it can stay as-is.

**Testing/swapping the tile folder:** the API-key method can only see a
folder shared as **"Anyone with the link"** — a folder shared only to a
specific Google account (the default when someone shares a folder "with
you") returns `200` with an *empty* file list, not an error, which looks
like nothing's wrong until you check closely. To verify a folder id
before pointing `_FOLDER_ID` at it:

```bash
python3 - << 'PYEOF'
import requests
FOLDER_ID = "paste-the-folder-id-here"
API_KEY = "AIzaSyAV_AcHCVnyUf5rAXehiCA7EfGkiSK-L_A"
r = requests.get(
    "https://www.googleapis.com/drive/v3/files",
    params={"q": f"'{FOLDER_ID}' in parents and trashed = false",
            "fields": "files(id,name,size)", "pageSize": 10, "key": API_KEY},
    timeout=30)
print(r.status_code, r.text[:1500])
PYEOF
```

A working folder returns real `agcd_v101_daily_S##E###.nc` filenames.
An empty `files: []` at `200` means fix the folder's sharing setting
(folder → Share → General access → "Anyone with the link") and re-run.

**Renamed tiles (e.g. "Copy of agcd_v101_daily_S28E151.nc"):** copying
files in Drive (its own "Make a copy" action, or some copy workflows)
prepends "Copy of " to the filename. `_find_file_id()` in `core/agcd.py`
handles this automatically — it tries an exact filename match first,
and only if that finds nothing falls back to a substring match, so a
renamed tile still resolves without needing to know the exact prefix in
advance. Locally cached tiles are always saved under their clean
canonical name regardless of what Drive calls them, so this is invisible
everywhere else in the app.

## Troubleshooting

**Local and deployed (or two deployed) environments give slightly
different percentages on "What chance?"** for the same station/query —
almost never a rounding issue (each disagreeing *year* moves the overall
percentage by roughly `100/n_years`, e.g. ~0.8 points with 123 years of
record, so a few points' gap means several years are genuinely
classified differently). Usual cause: the two environments have cached
different vintages of the same tile — `.agcd_cache/` is deliberately
never invalidated (the archive is supposed to be frozen), so if
`_FOLDER_ID` changed at some point, an environment that cached a tile
*before* the change keeps using it silently, with no error. Fixes, in
order:
1. Clear the cache and re-fetch: `rm -rf .agcd_cache/tiles/*.nc
   .agcd_cache/points/*.parquet .agcd_cache/points/*.json`, then re-run
   and re-select the station.
2. On Streamlit Cloud specifically, a `git push` alone doesn't clear a
   running container's disk — use **⋮ menu → Reboot app** to force it.
3. To find exactly which years disagree rather than just the headline
   percentage: open "What chance?"'s **"Year-by-year detail"** expander
   and download the CSV from each environment, then diff the "Met
   criteria" column between them — this pinpoints the specific years
   (and via the daily data, the specific rain events) actually in
   question, which is far more precise than comparing two percentages.

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

**"Data fetch failed: No module named 'h5py', backend not available"**
(typically on Streamlit Community Cloud) — `h5netcdf` depends on `h5py`,
which should install automatically as a dependency but occasionally
doesn't get picked up cleanly by Streamlit Cloud's build. `requirements.txt`
now lists `h5py` explicitly as its own line to force it. If you still hit
this after that change is deployed: on Streamlit Cloud, editing
`requirements.txt` alone doesn't always trigger a full environment
rebuild — use the app's "⋮" menu → **Reboot app**, or delete and
redeploy the app, to force it to reinstall from a clean environment.

**A map shows a diagonal "API KEY REQUIRED" watermark** — that's the tile
provider's own overlay, not an app bug. Carto retired free/anonymous
access to its "positron"/"dark_matter" basemap styles; `home.py` now uses
Esri's free, key-free light-gray canvas basemap instead (`_MAP_TILES` /
`_MAP_ATTR` near the top of the file). If a tile provider ever does this
again, that's the one place to swap it.

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

## UI notes

- **Maps are locked against accidental rescaling.** Scroll-wheel, pinch,
  double-click/double-tap, and drag-box zoom are all disabled on both
  the location-search map and the reliability map — these were the
  gestures making the maps feel unstable on touch screens (a stray
  two-finger touch or scroll being read as a zoom). Panning and the
  deliberate +/− zoom buttons still work. See `_MAP_LOCK` in `home.py`.
- **Charts are locked against rescaling too.** Both Plotly charts
  ("What chance?" and "Climate by month") have `dragmode=False` and
  `fixedrange=True` on every axis, with scroll-zoom and the zoom modebar
  turned off in `st.plotly_chart`'s `config`. Hover tooltips still work;
  drag-to-zoom and pinch-zoom don't. The Trend page's charts are static
  matplotlib images, so they were never zoomable in the first place.
- **"Change station" is a one-click reset**, not a plain link. A page
  link alone would take you to Menu with the *previous* station still
  shown as confirmed, needing a second click there to actually change
  it. `core/styles.py`'s `change_station_button()` clears the current
  selection first, then switches to Menu, landing straight on the
  search box.

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
