"""
POC render karet pro /test-profile — profilové embedy jako obrázky (PIL).
Čisté PIL, vrací io.BytesIO (PNG). Portrét se předává jako bajty (stáhne cog).
"""
import io, os, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

try:
    from src.logic.stats import get_xp_cap, STAT_LABELS, SKILL_LABELS
except Exception:
    STAT_LABELS  = ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']
    SKILL_LABELS = ['Síla', 'Obratnost', 'Magie', 'Výdrž']
    def get_xp_cap(level): return 15000

# ── fonty ─────────────────────────────────────────────────────────────────────
_FONT_DIRS = ["src/assets/fonts", "/usr/share/fonts/truetype/dejavu",
              "/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/freefont"]
_SERIF = ["LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf", "FreeSerifBold.ttf"]
_SANS  = ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "FreeSansBold.ttf"]
def _find(names):
    for dp in _FONT_DIRS:
        for n in names:
            p = os.path.join(dp, n)
            if os.path.exists(p): return p
    return None
_SERIF_PATH, _SANS_PATH = _find(_SERIF), _find(_SANS)
def _font(size, serif=False):
    try:
        p = _SERIF_PATH if serif else _SANS_PATH
        if p: return ImageFont.truetype(p, size)
    except Exception: pass
    return ImageFont.load_default()

GOLD = (232, 220, 192); GREY = (150, 150, 165); GOLD_HARD = (212, 175, 55)

# ── stavební bloky ────────────────────────────────────────────────────────────
def _base(W, H, accent=(184, 137, 58), tint=(0, 0, 0)):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0)); pd = ImageDraw.Draw(panel)
    for y in range(H):
        t = y / H
        pd.line([(0, y), (W, y)], fill=(int(24 - 10*t + tint[0]*0.04),
                                        int(24 - 10*t + tint[1]*0.04),
                                        int(36 - 14*t + tint[2]*0.04), 255))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([4, 4, W-5, H-5], radius=30, fill=255)
    img.paste(panel, (0, 0), mask)
    _starfield(img, mask)
    _vignette(img, mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, W-5, H-5], radius=30, outline=accent + (255,), width=3)
    d.rounded_rectangle([11, 11, W-12, H-12], radius=25, outline=(120, 90, 40, 110), width=1)
    _corner_flourish(d, W, H, accent)
    return img, d

def _starfield(img, mask, n=140, seed=7):
    rnd = random.Random(seed); W, H = img.size
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
    for _ in range(n):
        x, y = rnd.randint(0, W), rnd.randint(0, H)
        r = rnd.choice([1, 1, 1, 2]); a = rnd.randint(15, 70)
        ld.ellipse([x, y, x+r, y+r], fill=(255, 255, 240, a))
    img.paste(layer, (0, 0), Image.composite(layer.split()[3], Image.new("L", (W, H), 0), mask))

def _vignette(img, mask):
    W, H = img.size
    v = Image.new("L", (W, H), 0)
    ImageDraw.Draw(v).ellipse([int(-W*0.25), int(-H*0.25), int(W*1.25), int(H*1.25)], fill=255)
    v = v.filter(ImageFilter.GaussianBlur(140))
    inv = Image.eval(v, lambda p: 255 - p)
    inv = Image.composite(inv, Image.new("L", (W, H), 0), mask)
    img.paste(Image.new("RGBA", (W, H), (0, 0, 0, 170)), (0, 0), inv)

def _corner_flourish(d, W, H, accent):
    a = accent + (180,)
    for (cx, cy, sx, sy) in [(20, 20, 1, 1), (W-20, 20, -1, 1), (20, H-20, 1, -1), (W-20, H-20, -1, -1)]:
        d.line([(cx+sx*14, cy+sy*14), (cx+sx*52, cy+sy*14)], fill=a, width=2)
        d.line([(cx+sx*14, cy+sy*14), (cx+sx*14, cy+sy*52)], fill=a, width=2)
        d.ellipse([cx+sx*10-3, cy+sy*10-3, cx+sx*10+3, cy+sy*10+3], fill=GOLD_HARD + (255,))

def _cover(im, w, h):
    iw, ih = im.size; s = max(w/iw, h/ih)
    im = im.resize((max(1, int(iw*s)), max(1, int(ih*s))), Image.LANCZOS)
    nw, nh = im.size; x, y = (nw-w)//2, (nh-h)//2
    return im.crop((x, y, x+w, y+h))

def _rmask(w, h, r):
    m = Image.new("L", (w, h), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, w-1, h-1], radius=r, fill=255); return m

def _portrait(img, portrait, x, y, w, h, r=18, frame=GOLD_HARD, circle=False):
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    if circle:
        gd.ellipse([x-8, y-8, x+w+8, y+h+8], fill=frame + (130,))
    else:
        gd.rounded_rectangle([x-8, y-8, x+w+8, y+h+8], radius=r+8, fill=frame + (130,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(img)
    if portrait is None:
        if circle: d.ellipse([x, y, x+w, y+h], fill=(30, 30, 42, 255))
        else: d.rounded_rectangle([x, y, x+w, y+h], radius=r, fill=(30, 30, 42, 255))
        d.text((x+w//2, y+h//2), "?", font=_font(int(h*0.5), serif=True), fill=GREY, anchor="mm")
    else:
        p = _cover(portrait, w, h)
        if circle:
            m = Image.new("L", (w, h), 0); ImageDraw.Draw(m).ellipse([0, 0, w-1, h-1], fill=255)
        else:
            m = _rmask(w, h, r)
        img.paste(p, (x, y), m)
    if circle:
        d.ellipse([x, y, x+w, y+h], outline=frame + (255,), width=4)
    else:
        d.rounded_rectangle([x, y, x+w, y+h], radius=r, outline=frame + (255,), width=4)
        d.rounded_rectangle([x+4, y+4, x+w-4, y+h-4], radius=r-3, outline=(255, 255, 255, 40), width=1)

def _grad_bar(img, d, x, y, w, h, pct, c1, c2, r=11):
    pct = max(0.0, min(1.0, pct))
    d.rounded_rectangle([x, y, x+w, y+h], radius=r, fill=(20, 20, 28, 255), outline=(70, 70, 88, 255), width=1)
    fw = int(w*pct)
    if fw <= r: return
    g = Image.new("RGB", (fw, h)); gd = ImageDraw.Draw(g)
    for i in range(fw):
        tt = i/max(1, fw-1)
        gd.line([(i, 0), (i, h)], fill=tuple(int(c1[j]+(c2[j]-c1[j])*tt) for j in range(3)))
    img.paste(g, (x, y), _rmask(fw, h, r))
    d.line([(x+r, y+2), (x+fw-r, y+2)], fill=(255, 255, 255, 75), width=2)

def _rank_stars(d, x, y, filled, total=3):
    for i in range(total):
        col = GOLD_HARD if i < filled else (70, 70, 85)
        cx, cy = x+i*42, y
        pts = [(cx, cy-14), (cx+5, cy-4), (cx+14, cy-4), (cx+6, cy+3), (cx+10, cy+13),
               (cx, cy+6), (cx-10, cy+13), (cx-6, cy+3), (cx-14, cy-4), (cx-5, cy-4)]
        d.polygon(pts, fill=col + (255,))

def _divider(d, x1, x2, y, accent=(150, 120, 55)):
    d.line([(x1, y), (x2, y)], fill=accent + (140,), width=1)
    cx = (x1+x2)//2
    d.polygon([(cx, y-5), (cx+6, y), (cx, y+5), (cx-6, y)], fill=GOLD_HARD + (255,))

def _save(img):
    buf = io.BytesIO(); img.convert("RGBA").save(buf, "PNG"); buf.seek(0); return buf

def _open_portrait(portrait_bytes):
    if not portrait_bytes: return None
    try: return Image.open(io.BytesIO(portrait_bytes)).convert("RGBA")
    except Exception: return None

def _xp_bar(img, d, level, xp, cap, x, y, w):
    d.rounded_rectangle([x, y, x+w, y+118], radius=18, fill=(16, 16, 24, 255), outline=(150, 120, 55, 200), width=2)
    d.text((x+w//2, y+22), f"Lvl {level}  \u00b7  Postup", font=_font(28, serif=True), fill=GOLD, anchor="ma")
    bx, by, bw, bh = x+36, y+58, w-72, 32
    _grad_bar(img, d, bx, by, bw, bh, (xp/cap) if cap else 1.0, (160, 110, 20), (245, 200, 60), r=14)
    for s in range(1, 10):
        sxp = bx+int(bw*s/10); d.line([(sxp, by+3), (sxp, by+bh-3)], fill=(0, 0, 0, 90), width=2)
    txt = (f"{xp:,} / {cap:,}".replace(",", " ")) if cap else (f"{xp:,}  (MAX)".replace(",", " "))
    d.text((bx+bw//2, by+bh//2), txt, font=_font(19), fill=(20, 20, 20), anchor="mm")

# ── KARTA: PRŮKAZ (velký portrét) ─────────────────────────────────────────────
def render_prukaz_card(profile, char_name, gold, silver, stardust, rank="F3",
                       spirit_name=None, portrait_bytes=None):
    W, H = 1000, 640
    img, d = _base(W, H, accent=(70, 110, 180), tint=(20, 40, 90))
    portrait = _open_portrait(portrait_bytes)
    # velký portrét vlevo
    px, py, pw, ph = 40, 60, 320, 440
    _portrait(img, portrait, px, py, pw, ph, r=20, frame=(212, 175, 55))
    d = ImageDraw.Draw(img)

    rx = px + pw + 40
    d.text((rx, 56), char_name, font=_font(50, serif=True), fill=GOLD)
    title = profile.get("title", "")
    if title:
        d.text((rx, 118), title, font=_font(24, serif=True), fill=GREY)
    d.text((rx, 158), f"Rank {rank}", font=_font(24), fill=GOLD); _rank_stars(d, rx+150, 170, 1)

    _divider(d, rx, W-50, 212)
    # měny
    d.text((rx, 232), f"\u25c6 Zlato {gold}", font=_font(24), fill=(241, 196, 15))
    d.text((rx, 268), f"\u25c6 Stříbro {silver}", font=_font(24), fill=(189, 195, 199))
    d.text((rx, 304), f"\u25c6 Stardust {stardust}", font=_font(24), fill=(155, 120, 230))
    if spirit_name:
        d.text((rx, 348), f"Strážný duch: {spirit_name}", font=_font(20, serif=True), fill=GREY)

    _divider(d, rx, W-50, 396)
    d.text((rx, 412), "Poslední vzpomínka", font=_font(22, serif=True), fill=(210, 100, 100))
    mem = (profile.get("memories") or ["Zatím žádná vzpomínka…"])[-1]
    fnt = _font(23, serif=True); line, yy, maxw = "", 448, W-50-rx
    for word in mem.split():
        if d.textlength(line+" "+word, font=fnt) > maxw:
            d.text((rx, yy), line, font=fnt, fill=(212, 212, 222)); line = word; yy += 34
            if yy > H-70: break
        else:
            line = (line+" "+word).strip()
    if line and yy <= H-70:
        d.text((rx, yy), line, font=fnt, fill=(212, 212, 222))
    return _save(img)

# ── KARTA: STATY (portrét jako akcent) ────────────────────────────────────────
def render_stats_card(profile, char_name, portrait_bytes=None):
    W, H = 1000, 760
    img, d = _base(W, H, accent=(184, 137, 58), tint=(40, 30, 10))
    portrait = _open_portrait(portrait_bytes)
    _portrait(img, portrait, 44, 44, 130, 130, circle=True, frame=(212, 175, 55))
    d = ImageDraw.Draw(img)
    d.text((196, 56), char_name, font=_font(46, serif=True), fill=GOLD)
    d.text((200, 116), "Statistiky", font=_font(22, serif=True), fill=GREY)

    hp_max = profile.get("hp_max", 50);  hp = profile.get("hp_cur", hp_max)
    mn_max = profile.get("mana_max", 5); mn = profile.get("mana_cur", 0)
    hu_max = profile.get("hunger_max", 10); hu = profile.get("hunger_cur", hu_max)
    fu_max = profile.get("fury_max", 0); fu = profile.get("fury_cur", 0)
    rows = [("Zdraví", f"{hp} / {hp_max}", hp/hp_max if hp_max else 0, (192, 57, 43), (231, 76, 60)),
            ("Mana", f"{mn} / {mn_max}", mn/mn_max if mn_max else 0, (37, 99, 235), (59, 130, 246)),
            ("Hlad", f"{hu} / {hu_max}", hu/hu_max if hu_max else 0, (214, 137, 16), (241, 196, 15)),
            ("Furioka", f"{fu} / {fu_max}" if fu_max else f"{fu}", fu/fu_max if fu_max else 0, (30, 132, 73), (46, 204, 113))]
    y = 210
    for name, val, pct, c1, c2 in rows:
        d.text((48, y-2), name, font=_font(22), fill=(228, 228, 238))
        _grad_bar(img, d, 230, y, 600, 30, pct, c1, c2)
        d.text((838, y+3), val, font=_font(20), fill=GOLD, anchor="la")
        y += 52

    _divider(d, 48, W-48, y+10)
    stats  = profile.get("stats", {}); skills = profile.get("skills", {})
    d.text((48, y+30), "Atributy", font=_font(19, serif=True), fill=GREY)
    d.text((48, y+58), "    ".join(f"{k} {stats.get(k, 0)}" for k in STAT_LABELS), font=_font(22), fill=(222, 222, 232))
    d.text((48, y+96), "Skilly", font=_font(19, serif=True), fill=GREY)
    d.text((48, y+124), "    ".join(f"{s} {skills.get(s, 0)}" for s in SKILL_LABELS), font=_font(22), fill=(222, 222, 232))
    d.text((W-48, y+58), f"AP {profile.get('ap', 0)}", font=_font(24, serif=True), fill=GOLD, anchor="ra")
    d.text((W-48, y+96), f"SP {profile.get('sp', 0)}", font=_font(24, serif=True), fill=GOLD, anchor="ra")

    _xp_bar(img, d, profile.get("level", 0), profile.get("xp", 0), get_xp_cap(profile.get("level", 0)), 40, H-150, W-80)
    return _save(img)