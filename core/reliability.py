"""
core/reliability.py
====================
Static SILO station reliability lookup, bundled as `data/silo_reliability.csv`
(station_id, name, lat, lon, state, elevation, total_days, observed_days,
pct_observed, first_date, last_date — ~7,950 stations).

`pct_observed` is the percentage of days with observed (non-interpolated)
rainfall data over the analysis window recorded in the CSV. This is a
static snapshot, not a live computation — getting a true reliability
figure requires downloading each station's full daily series and counting
source flags, which is far too slow to do per-marker on a map. Regenerate
the CSV and replace the bundled copy to refresh the numbers.
"""

from functools import lru_cache
from pathlib import Path

import pandas as pd

_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "silo_reliability.csv"


@lru_cache(maxsize=1)
def _load() -> "pd.DataFrame | None":
    try:
        df = pd.read_csv(_CSV_PATH)
        return df.set_index("station_id")
    except Exception:
        return None


def is_loaded() -> bool:
    """True if the bundled reliability CSV was found and parsed successfully."""
    return _load() is not None


def get_pct_observed(station_id: int) -> "float | None":
    """Return pct_observed (0-100) for a station, or None if not in the lookup."""
    df = _load()
    if df is None:
        return None
    try:
        return float(df.loc[int(station_id), "pct_observed"])
    except (KeyError, ValueError, TypeError):
        return None


def reliability_color(pct: "float | None") -> str:
    """Map pct_observed to a marker color."""
    if pct is None:
        return "#999999"   # unknown — grey
    if pct >= 90:
        return "#2e7d32"   # green — reliable
    if pct >= 50:
        return "#e8a33d"   # amber — patchy
    return "#c0392b"       # red — mostly gap-filled / no data


def reliability_label(pct: "float | None") -> str:
    if pct is None:
        return "no reliability data"
    return f"{pct:.0f}% observed"
