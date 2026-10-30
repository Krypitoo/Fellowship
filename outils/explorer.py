# Exploration ponctuelle : schema de l'API (champs "description") et lisibilite de fellows.gg
import base64, json, os, re, urllib.request
out = {}
cid, sec = os.environ["FELLOWSHIP_CLIENT_ID"], os.environ["FELLOWSHIP_CLIENT_SECRET"]
UA = {"User-Agent": "PersonalBuildSummary/1.0 (usage personnel)"}
def post(url, data, headers):
    r = urllib.request.Request(url, data=data, headers={**UA, **headers}, method="POST")
    return json.loads(urllib.request.urlopen(r, timeout=60).read())
tok = post("https://www.fellowshiplogs.com/oauth/token", b"grant_type=client_credentials",
           {"Authorization": "Basic " + base64.b64encode(f"{cid}:{sec}".encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded"})["access_token"]
def gql(q):
    return post("https://www.fellowshiplogs.com/api/v2/client", json.dumps({"query": q}).encode(),
                {"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
q = "{ __schema { types { name kind fields { name args { name } type { name kind ofType { name kind ofType { name } } } } } } }"
s = gql(q)
types = {t["name"]: t for t in s["data"]["__schema"]["types"] if not t["name"].startswith("__")}
out["types_avec_description"] = {n: [f["name"] for f in t["fields"] or []] for n, t in types.items()
                                 if any(re.search("desc|tooltip|text", f["name"], re.I) for f in t["fields"] or [])}
out["GameData"] = {n: [(f["name"], [a["name"] for a in f["args"]]) for f in (t["fields"] or [])]
                   for n, t in types.items() if n.lower().startswith("game")}
for test in ["{ gameData { ability(id: 2000158) { id name icon description } } }",
             "{ gameData { ability(id: 2000158) { id name icon } } }"]:
    try: out[test] = gql(test)
    except Exception as e: out[test] = repr(e)[:300]
for url in ["https://fellows.gg/talent/158/frog-squad", "https://fellows.gg/api/talents"]:
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30)
        body = r.read().decode("utf-8", "replace")
        out[url] = {"status": r.status, "taille": len(body), "debut": body[:1500],
                    "infernal": [m.start() for m in re.finditer("Infernal|Frog Squad", body)][:5],
                    "scripts_json": re.findall(r'<script[^>]*(?:json|__NEXT_DATA__|__NUXT__)[^>]*>', body)[:5]}
    except Exception as e:
        out[url] = repr(e)[:300]
os.makedirs("outils", exist_ok=True)
json.dump(out, open("outils/exploration.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:3000])
