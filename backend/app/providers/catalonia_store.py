"""Queries on the Catalan batch layer (data already downloaded).

Built by `backend/scripts/catalonia_build.py` and only read here: everything is local,
so it answers in milliseconds and works offline.

All geometry is in ETRS89 UTM 31N (EPSG:25831), the sources' own system: the point is
projected once and everything works in metres.
"""

from __future__ import annotations

import gzip
import json
import re
from functools import lru_cache
from pathlib import Path

from .. import config, geo


class CataloniaStore:
    def __init__(self, base_dir: Path):
        self.base = Path(base_dir)

    def _read(self, name: str):
        path = self.base / name
        if not path.exists():
            return None
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)

    @property
    def manifest(self) -> dict:
        path = self.base / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    @property
    def available(self) -> bool:
        return (self.base / "municipalities.json.gz").exists()

    @property
    def municipalities(self) -> list[dict]:
        if not hasattr(self, "_munis"):
            self._munis = self._read("municipalities.json.gz") or []
        return self._munis

    @property
    def agora(self) -> dict:
        if not hasattr(self, "_agora"):
            self._agora = self._read("agora_episodes.json.gz") or {"episodes": {}, "by_municipality": {}}
        return self._agora

    @property
    def fires(self) -> list[dict]:
        if not hasattr(self, "_fires"):
            self._fires = self._read("fire_perimeters.json.gz") or []
        return self._fires

    @property
    def fire_stats(self) -> dict:
        if not hasattr(self, "_stats"):
            self._stats = self._read("fire_stats.json.gz") or {}
        return self._stats

    def municipality_at(self, lat: float, lon: float, tolerance_m: float = 1500) -> dict | None:
        """Catalan municipality of the point, or None outside Catalonia.

        It also decides whether the Catalan sources are switched on. Municipal polygons
        end at the coastline, so a point on the beachfront can fall "outside Catalonia":
        if the point is inside no municipality, the nearest one within `tolerance_m` is
        assigned, and that is stated.
        """
        x, y = geo.utm_forward(lat, lon)
        nearest, nearest_d = None, float("inf")
        for m in self.municipalities:
            if not geo.bbox_near(m["bbox"], x, y, tolerance_m):
                continue
            polys = _as_polys(m["polygons"])
            if geo.point_in_multipolygon(x, y, polys):
                return {**_public(m), "match": "inside", "distance_m": 0}
            d = geo.distance_to_polygons(x, y, polys)
            if d < nearest_d:
                nearest, nearest_d = m, d
        if nearest is not None and nearest_d <= tolerance_m:
            return {**_public(nearest), "match": "nearest", "distance_m": round(nearest_d)}
        return None

    def flood_episodes(self, municipality_code: str) -> list[dict]:
        ids = self.agora["by_municipality"].get(municipality_code, [])
        episodes = [self.agora["episodes"][i] for i in ids if i in self.agora["episodes"]]
        return sorted(episodes, key=lambda e: e.get("start") or "", reverse=True)

    def fires_near(self, lat: float, lon: float, radius_m: float,
                   with_geometry: bool = False) -> list[dict]:
        """Fires whose perimeter lies less than `radius_m` from the point.

        The distance is to the edge of the perimeter, not to its centre: a huge fire
        whose centre is 8 km away may have come within 500 m of the house.
        """
        x, y = geo.utm_forward(lat, lon)
        out = []
        for fire in self.fires:
            if not geo.bbox_near(fire["bbox"], x, y, radius_m):
                continue
            d = geo.distance_to_polygons(x, y, _as_polys(fire["polygons"]))
            if d <= radius_m:
                item = {
                    "code": fire["code"], "year": fire["year"], "date": fire["date"],
                    "municipality": fire["municipality"], "area_ha": fire["area_ha"],
                    "distance_m": round(d), "inside": d == 0,
                }
                if with_geometry:
                    item["polygons"] = to_latlon(fire["polygons"], tolerance_m=25)
                out.append(item)
        return sorted(out, key=lambda f: (f["distance_m"], -(f["year"] or 0)))

    def municipal_fire_stats(self, municipality_code: str) -> list[dict]:
        return self.fire_stats.get(municipality_code, [])

    @property
    def avalanche_data(self) -> dict:
        if not hasattr(self, "_aval"):
            self._aval = self._read("avalanches.json.gz") or {
                "zones": [], "observations": [], "surveys": [], "nivo_zones": []}
        return self._aval

    def avalanches_near(self, lat: float, lon: float, radius_m: float = 1000,
                        with_geometry: bool = False) -> dict | None:
        """ICGC avalanche data around the point; None if the layer is not built.

        Distances are to the edge of each outline (0 = inside). `nivo_zone` is the
        snow-climate zone containing the point: the zones of ICGC's daily avalanche
        bulletin. No zone means the point is outside the mountains ICGC maps.
        """
        data = self.avalanche_data
        if not data["zones"]:
            return None
        x, y = geo.utm_forward(lat, lon)

        def near(items):
            out = []
            for it in items:
                if not geo.bbox_near(it["bbox"], x, y, radius_m):
                    continue
                d = geo.distance_to_polygons(x, y, _as_polys(it["polygons"]))
                if d <= radius_m:
                    out.append((d, it))
            return sorted(out, key=lambda t: t[0])

        def item(d, it, **extra):
            out = {"code": it.get("code"), "distance_m": round(d), "inside": d == 0, **extra}
            if with_geometry:
                out["polygons"] = to_latlon(it["polygons"], tolerance_m=10)
            return out

        nivo = next((z["name"] for z in data["nivo_zones"]
                     if geo.bbox_near(z["bbox"], x, y, 0)
                     and geo.point_in_multipolygon(x, y, _as_polys(z["polygons"]))), None)
        return {
            "radius_m": radius_m,
            "zones": [item(d, it, type=it["type"]) for d, it in near(data["zones"])],
            "observations": [item(d, it, year=it.get("year")) for d, it in near(data["observations"])],
            "surveys": [item(d, it) for d, it in near(data["surveys"])],
            "nivo_zone": nivo,
        }

    def municipality_outline(self, code: str) -> list | None:
        """Outline of the municipality in degrees, simplified to 30 m."""
        m = next((m for m in self.municipalities if m["code"] == code), None)
        return to_latlon(m["polygons"], tolerance_m=30) if m else None


def to_latlon(raw, tolerance_m: float = 25) -> list:
    """EPSG:25831 polygons -> [[[lat, lon], ...], ...] per ring, simplified for drawing."""
    out = []
    for rings in raw:
        poly = []
        for ring in rings:
            pts = geo.simplify([(p[0], p[1]) for p in ring], tolerance_m)
            poly.append([[round(la, 5), round(lo, 5)]
                         for la, lo in (geo.utm_inverse(x, y) for x, y in pts)])
        out.append(poly)
    return out


def _as_polys(raw) -> list[list[list[tuple[float, float]]]]:
    return [[[(p[0], p[1]) for p in ring] for ring in rings] for rings in raw]


def _public(m: dict) -> dict:
    """A municipality as the reports name it. Catalan writes the article in lower case
    ("el Masnou"); English text opens the name with a capital ("El Masnou")."""
    out = {k: m[k] for k in ("code", "name", "comarca", "province")}
    out["name"] = out["name"][:1].upper() + out["name"][1:]
    return out


@lru_cache(maxsize=1)
def store() -> CataloniaStore:
    return CataloniaStore(config.CATALONIA_DIR)


def parse_losses(raw) -> float | None:
    """AGORA's losses field to euros.

    The field is text with mixed formats ("1858716,06", "994 M Euros (2015)"). The
    unambiguous ones are parsed and None is returned for the rest, rather than an
    invented number.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    millions = re.match(r"^\s*([\d.,]+)\s*M\s*(?:€|Euros?)?", text, re.I)
    if millions:
        value = _to_float(millions.group(1))
        return None if value is None else value * 1_000_000
    if re.fullmatch(r"[\d.,]+", text):
        return _to_float(text)
    return None


def _to_float(text: str) -> float | None:
    """Number in Spanish format: the dot separates thousands and the comma decimals."""
    t = text.strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None
