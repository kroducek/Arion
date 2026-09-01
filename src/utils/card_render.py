"""Dynamický render sběratelských karet přímo přes čistý artwork."""

import io

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from src.logic.profile_render import _font, _save, _truncate, _wrap

W, H = 1024, 1536
PAD = 62


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


def render_card_showcase(image, name, description, accent, chips, rows, unique_id, footer=None):
    """Vykreslí kompletní vertikální kartu s textem přes artwork."""
    art = _open_image(image)
    if art is None:
        return None

    art = ImageOps.fit(art, (W, H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    art = ImageEnhance.Contrast(art).enhance(1.04)
    canvas = art.copy()

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    panel_top = 900
    for y in range(panel_top, H):
        opacity = int(238 * ((y - panel_top) / (H - panel_top)) ** 0.55)
        shadow_draw.line((0, y, W, y), fill=(5, 8, 16, opacity))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    canvas = Image.alpha_composite(canvas, shadow)
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle(
        (PAD, 55, PAD + 132, 109),
        radius=16,
        fill=(8, 10, 18, 205),
        outline=accent + (255,),
        width=3,
    )
    print_value = next((value for label, value in rows if label == "Tisk"), "#?")
    draw.text((PAD + 66, 82), str(print_value), font=_font(27), fill=(255, 255, 255), anchor="mm")

    y = 1040
    chip_x = PAD
    for text, color in chips:
        chip_x += _chip(draw, chip_x, y, text, color) + 12

    y += 68
    title_font = _fit_name(draw, name or "?", W - 2 * PAD)
    draw.text(
        (PAD, y),
        _truncate(draw, (name or "?").upper(), title_font, W - 2 * PAD),
        font=title_font,
        fill=(255, 245, 218),
        stroke_width=3,
        stroke_fill=(10, 10, 15),
    )
    y += title_font.size + 18

    description_font = _font(25, serif=True)
    for line in _wrap(draw, description, description_font, W - 2 * PAD, max_lines=2):
        draw.text((PAD, y), line, font=description_font, fill=(220, 222, 232))
        y += 34

    y += 18
    detail_rows = [(label, value) for label, value in rows if label not in {"Tisk", "Vytisknuto"}]
    if detail_rows:
        draw.line((PAD, y, W - PAD, y), fill=accent + (180,), width=2)
        y += 18
        label_font = _font(19)
        value_font = _font(21, serif=True)
        for label, value in detail_rows:
            draw.text((PAD, y), label.upper(), font=label_font, fill=(165, 170, 188))
            draw.text(
                (W - PAD, y),
                _truncate(draw, str(value), value_font, 570),
                font=value_font,
                fill=(240, 240, 245),
                anchor="ra",
            )
            y += 32

    id_font = _font(20)
    draw.text((PAD, H - 52), f"ID {unique_id}", font=id_font, fill=(190, 194, 208), anchor="lm")
    if footer:
        draw.text(
            (W - PAD, H - 52),
            _truncate(draw, footer, id_font, 590),
            font=id_font,
            fill=(190, 194, 208),
            anchor="rm",
        )

    draw.rounded_rectangle((18, 18, W - 18, H - 18), radius=28, outline=accent + (255,), width=8)
    return _save(canvas)
