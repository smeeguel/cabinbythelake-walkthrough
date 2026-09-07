# The phone's Memories and Dreams galleries.
#
# These are the two reward collections drawn beside Mail in the `rewards` screen
# of each `sceneEndChoices<Char>.rpy`, and they are NOT a third and fourth copy
# of the Mail system:
#
#   * No per-item boolean. Mail is 175 `default <Char>SMS<n> = False`
#     declarations; a Memory/Dream has none. Its identity is the `Jump("<label>")`
#     on its thumbnail.
#   * No grant site, no PushToLog, no end-of-run sweep, no cheat layer. An entry
#     is unlocked when a *condition* holds, evaluated live as the panel draws.
#   * Not reachable in a run. All 80 scenes exist as containers but have zero
#     routes from any of the 39 roots -- they are replay tiles, not scenes you
#     visit during a weekend.
#
# So a reward's "plan" is a prerequisite plan, not an itinerary to the scene, and
# what this extractor has to produce is the tile's unlock condition, split into
# the corruption rungs it wants (which cross-link to their own Corruption-tab
# plans) and the residue the planner can chain into a real weekend.
#
# The file is indentation-sensitive in exactly the way landmine 64 describes, so
# the walk below is a plain indent tree with no re-baselining of the decompiler.
import json, os, re
from collections import defaultdict

DEC = "_decompiled"
CHARS = ["Alex", "Carla", "Cassidy", "Haily", "Jenny", "Lin", "Lina", "Lisa", "Sami"]

RE_REWARDS = re.compile(r'^(?:el)?if endmenuchascreen == "rewards":$')
RE_HEAD    = re.compile(r'^Text " (Memories|Dreams) " size 18')
RE_JUMP    = re.compile(r'action\s+Jump\(\s*"(\w+)"')
RE_NAME    = re.compile(r'^Text\s+"((?:[^"\\]|\\.)*)"\s+size 14\b')
RE_TIP     = re.compile(r'Tip="((?:[^"\\]|\\.)*)"')
RE_IF      = re.compile(r'^(if|elif)\s+(.*?):$')
RE_ELSE    = re.compile(r'^else:$')

# `mails.py` ignores this file for the same reason: it is the legacy/cheat panel.
# It holds one stray Dream tile (`TheProgression`) that no character's panel draws.
SKIP = "sceneEndChoices.rpy"

def unescape(s):
    return s.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")

# ---------- the indent tree ----------

class N:
    __slots__ = ("line", "ind", "text", "kids")
    def __init__(self, line, ind, text):
        self.line, self.ind, self.text, self.kids = line, ind, text, []

def tree(lines, lo, hi):
    """The block lines[lo:hi] as a forest, by indentation.

    Landmine 64: the decompiler indents a narrator Say one column too deep, so a
    stack that pops on `>= ind` adopts the next sibling into the block above it.
    A screen block holds no Say lines, but the pop is written `> ind` anyway so a
    stray column cannot silently reparent a tile.
    """
    root, stack = N(lo, -1, ""), None
    stack = [root]
    for i in range(lo, hi):
        raw = lines[i]
        s = raw.strip()
        if not s: continue
        ind = len(raw) - len(raw.lstrip())
        while len(stack) > 1 and stack[-1].ind >= ind: stack.pop()
        n = N(i + 1, ind, s)
        stack[-1].kids.append(n)
        stack.append(n)
    return root

# ---------- walking a tile ----------

def walk(node, guards, out):
    """Depth-first, threading the positive guard stack.

    An `elif`/`else` carries the negation of the branches above it, and in this
    panel the negative branch is always the padlock and the `???` caption -- the
    thing we are deliberately not reading. The chain is still recorded, so a
    future version that puts a real tile in an `else` shows up as `not (...)`
    rather than being silently promoted to unconditional.
    """
    chain = []
    for k in node.kids:
        m = RE_IF.match(k.text)
        if m:
            if m.group(1) == "if": chain = []
            cond = m.group(2).strip()
            g = guards + ["not (%s)" % c for c in chain] + [cond]
            chain.append(cond)
            walk(k, g, out)
            continue
        if RE_ELSE.match(k.text):
            walk(k, guards + ["not (%s)" % c for c in chain], out)
            continue
        chain = []
        out.append((k, guards))
        walk(k, guards, out)

def tiles(root, guards):
    """Minimal subtrees holding both a Jump and a `Text "..." size 14` caption.

    Tile markup is not uniform -- most are `MultiBox at truecenter xsize 240
    ysize mailYSize`, but Cassidy's are not, so anchoring on that box loses four
    of the eighty. What every tile does have is a thumbnail that jumps and a
    caption under it, so that pair is the anchor.
    """
    flat = []
    walk(root, guards, flat)
    def has(n, rx, size14=False):
        if rx.search(n.text) if not size14 else RE_NAME.match(n.text): return True
        return any(has(k, rx, size14) for k in n.kids)
    found = [(n, g) for n, g in flat
             if has(n, RE_JUMP) and has(n, RE_NAME, True)]
    # Minimal ones only: every ancestor of a tile also holds a Jump and a
    # caption, so the enclosing `vpgrid` would otherwise come back as one tile
    # holding the whole section.
    return [(n, g) for n, g in found
            if not any(m is not n and _inside(m, n) for m, _ in found)]

def _inside(node, outer):
    for k in outer.kids:
        if k is node or _inside(node, k): return True
    return False

def read_tile(node, guards):
    """(scene, name, hint, cond) for one tile."""
    flat = []
    walk(node, guards, flat)
    # the caption in the unlocked branch, never the `???` else-branch
    name, cond = None, None
    for n, g in flat:
        m = RE_NAME.match(n.text)
        if not m: continue
        txt = unescape(m.group(1)).strip()
        if txt in ("", "???"): continue
        name, cond = txt, g
        break
    scenes, hint, jg = [], None, None
    for n, g in flat:
        j = RE_JUMP.search(n.text)
        if j:
            if j.group(1) not in scenes: scenes.append(j.group(1))
            if jg is None: jg = g
        t = RE_TIP.search(n.text)
        if t and hint is None: hint = unescape(t.group(1)).strip()
    return scenes, name, hint, (cond if cond is not None else jg) or []

# ---------- the condition splitter ----------
#
# `not alexCorruption5` is a POSITIVE requirement: the game's corruption unlock
# vars are inverted, so `False` means unlocked and `not X` means "X is unlocked".
# The obvious move is to teach `atom_facts` an `("unlocked", var)` fact, and it
# is the wrong one -- `not <char>CorruptionN` appears in scene guards all over
# the game, so minting a fact for it would rewrite all 732 existing plans and
# move every tripwire in `build_all`'s summary. Split the condition here instead:
# the rungs become cross-links the planner never sees, and only the residue is
# handed to it, in shapes it already understands.

RE_TOKEN = re.compile(r'^not\s+([A-Za-z_]\w*)$')
# Landmine 70: match the token, THEN check the suffix. `\b(\w+?Corruption\w*?)\b(?!On)`
# does not exclude `hailyCorruption4On` -- the lookahead sits past the whole
# token, so the regex eats the very variable the requirement is about.
RE_COR   = re.compile(r'^([a-z]+)Corruption(\w*)$')

def _rung(var):
    m = RE_COR.match(var)
    if not m or var.endswith("On"): return None
    return m.group(1)

# `...Moonstone` is inverted the other way again: `True` = unlocked, default
# False, so its unlock shape is the bare variable rather than `not <var>`.
# Nothing in 0.62d's panels uses it; the split has to be right for the version
# that does.
def _unlocked(atom):
    """The rung this atom asserts is unlocked, or None."""
    a = atom.strip()
    m = RE_TOKEN.match(a)
    if m:
        v = m.group(1)
        return None if v.endswith("Moonstone") else (v if _rung(v) else None)
    if re.match(r'^[A-Za-z_]\w*$', a) and a.endswith("Moonstone") and _rung(a):
        return a
    return None

def _split_top(s, op):
    """Split on a top-level ` and ` / ` or `, respecting parens and brackets."""
    out, depth, last, i, tok = [], 0, 0, 0, " %s " % op
    while i < len(s):
        c = s[i]
        if c in "([": depth += 1
        elif c in ")]": depth -= 1
        elif depth == 0 and s.startswith(tok, i):
            out.append(s[last:i]); i += len(tok); last = i; continue
        i += 1
    out.append(s[last:])
    return [x.strip() for x in out if x.strip()]

def unwrap(s):
    """Strip a wrapping paren pair, but only when the leading `(` is the one the
    trailing `)` closes -- `(A) or (B)` must not come back as `A) or (B`."""
    s = s.strip()
    while s.startswith("(") and s.endswith(")"):
        depth = 0
        for i, c in enumerate(s):
            if c == "(": depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    if i != len(s) - 1: return s
                    break
        s = s[1:-1].strip()
    return s

def split_cond(conjuncts, names):
    """(requires, residue) for a tile's guard stack.

    `requires` is one entry per corruption prerequisite, each holding the
    alternatives that satisfy it -- `not jennyCorruption4D or not jennyCorruption4M`
    is one requirement with two ways to meet it, not two requirements. `residue`
    is everything else, re-joined for the planner.
    """
    requires, residue, seen = [], [], set()
    for c in conjuncts:
        for part in _split_top(unwrap(c), "and"):
            part = unwrap(part)
            if part in ("True", ""): continue
            alts = _split_top(part, "or")
            rungs = [_unlocked(a) for a in alts]
            if all(rungs):
                key = tuple(sorted(rungs))
                if key in seen: continue
                seen.add(key)
                requires.append({"alts": [_entry(v, names) for v in rungs]})
            else:
                if part not in residue: residue.append(part)
    return requires, " and ".join(residue)

def _entry(var, names):
    ch = _rung(var)
    return {"var": var, "char": ch.capitalize(),
            "name": names.get(var, var), "targetId": "cor:" + var}

def rung_names():
    L = json.load(open("_analysis/ladders.json", encoding="utf-8"))
    return {e["var"]: e["name"] for c in L for e in L[c]}

# ---------- assemble ----------

def build():
    names = rung_names()
    out, anomalies = [], []
    for ch in CHARS:
        fn = "sceneEndChoices%s.rpy" % ch
        path = os.path.join(DEC, fn)
        if fn == SKIP or not os.path.exists(path):
            anomalies.append("%s: missing" % fn); continue
        lines = open(path, encoding="utf-8").read().split("\n")
        blk = None
        for i, raw in enumerate(lines):
            if RE_REWARDS.match(raw.strip()):
                ind = len(raw) - len(raw.lstrip())
                end = len(lines)
                for j in range(i + 1, len(lines)):
                    if not lines[j].strip(): continue
                    if len(lines[j]) - len(lines[j].lstrip()) <= ind: end = j; break
                blk = (i + 1, end)
                break
        if blk is None:
            anomalies.append("%s: no rewards block" % fn); continue

        # Section is position: everything between the two heading literals is a
        # Memory, everything after the second is a Dream. That also excludes the
        # inline Mail panel Cassidy, Lin and Lisa fold into the same screen,
        # which sits above the Memories heading.
        lo, hi = blk
        heads = [(k, RE_HEAD.match(lines[k].strip()).group(1))
                 for k in range(lo, hi) if RE_HEAD.match(lines[k].strip())]
        if [h for _, h in heads] != ["Memories", "Dreams"]:
            anomalies.append("%s: headings %s" % (fn, [h for _, h in heads]))
            continue
        bounds = {"memory": (heads[0][0] + 1, heads[1][0]),
                  "dream":  (heads[1][0] + 1, hi)}

        for section in ("memory", "dream"):
            a, b = bounds[section]
            seen = {}
            for node, guards in tiles(tree(lines, a, b), []):
                scenes, name, hint, cond = read_tile(node, guards)
                if not scenes:
                    anomalies.append("%s:%d no jump" % (fn, node.line)); continue
                if len(scenes) > 1:
                    anomalies.append("%s:%d jumps to %s" % (fn, node.line, scenes))
                scene = scenes[0]
                # `CarlaSamiMovieNight` is jumped to twice inside one tile -- an
                # `if optionPreg`/`else` pair differing only in artwork. Identity
                # is (char, section, jump target), so the second is the same
                # tile, not a seventh Memory.
                if scene in seen: continue
                requires, residue = split_cond(cond, names)
                rec = {"id": "%s:%s:%s" % ("mem" if section == "memory" else "dream",
                                           ch, scene),
                       "char": ch, "section": section, "scene": scene,
                       "name": name or scene, "hint": hint,
                       "cond": " and ".join(cond), "requires": requires,
                       "residue": residue, "file": fn, "line": node.line}
                seen[scene] = rec
                out.append(rec)
                if not name: anomalies.append("%s:%d no caption" % (fn, node.line))
    return out, anomalies

def main():
    rows, anomalies = build()
    json.dump(rows, open("_analysis/rewards.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    by = defaultdict(lambda: [0, 0])
    for r in rows: by[r["char"]][0 if r["section"] == "memory" else 1] += 1
    mem = sum(1 for r in rows if r["section"] == "memory")
    dre = len(rows) - mem
    free = sum(1 for r in rows if not r["requires"] and not r["residue"])
    linked = {a["var"] for r in rows for q in r["requires"] for a in q["alts"]}
    print("rewards      : %d memories, %d dreams, %d characters" % (mem, dre, len(by)))
    for c in CHARS:
        print("  %-8s %d / %d" % (c, by[c][0], by[c][1]))
    print("available now: %d" % free)
    print("cross-linked rungs: %d" % len(linked))
    print("with a residue: %d" % sum(1 for r in rows if r["residue"]))
    print("no hint      : %d" % sum(1 for r in rows if not r["hint"]))
    if anomalies:
        print("ANOMALIES    : %d" % len(anomalies))
        for a in anomalies[:20]: print("   ", a)

if __name__ == "__main__":
    main()
