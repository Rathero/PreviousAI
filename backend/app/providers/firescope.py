"""Wildfire risk for 2026 at 30 m · FireScope (INSAIT). Europe and Asia, no key.

FireScope is a research vision-language model (CVPR 2026) trained on the US Wildfire Risk
to Communities layer "risk to potential structures" and applied to Sentinel-2 imagery
and NASA POWER climate across Eurasia. It adds what the weather card lacks: the fuel and
the terrain around the address. It is an AI model's output, so it is shown as context
and never scored.

The published map is one GeoTIFF per region on Hugging Face (CC BY 4.0): a BigTIFF in
EPSG:3857 with 30 m pixels, 512 x 512 LZW tiles, uint8, 255 = no data. Europe alone is
12 GB, so only the few tiles around the point are read, with HTTP range requests. Values
map linearly onto FireScope's 0-100 score (value / 2.55), which matches its own map and
legend. Its classes: Safe < 25 <= Low < 50 <= Moderate < 75 <= High. Built-up land and
water read 0. The model predicts in patches of ~10 km, and the seams between patches
show on its own map too: they are in the data, not an artefact of this reader.

The text explanations FireScope publishes next to the map are LLM output with visible
mistakes, so they are not used.
"""

from __future__ import annotations

import base64
import math
import struct
import zlib
from collections import OrderedDict

import httpx

from .. import cache, config

# Pinned revision: the numbers can be reproduced even if a new map is published under
# the same name.
REVISION = "1c69a10a637d6f0c83f678307102838db958787a"
BASE_URL = f"https://huggingface.co/datasets/INSAIT-Institute/firescope-risk-2026/resolve/{REVISION}/"
PAGE_URL = "https://firescope.ai/"
# Rough extent of each raster (from firescope.ai's own map bounds), to choose the
# file without touching the network and to skip the Americas, Africa and Oceania.
RASTERS = (
    ("europe_risk.tif", (33.9, -10.7, 71.3, 46.1)),
    ("asia_risk.tif", (18.1, 45.9, 60.1, 180.0)),
)
NODATA = 255
SCALE = 100 / 255          # uint8 -> 0-100 (value / 2.55)
CLASSES = ((75, "High"), (50, "Moderate"), (25, "Low"), (0, "Safe"))
STATS_RADIUS_M = 1000      # the surroundings described on the card
SEARCH_RADIUS_M = 3000     # how far the nearest risky land is looked for
OVERLAY_HALF_M = 3000      # the map overlay: a 6 x 6 km square
TTL_S = 365 * 24 * 3600    # one fixed map for 2026
MERCATOR_R = 6378137.0
# Decoded tiles kept in memory (256 KB each): nearby reports reuse them.
TILE_MEMORY = 24
_TILES: OrderedDict[tuple[str, int, int], bytes | None] = OrderedDict()

# FireScope's own legend (firescope.ai), so the overlay reads like their map.
GRADIENT = ((0, (198, 214, 79)), (4, (220, 235, 109)), (8, (230, 240, 132)),
            (18, (226, 240, 149)), (28, (255, 245, 178)), (39, (255, 223, 94)),
            (49, (255, 197, 96)), (60, (249, 166, 50)), (70, (244, 99, 55)),
            (80, (230, 69, 41)), (90, (173, 19, 14)), (100, (190, 0, 0)))
LEGEND = [
    {"color": "#ffd25f", "label": "Low (25-50)"},
    {"color": "#f6843a", "label": "Moderate (50-75)"},
    {"color": "#c8281a", "label": "High (75-100)"},
]


def raster_for(lat: float, lon: float) -> str | None:
    for name, (s, w, n, e) in RASTERS:
        if s <= lat <= n and w <= lon <= e:
            return name
    return None


def risk_class(value: float | None) -> str | None:
    if value is None:
        return None
    return next(label for floor, label in CLASSES if value >= floor)


def to_score(raw: int) -> float | None:
    return None if raw == NODATA else round(raw * SCALE, 1)


# --------------------------------------------------------------------------- #
# TIFF LZW (no numpy, no GDAL: the request path stays pure Python)
# --------------------------------------------------------------------------- #
def lzw_decode(data: bytes) -> bytes:
    """TIFF's LZW: MSB-first codes of 9-12 bits, 256 = clear, 257 = end, and the
    "early change" the TIFF spec uses (the width grows one code early)."""
    out = bytearray()
    table = [bytes([i]) for i in range(256)] + [b"", b""]
    buf = bits = pos = 0
    width, prev, n = 9, None, len(data)
    while True:
        while bits < width:
            if pos >= n:
                return bytes(out)
            buf = (buf << 8) | data[pos]
            pos += 1
            bits += 8
        bits -= width
        code = (buf >> bits) & ((1 << width) - 1)
        buf &= (1 << bits) - 1
        if code == 257:
            break
        if code == 256:
            del table[258:]
            width, prev = 9, None
            continue
        if prev is None:
            entry = table[code]
        elif code < len(table):
            entry = table[code]
            table.append(prev + entry[:1])
        else:
            entry = prev + prev[:1]
            table.append(entry)
        out += entry
        prev = entry
        if len(table) + 1 >= (1 << width) and width < 12:
            width += 1
    return bytes(out)


# --------------------------------------------------------------------------- #
# Reading the remote GeoTIFF
# --------------------------------------------------------------------------- #
_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8,
              16: 8, 17: 8, 18: 8}
_TYPE_FMT = {1: "B", 3: "H", 4: "I", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q", 17: "q", 18: "Q"}


class RemoteTiff:
    """The first image of a tiled (Big)TIFF, read with range requests."""

    def __init__(self, url: str, client: httpx.Client):
        self.url, self.client = url, client

    def read(self, start: int, length: int) -> bytes:
        resp = self.client.get(self.url, headers={"Range": f"bytes={start}-{start + length - 1}"})
        if resp.status_code != 206:
            raise httpx.HTTPStatusError(f"range request answered {resp.status_code}",
                                        request=resp.request, response=resp)
        # Hugging Face redirects to a signed CDN URL: reuse it for the next reads.
        self.url = str(resp.url)
        return resp.content


def parse_header(head: bytes, read) -> dict:
    """Georeferencing and tile layout of the first IFD. `read(start, length)`
    fetches the values stored outside the IFD entries."""
    bo = "<" if head[:2] == b"II" else ">"
    big = struct.unpack(bo + "H", head[2:4])[0] == 43
    off = struct.unpack(bo + ("Q" if big else "I"), head[8:16] if big else head[4:8])[0]
    esz, cnt_fmt, inline = (20, "Q", 8) if big else (12, "H", 4)
    ifd = head[off:off + 8 + 20 * 64] if off + 8 < len(head) else read(off, 8 + 20 * 64)
    n = struct.unpack(bo + cnt_fmt, ifd[:8 if big else 2])[0]
    base = 8 if big else 2
    tags = {}
    for i in range(n):
        e = ifd[base + i * esz: base + (i + 1) * esz]
        tag, typ = struct.unpack(bo + "HH", e[:4])
        count = struct.unpack(bo + ("Q" if big else "I"), e[4:12] if big else e[4:8])[0]
        size = _TYPE_SIZE.get(typ, 1) * count
        raw = e[12:20] if big else e[8:12]
        if tag in (324, 325):  # tile offsets / byte counts: keep where they are
            pos = struct.unpack(bo + ("Q" if big else "I"), raw)[0] if size > inline else None
            tags[tag] = {"type": typ, "count": count, "pos": pos,
                         "inline": raw[:size].hex() if pos is None else None}
            continue
        data = raw[:size] if size <= inline else read(struct.unpack(bo + ("Q" if big else "I"), raw)[0], size)
        if typ == 2:
            tags[tag] = data.rstrip(b"\0").decode("latin-1")
        elif typ in _TYPE_FMT:
            tags[tag] = list(struct.unpack(bo + _TYPE_FMT[typ] * count, data))
    scale, tie = tags[33550], tags[33922]
    return {
        "byteorder": bo, "width": tags[256][0], "height": tags[257][0],
        "tile_w": tags[322][0], "tile_h": tags[323][0], "compression": tags[259][0],
        "predictor": (tags.get(317) or [1])[0],
        "x0": tie[3] - tie[0] * scale[0], "y0": tie[4] + tie[1] * scale[1],
        "px": scale[0], "py": scale[1],
        "offsets": tags[324], "counts": tags[325],
        "nodata": tags.get(42113),
    }


class Raster:
    """One FireScope raster: the header once, then tiles on demand."""

    def __init__(self, name: str, client: httpx.Client):
        self.name = name
        self.remote = RemoteTiff(BASE_URL + name, client)
        key = f"header:{REVISION}:{name}"
        header = cache.get("firescope", key, ttl=TTL_S)
        if header is None:
            header = parse_header(self.remote.read(0, 65536), self.remote.read)
            cache.set("firescope", key, header)
        if header["compression"] != 5 or header["predictor"] != 1:
            raise ValueError(f"unsupported FireScope TIFF layout: {header}")
        self.h = header
        self.tiles_across = math.ceil(header["width"] / header["tile_w"])

    def _entry(self, table: dict, index: int) -> int:
        size = _TYPE_SIZE[table["type"]]
        if table["pos"] is None:  # a single tile, stored inside the IFD entry
            raw = bytes.fromhex(table["inline"])[index * size:(index + 1) * size]
        else:
            raw = self.remote.read(table["pos"] + index * size, size)
        return struct.unpack(self.h["byteorder"] + _TYPE_FMT[table["type"]], raw)[0]

    def tile(self, col: int, row: int) -> bytes | None:
        key = (self.name, col, row)
        if key in _TILES:
            _TILES.move_to_end(key)
            return _TILES[key]
        index = row * self.tiles_across + col
        length = self._entry(self.h["counts"], index)
        data = lzw_decode(self.remote.read(self._entry(self.h["offsets"], index), length)) \
            if length else None
        _TILES[key] = data
        if len(_TILES) > TILE_MEMORY:
            _TILES.popitem(last=False)
        return data

    def value(self, mx: float, my: float) -> int:
        h = self.h
        c = int((mx - h["x0"]) // h["px"])
        r = int((h["y0"] - my) // h["py"])
        if not (0 <= c < h["width"] and 0 <= r < h["height"]):
            return NODATA
        t = self.tile(c // h["tile_w"], r // h["tile_h"])
        if t is None:
            return NODATA
        return t[(r % h["tile_h"]) * h["tile_w"] + (c % h["tile_w"])]


# --------------------------------------------------------------------------- #
# What the report uses
# --------------------------------------------------------------------------- #
def mercator(lat: float, lon: float) -> tuple[float, float]:
    return (MERCATOR_R * math.radians(lon),
            MERCATOR_R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def inverse_mercator(x: float, y: float) -> tuple[float, float]:
    return (math.degrees(2 * math.atan(math.exp(y / MERCATOR_R)) - math.pi / 2),
            math.degrees(x / MERCATOR_R))


def summarize(value_at, lat: float, lon: float, px: float = 30.0) -> dict:
    """Point value, the 1 km surroundings and the nearest risky land within 3 km.

    `value_at(mx, my)` returns the raw pixel. Distances are on the ground: in Web
    Mercator a metre is 1/cos(latitude) map metres."""
    mx, my = mercator(lat, lon)
    k = 1 / max(math.cos(math.radians(lat)), 0.05)
    reach = int(SEARCH_RADIUS_M * k // px)
    around, nearest = [], {"low": None, "moderate": None, "high": None}
    where: dict[str, tuple[float, float]] = {}
    floors = (("high", 75), ("moderate", 50), ("low", 25))
    for i in range(-reach, reach + 1):
        for j in range(-reach, reach + 1):
            d = math.hypot(i, j) * px / k
            if d > SEARCH_RADIUS_M:
                continue
            score = to_score(value_at(mx + i * px, my + j * px))
            if score is None:
                continue
            if d <= STATS_RADIUS_M:
                around.append(score)
            for name, floor in floors:
                if score >= floor and (nearest[name] is None or d < nearest[name]):
                    nearest[name] = d
                    where[name] = (mx + i * px, my + j * px)
    point = to_score(value_at(mx, my))
    if not around and point is None:
        return {"covered": False}
    around.sort()
    share = (lambda f: round(sum(v >= f for v in around) / len(around), 3)) if around else (lambda f: None)
    return {
        "covered": True,
        "value": point, "class": risk_class(point),
        "radius_m": STATS_RADIUS_M, "search_m": SEARCH_RADIUS_M,
        "max": around[-1] if around else None,
        "max_class": risk_class(around[-1]) if around else None,
        "median": around[len(around) // 2] if around else None,
        "share_moderate": share(50), "share_high": share(75),
        "nearest_m": {k2: None if v is None else round(v) for k2, v in nearest.items()},
        # Where that land is: the fire-spread what-if starts from the nearest one.
        "nearest_at": {k2: [round(c, 5) for c in inverse_mercator(*xy)] for k2, xy in where.items()},
        "pixels": len(around),
    }


def _color(score: float) -> tuple[int, int, int]:
    for (a, ca), (b, cb) in zip(GRADIENT, GRADIENT[1:]):
        if score <= b:
            t = (score - a) / (b - a) if b > a else 0
            return tuple(round(ca[i] + (cb[i] - ca[i]) * t) for i in range(3))
    return GRADIENT[-1][1]


def png_rgba(width: int, height: int, rows: list[bytes]) -> bytes:
    """A minimal PNG encoder (RGBA, no filter): enough for a map overlay."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(
            ">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + r for r in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def overlay(value_at, lat: float, lon: float, px: float = 30.0) -> dict:
    """The 6 x 6 km square around the point, coloured like FireScope's map.

    Safe land (< 25, which includes towns and water) is left transparent so the
    street map shows through and only the risky land is painted. The raster is
    already in Web Mercator, the web map's projection: pixels are drawn as they
    are, no resampling."""
    mx, my = mercator(lat, lon)
    k = 1 / max(math.cos(math.radians(lat)), 0.05)
    half = int(OVERLAY_HALF_M * k // px)
    # Snap to the raster's own pixel grid so each image pixel is one FireScope pixel.
    cx, cy = math.floor(mx / px) * px, math.floor(my / px) * px
    rows = []
    for j in range(half, -half, -1):          # north to south
        row = bytearray()
        for i in range(-half, half):
            score = to_score(value_at(cx + i * px + px / 2, cy + j * px - px / 2))
            if score is None or score < 25:
                row += b"\x00\x00\x00\x00"
            else:
                row += bytes(_color(score)) + b"\xa6"
        rows.append(bytes(row))
    size = 2 * half
    south, west = inverse_mercator(cx - half * px, cy - half * px)
    north, east = inverse_mercator(cx + half * px, cy + half * px)
    png = png_rgba(size, size, rows)
    return {"bounds": [[round(south, 6), round(west, 6)], [round(north, 6), round(east, 6)]],
            "image": "data:image/png;base64," + base64.b64encode(png).decode(),
            "pixels": size}


def around(lat: float, lon: float) -> dict | None:
    """FireScope's risk at and around the point, plus the map overlay.

    Synchronous and CPU-bound (LZW in pure Python): the report runs it in a
    thread. None outside Eurasia. Cached per point for a year: the map is a
    fixed product for 2026."""
    name = raster_for(lat, lon)
    if not name:
        return None
    key = f"v2:{REVISION}:{name}:{lat:.5f},{lon:.5f}"  # v2: with nearest_at
    hit = cache.get("firescope", key, ttl=TTL_S)
    if hit is not None:
        return hit
    try:
        with httpx.Client(timeout=config.HTTP_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": config.USER_AGENT}) as client:
            raster = Raster(name, client)
            px = raster.h["px"]
            result = summarize(raster.value, lat, lon, px)
            if result.get("covered"):
                result["overlay"] = overlay(raster.value, lat, lon, px)
    except (httpx.HTTPError, KeyError, ValueError, struct.error):
        stale = cache.get("firescope", key, allow_stale=True)
        if stale is not None:
            return stale
        raise
    result.update({"raster": name, "revision": REVISION,
                   "url": BASE_URL.replace("/resolve/", "/blob/") + name})
    cache.set("firescope", key, result)
    return result
