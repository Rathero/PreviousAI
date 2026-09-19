"""Official SNCZI flood zones, via MITECO's WFS. All of Spain.

Official polygons per return period, with the river and the study that produced them:
street-scale flood information. Queried live (0.1-1 s per layer) with a disk cache. It
is a public government server: it must not be hammered.

Licence: free use with attribution to Spain's Ministry for the Ecological Transition
and the Demographic Challenge as author and owner.
"""

from __future__ import annotations

import asyncio
import re

import httpx

from .. import cache, config

WFS_URL = "https://gis.miteco.gob.es/geoserver/agua/ows"

# Order of severity: the preferential flow zone is the most restrictive (it legally
# restricts building) and T500 the least likely.
LAYERS = {
    "zfp": ("agua:ZI_Laminas_ZFP", "Preferential flow zone"),
    "t10": ("agua:Zi_laminas_q10", "Flood zone T=10 years (high probability)"),
    "t50": ("agua:Zi_laminas_q50", "Flood zone T=50 years (frequent flooding)"),
    "t100": ("agua:Zi_laminas_q100", "Flood zone T=100 years (medium probability)"),
    "t500": ("agua:Zi_laminas_q500", "Flood zone T=500 years (low probability)"),
}
# The ARPSI layer is deliberately not queried: its features are river stretches
# (lines), and a point never intersects a line. The extents above are the polygons that
# answer "does this point flood?".

GEOMETRY_FIELD = "shape"

# Mainland, Balearic and Canary Islands, Ceuta and Melilla. Outside it, no query is made.
SPAIN_BBOX = (27.4, -18.4, 44.0, 4.6)  # south, west, north, east

KEEP_PROPS = ("id_zona", "zona", "tipo_zona", "rio", "long_km", "hipotesis",
              "hidrologia", "precision", "hidraul", "estudio")
SAFE_PROPS = ("id_zona", "zona", "tipo_zona", "rio", "estudio")


def in_spain(lat: float, lon: float) -> bool:
    s, w, n, e = SPAIN_BBOX
    return s <= lat <= n and w <= lon <= e


def parse_features(payload: dict) -> tuple[bool, dict | None]:
    """(inside, attributes of the first polygon) from the WFS GeoJSON."""
    feats = (payload or {}).get("features") or []
    if not feats:
        return False, None
    props = feats[0].get("properties") or {}
    return True, {k: props[k] for k in KEEP_PROPS if props.get(k) not in (None, "")}


def props_for_schema(schema_xml: str) -> list[str]:
    """KEEP_PROPS fields that really exist in the layer.

    The layers do not share a schema, and asking for a missing field in
    `propertyName` makes GeoServer reject the WHOLE query.
    """
    existing = set(re.findall(r'<xsd:element[^>]*name="([^"]+)"', schema_xml or ""))
    props = [p for p in KEEP_PROPS if p in existing]
    return props or list(SAFE_PROPS)


async def _layer_props(client: httpx.AsyncClient, type_name: str) -> list[str]:
    key = f"schema:{type_name}"
    hit = cache.get("miteco_schema", key)
    if hit:
        return hit
    try:
        resp = await client.get(WFS_URL, params={"service": "WFS", "version": "1.1.0",
                                                 "request": "DescribeFeatureType",
                                                 "typeName": type_name})
        resp.raise_for_status()
        props = props_for_schema(resp.text)
    except httpx.HTTPError:
        return list(SAFE_PROPS)  # not cached: retried next time
    cache.set("miteco_schema", key, props)
    return props


async def _query_layer(client: httpx.AsyncClient, type_name: str, lat: float, lon: float):
    params = {
        "service": "WFS", "version": "1.1.0", "request": "GetFeature",
        "typeName": type_name, "outputFormat": "application/json", "maxFeatures": 1,
        "CQL_FILTER": f"INTERSECTS({GEOMETRY_FIELD},SRID=4326;POINT({lon} {lat}))",
        # Attributes only. Without it the WFS returns the whole polygon containing the
        # point, which for a large river delta weighs over a hundred megabytes.
        "propertyName": ",".join(await _layer_props(client, type_name)),
    }
    resp = await client.get(WFS_URL, params=params)
    resp.raise_for_status()
    return parse_features(resp.json())


async def flood_zones(lat: float, lon: float) -> dict:
    """Flood zones that contain the point.

    Returns {"layers": {key: {"inside", "label", "props"}}, "errors": [...]}. Only a
    complete result is cached: a timeout must not be served for a month as "outside".
    """
    key = f"miteco:{lat:.5f},{lon:.5f}"
    hit = cache.get("miteco", key)
    if hit is not None:
        layers = {k: {**v, "label": LAYERS[k][1]} for k, v in hit["layers"].items() if k in LAYERS}
        return {**hit, "layers": layers, "from_cache": True}

    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        results = await asyncio.gather(
            *(_query_layer(client, type_name, lat, lon) for type_name, _ in LAYERS.values()),
            return_exceptions=True,
        )

    layers, errors = {}, []
    for (k, (type_name, label)), res in zip(LAYERS.items(), results):
        if isinstance(res, Exception):
            errors.append(f"{type_name}: {type(res).__name__}")
            layers[k] = {"inside": None, "label": label, "props": None}
        else:
            inside, props = res
            layers[k] = {"inside": inside, "label": label, "props": props}

    out = {"layers": layers, "errors": errors, "source": WFS_URL}
    if not errors:
        cache.set("miteco", key, out)
    return {**out, "from_cache": False}
