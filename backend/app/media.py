"""Illustrations: short generated clips that turn a hazard's number into something you can see.

"1.58 m of water" is a number people read and do not feel. A street with water up to the
top of the front door is the same number, felt. That is all these clips are for, and the
provenance contract applies to them as much as to any figure:

  1. The DATA choose the clip. The flood card picks by the SNCZI water depth at the
     point (six depth bands); heat, extreme rain, wildfire and avalanches pick by the
     card's level. The clip never changes, adds or estimates a number, and a card with
     no number to pick by gets no clip.
  2. Every clip says what it is: an AI illustration of a GENERIC scene, not a picture of
     this place and not a forecast; which models drew it, from which prompt; and which
     value chose it (`chosen_by`).
  3. They are generated ONCE, in batch, by backend/scripts/fal_media.py, and kept in
     data/media/illustrations with a manifest. A report only looks the clip up: nothing
     is generated on the user's path and there is no cost per report.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config

LIBRARY_DIR = config.MEDIA_DIR / "illustrations"
MANIFEST = LIBRARY_DIR / "manifest.json"
URL_PREFIX = "/media/illustrations/"

STYLE = ("Photorealistic documentary photograph, natural colours, eye level, wide 16:9 "
         "frame. No text, no legible signs, no logos, no watermark.")
VIDEO_NEGATIVE = ("text, captions, subtitles, watermark, logo, morphing buildings, warping, "
                  "distorted cars, blur, low quality, close-up faces")
ILLUSTRATION_LIMITATION = (
    "An AI-generated illustration of a generic scene, not a picture of this place and not "
    "a forecast. It only puts the value that chose it into human scale.")

# --------------------------------------------------------------------------- #
# Flooding: one street, six water depths
# --------------------------------------------------------------------------- #
# The same street in every band (an edit of one base image), so moving between
# reports the only thing that changes is the water. The reference objects are
# chosen for their known heights: kerb ~15 cm, wheel ~60 cm, bench seat ~45 cm,
# car window ~1 m, car roof ~1.5 m, front door ~2.1 m, first floor ~3 m.
FLOOD_BASE = {
    "id": "flood-street-base",
    "prompt": ("A quiet residential street in a small southern European town, seen from the "
               "middle of the road. On the left, a small grey hatchback parked by the kerb. On "
               "the right, a two-storey house with a wooden front door two stone steps above "
               "the pavement, a ground-floor window with iron bars and a small first-floor "
               "balcony. A green street bench on the pavement. Overcast daylight, dry asphalt, "
               "no people. " + STYLE),
}

FLOOD_MOTION = ("The floodwater flows slowly from left to right with gentle ripples and a few "
                "floating leaves; light rain falls on the water. The camera is completely "
                "static. The buildings, the car and the door do not move or change shape.")

# (from_m, to_m, suffix, how the water looks, short label)
DEPTH_BANDS = [
    (0.0, 0.15, "0", "a thin sheet of muddy water a few centimetres deep covers the road and "
                     "reaches the kerbs; the pavement is still dry", "a few centimetres"),
    (0.15, 0.4, "1", "muddy brown floodwater about 30 cm deep covers the road and the pavement, "
                     "reaches the middle of the car's wheels and laps at the first door step",
     "about 30 cm"),
    (0.4, 0.8, "2", "muddy brown floodwater about 60 cm deep: up to the top of the car's wheels, "
                    "over the bench seat, over both door steps and into the ground floor",
     "about 60 cm"),
    # The image model keeps doors and windows dry unless told exactly where the water
    # line sits on them, so the deep bands say it object by object.
    (0.8, 1.5, "3", "muddy brown floodwater whose surface is about 1.1 m above the road: the "
                    "car is submerged up to the bottom of its side windows, the bench is "
                    "completely under water, both door steps are under water and the water "
                    "covers the lower third of the wooden front door and the lower part of the "
                    "barred window", "about 1 m"),
    (1.5, 2.5, "4", "muddy brown floodwater whose surface is about 2 m above the road: the car "
                    "is completely under water, only a faint shape below the surface; the bench "
                    "cannot be seen; the water covers the wooden front door up to just below "
                    "its top, so only the top 15 cm of the door frame shows above the water, "
                    "and the barred window is under water except its top edge", "about 2 m"),
    (2.5, None, "5", "muddy brown floodwater whose surface is just below the first-floor "
                     "balcony: the whole ground floor is under water, and the front door, the "
                     "barred window, the car and the bench are completely submerged and cannot "
                     "be seen; only the first floor, the balcony with its flower pots and the "
                     "storeys above stand out of the water", "3 m or more"),
]


def _band_text(lo: float, hi: float | None) -> str:
    return f"{lo:g}–{hi:g} m" if hi is not None else f"{lo:g} m or more"


def flood_scene_id(depth_m: float) -> str:
    for lo, hi, suffix, *_ in DEPTH_BANDS:
        if depth_m >= lo and (hi is None or depth_m < hi):
            return f"flood-depth-{suffix}"
    return f"flood-depth-{DEPTH_BANDS[0][2]}"


# --------------------------------------------------------------------------- #
# Heat, extreme rain, wildfire, avalanches: one scene per level
# --------------------------------------------------------------------------- #
# Only from "moderate" up: a "low" card does not need a picture to be understood,
# and a calm scene next to it would read as reassurance nobody measured. The one
# exception is avalanches: that card only exists where there ARE steep slopes and
# snow (flat or snowless places get a note, not a card), so even its "low" scene
# shows something the data found: the terrain, quiet.
LEVEL_SLUGS = {"low": "low", "moderate": "moderate", "high": "high", "very high": "very-high"}
MIN_LEVEL = {"avalanche": "low"}
LEVEL_ORDER = ["very low", "low", "moderate", "high", "very high"]

LEVEL_SCENES = {
    "heat": {
        "motion": "Heat haze shimmers over the asphalt and leaves stir slightly. A very slow "
                  "push-in. Nothing else changes.",
        "moderate": ("A sunny summer afternoon on a tree-lined street in a southern European "
                     "city: bright sun, people walking on the shady side, café awnings open, "
                     "a few sun hats. " + STYLE),
        # No person in this one: a lone figure in a heatwave trips content checkers
        # (it reads as someone collapsing).
        "high": ("A heatwave afternoon in a southern European city: an almost empty street "
                 "under a harsh white sun, window shutters closed, awnings pulled down, heat "
                 "haze rising from the asphalt, a stone drinking fountain in the shade of a "
                 "plane tree. " + STYLE),
        "very high": ("Extreme heat in a city in mid-afternoon: a deserted wide avenue under "
                      "blinding white light, strong heat shimmer distorting the far end of the "
                      "road, wilted plants, shade sails stretched over the pavement, bleached "
                      "colours. " + STYLE),
    },
    "rain": {
        "motion": "Rain falls hard and the water keeps flowing along the street. The camera "
                  "is static; the buildings do not change.",
        "moderate": ("A heavy downpour on a city street: rain bouncing off the asphalt, water "
                     "running fast along the gutters, a few people with umbrellas. " + STYLE),
        "high": ("Torrential rain in a town: the street has turned into a shallow stream "
                 "flowing over the kerbs, storm drains overflowing, a car driving slowly "
                 "through the water with spray. " + STYLE),
        "very high": ("A flash flood after a cloudburst: a fast, muddy torrent carrying branches "
                      "runs down a town street, water well above the kerbs, a car stranded in "
                      "the current, no people in the water. " + STYLE),
    },
    "wildfire": {
        "motion": "Wind moves the vegetation and the smoke drifts with it. The camera is "
                  "static; the houses do not change.",
        # The calm scenes get a calm motion: with the shared one, video models add
        # smoke to a "no fire" scene and an avalanche to a "no avalanche" one.
        "motion_by_level": {
            "moderate": "A warm wind bends the dry grass and moves the pine branches; a little "
                        "dust blows. There is no fire and no smoke anywhere. The camera is "
                        "static; the houses do not change.",
        },
        "negative_by_level": {"moderate": "fire, flames, smoke, haze"},
        "moderate": ("Dry summer hills of pine forest and yellow scrub at the edge of a village "
                     "of white houses, late afternoon, a warm wind bending the dry grass. No "
                     "fire and no smoke. " + STYLE),
        "high": ("A wildfire smoke column rising behind Mediterranean hills of Aleppo pine and "
                 "scrub above a village of white houses with terracotta roofs, hazy orange sky, "
                 "the sun a red disc through the smoke. The fire is on the far ridge, not near "
                 "the houses. " + STYLE),
        "very high": ("A wind-driven wildfire racing through Mediterranean pine forest and scrub "
                      "on a hillside just above the last white houses with terracotta roofs of "
                      "a village at dusk: tall flames, glowing embers carried by the wind, thick "
                      "smoke. " + STYLE),
    },
    "avalanche": {
        "motion": "The snow moves as described and the powder cloud grows and drifts. The "
                  "camera is static, far across the valley.",
        "motion_by_level": {
            "low": "A gentle breeze lifts a little powder snow off the ridge and thin smoke "
                   "rises from the village chimneys. Nothing slides: no avalanche, no snow "
                   "cloud. The camera is static.",
            # Loaded slopes invite an avalanche even with "nothing slides": here only the
            # camera moves, and the prompt weighs more (cfg_scale).
            "moderate": "A very slow push-in towards the village. The mountains and the snow "
                        "stay completely still; only a few snowflakes drift in the air. No "
                        "avalanche, no snow cloud.",
        },
        "cfg_by_level": {"moderate": 0.8},
        "negative_by_level": {"low": "avalanche, snow cloud, sliding snow, powder cloud",
                              "moderate": "avalanche, snow cloud, sliding snow, powder cloud"},
        "low": ("Snow-covered mountain slopes above a stone village in a Pyrenean valley on a "
                "calm, sunny winter day; the steep slopes rise some distance from the houses; "
                "old avalanche tracks are barely visible in the forest. No avalanche. " + STYLE),
        "moderate": ("Steep mountain slopes loaded with fresh snow above a valley road and a "
                     "small stone village in the Pyrenees after a heavy snowfall, cornices on "
                     "the ridge, a clear cold morning. No avalanche. " + STYLE),
        "high": ("A slab avalanche releasing on a steep snowy mountain slope, seen from across "
                 "the valley: a clean fracture line across the slope, blocks of snow starting "
                 "to slide, a powder cloud forming. Ski lifts far below. " + STYLE),
        "very high": ("A large powder avalanche running down a defined gully on a mountain "
                      "towards the valley floor, a huge billowing snow cloud, seen from a safe "
                      "distance across the valley, a road and buildings far below. " + STYLE),
    },
}

FAMILY = {"rain": "flooding", "heat": "heat", "wildfire": "wildfire", "avalanche": "avalanche"}

# Which scene set each card draws from, and how the card words it. The recorded-
# event cards (floods and fires on record) borrow the weather scenes: a generic
# downpour or dry hills, never a recreation of an episode they count.
CARD_SCENES = {
    "heat": ("heat", "What {level} extreme heat looks like",
             "Illustration for a {level} level of extreme heat, in a generic city."),
    "rain": ("rain", "What {level} extreme rain looks like",
             "Illustration for a {level} level of extreme rain, in a generic town."),
    "flood_history": ("rain", "Flood weather, illustrated",
                      "Illustration for a {level} level of recorded floods: a generic town, "
                      "not any of the episodes on record."),
    "wildfire": ("wildfire", "What {level} wildfire danger looks like",
                 "Illustration for a {level} level of fire-prone weather, in a generic place."),
    "fire_history": ("wildfire", "Wildfire country, illustrated",
                     "Illustration for a {level} level of recorded wildfires nearby: a generic "
                     "place, not any of the fires on record."),
    "avalanche": ("avalanche", "What {level} avalanche terrain looks like",
                  "Illustration for a {level} avalanche level, in a generic valley."),
}


# Asked for 2-3 m of water, the default edit model keeps the water at the door step:
# it will not submerge a door. The two deepest bands use a stricter edit model
# (config.FAL_STRICT_EDIT_MODEL), prompted with what stays visible above the waterline.
DEEP_BANDS = {
    "4": ("Edit this photograph into a severe flood. Muddy brown floodwater fills the street "
          "about 2 metres deep: the waterline crosses the wooden front door near its top, so "
          "only the top 15 cm of the door frame is above water; the barred ground-floor window "
          "is under water except its top edge; the parked car and the bench are completely "
          "under water and cannot be seen. Keep the camera position and the upper storeys "
          "exactly as they are. Overcast light, light rain. No people. Photorealistic "
          "documentary photograph. No text."),
    "5": ("Edit this photograph into a severe flood. A flat sheet of muddy brown floodwater "
          "fills the street up to about 3 metres deep: the waterline runs across the house "
          "fronts just below the first-floor balcony. Everything below that line is under the "
          "water and cannot be seen: the parked car, the bench, the door steps, the whole "
          "wooden front door and the barred ground-floor window. Only the first floor, the "
          "balcony with its flower pots and the storeys above stand out of the water. Keep the "
          "camera position and the upper storeys exactly as they are. Overcast light, light "
          "rain. No people. Photorealistic documentary photograph. No text."),
}


def catalogue() -> list[dict]:
    """Every scene in the library, with the prompts that draw it. The batch script
    generates from this list; /api/illustrations publishes it."""
    scenes = []
    for lo, hi, suffix, water, short in DEPTH_BANDS:
        prompt = DEEP_BANDS.get(suffix) or (
            f"Edit this photograph: the street is flooded; {water}. Keep the camera position, "
            f"the buildings, the car, the bench and the door exactly as they are. Overcast "
            f"light, light rain. No people. " + STYLE)
        scenes.append({
            "id": f"flood-depth-{suffix}", "family": "flooding", "card": "flood_zone",
            "selector": f"SNCZI water depth {_band_text(lo, hi)}",
            "title": f"What floodwater {short} deep looks like",
            "caption": f"Illustration for a water depth of {_band_text(lo, hi)}, in a generic "
                       f"street. The door is about 2 m tall; a car wheel, about 60 cm.",
            "base": FLOOD_BASE["id"], "image_prompt": prompt, "motion_prompt": FLOOD_MOTION,
            "edit_model": config.FAL_STRICT_EDIT_MODEL if suffix in DEEP_BANDS else None,
        })
    for kind, spec in LEVEL_SCENES.items():
        cards = [c for c, (k, *_) in CARD_SCENES.items() if k == kind]
        for level, slug in LEVEL_SLUGS.items():
            if level not in spec:
                continue
            scenes.append({
                "id": f"{kind}-{slug}", "family": FAMILY[kind], "card": cards[0],
                "selector": f"level {level} on the {' or '.join(cards)} card",
                "title": CARD_SCENES[kind][1].format(level=level),
                "caption": CARD_SCENES[kind][2].format(level=level),
                "base": None, "image_prompt": spec[level],
                "motion_prompt": spec.get("motion_by_level", {}).get(level, spec["motion"]),
                "negative": ", ".join(filter(None, [
                    VIDEO_NEGATIVE, spec.get("negative_by_level", {}).get(level)])),
                "cfg_scale": spec.get("cfg_by_level", {}).get(level),
            })
    return scenes


def scene(scene_id: str) -> dict | None:
    return next((s for s in catalogue() if s["id"] == scene_id), None)


# --------------------------------------------------------------------------- #
# Manifest: what has actually been generated
# --------------------------------------------------------------------------- #
_manifest_cache: tuple[float, dict] | None = None


def manifest() -> dict:
    """The generated library ({"scenes": {id: record}}), re-read when the file changes."""
    global _manifest_cache
    try:
        mtime = MANIFEST.stat().st_mtime
    except OSError:
        return {"scenes": {}}
    if _manifest_cache and _manifest_cache[0] == mtime:
        return _manifest_cache[1]
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"scenes": {}}
    data.setdefault("scenes", {})
    _manifest_cache = (mtime, data)
    return data


def save_manifest(data: dict) -> None:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(MANIFEST)


def generated(scene_id: str) -> dict | None:
    rec = manifest()["scenes"].get(scene_id)
    if not rec or not (LIBRARY_DIR / rec.get("video", "")).is_file():
        return None
    return rec


def file_path(url: str) -> Path | None:
    """Local file behind a /media/illustrations/... URL."""
    if not url or not url.startswith(URL_PREFIX):
        return None
    path = (LIBRARY_DIR / url[len(URL_PREFIX):]).resolve()
    return path if path.is_file() and LIBRARY_DIR.resolve() in path.parents else None


# --------------------------------------------------------------------------- #
# Choosing: the card's data pick the clip
# --------------------------------------------------------------------------- #
def _indicator(hazard: dict, key: str) -> dict | None:
    return next((i for i in hazard.get("indicators", []) if i.get("key") == key), None)


def _says_something(ind: dict) -> bool:
    extras = ind.get("extras") or {}
    if extras.get("contrast"):
        return False
    display = str(extras.get("display") or "")
    if display:
        return display not in ("No", "no value", "no response", "—")
    return isinstance(ind.get("value"), (int, float)) and ind["value"] != 0


def _telling(hazard: dict) -> dict | None:
    """The card's primary indicator, or its first one that states something: "Inside
    a mapped avalanche zone: No" does not explain a picture; "919 m to the nearest
    one" does."""
    primary = _indicator(hazard, hazard.get("primary_metric", ""))
    if primary and _says_something(primary):
        return primary
    return next((i for i in hazard.get("indicators", []) if _says_something(i)), primary)


def _shown(ind: dict) -> str:
    display = (ind.get("extras") or {}).get("display")
    if display:
        return str(display)
    value, unit = ind.get("value"), ind.get("unit") or ""
    if value is None:
        return "—"
    return f"{value:g} {unit}".strip() if isinstance(value, (int, float)) else f"{value} {unit}"


def _chosen_by(ind: dict | None, rule: str, hazard: dict) -> dict:
    out = {"card": hazard["label"], "rule": rule, "score": hazard.get("score"),
           "level": hazard.get("level")}
    if ind:
        prov = ind.get("provenance") or {}
        out.update({"indicator": ind["key"], "label": ind["label"], "value": ind.get("value"),
                    "unit": ind.get("unit"), "shown": _shown(ind), "source": prov.get("source"),
                    "dataset": prov.get("dataset")})
    return out


def flood_depth(hazard: dict) -> dict | None:
    """The depth that picks the flood clip: the river's reference depth (the 100-year
    flood when published), else the coastal one. None when there is no depth."""
    for key in ("flood_depth_fluvial", "flood_zone_marine_t100", "flood_zone_marine_t500"):
        ind = _indicator(hazard, key)
        if ind and isinstance(ind.get("value"), (int, float)) and ind["value"] > 0:
            return ind
    return None


def pick(hazard: dict) -> tuple[str, dict] | None:
    """(scene id, chosen_by) for a card, or None when its data do not pick one."""
    key = hazard.get("key")
    if key == "flood_zone":
        ind = flood_depth(hazard)
        if not ind:
            return None
        sid = flood_scene_id(ind["value"])
        band = next(b for b in DEPTH_BANDS if f"flood-depth-{b[2]}" == sid)
        return sid, _chosen_by(ind, f"water depth {ind['value']:.2f} m → band "
                                    f"{_band_text(band[0], band[1])}", hazard)
    level = hazard.get("level")
    if key in CARD_SCENES and level in LEVEL_SLUGS:
        kind = CARD_SCENES[key][0]
        floor = MIN_LEVEL.get(kind, "moderate")
        if LEVEL_ORDER.index(level) < LEVEL_ORDER.index(floor) or level not in LEVEL_SCENES[kind]:
            return None
        ind = _telling(hazard)
        rule = f"card level {level} ({round(hazard['score'])}/100)"
        return f"{kind}-{LEVEL_SLUGS[level]}", _chosen_by(ind, rule, hazard)
    return None


def illustration_for(hazard: dict) -> dict | None:
    picked = pick(hazard)
    if not picked:
        return None
    sid, chosen = picked
    rec = generated(sid)
    spec = scene(sid)
    if not rec or not spec:
        return None
    title, caption = spec["title"], spec["caption"]
    if hazard["key"] in CARD_SCENES:  # the card's own wording ("Flood weather, illustrated")
        _, t, c = CARD_SCENES[hazard["key"]]
        title, caption = t.format(level=hazard["level"]), c.format(level=hazard["level"])
    return {
        "id": sid,
        "kind": "illustration",
        "video": URL_PREFIX + rec["video"],
        "poster": URL_PREFIX + rec["poster"] if rec.get("poster") else None,
        "title": title,
        "caption": caption,
        "chosen_by": chosen,
        "generated_with": {
            "via": "fal.ai",
            "image_model": rec.get("image_model"),
            "video_model": rec.get("video_model"),
            "image_prompt": rec.get("image_prompt"),
            "motion_prompt": rec.get("motion_prompt"),
            "generated_at": rec.get("generated_at"),
        },
        "limitation": ILLUSTRATION_LIMITATION,
    }


def attach(report: dict) -> int:
    """Adds `illustration` to the cards whose data pick a generated clip. Returns
    how many cards got one."""
    n = 0
    for hazard in report.get("hazards", []):
        ill = illustration_for(hazard)
        if ill:
            hazard["illustration"] = ill
            n += 1
    return n


def status() -> dict:
    scenes = catalogue()
    ready = [s["id"] for s in scenes if generated(s["id"])]
    return {"scenes": len(scenes), "generated": len(ready), "missing":
            [s["id"] for s in scenes if s["id"] not in ready]}
