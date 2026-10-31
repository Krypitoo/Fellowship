#!/usr/bin/env python3
"""Lit les bonus de gemmes copies depuis fellows.gg ("Nom", "Couleur•Power N", description)
et ecrit gemmes.json :  python outils/importer_gemmes.py copie.txt"""
import json, re, sys
from pathlib import Path

DEST = Path(__file__).resolve().parent.parent / "gemmes.json"
HEAD = re.compile(r"^(\w+)\s*[•·]\s*Power\s+(\d+)$")

lines = [l.rstrip() for l in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()]
heads = [i for i in range(1, len(lines)) if HEAD.match(lines[i].strip()) and lines[i - 1].strip()]
out = {}
for k, i in enumerate(heads):
    color, power = HEAD.match(lines[i].strip()).groups()
    end = heads[k + 1] - 1 if k + 1 < len(heads) else len(lines)
    body = "\n".join(l.strip() for l in lines[i + 1:end]).strip()
    rep = re.search(r"\(Replaces (.+?)\)", body)
    body = re.sub(r"\s*\(Replaces .+?\)\s*$", "", body).strip()
    out.setdefault(color, []).append({"name": " ".join(lines[i - 1].split()), "power": int(power),
                                      "desc": re.sub(r"\n{3,}", "\n\n", body),
                                      "replaces": rep.group(1) if rep else None})
for c in out:
    out[c].sort(key=lambda b: b["power"])
DEST.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print({c: len(v) for c, v in out.items()})
