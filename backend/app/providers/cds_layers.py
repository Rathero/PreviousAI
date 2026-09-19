"""The Copernicus fire-danger projection, built locally by backend/scripts/cds_hazards.py.

Days of high and very high fire danger, EURO-CORDEX, 1981-2005 versus 2041-2060 (RCP4.5
and RCP8.5). If the file does not exist everything returns None and the report comes
out without it.
"""

from __future__ import annotations

import gzip
import json
import math
from functools import lru_cache

from .. import config
from ..geo import haversine_km

FIRE_PATH = config.CDS_DIR / "fire_danger_projections.json.gz"


def _load(path):
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def fire_data() -> dict | None:
    data = _load(FIRE_PATH)
    if data:
        # Index by half-degree cell so as not to scan the whole box.
        for run in data["runs"].values():
            for key, pts in list(run.items()):
                grid: dict[tuple[int, int], list] = {}
                for p in pts:
                    grid.setdefault((math.floor(p[0] * 2), math.floor(p[1] * 2)), []).append(p)
                run[key] = grid
    return data


def fire_projection(lat: float, lon: float, data: dict | None = None) -> dict | None:
    data = data if data is not None else fire_data()
    if not data:
        return None
    out = {}
    for run, layers in data["runs"].items():
        for key, grid in layers.items():
            cell = (math.floor(lat * 2), math.floor(lon * 2))
            cands = [p for a in (-1, 0, 1) for b in (-1, 0, 1)
                     for p in grid.get((cell[0] + a, cell[1] + b), ())]
            if not cands:
                continue
            best = min(cands, key=lambda p: haversine_km(lat, lon, p[0], p[1]))
            if haversine_km(lat, lon, best[0], best[1]) <= 25:
                out.setdefault(run, {})[key] = best[2]
    return out or None
