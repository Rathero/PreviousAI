"""Avalanches: the official map in the Catalan Pyrenees, a terrain + snow proxy elsewhere.

In Catalonia ICGC maps where avalanches run (17,811 zones, 1:25,000) and keeps a
database of avalanches actually observed (6,468, 1971-2024) and recalled by local
people (739). That is point-scale, official information, and it decides the score.

Everywhere else there is no open per-point avalanche map, so the card says what can
honestly be said: whether there are slopes of 28-55 degrees within 1 km (Copernicus
DEM) and whether it snows enough for them to load (ERA5-Land). That proxy never goes
above "high" and never pretends to be a map of paths.

Today's avalanche danger is a daily bulletin, not a climatology: the card points to it
(the snow-climate zone is the bulletin's zone) and never scores it.
"""

from __future__ import annotations

from . import scoring
from .hazards import Hazard
from .indicators import ERA5, ICGC_AVALANCHE_EVENTS, ICGC_AVALANCHE_ZONES, TERRAIN, Indicator, Provenance
from .providers.terrain import AVALANCHE_MIN_DEG, RADII_M

ZONE_TYPES = {1: "defined avalanche path", 2: "avalanche slope (paths hard to separate)"}
ZONE_TYPES_SOURCE = {1: "zona de circulació preferent", 2: "zona de difícil individualització"}
ZONES_PERIOD = "fieldwork 1996-2006"


def _ind(key, label, value, unit, prov: dict, *, period, method, confidence="high",
         display=None, context=None) -> Indicator:
    extras = {"display": display} if display is not None else {}
    return Indicator(
        key=key, label=label,
        value=None if value is None else round(float(value), 2),
        unit=unit,
        provenance=Provenance(period=period, method=method, confidence=confidence, **prov),
        context=context, extras=extras,
    )


def _terrain_indicators(terrain: dict | None) -> list[Indicator]:
    if not terrain:
        return []
    return [
        _ind("avalanche_max_slope", f"Steepest slope within {terrain['radius_m'] / 1000:g} km",
             terrain["max_slope_deg"], "°", TERRAIN, period="Copernicus DEM GLO-90",
             method=f"slope of each segment along 16 rays sampled at "
                    f"{', '.join(str(r) for r in RADII_M)} m ({terrain['points']} elevations); "
                    f"a 90 m model smooths the terrain, so real slopes are steeper",
             confidence="medium",
             context=f"Point at {terrain['center_m']:.0f} m; {terrain['relief_m']} m of height "
                     f"difference within {terrain['radius_m']} m"),
        _ind("avalanche_steep_share", f"Share of slopes between {AVALANCHE_MIN_DEG}° and 55°",
             terrain["steep_share"] * 100, "%", TERRAIN, period="Copernicus DEM GLO-90",
             method="segments whose slope is in the range where avalanches usually release",
             confidence="medium"),
    ]


def _snow_indicators(snow: dict | None, terrain: dict | None) -> list[Indicator]:
    if not snow:
        return []
    ctx = None
    if terrain and snow.get("grid_elevation_m") is not None:
        gap = terrain["center_m"] - snow["grid_elevation_m"]
        if abs(gap) >= 200:
            ctx = (f"The ERA5-Land cell sits at {snow['grid_elevation_m']:.0f} m and the point at "
                   f"{terrain['center_m']:.0f} m: " + ("more snow falls up here than this figure"
                                                        if gap > 0 else "less snow falls down here"))
    return [
        _ind("snowfall_annual", "Snowfall in a typical year", snow["annual_cm"], "cm", ERA5,
             period=snow["period"], method="mean of the annual sum of snowfall_sum, complete years",
             confidence="medium", context=ctx),
        _ind("snowfall_heavy_days", "Days a year with 20 cm of new snow or more", snow["heavy_days"],
             "days/year", ERA5, period=snow["period"],
             method="mean number of days with snowfall_sum >= 20 cm; heavy snowfall is the "
                    "usual trigger of natural avalanches", confidence="medium"),
    ]


def _official(icgc: dict, terrain: dict | None, snow: dict | None) -> Hazard:
    zones, obs, surveys = icgc["zones"], icgc["observations"], icgc["surveys"]
    radius = icgc["radius_m"]
    inside = [z for z in zones if z["inside"]]
    nearest = min(zones, key=lambda z: z["distance_m"]) if zones else None
    years = sorted(o["year"] for o in obs if o.get("year"))

    candidates = []
    if inside:
        candidates.append(max(scoring.AVALANCHE_ZONE_SCORES.get(z["type"], 60) for z in inside))
    elif nearest:
        candidates.append(scoring.score_avalanche_distance(nearest["distance_m"]))
    if any(e["distance_m"] <= scoring.AVALANCHE_REACHED_M for e in obs + surveys):
        candidates.append(scoring.AVALANCHE_REACHED_FLOOR)
    candidates.append(next((f for n, f in scoring.AVALANCHE_OBSERVED_FLOORS if len(obs) >= n), None))
    score = max((c for c in candidates if c is not None), default=8.0)

    if inside:
        z = min(inside, key=lambda z: z["type"])
        headline = f"Inside a mapped {ZONE_TYPES.get(z['type'], 'avalanche zone')} ({z['code']})"
    elif nearest:
        headline = f"Nearest mapped avalanche zone {nearest['distance_m']} m away"
    else:
        headline = f"No mapped avalanche zone within {radius / 1000:.0f} km"
    if obs:
        headline += (f"; {len(obs)} avalanche{'s' if len(obs) > 1 else ''} observed within "
                     f"{radius / 1000:.0f} km" + (f" since {years[0]}" if years else ""))
    elif surveys:
        headline += (f"; {len(surveys)} avalanche{'s' if len(surveys) > 1 else ''} recalled by "
                     f"local people within {radius / 1000:.0f} km")
    # The snow a place gets is what people talk about ("plenty of snow").
    if isinstance(snow, dict) and snow.get("annual_cm"):
        headline += f"; {snow['annual_cm']} cm of snow in a typical year"

    indicators = [
        _ind("avalanche_zone", "Inside a mapped avalanche zone", 1 if inside else 0, "",
             ICGC_AVALANCHE_ZONES, period=ZONES_PERIOD,
             method="point-in-polygon against ICGC's avalanche zones (photo-interpretation, "
                    "terrain and vegetation evidence, and local surveys)",
             display=("Yes · " + ", ".join(f"{ZONE_TYPES.get(z['type'], '?')} {z['code']}"
                                           for z in inside)) if inside else "No"),
    ]
    if not inside:
        indicators.append(_ind(
            "avalanche_nearest_zone", "Distance to the nearest mapped avalanche zone",
            nearest["distance_m"] if nearest else None, "m", ICGC_AVALANCHE_ZONES,
            period=ZONES_PERIOD, method=f"distance to the edge of the nearest zone, searched "
                                        f"within {radius} m",
            display=None if nearest else f"none within {radius} m",
            context=(f"{nearest['code']} · {ZONE_TYPES.get(nearest['type'], '?')} (ICGC: "
                     f"{ZONE_TYPES_SOURCE.get(nearest['type'], '?')})" if nearest else None)))
    obs_period = f"{years[0]}-{years[-1]}" if years else "1971-2024"
    indicators += [
        _ind("avalanche_observed", f"Avalanches observed within {radius / 1000:.0f} km",
             len(obs), "avalanches", ICGC_AVALANCHE_EVENTS, period=obs_period,
             method="ICGC observations whose outline comes within the radius; the year is "
                    "read from the observation code",
             context=(f"The closest reached {obs[0]['distance_m']} m from the point"
                      + (f" ({obs[0]['year']})" if obs[0].get("year") else "")
                      + (f"; latest year with an observation: {years[-1]}" if years else "")
                      if obs else None)),
        _ind("avalanche_surveyed", f"Historical avalanches recalled within {radius / 1000:.0f} km",
             len(surveys), "avalanches", ICGC_AVALANCHE_EVENTS, period="local surveys",
             method="avalanches reported by local people in ICGC's surveys",
             confidence="medium"),
    ]
    if icgc.get("nivo_zone"):
        indicators.append(_ind(
            "avalanche_bulletin_zone", "Snow-climate zone (daily avalanche bulletin)", None, "",
            ICGC_AVALANCHE_ZONES, period="current", method="zone containing the point",
            display=icgc["nivo_zone"],
            context="In winter, ICGC's daily avalanche danger bulletin rates this zone from "
                    "1 to 5: check it before going into the mountains"))
    indicators += _terrain_indicators(terrain) + _snow_indicators(snow, terrain)

    return Hazard(
        key="avalanche", label="Avalanches", score=score, level=scoring.level_for(score),
        headline=headline, primary_metric="avalanche_zone", indicators=indicators,
        limitation="ICGC's map shows where avalanches run, not how often or how big, and it "
                   "covers the Catalan Pyrenees from fieldwork done in 1996-2006. Being outside "
                   "a mapped zone does not rule out an avalanche in an exceptional winter, and "
                   "the observation record is only as complete as the people who reported it. "
                   "Today's danger changes daily: that is the avalanche bulletin's job, not "
                   "this card's.",
    )


def _proxy_score(terrain: dict, snow: dict) -> float:
    slope = terrain["max_slope_deg"]
    pts = 45 if slope > 45 else 40 if slope > 35 else 30
    pts += 5 if terrain["steep_share"] >= 0.2 else 0
    annual = snow["annual_cm"]
    pts += 15 if annual >= 300 else 10 if annual >= 150 else 5 if annual >= 50 else 0
    pts += 5 if snow["heavy_days"] >= 3 else 0
    return float(min(scoring.AVALANCHE_PROXY_MAX, pts))


def hazard_avalanche(icgc: dict | None, terrain: dict | None,
                     snow: dict | None) -> tuple[Hazard | None, str | None, bool]:
    """(card, note, ruled_out).

    A card where there is avalanche terrain; otherwise a note saying why not, and
    whether that note rules the hazard out (flat or snowless) or only could not check it.
    """
    official = icgc is not None and (icgc["zones"] or icgc["observations"] or icgc["surveys"]
                                     or icgc.get("nivo_zone"))
    if official:
        return _official(icgc, terrain, snow), None, False
    if not terrain:
        return None, None, False
    if terrain["max_slope_deg"] < AVALANCHE_MIN_DEG:
        return None, (f"Avalanches: no slope of {AVALANCHE_MIN_DEG}° or more within "
                      f"{terrain['radius_m'] / 1000:g} km (the steepest is {terrain['max_slope_deg']:.0f}°), "
                      f"so they do not apply here."), True
    if not snow:
        return None, (f"Avalanches: there are slopes of {terrain['max_slope_deg']:.0f}° within "
                      f"{terrain['radius_m'] / 1000:g} km, but the snowfall record could not be "
                      f"checked right now; try again later."), False
    if snow["annual_cm"] < 50 and snow["heavy_days"] < 0.5:
        return None, (f"Avalanches: there are slopes of {terrain['max_slope_deg']:.0f}°, but "
                      f"too little snow ({snow['annual_cm']} cm of snowfall a year) to build "
                      f"avalanches."), True
    score = _proxy_score(terrain, snow)
    card = Hazard(
        key="avalanche", label="Avalanches · terrain and snow", score=score,
        level=scoring.level_for(score),
        headline=(f"Slopes of up to {terrain['max_slope_deg']:.0f}° and {snow['annual_cm']} cm "
                  f"of snowfall a year: avalanche terrain, with no official avalanche map here"),
        primary_metric="avalanche_max_slope",
        indicators=_terrain_indicators(terrain) + _snow_indicators(snow, terrain),
        limitation="This is not an avalanche map: it only says the two ingredients are "
                   "present (slopes of 28-55° and enough snow). It does not know where the "
                   "paths run, so it never goes above \"high\". The 90 m terrain model "
                   "underestimates slopes and ERA5-Land's 9 km cell can sit far below the "
                   "point. Where there is one, the national avalanche service's map and daily "
                   "bulletin are the reference (see avalanches.org).",
    )
    return card, None, False
