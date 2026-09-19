"""Sea-level rise · WMS of the Institut Cartogràfic i Geològic de Catalunya (ICGC).

Permanent flooding from sea-level rise: a "bathtub" model on ICGC's LiDAR terrain model
with IPCC AR6 rises. The WMS answers whether a point is flooded but does not return the
value; with one layer per rise height (0.077 to 0.848 m), the smallest rise that floods
the point is found by bisection: about 7 requests instead of 44.

The height layers are called `cat_0.077cm_rc1`, but the numbers are METRES.

ICGC's avalanche data are a batch layer (backend/scripts/catalonia_build.py), queried in
`catalonia_store.py`.
"""

from __future__ import annotations

import re

import httpx

from .. import cache, config

SLR_URL = "https://geoserveis.icgc.cat/servei/catalunya/inundacio-litoral-1x1/wms"

_LAYER_RE = re.compile(r"^cat_([\d.]+)c?m_rc1$")


def heights_from_capabilities(xml: str) -> list[tuple[float, str]]:
    """[(height_m, layer_name)] sorted from lowest to highest."""
    names = re.findall(r"<Name>([^<]+)</Name>", xml)
    out = []
    for name in names:
        m = _LAYER_RE.match(name)
        if m:
            out.append((float(m.group(1)), name))
    return sorted(set(out))


def plain_has_feature(text: str) -> bool:
    """MapServer in text/plain lists "Feature 0:" when the point falls inside."""
    return "Feature 0" in (text or "")


def _feature_info_params(layer: str, lat: float, lon: float, fmt: str, half: float) -> dict:
    return {
        "service": "WMS", "version": "1.1.1", "request": "GetFeatureInfo",
        "layers": layer, "query_layers": layer, "styles": "", "srs": "EPSG:4326",
        "bbox": f"{lon - half},{lat - half},{lon + half},{lat + half}",
        "width": 41, "height": 41, "x": 20, "y": 20,
        "info_format": fmt, "feature_count": 5,
    }


async def _slr_heights(client: httpx.AsyncClient) -> list[tuple[float, str]]:
    hit = cache.get("icgc_caps", "slr-heights")
    if hit:
        return [tuple(h) for h in hit]
    resp = await client.get(SLR_URL, params={"service": "WMS", "request": "GetCapabilities",
                                             "version": "1.3.0"})
    resp.raise_for_status()
    heights = heights_from_capabilities(resp.text)
    if heights:
        cache.set("icgc_caps", "slr-heights", heights)
    return heights


async def sea_level_threshold(lat: float, lon: float) -> dict:
    """Smallest mean sea-level rise (m) that floods the point, or None."""
    key = f"slr:{lat:.5f},{lon:.5f}"
    hit = cache.get("icgc_slr", key)
    if hit is not None:
        return {**hit, "from_cache": True}

    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT, follow_redirects=True,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        heights = await _slr_heights(client)
        if not heights:
            raise RuntimeError("the ICGC coastal flooding WMS lists no height layers")
        requests = 0

        async def flooded(index: int) -> bool:
            nonlocal requests
            requests += 1
            params = _feature_info_params(heights[index][1], lat, lon, "text/plain", 0.0002)
            resp = await client.get(SLR_URL, params=params)
            resp.raise_for_status()
            return plain_has_feature(resp.text)

        # If even the largest rise does not flood it, one request is enough.
        threshold = None
        if await flooded(len(heights) - 1):
            lo, hi = 0, len(heights) - 1
            while lo < hi:
                mid = (lo + hi) // 2
                if await flooded(mid):
                    hi = mid
                else:
                    lo = mid + 1
            threshold = heights[lo][0]

    out = {
        "threshold_m": threshold,
        "threshold_layer": next((name for h, name in heights if h == threshold), None),
        "min_modelled_m": heights[0][0],
        "max_modelled_m": heights[-1][0],
        "layers": len(heights),
        "requests": requests,
        "source": SLR_URL,
    }
    cache.set("icgc_slr", key, out)
    return {**out, "from_cache": False}
