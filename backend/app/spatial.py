"""Point-in-polygon for thousands of points against one very big polygon set.

`geo.point_in_multipolygon` walks every edge of every ring. That is the right shape for
a report, which asks once. The national analysis asks differently: a single official
flood zone can carry twenty thousand vertices, and a municipality has thousands of
buildings to test against it. Walking the whole outline once per building is minutes of
work for an answer that only depends on the handful of edges at the building's latitude.

So the edges are filed once by the horizontal band they span, and a query only ray-casts
against the band it falls in - a hundred edges instead of twenty thousand. The result is
identical to `geo.point_in_multipolygon`: the same even-odd rule, the same ray to the
right, crossings counted per polygon so that two overlapping polygons cannot cancel each
other out.

Coordinates are whatever the caller uses (degrees here). The index is read-only once
built, so it can be reused across every building of a municipality.
"""

from __future__ import annotations

import math

Ring = list[tuple[float, float]]

# Edges per band, aimed for. Lower means more bands: faster queries, more memory.
EDGES_PER_BAND = 8
MIN_BANDS, MAX_BANDS = 16, 8192


class BandIndex:
    """Even-odd point-in-polygon over many polygons, indexed by horizontal band.

    `polygons` is a list of polygons, each a list of rings (exterior first, then
    holes), each ring a list of (x, y). Empty input answers False to everything.
    """

    __slots__ = ("bands", "y0", "height", "count", "bbox", "_edges")

    def __init__(self, polygons: list[list[Ring]]):
        edges: list[tuple[float, float, float, float, int]] = []
        for poly_id, rings in enumerate(polygons):
            for ring in rings:
                for i in range(len(ring)):
                    x1, y1 = ring[i - 1]
                    x2, y2 = ring[i]
                    if y1 != y2:  # horizontal edges never cross a horizontal ray
                        edges.append((x1, y1, x2, y2, poly_id))
        self.count = len(edges)
        self._edges = edges
        if not edges:
            self.bands, self.y0, self.height, self.bbox = [], 0.0, 1.0, None
            return

        xs = [e[0] for e in edges] + [e[2] for e in edges]
        ys = [e[1] for e in edges] + [e[3] for e in edges]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))
        self.y0 = self.bbox[1]
        span = self.bbox[3] - self.bbox[1]
        n = max(MIN_BANDS, min(MAX_BANDS, len(edges) // EDGES_PER_BAND or 1))
        self.height = (span / n) if span > 0 else 1.0
        self.bands = [[] for _ in range(n + 1)]
        for e in edges:
            lo = self._band(min(e[1], e[3]))
            hi = self._band(max(e[1], e[3]))
            for b in range(lo, hi + 1):
                self.bands[b].append(e)

    def _band(self, y: float) -> int:
        if not self.bands:
            return 0
        b = int((y - self.y0) / self.height)
        return 0 if b < 0 else (len(self.bands) - 1 if b >= len(self.bands) else b)

    def contains(self, x: float, y: float) -> bool:
        """Whether the point falls inside any of the polygons."""
        if self.bbox is None:
            return False
        minx, miny, maxx, maxy = self.bbox
        if not (minx <= x <= maxx and miny <= y <= maxy):
            return False
        crossings: dict[int, int] = {}
        for x1, y1, x2, y2, poly_id in self.bands[self._band(y)]:
            if (y1 > y) != (y2 > y):
                x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if x < x_cross:
                    crossings[poly_id] = crossings.get(poly_id, 0) + 1
        return any(c % 2 for c in crossings.values())

    def busiest_band(self) -> int:
        """How many edges the fullest band holds: what a query costs at worst."""
        return max((len(b) for b in self.bands), default=0)


def rings_from_geojson(geometry: dict | None) -> list[list[Ring]]:
    """GeoJSON Polygon or MultiPolygon -> the list-of-polygons shape used here."""
    if not geometry:
        return []
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "Polygon":
        return [[[(float(x), float(y)) for x, y, *_ in ring] for ring in coords]]
    if kind == "MultiPolygon":
        return [[[(float(x), float(y)) for x, y, *_ in ring] for ring in poly]
                for poly in coords]
    return []


def bbox_overlaps(a: tuple[float, float, float, float] | None,
                  b: tuple[float, float, float, float] | None) -> bool:
    if a is None or b is None:
        return False
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def haversine_area_km2(bbox: tuple[float, float, float, float]) -> float:
    """Rough area of a lon/lat bbox, for reporting how much ground a query covered."""
    w, s, e, n = bbox
    mid = math.radians((s + n) / 2)
    return abs(e - w) * 111.32 * math.cos(mid) * abs(n - s) * 110.57
