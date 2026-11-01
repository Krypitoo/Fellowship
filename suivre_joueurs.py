#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
suivre_joueurs.py - recupere le build actuel des joueurs listes dans joueurs.json
(dernier combat de donjon trouve dans leurs logs recents sur Fellowship Logs).

  python suivre_joueurs.py            -> ecrit resultats/joueurs_suivis.json

joueurs.json : [{"nom": "Kerdead", "heros": "Helena"}, ...]  ("heros" est facultatif :
sans lui, on prend le heros joue dans le dernier log).
"""
import json
import os
import sys
import time
from pathlib import Path

from comparer_builds import Client, OUT_DIR, cache_get, cache_put, fetch_fight_players

HERE = Path(__file__).resolve().parent
LISTE = HERE / "joueurs.json"
MAX_REPORTS = 5


def recent_reports(client, nom):
    body = ('characterData { character(name: %s, serverSlug: "global", serverRegion: "global") '
            '{ id name recentReports(limit: %d) { data { code startTime } } } }' % (json.dumps(nom), MAX_REPORTS))
    ch = client.query(body)["characterData"]["character"]
    if not ch:
        return None
    return sorted((ch.get("recentReports") or {}).get("data") or [], key=lambda r: -(r.get("startTime") or 0))


def report_fights(client, code):
    name = f"fights_{code}.json"
    cached = cache_get(name, 24)
    if cached is not None:
        return cached
    body = 'reportData { report(code: %s) { startTime fights { id encounterID startTime } } }' % json.dumps(code)
    rep = client.query(body)["reportData"]["report"] or {}
    fights = [f for f in rep.get("fights") or [] if f.get("encounterID")]
    out = {"startTime": rep.get("startTime"), "fights": fights}
    cache_put(name, out)
    return out


def find_build(client, nom, heros):
    reports = recent_reports(client, nom)
    if reports is None:
        return {"erreur": "joueur introuvable sur Fellowship Logs"}
    for rep in reports:
        info = report_fights(client, rep["code"])
        for f in sorted(info["fights"], key=lambda f: -(f.get("startTime") or 0)):
            players = fetch_fight_players(client, rep["code"], f["id"])
            for lst in players.values():
                for p in lst or []:
                    if p.get("name") != nom or not p.get("combatantInfo"):
                        continue
                    if heros and p.get("type") != heros:
                        continue
                    return {"heros": p.get("type"), "report": rep["code"], "fight": f["id"],
                            "encounter": f.get("encounterID"),
                            "date": (info.get("startTime") or 0) + (f.get("startTime") or 0),
                            "info": p["combatantInfo"]}
    return {"erreur": "aucun combat de donjon trouve dans les derniers logs" + (f" avec {heros}" if heros else "")}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    liste = json.loads(LISTE.read_text(encoding="utf-8")) if LISTE.exists() else []
    if not liste:
        print("joueurs.json vide : rien a faire"); return
    client = Client(os.environ["FELLOWSHIP_CLIENT_ID"], os.environ["FELLOWSHIP_CLIENT_SECRET"])
    out = []
    for j in liste:
        nom, heros = j.get("nom"), j.get("heros")
        try:
            res = find_build(client, nom, heros)
        except Exception as e:  # un joueur en erreur ne bloque pas les autres
            res = {"erreur": f"erreur API : {str(e)[:200]}"}
        res.update({"nom": nom, "heros": res.get("heros") or heros, "releve": int(time.time() * 1000)})
        print(f"{nom} ({res.get('heros')}) : {res.get('erreur') or 'build trouve'}")
        out.append(res)
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "joueurs_suivis.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
