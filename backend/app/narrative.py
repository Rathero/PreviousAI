"""The report in words, written by code.

The data calculate; this module only reorders and puts into words the values already
calculated, and never invents a number. The advice bank below is hand-written:
`advice.py` chooses from it (with the AI, by relevance to the household) but never
writes new advice.
"""

from __future__ import annotations

from .hazards import MONTHS_EN

# Home: what to check when living in, buying or renting a home.
ADVICE = {
    "heat": [
        "Check whether the home has solar protection on its south and west façades; "
        "it is more effective and cheaper than a bigger air conditioner.",
        "Find the coolest spot in the home and the nearest public climate shelter "
        "before the first heatwave arrives.",
        "Tropical nights are the dangerous ones: if it does not drop below 20 degrees at "
        "night, the body does not recover. Make sure the bedroom can be ventilated or cooled.",
    ],
    "rain": [
        "If there is a garage, basement or ground floor, that is the weak point: check "
        "the drains, gullies and whether there is a non-return valve.",
        "Look at the official flood-zone mapping before signing anything "
        "(in Spain, MITECO's SNCZI viewer).",
        "Check that the insurance covers water damage and how extraordinary floods are "
        "covered where you live (in Spain, the Consorcio de Compensación de Seguros).",
    ],
    "wildfire": [
        "Check the real distance to continuous forest and whether there is a "
        "perimeter firebreak.",
        "The materials of the eaves, the roof and the ventilation openings matter more "
        "than distance: embers get in through there.",
        "Know two different evacuation routes. A single one is not a plan.",
    ],
    "flood_zone": [
        "In a preferential flow zone water law limits the permitted uses: before "
        "buying or renovating, check the SNCZI viewer and the municipal land-use plan.",
        "Check in the SNCZI viewer whether water depths are published for your stretch: "
        "20 cm is not the same as a metre and a half of water.",
    ],
    "flood_history": [
        "Ask the neighbours and the town hall how far the water reached in the recorded "
        "episodes: the real mark is worth more than any map.",
    ],
    "sea_level": [
        "With a few centimetres of rise the problem is not only permanent water: storms "
        "reach much further. Check the ground floor's height relative to the street.",
    ],
    "fire_history": [
        "That fire has burnt nearby points to continuous vegetation and favourable "
        "conditions: check that the development keeps its perimeter protection strip clear.",
    ],
    "avalanche": [
        "In an avalanche zone, ask whether the building is protected (snow fences, "
        "deflecting walls, reforestation) and whether the access road closes in winter.",
        "Find out which snow-climate zone you are in and follow its daily avalanche bulletin "
        "all winter: danger 3 out of 5 is where most fatal accidents happen.",
    ],
    "flood_regional": [
        "The regional level only says there are floods in the area: look for the "
        "country's or municipality's official flood-zone map before deciding.",
        "Check whether the home insurance covers flooding; in many countries it is separate.",
    ],
}

# Trip: what to do before and during a stay.
TRAVEL_ADVICE = {
    "heat": [
        "Plan outdoor activities before 11:00 and after 18:00, and check that the "
        "accommodation has real cooling.",
        "Carry water all day and plan a cool indoor stop (a museum, a café) for the "
        "middle of the day.",
        "Where nights stay above 20 degrees, choose accommodation with air conditioning "
        "or cross ventilation in the bedrooms: children and older people recover from "
        "the heat at night.",
    ],
    "rain": [
        "Take travel insurance that covers cancellation for bad weather and have an "
        "indoor alternative for each day.",
    ],
    "wildfire": [
        "Check active fires in the days before and keep the local emergency number handy.",
    ],
    "flood_zone": [
        "Avoid ground-floor rooms next to the river and follow Civil Protection warnings "
        "if heavy rain is announced.",
    ],
    "flood_history": [
        "If heavy rain is announced, do not cross fords or flooded streams: it is the most "
        "common cause of deaths.",
    ],
    "fire_history": [
        "Before heading into the hills in Catalonia, check that day's access restrictions "
        "under the Pla Alfa.",
    ],
    "flood_regional": [
        "Avoid ground-floor accommodation next to rivers or on the seafront if heavy rain "
        "is announced.",
    ],
    "avalanche": [
        "Check the avalanche bulletin for your zone every day before going out; at danger "
        "3 or more, stay on marked, controlled slopes.",
        "Off-piste or on a snowshoe route, carry a transceiver, shovel and probe, and know "
        "how to use them: without them, the chances of a buried person drop fast after "
        "15 minutes.",
    ],
}

# Advice for who lives there or is going. Chosen only when the household matches, and
# ranked by the AI against the place's hazards.
PROFILE_ADVICE = [
    {"hazards": ["heat"], "profiles": ["children"],
     "text": "Children overheat faster than adults: plan shade and water breaks every hour, "
             "and never leave them in a parked car, even for a few minutes."},
    {"hazards": ["heat"], "profiles": ["older_adults"],
     "text": "People over 65 often do not feel thirst: set reminders to drink and check on "
             "them twice a day during heatwaves; many heat deaths happen alone at home."},
    {"hazards": ["heat"], "profiles": ["pregnancy"],
     "text": "Heat raises the risks of pregnancy: avoid the hottest hours and stay in cool, "
             "air-conditioned places."},
    {"hazards": ["heat"], "profiles": ["outdoor"],
     "text": "Start hikes at dawn and finish before noon; carry at least a litre of water "
             "per hour of walking in the heat."},
    {"hazards": ["wildfire", "fire_history"], "profiles": ["respiratory"],
     "text": "Wildfire smoke travels hundreds of kilometres: an FFP2 mask and a room with a "
             "HEPA filter protect the lungs on smoky days."},
    {"hazards": ["wildfire", "fire_history"], "profiles": ["outdoor"],
     "text": "Check the day's forest access restrictions before hiking: on high-danger days "
             "many trails close and any use of fire is banned."},
    {"hazards": ["wildfire", "fire_history"],
     "profiles": ["reduced_mobility", "older_adults"],
     "text": "If someone needs help to move, evacuate at the first warning, not the last, "
             "and tell the local civil protection service in advance."},
    {"hazards": ["flood_zone", "flood_history", "flood_regional", "rain"],
     "profiles": ["reduced_mobility", "older_adults"],
     "text": "Avoid ground-floor or basement bedrooms: if the water rises you need to go up, "
             "not out."},
    {"hazards": ["flood_zone", "flood_history", "flood_regional", "rain"], "profiles": ["children"],
     "text": "Teach children never to walk or play near swollen streams, storm drains or "
             "flooded underpasses."},
    {"hazards": ["rain", "flood_history", "flood_regional"], "profiles": ["outdoor"],
     "text": "Never camp in a dry riverbed: flash floods arrive in minutes, even when it is "
             "not raining where you are."},
    {"hazards": ["avalanche"], "profiles": ["outdoor"],
     "text": "Plan routes with the avalanche bulletin and a slope-angle map: most avalanches "
             "start on slopes of 30-45 degrees, often ones that look harmless from below."},
    {"hazards": ["avalanche"], "profiles": ["children", "older_adults", "reduced_mobility"],
     "text": "In avalanche country, stay on open, groomed pistes and marked paths with anyone "
             "who could not move quickly out of a slope's runout zone."},
]

PROJECTION_METRIC_EN = {
    "hot_days_35": "days above 35 °C",
    "hot_days_32": "days above 32 °C",
    "rx1day": "rain on the wettest day",
}


def _lower_first(text: str) -> str:
    """Lower case on the first letter only, so proper names inside headlines survive."""
    return text[:1].lower() + text[1:] if text else text


def summarize(report: dict) -> dict:
    """Headline, paragraphs and default advice from the indicators."""
    place = report["location"]["label"]
    mode = report["mode"]
    hazards = sorted(
        [h for h in report["hazards"] if h["score"] is not None],
        key=lambda h: -h["score"],
    )
    if not hazards:
        return {"headline": "Not enough data", "paragraphs": [], "advice": [],
                "generated_by": "deterministic"}

    top = hazards[0]
    others = [h for h in hazards[1:] if h["score"] >= 40]
    score = report["overall"]["score"]
    level = report["overall"]["level"]

    if mode == "travel":
        months = report.get("window", {}).get("months", [])
        month_text = " and ".join(MONTHS_EN[m] for m in months) if months else "the chosen period"
        headline = (
            f"For {place} in {month_text}, the natural hazard risk is {level} ({score}/100), "
            f"and the main one is {top['label'].lower()}."
        )
    else:
        headline = (
            f"In {place} the natural hazard risk is {level} ({score}/100), "
            f"and the main one is {top['label'].lower()}."
        )

    paragraphs = [top["headline"] + "."]
    if others:
        paragraphs.append(
            "Also significant: "
            + "; ".join(f"{h['label'].lower()} ({_lower_first(h['headline'])})" for h in others[:3])
            + "."
        )

    # Trends are only mentioned when they pass the statistical test.
    moving = []
    for hazard in hazards:
        for ind in hazard["indicators"]:
            if ind.get("trend_significant") and ind.get("trend_per_decade"):
                direction = "rising" if ind["trend_per_decade"] > 0 else "falling"
                label = ind["label"][0].lower() + ind["label"][1:]
                moving.append(
                    f"{label} is {direction} "
                    f"({ind['trend_per_decade']:+.1f} {ind['unit'].split('/')[0]} per decade)"
                )
    if moving:
        paragraphs.append("The local climate is shifting: " + "; ".join(moving[:3]) + ".")

    projection_bits = []
    for hazard in hazards:
        proj = hazard.get("projection")
        if not proj:
            continue
        for m in proj["metrics"]:
            if m["delta"] and abs(m["delta"]) >= 1:
                name = PROJECTION_METRIC_EN.get(m["key"], hazard["label"].lower())
                projection_bits.append(f"{name}: {m['baseline']} -> {m['future']} {m['unit']}")
    if projection_bits:
        paragraphs.append(
            "Mid-century projection (CMIP6, high-emissions scenario): "
            + "; ".join(projection_bits[:3]) + "."
        )

    return {
        "headline": headline,
        "paragraphs": paragraphs,
        "advice": default_advice(hazards, mode),
        "generated_by": "deterministic",
    }


def default_advice(hazards: list[dict], mode: str) -> list[dict]:
    """Advice without AI: the first items of the three worst hazards."""
    bank = TRAVEL_ADVICE if mode == "travel" else ADVICE
    out = []
    for hazard in hazards[:3]:
        for text in bank.get(hazard["key"], [])[:1 if mode == "travel" else 2]:
            out.append({"text": text, "hazard": hazard["key"], "hazard_label": hazard["label"],
                        "profiles": [], "relevance": None})
    return out[:6]
