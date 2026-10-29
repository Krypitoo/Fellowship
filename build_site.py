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

KNOWN_HEROES = ["Helena", "Mara", "Elarion", "Xavian", "Sylvie", "Ardeos",
                "Tariq", "Vigour", "Meiko", "Rime", "Aeona", "Gunde"]
# Noms de secours si le fichier de builds ne contient pas encore "encounterName"
ENCOUNTER_NAMES = {6: "Empyrean Sands", 7: "Cithrel's Fall"}

SLOT_GROUPS = [
    ("Arme", [13]), ("Tête", [0]), ("Cou", [1]), ("Épaules", [2]), ("Dos", [3]),
    ("Torse", [4]), ("Poignets", [5]), ("Mains", [6]), ("Taille", [7]), ("Pieds", [8]),
    ("Anneaux", [9, 10]), ("Orbes", [11, 12]),
]
SLOT_LABELS = {s: lab for lab, ss in SLOT_GROUPS for s in ss}
GEAR_SLOTS = set(range(14))           # 14 et 15 = potion, rez : ignores
SECONDARY = ["Crit", "Haste", "Expertise", "Spirit"]
SECONDARY_FR = {"Crit": "Critique", "Haste": "Hâte", "Expertise": "Expertise", "Spirit": "Esprit"}
MAIN_STATS = ["Strength", "Agility", "Intellect"]
MAIN_FR = {"Strength": "Force", "Agility": "Agilité", "Intellect": "Intelligence"}
GEM_KEYS = ["Sapphire", "Emerald", "Ruby", "Diamond", "Topaz", "Amethyst"]


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


def level_table(per_build, n, top):
    """per_build : liste de Counter {nom: total}. -> % builds, mediane et zone courante."""
    pres = Counter()
    for d in per_build:
        pres.update(k for k, v in d.items() if v > 0)
    out = []
    for name, c in pres.most_common(top):
        vals = [d[name] for d in per_build if d.get(name, 0) > 0]
        q1, q3 = quart(vals)
        out.append({"name": name, "pct": pct(c, n), "median": r1(med(vals)),
                    "q1": r1(q1), "q3": r1(q3)})
    return out


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
        q1, q3 = quart(pc)
        sec.append({"key": k, "label": SECONDARY_FR[k], "raw": r1(med(raw)),
                    "pct": r1(med(pc)), "q1": r1(q1), "q3": r1(q3),
                    "min": r1(min(pc)), "max": r1(max(pc))})
    sec.sort(key=lambda s: -s["pct"])
    A["secondary"] = sec

    other = []
    for k in MAIN_STATS:
        v = [x for x in (stat(b, k) for b in builds) if x is not None]
        if v:
            other.append({"label": MAIN_FR[k], "median": r1(med(v))})
    ilvl = []
    for b in builds:
        lv = [g.get("itemLevel") for g in gear(b) if g.get("itemLevel")]
        if lv:
            ilvl.append(sum(lv) / len(lv))
    if ilvl:
        other.append({"label": "Niveau d'objet moyen", "median": r1(med(ilvl))})
    for k, lab in (("Stamina", "Endurance"), ("Health", "Points de vie"), ("Armor", "Armure")):
        v = [x for x in (stat(b, k) for b in builds) if x is not None]
        if v:
            other.append({"label": lab, "median": r1(med(v))})
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
        for a in b["info"].get("artifact") or []:
            nm = clean(a.get("name") or "")
            if nm and a.get("type") != 1024 and not is_ench(nm) and a.get("total", 0) >= 1:
                present.add(nm)
        trait_pres.update(present)
        traits_pb.append(tr)
        ench_pb.append(en)
        bless_pb.append(bl)
    traits = []
    for name, c in trait_pres.most_common(10):
        vals = [d[name] for d in traits_pb if d.get(name, 0) > 0]
        traits.append({"name": name, "pct": pct(c, n), "median": r1(med(vals))})
    A["traits"] = traits
    A["enchants"] = level_table(ench_pb, n, 6)
    A["blessings"] = level_table(bless_pb, n, 8)
    return A


def enc_short(e):
    return int(e) % 50000 if int(e) >= 50000 else int(e)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="fichiers builds_<heros>.json")
    ap.add_argument("-o", "--out", default="index.html")
    ap.add_argument("--fragment", action="store_true",
                    help="sans <html>/<head> (pour une publication sur Claude)")
    args = ap.parse_args()

    heroes, enc_names = {}, {}
    for f in args.files:
        p = Path(f)
        hero = p.stem.split("builds_", 1)[-1]
        builds = json.loads(p.read_text(encoding="utf-8"))
        builds = [b for b in builds if isinstance(b, dict) and isinstance(b.get("info"), dict)]
        if not builds:
            continue
        for b in builds:
            if b.get("encounterName"):
                enc_names[str(b["encounter"])] = b["encounterName"]
        by_enc = defaultdict(list)
        for b in builds:
            by_enc[str(b["encounter"])].append(b)
        heroes[hero] = {"all": aggregate(builds),
                        "byEncounter": {e: aggregate(bs) for e, bs in sorted(by_enc.items())}}
        print(f"{hero} : {len(builds)} builds, {len(by_enc)} donjon(s)")

    all_enc = sorted({e for h in heroes.values() for e in h["byEncounter"]}, key=int)
    names = {e: enc_names.get(e) or ENCOUNTER_NAMES.get(enc_short(e)) or f"Donjon {e}"
             for e in all_enc}
    data = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "heroOrder": KNOWN_HEROES + sorted(h for h in heroes if h not in KNOWN_HEROES),
            "encounters": names, "heroes": heroes}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    if not args.fragment:
        head, body = html.split("</style>", 1)
        html = ('<!doctype html>\n<html lang="fr"><head><meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                + head + "</style>\n</head><body>" + body + "</body></html>\n")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"-> {out} ({out.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
