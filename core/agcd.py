"""
core/agcd.py
============
AGCD (Australian Gridded Climate Data) tile-archive backend for WeatherStrat.

This is the swap-in replacement for core/silo.py's climate-fetch interface,
sourcing daily rainfall/tmax/tmin from Ken Brook's AGCD v1-0-1 tile archive
(Aug 2026 briefing) instead of the live SILO API. WeatherStrat's three pages
(What chance?, Climate by month, Trend vs variability) call this module
exactly the way they'd call core/silo.py — same function names, same
argument order, same DataFrame shape — so this is the only file a page
needs a different import line for.

Key differences from SILO, baked into this module so the pages don't have
to know about them:
  - Coverage is 1900-01-01 to 2022-12-31 only (frozen archive, no updates).
    Rainfall from 1900, temperature from 1910 (blank/NaN before that).
  - No evaporation, radiation or vapour pressure — rain/tmax/tmin/tmean only.
  - Location is a lat/lon grid cell, not a named station. WeatherStrat's
    home.py still uses SILO's station search purely for name -> lat/lon
    lookup and the reliability map; only the daily met record itself comes
    from here.

Architecture — delivery via shared Google Drive (Ken Brook, Aug 2026)
-----------------------------------------------------------------------
The archive is 869 one-degree netCDF4 tiles (~38 GB total, ~40 MB each),
one per integer-degree square of Australian land, sitting in a Google
Drive folder (see agcd_point_readme.txt / AGCD_how_it_was_built.docx
section 8 for the reasoning — this is the "home-scale" alternative to a
proper object store + API). _FOLDER_ID below points at David's own copy
of that folder (Ken remains the underlying owner) — set to "Anyone with
the link" access, since the API-key method below can't see a folder
shared only to a specific account. Ported here from Ken's own
agcd_point.py:

    1. session_state   — instant, same browser session
    2. disk parquet    — one small file per point already extracted
    3. Drive download  — ~40 MB the first time a *new* one-degree square
                          is visited: files.list (by tile filename) to find
                          the file id, then files/{id}?alt=media to stream
                          it down; every other point in that square (any
                          farm within ~100 km) then costs nothing
    4. (nothing further) — the archive is frozen, so unlike SILO's 24h
                          cache, nothing here ever needs re-fetching once
                          it's on disk.

The API key below is Ken's own (from agcd_point_readme.txt) — it only
reads these already-public tiles, not his account, so it's fine to ship
short-term. Per his readme, swap in your own free key (10-minute Google
Cloud Console setup, no billing) once you have a spare moment, both so you
aren't sharing his rate limit and so requests are properly yours if this
becomes a regular tool. Nothing else in this file needs to change to do
that — just replace the string below.
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd

# ── Config — Google Drive delivery (see agcd_point_readme.txt) ──────────────
_FOLDER_ID = "1l9ptW0KHxCeniJ2iOiSe3wcGjLafxgAb"   # AGCD tile folder currently in use
_API_KEY   = "AIzaSyAV_AcHCVnyUf5rAXehiCA7EfGkiSK-L_A"  # Ken's key — swap in your own when convenient (see readme)

_ARCHIVE_START = "19000101"
_ARCHIVE_END   = "20221231"    # archive is frozen — never advances

_CACHE_DIR      = Path(__file__).resolve().parent.parent / ".agcd_cache"
_TILE_DIR       = _CACHE_DIR / "tiles"
_POINT_DIR      = _CACHE_DIR / "points"

_OFFSHORE_WEIGHT = 1.0   # AGCD's precip_weight reads <1 essentially only over ocean
_FAR_WARNING_KM  = 8.0   # matches the extractor's own coordinate-typo tripwire


class AgcdUnavailableError(RuntimeError):
    """Raised when a tile can't be obtained: no network/Drive access and
    nothing cached yet, or the point isn't covered by the archive (over
    ocean, outside Australia)."""


# ── Tile addressing ──────────────────────────────────────────────────────────

def tile_id(lat: float, lon: float) -> str:
    """1-degree tile name for a point, e.g. (-27.18, 151.27) -> 'S28E151'."""
    la, lo = math.floor(lat), math.floor(lon)
    return f"{'S' if la < 0 else 'N'}{abs(la):02d}E{lo:03d}"


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ── Google Drive lookup + download (ported from Ken's agcd_point.py) ────────

def _drive_query(q: str) -> list:
    import requests

    r = requests.get(
        "https://www.googleapis.com/drive/v3/files",
        params={"q": q, "fields": "files(id,name)", "key": _API_KEY},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("files", [])


def _find_file_id(name: str) -> "str | None":
    """
    Look up a tile's Google Drive file id by filename, within the shared
    tile folder (_FOLDER_ID). Tries an exact match first (the normal
    case: agcd_v101_daily_S28E151.nc); if that finds nothing, falls back
    to a substring match, since some copies of the archive pick up a
    renamed filename along the way — e.g. Drive's own "Make a copy"
    action prepends "Copy of " to every file. This keeps any folder
    working without needing to know its exact naming quirk in advance.
    If several files match the substring (e.g. a folder with more than
    one stray copy of the same tile), the first result is used.
    """
    exact = _drive_query(f"'{_FOLDER_ID}' in parents and name = '{name}' and trashed = false")
    if exact:
        return exact[0]["id"]

    fuzzy = _drive_query(f"'{_FOLDER_ID}' in parents and name contains '{name}' and trashed = false")
    return fuzzy[0]["id"] if fuzzy else None


def _download_tile(name: str, dest: Path) -> None:
    """Stream a tile down from Drive by its file id, writing to a .part
    file first so a crash mid-download can never leave a corrupt tile
    sitting under its real name."""
    import requests

    fid = _find_file_id(name)
    if not fid:
        raise AgcdUnavailableError(
            f"No tile {name} in the AGCD archive — the point is over ocean, "
            f"outside Australia, or the coordinates are mistyped "
            f"(latitude negative -10 to -44; longitude positive 112 to 154)."
        )
    url = f"https://www.googleapis.com/drive/v3/files/{fid}"
    tmp = dest.with_suffix(".part")
    try:
        with requests.get(url, params={"alt": "media", "key": _API_KEY},
                           stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        tmp.rename(dest)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise AgcdUnavailableError(f"Could not download AGCD tile {name}: {exc}") from exc


def _ensure_tile_cached(tid: str) -> Path:
    """Download a tile once, then reuse the cached copy forever (frozen archive)."""
    _TILE_DIR.mkdir(parents=True, exist_ok=True)
    name = f"agcd_v101_daily_{tid}.nc"
    path = _TILE_DIR / name
    if path.exists():
        return path
    _download_tile(name, path)
    return path


# ── Point extraction ──────────────────────────────────────────────────────────

def _tile_fingerprint(path: Path) -> tuple:
    """(size in bytes, short sha256) of a tile file on disk — lets two
    environments confirm whether they're actually looking at the same
    physical file when a filename/coordinate match isn't enough proof."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return path.stat().st_size, h.hexdigest()[:16]


def _extract_point(lat: float, lon: float) -> pd.DataFrame:
    """
    Pull one grid cell's full daily record (1900-2022) out of its tile.
    Returns a date-indexed DataFrame matching core/silo.py's shape:
    rain, tmax, tmin, tmean, year, month, day, doy.
    """
    import xarray as xr  # imported lazily — only needed on this code path

    tid = tile_id(lat, lon)
    path = _ensure_tile_cached(tid)
    tile_size, tile_hash = _tile_fingerprint(path)

    with xr.open_dataset(path) as ds:
        pt = ds.sel(lat=lat, lon=lon, method="nearest").load()
        px_lat, px_lon = float(pt["lat"]), float(pt["lon"])
        weight_mean = float(pt["precip_weight"].mean()) if "precip_weight" in pt else None

    dist_km = _haversine_km(lat, lon, px_lat, px_lon)

    df = pd.DataFrame(
        {
            "rain": pt["precip"].values.astype(float),
            "tmax": pt["tmax"].values.astype(float),
            "tmin": pt["tmin"].values.astype(float),
        },
        index=pd.to_datetime(pt["time"].values),
    )
    df.index.name = "date"
    df["tmean"] = (df["tmax"] + df["tmin"]) / 2.0
    df["year"]  = df.index.year
    df["month"] = df.index.month
    df["day"]   = df.index.day
    df["doy"]   = df.index.dayofyear
    df["rain"]  = df["rain"].fillna(0.0).clip(lower=0.0)

    df.attrs["source"]        = "AGCD v1-0-1"
    df.attrs["tile_id"]       = tid
    df.attrs["tile_size"]     = tile_size
    df.attrs["tile_sha256_16"] = tile_hash
    df.attrs["pixel_centre"]  = (px_lat, px_lon)
    df.attrs["distance_km"]   = dist_km
    df.attrs["mean_weight"]   = weight_mean
    if weight_mean is not None and weight_mean < _OFFSHORE_WEIGHT:
        df.attrs["offshore_warning"] = (
            f"Analysis weight ({weight_mean:.2f}) suggests this point is "
            f"over water, not land — check the coordinates."
        )
    if dist_km > _FAR_WARNING_KM:
        df.attrs["distance_warning"] = (
            f"Requested point resolved to a grid cell {dist_km:.1f} km away "
            f"— check the coordinates."
        )
    return df


def _point_cache_path(lat: float, lon: float) -> Path:
    _POINT_DIR.mkdir(parents=True, exist_ok=True)
    return _POINT_DIR / f"{lat:.3f}_{lon:.3f}.parquet"


def _point_meta_path(lat: float, lon: float) -> Path:
    """
    Sidecar JSON next to the parquet cache, holding the grid-cell metadata
    (tile id, pixel centre, distance from the requested point, gauge
    weight). Needed because pandas' DataFrame.attrs isn't preserved by
    to_parquet/read_parquet, so a disk-cache hit would otherwise come back
    with none of this — only a freshly-extracted DataFrame would.
    """
    _POINT_DIR.mkdir(parents=True, exist_ok=True)
    return _POINT_DIR / f"{lat:.3f}_{lon:.3f}.json"


def _save_point_meta(lat: float, lon: float, df: pd.DataFrame) -> None:
    import json
    meta = {k: v for k, v in df.attrs.items()}
    try:
        _point_meta_path(lat, lon).write_text(json.dumps(meta))
    except Exception:
        pass  # metadata is a nice-to-have; never let it break the fetch


def _load_point_meta(lat: float, lon: float) -> dict:
    import json
    mpath = _point_meta_path(lat, lon)
    if not mpath.exists():
        return {}
    try:
        return json.loads(mpath.read_text())
    except Exception:
        return {}


def describe_grid_cell(df: pd.DataFrame) -> "str | None":
    """
    One-line, page-ready caption describing which AGCD grid cell a
    fetched record actually came from, and how far it sits from the
    site that was searched for — e.g.:
    "AGCD grid cell -27.200, 151.250 (tile S28E151) — 3.0 km from the
    selected site."
    Returns None if the distance isn't known (e.g. a very old disk
    cache written before this metadata existed).
    """
    dist = df.attrs.get("distance_km")
    centre = df.attrs.get("pixel_centre")
    tile = df.attrs.get("tile_id")
    if dist is None or centre is None:
        return None
    return (
        f"AGCD grid cell {centre[0]:.3f}, {centre[1]:.3f} (tile {tile}) "
        f"\u2014 {dist:.1f} km from the selected site (nearest 0.05\u00b0 "
        f"grid centre, not interpolated)."
    )


def grid_cell_warning(df: pd.DataFrame) -> "str | None":
    """Either of the two sanity-check warnings computed at extraction
    time (far-away match / likely-offshore match), if either fired."""
    return df.attrs.get("distance_warning") or df.attrs.get("offshore_warning")


def describe_tile_fingerprint(df: pd.DataFrame) -> "str | None":
    """
    One-line summary of exactly which physical tile file backs this
    record — its byte size and a short sha256 — so two environments
    (e.g. local vs a Streamlit Cloud deployment) that both claim to be
    reading "the same tile" can be compared directly by a single string,
    rather than by re-deriving and comparing hundreds of rows of output.
    A mismatch here means the two environments are NOT reading the same
    file, whatever their filenames or folder configs suggest — most
    likely a stale local/deployed cache, or a genuinely different file
    at the source. Returns None if this came from a disk cache written
    before this field existed (no fingerprint recorded).
    """
    size = df.attrs.get("tile_size")
    h = df.attrs.get("tile_sha256_16")
    if size is None or h is None:
        return None
    return f"Tile file: {size:,} bytes, sha256 {h}\u2026"


# ── Shared session-state + disk cache (mirrors core/silo.py) ────────────────

def ensure_climate_cached(station_id, lat: float = None, lon: float = None,
                           session_state=None) -> pd.DataFrame:
    """
    Return the full AGCD daily record (1900-2022) for the point nearest
    (lat, lon). `station_id` is accepted (and ignored, beyond cache-key
    disambiguation) purely so this drops into pages written against
    core/silo.py's ensure_climate_cached(station_id, lat, lon, ...)
    without any call-site changes.

    Priority order:
      1. session_state — instant (same browser session)
      2. disk cache     — ~0.1 s (parquet file for this exact point)
      3. tile download  — a few seconds if the tile is already cached,
                           ~10-30 s the first time that one-degree square
                           is visited at all

    The returned DataFrame's .attrs carries grid-cell metadata (tile id,
    pixel centre, distance from the requested point) — see
    describe_grid_cell() / grid_cell_warning() to surface it in the UI.

    Raises AgcdUnavailableError if the tile can't be obtained.
    """
    import streamlit as _st
    ss = session_state if session_state is not None else _st.session_state

    if lat is None or lon is None:
        raise AgcdUnavailableError(
            "AGCD needs a lat/lon for this location — station metadata "
            "without coordinates isn't enough."
        )

    key = f"agcd_{lat:.3f}_{lon:.3f}"

    # 1. Session state
    if ss.get("climate_key") == key and ss.get("climate_df") is not None:
        return ss["climate_df"]

    # 2. Disk cache
    cpath = _point_cache_path(lat, lon)
    if cpath.exists():
        try:
            df = pd.read_parquet(cpath)
            df.attrs.update(_load_point_meta(lat, lon))
            ss["climate_df"], ss["climate_key"] = df, key
            return df
        except Exception:
            pass  # fall through and re-extract a corrupt cache file

    # 3. Extract from tile (downloading it first if needed)
    df = _extract_point(lat, lon)
    try:
        df.to_parquet(cpath)
    except Exception:
        pass  # disk write failure is non-fatal, same as core/silo.py
    _save_point_meta(lat, lon, df)

    ss["climate_df"], ss["climate_key"] = df, key
    return df


def slice_climate(df: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    """Slice a full-record met DataFrame to [start, end] inclusive."""
    lo = pd.Timestamp(start) if start is not None else df.index.min()
    hi = pd.Timestamp(end)   if end   is not None else df.index.max()
    return df.loc[lo:hi].copy()


def load_sample_data(session_state=None):
    """
    No bundled AGCD sample dataset (yet). Kept as a function — rather than
    omitted — so pages ported from Weather Explorer, which offer a
    "use sample data" fallback button when the live source is unreachable,
    keep working: they'll just get a clear message instead of a crash.
    """
    raise FileNotFoundError(
        "No bundled AGCD sample dataset yet — try again once the tile "
        "archive is reachable, or ask Ken for a small sample tile."
    )


def clear_stale_cache(*_args, **_kwargs) -> int:
    """
    No-op, kept for interface parity with core/silo.py. AGCD's cache never
    goes stale (the archive is frozen), so there's nothing to clear.
    """
    return 0
