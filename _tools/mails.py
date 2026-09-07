# The phone mail catalogue.
#
# Mails are NOT the same thing as the `addCor(... n|New Mail: X)` corruption
# records. Those records only cover the mails that also happen to be worth a
# corruption token; the real catalogue is the per-character `<Char>SMS<n>`
# booleans, declared as `default <Char>SMS<n> = False` in sceneEndPhone.rpy and
# rendered by the Mail panel inside each `sceneEndChoices<Char>.rpy`.
#
# Three things have to be pulled out of the panel, because nothing else has
# them:
#   * the mail's display name        Text "Underboob" under `if <var>:`
#   * the game's own unlock hint     Tip="..." on the locked padlock button
#   * which variables are variants   `if A or B:` sharing one name cell
#
# Grants live in two places: inside story scenes (`$ AlexSMS6 = True`), and in
# the end-of-run sweep at the top of `label endCyclePhone`, which awards mail
# from conditions evaluated once the weekend is over. The sweep is dateVar 22,
# so it routes like any other site.
import json, os, re
from collections import defaultdict, OrderedDict

DEC = "_decompiled"
CHARS = ["Alex", "Carla", "Cassidy", "Haily", "Jenny", "Lina", "Lin", "Lisa", "Sami"]
RE_VAR = re.compile(r'\b(%s)SMS([0-9]+[a-z]?)\b' % "|".join(CHARS))   # Lina before Lin

def split_var(v):
    m = RE_VAR.match(v)
    return (m.group(1), m.group(2)) if m else (None, None)

def sort_key(v):
    _, n = split_var(v)
    m = re.match(r'(\d+)([a-z]?)', n or "0")
    return (int(m.group(1)), m.group(2))

# ---------- catalogue: every mail variable the game declares ----------

RE_DEFAULT = re.compile(r'^default ((?:%s)SMS[0-9]+[a-z]?) = ' % "|".join(CHARS))

def catalogue():
    out = defaultdict(list)
    for fn in sorted(os.listdir(DEC)):
        if not fn.endswith(".rpy"): continue
        for line in open(os.path.join(DEC, fn), encoding="utf-8"):
            m = RE_DEFAULT.match(line.strip())
            if not m: continue
            v = m.group(1)
            ch, _ = split_var(v)
            if v not in out[ch]: out[ch].append(v)
    for ch in out: out[ch].sort(key=sort_key)
    return out

# ---------- the Mail panel: names, hints, message labels ----------

RE_GUARD = re.compile(r'^(?:el)?if\s+((?:%s)SMS[0-9]+[a-z]?)(Open)?\s*'
                      r'(?:and\s+activeButtons\s*)?:$' % "|".join(CHARS))
RE_NAMEG = re.compile(r'^if\s+((?:%s)SMS[0-9]+[a-z]?(?:\s+or\s+(?:%s)SMS[0-9]+[a-z]?)*)\s*:$'
                      % ("|".join(CHARS), "|".join(CHARS)))
RE_CALL  = re.compile(r'action\s+Call\(\s*"(\w+)"')
RE_TIP   = re.compile(r'Tip="((?:[^"\\]|\\.)*)"')
RE_TEXT  = re.compile(r'^Text\s+"((?:[^"\\]|\\.)*)"')

def unescape(s):
    return s.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")

def panels():
    """var -> {hint, msg}, plus the variant groups in panel order."""
    info = defaultdict(dict)
    names = OrderedDict()          # tuple(vars) -> display name pieces
    for fn in sorted(os.listdir(DEC)):
        if not fn.startswith("sceneEndChoices") or not fn.endswith(".rpy"): continue
        lines = open(os.path.join(DEC, fn), encoding="utf-8").read().split("\n")
        cur = None
        for i, raw in enumerate(lines):
            s = raw.strip()

            # The name cell is `if A or B:` followed by a Text. It has to be
            # tried before the button guard, which looks the same for one var.
            n = RE_NAMEG.match(s)
            if n:
                nxt = next((l.strip() for l in lines[i + 1:i + 4] if l.strip()), "")
                t = RE_TEXT.match(nxt)
                if t:
                    key = tuple(n.group(1).split(" or "))
                    names.setdefault(key, []).append(unescape(t.group(1)))
                    continue

            g = RE_GUARD.match(s)
            if g:
                cur = g.group(1)
                continue

            if cur:
                c = RE_CALL.search(s)
                if c: info[cur].setdefault("msg", c.group(1))
                p = RE_TIP.search(s)
                if p: info[cur].setdefault("hint", unescape(p.group(1)).strip())
    return info, names

# ---------- grant sites, and the name each one announces ----------
# Every grant sits within a line or two of the PushToLog / addCor that names the
# mail, and those names distinguish variants the panel does not ("Mountains" vs
# "Mountains+"). Sites inside the cheat menu and the save/load shuffling at the
# top of Phone_Init are not real grants.

RE_GRANT = re.compile(r'^\$?\s*((?:%s)SMS[0-9]+[a-z]?)\s*=\s*True\s*$' % "|".join(CHARS))
RE_LOG   = re.compile(r'PushToLog\(\s*"(?:\{[^}]*\})?\s*New Mail:\s*((?:[^"\\]|\\.)*)"')
RE_ADD   = re.compile(r'addCor\(\s*"[^"]*\|n\|New Mail:\s*([^"]*)"')

def announced(lines, i):
    """The mail name announced beside the grant on line i, if any.

    Nearest line wins. Variants sit two or three lines apart in the same if/else
    (`AlexSMS8` and `AlexSMS8b`), so a widening search that took the first hit
    would hand a mail its sibling's name.
    """
    for d in range(0, 4):
        for j in (i + d, i - d):
            if 0 <= j < len(lines):
                m = RE_LOG.search(lines[j]) or RE_ADD.search(lines[j])
                if m: return unescape(m.group(1)).strip()
    return None

def grants():
    out = defaultdict(list)
    for fn in sorted(os.listdir(DEC)):
        if not fn.endswith(".rpy"): continue
        if fn == "sceneEndChoices.rpy": continue         # the cheat menu
        lines = open(os.path.join(DEC, fn), encoding="utf-8").read().split("\n")
        in_init = False
        for i, raw in enumerate(lines):
            s = raw.strip()
            if s.startswith("label "):
                in_init = s.startswith("label Phone_Init")
            if in_init: continue
            m = RE_GRANT.match(s)
            if not m: continue
            out[m.group(1)].append({"file": fn, "line": i + 1,
                                    "says": announced(lines, i)})
    return out

# ---------- assemble ----------

def build():
    cat, (info, names) = catalogue(), panels()
    group_of, group_name = {}, {}
    for key, pieces in names.items():
        nm = "".join(pieces).strip() or None
        for v in key:
            group_of[v] = list(key)
            group_name[v] = nm

    gr = grants()
    out = {}
    for ch, vars_ in cat.items():
        rows = []
        for v in vars_:
            sites = gr.get(v, [])
            said = next((s["says"] for s in sites if s["says"]), None)
            panel = group_name.get(v)
            # The announced name is the one that distinguishes variants sharing
            # a panel cell ("Mountains" / "Mountains+"), so it wins -- except
            # where it only differs from the panel by casing, which is the
            # author being inconsistent rather than naming a variant.
            name = said or panel or v
            if said and panel and said.lower() == panel.lower(): name = panel
            hint, variant = info.get(v, {}).get("hint") or None, None
            if hint and "\n" in hint:
                head, rest = hint.split("\n", 1)
                if head.strip().lower().endswith("variant"):
                    variant, hint = head.strip(), rest.strip()
            rows.append({
                "var": v, "char": ch, "name": name,
                "group": group_of.get(v, [v]), "groupName": panel,
                "variant": variant, "hint": hint,
                "msg": info.get(v, {}).get("msg"),
                "sites": [{"file": s["file"], "line": s["line"]} for s in sites],
            })
        out[ch] = rows
    return out

def main():
    data = build()
    json.dump(data, open("_analysis/mails.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    total = sum(len(v) for v in data.values())
    nosite = [r["var"] for v in data.values() for r in v if not r["sites"]]
    noname = [r["var"] for v in data.values() for r in v if not r["groupName"]]
    nohint = [r["var"] for v in data.values() for r in v if not r["hint"]]
    print("mails        : %d across %d characters" % (total, len(data)))
    for ch in sorted(data): print("  %-8s %d" % (ch, len(data[ch])))
    print("NO GRANT SITE: %d %s" % (len(nosite), nosite))
    print("NO PANEL NAME: %d %s" % (len(noname), noname))
    print("no hint      : %d" % len(nohint))

if __name__ == "__main__":
    main()
