"""Public money for protecting the home: grants, tax deductions and public cover.

A hand-checked catalogue: every programme carries its official page, its legal reference,
the date it was checked and its deadline. It is matched to the report by three things:

  - where the home is: Spain, Catalonia, the province or the municipality;
  - which risks matter here: those worth preparing for today and those the 2050 view
    projects to grow (warm nights by the sea make heat-protection works relevant even
    when today's heat score is low);
  - who can apply: the household, the owners' association (works on a block of flats),
    the town hall, or anyone after damage.

Nothing here scores, and a programme never changes which risks or measures are shown.
Amounts and deadlines change: the official page decides, and the view says so.
"""

from __future__ import annotations

import datetime as dt

CHECKED = "2026-09-19"

# Who applies, in the order the panel shows them.
GROUPS = [
    ("household", "You can apply",
     "Programmes a household applies for itself, for works in its own home."),
    ("owners", "Your owners' association can apply",
     "Works on the building or the plot are decided and applied for by the owners together."),
    ("municipality", "Your town hall applies",
     "Public bodies apply for these; ask the town hall whether it has done so for your street."),
    ("after", "If damage happens",
     "Money that pays out after a flood, a storm or a fire, not before."),
]

STATUS_LABELS = {"open": "Open", "permanent": "Always open", "upcoming": "Coming soon",
                 "closed": "Closed"}

# Families of the app's four risks.
FAMILIES = ("wildfire", "flood", "heat", "avalanche")

# The catalogue. `where` is one of {"country": "ES"}, {"region": "Catalonia"},
# {"provinces": [...]} or {"municipalities": [INE codes]}; `families` are the risks it pays
# to protect against; `who` is one of GROUPS; `deadline` is an ISO date or None.
PROGRAMMES: list[dict] = []


def _municipality(report: dict) -> dict:
    return (report.get("coverage") or {}).get("municipality") or {}


def _applies_here(programme: dict, report: dict) -> bool:
    where = programme["where"]
    coverage = report.get("coverage") or {}
    region = coverage.get("region")
    code = str(_municipality(report).get("code") or "")
    if "municipalities" in where:
        return code in where["municipalities"]
    if "provinces" in where:
        return code[:2] in where["provinces"]
    if "region" in where:
        return region == where["region"]
    if where.get("country") == "ES":
        return region in ("Spain", "Catalonia")
    return False


def _relevant_families(tiles: list[dict], ahead: dict | None) -> set[str]:
    """The risks worth preparing for today, plus those the 2050 view sees growing."""
    worth = {t["key"] for t in tiles if t.get("worth")}
    growing = {k for k, r in ((ahead or {}).get("risks") or {}).items() if r.get("direction") == "up"}
    return worth | growing


def _status(programme: dict, today: dt.date) -> str:
    status = programme["status"]
    deadline = programme.get("deadline")
    if deadline and status in ("open", "permanent") and dt.date.fromisoformat(deadline) < today:
        return "closed"
    return status


def _status_label(status: str, deadline: str | None) -> str:
    if status == "open" and deadline:
        day = dt.date.fromisoformat(deadline)
        return f"Open until {day.day} {day.strftime('%b')} {day.year}"
    if status == "permanent" and deadline:
        day = dt.date.fromisoformat(deadline)
        return f"Until {day.day} {day.strftime('%b')} {day.year}"
    return STATUS_LABELS.get(status, status)


def _item(programme: dict, status: str, dwelling: dict | None) -> dict:
    group = programme["who"]
    # In a house the household is also the owner of the building: nobody else decides.
    if group == "owners" and (dwelling or {}).get("kind") == "house":
        group = "household"
    return {
        "id": programme["id"], "name": programme["name"],
        "official_name": programme.get("official_name"), "body": programme["body"],
        "families": [f for f in programme["families"] if f in FAMILIES],
        "funds": programme["funds"], "amount": programme["amount"],
        "note": programme.get("note"), "group": group,
        "status": status, "status_label": _status_label(status, programme.get("deadline")),
        "deadline": programme.get("deadline"), "url": programme["url"],
        "ref": programme.get("ref"), "checked": programme.get("checked", CHECKED),
    }


def _count(n: int) -> str:
    return f"{n} public programme{'s' if n != 1 else ''}"


FAMILY_WORDS = {"flood": "flood protection", "wildfire": "fire protection",
                "heat": "keeping the heat out", "avalanche": "avalanche protection"}


def for_report(report: dict, tiles: list[dict], ahead: dict | None = None,
               today: dt.date | None = None) -> dict:
    """The programmes that can pay for part of this home's plan, grouped by who applies."""
    today = today or dt.date.today()
    families = _relevant_families(tiles, ahead)
    dwelling = report.get("dwelling")
    items = []
    for p in PROGRAMMES:
        if not _applies_here(p, report):
            continue
        status = _status(p, today)
        if status == "closed":
            continue
        if not (set(p["families"]) & families):
            continue
        items.append(_item(p, status, dwelling))
    order = {g[0]: i for i, g in enumerate(GROUPS)}
    items.sort(key=lambda i: (order[i["group"]], i["status"] != "open", i["deadline"] or "9999"))
    before = [i for i in items if i["group"] != "after"]
    by_family = {}
    for key in FAMILIES:
        mine = [i for i in items if key in i["families"]]
        if mine:
            paying = [i for i in mine if i["group"] != "after"]
            by_family[key] = {
                "count": len(mine),
                "text": (f"{_count(len(paying))} can help pay for {FAMILY_WORDS[key]}"
                         if paying else f"{_count(len(mine))} if damage happens"),
            }
    muni = _municipality(report).get("name")
    return {
        "items": items,
        "groups": [{"key": k, "label": label, "note": note} for k, label, note in GROUPS
                   if any(i["group"] == k for i in items)],
        "families": by_family,
        "summary": (f"{_count(len(before))} can help pay for your plan here"
                    if before else f"{_count(len(items))} if damage happens") if items else None,
        "intro": (f"Grants, tax deductions and public cover that apply to a home in "
                  f"{muni or 'this place'}, for the risks that matter here."),
        "note": (f"Checked on {dt.date.fromisoformat(CHECKED).day} "
                 f"{dt.date.fromisoformat(CHECKED).strftime('%B %Y')}. Amounts, conditions and "
                 f"deadlines change and the official page decides; Previous AI does not process "
                 f"applications."),
        "checked": CHECKED,
    }
