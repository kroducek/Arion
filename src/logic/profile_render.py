"""
POC render karet pro /test-profile — profilové embedy jako obrázky (PIL).
Čisté PIL, vrací io.BytesIO (PNG). Portrét se předává jako bajty (stáhne cog).
"""
import io, os, random, re
from PIL import Image, ImageDraw, ImageFont, ImageFilter

try:
    from src.logic.stats import get_xp_cap, STAT_LABELS, _skill_registry, _roman, level_label
except Exception:
    STAT_LABELS  = ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']
    def get_xp_cap(level): return 15000
    def _skill_registry(): return {}
    def _roman(n): return str(n)
    def level_label(level): return f"Lvl {level}"

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

def _accent_rgb(profile, default):
    c = profile.get("accent_color")
    if isinstance(c, int) and c > 0:
        return ((c >> 16) & 255, (c >> 8) & 255, c & 255)
    return default

# ── stavební bloky ────────────────────────────────────────────────────────────
def _base(W, H, accent=(184, 137, 58), tint=(0, 0, 0), bg_portrait=None):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if bg_portrait is not None:
        bg = _cover(bg_portrait, W, H).convert("RGBA").filter(ImageFilter.GaussianBlur(26))
        bg = Image.alpha_composite(bg, Image.new("RGBA", (W, H), (8, 8, 16, 120)))
        grad = Image.new("L", (W, H), 0); gd = ImageDraw.Draw(grad)
        for x in range(W):
            gd.line([(x, 0), (x, H)], fill=int(55 + 165 * (x / W)))
        panel = Image.composite(Image.new("RGBA", (W, H), (6, 7, 14, 255)), bg, grad)
    else:
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
    nw, nh = im.size; x, y = (nw-w)//2, int((nh-h)*0.18)  # crop spíš odshora (obličeje)
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
    d.text((x+w//2, y+22), f"{level_label(level)}  \u00b7  Postup", font=_font(28, serif=True), fill=GOLD, anchor="ma")
    bx, by, bw, bh = x+36, y+58, w-72, 32
    _grad_bar(img, d, bx, by, bw, bh, (xp/cap) if cap else 1.0, (160, 110, 20), (245, 200, 60), r=14)
    for s in range(1, 10):
        sxp = bx+int(bw*s/10); d.line([(sxp, by+3), (sxp, by+bh-3)], fill=(0, 0, 0, 90), width=2)
    txt = (f"{xp:,} / {cap:,}".replace(",", " ")) if cap else (f"{xp:,}  (MAX)".replace(",", " "))
    d.text((bx + bw // 2, by + bh // 2), txt, font=_font(22, serif=True), fill=(255, 255, 255),
           anchor="mm", stroke_width=3, stroke_fill=(35, 22, 0))

def _truncate(d, text, font, maxw):
    if d.textlength(text, font=font) <= maxw:
        return text
    while text and d.textlength(text + "…", font=font) > maxw:
        text = text[:-1]
    return text + "…"

def _wrap(d, text, font, maxw, max_lines=99):
    words = (text or "").split()
    lines, line = [], ""
    for w in words:
        test = (line + " " + w).strip()
        if d.textlength(test, font=font) <= maxw:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
            if len(lines) == max_lines:
                last = lines[-1]
                while last and d.textlength(last + " …", font=font) > maxw:
                    last = last[:-1]
                lines[-1] = last + " …"
                return lines
    if line and len(lines) < max_lines:
        lines.append(line)
    return lines[:max_lines]

def _currency_row(d, x, y, items):
    cx = x
    fnt = _font(20)
    for col, label, val in items:
        d.polygon([(cx, y + 11), (cx + 7, y + 18), (cx, y + 25), (cx - 7, y + 18)], fill=col + (255,))
        txt = f"{label} {val}"
        d.text((cx + 16, y), txt, font=fnt, fill=(226, 216, 184))
        cx += 16 + int(d.textlength(txt, font=fnt)) + 34

# ── KARTA: PRŮKAZ (velký portrét + rozmazané pozadí) ──────────────────────────
def render_prukaz_card(profile, char_name, gold, silver, stardust, rank="F3",
                       spirit_name=None, portrait_bytes=None, reputation=None):
    W, H = 1000, 760
    portrait = _open_portrait(portrait_bytes)
    accent = _accent_rgb(profile, (70, 110, 180))
    use_bg = profile.get("card_bg", "portrait") != "plain"
    img, d = _base(W, H, accent=accent, tint=(20, 40, 90), bg_portrait=portrait if use_bg else None)
    px, py, pw, ph = 40, 60, 340, 560
    _portrait(img, portrait, px, py, pw, ph, r=20, frame=accent)
    d = ImageDraw.Draw(img)

    rx = px + pw + 40
    maxw = W - 50 - rx
    d.text((rx, 60), _truncate(d, char_name, _font(48, serif=True), maxw), font=_font(48, serif=True), fill=GOLD)
    title = profile.get("title", "")
    if title:
        d.text((rx, 122), _truncate(d, title, _font(24, serif=True), maxw), font=_font(24, serif=True), fill=GREY)
    # Hvězdy dle POSTUPU, ne dle číslice: X3 = ★☆☆ (nejnižší) … X1 = ★★★, S/S+ = ★★★.
    # Dřív se brala číslice napřímo → F3 (nejhorší) svítilo ★★★ a F1 (nejlepší) ★☆☆.
    try:
        from src.logic.ranks import rank_stars
        filled = rank_stars(rank)
    except Exception:
        filled = 1
    d.text((rx, 160), f"Rank {rank}", font=_font(24), fill=GOLD)
    _rank_stars(d, rx + 150, 172, filled)

    _divider(d, rx, W - 50, 206, accent=accent)
    y = 220
    # MOTIVACE (prominentně, nad bio)
    motivation = profile.get("motivation", "")
    if motivation:
        d.text((rx, y), "◆ Motivace", font=_font(19, serif=True), fill=(212, 175, 55)); y += 28
        for ln in _wrap(d, f"„{motivation}“", _font(24, serif=True), maxw, max_lines=2):
            d.text((rx, y), ln, font=_font(24, serif=True), fill=(245, 232, 190)); y += 33
        y += 8
    # BIO (sekundárně)
    bio = profile.get("bio", "")
    if bio:
        d.text((rx, y), "O postavě", font=_font(18, serif=True), fill=(150, 150, 165)); y += 26
        for ln in _wrap(d, bio, _font(20, serif=True), maxw, max_lines=2):
            d.text((rx, y), ln, font=_font(20, serif=True), fill=(205, 205, 218)); y += 28
        y += 8
    _divider(d, rx, W - 50, y, accent=accent); y += 18

    _currency_row(d, rx, y,
                  [((241, 196, 15), "Zlato", gold),
                   ((189, 195, 199), "Stříbro", silver),
                   ((155, 120, 230), "Stardust", stardust)])
    y += 40
    if spirit_name:
        d.text((rx, y), f"Strážný duch: {spirit_name}", font=_font(19, serif=True), fill=GREY); y += 34
    if reputation:
        d.text((rx, y), "◆ Reputace", font=_font(19, serif=True), fill=(212, 175, 55)); y += 26
        for ln in _wrap(d, reputation, _font(20, serif=True), maxw, max_lines=2):
            d.text((rx, y), ln, font=_font(20, serif=True), fill=(205, 205, 218)); y += 28
        y += 4
    _divider(d, rx, W - 50, y, accent=accent); y += 18

    d.text((rx, y), "Poslední vzpomínka", font=_font(21, serif=True), fill=(210, 100, 100)); y += 32
    mem = (profile.get("memories") or ["Zatím žádná vzpomínka…"])[-1]
    maxlines = max(1, (H - 54 - y) // 30)
    for ln in _wrap(d, mem, _font(21, serif=True), maxw, max_lines=maxlines):
        d.text((rx, y), ln, font=_font(21, serif=True), fill=(212, 212, 222)); y += 30
    return _save(img)

# ── KARTA: STATY (portrét jako akcent) ────────────────────────────────────────
def _skill_chip(d, x, y, w, h, name, rom, font, accent):
    """Epická skill pilulka: zaoblený rámeček, accent okraj, zlatá římská číslice."""
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=(30, 30, 46, 255),
                        outline=accent + (215,), width=2)
    d.rounded_rectangle([x + 2, y + 2, x + w - 2, y + h - 2], radius=(h - 4) // 2,
                        outline=(255, 255, 255, 22), width=1)
    tx = x + 16
    d.text((tx, y + h // 2 - 1), name, font=font, fill=(228, 228, 238), anchor="lm")
    if rom:
        nw = d.textlength(name + " ", font=font)
        d.text((tx + nw, y + h // 2 - 1), rom, font=font, fill=GOLD_HARD, anchor="lm")


def render_stats_card(profile, char_name, portrait_bytes=None, extras=None):
    W = 1000
    _ex    = extras or {}
    accent = _accent_rgb(profile, (184, 137, 58))
    stats  = profile.get("stats", {})
    skills = profile.get("skills", {})
    _reg   = _skill_registry()
    learned = [(_reg.get(sid, {}).get("name", sid), _roman(lvl))
               for sid, lvl in skills.items() if lvl]

    chip_font = _font(21)
    _meas = ImageDraw.Draw(Image.new("RGBA", (W, 8)))
    x0, max_x, chip_h, gap = 48, W - 48, 42, 12
    chips = [(nm, rom, int(_meas.textlength(f"{nm} {rom}".strip(), font=chip_font)) + 34)
             for nm, rom in learned]
    rows_layout, row, cx = [], [], x0
    for nm, rom, w in chips:
        if row and cx + w > max_x:
            rows_layout.append(row); row, cx = [], x0
        row.append((nm, rom, w)); cx += w + gap
    if row:
        rows_layout.append(row)
    n_rows = max(1, len(rows_layout))

    skills_top = 586  # posunuto o Vliv řádek pod Furiokou
    _statuses = _ex.get("statuses") or []
    H = skills_top + n_rows * (chip_h + 12) + 40 + (50 if _statuses else 0) + 160

    img, d = _base(W, H, accent=accent, tint=(40, 30, 10))
    portrait = _open_portrait(portrait_bytes)
    _portrait(img, portrait, 44, 44, 130, 130, circle=True, frame=accent)
    d = ImageDraw.Draw(img)
    d.text((196, 56), char_name, font=_font(46, serif=True), fill=GOLD)
    d.text((200, 116), "Statistiky", font=_font(22, serif=True), fill=GREY)

    hp_max = profile.get("hp_max", 50);  hp = profile.get("hp_cur", hp_max)
    mn_max = profile.get("mana_max", 5); mn = profile.get("mana_cur", 0)
    hu_max = profile.get("hunger_max", 10); hu = profile.get("hunger_cur", hu_max)
    fu_max = profile.get("fury_max", 0); fu = profile.get("fury_cur", 0)
    _hpval = f"{hp} / {hp_max}" + (f"  ·  {_ex['def']} DEF" if _ex.get("def") else "")
    _fuval = (f"{fu} / {fu_max}" if fu_max else f"{fu}") + (f"  +{_ex['fury_spirit']}" if _ex.get("fury_spirit") else "")
    rows = [("Zdraví", _hpval, hp/hp_max if hp_max else 0, (192, 57, 43), (231, 76, 60)),
            ("Mana", f"{mn} / {mn_max}", mn/mn_max if mn_max else 0, (37, 99, 235), (59, 130, 246)),
            ("Hlad", f"{hu} / {hu_max}", hu/hu_max if hu_max else 0, (214, 137, 16), (241, 196, 15)),
            ("Furioka", _fuval, fu/fu_max if fu_max else 0, (30, 132, 73), (46, 204, 113))]
    y = 210
    for name, val, pct, c1, c2 in rows:
        d.text((48, y - 2), name, font=_font(22), fill=(228, 228, 238))
        _grad_bar(img, d, 230, y, 470, 30, pct, c1, c2)
        d.text((712, y + 3), val, font=_font(20), fill=GOLD, anchor="la")
        y += 52

    # ── Vliv (pod Furioka barem — souvisí: 1 Vliv = 5 furiok) ──
    v_s = profile.get("vliv_svetlo", 0)
    v_t = profile.get("vliv_temnota", 0)
    v_r = profile.get("vliv_rovnovaha", 0)
    d.text((48, y + 4), "Vliv", font=_font(19, serif=True), fill=GREY)
    _viv = f"Světlo {v_s}     Temnota {v_t}     Rovnováha {v_r}"
    if _ex.get("fury_spirit_name"):
        _viv += f"       ·  Duch: {_ex['fury_spirit_name']}"
    d.text((150, y + 2), _viv, font=_font(22), fill=(222, 222, 232))
    y += 44

    _divider(d, 48, W - 48, y + 10, accent=accent)
    d.text((48, y + 30), "Atributy", font=_font(19, serif=True), fill=GREY)
    d.text((48, y + 58), "    ".join(f"{k} {stats.get(k, 0)}" for k in STAT_LABELS),
           font=_font(22), fill=(222, 222, 232))
    d.text((W - 48, y + 30), f"AP {profile.get('ap', 0)}", font=_font(24, serif=True), fill=GOLD, anchor="ra")
    d.text((W - 48, y + 58), f"SP {profile.get('sp', 0)}", font=_font(24, serif=True), fill=GOLD, anchor="ra")

    d.text((48, y + 96), "Skilly", font=_font(19, serif=True), fill=GREY)
    sy = skills_top
    if not rows_layout:
        d.text((48, sy + 8), "—", font=chip_font, fill=(150, 150, 165))
    for r in rows_layout:
        sx = x0
        for nm, rom, w in r:
            _skill_chip(d, sx, sy, w, chip_h, nm, rom, chip_font, accent)
            sx += w + gap
        sy += chip_h + 12

    # ── Sbírka ──
    d.text((48, sy + 6), "Sbírka", font=_font(19, serif=True), fill=GREY)
    d.text((150, sy + 4), f"Perky {_ex.get('perks', 0)}     Achievementy {_ex.get('achievements', 0)}     Karty {_ex.get('cards', 0)}",
           font=_font(22), fill=(222, 222, 232))

    # ── Statusy (pilulky) ──
    if _statuses:
        sy += 42
        d.text((48, sy + 6), "Statusy", font=_font(19, serif=True), fill=GREY)
        sx = 150
        for nm in _statuses[:6]:
            w = int(_meas.textlength(nm, font=chip_font)) + 30
            if sx + w > W - 48:
                break
            _skill_chip(d, sx, sy, w, chip_h, nm, "", chip_font, (200, 70, 70))
            sx += w + gap

    _xp_bar(img, d, profile.get("level", 0), profile.get("xp", 0),
            get_xp_cap(profile.get("level", 0)), 40, H - 150, W - 80)
    return _save(img)