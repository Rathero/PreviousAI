"""Free text -> place, mode, dates and who is going.

"Seville in August with my elderly parents" has to become: place "Seville", a stay in
August, older adults. The AI (Nebius Token Factory or TypeSafe Jev, see
`providers/ai.py`) never *writes* the place: code cuts the request into candidate spans
and the AI *chooses* one. The AI reads which month and day the text names, and code does
all the calendar maths.

Every field carries its probability. Without an AI key the whole text goes to the
geocoder.
"""

from __future__ import annotations

import datetime as dt
import re

from .providers import ai, geocoding

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]

PROFILES = {
    "children": ("Children",
                 "Children, babies or teenagers are going, or live there"),
    "older_adults": ("Over-65s",
                     "People over about 65 are going or live there: elderly parents, "
                     "grandparents, retirees"),
    "respiratory": ("Asthma, lung or heart condition",
                    "Someone has asthma, COPD, allergies or another breathing or heart condition"),
    "pregnancy": ("Pregnancy", "Someone is pregnant"),
    "reduced_mobility": ("Reduced mobility",
                         "Someone uses a wheelchair, walks with difficulty or needs help to move"),
    "outdoor": ("Outdoor activities",
                "They plan outdoor activities: hiking, skiing, mountaineering, cycling, "
                "camping, beach, diving, sailing or similar"),
}

# Words that can never be part of a place name in these requests. They cut the
# candidate spans, so the AI chooses among a few dozen options, not hundreds.
_TIME_WORDS = {
    *(m.lower() for m in MONTHS), "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "sept", "oct", "nov", "dec", "summer", "winter", "spring", "autumn", "fall",
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
    "setiembre", "octubre", "noviembre", "diciembre", "verano", "invierno", "primavera",
    "otoño", "gener", "febrer", "març", "maig", "juny", "juliol", "agost", "setembre",
    "novembre", "desembre", "estiu", "hivern", "tardor",
    "today", "tomorrow", "tonight", "weekend", "week", "weeks", "month", "hoy", "mañana",
    "semana", "finde", "demà", "setmana",
}
# Joining words that cannot start or end a place, but only in lower case:
# "La Palma", "A Coruña" and "El Puerto" keep their capitalised article.
_EDGE_WORDS = {
    "in", "at", "to", "for", "with", "on", "from", "near", "of", "and", "or", "by", "into",
    "around", "next", "this", "my", "our", "the", "a", "an", "we", "i", "going", "trip",
    "en", "al", "con", "de", "del", "para", "por", "cerca", "y", "o", "mi", "mis", "nuestro",
    "nuestra", "la", "el", "los", "las", "un", "una", "amb", "per", "prop", "les", "voy",
    "vamos", "viaje", "piso", "casa",
}
MAX_SPAN_TOKENS = 10  # "street, number, comma and town" can take 9 tokens
MAX_CANDIDATES = 150
MAX_TEXT = 300
NO_PLACE = "(no place)"


def candidate_spans(text: str) -> list[str]:
    """Every contiguous span that could be the place, as the user wrote it."""
    tokens = [(m.group(), m.start(), m.end())
              for m in re.finditer(r"[\w'’.\-/]+|,", text[:MAX_TEXT])]
    out: list[str] = []
    seen = set()
    for i in range(len(tokens)):
        for j in range(i, min(i + MAX_SPAN_TOKENS, len(tokens))):
            words = [t[0] for t in tokens[i:j + 1]]
            first, last = words[0], words[-1]
            if first == "," or last == ",":
                continue
            if any(w.lower().strip(".") in _TIME_WORDS for w in words):
                break  # a longer span would contain the same time word
            if (first in _EDGE_WORDS) or (last in _EDGE_WORDS):
                continue
            if all(re.fullmatch(r"[\d.\-/]+", w) for w in words if w != ","):
                continue
            span = text[tokens[i][1]:tokens[j][2]].strip(" .,")
            if span and span.lower() not in seen:
                seen.add(span.lower())
                out.append(span)
    if len(out) > MAX_CANDIDATES:
        # Keep the spans that look like names (a capital letter or a house number).
        named = [s for s in out if re.search(r"[A-ZÀ-Þ]|\d", s)]
        out = (named + [s for s in out if s not in named])[:MAX_CANDIDATES]
    return out


def _questions(candidates: list[str]) -> dict:
    none = "The text does not state this."
    q = {
        "place": ai.choice(
            "Which option is the place the person wants analysed: the address of the home "
            "or the destination of the trip? Choose the most complete option that names only "
            "the place (street and number plus town when given), without words about the "
            "property, time, people or activities.",
            {**{c: None for c in candidates}, NO_PLACE: "The text does not name any place"}),
        "mode": ai.choice(
            "Why does the person ask about this place?",
            {"home": "Living in, moving to, buying, renting or checking a home, property, "
                     "plot or business there",
             "travel": "Visiting it: a trip, holiday, weekend away, business trip or event"}),
        "timing": ai.choice(
            "Does the text say when?",
            {"none": "No time is stated",
             "months": "It names months or seasons but no specific days, e.g. 'in August', "
                       "'this summer'",
             "dates": "It names specific calendar days, e.g. '24-28 September', 'from 3 to 10 "
                      "August', 'on 5 May'",
             "relative": "It says when relative to today without a calendar date, e.g. "
                         "'tomorrow', 'this weekend', 'next week', 'in two weeks'"}),
        "relative": ai.choice(
            "If the time is given relative to today, which is it?",
            {"tomorrow": None, "next_few_days": "Within the next few days, or this week",
             "this_weekend": None, "next_week": None, "next_weekend": None,
             "in_two_weeks": "In about two weeks", "none": "Not stated relative to today"}),
    }
    for n, name in enumerate(MONTHS, start=1):
        q[f"month_{n}"] = ai.noul(
            f"The trip or stay happens at least partly in {name}.",
            true=f"The text names {name}, a date in {name}, or a season that contains {name} "
                 "(winter = December-February, spring = March-May, summer = June-August, "
                 "autumn or fall = September-November)",
            false=f"The text does not place it in {name}")
    for part, word in (("start", "starts"), ("end", "ends")):
        q[f"{part}_day"] = ai.choice(
            f"If the text gives specific calendar dates, on which day of the month the trip {word}?",
            {**{str(d): None for d in range(1, 32)}, "none": none})
        q[f"{part}_month"] = ai.choice(
            f"If the text gives specific calendar dates, in which month the trip {word}?",
            {**{m: None for m in MONTHS}, "none": none})
    for key, (_, description) in PROFILES.items():
        q[f"who_{key}"] = ai.noul(description + ".", false="Not mentioned")
    return q


# --- Calendar maths: code, never the model ------------------------------------------
def _calendar_date(month: int, day: int, today: dt.date) -> dt.date:
    """The next occurrence of that day: a trip on 3 January asked in September is next year's."""
    date = dt.date(today.year, month, day)
    return date if date >= today - dt.timedelta(days=1) else dt.date(today.year + 1, month, day)


def resolve_dates(a: dict, today: dt.date) -> tuple[dt.date, dt.date] | None:
    sd, sm = a["start_day"]["choice"], a["start_month"]["choice"]
    ed, em = a["end_day"]["choice"], a["end_month"]["choice"]
    if sd == "none" or sm == "none":
        return None
    try:
        start = _calendar_date(MONTHS.index(sm) + 1, int(sd), today)
        end_month = MONTHS.index(em) + 1 if em != "none" else start.month
        end_day = int(ed) if ed != "none" else start.day
        end = dt.date(start.year, end_month, end_day)
        if end < start:  # "28 September to 3 October" without the month on the end
            end = (dt.date(start.year, end_month % 12 + 1, end_day) if em == "none"
                   else dt.date(start.year + 1, end_month, end_day))
    except ValueError:  # 31 June, 30 February…
        return None
    return (start, end) if (end - start).days <= 90 else None


def resolve_relative(kind: str, today: dt.date) -> tuple[dt.date, dt.date] | None:
    saturday = today + dt.timedelta(days=(5 - today.weekday()) % 7)
    monday = today + dt.timedelta(days=7 - today.weekday())
    return {
        "tomorrow": (today + dt.timedelta(days=1),) * 2,
        "next_few_days": (today, today + dt.timedelta(days=6)),
        "this_weekend": (saturday, saturday + dt.timedelta(days=1)),
        "next_weekend": (saturday + dt.timedelta(days=7), saturday + dt.timedelta(days=8)),
        "next_week": (monday, monday + dt.timedelta(days=6)),
        "in_two_weeks": (today + dt.timedelta(days=14), today + dt.timedelta(days=20)),
    }.get(kind)


def trip_months(start: dt.date, end: dt.date) -> set[int]:
    months, day = set(), start
    while day <= end:
        months.add(day.month)
        day = (day.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    return months


def plain(text: str) -> dict:
    """What the request means without AI: the whole text is the place."""
    return {"text": text, "by": None, "place": {"query": text, "confidence": None,
                                                "options": [{"text": text, "probability": None}]},
            "mode": None, "months": None, "trip": None, "profile": [], "notes": []}


async def run(text: str, today: dt.date | None = None) -> dict:
    text = " ".join(text.split())[:MAX_TEXT]
    if not ai.available() or geocoding.parse_coordinates(text):
        return plain(text)
    candidates = candidate_spans(text)
    if not candidates:
        return plain(text)
    today = today or dt.date.today()
    meter = ai.Meter()
    try:
        result = meter.add(await ai.ask({"request": text}, _questions(candidates)))
    except ai.AIUnavailable as exc:
        out = plain(text)
        out["notes"].append(f"AI interpretation unavailable ({exc}); the whole text was used as the place.")
        return out
    a = result["answers"]

    place = a["place"]
    ranked = sorted(((k, p) for k, p in place["probabilities"].items() if k != NO_PLACE),
                    key=lambda kp: -kp[1])
    options = [{"text": k, "probability": round(p, 3)} for k, p in ranked[:3]]
    notes = []
    if place["choice"] == NO_PLACE:
        notes.append("No place was recognised in the request; the most likely span was tried.")

    trip, months, timing = None, set(), a["timing"]
    if timing["choice"] == "dates":
        trip = resolve_dates(a, today)
    elif timing["choice"] == "relative":
        trip = resolve_relative(a["relative"]["choice"], today)
    if trip:
        months = trip_months(*trip)
    elif timing["choice"] != "none":
        months = {n for n in range(1, 13) if a[f"month_{n}"]["noul"] >= 0.5}

    mode = a["mode"]
    if mode["confidence"] >= 0.6:
        mode_value, mode_source = mode["choice"], "ai"
    else:
        mode_value, mode_source = ("travel" if (trip or months) else "home"), "default"
    if mode_value == "home" and (trip or months):
        notes.append("Home reports cover the whole year, so the dates in the request were not used.")
        trip, months = None, set()

    profile = [{"key": k, "label": PROFILES[k][0], "probability": round(a[f"who_{k}"]["noul"], 3)}
               for k in PROFILES if a[f"who_{k}"]["noul"] >= 0.5]
    return {
        "text": text, "by": result.get("model"),
        "place": {"query": ranked[0][0] if ranked else text,
                  "confidence": round(place["confidence"], 3), "options": options},
        "mode": {"value": mode_value, "confidence": round(mode["confidence"], 3),
                 "source": mode_source},
        "timing": {"kind": timing["choice"], "confidence": round(timing["confidence"], 3)},
        "months": sorted(months) or None,
        "trip": [trip[0].isoformat(), trip[1].isoformat()] if trip else None,
        "profile": profile, "notes": notes, "ai": meter.to_dict(),
    }


async def resolve_place(interpretation: dict) -> tuple[dict, str]:
    """Geocode the most likely span; if the geocoder does not know it, the next one."""
    last_error = None
    for option in interpretation["place"]["options"][:3] or [{"text": interpretation["text"]}]:
        try:
            return await geocoding.resolve(option["text"]), option["text"]
        except geocoding.GeocodingError as exc:
            last_error = exc
    raise last_error or geocoding.GeocodingError(f"no place found in '{interpretation['text']}'")
