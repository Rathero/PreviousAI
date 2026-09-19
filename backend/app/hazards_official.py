"""Hazards built from official mapping and records.

They complement the climate cards (`hazards.py`) with street- or municipality-scale
sources. MITECO's flood zones cover all of Spain; the rest are Catalan. The official
avalanche map lives in `hazards_avalanche.py`.

Each card says what its value does NOT mean: a point outside a flood extent is not a
safe point, and a place with no recorded fire can still burn.
"""

from __future__ import annotations

import re

from . import scoring
from .hazards import Hazard
from .indicators import (AGORA_UB, GENCAT_FIRE_PERIMETERS, GENCAT_FIRE_STATS, ICGC_SLR,
                         IGN_SNCZI, MITECO_SNCZI, Indicator, Provenance)
from .providers.catalonia_store import parse_losses


def _distance_text(metres: float) -> str:
    """"49 m" below a kilometre; otherwise "3.9 km"."""
    if metres < 1000:
        return f"{metres:.0f} m"
    return f"{metres / 1000:.1f} km"


def _ind(key, label, value, unit, prov: dict, *, period, method, confidence="high",
         display=None, context=None) -> Indicator:
    extras = {"display": display} if display is not None else {}
    return Indicator(
        key=key, label=label,
        value=None if value is None else round(float(value), 3),
        unit=unit,
        provenance=Provenance(period=period, method=method, confidence=confidence, **prov),
        context=context, extras=extras,
    )


# --------------------------------------------------------------------------- #
# Official flood zones · MITECO · all of Spain
# --------------------------------------------------------------------------- #
ZONE_ORDER = ("zfp", "t10", "t50", "t100", "t500")
ZONE_SHORT = {"zfp": "preferential flow zone", "t10": "10-year flood zone",
              "t50": "50-year flood zone", "t100": "100-year flood zone",
              "t500": "500-year flood zone"}
MARINE_SHORT = {"marine_t100": "100-year coastal flood zone",
                "marine_t500": "500-year coastal flood zone"}


def river_label(props: dict | None) -> str | None:
    """The watercourse for the headline, as MITECO names it.

    Some studies list every watercourse of a valley in one field, and the point cannot
    tell which one floods it: a long list becomes the study area and how many
    watercourses it covers.
    """
    names = [n.strip() for n in ((props or {}).get("rio") or "").split(";") if n.strip()]
    if len(names) <= 2:
        return " and ".join(names) or None
    area = re.sub(r"^\d+\.-?\s*", "", (props or {}).get("zona") or "").strip()
    return (f"{area} study area, {len(names)} rivers and streams" if area
            else f"{names[0]} and {len(names) - 1} more watercourses")


def _m(depth: float) -> str:
    return f"{depth:.2f} m"


def hazard_flood_zones(result: dict | None, depths: dict | None = None) -> Hazard:
    """Official flood zone: river (MITECO polygons) + coastal (IGN water depths).

    The two sources do not say the same thing and the card does not mix them: the
    river polygons allow "inside" and "outside"; the IGN depths only allow "inside,
    with this much water".
    """
    layers = (result or {}).get("layers", {})
    d = (depths or {}).get("depths", {})
    inside = [k for k in ZONE_ORDER if layers.get(k, {}).get("inside")]
    unknown = [k for k in ZONE_ORDER if layers.get(k, {}).get("inside") is None]
    marine = [k for k in ("marine_t100", "marine_t500") if d.get(k)]
    worst = inside[0] if inside else None
    props = layers[worst]["props"] if worst else None
    river = river_label(props)
    score = max(scoring.score_flood_zones(inside), scoring.score_flood_zones(marine))

    # Reference depth: the 100-year flood, the one land-use planning uses. The 10-year
    # depth can be a centimetre where the 100-year one is well over a metre; the other
    # return periods go in as context.
    ref_key = next((k for k in ("fluvial_t100", "fluvial_t500", "fluvial_t10") if d.get(k)), None)
    fluvial_depth = d.get(ref_key) if ref_key else None
    if worst:
        # The watercourse name already carries its article or type, so it goes in as is.
        headline = f"Inside the {ZONE_SHORT[worst]}" + (f" ({river})" if river else "")
        if marine:
            headline += f"; also in the {MARINE_SHORT[marine[0]]}"
    elif marine:
        headline = f"Inside the {MARINE_SHORT[marine[0]]} (water depth {_m(d[marine[0]])})"
    elif unknown and result is not None:
        headline = "Not every river flood zone could be checked"
    elif result is None:
        headline = "No response from the river flood zone service"
    else:
        headline = "Outside the mapped river flood zones"

    indicators = []
    for k in ZONE_ORDER:
        layer = layers.get(k, {})
        state = layer.get("inside")
        indicators.append(_ind(
            f"flood_zone_{k}", layer.get("label", k),
            None if state is None else (1 if state else 0), "", MITECO_SNCZI,
            period="current SNCZI mapping",
            method="intersection of the point with the layer's official polygons",
            display="Yes" if state else ("No" if state is False else "no response"),
            confidence="high" if state is not None else "low",
        ))
    if props:
        indicators.append(_ind(
            "flood_zone_study", "River stretch and study", None, "", MITECO_SNCZI,
            period="current SNCZI mapping",
            method="attributes of the polygon containing the point",
            display=" · ".join(str(props[k]) for k in ("zona", "estudio") if props.get(k)) or "—",
        ))

    if depths is not None:
        for k, label in (("marine_t100", "Coastal flood zone, 100-year return period"),
                         ("marine_t500", "Coastal flood zone, 500-year return period")):
            value = d.get(k)
            indicators.append(_ind(
                f"flood_zone_{k}", label, value, "m" if value else "", IGN_SNCZI,
                period="current SNCZI mapping",
                method="IGN raster water depth at the point; only a positive value is "
                       "a statement",
                display=(f"Yes · depth {_m(value)}" if value else "no value"),
                context=None if value else
                        "No value does NOT mean \"outside\": the service cannot tell a dry "
                        "point from an unstudied stretch",
                confidence="high" if value else "low",
            ))
        if fluvial_depth:
            periods = {"fluvial_t10": "10", "fluvial_t100": "100", "fluvial_t500": "500"}
            others = [f"T{periods[k]}: {_m(d[k])}" for k in periods if d.get(k) and k != ref_key]
            indicators.append(_ind(
                "flood_depth_fluvial", f"River water depth, {periods[ref_key]}-year flood",
                fluvial_depth, "m", IGN_SNCZI,
                period="current SNCZI mapping",
                method="IGN river raster water depth at the point",
                context=("Other return periods: " + ", ".join(others)) if others else None,
            ))

    return Hazard(
        key="flood_zone", label="Official flood zone", score=score,
        level=scoring.level_for(score), headline=headline, primary_metric="flood_zone",
        indicators=indicators,
        limitation="A flood extent gives a probability per return period, not a "
                   "prediction. Being outside does NOT mean being safe: only the studied "
                   "stretches are mapped, and it does not include flooding from intense "
                   "local rain or overflowing sewers. COASTAL flooding can only be "
                   "confirmed, never ruled out: the IGN service cannot tell a dry point "
                   "from an unstudied one. For planning decisions, the reference is the "
                   "SNCZI viewer and the municipal land-use plan.",
    )


# --------------------------------------------------------------------------- #
# Recorded floods · AGORA (UB) · Catalonia
# --------------------------------------------------------------------------- #
def hazard_flood_history(municipality: dict, episodes: list[dict], period: str) -> Hazard:
    n = len(episodes)
    recent = [e for e in episodes if (e.get("start") or "") >= "1990"]
    categories = [int(e["category"]) for e in episodes
                  if str(e.get("category") or "").strip().isdigit()]
    victims = [(int(e["victims"]), e) for e in episodes
               if str(e.get("victims") or "").strip().isdigit() and int(e["victims"]) > 0]
    worst = max(victims, key=lambda v: v[0]) if victims else None
    last = episodes[0] if episodes else None
    score = scoring.score_for("flood_history", n)
    name = municipality["name"]

    headline = (f"{n} flood episodes affected {name} between {period.replace('-', ' and ')}"
                if n else f"No flood episodes recorded in {name} ({period})")

    def ep(key, label, value, unit, method, **kw):
        return _ind(key, label, value, unit, AGORA_UB, period=period, method=method, **kw)

    indicators = [
        ep("flood_episodes", "Episodes that affected the municipality", n, "episodes",
           "count of AGORA episodes linked to the municipality's INE code"),
        ep("flood_episodes_1990", "Episodes since 1990", len(recent), "episodes",
           "episodes starting in 1990 or later"),
        ep("flood_last", "Latest recorded episode", None, "",
           "most recent start date", display=(last or {}).get("start") or "—",
           context="The AGORA record ends in 2020" if last else None),
        ep("flood_max_category", "Highest category reached",
           max(categories) if categories else None, "",
           "maximum of the episodes' CATEGORIA field", confidence="medium",
           context="AGORA's own scale; the service does not publish its definition"),
    ]
    if worst:
        losses = parse_losses(worst[1].get("losses_raw"))
        indicators.append(ep(
            "flood_worst_victims", "Episode with the most victims", worst[0], "victims",
            "maximum of the VICTIMES field", confidence="medium",
            display=f"{worst[0]} victims · {worst[1].get('start')}",
            context="Victims and losses are for the whole episode across Catalonia, "
                    "not only for this municipality"
                    + (f". Losses in the episode: €{losses / 1e6:,.1f} M" if losses else ""),
        ))
    if municipality.get("match") == "nearest":
        indicators.append(ep(
            "municipality_match", "Assigned municipality", None, "",
            "the point falls outside every municipal polygon (right on the coastline), so "
            "the nearest municipality is assigned",
            display=f"{name} ({municipality['distance_m']} m away)", confidence="medium"))

    return Hazard(
        key="flood_history", label="Recorded floods", score=score,
        level=scoring.level_for(score), headline=headline, primary_metric="flood_episodes",
        indicators=indicators,
        limitation="This is a historical record per municipality, not a map: it says the "
                   "municipality was affected, not that the water reached this street. "
                   "Victims and losses belong to the whole episode. The record ends in "
                   "2020 and the service states no licence for non-academic use.",
    )


# --------------------------------------------------------------------------- #
# Sea-level rise · ICGC · Catalan coast
# --------------------------------------------------------------------------- #
def hazard_sea_level(result: dict) -> Hazard:
    t = result["threshold_m"]
    score = scoring.score_for("sea_level", t)
    lo, hi = result["min_modelled_m"], result["max_modelled_m"]
    headline = (f"Under water with a sea-level rise of {t * 100:.0f} cm"
                if t <= lo else
                f"Under water if the sea rises {t * 100:.0f} cm")

    def sl(key, label, value, unit, method, **kw):
        return _ind(key, label, value, unit, ICGC_SLR,
                    period="scenarios SSP1-1.9 to SSP5-8.5, horizons 2020-2100", method=method, **kw)

    return Hazard(
        key="sea_level", label="Sea-level rise", score=score,
        level=scoring.level_for(score), headline=headline, primary_metric="sea_level_threshold",
        indicators=[
            sl("sea_level_threshold", "Smallest rise that floods the point", t, "m",
               f"binary search over ICGC's {result['layers']} height layers: "
               f"the first one containing the point ({result['requests']} queries)",
               context="It is the lowest modelled layer: the point is practically at "
                       "today's sea level" if t <= lo else None),
            sl("sea_level_range", "Rises modelled by ICGC", None, "",
               "range of heights of the published layers",
               display=f"from {lo * 100:.1f} to {hi * 100:.1f} cm"),
        ],
        limitation="A \"bathtub\" model: it marks the land left below the new mean sea "
                   "level, without storms, waves or tides, which reach considerably "
                   "further. The mapping between each height and its scenario and year "
                   "is not included, so the figure does not say when it would happen.",
    )


# --------------------------------------------------------------------------- #
# Recorded wildfires · Government of Catalonia
# --------------------------------------------------------------------------- #
def hazard_fire_history(fires_5km: list[dict], municipality: dict, stats: list[dict],
                        perimeters_period: str, stats_period: str) -> Hazard:
    n5 = len(fires_5km)
    n1 = sum(1 for f in fires_5km if f["distance_m"] <= 1000)
    inside = [f for f in fires_5km if f["inside"]]
    nearest = fires_5km[0] if fires_5km else None
    latest = max(fires_5km, key=lambda f: f["year"]) if fires_5km else None
    total_ha = sum(f["area_ha"] for f in fires_5km)

    score = scoring.score_for("fire_history", n5)
    if inside:
        score = max(score, scoring.FIRE_INSIDE_FLOOR)

    if inside:
        big = max(inside, key=lambda f: f["area_ha"])
        headline = (f"The point lies inside the perimeter of a {big['year']} fire "
                    f"({big['area_ha']:,.0f} ha)")
    elif nearest:
        headline = (f"{n5} mapped fires within 5 km since "
                    f"{perimeters_period[:4]}; the nearest, from {nearest['year']}, "
                    f"{_distance_text(nearest['distance_m'])} away")
    else:
        headline = f"No mapped fire within 5 km since {perimeters_period[:4]}"

    def per(key, label, value, unit, method, **kw):
        return _ind(key, label, value, unit, GENCAT_FIRE_PERIMETERS,
                    period=perimeters_period, method=method, **kw)

    def sta(key, label, value, unit, method, **kw):
        return _ind(key, label, value, unit, GENCAT_FIRE_STATS,
                    period=stats_period, method=method, **kw)

    indicators = [
        per("fires_5km", "Fires within 5 km", n5, "fires",
            "fires whose perimeter lies less than 5 km from the point (distance to the edge)"),
        per("fires_1km", "Fires within 1 km", n1, "fires",
            "fires whose perimeter lies less than 1 km from the point"),
        per("fire_nearest_km", "Distance to the nearest perimeter",
            nearest["distance_m"] / 1000 if nearest else None, "km",
            "Euclidean distance to the edge of the perimeter, in ETRS89 UTM 31N",
            context=f"Fire of {nearest['year']} in {nearest['municipality']}"
                    if nearest else None),
        per("fire_latest", "Most recent fire within 5 km", None, "",
            "date of the most recent fire in the radius",
            display=(latest.get("date") or str(latest["year"])) if latest else "—"),
        per("fires_5km_ha", "Area of those fires", total_ha if fires_5km else None, "ha",
            "sum of the total area of each fire in the radius",
            context="The full area of each fire, not only the part within the 5 km"),
    ]
    if stats:
        indicators += [
            sta("muni_fires", f"Fires in {municipality['name']}", len(stats), "fires",
                "count of the municipality's records in the Government of Catalonia's open data",
                context="Includes tiny outbreaks that have no mapped perimeter"),
            sta("muni_fire_ha", "Forest area burnt in the municipality",
                sum(s.get("haforestal", 0) for s in stats), "ha",
                "sum of the haforestal field"),
        ]

    return Hazard(
        key="fire_history", label="Recorded wildfires", score=score,
        level=scoring.level_for(score), headline=headline, primary_metric="fires_5km",
        indicators=indicators,
        limitation="These are fires that already happened, not a prediction. Perimeters "
                   "only exist for fires of a certain size (small outbreaks are in the "
                   "municipal statistics, without geometry) and have been simplified to "
                   "10 m. That nothing has burnt nearby does not mean it cannot burn.",
    )
