"""The report read backwards: every municipality of Spain, ranked, then its buildings.

The product answers "what threatens this home". This asks the same engine the opposite
question - "which homes does this threaten" - because a town hall, a comarca or an
emergency service cannot type eight thousand addresses, and the households who most
need the report are exactly the ones who will never go looking for it.

It is the same data and the same scales, at a different unit:

    municipality   the ranking. What can be known for all of Spain at once: the
                   official fire-danger grid at its centre, and, in Catalonia, the
                   flood episodes, wildfire perimeters and avalanche zones already on
                   disk for the reports.
    building       the drill-down. The cadastre's footprints for one municipality
                   crossed with the official flood zones that cover them, which is the
                   same question `providers/miteco.py` asks for one point, asked once
                   for every building in the town.

Nothing here is computed on the request path: `backend/scripts/analysis_build.py`
writes `data/analysis/` and this module only reads it. A ranking that recomputed
itself would be a different ranking every time it was opened, and the whole point is
a list somebody can act on and come back to.

What the ranking deliberately does NOT do:

  - It does not carry a heat score for the whole country. ERA5 is not available for
    eight thousand towns on a free tier, so heat is filled in only for the
    municipalities the build script was pointed at, and the rest say so rather than
    carry an invented number.
  - It does not rank people. The unit is a building, with what the cadastre publishes
    about the building: when it was built, what it is used for, how many dwellings it
    holds. Who lives in it is not in here and must not be put in here.
"""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path

from . import config, scoring
from .indicators import Indicator, Provenance

DIR = config.ANALYSIS_DIR
MUNICIPALITIES = DIR / "municipalities.json.gz"
RANKING = DIR / "ranking.json.gz"
EXPOSURE_DIR = DIR / "exposure"
VERSION = 1

# The hazards the ranking can sort by. `overall` is the aggregate of the rest, with
# the same rule the report uses: the worst hazard rules and the others push up a little.
HAZARDS = ("overall", "people", "homes", "flood", "fire_weather", "flood_history",
           "fire_history", "avalanche", "heat")

# These two are not scores. They are the columns an institution actually plans around:
# how many dwellings, and how many residents, stand in an official flood zone, in
# absolute numbers. A small town can be a 92 and hold four hundred homes; a city can be
# a 70 and hold fifty thousand, and whoever has to reach them needs the second one
# first. `people` exists only where TALAIA has been asked (the `assets` build step).
COUNTS = {"homes": "homes_at_risk", "people": "people_at_risk"}

LABELS = {
    "overall": "Overall",
    "people": "People in a flood zone",
    "homes": "Homes in a flood zone",
    "flood": "Flooding (official zones, per building)",
    "fire_weather": "Wildfire weather",
    "flood_history": "Floods on record",
    "fire_history": "Wildfires on record",
    "avalanche": "Avalanches",
    "heat": "Extreme heat",
}

# --- Where each municipal number comes from ----------------------------------------

CATASTRO = dict(
    source="Dirección General del Catastro, INSPIRE download service",
    dataset="ES.SDGC.BU (buildings)",
    resolution="building footprint",
    url="https://www.catastro.hacienda.gob.es/INSPIRE/buildings/ES.SDGC.BU.atom.xml",
    scale="building",
    scale_kind="point",
)

CDS_FIRE_GRID = dict(
    source="Copernicus CDS · fire danger indicators for Europe (EURO-CORDEX)",
    dataset="sis-tourism-fire-danger-indicators",
    resolution="~11 km (EURO-CORDEX)",
    url="https://cds.climate.copernicus.eu/datasets/sis-tourism-fire-danger-indicators",
    scale="~11 km grid",
    scale_kind="grid",
)

TALAIA_AOI = dict(
    source="TALAIA · values at risk inside a polygon",
    dataset="talaia-v1-exposure",
    resolution="per asset; population from the 1 km INE census grid",
    url="https://talaia.up.railway.app",
    scale="the flooded part of the municipality",
    scale_kind="radius",
)

SNCZI_MUNICIPAL = dict(
    source="SNCZI (MITECO) flood zones crossed with the cadastre's building footprints",
    dataset="snczi-laminas × ES.SDGC.BU",
    resolution="official polygons at plot scale",
    url="https://gis.miteco.gob.es/geoserver/agua/ows",
    scale="municipality",
    scale_kind="municipality",
)


def _read(path):
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _write(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    tmp.replace(path)


read = _read    # the build script reads and writes through the same door the API uses
write = _write


@lru_cache(maxsize=64)
def _cached(path_str: str, _mtime: float) -> dict | None:
    return _read(Path(path_str))


def _fresh(path) -> dict | None:
    """The file, parsed once and kept - but keyed on when it was last written.

    The ranking is rebuilt while the server is running. Caching it by path alone would
    serve the build from before the rebuild until someone restarted the process, and a
    ranking nobody can refresh is worse than no ranking.
    """
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    return _cached(str(path), mtime)


def ranking_data() -> dict | None:
    """The built ranking, or None when `analysis_build.py` has not run."""
    return _fresh(RANKING)


def universe() -> dict | None:
    return _fresh(MUNICIPALITIES)


def reload() -> None:
    """Forget what is cached in memory: the build script has written a new file."""
    _cached.cache_clear()


def available() -> bool:
    return ranking_data() is not None


def exposure(code: str) -> dict | None:
    """The building-by-building result for one municipality, if it has been built."""
    if not str(code).isdigit():
        return None
    return _fresh(EXPOSURE_DIR / f"{code}.json.gz")


# --- Queries -----------------------------------------------------------------------

def _score(row: dict, hazard: str) -> float:
    if hazard in COUNTS:
        return float(row.get(COUNTS[hazard]) or -1.0)
    value = (row.get("scores") or {}).get(hazard)
    return -1.0 if value is None else float(value)


def ranking(hazard: str = "overall", province: str | None = None, limit: int = 50,
            offset: int = 0, min_score: float | None = None,
            only_exposed: bool = False, query: str | None = None) -> dict:
    """The ranked municipalities, filtered.

    `hazard` picks the column to sort by, `only_exposed` keeps the ones whose buildings
    have been crossed with the flood zones, and `query` matches the name of the town.
    """
    data = ranking_data()
    if not data:
        return {"available": False, "total": 0, "rows": [], "hazards": list(HAZARDS)}

    hazard = hazard if hazard in HAZARDS else "overall"
    rows = data["rows"]
    if province:
        rows = [r for r in rows if r["province_code"] == province or r["province"] == province]
    if query:
        needle = _fold(query)
        rows = [r for r in rows if needle in _fold(r["name"])]
    if only_exposed:
        rows = [r for r in rows if r.get("exposure")]
    if hazard in COUNTS:
        # A count column lists the towns that HAVE the count. A town whose buildings
        # were never crossed with the flood maps does not hold zero people; it holds an
        # unknown number, and putting it in the list sorted as a zero would be a lie
        # told in alphabetical order.
        rows = [r for r in rows if r.get(COUNTS[hazard]) is not None]
    if min_score is not None:
        rows = [r for r in rows if _score(r, hazard) >= min_score]

    rows = sorted(rows, key=lambda r: (-_score(r, hazard), r["name"]))
    total = len(rows)
    page = rows[max(0, offset):max(0, offset) + max(1, min(limit, 500))]
    return {
        "available": True,
        "hazard": hazard,
        "label": LABELS.get(hazard, hazard),
        "hazards": [{"key": k, "label": LABELS[k]} for k in HAZARDS],
        "total": total,
        "offset": offset,
        # A count has no level: 47,089 homes is not "very high", it is 47,089 homes.
        "is_count": hazard in COUNTS,
        "rows": [{**r, "rank": offset + i + 1,
                  "level": None if hazard in COUNTS else scoring.level_for(_score(r, hazard))}
                 for i, r in enumerate(page)],
        "provinces": data.get("provinces", []),
        "meta": data.get("meta", {}),
    }


def _fold(text: str) -> str:
    """Lowercase and without accents, so "Alcala" finds "Alcalá"."""
    import unicodedata
    stripped = unicodedata.normalize("NFD", str(text))
    return "".join(c for c in stripped if unicodedata.category(c) != "Mn").lower()


def municipality(code: str) -> dict | None:
    """One municipality: its scores with their sources, and its buildings if built."""
    data = ranking_data()
    if not data:
        return None
    row = next((r for r in data["rows"] if r["code"] == str(code)), None)
    if not row:
        return None
    exp = exposure(code)
    return {
        **row,
        "indicators": [i.to_dict() for i in _indicators(row, exp)],
        "exposure": exp or row.get("exposure"),
        "meta": data.get("meta", {}),
    }


def _indicators(row: dict, exp: dict | None) -> list[Indicator]:
    """Every municipal number with where it comes from, the same contract as a report."""
    out: list[Indicator] = []
    metrics = row.get("metrics") or {}

    if metrics.get("fire_weather_days") is not None:
        out.append(Indicator(
            key="fire_weather_days",
            label="Days a year with a Fire Weather Index above 30",
            value=metrics["fire_weather_days"], unit="days/year",
            provenance=Provenance(period="1981-2005", confidence="medium",
                                  method="EURO-CORDEX multi-model mean, the grid cell "
                                         "nearest the centre of the municipality "
                                         "(within 25 km)",
                                  **CDS_FIRE_GRID),
            context=metrics.get("fire_weather_context"),
        ))

    if metrics.get("heat_days_35") is not None:
        out.append(Indicator(
            key="heat_days_35", label="Days a year above 35 °C",
            value=metrics["heat_days_35"], unit="days/year",
            provenance=Provenance(
                source="ERA5 / ERA5-Land (Copernicus C3S) via Open-Meteo Archive API",
                dataset="era5-land", period=f"{config.CLIMATOLOGY_START} to today",
                resolution="~9 km (ERA5-Land)",
                method="mean number of days with temperature_2m_max >= 35 °C at the "
                       "centre of the municipality, the same series a report reads",
                confidence="high", scale="~9 km grid", scale_kind="grid",
                url="https://open-meteo.com/en/docs/historical-weather-api"),
        ))

    if exp:
        total = exp["buildings"]["total"]
        out.append(Indicator(
            key="buildings_total", label="Buildings in the cadastre", value=total,
            unit="buildings",
            provenance=Provenance(period=exp["meta"]["cadastre_date"], confidence="high",
                                  method="every building of the municipality in the "
                                         "INSPIRE download, current at the date shown",
                                  **CATASTRO),
        ))
        out.append(Indicator(
            key="buildings_flooded",
            label="Buildings whose footprint centre falls in an official flood zone",
            value=exp["flood"]["buildings"], unit="buildings",
            provenance=Provenance(period="SNCZI, as published", confidence="medium",
                                  method="point-in-polygon of each footprint centre "
                                         "against the five SNCZI layers (preferential "
                                         "flow, T10, T50, T100, T500) over the "
                                         "municipality's bounding box",
                                  **SNCZI_MUNICIPAL),
            # From the counts, not from flood.share: that one is the cumulative share
            # of the zone that set the score, which is a different question.
            context=(f"{exp['flood']['buildings'] / total * 100:.1f} % of the town's "
                     f"buildings" if total else None),
        ))
        if exp["flood"]["dwellings"]:
            out.append(Indicator(
                key="dwellings_flooded", label="Dwellings in those buildings",
                value=exp["flood"]["dwellings"], unit="dwellings",
                provenance=Provenance(period=exp["meta"]["cadastre_date"],
                                      confidence="medium",
                                      method="numberOfDwellings of each exposed "
                                             "building, as the cadastre publishes it",
                                      **CATASTRO),
            ))

    assets = (exp or {}).get("assets") or {}
    if assets.get("available"):
        inside = assets["in_flood_zone"]
        out.append(Indicator(
            key="population_flooded", label="Residents of the flooded area",
            value=round(assets["population_resident"]), unit="people",
            provenance=Provenance(
                period=str(assets.get("generated_at") or "")[:10] or "as published",
                confidence="medium",
                method="INE census grid, area-weighted to the box around the buildings "
                       f"that stand in a flood zone ({assets['aoi']['km2']} km2). It "
                       "counts residents of that ground, not of the buildings",
                **TALAIA_AOI),
        ))
        out.append(Indicator(
            key="institutions_flooded",
            label="Schools, care homes and other places that hold people, inside a zone",
            value=inside["count"], unit="places",
            provenance=Provenance(
                period=str(assets.get("generated_at") or "")[:10] or "as published",
                confidence="medium",
                method="every asset TALAIA returned for the area, placed in a flood "
                       "zone by the same point-in-polygon test the buildings went "
                       "through",
                **TALAIA_AOI),
            context=(f"{inside['people']:.0f} people at capacity"
                     if inside["people"] else None),
        ))
        if assets.get("hazardous"):
            out.append(Indicator(
                key="hazardous_sites", label="Hazardous sites in the area",
                value=assets["hazardous"], unit="sites",
                provenance=Provenance(
                    period=str(assets.get("generated_at") or "")[:10] or "as published",
                    confidence="medium",
                    method="assets TALAIA flags as hazardous (fuel, chemicals, "
                           "industry holding dangerous substances)",
                    **TALAIA_AOI),
            ))
        if inside.get("value_eur"):
            out.append(Indicator(
                key="value_flooded", label="Replacement value inside a flood zone",
                value=round(inside["value_eur"]), unit="EUR",
                provenance=Provenance(
                    period=str(assets.get("generated_at") or "")[:10] or "as published",
                    confidence="low",
                    method="TALAIA's replacement valuation of the assets inside a "
                           "zone. A modelled cost from class defaults, not a survey "
                           "and not a market value",
                    **TALAIA_AOI),
            ))

    for key, label, period, method, source in _CATALAN_INDICATORS:
        value = metrics.get(key)
        if value is not None:
            out.append(Indicator(key=key, label=label, value=value, unit=source["unit"],
                                 provenance=Provenance(period=period, method=method,
                                                       confidence="high",
                                                       **source["provenance"])))
    return out


AGORA = dict(
    source="AGORA · University of Barcelona, flood episodes in Catalonia",
    dataset="agora-episodes", resolution="municipality",
    url="https://www.ub.edu/agora/", scale="municipality", scale_kind="municipality",
)
GENCAT_FIRE = dict(
    source="Government of Catalonia · wildfire perimeters",
    dataset="incendis-forestals", resolution="mapped perimeter",
    url="https://analisi.transparenciacatalunya.cat/", scale="municipality",
    scale_kind="municipality",
)
ICGC_AVALANCHE = dict(
    source="ICGC · avalanche zone map 1:25,000",
    dataset="allaus-zones", resolution="1:25,000",
    url="https://www.icgc.cat/", scale="municipality", scale_kind="municipality",
)

_CATALAN_INDICATORS = [
    ("flood_episodes", "Flood episodes that affected the municipality", "1902-2020",
     "count of AGORA episodes listing this municipality",
     {"unit": "episodes", "provenance": AGORA}),
    ("fires_count", "Wildfires recorded in the municipality", "2011 to today",
     "fires the Government of Catalonia lists for this municipality. Shown, not "
     "scored: counting fires ranks the towns with the most roadside grass first",
     {"unit": "fires", "provenance": GENCAT_FIRE}),
    ("burnt_ha", "Forest area burnt inside the municipality", "2011 to today",
     "sum of the forest hectares of those fires; this is what the wildfire-history "
     "score is built on",
     {"unit": "ha", "provenance": GENCAT_FIRE}),
    ("avalanche_zones", "Mapped avalanche zones in the municipality", "ICGC, as published",
     "avalanche zones whose centre falls inside the municipality. It says how much "
     "avalanche terrain was mapped here, never that a given house stands in one",
     {"unit": "zones", "provenance": ICGC_AVALANCHE}),
]


def buildings(code: str, zone: str | None = None, limit: int = 200,
              offset: int = 0) -> dict:
    """The exposed buildings of a municipality, worst zone first.

    Each one carries the coordinates the report takes as a query, which is the whole
    point of the drill-down: from a ranked town to a building to its own report.
    """
    exp = exposure(code)
    if not exp:
        return {"available": False, "total": 0, "rows": []}
    rows = exp.get("exposed") or []
    if zone:
        rows = [b for b in rows if b["zone"] == zone]
    total = len(rows)
    page = rows[max(0, offset):max(0, offset) + max(1, min(limit, 1000))]
    return {
        "available": True, "code": exp["code"], "name": exp["name"],
        "total": total, "offset": offset, "rows": page,
        "zones": exp["flood"]["by_zone"], "meta": exp["meta"],
    }
