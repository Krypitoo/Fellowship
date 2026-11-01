import sys, json, os
sys.path.insert(0, ".")
from comparer_builds import Client
c = Client(os.environ["FELLOWSHIP_CLIENT_ID"], os.environ["FELLOWSHIP_CLIENT_SECRET"])
for code in ["FdGy76ZrcA1BbfhL","nd3pfJ8CBMZGxjc6","h9zPd7Y4fJq8RtHw","PV8x7bdRjBf3YqvK","Tpzv7g4FZMGqtwDA","xHhBzmV9afGFDWNL"]:
    try:
        rep = c.query('reportData { report(code: %s) { startTime masterData { actors(type: "Player") { id name subType type } } fights { id encounterID startTime friendlyPlayers } } }' % json.dumps(code))["reportData"]["report"]
    except Exception as e:
        print(code, "ERR", e); continue
    act = {a["id"]: (a["name"], a.get("subType")) for a in rep["masterData"]["actors"]}
    fs = [f for f in rep["fights"] if f.get("encounterID")]
    print("==", code, len(fs), "fights; actors", sorted(set(act.values())))
    heroes = {}
    for f in fs:
        for i in f.get("friendlyPlayers") or []:
            if act.get(i, ("",""))[0] == "Krypi": heroes.setdefault(act[i][1], []).append((f["id"], f["encounterID"]))
    print("   Krypi:", {h: v[-3:] for h, v in heroes.items()})
print(c.query("rateLimitData { pointsSpentThisHour limitPerHour }"))
