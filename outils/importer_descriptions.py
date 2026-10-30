#!/usr/bin/env python3
"""Ajoute a descriptions.json les descriptions copiees depuis une page "Database" de fellows.gg
(Ctrl+A, Ctrl+C sur la page, colle dans un fichier texte).

  python outils/importer_descriptions.py copie.txt
"""
import json, re, sys
from pathlib import Path

DEST = Path(__file__).resolve().parent.parent / "descriptions.json"
PATCH = re.compile(r"^(Early Access|Season|Patch|Alpha|Beta|Release)\b.*", re.I)
SKIP = re.compile(r"^(Max Rank:.*|Cost:.*|-|Showing \d+ to \d+ of \d+ results)$", re.I)


def norm(s):
    return " ".join(s.split())


def parse(text):
    lines = [l.rstrip() for l in text.splitlines()]
    # le tableau commence apres la ligne d'en-tete "Name  Heroes  Description  Patch"
    start = next((k + 1 for k, l in enumerate(lines) if re.match(r"^Name\s.*Description", l.strip())), 0)
    lines = lines[start:]
    out, i = {}, 0
    while i < len(lines) - 1:
        name = norm(lines[i])
        # une entree commence par le nom ecrit deux fois (icone + lien)
        if name and norm(lines[i + 1]) == name and not PATCH.match(name):
            j, body = i + 2, []
            while j < len(lines) and not PATCH.match(lines[j].strip()):
                if lines[j + 1:j + 2] and norm(lines[j]) and norm(lines[j + 1]) == norm(lines[j]):
                    break  # entree suivante sans ligne de patch
                body.append(lines[j].strip())
                j += 1
            # retire en-tete (Max Rank, heros, tirets) avant la description
            # (categorie "Master", "StatEnchant", nom du heros... : un seul mot)
            while body and (not body[0] or SKIP.match(body[0]) or (" " not in body[0] and not body[0][0] in "+-0123456789")):
                body.pop(0)
            desc = "\n".join(body).strip()
            desc = re.sub(r"\n{3,}", "\n\n", desc)
            if desc:
                out[name] = desc
            i = j + 1
        else:
            i += 1
    return out


def main():
    data = json.loads(DEST.read_text(encoding="utf-8")) if DEST.exists() else {}
    for f in sys.argv[1:]:
        new = parse(Path(f).read_text(encoding="utf-8"))
        data.update(new)
        print(f"{f} : {len(new)} descriptions")
    DEST.write_text(json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {DEST.name} : {len(data)} descriptions au total")


if __name__ == "__main__":
    main()
