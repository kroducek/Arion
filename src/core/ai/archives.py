"""Registrované archivy, místní index zpráv a výběr scén pro ArionAI."""
import re
import sqlite3
import unicodedata

from src.database import db


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold())
                   if not unicodedata.combining(c))


def words(text):
    return re.findall(r"[a-z0-9]+", normalize(text))


def alias_match(alias, question):
    tokens = words(question)
    name = words(alias)
    if not name:
        return False
    # Vall, Valla, Vallovi; Karl, Karla, Karlovi.
    endings = ("", "a", "u", "ovi", "em", "e", "uv")
    return any(tokens[i:i + len(name) - 1] == name[:-1]
               and tokens[i + len(name) - 1] in {name[-1] + end for end in endings}
               for i in range(len(tokens) - len(name) + 1))


def setup(conn=None):
    conn = db.connect() if conn is None else conn
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ai_archives (
            guild INTEGER NOT NULL, channel INTEGER PRIMARY KEY, names TEXT NOT NULL,
            complete INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS ai_messages (
            channel INTEGER NOT NULL REFERENCES ai_archives(channel) ON DELETE CASCADE,
            id INTEGER NOT NULL, author TEXT NOT NULL, body TEXT NOT NULL, searchable TEXT NOT NULL,
            PRIMARY KEY(channel,id));
        CREATE INDEX IF NOT EXISTS ai_message_authors ON ai_messages(channel,author,id);
    """)
    # Produkční SQLite podporuje FTS5. Na sestavení bez něj funguje vyhledání přes instr().
    fresh = not conn.execute("SELECT 1 FROM sqlite_master WHERE name='ai_terms'").fetchone()
    try:
        conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS ai_terms USING fts5(
            searchable, content='ai_messages', content_rowid='rowid')""")
    except sqlite3.OperationalError as exc:
        if "no such module: fts5" in str(exc):
            return
        raise
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS ai_terms_insert AFTER INSERT ON ai_messages BEGIN
            INSERT INTO ai_terms(rowid,searchable) VALUES(new.rowid,new.searchable);
        END;
        CREATE TRIGGER IF NOT EXISTS ai_terms_delete AFTER DELETE ON ai_messages BEGIN
            INSERT INTO ai_terms(ai_terms,rowid,searchable) VALUES('delete',old.rowid,old.searchable);
        END;
        CREATE TRIGGER IF NOT EXISTS ai_terms_update AFTER UPDATE OF searchable ON ai_messages BEGIN
            INSERT INTO ai_terms(ai_terms,rowid,searchable) VALUES('delete',old.rowid,old.searchable);
            INSERT INTO ai_terms(rowid,searchable) VALUES(new.rowid,new.searchable);
        END;
    """)
    if fresh:
        conn.execute("INSERT INTO ai_terms(ai_terms) VALUES('rebuild')")


def registered(guild):
    return db.connect().execute("SELECT * FROM ai_archives WHERE guild=? ORDER BY channel", (guild,)).fetchall()


def register(guild, channel, names):
    db.connect().execute("""INSERT INTO ai_archives(guild,channel,names) VALUES(?,?,?)
        ON CONFLICT(channel) DO UPDATE SET names=excluded.names""", (guild, channel, names))


def rows_for(message, bot_id):
    body = message.clean_content.strip()
    if message.is_system() or message.author.id == bot_id:
        body = ""
    return (message.channel.id, message.id, message.author.display_name if body else "", body, normalize(body))


def insert_batch(rows, *, replace=False):
    on_conflict = ("DO UPDATE SET author=excluded.author,body=excluded.body,searchable=excluded.searchable"
                   if replace else "DO NOTHING")
    with db.transaction() as conn:
        conn.executemany("INSERT INTO ai_messages(channel,id,author,body,searchable) VALUES(?,?,?,?,?) "
                         "ON CONFLICT(channel,id) " + on_conflict, rows)


def erase(channel, ids):
    # Prázdný řádek zabrání obnovení zprávy ze souběžně načtené stránky.
    insert_batch([(channel, mid, "", "", "") for mid in ids], replace=True)


def capabilities_question(question):
    return bool(re.fullmatch(r"(?:ahoj )?(?:arion(?:ai)? )?(?:co (?:vsechno )?(?:umis|dokazes|zvladas)|"
                             r"jake (?:mas funkce|jsou tve schopnosti))(?: arion(?:ai)?)?", " ".join(words(question))))


STOP = set("""co kdy kde kdo jak proc prvni poprve naposled naposledy posledni posledne nedavno
              byl byla bylo byli je se si to na do ve ze za pro jen jaky jsem jsme mi vse vsechno
              shrn rekni popis strucne lorove lore zazil stalo potkal potkala setkal znamena
              zkratka zkratku slovo pribehu jake jsou jeho jeji scene scena mezi archiv archivu""".split())


def lookup_terms(question, phrase, names):
    """Téma neřízeného hledání. Scénové dotazy ponechá výběru děje v archivu postavy."""
    if phrase.strip():
        return [normalize(phrase.strip())]
    q = " ".join(words(question))
    match = re.search(r"\b(?:kdo (?:je|byl|byla)|co (?:vis|vime|znas|se vi) o|co o|"
                      r"(?:informace|zminky|neco|vsechno) o|co je zac|"
                      r"(?:vyhledej|dohledej|najdi)(?: mi)?) (.+)", q)
    aliases = set()
    for group in names:
        if any(alias_match(name, question) for name in group):
            aliases.update(normalize(name.strip()) for name in group if name.strip())
    if not match and any(w.startswith(("naposled", "posledn", "poprve", "prvni")) for w in q.split()):
        return []
    if aliases:
        return sorted(aliases)[:10]
    if match:
        tokens = [w for w in match[1].split() if w not in STOP and w not in {"vis", "vime", "vlastne", "znas"} and len(w) > 1]
        return [re.sub(r"(ovi|em|ou|a|u)$", "", w) if len(w) > 3 else w for w in tokens[:6]]
    return []


def select_scene(channel, question, phrase, aliases, before_id, conn=None, *, subject=()):
    """Najde kotvy a doplní sousední zprávy. Pořadí Discord ID odpovídá času."""
    conn = db.connect() if conn is None else conn
    q = words(question)
    first = "poprve" in q or "nejdrive" in q or any(w.startswith("prvni") for w in q)
    latest = "nedavno" in q or any(w.startswith(("naposled", "posledn", "nejnovej")) for w in q)
    terms = [w for w in q if len(w) >= 3 and w not in STOP
             and not any(alias_match(alias, w) for alias in aliases)]
    short = [normalize(token) for token in re.findall(r"\b[^\W\d_]{2,8}\b", question)
             if token.isupper() and normalize(token) not in {normalize(n.strip()) for n in aliases}]
    if not short and "zkratka" in q:
        pos = q.index("zkratka") + 1
        short = q[pos:pos+1]
    if subject:
        terms = list(subject)
    elif phrase.strip():
        terms = [normalize(phrase.strip())]
    elif short:
        terms = short
    elif latest:
        terms = []
    else:
        terms = [re.sub(r"(ovi|em|ou|a|u|i)$", "", w) if len(w) > 3 else w for w in terms]
    terms = list(dict.fromkeys(terms))[:10]
    scope = "channel=? AND id<? AND body<>''"
    params = (channel.id, before_id)
    direction = "ASC" if first else "DESC"
    fulltext = terms and not phrase.strip() and conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='ai_terms'").fetchone()
    if fulltext:
        # Pouze normalizovaná slova; zkratka vyžaduje celé slovo, jména připouštějí koncovku.
        quoted = ['"' + term.replace('"', '""') + '"' for term in terms]
        expression = " OR ".join(term + ("" if short and not subject else "*") for term in quoted)
        order = "m.id ASC" if first else "rank, m.id DESC"
        anchors = conn.execute(f"""SELECT m.id FROM ai_terms JOIN ai_messages m ON m.rowid=ai_terms.rowid
            WHERE ai_terms MATCH ? AND m.channel=? AND m.id<? ORDER BY {order} LIMIT 5""",
                               (expression, *params)).fetchall()
    elif terms:
        score = "+".join("(instr(searchable,?)>0)" for _ in terms)
        order = "id ASC" if first else "score DESC,id DESC"
        anchors = conn.execute(f"SELECT id,({score}) AS score FROM ai_messages WHERE {scope} "
                               f"AND score>0 ORDER BY {order} LIMIT 5", (*terms, *params)).fetchall()
    else:
        # Označená domluva hráčů může pokračovat dlouho po skončení scény.
        scene_scope = scope + " AND ltrim(searchable) NOT LIKE 'ooc:%' AND ltrim(body) NOT LIKE '//%' AND ltrim(body) NOT LIKE '((%'"
        anchors = conn.execute(f"SELECT id FROM ai_messages WHERE {scene_scope} ORDER BY id {direction} LIMIT 36",
                               params).fetchall()
    ids = {row["id"] for row in anchors}
    if subject and not phrase.strip():
        # Repliky podepsané jménem postavy často neobsahují její jméno v textu.
        authors = conn.execute("SELECT DISTINCT author FROM ai_messages WHERE channel=?", (channel.id,))
        names = [r["author"] for r in authors if any(alias_match(t, r["author"]) for t in subject)][:32]
        if names:
            slots = ",".join("?" for _ in names)
            ids.update(r["id"] for r in conn.execute(
                f"SELECT id FROM ai_messages WHERE {scope} AND author IN ({slots}) ORDER BY id {direction} LIMIT 4",
                (*params, *names)))
    if terms:
        for row in anchors:
            for op, order in (("<", "DESC"), (">", "ASC")):
                nearby = conn.execute(f"SELECT id FROM ai_messages WHERE {scope} AND id{op}? "
                                      f"ORDER BY id {order} LIMIT 2", (*params, row["id"]))
                ids.update(r["id"] for r in nearby)
    if not ids:
        return []
    slots = ",".join("?" for _ in ids)
    rows = conn.execute(f"SELECT * FROM ai_messages WHERE channel=? AND id IN ({slots}) ORDER BY id",
                        (channel.id, *ids))
    records = []
    for row in rows:
        positions = [row["searchable"].find(t) for t in terms if t in row["searchable"]]
        start = max(0, min(positions, default=0) - 180)
        records.append(dict(autor=row["author"], text=row["body"][start:start+650],
                            datum_utc=message_date(row["id"]),
                            zdroj=f"https://discord.com/channels/{channel.guild.id}/{channel.id}/{row['id']}"))
    return records


def message_date(message_id):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(((message_id >> 22) + 1420070400000) / 1000,
                                  timezone.utc).strftime("%Y-%m-%d")


def coverage(channel_id, complete):
    row = db.connect().execute("SELECT min(id),max(id),count(*) FROM ai_messages WHERE channel=? AND body<>''",
                               (channel_id,)).fetchone()
    status = "Index celé dostupné historie." if complete else "Index je zatím neúplný."
    if row[2]:
        return f"{status} {row[2]} textů ({message_date(row[0])} až {message_date(row[1])} UTC)."
    return status
