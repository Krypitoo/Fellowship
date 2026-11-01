import sys, json, datetime
sys.path.insert(0, ".")
from comparer_builds import Client, fetch_fight_players
import os
c = Client(os.environ["FELLOWSHIP_CLIENT_ID"], os.environ["FELLOWSHIP_CLIENT_SECRET"])
def d(ms): return datetime.datetime.utcfromtimestamp((ms or 0)/1000).strftime("%m-%d %H:%M")
for nom in ["Krypi", "MrApple"]:
    q = ('characterData { character(name: %s, serverSlug: "global", serverRegion: "global") '
         '{ id name recentReports(limit: 10) { data { code startTime } } } }' % json.dumps(nom))
    ch = c.query(q)["characterData"]["character"]
    print("==", nom, ch and ch["id"])
    for r in (ch or {}).get("recentReports", {}).get("data", []):
        print("  report", r["code"], d(r["startTime"]))
q = ('characterData { character(name: "MrApple", serverSlug: "global", serverRegion: "global") '
     '{ recentReports(limit: 3) { data { code startTime } } } }')
reps = c.query(q)["characterData"]["character"]["recentReports"]["data"]
for r in sorted(reps, key=lambda r: -r["startTime"])[:2]:
    rep = c.query('reportData { report(code: %s) { startTime owner { name } fights { id encounterID startTime } } }' % json.dumps(r["code"]))["reportData"]["report"]
    print("== report MrApple", r["code"], d(rep["startTime"]), rep.get("owner"))
    for f in [f for f in rep["fights"] if f.get("encounterID")][-3:]:
        pl = fetch_fight_players(c, r["code"], f["id"])
        print("  fight", f["id"], f["encounterID"], [(p.get("name"), p.get("type"), bool(p.get("combatantInfo"))) for l in pl.values() for p in (l or [])])
