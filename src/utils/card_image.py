"""
Utility pro aplikování rámečku na obrázky karet.
Překrývá PNG rámečka na kartu.
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
    """Čte JSON soubor a automaticky inicializuje prázdné frames."""
    if not os.path.exists(filepath):
        if filepath.endswith("cards_frames.json"):
            ensure_frames_data(filepath)
            return load_json(filepath)
        return []
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not data and filepath.endswith("cards_frames.json"):
                ensure_frames_data(filepath)
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            return data
    except Exception:
        if filepath.endswith("cards_frames.json"):
            ensure_frames_data(filepath)
            return load_json(filepath)
        return []

def ensure_frames_data(filepath):
    """Zajistí, aby cards_frames.json obsahoval alespoň Riddler."""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            default_frames = [
                {
                    "id": "riddler_frame",
                    "name": "Riddler Rámeček",
                    "image": "riddler-frame.png",
                    "color": "#FF6B9D",
                    "rarity_exclusive": None
                }
            ]
            json.dump(default_frames, f, indent=4, ensure_ascii=False)
    except Exception:
        pass

def get_frame_by_id(frame_id):
    """Vrátí data rámečku podle ID."""
    frames = load_json(FRAMES_FILE)
    for frame in frames:
        if frame.get("id") == frame_id:
            return frame
    return None

def apply_frame_to_card(card_image_path: str, frame_id: str = None):
    """
    Aplikuje PNG rámeček na kartu.
    
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
    
    # Cesta k frame PNG
    frame_image_path = os.path.join(FRAMES_DIR, frame.get("image"))
    if not os.path.exists(frame_image_path):
        # Asset soubor neexistuje - fallback na kartu
        img = Image.open(card_image_path).convert("RGB")
        byte_io = io.BytesIO()
        img.save(byte_io, format="PNG")
        byte_io.seek(0)
        return byte_io
    
    try:
        # Otevři kartu a frame
        card_img = Image.open(card_image_path).convert("RGBA")
        frame_img = Image.open(frame_image_path).convert("RGBA")
        
        # Pokud frame není stejné velikosti, resize na velikost karty
        if frame_img.size != card_img.size:
            frame_img = frame_img.resize(card_img.size, Image.Resampling.LANCZOS)
        
        # Aplikuj frame jako overlay na kartu
        result = Image.new("RGBA", card_img.size, (0, 0, 0, 0))
        result.paste(card_img, (0, 0), card_img)
        result.paste(frame_img, (0, 0), frame_img)
        
        # Převeď na RGB pro Discord
        rgb_result = Image.new("RGB", result.size, (255, 255, 255))
        rgb_result.paste(result, mask=result.split()[3])
        
        # Ulož do BytesIO
        byte_io = io.BytesIO()
        rgb_result.save(byte_io, format="PNG")
        byte_io.seek(0)
        return byte_io
    except Exception:
        # Jakákoli chyba → fallback na jen kartu
        img = Image.open(card_image_path).convert("RGB")
        byte_io = io.BytesIO()
        img.save(byte_io, format="PNG")
        byte_io.seek(0)
        return byte_io

def get_card_image_path(image_filename: str):
    """Vrátí cestu k obrázku karty podle jména souboru."""
    if not image_filename:
        return None
    path = os.path.join(CARDS_DIR, image_filename)
    if os.path.exists(path):
        return path
    return None
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
    """Čte JSON soubor a automaticky inicializuje prázdné frames."""
    if not os.path.exists(filepath):
        if filepath.endswith("cards_frames.json"):
            ensure_frames_data(filepath)
            return load_json(filepath)
        return []
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Pokud je soubor prázdný ale existuje
            if not data and filepath.endswith("cards_frames.json"):
                ensure_frames_data(filepath)
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            return data
    except Exception:
        if filepath.endswith("cards_frames.json"):
            ensure_frames_data(filepath)
            return load_json(filepath)
        return []

def ensure_frames_data(filepath):
    """Zajistí, aby cards_frames.json obsahoval alespoň Riddler."""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            default_frames = [
                {
                    "id": "riddler_frame",
                    "name": "Riddler Rámeček",
                    "image": "riddler-frame.png",
                    "color": "#FF6B9D",
                    "rarity_exclusive": None
                }
            ]
            json.dump(default_frames, f, indent=4, ensure_ascii=False)
    except Exception:
        pass

def get_frame_by_id(frame_id):
    """Vrátí data rámečku podle ID."""
    # Vždy zkontroluj aby frames byly inicializované
    frames = load_json(FRAMES_FILE)
    for frame in frames:
        if frame.get("id") == frame_id:
            return frame
    # Pokud frame nenajde ani po load_json (který inicializuje), vrátí None
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
    
    print(f"DEBUG apply_frame_to_card: card_image_path={card_image_path}, frame_id={frame_id}")
    
    # Zkontroluj existenci karty
    if not os.path.exists(card_image_path):
        print(f"DEBUG: Karta cesta neexistuje! {card_image_path}")
        raise FileNotFoundError(f"Obrázek karty nenalezen: {card_image_path}")
    
    # Pokud není frame_id, vrátí jen kartu
    if not frame_id or frame_id == "default":
        print(f"DEBUG: Žádný frame_id, vrací jen kartu")
        img = Image.open(card_image_path).convert("RGB")
        byte_io = io.BytesIO()
        img.save(byte_io, format="PNG")
        byte_io.seek(0)
        return byte_io
    
    # Načti frame info
    frame = get_frame_by_id(frame_id)
    print(f"DEBUG: get_frame_by_id({frame_id}) vrátil: {frame}")
    
    if not frame or "image" not in frame:
        # Fallback: vrátí jen kartu (frame neexistuje)
        print(f"DEBUG: Frame nenalezen nebo chybí 'image' pole, fallback na jen kartu")
        img = Image.open(card_image_path).convert("RGB")
        byte_io = io.BytesIO()
        img.save(byte_io, format="PNG")
        byte_io.seek(0)
        return byte_io
    
    # Pojď aplikovat frame image
    frame_image_path = os.path.join(FRAMES_DIR, frame.get("image"))
    print(f"DEBUG: Frame image path: {frame_image_path}, existuje: {os.path.exists(frame_image_path)}")
    
    if not os.path.exists(frame_image_path):
        # Asset soubor neexistuje - fallback na kartu
        print(f"DEBUG: Frame soubor neexistuje! {frame_image_path}")
        img = Image.open(card_image_path).convert("RGB")
        byte_io = io.BytesIO()
        img.save(byte_io, format="PNG")
        byte_io.seek(0)
        return byte_io
    
    try:
        print(f"DEBUG: Otevírám kartu a frame...")
        # Otevři kartu a frame
        card_img = Image.open(card_image_path).convert("RGBA")
        frame_img = Image.open(frame_image_path).convert("RGBA")
        
        print(f"DEBUG: Karty velikost: {card_img.size}, Frame velikost: {frame_img.size}")
        
        # Zmenšuj frame aby odpovídal kartě
        frame_img = frame_img.resize(card_img.size, Image.Resampling.LANCZOS)
        
        print(f"DEBUG: Frame resizován na: {frame_img.size}")
        
        # Aplikuj frame jako overlay na kartu
        result = Image.new("RGBA", card_img.size, (0, 0, 0, 0))
        result.paste(card_img, (0, 0), card_img)
        result.paste(frame_img, (0, 0), frame_img)
        
        print(f"DEBUG: Frame aplikován na kartu")
        
        # Převeď na RGB pro Discord (bez alpha channelu)
        rgb_result = Image.new("RGB", result.size, (255, 255, 255))
        rgb_result.paste(result, mask=result.split()[3])
        
        print(f"DEBUG: Obrázek převeden na RGB, ukládám do BytesIO")
        
        # Ulož do BytesIO
        byte_io = io.BytesIO()
        rgb_result.save(byte_io, format="PNG")
        byte_io.seek(0)
        
        print(f"DEBUG: Hotovo! BytesIO velikost: {len(byte_io.getvalue())}")
        return byte_io
    except Exception as e:
        # Jakákoli chyba → fallback na jen kartu
        print(f"DEBUG: Chyba při aplikování frame! {str(e)}")
        import traceback
        traceback.print_exc()
        img = Image.open(card_image_path).convert("RGB")
        byte_io = io.BytesIO()
        img.save(byte_io, format="PNG")
        byte_io.seek(0)
        return byte_io

def get_card_image_path(image_filename: str):
    """Vrátí cestu k obrázku karty podle jména souboru."""
    if not image_filename:
        return None
    path = os.path.join(CARDS_DIR, image_filename)
    if os.path.exists(path):
        return path
    return None
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
