"""CDS slow layer for the wildfire projection.

A Climate Data Store dataset the fast layer cannot provide:

  - sis-tourism-fire-danger-indicators: days a year with a Fire Weather Index above 30
    (high danger) and above 45 (very high), EURO-CORDEX, multi-model mean, 1981-2005
    versus 2041-2060 under RCP4.5 and RCP8.5: Copernicus's fire danger projection.

    python backend/scripts/cds_hazards.py download        # queues and waits (hours)
    python backend/scripts/cds_hazards.py download --dry-run
    python backend/scripts/cds_hazards.py build           # NetCDF -> data/cds/*.json.gz

The output is queried locally from app/providers/cds_layers.py.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import tempfile
import time
import warnings
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from app import config  # noqa: E402
from app.providers import cds  # noqa: E402

RAW = config.CDS_DIR / "hazards"
FIRE_OUT = config.CDS_DIR / "fire_danger_projections.json.gz"

FIRE_RUNS = [("historical", "1981_2005"), ("rcp4_5", "2041_2060"), ("rcp8_5", "2041_2060")]
# Cropping of the European fire file when saving it: the mainland, the Balearic
# and the Canary Islands fit in this box (lat, lon).
FIRE_BOX = (27.0, 44.5, -18.5, 5.0)
# Variable name inside the NetCDF -> internal key. "High" is FWI > 30 and
# "very high" FWI > 45; they are exceedance thresholds, so the first includes
# the second.
FIRE_KEYS = {"fwi-nods-gt-30": "high", "fwi-nods-gt-45": "very_high"}


def jobs() -> list[tuple[str, dict, Path]]:
    out = []
    for exp, period in FIRE_RUNS:
        out.append((cds.DATASET_FIRE_PROJECTIONS,
                    cds.build_fire_projection_request(experiment=exp, period=period),
                    RAW / f"fire_{exp}_{period}.nc"))
    return out


# --------------------------------------------------------------------------- #
def _open_datasets(path: Path):
    """The CDS sometimes delivers NetCDF and sometimes a ZIP with one or more NetCDF files."""
    import xarray as xr

    if zipfile.is_zipfile(path):
        tmp = Path(tempfile.mkdtemp(prefix="cds_"))
        with zipfile.ZipFile(path) as zf:
            zf.extractall(tmp)
        return [xr.open_dataset(p) for p in sorted(tmp.rglob("*.nc"))]
    return [xr.open_dataset(path)]


def _coords(ds):
    lat = next(n for n in ("latitude", "lat", "rlat", "y") if n in ds.coords or n in ds.dims)
    lon = next(n for n in ("longitude", "lon", "rlon", "x") if n in ds.coords or n in ds.dims)
    return lat, lon


def build_fire() -> dict | None:
    import numpy as np

    runs = {}
    for exp, period in FIRE_RUNS:
        path = RAW / f"fire_{exp}_{period}.nc"
        if not path.exists():
            print(f"  fire: missing {path.name}")
            continue
        for ds in _open_datasets(path):
            lat_n, lon_n = _coords(ds)
            lat2 = ds[lat_n].values
            lon2 = ds[lon_n].values
            if lat2.ndim == 1:  # regular grid -> mesh
                lon2, lat2 = np.meshgrid(lon2, lat2)
            box = ((lat2 >= FIRE_BOX[0]) & (lat2 <= FIRE_BOX[1])
                   & (lon2 >= FIRE_BOX[2]) & (lon2 <= FIRE_BOX[3]))
            spatial = ds[lat_n].dims if ds[lat_n].ndim == 2 else (lat_n, lon_n)
            for var in ds.data_vars:
                da = ds[var]
                # Drop time_bnds, rotated_pole and anything that is not a map.
                if tuple(da.dims[-2:]) != tuple(spatial):
                    continue
                arr = da.values
                with warnings.catch_warnings():  # sea cells: all NaN
                    warnings.simplefilter("ignore", RuntimeWarning)
                    while arr.ndim > 2:  # one value per year: mean over the period
                        arr = np.nanmean(arr, axis=0)
                # The file does not say "high": it says fwi-nods-gt-30 and
                # fwi-nods-gt-45 (days with FWI above 30 and above 45).
                key = FIRE_KEYS.get(var, var)
                pts = [(round(float(la), 3), round(float(lo), 3), round(float(v), 1))
                       for la, lo, v in zip(lat2[box], lon2[box], arr[box]) if not np.isnan(v)]
                runs.setdefault(f"{exp}_{period}", {})[key] = pts
                print(f"  {path.name}: {var} -> {key}, {len(pts)} cells in the box")
    if not runs:
        return None
    return {"meta": {"dataset": cds.DATASET_FIRE_PROJECTIONS,
                     "product": "multi_model_mean_case, annual_indicators, v1_0",
                     "runs": sorted(runs), "built": time.strftime("%Y-%m-%d")},
            "runs": runs}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["download", "build"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-wait-minutes", type=float, default=240)
    args = ap.parse_args()

    if args.action == "download":
        todo = jobs()
        if args.dry_run:
            for dataset, request, target in todo:
                print(f"{dataset} -> {target.name}\n  {json.dumps(request)}")
            return 0
        RAW.mkdir(parents=True, exist_ok=True)
        results = cds.retrieve_many(todo, on_log=print, max_in_flight=2,
                                    max_wait_seconds=args.max_wait_minutes * 60)
        ok = sum(1 for p in results.values() if p)
        print(f"\n{ok}/{len(results)} files ready in {RAW}")
        return 0 if ok == len(results) else 1

    for name, builder, out in (("fire", build_fire, FIRE_OUT),):
        print(f"{name}:")
        data = builder()
        if data is None:
            continue
        with gzip.open(out, "wt", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
        print(f"  -> {out} ({out.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
