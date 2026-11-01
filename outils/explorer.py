# Exploration ponctuelle : peut-on retrouver le build d'un joueur precis ?
import base64, json, os, urllib.request
cid, sec = os.environ["FELLOWSHIP_CLIENT_ID"], os.environ["FELLOWSHIP_CLIENT_SECRET"]
UA = {"User-Agent": "PersonalBuildSummary/1.0 (usage personnel)"}
def post(url, data, headers):
    r = urllib.request.Request(url, data=data, headers={**UA, **headers}, method="POST")
    return json.loads(urllib.request.urlopen(r, timeout=60).read())
tok = post("https://www.fellowshiplogs.com/oauth/token", b"grant_type=client_credentials",
           {"Authorization": "Basic " + base64.b64encode(f"{cid}:{sec}".encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded"})["access_token"]
def gql(q):
    try:
        return post("https://www.fellowshiplogs.com/api/v2/client", json.dumps({"query": q}).encode(),
                    {"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    except Exception as e:
        return {"exception": repr(e)[:300]}
out = {}
def typ(name):
    return gql('{ __type(name: "%s") { name fields { name args { name type { name kind ofType { name } } } type { name kind ofType { name kind ofType { name } } } } } }' % name)
for t in ["CharacterData", "Character", "Server", "Region", "WorldData", "User", "UserData"]:
    out["type_" + t] = typ(t)
# un joueur du classement pour tester
r = gql('{ worldData { encounter(id: 150006) { characterRankings(specName: "Helena", page: 1) } } }')
try:
    rk = r["data"]["worldData"]["encounter"]["characterRankings"]
    rk = json.loads(rk) if isinstance(rk, str) else rk
    first = rk["rankings"][0]
    out["exemple_classement"] = {k: first.get(k) for k in ("name", "server", "class", "spec", "report", "hardModeLevel", "id", "guild")}
    srv = first.get("server") or {}
    name = first["name"]
    out["test_character_nom"] = gql('{ characterData { character(name: %s, serverSlug: %s, serverRegion: %s) { id name } } }'
                                    % (json.dumps(name), json.dumps(srv.get("name", "")), json.dumps(srv.get("region", ""))))
    if first.get("id"):
        out["test_character_id"] = gql('{ characterData { character(id: %d) { id name } } }' % first["id"])
except Exception as e:
    out["erreur_classement"] = repr(e)[:300]
os.makedirs("outils", exist_ok=True)
json.dump(out, open("outils/exploration.json", "w"), ensure_ascii=False, indent=1)
