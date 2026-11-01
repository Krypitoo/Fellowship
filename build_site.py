#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_site.py - transforme les fichiers builds_<heros>.json en un site d'une page.

Exemple :
  python build_site.py resultats/builds_*.json -o docs/index.html

Le site est un seul fichier HTML (donnees incluses), a ouvrir tel quel ou a publier
(GitHub Pages...). Il ne contient aucun identifiant de l'API.
"""
import argparse
import json
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "modele_site.html"

KNOWN_HEROES = ["Helena", "Meiko", "Xavian", "Gunde", "Tariq", "Mara",
                "Rime", "Elarion", "Ardeos", "Sylvie", "Vigour", "Aeona"]
# Noms de secours si le fichier de builds ne contient pas encore "encounterName"
ENCOUNTER_NAMES = {6: "Empyrean Sands", 7: "Cithrel's Fall"}

SLOT_GROUPS = [
    ("Arme", [13]), ("Tête", [0]), ("Cou", [1]), ("Épaules", [2]), ("Dos", [3]),
    ("Torse", [4]), ("Poignets", [5]), ("Mains", [6]), ("Taille", [7]), ("Pieds", [8]),
    ("Anneaux", [9, 10]), ("Orbes", [11, 12]),
]
SLOT_LABELS = {s: lab for lab, ss in SLOT_GROUPS for s in ss}
GEAR_SLOTS = set(range(14))           # 14 et 15 = potion, rez : ignores
SECONDARY = ["Crit", "Expertise", "Haste", "Spirit"]   # ordre d'affichage
SECONDARY_FR = {"Crit": "Critique", "Haste": "Hâte", "Expertise": "Expertise", "Spirit": "Esprit"}
MAIN_STATS = ["Strength", "Agility", "Intellect"]
MAIN_FR = {"Strength": "Force", "Agility": "Agilité", "Intellect": "Intelligence"}
GEM_KEYS = ["Sapphire", "Emerald", "Ruby", "Diamond", "Topaz", "Amethyst"]
GEM_TIERS = [125, 625, 1500]   # paliers de puissance de gemmes


def is_ench(name):
    return " / " in name


def clean(name):
    return " ".join(name.split())


def med(vals):
    return st.median(vals) if vals else None


def quart(vals):
    vals = sorted(vals)
    if len(vals) < 2:
        return (vals[0], vals[0]) if vals else (None, None)
    q = st.quantiles(vals, n=4, method="inclusive")
    return q[0], q[2]


def r1(x):
    return None if x is None else round(x, 1)


def stat(b, key):
    s = (b["info"].get("stats") or {}).get(key)
    if s is None:
        return None
    return s.get("max", s.get("min"))


def gear(b):
    return [g for g in (b["info"].get("gear") or [])
            if isinstance(g, dict) and g.get("slot") in GEAR_SLOTS and g.get("name")]


def pct(c, n):
    return round(100 * c / n, 1) if n else 0


def counted(counter, n, top=None):
    return [{"name": k, "pct": pct(c, n), "n": c} for k, c in counter.most_common(top)]


MAX_LEVEL = 8   # au-dela, regroupe dans la derniere colonne


def distribution(levels):
    """{niveau: nombre de builds}, niveaux > MAX_LEVEL regroupes."""
    d = Counter(min(int(round(v)), MAX_LEVEL) for v in levels)
    return {str(k): c for k, c in sorted(d.items())}


def level_table(per_build, n, top, with_dist=False):
    """per_build : liste de Counter {nom: total}. -> % builds, mediane et zone courante."""
    pres = Counter()
    for d in per_build:
        pres.update(k for k, v in d.items() if v > 0)
    out = []
    for name, c in pres.most_common(top):
        vals = [d[name] for d in per_build if d.get(name, 0) > 0]
        q1, q3 = quart(vals)
        row = {"name": name, "pct": pct(c, n), "n": c, "median": r1(med(vals)),
               "q1": r1(q1), "q3": r1(q3)}
        if with_dist:
            row["dist"] = distribution(vals)
        out.append(row)
    return out


def weapon_fx(builds):
    """Arme -> effet special (type 1024) qu'elle donne, par heros (le meme nom d'arme
    donne un effet different selon le heros)."""
    pairs = defaultdict(Counter)
    for b in builds:
        weapons = {clean(g["name"]) for g in gear(b) if g.get("slot") == 13 and g.get("name")}
        fx = {a["name"] for a in b["info"].get("artifact") or []
              if a.get("type") == 1024 and a.get("total", 0) >= 1 and a.get("name")}
        if len(weapons) == 1 and len(fx) == 1:
            pairs[next(iter(weapons))][next(iter(fx))] += 1
    return {w: c.most_common(1)[0][0] for w, c in pairs.items()}


def aggregate(builds):
    n = len(builds)
    A = {"n": n}
    scores = [b["score"] for b in builds if b.get("score") is not None]
    keys = [b["difficulty"] for b in builds if b.get("difficulty") is not None]
    A["score"] = [r1(min(scores)), r1(med(scores)), r1(max(scores))] if scores else None
    A["key"] = [min(keys), r1(med(keys)), max(keys)] if keys else None

    # Talents
    tc, combos = Counter(), Counter()
    for b in builds:
        names = sorted({t["name"] for t in b["info"].get("talents") or [] if t.get("name")})
        tc.update(names)
        combos[tuple(names)] += 1
    A["talents"] = counted(tc, n)
    A["talentCombos"] = [{"names": list(k), "pct": pct(c, n), "n": c}
                         for k, c in combos.most_common(4)]

    # Stats secondaires (valeur brute et %)
    sec = []
    for k in SECONDARY:
        raw = [v for v in (stat(b, k) for b in builds) if v is not None]
        pc = [v / 100 for v in (stat(b, k + "Percent") for b in builds) if v is not None]
        if not pc:
            continue
        q1, q3 = quart(raw)
        sec.append({"key": k, "label": SECONDARY_FR[k], "raw": r1(med(raw)),
                    "q1": r1(q1), "q3": r1(q3), "min": r1(min(raw)), "max": r1(max(raw)),
                    "pct": r1(med(pc))})
    A["secondary"] = sec

    other = []

    def add_other(label, v):
        if v:
            q1, q3 = quart(v)
            other.append({"label": label, "median": r1(med(v)), "q1": r1(q1), "q3": r1(q3),
                          "min": r1(min(v)), "max": r1(max(v))})
    for k in MAIN_STATS:
        add_other(MAIN_FR[k], [x for x in (stat(b, k) for b in builds) if x is not None])
    ilvl = []
    for b in builds:
        lv = [g.get("itemLevel") for g in gear(b) if g.get("itemLevel")]
        if lv:
            ilvl.append(sum(lv) / len(lv))
    add_other("Niveau d'objet moyen", ilvl)
    for k, lab in (("Stamina", "Endurance"), ("Health", "Points de vie"), ("Armor", "Armure")):
        add_other(lab, [x for x in (stat(b, k) for b in builds) if x is not None])
    A["otherStats"] = other

    # Gemmes : puissance par couleur + gemmes serties
    gp = []
    for k in GEM_KEYS:
        vals = [stat(b, k) or 0 for b in builds]
        if any(vals):
            q1, q3 = quart(vals)
            gp.append({"key": k, "median": r1(med(vals)), "q1": r1(q1), "q3": r1(q3),
                       "pct": pct(sum(1 for v in vals if v > 0), n)})
    A["gemPower"] = gp
    # Paliers de puissance de gemmes (0 / 125 / 625 / 1500) : part des builds a chaque palier
    tiers = {}
    for k in GEM_KEYS:
        c = Counter()
        for b in builds:
            v = stat(b, k) or 0
            c[sum(v >= s for s in GEM_TIERS)] += 1
        tiers[k] = [pct(c[i], n) for i in range(len(GEM_TIERS) + 1)]
    A["gemTiers"] = tiers
    gems = Counter()
    for b in builds:
        gems.update({g["gem"]["name"] for g in gear(b)
                     if isinstance(g.get("gem"), dict) and g["gem"].get("name")})
    A["gems"] = counted(gems, n, 10)

    # Objets par emplacement (% de builds qui portent l'objet)
    slots = []
    for label, ss in SLOT_GROUPS:
        c = Counter()
        for b in builds:
            c.update({clean(g["name"]) for g in gear(b) if g.get("slot") in ss})
        if c:
            slots.append({"slot": label, "items": counted(c, n, 3)})
    A["slots"] = slots

    # Legendaire (qualite 6) et effets speciaux (type 1024)
    leg, special, has_leg = Counter(), Counter(), 0
    for b in builds:
        items = {f"{clean(g['name'])}|{SLOT_LABELS.get(g['slot'], '?')}"
                 for g in gear(b) if g.get("quality") == 6}
        has_leg += bool(items)
        leg.update(items)
        special.update({a["name"] for a in b["info"].get("artifact") or []
                        if a.get("type") == 1024 and a.get("total", 0) >= 1 and a.get("name")})
    A["legendary"] = [{"name": k.split("|")[0], "slot": k.split("|")[1], "pct": pct(c, n)}
                      for k, c in leg.most_common(5)]
    A["legendaryPct"] = pct(has_leg, n)
    A["special"] = counted(special, n, 5)

    # Cou
    neck, ncombo = Counter(), Counter()
    for b in builds:
        picks = sorted({h["name"] for h in b["info"].get("heartOfAzeroth") or []
                        if h.get("total", 0) >= 1 and h.get("name")})
        neck.update(picks)
        if picks:
            ncombo[tuple(picks)] += 1
    A["neck"] = counted(neck, n)
    A["neckCombos"] = [{"names": list(k), "pct": pct(c, n)} for k, c in ncombo.most_common(3)]

    # Traits (arme + objets fusionnes) et enchantements (total cumule des rangs)
    traits_pb, ench_pb, bless_pb = [], [], []
    trait_pres = Counter()
    present_pb = []
    for b in builds:
        tr, en, bl = Counter(), Counter(), Counter()
        present = set()
        for g in gear(b):
            for t in g.get("traits") or []:
                if not t.get("name"):
                    continue
                nm = clean(t["name"])
                if is_ench(nm):
                    en[nm] += t.get("rank", 1)
                else:
                    tr[nm] += t.get("rank", 1)
                    present.add(nm)
            for x in g.get("blessings") or []:
                if x.get("name"):
                    bl[x["name"]] += x.get("level", 1)
        # rangs donnes par l'arbre de l'arme : ils s'ajoutent a ceux de l'equipement (comme dans les logs)
        for nm, tot in weapon_tree(b).items():
            if is_ench(nm):
                en[nm] += tot
            else:
                tr[nm] += tot
                present.add(nm)
        trait_pres.update(present)
        present_pb.append(present)
        traits_pb.append(tr)
        ench_pb.append(en)
        bless_pb.append(bl)
    traits = []
    for name, c in trait_pres.most_common(40):
        vals = [d[name] for d in traits_pb if d.get(name, 0) > 0]
        levels = [d.get(name, 0) for d, pr in zip(traits_pb, present_pb) if name in pr]
        traits.append({"name": name, "pct": pct(c, n), "n": c, "median": r1(med(vals)),
                       "dist": distribution(levels)})
    A["traits"] = traits
    A["enchants"] = level_table(ench_pb, n, 6)
    A["blessings"] = level_table(bless_pb, n, 10, with_dist=True)
    return A


def weapon_tree(b):
    """Rangs actifs dans l'arbre de l'arme (champ "artifact" du log, hors effets speciaux)."""
    out = Counter()
    for a in b["info"].get("artifact") or []:
        nm = clean(a.get("name") or "")
        if nm and a.get("type") != 1024 and a.get("total", 0) >= 1:
            out[nm] += a["total"]
    return out


def profile(b):
    """Build d'un joueur sous forme simple, pour le comparer a un build objectif."""
    info = b["info"]
    tr, bl = Counter(), Counter()
    for g in gear(b):
        for t in g.get("traits") or []:
            if t.get("name") and not is_ench(clean(t["name"])):
                tr[clean(t["name"])] += t.get("rank", 1)
        for x in g.get("blessings") or []:
            if x.get("name"):
                bl[x["name"]] += x.get("level", 1)
    for nm, tot in weapon_tree(b).items():
        if not is_ench(nm):
            tr[nm] += tot
    lv = [g.get("itemLevel") for g in gear(b) if g.get("itemLevel")]
    return {
        "talents": sorted({t["name"] for t in info.get("talents") or [] if t.get("name")}),
        "stats": {k: stat(b, k) for k in SECONDARY if stat(b, k) is not None},
        "pct": {k: r1((stat(b, k + "Percent") or 0) / 100) for k in SECONDARY},
        "gems": {k: stat(b, k) or 0 for k in GEM_KEYS},
        "neck": sorted({h["name"] for h in info.get("heartOfAzeroth") or [] if h.get("total", 0) >= 1 and h.get("name")}),
        "legendary": sorted({clean(g["name"]) for g in gear(b) if g.get("quality") == 6}),
        "special": sorted({a["name"] for a in info.get("artifact") or []
                           if a.get("type") == 1024 and a.get("total", 0) >= 1 and a.get("name")}),
        "traits": dict(tr), "blessings": dict(bl),
        "items": {SLOT_LABELS.get(g["slot"], "?") + ("" if g["slot"] not in (10, 12) else " 2"): clean(g["name"]) for g in gear(b)},
        "ilvl": r1(sum(lv) / len(lv)) if lv else None,
    }


def load_players(path):
    out = []
    for j in json.loads(Path(path).read_text(encoding="utf-8")):
        row = {k: j.get(k) for k in ("nom", "heros", "date", "encounter", "report", "erreur", "releve")}
        if j.get("info"):
            row["build"] = profile({"info": j["info"]})
        out.append(row)
    return out


def enc_short(e):
    return int(e) % 50000 if int(e) >= 50000 else int(e)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="fichiers builds_<heros>.json")
    ap.add_argument("--from-html", metavar="PAGE",
                    help="reprend les donnees deja calculees dans une page existante "
                         "(ex. docs/index.html) : change seulement la mise en page")
    ap.add_argument("-o", "--out", default="index.html")
    ap.add_argument("--joueurs", metavar="FICHIER",
                    help="builds des joueurs suivis (resultats/joueurs_suivis.json)")
    ap.add_argument("--joueurs-maj", metavar="FICHIER",
                    help="actualise seulement les joueurs presents dans ce fichier (le reste est garde)")
    ap.add_argument("--fragment", action="store_true",
                    help="sans <html>/<head> (pour une publication sur Claude)")
    args = ap.parse_args()

    if args.from_html:
        data = data_from_html(Path(args.from_html))
        print(f"Donnees reprises de {args.from_html} ({len(data['heroes'])} heros)")
    elif args.files:
        data = build_data(args.files)
    else:
        ap.error("donne des fichiers builds_<heros>.json ou --from-html")
    if args.joueurs and Path(args.joueurs).exists():
        data["players"] = load_players(args.joueurs)
        print(f"Joueurs suivis : {len(data['players'])}")
    if args.joueurs_maj and Path(args.joueurs_maj).exists():
        maj = load_players(args.joueurs_maj)
        noms = {p["nom"].lower() for p in maj}
        data["players"] = [p for p in data.get("players", []) if p["nom"].lower() not in noms] + maj
        print(f"Joueurs actualises : {len(noms)}")
    render(data, Path(args.out), args.fragment)


def data_from_html(path):
    s = path.read_text(encoding="utf-8")
    i = s.index("const DATA = ") + len("const DATA = ")
    data, _ = json.JSONDecoder().raw_decode(s[i:])
    return data


def collect_icons(builds, icons, ids):
    """Nom -> fichier d'icone du jeu et nom -> numero (talents, cou, traits, benedictions)."""
    for b in builds:
        info = b["info"]
        for key in ("talents", "heartOfAzeroth", "artifact"):
            for t in info.get(key) or []:
                if not t.get("name"):
                    continue
                if t.get("abilityIcon"):
                    icons.setdefault(clean(t["name"]), t["abilityIcon"])
                if t.get("type") != 1024 and isinstance(t.get("guid"), int) and t["guid"] >= 1000000:
                    ids.setdefault(clean(t["name"]), t["guid"])
        for g in gear(b):
            for t in (g.get("traits") or []) + (g.get("blessings") or []):
                if not t.get("name"):
                    continue
                if t.get("icon"):
                    icons.setdefault(clean(t["name"]), t["icon"])
                if isinstance(t.get("id"), int) and t["id"] >= 1000000:
                    ids.setdefault(clean(t["name"]), t["id"])


def collect_items(builds, items):
    """Nom d'objet -> icone, numero, qualite, emplacement, niveau et caracteristiques (au plus haut niveau vu)."""
    for b in builds:
        for g in gear(b):
            nm = clean(g["name"])
            cur = items.get(nm)
            if cur and cur["ilvl"] >= (g.get("itemLevel") or 0):
                continue
            items[nm] = {"icon": g.get("icon"), "id": g.get("id"), "q": g.get("quality"),
                         "slot": SLOT_LABELS.get(g.get("slot"), "?"), "ilvl": g.get("itemLevel") or 0,
                         "attrs": [[a["name"], a["value"]] for a in g.get("attributes") or []
                                   if a.get("name") and a.get("value")],
                         "socket": bool(g.get("hasGemSocket"))}


def build_data(files):
    heroes, enc_names, icons, ids = {}, {}, {}, {}
    for f in files:
        p = Path(f)
        hero = p.stem.split("builds_", 1)[-1]
        builds = json.loads(p.read_text(encoding="utf-8"))
        builds = [b for b in builds if isinstance(b, dict) and isinstance(b.get("info"), dict)]
        if not builds:
            continue
        for b in builds:
            if b.get("encounterName"):
                enc_names[str(b["encounter"])] = b["encounterName"]
        collect_icons(builds, icons, ids)
        items = {}
        collect_items(builds, items)
        by_enc = defaultdict(list)
        for b in builds:
            by_enc[str(b["encounter"])].append(b)
        heroes[hero] = {"all": aggregate(builds), "items": items, "weaponFx": weapon_fx(builds),
                        "byEncounter": {e: aggregate(bs) for e, bs in sorted(by_enc.items())}}
        print(f"{hero} : {len(builds)} builds, {len(by_enc)} donjon(s)")

    all_enc = sorted({e for h in heroes.values() for e in h["byEncounter"]}, key=int)
    names = {e: enc_names.get(e) or ENCOUNTER_NAMES.get(enc_short(e)) or f"Donjon {e}"
             for e in all_enc}
    data = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "heroOrder": KNOWN_HEROES + sorted(h for h in heroes if h not in KNOWN_HEROES),
            "encounters": names, "icons": icons, "ids": ids, "heroes": heroes}
    return data


def render(data, out, fragment):
    desc_file = HERE / "descriptions.json"   # descriptions copiees depuis fellows.gg
    if desc_file.exists():
        data["desc"] = json.loads(desc_file.read_text(encoding="utf-8"))
    form_file = HERE / "formulaire.json"   # adresse publique du formulaire de suivi (sans secret)
    if form_file.exists():
        f = json.loads(form_file.read_text(encoding="utf-8"))
        data["form"] = {k: f[k] for k in ("envoi", "champ_pseudo", "champ_heros")}
    gem_file = HERE / "gemmes.json"   # bonus de gemmes copies depuis fellows.gg
    if gem_file.exists():
        data["gemBonus"] = json.loads(gem_file.read_text(encoding="utf-8"))
    links_file = HERE / "liens_fellows.json"   # liens fellows.gg releves sur leurs pages
    if links_file.exists():
        data["links"] = json.loads(links_file.read_text(encoding="utf-8"))
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    if not fragment:
        head, body = html.split("</style>", 1)
        html = ('<!doctype html>\n<html lang="fr"><head><meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                + head + "</style>\n</head><body>" + body + "</body></html>\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"-> {out} ({out.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
