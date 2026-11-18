#!/usr/bin/env python3
"""Draw the window and taskbar icon of every SurveyPlatform app.

    py -3 pipelines/common/make_app_icons.py

Writes, for each key in ``brand.APP_ICONS``, into ``pipelines/common/icons/``:

    <key>.ico                 16-256 px, for Windows and the PyInstaller EXEs
    <key>_16.png ... _256.png for Tk's iconphoto

and ``contact_sheet.png``, every icon side by side at each size.

The icons share one look: a rounded Normington Petts tile with a white glyph
and a light-blue accent. Glyphs are drawn on a 16-unit grid, so at 16 px and
32 px every straight edge lands on a whole pixel and stays sharp.
Needs Pillow.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import brand  # noqa: E402

ICON_DIR = HERE / "icons"
PNG_SIZES = (16, 32, 48, 256)
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SUPERSAMPLE = 8

WHITE = (255, 255, 255, 255)
ACCENT = "#9CCBF2"  # light Normington blue, for the second part of a glyph
SKY = "#2E7BBF"  # Normington blue lifted, so neighbouring tiles differ

# key -> (tile colour, label on the contact sheet)
TILES: dict[str, tuple[str, str]] = {
    "launcher": (brand.BLUE, "Survey Launcher"),
    "wincross": (brand.DEEP_BLUE, "WinCross Table Gen"),
    "table_merger": (SKY, "Table Merger"),
    "open_end_coder": (brand.GREY, "Open-End Coder"),
    "oe_codebook": (brand.INK, "OE Codebook Editor"),
    "quota_checker": (brand.DEEP_BLUE, "Sample Quota Checker"),
    "weighting": (brand.GREY, "Sample Weighting"),
    "trend_table_updater": (SKY, "Trend Table Updater"),
    "auto_results": (brand.INK, "Auto Results"),
    "tomas": (SKY, "TOMAS"),
    "dashboard": (brand.INK, "Repository Dashboard"),
    "question_browser": (brand.GREY, "Question Browser"),
    "survey_writer": (brand.BLUE, "Survey Writer"),
}


def _rgb(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _shade(colour: str, factor: float) -> tuple[int, int, int, int]:
    """Lighter (factor > 0) or darker (factor < 0) version of a colour."""
    r, g, b = _rgb(colour)
    if factor >= 0:
        r, g, b = (round(c + (255 - c) * factor) for c in (r, g, b))
    else:
        r, g, b = (round(c * (1 + factor)) for c in (r, g, b))
    return (r, g, b, 255)


class Pen:
    """Draws in 16-unit grid coordinates on a supersampled canvas."""

    def __init__(self, image: Image.Image, unit: float, tile: str) -> None:
        self.draw = ImageDraw.Draw(image)
        self.u = unit
        self.tile = _shade(tile, 0)
        self.accent = ACCENT

    def _box(self, x0, y0, x1, y1):
        u = self.u
        return (x0 * u, y0 * u, x1 * u - 1, y1 * u - 1)

    def rect(self, x0, y0, x1, y1, fill=WHITE, radius=0.0):
        """Filled rectangle covering grid cells [x0, x1) x [y0, y1)."""
        if radius:
            self.draw.rounded_rectangle(self._box(x0, y0, x1, y1), radius=radius * self.u, fill=fill)
        else:
            self.draw.rectangle(self._box(x0, y0, x1, y1), fill=fill)

    def hole(self, x0, y0, x1, y1):
        self.rect(x0, y0, x1, y1, fill=self.tile)

    def poly(self, points, fill=WHITE):
        self.draw.polygon([(x * self.u, y * self.u) for x, y in points], fill=fill)

    def line(self, points, width=1.0, fill=WHITE):
        pts = [(x * self.u, y * self.u) for x, y in points]
        self.draw.line(pts, fill=fill, width=max(1, round(width * self.u)), joint="curve")
        r = width * self.u / 2  # round the ends
        for x, y in (pts[0], pts[-1]):
            self.draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)

    def ellipse(self, x0, y0, x1, y1, fill=WHITE, outline=None, width=0.0):
        self.draw.ellipse((x0 * self.u, y0 * self.u, x1 * self.u, y1 * self.u), fill=fill,
                          outline=outline, width=round(width * self.u) if outline else 0)

    def pie(self, x0, y0, x1, y1, start, end, fill=WHITE):
        self.draw.pieslice((x0 * self.u, y0 * self.u, x1 * self.u, y1 * self.u), start, end, fill=fill)

    def arc(self, x0, y0, x1, y1, start, end, width=1.0, fill=WHITE):
        self.draw.arc((x0 * self.u, y0 * self.u, x1 * self.u, y1 * self.u), start, end, fill=fill,
                      width=max(1, round(width * self.u)))


# ---- glyphs: one per app, drawn inside the 16-unit tile ---------------------------------

def glyph_launcher(p: Pen) -> None:
    """Four app tiles: the hub that opens the others."""
    p.rect(3, 3, 7, 7, radius=0.8)
    p.rect(9, 3, 13, 7, radius=0.8)
    p.rect(3, 9, 7, 13, radius=0.8)
    p.rect(9, 9, 13, 13, fill=p.accent, radius=0.8)


def glyph_wincross(p: Pen) -> None:
    """A crosstab: solid header row over a grid of cells."""
    p.rect(2, 3, 14, 13)
    p.rect(2, 3, 14, 6, fill=p.accent)
    for x0, x1 in ((3, 6), (7, 13)):
        for y0, y1 in ((6, 9), (10, 12)):
            p.hole(x0, y0, x1, y1)


def glyph_table_merger(p: Pen) -> None:
    """Two sheets flowing into one."""
    p.line([(2.5, 4), (5.5, 4), (8.5, 8)], width=2)
    p.line([(2.5, 12), (5.5, 12), (8.5, 8)], width=2, fill=p.accent)
    p.line([(8.5, 8), (10.5, 8)], width=2)
    p.poly([(10, 4.5), (14, 8), (10, 11.5)])


def glyph_open_end_coder(p: Pen) -> None:
    """A speech bubble (a verbatim) with a code tag on it."""
    p.rect(2, 3, 14, 11, radius=2)
    p.poly([(4, 10), (8, 10), (4, 14)])
    p.hole(4, 5, 12, 6)
    p.hole(4, 8, 9, 9)
    p.rect(10, 7, 13, 10, fill=p.accent, radius=0.5)


def glyph_oe_codebook(p: Pen) -> None:
    """An open book: the code list."""
    p.poly([(1.5, 4), (7.5, 5), (7.5, 13.5), (1.5, 12.5)])
    p.poly([(8.5, 5), (14.5, 4), (14.5, 12.5), (8.5, 13.5)])
    p.rect(7.5, 4.5, 8.5, 13.5, fill=p.accent)
    p.line([(3, 7), (6, 7.5)], width=0.9, fill=p.tile)
    p.line([(10, 7.5), (13, 7)], width=0.9, fill=p.tile)
    p.line([(3, 9.5), (6, 10)], width=0.9, fill=p.tile)
    p.line([(10, 10), (13, 9.5)], width=0.9, fill=p.tile)


def glyph_quota_checker(p: Pen) -> None:
    """Bars against a quota line, with a tick."""
    p.rect(2, 3, 9, 5)
    p.rect(2, 7, 12, 9)
    p.rect(2, 11, 7, 13)
    p.rect(10, 2, 11, 14, fill=p.accent)


def glyph_weighting(p: Pen) -> None:
    """A balance scale."""
    p.rect(7, 4, 9, 13)
    p.rect(4, 12, 12, 14, radius=0.5)
    p.rect(2, 4, 14, 5.5, radius=0.5)
    p.ellipse(6.5, 1.5, 9.5, 4.5)
    for cx, fill in ((4, WHITE), (12, p.accent)):
        p.line([(cx, 5), (cx - 2.2, 9)], width=0.8, fill=fill)
        p.line([(cx, 5), (cx + 2.2, 9)], width=0.8, fill=fill)
        p.pie(cx - 3, 6.5, cx + 3, 11.5, 0, 180, fill=fill)


def glyph_trend_table_updater(p: Pen) -> None:
    """A rising trend line on chart axes."""
    p.rect(2, 2, 3.5, 14, fill=p.accent)
    p.rect(2, 12.5, 14, 14, fill=p.accent)
    p.line([(4.5, 10.5), (7, 7.5), (9, 9), (12, 5)], width=2)
    p.poly([(9.8, 3.6), (14, 2.5), (13, 6.7)])


def glyph_auto_results(p: Pen) -> None:
    """A report page filling itself in: page, folded corner, lightning bolt."""
    p.poly([(3, 1.5), (10, 1.5), (13.5, 5), (13.5, 14.5), (3, 14.5)])
    p.poly([(10, 1.5), (10, 5), (13.5, 5)], fill=p.accent)
    p.poly([(9.5, 4), (5, 9.5), (8, 9.5), (6.5, 13.5), (11.5, 7.5), (8.5, 7.5), (10, 4)], fill=p.tile)


def glyph_tomas(p: Pen) -> None:
    """A globe: the Spanish translation."""
    p.ellipse(1.5, 1.5, 14.5, 14.5, fill=None, outline=WHITE, width=1.6)
    p.ellipse(5, 1.5, 11, 14.5, fill=None, outline=p.accent, width=1.4)
    p.rect(2, 7.3, 14, 8.7)


def glyph_dashboard(p: Pen) -> None:
    """A database drum: the question repository."""
    p.rect(3, 3.5, 13, 12.5)
    p.ellipse(3, 10.5, 13, 14.5)
    p.ellipse(3, 1.5, 13, 5.5, fill=p.accent)
    p.arc(3, 4.5, 13, 8.5, 0, 180, width=1, fill=p.tile)
    p.arc(3, 7.5, 13, 11.5, 0, 180, width=1, fill=p.tile)


def glyph_question_browser(p: Pen) -> None:
    """A magnifying glass over the question list."""
    p.ellipse(1.5, 1.5, 11.5, 11.5, fill=p.accent)
    p.ellipse(3.5, 3.5, 9.5, 9.5, fill=p.tile)
    p.line([(9.8, 9.8), (13.5, 13.5)], width=2.6)


def glyph_survey_writer(p: Pen) -> None:
    """A pencil: writing the questionnaire."""
    p.rect(2, 13, 9, 14.5, fill=p.accent)
    p.poly([(3, 10), (10.5, 2.5), (13.5, 5.5), (6, 13)])
    p.poly([(3, 10), (6, 13), (1.8, 14.2)])
    p.poly([(2.4, 12.4), (3.6, 13.6), (1.8, 14.2)], fill=p.tile)
    p.poly([(10.5, 2.5), (11.5, 1.5), (14.5, 4.5), (13.5, 5.5)], fill=p.accent)


GLYPHS = {
    "launcher": glyph_launcher,
    "wincross": glyph_wincross,
    "table_merger": glyph_table_merger,
    "open_end_coder": glyph_open_end_coder,
    "oe_codebook": glyph_oe_codebook,
    "quota_checker": glyph_quota_checker,
    "weighting": glyph_weighting,
    "trend_table_updater": glyph_trend_table_updater,
    "auto_results": glyph_auto_results,
    "tomas": glyph_tomas,
    "dashboard": glyph_dashboard,
    "question_browser": glyph_question_browser,
    "survey_writer": glyph_survey_writer,
}


def render(key: str, size: int) -> Image.Image:
    """One icon at one size."""
    tile, _label = TILES[key]
    canvas = size * SUPERSAMPLE
    unit = canvas / 16
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # Tile: rounded square, a shade lighter at the top, with a darker rim.
    radius = 3 * unit
    draw.rounded_rectangle((0, 0, canvas - 1, canvas - 1), radius=radius, fill=_shade(tile, -0.25))
    inset = SUPERSAMPLE * max(1, size // 64) if size >= 32 else 0  # 1-4 px rim
    body = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    top, bottom = _shade(tile, 0.12), _shade(tile, 0)
    for y in range(canvas):
        t = y / (canvas - 1)
        ImageDraw.Draw(body).line([(0, y), (canvas, y)],
                                  fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    mask = Image.new("L", (canvas, canvas), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset, inset, canvas - 1 - inset, canvas - 1 - inset), radius=radius - inset, fill=255)
    image.paste(body, (0, 0), mask)
    pen = Pen(image, unit, tile)
    pen.tile = _shade(tile, 0.05)  # holes match the tile's mid gradient
    GLYPHS[key](pen)
    return image.reduce(SUPERSAMPLE)


def contact_sheet(path: Path) -> None:
    """Every icon at 256 px with its small sizes, then strips as a title bar and taskbar show them."""
    keys = list(brand.APP_ICONS)
    pad, cell_w, cols = 24, 300, 5
    cell_h = 160 + 30 + 64 + 30
    rows = math.ceil(len(keys) / cols)
    strip_h = 2 * 60 + 40
    width = cols * cell_w + pad
    sheet = Image.new("RGB", (width, 70 + rows * cell_h + strip_h + pad), brand.BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    try:
        title_font = ImageFont.truetype("segoeuib.ttf", 22)
        font = ImageFont.truetype("segoeui.ttf", 15)
        small = ImageFont.truetype("segoeui.ttf", 12)
    except OSError:
        title_font = font = small = ImageFont.load_default()
    draw.text((pad, 20), "SurveyPlatform app icons", fill=brand.BLUE, font=title_font)
    draw.text((pad + 300, 28), "160 px preview; below it 48, 32 and 16 px at actual size, "
              "and 16 px blown up 4x to show the pixels", fill=brand.GREY, font=small)
    for i, key in enumerate(keys):
        x = pad + (i % cols) * cell_w
        y = 70 + (i // cols) * cell_h
        big = render(key, 256).resize((160, 160), Image.LANCZOS)
        sheet.paste(big, (x, y), big)
        draw.text((x, y + 166), TILES[key][1], fill=brand.INK, font=font)
        draw.text((x + 175, y + 4), key, fill=brand.GREY, font=small)
        sx, base = x, y + 194 + 64
        for size in (48, 32, 16):
            icon = render(key, size)
            sheet.paste(icon, (sx, base - size), icon)
            sx += size + 12
        zoom = render(key, 16).resize((64, 64), Image.NEAREST)
        sheet.paste(zoom, (sx + 8, base - 64), zoom)
    # A light title-bar strip at 16 px and a dark taskbar strip at 32 px.
    y = 70 + rows * cell_h + 10
    draw.rectangle((pad, y, width - pad, y + 40), fill=brand.WHITE, outline="#C9D3DE")
    sx = pad + 12
    for key in keys:
        icon = render(key, 16)
        sheet.paste(icon, (sx, y + 12), icon)
        sx += 16 + 22
    draw.text((sx + 10, y + 11), "title bars, 16 px", fill=brand.GREY, font=small)
    y += 56
    draw.rectangle((pad, y, width - pad, y + 56), fill="#202020")
    sx = pad + 12
    for key in keys:
        icon = render(key, 32)
        sheet.paste(icon, (sx, y + 12), icon)
        sx += 32 + 18
    draw.text((sx + 10, y + 20), "taskbar, 32 px", fill="#BBBBBB", font=small)
    sheet.save(path)


def main() -> int:
    missing = set(brand.APP_ICONS) ^ set(GLYPHS)
    if missing:
        raise SystemExit(f"brand.APP_ICONS and GLYPHS disagree on: {sorted(missing)}")
    ICON_DIR.mkdir(exist_ok=True)
    for key in brand.APP_ICONS:
        images = {size: render(key, size) for size in ICO_SIZES}
        for size in PNG_SIZES:
            images[size].save(ICON_DIR / f"{key}_{size}.png", optimize=True)
        images[256].save(ICON_DIR / f"{key}.ico", sizes=[(s, s) for s in ICO_SIZES],
                         append_images=[images[s] for s in ICO_SIZES if s != 256])
    contact_sheet(ICON_DIR / "contact_sheet.png")
    print(f"Wrote {len(brand.APP_ICONS)} icons to {ICON_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
