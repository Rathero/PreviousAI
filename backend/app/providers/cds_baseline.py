"""Baselines precomputed from Climate Data Store downloads.

The other end of the bridge that starts in `cds.py`: NetCDF is downloaded in batch,
`scripts/cds_build_baseline.py` aggregates it into indicators per cell, and here it is
queried in microseconds.

The fast layer (Open-Meteo, ERA5-Land ~9 km) and the CDS (native ERA5, 0.25°) serve the
same reanalysis through different paths and resolutions. Comparing the two and showing
the deviation is a check no black-box score offers.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache

from .. import config


@lru_cache(maxsize=8)
def _load_all() -> tuple[dict, ...]:
    out = []
    for path in sorted(config.BASELINE_DIR.glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return tuple(out)


def available() -> list[dict]:
    return [
        {
            "name": b.get("name"),
            "dataset": b.get("dataset"),
            "period": b.get("period"),
            "bbox": b.get("bbox"),
            "cells": len(b.get("cells", [])),
            "indicators": sorted({k for c in b.get("cells", []) for k in c.get("indicators", {})}),
        }
        for b in _load_all()
    ]


# The bbox runs through the centres of the edge cells, and each 0.25° cell reaches half a
# cell beyond its centre.
HALF_CELL_DEG = 0.125


def _covers(baseline: dict, lat: float, lon: float) -> bool:
    bbox = baseline.get("bbox")
    if not bbox or len(bbox) != 4:
        return False
    north, west, south, east = bbox
    h = HALF_CELL_DEG
    return south - h <= lat <= north + h and west - h <= lon <= east + h


def nearest_cell(lat: float, lon: float) -> dict | None:
    """Nearest grid cell among all the loaded baselines."""
    best, best_dist, best_baseline = None, math.inf, None
    for baseline in _load_all():
        if not _covers(baseline, lat, lon):
            continue
        for cell in baseline.get("cells", []):
            d = (cell["lat"] - lat) ** 2 + (cell["lon"] - lon) ** 2
            if d < best_dist:
                best, best_dist, best_baseline = cell, d, baseline
    if best is None:
        return None
    return {
        "lat": best["lat"],
        "lon": best["lon"],
        "distance_km": round(math.sqrt(best_dist) * 111.0, 1),
        "indicators": best.get("indicators", {}),
        "baseline": {
            "name": best_baseline.get("name"),
            "dataset": best_baseline.get("dataset"),
            "period": best_baseline.get("period"),
            "source": "ERA5 (Copernicus C3S) via Climate Data Store",
            "resolution": best_baseline.get("resolution", "0.25 degrees (~28 km)"),
        },
    }


def cross_check(lat: float, lon: float, fast_values: dict[str, float | None]) -> dict | None:
    """Compares the fast layer with the CDS baseline, indicator by indicator."""
    cell = nearest_cell(lat, lon)
    if cell is None:
        return None

    comparisons = []
    for key, cds_value in cell["indicators"].items():
        fast = fast_values.get(key)
        if fast is None or cds_value is None:
            continue
        diff = fast - cds_value
        # With cds_value == 0 there is no relative error; if both are 0 they agree.
        rel = None if cds_value == 0 else abs(diff) / abs(cds_value) * 100
        if abs(diff) < 1e-9:
            agreement = "high"
        elif rel is None:
            agreement = "low"
        else:
            agreement = "high" if rel <= 15 else "medium" if rel <= 35 else "low"
        comparisons.append({
            "key": key,
            "fast_layer": round(fast, 2),
            "cds": round(cds_value, 2),
            "difference": round(diff, 2),
            "relative_pct": None if rel is None else round(rel, 1),
            "agreement": agreement,
        })

    return {
        "verified": bool(comparisons),
        "cell": {"lat": cell["lat"], "lon": cell["lon"], "distance_km": cell["distance_km"]},
        "baseline": cell["baseline"],
        "comparisons": comparisons,
        "period": cell["baseline"].get("period"),
        "note": "Comparison over the SAME years in both layers. Both serve ERA5, but at "
                "different resolutions (~9 km ERA5-Land versus native ERA5's 0.25 degrees), "
                "so a small deviation is to be expected; a large one means the point is in "
                "complex terrain (coast, mountains).",
    }
