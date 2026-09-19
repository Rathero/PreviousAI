"""What to do about each hazard: measures, products, services, insurance and public help.

The measure catalogue behind the four hazard families (flooding, wildfire, avalanches,
extreme heat), published through /api/protection and carried by every report. Each
measure has slots for the companies that sell or install it.

Rules that keep the report honest:

  * Partners never touch a score, and never decide which measures are "recommended
    here": that comes only from this report's cards and the thresholds written below.
  * Order inside a section is recommended first, then impact, then cost. A paid
    placement does not buy a higher position.
  * Every commercial name carries its status: "example" (listed with no agreement),
    "partner" (a paid placement, labelled as such) or "official" (a public body or a
    free public tool).
  * Costs are indicative ranges, not quotes, and every measure cites where the
    recommendation comes from.
  * The home (house or flat, and which floor) never changes a score: it only says who
    acts on each measure, the household or the building.
"""

from __future__ import annotations

# Which report cards belong to each family. Extreme rain and sea-level rise count as
# flooding.
FAMILIES = {
    "flood": {"label": "Flooding",
              "cards": ["flood_zone", "flood_history", "sea_level", "flood_regional", "rain"]},
    "wildfire": {"label": "Wildfire", "cards": ["wildfire", "fire_history"]},
    "avalanche": {"label": "Avalanches", "cards": ["avalanche"]},
    "heat": {"label": "Extreme heat", "cards": ["heat"]},
}

# Panel sections, in the order they are shown.
SECTIONS = [
    ("act", "Start today · free", "Before and during the trip · free"),
    ("product", "Protect the home", "Gear worth taking"),
    ("service", "Professional help", "Professional help"),
    ("insurance", "Insurance", "Insurance"),
    ("public", "Public help and official tools", "Official tools"),
]
KINDS = [s[0] for s in SECTIONS]
IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2}
COST_BANDS = {0: "free", 1: "€", 2: "€€", 3: "€€€"}

# Geographic scope of a measure or a partner. A place in Catalonia sees CAT, ES
# and ALL items; elsewhere in Spain ES and ALL; the rest of the world only ALL.
SCOPES = {"Catalonia": {"CAT", "ES", "ALL"}, "Spain": {"ES", "ALL"}}

DISCLOSURE = (
    "Scores never depend on partners, and partners never decide which measures are "
    "recommended here: that comes from this report's cards. Names marked \"example\" have "
    "no commercial agreement with Previous AI; \"partner\" marks a paid placement. Costs "
    "are indicative ranges in Spain (2026), not quotes. Previous AI is not an insurance "
    "intermediary: insurance entries are information, not advice."
)
LIMITATION = (
    "These measures reduce damage and danger; none makes a place safe, and none changes "
    "the scores above. The score measures the place, not the building or the people in it."
)

SOURCES = {
    "miteco_ccs": ("MITECO and Consorcio de Compensación de Seguros, guide for reducing the "
                   "vulnerability of buildings to floods (2017)",
                   "https://www.miteco.gob.es/en/agua/temas/gestion-de-los-riesgos-de-inundacion/"
                   "usos-del-suelo-en-zonas-inundables/guias-adaptacion-riesgo-inundacion-criterios-constructivos.html"),
    "rd_590": ("Royal Decree 590/2026 on flood-adaptation grants (BOE-A-2026-15458)",
               "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-15458"),
    "ccs": ("Consorcio de Compensación de Seguros, extraordinary risks cover",
            "https://www.consorseguros.es/"),
    "civil_protection": ("Spain's Civil Protection self-protection advice",
                         "https://www.proteccioncivil.es/"),
    "bs851188": ("BS 851188 flood-resistance products standard and the CIRIA property flood "
                 "resilience code of practice",
                 "https://befloodready.ciwem.org/property-flood-resilience/"),
    "llei_5_2003": ("Catalan Law 5/2003 and Decree 123/2005, wildfire prevention in developments",
                    "https://interior.gencat.cat/ca/arees_dactuacio/bombers/foc-forestal/"
                    "publicacions_tecniques_i_normativa/normativa/"),
    "bombers": ("Barcelona fire service advice on preventing wildfires",
                "https://ajuntament.barcelona.cat/horta-guinardo/es/noticias/"
                "los-consejos-de-los-bomberos-de-barcelona-para-prevenir-incendios-forestales-1643991"),
    "tecnifuego": ("Tecnifuego, self-protection for homes in forest settings",
                   "https://www.tecnifuego.org/comunicacion/autoproteccion-como-proteger-la-vivienda-en-entorno-forestal"),
    "ibhs": ("IBHS Wildfire Prepared Home standard (California)",
             "https://wildfireprepared.org/"),
    "madrid_hedges": ("Community of Madrid, change to the Urban Trees Law to replace cypress "
                      "hedges (June 2026)",
                      "https://www.comunidad.madrid/noticias/2026/06/02/comunidad-madrid-modificara-su-ley-"
                      "arbolado-urbano-facilitar-sustitucion-setos-arizonicas-otras-especies-menos-inflamables"),
    "icgc_bpa": ("ICGC avalanche danger bulletin (BPA)",
                 "https://www.icgc.cat/en/Thematic-areas/Risks-and-emergencies/Avalanches/Avalanche-Danger-Bulletin-BPA"),
    "icgc_zones": ("ICGC map of avalanche zones of Catalonia 1:25,000",
                   "https://www.icgc.cat/en/Geoinformation-and-Maps/Data-and-products/"
                   "Geologic-and-geophysical-geoinformation/Geological-risks-cartography/"
                   "Map-avalanche-zones-Catalonia-125000"),
    "slf": ("Swiss guideline for defence structures in avalanche starting zones (FOEN / SLF)",
            "https://www.geobrugg.com/en/Avalanche-Prevention-77538.html"),
    "acna": ("ACNA, avalanche terrain safety courses (STA)", "https://www.acna.cat/"),
    "rescue_costs": ("Intermundial, what a mountain insurance covers (rescue costs in Spain)",
                     "https://www.intermundial.es/blog/seguro-deportes-riesgo-rescate-montana"),
    "irpf": ("Spanish income-tax deductions for energy-efficiency works (Law 35/2006, additional "
             "provision 50, as worded by Royal Decree-law 7/2026)",
             "https://www.boe.es/buscar/act.php?id=BOE-A-2006-20764"),
    "bcn_shelters": ("Barcelona climate shelters network", "https://www.barcelona.cat/"
                     "barcelona-pel-clima/en/specific-actions/climate-shelters-network"),
    "who_heat": ("WHO Europe, staying safe in the heat: health advice (2022)",
                 "https://www.who.int/europe/news-room/27-07-2022-staying-safe-in-the-heat--health-"
                 "advice-for-times-of-extreme-temperature-and-wildfires"),
    "guidance": ("Previous AI's own guidance, built on the public sources above", None),
}

# status: "official" (public body or free public tool), "example" (commercial,
# no agreement: listed so the panel works today), "partner" (paid placement).
PARTNERS = {
    # Official and free tools -------------------------------------------------
    "snczi": {"name": "SNCZI flood map viewer · MITECO", "kind": "public", "scope": "ES",
              "status": "official", "offer": "Official flood zones and water depths for your plot",
              "url": "https://www.miteco.gob.es/en/agua/temas/gestion-de-los-riesgos-de-inundacion/snczi.html"},
    "ccs": {"name": "Consorcio de Compensación de Seguros", "kind": "public", "scope": "ES",
            "status": "official", "offer": "Pays extraordinary floods to anyone with a home policy in force",
            "url": "https://www.consorseguros.es/"},
    "rd_590": {"name": "MITECO flood-adaptation grants (DANA municipalities)", "kind": "public",
               "scope": "ES", "status": "official",
               "offer": "Paid to the town halls of the 62 DANA municipalities, which can open calls for owners",
               "url": "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-15458"},
    "miteco_guides": {"name": "MITECO flood-adaptation guides", "kind": "public", "scope": "ES",
                      "status": "official", "offer": "Free guides for owners, with measures by building type",
                      "url": SOURCES["miteco_ccs"][1]},
    "civil_protection": {"name": "Civil Protection · ES-Alert", "kind": "public", "scope": "ES",
                         "status": "official", "offer": "Warnings arrive on every phone in the area, no sign-up",
                         "url": "https://www.proteccioncivil.es/"},
    "gencat_fire": {"name": "Generalitat de Catalunya · wildfire rules for developments",
                    "kind": "public", "scope": "CAT", "status": "official",
                    "offer": "Law 5/2003: the 25 m strip, plots and self-protection plans",
                    "url": SOURCES["llei_5_2003"][1]},
    "pla_alfa": {"name": "Pla Alfa · Catalan Rural Agents", "kind": "public", "scope": "CAT",
                 "status": "official", "offer": "Today's fire-danger level (0-4) by municipality, with its restrictions",
                 "url": "https://interior.gencat.cat/ca/arees_dactuacio/agents-rurals/pla-alfa/index.html"},
    "fireprime": {"name": "FIREPRIME app · Pau Costa Foundation", "kind": "ngo", "scope": "ALL",
                  "status": "official", "offer": "Free app that rates a home's wildfire readiness",
                  "url": "https://www.paucostafoundation.org/fireprime-acaba-con-el-lanzamiento-de-una-app-"
                         "para-conocer-el-riesgo-de-las-viviendas-frente-a-los-incendios-forestales/"},
    "icgc_bpa": {"name": "ICGC avalanche bulletin", "kind": "public", "scope": "CAT", "status": "official",
                 "offer": "Danger 1-5 for the 7 zones of the Catalan Pyrenees, by e-mail too",
                 "url": SOURCES["icgc_bpa"][1]},
    "lauegi": {"name": "Centre de Lauegi · Val d'Aran", "kind": "public", "scope": "CAT",
               "status": "official", "offer": "Aran's avalanche bulletin and awareness talks",
               "url": "http://lauegi.conselharan.org/training-and-awareness/?lang=en"},
    "aemet_bpa": {"name": "AEMET avalanche bulletins", "kind": "public", "scope": "ES",
                  "status": "official",
                  "offer": "Pyrenees (Catalan side included) and Picos de Europa; weekly for Guadarrama and "
                           "Cordel-Peña Labra",
                  "url": "https://www.aemet.es/en/eltiempo/prediccion/montana/boletin_peligro_aludes"},
    "eaws": {"name": "European Avalanche Warning Services", "kind": "public", "scope": "ALL",
             "status": "official", "offer": "Links to every European avalanche bulletin",
             "url": "https://www.avalanches.org/"},
    "icgc_zones": {"name": "ICGC avalanche zones map", "kind": "public", "scope": "CAT",
                   "status": "official", "offer": "Mapped avalanche paths and slopes, 1:25,000",
                   "url": SOURCES["icgc_zones"][1]},
    "bcn_shelters": {"name": "Barcelona climate shelters", "kind": "public", "scope": "CAT",
                     "status": "official", "offer": "500 cool places in 2026, most within 10 minutes' walk",
                     "url": SOURCES["bcn_shelters"][1]},
    "gencat_shelters": {"name": "Climate shelters in Catalonia", "kind": "public", "scope": "CAT",
                        "status": "official", "offer": "Map of close to 2,000 shelters across Catalonia",
                        "url": "https://web.gencat.cat/ca/inici/actualitat/estiu/refugis-climatics"},
    "irpf": {"name": "Income-tax deductions for energy-efficiency works", "kind": "public",
             "scope": "ES", "status": "official",
             "offer": "20 % or 40 % of the cost to 31 Dec 2026; 60 % for whole-building works to 31 Dec 2027",
             "url": SOURCES["irpf"][1]},
    # Retail ------------------------------------------------------------------
    "leroy_merlin": {"name": "Leroy Merlin", "kind": "retailer", "scope": "ES", "status": "example",
                     "offer": "Barriers, pumps, extinguishers, mesh, awnings, fans; installation service",
                     "url": "https://www.leroymerlin.es/"},
    "decathlon": {"name": "Decathlon", "kind": "retailer", "scope": "ALL", "status": "example",
                  "offer": "Avalanche kits, hydration and sun protection for the outdoors",
                  "url": "https://www.decathlon.es/"},
    # Flooding ----------------------------------------------------------------
    "aguabloc": {"name": "Aguabloc", "kind": "manufacturer", "scope": "ES", "status": "example",
                 "offer": "Aluminium door and garage barriers fitted on existing frames",
                 "url": "https://aguabloc.com/"},
    "isoflots": {"name": "Isoflots", "kind": "manufacturer", "scope": "ES", "status": "example",
                 "offer": "Made-to-measure barriers for doors, garages and shop fronts",
                 "url": "https://isoflots.es/"},
    "antiinundaciones": {"name": "Antiinundaciones.com", "kind": "installer", "scope": "ES",
                         "status": "example",
                         "offer": "Turnkey barriers, maintenance and help with grant paperwork",
                         "url": "https://www.antiinundaciones.com/"},
    "zubieta": {"name": "Talleres Zubieta", "kind": "manufacturer", "scope": "ES", "status": "example",
                "offer": "Watertight doors and gates for garages, made in Spain",
                "url": "https://www.tallereszubieta.com/sistema-anti-inundaciones/"},
    "verisure": {"name": "Verisure", "kind": "service", "scope": "ES", "status": "example",
                 "offer": "Flood and smoke detectors linked to a 24/7 monitoring centre",
                 "url": "https://www.verisure.es/dispositivos/detectores"},
    "shelly": {"name": "Shelly", "kind": "manufacturer", "scope": "ALL", "status": "example",
               "offer": "Wi-Fi water-leak and smoke sensors that alert your phone",
               "url": "https://www.shelly.com/"},
    "murprotec": {"name": "Murprotec", "kind": "installer", "scope": "ES", "status": "example",
                  "offer": "Damp-proofing and waterproofing of walls and basements",
                  "url": "https://www.murprotec.es/"},
    "rastreator": {"name": "Rastreator", "kind": "insurance", "scope": "ES", "status": "example",
                   "offer": "Compare home insurance, including water-damage limits",
                   "url": "https://www.rastreator.com/"},
    "acierto": {"name": "Acierto.com", "kind": "insurance", "scope": "ES", "status": "example",
                "offer": "Compare home insurance with an adviser on the phone",
                "url": "https://www.acierto.com/"},
    # Wildfire ----------------------------------------------------------------
    "medi_xxi": {"name": "Medi XXI GSA", "kind": "manufacturer", "scope": "ES", "status": "example",
                 "offer": "SIDEINFO domestic wildfire defence: sprinklers fed from the pool",
                 "url": "https://es.linkedin.com/company/medi-xxi-gsa"},
    "cantudo": {"name": "Instalaciones Cantudo", "kind": "installer", "scope": "ES", "status": "example",
                "offer": "Smart sprinkler system triggered by smoke or flame",
                "url": "https://cantudosl.com/areas-de-negocio/sistema-inteligente-contra-incendios/"},
    "hephaestus": {"name": "Hephaestus", "kind": "manufacturer", "scope": "ALL", "status": "example",
                   "offer": "CE-certified perimeter sprinklers and water cannons",
                   "url": "https://hephaestus.solutions/es/categoria-producto/equipos-contra-incendios/aspersores-canones/"},
    "descartes": {"name": "Descartes Underwriting", "kind": "insurance", "scope": "ES", "status": "example",
                  "offer": "Parametric wildfire cover for businesses and owners' associations",
                  "url": "https://descartesunderwriting.com/"},
    # Avalanches --------------------------------------------------------------
    "geobrugg": {"name": "Geobrugg", "kind": "manufacturer", "scope": "ALL", "status": "example",
                 "offer": "Snow nets for avalanche starting zones (Swiss FOEN/SLF guideline)",
                 "url": "https://www.geobrugg.com/en/Avalanche-Prevention-77538.html"},
    "mammut": {"name": "Mammut", "kind": "manufacturer", "scope": "ALL", "status": "example",
               "offer": "Transceivers, probes, shovels and airbag backpacks",
               "url": "https://www.mammut.com/"},
    "ortovox": {"name": "Ortovox", "kind": "manufacturer", "scope": "ALL", "status": "example",
                "offer": "Transceivers, safety kits, airbags and free avalanche training content",
                "url": "https://www.ortovox.com/"},
    "acna": {"name": "ACNA · snow and avalanche association", "kind": "training", "scope": "CAT",
             "status": "example", "offer": "STA 1 and 2 avalanche terrain courses, in the Pyrenees",
             "url": "https://www.acna.cat/"},
    "aegm": {"name": "Spanish Mountain Guides Association (AEGM)", "kind": "training", "scope": "ES",
             "status": "example", "offer": "Find a qualified guide for off-piste and ski touring",
             "url": "https://www.aegm.org/"},
    "intermundial": {"name": "Intermundial · Wintersports", "kind": "insurance", "scope": "ES",
                     "status": "example", "offer": "Ski insurance with rescue and medical costs",
                     "url": "https://www.intermundial.es/seguros-deportivos/seguro-wintersports"},
    "intermundial_travel": {"name": "Intermundial", "kind": "insurance", "scope": "ES",
                            "status": "example",
                            "offer": "Travel insurance with medical cover and cancellation",
                            "url": "https://www.intermundial.es/"},
    "arag": {"name": "ARAG ski insurance", "kind": "insurance", "scope": "ES", "status": "example",
             "offer": "Skiing and snowboarding cover, rescue included",
             "url": "https://www.arag.es/productos/seguro-viaje/esquiadores/"},
    "feec": {"name": "FEEC federation licence", "kind": "insurance", "scope": "CAT", "status": "example",
             "offer": "Yearly mountain licence with accident and rescue cover",
             "url": "https://www.feec.cat/"},
    # Heat --------------------------------------------------------------------
    "bandalux": {"name": "Bandalux", "kind": "manufacturer", "scope": "ES", "status": "example",
                 "offer": "Awnings, exterior blinds and screens, made in Spain since 1986",
                 "url": "https://bandalux.com/"},
    "somfy": {"name": "Somfy", "kind": "manufacturer", "scope": "ALL", "status": "example",
              "offer": "Motors and sun sensors that close awnings and shutters on their own",
              "url": "https://www.somfy.es/"},
    "heymondo": {"name": "Heymondo", "kind": "insurance", "scope": "ES", "status": "example",
                 "offer": "Travel insurance with medical cover and cancellation",
                 "url": "https://heymondo.es/"},
    "booking": {"name": "Booking.com", "kind": "travel", "scope": "ALL", "status": "example",
                "offer": "Filter stays by air conditioning",
                "url": "https://www.booking.com/"},
}


def _m(id, family, kind, title, why, *, modes=("home",), cost="free", band=0, impact="medium",
       triggers=None, scope="ALL", partners=(), slot=None, standard=None, profiles=(),
       source="guidance", unit="home"):
    """One measure. `triggers` maps card keys (or "*" for the whole family) to the minimum
    score at which the measure is recommended for this place; `source` is one key of
    SOURCES or a tuple of them. `unit` is who acts: "home" (the household) or "building"
    (works on the building or the plot: in a flat, the owners' association)."""
    return {"id": id, "family": family, "kind": kind, "title": title, "why": why,
            "modes": list(modes), "cost": cost, "cost_band": band, "impact": impact,
            "triggers": triggers or {"*": 30}, "scope": scope, "partners": list(partners),
            "slot": slot, "standard": standard, "profiles": list(profiles),
            "sources": [source] if isinstance(source, str) else list(source), "unit": unit}


BOTH = ("home", "travel")
TRAVEL = ("travel",)

MEASURES = [
    # ======================================================== FLOODING ======
    _m("flood_map", "flood", "act", "Check your exact plot on the official flood map",
       "The report samples one point; the official viewer shows the zone's edge, the return "
       "period and, in many stretches, the water depth.",
       impact="high", triggers={"*": 30, "flood_zone": 20},
       scope="ES", partners=["snczi"], source="miteco_ccs"),
    _m("flood_plan", "flood", "act", "Plan to go up, not out, and keep a grab bag",
       "Most flood deaths happen in cars, garages and basements. Know the highest floor you "
       "can reach, keep documents in a waterproof bag up there, and never go down to rescue "
       "the car.",
       modes=BOTH, impact="high", triggers={"*": 30},
       profiles=["older_adults", "reduced_mobility", "children"], partners=["civil_protection"],
       source="civil_protection"),
    _m("flood_valuables", "flood", "act", "Move electrics, valuables and stock above the water line",
       "Water at 20 cm already ruins sockets, boilers and whatever sits on the floor. Shelving "
       "and a rule of \"nothing valuable at floor level\" cost almost nothing.",
       cost="free to €100", band=1, impact="medium",
       triggers={"flood_zone": 40, "flood_history": 50, "sea_level": 40, "rain": 60},
       source="miteco_ccs"),
    _m("flood_fords", "flood", "act", "Never drive or walk through flooded roads or fords",
       "Thirty centimetres of moving water can float a car. It is the most common way people "
       "die in floods.",
       modes=TRAVEL, impact="high", triggers={"*": 30}, partners=["civil_protection"],
       source="civil_protection"),
    _m("flood_room", "flood", "act", "Book a room above the ground floor near rivers and the seafront",
       "If heavy rain is announced, the ground floor next to a river or the sea is where water "
       "arrives first.",
       modes=TRAVEL, impact="medium", triggers={"flood_zone": 40, "flood_regional": 50, "rain": 60},
       partners=["booking"]),
    _m("backflow_valve", "flood", "product", "Non-return (backflow) valves on the drains",
       "When the sewer is full, water comes back up through toilets, sinks and floor drains of "
       "basements and ground floors. A valve closes that way in.",
       cost="€150-600 fitted, per drain line", band=2, impact="high",
       triggers={"flood_zone": 40, "sea_level": 40, "rain": 60},
       standard="EN 13564 anti-flooding devices for buildings",
       partners=["leroy_merlin"], slot="Plumber certified for backflow valves", source="miteco_ccs"),
    _m("flood_barriers", "flood", "product", "Demountable flood barriers for doors and the garage",
       "Aluminium boards that slot into fixed side frames and stop water at the openings. They "
       "only work if they are stored close by and someone can fit them in minutes.",
       cost="€400-1,500 per opening", band=2, impact="high",
       triggers={"flood_zone": 40, "sea_level": 40},
       standard="Tested to BS 851188 (Kitemark) or equivalent leakage tests",
       partners=["aguabloc", "isoflots", "antiinundaciones", "leroy_merlin"],
       slot="Certified flood-barrier installer", source="bs851188"),
    _m("watertight_door", "flood", "product", "Watertight garage door or gate",
       "For garages that sit below the street or the river bank, a permanent watertight door "
       "avoids depending on someone fitting a barrier in time.",
       cost="from €2,000", band=3, impact="high", triggers={"flood_zone": 60},
       partners=["zubieta"], slot="Watertight door manufacturer", source="miteco_ccs"),
    _m("sump_pump", "flood", "product", "Sump pump with a float switch",
       "Drains the basement or garage automatically. Choose one that runs off a battery or a "
       "generator too: the power often goes first.",
       cost="€100-400 plus fitting", band=1, impact="medium",
       triggers={"flood_zone": 40, "rain": 60},
       partners=["leroy_merlin"], source="rd_590"),
    _m("water_sensors", "flood", "product", "Water sensors that alert your phone",
       "A sensor on the lowest floor warns you while there is still time to act, even when "
       "you are away. Monitored alarms can call the emergency services.",
       cost="€15-50 per sensor; monitored alarms from a monthly fee", band=1, impact="medium",
       triggers={"*": 40}, partners=["shelly", "verisure"], slot="Smart-home security provider"),
    _m("flood_survey", "flood", "service", "Flood-resilience survey of the building",
       "A building surveyor (arquitecto técnico) finds every way in for water, from air bricks "
       "to cable ducts, and sizes barriers and valves before you buy them.",
       cost="€150-500", band=2, impact="high", triggers={"flood_zone": 60, "sea_level": 60},
       scope="ES", slot="Building surveyor trained in the MITECO guide", source="miteco_ccs"),
    _m("flood_sealing", "flood", "service", "Seal walls, doors, windows and gaps",
       "Waterproofing the façade and sealing ducts and gaps is on MITECO's list of measures "
       "that make a building flood-resilient.",
       cost="quote per building", band=2, impact="medium",
       triggers={"flood_zone": 60, "sea_level": 60},
       partners=["murprotec"], slot="Waterproofing contractor", source="miteco_ccs"),
    _m("flood_policy", "flood", "insurance", "Keep a home policy in force: it is what switches on the Consorcio",
       "In Spain extraordinary floods are paid by the Consorcio de Compensación de Seguros, "
       "but only to people with a property policy in force. Rain that gets in through the roof "
       "or the drains is not an extraordinary flood: check your own policy's water-damage limit.",
       cost="free to check", band=0, impact="high", triggers={"*": 30}, scope="ES",
       partners=["ccs", "rastreator", "acierto"], slot="Home insurer or broker", source="ccs"),
    _m("flood_travel_insurance", "flood", "insurance", "Travel insurance that covers cancellation for bad weather",
       "If a flood warning closes the destination, the right policy refunds what you cannot "
       "use. Read how it defines \"extreme weather\".",
       modes=TRAVEL, cost="from a few euros a day", band=1, impact="medium", triggers={"*": 40},
       scope="ES", partners=["heymondo", "intermundial_travel"], slot="Travel insurer"),
    _m("flood_grants", "flood", "public", "Check for flood-adaptation grants",
       "Spain's flood-adaptation grants (Royal Decree 590/2026) go to the town halls of the 62 "
       "municipalities hit by the 2024 DANA, which can open calls for owners; works since 30 "
       "October 2024 count. Elsewhere, ask the town hall and the regional government, and "
       "remember that renovation works pay 10 % VAT instead of 21 %.",
       cost="grant", band=0, impact="medium", triggers={"flood_zone": 40},
       scope="ES", partners=["rd_590"], source="rd_590"),
    _m("flood_guide", "flood", "public", "Read the official guide for owners",
       "The MITECO and Consorcio guide explains, building type by building type, what reduces "
       "flood damage and in what order to do it.",
       triggers={"flood_zone": 40, "sea_level": 40}, scope="ES",
       partners=["miteco_guides"], source="miteco_ccs"),
    _m("flood_alerts", "flood", "public", "Warnings reach your phone on their own",
       "ES-Alert sends Civil Protection warnings to every phone in the area. Also follow AEMET's "
       "yellow-orange-red rain warnings for your area.",
       modes=BOTH, impact="medium", triggers={"*": 20}, scope="ES", partners=["civil_protection"],
       source="civil_protection"),

    # ======================================================== WILDFIRE ======
    _m("fire_2m", "wildfire", "act", "A clear strip of 2 m around the walls, and clean gutters",
       "Embers, not the fire front, burn most houses: they land on dry leaves in gutters, in "
       "corners and against the walls. Firefighters ask for at least 2 m free of vegetation "
       "and debris.",
       impact="high", triggers={"*": 30}, partners=["fireprime"], source="bombers"),
    _m("fire_fuel", "wildfire", "act", "Move firewood, gas bottles and garden furniture away from the house",
       "Anything that burns next to a wall or under a porch carries the fire inside.",
       impact="high", triggers={"*": 30}, source="ibhs"),
    _m("fire_evacuation", "wildfire", "act", "Two evacuation routes and a bag ready: leave early",
       "One route is not a plan. If someone needs help to move, leave at the first warning, "
       "not the last.",
       modes=BOTH, impact="high", triggers={"*": 30},
       profiles=["older_adults", "reduced_mobility", "children"], source="civil_protection"),
    _m("fire_restrictions", "wildfire", "act", "Check the day's fire danger and forest access rules",
       "On high-danger days many trails close and any use of fire is banned; in Catalonia the "
       "Pla Alfa level sets the restrictions.",
       modes=TRAVEL, impact="medium", triggers={"*": 30}, profiles=["outdoor"],
       partners=["pla_alfa"]),
    _m("fire_strip_25", "wildfire", "act", "Keep your development's 25 m protection strip",
       "In Catalonia, developments next to forest must keep a 25 m perimeter strip free of dry "
       "vegetation with thinned trees, and plots inside it in the same condition. Owners and "
       "the owners' community are responsible.",
       impact="high", triggers={"fire_history": 50, "wildfire": 60}, scope="CAT",
       partners=["gencat_fire"], slot="Forestry contractor for strip clearing", source="llei_5_2003"),
    _m("ember_mesh", "wildfire", "product", "Ember-proof mesh on vents, eaves and gutters",
       "Metal mesh of 3 mm or less on every vent and gutter guards keep embers out of the roof "
       "space, the most common way a house catches fire.",
       cost="€10-40 per vent; €5-15 per metre of gutter", band=1, impact="high",
       triggers={"fire_history": 50, "wildfire": 60}, standard="Non-combustible metal mesh, openings of 3 mm or less",
       partners=["leroy_merlin"], source="ibhs"),
    _m("fire_fence", "wildfire", "product", "Replace flammable fences and hedges",
       "Heather, reed and plastic screens, and cypress hedges, carry the fire to the house. Use "
       "stone, brick or metal, or keep hedges more than 5 m from the building. Madrid is "
       "changing its law to let owners replace cypress hedges.",
       cost="quote per metre", band=2, impact="high", triggers={"fire_history": 50, "wildfire": 60},
       partners=["leroy_merlin"], slot="Fencing and landscaping contractor",
       source=("bombers", "madrid_hedges")),
    _m("fire_water", "wildfire", "product", "Hoses that reach the whole perimeter, and a water reserve",
       "Mains pressure drops when a whole area is fighting a fire. A tank or the pool with a "
       "petrol motor pump keeps water available.",
       cost="€50-150 hoses; €200-600 motor pump", band=2, impact="medium",
       triggers={"fire_history": 50, "wildfire": 60},
       partners=["leroy_merlin"], source="tecnifuego"),
    _m("fire_extinguisher", "wildfire", "product", "Extinguisher, fire blanket and smoke detectors",
       "For the spot fire an ember starts: a 6 kg ABC extinguisher, serviced every year, and a "
       "detector on every floor.",
       cost="€30-70 extinguisher; €15-40 per detector", band=1, impact="medium", triggers={"*": 30},
       standard="EN 3-7 extinguisher; EN 14604 smoke alarm",
       partners=["leroy_merlin", "verisure", "shelly"], source="tecnifuego"),
    _m("fire_sprinklers", "wildfire", "product", "Perimeter sprinklers for isolated houses",
       "Automatic sprinklers or cannons wet the house and the ring around it as the fire "
       "arrives. They need their own water and power, since both often fail during a fire.",
       cost="several thousand euros; quote", band=3, impact="medium",
       triggers={"fire_history": 60, "wildfire": 80},
       partners=["medi_xxi", "cantudo", "hephaestus"], slot="Wildfire sprinkler installer",
       source="tecnifuego"),
    _m("fire_smoke", "wildfire", "product", "FFP2 masks and a HEPA purifier for one room",
       "Wildfire smoke travels hundreds of kilometres. One sealed room with a purifier protects "
       "lungs and hearts on smoky days.",
       modes=BOTH, cost="€100-300 purifier; €10-20 a box of masks", band=1, impact="medium",
       triggers={"*": 40}, standard="EN 149 FFP2; purifier with a stated CADR",
       profiles=["respiratory", "children", "older_adults", "pregnancy"], partners=["leroy_merlin"]),
    _m("fire_clearing", "wildfire", "service", "Brush clearing and tree thinning",
       "A forestry contractor clears undergrowth, prunes low branches and opens space between "
       "tree crowns, especially uphill of the house.",
       cost="quote per plot", band=2, impact="high", triggers={"fire_history": 50, "wildfire": 60},
       slot="Forestry contractor", source="llei_5_2003"),
    _m("fire_retrofit", "wildfire", "service", "Fire-resistant renovation",
       "Tiled or slate roofs, tempered double glazing, non-combustible cladding and "
       "intumescent treatment of exposed wood stop the house burning from the outside.",
       cost="quote", band=3, impact="high", triggers={"fire_history": 55, "wildfire": 80},
       standard="Reaction to fire class A1/A2 (EN 13501-1)", slot="Builder for fire-resistant retrofits",
       source="tecnifuego"),
    _m("fire_policy", "wildfire", "insurance", "Insure for rebuild cost, not market value",
       "Fire is a standard cover in Spanish home policies, but many are under-insured: the sum "
       "should pay for rebuilding the house and replacing its contents.",
       cost="free to check", band=0, impact="high", triggers={"*": 30}, scope="ES",
       partners=["rastreator", "acierto"], slot="Home insurer or broker"),
    _m("fire_parametric", "wildfire", "insurance", "Parametric wildfire cover for communities and businesses",
       "Pays a fixed amount quickly when satellites see fire within an agreed radius, with no "
       "loss adjustment. Suits owners' associations, rural hotels and wineries.",
       cost="quote", band=2, impact="low", triggers={"fire_history": 55, "wildfire": 80},
       scope="ES", partners=["descartes"], slot="Parametric insurer"),
    _m("fire_selfprotection", "wildfire", "public", "Your development's self-protection plan and hydrants",
       "In Catalonia, developments at risk need a self-protection plan and a hydrant network. "
       "Ask the town hall or the owners' community whether yours is up to date.",
       triggers={"fire_history": 50}, scope="CAT", partners=["gencat_fire"],
       source="llei_5_2003"),
    _m("fire_app", "wildfire", "public", "Rate your home with a free app",
       "FIREPRIME, from a European project with the Pau Costa Foundation, scores a home's "
       "readiness for wildfire from a few questions and photos.",
       triggers={"fire_history": 40, "wildfire": 50}, partners=["fireprime"]),

    # ====================================================== AVALANCHES ======
    _m("aval_bulletin", "avalanche", "act", "Read the avalanche bulletin every day in winter",
       "Danger goes from 1 to 5 and changes daily; danger 3 (considerable) is where most fatal "
       "accidents happen. At 3 or more, stay on marked, controlled pistes.",
       modes=BOTH, impact="high", triggers={"*": 0}, profiles=["outdoor"],
       partners=["icgc_bpa", "lauegi", "aemet_bpa", "eaws"], source="icgc_bpa"),
    _m("aval_map", "avalanche", "act", "Check whether the plot is in a mapped avalanche zone",
       "Before buying or renovating, look at the official avalanche map and the municipal plan: "
       "they decide what can be built and where.",
       impact="high", triggers={"*": 0}, scope="CAT", partners=["icgc_zones"], source="icgc_zones"),
    _m("aval_winter", "avalanche", "act", "A winter plan for when the road closes",
       "Avalanche-prone access roads close for days. Keep food, medicines and a backup for "
       "heating, and know who checks on vulnerable neighbours.",
       impact="medium", triggers={"*": 40}, profiles=["older_adults", "reduced_mobility"]),
    _m("aval_kit", "avalanche", "product", "Transceiver, shovel and probe, and practice with them",
       "Off-piste or on a snowshoe route, every member of the group carries all three. After 15 "
       "minutes the chances of a buried person drop fast: companions, not rescuers, dig them out.",
       modes=TRAVEL, cost="€300-600 the set; €10-25 a day to rent", band=2, impact="high",
       triggers={"*": 0}, standard="Transceiver to EN 300 718 (457 kHz)", profiles=["outdoor"],
       partners=["mammut", "ortovox", "decathlon"], slot="Ski shop that rents safety kits",
       source="acna"),
    _m("aval_airbag", "avalanche", "product", "Avalanche airbag backpack",
       "Helps keep a person on the surface of a moving avalanche. It is an extra, never a "
       "substitute for the transceiver, shovel and probe.",
       modes=TRAVEL, cost="€500-1,200", band=3, impact="medium", triggers={"*": 40},
       profiles=["outdoor"], partners=["mammut", "ortovox"]),
    _m("aval_structures", "avalanche", "service", "Protection works on the slope",
       "Snow nets and fences in the starting zone, deflecting dams and reinforced walls on the "
       "uphill façade. They are designed for the slope, usually with the community or the "
       "town hall, by avalanche engineers.",
       cost="quote; usually a community project", band=3, impact="high", triggers={"avalanche": 55},
       standard="Swiss guideline for defence structures in starting zones (FOEN / SLF)",
       partners=["geobrugg"], slot="Avalanche protection engineer", source="slf"),
    _m("aval_facade", "avalanche", "service", "Check the uphill façade and openings",
       "A structural engineer can say whether the walls, windows and shutters facing the slope "
       "would take the pressure of an avalanche's powder cloud.",
       cost="€300-800 survey", band=2, impact="medium", triggers={"avalanche": 40},
       slot="Structural engineer"),
    _m("aval_course", "avalanche", "service", "Avalanche terrain safety course (STA 1)",
       "Two or three days to learn to read the bulletin and the terrain, and to practise a "
       "companion rescue.",
       modes=TRAVEL, cost="course fee", band=2, impact="high", triggers={"*": 0}, profiles=["outdoor"],
       partners=["acna", "lauegi"], slot="Avalanche course provider", source="acna"),
    _m("aval_guide", "avalanche", "service", "Go off-piste with a qualified mountain guide",
       "A guide chooses the route for the day's danger, and many insurers only cover off-piste "
       "skiing when you go with one.",
       modes=TRAVEL, cost="day rate", band=2, impact="high", triggers={"*": 40}, scope="ES",
       profiles=["outdoor"], partners=["aegm"], slot="Mountain guide"),
    _m("aval_rescue_insurance", "avalanche", "insurance", "Insurance that pays rescue off-piste",
       "A mountain rescue in Spain costs €3,500-5,000 on average and up to €8,000 by helicopter. "
       "Insurance bought with the lift pass usually covers the pistes only.",
       modes=TRAVEL, cost="from a few euros a day; licences yearly", band=1, impact="high",
       triggers={"*": 0}, scope="ES", profiles=["outdoor"],
       partners=["intermundial", "arag", "feec"], slot="Mountain and ski insurer",
       source="rescue_costs"),
    _m("aval_home_policy", "avalanche", "insurance", "Check that your home policy covers snow and avalanches",
       "Avalanches are not among the natural events the Consorcio lists as extraordinary risks, "
       "so damage depends on your own policy: look for snow load and avalanche.",
       cost="free to check", band=0, impact="high", triggers={"*": 40}, scope="ES",
       partners=["rastreator", "acierto"], slot="Home insurer or broker", source="ccs"),

    # ==================================================== EXTREME HEAT ======
    _m("heat_shutters", "heat", "act", "Shut the sunny side by day, open it all at night",
       "Closing outside shutters on south and west windows before the sun hits them, and cross-"
       "ventilating at night, is the cheapest cooling there is.",
       impact="high", triggers={"*": 30}, source="who_heat"),
    _m("heat_cool_room", "heat", "act", "Find the cool room and the nearest climate shelter",
       "Before the first heatwave: which room stays coolest at night, and where the nearest "
       "air-conditioned public space is.",
       modes=BOTH, impact="medium", triggers={"*": 30},
       partners=["bcn_shelters", "gencat_shelters"], source="bcn_shelters"),
    _m("heat_checkins", "heat", "act", "Check on older people twice a day during heatwaves",
       "Over-65s often do not feel thirst, and many heat deaths happen alone at home. A call in "
       "the morning and one in the afternoon.",
       modes=BOTH, impact="high", triggers={"*": 40}, profiles=["older_adults"], source="who_heat"),
    _m("heat_timing", "heat", "act", "Outdoors before 11:00 and after 18:00",
       "Plan the day around the heat, carry water, and keep a cool indoor stop for the middle "
       "of the day.",
       modes=TRAVEL, impact="high", triggers={"*": 30}, profiles=["children", "outdoor", "pregnancy"],
       source="who_heat"),
    _m("heat_shading", "heat", "product", "Outdoor shading: awnings, exterior blinds, shutters",
       "Shade outside the glass stops the heat before it gets in; blinds inside only stop it "
       "once it is already in the room. Motors with a sun sensor close them on their own.",
       cost="€300-1,500 per window or terrace", band=2, impact="high", triggers={"*": 40},
       partners=["bandalux", "somfy", "leroy_merlin"], slot="Awning and shutter installer",
       source="who_heat"),
    _m("heat_film", "heat", "product", "Solar-control window film",
       "For windows that cannot take outdoor shading: it reflects part of the sun's heat and "
       "costs a fraction of new glazing.",
       cost="€30-80 per m² fitted", band=1, impact="medium", triggers={"*": 50},
       partners=["leroy_merlin"], slot="Window film installer"),
    _m("heat_fans", "heat", "product", "Ceiling fans and a thermometer in the bedroom",
       "A fan makes the same room feel several degrees cooler for a few watts, and a cheap "
       "thermometer tells you when the bedroom is not cooling down at night.",
       cost="€60-250 per fan; €10-25 thermometer", band=1, impact="medium", triggers={"*": 30},
       partners=["leroy_merlin"]),
    _m("heat_ac", "heat", "product", "Efficient air conditioning in the bedroom",
       "Tropical nights are the dangerous ones: WHO Europe advises keeping the bedroom below "
       "24 °C at night, above all for babies, over-60s and the chronically ill. A heat-pump "
       "split in one room is enough.",
       cost="€800-2,500 installed per split", band=3, impact="high", triggers={"heat": 60},
       profiles=["older_adults", "children", "respiratory", "pregnancy"],
       partners=["leroy_merlin"], slot="Air-conditioning installer", source="who_heat"),
    _m("heat_accommodation", "heat", "product", "Accommodation with real cooling",
       "Check that the room, not only the lobby, has air conditioning, and that it faces away "
       "from the afternoon sun.",
       modes=TRAVEL, cost="free to check", impact="high", triggers={"*": 40},
       profiles=["older_adults", "children", "pregnancy"], partners=["booking"]),
    _m("heat_insulation", "heat", "service", "Insulate the roof and walls, or paint a cool roof",
       "Most of the heat in a top-floor flat comes through the roof. Insulation or a reflective "
       "coating lowers indoor temperature all summer and can count towards tax deductions.",
       cost="quote; 20-60 % deductible with energy certificates", band=3, impact="high",
       triggers={"heat": 50}, slot="Energy-efficiency contractor", source="irpf"),
    _m("heat_telecare", "heat", "service", "Telecare for older people living alone",
       "A pendant button and a call from the service on heatwave days. Many town halls provide "
       "it free or at a low cost.",
       cost="often free through the town hall", band=0, impact="medium", triggers={"*": 50},
       profiles=["older_adults", "reduced_mobility"], slot="Telecare provider"),
    _m("heat_travel_insurance", "heat", "insurance", "Travel insurance with medical cover",
       "Heat illness abroad can mean an emergency room and a changed flight. Check medical "
       "costs, repatriation and cancellation.",
       modes=TRAVEL, cost="from a few euros a day", band=1, impact="medium", triggers={"*": 50},
       scope="ES", profiles=["older_adults", "pregnancy"], partners=["heymondo", "intermundial_travel"],
       slot="Travel insurer"),
    _m("heat_tax", "heat", "public", "Tax deductions for energy-efficiency works",
       "Works that cut heating and cooling demand can deduct 20 % or 40 % of the cost from "
       "income tax until 31 December 2026, and works on the whole building 60 % until 31 "
       "December 2027, with energy certificates before and after.",
       cost="deduction", band=0, impact="medium", triggers={"heat": 50}, scope="ES",
       partners=["irpf"], source="irpf"),
]


# Works on the building or the plot. In a flat above the ground floor they are for the
# owners' association; in a house, or for flooding on a ground floor, they are the
# household's own.
BUILDING_MEASURES = {
    "flood_valuables", "backflow_valve", "flood_barriers", "watertight_door", "sump_pump",
    "flood_survey", "flood_sealing", "flood_grants",
    "fire_2m", "fire_fuel", "fire_strip_25", "ember_mesh", "fire_fence", "fire_water",
    "fire_sprinklers", "fire_clearing", "fire_retrofit", "fire_selfprotection", "fire_app",
    "heat_insulation",
    "aval_structures", "aval_facade",
}
for _measure in MEASURES:
    if _measure["id"] in BUILDING_MEASURES:
        _measure["unit"] = "building"


def catalogue() -> dict:
    """The whole catalogue, for /api/protection and for whoever manages partners."""
    return {"families": FAMILIES, "sections": [{"kind": k, "home": h, "travel": t}
                                               for k, h, t in SECTIONS],
            "measures": MEASURES, "partners": PARTNERS,
            "sources": {k: {"name": n, "url": u} for k, (n, u) in SOURCES.items()},
            "disclosure": DISCLOSURE}


def _region(report: dict) -> str:
    return (report.get("coverage") or {}).get("region") or "global"


def _profile_keys(report: dict) -> list[str]:
    pers = report.get("personalization") or {}
    if pers.get("profile_keys"):
        return list(pers["profile_keys"])
    return [p["key"] for p in (report.get("interpretation") or {}).get("profile", []) if "key" in p]


def _trigger(measure: dict, cards: list[dict]) -> dict | None:
    """The card that makes this measure recommended here, the worst one if several do."""
    best = None
    for card in cards:
        score = card.get("score")
        if score is None:
            continue
        for key, minimum in measure["triggers"].items():
            if (key == "*" or key == card["key"]) and score >= minimum:
                if best is None or score > best["score"]:
                    best = card
    return best


def _partner(pid: str) -> dict:
    p = PARTNERS[pid]
    return {"id": pid, "name": p["name"], "url": p["url"], "kind": p["kind"],
            "status": p["status"], "offer": p["offer"]}


def _for_building(measure: dict, dwelling: dict | None) -> bool:
    """Whether, for this home, the measure is the building's rather than the household's."""
    if measure.get("unit") != "building" or not dwelling or dwelling.get("kind") != "apartment":
        return False
    floor = dwelling.get("floor")
    # On the ground floor the flood works protect the flat itself.
    return not (measure["family"] == "flood" and floor is not None and floor <= 0)


def _measure(measure: dict, cards: list[dict], scopes: set[str], profile: list[str],
             dwelling: dict | None) -> dict:
    card = _trigger(measure, cards)
    partners = [_partner(pid) for pid in measure["partners"] if PARTNERS[pid]["scope"] in scopes]
    building = _for_building(measure, dwelling)
    return {
        "id": measure["id"], "kind": measure["kind"], "title": measure["title"],
        "why": measure["why"], "cost": measure["cost"], "cost_band": measure["cost_band"],
        "cost_label": COST_BANDS[measure["cost_band"]], "impact": measure["impact"],
        "recommended": card is not None,
        "reason": (f"{card['label']}: {round(card['score'])}/100, {card['level']}" if card else None),
        "for": [p for p in measure["profiles"] if p in profile],
        "who": "building" if building else "household",
        "who_note": ("For the building: raise it with the owners' association." if building else None),
        "standard": measure["standard"],
        "sources": [{"name": SOURCES[s][0], "url": SOURCES[s][1]} for s in measure["sources"]],
        "partners": partners,
        # An open, sellable slot is shown only where nobody is listed yet.
        "slot": measure["slot"] if not any(p["status"] != "official" for p in partners) else None,
    }


def _context(family: str, scores: dict[str, float]) -> str | None:
    """What the family's score can and cannot see, when that changes what to do.

    Building measures only fire on point-scale evidence (the official flood zone, sea
    level) or on mapped fires nearby. When the score comes from coarser data, the
    measures are listed but not flagged, and the note says why.
    """
    if family == "flood":
        point = [scores[k] for k in ("flood_zone", "sea_level") if k in scores]
        if point and max(point) < 40:
            return ("This point is outside the mapped flood zones, so measures for the building "
                    "are listed but not flagged. The score comes from recorded floods in the "
                    "municipality or from extreme rain over a ~9 km cell.")
        if not point:
            return ("No official flood map covers this exact point, so measures for the building "
                    "are listed but not flagged: find the country's or the town's flood map first.")
    if family == "wildfire" and "fire_history" not in scores:
        return ("Here the wildfire score is fire weather over a ~9 km cell: it cannot see whether "
                "forest or scrub reaches your home. Measures for the house matter most next to "
                "vegetation.")
    return None


def _sort_key(item: dict) -> tuple:
    return (not item["recommended"], item["who"] == "building", not item["for"],
            IMPACT_ORDER[item["impact"]], item["cost_band"])


def build(report: dict, profile: list[str] | None = None, dwelling: dict | None = None) -> dict:
    """The four families for this report: score, the cards behind it, and the measures.

    Deterministic, and it only reads the report: nothing here changes a score. `profile`
    (who lives there) only tags measures; `dwelling` only says who acts on them.
    """
    mode = report.get("mode", "home")
    region = _region(report)
    scopes = SCOPES.get(region, {"ALL"})
    profile = list(profile) if profile is not None else _profile_keys(report)
    hazards = report.get("hazards", [])
    coverage = report.get("coverage") or {}
    notes = coverage.get("notes", [])
    ruled_out = coverage.get("ruled_out") or {}
    col = 1 if mode == "home" else 2
    families = []
    for key, fam in FAMILIES.items():
        cards = [h for h in hazards if h["key"] in fam["cards"]]
        scored = [c for c in cards if c.get("score") is not None]
        top = max(scored, key=lambda c: c["score"]) if scored else None
        measures = [_measure(m, scored, scopes, profile, dwelling) for m in MEASURES
                    if m["family"] == key and mode in m["modes"] and m["scope"] in scopes]
        measures.sort(key=_sort_key)
        entry = {
            "key": key, "label": fam["label"], "applies": bool(scored),
            "ruled_out": key in ruled_out,
            "score": round(top["score"]) if top else None,
            "level": top["level"] if top else None,
            "cards": [{"key": c["key"], "label": c["label"], "score": round(c["score"]),
                       "level": c["level"]} for c in sorted(scored, key=lambda c: -c["score"])],
            "measures": measures if scored else [],
            "recommended": sum(1 for m in measures if m["recommended"]) if scored else 0,
        }
        if not scored:
            # Why the family is not assessed: the report's own note when it has one.
            word = fam["label"].split()[0].lower().rstrip("s")
            entry["note"] = ruled_out.get(key) or next(
                (n for n in notes if n.lower().startswith(word)),
                f"{fam['label']} is not assessed at this point.")
        elif top["score"] < 30:
            entry["note"] = "The hazard is low here: the free steps are usually enough."
        else:
            entry["note"] = _context(key, {c["key"]: c["score"] for c in scored})
        families.append(entry)
    return {
        "mode": mode,
        "region": region,
        "families": families,
        "sections": [{"kind": s[0], "label": s[col]} for s in SECTIONS],
        "disclosure": DISCLOSURE,
        "limitation": LIMITATION,
        "partners_note": (None if region in SCOPES else
                          "Providers and public programmes are listed for Spain so far; "
                          "outside it only international ones appear."),
    }
