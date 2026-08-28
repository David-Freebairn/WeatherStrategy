# WeatherStrat

A test bed: the same three "big picture" strategic analyses as
[Weather Explorer](../weather-explorer)'s History section, but reading
daily rainfall/temperature from the **AGCD tile archive** instead of the
live **SILO** API, to see whether an independent, Commonwealth-hosted
dataset is a workable fallback data source.

## Analyses

1. **What chance?** — rainfall frequency analysis
2. **Climate by month** — long-term monthly rainfall/temperature averages
3. **Trend vs variability** — annual rainfall/temperature trend over time

These pages are unchanged from Weather Explorer beyond the data-source
import (`core/agcd` instead of `core/silo`) — see each page's docstring.

## What's different from Weather Explorer, and why

| | SILO (Weather Explorer) | AGCD (WeatherStrat) |
|---|---|---|
| Coverage | 1889 → today, updates daily | 1900–2022 only, frozen |
| Temperature from | 1889 | 1910 |
| Evaporation | Yes (pan evap) | **No** — dropped from Climate by month |
| Location | Named station | 1-degree-tiled 5 km grid cell |
| Access | Live API call | ~40 MB tile, downloaded once per 1° square, then cached forever |

Location picking still goes through SILO's station search (`core/silo.py`)
— that's just a name → lat/lon lookup and the reliability-map context, not
a live data fetch. The actual daily met record for all three pages comes
from `core/agcd.py`.

## Data source module: `core/agcd.py`

Mirrors `core/silo.py`'s interface (`ensure_climate_cached`,
`slice_climate`, `load_sample_data`) so the three pages needed no logic
changes — only the import line. See its docstring for the caching
architecture (session state → disk parquet per point → tile download).

**Wired up and working:** tiles come from Ken Brook's shared Google Drive
folder, via the Google Drive API (`files.list` to find a tile by name,
then a streamed download), ported from his own `agcd_point.py`. The app
currently ships with Ken's API key (it's read-only against these already-
public tiles — see `agcd_point_readme.txt`). Swap in your own free key
when convenient: generate one at console.cloud.google.com (Drive API
enabled, no billing needed — a ten-minute job, no OAuth consent screen),
then replace the `_API_KEY` string near the top of `core/agcd.py`. Nothing
else needs to change.

## Background material

The AGCD briefing, technical reference, "how it was built" note, and
Ken's worked example/extractor scripts aren't included in this repo (kept
alongside the tiles themselves) — see David's copies if you need to
revisit the archive's design decisions (the analysis-weight
interpretation, tile naming scheme, the Google Drive delivery model, etc.).

## Run locally

```
pip install -r requirements.txt
streamlit run Menu.py
```
