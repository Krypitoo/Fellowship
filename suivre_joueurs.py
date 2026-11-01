#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
suivre_joueurs.py - recupere le build actuel des joueurs listes dans joueurs.json
(dernier combat de donjon trouve dans leurs logs recents sur Fellowship Logs).

  python suivre_joueurs.py            -> ecrit resultats/joueurs_suivis.json

joueurs.json : [{"nom": "Kerdead", "heros": "Helena"}, ...]  ("heros" est facultatif :
sans lui, on prend le heros joue dans le dernier log).
"""
import csv
import io
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from comparer_builds import Client, KNOWN_HEROES, OUT_DIR, cache_get, cache_put, fetch_fight_players

HERE = Path(__file__).resolve().parent
LISTE = HERE / "joueurs.json"
FORM = HERE / "formulaire.json"            # pseudos envoyes depuis le site (formulaire Google)
PSEUDO_OK = re.compile(r"^[^\W_][\w' .-]{1,23}$", re.UNICODE)


ETAT = HERE / "etat_demandes.json"       # demandes d'actualisation deja traitees
DELAI_MIN_MS = 3600 * 1000                 # une actualisation par pseudo et par heure au plus
ACTUALISER = "Actualiser"


def form_rows():
    if not FORM.exists():
        return None
    cfg = json.loads(FORM.read_text(encoding="utf-8"))
    try:
        raw = urllib.request.urlopen(cfg["reponses_csv"], timeout=30).read().decode("utf-8")
    except Exception as e:
        print(f"Formulaire illisible : {e}")
        return None
    return list(csv.reader(io.StringIO(raw)))[1:], cfg


def form_players():
    """Pseudos saisis sur le site : le plus recent d'abord, un seul par pseudo, format verifie."""
    got = form_rows()
    if not got:
        return []
    rows, cfg = got
    rows = [r for r in rows if len(r) >= 3 and r[2].strip() != ACTUALISER]
    seen, out = set(), []
    for r in reversed(rows):                      # les reponses les plus recentes en premier
        if len(r) < 3:
            continue
        nom, heros = r[1].strip(), r[2].strip().capitalize()
        if heros not in KNOWN_HEROES:
            heros = None                          # "Tous" : tous les heros joues par ce pseudo
        if not PSEUDO_OK.match(nom):
            continue
        key = (nom.lower(), heros)
        if key in seen:
            continue
        seen.add(key)
        out.append({"nom": nom, "heros": heros, "source": "site"})
    return out[: int(cfg.get("max_joueurs", 100))]
MAX_REPORTS = 20   # logs recents parcourus par joueur
MAX_OWNERS = 3     # comptes dont on lit aussi les derniers logs envoyes
MAX_FIGHTS = 15    # builds lus au maximum par joueur (un par heros trouve)


def recent_reports(client, nom):
    """Logs recents du joueur. Fellowship Logs met du temps a rattacher un nouveau log aux
    personnages : on ajoute donc les derniers logs envoyes par les comptes qui ont publie ses
    logs (lui-meme ou un membre de son groupe), qu'on filtre ensuite sur son nom."""
    body = ('characterData { character(name: %s, serverSlug: "global", serverRegion: "global") '
            '{ id name recentReports(limit: %d) { data { code startTime owner { id } } } } }' % (json.dumps(nom), MAX_REPORTS))
    ch = client.query(body)["characterData"]["character"]
    if not ch:
        return None
    reps = {r["code"]: r for r in (ch.get("recentReports") or {}).get("data") or []}
    owners = []
    for r in sorted(reps.values(), key=lambda r: -(r.get("startTime") or 0)):
        oid = (r.get("owner") or {}).get("id")
        if oid and oid not in owners:
            owners.append(oid)
    for oid in owners[:MAX_OWNERS]:
        try:
            got = client.query('reportData { reports(userID: %d, limit: 5) { data { code startTime } } }' % int(oid))
            for r in got["reportData"]["reports"]["data"] or []:
                reps.setdefault(r["code"], r)
        except Exception as e:  # le suivi marche quand meme sans ce complement
            print(f"  (logs du compte {oid} non lus : {e})")
    return sorted(reps.values(), key=lambda r: -(r.get("startTime") or 0))[:MAX_REPORTS + 5]


def report_fights(client, code, start=None):
    """Combats d'un log, avec pour chacun les heros joues par chaque joueur (sans lire les builds).
    Un log recent peut encore recevoir des combats : on ne garde en cache que les logs de plus de 2 jours."""
    name = f"fights2_{code}.json"
    ancien = start and time.time() * 1000 - start > 48 * 3600 * 1000
    cached = cache_get(name, 24 * 30) if ancien else None
    if cached is not None:
        return cached
    body = ('reportData { report(code: %s) { startTime masterData { actors(type: "Player") { id name subType } } '
            'fights { id encounterID startTime friendlyPlayers } } }' % json.dumps(code))
    rep = client.query(body)["reportData"]["report"] or {}
    actors = {a["id"]: [a.get("name"), a.get("subType")] for a in (rep.get("masterData") or {}).get("actors") or []}
    fights = [{"id": f["id"], "encounterID": f["encounterID"], "startTime": f.get("startTime"),
               "players": [actors[i] for i in f.get("friendlyPlayers") or [] if i in actors]}
              for f in rep.get("fights") or [] if f.get("encounterID")]
    out = {"startTime": rep.get("startTime"), "fights": fights}
    cache_put(name, out)
    return out


def find_builds(client, nom, heros=None):
    """Build du combat le plus recent de chaque heros joue par `nom` (ou du seul `heros` demande).
    Tous les combats des logs recents sont classes par date reelle (debut du log + moment du
    combat), tous logs confondus, puis on lit le build du plus recent pour chaque heros."""
    reports = recent_reports(client, nom)
    if reports is None:
        return [], "joueur introuvable sur Fellowship Logs"
    combats = []   # (date, code du log, combat, heros joues par `nom`)
    for rep in reports:
        info = report_fights(client, rep["code"], rep.get("startTime"))
        debut = info.get("startTime") or rep.get("startTime") or 0
        for f in info["fights"]:
            joues = {h for n, h in f["players"] if n == nom and h in KNOWN_HEROES and (not heros or h == heros)}
            if joues:
                combats.append((debut + (f.get("startTime") or 0), rep["code"], f, joues))
    combats.sort(key=lambda c: -c[0])
    found, lus = {}, 0
    for date, code, f, joues in combats:
        joues = joues - found.keys()
        if not joues or lus >= MAX_FIGHTS:
            continue
        lus += 1
        players = fetch_fight_players(client, code, f["id"])
        for lst in players.values():
            for p in lst or []:
                h = p.get("type")
                if p.get("name") == nom and h in joues and p.get("combatantInfo"):
                    found[h] = {"heros": h, "report": code, "fight": f["id"],
                                "encounter": f.get("encounterID"), "date": date,
                                "info": p["combatantInfo"]}
        if heros and heros in found:
            break
    if not found:
        return [], "aucun combat de donjon trouvé dans les derniers logs" + (f" avec {heros}" if heros else "")
    return list(found.values()), None


def demandes(client_factory):
    """Mode --demandes : traite les nouvelles lignes du formulaire (demandes d'actualisation
    et nouvelles inscriptions) depuis le dernier passage. Ecrit resultats/joueurs_maj.json."""
    etat = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.exists() else {"lignes": None, "dernier": {}}
    got = form_rows()
    if not got:
        return False
    rows, _ = got
    if etat.get("lignes") is None:          # premier passage : on part de la fin, sans tout retraiter
        etat["lignes"] = len(rows)
        ETAT.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
        print("Etat initialise"); return False
    nouvelles = rows[etat["lignes"]:]
    etat["lignes"] = len(rows)
    now = int(time.time() * 1000)
    noms = []
    for r in nouvelles:
        if len(r) < 2 or not PSEUDO_OK.match(r[1].strip()):
            continue
        nom = r[1].strip()
        if now - etat["dernier"].get(nom.lower(), 0) < DELAI_MIN_MS:
            print(f"{nom} : deja actualise il y a moins d'une heure"); continue
        if nom.lower() not in {n.lower() for n in noms}:
            noms.append(nom)
    noms = noms[:20]                        # au plus 20 joueurs par passage (quota de l'API)
    if not noms:
        ETAT.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
        print("Aucune demande a traiter"); return False
    client = client_factory()
    out = []
    for nom in noms:
        try:
            builds, err = find_builds(client, nom)
        except Exception as e:
            builds, err = [], f"erreur API : {str(e)[:200]}"
        if err:
            out.append({"nom": nom, "heros": None, "erreur": err, "releve": now})
        for res in builds:
            res.update({"nom": nom, "releve": now}); out.append(res)
        etat["dernier"][nom.lower()] = now
        print(f"{nom} : {err or ', '.join(r['heros'] for r in builds)}")
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "joueurs_maj.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    ETAT.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--demandes" in sys.argv:
        fait = demandes(lambda: Client(os.environ["FELLOWSHIP_CLIENT_ID"], os.environ["FELLOWSHIP_CLIENT_SECRET"]))
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as f:
                f.write(f"a_faire={'true' if fait else 'false'}\n")
        return
    liste = json.loads(LISTE.read_text(encoding="utf-8")) if LISTE.exists() else []
    connus = {(j["nom"].lower(), j.get("heros")) for j in liste}
    for j in form_players():
        if (j["nom"].lower(), j["heros"]) not in connus:
            liste.append(j)
            connus.add((j["nom"].lower(), j["heros"]))
    print(f"{len(liste)} joueur(s) a suivre")
    if not liste:
        OUT_DIR.mkdir(exist_ok=True)
        (OUT_DIR / "joueurs_suivis.json").write_text("[]", encoding="utf-8")
        print("Aucun joueur a suivre"); return
    client = Client(os.environ["FELLOWSHIP_CLIENT_ID"], os.environ["FELLOWSHIP_CLIENT_SECRET"])
    out = []
    # un pseudo inscrit sans heros couvre tous ses heros : inutile de le chercher aussi heros par heros
    tous = {j["nom"].lower() for j in liste if not j.get("heros")}
    liste = [j for j in liste if not j.get("heros") or j["nom"].lower() not in tous]
    now = int(time.time() * 1000)
    for j in liste:
        nom, heros = j.get("nom"), j.get("heros")
        try:
            builds, err = find_builds(client, nom, heros)
        except Exception as e:  # un joueur en erreur ne bloque pas les autres
            builds, err = [], f"erreur API : {str(e)[:200]}"
        if err:
            out.append({"nom": nom, "heros": heros, "erreur": err, "releve": now})
        for res in builds:
            res.update({"nom": nom, "releve": now})
            out.append(res)
        print(f"{nom} : {err or ', '.join(r['heros'] for r in builds)}")
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "joueurs_suivis.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
