"""
POC render karet pro /test-profile — vykresluje profilové embedy jako obrázky (PIL).
Čisté PIL, vrací io.BytesIO (PNG). Discord soubor se obalí až v cogu.
"""
import io, os
from PIL import Image, ImageDraw, ImageFont

try:
    from src.logic.stats import get_xp_cap, STAT_LABELS, SKILL_LABELS
except Exception:  # fallback pro lokální test
    STAT_LABELS  = ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']
    SKILL_LABELS = ['Síla', 'Obratnost', 'Magie', 'Výdrž']
    def get_xp_cap(level): return 15000

# ── fonty (robustně: zkus víc cest, fallback na default) ──────────────────────
_FONT_DIRS = [
    "src/assets/fonts",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype/freefont",
]
_SERIF = ["LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf", "FreeSerifBold.ttf"]
_SANS  = ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "FreeSansBold.ttf"]

def _find(names):
    for dpath in _FONT_DIRS:
        for n in names:
            p = os.path.join(dpath, n)
            if os.path.exists(p):
                return p
    return None

_SERIF_PATH = _find(_SERIF)
_SANS_PATH  = _find(_SANS)

def _font(size, serif=False):
    path = _SERIF_PATH if serif else _SANS_PATH
    try:
        if path:
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    return ImageFont.load_default()

GOLD = (232, 220, 192)
GREY = (150, 150, 165)

# ── stavební bloky ────────────────────────────────────────────────────────────
def _panel(W, H, accent=(184, 137, 58)):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    for y in range(H):
        t = y / H
        pd.line([(0, y), (W, y)], fill=(int(26 - 12 * t), int(26 - 12 * t), int(37 - 16 * t), 255))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([4, 4, W - 5, H - 5], radius=28, fill=255)
    img.paste(panel, (0, 0), mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, W - 5, H - 5], radius=28, outline=accent + (255,), width=3)
    d.rounded_rectangle([10, 10, W - 11, H - 11], radius=24, outline=(120, 90, 40, 110), width=1)
    return img, d

def _grad_bar(img, d, x, y, w, h, pct, c1, c2, r=11):
    pct = max(0.0, min(1.0, pct))
    d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=(22, 22, 30, 255),
                        outline=(70, 70, 88, 255), width=1)
    fw = int(w * pct)
    if fw <= r:
        return
    g = Image.new("RGB", (fw, h))
    gd = ImageDraw.Draw(g)
    for i in range(fw):
        tt = i / max(1, fw - 1)
        gd.line([(i, 0), (i, h)], fill=tuple(int(c1[j] + (c2[j] - c1[j]) * tt) for j in range(3)))
    m = Image.new("L", (fw, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, fw - 1, h - 1], radius=r, fill=255)
    img.paste(g, (x, y), m)
    d.line([(x + r, y + 2), (x + fw - r, y + 2)], fill=(255, 255, 255, 70), width=2)

def _stars(d, x, y, filled, total=3):
    for i in range(total):
        col = (212, 175, 55) if i < filled else (70, 70, 85)
        cx, cy = x + i * 44, y
        pts = [(cx, cy - 15), (cx + 5, cy - 4), (cx + 15, cy - 4), (cx + 6, cy + 3),
               (cx + 10, cy + 14), (cx, cy + 6), (cx - 10, cy + 14), (cx - 6, cy + 3),
               (cx - 15, cy - 4), (cx - 5, cy - 4)]
        d.polygon(pts, fill=col)

def _save(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf

def _xp_bar(img, d, level, xp, cap, x, y, w):
    d.rounded_rectangle([x, y, x + w, y + 120], radius=18, fill=(18, 18, 26, 255),
                        outline=(150, 120, 55, 200), width=2)
    cx = x + w // 2
    d.text((cx, y + 24), f"Lvl {level}  ·  Postup", font=_font(28, serif=True), fill=GOLD, anchor="ma")
    bx, by, bw, bh = x + 36, y + 60, w - 72, 34
    pct = (xp / cap) if cap else 1.0
    _grad_bar(img, d, bx, by, bw, bh, pct, (160, 110, 20), (245, 200, 60), r=14)
    for s in range(1, 10):
        sxp = bx + int(bw * s / 10)
        d.line([(sxp, by + 3), (sxp, by + bh - 3)], fill=(0, 0, 0, 90), width=2)
    cap_txt = f"{xp:,} / {cap:,}".replace(",", " ") if cap else f"{xp:,}  (MAX)".replace(",", " ")
    d.text((bx + bw // 2, by + bh // 2), cap_txt, font=_font(19), fill=(20, 20, 20), anchor="mm")

# ── KARTA: STATY ──────────────────────────────────────────────────────────────
def render_stats_card(profile, char_name):
    W, H = 880, 700
    img, d = _panel(W, H)
    d.text((40, 28), char_name, font=_font(42, serif=True), fill=GOLD)
    d.text((44, 80), "Statistiky", font=_font(20, serif=True), fill=GREY)

    hp_max = profile.get("hp_max", 50);  hp = profile.get("hp_cur", hp_max)
    mn_max = profile.get("mana_max", 5); mn = profile.get("mana_cur", 0)
    hu_max = profile.get("hunger_max", 10); hu = profile.get("hunger_cur", hu_max)
    fu_max = profile.get("fury_max", 0); fu = profile.get("fury_cur", 0)
    rows = [("Zdraví", f"{hp} / {hp_max}", hp / hp_max if hp_max else 0, (192, 57, 43), (231, 76, 60)),
            ("Mana",   f"{mn} / {mn_max}", mn / mn_max if mn_max else 0, (37, 99, 235), (59, 130, 246)),
            ("Hlad",   f"{hu} / {hu_max}", hu / hu_max if hu_max else 0, (214, 137, 16), (241, 196, 15)),
            ("Furioka", f"{fu} / {fu_max}" if fu_max else f"{fu}", fu / fu_max if fu_max else 0, (30, 132, 73), (46, 204, 113))]
    y = 128
    for name, val, pct, c1, c2 in rows:
        d.text((44, y - 2), name, font=_font(21), fill=(225, 225, 235))
        _grad_bar(img, d, 200, y, 560, 28, pct, c1, c2)
        d.text((760, y + 2), val, font=_font(19), fill=GOLD, anchor="ra")
        y += 48

    # atributy + skilly (kompaktně)
    stats  = profile.get("stats", {})
    skills = profile.get("skills", {})
    d.text((44, y + 4), "Atributy", font=_font(18, serif=True), fill=GREY)
    d.text((44, y + 30), "   ".join(f"{k} {stats.get(k, 0)}" for k in STAT_LABELS),
           font=_font(20), fill=(220, 220, 230))
    d.text((44, y + 62), "Skilly", font=_font(18, serif=True), fill=GREY)
    d.text((44, y + 88), "   ".join(f"{s} {skills.get(s, 0)}" for s in SKILL_LABELS),
           font=_font(20), fill=(220, 220, 230))

    ap = profile.get("ap", 0); sp = profile.get("sp", 0)
    d.text((760, y + 30), f"AP {ap}   SP {sp}", font=_font(20), fill=GOLD, anchor="ra")

    _xp_bar(img, d, profile.get("level", 0), profile.get("xp", 0),
            get_xp_cap(profile.get("level", 0)), 40, H - 150, W - 80)
    return _save(img)

# ── KARTA: PRŮKAZ ─────────────────────────────────────────────────────────────
def render_prukaz_card(profile, char_name, gold, silver, stardust, rank="F3", spirit_name=None):
    W, H = 880, 560
    img, d = _panel(W, H, accent=(70, 110, 180))
    d.text((40, 28), char_name, font=_font(44, serif=True), fill=GOLD)
    title = profile.get("title", "")
    if title:
        d.text((44, 84), title, font=_font(22, serif=True), fill=GREY)
    # rank + hvězdy
    d.text((W - 230, 36), f"Rank {rank}", font=_font(22), fill=GOLD, anchor="ra")
    _stars(d, W - 130, 48, filled=1)

    # měny
    d.text((44, 134), f"Zlato {gold}    Stříbro {silver}    Stardust {stardust}",
           font=_font(22), fill=(225, 215, 170))
    if spirit_name:
        d.text((44, 168), f"Strážný duch: {spirit_name}", font=_font(19, serif=True), fill=GREY)

    # poslední vzpomínka (box)
    memories = profile.get("memories", [])
    bx, by, bw, bh = 40, 220, W - 80, H - 270
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=16, fill=(16, 16, 24, 255),
                        outline=(80, 80, 100, 160), width=1)
    d.text((bx + 20, by + 16), "Poslední vzpomínka", font=_font(20, serif=True), fill=(200, 90, 90))
    mem = (memories[-1] if memories else "Zatím žádná vzpomínka…")
    # zalom text
    words = mem.split()
    line, yy = "", by + 54
    fnt = _font(22, serif=True)
    for w in words:
        if d.textlength(line + " " + w, font=fnt) > bw - 40:
            d.text((bx + 20, yy), line, font=fnt, fill=(210, 210, 220)); line = w; yy += 32
            if yy > by + bh - 40: break
        else:
            line = (line + " " + w).strip()
    if line and yy <= by + bh - 40:
        d.text((bx + 20, yy), line, font=fnt, fill=(210, 210, 220))
    return _save(img)