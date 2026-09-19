"""The Action plan: a basic emergency plan and one plan per hazard present at the home.

The content is hand-written and fixed. What the report decides is only which hazard
plans appear and in which order: the families that apply at this address, worst first.
Each hazard plan has four phases (before, buy or arrange, during, after). Partner names
in "Buy or arrange" are links; partners never change a score or which plans appear.
A step to buy something can carry real products (`products.py`): a photo, the price and
a direct link to the store's page.
"""

from __future__ import annotations

import re

from . import products as P

# Hazard plans appear for families at or above this score, and always the worst one.
MIN_SCORE = 20

PARTNERS = {
    "leroy_merlin": {"name": "Leroy Merlin", "url": "https://www.leroymerlin.es/"},
    "verisure": {"name": "Verisure", "url": "https://www.verisure.es/"},
    "catalana_occidente": {"name": "Catalana Occidente", "url": "https://www.catalanaoccidente.com/"},
    "mapfre": {"name": "Mapfre", "url": "https://www.mapfre.es/"},
    "xiaomi": {"name": "Xiaomi", "url": "https://www.mi.com/es/"},
    "applus": {"name": "Applus+", "url": "https://www.applus.com/"},
    "bureau_veritas": {"name": "Bureau Veritas", "url": "https://www.bureauveritas.es/"},
    "cortizo": {"name": "Cortizo", "url": "https://www.cortizo.com/"},
    "ortovox": {"name": "Ortovox", "url": "https://www.ortovox.com/"},
    "mitsubishi_electric": {"name": "Mitsubishi Electric", "url": "https://www.mitsubishielectric.es/"},
    "isover": {"name": "ISOVER (Saint-Gobain)", "url": "https://www.isover.es/"},
}

EMERGENCY_PLAN = {
    "key": "emergency",
    "label": "Emergency plan",
    "title": "First: your basic emergency plan",
    "items": [
        "Enable Civil Protection alerts.",
        "Save: 112, 061, insurer and utility numbers.",
        "Install My112: [Android](https://play.google.com/store/apps/details?id=com.telefonica.my112) · "
        "[iPhone](https://apps.apple.com/es/app/my112/id804779618)",
        "Pack an emergency bag.",
        ("Store water, medicines, torch, radio and power bank.",
         ["midland_er300_pro", "xiaomi_power_bank"]),
        "Waterproof IDs and insurance documents.",
        "Plan a stair-only exit.",
        "Include children, older or disabled people, and pets.",
        "Locate electricity, water and gas shut-offs.",
        "Photograph your home and belongings.",
    ],
}

# Partners are written {like_this} and become links; other brands stay plain text. A step
# is its text, or (text, [product ids]) when it proposes products to buy.
PLANS = {
    "flood": {
        "label": "Floods",
        "phases": [
            ("before", "Before a flood", [
                "Clean gutters, drains and downpipes.",
                "Identify a safe higher floor or nearby high ground.",
                "Move chemicals, appliances and valuables upstairs.",
                "Move your car out of underground parking when warned.",
            ]),
            ("buy", "Buy or arrange", [
                ("Water alarms for low areas, or a 24/7 monitored sensor from {verisure}.",
                 ["shelly_flood_gen4", "garza_leak_alarm"]),
                ("Raised storage shelves.", ["spaceo_shelving"]),
                ("Removable flood barriers for doors and the garage, and water-activated sacks "
                 "for the gaps.", ["mbm_flood_barrier", "hydrosnake_sacks"]),
                ("A sump pump with a float switch, and a non-return valve on the drains — fitted "
                 "by the {leroy_merlin} installation service.",
                 ["gardena_20000_pump", "karmat_backwater_valve"]),
                "Check whether your home insurance already covers flood damage, or get a quote — "
                "{catalana_occidente} or {mapfre}.",
            ]),
            ("during", "During a flood", [
                "Follow official instructions.",
                "Move to a higher floor. Do not use the lift.",
                "Never enter a basement or underground garage.",
                "Never walk or drive through floodwater.",
                "Switch off electricity only if safely accessible.",
                "Call 112 if anyone is in danger.",
            ]),
            ("after", "After the flood", [
                "Return only when authorities say it is safe.",
                "Do not restore electricity or gas without a professional check.",
                "Use bottled water if tap water may be unsafe.",
                "Photograph the damage and contact your insurer — {catalana_occidente} or "
                "{mapfre} claims line.",
            ]),
        ],
    },
    "wildfire": {
        "label": "Wildfires",
        "phases": [
            ("before", "Before a wildfire", [
                "Remove dry leaves, plants and branches.",
                "Keep branches away from the roof and walls.",
                "Move firewood, fuel and gas bottles away from the home.",
                "Clear emergency access roads.",
                "Remove flammable items from balconies and terraces.",
            ]),
            ("buy", "Buy or arrange", [
                ("Smoke alarms, or a monitored alarm from {verisure}.",
                 ["xsense_wifi_smoke", "garza_smoke_pack"]),
                ("Fire extinguisher and fire blanket.",
                 ["ferretelix_extinguisher", "securikit_fire_blanket"]),
                ("HEPA air purifier for a room you can close — {xiaomi} or Equation.",
                 ["xiaomi_purifier_4_compact", "equation_air_corner"]),
                ("FFP2 masks.", ["3m_ffp2_masks"]),
                ("Long garden hose.", ["geolia_hose_30m"]),
                ("Metal mesh over vents, eaves and gutters, so embers cannot get in.",
                 ["saturnia_ember_mesh"]),
                "Professional vegetation and roof inspection — {applus} or {bureau_veritas} "
                "technical inspection service.",
            ]),
            ("during", "During a wildfire", [
                "Follow official instructions.",
                "Evacuate immediately if ordered.",
                "If told to shelter, stay inside.",
                "Close doors, windows, shutters and ventilation.",
                "Stay away from windows and smoke.",
                "Never stay outside to protect the property.",
                "Call 112 if anyone is in danger.",
            ]),
            ("after", "After the wildfire", [
                "Return only when authorities say it is safe.",
                "Watch for hot embers and damaged structures.",
                "Keep children and pets away from ash.",
                "Photograph the damage and contact your insurer — {catalana_occidente} or "
                "{mapfre} claims line.",
            ]),
        ],
    },
    "avalanche": {
        "label": "Avalanches",
        "phases": [
            ("before", "Before an avalanche", [
                "Identify the mountain-facing side of your home and choose a safe room on the "
                "opposite side.",
                "Keep external shutters in good condition.",
                "Have the roof and structure professionally checked — {applus} or "
                "{bureau_veritas} technical inspection.",
                "Prepare for road closures and power cuts.",
            ]),
            ("buy", "Buy or arrange", [
                "Strong external shutters — {cortizo} aluminium systems, installed via "
                "{leroy_merlin}.",
                "Roof and structural inspection — {applus} or {bureau_veritas} technical "
                "inspection service.",
                "Reinforcement recommended by a qualified engineer — follow-up work certified by "
                "{applus} or {bureau_veritas}.",
                ("For mountain activities: a transceiver, probe and shovel for each person, and "
                 "training to use them — or an {ortovox} kit.", ["arva_evo4_pack"]),
            ]),
            ("during", "During an avalanche alert", [
                "Follow official instructions.",
                "Stay inside and close the shutters.",
                "Move away from windows and the mountain-facing wall.",
                "Do not go outside or use mountain roads.",
                "Call 112 if the building is hit or someone is trapped.",
            ]),
            ("after", "After the avalanche", [
                "Wait for official permission before going outside.",
                "Be alert for further avalanches.",
                "Have structural and utility damage checked — {applus} or {bureau_veritas} "
                "technical inspection.",
                "Photograph the damage and contact your insurer — {catalana_occidente} or "
                "{mapfre} claims line.",
            ]),
        ],
    },
    "heat": {
        "label": "Heat waves",
        "phases": [
            ("before", "Before extreme heat", [
                "Install or maintain external blinds and awnings.",
                "Check air conditioning and home insulation.",
                "Choose the coolest room in your home.",
                "Plan where to go if your home becomes too hot.",
                "Arrange daily checks for vulnerable people.",
            ]),
            ("buy", "Buy or arrange", [
                ("Indoor thermometer.", ["xiaomi_th_monitor_2"]),
                ("External blinds or awnings.", ["naterial_calima_awning"]),
                ("Fan.", ["arte_confort_cacela_fan"]),
                ("Air conditioner or heat pump — {mitsubishi_electric} or Daikin units, installed "
                 "via {leroy_merlin} or a local installer.", ["mitsubishi_msz_ay35"]),
                ("Roof or attic insulation — {isover} materials, installed via {leroy_merlin} or a "
                 "local installer.", ["isover_ibr80"]),
            ]),
            ("during", "During extreme heat", [
                "Close blinds before direct sunlight enters.",
                "Keep windows closed when it is hotter outside.",
                "Open windows at night when it is cooler.",
                "Drink water regularly.",
                "Avoid exercise and direct sun during the hottest hours.",
                "Move to a cooled place if your home stays too hot.",
                "Never leave people or pets in a parked car.",
                "Call 112 or 061 for confusion, collapse or unconsciousness.",
            ]),
            ("after", "After extreme heat", [
                "Continue checking vulnerable people.",
                "Check food and medicines after a power cut.",
                "Review which rooms became too hot.",
                "Improve cooling, shading or insulation before the next event — {isover} or "
                "{mitsubishi_electric}, installed via {leroy_merlin}.",
            ]),
        ],
    },
}

_TOKEN = re.compile(r"\{([a-z_]+)\}|\[([^\]]+)\]\((https?://[^)]+)\)")


def segments(text: str) -> list[dict]:
    """A line as text runs and links: partners ({id}) and plain links ([label](url))."""
    out, pos = [], 0
    for m in _TOKEN.finditer(text):
        if m.start() > pos:
            out.append({"text": text[pos:m.start()]})
        if m.group(1):
            p = PARTNERS[m.group(1)]
            out.append({"text": p["name"], "url": p["url"], "partner": m.group(1)})
        else:
            out.append({"text": m.group(2), "url": m.group(3)})
        pos = m.end()
    if pos < len(text):
        out.append({"text": text[pos:]})
    return out


def _product(pid: str) -> dict:
    """A product as the plan shows it; `partner` when the store is one of the partners."""
    p = P.PRODUCTS[pid]
    return {"id": pid, "name": p["name"], "what": p["what"], "price": p["price"],
            "store": P.STORES[p["store"]], "url": p["url"], "image": p["image"],
            "partner": p["store"] if p["store"] in PARTNERS else None}


def _item(plan: str, phase: str, n: int, step: str | tuple[str, list[str]]) -> dict:
    text, products = (step, []) if isinstance(step, str) else step
    segs = segments(text)
    return {"id": f"{plan}.{phase}.{n}", "segments": segs,
            "partners": sorted({s["partner"] for s in segs if s.get("partner")}),
            "products": [_product(pid) for pid in products]}


def _emergency() -> dict:
    return {"key": EMERGENCY_PLAN["key"], "label": EMERGENCY_PLAN["label"],
            "title": EMERGENCY_PLAN["title"],
            "items": [_item("emergency", "first", i, t) for i, t in enumerate(EMERGENCY_PLAN["items"])]}


def _hazard_plan(key: str, family: dict | None, note: str | None) -> dict:
    spec = PLANS[key]
    return {
        "key": key, "label": spec["label"],
        "score": family.get("score") if family else None,
        "level": family.get("level") if family else None,
        "note": note,
        "phases": [{"key": ph, "label": label,
                    "items": [_item(key, ph, i, t) for i, t in enumerate(items)]}
                   for ph, label, items in spec["phases"]],
    }


def build(report: dict) -> dict:
    """The emergency plan, then the plan of every hazard present here, worst first."""
    families = {f["key"]: f for f in (report.get("protection") or {}).get("families", [])}
    present = sorted((f for f in families.values() if f.get("applies") and f.get("score") is not None),
                     key=lambda f: -f["score"])
    chosen = [f for f in present if f["score"] >= MIN_SCORE] or present[:1]
    notes = (report.get("dwelling") or {}).get("notes") or {}
    # With a household profile, the advice ranked for it (the AI picks, never writes),
    # items written for those people first.
    ranked = ((report.get("narrative") or {}).get("advice") or []) if report.get("personalization") else []
    ranked = sorted(ranked, key=lambda a: not a.get("profiles"))
    household = [{"text": a["text"], "hazard_label": a.get("hazard_label"),
                  "profiles": a.get("profiles") or [], "relevance": a.get("relevance")}
                 for a in ranked[:3]]
    return {
        "plans": [_emergency()] + [_hazard_plan(f["key"], f, notes.get(f["key"])) for f in chosen],
        "household": household,
        "household_by": (report.get("personalization") or {}).get("by"),
        "partners": PARTNERS,
        "prices_seen": P.CHECKED,
        "note": ("Plans appear for the hazards present at this address, worst first. Partners "
                 "and products never change a score or which plans appear."),
    }
