# Extract unlockable content + the branch path required to reach it.
import os, re, json, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "_decompiled"
OUT = sys.argv[2] if len(sys.argv) > 2 else "_analysis"

COR = re.compile(r'(addCor|totalCorruption\.add)\(\s*"([^"]*)"\s*\)')
PUSH = re.compile(r'PushToLog\(\s*"(.*?)"\s*\)')
IMG = re.compile(r'\{image=ui/iconmini(\w+)\.png\}|\{image=ui/cor\w+\.png\}')

def parse_cor(v):
    d = {"scene": "", "tier": "", "cha": "", "style": "", "preg": "", "peg": "", "name": ""}
    try:
        scene, _, rest = v.partition("|t|")
        tier, _, rest = rest.partition("|c|")
        cha, _, rest = rest.partition("|s|")
        style, _, rest = rest.partition("|p|")
        preg, _, rest = rest.partition("|f|")
        peg, _, name = rest.partition("|n|")
        d.update(scene=scene, tier=tier, cha=cha, style=style, preg=preg, peg=peg, name=name)
    except Exception:
        pass
    return d

def indent(line):
    return len(line) - len(line.lstrip(" "))

# lines that establish context worth reporting
CTX = re.compile(r'^(label |menu:|"|if |elif |else:|while )')

def context_chain(lines, i):
    """Walk upward collecting the enclosing label / menu-choice / condition lines."""
    chain = []
    cur = indent(lines[i])
    j = i - 1
    while j >= 0 and cur > 0:
        l = lines[j]
        if not l.strip() or l.strip().startswith("#"):
            j -= 1; continue
        ind = indent(l)
        if ind < cur:
            s = l.strip()
            if CTX.match(s):
                chain.append((ind, s))
                cur = ind
            else:
                cur = ind
        j -= 1
    chain.reverse()
    return chain

def main():
    os.makedirs(OUT, exist_ok=True)
    records = []
    catalog = {}      # full corruption catalog from totalCorruption.add
    unlock_notes = [] # PushToLog "Corruption Unlock" style messages

    for fn in sorted(os.listdir(SRC)):
        if not fn.endswith(".rpy"): continue
        lines = open(os.path.join(SRC, fn), encoding="utf-8").read().split("\n")
        for i, line in enumerate(lines):
            m = COR.search(line)
            if m:
                kind, val = m.group(1), m.group(2)
                rec = parse_cor(val)
                rec["kind"] = "catalog" if kind != "addCor" else "unlock"
                rec["file"] = fn
                rec["line"] = i + 1
                rec["raw"] = val
                if rec["kind"] == "catalog":
                    catalog[val] = rec
                else:
                    rec["path"] = [s for _, s in context_chain(lines, i)]
                    records.append(rec)
            p = PUSH.search(line)
            if p and ("Corruption Unlock" in p.group(1) or "New Mail" in p.group(1)
                      or "New Memory" in p.group(1) or "Unlock" in p.group(1)):
                txt = p.group(1)
                cha = ""
                mm = re.search(r'iconmini(\w+)\.png', txt)
                if mm: cha = mm.group(1)
                clean = re.sub(r'\{[^}]*\}', '', txt).strip()
                unlock_notes.append({
                    "file": fn, "line": i + 1, "cha": cha, "text": clean,
                    "path": [s for _, s in context_chain(lines, i)],
                })

    json.dump({"catalog": list(catalog.values()), "unlocks": records,
               "notes": unlock_notes},
              open(os.path.join(OUT, "content.json"), "w", encoding="utf-8"), indent=1)

    # ---- summary ----
    print("catalog entries : %d" % len(catalog))
    print("addCor sites    : %d" % len(records))
    print("push notes      : %d" % len(unlock_notes))

    from collections import Counter, defaultdict
    print("\nBy character (catalog):")
    for c, n in Counter(r["cha"] for r in catalog.values()).most_common():
        print("  %-10s %d" % (c, n))
    print("\nBy tier (catalog):")
    for c, n in sorted(Counter(r["tier"] for r in catalog.values()).items()):
        print("  tier %-3s %d" % (c, n))
    print("\nBy style (catalog):")
    for c, n in Counter(r["style"] for r in catalog.values()).most_common():
        print("  %-8s %d" % (c, n))

    # which catalog entries are never granted by an addCor
    granted = set(r["raw"] for r in records)
    orphan = [k for k in catalog if k not in granted]
    print("\ncatalog entries with no addCor site: %d" % len(orphan))
    for o in orphan[:15]: print("   ", o)

if __name__ == "__main__":
    main()
