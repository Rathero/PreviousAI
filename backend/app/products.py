"""The real products the Action plan proposes: one or two for each thing it says to buy.

Each product is a page someone can buy from today: the store, the direct link, the photo
the store publishes and the price the page showed on CHECKED. Prices and stock change,
so the plan says when they were seen. The step comes first and the product is one way to
do it: products never decide which plans or steps appear, and never touch a score.

Photos are the stores' own, loaded from their image servers at card size.
"""

from __future__ import annotations

from urllib.parse import quote_plus

# The day every link, price and photo below was checked on the store's own page.
CHECKED = "2026-09-19"

STORES = {
    "leroy_merlin": "Leroy Merlin",
    "xiaomi": "Xiaomi",
    "shelly": "Shelly",
    "bauhaus": "Bauhaus",
    "decathlon": "Decathlon",
    "midland": "Midland",
}


def _lm(path: str) -> str:
    """A Leroy Merlin photo from its image server, at the size of a card."""
    return f"https://media.adeo.com/{path}?width=240&height=240&fit=bounds"


def _lm_page(slug: str) -> str:
    return f"https://www.leroymerlin.es/productos/{slug}.html"


PRODUCTS = {
    # Emergency ------------------------------------------------------------------
    "midland_er300_pro": {
        "name": "Midland ER300 Pro",
        "what": "Emergency radio with hand crank and solar panel, a torch and a 10,000 mAh "
                "battery that charges a phone.",
        "price": 89.00, "store": "midland",
        "url": "https://es.midlandeurope.com/es_ES/productos/er-300-pro",
        "image": "https://es.midlandeurope.com/media/cache/resolve/sylius_shop_product_small_thumbnail/"
                 "32/c0/1435da9e5f725c1d58bfe26500f2.jpg",
    },
    "xiaomi_power_bank": {
        "name": "Xiaomi Power Bank 20000mAh",
        "what": "Charges a phone several times over, with its own built-in cable.",
        "price": 20.99, "store": "xiaomi",
        "url": "https://www.mi.com/es/product/xiaomi-power-bank-20000/buy/",
        "image": "https://i05.appmifile.com/825_item_es/04/08/2025/25be777c6f72908ae8c4f968419ab72f.png"
                 "?thumb=1&w=240&h=240",
    },
    # Flooding -------------------------------------------------------------------
    "shelly_flood_gen4": {
        "name": "Shelly Flood Gen4",
        "what": "Battery Wi-Fi leak sensor with a 2 m sensing cable: it sounds and alerts your phone.",
        "price": 34.90, "store": "shelly",
        "url": "https://www.shelly.com/es/products/shelly-flood-gen4",
        "image": "https://www.shelly.com/cdn/shop/files/Shelly-Flood-Gen4-main-image-02_1.png"
                 "?v=1756710152&width=240",
    },
    "garza_leak_alarm": {
        "name": "Garza water leak alarm",
        "what": "Stand-alone battery alarm: an 85 dB siren as soon as water reaches it.",
        "price": 9.49, "store": "leroy_merlin",
        "url": _lm_page("detector-fugas-de-agua-e-inundaciones-garza-82189417"),
        "image": _lm("media/4005898/media.jpg"),
    },
    "spaceo_shelving": {
        "name": "Spaceo galvanised shelving",
        "what": "Five steel shelves of 175 kg each, 176 × 90 × 40 cm, boltless assembly.",
        "price": 47.00, "store": "leroy_merlin",
        "url": _lm_page("estanteria-metalica-en-kit-galvanizada-spaceo-5-baldas-175kg-balda-176x90x40cm-85061884"),
        "image": _lm("media/3242267/media.jpg"),
    },
    "mbm_flood_barrier": {
        "name": "MBM aluminium door barrier",
        "what": "Made to measure for openings 60-120 cm wide, 60 cm high: the side posts stay "
                "fixed and the board goes in in minutes.",
        "price": 683.00, "store": "leroy_merlin",
        "url": _lm_page("mampara-antiinundacion-diy-personalizada-altura-60-cm-ancho-de-60-a-120-cm-"
                        "made-in-italy-89573099"),
        "image": _lm("mkp/0389a36320a850108df162f5ece6e21f/media.jpg"),
    },
    "hydrosnake_sacks": {
        "name": "Hydrosnake flood sacks, pack of 2",
        "what": "145 × 25 cm sacks with no sand: soaked, they swell into a barrier in 2-3 minutes.",
        "price": 29.99, "store": "leroy_merlin",
        "url": _lm_page("saco-anti-inundaciones-hydrosnake-145x25-cm-bolsa-de-2-unidades-19642420"),
        "image": _lm("media/1850574/media.png"),
    },
    "gardena_20000_pump": {
        "name": "Gardena 20000 dirty-water pump",
        "what": "750 W submersible pump with an adjustable float switch, up to 20,000 litres an hour.",
        "price": 119.00, "store": "leroy_merlin",
        "url": _lm_page("bomba-de-achique-para-aguas-sucias-gardena-20000-de-750w-de-potencia-y-caudal-"
                        "maximo-de-20000-l-h-83647728"),
        "image": _lm("media/2033854/media.jpg"),
    },
    "karmat_backwater_valve": {
        "name": "Karmat 110 mm backwater valve",
        "what": "Non-return valve for a horizontal 110 mm drain: sewage cannot come back up into "
                "low floors.",
        "price": 62.99, "store": "leroy_merlin",
        "url": _lm_page("110mm-polipropileno-comprobar-no-retorno-anti-inundacion-valvula-remanso-89178519"),
        "image": _lm("mkp/33ac70cec771a2eca12e703d6b091271/media.jpg"),
    },
    # Wildfire -------------------------------------------------------------------
    "xsense_wifi_smoke": {
        "name": "X-Sense Wi-Fi smoke alarm",
        "what": "Sounds and flashes, and alerts your phone when you are away.",
        "price": 18.99, "store": "leroy_merlin",
        "url": _lm_page("detector-de-humo-wifi-xsense-95983143"),
        "image": _lm("media/4796803/media.jpg"),
    },
    "garza_smoke_pack": {
        "name": "Garza smoke alarms, pack of 2",
        "what": "85 dB ceiling alarms with batteries and fixings; they also warn when the battery runs out.",
        "price": 11.99, "store": "leroy_merlin",
        "url": _lm_page("pack-de-2-detectores-de-humos-garza-81896304"),
        "image": _lm("media/4005902/media.jpg"),
    },
    "ferretelix_extinguisher": {
        "name": "Ferretelix 6 kg ABC extinguisher",
        "what": "Powder extinguisher rated 34A 233B C, made in 2026, with a wall bracket.",
        "price": 49.99, "store": "leroy_merlin",
        "url": _lm_page("ferretelix-extintor-6-kg-abc-alta-eficacia-34a-233b-c-incluye-soporte-de-pared-"
                        "homologado-ce0029-fabricado-en-2026-90730659"),
        "image": _lm("mkp/8de5874e3ebde81e0b279c097362864b/media.jpg"),
    },
    "securikit_fire_blanket": {
        "name": "Securikit fire blanket, 1.2 × 1 m",
        "what": "Fire blanket to EN 1869 for pan fires and small fires; hang it in the kitchen.",
        "price": 21.49, "store": "bauhaus",
        "url": "https://www.bauhaus.es/extintores-de-coche/manta-ignifuga-securikit/p/25155082",
        "image": "https://media.cdn.bauhaus/m/166639-1/prod_large_square.webp",
    },
    "xiaomi_purifier_4_compact": {
        "name": "Xiaomi Smart Air Purifier 4 Compact",
        "what": "Traps 99.97 % of fine particles, smoke included: 230 m³/h of clean air for 16-27 m².",
        "price": 99.99, "store": "xiaomi",
        "url": "https://www.mi.com/es/product/xiaomi-smart-air-purifier-4-compact/buy/",
        "image": "https://i01.appmifile.com/webfile/globalimg/Air-Purifier-4-Compact.png",
    },
    "equation_air_corner": {
        "name": "Equation Air Corner purifier",
        "what": "HEPA H13 and activated-carbon filters, 220 m³/h of clean air and an air-quality light.",
        "price": 129.00, "store": "leroy_merlin",
        "url": _lm_page("purificador-de-aire-air-corner-equation-para-superficie-hasta-45m2-88282985"),
        "image": _lm("media/1690630/media.jpg"),
    },
    "3m_ffp2_masks": {
        "name": "3M FFP2 masks with valve, pack of 3",
        "what": "Particle masks for smoky days; the valve makes breathing out easier.",
        "price": 10.99, "store": "leroy_merlin",
        "url": _lm_page("mascarilla-3m-con-filtro-de-particulas-ffp2-81884164"),
        "image": _lm("media/3055974/media.jpg"),
    },
    "geolia_hose_30m": {
        "name": "Geolia Aqualis hose, 30 m",
        "what": "15 mm garden hose rated to 21 bar, long enough to reach round most houses.",
        "price": 29.99, "store": "leroy_merlin",
        "url": _lm_page("manguera-geolia-aqualis-de-pvc-de-15-mm-de-y-30-m-de-longitud-95317539"),
        "image": _lm("media/5271818/media.png"),
    },
    "saturnia_ember_mesh": {
        "name": "Saturnia galvanised steel mesh, 1 × 25 m",
        "what": "16 × 16 weave with openings well under 3 mm: cut it to cover vents, eaves and gutters.",
        "price": 43.68, "store": "leroy_merlin",
        "url": _lm_page("tela-mosquitera-galvanizada-16x16-100-cm-rollo-25-metros-88398452"),
        "image": _lm("mkp/903472818077517dc2b10da3266e04c7/media.jpg"),
    },
    # Avalanches -----------------------------------------------------------------
    "arva_evo4_pack": {
        "name": "Arva Evo4 avalanche pack",
        "what": "Transceiver, metal shovel and cable probe: the three things each person carries off-piste.",
        "price": 259.99, "store": "decathlon",
        "url": "https://www.decathlon.es/es/p/pack-avalancha-arva-evo4-v2-pala-metal-sonda-cable-dva-evo-4-v2/"
               "353791/m8981465",
        "image": "https://contents.mediadecathlon.com/p3007015/k$772f9c6e536196274f20b691d0fbf9aa/"
                 "picture.jpg?format=auto&f=240x240",
    },
    # Extreme heat ---------------------------------------------------------------
    "xiaomi_th_monitor_2": {
        "name": "Mi Temperature and Humidity Monitor 2",
        "what": "A small screen with the room's temperature and humidity, readable on your phone too.",
        "price": 9.99, "store": "xiaomi",
        "url": "https://www.mi.com/es/product/mi-temperature-and-humidity-monitor-2/buy/",
        "image": "https://i01.appmifile.com/v1/MI_18455B3E4DA706226CF7535A58E875F0267/"
                 "pms_1605088817.31146374.png?thumb=1&w=240&h=240",
    },
    "naterial_calima_awning": {
        "name": "Naterial Calima awning, 2.5 × 2 m",
        "what": "Hand-cranked awning for a window or balcony: the shade stays outside the glass.",
        "price": 139.00, "store": "leroy_merlin",
        "url": _lm_page("toldo-brazo-extensible-2-5x2m-para-terraza-calima-estructura-blanca-manual-con-"
                        "manivela-tela-poliester-beige-naterial-82752785"),
        "image": _lm("media/1250533/media.png"),
    },
    "arte_confort_cacela_fan": {
        "name": "Arte Confort Cacela ceiling fan",
        "what": "Quiet 92 cm DC fan using 23 W, with light and remote, for rooms up to 13 m².",
        "price": 54.99, "store": "leroy_merlin",
        "url": _lm_page("ventilador-de-techo-con-luz-silencioso-dc-23w-con-mando-92-cm-cacela-arte-confort-"
                        "blanco-luz-cct-3-aspas-6-velocidades-modo-verano-invierno-brisa-temporizador-"
                        "recomendado-para-13m2-83738629"),
        "image": _lm("media/3365627/media.jpg"),
    },
    "mitsubishi_msz_ay35": {
        "name": "Mitsubishi Electric MSZ-AY35VGK",
        "what": "3.5 kW heat-pump split, A+++ for cooling and heating, 18 dB(A) and Wi-Fi. "
                "Installation not included.",
        "price": 889.11, "store": "leroy_merlin",
        "url": _lm_page("aire-acondicionado-split-1x1-mitsubishi-electric-msz-ay35vgk-a-wi-fi-3010-fg-87569555"),
        "image": _lm("media/4748813/media.jpg"),
    },
    "isover_ibr80": {
        "name": "ISOVER IBR 80 insulation roll",
        "what": "Glass wool 80 mm thick, 10 × 1.2 m, with a kraft vapour barrier (R = 2).",
        "price": 42.58, "store": "leroy_merlin",
        "url": _lm_page("1-ud-de-aislamiento-fibra-de-vidrio-ibr80-isover-10x1-2m-espesor-80mm-r-2-95578039"),
        "image": _lm("media/1822787/media.jpg"),
    },
}


# --------------------------------------------------------------------------- #
# The Advanced Kit: step two, once the basics are covered
# --------------------------------------------------------------------------- #
# The same seven things for every home: they keep working with no electricity, no phone
# network and no shop open, the first 72 hours after a big fire or flood. Prices are
# indicative; each link opens the store's search for the item, and the photos are the
# app's own.
KIT_STORES = {
    "amazon": ("Amazon", "https://www.amazon.es/s?k={q}"),
    "leroy_merlin": ("Leroy Merlin", "https://www.leroymerlin.es/search?q={q}"),
    "decathlon": ("Decathlon", "https://www.decathlon.es/es/search?Ntt={q}"),
}

ADVANCED_KIT = [
    {"id": "solar_charger", "name": "Solar charger, 20 W foldable",
     "what": "Charges a phone from sunlight on day three of a blackout. IP67.",
     "price": 49.90, "store": "amazon", "search": "cargador solar plegable 20W IP67",
     "image": "solar-charger.jpg", "alt": "Foldable 20 W solar charger with a phone charging from it"},
    {"id": "walkie_talkies", "name": "Walkie-talkies, pack of 2",
     "what": "PMR446, no licence needed. Talk within a few kilometres with no network.",
     "price": 59.90, "store": "amazon", "search": "walkie talkie PMR446 pack 2",
     "image": "walkie-talkies.jpg", "alt": "Pair of PMR446 walkie-talkies with charging dock"},
    {"id": "gas_stove", "name": "Portable gas stove with case",
     "what": "Hot food and boiled water with no electricity and no gas supply.",
     "price": 24.90, "store": "leroy_merlin", "search": "hornillo gas portatil maletin",
     "image": "gas-stove.jpg", "alt": "Portable gas stove with its carrying case"},
    {"id": "folding_shovel", "name": "Folding shovel multitool",
     "what": "Digs, cuts and pries. Clears mud or a jammed door after a flood.",
     "price": 29.95, "store": "decathlon", "search": "pala plegable",
     "image": "folding-shovel.jpg", "alt": "Folding shovel multitool"},
    {"id": "duct_tape", "name": "Heavy-duty duct tape, 4 rolls",
     "what": "Seals a broken window, a leaking pipe or a gap under the door.",
     "price": 19.90, "store": "leroy_merlin", "search": "cinta americana",
     "image": "duct-tape.jpg", "alt": "Roll of black heavy-duty duct tape"},
    {"id": "whistle", "name": "Aluminium survival whistle",
     "what": "Carries much further than a shout, and never runs out of battery.",
     "price": 6.95, "store": "decathlon", "search": "silbato emergencia",
     "image": "whistle.jpg", "alt": "Aluminium survival whistle on a keyring"},
    {"id": "faraday_bag", "name": "Faraday bag for phone and keys",
     "what": "Blocks every radio signal in or out: no relay theft, no tracking.",
     "price": 24.95, "store": "amazon", "search": "bolsa faraday movil llaves",
     "image": "faraday-bag.jpg", "alt": "Faraday bag holding a car key and a V16 emergency beacon"},
]
KIT_IMAGES = "/assets/media/kit/"
KIT_PRICED = "Spain, September 2026"
KIT_NOTE = ("The gas stove needs butane cartridges, sold separately; use it in a ventilated room, "
            "never in a closed one.")


def advanced_kit() -> dict:
    """The Advanced Kit as the app shows it: each item with its store and link, the total
    and how many stores it takes."""
    items = []
    for item in ADVANCED_KIT:
        store, search = KIT_STORES[item["store"]]
        items.append({"id": item["id"], "name": item["name"], "what": item["what"],
                      "price": item["price"], "store": store,
                      "url": search.format(q=quote_plus(item["search"])),
                      "image": KIT_IMAGES + item["image"], "alt": item["alt"]})
    return {"items": items, "total": round(sum(i["price"] for i in items), 2),
            "stores": len({i["store"] for i in ADVANCED_KIT}), "priced": KIT_PRICED, "note": KIT_NOTE}

