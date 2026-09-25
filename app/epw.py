"""Minimal, fast EPW reader — multi-variable edition.

Reads the LOCATION header and hourly columns for dry-bulb, dew-point,
relative humidity, global horizontal radiation and wind speed, in one
bulk read per file (~1.7 MB). Also derives building-science metrics:
heating/cooling degree days (base 18 degC), extreme-heat hours (>32 degC)
and frost hours (<0 degC).

One bulk read per file rather than buffered small reads — this matters
when /data lives on a network mount (Docker Desktop 9p shares).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

# 0-indexed EPW data columns we aggregate: name -> (index, min, max)
VARS: dict[str, tuple[int, float, float]] = {
    "temp":     (6,  -90.0, 60.0),
    "dewpoint": (7,  -90.0, 60.0),
    "rh":       (8,    0.0, 100.0),
    "glohorz":  (13,   0.0, 1600.0),   # sentinel 999999 excluded by range
    "wind":     (21,   0.0,  45.0),
}
VAR_UNITS: dict[str, str] = {
    "temp": "°C", "dewpoint": "°C", "rh": "%", "glohorz": "W/m²", "wind": "m/s",
}


@dataclass(slots=True)
class EpwSummary:
    """Per-file climate summary: everything the UI needs in one payload."""

    site_id: int
    label: str
    color: str
    city: str
    lat: float
    lon: float
    elev_m: float | None
    # legacy convenience fields (dry-bulb)
    mean_db: float
    tmax_db: float
    tmin_db: float
    monthly_db: list[float]
    # multi-variable aggregates
    means: dict[str, float]              # variable -> annual mean
    monthly: dict[str, list[float]]      # variable -> 12 monthly means
    hdd18: float                         # heating degree days, base 18 degC
    cdd18: float                         # cooling degree days, base 18 degC
    # (degree days = hourly deviation sum / 24)
    hot_hours_32: int                    # hours with dry-bulb > 32 degC
    frost_hours_0: int                   # hours with dry-bulb < 0 degC


def read_location_header(path: Path) -> dict:
    """Parse the LOCATION line: city,province,region,country,lat,lon,TZ,elev."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        first = fh.readline().strip()
    parts = next(csv.reader([first]))
    def _num(value: str) -> float | None:
        try:
            return float(value)
        except ValueError:
            return None
    return {
        "city": parts[1] if len(parts) > 1 else "-",
        "lat": _num(parts[6]) if len(parts) > 6 else None,
        "lon": _num(parts[7]) if len(parts) > 7 else None,
        "elev_m": _num(parts[9]) if len(parts) > 9 else None,
    }


def _parse_location_row(row: list[str]) -> dict:
    def _num(value: str) -> float | None:
        try:
            return float(value)
        except ValueError:
            return None
    return {
        "city": row[1] if len(row) > 1 else "-",
        "lat": _num(row[6]) if len(row) > 6 else None,
        "lon": _num(row[7]) if len(row) > 7 else None,
        "elev_m": _num(row[9]) if len(row) > 9 else None,
    }


def summarize_epw(path: Path, site_id: int, label: str, color: str) -> EpwSummary:
    """Single bulk read; aggregates every variable in VARS + degree-day metrics."""
    loc_vals = {"city": None, "lat": None, "lon": None, "elev_m": None}
    sums = {k: [0.0] * 12 for k in VARS}
    cnts = {k: [0] * 12 for k in VARS}
    totals = {k: 0.0 for k in VARS}
    counts = {k: 0 for k in VARS}
    tmax, tmin = float("-inf"), float("inf")
    hdd = cdd = 0.0
    hot32 = frost0 = 0
    temp_idx, tlo, thi = VARS["temp"]

    text = path.read_bytes().decode("latin-1", errors="replace")
    lines = text.splitlines()
    if not lines:
        raise ValueError(f"empty file {path.name}")

    for row_idx, line in enumerate(lines):
        if row_idx == 0:
            loc = _parse_location_row(next(csv.reader([line])))
            loc_vals.update(loc)
            continue
        if row_idx < 8:
            continue
        parts = line.split(",")
        if len(parts) <= VARS["wind"][0]:
            continue
        try:
            month = int(parts[1])
        except ValueError:
            continue
        if not 1 <= month <= 12:
            continue
        mi = month - 1
        for key, (idx, lo, hi) in VARS.items():
            try:
                v = float(parts[idx])
            except ValueError:
                continue
            if not lo <= v <= hi:
                continue
            sums[key][mi] += v
            cnts[key][mi] += 1
            totals[key] += v
            counts[key] += 1
            if key == "temp":
                if v > tmax:
                    tmax = v
                if v < tmin:
                    tmin = v
                hdd += max(0.0, 18.0 - v)
                cdd += max(0.0, v - 18.0)
                if v > 32.0:
                    hot32 += 1
                elif v < 0.0:
                    frost0 += 1

    if counts["temp"] == 0:
        raise ValueError(f"no valid dry-bulb rows in {path.name}")

    monthly = {
        key: [round(s / c, 1) if c else None for s, c in zip(sums[key], cnts[key])]
        for key in VARS
    }
    means = {key: round(totals[key] / counts[key], 2) for key in VARS if counts[key]}

    return EpwSummary(
        site_id=site_id, label=label, color=color,
        city=loc_vals["city"] or "-",
        lat=loc_vals["lat"] if loc_vals["lat"] is not None else 0.0,
        lon=loc_vals["lon"] if loc_vals["lon"] is not None else 0.0,
        elev_m=loc_vals["elev_m"],
        mean_db=means.get("temp", 0.0),
        tmax_db=round(tmax, 1) if tmax != float("-inf") else None,
        tmin_db=round(tmin, 1) if tmin != float("inf") else None,
        monthly_db=monthly["temp"],
        means=means,
        monthly=monthly,
        hdd18=round(hdd / 24, 0),
        cdd18=round(cdd / 24, 0),
        hot_hours_32=hot32,
        frost_hours_0=frost0,
    )
