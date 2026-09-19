"""Public money for protecting the home: grants, tax deductions and public cover.

A hand-checked catalogue: every programme carries its official page, its legal reference,
the date it was checked and its deadline. It is matched to the report by three things:

  - where the home is: Spain, Catalonia or the municipality;
  - which risks matter here: those worth preparing for today and those the 2050 view
    projects to grow (warm nights by the sea make heat-protection works relevant even
    when today's heat score is low);
  - who can apply: the household, the owners' association (works on a block of flats),
    the town hall, or anyone after damage.

What does not exist is said too: a household asking for flood or avalanche money should
hear that there is none here, not find an empty list. Nothing here scores, and a programme
never changes which risks or measures are shown. Amounts and deadlines change: the
official page decides, and the view says so.

Checked on 19 September 2026 against the official sources linked in each entry (BOE,
DOGC, Agencia Tributaria, MITECO, the Consorcio, the Generalitat and the town halls).
Covered so far: Spain-wide programmes, Catalonia, and the demo towns El Masnou and
Vielha e Mijaran.
"""

from __future__ import annotations

import datetime as dt

CHECKED = "2026-09-19"

# INE codes of the municipalities with their own entries.
EL_MASNOU = "081189"
VIELHA = "252430"

# Who applies, in the order the panel shows them.
GROUPS = [
    ("household", "You can apply",
     "Programmes a household applies for itself, for works in its own home."),
    ("owners", "Your owners' association can apply",
     "Works on the building or the plot are decided and applied for by the owners together."),
    ("municipality", "Your town hall applies",
     "Only public bodies apply for these; ask the town hall whether it will do so for your street."),
    ("after", "If damage happens",
     "Money that pays out after a flood, a storm or a fire, not before."),
]

STATUS_LABELS = {"open": "Open", "permanent": "Permanent", "upcoming": "Coming soon",
                 "closed": "Closed"}

# Families of the app's four risks.
FAMILIES = ("wildfire", "flood", "heat", "avalanche")

# The catalogue. `where` is {"country": "ES"}, {"region": "Catalonia"} or
# {"municipalities": [INE codes]}; `families` are the risks it helps protect against;
# `who` is one of GROUPS; `communities_only` keeps it off single houses; `notes_by_place`
# adds a line for a municipality (INE code) or a region; `deadline` is an ISO date.
PROGRAMMES: list[dict] = [
    # ================================================================ Spain
    {
        "id": "irpf_energy_home",
        "name": "Income-tax deduction for energy works in your home",
        "official_name": "Deducción por obras de mejora de la eficiencia energética de viviendas",
        "body": "Agencia Tributaria",
        "where": {"country": "ES"}, "who": "household", "families": ["heat"],
        "funds": "Insulation, windows, shading and heat pumps that cut the heating and cooling "
                 "demand of your main home (or one you rent out), with an energy certificate "
                 "before and after.",
        "amount": "20 % of up to €5,000 a year if the demand drops 7 %; 40 % of up to €7,500 if "
                  "energy use drops 30 % or the home reaches class A or B.",
        "note": "Payments until 31 Dec 2026, with the final certificate issued before 1 Jan 2027. "
                "Pay by card or transfer; boilers and other fossil-fuel equipment do not count.",
        "status": "open", "deadline": "2026-12-31",
        "ref": "Law 35/2006, add. provision 50 (Royal Decree-law 7/2026)",
        "url": "https://www.boe.es/buscar/act.php?id=BOE-A-2006-20764",
    },
    {
        "id": "irpf_energy_building",
        "name": "Income-tax deduction for energy works on the whole building",
        "official_name": "Deducción por obras de mejora de la eficiencia energética de viviendas",
        "body": "Agencia Tributaria",
        "where": {"country": "ES"}, "who": "owners", "families": ["heat"],
        "funds": "Works on the whole residential building (in a block of flats, agreed by the "
                 "owners) that cut its non-renewable energy use by 30 % or reach class A or B.",
        "amount": "60 % of up to €5,000 a year per owner, €15,000 in total.",
        "note": "Payments until 31 Dec 2027.",
        "status": "open", "deadline": "2027-12-31",
        "ref": "Law 35/2006, add. provision 50 (Royal Decree-law 7/2026)",
        "url": "https://www.boe.es/buscar/act.php?id=BOE-A-2006-20764",
    },
    {
        "id": "cae",
        "name": "Energy-savings certificates",
        "official_name": "Sistema de Certificados de Ahorro Energético (CAE)",
        "body": "MITECO",
        "where": {"country": "ES"}, "who": "household", "families": ["heat"],
        "funds": "Insulating walls and roofs, new windows, or a heat pump instead of a boiler: an "
                 "energy company or an intermediary pays for the verified savings.",
        "amount": "A price agreed with the buyer for each standard measure; there is no public call.",
        "note": "Owners' associations can use it too. No standard measure covers shading or new "
                "air conditioning.",
        "status": "permanent", "deadline": None,
        "ref": "Royal Decree 36/2023",
        "url": "https://www.miteco.gob.es/en/energia/eficiencia/cae/catalogo-de-fichas/"
               "catalogo-vigente-de-fichas/residencial.html",
    },
    {
        "id": "vat_10",
        "name": "10 % VAT on renovation and repair works",
        "official_name": "Tipo reducido del IVA en obras de renovación y reparación de viviendas",
        "body": "Agencia Tributaria",
        "where": {"country": "ES"}, "who": "household", "families": ["flood", "wildfire", "heat"],
        "funds": "Fitted flood barriers, waterproofing, new windows or insulation: the contractor "
                 "charges 10 % VAT instead of 21 %.",
        "amount": "11 points less VAT on the bill.",
        "note": "The home must be at least two years old and used privately, and the materials the "
                "contractor supplies must be at most 40 % of the price.",
        "status": "permanent", "deadline": None,
        "ref": "Law 37/1992, art. 91.Uno.2.10º",
        "url": "https://www.boe.es/buscar/act.php?id=BOE-A-1992-28740",
    },
    {
        "id": "state_housing_plan",
        "name": "State Housing Plan renovation grants",
        "official_name": "Plan Estatal de Vivienda 2026-2030 · programas de rehabilitación",
        "body": "Ministry of Housing, with calls run by each region",
        "where": {"country": "ES"}, "who": "household", "families": ["heat", "wildfire"],
        "funds": "Insulation and heat pumps that cut heating and cooling demand, structural safety "
                 "works and fire protection of the building envelope, in buildings finished "
                 "before 2006.",
        "amount": "40 % up to €7,500 for part of the envelope; 65–80 % up to €13,000–20,500 per home "
                  "for a whole building; up to 100 % for vulnerable households.",
        "note": "Owners, owners' associations and tenants with the owner's consent can apply. "
                "In force since 24 Apr 2026.",
        "notes_by_place": {"Catalonia": "The Catalan call has not opened yet; it is expected in "
                                        "the second half of 2026."},
        "status": "upcoming", "deadline": None,
        "ref": "Royal Decree 326/2026",
        "url": "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-8872",
    },
    {
        "id": "consorcio",
        "name": "Consorcio cover for extraordinary floods",
        "official_name": "Seguro de riesgos extraordinarios",
        "body": "Consorcio de Compensación de Seguros (public)",
        "where": {"country": "ES"}, "who": "after", "families": ["flood"],
        "funds": "Floods from rain, rivers, snowmelt and sea surges, storms with gusts over "
                 "120 km/h and earthquakes, for anyone with a home or contents policy in force.",
        "amount": "The damage your policy covers, with no excess for homes.",
        "note": "Not covered: water that gets in through the roof or drains, landslides, "
                "avalanches, and wildfire (your policy's own fire cover pays for that). New "
                "policies wait 7 days; report the damage within 7 days.",
        "status": "permanent", "deadline": None,
        "ref": "Royal Decree 300/2004",
        "url": "https://www.consorseguros.es/en/preguntas-frecuentes/seguros-de-riesgos-extraodinarios",
    },
    {
        "id": "interior_aid",
        "name": "Government aid after a disaster",
        "official_name": "Subvenciones en atención a necesidades derivadas de situaciones de "
                         "emergencia o de naturaleza catastrófica",
        "body": "Ministry of the Interior, through the Government Subdelegation",
        "where": {"country": "ES"}, "who": "after", "families": ["flood", "wildfire", "avalanche"],
        "funds": "Damage to your main home and essential belongings that insurance and the "
                 "Consorcio do not pay, for households under an income limit; owners' "
                 "associations for common parts.",
        "amount": "Up to €15,120 if the home is destroyed; 50 % of structural damage up to "
                  "€10,320; essential belongings up to €2,580.",
        "note": "Apply within one month of the event. It is the only public route for avalanche "
                "and landslide damage.",
        "notes_by_place": {
            EL_MASNOU: "In 2026 the Government declared several Catalan rain and flood episodes and "
                       "the Tiana wildfire serious emergencies: if your home was damaged, ask the "
                       "Subdelegation in Barcelona now, as the one-month windows are closing.",
            VIELHA: "The wildfire of 2 Aug 2026 in Vielha e Mijaran was declared a serious "
                    "emergency on 15 Sep 2026: if your home was damaged, ask the Subdelegation in "
                    "Lleida.",
        },
        "status": "permanent", "deadline": None,
        "ref": "Royal Decree 307/2005",
        "url": "https://www.proteccioncivil.es/ayudas/lineas-de-ayuda",
    },
    # ================================================================ Catalonia
    {
        "id": "cat_rehab_loans",
        "name": "Generalitat loans for renovating the building",
        "official_name": "Ajuts en forma de préstecs a comunitats de propietaris per a la rehabilitació",
        "body": "Agència de l'Habitatge de Catalunya, with the Institut Català de Finances",
        "where": {"region": "Catalonia"}, "who": "owners", "communities_only": True,
        "families": ["heat"],
        "funds": "Renovating the façades, roofs and energy systems of a block of flats.",
        "amount": "Fixed-rate loans from €30,000 per building, up to €20,000 per home.",
        "note": "Check the loan terms on the official page.",
        "status": "open", "deadline": "2026-12-30",
        "ref": "DOGC 9567 (extension of the call)",
        "url": "https://tramits.gencat.cat/ca/tramits/tramits-temes/21909-Ajuts-prestecs-per-a-la-rehabilitacio",
    },
    {
        "id": "cat_fire_strips",
        "name": "Grants for wildfire protection strips around developments",
        "official_name": "Ajuts per al tractament de la vegetació en urbanitzacions (Llei 5/2003)",
        "body": "Departament d'Agricultura, Generalitat de Catalunya",
        "where": {"region": "Catalonia"}, "who": "municipality", "families": ["wildfire"],
        "funds": "Clearing the 25 m protection strip around developments next to woodland, "
                 "municipal plots and access strips, which owners otherwise pay for.",
        "amount": "80 % of the cost (95 % in rural municipalities), up to €250,000 per municipality.",
        "note": "Only town halls and local bodies apply. If your home is in a development next to "
                "woodland, ask the town hall whether it will apply before the call closes.",
        "notes_by_place": {VIELHA: "In Aran the Conselh Generau d'Aran can apply too."},
        "status": "open", "deadline": "2026-10-06",
        "ref": "Resolució ARP/2825/2026",
        "url": "https://web.gencat.cat/ca/inici/actualitat/noticies/2026/08/"
               "ajuts-per-crear-franges-de-proteccio-contra-incendis",
    },
    # ================================================================ El Masnou
    {
        "id": "masnou_icio",
        "name": "El Masnou building-works tax bonus",
        "official_name": "Bonificacions de l'impost sobre construccions, instal·lacions i obres (ICIO)",
        "body": "Ajuntament del Masnou",
        "where": {"municipalities": [EL_MASNOU]}, "who": "household", "families": ["heat"],
        "funds": "Solar and other alternative-energy systems, water-saving works, and full façade "
                 "or roof restorations the council declares of special interest.",
        "amount": "Up to 95 % off the municipal building-works tax (ICIO).",
        "note": "Ask the town hall how to claim it, and whether a heat pump counts as alternative "
                "energy.",
        "status": "permanent", "deadline": None,
        "ref": "Fiscal ordinance 8 (September 2025)",
        "url": "https://elmasnou.cat/media/repository/documents_oficials/normativa_fiscal/"
               "ordenances_fiscals_2025/08_Impost_sobre_construccions_installacions_i_obres_"
               "setembre_2025.pdf",
    },
]

# What is missing, said once per risk: {family: [(where, text)]}, where "ES" or a region.
GAPS = {
    "flood": [
        ("ES", "Spain's flood-adaptation grants (Royal Decree 590/2026) only reach the town halls "
               "of the 62 municipalities hit by the 2024 DANA."),
        ("Catalonia", "No Catalan programme pays households for flood barriers or valves yet."),
    ],
    "wildfire": [
        ("Catalonia", "Wildfire-prevention money in Catalonia goes to town halls and forest "
                      "owners; none pays a household to clear its own plot."),
    ],
    "avalanche": [
        ("ES", "No public programme pays for protecting a private home against avalanches, and "
               "the Consorcio does not cover them: check that your own policy does."),
    ],
}


def _municipality(report: dict) -> dict:
    return (report.get("coverage") or {}).get("municipality") or {}


def _region(report: dict) -> str | None:
    return (report.get("coverage") or {}).get("region")


def _applies_here(programme: dict, report: dict) -> bool:
    where = programme["where"]
    region = _region(report)
    if "municipalities" in where:
        return str(_municipality(report).get("code") or "") in where["municipalities"]
    if "region" in where:
        return region == where["region"]
    if where.get("country") == "ES":
        return region in ("Spain", "Catalonia")
    return False


def _in_scope(scope: str, report: dict) -> bool:
    region = _region(report)
    return region in ("Spain", "Catalonia") if scope == "ES" else region == scope


def _relevant_families(tiles: list[dict], ahead: dict | None) -> set[str]:
    """The risks worth preparing for today, plus those the 2050 view sees growing."""
    worth = {t["key"] for t in tiles if t.get("worth")}
    growing = {k for k, r in ((ahead or {}).get("risks") or {}).items() if r.get("direction") == "up"}
    return worth | growing


def _status(programme: dict, today: dt.date) -> str:
    status = programme["status"]
    deadline = programme.get("deadline")
    if deadline and dt.date.fromisoformat(deadline) < today:
        return "closed"
    return status


def _date(iso: str) -> str:
    day = dt.date.fromisoformat(iso)
    return f"{day.day} {day.strftime('%b')} {day.year}"


def _status_label(status: str, deadline: str | None) -> str:
    if status == "open" and deadline:
        return f"Open until {_date(deadline)}"
    return STATUS_LABELS.get(status, status)


def _item(programme: dict, status: str, report: dict) -> dict:
    group = programme["who"]
    # In a house the household owns the whole building: nobody else decides.
    if group == "owners" and ((report.get("dwelling") or {}).get("kind") == "house"):
        group = "household"
    places = programme.get("notes_by_place") or {}
    local = places.get(str(_municipality(report).get("code") or "")) or places.get(_region(report) or "")
    note = " ".join(n for n in (programme.get("note"), local) if n) or None
    return {
        "id": programme["id"], "name": programme["name"],
        "official_name": programme.get("official_name"), "body": programme["body"],
        "families": [f for f in programme["families"] if f in FAMILIES],
        "funds": programme["funds"], "amount": programme["amount"], "note": note,
        "group": group, "status": status,
        "status_label": _status_label(status, programme.get("deadline")),
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
    house = (report.get("dwelling") or {}).get("kind") == "house"
    items = []
    for p in PROGRAMMES:
        if not _applies_here(p, report) or (house and p.get("communities_only")):
            continue
        status = _status(p, today)
        if status == "closed" or not (set(p["families"]) & families):
            continue
        items.append(_item(p, status, report))
    order = {g[0]: i for i, g in enumerate(GROUPS)}
    items.sort(key=lambda i: (order[i["group"]], i["status"] != "open", i["deadline"] or "9999"))

    def paying(group: list[dict]) -> list[dict]:
        return [i for i in group if i["group"] in ("household", "owners")]

    by_family = {}
    for key in FAMILIES:
        if key not in families:
            continue
        mine = [i for i in items if key in i["families"]]
        gaps = [text for scope, text in GAPS.get(key, []) if _in_scope(scope, report)]
        if not mine and not gaps:
            continue
        pay = paying(mine)
        by_family[key] = {
            "count": len(mine),
            "text": (f"{_count(len(pay))} can help pay for {FAMILY_WORDS[key]}" if pay else
                     f"{_count(len(mine))} can help after damage" if mine else None),
            "gaps": gaps,
        }
    muni = _municipality(report).get("name")
    pay = paying(items)
    checked = dt.date.fromisoformat(CHECKED)
    return {
        "items": items,
        "groups": [{"key": k, "label": label, "note": note} for k, label, note in GROUPS
                   if any(i["group"] == k for i in items)],
        "families": by_family,
        "summary": (f"{_count(len(pay))} can help pay for your plan here" if pay else
                    f"{_count(len(items))} can help after damage" if items else None),
        "intro": (f"Grants, tax deductions and public cover for a home in {muni or 'this place'}, "
                  f"for the risks that matter here, today or by 2050."),
        "note": (f"Checked on {checked.day} {checked.strftime('%B %Y')} against the official "
                 f"pages. Amounts, conditions and deadlines change and the official page decides; "
                 f"Previous AI does not process applications."),
        "checked": CHECKED,
    }
