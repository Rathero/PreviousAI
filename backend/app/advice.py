"""Advice ranked for the household.

The advice bank is hand-written (`narrative.py`) and the AI never adds to it. What the
AI decides is which items matter for THESE people at THIS place: a family with children
in a hot town needs the heat advice for children before the generic one about solar
protection on façades. One yes/no question per candidate item, all in a single call; the
ranking mixes the AI's relevance with the hazard's score, in code.

Without a request text or a household profile there is nothing to personalise and the
default advice stays. Without an AI key, the profile items that match come first, by
hazard score.
"""

from __future__ import annotations

from . import narrative
from .interpret import PROFILES
from .providers import ai

MIN_SCORE = 30
MAX_ITEMS = 6
MAX_PER_HAZARD = 2
# Months of the Catalan daily avalanche bulletin (December to May, roughly).
SNOW_SEASON = {12, 1, 2, 3, 4, 5}
# On a trip, recorded-wildfire advice only makes sense if the weather of those months
# favours fire at all.
TRAVEL_FIRE_WEATHER_MIN = 10
# By the sea the heat card can score low (35 °C is rare) while the nights do not cool
# down. From these counts of tropical nights the heat advice is offered. Over a seasonal
# window the count is an annual equivalent: 120 means a third of the nights.
TROPICAL_NIGHTS_MIN = {"home": 30, "travel": 120}


def advised_hazards(report: dict) -> list[dict]:
    """Hazards whose advice applies, by score, with seasonal exceptions for trips.

    Warm nights bring the heat advice even when 35 °C is rare. A ski week in a town far
    from the nearest avalanche path scores low at the hotel, but the danger is on the
    slopes: inside a snow-climate zone of the avalanche bulletin, in the snow season,
    the avalanche advice is offered. A winter trip does not get summer wildfire advice.
    """
    hazards = [h for h in report["hazards"] if (h["score"] or 0) >= MIN_SCORE]
    heat = next((h for h in report["hazards"] if h["key"] == "heat"), None)
    nights = next((i.get("value") for i in (heat or {}).get("indicators", [])
                   if i["key"] == "tropical_nights"), None)
    if heat and heat not in hazards and (nights or 0) >= TROPICAL_NIGHTS_MIN.get(report.get("mode"), 30):
        hazards.append(heat)
    if report.get("mode") != "travel":
        return hazards[:6]
    months = set((report.get("window") or {}).get("months") or [])
    fire_weather = next((h for h in report["hazards"] if h["key"] == "wildfire"), None)
    if fire_weather and (fire_weather["score"] or 0) < TRAVEL_FIRE_WEATHER_MIN:
        hazards = [h for h in hazards if h["key"] not in ("fire_history", "wildfire")]
    avalanche = next((h for h in report["hazards"] if h["key"] == "avalanche"), None)
    in_bulletin = avalanche and any(i["key"] == "avalanche_bulletin_zone" for i in avalanche["indicators"])
    if in_bulletin and months & SNOW_SEASON and avalanche not in hazards:
        hazards.append(avalanche)
    return hazards[:6]


def candidates(report: dict, profile: list[str]) -> list[dict]:
    hazards = advised_hazards(report)
    bank = narrative.TRAVEL_ADVICE if report["mode"] == "travel" else narrative.ADVICE
    out = []
    for h in hazards:
        for text in bank.get(h["key"], []):
            out.append({"text": text, "hazard": h["key"], "hazard_label": h["label"],
                        "profiles": [], "weight": h["score"]})
    wanted = set(profile)
    for item in narrative.PROFILE_ADVICE:
        who = sorted(wanted & set(item["profiles"]))
        matched = [h for h in hazards if h["key"] in item["hazards"]]
        if who and matched:
            out.append({"text": item["text"], "hazard": matched[0]["key"],
                        "hazard_label": matched[0]["label"], "profiles": who,
                        "weight": matched[0]["score"]})
    return out


def describe(person_text: str | None, profile: list[str], mode: str) -> str:
    who = ", ".join(PROFILES[k][0].lower() for k in profile if k in PROFILES)
    situation = "planning a trip" if mode == "travel" else "living in, buying or renting a home"
    parts = [f"Situation: {situation}."]
    if person_text:
        parts.append(f"In their own words: \"{person_text}\".")
    if who:
        parts.append(f"Who is involved: {who}.")
    return " ".join(parts)


def _pick(items: list[dict]) -> list[dict]:
    out, per = [], {}
    for item in items:
        if per.get(item["hazard"], 0) >= MAX_PER_HAZARD:
            continue
        per[item["hazard"]] = per.get(item["hazard"], 0) + 1
        out.append({k: v for k, v in item.items() if k != "weight"})
        if len(out) == MAX_ITEMS:
            break
    return out


async def personalize(report: dict, person_text: str | None, profile: list[str]) -> dict | None:
    if not person_text and not profile:
        return None
    pool = candidates(report, profile)
    if not pool:
        return None
    person = describe(person_text, profile, report["mode"])
    labels = [PROFILES[k][0] for k in profile if k in PROFILES]
    who = {"person": person, "profile": labels, "profile_keys": [k for k in profile if k in PROFILES]}

    if not ai.available():
        ordered = sorted(pool, key=lambda c: (not c["profiles"], -c["weight"]))
        return {"items": _pick([{**c, "relevance": None} for c in ordered]), "by": "deterministic",
                **who}

    top = advised_hazards(report)
    state = {
        "person": person,
        "place": report["location"]["label"],
        "main hazards at this place": [f"{h['label']}: {h['level']} ({h['score']}/100). {h['headline']}"
                                       for h in top],
    }
    questions = {
        f"a{i}": ai.noul(
            f"This advice is relevant and useful for this person at this place: \"{c['text']}\"",
            true="It addresses one of the hazards listed for this place and suits this "
                 "person and their situation",
            false="It concerns a hazard that is not listed, or it does not fit this person "
                  "or their situation")
        for i, c in enumerate(pool)
    }
    meter = ai.Meter()
    try:
        result = meter.add(await ai.ask(state, questions))
    except ai.AIUnavailable as exc:
        ordered = sorted(pool, key=lambda c: (not c["profiles"], -c["weight"]))
        return {"items": _pick([{**c, "relevance": None} for c in ordered]), "by": "deterministic",
                **who, "note": f"AI ranking unavailable: {exc}"}

    for i, c in enumerate(pool):
        c["relevance"] = round(result["answers"][f"a{i}"]["noul"], 3)
    # Relevance decides; the hazard's score breaks ties between equally relevant items.
    ranked = sorted(pool, key=lambda c: -(c["relevance"] * (0.6 + 0.4 * c["weight"] / 100)))
    chosen = _pick([c for c in ranked if c["relevance"] >= 0.5])
    if len(chosen) < 3:  # never less advice than the default
        chosen = _pick(ranked)
    return {"items": chosen, "by": result.get("model"), **who, "ai": meter.to_dict()}
