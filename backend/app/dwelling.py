"""The home: a house or a flat, and on which floor.

It never changes a score: the hazard belongs to the place. It changes who acts on each
measure (the household or the building) and what the mapped flood water means for this
particular home.
"""

from __future__ import annotations

# A typical storey, floor to floor. Only used to say whether mapped water stays below a
# floor; the note says "about".
FLOOR_HEIGHT_M = 3.0


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def label(kind: str, floor: int | None) -> str:
    if kind == "house":
        return "House"
    if floor is None:
        return "Apartment"
    if floor < 0:
        return "Basement flat"
    if floor == 0:
        return "Ground-floor flat"
    return f"{ordinal(floor)}-floor flat"


def parse(kind: str | None, floor: str | int | None) -> dict | None:
    """The home as given by the person, or None when it was not given."""
    kind = (kind or "").strip().lower()
    if kind in ("building", "flat", "apartment_building", "apartment-building"):
        kind = "apartment"
    if kind not in ("house", "apartment"):
        return None
    value = None
    if kind == "apartment" and floor not in (None, ""):
        try:
            value = max(-3, min(150, int(str(floor).strip())))
        except ValueError:
            value = None
    return {"kind": kind, "floor": value, "label": label(kind, value)}


def _flood_card(report: dict) -> dict | None:
    return next((h for h in report.get("hazards", []) if h["key"] == "flood_zone"), None)


def _mapped_depth(card: dict) -> tuple[float, str] | None:
    """The reference water depth at the point and what it is (the 100-year flood...)."""
    for key in ("flood_depth_fluvial", "flood_zone_marine_t100", "flood_zone_marine_t500"):
        ind = next((i for i in card.get("indicators", []) if i.get("key") == key), None)
        if ind and isinstance(ind.get("value"), (int, float)) and ind["value"] > 0:
            label_text = ind["label"]
            if key == "flood_depth_fluvial":
                what = label_text.split(",", 1)[-1].strip() or "mapped flood"
            else:
                what = "100-year coastal flood" if key.endswith("t100") else "500-year coastal flood"
            return float(ind["value"]), what
    return None


def flood_note(report: dict, dwelling: dict | None) -> str | None:
    """What the official flood map means for this home, in one sentence."""
    if not dwelling:
        return None
    card = _flood_card(report)
    if not card or not card.get("score"):
        return None
    floor = dwelling.get("floor")
    raised = dwelling["kind"] == "apartment" and floor is not None and floor >= 1
    depth = _mapped_depth(card)
    if depth:
        metres, what = depth
        if raised:
            level = floor * FLOOR_HEIGHT_M
            if metres < level:
                return (f"The mapped water ({metres:.2f} m in the {what}) would stay below your "
                        f"{ordinal(floor)} floor, about {level:.0f} m up, but the entrance, lifts, "
                        f"storage rooms and car park would flood.")
            return (f"The mapped water ({metres:.2f} m in the {what}) could reach your "
                    f"{ordinal(floor)} floor.")
        if dwelling["kind"] == "apartment" and floor is not None and floor < 0:
            return (f"A basement floods first: the mapped water reaches {metres:.2f} m at street "
                    f"level in the {what}.")
        return (f"At street level the mapped water reaches {metres:.2f} m in the {what}: a house "
                f"or ground floor takes it directly.")
    if card["score"] >= 40:
        if raised:
            return ("Your floor is above the street, but the building's entrance, lifts and car "
                    "park are inside the official flood zone.")
        return "Your home is at street level inside the official flood zone."
    return None


def describe(report: dict, dwelling: dict | None) -> dict | None:
    """The home as the report carries it, with the notes it adds per hazard family."""
    if not dwelling:
        return None
    notes = {}
    flood = flood_note(report, dwelling)
    if flood:
        notes["flood"] = flood
    return {**dwelling, "notes": notes,
            "rule": "The home never changes a score: the hazard belongs to the place."}
