"""Map layers for a report: what can be drawn, from which source and at what scale.

Every value is drawn as what it is, so a map shows the accuracy: the official flood and
avalanche zones over the street, the climate as the ~9 km square it corresponds to,
recorded fires and avalanches with the radius they were searched in. The web app uses
the aerial base to show the home when there is no Street View; the layers are part of
the report API for integrations.
"""

from __future__ import annotations

from .providers import catalonia_store

ERA5_LAND_CELL_DEG = 0.1

MITECO_WMS = "https://gis.miteco.gob.es/geoserver/agua/wms"
IGN_FLOOD_WMS = "https://servicios.idee.es/wms-inspire/riesgos-naturales/inundaciones"
ICGC_SEA_WMS = "https://geoserveis.icgc.cat/servei/catalunya/inundacio-litoral-1x1/wms"
ICGC_AVALANCHE_WMS = "https://geoserveis.icgc.cat/geoserver/nivoallaus/wms"

# Legends: the colours are each service's own, the same anyone sees in its viewer.
MITECO_LEGEND = [
    {"color": "#CCCCCC", "border": "#4e4e4e", "label": "Preferential flow zone"},
    {"color": "#FF0000", "label": "Floods every 10 years (high probability)"},
    {"color": "#E8BEFF", "label": "Floods every 100 years (medium probability)"},
    {"color": "#FF73DF", "label": "Floods every 500 years (low probability)"},
]
IGN_MARINE_LEGEND = [{"color": "#189ef1", "label": "Floods from the sea every 100 years (shade shows the depth)"}]
ICGC_SEA_LEGEND = [{"color": "#002df8", "label": "Land below sea level with that rise"}]
ICGC_AVALANCHE_LEGEND = [
    {"color": "#FF9933", "border": "#663300", "label": "Defined avalanche path (zona de circulació preferent)"},
    {"color": "#FFCC99", "border": "#663300", "label": "Avalanche slopes, paths hard to separate"},
]

_IGN_WMTS = ("https://www.ign.es/wmts/{svc}?layer={layer}&style=default&tilematrixset="
             "GoogleMapsCompatible&Service=WMTS&Request=GetTile&Version=1.0.0&Format=image/jpeg"
             "&TileMatrix={{z}}&TileCol={{x}}&TileRow={{y}}")
BASE_OSM = {"id": "osm", "label": "OpenStreetMap", "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            "attribution": "© OpenStreetMap contributors", "max_zoom": 19}
BASE_IGN = {"id": "ign", "label": "IGN map", "url": _IGN_WMTS.format(svc="ign-base", layer="IGNBaseTodo"),
            "attribution": "© Instituto Geográfico Nacional", "max_zoom": 19}
# Aerial imagery with licences that allow commercial use with attribution: Spain's
# national orthophoto (CC BY 4.0) and, elsewhere, Sentinel-2 cloudless 2016 (CC BY 4.0).
AERIAL_PNOA = {"id": "pnoa", "label": "PNOA aerial imagery",
               "url": _IGN_WMTS.format(svc="pnoa-ma", layer="OI.OrthoimageCoverage"),
               "attribution": "PNOA © Instituto Geográfico Nacional", "max_zoom": 19}
AERIAL_S2 = {"id": "s2cloudless", "label": "Sentinel-2 cloudless",
             "url": "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg",
             "attribution": "Sentinel-2 cloudless 2016 by EOX IT Services GmbH (contains modified "
                            "Copernicus Sentinel data 2016)", "max_zoom": 15}


def _circle(lat, lon, radius_km, label):
    return {"type": "circle", "lat": lat, "lon": lon, "radius_m": radius_km * 1000, "label": label}


def build(*, lat: float, lon: float, place: dict, archive: dict, data: dict, spain: bool,
          municipality: dict | None) -> dict:
    """Map layers for a report. Data only: the client does the drawing."""
    layers = []

    # Climate cell: the square inside which all the climate is the same.
    clat, clon = archive.get("latitude"), archive.get("longitude")
    if clat is not None and clon is not None:
        h = ERA5_LAND_CELL_DEG / 2
        layers.append({
            "id": "cell", "label": "ERA5-Land climate cell", "scale": "~9 km grid",
            "kind": "grid", "visible": True,
            "note": "All of the report's climate (heat, rain, fire weather, snowfall) is the "
                    "same inside this square.",
            "features": [{"type": "rect", "bounds": [[clat - h, clon - h], [clat + h, clon + h]],
                          "label": f"ERA5-Land cell centred on {clat:.2f}, {clon:.2f}"}],
        })

    cat = catalonia_store.store()
    if municipality:
        outline = cat.municipality_outline(municipality["code"])
        if outline:
            layers.append({
                "id": "municipality", "label": f"Municipality of {municipality['name']}",
                "scale": "municipality", "kind": "municipality", "visible": True,
                "note": "Recorded floods and the wildfire statistics cover the whole "
                        "municipality.",
                "features": [{"type": "polygon", "rings": ring, "label": municipality["name"]}
                             for ring in outline],
            })
        fires = cat.fires_near(lat, lon, 5000, with_geometry=True)[:8]
        feats = [_circle(lat, lon, 5, "5 km radius searched for fires")]
        for f in fires:
            label = f"Fire of {f['year']} · {f['area_ha']:,.0f} ha · {f['municipality']}"
            feats += [{"type": "polygon", "rings": rings, "label": label} for rings in f["polygons"]]
        layers.append({"id": "fires", "label": "Fires with a perimeter (1986-2024)",
                       "scale": "5 km radius", "kind": "radius", "visible": True, "features": feats})

    aval = cat.avalanches_near(lat, lon, 1000, with_geometry=True) if municipality else None
    if aval and (aval["observations"] or aval["surveys"]):
        feats = [_circle(lat, lon, 1, "1 km radius searched for observed avalanches")]
        for o in aval["observations"][:25]:
            label = f"Avalanche {o['code']}" + (f" · {o['year']}" if o.get("year") else "")
            feats += [{"type": "polygon", "rings": rings, "label": label} for rings in o["polygons"]]
        for sv in aval["surveys"][:10]:
            feats += [{"type": "polygon", "rings": rings,
                       "label": f"Historical avalanche {sv['code']} (local survey)"}
                      for rings in sv["polygons"]]
        layers.append({"id": "avalanches", "label": "Observed and recalled avalanches (ICGC)",
                       "scale": "1 km radius", "kind": "radius", "visible": True, "features": feats})

    layers += _wildfire_layers(lat, lon, data)

    return {
        "center": [lat, lon],
        "precision": place.get("precision"),
        "zoom": 18 if place.get("precision") in ("address", "coordinates") else
                17 if place.get("precision") == "street" else 15,
        "aerial": AERIAL_PNOA if spain else AERIAL_S2,
        "bases": ([BASE_IGN, AERIAL_PNOA] if spain else []) + [BASE_OSM],
        "wms": _wms_overlays(data, spain, municipality),
        "layers": layers,
    }


def _fire_label(f: dict, what: str) -> str:
    day = (f.get("first") or "")[:10]
    size = f" · perimeter ~{f['area_ha']:.0f} ha" if f.get("area_ha") else ""
    return f"{what} · {day} · {f['detections']} satellite detections{size} (Deepfire)"


def _wildfire_layers(lat: float, lon: float, data: dict) -> list[dict]:
    """FireScope's risk around the point and the fires Deepfire saw from space."""
    from .providers.firescope import LEGEND

    out = []
    fs = data.get("firescope") if isinstance(data.get("firescope"), dict) else None
    if fs and fs.get("overlay"):
        ov = fs["overlay"]
        out.append({
            "id": "firescope", "label": "AI-estimated wildfire risk 2026 (FireScope)",
            "scale": "30 m", "kind": "point", "visible": True, "legend": LEGEND,
            "note": "An AI research model's estimate (INSAIT), not an official map. Safe land "
                    "(below 25, including towns and water) is left clear. Straight edges are "
                    "the seams of its ~10 km prediction patches.",
            "features": [{"type": "image", "image": ov["image"], "bounds": ov["bounds"],
                          "opacity": 0.7, "label": "FireScope risk"}],
        })
    rec = data.get("fires_record") if isinstance(data.get("fires_record"), dict) else None
    if rec and rec.get("fires"):
        feats = [_circle(lat, lon, rec.get("radius_km", 10),
                         f"{rec.get('radius_km', 10)} km radius searched for satellite-detected fires")]
        for f in rec["fires"]:
            feats += [{"type": "polygon", "rings": [ring], "label": _fire_label(f, "Estimated perimeter")}
                      for ring in f.get("perimeter") or []]
            feats.append({"type": "point", "lat": f["lat"], "lon": f["lon"],
                          "size": min(8, 3 + f["detections"] ** 0.5),
                          "label": _fire_label(f, "Fire seen by satellite")})
        out.append({"id": "satellite_fires", "label": "Fires seen by satellite since 2025 (Deepfire)",
                    "scale": f"{rec.get('radius_km', 10)} km radius", "kind": "radius",
                    "visible": True, "features": feats,
                    "note": "Nearest detection of each fire; outlines are Deepfire's estimates "
                            "from the detections, not surveyed perimeters."})
    now = data.get("fires_now") if isinstance(data.get("fires_now"), dict) else None
    if now and now.get("fires"):
        feats = []
        for f in now["fires"]:
            feats += [{"type": "polygon", "rings": [ring], "label": _fire_label(f, "Possible fire, last 24 h")}
                      for ring in f.get("perimeter") or []]
            feats.append({"type": "point", "lat": f["lat"], "lon": f["lon"], "size": 8,
                          "label": _fire_label(f, "Possible fire, last 24 h") + f" · {f['distance_km']:.0f} km away"})
        out.append({"id": "fires_now", "label": "Possible fires in the last 24 h, 50 km (Deepfire)",
                    "scale": "50 km radius", "kind": "radius", "visible": True, "features": feats})
    return out


def _wms_overlays(data: dict, spain: bool, municipality: dict | None) -> list[dict]:
    out = []
    if spain:
        out.append({"id": "flood_zones", "label": "Official flood zones (MITECO)",
                    "scale": "point", "url": MITECO_WMS,
                    "layers": "agua:Zi_laminas_q500,agua:Zi_laminas_q100,agua:Zi_laminas_q10,"
                              "agua:ZI_Laminas_ZFP",
                    "opacity": 0.6, "visible": True,
                    "attribution": "SNCZI © MITECO", "legend": MITECO_LEGEND,
                    "note": "Official SNCZI colours. The 500-year zone contains the 100-year "
                            "one, and that one the 10-year one."})
        depths = data.get("flood_depths") if isinstance(data.get("flood_depths"), dict) else {}
        marine = any((depths.get("depths") or {}).get(k) for k in ("marine_t100", "marine_t500"))
        out.append({"id": "marine", "label": "Coastal flood zone T100 (IGN)", "scale": "point",
                    "url": IGN_FLOOD_WMS, "layers": "NZ.Flood.MarinaT100", "opacity": 0.7,
                    "visible": marine, "attribution": "SNCZI © IGN", "legend": IGN_MARINE_LEGEND})
    if municipality:
        slr = data.get("sea_level") if isinstance(data.get("sea_level"), dict) else None
        if slr and slr.get("threshold_m") is not None:
            layer = slr.get("threshold_layer") or f"cat_{slr['threshold_m']:.3f}cm_rc1"
            out.append({"id": "sea_level",
                        "label": f"Under water with {slr['threshold_m'] * 100:.0f} cm more sea (ICGC)",
                        "scale": "point", "url": ICGC_SEA_WMS, "layers": layer, "opacity": 0.7,
                        "visible": True, "attribution": "© ICGC", "legend": ICGC_SEA_LEGEND})
        aval = data.get("avalanche") if isinstance(data.get("avalanche"), dict) else None
        if aval and (aval.get("zones") or aval.get("nivo_zone")):
            out.append({"id": "avalanche_zones", "label": "Avalanche zones 1:25,000 (ICGC)",
                        "scale": "point", "url": ICGC_AVALANCHE_WMS, "layers": "zonesallaus_color",
                        "opacity": 0.75, "visible": True, "attribution": "© ICGC",
                        "legend": ICGC_AVALANCHE_LEGEND,
                        "note": "Official ICGC colours. Only the Catalan Pyrenees are mapped."})
    return out
