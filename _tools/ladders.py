# Extract the corruption ladder (var -> display name) and every unlock site.
import os, re, json, sys
sys.path.insert(0, os.path.dirname(__file__))
from analyze import context_chain

SRC = "_decompiled"
CHARS = ["alex", "carla", "cassidy", "haily", "jenny", "lin", "lina", "lisa", "sami"]

# In the end-menu, a locked level renders "???"; an unlocked one renders a
# _textbutton whose label is the display name and whose action sets <var>On.
# Each rung renders as:  if <var>On:  ...  _textbutton " {size=12}<Name>{/size}"
# The guard names the rung; the action lists cascade prerequisites in an order
# that differs per character, so the guard is the only reliable anchor.
GUARD = re.compile(r'^if (\w+?)On:$')
LABEL = re.compile(r'_textbutton\s+"\s*\{size=12\}(.*?)\{/size\}"')

def ladder():
    # Per-character panels (v0.62) take priority over the legacy combined file.
    files = [f for f in sorted(os.listdir(SRC))
             if f.startswith("sceneEndChoices") and f != "sceneEndChoices.rpy"]
    files.append("sceneEndChoices.rpy")
    names = {}
    for f in files:
        pending = None
        for line in open(os.path.join(SRC, f), encoding="utf-8"):
            s = line.strip()
            g = GUARD.match(s)
            if g:
                pending = g.group(1)
                continue
            if pending:
                m = LABEL.search(s)
                if m:
                    names.setdefault(pending, m.group(1).strip())
                    pending = None
                elif s.startswith(("if ", "elif ", "else:")):
                    pending = None
    return names

# Moonstone/Preg are stored inverted vs the numbered tiers.
def unlocked_value(var):
    return "True" if "Moonstone" in var else "False"

def find_unlocks(vars_):
    sites = {v: [] for v in vars_}
    # matches both "$ var = False" and a bare "var = False" inside python:
    pat = {v: re.compile(r'^(?:\$\s*)?%s\s*=\s*(True|False)\s*$' % re.escape(v)) for v in vars_}
    for fn in sorted(os.listdir(SRC)):
        if not fn.endswith(".rpy"): continue
        if fn == "characters.rpy" or fn.startswith("sceneEndChoices"): continue
        lines = open(os.path.join(SRC, fn), encoding="utf-8").read().split("\n")
        for i, line in enumerate(lines):
            s = line.strip()
            if "Corruption" not in s: continue
            for v in vars_:
                m = pat[v].match(s)
                if m and m.group(1) == unlocked_value(v):
                    sites[v].append({
                        "file": fn, "line": i + 1,
                        "path": [p for _, p in context_chain(lines, i)],
                    })
    return sites

def main():
    names = ladder()
    vars_ = [v for v in names if any(v.startswith(c) for c in CHARS)]
    sites = find_unlocks(vars_)

    out = {}
    for c in CHARS:
        out[c] = []
        for v in vars_:
            if not v.startswith(c): continue
            # avoid 'lin' matching 'lina'
            if c == "lin" and v.startswith("lina"): continue
            out[c].append({"var": v, "name": names[v], "sites": sites[v]})
    json.dump(out, open("_analysis/ladders.json", "w", encoding="utf-8"), indent=1)

    for c in CHARS:
        print("\n=== %s ===" % c.upper())
        for e in out[c]:
            locs = ", ".join("%s:%s" % (s["file"].replace(".rpy", ""), s["line"]) for s in e["sites"]) or "NO DIRECT SITE"
            print("  %-32s %-14s %s" % (e["var"], e["name"], locs))

if __name__ == "__main__":
    main()
