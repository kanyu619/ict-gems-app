#!/usr/bin/env python3
"""ICT Gems App – Generator.

Baut aus der ICT Gems Bibliothek (Obsidian-Vault) die Handy-App (eine HTML-Datei).
Aufruf:  python3 gems_app_build.py <Vault-Pfad> <Ausgabe-Ordner>
Erzeugt: <Ausgabe>/ict-gems-app.html, <Ausgabe>/ICT Gems App.md, <Ausgabe>/bericht.json

Regel: Nur Inhalte aus den Karten. Fehlendes -> "— fehlt in Karte". *Deutung:* und Offen -> ⚠️.
"""
import base64, datetime, hashlib, html, json, os, re, sys

VAULT, OUT = sys.argv[1], sys.argv[2]
LIB = os.path.join(VAULT, "Trading", "ICT Gems Bibliothek")
HERE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(OUT, exist_ok=True)

def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()

# ---------- Hilfen ----------
def frontmatter(md):
    m = re.match(r"^---\n(.*?)\n---\n", md, re.S)
    fm = {}
    if not m:
        return fm, md
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip() for x in v[1:-1].split(",") if x.strip()]
        fm[k.strip()] = v
    return fm, md[m.end():]

def inline(t):
    """Markdown-Inline -> HTML (fett, kursiv, Wikilinks). *Deutung:* -> ⚠️-Tag."""
    t = html.escape(t.strip(), quote=False)
    t = re.sub(r"\[\[([^\]|]+)\\?\|([^\]]+)\]\]", r"\2", t)
    t = re.sub(r"\[\[([^\]]+)\]\]", r"\1", t)
    t = re.sub(r"\*Deutung:\*", '<span class="tag-d">⚠️ Deutung</span>', t)
    t = re.sub(r"\*Mein Plan:\*", '<span class="tag-p">Mein Plan</span>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    return t

def plain(t):
    return re.sub(r"<[^>]+>", "", inline(t))

def sections(body):
    out, cur = {}, None
    for line in body.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return out

def find_sec(secs, key):
    for k, v in secs.items():
        if key.lower() in k.lower():
            return v
    return []

def callouts(body):
    res, cur = [], None
    for line in body.splitlines():
        m = re.match(r"^>\s*\[!(\w+)\]([-+]?)\s*(.*)$", line)
        if m:
            cur = {"type": m.group(1), "title": m.group(3).strip(), "body": []}
            res.append(cur)
        elif line.startswith(">") and cur is not None:
            cur["body"].append(line[1:].strip())
        else:
            cur = None
    return res

def table(lines):
    rows = []
    for l in lines:
        l = l.strip()
        if not l.startswith("|"):
            continue
        l = l.replace("\\|", "\u0001")
        cells = [c.strip().replace("\u0001", "|") for c in l.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    return rows

MISSING_RX = re.compile(r"^(–|-|—)?$|nicht genannt|keine angabe", re.I)

def trade_field(raw):
    """-> {html, missing, deutung}"""
    parts = [p.strip() for p in raw.split(" · ")]
    missing = False
    keep = []
    for p in parts:
        if MISSING_RX.search(p.strip()):
            missing = True
        else:
            keep.append(p)
    deut = "*Deutung:*" in raw
    return {
        "html": " · ".join(inline(p) for p in keep),
        "missing": missing or not keep,
        "deutung": deut,
        "onlyDeutung": bool(keep) and all("*Deutung:*" in p for p in keep),
    }

TF_RX = re.compile(r"alle Timeframes|\b(?:M1|M5|M15|M30|H1|H4|Daily|Weekly)\b|\d+\s?-?min", re.I)
# Uhrzeiten immer zweistellig (07:00–09:00); Video-Zeitstempel wie 0:10–0:15 sind keine Fenster
WIN_RX = re.compile(r"(?<![\d:])(\d{2}:\d{2})\s*[–-]\s*(\d{2}:\d{2})(?!\d)")

def svg_uri(name):
    p = os.path.join(LIB, "Bilder", name)
    if not os.path.exists(p):
        return None
    s = read(p)
    s = re.sub(r"<metadata>.*?</metadata>", "", s, flags=re.S)
    return "data:image/svg+xml;base64," + base64.b64encode(s.encode("utf-8")).decode()

# ---------- Landkarte ----------
index_md = read(os.path.join(LIB, "ICT Gems Bibliothek.md"))
stufen = []
# Nur Hauptknoten A–E (ein Buchstabe) sind Stufen; Unterknoten wie C1, D4 haben Ziffern
for node, label in re.findall(r'(?<![\w])([A-Z])\["([^"]+)"\]', index_md):
    name, _, sub = label.partition("<br/>")
    icon, _, nm = name.strip().partition(" ")
    if nm in [s["name"] for s in stufen]:
        continue
    if not sub:  # Unterknoten wie SIBI/IOFED
        continue
    stufen.append({"name": nm.strip(), "icon": icon, "frage": sub.strip()})

# ---------- Video-Notizen (Quelle, Link, Kernaussage, Regeln mit Zeitstempel) ----------
videos = {}
vdir = os.path.join(LIB, "Videos")
if os.path.isdir(vdir):
    for vf in sorted(os.listdir(vdir)):
        if not vf.endswith(".md"):
            continue
        vmd = read(os.path.join(vdir, vf))
        vfm, vbody = frontmatter(vmd)
        vsecs = sections(vbody)
        stem = vf[:-3]
        datum, _, vtitle = stem.partition(" – ")
        kern = next((" ".join(c["body"]) for c in callouts(vbody) if "kernaussage" in c["title"].lower()), "")
        regeln = [{"r": inline(r[0]), "t": r[1]} for r in table(find_sec(vsecs, "Regeln"))[1:] if len(r) >= 2]
        videos[stem] = {"name": stem, "datum": datum, "titel": vtitle or stem, "url": str(vfm.get("quelle", "")),
                        "kanal": str(vfm.get("kanal", "ICT Gems")), "orig": str(vfm.get("original-quelle", "")),
                        "laenge": str(vfm.get("länge", "")), "kern": inline(kern), "regeln": regeln}

VIDEO_LINK_RX = re.compile(r"\[\[(\d{4}-\d{2}-\d{2} – [^\]|]+)(?:\|[^\]]*)?\]\]")
QUESTION_RX = re.compile(r"(?:Backtest[^:?.\n]*:|prüfen:|Prüffrage[^:?.\n]*:)\s*([^?.\n]+\?)")

# ---------- Konzepte ----------
concepts, gaps = [], {}
kdir = os.path.join(LIB, "Konzepte")
for fn in sorted(os.listdir(kdir)):
    if not fn.endswith(".md") or fn.startswith("_"):
        continue
    md = read(os.path.join(kdir, fn))
    fm, body = frontmatter(md)
    secs = sections(body)
    cos = callouts(body)
    title = re.search(r"^# (.+)$", body, re.M).group(1).strip()
    m = re.search(r"\(([^)]+)\)\s*$", title)
    abk = m.group(1) if m else (fm.get("aliases") or [title])[0]
    name = re.sub(r"\s*\([^)]+\)\s*$", "", title)
    if len(abk) > 14:  # Klammerzusatz ist keine Abkürzung (z. B. „Konsolidierung ≠ Akkumulation“) -> Name groß, Zusatz klein
        abk, name = name, title
    cid =re.sub(r"[^a-z0-9]", "", abk.lower()) or re.sub(r"[^a-z0-9]", "", name.lower())[:12]

    satz = next((" ".join(c["body"]) for c in cos if "einem satz" in c["title"].lower()), "")
    emb = re.search(r"!\[\[([^\]]+\.svg)\]\]", body)
    svg_name = emb.group(1) if emb else fn[:-3] + ".svg"
    svg = svg_uri(svg_name)

    # Tabelle darf mehr als 3 Spalten haben (z. B. Silver Bullet: Fenster | Deutsche Zeit | Für dich):
    # weitere Spalten werden mit ihrer Überschrift angehängt, nichts geht verloren.
    srows = table(find_sec(secs, "So läuft"))
    shead = srows[0] if srows else []
    steps = []
    for r in srows[1:]:
        if len(r) < 3:
            continue
        see = inline(r[2])
        for i in range(3, len(r)):
            if r[i].strip():
                lab = shead[i].strip() if i < len(shead) and shead[i].strip() else ""
                see += " · " + ((inline(lab) + ": ") if lab else "") + inline(r[i])
        steps.append({"n": r[0], "name": inline(r[1]), "see": see, "no": "❌" in " ".join(r)})
    steps_note = [inline(l) for l in find_sec(secs, "So läuft")
                  if l.strip() and not l.strip().startswith("|")]

    # Weitere Abschnitte der Karte (z. B. „Richtig einzeichnen“) mit eigenen Skizzen – 1:1 übernommen
    KNOWN = ("so läuft", "checkliste", "trade auf", "zeit")
    extra = []
    for sk, sl in secs.items():
        if any(k in sk.lower() for k in KNOWN):
            continue
        imgs, items = [], []
        for l in sl:
            l = l.strip()
            if not l:
                continue
            m2 = re.search(r"!\[\[([^\]]+\.svg)\]\]", l)
            if m2:
                u = svg_uri(m2.group(1))
                if u:
                    imgs.append(u)
                continue
            items.append(inline(re.sub(r"^-\s*", "", l)))
        if imgs or items:
            extra.append({"title": inline(sk), "svgs": imgs, "items": items})

    checks = [inline(re.sub(r"^- \[ \]\s*", "", l.strip()))
              for l in find_sec(secs, "Checkliste") if l.strip().startswith("- [ ]")]

    trows = table(find_sec(secs, "Trade auf einen Blick"))
    trade = {}
    if len(trows) >= 2:
        keys = ["entry", "sl", "tp", "inv"]
        for i, k in enumerate(keys):
            trade[k] = trade_field(trows[1][i] if i < len(trows[1]) else "")
    else:
        for k in ["entry", "sl", "tp", "inv"]:
            trade[k] = {"html": "", "missing": True, "deutung": False, "onlyDeutung": False}

    zeit_lines = [re.sub(r"^-\s*", "", l.strip()) for l in find_sec(secs, "Zeit") if l.strip().startswith("-")]
    tfs, windows, zeit_notes = [], [], []
    for l in zeit_lines:
        is_d = "*Deutung:*" in l
        # "Timeframe nicht genannt. Der Chart zeigt eine 60-min-FVG …" -> kein Timeframe-Chip
        if not re.search(r"timeframe[^.]*nicht genannt", l, re.I):
            for t in TF_RX.findall(l):
                label = "alle TF" if t.lower().startswith("alle") else t
                tfs.append({"t": label, "d": is_d})
        if not is_d:
            for a, b in WIN_RX.findall(l):
                windows.append([a, b])
        zeit_notes.append(inline(l))
    # Zeitfenster stehen in der Ablauf-Tabelle (Silver Bullet: „Fenster siehe oben“):
    # Zeilen, die die Karte selbst mit ❌ markiert, zählen nicht für den Jetzt-Filter.
    if not windows:
        for r in srows[1:]:
            if len(r) >= 2 and "❌" not in " ".join(r):
                for a, b in WIN_RX.findall(r[1]):
                    windows.append([a, b])
    # Duplikate raus
    seen, tfu = set(), []
    for t in tfs:
        if (t["t"], t["d"]) not in seen:
            seen.add((t["t"], t["d"])); tfu.append(t)

    plan_c = next((c for c in cos if "plan" in c["title"].lower()), None)
    plan_lines = [l for l in (plan_c["body"] if plan_c else []) if l.strip()]
    first = re.sub(r"[*_]", "", plan_lines[0]).strip().lower() if plan_lines else ""
    pf = str(fm.get("plan", "")).strip().lower()
    if pf in ("passt", "passt nicht"):
        plan_status = pf
    elif first.startswith("nein"):
        plan_status = "passt nicht"
    elif first.startswith("ja") or first.startswith("nur") or first.startswith("teilweise"):
        plan_status = "passt"      # „Nur mit …“, „Nur eingeschränkt“, „Teilweise“ -> passt (bedingt)
    elif re.search(r"\bja\b", first.split(".")[0]) and not re.search(r"\bnein\b", first.split(".")[0]):
        plan_status = "passt"      # z. B. „**Fenster 2 ja**, die anderen kaum.“ -> passt (bedingt)
    else:
        plan_status = "unklar"
    plan_bedingt = plan_status == "passt" and not first.startswith("ja")

    video_c = next((c for c in cos if c["type"] == "example"), None)
    detail_c = next((c for c in cos if c["type"] == "note"), None)
    detail_items, unklar = [], []
    for l in (detail_c["body"] if detail_c else []):
        l = re.sub(r"^-\s*", "", l).strip()
        if not l:
            continue
        if re.match(r"\*\*Offen:?\*\*", l) or l.lower().startswith("offen"):
            unklar.append(inline(re.sub(r"^\*\*Offen:?\*\*:?\s*", "", l)))
        else:
            detail_items.append(inline(l))
    # weitere Unklar-Hinweise aus Trade-Feldern
    for k, lab in [("inv", "❌ ungültig wenn")]:
        raw = trows[1][3] if len(trows) >= 2 and len(trows[1]) > 3 else ""
        if "nicht" in raw and "geklärt" in raw:
            unklar.append(inline(lab + ": " + raw))

    aliases = fm.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    stufe = fm.get("stufe", "")
    bt = str(fm.get("backtest", "ungetestet")).strip().lower()

    # Videos der Karte: alle Video-Wikilinks in Reihenfolge, Zeitstempel aus der Quellen-Zeile
    vnames, vts = [], {}
    for vn in VIDEO_LINK_RX.findall(body):
        if vn not in vnames:
            vnames.append(vn)
    qline = next((l for l in (detail_c["body"] if detail_c else []) if "Quellen" in l), "")
    for vn, ts in re.findall(r"\[\[(\d{4}-\d{2}-\d{2} – [^\]|]+)(?:\|[^\]]*)?\]\]\s*@\s*([^·\n]+)", qline):
        vts[vn] = ts.strip()
    cvideos = []
    for vn in vnames:
        v = videos.get(vn)
        if v:
            cvideos.append({**v, "ts": vts.get(vn, "")})
        else:
            dat, _, tit = vn.partition(" – ")
            cvideos.append({"name": vn, "datum": dat, "titel": tit or vn, "url": "", "kanal": "", "orig": "",
                            "laenge": "", "kern": "", "regeln": [], "ts": vts.get(vn, "")})
    # Quelle: ICT Gems, außer die Karte sagt „Quelle … nicht … ICT Gems (Kanal)“
    allp = " ".join(plan_lines + (detail_c["body"] if detail_c else []))
    mq = re.search(r"Quelle[^.\n]*?nicht[^.\n]*?ICT Gems\s*\(([^)]+)\)", re.sub(r"[*_]", "", allp))
    quelle = mq.group(1).strip() if mq else "ICT Gems"
    # Backtest-Prüffragen aus der Karte (nur Sätze mit Fragezeichen hinter „Backtest…:“ / „prüfen:“)
    fragen = [inline(q.strip()) for q in QUESTION_RX.findall(re.sub(r"[*_]", "", allp))]

    src_hash = hashlib.sha1((md + (svg or "")).encode()).hexdigest()[:8]

    lack = []
    for k, lab in [("entry", "Entry"), ("sl", "SL"), ("tp", "TP"), ("inv", "Ungültig")]:
        if trade[k]["missing"]:
            lack.append(lab + (" (nur Deutung)" if trade[k]["html"] else ""))
        elif trade[k]["onlyDeutung"]:
            lack.append(lab + " (nur Deutung)")
    if not windows:
        lack.append("Zeitfenster")
    if not tfu:
        lack.append("Timeframes")
    if not checks:
        lack.append("Checkliste")
    if not svg:
        lack.append("Skizze")
    if plan_status == "unklar":
        lack.append("Plan-Abgleich")
    gaps[abk] = lack

    concepts.append({
        "id": cid, "name": name, "abk": abk, "file": fn[:-3], "aliases": aliases,
        "stufe": stufe, "backtest": bt, "videos": fm.get("videos", ""),
        "satz": inline(satz), "svg": svg, "steps": steps, "stepsNote": steps_note,
        "checks": checks, "trade": trade, "tfs": tfu, "windows": windows,
        "zeitNotes": zeit_notes, "plan": plan_status, "planBedingt": plan_bedingt,
        "planLines": [inline(l) for l in plan_lines],
        "video": [inline(l) for l in (video_c["body"] if video_c else []) if l],
        "details": detail_items, "unklar": unklar, "hash": src_hash, "lack": lack,
        "extra": extra, "videos": cvideos, "quelle": quelle, "fragen": fragen,
    })

# ---------- Fehlermuster (3 häufigste, Zahlen aus der Notiz geprüft) ----------
fm_md = read(os.path.join(VAULT, "Trading", "Fehlermuster FTMO-Trades.md"))
plan_md = read(os.path.join(VAULT, "Trading", "Trading-Plan ab 15.10.2026.md"))
FEHLER = [
    ("Entry ohne M5-MSS?", "78 von 97 Trades ohne MSS", "78 von 97"),
    ("Gegen die Tagesrichtung?", "Fading: 67 Trades · 22 % · −4.637 €", "67 Trades, 22 % Trefferquote, −4.637 €"),
    ("Teil-TP schon in der Order?", "70 % der Verlierer waren vorher ≥ 20 Pkt im Plus", "70 % der Verlierer waren vorher ≥ 20 Pkt im Plus"),
]
fehler = []
for q, sub, must in FEHLER:
    if must in fm_md:
        fehler.append({"q": q, "sub": sub})
    else:
        print("WARNUNG Fehlermuster nicht mehr in Notiz:", must)

PLAN = {
    "windows": [
        {"name": "NY AM", "from": "09:30", "to": "11:00", "note": "an 08:30-News-Tagen ab 08:45"},
        {"name": "NY PM", "from": "13:30", "to": "16:00", "note": "nur A+"},
    ],
    "hinweise": [
        "Ohne M5-MSS kein Trade.",
        "London nur am Desktop – am Handy keine neuen Trades.",
        "Vor High-Impact-News (CPI, NFP, FOMC, PPI) keine neue Position.",
        "Nach 2 Verlusten oder −1.200 € ist der Tag vorbei. Max. 3 Trades.",
    ],
}
for must in ["NY AM 09:30–11:00", "NY PM 13:30–16:00 nur A+", "Am Handy keine neuen Trades",
             "Ohne M5-MSS kein Trade", "Nach 2 Verlusten oder −1.200 € ist der Tag vorbei", "Max. 3 Trades pro Tag"]:
    if must not in plan_md:
        print("WARNUNG Plan-Text geändert:", must)

now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=2)))
stand = now.strftime("%d.%m.%Y %H:%M")
DATA = {"stand": stand, "stufen": stufen, "concepts": concepts, "fehler": fehler, "plan": PLAN}

tpl = read(os.path.join(HERE, "gems_app_template.html"))
out_html = tpl.replace("/*__DATA__*/null", json.dumps(DATA, ensure_ascii=False))
with open(os.path.join(OUT, "ict-gems-app.html"), "w", encoding="utf-8") as f:
    f.write(out_html)

# ---------- Diff zum letzten Stand ----------
old = {}
note_p = os.path.join(LIB, "ICT Gems App.md")
if os.path.exists(note_p):
    for abk, h in re.findall(r"^\|\s*\[\[[^\]|]+\\?\|?([^\]]*)\]\][^\n]*`([0-9a-f]{8})`", read(note_p), re.M):
        old[abk] = h
neu = [c["abk"] for c in concepts if c["abk"] not in old] if old else [c["abk"] for c in concepts]
geaendert = [c["abk"] for c in concepts if c["abk"] in old and old[c["abk"]] != c["hash"]]
entfernt = [a for a in old if a not in [c["abk"] for c in concepts]]

report = {"stand": stand, "anzahl": len(concepts), "neu": neu, "geaendert": geaendert,
          "entfernt": entfernt, "ausgeblendet": [c["abk"] for c in concepts if c["plan"] == "passt nicht"],
          "luecken": gaps}
with open(os.path.join(OUT, "bericht.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)
print(json.dumps(report, ensure_ascii=False, indent=1))

# ---------- Vault-Notiz "ICT Gems App.md" ----------
URL = sys.argv[3] if len(sys.argv) > 3 else "(noch nicht veröffentlicht)"
def trade_missing(c):
    return any(k in c["lack"] or (k + " (nur Deutung)") in c["lack"] for k in ("SL", "TP"))
rows = []
for c in concepts:
    pl = c["plan"] + (" (bedingt)" if c["planBedingt"] else "")
    rows.append(f"| [[{c['file']}\\|{c['abk']}]] | {c['stufe'] or '–'} | {c['backtest']} | {pl} | "
                f"{', '.join(c['lack']) or '–'} | `{c['hash']}` |")
aend = []
if neu: aend.append("neu: " + ", ".join(neu))
if geaendert: aend.append("geändert: " + ", ".join(geaendert))
if entfernt: aend.append("entfernt: " + ", ".join(entfernt))
note = f"""---
tags: [trading, ict-gems, app]
stand: {now.strftime('%Y-%m-%d')}
link: https://kanyu619.github.io/ict-gems-app/
artifact: {URL}
repo: https://github.com/kanyu619/ict-gems-app
---
# ICT Gems App

Gehört zu [[ICT Gems Bibliothek]] · Regeln: [[Trading-Plan ab 15.10.2026]] · Fehler-Leiste aus [[Fehlermuster FTMO-Trades]]
**Kernaussage:** Handy-App zum 10-Sekunden-Abgleich am Live-Chart: Passt das Bild zu einem Konzept – ja/nein? **Abgleich-Werkzeug, kein Signalgeber.**

**Handy-App (installierbar, offline):** https://kanyu619.github.io/ict-gems-app/ · Android: Chrome → ⋮ → „App installieren“
**Artifact-Link (claude.ai, Vorschau):** {URL}
**Stand:** {stand} · **{len(concepts)} Konzepte** · Letzte Änderung: {'; '.join(aend) or 'keine'}

## Enthaltene Konzepte
| Konzept | Stufe | Backtest | Plan | Lücken in der Karte | Hash |
|---|---|---|---|---|---|
""" + "\n".join(rows) + f"""

Ausgeblendet (Plan passt nicht): {', '.join(report['ausgeblendet']) or 'keins'}

## Quelle und Videos je Konzept
| Konzept | Quelle | Videos |
|---|---|---|
""" + "\n".join(f"| {c['abk']} | {c['quelle']}{' ⚠️' if c['quelle'] != 'ICT Gems' else ''} | " +
                 (" · ".join(f"[[{v['name']}]]" + (f" @ {v['ts']}" if v['ts'] else "") for v in c['videos']) or '–') + " |"
                 for c in concepts) + f"""

## Backtest-Lab – Prüffragen aus den Karten
""" + ("\n".join(f"- [ ] **{c['abk']}** ({c['plan']}{' bedingt' if c['planBedingt'] else ''}): {plain(q)}" for c in concepts for q in c['fragen']) or "- keine") + f"""
- Ohne Prüffrage in der Karte: {', '.join(c['abk'] for c in concepts if not c['fragen']) or 'keins'}

## So funktioniert die App
- Startseite: Kacheln nach Stufe der Landkarte, Badges Backtest + Plan. „Plan: passt nicht“ ist ausgeblendet (Schalter „alle zeigen“). Suche findet Namen + aliases.
- **Jetzt-Filter:** Karte nennt eine Zeit → sie zählt nur innerhalb der Plan-Fenster NY AM 09:30–11:00 / NY PM 13:30–16:00 (nur A+); Fenster außerhalb des Plans stehen als Chip mit ⚠️ „außerhalb Plan“. Karte nennt keine Zeit → Plan-Fenster. Zeilen, die die Karte mit ❌ markiert (Silver Bullet London/07–09), zählen nicht. Umrechnung nach Berlin automatisch, auch in der Zeitumstellungs-Woche.
- Konzept-Ansicht: Skizze (Vollbild per Tipp), Checkliste → Ampel unten, Trade auf einen Blick, Zeit-Chips, Plan-Box rot, Rest eingeklappt.
- „— fehlt in Karte“ = steht nicht in der Karte. ⚠️ Deutung / ⚠️ Unklar = aus der Karte übernommen.
- Fehler-Leiste (3 häufigste aus [[Fehlermuster FTMO-Trades]]): Entry ohne M5-MSS (78 von 97) · Gegen die Tagesrichtung (67 Trades) · Teil-TP nicht gesichert (70 % der Verlierer vorher ≥ 20 Pkt im Plus).
- Offline: Die installierte Handy-App (GitHub Pages) läuft komplett offline. Das Repo ist öffentlich: Wer den Link kennt, sieht Karten + Fehlermuster (keine Kontodaten).

## Aktualisieren – „Gems-App aktualisieren“
1. Claude liest Index, alle `Konzepte/*.md`, `Bilder/*.svg`, Trading-Plan, Fehlermuster.
2. `App/gems_app_build.py` erzeugt die App neu aus `App/gems_app_template.html` und vergleicht mit der Hash-Spalte oben (neu/geändert).
3. Inhalt von `out/pwa/` ins GitHub-Repo `kanyu619/ict-gems-app` (Branch main) pushen → Handy-App aktualisiert sich beim nächsten Öffnen mit Netz. Artifact-Link wird ebenfalls überschrieben, diese Notiz + Logbuch werden aktualisiert.
4. Meldung: neue/geänderte Konzepte + Karten mit Lücken.
- Karte kann den Plan-Status fest vorgeben mit `plan: passt` oder `plan: passt nicht` im YAML-Kopf. Sonst liest die App den ersten Satz der Plan-Box („Ja“ / „Nur mit …“ = passt, „Nein“ = passt nicht, „… ja, …“ wie „Fenster 2 ja“ = passt (bedingt)).
- Weitere `##`-Abschnitte einer Karte (z. B. „Richtig einzeichnen“ mit zweiter Skizze) erscheinen eingeklappt in der Konzept-Ansicht.
- **Aus den Videos:** Jede Konzept-Ansicht zeigt die Quelle (ICT Gems oder anderer Kanal, dann ⚠️) und alle Video-Notizen der Karte als Chips (Datum, Titel, Zeitstempel). Antippen öffnet Kernaussage + Regeln der Video-Notiz, Link führt zum YouTube-Short. „So erkennst du es“ = Ablauf-Tabelle der Karte, offen sichtbar. Ohne Marke = aus dem Video, ⚠️ Deutung = Auslegung, „Mein Plan“ = eigene Regel.
- **Backtest-Lab (Startseite unten):** flache Liste aller Prüffragen aus den Karten (Sätze hinter „Backtest…:“ oder „prüfen:“ mit Fragezeichen) mit Plan-Status.

## Offen
- [ ] SL und TP fehlen in: {', '.join(c['abk'] for c in concepts if trade_missing(c)) or 'keiner'} – kommen erst mit weiteren Videos oder eigenem Backtest.
- [ ] Zeitfenster fehlen in: {', '.join(c['abk'] for c in concepts if 'Zeitfenster' in c['lack']) or 'keiner'}.

Zurück: [[ICT Gems Bibliothek]] · [[00 Start]]
"""
with open(os.path.join(OUT, "ICT Gems App.md"), "w", encoding="utf-8") as f:
    f.write(note)

# ---------- Installierbare App (PWA) für GitHub Pages: out/pwa/ ----------
PWA = os.path.join(OUT, "pwa")
os.makedirs(PWA, exist_ok=True)
ver = hashlib.sha1(out_html.encode()).hexdigest()[:10]
head = ('<!doctype html><html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<meta name="theme-color" content="#0d1113"><link rel="manifest" href="manifest.webmanifest">'
        '<link rel="icon" href="icon-192.png"><link rel="apple-touch-icon" href="icon-192.png">'
        '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
        'body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style></head><body>')
tail = ('<script>if("serviceWorker" in navigator){addEventListener("load",()=>navigator.serviceWorker.register("sw.js"))}</script>'
        '</body></html>')
with open(os.path.join(PWA, "index.html"), "w", encoding="utf-8") as f:
    f.write(head + out_html + tail)
with open(os.path.join(PWA, "manifest.webmanifest"), "w", encoding="utf-8") as f:
    json.dump({"name": "ICT Gems App", "short_name": "ICT Gems", "lang": "de",
               "description": "Live-Abgleich: Chartbild gegen ICT-Gems-Konzeptkarten",
               "start_url": "./", "scope": "./", "display": "standalone", "orientation": "portrait",
               "background_color": "#0d1113", "theme_color": "#0d1113",
               "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
                         {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
                         {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]},
              f, ensure_ascii=False, indent=1)
with open(os.path.join(PWA, "sw.js"), "w", encoding="utf-8") as f:
    f.write(f"""// ICT Gems App – Offline-Speicher. Version {ver} (ändert sich bei jedem Neubau)
const C='gems-{ver}', CORE=['./','index.html','manifest.webmanifest','icon-192.png','icon-512.png'];
self.addEventListener('install',e=>{{e.waitUntil(caches.open(C).then(c=>c.addAll(CORE)));self.skipWaiting()}});
self.addEventListener('activate',e=>{{e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==C).map(x=>caches.delete(x)))));self.clients.claim()}});
self.addEventListener('fetch',e=>{{
  if(e.request.method!=='GET')return;
  if(e.request.mode==='navigate'){{ // neueste Version bei Netz, sonst gespeicherte
    e.respondWith(fetch(e.request).then(r=>{{caches.open(C).then(c=>c.put('index.html',r.clone()));return r}}).catch(()=>caches.match('index.html')));return}}
  e.respondWith(caches.match(e.request).then(m=>m||fetch(e.request).then(r=>{{const cp=r.clone();caches.open(C).then(c=>c.put(e.request,cp));return r}})));
}});
""")
from PIL import Image, ImageDraw
def icon(sz):
    im = Image.new("RGB", (sz, sz), "#0d1113"); d = ImageDraw.Draw(im); u = sz / 16
    # drei Kerzen: grün, rot, grün + orange Lücke (SIBI) – Farben wie in den Skizzen
    d.rectangle([5.2*u, 6.6*u, 10.8*u, 8.0*u], fill="#f59e0b")
    for x, top, bot, wt, wb, col in [(4.2, 7.6, 11.6, 6.4, 12.6, "#1f9d6b"), (7.4, 4.4, 9.6, 3.4, 10.4, "#d64545"), (10.6, 8.0, 10.8, 7.0, 11.8, "#1f9d6b")]:
        d.rectangle([(x+0.55)*u, wt*u, (x+0.85)*u, wb*u], fill=col)
        d.rounded_rectangle([x*u, top*u, (x+1.4)*u, bot*u], radius=0.2*u, fill=col)
    return im
for s in (192, 512):
    icon(s).save(os.path.join(PWA, f"icon-{s}.png"))
print("PWA:", sorted(os.listdir(PWA)), "Version", ver)
