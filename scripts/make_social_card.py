"""Generate the Open Graph social card served at assets/images/social-card.png.

Run once (or after a brand change):

    uv run python scripts/make_social_card.py

Output is committed, so the deploy does not need Pillow.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "zensical" / "docs" / "assets" / "images" / "social-card.png"

WIDTH, HEIGHT = 1200, 630

# Pulled from zensical.css so the card matches the site's light scheme.
BG = "#fbfbfa"
PANEL = "#f1f2ee"
BORDER = "#d9dbd5"
INK = "#1b1f1a"
MUTED = "#5b625b"
PINE = "#15633d"

TITLE = "Pine Hills Fantasy Football League"
TAGLINE = "The collaborative history of the league, kept by the league."
STATS = [("8", "SEASONS"), ("33", "FRANCHISES"), ("527", "MATCHUPS")]

# macOS system faces; the fallbacks keep this runnable elsewhere.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
]
FONT_CANDIDATES_TEXT = [
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]


def load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    # Pine rule along the top edge.
    draw.rectangle([0, 0, WIDTH, 12], fill=PINE)

    title_font = load_font(FONT_CANDIDATES, 76)
    tagline_font = load_font(FONT_CANDIDATES_TEXT, 34)
    stat_font = load_font(FONT_CANDIDATES, 60)
    cap_font = load_font(FONT_CANDIDATES_TEXT, 22)

    margin = 84
    y = 120

    for line in wrap(draw, TITLE, title_font, WIDTH - margin * 2):
        draw.text((margin, y), line, font=title_font, fill=INK)
        y += 88

    y += 14
    for line in wrap(draw, TAGLINE, tagline_font, WIDTH - margin * 2):
        draw.text((margin, y), line, font=tagline_font, fill=MUTED)
        y += 46

    # Stat cards along the bottom.
    card_w, card_h, gap = 296, 140, 24
    card_y = HEIGHT - margin - card_h
    for index, (value, caption) in enumerate(STATS):
        x = margin + index * (card_w + gap)
        draw.rounded_rectangle(
            [x, card_y, x + card_w, card_y + card_h],
            radius=8,
            fill=PANEL,
            outline=BORDER,
            width=2,
        )
        value_w = draw.textlength(value, font=stat_font)
        draw.text(
            (x + (card_w - value_w) / 2, card_y + 26), value, font=stat_font, fill=PINE
        )
        caption_w = draw.textlength(caption, font=cap_font)
        draw.text(
            (x + (card_w - caption_w) / 2, card_y + 96),
            caption,
            font=cap_font,
            fill=MUTED,
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT, "PNG", optimize=True)
    print(f"[social-card] wrote {OUT.relative_to(REPO)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
