"""Physical indicator -> 0-100 score.

Every breakpoint lives here, in plain sight and with its rationale. These thresholds
are an informed product judgement, not a physical law: a temperate European climate
sits at 20-45 and a recognisable extreme (Phoenix in summer, the Sahel) reaches
80-100. They are published so they can be argued with.

Annualised metrics (days a year) can approach 365 when they are computed over a
seasonal window ("a whole year of Augusts"). That is why the top bands of `heat` and
`wildfire` reach 365 and 250: without that headroom Seville in August and Phoenix all
year would both score 100 and the scale would stop discriminating where it matters.
"""

from __future__ import annotations

LEVELS = [
    (0, 20, "very low"),
    (20, 40, "low"),
    (40, 60, "moderate"),
    (60, 80, "high"),
    (80, 101, "very high"),
]

# metric -> list of (value, score), linearly interpolated between breakpoints
BREAKPOINTS: dict[str, list[tuple[float, float]]] = {
    # days a year with a maximum temperature of 35 °C or more
    "heat": [(0, 0), (1, 12), (5, 30), (15, 50), (30, 66), (60, 80), (100, 90),
             (180, 96), (365, 100)],
    # RX1day: rain on the wettest day of a typical year, in mm
    "rain": [(10, 0), (25, 15), (40, 30), (60, 50), (85, 68), (120, 85), (180, 100)],
    # days a year with high fire-danger weather
    "wildfire": [(0, 0), (2, 12), (8, 30), (20, 50), (40, 70), (70, 85), (120, 93),
                 (250, 100)],
}

# --- Official sources ------------------------------------------------------------------
# These scales come from official categories or counts of real events, and they are
# here for the same reason as the ones above: so they can be read and argued with.
BREAKPOINTS.update({
    # Smallest sea-level rise (m) that puts the point under water. The LOWER, the
    # worse: 0.077 m is ICGC's lowest layer.
    "sea_level": [(0.0, 95), (0.08, 90), (0.2, 75), (0.4, 58), (0.6, 45), (0.85, 32)],
    # Flood episodes that affected the municipality, 1902-2020 (AGORA). Capped at 60:
    # it is a MUNICIPAL figure. A big city shows up in almost every regional episode,
    # and that count must not dominate a street that lies outside every flood zone.
    "flood_history": [(0, 0), (1, 8), (3, 18), (10, 32), (25, 45), (50, 55), (100, 60)],
    # Fires with a mapped perimeter less than 5 km away since 1986.
    "fire_history": [(0, 0), (1, 18), (3, 35), (6, 52), (12, 68), (25, 82), (50, 92)],
})

# ThinkHazard! is REGIONAL: its "high" describes a whole province, not a street. Its
# top level stays at 70 and never reaches "very high", which is reserved for data about
# the point. At country level it does not score.
THINKHAZARD_SCORES = {"HIG": 70, "MED": 45, "LOW": 22, "VLO": 6}


def score_thinkhazard(level: str | None, scope: str | None) -> float | None:
    if not level or scope == "country":
        return None
    return THINKHAZARD_SCORES.get(level)


# Official flood zones (SNCZI). The most severe zone containing the point wins.
FLOOD_ZONE_SCORES = {
    "zfp": 92,   # preferential flow zone: legally restricts building
    "t10": 88,
    "t50": 78,
    "t100": 66,
    "t500": 42,
    # Coastal (IGN water depth): same weight as its river equivalent.
    "marine_t100": 66,
    "marine_t500": 42,
}

# Being INSIDE a burnt perimeter is worse than any nearby count.
FIRE_INSIDE_FLOOR = 60


# --- Avalanches --------------------------------------------------------------------
# ICGC's avalanche zone map (Catalan Pyrenees, 1:25,000). Being inside a mapped path is
# the strongest statement available; distance to the nearest path and avalanches
# observed nearby only set floors.
AVALANCHE_ZONE_SCORES = {1: 90,   # "zona de circulació preferent": a defined avalanche path
                         2: 75}   # "zona de difícil individualització": avalanche slopes
# Nearest mapped avalanche zone (m) -> score, when the point is outside all of them.
AVALANCHE_DISTANCE = [(100, 55), (300, 40), (1000, 22)]
# An observed or surveyed avalanche that reached within this distance sets a floor.
AVALANCHE_REACHED_M = 100
AVALANCHE_REACHED_FLOOR = 60
# Observed avalanches within 1 km (count) -> floor: active avalanche terrain nearby.
AVALANCHE_OBSERVED_FLOORS = [(10, 35), (1, 25)]
# Outside ICGC's map there is only a proxy (steep slopes + snowfall): like the
# regional levels, it never goes above "high".
AVALANCHE_PROXY_MAX = 60


def score_avalanche_distance(distance_m: float | None) -> float | None:
    if distance_m is None:
        return None
    return next((s for d, s in AVALANCHE_DISTANCE if distance_m <= d), None)


def score_flood_zones(inside: list[str]) -> float:
    return float(max((FLOOD_ZONE_SCORES[k] for k in inside if k in FLOOD_ZONE_SCORES), default=0))


def interpolate(value: float | None, breakpoints: list[tuple[float, float]]) -> float | None:
    if value is None:
        return None
    lo_v, lo_s = breakpoints[0]
    if value <= lo_v:
        return lo_s
    for (v0, s0), (v1, s1) in zip(breakpoints, breakpoints[1:]):
        if value <= v1:
            span = v1 - v0
            frac = 0.0 if span == 0 else (value - v0) / span
            return round(s0 + frac * (s1 - s0), 1)
    return breakpoints[-1][1]


def score_for(hazard_key: str, value: float | None) -> float | None:
    bps = BREAKPOINTS.get(hazard_key)
    if bps is None or value is None:
        return None
    return interpolate(value, bps)


def level_for(score: float | None) -> str:
    if score is None:
        return "no data"
    for lo, hi, name in LEVELS:
        if lo <= score < hi:
            return name
    return "very high"


def aggregate(scores: list[float]) -> float:
    """Overall score: the worst hazard rules and the next ones only push up a little.

    An arithmetic mean would be a product mistake: a place with wildfire risk 90 and
    everything else at 10 is not a "risk 23" place.
    """
    valid = sorted((s for s in scores if s is not None), reverse=True)
    if not valid:
        return 0.0
    top = valid[0]
    headroom = 1.0 - top / 100.0
    bonus = sum(w * s * headroom for w, s in zip((0.15, 0.07, 0.04), valid[1:4]))
    return round(min(100.0, top + bonus), 1)


def explain_breakpoints(hazard_key: str) -> list[dict]:
    """Published through the API so anyone can see the scale that was applied."""
    return [{"value": v, "score": s} for v, s in BREAKPOINTS.get(hazard_key, [])]
