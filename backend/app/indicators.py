"""The traceability contract.

No number leaves the backend without saying where it comes from, for which period, at
what resolution and how it was calculated. Commercial climate-risk scores disagree
with each other and cannot be audited; these can.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Confidence = Literal["high", "medium", "low"]


@dataclass
class Provenance:
    source: str
    dataset: str
    period: str
    resolution: str
    method: str
    confidence: Confidence = "medium"
    url: str | None = None
    # At what scale the value describes this place: the label people see ("point",
    # "municipality", "~9 km grid", "1 km radius", "province") and its kind.
    scale: str | None = None
    scale_kind: str | None = None  # point | municipality | grid | radius | region | country


@dataclass
class Indicator:
    key: str
    label: str
    value: float | None
    unit: str
    provenance: Provenance
    # Slope per decade (linear regression over the annual aggregates).
    trend_per_decade: float | None = None
    trend_significant: bool | None = None
    context: str | None = None
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["provenance"] = asdict(self.provenance)
        return d


# Reusable sources ------------------------------------------------------------------

ERA5 = dict(
    source="ERA5 / ERA5-Land (Copernicus C3S) via Open-Meteo Archive API",
    dataset="era5-land",
    resolution="~9 km (ERA5-Land) over land, 0.25 degrees (ERA5) elsewhere",
    url="https://open-meteo.com/en/docs/historical-weather-api",
    scale="~9 km grid",
    scale_kind="grid",
)

CMIP6 = dict(
    source="CMIP6 HighResMIP, downscaled to 10 km and bias-corrected against ERA5 (Open-Meteo Climate API)",
    dataset="cmip6-highresmip",
    resolution="10 km (statistical downscaling)",
    url="https://open-meteo.com/en/docs/climate-api",
    scale="~10 km grid",
    scale_kind="grid",
)

MITECO_SNCZI = dict(
    source="Spain's National Flood Zone Mapping System (SNCZI, MITECO), via WFS",
    dataset="snczi-laminas",
    resolution="official polygons at plot scale",
    url="https://gis.miteco.gob.es/geoserver/agua/ows",
    scale="point",
    scale_kind="point",
)

IGN_SNCZI = dict(
    source="SNCZI · river and coastal flood depths, via the IGN INSPIRE WMS",
    dataset="ign-inspire-nz-flood",
    resolution="water-depth raster for the studied river stretches",
    url="https://servicios.idee.es/wms-inspire/riesgos-naturales/inundaciones",
    scale="point",
    scale_kind="point",
)

ICGC_SLR = dict(
    source="ICGC (Catalan Cartographic and Geological Institute) · permanent flooding from sea-level rise, via WMS",
    dataset="icgc-inundacio-litoral-1x1",
    resolution="1 × 1 m LiDAR terrain model (root-mean-square error 15 cm)",
    url="https://www.icgc.cat/ca/Ambits-tematics/Ambit-litoral/Aplicacions-i-visors/Inundacio-permanent-la-pujada-del-nivell-del-mar",
    scale="point",
    scale_kind="point",
)

AGORA_UB = dict(
    source="AGORA · GAMA group, University of Barcelona (with the Catalan Water Agency)",
    dataset="agora-episodis",
    resolution="municipal",
    url="https://agora.ub.edu/",
    scale="municipality",
    scale_kind="municipality",
)

GENCAT_FIRE_PERIMETERS = dict(
    source="Government of Catalonia · Department of Agriculture · wildfire perimeters",
    dataset="gencat-incendis-perimetres",
    resolution="perimeters simplified to 10 m (ETRS89 UTM 31N)",
    url="https://agricultura.gencat.cat/ca/serveis/cartografia-sig/bases-cartografiques/boscos/incendis-forestals/",
    scale="5 km radius",
    scale_kind="radius",
)

GENCAT_FIRE_STATS = dict(
    source="Government of Catalonia · Department of Agriculture · wildfires by municipality (open data)",
    dataset="gencat-incendis-socrata",
    resolution="municipal, no geometry",
    url="https://analisi.transparenciacatalunya.cat/Medi-Rural-Pesca/Incendis-forestals-a-Catalunya-Anys-2011-2024/bks7-dkfd",
    scale="municipality",
    scale_kind="municipality",
)

CDS_ERA5 = dict(
    source="ERA5 (Copernicus C3S) via Climate Data Store",
    dataset="derived-era5-single-levels-daily-statistics",
    resolution="0.25 degrees (~28 km)",
    url="https://cds.climate.copernicus.eu/datasets/derived-era5-single-levels-daily-statistics",
    scale="~28 km grid",
    scale_kind="grid",
)

THINKHAZARD = dict(
    source="ThinkHazard! · GFDRR (World Bank), by administrative region",
    dataset="thinkhazard",
    resolution="administrative region (province, state or country)",
    url="https://thinkhazard.org/",
    scale="province or region",
    scale_kind="region",
)

CDS_FIRE_PROJ = dict(
    source="Fire danger indicators for Europe (FWI, EURO-CORDEX) via Climate Data Store",
    dataset="sis-tourism-fire-danger-indicators",
    resolution="~12 km (EURO-CORDEX 0.11 degrees)",
    url="https://cds.climate.copernicus.eu/datasets/sis-tourism-fire-danger-indicators",
    scale="~12 km grid",
    scale_kind="grid",
)

TERRAIN = dict(
    source="Copernicus DEM GLO-90 via Open-Meteo Elevation API",
    dataset="copernicus-dem-glo90",
    resolution="90 m",
    url="https://open-meteo.com/en/docs/elevation-api",
    scale="500 m surroundings",
    scale_kind="point",
)

ICGC_AVALANCHE_ZONES = dict(
    source="ICGC · Mapa de zones d'allaus de Catalunya 1:25,000 (Catalan avalanche database, BDAC), via WFS",
    dataset="icgc-nivoallaus-zonesallaus",
    resolution="1:25,000, polygons simplified to 10 m",
    url="https://www.icgc.cat/en/Geoinformation-and-Maps/Data-and-products/Geologic-and-geophysical-geoinformation/Geological-risks-cartography/Map-avalanche-zones-Catalonia-125000",
    scale="point",
    scale_kind="point",
)

ICGC_AVALANCHE_EVENTS = dict(
    source="ICGC · Base de Dades d'Allaus de Catalunya (observed and surveyed avalanches), via WFS",
    dataset="icgc-nivoallaus-observacions",
    resolution="avalanche outlines simplified to 10 m",
    url="https://www.icgc.cat/en/Geoinformation-and-Maps/Data-and-products/Databases-and-catalogues/Database-avalanches-Catalonia-BDAC",
    scale="1 km radius",
    scale_kind="radius",
)

FIRESCOPE = dict(
    source="FireScope 2026 wildfire risk map · INSAIT (Markov et al., CVPR 2026), read from "
           "Hugging Face",
    dataset="firescope-risk-2026",
    resolution="30 m (Web Mercator), predicted in patches of ~10 km whose seams can show",
    url="https://firescope.ai/",
    scale="point",
    scale_kind="point",
)

GENCAT_INFOCAT = dict(
    source="Government of Catalonia · Directorate-General for Civil Protection · municipal "
           "civil protection plan obligations (INFOCAT wildfire plan), open data",
    dataset="gencat-pcivil-obligacions-infocat",
    resolution="municipal classes (static danger relative to the Catalan average; vulnerability)",
    url="https://analisi.transparenciacatalunya.cat/Seguretat/Obligacions-i-vig-ncies-dels-plans-de-protecci-civil-m/eqag-gzjs",
    scale="municipality",
    scale_kind="municipality",
)

DEEPFIRE_FIRES = dict(
    source="Deepfire · satellite hotspots grouped into fires (VIIRS, MODIS, MTG, Sentinel-3, "
           "Landsat), OGC API",
    dataset="deepfire-clusters",
    resolution="detections of 375 m (VIIRS) to 2 km (MTG); perimeters estimated from them",
    url="https://docs.deepfire.co/api/clusters",
    scale="10 km radius",
    scale_kind="radius",
)
