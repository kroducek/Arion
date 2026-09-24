"""Bounded, single-play summon animation. No Discord or storage side effects."""
import io
import math
import os
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from src.utils.paths import ASSETS_DIR
from src.core.cards.card_rules import RARITIES

SIZE = (640, 420)
FRAME_MS = 80
MAX_BYTES = 8 * 1024 * 1024
PURPLE = (172, 119, 245)
GOLD = (242, 200, 105)
INK = (12, 13, 25)
RARITY_COLORS = {name: ((data['color'] >> 16) & 255, (data['color'] >> 8) & 255, data['color'] & 255)
                 for name, data in RARITIES.items()}


@lru_cache(maxsize=20)
def font(size, serif=False):
    names = ["DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf"] if serif else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"]
    for directory in [os.path.join(ASSETS_DIR, "fonts"), "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation", "C:/Windows/Fonts"]:
        for name in names + (["georgiab.ttf"] if serif else ["segoeui.ttf"]):
            try:
                return ImageFont.truetype(os.path.join(directory, name), size)
            except OSError:
                pass
    return ImageFont.load_default(size=size)


def label(draw, xy, text, size=16, fill=(239, 231, 218), serif=False):
    draw.text(xy, text, font=font(size, serif), fill=fill, anchor="mm")


@lru_cache(maxsize=48)
def _thumbnail(path, modified):
    with Image.open(path) as source:
        return ImageOps.fit(source.convert("RGB"), (146, 214), method=Image.Resampling.LANCZOS)


def thumbnail(path):
    try:
        return _thumbnail(path, os.stat(path).st_mtime_ns).copy()
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def card_back():
    image = Image.new("RGB", (150, 220), (26, 23, 46))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((1, 1, 148, 218), radius=12, outline=GOLD, width=2)
    d.rounded_rectangle((9, 9, 140, 210), radius=8, outline=(91, 72, 118))
    for y in range(24, 205, 22):
        d.line((15, y, 135, y + 45), fill=(43, 36, 65))
        d.line((135, y, 15, y + 45), fill=(43, 36, 65))
    d.ellipse((34, 69, 116, 151), outline=GOLD, width=2)
    d.polygon([(75, 59), (108, 110), (75, 161), (42, 110)], outline=PURPLE, width=2)
    star = [(75, 77), (82, 101), (104, 110), (82, 117),
            (75, 145), (68, 117), (46, 110), (68, 101)]
    glow = Image.new("RGBA", image.size)
    ImageDraw.Draw(glow).polygon(star, fill=(255, 207, 110, 220))
    image = Image.alpha_composite(image.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(9)))
    d = ImageDraw.Draw(image)
    d.polygon(star, fill=(255, 237, 176), outline=(255, 251, 230), width=2)
    d.ellipse((72, 107, 78, 113), fill=(255, 255, 250))
    label(d, (75, 188), "AURIONIS", 10, GOLD)
    return image.convert("RGB")


def card_front(path):
    art = thumbnail(path) if path else None
    if art is None:
        return card_back()
    image = Image.new("RGB", (150, 220), INK)
    image.paste(art, (2, 3))
    ImageDraw.Draw(image).rounded_rectangle((1, 1, 148, 218), radius=10, outline=GOLD, width=2)
    return image


@lru_cache(maxsize=1)
def night_sky():
    """Stable navy sky and soft nebula, drawn once per process."""
    image = Image.new("RGB", SIZE)
    pixels = image.load()
    for y in range(SIZE[1]):
        for x in range(SIZE[0]):
            cloud = math.exp(-((y - 310 + x * 0.32) / 67) ** 2)
            cloud *= 0.65 + 0.35 * math.sin(x / 105 + y / 130)
            pixels[x, y] = (int(7 + cloud * 18), int(12 + cloud * 13), int(28 + cloud * 38))
    d = ImageDraw.Draw(image)
    rng = random.Random(731)
    for _ in range(160):
        x, y = rng.randrange(23, 617), rng.randrange(20, 397)
        if 125 < x < 515 and y < 116:
            continue
        brightness = rng.randrange(70, 170)
        d.point((x, y), fill=(brightness, brightness, min(255, brightness + 40)))
    return image


def render_opening(card, art_path, roll_paths, *,
                   max_bytes=MAX_BYTES):
    """Return (GIF bytes, playback seconds); raise ValueError above upload budget.

    No loop extension means one play, holding the revealed card at the end.
    Randomness here is cosmetic and never consumes the game's random generator.
    """
    mythic = card.get("rarity") == "mythic"
    rng = random.Random(42)
    back = card_back()
    front = card_front(art_path)
    thumbs = [card_front(path) for path in roll_paths[:8]] or [back]
    particles = [(rng.randrange(24, 616), rng.randrange(90, 365), rng.random()) for _ in range(28)]
    accent = RARITY_COLORS.get(card.get("rarity"), PURPLE)
    duration = 12.0 if mythic else 10.8
    # One palette for the entire clip keeps text/meters from changing colour
    # as different artwork passes through the reel, and speeds up encoding.
    palette_source = Image.new("RGB", (640, 480), INK)
    for i, tile in enumerate([back, front] + thumbs[:6]):
        palette_source.paste(tile.resize((150, 150)), ((i % 4) * 150, (i // 4) * 150))
    pd = ImageDraw.Draw(palette_source)
    for i, shade in enumerate([PURPLE, GOLD, accent, (117, 212, 160), (239, 231, 218), (194, 181, 210), (123, 113, 144)]):
        pd.rectangle((i * 90, 320, i * 90 + 89, 365), fill=shade)
    for y in range(366, 480):
        f = (y - 366) / 114
        pd.line((0, y, 640, y), fill=tuple(int(INK[i] + PURPLE[i] * f * 0.3) for i in range(3)))
    palette_source.paste(night_sky().resize((320, 110)), (320, 370))
    palette = palette_source.quantize(colors=128)
    frames = []
    frame_count = round(duration * 1000 / FRAME_MS)
    for index in range(frame_count):
        t = index * FRAME_MS / 1000
        reveal_at = 9.8 if mythic else 8.6
        reveal = max(0.0, min(1.0, (t - reveal_at) / 0.8))
        color = accent if t >= reveal_at - 0.3 else PURPLE
        image = night_sky().copy()
        d = ImageDraw.Draw(image)
        for i in range(12):
            sx, sy = 34 + (i * 137) % 570, 130 + (i * 83) % 247
            brightness = int(135 + 65 * math.sin(t * 1.4 + i))
            shade = (brightness, brightness, min(255, brightness + 40))
            d.line((sx - 2, sy, sx + 2, sy), fill=shade)
            d.line((sx, sy - 2, sx, sy + 2), fill=shade)
        d.rounded_rectangle((16, 14, 623, 405), radius=16, outline=(65, 52, 84))
        label(d, (320, 37), "A U R I O N I S   /   C A R D S", 12, GOLD)
        if t < 1.04:
            title, subtitle = "Pečeť se probouzí", "Základní bedna"
        elif t < 2.0:
            title, subtitle = "Pečeť se otevírá", "Tvá karta čeká na odhalení"
        elif t < reveal_at:
            title = "Karty se točí"
            subtitle = "Osud vybírá tvou kartu"
        else:
            title = "MYTHIC" if mythic else "Tvá karta přichází"
            subtitle = f"{card.get('rarity', 'uncommon').upper()}  /  {card.get('quality', 'normal').upper()}"
        label(d, (320, 69), title, 27, serif=True)
        label(d, (320, 101), subtitle, 14, color if t >= reveal_at else (166, 157, 185))
        for px, py, phase in particles:
            y = 126 + (py - t * (9 + phase * 12)) % 228
            brightness = 0.3 + 0.5 * abs(math.sin(t * 2 + phase * 6))
            shade = tuple(int(c * brightness) for c in color)
            d.ellipse((px, y, px + 2, y + 2), fill=shade)
        if t < 2:
            pulse = int(8 * math.sin(t * 3))
            d.ellipse((218 - pulse, 135 - pulse, 422 + pulse, 351 + pulse), outline=color, width=2)
            image.paste(back, (245, 133))
        elif t < reveal_at:
            p = min(1, (t - 2) / (reveal_at - 2))
            offset = 7 * 180 * (1 - p) ** 3
            for slot in range(-2, 10):
                x = int(245 + slot * 180 - offset)
                if x < -150 or x > 640:
                    continue
                tile = back if slot == 0 else thumbs[slot % len(thumbs)]
                distance = min(1, abs(x - 245) / 260)
                tile = ImageEnhance.Brightness(tile).enhance(1 - distance * 0.65)
                if distance > 0.3:
                    tile = tile.filter(ImageFilter.GaussianBlur(1.4))
                image.paste(tile, (x, 133))
            d = ImageDraw.Draw(image)
            d.polygon([(312, 120), (328, 120), (320, 130)], fill=GOLD)
            d.polygon([(312, 366), (328, 366), (320, 356)], fill=GOLD)
        else:
            if mythic:
                for ray in range(24):
                    angle = ray * math.pi / 12 + t * 0.12
                    inner, outer = 130, 160 + 18 * math.sin(t * 2 + ray)
                    d.line((320 + math.cos(angle) * inner, 243 + math.sin(angle) * inner * 0.65,
                            320 + math.cos(angle) * outer, 243 + math.sin(angle) * outer * 0.65),
                           fill=(130, 103, 55), width=2)
            for ring in range(4):
                pad = 5 + ring * 4
                shade = tuple(int(c * (0.7 - ring * 0.13)) for c in color)
                d.rounded_rectangle((245 - pad, 133 - pad, 395 + pad, 353 + pad), radius=14, outline=shade, width=2)
            width = max(2, int(150 * abs(math.cos(reveal * math.pi))))
            tile = (back if reveal < 0.5 else front).resize((width, 220), Image.Resampling.LANCZOS)
            image.paste(tile, (320 - width // 2, 133))
            if reveal >= 1 and card.get("quality") in ("excellent", "pristine"):
                overlay = Image.new("RGBA", SIZE)
                od = ImageDraw.Draw(overlay)
                sweep = int(((t - reveal_at - 0.8) / 1.2) * 220)
                shine = (255, 246, 205, 70) if card.get("quality") == "excellent" else (210, 235, 255, 85)
                for x in range(245, 395):
                    for y in range(133, 353):
                        if abs(x - 245 + (y - 133) * 0.22 - sweep) < 9:
                            od.point((x, y), fill=shine)
                image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        d = ImageDraw.Draw(image)
        label(d, (320, 392), "MYTHIC · VZÁCNÝ OBJEV" if mythic and t >= reveal_at else "ARIONCARDS  ·  SBĚRATELSKÉ KARTY", 10, GOLD if mythic else (123, 113, 144))
        frames.append(image.quantize(palette=palette, dither=Image.Dither.NONE))
    output = io.BytesIO()
    frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:],
                   duration=FRAME_MS, optimize=False, disposal=1)
    if output.tell() > max_bytes:
        raise ValueError("Summon animation exceeds attachment budget")
    return output.getvalue(), frame_count * FRAME_MS / 1000
