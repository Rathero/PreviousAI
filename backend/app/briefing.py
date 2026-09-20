"""The narrated video briefing: the report in under a minute, as an MP4 to share.

Division of labour:

    the DATA        -> every number on screen and in the voice, with its source
    CODE            -> writes the script, word for word, from the report
                       (`build_script`): no model writes a sentence
    fal.ai (voice)  -> only READS that script aloud (text to speech)
    the library     -> the pictures behind each hazard are the card's own illustration
                       (media.py), labelled "AI illustration"
    ffmpeg          -> puts it together (video.py)

Without FAL_KEY the briefing still comes out, silent, with the same captions; without an
illustration the scene gets a plain background in the hazard's colour. Briefings are
cached by their content: the same report gives the same file, and a repeated one costs
nothing.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config, media, video, view
from .hazards import MONTHS_EN
from .providers import fal

VERSION = 3   # bump when the look changes: cached briefings are keyed by it
W, H = 1280, 720
OUT_DIR = config.MEDIA_DIR / "briefings"
WORK_DIR = config.CACHE_DIR / "briefing_work"
URL_PREFIX = "/media/briefings/"
MAX_HAZARDS = 3
FADE_S = 0.35
LEAD_S = 0.3     # silence before the voice starts in each scene
TAIL_S = 0.5     # and after it ends

COLORS = {"bg": (16, 29, 19), "panel": (24, 42, 27), "text": (247, 245, 239),
          "muted": (196, 202, 186), "ai": (186, 242, 74), "accent": (186, 242, 74)}
# Each hazard keeps the colour it has in the web app.
FAMILY_RGB = {"heat": (231, 192, 119), "flood": (127, 180, 220), "rain": (127, 180, 220),
              "flood_zone": (127, 180, 220),
              "flood_history": (127, 180, 220), "sea_level": (127, 180, 220),
              "flood_regional": (127, 180, 220), "wildfire": (229, 138, 99),
              "fire_history": (229, 138, 99), "avalanche": (199, 203, 214)}

LIMITATION = ("A summary of the report, not a replacement for it: each card's full method and "
              "its \"what this does NOT say\" are in the report. The pictures are AI "
              "illustrations of generic places, chosen by the card's value; they are not this "
              "place and not a forecast.")


@dataclass
class Scene:
    kind: str                      # intro | hazard | advice | closing
    say: str                       # exactly what the voice reads
    title: str = ""
    kicker: str = ""
    figure: str = ""
    figure_label: str = ""
    caption: str = ""
    source: str = ""
    level: str | None = None
    tint: tuple | None = None          # the hazard's colour
    illustration: str | None = None   # a media.py scene id
    lines: list[str] = field(default_factory=list)   # closing: the risks at a glance


# --------------------------------------------------------------------------- #
# The script: code, from the report
# --------------------------------------------------------------------------- #
_COORDS = re.compile(r"\s*\(?-?\d{1,2}\.\d+\s*,\s*-?\d{1,3}\.\d+\)?\s*")


def spoken_place(report: dict) -> str:
    """The place as a person would say it: never "forty-one point nine eight…", and
    without the region and country the listener already knows."""
    loc = report["location"]
    label = str(loc.get("label") or "")
    name = _COORDS.sub(" ", label).strip(" ,")
    parts = [p.strip() for p in name.split(",") if p.strip()]
    tail = {str(loc.get(k) or "").lower() for k in ("country", "admin1")} | {"spain", "catalonia"}
    while len(parts) > 1 and parts[-1].lower() in tail:
        parts.pop()
    name = ", ".join(parts)
    if name:
        return name
    muni = (report.get("coverage") or {}).get("municipality") or {}
    return muni.get("name") or "the selected point"


def spoken_town(report: dict) -> str | None:
    """The town alone, for the voice: the screen already shows the street, and a street
    name in Catalan or Spanish is where an English voice stumbles."""
    town = re.sub(r"^\d{4,5}\s+", "", spoken_place(report).rsplit(",", 1)[-1].strip())
    return None if town == "the selected point" else town


def _when(report: dict) -> str:
    if report.get("mode") != "travel":
        home = (report.get("dwelling") or {}).get("label")
        return f"for your {home.lower()}, all year round" if home else "for living there all year round"
    trip = (report.get("outlook") or {}).get("trip")
    if trip:
        a, b = (dt.date.fromisoformat(d) for d in trip)
        return f"for a trip from {a.day} {MONTHS_EN[a.month]} to {b.day} {MONTHS_EN[b.month]}"
    months = (report.get("window") or {}).get("months") or []
    return "for a trip in " + " and ".join(MONTHS_EN[m] for m in months)


def _spoken_when(report: dict) -> str:
    """_when as the voice says it, with the town: "for your house in El Masnou, covering
    the whole year"."""
    town = spoken_town(report)
    if report.get("mode") != "travel":
        home = (report.get("dwelling") or {}).get("label")
        at = f" in {town}" if town else ""
        return (f"for your {home.lower()}{at}, covering the whole year" if home
                else f"for living{at} all year round")
    to = f" to {town}" if town else ""
    trip = (report.get("outlook") or {}).get("trip")
    if trip:
        a, b = (dt.date.fromisoformat(d) for d in trip)
        return f"for your trip{to}, from {a.day} {MONTHS_EN[a.month]} to {b.day} {MONTHS_EN[b.month]}"
    months = (report.get("window") or {}).get("months") or []
    return f"for your trip{to} in " + " and ".join(MONTHS_EN[m] for m in months)


def _shown(ind: dict) -> str:
    display = (ind.get("extras") or {}).get("display")
    if display:
        return str(display)
    value, unit = ind.get("value"), (ind.get("unit") or "").replace(" equiv.", "")
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        # The figure as the source gave it, trimmed, never re-rounded into a new
        # number: a 1.58 m water depth is said "1.58", not "1.6".
        digits = 3 if abs(value) < 1 else 2 if abs(value) < 10 else 1 if abs(value) < 100 else 0
        text = f"{value:,.{digits}f}".rstrip("0").rstrip(".") if digits else f"{value:,.0f}"
        return f"{text} {unit}".strip()
    return f"{value} {unit}".strip()


def key_indicator(hazard: dict) -> dict | None:
    """The one number a scene shows for a card: the one that chose its illustration,
    else its primary metric, else its first stated value."""
    inds = hazard.get("indicators") or []
    # The value that picks the illustration, whether or not its clip exists yet
    # (for the flood card, the water depth rather than a "Yes").
    picked = media.pick(hazard)
    chosen = (picked[1].get("indicator") if picked else None)
    for key in (chosen, hazard.get("primary_metric")):
        ind = next((i for i in inds if key and i.get("key") == key), None)
        if ind and _shown(ind) and _shown(ind) != "No":
            return ind
    positive = [i for i in inds if str((i.get("extras") or {}).get("display", "")).startswith("Yes")]
    if positive:
        return positive[0]
    return next((i for i in inds if media._says_something(i)), None)


_UNITS = [("°C", "degree", "degrees"), ("°", "degree", "degrees"), ("mm", "millimetre", "millimetres"),
          ("cm", "centimetre", "centimetres"), ("km", "kilometre", "kilometres"),
          ("m", "metre", "metres"), ("%", "percent", "percent"), ("ha", "hectare", "hectares")]


def speakable(text: str) -> str:
    """Written text -> what a voice should read ("1.58 m" -> "1.58 metres")."""
    # Zeros after the point are only trimmed: "2.0 km" is said "2 kilometres", not
    # "two point zero", and 1.58 stays 1.58.
    out = re.sub(r"(\d)\.0+(?!\d)", r"\1", text)
    for sym, one, many in _UNITS:
        pattern = re.compile(r"(\d[\d,.]*)\s*" + re.escape(sym) + (r"(?![A-Za-z])" if sym[-1].isalpha() else ""))
        out = pattern.sub(lambda m: f"{m.group(1)} {one if m.group(1) in ('1', '1.0') else many}", out)
    out = re.sub(r"\bdays/year( equiv\.)?", "days a year", out)
    out = re.sub(r"\bnights/year", "nights a year", out)
    out = re.sub(r"/year\b", " a year", out)
    out = re.sub(r"\bT(\d+)\b", r"\1-year", out)
    out = re.sub(r"\b(\d{4})-(\d{4})\b", r"\1 to \2", out)
    out = out.replace(" · ", ", ").replace("·", ",").replace("≥", "at least ").replace("→", "to")
    out = re.sub(r"\s*[()]\s*", ", ", out)
    out = re.sub(r"\s*;\s*(\w)", lambda m: ". " + m.group(1).upper(), out)
    out = re.sub(r"\s+,", ",", out)
    out = re.sub(r",\s*([.,:])", r"\1", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,")
    return out


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def _lower_first(text: str) -> str:
    """"Remove dry leaves" -> "remove dry leaves", to follow a lead-in; a word in
    capitals ("FFP2") keeps them."""
    word = text.split(" ", 1)[0]
    return text[:1].lower() + text[1:] if word[1:] == word[1:].lower() else text


def _n(count: str, one: str, many: str) -> str:
    """"1 fire has", "6 fires have"."""
    return f"{count} {one if count == '1' else many}"


_REGIONAL = {"river": "river floods", "urban (rain)": "urban flooding from rain",
             "coastal": "coastal floods"}


def _regional(m: re.Match) -> str:
    """"In Arizona: high river and high urban (rain) flooding" -> "In Arizona, the regional
    flood hazard is high for river floods and high for urban flooding from rain"."""
    said = []
    for part in re.split(r", | and ", m[2]):
        kind = next((k for k in _REGIONAL if part.endswith(" " + k)), None)
        if not kind:
            return m[0]
        said.append(f"{part[:-len(kind) - 1]} for {_REGIONAL[kind]}")
    return f"In {m[1]}, the regional flood hazard is " + (
        said[0] if len(said) == 1 else ", ".join(said[:-1]) + " and " + said[-1])


# The card headlines are captions, written for the screen: "6 mapped fires within 5 km
# since 1986; the nearest, from 1994, 2.0 km away". Read aloud, a caption sounds like a
# list being read, so the voice says the same figures inside sentences. Each rule
# matches one headline template in hazards*.py and changes only the words around the
# figures; <S>/<s> is the home or the place. A headline no rule knows (a template that
# changed) is read as it is.
_SPOKEN = [(re.compile(pattern), repl) for pattern, repl in [
    # Fires on record (fire_history)
    (r"^The point lies inside the perimeter of a (\d{4}) fire \(([^)]+)\)",
     r"<S> lies inside the perimeter of a \1 fire that burned \2"),
    (r"^(\d+) mapped fires? within (\S+ k?m) since (\d{4}); the nearest, from (\d{4}), (\S+ k?m) away",
     lambda m: f"Since {m[3]}, {_n(m[1], 'fire has', 'fires have')} been mapped within {m[2]} "
               f"of <s>, and the nearest one, in {m[4]}, was {m[5]} away"),
    (r"^No mapped fire within (\S+ k?m) since (\d{4})",
     r"No fire has been mapped within \1 of <s> since \2"),
    # Fire weather (wildfire)
    (r"^(\d+ days?|Less than one day) a year with fire-prone weather",
     lambda m: f"There {'is' if m[1].endswith('day') else 'are'} {_lower_first(m[1])} a year "
               f"of fire-prone weather"),
    (r"^(Less than 1 %|\d+ %) of days in (.+?) with fire-prone weather",
     r"\1 of days in \2 have fire-prone weather"),
    (r"; by (\d{4}-\d{4}) \(RCP8\.5\) (\d+) more days a year of high danger \(FWI > 30\) "
     r"are projected",
     r". By \1, under a high-emissions scenario, \2 more days a year of high fire danger "
     r"are projected"),
    # Heat
    (r"^(\d+ days?|Less than one day) a year above (\d+) degrees",
     lambda m: f"It goes above {m[2]} degrees on {_lower_first(m[1])} a year"),
    (r"^(Less than 1 %|\d+ %) of days in (.+?) above (\d+) degrees",
     lambda m: f"It goes above {m[3]} degrees on {_lower_first(m[1])} of days in {m[2]}"),
    (r"; (\d+) tropical nights a year \(the night never cools below ([^)]+)\)",
     r", and there are \1 tropical nights a year, when the night never cools below \2"),
    (r"; (\d+ in 10 nights never cool)", r", and \1"),
    # Official flood zones and avalanche zones (the zone's code is not read out)
    (r"^Inside a mapped (.+?) \([^)]*\)", r"<S> is inside a mapped \1"),
    (r"^Inside the (.+?) \(water depth ([^)]+)\)", r"<S> is inside the \1, with a water depth of \2"),
    (r"^Inside the ", r"<S> is inside the "),
    (r"; also in the ", r", and also in the "),
    (r"^Outside the ", r"<S> is outside the "),
    # Recorded floods, sea level, regional flooding
    (r"^No flood episodes recorded in (.+?) \((\d{4})-(\d{4})\)",
     r"No flood episodes were recorded in \1 between \2 and \3"),
    (r"^Under water with ", r"<S> would be under water with "),
    (r"^Under water if the sea rises ", r"<S> would be under water if the sea rose "),
    (r"^In (.+?): (.+) flooding$", _regional),
    # Avalanches
    (r"^Nearest mapped avalanche zone (\S+ k?m) away", r"The nearest mapped avalanche zone is \1 away"),
    (r"^No mapped avalanche zone within ", r"There is no mapped avalanche zone within "),
    (r"; (\d+) avalanches? observed within (\S+ k?m)((?: since \d{4})?)",
     lambda m: f". {_n(m[1], 'avalanche has', 'avalanches have')} been observed within {m[2]}{m[3]}"),
    (r"; (\d+) avalanches? recalled by local people within (\S+ k?m)",
     lambda m: f", and local people recall {_n(m[1], 'avalanche', 'avalanches')} within {m[2]}"),
    (r"; (\S+ cm) of snow in a typical year", r". A typical year brings \1 of snow"),
    (r"^Slopes of up to (.+?) and (.+?) of snowfall a year: avalanche terrain, with no official "
     r"avalanche map here",
     r"With slopes of up to \1 and \2 of snowfall a year, this is avalanche terrain, though "
     r"there is no official avalanche map here"),
]]


def spoken_headline(headline: str, subject: str) -> str:
    """A card's headline as the voice says it (see _SPOKEN)."""
    for pattern, repl in _SPOKEN:
        headline = pattern.sub(repl, headline, count=1)
    return headline.replace("<S>", subject[:1].upper() + subject[1:]).replace("<s>", subject)


def _risk_lead(risk: dict, i: int, count: int, previous: dict | None) -> str:
    """"Fire is a moderate risk here, at 52 out of 100.": each score is said once, in its
    own scene, and each scene follows on from the one before."""
    verb = "are" if risk["key"] in view.PLURAL else "is"
    score = f"a {risk['level']} risk"
    if i == 0:
        return f"{risk['label']} {verb} {score} here, at {risk['score']} out of 100."
    also = " also" if previous and previous["level"] == risk["level"] else ""
    lead = "And" if i == count - 1 else "Next,"
    return f"{lead} {risk['label'].lower()} {verb}{also} {score}, at {risk['score']} out of 100."


def _spoken_indicator(ind: dict, figure: str) -> str:
    """A figure the headline does not say: the river's water depth as a sentence, any
    other as "label: value"."""
    period = re.search(r"(\d+)-year flood", ind.get("label") or "")
    if ind.get("key") == "flood_depth_fluvial" and period:
        return f"In a {period[1]}-year flood, the river water here would be {figure} deep."
    return f"{ind['label']}: {figure}."


def _what_to_do(report: dict, worst: dict | None) -> tuple[str, str, str] | None:
    """The advice the video reads, from the report's action plan: the household's first
    measure when one was ranked for it, else the first steps before the worst risk.
    Returns (label, text on screen, what the voice says)."""
    plan = report.get("action_plan") or {}
    household = [a for a in plan.get("household") or [] if isinstance(a, dict) and a.get("text")]
    if household:
        text = _sentence(household[0]["text"])
        return "For your household", text, f"One tip for your household. {text}"
    hazard = next((p for p in plan.get("plans", []) if worst and p.get("key") == worst["key"]), None)
    before = next((ph for ph in (hazard or {}).get("phases", []) if ph["key"] == "before"), None)
    if before and before["items"]:
        steps = ["".join(seg["text"] for seg in item["segments"]) for item in before["items"][:2]]
        text = " ".join(_sentence(step) for step in steps)
        # "Before a wildfire, remove dry leaves..."
        return before["label"], text, f"{before['label']}, {_lower_first(text)}"
    return None


def build_script(report: dict) -> list[Scene]:
    """The script, scene by scene: the four risks exactly as the app shows them (the worst
    opens, those of 20 or more get a scene each, all of them close), each told through
    the card that sets its score."""
    place = spoken_place(report)
    cards = {h["key"]: h for h in report["hazards"]}
    risks = sorted((r for r in view.risks(report) if r["score"] is not None and r["cards"]),
                   key=lambda r: -r["score"])
    shown = [r for r in risks if r["score"] >= 20][:MAX_HAZARDS] or risks[:1]
    worst = risks[0] if risks else None

    def clip(risk: dict) -> str | None:
        """The illustration of the risk's worst card that has one."""
        return next(((cards[c["key"]].get("illustration") or {}).get("id") for c in risk["cards"]
                     if cards[c["key"]].get("illustration")), None)

    # The voice says the town and the risk; the scores come one per scene.
    intro = f"This is your Previous AI report {_spoken_when(report)}."
    if worst:
        when = "for these dates" if report.get("mode") == "travel" else "here"
        intro += f" The biggest risk {when} comes from {worst['label'].lower()}."
    subject = ("your home" if report.get("mode") != "travel" and report.get("dwelling")
               else "this place")
    scenes = [Scene(
        kind="intro", title=place, kicker="Previous AI · natural hazard report",
        caption=f"Flooding, wildfire, avalanches and extreme heat, {_when(report)}.",
        figure=f"{worst['score']}%" if worst else "",
        figure_label=f"{worst['label'].lower()} · {worst['level']}" if worst else "",
        level=(worst or {}).get("level"), tint=FAMILY_RGB.get((worst or {}).get("key")),
        illustration=next((c for c in map(clip, shown + risks) if c), None),
        say=speakable(intro),
    )]

    # What the flood map means for this home (its floor), said with the flood scene.
    home_note = ((report.get("dwelling") or {}).get("notes") or {}).get("flood")
    for i, risk in enumerate(shown):
        h = cards[risk["cards"][0]["key"]]
        ind = key_indicator(h)
        figure = _shown(ind) if ind else ""
        headline = _sentence(spoken_headline(h["headline"], subject))
        say = f"{_risk_lead(risk, i, len(shown), shown[i - 1] if i else None)} {headline}"
        # The figure is said only when nothing else says it: the headline is written
        # from the primary metric ("brings 44 mm"), so repeating it ("44.4 mm") only adds
        # seconds, and a bare "Yes" adds nothing. The flood depth is not in the headline,
        # but the note on the home says it, measured against the floor.
        note = home_note if risk["key"] == "flood" else None
        number = re.search(r"\d[\d.,]*", figure or "")
        if (ind and figure and not note and ind.get("key") != h.get("primary_metric")
                and not figure.startswith(("Yes", "No"))
                and not (number and number.group(0) in h["headline"])):
            say += f" {_spoken_indicator(ind, figure)}"
        if note:
            # "Your home is inside the zone. Your home is at street level" -> "It is..."
            if headline.startswith("Your home ") and note.startswith("Your home "):
                note = "It " + note[len("Your home "):]
            say += f" {_sentence(note)}"
        scenes.append(Scene(
            kind="hazard", kicker=f"{risk['label']} · {risk['level']} · {risk['score']}%",
            figure=figure, figure_label=(ind or {}).get("label", ""),
            caption=h["headline"], level=risk["level"], tint=FAMILY_RGB.get(risk["key"]),
            illustration=clip(risk),
            say=speakable(say),
        ))

    tip = _what_to_do(report, worst)
    if tip:
        about, text, said = tip
        scenes.append(Scene(
            kind="advice", kicker="What to do about it", caption=text,
            figure_label=about, level=None,
            say=speakable(said),
        ))

    glance = [f"{r['label']}: {r['score']}%" for r in sorted(
        (r for r in view.risks(report) if r["score"] is not None), key=lambda r: -r["score"])]
    scenes.append(Scene(
        kind="closing", title="Your home at a glance", lines=glance,
        caption="The full report shows what each value means and what it does not say.",
        say=("The full report explains what each value means, and what it does not say. And "
             "remember, the pictures are AI illustrations, not this place."),
    ))
    return scenes


# --------------------------------------------------------------------------- #
# Drawing each scene's overlay (Pillow)
# --------------------------------------------------------------------------- #
_FONT_FILES = {
    "regular": ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "Helvetica.ttc"],
    "bold": ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "Helvetica.ttc"],
}
_FONT_DIRS = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu"),
              Path("/Library/Fonts"), Path("/System/Library/Fonts")]


def _font(weight: str, size: int):
    from PIL import ImageFont
    for name in _FONT_FILES[weight]:
        for folder in _FONT_DIRS:
            path = folder / name
            if path.exists():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def _wrap(draw, text: str, font, width: int, max_lines: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        line = word
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines[-1] = last + "…"
    return lines


def _gradient(img, top: int, max_alpha: int, *, bottom: bool = True) -> None:
    """Darkens the picture behind the text: opaque enough where the text sits, even
    over a bright clip, and fading out above it."""
    from PIL import Image
    height = (H - top) if bottom else top
    mask = Image.linear_gradient("L").resize((W, height))
    if not bottom:
        mask = mask.rotate(180)
    # Reaches full strength a little past half-way, where the text starts.
    mask = mask.point(lambda v: int(min(1.0, v / 255 * 1.9) * max_alpha))
    img.paste(Image.new("RGBA", (W, height), COLORS["bg"] + (255,)),
              (0, top if bottom else 0), mask)


class _ShadowDraw:
    """ImageDraw whose text gets a soft dark shadow, legible over any frame."""

    def __init__(self, draw):
        self._draw = draw

    def text(self, xy, text, font=None, fill=None):
        x, y = xy
        self._draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 170))
        self._draw.text((x, y), text, font=font, fill=fill)

    def __getattr__(self, name):
        return getattr(self._draw, name)


def _badge(draw, text: str, color, right: int, top: int) -> None:
    font = _font("bold", 18)
    width = int(draw.textlength(text, font=font)) + 28
    draw.rounded_rectangle((right - width, top, right, top + 34), radius=17,
                           fill=COLORS["bg"] + (220,), outline=color + (255,), width=2)
    draw.text((right - width + 14, top + 6), text, font=font, fill=color + (255,))


def render_overlay(scene: Scene, path: Path, *, has_picture: bool, footer: str = "") -> None:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    lvl = tuple(scene.tint) if scene.tint else COLORS["accent"]
    if scene.kind in ("intro", "closing", "advice") and has_picture:
        img.paste(Image.new("RGBA", (W, H), (0, 0, 0, 110)), (0, 0))
    if scene.kind == "closing":
        img.paste(Image.new("RGBA", (W, H), COLORS["bg"] + (235,)), (0, 0))
    else:
        _gradient(img, 230 if scene.kind == "intro" else 270, 245)
        if has_picture:
            _gradient(img, 120, 200, bottom=False)  # behind the wordmark and the badge
    draw = _ShadowDraw(ImageDraw.Draw(img))

    # Header: wordmark and, when there is a generated picture behind, the label.
    word = _font("bold", 30)
    draw.text((48, 34), "Previous", font=word, fill=COLORS["text"] + (255,))
    wx = 48 + draw.textlength("Previous", font=word) + 4
    draw.text((wx, 34), "AI", font=_font("regular", 16), fill=COLORS["text"] + (200,))
    draw.text((wx + 34, 44), "floods · wildfires · avalanches · heat waves", font=_font("regular", 19),
              fill=COLORS["muted"] + (255,))
    if has_picture and scene.kind != "closing":
        _badge(draw, "AI illustration · not this place", COLORS["ai"], W - 44, 34)

    x, text_w = 72, W - 144
    if scene.kind == "intro":
        title_font = _font("bold", 60)
        lines = _wrap(draw, scene.title, title_font, text_w, 2)
        y = 700 - 60 - 110 - 50 - 70 * len(lines)
        draw.text((x, y), scene.kicker.upper(), font=_font("bold", 22), fill=lvl + (255,))
        y += 40
        for line in lines:
            draw.text((x, y), line, font=title_font, fill=COLORS["text"] + (255,))
            y += 70
        for line in _wrap(draw, scene.caption, _font("regular", 26), text_w, 2):
            draw.text((x, y + 6), line, font=_font("regular", 26), fill=COLORS["muted"] + (255,))
            y += 34
        y += 24
        fig_font = _font("bold", 88)
        draw.text((x, y), scene.figure, font=fig_font, fill=lvl + (255,))
        fx = x + draw.textlength(scene.figure, font=fig_font) + 22
        draw.text((fx, y + 44), scene.figure_label, font=_font("regular", 30),
                  fill=COLORS["text"] + (255,))
    elif scene.kind == "closing":
        y = 150
        draw.text((x, y), scene.title, font=_font("bold", 46), fill=COLORS["text"] + (255,))
        y += 76
        for src in scene.lines[:5]:
            for i, line in enumerate(_wrap(draw, src, _font("regular", 24), text_w - 30, 2)):
                if i == 0:
                    draw.ellipse((x, y + 12, x + 10, y + 22), fill=COLORS["accent"] + (255,))
                draw.text((x + 26, y), line, font=_font("regular", 24), fill=COLORS["text"] + (255,))
                y += 32
            y += 10
        y += 16
        for line in _wrap(draw, scene.caption, _font("regular", 24), text_w, 2):
            draw.text((x, y), line, font=_font("regular", 24), fill=COLORS["muted"] + (255,))
            y += 32
        foot = _wrap(draw, footer, _font("regular", 18), text_w, 4)
        fy = H - 48 - 26 * len(foot)
        for line in foot:
            draw.text((x, fy), line, font=_font("regular", 18), fill=COLORS["muted"] + (255,))
            fy += 26
    else:
        # hazard / advice: kicker, big figure, the card's headline, the source.
        cap_font, src_font = _font("regular", 28), _font("regular", 18)
        caption = _wrap(draw, scene.caption, cap_font, text_w, 3 if scene.kind == "advice" else 2)
        source = _wrap(draw, scene.source, src_font, text_w, 2) if scene.source else []
        fig_font = _font("bold", 78)
        has_fig = bool(scene.figure) and draw.textlength(scene.figure, font=fig_font) < text_w * 0.62
        block = 36 + (92 if has_fig else 0) + 38 * len(caption) + (12 + 25 * len(source))
        y = H - 52 - block
        draw.rectangle((44, y + 4, 50, H - 56), fill=lvl + (255,))
        draw.text((x, y), scene.kicker.upper(), font=_font("bold", 22), fill=lvl + (255,))
        y += 36
        if has_fig:
            draw.text((x, y), scene.figure, font=fig_font, fill=COLORS["text"] + (255,))
            fx = x + draw.textlength(scene.figure, font=fig_font) + 22
            label = _wrap(draw, scene.figure_label, _font("regular", 24), W - 72 - int(fx), 2)
            for i, line in enumerate(label):
                draw.text((fx, y + 22 + i * 30), line, font=_font("regular", 24),
                          fill=COLORS["muted"] + (255,))
            y += 92
        for line in caption:
            draw.text((x, y), line, font=cap_font, fill=COLORS["text"] + (255,))
            y += 38
        y += 12
        for line in source:
            draw.text((x, y), line, font=src_font, fill=COLORS["muted"] + (255,))
            y += 25
    img.save(path)


def render_background(tint: tuple | None, path: Path) -> None:
    """A plain background in the hazard's colour, for scenes without a picture."""
    from PIL import Image
    tint = tuple(tint) if tint else COLORS["accent"]
    img = Image.new("RGB", (W, H), COLORS["bg"])
    glow = Image.radial_gradient("L").resize((W * 2, H * 2)).crop((W // 2, 0, W // 2 + W, H))
    glow = glow.point(lambda v: int((255 - v) * 0.35))
    img.paste(Image.new("RGB", (W, H), tint), (0, 0), glow)
    img.save(path)


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def _scene_args(bg: Path, is_clip: bool, overlay: Path, wav: Path | None, seconds: float,
                out: Path) -> list[str]:
    args = (["-stream_loop", "-1", "-i", str(bg)] if is_clip
            else ["-loop", "1", "-framerate", "30", "-i", str(bg)])
    args += ["-loop", "1", "-framerate", "30", "-i", str(overlay)]
    if wav:
        args += ["-i", str(wav)]
        audio = (f"[2:a]adelay=delays={int(LEAD_S * 1000)}:all=1,apad,atrim=0:{seconds:.3f},"
                 f"afade=t=out:st={max(0.0, seconds - 0.3):.3f}:d=0.3[a]")
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"]
        audio = f"[2:a]atrim=0:{seconds:.3f}[a]"
    fade_out = max(0.0, seconds - FADE_S)
    video_f = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,"
               f"fps=30[bg];[bg][1:v]overlay=0:0,format=yuv420p,"
               f"fade=t=in:st=0:d={FADE_S},fade=t=out:st={fade_out:.3f}:d={FADE_S}[v]")
    args += ["-filter_complex", f"{video_f};{audio}", "-map", "[v]", "-map", "[a]",
             "-t", f"{seconds:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
             "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
             "-ac", "1", str(out)]
    return args


def content_key(scenes: list[Scene], narrate: bool) -> str:
    body = {"v": VERSION, "narrate": narrate, "scenes": [asdict(s) for s in scenes],
            "tts": [config.FAL_TTS_MODEL, config.FAL_TTS_VOICE] if narrate else None,
            "clips": {s.illustration: (media.generated(s.illustration) or {}).get("generated_at")
                      for s in scenes if s.illustration}}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _words_seconds(text: str) -> float:
    """Silent version: time to read the screen, a little faster than speech."""
    return max(3.5, len(text.split()) / 3.0 + 1.2)


async def render(report: dict, *, narrate: bool = True, progress=None) -> dict:
    """Builds (or reuses) the briefing MP4 for a report. Returns its record."""
    async def say(text: str) -> None:
        if progress:
            await progress(text)

    if not video.available():
        raise video.VideoError("ffmpeg not found: pip install imageio-ffmpeg")
    scenes = build_script(report)
    narrate = narrate and fal.available()
    key = content_key(scenes, narrate)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out, meta_path = OUT_DIR / f"{key}.mp4", OUT_DIR / f"{key}.json"
    if out.exists() and meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))

    work = WORK_DIR / f"{key}-{uuid.uuid4().hex[:6]}"
    work.mkdir(parents=True, exist_ok=True)
    tts_model, voice, notes = None, None, []
    try:
        # 1. Voice, one sentence per scene, all read at once: each scene then lasts as
        # long as its sentence.
        durations, wavs = [], []
        if narrate:
            await say(f"Narrating {len(scenes)} scenes with fal.ai")
            spoken = await asyncio.gather(*(fal.speak(sc.say) for sc in scenes),
                                          return_exceptions=True)
            failed = next((s for s in spoken if isinstance(s, BaseException)), None)
            if failed is not None:
                notes.append(f"Narration unavailable ({failed}); this briefing is silent.")
                narrate = False
            else:
                for i, s in enumerate(spoken):
                    tts_model, voice = s["model"], s["voice"]
                    mp3, wav = work / f"s{i}.mp3", work / f"s{i}.wav"
                    mp3.write_bytes(s["audio"])
                    seconds = await asyncio.to_thread(video.to_wav, mp3, wav) + LEAD_S + TAIL_S
                    durations.append(round(seconds, 3))
                    wavs.append(wav)
        if not narrate:  # no key, or a voice failure: the whole briefing goes silent
            wavs = [None] * len(scenes)
            durations = [_words_seconds(sc.say) for sc in scenes]
            # ...and is filed as the silent version, so a later narrated try is not
            # answered with it from the cache.
            key = content_key(scenes, False)
            out, meta_path = OUT_DIR / f"{key}.mp4", OUT_DIR / f"{key}.json"

        # 2. Pictures and overlays, 3. one clip per scene, 4. joined.
        footer = ("Illustrations: AI-generated, generic places, chosen by each value. Narration: "
                  + ("an AI voice reading a script written from the report, word for word."
                     if narrate else "none (silent version).")
                  + f" Report generated {report['meta']['generated_at'][:10]}.")
        parts = []
        for i, sc in enumerate(scenes):
            await say(f"Assembling scene {i + 1} of {len(scenes)}")
            clip = media.generated(sc.illustration) if sc.illustration else None
            if clip:
                bg, is_clip = media.LIBRARY_DIR / clip["video"], True
            else:
                bg, is_clip = work / f"bg{i}.png", False
                await asyncio.to_thread(render_background, sc.tint, bg)
            overlay = work / f"ov{i}.png"
            await asyncio.to_thread(render_overlay, sc, overlay, has_picture=bool(clip),
                                    footer=footer)
            part = work / f"part{i}.mp4"
            await video.arun(_scene_args(bg, is_clip, overlay, wavs[i], durations[i], part))
            parts.append(part)
        await say("Joining the scenes")
        listing = work / "parts.txt"
        listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        tmp = work / "briefing.mp4"
        await video.arun(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
                          "-movflags", "+faststart", str(tmp)])
        shutil.move(str(tmp), out)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    record = {
        "id": key,
        "video": URL_PREFIX + out.name,
        "bytes": out.stat().st_size,
        "duration_s": round(sum(durations), 1),
        "narrated": narrate,
        "narration": ({"via": "fal.ai", "model": tts_model, "voice": voice} if narrate else None),
        "place": report["location"]["label"],
        "mode": report["mode"],
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "report_generated_at": report["meta"]["generated_at"],
        "scenes": [{"kind": s.kind, "say": s.say, "figure": s.figure, "figure_label": s.figure_label,
                    "source": s.source, "illustration": s.illustration, "seconds": d}
                   for s, d in zip(scenes, durations)],
        "script_by": "Written by code from the report: no AI writes a word",
        "notes": notes,
        "limitation": LIMITATION,
    }
    meta_path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return record


def file_path(url: str) -> Path | None:
    if not url or not url.startswith(URL_PREFIX):
        return None
    path = (OUT_DIR / url[len(URL_PREFIX):]).resolve()
    return path if path.is_file() and OUT_DIR.resolve() in path.parents else None


# --------------------------------------------------------------------------- #
# Jobs: the API answers at once and the page polls
# --------------------------------------------------------------------------- #
# Recommended by Norma — fixed with Claude Opus 5 via Claude Code
# In-process on purpose: see the note on state in main.py. A restart drops the jobs
# still queued or running; `get` falls back to the .json and .mp4 on disk, so a
# finished briefing is never lost and an unfinished one is simply rendered again.
JOBS: dict[str, dict] = {}
_TASKS: set[asyncio.Task] = set()
_RENDER_LOCK = asyncio.Lock()   # one encode at a time, so the API stays responsive


def _public(job: dict) -> dict:
    return {k: v for k, v in job.items() if not k.startswith("_")}


def start(report: dict, *, narrate: bool = True) -> dict:
    scenes = build_script(report)
    narrate_now = narrate and fal.available()
    key = content_key(scenes, narrate_now)
    meta = OUT_DIR / f"{key}.json"
    if meta.exists() and (OUT_DIR / f"{key}.mp4").exists():
        return {"id": key, "status": "done", "progress": "ready",
                "result": json.loads(meta.read_text(encoding="utf-8"))}
    job = JOBS.get(key)
    if job and job["status"] in ("queued", "running"):
        return _public(job)
    job = {"id": key, "status": "queued", "progress": "waiting to start", "result": None,
           "error": None, "narrated": narrate_now,
           "script": [{"kind": s.kind, "say": s.say} for s in scenes]}
    JOBS[key] = job

    async def progress(text: str) -> None:
        job["progress"] = text

    async def run() -> None:
        async with _RENDER_LOCK:
            job["status"] = "running"
            try:
                job["result"] = await render(report, narrate=narrate, progress=progress)
                job["status"], job["progress"] = "done", "ready"
            except Exception as exc:  # noqa: BLE001 - a job must never stay "running" forever
                job["status"], job["error"] = "failed", f"{type(exc).__name__}: {exc}"

    task = asyncio.create_task(run())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return _public(job)


def get(job_id: str) -> dict | None:
    job = JOBS.get(job_id)
    if job:
        return _public(job)
    if not re.fullmatch(r"[0-9a-f]{16}", job_id):
        return None
    meta = OUT_DIR / f"{job_id}.json"
    if meta.exists() and (OUT_DIR / f"{job_id}.mp4").exists():
        return {"id": job_id, "status": "done", "progress": "ready",
                "result": json.loads(meta.read_text(encoding="utf-8"))}
    return None
