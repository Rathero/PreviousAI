"""CDS NetCDF -> indicators per grid cell (the "baseline").

Second step of the slow layer. It turns what `cds_download.py` downloaded into a small
JSON that the API queries in microseconds.

    python backend/scripts/cds_build_baseline.py
    python backend/scripts/cds_build_baseline.py --name valencia --glob "valencia_*.nc"

ERA5 details handled here:
  - temperature comes in KELVIN
  - total precipitation comes in METRES (not mm)
  - the time axis is called `valid_time` in new deliveries and `time` in old ones
  - sometimes the CDS delivers a .zip with the .nc inside
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402

try:
    import numpy as np
    import xarray as xr
except ImportError:  # pragma: no cover
    print("Batch dependencies are missing: pip install xarray netCDF4 numpy", file=sys.stderr)
    raise SystemExit(1)

TIME_DIMS = ("valid_time", "time", "date")
LAT_DIMS = ("latitude", "lat")
LON_DIMS = ("longitude", "lon")


def _pick(names, candidates):
    for c in candidates:
        if c in names:
            return c
    return None


def _unzip_if_needed(path: Path) -> Path:
    if not zipfile.is_zipfile(path):
        return path
    out_dir = path.with_suffix("")
    out_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(path) as zf:
        members = [m for m in zf.namelist() if m.endswith(".nc")]
        if not members:
            raise ValueError(f"{path.name} is a zip with no .nc files inside")
        zf.extractall(out_dir)
    return out_dir / members[0]


def _normalise(da, name: str):
    """Returns (array in useful units, unit, kind)."""
    units = str(da.attrs.get("units", "")).lower()
    if units in ("k", "kelvin"):
        return da - 273.15, "C", "temperature"
    if units in ("m", "metres", "meters"):
        return da * 1000.0, "mm", "precipitation"
    if "m s**-1" in units or units in ("m/s", "m s-1"):
        return da * 3.6, "km/h", "wind"
    if units in ("mm",):
        return da, "mm", "precipitation"
    if units in ("degc", "c", "celsius"):
        return da, "C", "temperature"
    return da, units or "?", "unknown"


def statistic_from_name(path: Path) -> str | None:
    """Works out from the file name whether it holds maxima, minima or totals.

    A `daily_maximum` file is no use for a cold record: it would give the minimum of the
    maxima, which is another quantity, and the cross-check would compare different things.
    """
    stem = path.stem.lower()
    for needle, tag in (("daily_maximum", "maximum"), ("daily_minimum", "minimum"),
                        ("daily_sum", "sum"), ("daily_mean", "mean")):
        if needle in stem:
            return tag
    return None


def indicators_for(
    kind: str, values: "np.ndarray", years: "np.ndarray", statistic: str | None = None
) -> dict:
    """The same indicators the fast layer calculates, so they can be compared."""
    # Values and years are filtered TOGETHER: if only the values are filtered,
    # the years stop lining up and the annual indices (RX1day) come out wrong.
    if values.size:
        keep = ~np.isnan(values)
        values = values[keep]
        if years is not None and years.size == keep.size:
            years = years[keep]
    if values.size == 0:
        return {}

    if kind == "temperature":
        n = values.size
        # Only the indicators this series can support.
        if statistic == "minimum":
            return {
                "frost_days": float((values <= 0).sum()) / n * 365.25,
                "severe_frost_days": float((values <= -5).sum()) / n * 365.25,
                "tropical_nights": float((values >= 20).sum()) / n * 365.25,
                "cold_record": float(values.min()),
            }
        if statistic in ("maximum", None):
            out = {
                "hot_days_35": float((values >= 35).sum()) / n * 365.25,
                "hot_days_32": float((values >= 32).sum()) / n * 365.25,
                "hot_days_40": float((values >= 40).sum()) / n * 365.25,
                "heat_record": float(values.max()),
            }
            if statistic is None:
                # Unknown statistic: no cold indicators are invented.
                out["_warning"] = "statistic not identified in the file name"
            return out
        return {}
    if kind == "precipitation":
        n = values.size
        out = {
            "heavy_rain_days": float((values >= 50).sum()) / n * 365.25,
            "torrential_days": float((values >= 100).sum()) / n * 365.25,
            "precip_record": float(values.max()),
            "precip_p99": float(np.percentile(values, 99)),
            "annual_precip": float(values.mean()) * 365.25,
        }
        if years is not None and years.size == values.size:
            annual_maxima = [values[years == y].max() for y in np.unique(years)
                             if (years == y).sum() > 300]
            if annual_maxima:
                out["rx1day"] = float(np.mean(annual_maxima))
        return out
    if kind == "wind":
        n = values.size
        return {
            "gust_p99": float(np.percentile(values, 99)),
            "gust_record": float(values.max()),
            "gale_days": float((values >= 70).sum()) / n * 365.25,
        }
    return {}


def process(paths: list[Path], name: str) -> dict:
    """Reads all the NetCDF files and calculates the indicators ONCE at the end.

    The CDS forces splitting by years, so several files for the same point and variable
    arrive here, one per year. Their series are CONCATENATED before calculating anything;
    calculating per file and merging would let the last year overwrite the others.
    """
    # (lat, lon, kind) -> {"values": [...], "years": [...]}
    buckets: dict[tuple[float, float, str, str | None], dict[str, list]] = {}
    bbox = [-90.0, 180.0, 90.0, -180.0]  # N, W, S, E: widened as files are read
    periods, datasets = set(), set()

    for path in paths:
        real = _unzip_if_needed(path)
        statistic = statistic_from_name(path)
        print(f"  reading {real.name}  (statistic: {statistic or 'UNKNOWN'})")
        if statistic is None:
            print("    [warning] the name does not say whether these are maxima or "
                  "minima; maxima will be assumed. Rename the file with "
                  "daily_maximum/daily_minimum so the indicators are right.")
        with xr.open_dataset(real) as ds:
            tdim = _pick(ds.dims, TIME_DIMS) or _pick(ds.coords, TIME_DIMS)
            latdim = _pick(ds.dims, LAT_DIMS)
            londim = _pick(ds.dims, LON_DIMS)
            if not all((tdim, latdim, londim)):
                print(f"    [skipped] cannot find the axes (dims={tuple(ds.dims)})")
                continue

            times = ds[tdim].values
            years = times.astype("datetime64[Y]").astype(int) + 1970
            y0, y1 = int(years.min()), int(years.max())
            periods.add((y0, y1))
            datasets.add(path.stem)

            lats = ds[latdim].values
            lons = ds[londim].values
            bbox = [max(bbox[0], float(lats.max())), min(bbox[1], float(lons.min())),
                    min(bbox[2], float(lats.min())), max(bbox[3], float(lons.max()))]

            for var in ds.data_vars:
                da = ds[var]
                if tdim not in da.dims:
                    continue
                converted, unit, kind = _normalise(da, str(var))
                if kind == "unknown":
                    print(f"    [warning] {var}: units {unit!r} not recognised, skipped")
                    continue
                arr = converted.transpose(tdim, latdim, londim).values
                print(f"    {var} -> {kind} ({unit}), grid {arr.shape[1]}x{arr.shape[2]}"
                      f", {arr.shape[0]} days")
                for i, lat in enumerate(lats):
                    for j, lon in enumerate(lons):
                        key = (round(float(lat), 3), round(float(lon), 3), kind, statistic)
                        bucket = buckets.setdefault(key, {"values": [], "years": []})
                        bucket["values"].append(arr[:, i, j])
                        bucket["years"].append(years)

    # Now: concatenate each series and calculate the indicators just once.
    cells: dict[tuple[float, float], dict] = {}
    for (lat, lon, kind, statistic), bucket in buckets.items():
        values = np.concatenate(bucket["values"])
        yrs = np.concatenate(bucket["years"])
        order = np.argsort(yrs, kind="stable")
        cell = cells.setdefault((lat, lon), {"lat": lat, "lon": lon, "indicators": {}})
        cell["indicators"].update(
            indicators_for(kind, values[order], yrs[order], statistic))

    period = (f"{min(p[0] for p in periods)}-{max(p[1] for p in periods)}"
              if periods else "unknown")
    return {
        "name": name,
        "dataset": "derived-era5-single-levels-daily-statistics",
        "source": "ERA5 (Copernicus C3S) via Climate Data Store",
        "resolution": "0.25 degrees (~28 km)",
        "period": period,
        "bbox": [round(v, 3) for v in bbox],
        "files": sorted(datasets),
        "cells": sorted(cells.values(), key=lambda c: (-c["lat"], c["lon"])),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--glob", default="*.nc", help="pattern inside data/cds/")
    p.add_argument("--name", default="baseline", help="name of the resulting baseline")
    args = p.parse_args()

    paths = sorted(config.CDS_DIR.glob(args.glob))
    if not paths:
        print(f"No files match {args.glob!r} in {config.CDS_DIR}.")
        print("Run first:  python backend/scripts/cds_download.py --preset valencia")
        return 1

    print(f"Processing {len(paths)} file(s) from {config.CDS_DIR}")
    baseline = process(paths, args.name)
    if not baseline["cells"]:
        print("No cell could be extracted.", file=sys.stderr)
        return 1

    out = config.BASELINE_DIR / f"{args.name}.json"
    out.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    n_ind = len({k for c in baseline["cells"] for k in c["indicators"]})
    print()
    print(f"Wrote {out}")
    print(f"  {len(baseline['cells'])} cells, {n_ind} indicators, period {baseline['period']}")
    print(f"  bbox [N,W,S,E] = {baseline['bbox']}")
    print()
    print("Restart the API: the CDS <-> Open-Meteo cross-check now shows up in /api/risk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
