"""Dynamický render sběratelských karet přímo přes čistý artwork."""

import io
import math
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageFont

from src.logic.profile_render import _font as _shared_font, _save, _truncate, _wrap
from src.utils.paths import FRAMES_DIR
from src.core.cards.card_rules import RARITIES, QUALITIES, RARITY_ORDER, QUALITY_ORDER

W, H = 1024, 1536
PAD = 144  # Keep text inside the opening of decorative edge frames.


@lru_cache(maxsize=32)
def _font(size, serif=False):
    font = _shared_font(size, serif=serif)
    if getattr(font, "size", None) == size:
        return font
    # The shared fallback can ignore requested sizes when system fonts are absent.
    try:
        filename = "georgiab.ttf" if serif else "segoeui.ttf"
        return ImageFont.truetype(os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", filename), size)
    except OSError:
        return ImageFont.load_default(size=size)


def _open_image(image):
    if image is None:
        return None
    try:
        if isinstance(image, (bytes, bytearray)):
            image = io.BytesIO(image)
        return Image.open(image).convert("RGBA")
    except Exception:
        return None


def _fit_name(draw, text, max_width):
    for size in range(70, 39, -2):
        font = _font(size, serif=True)
        if draw.textlength(text, font=font) <= max_width:
            return font
    return _font(40, serif=True)


def _chip(draw, x, y, text, color):
    font = _font(22)
    text = text.upper()
    width = int(draw.textlength(text, font=font)) + 34
    draw.rounded_rectangle(
        (x, y, x + width, y + 42),
        radius=21,
        fill=(12, 14, 22, 210),
        outline=color + (255,),
        width=2,
    )
    draw.text((x + width // 2, y + 21), text.upper(), font=font, fill=(245, 245, 248), anchor="mm")
    return width


def _load_frame(frame_id):
    """Load a usable decorative frame, or preserve the default border fallback."""
    if not frame_id:
        return None
    
    frame_path = os.path.join(FRAMES_DIR, f"{frame_id}.png")
    
    # Zkus bez přípony
    if not os.path.exists(frame_path):
        frame_path = os.path.join(FRAMES_DIR, frame_id)
    
    if not os.path.exists(frame_path):
        return None
    
    try:
        frame = Image.open(frame_path).convert("RGBA")
        
        # Zmenši/zvětši frame aby odpovídal kartě (1024×1536)
        if frame.size != (W, H):
            frame = ImageOps.fit(frame, (W, H), method=Image.Resampling.LANCZOS)
        
        return frame
    except Exception:
        return None


def _clip_burned_exterior(canvas, frame):
    """Hide artwork outside the burned rim while keeping its central opening."""
    # Fill between the rim's outer edges on each row. Transparent cracks in
    # the rim cannot accidentally connect the exterior to the central opening.
    barrier = frame.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    mask = Image.new("L", canvas.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    for y in range(H):
        bounds = barrier.crop((0, y, W, y + 1)).getbbox()
        if bounds:
            mask_draw.line((bounds[0], y, bounds[2] - 1, y), fill=255)
    clipped = Image.new("RGBA", canvas.size)
    clipped.paste(canvas, (0, 0), mask)
    return clipped


def render_card_showcase(image, name, description, accent, chips, rows, unique_id, footer=None, frame_id=None):
    """Vykreslí kompletní vertikální kartu s textem přes artwork."""
    art = _open_image(image)
    if art is None:
        return None

    art = ImageOps.fit(art, (W, H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    art = ImageEnhance.Contrast(art).enhance(1.04)
    canvas = art.copy()

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    panel_top = 780
    for y in range(panel_top, H):
        opacity = int(238 * ((y - panel_top) / (H - panel_top)) ** 0.55)
        shadow_draw.line((0, y, W, y), fill=(5, 8, 16, opacity))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    canvas = Image.alpha_composite(canvas, shadow)
    draw = ImageDraw.Draw(canvas)

    print_value = next((value for label, value in rows if label == "Tisk"), "#?")
    content_width = W - 2 * PAD
    title = (name or "?").upper()
    title_font = _fit_name(draw, title, content_width)
    description_font = _font(25, serif=True)
    description_lines = _wrap(draw, description, description_font, content_width, max_lines=2)
    detail_rows = [(label, value) for label, value in rows if label not in {"Tisk", "Vytisknuto"}]
    id_y = H - 180
    content_height = 68 + title_font.size + 18 + len(description_lines) * 34 + 18
    if detail_rows:
        content_height += 18 + len(detail_rows) * 32
    y = min(950, id_y - 40 - content_height)
    # Print belongs with the other badges, away from top/side ornaments.
    badges = [(str(print_value), accent), *chips]
    chip_font = _font(22)
    badge_width = sum(int(draw.textlength(text.upper(), font=chip_font)) + 34 for text, _ in badges)
    badge_width += 12 * (len(badges) - 1)
    chip_x = (W - badge_width) // 2
    for text, color in badges:
        chip_x += _chip(draw, chip_x, y, text, color) + 12

    y += 68
    draw.text(
        (W // 2, y),
        _truncate(draw, title, title_font, content_width),
        font=title_font,
        anchor="ma",
        fill=(255, 245, 218),
        stroke_width=3,
        stroke_fill=(10, 10, 15),
    )
    y += title_font.size + 18

    for line in description_lines:
        draw.text((W // 2, y), line, font=description_font, fill=(220, 222, 232), anchor="ma")
        y += 34

    y += 18
    if detail_rows:
        draw.line((PAD, y, W - PAD, y), fill=accent + (180,), width=2)
        y += 18
        label_font = _font(19)
        value_font = _font(21, serif=True)
        label_width = max(draw.textlength(label.upper(), font=label_font) for label, _ in detail_rows)
        value_width = max(80, content_width - label_width - 32)
        for label, value in detail_rows:
            draw.text((PAD, y), label.upper(), font=label_font, fill=(165, 170, 188))
            draw.text(
                (W - PAD, y),
                _truncate(draw, str(value), value_font, value_width),
                font=value_font,
                fill=(240, 240, 245),
                anchor="ra",
            )
            y += 32

    id_font = _font(20)
    draw.text((W // 2, id_y), f"ID {unique_id}", font=id_font, fill=(190, 194, 208), anchor="mm")
    if footer:
        draw.text(
            (W // 2, id_y + 32),
            _truncate(draw, footer, id_font, content_width),
            font=id_font,
            fill=(190, 194, 208),
            anchor="mm",
        )

    frame = _load_frame(frame_id)
    if frame is None:
        draw.rounded_rectangle((18, 18, W - 18, H - 18), radius=28, outline=accent + (255,), width=8)
    else:
        if os.path.splitext(frame_id)[0] == "burned":
            canvas = _clip_burned_exterior(canvas, frame)
        canvas = Image.alpha_composite(canvas, frame)
    
    return _save(canvas)


# ---------------------------------------------------------------------------
# Album renderer — mřížka karet pro /cards album
# ---------------------------------------------------------------------------

_COLS = 3          # počet karet na řádek
_THUMB_W = 320     # šířka miniaturní karty
_THUMB_H = 480     # výška miniaturní karty
_GAP = 18          # mezera mezi kartami
_HEADER_H = 120    # výška hlavičky alba
_PAD_OUT = 36      # vnější padding vlevo/vpravo
_BORDER_R = 14     # zaoblení rohu jednotlivé miniatury
_QUALITY_ORDER = QUALITY_ORDER
_RARITY_ORDER  = RARITY_ORDER


def _quality_key(q: str) -> int:
    try:
        return _QUALITY_ORDER.index(q)
    except ValueError:
        return len(_QUALITY_ORDER)


def _rarity_key(r: str) -> int:
    try:
        return _RARITY_ORDER.index(r)
    except ValueError:
        return len(_RARITY_ORDER)


def _rarity_color(rarity: str) -> tuple:
    """Vrátí RGB barvu podle rarity."""
    color = RARITIES.get(rarity, {"color": 0x787878})["color"]
    return ((color >> 16) & 255, (color >> 8) & 255, color & 255)


def _quality_label(quality: str) -> str:
    data = QUALITIES.get(quality)
    return f"{data['emoji']} {data['name']}" if data else quality.capitalize()


def _draw_nocard_thumb(nocard_path: str | None) -> Image.Image:
    """Vykreslí placeholder miniaturu pro nevlastněnou kartu."""
    thumb = Image.new("RGBA", (_THUMB_W, _THUMB_H), (14, 14, 22, 255))
    draw = ImageDraw.Draw(thumb)

    # Tmavý gradient
    for y in range(_THUMB_H):
        t = y / _THUMB_H
        c = int(18 + 10 * t)
        draw.line([(0, y), (_THUMB_W, y)], fill=(c, c, c + 8, 255))

    # Rámeček
    draw.rounded_rectangle(
        (4, 4, _THUMB_W - 4, _THUMB_H - 4),
        radius=_BORDER_R,
        outline=(55, 55, 75, 255),
        width=3,
    )

    # Pokud máme nocard.png, použijeme ho jako základ
    if nocard_path and os.path.exists(nocard_path):
        try:
            nc = Image.open(nocard_path).convert("RGBA")
            nc = nc.resize((_THUMB_W, _THUMB_H), Image.Resampling.LANCZOS)
            # Ztmav ho trochu
            from PIL import ImageEnhance
            nc = ImageEnhance.Brightness(nc).enhance(0.85)
            thumb.alpha_composite(nc)
            return thumb
        except Exception:
            pass

    # Fallback — malovaný placeholder
    cx, cy = _THUMB_W // 2, _THUMB_H // 2

    # Velký otazník
    q_font = _font(180, serif=True)
    draw.text((cx, cy - 40), "?", font=q_font, fill=(50, 50, 68, 255), anchor="mm")
    draw.text((cx, cy - 40), "?", font=q_font, fill=(70, 70, 95, 200), anchor="mm")

    # ???? dole
    s_font = _font(38)
    draw.text((cx, cy + 150), "????", font=s_font, fill=(75, 75, 100, 255), anchor="mm")

    return thumb


def _draw_card_thumb(art_path: str, rarity: str, quality: str, name: str) -> Image.Image:
    """Vykreslí miniaturu pro vlastněnou kartu s art + barevným okrajem."""
    rarity_col = _rarity_color(rarity)

    # Základ z artworku
    art = _open_image(art_path)
    if art:
        thumb = ImageOps.fit(art, (_THUMB_W, _THUMB_H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.3))
        thumb = ImageEnhance.Contrast(thumb).enhance(1.05)
    else:
        thumb = Image.new("RGBA", (_THUMB_W, _THUMB_H), (20, 20, 30, 255))

    draw = ImageDraw.Draw(thumb)

    # Spodní gradient — tmavý přechod pro text
    shadow = Image.new("RGBA", (_THUMB_W, _THUMB_H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    panel_top = int(_THUMB_H * 0.60)
    for y in range(panel_top, _THUMB_H):
        opacity = int(220 * ((y - panel_top) / (_THUMB_H - panel_top)) ** 0.5)
        sd.line([(0, y), (_THUMB_W, y)], fill=(5, 8, 16, opacity))
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    thumb = Image.alpha_composite(thumb, shadow)
    draw = ImageDraw.Draw(thumb)

    # Jméno karty (zkrácené)
    name_font = _font(22, serif=True)
    max_w = _THUMB_W - 16
    name_text = name or "?"
    while draw.textlength(name_text, font=name_font) > max_w and len(name_text) > 3:
        name_text = name_text[:-1]
    if name_text != name:
        name_text = name_text.rstrip() + "…"
    draw.text((_THUMB_W // 2, _THUMB_H - 52), name_text, font=name_font, fill=(245, 240, 220), anchor="mm",
              stroke_width=2, stroke_fill=(5, 5, 10))

    # Kvalita / rarita chip dole
    qual_font = _font(17)
    qual_text = _quality_label(quality)
    draw.text((_THUMB_W // 2, _THUMB_H - 24), qual_text, font=qual_font, fill=rarity_col, anchor="mm",
              stroke_width=1, stroke_fill=(5, 5, 10))

    # Barevný rámeček podle rarity
    border_w = 4
    draw.rounded_rectangle(
        (border_w // 2, border_w // 2, _THUMB_W - border_w // 2, _THUMB_H - border_w // 2),
        radius=_BORDER_R,
        outline=rarity_col + (255,),
        width=border_w,
    )

    return thumb


def render_album_grid(
    collection_name: str,
    collection_emoji: str,
    collection_desc: str,
    collection_color: tuple,  # RGB
    cards: list,              # list of (template_dict, best_instance_or_None)
    nocard_path: str | None = None,
) -> io.BytesIO:
    """
    Vykreslí kompletní PNG album kolekce jako mřížku karet.

    Args:
        collection_name:  Název kolekce (např. "Chosen")
        collection_emoji: Emoji kolekce
        collection_desc:  Popis kolekce
        collection_color: (r, g, b) barva kolekce
        cards:            Seřazený seznam (šablona, nejlepší_instance|None)
        nocard_path:      Cesta k nocard.png (volitelné)

    Returns:
        BytesIO s PNG.
    """
    n = len(cards)
    cols = min(_COLS, n) if n > 0 else 1
    rows = max(1, math.ceil(n / cols))

    total_w = _PAD_OUT * 2 + cols * _THUMB_W + (cols - 1) * _GAP
    total_h = _HEADER_H + _PAD_OUT + rows * (_THUMB_H + _GAP) + _PAD_OUT

    # Tmavé pozadí s barevným tónováním kolekce
    bg = Image.new("RGBA", (total_w, total_h), (12, 12, 20, 255))
    bg_draw = ImageDraw.Draw(bg)
    r0, g0, b0 = collection_color
    for y in range(total_h):
        t = y / total_h
        bg_draw.line(
            [(0, y), (total_w, y)],
            fill=(
                int(12 + r0 * 0.06 * (1 - t)),
                int(12 + g0 * 0.06 * (1 - t)),
                int(20 + b0 * 0.06 * (1 - t)),
                255,
            ),
        )

    # ── Header ──────────────────────────────────────────────────────────────
    owned = sum(1 for _, inst in cards if inst is not None)
    title = f"{collection_emoji}  {collection_name.capitalize()}  •  {owned}/{n}"

    title_font = _font(42, serif=True)
    desc_font  = _font(22, serif=True)

    bg_draw.text((_PAD_OUT, 28), title, font=title_font, fill=(245, 238, 210))
    bg_draw.text((_PAD_OUT, 80), collection_desc, font=desc_font, fill=(160, 160, 175))

    # Thin divider pod headerem
    bg_draw.line(
        [(_PAD_OUT, _HEADER_H - 8), (total_w - _PAD_OUT, _HEADER_H - 8)],
        fill=collection_color + (140,),
        width=2,
    )

    # ── Karta po kartě ───────────────────────────────────────────────────────
    for i, (template, instance) in enumerate(cards):
        col_i = i % cols
        row_i = i // cols
        x = _PAD_OUT + col_i * (_THUMB_W + _GAP)
        y = _HEADER_H + _PAD_OUT + row_i * (_THUMB_H + _GAP)

        if instance is not None:
            art_filename = instance.get("image") or template.get("image")
            art_path = None
            if art_filename:
                candidate = os.path.join(os.path.dirname(nocard_path or __file__), art_filename) if nocard_path else None
                # Fallback — sestavíme cestu z CARDS_DIR (resolveno dynamicky)
                from src.utils.paths import CARDS_DIR
                art_path = os.path.join(CARDS_DIR, art_filename) if art_filename else None
                if art_path and not os.path.exists(art_path):
                    art_path = None

            thumb = _draw_card_thumb(
                art_path,
                instance.get("rarity", "uncommon"),
                instance.get("quality", "normal"),
                instance.get("name") or template.get("name", "?"),
            )
        else:
            thumb = _draw_nocard_thumb(nocard_path)

        bg.paste(thumb, (x, y), thumb)

    # Vnější rámeček celého alba
    bg_draw.rounded_rectangle(
        (6, 6, total_w - 6, total_h - 6),
        radius=20,
        outline=collection_color + (180,),
        width=4,
    )

    return _save(bg)
