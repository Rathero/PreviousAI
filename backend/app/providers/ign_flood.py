"""SNCZI river and COASTAL flood water depths, via the IGN INSPIRE WMS.

It complements `miteco.py`: the Ministry's WFS only publishes RIVER flood extents as
polygons. COASTAL flood zones only exist in this WMS, as a water-depth raster in metres.

How the values read:
  - A POSITIVE value is a real water depth.
  - Zero does NOT mean "dry": inland points far from the sea also return 0.0.
  - 999, -9999 and ±3.4·10³⁸ are "no data": the point is outside the studied stretches.

So this service can STATE that a point floods and with how much water, but never state
that it does not. Several layers in one call get mislabelled by the server, hence one
request per layer, in parallel.

The river models leave buildings out: the cell under an address point (a building
entrance) is often empty although the street in front of it floods. When the official
polygons put the point inside a flood zone and the point itself has no depth,
`door_depths` reads the nearest flooded cell within DOOR_RADIUS_M: a small map image of
the layer shows which cells are wet, and the nearest of them are asked for their value.

Licence: free use with attribution to Spain's Ministry for the Ecological Transition
and the Demographic Challenge.
"""

from __future__ import annotations

import asyncio
import io
import math
import re

import httpx
from PIL import Image

from .. import cache, config

WMS_URL = "https://servicios.idee.es/wms-inspire/riesgos-naturales/inundaciones"

LAYERS = {
    "fluvial_t10": "NZ.Flood.FluvialT10",
    "fluvial_t100": "NZ.Flood.FluvialT100",
    "fluvial_t500": "NZ.Flood.FluvialT500",
    "marine_t100": "NZ.Flood.MarinaT100",
    "marine_t500": "NZ.Flood.MarinaT500",
}

# Above this it is not a physical depth: these are the "no data" codes.
_MAX_REAL_DEPTH_M = 50.0

DOOR_RADIUS_M = 15.0
_DOOR_PX = 61          # the map image: about half a metre per pixel
_DOOR_TRIES = 8        # wet pixels asked for their value, nearest first


def parse_depth(text: str) -> float | None:
    """Water depth in metres if the point is flooded; None in any other case."""
    m = re.search(r"GRAY_INDEX\s*=\s*([-+\d.eE]+)", text or "")
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    if 0 < value < _MAX_REAL_DEPTH_M:
        return round(value, 3)
    return None


async def _depth(client: httpx.AsyncClient, layer: str, lat: float, lon: float) -> float | None:
    h = 0.0002
    params = {
        "service": "WMS", "version": "1.1.1", "request": "GetFeatureInfo",
        "layers": layer, "query_layers": layer, "styles": "", "srs": "EPSG:4326",
        "bbox": f"{lon - h},{lat - h},{lon + h},{lat + h}",
        "width": 41, "height": 41, "x": 20, "y": 20,
        "info_format": "text/plain", "feature_count": 1,
    }
    resp = await client.get(WMS_URL, params=params)
    resp.raise_for_status()
    return parse_depth(resp.text)


async def flood_depths(lat: float, lon: float) -> dict:
    """{"depths": {key: depth_m | None}, "errors": [...]}. None = no statement possible."""
    key = f"ign:{lat:.5f},{lon:.5f}"
    hit = cache.get("ign_flood", key)
    if hit is not None:
        return {**hit, "from_cache": True}

    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT, follow_redirects=True,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        results = await asyncio.gather(
            *(_depth(client, layer, lat, lon) for layer in LAYERS.values()),
            return_exceptions=True,
        )

    depths, errors = {}, []
    for (k, layer), res in zip(LAYERS.items(), results):
        if isinstance(res, Exception):
            errors.append(f"{layer}: {type(res).__name__}")
            depths[k] = None
        else:
            depths[k] = res

    out = {"depths": depths, "errors": errors, "source": WMS_URL}
    if not errors:
        cache.set("ign_flood", key, out)
    return {**out, "from_cache": False}


async def _door_depth(client: httpx.AsyncClient, layer: str, lat: float, lon: float) -> dict | None:
    """{"depth_m", "distance_m"} of the nearest flooded cell around the point, or None."""
    dlat = DOOR_RADIUS_M / 111_320
    dlon = DOOR_RADIUS_M / (111_320 * math.cos(math.radians(lat)))
    base = {"service": "WMS", "version": "1.1.1", "layers": layer, "styles": "", "srs": "EPSG:4326",
            "bbox": f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}",
            "width": _DOOR_PX, "height": _DOOR_PX}
    resp = await client.get(WMS_URL, params={**base, "request": "GetMap", "format": "image/png",
                                             "transparent": "true"})
    resp.raise_for_status()
    # Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    with Image.open(io.BytesIO(resp.content)) as img:
        alpha = img.convert("RGBA").getchannel("A").load()
    centre, metres_per_px = (_DOOR_PX - 1) / 2, 2 * DOOR_RADIUS_M / _DOOR_PX

    def distance(p: tuple[int, int]) -> float:
        return math.hypot(p[0] - centre, p[1] - centre) * metres_per_px

    wet = sorted(((x, y) for y in range(_DOOR_PX) for x in range(_DOOR_PX) if alpha[x, y]), key=distance)
    candidates = [p for p in wet if distance(p) <= DOOR_RADIUS_M][:_DOOR_TRIES]

    async def value(x: int, y: int) -> float | None:
        info = await client.get(WMS_URL, params={
            **base, "request": "GetFeatureInfo", "query_layers": layer, "x": x, "y": y,
            "info_format": "text/plain", "feature_count": 1})
        info.raise_for_status()
        return parse_depth(info.text)

    # The drawn image is resampled, so a wet-looking pixel can still read "no data":
    # the nearest ones are asked in two small batches.
    for batch in (candidates[:4], candidates[4:]):
        values = await asyncio.gather(*(value(x, y) for x, y in batch))
        for p, depth in zip(batch, values):
            if depth:
                return {"depth_m": depth, "distance_m": round(distance(p), 1)}
    return None


async def door_depths(lat: float, lon: float, keys: list[str]) -> dict:
    """{key: {"depth_m", "distance_m"} | None} for river layers ("fluvial_t100"...) whose
    value at the point itself is empty."""
    key = f"door:{lat:.5f},{lon:.5f}:{','.join(sorted(keys))}"
    hit = cache.get("ign_flood", key)
    if hit is not None:
        return hit
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT, follow_redirects=True,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        results = await asyncio.gather(*(_door_depth(client, LAYERS[k], lat, lon) for k in keys),
                                       return_exceptions=True)
    out = {k: (None if isinstance(r, Exception) else r) for k, r in zip(keys, results)}
    if not any(isinstance(r, Exception) for r in results):
        cache.set("ign_flood", key, out)
    return out


async def complete_at_door(lat: float, lon: float, zones: dict, depths: dict) -> dict:
    """The point's depths, plus the river depths the official polygons call for (the point
    is inside that zone) but the point itself lacks, read at the nearest flooded cell."""
    layers = zones.get("layers") or {}
    missing = [f"fluvial_{k}" for k in ("t10", "t100", "t500")
               if (layers.get(k) or {}).get("inside") and not depths["depths"].get(f"fluvial_{k}")]
    if not missing:
        return depths
    try:
        found = {k: v for k, v in (await door_depths(lat, lon, missing)).items() if v}
    except (httpx.HTTPError, OSError):
        return depths
    if not found:
        return depths
    return {**depths,
            "depths": {**depths["depths"], **{k: v["depth_m"] for k, v in found.items()}},
            "door": {k: v["distance_m"] for k, v in found.items()}}

