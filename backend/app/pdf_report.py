"""The report as a PDF to keep and share.

Everything the web app shows, in more detail: the home and its pictures, the four risks
with every value that builds each score and what it does not say, what already happened
near the home, the climate to 2050, the full action plan with its partners, and the
sources. It is drawn from the same report as the app (`report.build_report` and
`view.app_view`): nothing here is computed that is not already there.

Pictures: the Street View image (credited to Google), an aerial view stitched from open
orthophoto tiles (credited to their source) and the AI illustrations the data picked,
labelled as such. Nothing is stored: the file is drawn on request.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import io
import math
import re
import unicodedata
from functools import lru_cache, partial
from xml.sax.saxutils import escape

import httpx
from PIL import Image, ImageDraw
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable, Frame, KeepTogether,
                                NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)
from reportlab.platypus import Image as PdfImage

from . import config, media, protection
from .providers import streetview

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
WIDTH = PAGE_W - 2 * MARGIN
BAND_H = 64 * mm
FOOT_Y = 10 * mm

FONT_FILE = config.ROOT / "frontend" / "assets" / "fonts" / "BricolageGrotesque.ttf"
BODY, BOLD, ITALIC = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"

INK = colors.HexColor("#1E261B")
MUTED = colors.HexColor("#5B6655")
FAINT = colors.HexColor("#8C9586")
LINE = colors.HexColor("#DDE1D8")
PANEL = colors.HexColor("#F2F4EE")
BRAND = colors.HexColor("#1C2618")
CREAM = colors.HexColor("#F7F5EF")
CREAM_SOFT = colors.HexColor("#CFCCC2")
LINK = "#3D7414"
ORDER = ["wildfire", "flood", "heat", "avalanche"]
HAZARD = {"wildfire": "#E58A63", "flood": "#7FB4DC", "heat": "#E7C077", "avalanche": "#C7CBD6"}
HAZARD_TEXT = {"wildfire": "#B4532C", "flood": "#2D6A99", "heat": "#94670F", "avalanche": "#5E6679"}
NAMES = {"wildfire": "Fire", "flood": "Flooding", "heat": "Heat waves", "avalanche": "Avalanches"}
CHECKABLE = {"before", "buy", "first"}
LEVELS = [("Very low", "0-19"), ("Low", "20-39"), ("Moderate", "40-59"), ("High", "60-79"),
          ("Very high", "80-100")]
PROJECTION_LABELS = {"hot_days_35": "Days a year above 35 °C", "hot_days_32": "Days a year above 32 °C",
                     "tropical_nights": "Tropical nights a year (never below 20 °C)",
                     "rx1day": "Rain on the wettest day of a typical year"}
PRECISION = {"address": "at the building entrance of the address", "street": "in the middle of the street",
             "town": "at the centre of the town", "place": "at the centre of the place",
             "coordinates": "at the coordinates given"}
# Services the app works with whose names stay out of what it shows.
PRIVATE_SOURCES = ("nebius", "typesafe", "fal.ai", "deepfire")
DISCLAIMER = ("Risk levels are 0–100 hazard scores built from public scientific and official data. "
              "They are not probabilities, valuations or insurance advice.")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #
_SWAP = {"→": "->", "←": "<-", "≥": ">=", "≤": "<=", "≈": "~", "−": "-", "★": "*",
         " ": " ", " ": " ", " ": " "}


def safe(text) -> str:
    """Text the body face can draw: Helvetica only has the Windows-1252 characters."""
    s = str(text if text is not None else "")
    for a, b in _SWAP.items():
        s = s.replace(a, b)
    return s.encode("cp1252", "ignore").decode("cp1252")


def plain(text) -> str:
    """Safe text escaped for Paragraph markup."""
    return escape(safe(text))


def _href(url: str) -> str:
    return escape(url, {'"': "&quot;"})


def nice_date(value) -> str:
    """"2020-01-21" -> "21 Jan 2020"; "2012" and labels stay as they are."""
    m = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$", str(value or "")[:10])
    if not m:
        return str(value or "")
    if not m.group(2):
        return m.group(1)
    month = MONTHS[int(m.group(2)) - 1]
    return f"{int(m.group(3))} {month} {m.group(1)}" if m.group(3) else f"{month} {m.group(1)}"


def dates(text) -> str:
    """ISO dates inside a text as people write them: "1982-11-05" -> "5 Nov 1982"."""
    return re.sub(r"\b\d{4}-\d{2}-\d{2}\b", lambda m: nice_date(m.group(0)), str(text or ""))


def public_source(text) -> str:
    """A source as the report names it: the data, not the service that delivered them."""
    s = str(text or "")
    if "deepfire" in s.lower():
        return "Satellite hotspots (VIIRS, MODIS)"
    return re.sub(r",?\s+(via|read from)\s+.*$", "", s)


def shown(ind: dict) -> str:
    """An indicator's value as the report states it, never re-rounded into a new number."""
    display = (ind.get("extras") or {}).get("display")
    if display not in (None, ""):
        return dates(display)
    value, unit = ind.get("value"), (ind.get("unit") or "").strip()
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        digits = 3 if abs(value) < 1 else 2 if abs(value) < 10 else 1 if abs(value) < 100 else 0
        text = f"{value:,.{digits}f}".rstrip("0").rstrip(".") if digits else f"{value:,.0f}"
        if value == 1 and unit.endswith("s") and "/" not in unit:
            unit = unit[:-1]   # "1 episode", not "1 episodes"
        return f"{text or '0'} {unit}".strip()
    return f"{value} {unit}".strip()


def segments(items: list[dict] | None) -> str:
    """An action-plan line as markup: its links (partners, official apps) stay links."""
    out = []
    for s in items or []:
        text = plain(s.get("text"))
        out.append(f'<a href="{_href(s["url"])}" color="{LINK}"><u>{text}</u></a>' if s.get("url") else text)
    return "".join(out)


def products(items: list[dict] | None) -> str:
    """The products proposed for a step, one per line: the name links to the store's page."""
    return "".join(f'<br/><font size="8" color="#5B6655"><a href="{_href(p["url"])}" color="{LINK}">'
                   f'<u>{plain(p["name"])}</u></a> · €{p["price"]:,.2f} at {plain(p["store"])}</font>'
                   for p in items or [])


def _tint(hex_color: str, amount: float) -> colors.Color:
    """The colour mixed with white: amount 0 is white, 1 is the colour."""
    c = colors.HexColor(hex_color)
    return colors.Color(1 - (1 - c.red) * amount, 1 - (1 - c.green) * amount, 1 - (1 - c.blue) * amount)


def _coords(loc: dict) -> str:
    lat, lon = float(loc["latitude"]), float(loc["longitude"])
    return f"{abs(lat):.5f}° {'N' if lat >= 0 else 'S'}, {abs(lon):.5f}° {'E' if lon >= 0 else 'W'}"


# --------------------------------------------------------------------------- #
# Fonts and styles
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def display_font() -> str:
    """The app's display face, Bricolage Grotesque at 600, as a static font built from the
    variable one; Helvetica Bold if it cannot be built."""
    try:
        from fontTools.ttLib import TTFont as VariableFont
        from fontTools.varLib.instancer import instantiateVariableFont
        static = instantiateVariableFont(VariableFont(str(FONT_FILE)), {"wght": 600, "opsz": 24, "wdth": 100})
        buf = io.BytesIO()
        static.save(buf)
        buf.seek(0)
        pdfmetrics.registerFont(TTFont("Display", buf))
        return "Display"
    except (ImportError, OSError, KeyError, ValueError):
        return BOLD


def _styles(display: str) -> dict[str, ParagraphStyle]:
    body = ParagraphStyle("body", fontName=BODY, fontSize=9.5, leading=13.5, textColor=INK)
    cell = ParagraphStyle("cell", fontName=BODY, fontSize=8, leading=10.6, textColor=INK)
    return {
        "body": body,
        "muted": ParagraphStyle("muted", parent=body, textColor=MUTED),
        "lead": ParagraphStyle("lead", fontName=BODY, fontSize=11, leading=15.5, textColor=MUTED),
        "small": ParagraphStyle("small", fontName=BODY, fontSize=8, leading=11, textColor=MUTED),
        "fine": ParagraphStyle("fine", fontName=ITALIC, fontSize=7.8, leading=10.6, textColor=FAINT),
        "title": ParagraphStyle("title", fontName=display, fontSize=20, leading=24, textColor=INK, spaceAfter=5),
        "h1": ParagraphStyle("h1", fontName=display, fontSize=19, leading=23, textColor=INK, spaceAfter=8),
        "h2": ParagraphStyle("h2", fontName=display, fontSize=13.5, leading=17, textColor=INK,
                             spaceBefore=10, spaceAfter=5),
        "h3": ParagraphStyle("h3", fontName=BOLD, fontSize=9.5, leading=13, textColor=INK,
                             spaceBefore=7, spaceAfter=3),
        "label": ParagraphStyle("label", fontName=BOLD, fontSize=7, leading=9.5, textColor=MUTED),
        "big": ParagraphStyle("big", fontName=display, fontSize=17, leading=19, textColor=INK),
        "cell": cell,
        "cellm": ParagraphStyle("cellm", parent=cell, textColor=MUTED),
        "cellh": ParagraphStyle("cellh", fontName=BOLD, fontSize=6.8, leading=9, textColor=MUTED),
    }


# --------------------------------------------------------------------------- #
# Drawn pieces
# --------------------------------------------------------------------------- #
def _draw_bars(c, x: float, y: float, width: float, height: float, score, color: str, dim: bool) -> None:
    """The ten segments of the app's risk tiles."""
    lit = 0 if not score or score <= 0 else max(1, round(score / 10))
    gap = height * 0.9
    seg = (width - gap * 9) / 10
    on = _tint(color, 0.6 if dim else 1)
    for i in range(10):
        c.setFillColor(on if i < lit else LINE)
        c.roundRect(x + i * (seg + gap), y, seg, height, height / 2, stroke=0, fill=1)


class RiskTiles(Flowable):
    """The four risks side by side, as on the app's report."""

    PAD, GAP = 3.6 * mm, 3 * mm

    def __init__(self, risks: list[dict], st: dict, display: str):
        super().__init__()
        self.risks, self.st, self.display = risks, st, display

    def wrap(self, aw, ah):
        self.width = aw
        self.col = (aw - 3 * self.GAP) / 4
        self.facts = [Paragraph(plain(r.get("fact") or ""), self.st["small"]) for r in self.risks]
        fact_h = max((p.wrap(self.col - 2 * self.PAD, 200 * mm)[1] for p in self.facts), default=0)
        self.height = self.PAD * 2 + 60 + fact_h
        return self.width, self.height

    def draw(self):
        c = self.canv
        for i, (risk, fact) in enumerate(zip(self.risks, self.facts)):
            key, x = risk["key"], i * (self.col + self.GAP)
            color, dim = HAZARD[key], not risk.get("worth")
            c.setFillColor(_tint(color, 0.06 if dim else 0.13))
            c.setStrokeColor(_tint(color, 0.3 if dim else 0.6))
            c.setLineWidth(0.6)
            c.roundRect(x, 0, self.col, self.height, 3 * mm, stroke=1, fill=1)
            left, y = x + self.PAD, self.height - self.PAD - 8
            c.setFillColor(_tint(color, 0.6 if dim else 1))
            c.circle(left + 2.2, y + 2.8, 2.3, stroke=0, fill=1)
            c.setFillColor(INK)
            c.setFont(BOLD, 9.5)
            c.drawString(left + 8, y, risk["label"])
            y -= 25
            score = risk.get("score")
            c.setFillColor(MUTED if dim else INK)
            c.setFont(self.display, 22)
            c.drawString(left, y, "-" if score is None else f"{score}%")
            y -= 9
            _draw_bars(c, left, y, self.col - 2 * self.PAD, 3.2, score, color, dim)
            y -= 11
            c.setFillColor(colors.HexColor(HAZARD_TEXT[key]))
            c.setFont(BOLD, 6.8)
            c.drawString(left, y, str(risk.get("level") or "not assessed").upper())
            _, h = fact.wrap(self.col - 2 * self.PAD, 200 * mm)
            fact.drawOn(c, left, y - 4 - h)


class RiskBanner(Flowable):
    """The heading of one risk: its name, level and score over its colour."""

    def __init__(self, risk: dict, display: str):
        super().__init__()
        self.risk, self.display = risk, display

    def wrap(self, aw, ah):
        self.width, self.height = aw, 17 * mm
        return self.width, self.height

    def draw(self):
        c, risk = self.canv, self.risk
        key, dim = risk["key"], not risk.get("worth")
        color = HAZARD[key]
        c.setFillColor(_tint(color, 0.08 if dim else 0.16))
        c.setStrokeColor(_tint(color, 0.3 if dim else 0.55))
        c.setLineWidth(0.6)
        c.roundRect(0, 0, self.width, self.height, 3 * mm, stroke=1, fill=1)
        c.setFillColor(_tint(color, 0.6 if dim else 1))
        c.circle(5 * mm, self.height - 7.2 * mm + 2.6, 2.6, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont(self.display, 15)
        c.drawString(8 * mm, self.height - 7.2 * mm, risk["label"])
        c.setFillColor(colors.HexColor(HAZARD_TEXT[key]))
        c.setFont(BOLD, 7.2)
        verdict = "worth preparing for" if risk.get("worth") else "not a concern here"
        c.drawString(8 * mm, 4.4 * mm, f"{risk.get('level') or 'not assessed'} · {verdict}".upper())
        score = risk.get("score")
        c.setFillColor(INK)
        c.setFont(self.display, 22)
        c.drawRightString(self.width - 5 * mm, self.height - 8.4 * mm, "-" if score is None else f"{score}%")
        _draw_bars(c, self.width - 60 * mm, 4.2 * mm, 55 * mm, 3, score, color, dim)


class Checkbox(Flowable):
    SIZE = 3.1 * mm

    def wrap(self, aw, ah):
        return self.SIZE, self.SIZE

    def draw(self):
        self.canv.setStrokeColor(MUTED)
        self.canv.setLineWidth(0.7)
        self.canv.roundRect(0, -0.4 * mm, self.SIZE, self.SIZE, 0.6 * mm, stroke=1, fill=0)


def _box(flowables: list, width: float = WIDTH, pad: float = 3.5 * mm) -> Table:
    t = Table([[flowables]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("LEFTPADDING", (0, 0), (-1, -1), pad), ("RIGHTPADDING", (0, 0), (-1, -1), pad),
        ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
        ("ROUNDEDCORNERS", [3 * mm] * 4),
    ]))
    return t


def _grid(rows: list[list], widths: list[float], *, header: bool = True, lines: bool = True) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
             ("TOPPADDING", (0, 0), (-1, -1), 3.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2)]
    if lines:
        style.append(("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE))
    if header:
        style.append(("LINEBELOW", (0, 0), (-1, 0), 0.7, MUTED))
    t.setStyle(TableStyle(style))
    return t


def _columns(cells: list, widths: list[float], gap: float) -> Table:
    """Flowables side by side, top-aligned, with a gap between columns."""
    t = Table([cells], colWidths=[w + (gap if i < len(widths) - 1 else 0) for i, w in enumerate(widths)])
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
             ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]
    style += [("RIGHTPADDING", (i, 0), (i, 0), gap) for i in range(len(widths) - 1)]
    t.setStyle(TableStyle(style))
    return t


# --------------------------------------------------------------------------- #
# Pictures of the home
# --------------------------------------------------------------------------- #
def _month_year(value) -> str:
    m = re.match(r"^(\d{4})-(\d{2})", str(value or ""))
    return f"{MONTHS[int(m.group(2)) - 1]} {m.group(1)}" if m else ""


async def _street(lat: float, lon: float) -> dict | None:
    meta = await streetview.metadata(lat, lon)
    if not meta.get("available"):
        return None
    jpeg = await streetview.image(lat, lon, width=640, height=400)
    when = _month_year(meta.get("date"))
    return {"jpeg": jpeg, "size": (640, 400),
            "caption": f"Street View{' · ' + when if when else ''} · {meta.get('copyright') or '© Google'}"}


async def _aerial(lat: float, lon: float, aerial: dict, zoom: int, size=(800, 500)) -> dict | None:
    """An aerial picture centred on the home, stitched from the map tiles the app uses."""
    z = min(zoom, int(aerial.get("max_zoom") or 18))
    n = 2 ** z
    px = (lon + 180) / 360 * n * 256
    lat_r = math.radians(lat)
    py = (1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n * 256
    w, h = size
    x0, y0 = px - w / 2, py - h / 2
    tx0, ty0, tx1, ty1 = int(x0 // 256), int(y0 // 256), int((x0 + w) // 256), int((y0 + h) // 256)

    async def tile(client: httpx.AsyncClient, tx: int, ty: int):
        url = aerial["url"].replace("{z}", str(z)).replace("{x}", str(tx % n)).replace("{y}", str(ty))
        resp = await client.get(url)
        resp.raise_for_status()
        return tx, ty, resp.content

    async with httpx.AsyncClient(timeout=config.SECONDARY_TIMEOUT,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        got = await asyncio.gather(*(tile(client, tx, ty) for tx in range(tx0, tx1 + 1)
                                     for ty in range(ty0, ty1 + 1)), return_exceptions=True)
    tiles = [g for g in got if not isinstance(g, BaseException)]
    if len(tiles) < len(got) / 2:
        return None
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (27, 38, 24))
    for tx, ty, content in tiles:
        try:
            mosaic.paste(Image.open(io.BytesIO(content)).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
        except OSError:
            continue
    left, top = round(x0 - tx0 * 256), round(y0 - ty0 * 256)
    picture = mosaic.crop((left, top, left + w, top + h))
    draw = ImageDraw.Draw(picture)
    cx, cy = w / 2, h / 2
    draw.ellipse((cx - 11, cy - 11, cx + 11, cy + 11), fill=(255, 255, 255))
    draw.ellipse((cx - 7.5, cy - 7.5, cx + 7.5, cy + 7.5), fill=(166, 226, 46))
    out = io.BytesIO()
    picture.save(out, format="JPEG", quality=86)
    return {"jpeg": out.getvalue(), "size": size, "caption": f"Aerial view · {aerial.get('attribution', '')}"}


async def pictures(report: dict) -> dict:
    """{"street": {...} | None, "aerial": {...} | None}: whatever can be had, never an error."""
    loc = report["location"]
    lat, lon = float(loc["latitude"]), float(loc["longitude"])
    tasks = {}
    if streetview.available():
        tasks["street"] = _street(lat, lon)
    aerial = (report.get("map") or {}).get("aerial")
    if aerial:
        tasks["aerial"] = _aerial(lat, lon, aerial, {"address": 18, "street": 17}.get(loc.get("precision"), 15))
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    return {k: (None if isinstance(v, BaseException) else v) for k, v in zip(tasks, results)}


def _picture(pic: dict, width: float, max_height: float | None = None) -> PdfImage:
    pw, ph = pic["size"]
    height = width * ph / pw
    if max_height and height > max_height:
        width, height = max_height * pw / ph, max_height
    return PdfImage(io.BytesIO(pic["jpeg"]), width=width, height=height)


def _illustration_file(ill: dict | None):
    poster = (ill or {}).get("poster") or ""
    if not poster.startswith(media.URL_PREFIX):
        return None
    root = media.LIBRARY_DIR.resolve()
    path = (root / poster[len(media.URL_PREFIX):]).resolve()
    return path if path.is_file() and root in path.parents else None


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #
def _cover(app: dict, pics: dict, st: dict, display: str) -> list:
    out = []
    shots = [p for p in (pics.get("street"), pics.get("aerial")) if p]
    if len(shots) == 2:
        col = (WIDTH - 5 * mm) / 2
        out.append(_columns([[_picture(p, col), Spacer(1, 1.5 * mm), Paragraph(plain(p["caption"]), st["small"])]
                             for p in shots], [col, col], 5 * mm))
    elif shots:
        out += [_picture(shots[0], WIDTH, 70 * mm), Spacer(1, 1.5 * mm),
                Paragraph(plain(shots[0]["caption"]), st["small"])]
    head = app.get("headline") or {}
    out += [Spacer(1, 7 * mm), Paragraph(plain(head.get("title")), st["title"]),
            Paragraph(plain(head.get("text")), st["lead"]), Spacer(1, 6 * mm)]
    risks = sorted(app["risks"], key=lambda r: ORDER.index(r["key"]))
    out += [RiskTiles(risks, st, display), Spacer(1, 7 * mm)]
    facts = (app.get("history") or {}).get("highlights") or []
    if facts:
        rows = [[Paragraph(plain(f["number"]), st["big"]), Paragraph(plain(f["text"]), st["body"])] for f in facts]
        t = Table(rows, colWidths=[24 * mm, WIDTH - 24 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
        out.append(KeepTogether([Paragraph("What has happened around this home", st["h2"]), t]))
    return out


def _story(risk: dict, st: dict, width: float) -> list:
    rows = [[Paragraph(plain(nice_date(r["when"])), st["cellm"]), Paragraph(plain(r["text"]), st["body"])]
            for r in risk.get("story") or [] if r["text"] != risk.get("fact")]
    if not rows:
        return []
    t = Table(rows, colWidths=[24 * mm, width - 24 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (0, -1), 3.4)]))
    return [Paragraph(plain(risk["story_title"]), st["h3"]), t]


def _card(card: dict, st: dict, heading: str | None = None) -> list:
    rows = [[Paragraph("INDICATOR", st["cellh"]), Paragraph("VALUE", st["cellh"]),
             Paragraph("PERIOD", st["cellh"]), Paragraph("SOURCE", st["cellh"])]]
    for ind in card.get("indicators") or []:
        prov = ind.get("provenance") or {}
        label = plain(ind.get("label"))
        if ind.get("context"):
            label += f'<br/><font size="7" color="#5B6655">{plain(dates(ind["context"]))}</font>'
        rows.append([Paragraph(label, st["cell"]), Paragraph(plain(shown(ind)), st["cell"]),
                     Paragraph(plain(prov.get("period")), st["cellm"]),
                     Paragraph(plain(public_source(prov.get("source"))), st["cellm"])])
    out = [CondPageBreak(45 * mm)] + ([Paragraph(heading, st["h3"])] if heading else []) + [
           Paragraph(f"<b>{plain(card['label'])}</b> · {round(card['score'])}% · {plain(card['level'])}",
                     st["body"]),
           Paragraph(plain(card.get("headline")), st["muted"]), Spacer(1, 2 * mm),
           _grid(rows, [62 * mm, 34 * mm, 30 * mm, WIDTH - 126 * mm])]
    if card.get("limitation"):
        out += [Spacer(1, 1.5 * mm),
                Paragraph(f"<b>What this does not say.</b> {plain(card['limitation'])}", st["fine"])]
    return out + [Spacer(1, 4 * mm)]


def _risk(report: dict, risk: dict, st: dict, display: str) -> list:
    key = risk["key"]
    out = [CondPageBreak(80 * mm), RiskBanner(risk, display), Spacer(1, 3.5 * mm)]
    if risk.get("fact"):
        out.append(Paragraph(f"<b>{plain(risk['fact'])}</b>", st["body"]))
    if not risk.get("worth"):
        out.append(Paragraph("Nothing to prepare for here: this address scores at the bottom of the scale for "
                             "this hazard, so the action plan has no steps for it.", st["muted"]))
    out.append(Spacer(1, 1.5 * mm))
    poster = _illustration_file(risk.get("illustration"))
    pic_w = 70 * mm
    left_w = WIDTH - pic_w - 6 * mm if poster else WIDTH
    left = _story(risk, st, left_w)
    note = risk.get("home_note")
    if note and not any(r["text"] == note for r in risk.get("story") or []):
        left += [Spacer(1, 2 * mm), _box([Paragraph("FOR YOUR HOME", st["label"]),
                                          Paragraph(plain(note), st["body"])], width=left_w)]
    if poster:
        ill = risk["illustration"]
        right = [Spacer(1, 3 * mm), PdfImage(str(poster), width=pic_w, height=pic_w * 536 / 960),
                 Spacer(1, 1.5 * mm),
                 Paragraph(f"<b>AI illustration · not this place.</b> {plain(ill.get('title'))}. "
                           f"{plain(ill.get('caption'))}", st["small"])]
        out.append(_columns([left or [Spacer(1, 1)], right], [left_w, pic_w], 6 * mm))
    else:
        out += left
    cards = sorted((h for h in report.get("hazards", [])
                    if h["key"] in protection.FAMILIES[key]["cards"] and h.get("score") is not None),
                   key=lambda h: -h["score"])
    for i, card in enumerate(cards):
        out += _card(card, st, "How the score is built" if i == 0 else None)
    if not cards and risk.get("summary"):
        out += [Spacer(1, 2 * mm), Paragraph(plain(risk["summary"]), st["muted"]), Spacer(1, 5 * mm)]
    return out


def _ahead(report: dict, st: dict) -> list:
    proj = report.get("projection") or {}
    metrics = proj.get("metrics") or []
    fire = next((h for h in report.get("hazards", []) if h["key"] == "wildfire"), None)
    fwi = [i for i in (fire or {}).get("indicators", []) if "FWI" in (i.get("label") or "")]
    if not metrics and not fwi:
        return []
    out = [CondPageBreak(70 * mm), Paragraph("Looking ahead", st["h2"])]
    if metrics:
        rows = [[Paragraph("CLIMATE", st["cellh"]), Paragraph(plain(proj.get("baseline_period")), st["cellh"]),
                 Paragraph(plain(proj.get("future_period")), st["cellh"]), Paragraph("CHANGE", st["cellh"])]]
        for m in metrics:
            unit = "days" if "days" in (m.get("unit") or "") else (m.get("unit") or "")
            change = f"{m['delta']:+.1f} {unit}"
            if m.get("pct_change") is not None:
                change += f" ({m['pct_change']:+.0f}%)"
            rows.append([Paragraph(plain(PROJECTION_LABELS.get(m["key"], m["key"])), st["cell"]),
                         Paragraph(plain(f"{m['baseline']:.1f} {unit}"), st["cell"]),
                         Paragraph(plain(f"{m['future']:.1f} {unit}"), st["cell"]),
                         Paragraph(plain(change), st["cell"])])
        method = (proj.get("provenance") or {}).get("method") or ""
        note = ". ".join(x for x in (proj.get("scenario"), method[:1].upper() + method[1:]) if x)
        out += [_grid(rows, [80 * mm, 30 * mm, 30 * mm, WIDTH - 140 * mm]), Spacer(1, 1.5 * mm),
                Paragraph(plain(note + "."), st["fine"])]
    if fwi:
        rows = [[Paragraph("FIRE WEATHER", st["cellh"]), Paragraph("VALUE", st["cellh"])]]
        rows += [[Paragraph(plain(i["label"]), st["cell"]), Paragraph(plain(shown(i)), st["cell"])] for i in fwi]
        out += [Spacer(1, 3 * mm), _grid(rows, [WIDTH - 40 * mm, 40 * mm])]
    return out


def _right_now(report: dict, st: dict) -> list:
    lines = []
    outlook = report.get("outlook") or {}
    if outlook.get("headline"):
        lines.append(f"<b>Next 15 days.</b> {plain(outlook['headline'])}.")
        for ev in outlook.get("events") or []:
            f, c = ev.get("forecast") or {}, ev.get("climatology") or {}
            if f.get("expected_days") is None:
                continue
            lines.append(f"{plain(ev['label'])}: {f['expected_days']:.1f} expected in the next "
                         f"{f.get('days', 15)} days (usually {float(c.get('expected_days') or 0):.1f}).")
    alerts = report.get("alerts") or {}
    alfa = alerts.get("pla_alfa")
    if alfa:
        lines.append(f"<b>Wildfire alert level today ({plain(alfa.get('municipality'))}):</b> "
                     f"{plain(alfa.get('label'))}: {plain(alfa.get('means'))}.")
    fires = [f for f in (alerts.get("active_fires") or {}).get("fires") or [] if f.get("active")]
    if fires:
        near = min(fires, key=lambda f: f.get("distance_km") or 1e9)
        lines.append(f"<b>Fires burning now, seen by satellite:</b> {len(fires)}; the nearest "
                     f"{near['distance_km']:.1f} km away.")
    if "alerts" in alerts:
        found = alerts.get("alerts") or []
        lines.append("<b>Official flood and wildfire alerts nearby:</b> "
                     + (", ".join(plain(a.get("title") or a.get("name") or "alert") for a in found) + "."
                        if found else "none."))
    if not lines:
        return []
    return [CondPageBreak(50 * mm), Paragraph("Right now", st["h2"]),
            Paragraph("Not part of the scores: they describe the climate and the record, not today's weather.",
                      st["fine"]), Spacer(1, 1.5 * mm)] + [Paragraph(line, st["body"]) for line in lines]


def _checklist(items: list[dict], width: float, checkable: bool, st: dict) -> Table:
    rows = [[Checkbox() if checkable else Paragraph("•", st["body"]),
             Paragraph(segments(i.get("segments")) + products(i.get("products")), st["body"])]
            for i in items]
    t = Table(rows or [[Spacer(1, 1), Spacer(1, 1)]], colWidths=[6 * mm, width - 6 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1.6),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6), ("TOPPADDING", (0, 0), (0, -1), 3.2)]))
    return t


def _plan(app: dict, st: dict) -> list:
    ap = app.get("action_plan") or {}
    plans = ap.get("plans") or []
    if not plans:
        return []
    out = [PageBreak(), Paragraph("Your action plan", st["h1"]),
           Paragraph("A basic emergency plan for every home and, for each risk worth preparing for, what to "
                     "do before, what to buy or arrange, and what to do during and after. Tick the boxes as "
                     "you go.", st["lead"]), Spacer(1, 3 * mm)]
    household = [a for a in ap.get("household") or [] if a.get("text")]
    if household:
        items = [Paragraph("FOR YOUR HOUSEHOLD", st["label"])]
        items += [Paragraph(f"• {plain(a['text'])}", st["body"]) for a in household]
        out += [_box(items), Spacer(1, 3 * mm)]
    col = (WIDTH - 8 * mm) / 2
    for plan in plans:
        if plan["key"] == "emergency":
            items = plan.get("items") or []
            half = (len(items) + 1) // 2
            out.append(KeepTogether([
                Paragraph(plain(plan["label"]), st["h2"]),
                _columns([_checklist(items[:half], col, True, st), _checklist(items[half:], col, True, st)],
                         [col, col], 8 * mm)]))
            continue
        key = plan["key"]
        head = [Paragraph(plain(NAMES.get(key, plan["label"])), st["h2"])]
        if plan.get("note"):
            head.append(Paragraph(plain(plan["note"]), st["muted"]))
        phase_style = ParagraphStyle(f"phase-{key}", parent=st["label"],
                                     textColor=colors.HexColor(HAZARD_TEXT.get(key, "#5B6655")))
        cells = [[Spacer(1, 2 * mm), Paragraph(plain(ph["label"]).upper(), phase_style), Spacer(1, 1 * mm),
                  _checklist(ph.get("items") or [], col, ph["key"] in CHECKABLE, st)]
                 for ph in plan.get("phases") or []]
        rows = [_columns(cells[i:i + 2] + [[Spacer(1, 1)]] * (2 - len(cells[i:i + 2])), [col, col], 8 * mm)
                for i in range(0, len(cells), 2)]
        out.append(KeepTogether(head + rows[:1]))
        out += rows[1:]
    return out


def _history(app: dict, st: dict) -> list:
    h = app.get("history") or {}
    items = h.get("items") or []
    out = [CondPageBreak(60 * mm), Paragraph("What already happened near this home", st["h1"])]
    if h.get("summary"):
        out += [Paragraph(plain(" · ".join(h["summary"])) + ".", st["lead"]), Spacer(1, 2 * mm)]
    if items:
        rows = [[Paragraph("DATE", st["cellh"]), Paragraph("WHAT HAPPENED", st["cellh"]),
                 Paragraph("DETAILS", st["cellh"])]]
        for it in items:
            dot = HAZARD.get(it.get("family"), "#8C9586")
            rows.append([Paragraph(plain(nice_date(it.get("date"))), st["cellm"]),
                         Paragraph(f'<font color="{dot}">•</font> {plain(it.get("title"))}', st["cell"]),
                         Paragraph(plain(it.get("detail") or ""), st["cellm"])])
        out.append(_grid(rows, [24 * mm, 70 * mm, WIDTH - 94 * mm]))
    if h.get("note"):
        out += [Spacer(1, 2 * mm), Paragraph(plain(h["note"]), st["muted"])]
    return out


def _about(report: dict, pics: dict, st: dict) -> list:
    loc = report["location"]
    dwelling = report.get("dwelling") or {}
    out = [PageBreak(), Paragraph("About this report", st["h1"]), Paragraph("How to read the levels", st["h3"])]
    t = Table([[Paragraph(name.upper(), st["cellh"]) for name, _ in LEVELS],
               [Paragraph(span, st["cell"]) for _, span in LEVELS]], colWidths=[WIDTH / 5] * 5)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.7, MUTED), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    rule = dwelling.get("rule") or "The home never changes a score: the hazard belongs to the place."
    out += [t, Spacer(1, 2 * mm),
            Paragraph("Each risk takes the score of the worst of the values that describe it. From 20 upwards a "
                      f"risk is worth preparing for and gets its own steps in the action plan. {plain(rule)} Your "
                      "home only changes who acts and what the mapped water means for your floor.", st["body"])]

    facts = [f"{plain(loc.get('label'))}.",
             f"Point analysed: {plain(_coords(loc))}, "
             f"{plain(PRECISION.get(loc.get('precision'), 'at the point found for the address'))}."]
    if loc.get("elevation_m") is not None:
        facts.append(f"Height above sea level: {loc['elevation_m']:.0f} m.")
    if loc.get("ref_catastral"):
        facts.append(f"Cadastral reference: {plain(loc['ref_catastral'])}.")
    if dwelling.get("label"):
        facts.append(f"Home: {plain(dwelling['label'])}.")
    out += [Paragraph("The home", st["h3"]), Paragraph(" ".join(facts), st["body"])]

    credits = [plain(p["caption"]) + "." for p in (pics.get("street"), pics.get("aerial")) if p]
    credits.append("Illustrations: AI-generated images of generic places, chosen by each risk's value. They are "
                   "not this place and not a forecast; they only put the value that chose them into human "
                   "scale.")
    out += [Paragraph("Pictures", st["h3"]), Paragraph(" ".join(credits), st["body"])]

    out.append(Paragraph("Sources", st["h3"]))
    listed = report.get("sources") or []
    sources = [s for s in listed if not any(p in s.get("name", "").lower() for p in PRIVATE_SOURCES)]
    if any("deepfire" in s.get("name", "").lower() for s in listed):
        sources.append({"name": "Satellite fire detections (VIIRS and MODIS hotspots)",
                        "role": "Fires seen by satellite near the point, since 2025"})
    for s in sources:
        line = f"<b>{plain(s['name'])}</b>. {plain(s.get('role'))}."
        if s.get("licence"):
            line += f" Licence: {plain(s['licence'])}."
        if s.get("url"):
            line += f' <a href="{_href(s["url"])}" color="{LINK}">{plain(s["url"])}</a>'
        out += [Paragraph(line, st["small"]), Spacer(1, 1.2 * mm)]

    meta = report.get("meta") or {}
    stamp = ""
    if meta.get("generated_at"):
        stamp = dt.datetime.fromisoformat(meta["generated_at"]).strftime("%d %b %Y, %H:%M UTC")
    out += [Spacer(1, 3 * mm), Paragraph(plain(DISCLAIMER), st["body"]),
            Paragraph(plain(f"Report generated {stamp} by Previous AI {meta.get('version', '')}.".replace("  ", " ")),
                      st["fine"])]
    return out


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
def _numbered_canvas():
    class NumberedCanvas(rl_canvas.Canvas):
        """Writes "Page N of M" once the number of pages is known."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self.setFont(BODY, 7.2)
                self.setFillColor(FAINT)
                self.drawRightString(PAGE_W - MARGIN, FOOT_Y, f"Page {self._pageNumber} of {total}")
                super().showPage()
            super().save()
    return NumberedCanvas


def _wordmark(c, x: float, y: float, size: float, display: str, color) -> None:
    c.setFillColor(color)
    c.setFont(display, size)
    c.drawString(x, y, "Previous")
    c.setFont(BODY, size * 0.38)
    c.drawString(x + pdfmetrics.stringWidth("Previous", display, size) + 1.5, y + size * 0.52, "AI")


def _footer(c) -> None:
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(MARGIN, FOOT_Y + 4 * mm, PAGE_W - MARGIN, FOOT_Y + 4 * mm)
    c.setFont(BODY, 6.8)
    c.setFillColor(FAINT)
    c.drawString(MARGIN, FOOT_Y, DISCLAIMER)


def _first_page(ctx: dict, display: str, c, doc) -> None:
    c.saveState()
    c.setFillColor(BRAND)
    c.rect(0, PAGE_H - BAND_H, PAGE_W, BAND_H, stroke=0, fill=1)
    top = PAGE_H - 15 * mm
    _wordmark(c, MARGIN, top, 21, display, CREAM)
    c.setFont(BODY, 8.8)
    c.setFillColor(CREAM_SOFT)
    c.drawString(MARGIN, top - 6.5 * mm, "Today's awareness. Protect what matters")
    c.setFont(BOLD, 7.2)
    c.setFillColor(CREAM)
    c.drawRightString(PAGE_W - MARGIN, top + 3, "NATURAL HAZARD REPORT")
    c.setFont(BODY, 8.8)
    c.setFillColor(CREAM_SOFT)
    c.drawRightString(PAGE_W - MARGIN, top - 3.5 * mm, ctx["date"])
    c.setFillColor(CREAM)
    c.setFont(display, 24)
    c.drawString(MARGIN, PAGE_H - BAND_H + 16 * mm, ctx["street"])
    c.setFont(BODY, 11)
    c.setFillColor(CREAM_SOFT)
    c.drawString(MARGIN, PAGE_H - BAND_H + 8.5 * mm, ctx["where"])
    c.setFont(BODY, 7.6)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - BAND_H + 8.5 * mm, ctx["coords"])
    _footer(c)
    c.restoreState()


def _later_page(ctx: dict, display: str, c, doc) -> None:
    c.saveState()
    _wordmark(c, MARGIN, PAGE_H - 12 * mm, 11, display, INK)
    c.setFont(BODY, 7.8)
    c.setFillColor(MUTED)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 12 * mm, ctx["title"])
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(MARGIN, PAGE_H - 15 * mm, PAGE_W - MARGIN, PAGE_H - 15 * mm)
    _footer(c)
    c.restoreState()


def render(report: dict, app: dict, pics: dict) -> bytes:
    """The PDF of a report (`build_report`) and its app view (`view.app_view`)."""
    display = display_font()
    st = _styles(display)
    loc = app["location"]
    street = loc.get("name") or loc.get("label") or "This home"
    town = loc.get("town")
    ctx = {
        "street": street,
        "where": safe(" · ".join(x for x in (town, (report.get("dwelling") or {}).get("label")) if x)),
        "title": safe(f"{street}, {town}" if town else street),
        "date": dt.date.today().strftime("%d %B %Y").lstrip("0"),
        "coords": safe(_coords(loc) + (f" · {loc['elevation_m']:.0f} m" if loc.get("elevation_m") is not None else "")),
    }
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                          topMargin=20 * mm, bottomMargin=18 * mm,
                          title=f"Previous AI report · {ctx['title']}", author="Previous AI",
                          subject="Natural hazard report", creator="Previous AI")
    cover = Frame(MARGIN, 18 * mm, WIDTH, PAGE_H - BAND_H - 8 * mm - 18 * mm, id="cover",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    page = Frame(MARGIN, 18 * mm, WIDTH, PAGE_H - 22 * mm - 18 * mm, id="page",
                 leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate("cover", [cover], onPage=partial(_first_page, ctx, display)),
        PageTemplate("page", [page], onPage=partial(_later_page, ctx, display)),
    ])
    story: list = [NextPageTemplate("page")]
    story += _cover(app, pics, st, display)
    story += [PageBreak(), Paragraph("The four risks in detail", st["h1"]),
              Paragraph("Worst first. Each score is the worst of the values below it, and every value names "
                        "its period and its source.", st["lead"]), Spacer(1, 4 * mm)]
    for risk in sorted(app["risks"], key=lambda r: -(r["score"] if r.get("score") is not None else -1)):
        story += _risk(report, risk, st, display)
    story += _ahead(report, st) + _right_now(report, st) + _plan(app, st) + _history(app, st)
    story += _about(report, pics, st)
    doc.build(story, canvasmaker=_numbered_canvas())
    return buf.getvalue()


def filename(app: dict) -> str:
    """"previous-ai-report-carrer-sarriulera-10-vielha.pdf"."""
    label = app["location"].get("label") or "home"
    ascii_label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_label.lower()).strip("-")[:60] or "home"
    return f"previous-ai-report-{slug}.pdf"
