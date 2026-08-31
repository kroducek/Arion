"""
Render sběratelské karty jako jeden obrázek (PIL) — kompaktní náhrada
za roztažené embed fieldy. Staví na stejných blocích jako profilové karty.
"""

import io

from PIL import Image, ImageDraw

from src.logic.profile_render import (
    GOLD,
    GOLD_HARD,
    GREY,
    _base,
    _divider,
    _font,
    _portrait,
    _save,
    _truncate,
    _wrap,
)

W, H = 900, 620
CARD_X, CARD_Y, CARD_W, CARD_H = 44, 58, 360, 504
COL_X = CARD_X + CARD_W + 40
COL_W = W - 44 - COL_X


def _open_image(image) -> Image.Image | None:
    """Přijme cestu, bajty i BytesIO a vrátí RGBA obrázek (None při chybě)."""
    if image is None:
        return None
    try:
        if isinstance(image, (bytes, bytearray)):
            image = io.BytesIO(image)
        return Image.open(image).convert("RGBA")
    except Exception:
        return None


def _chip(d, x, y, text, color, font):
    """Barevná pilulka s raritou / kvalitou. Vrátí šířku."""
    w = int(d.textlength(text, font=font)) + 30
    h = 34
    light = tuple(min(255, c + 70) for c in color)
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=(16, 16, 26, 235),
                        outline=color + (235,), width=2)
    d.text((x + w // 2, y + h // 2), text, font=font, fill=light, anchor="mm")
    return w


def render_card_showcase(image, name, description, accent, chips, rows, unique_id, footer=None):
    """
    Sestaví obrázek karty: velký art vlevo, kompaktní informace vpravo.

    image       — cesta / bajty / BytesIO s artem karty
    accent      — (r, g, b) barva podle rarity
    chips       — [(text, (r, g, b)), …] pilulky pod jménem
    rows        — [(popisek, hodnota), …] řádky detailů
    """
    art = _open_image(image)
    img, d = _base(W, H, accent=accent, tint=accent, bg_portrait=art)
    _portrait(img, art, CARD_X, CARD_Y, CARD_W, CARD_H, r=18, frame=accent)
    d = ImageDraw.Draw(img)

    y = CARD_Y
    name_font = _font(42, serif=True)
    d.text((COL_X, y), _truncate(d, name or "?", name_font, COL_W), font=name_font, fill=GOLD)
    y += 58

    if description:
        for line in _wrap(d, description, _font(20, serif=True), COL_W, max_lines=3):
            d.text((COL_X, y), line, font=_font(20, serif=True), fill=(198, 198, 212))
            y += 27
    y += 12

    if chips:
        chip_font = _font(20)
        cx = COL_X
        for text, color in chips:
            cw = _chip(d, cx, y, text, color, chip_font)
            cx += cw + 10
            if cx > W - 44:
                break
        y += 52

    _divider(d, COL_X, W - 44, y, accent=accent)
    y += 20

    label_font, value_font = _font(19), _font(22, serif=True)
    for label, value in rows:
        d.text((COL_X, y + 3), label, font=label_font, fill=GREY)
        d.text((W - 44, y), _truncate(d, str(value), value_font, COL_W - 150),
               font=value_font, fill=(228, 228, 238), anchor="ra")
        y += 36

    id_font = _font(20)
    id_text = f"ID  {unique_id}"
    id_w = int(d.textlength(id_text, font=id_font)) + 28
    d.rounded_rectangle([COL_X, H - 118, COL_X + id_w, H - 78], radius=12,
                        fill=(18, 18, 28, 255), outline=(120, 90, 40, 180), width=1)
    d.text((COL_X + 14, H - 98), id_text, font=id_font, fill=GOLD_HARD, anchor="lm")

    if footer:
        d.text((COL_X, H - 62), _truncate(d, footer, _font(18), COL_W), font=_font(18), fill=GREY)

    return _save(img)
