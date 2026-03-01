"""
dice_image.py — pomocný modul pro generování obrázku kostek
Používá Pillow (pip install Pillow).

Struktura složky:
    assets/dice/d1.png
    assets/dice/d2.png
    ...
    assets/dice/d6.png

Obrázky by měly být čtvercové (doporučeno 100x100 nebo 120x120 px).
"""

import io
import os
from PIL import Image

# ── KONFIGURACE ───────────────────────────────────────────────────────────────

ASSETS_DIR  = os.path.join(os.path.dirname(__file__), "..", "assets", "dice")
DICE_SIZE   = 100    # px — každá kostka se rescaluje na tuto velikost
PADDING     = 12     # px — mezera mezi kostkami
BG_COLOR    = (47, 49, 54, 0)   # průhledné pozadí (RGBA)


def _load_die(face: int) -> Image.Image:
    """Načte obrázek kostky pro danou hodnotu (1–6) a rescaluje ho."""
    path = os.path.join(ASSETS_DIR, f"d{face}.png")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Obrázek kostky nenalezen: {path}")
    img = Image.open(path).convert("RGBA")
    img = img.resize((DICE_SIZE, DICE_SIZE), Image.LANCZOS)
    return img


def build_dice_image(dice: list[int]) -> io.BytesIO:
    """
    Složí obrázky kostek do jednoho PNG v řadě.

    Args:
        dice: seznam hodnot kostek, např. [1, 3, 3, 5, 6, 2]

    Returns:
        BytesIO objekt připravený pro discord.File()
    """
    if not dice:
        raise ValueError("Prázdný seznam kostek.")

    n       = len(dice)
    width   = n * DICE_SIZE + (n - 1) * PADDING
    height  = DICE_SIZE

    canvas = Image.new("RGBA", (width, height), BG_COLOR)

    for i, face in enumerate(dice):
        die_img = _load_die(face)
        x = i * (DICE_SIZE + PADDING)
        canvas.paste(die_img, (x, 0), die_img)   # die_img jako maska (průhlednost)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return buf