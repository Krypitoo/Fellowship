import sys, json, os, datetime
sys.path.insert(0, ".")
from comparer_builds import Client
c = Client(os.environ["FELLOWSHIP_CLIENT_ID"], os.environ["FELLOWSHIP_CLIENT_SECRET"])
for nom in ["Krypi","MrApple"]:
    ch = c.query('characterData { character(name: %s, serverSlug: "global", serverRegion: "global") { recentReports(limit: 3) { data { code startTime endTime } } } }' % json.dumps(nom))["characterData"]["character"]
    for r in ch["recentReports"]["data"]: print(nom, r["code"], datetime.datetime.fromtimestamp(r["startTime"]/1000, datetime.UTC))
r = c.query('reportData { reports(limit: 5) { data { code startTime owner { name } title } } }')
print(json.dumps(r)[:1500])
