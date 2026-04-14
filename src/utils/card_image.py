"""
Utility pro generování obrázků karet s rámečkem.
Aplikuje rámeček okolo existujícího obrázku karty.
"""

from PIL import Image, ImageOps
import io
import os
import json

# Cesty k datům
FRAMES_FILE = os.path.join(os.path.dirname(__file__), "..", "database", "data", "cards_frames.json")
CARDS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "cards")

def load_json(filepath):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def get_frame_by_id(frame_id):
    frames = load_json(FRAMES_FILE)
    for frame in frames:
        if frame["id"] == frame_id:
            return frame
    return None

def hex_to_rgb(hex_color):
    """Konvertuje hex barvu na RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def apply_frame_to_card(card_image_path: str, frame_id: str = "gold_frame"):
    """
    Aplikuje rámeček na obrázek karty.
    
    Args:
        card_image_path: Cesta k PNG obrázku karty
        frame_id: ID rámečku
    
    Returns:
        BytesIO objekt s PNG obrázkem s rámečkem
    """
    
    # Zkontroluj existenci souboru
    if not os.path.exists(card_image_path):
        raise FileNotFoundError(f"Obrázek karty nenalezen: {card_image_path}")
    
    # Načti frame
    frame = get_frame_by_id(frame_id) or {"color": "#FFD700", "width": 8}
    frame_width = int(frame.get("width", 8))
    frame_color = hex_to_rgb(frame["color"])
    
    # Načti obrázek
    img = Image.open(card_image_path).convert("RGB")
    
    # Aplikuj rámeček pomocí ImageOps.expand
    img_with_frame = ImageOps.expand(img, border=frame_width, fill=frame_color)
    
    # Ulož do BytesIO
    byte_io = io.BytesIO()
    img_with_frame.save(byte_io, format="PNG")
    byte_io.seek(0)
    
    return byte_io

def get_card_image_path(card_id: int):
    """Vrátí cestu k obrázku karty podle ID."""
    # Pokud existuje, vrátí cestu; jinak None
    possible_names = [f"card_{card_id}.png", f"{card_id}.png"]
    for name in possible_names:
        path = os.path.join(CARDS_DIR, name)
        if os.path.exists(path):
            return path
    return None
