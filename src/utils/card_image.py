"""
Utility pro aplikování rámečku na obrázky karet.
Vezme PNG obrázek karty a PNG obrázek rámečku a spojí je.
"""

from PIL import Image
import io
import os
import json

# Cesty k datům
FRAMES_FILE = os.path.join(os.path.dirname(__file__), "..", "database", "data", "cards_frames.json")
FRAMES_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "frames")
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

def apply_frame_to_card(card_image_path: str, frame_id: str = None):
    """
    Aplikuje rámeček na kartu kombinací card image + frame image.
    
    Args:
        card_image_path: Cesta k PNG obrázku karty
        frame_id: ID rámečku (pokud None, vrátí jen kartu)
    
    Returns:
        BytesIO objekt s PNG obrázkem
    """
    
    # Zkontroluj existenci karty
    if not os.path.exists(card_image_path):
        raise FileNotFoundError(f"Obrázek karty nenalezen: {card_image_path}")
    
    # Pokud není frame_id, vrátí jen kartu
    if not frame_id or frame_id == "default":
        img = Image.open(card_image_path).convert("RGB")
        byte_io = io.BytesIO()
        img.save(byte_io, format="PNG")
        byte_io.seek(0)
        return byte_io
    
    # Načti frame info
    frame = get_frame_by_id(frame_id)
    if not frame or "image" not in frame:
        # Fallback: vrátí jen kartu
        img = Image.open(card_image_path).convert("RGB")
        byte_io = io.BytesIO()
        img.save(byte_io, format="PNG")
        byte_io.seek(0)
        return byte_io
    
    # Pojď aplikovat frame image
    frame_image_path = os.path.join(FRAMES_DIR, frame["image"])
    if not os.path.exists(frame_image_path):
        # Fallback: vrátí jen kartu
        img = Image.open(card_image_path).convert("RGB")
        byte_io = io.BytesIO()
        img.save(byte_io, format="PNG")
        byte_io.seek(0)
        return byte_io
    
    try:
        card_img = Image.open(card_image_path).convert("RGBA")
        frame_img = Image.open(frame_image_path).convert("RGBA")
        
        # Zmenšuj/zvětšuj frame aby odpovídal kartě
        frame_img = frame_img.resize(card_img.size, Image.Resampling.LANCZOS)
        
        # Vytvořuj nový obrázek s frame jako overlay
        result = Image.new("RGBA", card_img.size, (0, 0, 0, 0))
        result.paste(card_img, (0, 0), card_img)
        result.paste(frame_img, (0, 0), frame_img)
        
        # Převeď na RGB pro Discord
        rgb_result = Image.new("RGB", result.size, (255, 255, 255))
        rgb_result.paste(result, mask=result.split()[3])
        
        byte_io = io.BytesIO()
        rgb_result.save(byte_io, format="PNG")
        byte_io.seek(0)
        return byte_io
    except Exception:
        # Fallback na jen kartu
        img = Image.open(card_image_path).convert("RGB")
        byte_io = io.BytesIO()
        img.save(byte_io, format="PNG")
        byte_io.seek(0)
        return byte_io

def get_card_image_path(card_id: int):
    """Vrátí cestu k obrázku karty podle ID."""
    possible_names = [f"{card_id}.png", f"card_{card_id}.png"]
    for name in possible_names:
        path = os.path.join(CARDS_DIR, name)
        if os.path.exists(path):
            return path
    return None
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
