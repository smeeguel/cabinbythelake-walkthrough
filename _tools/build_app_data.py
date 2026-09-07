# Turn the raw graph into per-target, per-timeslot route bundles for the web app.
import json, re, os
from collections import defaultdict, Counter

G = json.load(open("_analysis/graph.json", encoding="utf-8"))
L = json.load(open("_analysis/ladders.json", encoding="utf-8"))
M = json.load(open("_analysis/mails.json", encoding="utf-8"))
# The Memories/Dreams galleries. Extracted by `rewards.py`, which must therefore
# run before anything imports this module.
R = json.load(open("_analysis/rewards.json", encoding="utf-8"))

ROOTS, EV, EDGES = G["roots"], G["events"], G["edges"]
RBR, NAMES = G["routesByRoot"], G["sceneNames"]
BOOK, CURSCENE = G["mapBook"], G["currentScene"]
# Only top-level `label X:`/`screen X:` are containers. A `label FooLoop:` nested
# inside a scene is not one, which is exactly what makes it recognisable as the
# scene's own menu loop rather than a jump to somewhere else.
CONTAINERS = set(G["containers"])

TIMES = ["earlymorning", "morning", "noon", "afternoon", "evening", "night", "midnight"]
TIMELABEL = {"earlymorning": "Early Morning", "morning": "Morning", "noon": "Noon",
             "afternoon": "Afternoon", "evening": "Evening", "night": "Night",
             "midnight": "Midnight", "explore": "Explore", "endofloop": "End of Loop"}
DAYS = ["", "Friday", "Saturday", "Sunday", "Monday", ""]
CHARS = ["alex", "carla", "cassidy", "haily", "jenny", "lin", "lina", "lisa", "sami"]
DISPLAY = {c: c.capitalize() for c in CHARS}

# Menu labels carry Ren'Py text tags ({image=...}) the engine draws as icons, and
# MapBook titles are wrapped to fit their grid cell ("Unloading\nCar").
RE_TAG = re.compile(r'\{/?[^}]*\}')
def clean(s):
    return re.sub(r'\s+', ' ', RE_TAG.sub("", s or "").replace("\\n", " ")).strip()

# Location pickers are named d<day><time><place>picker; show the place instead.
PLACES = {"garden": "the Garden", "lake": "the Lake", "forest": "the Forest",
          "livingroom": "the Living Room", "living": "the Living Room",
          "bathroom": "the Bathroom", "kitchenroom": "the Kitchen",
          "kitchen": "the Kitchen", "cbedroom": "Cassidy's Bedroom",
          "cbedroomroom": "Cassidy's Bedroom", "masterbedroom": "the Master Bedroom",
          "twinbedroom": "the Twin Bedroom", "yourroom": "your Room",
          "bedroom": "the Bedroom", "window": "the Window", "map": "the Map"}
RE_PICKER = re.compile(r'^d\d(?:%s)(\w+?)picker$' % "|".join(TIMES))

# The ten map hotspots, as `graph.py` reads them off the glow art. These are the
# names the player sees on the cabin map, so a step can say where to click.
PLACENAME = {"garden": "Garden", "lake": "Lake", "forest": "Forest",
             "livingroom": "Living Room", "kitchen": "Kitchen",
             "bathroom": "Bathroom", "yourroom": "Your Room",
             "cbedroom": "Cassidy's Bedroom", "twinroom": "Twin Bedroom",
             "masterbedroom": "Master Bedroom"}
def place_name(tok):
    return PLACENAME.get(tok, (tok or "").replace("room", " Room").title() or None)

# Labels the game never names, but which a plan has to be able to point at.
ALIAS = {"endCyclePhone": "Checking your phone"}

# `currentScene` persists until something reassigns it, so a label that never
# sets one is still, as far as the phone is concerned, inside whatever scene
# jumped into it: `HailyPicnicSuccess` is part of "Haily's Picnic". Inherited
# only when every way in agrees, so a shared sub-label is left unnamed rather
# than given one caller's name.
INC_SRC = defaultdict(set)
for _e in EDGES:
    if _e.get("firstRun") or _e["src"] == _e["dst"]: continue
    INC_SRC[_e["dst"]].add(_e["src"])

_CTX = dict(CURSCENE)
def context(label, seen=()):
    if label in _CTX: return _CTX[label]
    if label in seen: return None
    up = {context(s, seen + (label,)) for s in sorted(INC_SRC.get(label, ()))}
    up.discard(None)
    got = up.pop() if len(up) == 1 else None
    if not seen: _CTX[label] = got       # only memoise a full resolution
    return got

def sname(label):
    """The name the player knows a scene by.

    `sceneNameConv` is the author's own table and wins. Beyond it, the phone's
    MapBook page for the scene is titled with the same name, which covers a few
    hundred labels the table never lists -- and a sub-label that names no page of
    its own says which one it belongs to by setting `currentScene`, which is how
    `HailyPackageWatch` becomes "Mysterious Package: Saturday", or inherits one
    from the scene that jumped into it. Only then does the internal label get
    shown."""
    if label in ALIAS: return ALIAS[label]
    for k in (label, context(label)):
        if not k: continue
        if k in NAMES: return clean(NAMES[k])
        if "map" + k in BOOK: return clean(BOOK["map" + k])
    m = RE_PICKER.match(label)
    if m:
        return PLACES.get(m.group(1), m.group(1).replace("room", " room").title())
    return label

# ---------- branch id -> the scene that owns it ----------
# Every scene declares its decision ids in a `label <Scene>_Init:` block, right
# beside its own sceneNameConv entry. That is an exact mapping -- guessing the
# stem by trimming digits is wrong, because scene ids end in digits themselves
# (AlexForest10231 belongs to AlexForest1, not AlexForest).
RE_INIT = re.compile(r'^label (\w+)_Init:$')
RE_FLOW = re.compile(r'flowVar\s*\(\s*"([\w-]+)"')
TEMPSCENE = {}
for fn in sorted(os.listdir("_decompiled")):
    if not fn.endswith(".rpy"): continue
    cur = None
    for line in open("_decompiled/" + fn, encoding="utf-8"):
        s = line.strip()
        m = RE_INIT.match(s)
        if m: cur = m.group(1); continue
        if s.startswith("label "): cur = None; continue
        if cur:
            f = RE_FLOW.search(s)
            if f: TEMPSCENE.setdefault(f.group(1), cur)

# The in-game MapBook renders each decision node as its player-facing text.
RE_NODE = re.compile(r'Text\s+"(.*?)"\s+(?:text_)?style\s+choiceStyleHandler\('
                     r'tempFlags\[\s*"([\w-]+)"\s*\]\)')
TEMPNAME = {}
for fn in sorted(os.listdir("_decompiled")):
    if not fn.startswith("screenMapBook"): continue
    for m in RE_NODE.finditer(open("_decompiled/" + fn, encoding="utf-8").read()):
        TEMPNAME.setdefault(m.group(2), clean(m.group(1)))

# Fallback: the menu choice the assignment sits under.
RE_SET = re.compile(r'(?:tempFlags\[\s*"([\w-]+)"\s*\]\s*=|flowVar\s*\(\s*"([\w-]+)"\s*,)')
RE_CHOICE = re.compile(r'^"(.*?)"(?:\s+if\s+.*?)?:$')
for fn in sorted(os.listdir("_decompiled")):
    if fn.startswith("screen") or not fn.endswith(".rpy"): continue
    lines = open("_decompiled/" + fn, encoding="utf-8").read().split("\n")
    for i, line in enumerate(lines):
        m = RE_SET.search(line)
        if not m: continue
        tid = m.group(1) or m.group(2)
        if tid in TEMPNAME: continue
        cur = len(line) - len(line.lstrip(" "))
        for j in range(i - 1, max(-1, i - 400), -1):
            s = lines[j]
            if not s.strip(): continue
            ind = len(s) - len(s.lstrip(" "))
            if ind >= cur: continue
            cur = ind
            c = RE_CHOICE.match(s.strip())
            if c: TEMPNAME[tid] = clean(c.group(1)); break
            if s.strip().startswith("label "): break

def slot_label(r):
    return r["label"] if r["day"] in (0, 5) else "%s %s" % (DAYS[r["day"]], TIMELABEL[r["time"]])

def scene_slots(label):
    """Every timeslot this scene can be reached at, in chronological order."""
    out = {}
    for root, reach in RBR.items():
        if label in reach:
            r = ROOTS[root]
            dv = r.get("dateVar", 0)
            if dv not in out or len(reach[label]) < out[dv][1]:
                out[dv] = (slot_label(r), len(reach[label]))
    return [out[k][0] for k in sorted(out)]

def temp_desc(tid):
    """Describe a decision id the way the game presents it."""
    scene = TEMPSCENE.get(tid)
    nm = sname(scene) if scene else None
    label = TEMPNAME.get(tid)
    d = {"id": tid, "scene": nm, "choice": label,
         "slots": scene_slots(scene) if scene else []}
    if scene and tid == scene + "Scene":
        d["kind"] = "scene"; d["text"] = "Play “%s”" % (nm or scene)
    elif label:
        d["kind"] = "choice"; d["text"] = label
    else:
        d["kind"] = "unknown"; d["text"] = tid
    return d

# ---------- condition prettifying ----------

RE_COR   = re.compile(r'\b(\w+?Corruption\w*?)On\b')
RE_WORLD = re.compile(r'worldCorruption\s*(>=|>|==|<=|<)\s*(\d+)')
RE_STAT  = re.compile(r'\b(\w+?(?:Love|Horny|Jealousy|Concern|Nerve|Favor|Sus|Teach|Talk|BE))\s*(>=|>|==|<=|<)\s*(\d+)')
RE_TEMP  = re.compile(r'tempFlags\[\s*"([\w-]+)"\s*\]\s*(>=|==|>|<)?\s*(\d+)?')
RE_OPT   = re.compile(r'\b(optionPreg|optionPegging|optionHappy)\b')
RE_BURNT = re.compile(r'\b(\w+)Burnt\b')
RE_QUEST = re.compile(r'"(?:Quest:\s*)?([^"]+)"\s*\)?\s+in\s+commonEvents')

def ladder_name(var):
    for c in CHARS:
        for e in L.get(c, []):
            if e["var"] == var: return DISPLAY[c], e["name"]
    return None, var

OPTNAME = {"optionPreg": "Pregnancy content on", "optionPegging": "Pegging content on",
           "optionHappy": "Happy endings on"}

# ---------- what a toggle drags along ----------
# Switching a rung on at the end-of-loop menu switches on every rung below it:
# the button's action list is
#   SetVariable("cassidyCorruption5On",True), SetVariable("cassidyCorruption4On",True), …
# so `not cassidyCorruption4On` can never hold in a run with Together on. Some
# rungs also switch a sibling *off* (Jenny's Prey clears Pred).
#
# The subject of a button is found by matching its label to the rung name
# `ladders.py` already extracted — the order inside the action list varies per
# character and cannot be relied on. Where a rung has more than one ON button
# (Jenny's Princess reaches 4M or 4D depending on the path) only what they agree
# on is guaranteed, so the sets are intersected, never unioned.
RE_BUTTON = re.compile(r'_textbutton\s+"(.*?)"\s+action\s+\[(.*?)\]')
RE_SETVAR = re.compile(r'SetVariable\("(\w+?Corruption\w*?)On",\s*(True|False)\)')

def _cascades():
    on, off = {}, {}
    for fn in sorted(os.listdir("_decompiled")):
        if not fn.startswith("sceneEndChoices") or not fn.endswith(".rpy"): continue
        for line in open("_decompiled/" + fn, encoding="utf-8"):
            m = RE_BUTTON.search(line)
            if not m: continue
            sets = RE_SETVAR.findall(m.group(2))
            trues = {v for v, b in sets if b == "True"}
            falses = {v for v, b in sets if b == "False"}
            label = clean(m.group(1))
            for var in trues:
                if ladder_name(var)[1] != label: continue    # not this rung's switch
                on[var] = trues if var not in on else (on[var] & trues)
                off[var] = falses if var not in off else (off[var] & falses)
    return on, off

CASCADE_ON, CASCADE_OFF = _cascades()

# A couple of rungs cannot be switched on at all until the rest of the roster is
# somewhere: Cassidy's Together is padlocked unless every other girl is at her
# top rung, and her Open needs at least one of them there. The menu draws the
# padlock under a guard shaped `not <rung> and not ( … )`, and that inner
# expression is the requirement.
RE_ENDIF = re.compile(r'^(?:el)?if\s+(.*?):$')

def _inner_not(cond):
    m = re.search(r'\bnot\s*\(', cond)
    if not m: return None
    d, j = 1, m.end()
    while j < len(cond) and d:
        if cond[j] == "(": d += 1
        elif cond[j] == ")": d -= 1
        j += 1
    return cond[m.end():j - 1] if not d else None

def _rung_gates():
    out = {}
    for fn in sorted(os.listdir("_decompiled")):
        if not fn.startswith("sceneEndChoices") or not fn.endswith(".rpy"): continue
        lines = open("_decompiled/" + fn, encoding="utf-8").read().split("\n")
        for i, line in enumerate(lines):
            g = RE_ENDIF.match(line.strip())
            if not g: continue
            if not any("smalllock" in x for x in lines[i + 1:i + 4]): continue
            req = _inner_not(g.group(1))
            m = re.search(r'\b(\w+?Corruption\w*?)(?:On)?\b', g.group(1))
            if req and m: out.setdefault(m.group(1), req)
    return out

RUNG_GATE = _rung_gates()

# ...and that padlock is only the shape the *lock icon* takes. The menu also
# force-disables a rung by simply not drawing a button for it: Haily's Package
# renders as a bare `Text` -- unclickable -- under
# `not Spy1 and not Spy2 and not hailyCorruption2On`, and her Fertile has a
# `_textbutton` that sets the rung *False* in its `else`. Either way the rung
# cannot be switched on, and a plan that asks for it is unplayable.
#
# The honest question is not "is there a lock icon" but "what conditions reach a
# button that sets this rung True", so walk the if/elif chain to each one. What
# is left after assuming every *unlock* flag is unlocked is the run's own
# business: which other rungs have to be on first.
RE_ONBTN = re.compile(r'_textbutton\s+"(.*?)"\s+action\s+\[(.*?)\]')
RE_FREE = re.compile(r'^(?:\w+Corruption\w*On|option\w+)$')
RE_WORD = re.compile(r'\b[A-Za-z_]\w*\b')
RE_STR = re.compile(r'"[^"]*"')
_KEYWORD = {"and", "or", "not", "True", "False", "in", "is", "None"}

def _negate(c):
    c = c.strip()
    return "not %s" % c if re.match(r'^[\w."\[\]]+$', c) else "not (%s)" % c

def _btn_paths(node, guards, out):
    """Every `_textbutton` that switches a rung ON, with the chain reaching it."""
    chain = []
    for k in node.kids:
        t = k.text.strip()
        m = RE_ENDIF.match(t)
        if m:
            if not t.startswith("elif"): chain = []
            _btn_paths(k, guards + [_negate(c) for c in chain] + [m.group(1)], out)
            chain.append(m.group(1))
            continue
        if t == "else:":
            _btn_paths(k, guards + [_negate(c) for c in chain], out)
            chain = []
            continue
        chain = []
        b = RE_ONBTN.search(t)
        if b:
            label = clean(b.group(1))
            for var, val in RE_SETVAR.findall(b.group(2)):
                # the button's subject is the rung whose name it carries; the
                # rest of the action list is the cascade (landmine 21)
                if val == "True" and ladder_name(var)[1] == label:
                    out.setdefault(var, []).append(list(guards))
        _btn_paths(k, guards, out)

def _required(paths, subject):
    """Which rungs every way of switching `subject` on needs already ON.

    Substitute what the run cannot change -- an unlock flag is assumed unlocked
    (`False` for the usual ones, `True` for the inverted Moonstone), and the rung
    itself is currently off -- then enumerate what is left. A variable required
    by only some of the buttons is not required at all, which is why this asks
    the whole disjunction rather than each path."""
    def sub(c):
        # blank the string literals first, or the word pass rewrites their
        # contents and `endmenuchascreen == "bio"` quietly becomes True
        c = RE_STR.sub('"@"', c)
        def w(m):
            v = m.group(0)
            if v in _KEYWORD: return v
            if v == subject + "On": return "False"          # not on yet
            if RE_FREE.match(v): return v                   # a rung the run picks
            # an unlock flag: assume the player has it. `True` means *locked*
            # everywhere except Moonstone, which is inverted (see CLAUDE.md).
            if "Corruption" in v: return "True" if v.endswith("Moonstone") else "False"
            return "False"                                  # UI state, screen mode
        return RE_WORD.sub(w, c)
    expr = " or ".join("(%s)" % " and ".join(sub(c) for c in p) for p in paths if p)
    if not expr: return None
    free = sorted({v for v in RE_WORD.findall(expr)
                   if v not in _KEYWORD and RE_FREE.match(v)})
    if not free or len(free) > 10: return None
    need, sat = set(free), False
    for i in range(1 << len(free)):
        env = {v: bool(i >> j & 1) for j, v in enumerate(free)}
        try:
            if not eval(expr, {"__builtins__": {}}, env): continue
        except Exception:
            return None
        sat = True
        need &= {v for v in free if env[v]}
        if not need: break
    return " and ".join(sorted(need)) if sat and need else None

def _rung_reqs():
    out = {}
    for fn in sorted(os.listdir("_decompiled")):
        if not fn.startswith("sceneEndChoices") or not fn.endswith(".rpy"): continue
        import graph as _G                      # only for its indentation parser
        found = {}
        _btn_paths(_G.parse(os.path.join("_decompiled", fn), fn), [], found)
        for var, paths in found.items():
            req = _required(paths, var)
            if req: out[var] = req
    return out

RUNG_REQ = _rung_reqs()
for _v, _r in RUNG_REQ.items():
    RUNG_GATE[_v] = "(%s) and (%s)" % (RUNG_GATE[_v], _r) if _v in RUNG_GATE else _r

def toggles_on(vars_):
    """Every `<char>Corruption<rung>` that ends up ON for a run whose setup
    switches on `vars_`."""
    out = set()
    for v in vars_: out |= CASCADE_ON.get(v, {v})
    return out

def toggles_off(vars_):
    """Rungs those same switches turn OFF -- Jenny's Prey and Predator clear
    each other, so a setup cannot ask for both."""
    out = set()
    for v in vars_: out |= CASCADE_OFF.get(v, set())
    return out

def pretty(cond):
    """Rewrite a raw Ren'Py condition into something a player can act on."""
    if not cond: return ""
    s = cond
    s = RE_QUEST.sub(lambda m: 'quest “%s” done' % m.group(1), s)
    def cor(m):
        ch, nm = ladder_name(m.group(1))
        return "%s·%s ON" % (ch, nm) if ch else m.group(0)
    s = RE_COR.sub(cor, s)
    s = RE_WORLD.sub(lambda m: "World Corruption %s %s" % (m.group(1).replace(">=", "≥"), m.group(2)), s)
    def stat(m):
        n = statname(m.group(1))
        return "%s %s %s" % (n, m.group(2).replace(">=", "≥").replace("<=", "≤"), m.group(3))
    s = RE_STAT.sub(stat, s)
    def tmp(m):
        d = temp_desc(m.group(1))
        if d["kind"] == "scene": return d["text"]
        if d["kind"] == "choice":
            return "“%s”%s" % (d["choice"], " taken" if m.group(2) in (None, "==", ">=") else "")
        return m.group(1)
    s = RE_TEMP.sub(tmp, s)
    s = RE_OPT.sub(lambda m: OPTNAME[m.group(1)], s)
    s = RE_BURNT.sub(lambda m: "%s burnt out" % m.group(1).capitalize(), s)
    s = re.sub(r'\bnot\s+', "NOT ", s)
    return s.strip()

def statname(v):
    if v == "mood": return "Mood"
    m = re.match(r'^([a-z]+)(Love|Horny|Jealousy|Concern|Nerve|Favor|Sus|Teach|BE)', v)
    if not m: return v
    return "%s's %s" % (m.group(1).capitalize(), m.group(2))

# ---------- boolean structure ----------
# A condition like `A or B or C` means any one of them will do; listing all
# three as mandatory steps is simply wrong. Split on top-level operators so
# conjunctions become hard requirements and disjunctions become alternatives.

def split_top(s, op):
    parts, depth, q, cur, i = [], 0, False, [], 0
    pat = " " + op + " "
    while i < len(s):
        ch = s[i]
        if ch == '"': q = not q
        elif not q and ch in "([": depth += 1
        elif not q and ch in ")]": depth -= 1
        if depth == 0 and not q and s[i:i + len(pat)] == pat:
            parts.append("".join(cur)); cur = []; i += len(pat); continue
        cur.append(ch); i += 1
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]

def unwrap(s):
    s = s.strip()
    while s.startswith("(") and s.endswith(")") and len(split_top(s[1:-1], "or")) >= 1:
        inner = s[1:-1]
        # only strip if the parens actually wrap the whole expression
        d = 0; ok = True
        for i, ch in enumerate(inner):
            if ch in "([": d += 1
            elif ch in ")]": d -= 1
            if d < 0: ok = False; break
        if not ok or d != 0: break
        s = inner.strip()
    return s

def flatten(conds):
    """-> (list of conjunctive atoms, list of alternative-groups)"""
    hard, groups = [], []
    queue = [c for c in conds if c]
    while queue:
        c = unwrap(queue.pop())
        ors = split_top(c, "or")
        if len(ors) > 1:
            groups.append([unwrap(o) for o in ors])
            continue
        ands = split_top(c, "and")
        if len(ands) > 1:
            queue.extend(ands)
        else:
            hard.append(c)
    return hard, groups

def push_not(cond):
    """`not (A and B)` as something `flatten` can read: `not A or not B`.

    The halving in Jenny's garden is `not Prey and not Predator`, and the way to
    escape it is to switch one of those on -- an ordinary OR-group of two rungs
    once the negation is pushed down. Left as a negated compound it resolves to
    no facts at all and the run quietly keeps the halving.

    The output drops parentheses, so it is only safe to hand to `flatten`, which
    splits `or` before `and` and therefore reads it back with the right
    precedence. Do not print it or match it with a term-level regex."""
    s = unwrap(cond.strip())
    ands = split_top(s, "and")
    if len(ands) > 1: return " or ".join(push_not(x) for x in ands)
    ors = split_top(s, "or")
    if len(ors) > 1: return " and ".join(push_not(x) for x in ors)
    return unwrap(s[4:].strip()) if s.startswith("not ") else "not " + s

# ---------- which rungs a condition really speaks about ----------
# Every rung test in this pipeline was originally written against a *bare* atom
# -- `A_COR.match` on the whole stripped string -- and the guards are full of
# compounds, so all of them were blind to the common case. The worst was
# `cor_vars` reading `not (alexCorruptionPregOn and hailyCorruptionPregOn)` as
# *demanding both rungs ON*, the exact opposite of what it says.
#
# `not (A and B)` is a disjunction: one failing conjunct is enough, so a rung
# named inside it is a *way out*, not a requirement. That is the whole reason
# these return a list of alternatives rather than one set -- a caller that wants
# a requirement intersects them, and a caller choosing an escape ranks them.

RE_RUNG = re.compile(r'^(\w+?Corruption\w*?)On$')
_MAXD, _MAXALT = 4, 32
_ZERO = (frozenset(), frozenset(), 0)

def _lit(a):
    """One literal -> (need_on, need_off, n_other)."""
    a = unwrap(a)
    neg = a.startswith("not ")
    body = unwrap(a[4:].strip()) if neg else a
    m = RE_RUNG.match(body)
    if not m:
        # not a rung: still counted, because an escape that needs a quest item
        # or a Love threshold is not free the way a menu toggle is
        return (frozenset(), frozenset(), 0 if body in ("True", "(otherwise)") else 1)
    v = frozenset([m.group(1)])
    return (frozenset(), v, 0) if neg else (v, frozenset(), 0)

def _merge(alts):
    on, off, oth = set(), set(), 0
    for a in alts: on |= a[0]; off |= a[1]; oth += a[2]
    return (frozenset(on), frozenset(off), oth)

def cor_clauses(cond, depth=0):
    """One condition -> the alternative ways it can be satisfied.

    Each entry is `(need_on, need_off, n_other)`. A bare `not <rung>` gives one
    alternative with that rung in `need_off`; `not (A or B)` gives one holding
    both, because both really are required; `not (A and B)` gives **two**,
    because falsifying either is enough and which one is a choice."""
    hard, groups = flatten([cond])
    base, branches = [], []
    for a in hard:
        a = unwrap(a)
        if a.startswith("not ") and depth < _MAXD:
            body = unwrap(a[4:].strip())
            if len(split_top(body, "and")) > 1 or len(split_top(body, "or")) > 1:
                branches.append(cor_clauses(push_not(body), depth + 1)); continue
        base.append(_lit(a))
    for g in groups:
        if depth >= _MAXD:
            branches.append([(frozenset(), frozenset(), 1)]); continue
        alts = []
        for o in g: alts.extend(cor_clauses(o, depth + 1))
        branches.append(alts or [_ZERO])
    out = [_merge(base)]
    for br in branches:
        out = [_merge([x, y]) for x in out for y in br][:_MAXALT]
    return out

def cor_clash(conds, known):
    """How many of these conditions the rungs in `known` definitely contradict.

    Landmines 1 and 22, and the reason `cor_vars` alone cannot answer this. The
    Sunday-afternoon Living Room button opens the same picker three ways, and the
    third `elif` therefore carries `not (alexCorruption5On and hailyCorruption5On
    and cassidyCorruption5On)`. A run holding all three cannot be on that branch --
    it is on the first one, which reaches the identical scene -- so the branch has
    to lose, and only a per-alternative test says so: as a *requirement* the
    compound demands nothing (any one of the three failing would do), which is
    exactly what `cor_vars` correctly reports and exactly why it reads as free.

    `known` is a lower bound -- what the rest of the route needs ON, not the
    finished setup -- so a rung missing from it is unknown, not off. That is safe
    to judge only where every alternative is *purely* about rungs: then "the run
    does not switch this on" and "the run switches this off" are the same
    sentence and the branch is definitely not the one the game takes. An
    alternative carrying anything else (a quest item, a Love threshold) is
    unknown and makes the whole condition unknown."""
    on, n = toggles_on(known), 0
    for c in conds:
        if not c: continue
        for a in flatten([c])[0]:
            alts = cor_clauses(unwrap(a.strip()))
            if not alts: continue
            if all(x[1] & on for x in alts): n += 1
            elif all(x[2] == 0 and clause_state(x, on) == 2 for x in alts): n += 1
    return n

def clause_state(alt, on):
    """How does a run whose toggles are `on` stand against one alternative?

    0 = it already satisfies it for free, 1 = it does but with non-rung
    conditions to steer around, 2 = it contradicts it. The setup card fixes
    every toggle and anything it does not list is off, so a rung missing from
    `on` is definitively off -- which is what lets 2 be a definite answer."""
    need_on, need_off, oth = alt
    if (need_off & on) or (need_on - on): return 2
    return 1 if oth else 0

# ---------- requirement parsing ----------

def parse_reqs(all_conds):
    conds, groups = flatten(all_conds)
    cor, world, stats, temps, opts, other, quests = {}, [], {}, {}, set(), [], {}
    for raw in conds:
        if not raw: continue
        c = raw.strip()
        # a leading `not` inverts the whole atom: `not tempFlags[x] >= 3` is a
        # requirement to NOT have taken that branch
        neg_all = c.startswith("not ")
        # A compound says less than its terms do: `not (A and B)` needs only one
        # of them off, so marking every rung in it "must be off" invents a
        # requirement. Take what all the alternatives agree on and nothing more.
        for v in cor_vars([c]):
            ch, nm = ladder_name(v)
            if ch: cor.setdefault((ch, nm, v), True)
        for v in cor_vars([c], want=False):
            ch, nm = ladder_name(v)
            if ch: cor.setdefault((ch, nm, v), False)
        if not neg_all:
            for m in RE_WORLD.finditer(c): world.append(int(m.group(2)))
            for m in RE_STAT.finditer(c):
                stats.setdefault(m.group(1), []).append((m.group(2), int(m.group(3))))
            for m in RE_OPT.finditer(c): opts.add(m.group(1))
        for m in RE_TEMP.finditer(c):
            temps.setdefault(m.group(1), (not neg_all, (m.group(2) or "") + (m.group(3) or "")))
        for m in RE_QUEST.finditer(c):
            quests.setdefault(m.group(1), not neg_all)
        for m in RE_BURNT.finditer(c):
            other.append("Don't burn %s out" % m.group(1).capitalize())

    tf = []
    for k in sorted(temps):
        want, cmp_ = temps[k]
        d = temp_desc(k); d["want"] = want; d["cmp"] = cmp_
        tf.append(d)
    return {
        "corruption": [{"char": k[0], "level": k[1], "var": k[2], "on": v} for k, v in cor.items()],
        "world": max(world, default=0),
        "stats": [{"name": statname(k), "cmp": v[0][0], "value": max(x[1] for x in v)}
                  for k, v in stats.items()],
        "tempflags": tf,
        "quests": [{"name": k, "want": v} for k, v in sorted(quests.items())],
        "options": [OPTNAME[o] for o in sorted(opts)],
        "notes": sorted(set(other)),
        "anyOf": [[pretty(o) for o in g] for g in groups],
    }

# ---------- flag provenance ----------

SETTERS = defaultdict(list)
for e in EV:
    if e["type"] == "setflag" and e["val"] == "True":
        SETTERS[e["var"]].append(e)

RE_BAREFLAG = re.compile(r'\b([A-Za-z]\w*(?:Date|Quest|Trigger|Secret|Lesson|Setup|Primed|Peeked|Number|Book|Talk\w*))\b')

def flag_prereqs(conds):
    out = {}
    for raw in conds:
        if not raw: continue
        for m in RE_BAREFLAG.finditer(raw):
            v = m.group(1)
            if v in SETTERS and v not in out:
                s = SETTERS[v][0]
                out[v] = {"scene": sname(s["owner"]),
                          "slots": scene_slots(s["owner"]),
                          "choices": [clean(g["text"]) for g in s["guards"] if g["kind"] == "choice"]}
    return out

# ---------- routes ----------

# The alternatives are whole edges, not just their guard stacks: two ways into
# the same scene can differ in what they cost as well as in what they demand.
# `d1midnight` reaches `d1midnightDefault` twice over, and only the second hands
# the timeslot back.
EDGE_ALTS = defaultdict(list)
for _e in EDGES:
    EDGE_ALTS[(_e["src"], _e["dst"])].append(_e)

# ---------- scene scores ----------
# `PuzzleHold >= 4` tells a player nothing. The number is built on the spot: the
# scene zeroes the counter and then adds one for each clue you happen to be
# carrying, so the real requirement is "any 4 of these ten". `mood`, `hypnosisA`
# and the per-room event counters all work the same way. Recover the tally so a
# plan can say what actually counts.
RE_ZERO = re.compile(r'^\$?\s*(\w+)\s*=\s*0$')
RE_BUMP = re.compile(r'^\$?\s*(\w+)\s*\+=\s*(\d+)$')
RE_IF   = re.compile(r'^(?:el)?if\s+(.*?):$')

def _indent(s): return len(s) - len(s.lstrip(" "))

_LINES = {}
def _lines(fn):
    if fn not in _LINES:
        _LINES[fn] = open("_decompiled/" + fn, encoding="utf-8").read().split("\n")
    return _LINES[fn]

def _enclosing_menu(lines, h):
    """The `menu:` header the option at line `h` belongs to."""
    ind = _indent(lines[h])
    for k in range(h - 1, -1, -1):
        if not lines[k].strip(): continue
        if _indent(lines[k]) < ind:
            return k if lines[k].strip() == "menu:" else None
    return None

def _menu_tally(lines, k):
    """Every option of the menu at line `k`, with the counters its block feeds.

    A contest is really a menu, and "here are your choices and what each one is
    worth" is the only useful way to say it -- the player is standing in front
    of that list. Options that feed nothing (`That's all`, which is how you end
    the Sunday search) matter as much as the ones that do, so they are kept."""
    base, step, out = _indent(lines[k]), None, []
    for j in range(k + 1, len(lines)):
        if not lines[j].strip(): continue
        ind = _indent(lines[j])
        if ind <= base: break
        if step is None: step = ind
        if ind != step: continue
        m = RE_CHOICE.match(lines[j].strip())
        if not m: continue
        adds, e = [], j + 1                   # the option's whole block, nested included
        while e < len(lines):
            if lines[e].strip() and _indent(lines[e]) <= ind: break
            b = RE_BUMP.match(lines[e].strip())
            if b and b.group(2) != "0": adds.append((int(b.group(2)), b.group(1)))
            e += 1
        out.append((clean(m.group(1)), list(dict.fromkeys(adds))))
    return out

RE_EXIT = re.compile(r'^if\s+(\w+)\s*>=\s*(\d+)\s*:$')

def _menu_exit(lines, k):
    """A menu that loops back on itself: what ends it, and what a pass costs.

    `label C3DinnerHailySearch:` opens `if eventTimer >= 4: jump …Resolve` and
    then `$ eventTimer += 1`, so the questioning gives four picks -- and an
    option that bumps the counter far enough ends it on the spot. Without this
    the menu reads as though it has no way out, which is exactly how a player
    ends up cycling it: `That's all` is the exit and nothing else says so."""
    ind = _indent(lines[k])
    lab = None
    for j in range(k - 1, -1, -1):
        if not lines[j].strip(): continue
        if _indent(lines[j]) < ind:
            lab = j if lines[j].strip().startswith("label ") else None
            break
    if lab is None: return None
    var = at = per = None
    for j in range(lab + 1, k):
        s = lines[j].strip()
        if not s or _indent(lines[j]) != ind: continue
        m = RE_EXIT.match(s)
        if m and j + 1 < len(lines) and lines[j + 1].strip().startswith("jump "):
            var, at = m.group(1), int(m.group(2))
        b = RE_BUMP.match(s)
        if b and var and b.group(1) == var: per = int(b.group(2))
    return {"var": var, "at": at, "per": per or 1} if var else None

def _scores():
    out, menus = defaultdict(list), {}
    for fn in sorted(os.listdir("_decompiled")):
        if not fn.endswith(".rpy"): continue
        lines = _lines(fn)
        for i, line in enumerate(lines):
            m = RE_ZERO.match(line.strip())
            if not m: continue
            var, base = m.group(1), len(line) - len(line.lstrip(" "))
            for j in range(i + 1, len(lines)):
                s = lines[j]
                if not s.strip(): continue
                ind = len(s) - len(s.lstrip(" "))
                if ind < base: break                  # the block ended
                b = RE_BUMP.match(s.strip())
                if not b or b.group(1) != var or b.group(2) == "0": continue
                for h in range(j - 1, max(-1, j - 40), -1):   # what it hangs off
                    p = lines[h]
                    if not p.strip(): continue
                    if len(p) - len(p.lstrip(" ")) >= ind: continue
                    c, ch = RE_IF.match(p.strip()), RE_CHOICE.match(p.strip())
                    if c: out[var].append((int(b.group(2)), "cond", c.group(1)))
                    elif ch:
                        out[var].append((int(b.group(2)), "choice", clean(ch.group(1))))
                        mk = _enclosing_menu(lines, h)
                        # the first menu wins: a counter fed from a sub-menu as
                        # well is still built at the top one the player sees
                        if mk is not None and var not in menus: menus[var] = (fn, mk)
                    break
    # one scene can zero the same counter in two places; the tally is the same
    return ({k: list(dict.fromkeys(v)) for k, v in out.items()},
            {k: {"options": _menu_tally(_lines(fn), mk),
                 "exit": _menu_exit(_lines(fn), mk)} for k, (fn, mk) in menus.items()})

# Every counter, however few things feed it. A tally with a single source is not
# worth reporting as a score in its own right -- `SCORES` drops those -- but it
# is worth reporting as the *rival* of one that is: the Haily search weighs
# Bedroom against Forest, and Forest has exactly one clue behind it.
SCORE_PARTS, SCORE_MENUS = _scores()
SCORES = {k: v for k, v in SCORE_PARTS.items() if len(v) > 1}

# ---------- sessions: a counter the scene zeroes and rebuilds from its own menus
# `hypnosisA >= 6` looks like the scores above and is not one. A score is built
# from what the player walks in carrying, so it can be chased. This is built
# *inside* the scene, from a run of `menu:` blocks that each take exactly one
# pick, and read once at the end -- there is nothing to schedule, only a path to
# choose. Two of the sessions run two counters side by side: the girl you are
# hypnotising and Lina, sitting beside her and catching it, and every option
# moves both, often in opposite directions. Listing the positive contributions to
# one counter as "score at least 4 from these ten" is the wrong shape three times
# over -- the picks are not free, the list never says whose trance it is, and it
# hides what the same pick does to the other girl.
#
# The multipliers at the end matter as much as the picks. Jenny's first session
# *halves* her own counter unless she is Prey or Predator, and Cassidy's lesson
# scales both by 1.5, so whether a threshold is reachable at all depends on the
# setup. They are kept in source order, with the `int()` truncation, so a solver
# can reproduce the arithmetic exactly rather than approximate it.

# Both directions and both spellings: the sessions write `+= -1` and the Alex
# date writes `-=1`, and reading only `+=` makes a pick that costs a point look
# free. `RE_BUMP` above stays unsigned on purpose -- it feeds the score tallies.
RE_SBUMP = re.compile(r'^\$?\s*(\w+)\s*(\+|-)=\s*(-?\d+)$')
RE_SCALE = re.compile(r'^\$?\s*(\w+)\s*=\s*(int\()?\s*(\w+)\s*\*\s*([\d.]+)\s*\)?$')
RE_LABEL = re.compile(r'^label\s+([\w.]+)\s*:')
# `RE_CHOICE` throws the option's `if` away; here it decides whether the run may
# take that pick at all, so keep it.
RE_SOPT = re.compile(r'^"(.*?)"(?:\s+if\s+(.*?))?\s*:$')

def _block_end(lines, i, base):
    for j in range(i + 1, len(lines)):
        if lines[j].strip() and _indent(lines[j]) <= base: return j
    return len(lines)

RE_ASSIGN = re.compile(r'^\$?\s*(\w+)\s*=[^=]')

def _opt_adds(lines, k, ind, zeros):
    """What an option does to the counters on its own. -> (adds, exact?)

    Only what sits at the option's own indent counts, and nothing may assign the
    counter. A bump under an `if` depends on the rest of the setup; a bump under
    a nested `menu:` is a second pick this model does not make; an assignment is
    not a bump at all. Alex's bedroom visit has all three -- `"Compliment
    breasts"` opens a sub-menu whose branches are `+1` and `= -1` -- so summing
    everything in the block credited the option a point for a choice the plan
    never names. Where an option is not exact, the whole session is dropped: a
    path is only worth printing if the number at the end of it is right."""
    adds, exact, base = defaultdict(int), True, None
    for e in range(k + 1, _block_end(lines, k, ind)):
        s = lines[e].strip()
        if not s: continue
        if base is None: base = _indent(lines[e])
        own = _indent(lines[e]) == base
        b = RE_SBUMP.match(s)
        if b and b.group(1) in zeros:
            if own:
                adds[b.group(1)] += int(b.group(3)) * (1 if b.group(2) == "+" else -1)
            else: exact = False
            continue
        a = RE_ASSIGN.match(s)
        if a and a.group(1) in zeros: exact = False
    return dict(adds), exact

def _session(lines, i):
    """The label starting at line `i`, if it is a session. Else None."""
    end, zeros, menus, mods, base = _block_end(lines, i, 0), [], [], [], None
    last = i                       # where the run of menus finishes
    for j in range(i + 1, end):
        s = lines[j].strip()
        if not s: continue
        if base is None: base = _indent(lines[j])
        if _indent(lines[j]) != base: continue
        m = RE_ZERO.match(s)
        if m: zeros.append(m.group(1)); continue
        if s == "menu:":
            opts, step = [], None
            for k in range(j + 1, _block_end(lines, j, base)):
                if not lines[k].strip(): continue
                if step is None: step = _indent(lines[k])
                if _indent(lines[k]) != step: continue
                c = RE_SOPT.match(lines[k].strip())
                if not c: continue
                adds, flat = _opt_adds(lines, k, step, zeros)
                if not flat: opts = None; break
                opts.append({"text": clean(c.group(1)), "cond": c.group(2),
                             "adds": adds})
            if opts and any(o["adds"] for o in opts):
                menus.append(opts); last = _block_end(lines, j, base)
            continue
        c = RE_IF.match(s)
        if not c: continue
        for k in range(j + 1, _block_end(lines, j, base)):
            mm = RE_SCALE.match(lines[k].strip())
            if mm and mm.group(1) == mm.group(3) and mm.group(1) in zeros:
                mods.append({"group": j, "cond": c.group(1), "var": mm.group(1),
                             "factor": float(mm.group(4)), "int": bool(mm.group(2))})
    # One menu is an ordinary branch; a run of them building the same counter is
    # the shape that needs a path spelled out.
    if len(menus) < 2: return None
    used = [v for v in zeros if any(v in o["adds"] for m in menus for o in m)]
    if not used: return None
    # The number has to be finished before anything looks at it. Alex's oral
    # date tests `alexHorny >= 2` halfway through and then keeps offering picks,
    # so the menus after that test decide nothing about it -- adding them up
    # would report a total the scene never had when it mattered.
    rx = re.compile(r'\b(?:%s)\s*(?:>=|<=|==|!=|>|<)' % "|".join(used))
    for j in range(i + 1, last):
        s = lines[j].strip()
        if RE_SBUMP.match(s) or RE_ZERO.match(s) or RE_SCALE.match(s): continue
        if rx.search(s): return None
    return {"vars": used, "menus": menus,
            "mods": [d for d in mods if d["var"] in used]}

def _find_sessions():
    out = {}
    for fn in sorted(os.listdir("_decompiled")):
        if not fn.endswith(".rpy"): continue
        lines = _lines(fn)
        for i, line in enumerate(lines):
            m = RE_LABEL.match(line)
            if not m: continue
            s = _session(lines, i)
            if s: out[m.group(1)] = dict(s, file=fn, line=i + 1)
    return out

SESSION = _find_sessions()

def _session_at():
    """Every label a session's counters are still live in.

    The counter outlives the label that built it: `JennyGarden1Hypnosis` jumps
    to its own Part2 and on into `linahypbj`, and it is *there* that the number
    is read. So walk forward from each session until another one zeroes the
    counters or the loop hub takes over, and hang the session on everything in
    between -- that is how a step lands on the picks that decided it."""
    fwd = defaultdict(set)
    for e in EDGES: fwd[e["src"]].add(e["dst"])
    out = defaultdict(set)
    for s in SESSION:
        seen, q = {s}, [s]
        while q:
            for d in fwd.get(q.pop(), ()):
                if d in seen or d in SESSION or d in ("dayhandler", "dayInit"): continue
                seen.add(d); q.append(d)
        for lab in seen: out[lab].add(s)
    return {k: tuple(sorted(v)) for k, v in out.items()}

SESSION_AT = _session_at()

# Longest first, so `linaLove` is not read as Lin's and `LinaSMS9` not as Lin's.
_CHARPRE = sorted(CHARS, key=len, reverse=True)
RE_CHARVAR = re.compile(r'^(%s)(?=[A-Z])' % "|".join(_CHARPRE))
RE_MAILVAR = re.compile(r'^(%s)SMS' % "|".join(c.capitalize() for c in _CHARPRE))

def _counter_char(sess, var):
    """Whose trance a counter is, read off what clearing it actually pays.

    Nothing in the source says `hypnosisB` is Lina's -- the name is a letter.
    But the blocks it gates are unambiguous: they hand out `linaLove`, `linaBE`,
    `LinaSMS27` and a Lina corruption record, and nothing else. So take the
    verdict of everything the counter gates, scoped to the labels this session
    reaches -- `hypnosisA` is Jenny's in her garden and Lisa's in the master
    bedroom, and a global count would have to pick one and be wrong twice."""
    m = RE_CHARVAR.match(var)                # `alexHorny` names her outright
    if m: return DISPLAY[m.group(1)]
    labels = {k for k, v in SESSION_AT.items() if sess in v}
    rx, votes = re.compile(r'\b%s\s*[<>=]' % re.escape(var)), Counter()
    for e in EV:
        if e["owner"] not in labels: continue
        if not any(g.get("kind") == "cond" and rx.search(g.get("text") or "")
                   for g in e["guards"]): continue
        if e["type"] == "cor":
            c = re.search(r'\|c\|(\w+)\|', e.get("value") or "")
            if c and c.group(1).lower() in CHARS: votes[c.group(1).capitalize()] += 1
        elif e["type"] == "stat":
            c = RE_CHARVAR.match(e.get("var") or "")
            if c: votes[DISPLAY[c.group(1)]] += 1
        elif e["type"] == "setflag":
            c = RE_MAILVAR.match(e.get("var") or "")
            if c: votes[c.group(1)] += 1
    return votes.most_common(1)[0][0] if votes else None

SESSION_CHAR = {(s, v): _counter_char(s, v)
                for s, d in SESSION.items() for v in d["vars"]}

def counter_name(sess, var):
    """`hypnosisB` is Lina's trance; `alexHorny` is already Alex's Horny."""
    if RE_CHARVAR.match(var): return statname(var)
    who = SESSION_CHAR.get((sess, var))
    return "%s's trance" % who if who else var

def negated_at(text, pos):
    """Is the term starting at `pos` the one a `not` applies to?"""
    return re.search(r'(?:^|\W)not$', text[:pos].rstrip()) is not None

def cor_vars(conds, want=True):
    """The rungs these conditions demand ON (or, with want=False, OFF).

    A rung counts only when *every* way of satisfying the condition needs it,
    so an alternative is a requirement and a disjunct is not. Scanning the raw
    string instead -- which is what this did -- read
    `not (alexCorruptionPregOn and hailyCorruptionPregOn)` as demanding both
    rungs ON, and `pick_alts` scores route branches on exactly this."""
    out = set()
    k = 0 if want else 1
    for c in conds:
        if not c: continue
        alts = cor_clauses(c)
        if alts: out |= set.intersection(*[set(a[k]) for a in alts])
    return out

def guard_conds(gs):
    out = []
    for g in gs:
        if g["kind"] == "choice":
            if g.get("cond"): out.append(g["cond"])
        else:
            out.append(g["text"])
    return out

def pick_alts(route, known, banned=()):
    """A location often opens through an if/elif chain of alternatives; choose
    the branch that adds the fewest new corruption toggles.

    Walked backwards, so `known` already holds what the rest of the route needs
    switched on. A branch guarded `not hailyCorruption2On` is no use when a
    later hop demands that rung ON, however few toggles it appears to cost, so
    contradicting `known` outweighs everything else. `banned` is the mirror:
    rungs the target itself insists stay off, which a route must not demand.

    Between two branches that are equally compatible, the cheaper one in
    timeslots wins: an entrance that plays the scene and hands the sitting back
    is strictly better than one that spends it. Returns the chosen edge, so the
    caller can read its cost off the same alternative it is about to describe.
    """
    banned, chosen = set(banned), []
    for e in reversed(route):
        alts = EDGE_ALTS.get((e["src"], e["dst"])) or [e]
        best, score = None, None
        for a in alts:
            conds = guard_conds(a["guards"])
            need = cor_vars(conds)
            # a first-playthrough-only branch is not a route at all, so it loses
            # to anything else before toggle cost is even considered
            sc = (a.get("firstRun", False),
                  len(need & banned), cor_clash(conds, known), a.get("dv", 0),
                  len(need - known), len(need))
            if score is None or sc < score: best, score = a, sc
        chosen.append((best, len(alts)))
        known |= cor_vars(guard_conds(best["guards"]))
    return list(reversed(chosen))

def make_route(ev, root):
    reach = RBR.get(root, {})
    if ev["owner"] not in reach: return None
    route = [EDGES[i] for i in reach[ev["owner"]]]

    scene_steps, seed = [], []
    for g in ev["guards"]:
        if g["kind"] == "choice":
            scene_steps.append({"kind": "choice", "text": clean(g["text"])})
            if g.get("cond"): seed.append(g["cond"])
        else:
            seed.append(g["text"])
            scene_steps.append({"kind": "cond", "text": pretty(g["text"]), "raw": g["text"]})

    conds, nav = list(seed), []
    for e, (alt, nalt) in zip(route, pick_alts(route, cor_vars(seed))):
        gt = []
        for g in alt["guards"]:
            if g["kind"] == "choice":
                gt.append({"kind": "choice", "text": clean(g["text"])})
                if g.get("cond"): conds.append(g["cond"])
            else:
                conds.append(g["text"])
                gt.append({"kind": "cond", "text": pretty(g["text"]), "raw": g["text"]})
        nav.append({"to": sname(e["dst"]), "guards": gt, "alts": nalt})

    r = ROOTS[root]
    m = re.match(r'sceneC(\d)(\w+)\.rpy', ev.get("file", ""))
    return {
        "scene": sname(ev["owner"]), "label": ev["owner"],
        "file": ev["file"], "line": ev["line"],
        "day": r["day"], "time": r["time"], "dateVar": r.get("dateVar", 0),
        "slot": slot_label(r),
        "nav": nav, "scene_steps": scene_steps,
        "reqs": parse_reqs(conds), "flags": flag_prereqs(conds),
        "tier": {"tier": int(m.group(1)), "char": m.group(2)} if m else None,
    }

def routes_for(events):
    """One route per (unlock site x timeslot), deduped, in play order."""
    out, seen = [], set()
    for ev in events:
        for root in RBR:
            r = make_route(ev, root)
            if not r: continue
            key = (r["dateVar"], r["label"],
                   tuple(s["text"] for s in r["scene_steps"] if s["kind"] == "choice"),
                   tuple(n["to"] for n in r["nav"]))
            if key in seen: continue
            seen.add(key); out.append(r)
    out.sort(key=lambda r: (r["dateVar"], len(r["nav"])))
    return out

# ---------- the catalogue of dots ----------

# `totalCorruption` is the list of every unlockable the game draws a pip for --
# on each MapBook scene page, and in the per-tier checklist on every end-of-loop
# character panel. All 498 `totalCorruption.add(...)` calls sit in `_Init`
# blocks, and `addCor` is a no-op on a value that is not already in the set, so
# this -- not the grant sites -- is the catalogue. Six records in 0.62d are
# spelled differently at their grant site (the author's typos: a scene id or a
# `p|` flag that does not match), so the dot can never light; they are listed
# anyway, without a plan, because the checklist still shows them.
RE_CATALOG = re.compile(r'totalCorruption\.add\("([^"]+)"\)')

def read_catalog():
    """Every record in totalCorruption, in the order the _Init blocks add it."""
    out, seen = [], set()
    for fn in sorted(os.listdir("_decompiled")):
        if not fn.endswith(".rpy"): continue
        with open(os.path.join("_decompiled", fn), encoding="utf-8") as fh:
            for rec in RE_CATALOG.findall(fh.read()):
                if rec in seen: continue
                seen.add(rec); out.append(rec)
    return out

def parse_record(v):
    """sceneID|t|tier|c|character|s|style|p|pregBool|f|pegBool|n|display name"""
    try:
        scene, rest = v.split("|t|", 1)
        tier, rest = rest.split("|c|", 1)
        cha, rest = rest.split("|s|", 1)
        style, rest = rest.split("|p|", 1)
        preg, rest = rest.split("|f|", 1)
        peg, name = rest.split("|n|", 1)
    except ValueError:
        return None
    ch = cha.capitalize()
    # `nerve` is Lina's second bucket -- addCor itself rewrites it to lina.
    if ch.lower() == "nerve": ch = "Lina"
    return {"scene": scene, "tier": int(tier) if tier.isdigit() else 0,
            "char": ch, "style": style, "preg": preg == "True", "name": name}

def grant_sites():
    """addCor calls, by the exact record string they grant.

    `label after_load:` in script.rpy re-grants records from legacy persistent
    flags when an old save is loaded. It has the same shape as a real grant and
    is not one -- the same save-shuffling `mails.py` ignores in `Phone_Init` --
    so it is dropped here rather than left to be picked as a plan's final scene.
    """
    by = defaultdict(list)
    for ev in EV:
        if ev["type"] != "cor": continue
        if ev["owner"] == "after_load": continue
        by[ev["value"]].append(ev)
    return by

# ---------- targets ----------

def build_targets():
    targets = []

    for c in CHARS:
        for e in L.get(c, []):
            evs = [x for x in EV if x["type"] == "flag" and x["var"] == e["var"]
                   and any(x["file"] == s["file"] and x["line"] == s["line"] for s in e["sites"])]
            targets.append({"id": "cor:" + e["var"], "kind": "corruption",
                            "char": DISPLAY[c], "name": e["name"], "var": e["var"],
                            "routes": routes_for(evs), "_events": evs})

    # One target per dot. Keyed on the record string itself, so two dots with the
    # same name at different scenes stay two dots -- Alex's Corruption 2 Blowjob
    # is paid by "Moisturizing Alex" and by "Share Bed with Alex", and merging
    # them by name used to hide one of the two and plan the survivor from
    # whichever site happened to score better.
    grants = grant_sites()
    record = {}
    for seq, rec in enumerate(read_catalog()):
        r = parse_record(rec)
        if not r: continue
        evs = grants.get(rec, [])
        # A mail record is the dot the mail's path also pays, not the letter --
        # the letter is `<Char>SMS<n>` and has its own catalogue. Fold the
        # style/tier onto the mail for the phone tab, and keep the dot here.
        mail = r["name"].startswith("New Mail:")
        name = r["name"][len("New Mail:"):].strip() if mail else r["name"]
        if mail:
            record.setdefault((r["char"], name),
                              {"tier": r["tier"], "style": r["style"],
                               "preg": r["preg"]})
        targets.append({"id": "dot:" + rec, "kind": "unlock",
                        "char": r["char"], "name": name, "mailDot": mail,
                        "tier": r["tier"], "style": r["style"], "preg": r["preg"],
                        "scene": r["scene"], "sceneName": sname(r["scene"]),
                        "seq": seq, "grants": len(evs),
                        "routes": routes_for(evs), "_events": evs})

    # The mail catalogue proper: one target per <Char>SMS<n>, the booleans the
    # phone's Mail panel actually draws.
    for ch in sorted(M):
        for r in M[ch]:
            sites = {(s["file"], s["line"]) for s in r["sites"]}
            evs = [x for x in EV if x["type"] == "setflag" and x["var"] == r["var"]
                   and x["val"] == "True" and (x["file"], x["line"]) in sites]
            t = {"id": "mail:" + r["var"], "kind": "mail", "char": ch,
                 "name": r["name"], "variant": r["variant"], "hint": r["hint"],
                 "routes": routes_for(evs), "_events": evs}
            t.update(record.get((ch, r["name"]), {}))
            targets.append(t)

    # The Memories and Dreams galleries. A reward is not a scene you visit -- all
    # 80 have zero routes from any root -- so the target is a *prerequisite*
    # plan, anchored on `endCyclePhone`. That anchor is right twice over: the
    # panel really is drawn at the end-of-loop menu, and `<char>Love` resets each
    # loop, so a `Love >= 6` gate has to be met by the end of the very run whose
    # phone you are checking. dateVar 22 is exactly that deadline.
    #
    # The corruption rungs the tile wants are NOT handed to the planner: they
    # cross-link to their own `cor:<var>` targets. `not alexCorruption5` is a
    # positive requirement (the unlock vars are inverted), and minting a fact for
    # that shape would change every one of the game's other guards too. See
    # `rewards.split_cond`.
    for r in R:
        evs = []
        if r["residue"]:
            evs = [{"type": "reward", "owner": "endCyclePhone",
                    "guards": [{"kind": "cond", "text": r["residue"],
                                "file": r["file"], "line": r["line"]}],
                    "file": r["file"], "line": r["line"]}]
        targets.append({
            "id": r["id"], "kind": "memory" if r["section"] == "memory" else "dream",
            "char": r["char"], "name": r["name"], "section": r["section"],
            "scene": r["scene"], "hint": r["hint"], "cond": r["cond"],
            "requires": r["requires"],
            "available": not r["requires"] and not r["residue"],
            "routes": routes_for(evs), "_events": evs})

    ORDER = ["Corruption1", "CorruptionPrey", "CorruptionPred", "Corruption2",
             "Corruption3", "Corruption4", "Corruption4M", "Corruption4D",
             "Corruption5", "CorruptionNote", "CorruptionAlex", "CorruptionPast1",
             "CorruptionGym", "CorruptionSpy", "CorruptionMoonstone", "CorruptionPreg"]
    # mails list in the order the phone's Mail panel draws them
    MAILPOS = {"mail:" + r["var"]: i for ch in M for i, r in enumerate(M[ch])}
    # rewards list in the order their own section of the panel draws them
    REWPOS, _seen = {}, Counter()
    for r in R:
        REWPOS[r["id"]] = _seen[(r["char"], r["section"])]
        _seen[(r["char"], r["section"])] += 1
    for t in targets:
        if t["kind"] == "corruption":
            sfx = re.sub(r'^[a-z]+', "", t["var"])
            t["order"] = ORDER.index(sfx) if sfx in ORDER else 99
        elif t["kind"] == "mail":
            t["order"] = MAILPOS[t["id"]]
        elif t["kind"] in ("memory", "dream"):
            t["order"] = REWPOS[t["id"]]
        else:
            t["order"] = t.get("tier", 0)

    # A ladder rung or a mail with no route is content the game never wires up,
    # and there is nothing to say about it. A dot is different: the checklist
    # draws it whether or not it can be earned, so hiding one makes the tab
    # disagree with the panel the player is looking at. A Memory or Dream is the
    # same case again, and more so: a tile with nothing to earn is *available
    # now*, which is the most useful thing the tab can say about it.
    KEEP = {"unlock", "memory", "dream"}
    targets = [t for t in targets if t["routes"] or t["kind"] in KEEP]

    colors = {}
    for line in open("_decompiled/characters.rpy", encoding="utf-8"):
        m = re.match(r'define (\w+) = Character\("(.*?)".*who_color="(#\w+)"', line)
        if m and m.group(1) in CHARS: colors[DISPLAY[m.group(1)]] = m.group(3)

    return targets, colors

def main():
    targets, colors = build_targets()
    for t in targets: t.pop("_events", None)
    json.dump({"targets": targets, "colors": colors},
              open("_analysis/app_data.json", "w", encoding="utf-8"),
              separators=(",", ":"))

    import collections
    print("targets: %d" % len(targets))
    print(collections.Counter(t["kind"] for t in targets))
    print("routes: %d" % sum(len(t["routes"]) for t in targets))
    print("size: %.2f MB" % (os.path.getsize("_analysis/app_data.json") / 1048576))
    unres = sum(1 for t in targets for r in t["routes"]
                for tf in r["reqs"]["tempflags"] if tf["kind"] == "unknown")
    tot = sum(1 for t in targets for r in t["routes"] for tf in r["reqs"]["tempflags"])
    print("branch ids unresolved: %d / %d" % (unres, tot))

if __name__ == "__main__":
    main()
