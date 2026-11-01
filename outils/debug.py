# Diagnostic ponctuel : traits bruts de Krypi (Helena) dans le combat releve
import json, os, sys
sys.path.insert(0, ".")
from comparer_builds import Client, fetch_fight_players
c = Client(os.environ["FELLOWSHIP_CLIENT_ID"], os.environ["FELLOWSHIP_CLIENT_SECRET"])
players = fetch_fight_players(c, "h9zPd7Y4fJq8RtHw", int(os.environ.get("FIGHT", "0") or 0)) if os.environ.get("FIGHT") else None
if players is None:
    body = 'reportData { report(code: "h9zPd7Y4fJq8RtHw") { fights { id encounterID startTime } } }'
    fights = [f for f in c.query(body)["reportData"]["report"]["fights"] if f.get("encounterID")]
    for f in fights:
        players = fetch_fight_players(c, "h9zPd7Y4fJq8RtHw", f["id"])
        for lst in players.values():
            for p in lst or []:
                if p.get("name") == "Krypi" and f["encounterID"] == 150013:
                    info = p["combatantInfo"]
                    print("FIGHT", f["id"], f["encounterID"])
                    for g in info.get("gear") or []:
                        print("GEAR", g.get("slot"), repr(g.get("name")), [(t.get("name"), t.get("rank"), t.get("id")) for t in g.get("traits") or []])
                    print("ARTIFACT", [(a.get("name"), a.get("total"), a.get("type"), a.get("guid")) for a in info.get("artifact") or []])
                    print("KEYS", list(info.keys()))
                    raise SystemExit
