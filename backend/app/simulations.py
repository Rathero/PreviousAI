"""Simulations: the four hazards drawn by AI on a photo of the street itself.

The illustration library (media.py) shows generic scenes. For a few demo places the
report can instead show each hazard on a photo of the home's own street: the same view
with the water depth the SNCZI publishes there, or under snow with the avalanche slope
the ICGC maps. The provenance contract still applies:

  1. The DATA write the prompt. Each risk's prompt is built from the report's own values
     (the water depth, the distance to the nearest recorded fire or avalanche zone, the
     heat record) at the tile's level. That level is recorded with the clip, and when the
     report's level changes the simulation stops being shown.
  2. It says what it is: an AI simulation on a photo of this street, not a forecast and
     not a picture of any real event.
  3. It is generated ONCE, in batch, by backend/scripts/fal_place.py, into
     data/media/places. A report only looks it up.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config
from .geo import haversine_km
from .media import VIDEO_NEGATIVE, flood_depth

LIBRARY_DIR = config.MEDIA_DIR / "places"
MANIFEST = LIBRARY_DIR / "manifest.json"
URL_PREFIX = "/media/places/"

# A report within this distance of a place uses its photo: the same stretch of street.
RADIUS_M = 150

PLACES = {
    "vielha-avinguda-garona": {
        "label": "Avinguda Garona, Vielha",
        "query": "Avinguda Garona 10, Vielha",
        "lat": 42.7047685, "lon": 0.7972837,
        "credit": "Photo © Google Street View, edited by AI",
    },
}

LEVELS = ("very low", "low", "moderate", "high", "very high")

SIMULATION_LIMITATION = (
    "An AI simulation drawn on a photo of this street: the scene is invented, the value that "
    "chose it is not. It is not a forecast and not a picture of any real event.")

KEEP = ("Keep the camera position, the framing, the road, the buildings, the trees, the "
        "railings and the mountains exactly as they are, and change only what the scene "
        "needs. Do not add any text, signs or people. Photorealistic, natural colours.")
STATIC = ("The camera is completely static. The road, the buildings and the mountains do not "
          "move or change shape.")


# --------------------------------------------------------------------------- #
# The report's values that write each prompt
# --------------------------------------------------------------------------- #
def _card(report: dict, key: str) -> dict | None:
    return next((h for h in report.get("hazards", []) if h["key"] == key), None)


def _indicator(report: dict, card_key: str, key: str) -> dict | None:
    ind = next((i for i in (_card(report, card_key) or {}).get("indicators", [])
                if i.get("key") == key), None)
    return ind if ind and isinstance(ind.get("value"), (int, float)) else None


def _distance(km: float) -> str:
    return f"{round(km * 1000, -1):.0f} m" if km < 1 else f"{km:.1f} km"


def _chosen(ind: dict | None, shown: str | None, tile: dict) -> dict:
    return {"label": ind["label"] if ind else tile["label"], "shown": shown,
            "rule": f"{tile['label']} level {tile['level']} ({tile['score']}/100)",
            "source": ((ind or {}).get("provenance") or {}).get("source")}


def _water_line(depth: float) -> str:
    """Where the surface sits on things every street has: the image model keeps them dry
    unless told exactly where the waterline crosses them."""
    if depth < 0.15:
        return ("a thin sheet of muddy water a few centimetres deep covers the road up to the "
                "kerbs; the pavements stay dry")
    if depth < 0.4:
        return ("muddy brown floodwater about 30 cm deep covers the road and the pavements, up to "
                "the middle of the wheels of any parked car")
    if depth < 0.8:
        return ("muddy brown floodwater about 60 cm deep covers the road and the pavements, up to "
                "the top of the wheels of parked cars and halfway up the railings")
    if depth < 1.5:
        # Asked for "up to the windows" it drew half that: the waterline goes object by object.
        return (f"muddy brown floodwater whose surface is about {depth:.1f} m above the road fills "
                "the whole street. The waterline is high: on the parked cars it reaches the bottom "
                "of the side windows, so their wheels, doors, headlights and grilles are all under "
                "water and only the windows and roofs show; on the metal railings only the top "
                "rail shows above the water; the tree trunks are under water up to about 1 m")
    if depth < 2.5:
        return ("muddy brown floodwater about 2 m deep fills the whole street: parked cars and the "
                "railings are completely under water; only the upper part of the lamp posts and "
                "the trees stand out of it")
    return ("muddy brown floodwater 3 m deep or more fills the whole street: the ground floor of "
            "every building is under water up to the first-floor windows")


def flood(report: dict, tile: dict) -> dict:
    card = _card(report, "flood_zone")
    ind = flood_depth(card) if card else None
    coast = bool(ind) and ind["key"].startswith("flood_zone_marine")
    depth = ind["value"] if ind else {"very high": 1.0, "high": 0.6,
                                      "moderate": 0.3}.get(tile["level"], 0.1)
    return {
        "image": (f"Edit this street photograph into a flood. "
                  f"{'The sea has come inshore' if coast else 'The river has burst its banks'}: "
                  f"{_water_line(depth)}. The current flows along the street carrying branches "
                  f"and debris. Overcast sky, light rain. {KEEP}"),
        "motion": ("The muddy floodwater flows fast along the street with ripples, eddies and "
                   "floating branches; light rain falls on the water. " + STATIC),
        "negative": VIDEO_NEGATIVE,
        # "River water depth, 100-year flood" -> "the river water depth for the 100-year flood"
        "what": (f"{depth:.2f} m of water in the street, the "
                 f"{ind['label'].lower().replace(', ', ' for the ')} in the official maps"
                 if ind else f"a flood at this address's {tile['level']} level"),
        "chosen_by": _chosen(ind, f"{depth:.2f} m" if ind else None, tile),
    }


FIRE_SCENES = {
    "very low": "a dry summer day; there is no fire and no smoke anywhere",
    "low": ("a small forest fire on the wooded slopes in the background, about {far} away: a thin "
            "column of grey smoke rises from the trees and drifts with the wind; the town, the road "
            "and everything in the foreground are untouched, and the sky is still blue with a "
            "light haze"),
    "moderate": ("a forest fire on the wooded slopes in the background, about {far} away: a wide "
                 "column of smoke, a few flames at the tree line far away, a hazy orange light over "
                 "the town; the foreground is untouched"),
    "high": ("a wildfire burning on the slopes just beyond the town: flames along the tree line, "
             "thick smoke darkening the sky, orange light and ash in the air"),
    "very high": ("a wind-driven wildfire racing down the slopes to the edge of the town: tall "
                  "flames at the last trees, glowing embers blowing across the street, thick dark "
                  "smoke and a dusk-like orange light"),
}


def wildfire(report: dict, tile: dict) -> dict:
    level = tile["level"]
    ind = _indicator(report, "fire_history", "fire_nearest_km")
    far = _distance(ind["value"]) if ind else "a kilometre"
    calm = level == "very low"
    if calm:
        what = "no fire: at this level there is nothing to draw"
    elif ind and level in ("low", "moderate"):
        what = f"a forest fire on the slopes {far} away, as far as the nearest fire on record"
    else:
        what = f"a wildfire at this address's {level} level"
    return {
        "image": f"Edit this street photograph to show {FIRE_SCENES[level].format(far=far)}. {KEEP}",
        "motion": ("The leaves of the trees stir in a light breeze. There is no fire and no smoke. "
                   if calm else "The smoke rises slowly and drifts with the wind; the leaves of "
                                "the trees stir in the breeze. ") + STATIC,
        "negative": ", ".join([VIDEO_NEGATIVE, "fire, flames, smoke" if calm else
                               "flames in the street, burning buildings, fire in the foreground"]),
        "what": what,
        "chosen_by": _chosen(ind, far if ind else None, tile),
    }


HEAT_SCENES = {
    "very low": ("the hottest afternoon this place gets in a typical summer, still short of its "
                 "record of {record}: a strong high sun, a slightly hazy pale blue sky and a faint "
                 "heat shimmer at the far end of the asphalt; the trees and the grass stay green "
                 "and everything else stays as it is"),
    "low": ("a hot summer afternoon: a strong sun, a pale hazy sky, heat shimmer over the asphalt, "
            "some grass turning yellow"),
    "moderate": ("a very hot summer afternoon: a harsh sun, strong heat shimmer over the asphalt, "
                 "dry yellow grass, shutters and blinds closed"),
    "high": ("a heatwave afternoon: a blinding white sun, strong heat haze over the road, bleached "
             "colours, dry brown grass, wilted plants, every shutter closed"),
    "very high": ("an extreme heatwave in mid-afternoon: blinding white light, heat haze distorting "
                  "the far end of the road, scorched brown grass, wilted trees, bleached colours"),
}


def heat(report: dict, tile: dict) -> dict:
    level = tile["level"]
    ind = _indicator(report, "heat", "heat_record")
    record = f"{ind['value']:.1f} °C" if ind else "about 35 °C"
    return {
        "image": f"Edit this street photograph to show {HEAT_SCENES[level].format(record=record)}. {KEEP}",
        "motion": "Heat haze shimmers over the asphalt and the leaves stir slightly. " + STATIC,
        "negative": ", ".join([VIDEO_NEGATIVE, "fire, smoke"]),
        "what": (f"the hottest afternoon of a typical summer; the record here is {record}"
                 if level in ("very low", "low") else f"heat at this address's {level} level"),
        "chosen_by": _chosen(ind, record if ind else None, tile),
    }


AVALANCHE_SCENES = {
    "very low": "No avalanche and no sliding snow anywhere.",
    "low": ("Far away on a steep mountainside in the background, about {far} away, a small powder "
            "avalanche slides down an open gully in the forest and stops high on the slope, far "
            "above the houses."),
    "moderate": ("On the mountainside in the background, about {far} away, an avalanche runs down "
                 "a gully and stops at the foot of the slope, short of the houses; a cloud of "
                 "powder snow drifts over the forest."),
    "high": ("A large avalanche comes down the mountainside towards the edge of the town under a "
             "huge cloud of powder snow."),
    "very high": ("A large powder avalanche reaches the edge of the town, its snow cloud billowing "
                  "over the roofs."),
}


def avalanche(report: dict, tile: dict) -> dict:
    level = tile["level"]
    ind = _indicator(report, "avalanche", "avalanche_nearest_zone")
    far = _distance(ind["value"] / 1000) if ind else "a kilometre"
    calm = level == "very low"
    if calm:
        what = "a snowy winter day with no avalanche"
    elif ind and level in ("low", "moderate"):
        what = f"winter, with an avalanche on the nearest mapped avalanche slope, {far} away"
    else:
        what = f"an avalanche at this address's {level} level"
    return {
        "image": ("Edit this street photograph into a winter day after a heavy snowfall: deep snow "
                  "covers the mountains, the forest, the roofs and the ground; the road has been "
                  "cleared, with banks of snow along its edges; overcast, cold light. "
                  f"{AVALANCHE_SCENES[level].format(far=far)} {KEEP}"),
        "motion": ("A few snowflakes drift in the air. Nothing slides. " if calm else
                   "Far away on the mountainside the avalanche slides down and its powder cloud "
                   "grows, drifts and settles; a few snowflakes drift in the air. ") + STATIC,
        "negative": ", ".join([VIDEO_NEGATIVE, "avalanche, snow cloud, sliding snow" if calm else
                               "snow cloud over the street, avalanche reaching the road"]),
        "what": what,
        "chosen_by": _chosen(ind, far if ind else None, tile),
    }


SCENES = {"flood": flood, "wildfire": wildfire, "heat": heat, "avalanche": avalanche}


def scene(report: dict, tile: dict) -> dict | None:
    """The prompts a tile's data write, or None when the tile has no level."""
    if tile.get("key") not in SCENES or tile.get("level") not in LEVELS:
        return None
    return SCENES[tile["key"]](report, tile)


# --------------------------------------------------------------------------- #
# Looking a place up
# --------------------------------------------------------------------------- #
def place_at(lat: float, lon: float) -> str | None:
    return next((pid for pid, p in PLACES.items()
                 if haversine_km(lat, lon, p["lat"], p["lon"]) * 1000 <= RADIUS_M), None)


_manifest_cache: tuple[float, dict] | None = None


def manifest() -> dict:
    """{"places": {place id: {"scenes": {risk key: record}}}}, re-read when it changes."""
    global _manifest_cache
    try:
        mtime = MANIFEST.stat().st_mtime
    except OSError:
        return {"places": {}}
    if _manifest_cache and _manifest_cache[0] == mtime:
        return _manifest_cache[1]
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"places": {}}
    data.setdefault("places", {})
    _manifest_cache = (mtime, data)
    return data


def save_manifest(data: dict) -> None:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(MANIFEST)


def _file(rel: str | None) -> Path | None:
    path = LIBRARY_DIR / rel if rel else None
    return path if path and path.is_file() else None


def for_tile(report: dict, tile: dict) -> dict | None:
    """The tile's simulation, in the shape of view.py's illustrations, or None."""
    loc = report.get("location") or {}
    pid = place_at(loc["latitude"], loc["longitude"]) if "latitude" in loc else None
    rec = (manifest()["places"].get(pid) or {}).get("scenes", {}).get(tile["key"]) if pid else None
    # Drawn for another level (the data have changed since): not this tile's picture.
    if not rec or rec.get("level") != tile.get("level") or not _file(rec.get("video")):
        return None
    return {
        "kind": "simulation",
        "video": URL_PREFIX + rec["video"],
        "poster": URL_PREFIX + rec["poster"] if _file(rec.get("poster")) else None,
        "title": f"{tile['label']}: {tile['level']}",
        "caption": f"An AI simulation on a photo of this street: {rec['what']}.",
        "card": tile["label"],
        "chosen_by": rec.get("chosen_by") or {},
        "models": {"image_model": rec.get("image_model"), "video_model": rec.get("video_model")},
        "limitation": SIMULATION_LIMITATION,
        "credit": PLACES[pid]["credit"],
    }
