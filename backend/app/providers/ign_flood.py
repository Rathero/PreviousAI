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

Licence: free use with attribution to Spain's Ministry for the Ecological Transition
and the Demographic Challenge.
"""

from __future__ import annotations

import asyncio
import re

import httpx

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
