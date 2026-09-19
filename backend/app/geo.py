"""Pure-Python geometry: UTM projection and point-in-polygon operations.

No shapely or pyproj: the API installs anywhere without compiling anything, and only
a handful of operations on already-projected polygons are needed. The projection
matches pyproj to the millimetre.

Convention: projected coordinates are (easting, northing) in metres; geographic ones
are (lat, lon) in degrees.
"""

from __future__ import annotations

import math

# GRS80, the ETRS89 ellipsoid. ETRS89 and WGS84 differ by less than a metre in Europe.
_A = 6378137.0
_F = 1 / 298.257222101


def utm_forward(lat: float, lon: float, zone: int = 31) -> tuple[float, float]:
    """(lat, lon) in degrees -> (easting, northing) in metres, northern-hemisphere UTM.

    Krüger series to third order: error below a millimetre inside the zone. Catalonia
    lies entirely in zone 31 (EPSG:25831).
    """
    k0, false_e = 0.9996, 500000.0
    lon0 = math.radians(-183.0 + 6.0 * zone)
    n = _F / (2 - _F)
    big_a = _A / (1 + n) * (1 + n * n / 4 + n ** 4 / 64)
    alphas = (
        n / 2 - 2 * n * n / 3 + 5 * n ** 3 / 16,
        13 * n * n / 48 - 3 * n ** 3 / 5,
        61 * n ** 3 / 240,
    )
    phi, dlam = math.radians(lat), math.radians(lon) - lon0
    c = 2 * math.sqrt(n) / (1 + n)
    t = math.sinh(math.atanh(math.sin(phi)) - c * math.atanh(c * math.sin(phi)))
    xi = math.atan(t / math.cos(dlam))
    eta = math.atanh(math.sin(dlam) / math.sqrt(1 + t * t))
    easting = eta + sum(a * math.cos(2 * j * xi) * math.sinh(2 * j * eta)
                        for j, a in enumerate(alphas, start=1))
    northing = xi + sum(a * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
                        for j, a in enumerate(alphas, start=1))
    return false_e + k0 * big_a * easting, k0 * big_a * northing


def utm_inverse(easting: float, northing: float, zone: int = 31) -> tuple[float, float]:
    """Northern-hemisphere UTM (easting, northing) -> (lat, lon) in degrees."""
    k0, false_e = 0.9996, 500000.0
    lon0 = math.radians(-183.0 + 6.0 * zone)
    n = _F / (2 - _F)
    big_a = _A / (1 + n) * (1 + n * n / 4 + n ** 4 / 64)
    betas = (
        n / 2 - 2 * n * n / 3 + 37 * n ** 3 / 96,
        n * n / 48 + n ** 3 / 15,
        17 * n ** 3 / 480,
    )
    deltas = (
        2 * n - 2 * n * n / 3 - 2 * n ** 3,
        7 * n * n / 3 - 8 * n ** 3 / 5,
        56 * n ** 3 / 15,
    )
    xi = northing / (k0 * big_a)
    eta = (easting - false_e) / (k0 * big_a)
    xi_p = xi - sum(b * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
                    for j, b in enumerate(betas, start=1))
    eta_p = eta - sum(b * math.cos(2 * j * xi) * math.sinh(2 * j * eta)
                      for j, b in enumerate(betas, start=1))
    chi = math.asin(math.sin(xi_p) / math.cosh(eta_p))
    phi = chi + sum(d * math.sin(2 * j * chi) for j, d in enumerate(deltas, start=1))
    lam = lon0 + math.atan2(math.sinh(eta_p), math.cos(xi_p))
    return math.degrees(phi), math.degrees(lam)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial compass bearing from point 1 to point 2, 0-360 degrees."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


# --------------------------------------------------------------------------- #
# Polygons: a list of rings, each ring a list of (x, y). The first one is the exterior
# and the rest are holes. Winding order does not matter.
# --------------------------------------------------------------------------- #
Ring = list[tuple[float, float]]


def _in_ring(x: float, y: float, ring: Ring) -> bool:
    """Even-odd rule with a horizontal ray to the right."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            x_cross = xi + (y - yi) * (xj - xi) / (yj - yi)
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def point_in_polygon(x: float, y: float, rings: list[Ring]) -> bool:
    """Inside the exterior and outside every hole."""
    if not rings or not _in_ring(x, y, rings[0]):
        return False
    return not any(_in_ring(x, y, hole) for hole in rings[1:])


def point_in_multipolygon(x: float, y: float, polygons: list[list[Ring]]) -> bool:
    return any(point_in_polygon(x, y, rings) for rings in polygons)


def _dist_to_segment(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_to_polygons(x: float, y: float, polygons: list[list[Ring]]) -> float:
    """Distance from the point to the nearest edge; 0 if it is inside."""
    if point_in_multipolygon(x, y, polygons):
        return 0.0
    best = math.inf
    for rings in polygons:
        for ring in rings:
            for i in range(len(ring)):
                ax, ay = ring[i - 1]
                bx, by = ring[i]
                d = _dist_to_segment(x, y, ax, ay, bx, by)
                if d < best:
                    best = d
    return best


def ring_area(ring: Ring) -> float:
    """Area (shoelace formula), always positive."""
    s = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i - 1]
        x2, y2 = ring[i]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def polygon_area(rings: list[Ring]) -> float:
    if not rings:
        return 0.0
    return max(0.0, ring_area(rings[0]) - sum(ring_area(h) for h in rings[1:]))


def bbox_of(polygons: list[list[Ring]]) -> tuple[float, float, float, float]:
    xs = [x for rings in polygons for ring in rings for x, _ in ring]
    ys = [y for rings in polygons for ring in rings for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_near(bbox, x: float, y: float, margin: float) -> bool:
    minx, miny, maxx, maxy = bbox
    return minx - margin <= x <= maxx + margin and miny - margin <= y <= maxy + margin


def simplify(ring: Ring, tolerance: float) -> Ring:
    """Douglas-Peucker. Always keeps the first and last vertex.

    With a 10 m tolerance an edge moves by at most 10 m, which is invisible to a
    street-scale query and divides the size of the stored perimeters.
    """
    if len(ring) <= 4 or tolerance <= 0:
        return list(ring)

    keep = [False] * len(ring)
    keep[0] = keep[-1] = True
    stack = [(0, len(ring) - 1)]
    while stack:
        start, end = stack.pop()
        ax, ay = ring[start]
        bx, by = ring[end]
        worst, index = 0.0, None
        for i in range(start + 1, end):
            d = _dist_to_segment(ring[i][0], ring[i][1], ax, ay, bx, by)
            if d > worst:
                worst, index = d, i
        if index is not None and worst > tolerance:
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))
    out = [p for p, k in zip(ring, keep) if k]
    # A ring needs at least three distinct vertices to have an area.
    return out if len(out) >= 4 else list(ring)
