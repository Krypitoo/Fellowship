#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comparer_builds.py - resume les builds des meilleurs joueurs d'un heros (Fellowship Logs).

Exemples :
  python comparer_builds.py --hero Helena --top 30
  python comparer_builds.py --hero Helena Mara --top 25 --encounter 150006 150007
  python comparer_builds.py --all --top 20

Identifiants : variables d'environnement FELLOWSHIP_CLIENT_ID et FELLOWSHIP_CLIENT_SECRET
(ne jamais ecrire le secret dans ce fichier).
Usage personnel, non commercial. Les reponses sont mises en cache dans ./cache,
les resultats sont ecrits dans ./resultats.
"""
import argparse
import base64
import html
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

TOKEN_URL = "https://www.fellowshiplogs.com/oauth/token"
API_URL = "https://www.fellowshiplogs.com/api/v2/client"
USER_AGENT = "PersonalBuildSummary/1.0 (usage personnel, non commercial)"

# Les 7 donjons de la zone "Halloween Reset"
DEFAULT_ENCOUNTERS = [150006, 150007, 150012, 150013, 150021, 150024, 150025]
KNOWN_HEROES = ["Helena", "Mara", "Elarion", "Xavian", "Sylvie", "Ardeos",
                "Tariq", "Vigour", "Meiko", "Rime", "Aeona", "Gunde"]

SAFETY = 0.9               # on attend la remise a zero a 90 % du quota
RANKING_CACHE_HOURS = 6    # duree de vie du cache des classements
MAX_RANKING_PAGES = 5
RATE = "rateLimitData { pointsSpentThisHour limitPerHour pointsResetIn }"

CACHE_DIR = Path("cache")
OUT_DIR = Path("resultats")

SLOT_GROUPS = [
    ("Tete", [0]), ("Cou", [1]), ("Epaules", [2]), ("Dos", [3]), ("Torse", [4]),
    ("Poignets", [5]), ("Mains", [6]), ("Taille", [7]), ("Pieds", [8]),
    ("Anneaux", [9, 10]), ("Orbes (reliques ?)", [11, 12]), ("Arme", [13]),
]
SLOT_LABELS = {0: "Tete", 1: "Cou", 2: "Epaules", 3: "Dos", 4: "Torse", 5: "Poignets",
               6: "Mains", 7: "Taille", 8: "Pieds", 9: "Anneau", 10: "Anneau",
               11: "Orbe", 12: "Orbe", 13: "Arme"}
SECONDARY = ["Crit", "Haste", "Expertise", "Spirit"]
MAIN_STATS = ["Strength", "Agility", "Intellect"]
GEM_KEYS = ["Sapphire", "Emerald", "Ruby", "Diamond", "Topaz", "Amethyst"]


# --------------------------------------------------------------------------
# Acces a l'API
# --------------------------------------------------------------------------
class Client:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None
        self.spent = 0.0
        self.limit = 1000.0
        self.reset_in = 3600

    def _post(self, url, body, headers):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_token(self):
        creds = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode("utf-8")).decode("ascii")
        headers = {"Authorization": f"Basic {creds}",
                   "Content-Type": "application/x-www-form-urlencoded",
                   "User-Agent": USER_AGENT}
        data = self._post(TOKEN_URL, b"grant_type=client_credentials", headers)
        self.token = data["access_token"]

    def _sleep_until_reset(self, reason):
        wait = max(int(self.reset_in), 60) + 5
        print(f"\n  {reason} : pause de {wait // 60} min {wait % 60} s avant de reprendre...")
        time.sleep(wait)
        self.spent = 0.0

    def query(self, body, retries=3):
        text = f"query {{ {body} {RATE} }}"
        payload = json.dumps({"query": text}).encode("utf-8")
        for attempt in range(retries):
            if self.token is None:
                self.get_token()
            if self.spent >= SAFETY * self.limit:
                self._sleep_until_reset("Quota presque epuise")
            headers = {"Authorization": f"Bearer {self.token}",
                       "Content-Type": "application/json",
                       "User-Agent": USER_AGENT}
            try:
                data = self._post(API_URL, payload, headers)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    self.token = None
                    continue
                if e.code == 429:
                    self._sleep_until_reset("Limite atteinte (HTTP 429)")
                    continue
                detail = e.read()[:300]
                raise RuntimeError(f"HTTP {e.code} : {detail!r}")
            rl = (data.get("data") or {}).get("rateLimitData")
            if rl:
                self.spent = float(rl.get("pointsSpentThisHour", self.spent))
                self.limit = float(rl.get("limitPerHour", self.limit))
                self.reset_in = rl.get("pointsResetIn", self.reset_in)
            if data.get("errors"):
                msg = json.dumps(data["errors"], ensure_ascii=False)
                if re.search(r"rate limit|too many|points|quota", msg, re.I) \
                        and attempt < retries - 1:
                    self._sleep_until_reset("Quota epuise selon l'API")
                    continue
                raise RuntimeError(f"Erreur de l'API : {msg[:500]}")
            return data["data"]
        raise RuntimeError("Echec apres plusieurs tentatives")


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------
def cache_get(name, max_age_hours=None):
    p = CACHE_DIR / name
    if not p.exists():
        return None
    if max_age_hours is not None and time.time() - p.stat().st_mtime > max_age_hours * 3600:
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def cache_put(name, obj):
    CACHE_DIR.mkdir(exist_ok=True)
    (CACHE_DIR / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------
# Recuperation des donnees
# --------------------------------------------------------------------------
def fetch_rankings_page(client, encounter, hero, page):
    name = f"rank_{encounter}_{hero}_{page}.json"
    cached = cache_get(name, RANKING_CACHE_HOURS)
    if cached is not None:
        return cached
    body = (f"worldData {{ encounter(id: {int(encounter)}) {{ characterRankings("
            f"specName: {json.dumps(hero)}, page: {int(page)}) }} }}")
    data = client.query(body)
    result = data["worldData"]["encounter"]["characterRankings"]
    if isinstance(result, str):
        result = json.loads(result)
    cache_put(name, result)
    return result


def fetch_encounter_name(client, encounter):
    name = f"enc_{encounter}.json"
    cached = cache_get(name)
    if cached is not None:
        return cached
    try:
        data = client.query(f"worldData {{ encounter(id: {int(encounter)}) {{ name }} }}")
        result = data["worldData"]["encounter"]["name"]
    except (RuntimeError, KeyError, TypeError):
        return None
    cache_put(name, result)
    return result


def select_entries(client, encounter, hero, top):
    """Meilleure partie de chaque joueur (le classement est deja trie par score)."""
    chosen, seen = [], set()
    for page in range(1, MAX_RANKING_PAGES + 1):
        res = fetch_rankings_page(client, encounter, hero, page)
        for r in res.get("rankings", []):
            rep = r.get("report") or {}
            if not rep.get("code") or rep.get("fightID") is None:
                continue  # pas de rapport : impossible de lire le build
            if r["name"] in seen:
                continue
            seen.add(r["name"])
            chosen.append(r)
            if len(chosen) >= top:
                return chosen
        if not res.get("hasMorePages"):
            break
    return chosen


def fetch_fight_players(client, code, fight_id):
    name = f"fight_{code}_{fight_id}.json"
    cached = cache_get(name)
    if cached is not None:
        return cached
    body = (f"reportData {{ report(code: {json.dumps(code)}) {{ playerDetails("
            f"fightIDs: [{int(fight_id)}], includeCombatantInfo: true) }} }}")
    data = client.query(body)
    pd = data["reportData"]["report"]["playerDetails"]
    if isinstance(pd, str):
        pd = json.loads(pd)
    players = pd["data"]["playerDetails"]
    cache_put(name, players)
    return players


def find_player(players, name, hero):
    for lst in players.values():
        for p in lst or []:
            if p.get("name") == name and p.get("type") == hero:
                return p
    return None


def collect_builds(client, hero, encounters, top):
    builds = []
    for enc in encounters:
        enc_name = fetch_encounter_name(client, enc)
        entries = select_entries(client, enc, hero, top)
        print(f"  [{hero}] donjon {enc} : {len(entries)} joueurs retenus")
        for i, e in enumerate(entries, 1):
            rep = e["report"]
            print(f"    {i}/{len(entries)} {e['name']}".ljust(60), end="\r")
            try:
                players = fetch_fight_players(client, rep["code"], rep["fightID"])
            except (KeyError, TypeError) as err:
                print(f"\n    ignore : {e['name']} (rapport illisible : {err!r})")
                continue
            p = find_player(players, e["name"], hero)
            if not p or not p.get("combatantInfo"):
                print(f"\n    ignore : {e['name']} (pas d'infos de build)")
                continue
            builds.append({"player": e["name"], "encounter": enc, "encounterName": enc_name,
                           "score": e.get("score"), "difficulty": e.get("hardModeLevel"),
                           "report": rep["code"], "fight": rep["fightID"],
                           "info": p["combatantInfo"]})
        print()
    return builds


# --------------------------------------------------------------------------
# Synthese
# --------------------------------------------------------------------------
def fmt(x, nd=0):
    s = f"{x:,.{nd}f}".replace(",", " ")
    return s.replace(".", ",") if nd else s


def counter_table(counter, n, top=None, headers=("Element", "Builds", "%")):
    lines = [f"| {headers[0]} | {headers[1]} | {headers[2]} |", "|---|---:|---:|"]
    for name, c in counter.most_common(top):
        lines.append(f"| {name} | {c} | {100 * c / n:.0f} % |")
    return lines


def values_for(builds, key, default=None):
    out = []
    for b in builds:
        s = b["info"].get("stats", {}).get(key)
        if s is not None:
            out.append(s.get("max", s.get("min")))
        elif default is not None:
            out.append(default)
    return [v for v in out if v is not None]


def stats_table(builds, keys, scale=1, nd=0, default=None):
    lines = ["| Stat | Moyenne | Mediane | Min | Max |", "|---|---:|---:|---:|---:|"]
    for key in keys:
        vals = [v / scale for v in values_for(builds, key, default)]
        if not vals:
            continue
        lines.append(f"| {key} | {fmt(statistics.mean(vals), nd)} | "
                     f"{fmt(statistics.median(vals), nd)} | {fmt(min(vals), nd)} | "
                     f"{fmt(max(vals), nd)} |")
    return lines


def sanitize(builds):
    """Rend les builds tolerants aux entrees sans nom (objet vide, trait inconnu...)."""
    for b in builds:
        info = b.get("info") or {}
        for key in ("talents", "artifact", "heartOfAzeroth"):
            info[key] = [x for x in (info.get(key) or []) if isinstance(x, dict) and x.get("name")]
        gear = []
        for g in info.get("gear") or []:
            if not isinstance(g, dict):
                continue
            g.setdefault("name", "(sans nom)")
            if not g.get("name"):
                g["name"] = "(sans nom)"
            if isinstance(g.get("gem"), dict) and not g["gem"].get("name"):
                g["gem"] = None
            g["blessings"] = [x for x in (g.get("blessings") or []) if isinstance(x, dict) and x.get("name")]
            g["traits"] = [x for x in (g.get("traits") or []) if isinstance(x, dict) and x.get("name")]
            gear.append(g)
        info["gear"] = gear
        b["info"] = info
    return builds


def build_report(hero, builds, encounters):
    sanitize(builds)
    n = len(builds)
    L = []
    add = L.append
    scores = [b["score"] for b in builds if b.get("score") is not None]
    add(f"# Resume des builds - {hero}")
    add("")
    add(f"- Builds analyses : **{n}** (donjons : {', '.join(str(e) for e in encounters)})")
    if scores:
        add(f"- Scores de classement : de {min(scores):.0f} a {max(scores):.0f}")
    add("")

    # --- Talents
    add("## Talents")
    add("")
    talents, combos = Counter(), Counter()
    for b in builds:
        names = sorted({t["name"] for t in b["info"].get("talents", [])})
        talents.update(names)
        combos[" / ".join(names)] += 1
    L += counter_table(talents, n, headers=("Talent", "Builds", "%"))
    add("")
    add("Combinaisons completes les plus frequentes :")
    add("")
    for combo, k in combos.most_common(5):
        add(f"- {k} build(s) ({100 * k / n:.0f} %) : {combo}")
    add("")

    # --- Stats du personnage
    add("## Stats du personnage")
    add("")
    main = [k for k in MAIN_STATS if values_for(builds, k)]
    add("Valeurs brutes (notes) :")
    add("")
    L += stats_table(builds, main + SECONDARY + ["Stamina", "Armor", "Health", "Item Level"])
    add("")
    add("Pourcentages (valeur brute / 100 - a confirmer en jeu) :")
    add("")
    L += stats_table(builds, [k + "Percent" for k in SECONDARY], scale=100, nd=1)
    add("")
    prio = sorted(((statistics.mean(values_for(builds, k + "Percent")), k)
                   for k in SECONDARY if values_for(builds, k + "Percent")), reverse=True)
    if prio:
        add("Ordre des stats secondaires (mediane) (en %) : "
            + " > ".join(f"{k} {fmt(v / 100, 1)}" for v, k in prio))
        add("")

    # --- Gemmes
    add("## Gemmes (puissance totale par couleur)")
    add("")
    seen = [k for k in GEM_KEYS if any(k in b["info"].get("stats", {}) for b in builds)]
    L += stats_table(builds, seen, default=0)
    add("")
    gem_names = Counter()
    for b in builds:
        gem_names.update({g["gem"]["name"] for g in b["info"].get("gear", [])
                          if g.get("gem")})
    if gem_names:
        add("Gemmes serties (builds en ayant au moins une) :")
        add("")
        L += counter_table(gem_names, n, top=8, headers=("Gemme", "Builds", "%"))
        add("")

    # --- Cou
    add("## Cou")
    add("")
    neck_items, hoa, hoa_combos = Counter(), Counter(), Counter()
    for b in builds:
        neck_items.update({g["name"] for g in b["info"].get("gear", [])
                           if g.get("slot") == 1})
        picks = sorted({h["name"] for h in b["info"].get("heartOfAzeroth", [])
                        if h.get("total", 0) >= 1})
        hoa.update(picks)
        if picks:
            hoa_combos[" + ".join(picks)] += 1
    add("Objet porte au cou :")
    add("")
    L += counter_table(neck_items, n, top=5, headers=("Objet", "Builds", "%"))
    add("")
    add("Choix du cou (champ `heartOfAzeroth` du log, 3 choix par joueur) :")
    add("")
    L += counter_table(hoa, n, headers=("Choix", "Builds", "%"))
    add("")
    add("Combinaisons les plus frequentes :")
    add("")
    for combo, k in hoa_combos.most_common(5):
        add(f"- {k} build(s) ({100 * k / n:.0f} %) : {combo}")
    add("")

    # --- Equipement par emplacement
    add("## Equipement par emplacement")
    add("")
    add("| Emplacement | Objets les plus frequents |")
    add("|---|---|")
    for label, slots in SLOT_GROUPS:
        c = Counter()
        for b in builds:
            c.update({g["name"] for g in b["info"].get("gear", []) if g.get("slot") in slots})
        if not c:
            continue
        top3 = c.most_common(3)
        txt = " ; ".join(f"{name} ({100 * k / n:.0f} %)" for name, k in top3)
        if top3[0][1] / n >= 0.5:
            txt += "  <- majorite"
        add(f"| {label} | {txt} |")
    add("")

    # --- Legendaire
    add("## Legendaire (objets de qualite 6, probablement)")
    add("")
    leg, leg_n = Counter(), 0
    for b in builds:
        items = [g for g in b["info"].get("gear", []) if g.get("quality") == 6]
        leg_n += 1 if items else 0
        leg.update({f"{SLOT_LABELS.get(g.get('slot'), '?')} : {g['name']}" for g in items})
    add(f"Builds portant un objet de qualite 6 : {leg_n}/{n}")
    add("")
    if leg:
        L += counter_table(leg, n, headers=("Objet", "Builds", "%"))
        add("")
    special = Counter()
    for b in builds:
        special.update({a["name"] for a in b["info"].get("artifact", [])
                        if a.get("type") == 1024 and a.get("total", 0) >= 1})
    if special:
        add("Effets speciaux (type 1024 dans le log) :")
        add("")
        L += counter_table(special, n, headers=("Effet", "Builds", "%"))
        add("")

    # --- Traits d'equipement
    add("## Traits d'equipement les plus presents")
    add("")
    traits = Counter()
    for b in builds:
        traits.update({a["name"] for a in b["info"].get("artifact", [])
                       if a.get("type") != 1024 and a.get("total", 0) >= 1})
    L += counter_table(traits, n, top=10, headers=("Trait", "Builds", "%"))
    add("")

    # --- Benedictions
    add("## Benedictions (niveau total sur l'equipement)")
    add("")
    levels, present = Counter(), Counter()
    for b in builds:
        per = Counter()
        for g in b["info"].get("gear", []):
            for bl in g.get("blessings", []) or []:
                per[bl["name"]] += bl.get("level", 1)
        levels.update(per)
        present.update(per.keys())
    add("| Benediction | Builds | % | Niveau total moyen |")
    add("|---|---:|---:|---:|")
    for name, _ in present.most_common(8):
        add(f"| {name} | {present[name]} | {100 * present[name] / n:.0f} % | "
            f"{levels[name] / n:.1f} |")
    add("")
    return "\n".join(L)


# --------------------------------------------------------------------------
# Page HTML
# --------------------------------------------------------------------------
GEM_COLORS = {"Amethyst": "#ff69c8", "Diamond": "#d9d9d9", "Emerald": "#00a050",
              "Ruby": "#b00a4a", "Sapphire": "#1a8cff", "Topaz": "#ffd966"}


def _esc(x):
    return html.escape(str(x))


def _stat_summary(vals):
    vals = sorted(vals)
    if not vals:
        return None
    return {"mean": statistics.mean(vals), "median": statistics.median(vals),
            "min": vals[0], "max": vals[-1]}


def _bar(label, pct, right="", color=None, sub=""):
    style = f"width:{pct:.1f}%" + (f";background:{color}" if color else "")
    return (f'<div class="row"><div class="lab">{label}{f"<small>{sub}</small>" if sub else ""}</div>'
            f'<div class="track"><div class="fill" style="{style}"></div></div>'
            f'<div class="val">{right}</div></div>')


def _counter_bars(counter, n, top=None, color=None):
    out = []
    for name, c in counter.most_common(top):
        out.append(_bar(_esc(name), 100 * c / n, f"{c} <span>({100 * c / n:.0f} %)</span>", color))
    return "\n".join(out)


def _level_distribution(builds, extractor, top=10):
    """extractor(build) -> {nom: niveau total}. Repartition des niveaux par element."""
    n = len(builds)
    per_name = defaultdict(Counter)
    for b in builds:
        for name, lvl in extractor(b).items():
            per_name[name][lvl] += 1
    items = sorted(per_name.items(), key=lambda kv: -sum(kv[1].values()))[:top]
    if not items:
        return "<p class='muted'>Aucune donnee.</p>"
    max_lvl = max(l for _, c in items for l in c)
    head = "".join(f"<th>{l}</th>" for l in range(1, max_lvl + 1))
    rows = []
    for name, cnt in items:
        total = sum(cnt.values())
        cells = []
        for l in range(1, max_lvl + 1):
            c = cnt.get(l, 0)
            alpha = 0 if not c else 0.15 + 0.85 * c / total
            cells.append(f'<td style="--a:{alpha:.2f}">{c if c else ""}</td>')
        rows.append(f"<tr><th class='left'>{_esc(name)}</th><td class='tot'>{total}"
                    f" <span>({100 * total / n:.0f} %)</span></td>{''.join(cells)}</tr>")
    return ("<table class='heat'><thead><tr><th class='left'>Nom</th><th>Builds</th>"
            f"{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
            "<p class='muted'>Colonnes : niveau total cumule sur l'equipement, nombre de builds "
            "ayant ce niveau.</p>")


def build_html(hero, builds, encounters):
    sanitize(builds)
    n = len(builds)
    scores = [b["score"] for b in builds if b.get("score") is not None]
    P = []
    add = P.append

    def section(title, body, note=""):
        add(f"<section><h2>{title}</h2>{f'<p class=muted>{note}</p>' if note else ''}{body}</section>")

    # --- Talents
    tc = Counter()
    combos = Counter()
    for b in builds:
        names = sorted(t["name"] for t in b["info"].get("talents", []))
        tc.update(names)
        combos[tuple(names)] += 1
    body = _counter_bars(tc, n)
    body += "<h3>Combinaisons completes les plus frequentes</h3><ol class='combos'>"
    for combo, c in combos.most_common(5):
        body += f"<li><b>{c}</b> build(s) ({100 * c / n:.0f} %) : {_esc(' / '.join(combo))}</li>"
    body += "</ol>"
    section("Talents", body)

    # --- Stats
    cards = []
    for key in SECONDARY:
        raw = _stat_summary(values_for(builds, key))
        pct = _stat_summary([v / 100 for v in values_for(builds, key + "Percent")])
        if not raw or not pct:
            continue
        cards.append(
            f'<div class="card"><h3>{key}</h3>'
            f'<div class="big">{fmt(raw["median"])}<small> de stat (mediane)</small></div>'
            f'<div class="big2">{fmt(pct["median"], 1)} %</div>'
            f'<div class="muted">moyenne {fmt(raw["mean"])} ({fmt(pct["mean"], 1)} %)<br>'
            f'min {fmt(raw["min"])} ({fmt(pct["min"], 1)} %)<br>'
            f'max {fmt(raw["max"])} ({fmt(pct["max"], 1)} %)</div></div>')
    order = sorted(SECONDARY, key=lambda k: -statistics.median(
        [v / 100 for v in values_for(builds, k + "Percent")] or [0]))
    body = f'<div class="cards">{"".join(cards)}</div>'
    body += (f"<p>Ordre moyen des stats secondaires : <b>{' &gt; '.join(order)}</b></p>")
    rows = []
    for key in MAIN_STATS + ["Stamina", "Armor", "Health", "Item Level"]:
        s = _stat_summary(values_for(builds, key))
        if s:
            rows.append(f"<tr><th class='left'>{key}</th><td>{fmt(s['median'])}</td>"
                        f"<td>{fmt(s['mean'])}</td><td>{fmt(s['min'])}</td><td>{fmt(s['max'])}</td></tr>")
    body += ("<h3>Autres stats</h3><table><thead><tr><th class='left'>Stat</th><th>Mediane</th>"
             f"<th>Moyenne</th><th>Min</th><th>Max</th></tr></thead><tbody>{''.join(rows)}</tbody></table>")
    section("Stats du personnage", body,
            "Grand chiffre = valeur de la stat, en dessous = pourcentage (valeur brute / 100, a confirmer en jeu). "
            "Mediane sur les builds.")

    # --- Gemmes
    gem_stats = {k: _stat_summary(values_for(builds, k, default=0)) for k in GEM_KEYS}
    gmax = max((s["median"] for s in gem_stats.values() if s), default=1) or 1
    body = ""
    for k in GEM_KEYS:
        s = gem_stats[k]
        if s:
            body += _bar(f'<span class="dot" style="background:{GEM_COLORS[k]}"></span>{k}',
                         100 * s["median"] / gmax, f"{fmt(s['median'])}",
                         GEM_COLORS[k], f"moyenne {fmt(s['mean'])} - min {fmt(s['min'])} - max {fmt(s['max'])}")
    gems = Counter()
    for b in builds:
        gems.update({g["gem"]["name"] for g in b["info"].get("gear", []) if g.get("gem")})
    chips = ""
    for name, c in gems.most_common(12):
        col = next((GEM_COLORS[k] for k in GEM_KEYS if k.lower() in name.lower()), "#888")
        chips += (f'<span class="chip" style="--c:{col}"><i></i>{_esc(name)} '
                  f'<b>{c}</b> <span>({100 * c / n:.0f} %)</span></span>')
    body += f"<h3>Gemmes serties (builds en ayant au moins une)</h3><div class='chips'>{chips}</div>"
    section("Gemmes", body, "Barres : puissance totale de gemmes par couleur (mediane).")

    # --- Cou
    neck = Counter()
    for b in builds:
        for g in b["info"].get("gear", []):
            if g.get("slot") == 1:
                neck[g["name"]] += 1
    hoa = Counter()
    hcombo = Counter()
    for b in builds:
        ch = sorted(h["name"] for h in b["info"].get("heartOfAzeroth", []) if h.get("total", 0) >= 1)
        hoa.update(ch)
        hcombo[tuple(ch)] += 1
    body = ("<div class='two'><div><h3>Choix de talent du cou</h3>" + _counter_bars(hoa, n) +
            "<h4>Combinaisons</h4><ol class='combos'>" +
            "".join(f"<li><b>{c}</b> ({100 * c / n:.0f} %) : {_esc(' + '.join(k))}</li>"
                    for k, c in hcombo.most_common(5)) +
            "</ol></div><div><h3>Objet porte</h3>" + _counter_bars(neck, n, top=6) + "</div></div>")
    section("Cou", body, "Le champ du log est suppose etre le choix de talent du cou.")

    # --- Equipement
    rows = []
    for label, slots in SLOT_GROUPS:
        cnt = Counter()
        for b in builds:
            for g in b["info"].get("gear", []):
                if g.get("slot") in slots:
                    cnt[g["name"]] += 1
        denom = n * len(slots)
        parts = []
        for i, (name, c) in enumerate(cnt.most_common(3)):
            pct = 100 * c / denom
            cls = " class='maj'" if pct >= 50 else ""
            parts.append(f"<span{cls}>{_esc(name)} <b>{pct:.0f} %</b></span>")
        rows.append(f"<tr><th class='left'>{label}</th><td>{' '.join(parts)}</td></tr>")
    section("Equipement par emplacement",
            f"<table class='gear'><tbody>{''.join(rows)}</tbody></table>",
            "En vert : objet present chez au moins 50 % des builds.")

    # --- Legendaire
    leg = Counter()
    special = Counter()
    for b in builds:
        s = {f"{SLOT_LABELS.get(g.get('slot'), '?')} : {g['name']}"
             for g in b["info"].get("gear", []) if g.get("quality") == 6}
        leg.update(s)
        special.update({a["name"] for a in b["info"].get("artifact", [])
                        if a.get("type") == 1024 and a.get("total", 0) >= 1})
    body = ("<div class='two'><div><h3>Objet legendaire</h3>" + _counter_bars(leg, n) +
            "</div><div><h3>Effets speciaux</h3>" + _counter_bars(special, n) + "</div></div>")
    section("Legendaire", body)

    # --- Traits d'arme
    wt = Counter()
    for b in builds:
        wt.update({a["name"] for a in b["info"].get("artifact", [])
                   if a.get("type") != 1024 and a.get("total", 0) >= 1})
    section("Traits d'arme (arbre de l'arme)", _counter_bars(wt, n, top=12))

    # --- Benedictions
    def bless(b):
        per = Counter()
        for g in b["info"].get("gear", []):
            for bl in g.get("blessings", []) or []:
                per[bl["name"]] += bl.get("level", 1)
        return per
    section("Benedictions", _level_distribution(builds, bless, top=14))

    # --- Traits portes par les objets (glyphes / aspects ?)
    def item_traits(pred, count_items=False):
        def f(b):
            per = Counter()
            for g in b["info"].get("gear", []):
                for t in g.get("traits", []) or []:
                    if pred(t["name"]):
                        per[t["name"].strip()] += 1 if count_items else t.get("rank", 1)
            return per
        return f
    section("Traits sur objets : modificateurs a rang (type Hunter's Focus)",
            _level_distribution(builds, item_traits(lambda s: " / " not in s), top=14))
    section("Traits sur objets : triples stats (Might / Guille / Cunning)",
            _level_distribution(builds, item_traits(lambda s: " / " in s, True), top=8),
            "Colonnes : nombre d'objets portant ce trait (et non le rang).")

    sc = f"{min(scores):.0f} a {max(scores):.0f}" if scores else "?"
    return HTML_TEMPLATE.format(hero=_esc(hero), n=n, encounters=_esc(", ".join(map(str, encounters))),
                                scores=sc, body="\n".join(P))


HTML_TEMPLATE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Builds {hero} - Fellowship</title>
<style>
:root{{--bg:#f5f5f7;--fg:#1d1d22;--mut:#6b6b76;--card:#fff;--line:#e0e0e6;--fill:#5b6cff;--ok:#1a9d55}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b0b10;--fg:#ececf1;--mut:#9a9aa6;--card:#15151c;--line:#2a2a35;--fill:#7b88ff;--ok:#3ecf80}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,sans-serif}}
main{{max-width:980px;margin:0 auto;padding:24px 16px 64px}}
h1{{margin:0 0 4px}} h2{{margin:0 0 8px;font-size:20px}} h3{{margin:16px 0 8px;font-size:15px}} h4{{margin:12px 0 4px;font-size:13px;color:var(--mut)}}
section{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:16px 0}}
.muted,small,.val span{{color:var(--mut)}} .muted{{font-size:13px}}
.row{{display:grid;grid-template-columns:minmax(120px,38%) 1fr 90px;gap:10px;align-items:center;margin:5px 0}}
.lab small{{display:block;font-size:11px}} .val{{text-align:right;font-variant-numeric:tabular-nums}}
.track{{background:var(--line);border-radius:6px;height:12px;overflow:hidden}}
.fill{{height:100%;background:var(--fill);border-radius:6px}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
.card{{border:1px solid var(--line);border-radius:10px;padding:12px}} .card h3{{margin:0}}
.big{{font-size:26px;font-weight:700}} .big small{{font-size:12px;font-weight:400}} .big2{{font-size:18px;color:var(--fill);font-weight:600;margin-bottom:6px}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:20px}} @media(max-width:700px){{.two{{grid-template-columns:1fr}} .row{{grid-template-columns:1fr 80px}} .track{{grid-column:1/3;order:3}}}}
table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}} th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right}} th.left{{text-align:left}}
.heat td{{text-align:center}} .heat td:not(.tot){{background:color-mix(in srgb,var(--fill) calc(var(--a,0)*100%),transparent)}} .tot{{text-align:right}}
.gear td{{text-align:left}} .gear span{{display:inline-block;margin:2px 10px 2px 0}} .gear .maj{{color:var(--ok);font-weight:600}}
.chips{{display:flex;flex-wrap:wrap;gap:8px}} .chip{{border:1px solid var(--c);border-radius:999px;padding:3px 10px;font-size:13px;display:inline-flex;gap:5px;align-items:center}}
.chip i{{width:10px;height:10px;border-radius:50%;background:var(--c)}}
.combos{{margin:4px 0 0;padding-left:20px;font-size:14px}}
.pbtn{{float:right;padding:6px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);cursor:pointer}}
@media print{{
:root{{--bg:#fff;--fg:#111;--mut:#555;--card:#fff;--line:#ccc;--fill:#4a5bdc;--ok:#127a40}}
*{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.pbtn{{display:none}} main{{max-width:none;padding:0}} section{{break-inside:avoid;margin:10px 0}}
@page{{size:A4;margin:12mm}}}}
</style></head><body><main>
<button class="pbtn" onclick="window.print()">Enregistrer en PDF</button>
<h1>Builds {hero}</h1>
<p class="muted">{n} builds analyses - donjon(s) : {encounters} - scores de classement : {scores}</p>
{body}
</main></body></html>
"""


# --------------------------------------------------------------------------
def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hero", nargs="+", help="un ou plusieurs heros, ex. Helena Mara")
    ap.add_argument("--all", action="store_true", help="tous les heros connus")
    ap.add_argument("--top", type=int, default=30, help="joueurs par heros et par donjon")
    ap.add_argument("--encounter", nargs="+", type=int, default=DEFAULT_ENCOUNTERS,
                    help="identifiants de donjons (ex. 150006)")
    args = ap.parse_args()

    cid = os.environ.get("FELLOWSHIP_CLIENT_ID")
    secret = os.environ.get("FELLOWSHIP_CLIENT_SECRET")
    if not cid or not secret:
        sys.exit("Definis d'abord FELLOWSHIP_CLIENT_ID et FELLOWSHIP_CLIENT_SECRET "
                 "(voir le mode d'emploi).")

    heroes = KNOWN_HEROES if args.all else (args.hero or ["Helena"])
    client = Client(cid, secret)
    OUT_DIR.mkdir(exist_ok=True)
    for hero in heroes:
        print(f"== {hero} ==")
        builds = collect_builds(client, hero, args.encounter, args.top)
        if not builds:
            print(f"  Aucun build exploitable pour {hero}.")
            continue
        report = build_report(hero, builds, args.encounter)
        (OUT_DIR / f"resume_{hero}.md").write_text(report, encoding="utf-8")
        (OUT_DIR / f"resume_{hero}.html").write_text(
            build_html(hero, builds, args.encounter), encoding="utf-8")
        (OUT_DIR / f"builds_{hero}.json").write_text(
            json.dumps(builds, ensure_ascii=False, indent=1), encoding="utf-8")
        print(report)
        print(f"  -> ecrit dans {OUT_DIR / ('resume_' + hero + '.md')} et resume_{hero}.html")
        print(f"  Quota utilise cette heure : {client.spent:.0f}/{client.limit:.0f}")


if __name__ == "__main__":
    main()
