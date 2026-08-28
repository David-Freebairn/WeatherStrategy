"""
core/silo.py
============
SILO Patched Point API helpers used by all pages.

Uses PatchedPointDataset.php which returns the classic P51 format
with all variables in a single response — no WAF issues with this
endpoint when using format=csv without a comment parameter.

P51 response format:
    lat lon syn pan pre YY  SSSSSSTATION_NAME
    date    jday  tmax  tmin  rain  evap   rad   vp
    YYYYMMDD  DOY  ...
"""

import urllib.parse
import urllib.request
import io
import time
import pandas as pd
import numpy as np
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────────────
_PATCHEDPT = "https://www.longpaddock.qld.gov.au/cgi-bin/silo/PatchedPointDataset.php"
_DATADRILL = "https://www.longpaddock.qld.gov.au/cgi-bin/silo/DataDrillDataset.php"
_EMAIL     = "david.freebairn@gmail.com"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/plain, text/csv, */*",
    "Referer": "https://www.longpaddock.qld.gov.au/silo/",
}


# ── Station search ───────────────────────────────────────────────────────────

def search_stations(query: str) -> list:
    """Search SILO for stations matching a name fragment."""
    url = (f"{_PATCHEDPT}?format=name"
           f"&nameFrag={urllib.parse.quote(query.strip())}"
           f"&username={urllib.parse.quote(_EMAIL)}")
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"SILO station search failed: {exc}") from exc

    stations = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue
        try:
            sid   = int(parts[0])
            name  = parts[1].strip()
            lat   = float(parts[2]) if len(parts) > 2 and parts[2] else None
            lon   = float(parts[3]) if len(parts) > 3 and parts[3] else None
            state = parts[4].strip() if len(parts) > 4 else ""
            label = name
            if state:
                label += f"  [{state}]"
            if lat is not None and lon is not None:
                label += f"  ({lat:.3f}, {lon:.3f})"
            stations.append({"id": sid, "name": name, "label": label,
                              "lat": lat, "lon": lon, "state": state})
        except (ValueError, IndexError):
            continue
    return stations


def fetch_nearby_stations(station_id: int, radius_km: int = 50) -> list:
    """
    Stations within `radius_km` of `station_id`, via SILO's format=near.
    No username/password required. Returns list of dicts including
    distance_km, sorted by distance (as SILO returns them); the queried
    station itself is included at distance 0.0.
    """
    url = (f"{_PATCHEDPT}?format=near&station={station_id}&radius={radius_km}")
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"SILO nearby-station search failed: {exc}") from exc

    stations = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6:
            continue
        try:
            sid   = int(parts[0])
            name  = parts[1].strip()
            lat   = float(parts[2])
            lon   = float(parts[3])
            state = parts[4].strip()
            elev  = float(parts[5]) if parts[5] else None
            dist  = float(parts[6]) if len(parts) > 6 and parts[6] else None
            stations.append({"id": sid, "name": name, "lat": lat, "lon": lon,
                              "state": state, "elevation": elev, "distance_km": dist})
        except (ValueError, IndexError):
            continue
    return stations


# ── Core fetch ───────────────────────────────────────────────────────────────

def fetch_station_met(station_id: int, start: str, end: str,
                      lat: float = None, lon: float = None) -> pd.DataFrame:
    """
    Fetch SILO climate data for a station.

    Tries PatchedPointDataset.php first (returns classic P51 format with
    all variables including evap in one response).
    Falls back to DataDrillDataset.php using lat/lon if patched-point
    is blocked or returns no data.
    """
    # Try patched-point first
    try:
        raw = _fetch_patched_point(station_id, start, end)
        df  = _parse_p51(raw, station_id)
        if len(df) > 0 and df["rain"].sum() >= 0:
            return df
    except Exception:
        pass

    # Fall back to DataDrill (requires lat/lon)
    if lat is not None and lon is not None:
        return _fetch_datadrill(lat, lon, start, end, station_id)

    raise RuntimeError(
        f"Could not fetch climate data for station {station_id}. "
        "Both patched-point and DataDrill failed."
    )


def _fetch_patched_point(station_id: int, start: str, end: str) -> str:
    """
    Fetch from PatchedPointDataset.php — returns P51 format.
    Uses urllib.request (not requests library) to avoid WAF triggers.
    No comment= parameter needed — returns all variables by default.
    """
    params = urllib.parse.urlencode({
        "station":  station_id,
        "start":    start,
        "finish":   end,
        "format":   "csv",
        "username": _EMAIL,
        "password": "apirequest",
    })
    url = f"{_PATCHEDPT}?{params}"
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    if "<html" in raw.lower()[:200]:
        raise RuntimeError(f"WAF rejected patched-point request: {raw[:200]}")
    return raw


def _parse_p51(raw: str, station_id: int) -> pd.DataFrame:
    """
    Parse SILO P51 / patched-point CSV response.

    Handles two formats:
      Classic P51:
        -26.57 148.79 syn pan pre 70  43030ROMA POST OFFIC
          date    jday  tmax  tmin  rain  evap   rad   vp
         19000101    1  31.3  20.7   0.0   7.8  26.0  19.4

      New CSV (2025+):
        station,YYYY-MM-DD,daily_rain,daily_rain_source,metadata
        41023,2025-10-07,0.0,25,"name=..."
    """
    lines = raw.splitlines()

    # Find header row
    hi = None
    for i, ln in enumerate(lines):
        stripped = ln.strip().lower()
        if not stripped or stripped.startswith("#"):
            continue
        # Classic P51 header has 'date' and 'jday'
        if "date" in stripped and ("jday" in stripped or "tmax" in stripped):
            hi = i
            break
        # New CSV format
        if stripped.startswith("station,") or stripped.startswith("latitude,"):
            hi = i
            break

    if hi is None:
        raise RuntimeError(
            f"No header in SILO response for station {station_id}.\n"
            f"Preview: {raw[:400]}"
        )

    # Detect separator
    sep = "\t" if "\t" in lines[hi] else ","
    # P51 uses whitespace
    if sep == "," and "date" in lines[hi].lower() and "," not in lines[hi]:
        sep = None  # whitespace

    df_raw = pd.read_csv(
        io.StringIO("\n".join(lines[hi:])),
        sep=sep, skipinitialspace=True, dtype=str,
        engine="python" if sep is None else "c",
    )
    df_raw.columns = [c.strip().lower() for c in df_raw.columns]

    # Find date column
    date_col = next(
        (c for c in df_raw.columns
         if c in ("date", "yyyy-mm-dd", "yyyymmdd")),
        None,
    )
    if date_col is None:
        raise RuntimeError(
            f"No date column for station {station_id}. "
            f"Columns: {list(df_raw.columns)}"
        )

    date_raw = df_raw[date_col].astype(str).str.strip()
    # Try YYYYMMDD then YYYY-MM-DD
    dates = pd.to_datetime(date_raw, format="%Y%m%d", errors="coerce")
    mask  = dates.isna()
    if mask.any():
        dates[mask] = pd.to_datetime(date_raw[mask], format="%Y-%m-%d",
                                     errors="coerce")

    valid   = dates.notna()
    df_raw  = df_raw[valid].copy()
    dates   = dates[valid]

    out = pd.DataFrame(index=dates)
    out.index.name = "date"

    def _get(*candidates):
        for c in candidates:
            if c in df_raw.columns:
                return pd.to_numeric(df_raw[c], errors="coerce").values
        return np.full(len(df_raw), np.nan)

    # P51 uses 'evap', new format uses 'evap_pan'
    out["rain"]      = _get("rain", "daily_rain", "rainfall")
    out["tmax"]      = _get("tmax", "max_temp", "maximum_temperature")
    out["tmin"]      = _get("tmin", "min_temp", "minimum_temperature")
    out["epan"]      = _get("evap", "evap_pan", "epan", "evaporation", "pan_evap")
    out["radiation"] = _get("rad",  "radiation", "solar_radiation")
    out["vp"]        = _get("vp",   "vapour_pressure")

    out["tmean"] = (out["tmax"] + out["tmin"]) / 2.0
    out["year"]  = out.index.year
    out["month"] = out.index.month
    out["day"]   = out.index.day
    out["doy"]   = out.index.day_of_year

    out["rain"] = out["rain"].fillna(0.0).clip(lower=0.0)
    out["epan"] = out["epan"].fillna(0.0)

    # Remove duplicate dates (metadata rows in new format share dates)
    out = out[~out.index.duplicated(keep="last")]
    out = out.sort_index()

    # Fallback: estimate epan from radiation if missing
    if out["epan"].sum() < 1.0:
        try:
            rs    = out["radiation"].fillna(out["radiation"].median())
            tmean = out["tmean"].fillna(20.0)
            out["epan"] = (rs * 0.50 + tmean * 0.06).clip(lower=0.5)
        except Exception:
            out["epan"] = 5.0

    if len(out) == 0:
        raise RuntimeError(
            f"No valid rows parsed from SILO for station {station_id}."
        )

    return out


def _fetch_datadrill(lat: float, lon: float, start: str, end: str,
                     station_id: int) -> pd.DataFrame:
    """
    Fallback: fetch from DataDrill using lat/lon.
    Makes one request per variable using urllib.request.
    """
    variables = [
        ("daily_rain", "rain"),
        ("max_temp",   "tmax"),
        ("min_temp",   "tmin"),
        ("evap_pan",   "epan"),
        ("radiation",  "radiation"),
    ]

    silo_col_names = {
        "rain":      ["daily_rain", "rain", "rainfall"],
        "tmax":      ["max_temp", "maximum_temperature", "tmax"],
        "tmin":      ["min_temp", "minimum_temperature", "tmin"],
        "epan":      ["evap_pan", "evap", "evaporation", "epan"],
        "radiation": ["radiation", "solar_radiation"],
    }

    def _one(var_code):
        base = urllib.parse.urlencode({
            "lat": lat, "lon": lon,
            "start": start, "finish": end,
            "format": "csv",
            "username": _EMAIL, "password": "apirequest",
        })
        url = f"{_DATADRILL}?{base}&comment={var_code}"
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        if "<html" in raw.lower()[:200]:
            raise RuntimeError(f"WAF rejected {var_code}")
        return raw

    def _parse_dd(raw, col_name):
        lines = raw.splitlines()
        hi = next(
            (i for i, ln in enumerate(lines)
             if ln.strip() and "," in ln and
                any(t in ln.lower() for t in ("date","yyyy","latitude","station"))),
            None,
        )
        if hi is None:
            raise RuntimeError(f"No header for {col_name}")
        df = pd.read_csv(io.StringIO("\n".join(lines[hi:])), dtype=str,
                         low_memory=False)
        df.columns = [c.strip().lower() for c in df.columns]
        date_col = next((c for c in df.columns
                         if c in ("date","yyyy-mm-dd","yyyymmdd") or
                            ("yyyy" in c and "source" not in c)), None)
        dates = pd.to_datetime(df[date_col].astype(str).str.strip(),
                               errors="coerce")
        # Find the specific variable column
        candidates = silo_col_names.get(col_name, [col_name])
        target = next((c for c in candidates if c in df.columns), None)
        if target is None:
            skip = {date_col,"latitude","longitude","station","metadata"}
            skip.update(c for c in df.columns if c.endswith("_source"))
            val_cols = [c for c in df.columns if c not in skip]
            target = val_cols[0] if val_cols else None
        if target is None:
            raise RuntimeError(f"No value column for {col_name}")
        values = pd.to_numeric(df[target], errors="coerce")
        s = pd.Series(values.values, index=dates, name=col_name)
        s = s[s.index.notna()]
        s = s[~s.index.duplicated(keep="last")]
        return s.sort_index()

    series = {}
    for var_code, col_name in variables:
        try:
            series[col_name] = _parse_dd(_one(var_code), col_name)
        except Exception:
            series[col_name] = None

    if series.get("rain") is None:
        raise RuntimeError(f"DataDrill: could not fetch rain for {station_id}")

    idx = series["rain"].index
    out = pd.DataFrame(index=idx)
    out.index.name = "date"
    for col in ["rain","tmax","tmin","epan","radiation"]:
        s = series.get(col)
        out[col] = s.reindex(idx).values if s is not None else np.nan

    out["tmean"] = (out["tmax"] + out["tmin"]) / 2.0
    out["year"]  = out.index.year
    out["month"] = out.index.month
    out["day"]   = out.index.day
    out["doy"]   = out.index.day_of_year
    out["rain"]  = out["rain"].fillna(0.0).clip(lower=0.0)
    out["epan"]  = out["epan"].fillna(0.0)

    if out["epan"].sum() < 1.0:
        try:
            rs    = out["radiation"].fillna(out["radiation"].median())
            tmean = out["tmean"].fillna(20.0)
            out["epan"] = (rs * 0.50 + tmean * 0.06).clip(lower=0.5)
        except Exception:
            out["epan"] = 5.0

    return out


# ── Convenience wrappers ─────────────────────────────────────────────────────

def fetch_station_rainfall(station_id: int, start: str, end: str,
                           lat: float = None, lon: float = None) -> pd.DataFrame:
    """Fetch daily rainfall only. Used by 1_Season.py."""
    df = fetch_station_met(station_id, start, end, lat=lat, lon=lon)
    return df[["rain", "year", "month", "day", "doy"]]


def fetch_patched_point(station_id: int, start: str, end: str,
                        variables: str = "R",
                        lat: float = None, lon: float = None) -> pd.DataFrame:
    """Full met fetch. Used by 2_Odds.py."""
    return fetch_station_met(station_id, start, end, lat=lat, lon=lon)


# ── Shared session-state + disk climate cache ────────────────────────────────

_FULL_START    = "19000101"  # Weather Explorer default duration: 1900 → current
_CACHE_DIR     = Path(__file__).resolve().parent.parent / ".silo_cache"
_CACHE_MAX_AGE = 24 * 3600   # seconds — re-download if file older than this


def _full_end() -> str:
    from datetime import date as _date
    return _date.today().strftime("%Y%m%d")


def _cache_path(station_id: int) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{station_id}.parquet"


def _cache_is_fresh(path: Path) -> bool:
    """True if the cache file exists and is less than 24 hours old."""
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < _CACHE_MAX_AGE


def _load_disk_cache(station_id: int) -> "pd.DataFrame | None":
    path = _cache_path(station_id)
    if not _cache_is_fresh(path):
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def _save_disk_cache(station_id: int, df: pd.DataFrame) -> None:
    try:
        path = _cache_path(station_id)
        df.to_parquet(path)
    except Exception:
        pass   # disk write failure is non-fatal


def ensure_climate_cached(station_id: int,
                           lat: float = None, lon: float = None,
                           session_state=None) -> pd.DataFrame:
    """
    Return full met DataFrame (1995 → today) for this station.

    Priority order:
      1. session_state  — instant (same browser session)
      2. disk cache     — ~0.1 s  (parquet file < 24 hours old)
      3. SILO download  — 15–25 s (writes to both disk and session_state)

    Raises SiloUnavailableError if SILO cannot be reached and no cache exists.
    Cache key is station_id only — all pages share the same data.
    """
    import streamlit as _st
    ss = session_state if session_state is not None else _st.session_state

    key = f"climate_{station_id}"

    # 1. Session state
    if ss.get("climate_key") == key and ss.get("climate_df") is not None:
        return ss["climate_df"]

    # 2. Disk cache
    df = _load_disk_cache(station_id)
    if df is not None:
        ss["climate_df"]  = df
        ss["climate_key"] = key
        return df

    # 3. Download from SILO
    try:
        df = fetch_station_met(station_id, _FULL_START, _full_end(), lat=lat, lon=lon)
    except Exception as exc:
        raise SiloUnavailableError(str(exc)) from exc

    _save_disk_cache(station_id, df)
    ss["climate_df"]  = df
    ss["climate_key"] = key
    return df


class SiloUnavailableError(RuntimeError):
    """Raised when SILO cannot be reached and no cache is available."""


def load_sample_data(session_state=None) -> tuple:
    """
    Load the bundled Dalby sample dataset.
    Returns (df, station_info) where station_info matches the standard dict format.
    Raises FileNotFoundError if sample_data/ files are missing from the repo.
    """
    import json as _json
    import streamlit as _st

    ss = session_state if session_state is not None else _st.session_state

    sample_dir  = Path(__file__).resolve().parent.parent / "sample_data"
    parquet_path = sample_dir / "dalby_sample.parquet"
    json_path    = sample_dir / "dalby_station.json"

    if not parquet_path.exists() or not json_path.exists():
        raise FileNotFoundError(
            "Sample data files not found in sample_data/. "
            "Run fetch_sample_data.py locally to generate them."
        )

    df = pd.read_parquet(parquet_path)
    meta = _json.loads(json_path.read_text())

    station_info = {
        "id":    meta["id"],
        "name":  meta["name"],
        "label": meta["label"],
        "lat":   meta["lat"],
        "lon":   meta["lon"],
        "state": meta.get("state", "QLD"),
    }

    ss["climate_df"]  = df
    ss["climate_key"] = f"climate_{meta['id']}"

    return df, station_info


def clear_stale_cache(max_age_days: int = 7) -> int:
    """
    Delete disk cache files older than max_age_days.
    Returns number of files deleted.
    Safe to call at app startup.
    """
    if not _CACHE_DIR.exists():
        return 0
    cutoff = time.time() - max_age_days * 86400
    deleted = 0
    for f in _CACHE_DIR.glob("*.parquet"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                deleted += 1
        except Exception:
            pass
    return deleted


def slice_climate(df: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    """
    Slice a full-record met DataFrame to [start, end] inclusive.
    start/end accept datetime.date, pd.Timestamp, or 'YYYYMMDD' string.
    Returns a copy.
    """
    lo = pd.Timestamp(start) if start is not None else df.index.min()
    hi = pd.Timestamp(end)   if end   is not None else df.index.max()
    return df.loc[lo:hi].copy()
