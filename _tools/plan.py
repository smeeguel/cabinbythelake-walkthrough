# Backward-chaining planner: turn one unlock into a full slot-by-slot run plan.
#
# Every requirement is chased to the scene + choice that produces it, then the
# resulting visits are scheduled into the 21 timeslots of the weekend so that
# each producer lands strictly before whatever consumes it.
import re, json, itertools
from collections import defaultdict, deque

import build_app_data as B

EV, ROOTS, RBR, EDGES = B.EV, B.ROOTS, B.RBR, B.EDGES
MAXDEPTH = 6
LAST_DV = 22          # 1..21 are the weekend slots; 22 is end-of-loop mail

# ---------- where a scene can be played ----------

def scene_entries(label):
    """dateVar -> (root, edge-index path), shortest path per slot."""
    out = {}
    for root, reach in RBR.items():
        if label in reach:
            dv = ROOTS[root].get("dateVar", 0)
            if dv not in out or len(reach[label]) < len(out[dv][1]):
                out[dv] = (root, reach[label])
    return out

ENTRIES = {}
def entries(label):
    if label not in ENTRIES: ENTRIES[label] = scene_entries(label)
    return ENTRIES[label]

def candidate_dvs(label):
    e = entries(label)
    if not e: return []
    # Explore mode (dv 0) is available at every timeslot
    if 0 in e: return list(range(2, 22))          # Explore: any weekend slot
    return sorted(d for d in e if 1 <= d <= LAST_DV)

# ---------- what a visit costs in timeslots ----------
# `dayhandler` spends the sitting by doing `dateVar += 1` before it dispatches,
# so anything that does `dateVar -= 1` on the way in is played *and* leaves the
# slot's map still to come. Every automatic event works that way -- the Saturday
# wake-up crawls, Haily's packages, the Sunday-night bedcrawls -- and a couple of
# scenes go the other way and eat a second slot (`resolutions`, and the hot tub
# if you take the option that says "Advances Time").

PROD_TIME = defaultdict(list)
for e in EV:
    if e["type"] == "time": PROD_TIME[e["owner"]].append(e)

def route_path(label, dv):
    e = entries(label)
    if dv in e: return e[dv][1]
    if 0 in e: return e[0][1]
    return None

def route_dv(label, dv, known=(), banned=()):
    """Net dateVar delta along the map route into `label` at slot `dv`.

    Read off the same alternatives `nav_for` is going to describe -- a hop with
    two entrances can be free one way and cost a sitting the other, so costing
    the route from a branch the plan is not taking would be a fiction."""
    path = route_path(label, dv)
    if path is None: return 0
    route = [EDGES[i] for i in path]
    return sum(alt.get("dv", 0) for alt, _ in B.pick_alts(route, set(known), banned))

def scene_dv(label, choices=()):
    """Net dateVar delta the scene itself applies, given the picks we make.

    Only deltas that are certain: unconditional ones, and ones hanging off menu
    choices this visit is taking anyway. A refund behind `if alexBurnt:` is a
    bail-out we are not planning to trigger."""
    tot = 0
    for e in PROD_TIME.get(label, ()):
        gs = e["guards"]
        if any(g["kind"] != "choice" for g in gs): continue
        picks = [B.clean(g["text"]) for g in gs if g["kind"] == "choice"]
        if not all(p in choices for p in picks): continue
        tot += e["delta"]
    return tot

# ---------- the way back out of an explorable room ----------
# The ten rooms behind the map's Explore button are all one shape: a menu that
# loops back on itself (`jump GardenRoomLoop`) with a "Leave" option that does
# `dateVar -= 1` before handing control to `dayhandler`, which spends the sitting
# again. So a visit that only takes options returning to the room's own menu --
# search the garden, dig up the tarot card, leave -- is played for nothing and
# the map for that timeslot is still to come.
#
# The loop-back is the whole signal. `AlexForest1` also has a refunding "Leave",
# but none of its options return to its menu: they fall through to a plain
# `jump dayhandler` at the bottom of the scene, so the sitting is spent whatever
# the player wanted from it.

OUT_EDGES = defaultdict(list)
for _i, _e in enumerate(EDGES): OUT_EDGES[_e["src"]].append(_e)

def _choice_tuple(edge):
    return tuple(B.clean(g["text"]) for g in edge["guards"] if g["kind"] == "choice")

def exit_dv(label, choices=()):
    """The refund waiting on the way out of a scene we never had to leave."""
    outs = OUT_EDGES.get(label, ())
    # the scene's own way out, offered as a menu option, that winds the clock back
    refund = min([e.get("dv", 0) for e in outs
                  if e.get("dv", 0) < 0 and _choice_tuple(e)] or [0])
    if not refund: return 0
    # ...and somewhere for the other options to come back to. Without a menu loop
    # there is no "do the thing, then leave": the scene runs off its own end.
    if not any(e["dst"] not in B.CONTAINERS for e in outs): return 0
    # Judge the picks we are actually making, at their deepest: the shallower
    # entries of a nested menu are the branch we took to get to them.
    picks = [e for e in outs if _choice_tuple(e)
             and all(c in choices for c in _choice_tuple(e))]
    if picks:
        deep = max(len(_choice_tuple(e)) for e in picks)
        picks = [e for e in picks if len(_choice_tuple(e)) == deep]
        # every one of them walks out of the room, so the refund is forgone
        if all(e["dst"] in B.CONTAINERS for e in picks): return 0
    return refund

def is_explore(label, dv):
    """Entered through the map's Explore button rather than off the timeslot's
    own map. Explore mode is a second map one screen behind the first, so the
    step is a three-part instruction: Explore, then the room, then what to do."""
    e = entries(label)
    return dv not in e and 0 in e

def visit_cost(label, dv, choices=(), known=(), banned=()):
    """Timeslots this visit occupies: 0 for an automatic event, 1 normally."""
    return max(0, 1 + route_dv(label, dv, known, banned)
                    + scene_dv(label, choices) + exit_dv(label, choices))

def is_auto(label, dv, known=(), banned=()):
    """Does the game play this by itself at the top of the slot? The slot label
    jumps straight into it after handing the timeslot back -- there is no map
    click to describe, and it fires whether the player wants it or not."""
    return route_dv(label, dv, known, banned) < 0

def slots_taken(cost, dv, used):
    """The slots this visit needs, or None if they are not all free."""
    if cost <= 0: return []
    want = [dv + i for i in range(cost)]
    if any(d > LAST_DV or d in used for d in want): return None
    return want

# Some booleans start life True (`default GoodbyeEventCarla = True`) and are
# only ever cleared. A condition on one of those is satisfied on a fresh run,
# so it is a fact we already hold rather than one we must go and produce.
import os as _os
RE_DEFAULT = re.compile(r'^default (\w+) = (True|False)$')
DEFAULT_TRUE = set()
for _fn in sorted(_os.listdir("_decompiled")):
    if not _fn.endswith(".rpy"): continue
    for _line in open("_decompiled/" + _fn, encoding="utf-8"):
        _m = RE_DEFAULT.match(_line.strip())
        if _m and _m.group(2) == "True": DEFAULT_TRUE.add(_m.group(1))

# `gateFirstRun` is the exception to that: `default gateFirstRun = True`, but the
# first end-of-loop menu clears it (`sceneEndChoices.rpy:71`) and every plan here
# begins at that menu, so it is always False by the time a described run is
# played. Counting it as held makes `not gateFirstRun` -- the fall-through guard
# on most of the slot labels, and so on nearly every automatic event -- look
# unsatisfiable, which hid all of them from the affection top-up.
ALWAYS_FALSE = {"gateFirstRun"}
DEFAULT_TRUE -= ALWAYS_FALSE

# ---------- producer index ----------

PROD_BRANCH, PROD_ITEM, PROD_FLAG, PROD_STAT = (defaultdict(list) for _ in range(4))
for e in EV:
    if e["type"] == "branch" and e["val"] >= 2:
        PROD_BRANCH[e["id"]].append(e)
    elif e["type"] == "item":
        PROD_ITEM[e["name"]].append(e)
    elif e["type"] == "setflag" and e["val"] == "True":
        PROD_FLAG[e["var"]].append(e)
    elif e["type"] == "stat" and e["op"] == "+=" and e["amount"] > 0:
        PROD_STAT[e["var"]].append(e)

# ---------- facts ----------

RE_TEMPC = re.compile(r'tempFlags\[\s*"([\w-]+)"\s*\]\s*(>=|==|>|<|<=)?\s*(\d+)?')
# `("Item: King of Hearts") in commonEvents` -- the parens are the author's.
RE_ITEMC = re.compile(r'"([^"]+)"\s*\)?\s+in\s+commonEvents')
# `PuzzleHold >= 4` -- a tally the scene builds on the spot; see `B.SCORES`.
A_SCORE  = re.compile(r'^(\w+)\s*(>=|>|==)\s*(\d+)$')
# The same kind of tally scored as a contest: `C3DinnerHailySearchBedroom >=
# max(C3DinnerHailySearchHypnosis,C3DinnerHailySearchForest,1)`. The Sunday
# dinner search follows whichever theory you gave the most weight to, so the
# requirement is not a threshold but "beat the others, and score at least the
# integer in the max()".
A_CONTEST = re.compile(r'^(\w+)\s*>=\s*max\(([^()]*)\)$')

def negated_at(text, pos):
    """Is the term starting at `pos` the one a `not` applies to? An atom is not
    always a single term: an alternative inside an OR-group can be a whole
    clause, and `(A or B) and not C` must not be read as demanding C."""
    return re.search(r'(?:^|\W)not$', text[:pos].rstrip()) is not None

RE_NOTPAREN = re.compile(r'\bnot\s*\(')

def drop_negated_groups(a):
    """Remove `not ( … )` spans. Nothing inside one is a requirement, and the
    guards are full of them: `not (hailyCorruption3On and tempFlags[x] == 3)`."""
    out, i = [], 0
    while True:
        m = RE_NOTPAREN.search(a, i)
        if not m:
            out.append(a[i:]); return "".join(out)
        out.append(a[i:m.start()])
        d, j = 1, m.end()
        while j < len(a) and d:
            if a[j] == "(": d += 1
            elif a[j] == ")": d -= 1
            j += 1
        i = j

def stat_fact(m):
    """An affection comparison -> the `("stat", var, n)` floor it demands.

    A fact is "at least n", so only `>=` and `>` are one, and `>` is one more
    than it says: `alexLove > 4` wants five, and reading it as four is a plan
    that comes up exactly one short at the scene it was written for. The other
    three operators are not floors at all -- `alexLove <= 0`, `jennyLove <= 0`
    and `hailyTalk == 0` are *ceilings*, and turning one into "at least 0" makes
    an upper bound vanish as a gate that is trivially met. The model has no way
    to say "and no more than this", so they produce no fact and `unmodelled`
    reports them on the plan instead."""
    op, n = m.group(2), int(m.group(3))
    if op == ">=": return ("stat", m.group(1), n)
    if op == ">":  return ("stat", m.group(1), n + 1)
    return None

def atom_facts(atom):
    """A conjunctive atom -> the facts it demands (positive only)."""
    a = atom.strip()
    if a.startswith("not "): return []          # negatives are warnings, not goals
    a = drop_negated_groups(a)
    out = []
    def scan(rx, make):
        for m in rx.finditer(a):
            if negated_at(a, m.start()): continue
            f = make(m)
            if f: out.append(f)
    scan(B.RE_COR, lambda m: ("cor", m.group(1)))
    scan(B.RE_WORLD, lambda m: ("world", int(m.group(2))))
    scan(RE_ITEMC, lambda m: ("item", m.group(1)))
    scan(RE_TEMPC, lambda m: ("branch", m.group(1)))
    scan(B.RE_STAT, stat_fact)
    scan(B.RE_OPT, lambda m: ("option", m.group(1)))
    if not out:
        # A scene score -- `PuzzleHold >= 4` -- is an any-N-of-these built from
        # facts we can chase like any other. Only the tallies whose points come
        # from conditions; where the points come from options inside the gated
        # scene there is nothing to schedule, so it stays a note.
        m = A_SCORE.match(a)
        if m and any(k == "cond" for _, k, _ in B.SCORES.get(m.group(1), ())):
            out.append(("score", m.group(1), int(m.group(3))))
    if not out:
        w = a.split()
        if len(w) == 1 and re.match(r'^[A-Za-z]\w*$', a) and a in PROD_FLAG:
            out.append(("flag", a))
    return out

def guard_conds(guards):
    conds = []
    for g in guards:
        if g["kind"] == "choice":
            if g.get("cond"): conds.append(g["cond"])
        elif g["text"] != "(otherwise)":
            conds.append(g["text"])
    return conds

def site_reqs(guards):
    """-> (facts that must all hold, [ [alternative fact-lists], ... ])"""
    hard, groups = B.flatten(guard_conds(guards))
    facts = []
    for a in hard: facts.extend(atom_facts(a))
    alts = []
    for grp in groups:
        opts = [atom_facts(o) for o in grp]
        opts = [o for o in opts if o]
        if not opts: continue         # nothing actionable: treat as satisfied
        opts.sort(key=lambda f: sum(0 if k[0] in ("cor", "world", "option") else 1 for k in f))
        alts.append(opts)
    return facts, alts

def site_goals(guards):
    """Flat view used only for costing a candidate site."""
    hard, alts = site_reqs(guards)
    return hard + [f for grp in alts for f in grp[0]]

def choices_of(guards):
    return [B.clean(g["text"]) for g in guards if g["kind"] == "choice"]

RE_SMSVAR = re.compile(r'^not\s+\w+SMS[0-9]+[a-z]?(Open)?$')

def dedup(xs):
    return list(dict.fromkeys(xs))

def minimal_setup(vars_):
    """The toggles the player actually flips at the end-of-loop menu.

    Switching a rung on switches on every rung below it (landmine 21), so a
    ladder is a position, not a set: listing Lina·Found Out beside Lina·Open
    asks for a menu state that does not exist -- Open *is* Found Out. Keep only
    the rungs nothing else in the setup already brings with it. The add-on rungs
    sit on nobody's ladder (Fertile, Package, Pregnant's own switch), so they
    survive alongside the ladder position rather than being folded into it, and
    the closure is the same either way -- this changes the list, not the run."""
    vs = set(vars_)
    implied = set()
    for v in vs: implied |= B.CASCADE_ON.get(v, {v}) - {v}
    return sorted(vs - implied)

def rung_num(var):
    """`C2`, `C4-M`, `Preg`, or None for a rung that is not numbered."""
    m = re.match(r'^[a-z]+Corruption(\d)([MD])?$', var)
    if m: return "C%s%s" % (m.group(1), "-" + m.group(2) if m.group(2) else "")
    return "Preg" if var.endswith("Preg") else None

def _rung_row(var):
    ch, nm = B.ladder_name(var)
    return {"var": var, "char": ch, "level": nm, "num": rung_num(var)}

def _is_chain(var):
    """Is this rung a position on the ladder, or a modifier standing beside it?

    The end-of-loop panel's own rows are the answer: `Uncorrupted`,
    `Corruption 1`..`Corruption 5`, then `Corruption Preg` on a row of its own.
    So the numbered rungs are the ladder and everything else -- Preg, Fertile,
    Package, Support, Jenny's Prey/Predator -- is a modifier the player switches
    beside a position.

    Do *not* read this off `B.CASCADE_ON`. `samiCorruptionPreg` closes over
    C1-C5, so a closure test calls it a ladder position, and the ceiling then
    reports "Sami · C5 Composed MAX" -- which is her top rung and therefore says
    nothing at all, while the constraint that mattered (Pregnant must be off)
    vanishes. The closure still decides what a toggle *drags on* (landmine 21);
    it does not decide which menu row the toggle lives on."""
    return bool(re.search(r'Corruption\d', var))

def off_rungs(p, mapping, on):
    """Every rung this plan relies on being switched OFF, and the step that says so.

    The evidence is each visit's own guards plus the map route into it -- the
    `elif` chains on the route are where most rung negations live (landmine 49),
    and the scene's own fall-through negations are where the rest do.

    Per condition, take the cheapest alternative the run *already satisfies*, so
    the card and the itinerary can never disagree about which escape was chosen.
    A condition with no satisfiable alternative is a contradiction and belongs to
    `cascade_conflicts`, not here. Because only alternatives scoring 0 or 1
    contribute, the result is disjoint from `on` by construction, which is what
    makes the ceiling incapable of contradicting the toggle list above it."""
    out = {}
    for k, dv in sorted(mapping.items(), key=lambda x: (x[1], x[0])):
        v = p.visits[k]
        hard, _ = B.flatten(guard_conds(v.guards) +
                            nav_guards(v.owner, dv, set(p.setup_cor), p.banned_cor))
        for a in sorted(hard):
            alts = B.cor_clauses(B.unwrap(a.strip()))
            live = [x for x in alts if B.clause_state(x, on) < 2]
            if not live: continue
            best = min(live, key=lambda x: (x[2], len(x[0]) + len(x[1]),
                                            sorted(x[1]), sorted(x[0])))
            # nothing has to stay off for this one -- no ceiling to state
            if not best[1]: continue
            others = [x for x in live if x is not best and x[1]]
            for var in sorted(best[1]):
                if not B.ladder_name(var)[0]: continue
                out.setdefault(var, []).append({
                    "scene": B.sname(v.owner), "slot": DVLABEL.get(dv, "?"),
                    "alt": sorted({w for x in others for w in x[1]
                                   if B.ladder_name(w)[0]}),
                })
    return out

def roster(p, on, forbidden, why):
    """One row per character the run has anything to say about.

    Three separate questions, and the old single "Do not go past" pill ran them
    together into sentences that were wrong two ways over. `Hypnotising Carla`
    needs Haily's *ladder* at Uncorrupted while `Haily·Package` -- a modifier on
    its own menu row -- is switched ON, and one pill reading "Haily · Uncorrupted
    MAX" beside a toggle reading "Haily · Package ON" is a flat contradiction to
    read. And a cap is only worth stating when it caps something: "Sami · C5
    Composed MAX" is her top rung and forbids nothing.

    So: `min` is the ladder position to switch on, `cap` the highest position
    allowed (None when nothing limits it, `[]` when no position is), and `mods`
    the modifiers that must be ON or OFF. A modifier already ruled out by the cap
    is not listed -- Alex's Pregnant closes over C5, so a run capped at C4
    excludes it for free and saying so twice is noise."""
    setup, out = set(minimal_setup(p.setup_cor)), []
    for c in B.CHARS:
        ladder = [e["var"] for e in B.L.get(c, [])]
        mine = [v for v in ladder if v in setup]
        lo = [v for v in mine if _is_chain(v)]
        blocked = [v for v in ladder if v in forbidden]
        ok = _offerable(p, ladder, on, forbidden)
        cap = None
        if any(_is_chain(v) for v in blocked):
            implied = set()
            for v in ok: implied |= B.CASCADE_ON.get(v, {v}) - {v}
            cap = sorted(v for v in ok if v not in implied and _is_chain(v))
        allowed = ({v for v in ok if _is_chain(v)} if cap is not None
                   else {v for v in ladder if _is_chain(v)})
        mods = [dict(_rung_row(v), state="on") for v in mine if not _is_chain(v)]
        mods += [dict(_rung_row(v), state="off", why=why.get(v, []))
                 for v in blocked if not _is_chain(v)
                 and (B.CASCADE_ON.get(v, {v}) - {v}) <= allowed]
        if not lo and cap is None and not mods: continue
        out.append({
            "char": B.DISPLAY[c],
            "min": _rung_row(lo[-1]) if lo else None,
            "cap": [_rung_row(v) for v in cap] if cap is not None else None,
            "capWhy": [w for v in blocked if _is_chain(v) for w in why.get(v, [])],
            "mods": mods,
        })
    return out

def _offerable(p, ladder, on, forbidden):
    """The rungs of one ladder this run could still switch on.

    Landmine 52's dual. A ladder is a position, so a ceiling is a position too,
    and it is found with the same `B.CASCADE_ON` closure -- never by rung number.
    `alexCorruptionPreg` closes over C1-C5, but `hailyCorruptionPreg` closes over
    itself alone, so a "highest number wins" rule puts Haily's Pregnant above her
    Contact when the two are unrelated.

    A rung is offerable when its closure holds nothing forbidden, when it does
    not clear a rung the setup wants on (`CASCADE_OFF` -- Jenny's 4M and 4D clear
    each other, so they can never both be a maximum), when its `RUNG_GATE` holds
    (landmine 28 -- a ceiling of Cassidy's Together the player cannot even enter
    is worse than none), and, for a Preg rung, when the run has `optionPreg`,
    because the menu does not draw that row otherwise. Reducing the survivors by
    the same closure leaves the maximal positions; the add-on rungs close over
    themselves alone, so they stand beside the position exactly as they do in
    `minimal_setup`."""
    ok = []
    for v in ladder:
        if B.CASCADE_ON.get(v, {v}) & forbidden: continue
        if B.CASCADE_OFF.get(v, set()) & on: continue
        gate = B.RUNG_GATE.get(v)
        if gate and not guards_ok([{"kind": "cond", "text": gate}],
                                  on, set(), p, []): continue
        if v.endswith("Preg") and "optionPreg" not in p.setup_opt: continue
        ok.append(v)
    return ok

def neg_conds(conds):
    out = []
    for a in B.flatten(conds)[0]:
        a = a.strip()
        # `not AlexSMS4` guards a mail against being awarded twice. It is the
        # game's own bookkeeping, not something the player can act on.
        if not a.startswith("not ") or RE_SMSVAR.match(a): continue
        # ...and neither is a `dateVar` test the step's own slot has answered.
        if B.unwrap(a[4:].strip()) in ("True", "False"): continue
        out.append(B.pretty(a))
    return out

def negatives(guards, dv, on=None, produced=None, plan=None):
    """The scene's own negations the player still has to honour.

    Put through `atom_ok` for the same reason `nav_negatives` is (landmine 49):
    once a scene's fall-through negations are recorded, its own guards are as
    full of rung compounds as the route is, and `B.pretty` renders one as
    `NOT (Haily·Arrival ON and NOT (Haily·Hand Holding ON and "…" taken))` --
    a double negative on a step whose setup card already answers it. What the
    run cannot settle is still reported, and the sub-atoms `atom_ok` parks in
    `avoid` on the way are the specific don'ts behind a compound."""
    conds = [fix_dv(c, dv) for c in guard_conds(guards)]
    if on is None: return neg_conds(conds)
    return nav_negatives(conds, dv, on, produced, plan)

RE_DV_IN  = re.compile(r'dateVar\s+in\s+\[([\d,\s]*)\]')
RE_DV_CMP = re.compile(r'dateVar\s*(==|!=|>=|<=|>|<)\s*(\d+)')

def fix_dv(cond, dv):
    """Settle every `dateVar` test in a route guard from the slot we put the
    step in. A negation about which timeslot it is tells the player nothing --
    the row already says Saturday Noon -- but it is often one conjunct of a
    compound that does say something, so answer it rather than dropping it."""
    def rin(m):
        want = [int(x) for x in m.group(1).split(",") if x.strip()]
        return "True" if dv in want else "False"
    def rcmp(m):
        n = int(m.group(2))
        return "True" if {"==": dv == n, "!=": dv != n, ">=": dv >= n,
                          "<=": dv <= n, ">": dv > n, "<": dv < n}[m.group(1)] else "False"
    return RE_DV_CMP.sub(rcmp, RE_DV_IN.sub(rin, cond))

def route_gated(owner, dv, known, banned):
    """Does the way *in* turn on something the fact model cannot schedule?

    Then the row has to say so. The Sunday search is the case that matters: the
    plan named the scene the player ends up in and the picks to make there, but
    between the map click and that scene sits a menu of clues nothing in the
    itinerary mentioned -- so the first options on screen were not the ones
    listed, and the step looked simply wrong."""
    for a in B.flatten([fix_dv(c, dv) for c in nav_guards(owner, dv, known, banned)])[0]:
        a = a.strip()
        if not a or a == "(otherwise)" or a.startswith("not "): continue
        if a in ("True", "False") or atom_facts(a): continue
        if B.RE_BURNT.search(a): continue
        if A_FLAG.match(a) and (a in DEFAULT_TRUE or a in PROD_FLAG): continue
        return True
    return False

def nav_negatives(conds, dv, on, produced, plan):
    """Negations the map route carries that the player still has to honour.

    Landmine 5's mirror. The route into a scene is where the game's `elif`
    chains live, and their negations are requirements as real as the positive
    ones -- the Sunday dinner search only reaches Lina's bedroom because the
    branches above it did not fire, and which of them fires is decided entirely
    by the clues weighed on the way in.

    Most of these the run already settles: the setup card fixes every toggle,
    and anything it does not list is off, so `not (Haily·Contact ON and …)` is
    true before the player does anything. `atom_ok` is the existing answer to
    "does the run guarantee this", De Morgan and all (landmine 31); what it
    cannot confirm is what the player has to steer around, and the sub-atoms it
    parks in `avoid` on the way are the specific don'ts behind a compound."""
    out = []
    for a in B.flatten([fix_dv(c, dv) for c in conds])[0]:
        a = a.strip()
        if not a.startswith("not ") or RE_SMSVAR.match(a): continue
        if B.unwrap(a[4:].strip()) in ("True", "False"): continue
        acc = []
        if atom_ok(a, on, produced, plan, acc): out.extend(acc)
        else: out.append(B.pretty(a))
    return out

# ---------- resolution ----------

class Visit:
    __slots__ = ("owner", "choices", "guards", "gives", "needs", "key", "kinds",
                 "facts", "sess", "counters")
    def __init__(self, owner, guards):
        self.owner = owner
        self.guards = list(guards)
        self.choices = choices_of(guards)
        self.gives, self.needs = [], []
        self.kinds = []          # fact kinds this visit produces
        self.facts = []          # the facts themselves, for reachability checks
        self.key = (owner, tuple(self.choices))
        # thresholds on a counter the scene builds from its own menus
        self.sess, self.counters = None, {}

    def persistent(self):
        """tempFlags survive the loop; commonEvents and Love do not. A visit
        that only sets branch flags can therefore be done in an earlier run."""
        return bool(self.kinds) and all(k == "branch" for k in self.kinds)

def site_cost(site):
    """Prefer few sub-requirements, early availability, and wide availability."""
    dvs = candidate_dvs(site["owner"])
    if not dvs: return (10_000, 99, 0)
    return (len(site_goals(site["guards"])), min(dvs), -len(dvs))

def site_id(site):
    return (site["file"], site["line"])

def producers(fact, banned=()):
    k = fact[0]
    if k == "branch": lst = PROD_BRANCH.get(fact[1], [])
    elif k == "item": lst = PROD_ITEM.get(fact[1], [])
    elif k == "flag": lst = PROD_FLAG.get(fact[1], [])
    else: return []
    return [s for s in lst if site_id(s) not in banned]

FREE = ("<setup grant>",)     # memo marker: had, but from no visit

def setup_grant(site):
    """A site no route reaches whose only conditions are end-of-loop toggles.

    Switching Lisa's The Note on makes the reset hand every run the altered
    suitcase clue, and Alex's Past 1 does the same for her old photos. The owner
    is the reset block, which no map click reaches, so `resolve` skips the site
    and the fact reads as though only a scene could produce it -- the planner
    then goes and earns the clue the long way round, or gives up. These are not
    scenes; they are lines on the setup card.

    The conditions have to be *entirely* understood and there has to be at least
    one: an unreachable label with no guards at all is unwired content, not a
    free gift, and the unlock-everything cheat menu is a whole screen of them."""
    if candidate_dvs(site["owner"]): return None
    if any(g["kind"] == "choice" for g in site["guards"]): return None
    hard, alts = B.flatten(guard_conds(site["guards"]))
    if alts or not hard: return None
    out = []
    for a in hard:
        fs = atom_facts(a)
        if not fs or any(f[0] not in ("cor", "world", "option") for f in fs):
            return None
        out.extend(fs)
    return out

def option_free(facts):
    """Can this alternative be had without spending a sitting on it?"""
    for f in facts:
        if f[0] in ("cor", "world", "option"): continue
        if any(setup_grant(s) for s in producers(f)): continue
        return False
    return True

def cheapest(fact):
    """Rough cost of producing a fact, for ordering score clues."""
    ps = producers(fact)
    return min((site_cost(s)[0] for s in ps), default=99)

def describe(fact):
    k = fact[0]
    if k == "score": return "%s ≥ %d" % (fact[1], fact[2])
    if k == "branch":
        d = B.temp_desc(fact[1])
        return d["text"] if d["kind"] != "unknown" else fact[1]
    if k == "item":  return fact[1]
    if k == "flag":
        # internal flag names read better split on their camel case
        return re.sub(r'(?<!^)(?=[A-Z])', " ", fact[1]).replace("  ", " ")
    if k == "stat":  return "%s ≥ %d" % (B.statname(fact[1]), fact[2])
    if k == "cor":
        ch, nm = B.ladder_name(fact[1])
        return "%s · %s" % (ch, nm) if ch else fact[1]
    if k == "world": return "World Corruption ≥ %d" % fact[1]
    return str(fact)

class Plan:
    def __init__(self, banned=(), banned_cor=(), skip_scores=False):
        self.banned = set(banned)
        # Chasing a scene score can make a target unschedulable -- the photo
        # trades all live behind one screen and want one slot each, though the
        # game lets you make them in a single sitting. When that happens we fall
        # back to reporting the score instead of planning it.
        self.skip_scores = skip_scores
        # rungs the run must leave OFF, because a scene it has to play is
        # guarded `not <rung>On`. Switching on anything that cascades one of
        # these on is therefore not an option.
        self.banned_cor = set(banned_cor)
        self.visits = {}        # key -> Visit
        self.deps = defaultdict(set)   # key -> set of prerequisite keys
        self.setup_cor, self.setup_world, self.setup_opt = {}, 0, set()
        self.stats = {}         # var -> needed value
        self.unresolved = []
        self.memo = {}
        self.site_of = {}       # visit key -> (file,line) of the producing site
        self.failed = None      # visit key that could not be scheduled
        self.prior = set()      # visits pushed into an earlier loop
        self.granted = set()    # facts the end-of-loop setup hands over free
        self.cost_of = {}       # visit key -> timeslots it occupies (0 = automatic)

    def add_visit(self, site):
        """The visit that plays this site -- reusing an existing one where the
        same scene and the same picks can pay for both.

        Two sites usually can. A hypnosis session is where they cannot: the
        counters are zeroed on the way in, so `New Mail: Bathing` wanting Jenny's
        trance at 10 and Lina's at 10 is not one sitting with two rewards but two
        sittings, and only the tempFlags carry between them. Where the game
        cannot deliver both at once, take a second visit rather than claim a
        pick path that does not exist."""
        v = Visit(site["owner"], site["guards"])
        v.sess, v.counters = site_counters(site)
        key, n = v.key, 0
        while key in self.visits:
            cur = self.visits[key]
            # The first site to claim a visit is often an ungated one, so the
            # session comes from whichever site brought a threshold along.
            sess = cur.sess or v.sess
            merged = dict(cur.counters)
            for var, need in v.counters.items():
                merged[var] = max(merged.get(var, 0), need)
            if not sess or joint_ok(sess, merged):
                cur.sess, cur.counters = sess, merged
                # A shared visit answers to both sites' guards, so it has to
                # report both: the second site's conditions are the player's
                # too, and dropping them is how a threshold goes missing.
                seen = {(g.get("kind"), g.get("text")) for g in cur.guards}
                cur.guards.extend([g for g in v.guards
                                   if (g.get("kind"), g.get("text")) not in seen])
                return cur
            n += 1
            key = v.key + (n,)
        v.key = key
        self.visits[key] = v
        return v

    # --- transactional state, so a failed OR branch leaves no residue ---
    def snap(self):
        return (set(self.visits), dict(self.memo),
                {k: set(v) for k, v in self.deps.items()},
                dict(self.setup_cor), self.setup_world, set(self.setup_opt),
                dict(self.stats), len(self.unresolved), set(self.granted),
                {k: (len(v.gives), len(v.needs), len(v.kinds), len(v.facts),
                     len(v.guards), dict(v.counters), v.sess)
                 for k, v in self.visits.items()})

    def restore(self, s):
        keys, memo, deps, cor, world, opt, stats, nun, granted, lens = s
        self.granted = granted
        for k in list(self.visits):
            if k not in keys: del self.visits[k]
        for k, (ng, nn, nk, nf, nq, ctr, sess) in lens.items():
            if k in self.visits:
                del self.visits[k].gives[ng:]
                del self.visits[k].needs[nn:]
                del self.visits[k].kinds[nk:]
                del self.visits[k].facts[nf:]
                del self.visits[k].guards[nq:]
                self.visits[k].counters, self.visits[k].sess = ctr, sess
        self.memo = memo
        self.deps = defaultdict(set, deps)
        self.setup_cor, self.setup_world, self.setup_opt = cor, world, opt
        self.stats = stats
        del self.unresolved[nun:]

    def expand(self, owner_key, guards, depth, stack):
        """Attach everything `guards` demands to the visit `owner_key`."""
        hard, alts = site_reqs(guards)
        ok = True
        for f in hard:
            if f[0] == "score":
                if self.skip_scores:
                    self.unresolved.append((describe(f), None))
                else:
                    ok = self.reach_score(f, owner_key, depth, stack) and ok
                continue
            good, pk = self.resolve(f, depth, stack, owner_key)
            ok = ok and good
            if pk and pk != owner_key:
                self.deps[owner_key].add(pk)
                self.visits[owner_key].needs.append(describe(f))
        for grp in alts:
            done = False
            # `A or B` is a choice, and one of the two is often free: the plain
            # suitcase clue is a scene, the altered one is Lisa's The Note handed
            # over at the reset. Source order would spend a sitting on the first
            # thing that happens to work, so put the ones the setup card can pay
            # for in front. Everything else keeps its order.
            for option in sorted(grp, key=lambda o: 0 if option_free(o) else 1):
                s = self.snap()
                keys, good = [], True
                for f in option:
                    g, pk = self.resolve(f, depth, stack, owner_key)
                    if not g: good = False; break
                    if pk: keys.append((pk, f))
                if good:
                    for pk, f in keys:
                        if pk != owner_key:
                            self.deps[owner_key].add(pk)
                            self.visits[owner_key].needs.append(describe(f))
                    done = True; break
                self.restore(s)
            if not done and grp:
                # no alternative in this group could be produced
                self.unresolved.append((" or ".join(describe(f) for f in grp[0]), None))
                ok = False
        return ok

    def fix_session(self, owner_key, depth, stack):
        """Arrange whatever a session's thresholds need beyond the picks.

        Kept out of `expand` deliberately: it is answered once per site, after
        that site's own guards are in, so it sees the counters both sites of a
        shared visit ask for -- and it expands conditions of its own, which from
        inside `expand` would recurse."""
        v = self.visits.get(owner_key)
        if v is None or not v.sess or not v.counters: return True
        fix = session_fix(v.sess, v.counters)
        if fix is None:
            self.unresolved.append(
                ("no run of “%s” reaches %s" % (B.sname(v.sess), ", ".join(
                    "%s %d" % (B.counter_name(v.sess, x), n)
                    for x, n in sorted(v.counters.items()))), None))
            return False
        ok = True
        for cond, want in fix:
            g = [{"kind": "cond", "text": cond if want else push_not(cond)}]
            ok = self.expand(owner_key, g, depth, stack) and ok
        return ok

    def reach_score(self, fact, owner_key, depth, stack):
        """Earn enough points for a scene score.

        `PuzzleHold >= 4` is any four of ten clues, each of which is an ordinary
        fact -- a quest item or a decision flag. Take them cheapest first, each
        transactionally, until the total is enough. The five flags are
        persistent, so the scheduler is free to push them into an earlier loop;
        the five quest items reset, so they land in this run."""
        var, need = fact[1], fact[2]
        parts = []
        for amt, kind, text in B.SCORES.get(var, ()):
            if kind != "cond": continue
            fs = atom_facts(text)
            if fs and (amt, tuple(fs)) not in [(a, tuple(f)) for a, f in parts]:
                parts.append((amt, fs))
        parts.sort(key=lambda p: (-p[0], sum(cheapest(f) for f in p[1])))

        got = 0
        for amt, fs in parts:
            if got >= need: break
            s = self.snap()
            keys, good = [], True
            for f in fs:
                g, pk = self.resolve(f, depth + 1, stack, owner_key)
                if not g: good = False; break
                if pk: keys.append((pk, f))
            if not good:
                self.restore(s); continue
            for pk, f in keys:
                if pk != owner_key:
                    self.deps[owner_key].add(pk)
                    self.visits[owner_key].needs.append(describe(f))
            got += amt
        if got >= need: return True
        self.unresolved.append(
            ("%s: only %d of the %d points needed could be chained" % (var, got, need),
             None))
        return False

    def resolve(self, fact, depth, stack, consumer=None):
        """-> (satisfiable, visit key or None)"""
        k = fact[0]
        if k == "cor":
            # this run has to leave that rung off, so a route demanding it on is
            # not open to us; `cascade_conflicts` reports any that survive
            if B.toggles_on([fact[1]]) & self.banned_cor: return False, None
            if not B.ladder_name(fact[1])[0]: return True, None
            # Jenny's Prey and Predator buttons clear each other, so a setup
            # cannot hold both; back out and let another alternative be tried.
            if (B.toggles_on([fact[1]]) & B.toggles_off(self.setup_cor)
                    or B.toggles_off([fact[1]]) & B.toggles_on(self.setup_cor)):
                return False, None
            fresh = fact[1] not in self.setup_cor
            self.setup_cor[fact[1]] = True
            # Some rungs are padlocked until the rest of the roster is somewhere:
            # Cassidy's Together needs every other girl at her top rung. Listing
            # it without them is a setup the player cannot actually enter.
            gate = B.RUNG_GATE.get(fact[1]) if fresh else None
            if gate and consumer and consumer in self.visits and fact not in stack:
                if not self.expand(consumer, [{"kind": "cond", "text": gate}],
                                   depth + 1, stack | {fact}):
                    return False, None
            return True, None
        if k == "world":
            self.setup_world = max(self.setup_world, fact[1]); return True, None
        if k == "option":
            self.setup_opt.add(fact[1]); return True, None
        if k == "stat":
            need, who = self.stats.get(fact[1], (0, frozenset()))
            # keep every consumer: the earliest one sets the deadline
            self.stats[fact[1]] = (max(need, fact[2]),
                                   who | ({consumer} if consumer else frozenset()))
            return True, None
        if k == "flag" and fact[1] in DEFAULT_TRUE:
            return True, None          # already true when the loop starts
        if fact in self.memo:
            v = self.memo[fact]
            if v is FREE: return True, None
            return (v is not None), v
        if depth > MAXDEPTH or fact in stack:
            return False, None

        # Cheapest of all: something the setup itself hands you every run.
        for site in producers(fact, self.banned):
            fs = setup_grant(site)
            if not fs: continue
            s = self.snap()
            if all(self.resolve(f, depth + 1, stack | {fact}, consumer)[0]
                   for f in fs):
                self.memo[fact] = FREE
                self.granted.add(fact)
                return True, None
            self.restore(s)

        cands = sorted((s for s in producers(fact, self.banned)
                        if candidate_dvs(s["owner"])), key=site_cost)
        for site in cands[:3]:
            s = self.snap()
            v = self.add_visit(site)
            self.site_of[v.key] = site_id(site)
            v.gives.append(describe(fact))
            v.kinds.append(k)
            v.facts.append(fact)
            self.memo[fact] = v.key
            if (self.expand(v.key, site["guards"], depth + 1, stack | {fact})
                    and self.fix_session(v.key, depth + 1, stack | {fact})):
                return True, v.key
            self.restore(s)
        self.unresolved.append((describe(fact), fact))
        self.memo[fact] = None
        return False, None

    # ---------- scheduling ----------

    def schedule(self, target_key):
        # dependencies first, target last
        order, seen = [], set()
        def visit(k, stack=()):
            if k in seen or k in stack: return
            for p in sorted(self.deps.get(k, ())): visit(p, stack + (k,))
            seen.add(k); order.append(k)
        for p in sorted(self.deps.get(target_key, ())): visit(p)
        visit(target_key)
        for k in list(self.visits): visit(k)

        succ = defaultdict(set)
        for k, ps in self.deps.items():
            for p in ps: succ[p].add(k)

        # backward pass: the latest slot each visit may occupy. A producer must
        # land strictly before everything that consumes it, and the target is
        # capped by its own availability.
        latest = {}
        for k in reversed(order):
            dvs = candidate_dvs(self.visits[k].owner)
            hi = max(dvs) if dvs else LAST_DV
            for s in succ.get(k, ()):
                # a consumer that happens in an earlier loop imposes no
                # ordering on this run
                if s in self.prior: continue
                if s in latest: hi = min(hi, latest[s] - 1)
            latest[k] = hi

        # (scene, slot) pairs already spoken for. Costing nothing lets an
        # automatic event share a sitting with whatever the player then goes and
        # does, but it does not let one scene be played twice over: LinaC3Invite
        # is free and offers five wing-girls, and you still pick exactly one.
        played = set()
        # A visit that tests a run-scoped affection gate wants to sit as late as
        # it can, not as early: the stat is read the moment the scene starts, so
        # every sitting before it is a sitting that can bank the affection and
        # every sitting after it is wasted. Alex's Forest Handjob is playable at
        # Saturday Noon, Saturday Afternoon, Sunday Noon and Sunday Afternoon,
        # and wants 4 of her Love; taking the earliest left seven slots to find
        # it in and the plan came up two short. Everything else still takes the
        # earliest sitting that fits, which is what leaves room after it.
        late = {k for var, (_, cons) in self.stats.items()
                if stat_scope(var) == "run" for k in cons}
        placed, used, dead = {}, set(), set()
        for k in order:
            if k in self.prior: continue
            v = self.visits[k]
            lo, blocked = 1, False
            for p in self.deps.get(k, ()):
                if p in self.prior: continue          # satisfied in an earlier loop
                # A prerequisite that spends no sitting is over before the slot's
                # map is even drawn -- the automatic event fires at the top of it,
                # the Explore trip hands it straight back -- so what it produces
                # is in hand for a scene played in that same slot.
                if p in placed:
                    lo = max(lo, placed[p] + (0 if self.cost_of.get(p, 1) <= 0 else 1))
                else: blocked = True                  # prerequisite never scheduled
            window = [d for d in candidate_dvs(v.owner) if lo <= d <= latest[k]]
            if k in late: window.reverse()
            if blocked or not window:
                dead.add(k)
                if self.failed is None: self.failed = k
                continue
            # You get one location per timeslot. Falling back to an occupied
            # slot produces an itinerary that cannot be played; let it fail so
            # the demote-to-an-earlier-loop machinery gets a chance instead.
            # An automatic event is the exception: it costs nothing, so it can
            # share a sitting with whatever the player goes and does after it.
            fit = None
            for d in window:
                if (v.owner, d) in played: continue
                cost = visit_cost(v.owner, d, v.choices,
                                  set(self.setup_cor), self.banned_cor)
                take = slots_taken(cost, d, used)
                if take is None: continue
                fit = (d, cost, take); break
            if fit is None:
                dead.add(k)
                if self.failed is None: self.failed = k
                continue
            placed[k], self.cost_of[k] = fit[0], fit[1]
            used.update(fit[2])
            played.add((v.owner, fit[0]))
        self.dead = dead
        return placed, order

    def used_slots(self, placed):
        """Sittings this plan has actually spent -- automatic events spend none,
        and the two scenes that advance time spend the one after them too."""
        used = set()
        for k, dv in placed.items():
            for i in range(self.cost_of.get(k, 1)): used.add(dv + i)
        return used

    def schedule_all(self, target_key):
        """Fit everything into one run; anything that cannot fit but only sets
        persistent tempFlags gets demoted to a previous loop."""
        succ = defaultdict(set)
        for k, ps in self.deps.items():
            for p in ps: succ[p].add(k)

        for _ in range(14):
            self.failed = None
            placed, order = self.schedule(target_key)
            bad = [k for k in order
                   if k not in placed and k not in self.prior and k != target_key]
            if not bad and target_key in placed:
                break
            demote = [k for k in bad if self.visits[k].persistent()]
            if not demote:
                # Nothing failing is itself persistent, so relieve the squeeze
                # by moving a persistent *consumer* of the blockage into an
                # earlier loop -- tempFlags carry over, so that is legal.
                pressure = set()
                for b in bad or [target_key]:
                    stack = [b]
                    while stack:
                        x = stack.pop()
                        for s in succ.get(x, ()):
                            if s not in pressure:
                                pressure.add(s); stack.append(s)
                cand = [k for k in sorted(pressure)
                        if k != target_key and k not in self.prior
                        and self.visits[k].persistent()]
                cand.sort(key=lambda k: (len(candidate_dvs(self.visits[k].owner)), k))
                demote = cand[:1]
            if not demote:
                break
            self.prior.update(demote)

        # an earlier-loop visit needs its own prerequisites in that same loop
        prior_all, stack = set(), list(self.prior)
        while stack:
            k = stack.pop()
            if k in prior_all: continue
            prior_all.add(k)
            stack.extend(sorted(self.deps.get(k, ())))
        prior_order, seen = [], set()
        def walk(k):
            if k in seen or k not in prior_all: return
            seen.add(k)
            for p in sorted(self.deps.get(k, ())): walk(p)
            prior_order.append(k)
        for k in sorted(prior_all): walk(k)
        # Earlier-loop visits still have to run in order. When one cannot fit
        # after its prerequisite, spill into a further-back loop.
        prior_slots, used, played, loop_of = {}, set(), set(), {}
        loop = 0
        for k in prior_order:
            lo = 1
            owner, picks = self.visits[k].owner, self.visits[k].choices
            for p in self.deps.get(k, ()):
                if p in prior_slots and loop_of[p] == loop:
                    lo = max(lo, prior_slots[p]
                                 + (0 if self.cost_of.get(p, 1) <= 0 else 1))
            cost_at = lambda d: visit_cost(owner, d, picks,
                                           set(self.setup_cor), self.banned_cor)
            def open_slots(dvs):
                return [(d, cost_at(d)) for d in dvs
                        if (owner, d) not in played
                        and slots_taken(cost_at(d), d, used) is not None]
            fits = open_slots([d for d in candidate_dvs(owner) if d >= lo])
            if not fits:
                loop += 1; used = set(); played = set()
                fits = [(d, cost_at(d)) for d in candidate_dvs(owner)]
            if fits:
                d, c = fits[0]
                prior_slots[k] = d; self.cost_of[k] = c; loop_of[k] = loop
                used.update(slots_taken(c, d, used) or [])
                played.add((owner, d))
        self.prior_loop = loop_of
        self.prior_loops = loop + 1
        return placed, prior_slots

    def prune(self, placed, target_key):
        """Drop in-run visits nothing in this run actually consumes."""
        keep, stack = set(), [target_key]
        while stack:
            k = stack.pop()
            if k in keep: continue
            keep.add(k)
            for p in self.deps.get(k, ()):
                if p in placed: stack.append(p)
        return {k: v for k, v in placed.items() if k in keep}

# ---------- can we promise the game will offer this scene? ----------
# The planner resolves a *target's* prerequisites by going and producing them.
# Top-up scenes get no such treatment: they are opportunistic filler, dropped
# into spare slots, and nothing downstream ever revisits them. So a filler is
# only worth listing if the run the plan already describes reaches it — which
# means checking the route in, not just the scene's own guards. Two ways that
# bites: a scene behind a story chain nobody scheduled (PostTubLina needs the
# hot tub and Lina's hypnosis), and a scene the setup itself locks out (the
# Twister map button carries `not cassidyCorruption4On`, and Cassidy·Together
# switches Corruption 4 on).

A_COR   = re.compile(r'^(\w+?Corruption\w*?)On$')
A_TEMP  = re.compile(r'^tempFlags\[\s*"([\w-]+)"\s*\]\s*(?:(?:>=|==|>|<|<=)\s*\d+)?$')
A_ITEM  = re.compile(r'^"([^"]+)"\s+in\s+commonEvents$')
A_BURNT = re.compile(r'^(\w+)Burnt$')
A_WORLD = re.compile(r'^worldCorruption\s*(>=|>|==)\s*(\d+)$')
A_FLAG  = re.compile(r'^[A-Za-z]\w*$')

def atom_ok(atom, on, produced, plan, avoid):
    """Is this one condition guaranteed by what the plan already arranges?
    Only shapes we fully recognise can answer yes -- filler has to be certain,
    not merely plausible, so stat thresholds and array counters answer no."""
    a = B.unwrap(atom.strip())
    if not a or a == "(otherwise)": return True
    neg = a.startswith("not ")
    body = B.unwrap(a[4:].strip()) if neg else a

    # `not (A and B)` holds as soon as one conjunct fails, and `not (A or B)`
    # needs both to. The map gates are full of these, and answering "unknown" to
    # all of them throws away most of the affection the planner could bank.
    if neg:
        ands = B.split_top(body, "and")
        if len(ands) > 1:
            # One failing conjunct is enough, so prefer one the run already
            # settles: `not (A and B)` with B a rung the setup never switches on
            # is true before the player does anything, and asking them to steer
            # around A as well would be work the run does not need.
            costly = []
            for x in ands:
                acc = []
                if not atom_ok("not " + x, on, produced, plan, acc): continue
                if not acc: return True
                costly.append(acc)
            if costly: avoid.extend(costly[0]); return True
            return False
        ors = B.split_top(body, "or")
        if len(ors) > 1:
            # All of them, or none: a partial answer leaves "don't do this"
            # notes behind for a condition we could not promise anyway.
            acc = []
            if all(atom_ok("not " + x, on, produced, plan, acc) for x in ors):
                avoid.extend(acc); return True
            return False

    if body in ("True", "False"): return (body == "True") != neg
    if body in ALWAYS_FALSE: return neg      # cleared before any planned run

    def held(has):
        if neg and not has: avoid.append(B.pretty(a))
        return (not has) if neg else has

    m = A_COR.match(body)
    if m: return (m.group(1) not in on) if neg else (m.group(1) in on)

    m = A_TEMP.match(body)
    if m: return held(("branch", m.group(1)) in produced)

    m = A_ITEM.match(body)
    if m: return held(("item", m.group(1)) in produced)

    m = A_BURNT.match(body)
    if m:                       # nobody starts burnt out; just don't do it
        return held(False)

    m = A_WORLD.match(body)
    if m: return not neg and plan.setup_world >= int(m.group(2))

    if body in B.OPTNAME: return (body in plan.setup_opt) != neg

    if A_FLAG.match(body):
        return held(("flag", body) in produced or body in DEFAULT_TRUE)

    return False

def guards_ok(guards, on, produced, plan, avoid):
    hard, groups = B.flatten(guard_conds(guards))
    if not all(atom_ok(a, on, produced, plan, avoid) for a in hard): return False
    return all(any(atom_ok(o, on, produced, plan, avoid) for o in g) for g in groups)

def route_ok(owner, dv, on, produced, plan, avoid):
    """Every hop of the map route into `owner` at slot `dv` must have at least
    one alternative the plan can promise."""
    e = entries(owner)
    if dv in e: _, path = e[dv]
    elif 0 in e: _, path = e[0]
    else: return False
    for i in path:
        edge = EDGES[i]
        alts = B.EDGE_ALTS.get((edge["src"], edge["dst"])) or [edge]
        if not any(guards_ok(a["guards"], on, produced, plan, avoid) for a in alts):
            return False
    return True

RE_DATEVAR = re.compile(r'^dateVar\s*==\s*(\d+)$')

def unmodelled(p, placed, solved=(), playing=()):
    """Conditions the fact model cannot express, and so cannot plan for.

    The vocabulary knows corruption rungs, decision flags, quest items, affection
    and the content options. It does not know running tallies (`alexsex[0] >= 3`),
    scene-local scores (`PuzzleHold >= 4`, `mood >= 10`) or typed answers. Those
    used to fall out of `atom_facts` as an empty fact list, which `site_reqs`
    reads as "nothing to do" -- so a plan would happily claim a scene it had not
    earned. Collect them instead and say so."""
    out = {}
    for k, dv in placed.items():
        v = p.visits[k]
        hard, _ = B.flatten(guard_conds(v.guards) +
                            nav_guards(v.owner, dv, set(p.setup_cor), p.banned_cor))
        for a in hard:
            a = a.strip()
            if not a or a == "(otherwise)" or a.startswith("not "): continue
            fs = atom_facts(a)
            # a score we chose not to chain still needs spelling out
            if fs and not (p.skip_scores and len(fs) == 1 and fs[0][0] == "score"):
                continue
            if B.RE_BURNT.search(a): continue          # already an "avoid" note
            # A counter the step's own session block now solves is answered
            # there, with the picks that get it -- repeating the threshold at
            # the bottom of the page as an unexplained number helps nobody. One
            # it could *not* solve stays here, so nothing goes quiet.
            if k in solved and counter_needs([a], v.owner, playing)[1]: continue
            m = RE_DATEVAR.match(a)
            if m and int(m.group(1)) == dv: continue   # true by where we put it
            if A_FLAG.match(a) and (a in DEFAULT_TRUE or a in PROD_FLAG): continue
            out.setdefault(B.pretty(a), (B.sname(v.owner), score_of(a)))
    return [{"need": t, "scene": s, "score": sc} for t, (s, sc) in sorted(out.items())]

def short_name(var, others):
    """`C3DinnerHailySearchBedroom` next to its rivals is just "Bedroom".

    The counters of a contest are named off one stem, so dropping the stem they
    share leaves the theory each one stands for. Only when what is left still
    reads as a word of its own -- otherwise the raw name is the honest answer."""
    if not others: return var
    pre = _os.path.commonprefix([var] + list(others))
    tail = var[len(pre):]
    return tail if len(tail) > 1 and tail[0].isupper() else var

def score_of(atom):
    """A scene score spelled out: what each point is actually for.

    Two shapes. `PuzzleHold >= 4` is a threshold. The Sunday dinner search is a
    contest -- `Bedroom >= max(Hypnosis, Forest, 1)` -- where the points you do
    *not* want matter as much as the ones you do, so the rival tallies are
    spelled out alongside."""
    atom = atom.strip()
    m, rivals = A_SCORE.match(atom), []
    if m:
        var, value = m.group(1), int(m.group(3))
    else:
        m = A_CONTEST.match(atom)
        if not m: return None
        var = m.group(1)
        terms = [t.strip() for t in m.group(2).split(",") if t.strip()]
        value = max([int(t) for t in terms if t.isdigit()] or [1])
        rivals = [t for t in terms if not t.isdigit()]
    if var not in B.SCORES: return None
    def label(kind, text):
        if kind != "cond": return text
        nice = B.pretty(text)
        if nice != text: return nice
        fs = atom_facts(text)          # a bare flag reads better split up
        return describe(fs[0]) if len(fs) == 1 else nice
    def parts(v):
        return [{"amount": a, "kind": k, "text": label(k, t)}
                for a, k, t in B.SCORE_PARTS.get(v, ())]
    named = [var] + rivals
    nm = {v: short_name(v, [x for x in named if x != v]) for v in named}
    out = {"var": var, "name": nm[var], "value": value, "parts": parts(var),
           "rivals": [{"var": r, "name": nm[r], "parts": parts(r)}
                      for r in rivals if r in B.SCORE_PARTS]}
    # A contest is decided in a menu, and the menu is what the player is looking
    # at. List it: every option, what each one adds, and which of them ends the
    # questioning -- the tallies alone never say how to stop asking.
    m = B.SCORE_MENUS.get(var) if rivals else None
    if m and m["options"]:
        ex = m["exit"]
        # Name every counter the menu feeds, not just the ones in the comparison.
        # `Success >= 4` is checked one branch above this one, so an option that
        # builds it sends the search somewhere else entirely -- listing it as
        # adding nothing is the misreading that hides "Follow your hunch".
        fam = [v for _, v in (p for _, adds in m["options"] for p in adds)
               if not (ex and v == ex["var"])]
        fam = [v for v in dict.fromkeys(named + fam)]
        mnm = {v: short_name(v, [x for x in fam if x != v]) for v in fam}
        def ends(adds):
            return bool(ex) and any(v == ex["var"] and a >= ex["at"] - ex["per"]
                                    for a, v in adds)
        out["menu"] = [{"text": t,
                        "adds": [{"amount": a, "name": mnm[v]} for a, v in adds if v in mnm],
                        "ends": ends(adds)} for t, adds in m["options"]]
        if ex: out["picks"] = max(1, ex["at"] // ex["per"])
    return out

# ---------- hypnosis and the other in-scene counters ----------
# `B.SESSION` has the shape: a counter zeroed at the top of a scene, four menus
# that each take one pick, and a threshold read at the end. There is nothing to
# schedule, so `reach_score` cannot help and the old answer was to list the
# options that add to the counter and leave the player to it. That is not an
# instruction -- it reads as "any four of these ten", the picks are one per menu,
# and in Jenny's garden every pick moves Lina's trance as well as Jenny's, so a
# list of one counter's positives actively hides the other. 256 combinations is
# nothing to enumerate, so solve it and name the four picks.

def sessions_for(label, var, playing=()):
    """Which session built `var` by the time `label` reads it.

    `linahypbj` is reached from both of Jenny's sessions, so the label alone
    does not say. The run only plays one of them, so ask the plan."""
    cands = [s for s in B.SESSION_AT.get(label, ())
             if var in B.SESSION[s]["vars"]]
    if len(cands) > 1:
        near = [s for s in cands if s in playing]
        if len(near) == 1: return near[0]
    return cands[0] if len(cands) == 1 else None

# `not (alexHorny < 2)` is the same requirement wearing an `elif` chain's
# negation (landmine 30), and it is the shape the Horny build-ups arrive in.
# Left as a negative it reads on the row as "must not already have Alex's Horny
# below 2" -- a double negative about a counter the scene itself zeroes and the
# player has to build in front of them.
A_NCOUNT = re.compile(r'^not\s*\(?\s*(\w+)\s*(<|<=)\s*(\d+)\s*\)?$')

def _threshold(atom):
    a = B.unwrap(atom.strip())
    m = A_SCORE.match(a)
    if m: return m.group(1), int(m.group(3))
    m = A_NCOUNT.match(a)
    if m: return m.group(1), int(m.group(3)) + (0 if m.group(2) == "<" else 1)
    return None, None

def counter_needs(atoms, label, playing=()):
    """-> (session, {var: threshold}, atoms used) for the counters `atoms` gate on."""
    sess, needs, used = None, {}, []
    for a in atoms:
        var, need = _threshold(a)
        if var is None: continue
        s = sessions_for(label, var, playing)
        if s is None or (sess and s != sess): continue
        sess = s
        needs[var] = max(needs.get(var, 0), need)
        used.append(a)
    return (sess, needs, used) if needs else (None, {}, [])

def site_counters(site, playing=()):
    hard, _ = B.flatten(guard_conds(site["guards"]))
    return counter_needs(hard, site["owner"], playing)[:2]

def cond_text(cond):
    """A multiplier's condition in words. `B.pretty` knows rungs and quests but
    leaves a bare flag as the variable name, and `HypnosisLesson` is the one the
    player most needs to recognise -- it is a scene they have to go and play."""
    return re.sub(r'\b[A-Za-z]\w*\b',
                  lambda m: describe(("flag", m.group(0)))
                            if m.group(0) in PROD_FLAG else m.group(0),
                  B.pretty(cond))

def _apply(sess, combo, menus, mods):
    """Run the session's arithmetic exactly: the halving is not truncated and
    the lesson's boost is, so `int(x*.5*1.5)` and `int(int(x*.5)*1.5)` differ."""
    tot = {v: 0 for v in B.SESSION[sess]["vars"]}
    for mi, oi in enumerate(combo):
        for v, n in menus[mi][oi]["adds"].items(): tot[v] = tot.get(v, 0) + n
    for d in mods:
        x = tot.get(d["var"], 0) * d["factor"]
        tot[d["var"]] = int(x) if d["int"] else x
    return tot

def session_paths(sess, menus, mods):
    total = 1
    for m in menus: total *= len(m)
    if total > 200_000: return                # nothing in 0.62d comes close
    for combo in itertools.product(*(range(len(m)) for m in menus)):
        yield combo, _apply(sess, combo, menus, mods)

# lives beside `flatten` now, because the rung extractor needs it too
push_not = B.push_not

def mod_groups(sess):
    """The session's multipliers, one entry per `if` block, in source order."""
    out = []
    for d in B.SESSION[sess]["mods"]:
        if d["group"] not in [g[0] for g in out]:
            out.append((d["group"], d["cond"], d["factor"] >= 1))
    return out

def _reach(sess, needs, state):
    live = [d for d in B.SESSION[sess]["mods"] if state[d["group"]]]
    return any(all(t.get(v, 0) >= n for v, n in needs.items())
               for _, t in session_paths(sess, B.SESSION[sess]["menus"], live))

_FIX = {}

def session_fix(sess, needs):
    """Which multipliers the run has to arrange for these thresholds to exist.

    Jenny's trance tops out at 8 on the picks alone and her deep-trance commands
    want 10, so those runs are not asking for better picks -- they are asking for
    Cassidy's hypnosis lesson, which scales the whole session by half again. That
    is an ordinary requirement with an ordinary producer, and left unchased it is
    the difference between a plan that works and a threshold that cannot be met
    however the four menus go. -> [(condition, wanted)], or None if no
    arrangement of them reaches the thresholds at all."""
    key = (sess, tuple(sorted(needs.items())))
    if key in _FIX: return _FIX[key]
    groups = mod_groups(sess)
    # what the run gets without arranging anything: no boost, every cut
    base = {g: not boost for g, _, boost in groups}
    fix = None
    if _reach(sess, needs, base): fix = []
    else:
        for k in range(1, len(groups) + 1):
            for pick in itertools.combinations(range(len(groups)), k):
                st = dict(base)
                for i in pick: st[groups[i][0]] = not st[groups[i][0]]
                if _reach(sess, needs, st):
                    fix = [(groups[i][1], st[groups[i][0]]) for i in pick]
                    break
            if fix is not None: break
    _FIX[key] = fix
    return fix

_JOINT = {}

def joint_ok(sess, needs):
    """Can one sitting of this session meet all of these thresholds at once?

    Judged at the session's very best -- every multiplier counted, none of the
    cuts -- because this decides whether to split one visit into two, and a
    split forced on a guess would cost the player a slot they did not owe.
    Jenny's `New Mail: Bathing` is the case that needs it: it wants her trance
    at 10 *and* Lina's at 10, and no pick path gets both there, so the two
    halves are earned in separate sittings and the tempFlags remember."""
    key = (sess, tuple(sorted(needs.items())))
    if key not in _JOINT:
        S = B.SESSION[sess]
        best = [d for d in S["mods"] if d["factor"] >= 1]
        _JOINT[key] = any(all(t.get(v, 0) >= n for v, n in needs.items())
                          for _, t in session_paths(sess, S["menus"], best))
    return _JOINT[key]

def solve_session(sess, needs, on, produced, plan):
    """The four picks that put every counter in range, and what they add up to."""
    S = B.SESSION[sess]
    def sure(cond):
        return guards_ok([{"kind": "cond", "text": cond}], on, produced, plan, [])
    menus = [[o for o in m if not o["cond"] or sure(o["cond"])] for m in S["menus"]]
    if any(not m for m in menus): return None
    # A boost counts only when the run guarantees it; a cut counts unless the run
    # rules it out. Both err the same way -- towards the harder session -- so a
    # path this reports is one the player can actually hit. The cut has to be
    # asked about through `push_not`: `not (not Prey and not Predator)` resolves
    # to nothing at all, so a run that does switch Prey on still reads as halved.
    mods = []
    for d in S["mods"]:
        d = dict(d, applies=sure(d["cond"]) if d["factor"] >= 1
                            else not sure(push_not(d["cond"])))
        mods.append(d)
    live = [d for d in mods if d["applies"]]
    best = None
    for combo, tot in session_paths(sess, menus, live):
        if any(tot.get(v, 0) < n for v, n in needs.items()): continue
        # Nothing here is random, so slack on the threshold buys nothing. What
        # does pay is the other girl's counter: the same four picks decide both,
        # and every one of the session's commands has its own threshold, so the
        # path worth naming is the one that leaves the most on the table.
        key = (-sum(tot.values()), -min(tot[v] - n for v, n in needs.items()), combo)
        if best is None or key < best[0]: best = (key, combo, tot)
    def num(x): return int(x) if float(x).is_integer() else round(float(x), 1)
    def named(adds):
        return [{"name": B.counter_name(sess, v), "amount": n}
                for v, n in sorted(adds.items()) if n]
    # One `if` can scale both counters; report the block, not each line of it.
    groups = {}
    for d in mods:
        g = groups.setdefault(d["group"], dict(d, names=[]))
        g["names"].append(B.counter_name(sess, d["var"]))
    out = {"session": sess, "scene": B.sname(sess),
           "needs": [{"name": B.counter_name(sess, v), "need": n}
                     for v, n in sorted(needs.items())],
           # A cut is worth reporting either way round: the run that escapes the
           # halving is only switching Jenny·Prey on because of it, and the setup
           # card cannot say so.
           "mods": [{"text": cond_text(d["cond"]), "factor": d["factor"],
                     "escape": cond_text(push_not(d["cond"])),
                     "names": dedup(d["names"]), "applies": d["applies"]}
                    for _, d in sorted(groups.items())],
           "menus": len(menus)}
    if best is None:
        out["ok"] = False
        return out
    _, combo, tot = best
    out["ok"] = True
    out["picks"] = [{"text": menus[i][oi]["text"], "adds": named(menus[i][oi]["adds"])}
                    for i, oi in enumerate(combo)]
    out["totals"] = [{"name": B.counter_name(sess, v), "value": num(tot[v])}
                     for v in sorted(tot)]
    return out

def trance_for(p, k, dv, on, produced, playing):
    """-> (session block, the conditions it answers) for one step.

    The conditions come back so the row can stop repeating them: a solved path
    that ends at "Alex's Horny 2" has already said everything "must not already
    have Alex's Horny below 2" was trying to."""
    v = p.visits[k]
    hard, _ = B.flatten(guard_conds(v.guards) +
                        nav_guards(v.owner, dv, set(p.setup_cor), p.banned_cor))
    sess, needs, used = counter_needs(hard, v.owner, playing)
    if not needs: return None, ()
    tr = solve_session(sess, needs, on, produced, p)
    covers = {B.pretty(a) for a in used} if tr and tr.get("ok") else set()
    return tr, covers

def cascade_conflicts(p, placed, prior=()):
    """Steps the run's own setup cannot deliver, either way round.

    A scene guarded `not xCorruption4On` cannot be played in a run that switches
    on xCorruption5, because the menu button for the higher rung switches every
    rung below it on as well. The mirror matters just as much: a scene guarded
    `xCorruption4On` will not fire in a run whose setup never switches it on --
    the player follows the toggle list exactly, and anything not listed is off.

    Read through `cor_clauses`, because a rung negation is usually not a bare
    atom: `AlexShareBed` opens `if hailyCorruption2On and not (…): jump` and the
    old whole-atom match saw nothing at all, so four plans switched Haily's rung
    on, sent the player to the scene that replaces this one, and reported no
    conflict. Report only when *every* alternative is contradicted -- one
    holding a tempFlag or a Love threshold is unknown, not false, and an
    unknown must suppress the line rather than guess.

    `prior` is covered too: the setup card is one card for the whole plan, so a
    demoted visit contradicting it is exactly as broken as a placed one."""
    on, out = B.toggles_on(p.setup_cor), []
    for k, dv in list(placed.items()) + list(dict(prior).items()):
        v = p.visits[k]
        hard, _ = B.flatten(guard_conds(v.guards) +
                            nav_guards(v.owner, dv, set(p.setup_cor), p.banned_cor))
        for a in hard:
            alts = B.cor_clauses(B.unwrap(a.strip()))
            if not alts or any(B.clause_state(x, on) < 2 for x in alts): continue
            # every way out is dead; name the one that needed the least
            best = min(alts, key=lambda x: (len(x[0]) + len(x[1]) + x[2],
                                            sorted(x[0]), sorted(x[1])))
            want = "off" if (best[1] & on) else "on"
            var = sorted(best[1] & on)[0] if want == "off" else sorted(best[0] - on)[0]
            ch, nm = B.ladder_name(var)
            if not ch: continue
            out.append({"scene": B.sname(v.owner), "slot": DVLABEL.get(dv, "?"),
                        "char": ch, "level": nm, "var": var, "want": want,
                        # which producing site to avoid on a retry; stripped
                        # before the plan is written out
                        "_site": p.site_of.get(k)})
    return out

def plan_facts(plan, placed):
    """Everything the run described so far actually produces. Earlier-loop
    visits count too, but only for branch flags -- those are the one thing a
    reset does not wipe."""
    out = set(plan.granted)
    for k in placed:
        out |= set(plan.visits[k].facts)
    for k in plan.prior:
        if k in plan.visits:
            out |= {f for f in plan.visits[k].facts if f[0] == "branch"}
    return out

# ---------- love/mood top-up ----------

def stat_gain(e, choices):
    """What this bump is worth if we play its scene taking `choices`.

    Signed: `-=` is a loss, and a route that costs affection is not a boost.
    A plain `=` is a reset (all but two of them assign 0), never a gain.

    Only the menu picks are checked here. Whether the conditions around it hold
    is a question about the whole run, so the callers put it to `guards_ok`; a
    blanket "anything behind a condition is worth nothing" throws away most of
    the affection in the game, now that a scene's fall-through guards are
    recorded too."""
    picks = [B.clean(g["text"]) for g in e["guards"] if g["kind"] == "choice"]
    if not all(p in choices for p in picks): return 0
    if e["op"] == "-=": return -e["amount"]
    if e["op"] == "=":  return 0
    return e["amount"]

def route_gain(var, owner, choices, ok=None):
    """Everything `var` gains in one scene along the route `choices`.

    A single bump is not the route's worth: `AlexForest1` pays +1 for the choice
    and another +1 inside it, and once the visit is scheduled `stat_topup`
    counts both. Rank candidates on the same total it will later credit them
    with, or the biggest boost is not the one that gets picked.

    `ok` is the run's guard test. It is not optional in practice -- the bumps
    around a choice are usually behind conditions of their own (`if alexLove >= 4`,
    `if tempFlags["HailyText312"] >= 3`), and counting those unconditionally
    advertises affection the run will not actually collect."""
    return sum(stat_gain(e, choices) for e in PROD_STAT.get(var, ())
               if e["owner"] == owner and (ok is None or ok(e)))

TIEBREAK_STATS = ("mood",)

def tally_vars(skip=None):
    return sorted(v for v in PROD_STAT
                  if (v.endswith("Love") or v in TIEBREAK_STATS) and v != skip)

def combo_gain(owner, choices, skip=None, ok=None):
    """Total Love + Mood along one route -- the tiebreak between equal boosts.

    Both are per-run tallies cleared at the reset, so they are comparable; when
    two routes offer the same amount of the Love we are actually short of, the
    one that leaves the rest of the weekend better off wins."""
    return sum(route_gain(v, owner, choices, ok) for v in tally_vars(skip))

def side_gains(owner, choices, skip, ok=None):
    """The rest of what a top-up route pays, so the step says why it was chosen."""
    out = []
    for v in tally_vars(skip):
        g = route_gain(v, owner, choices, ok)
        if g > 0: out.append("+%d %s" % (g, B.statname(v)))
    return out

def stat_scope(var):
    """Horny is zeroed at the top of every timeslot by `dayhandler`, so it can
    only be raised inside the slot that tests it. linaNerve is not a per-run
    stat at all -- it counts the Nerve-tagged unlocks collected across runs."""
    if var.endswith("Horny"): return "slot"
    if var == "linaNerve": return "meta"
    return "run"

def gate_deadline(placed, consumers):
    dls = [placed[c] for c in consumers if c in placed]
    return min(dls) if dls else LAST_DV

def gate_have(plan, placed, var, deadline, on, produced):
    """How much of `var` the run banks before the scene that tests it."""
    have = 0
    for k, dv in placed.items():
        if dv >= deadline: continue
        v = plan.visits[k]
        for e in PROD_STAT.get(var, ()):
            if e["owner"] != v.owner: continue
            g = stat_gain(e, v.choices)
            if g and guards_ok(e["guards"], on, produced, plan, []): have += g
    return have

def fact_cost(f, produced, on):
    """What one more requirement is worth to a `chase_gate` candidate.

    A corruption rung, the world level and the content options are free: they
    are set once at the end-of-loop menu and cost the run no timeslot, so a
    scene behind one of them is no harder to reach than an ungated one.
    Anything else is a scene the run has to go and play.

    It is tempting to charge for a rung the setup does not already have -- it
    rewrites the whole weekend, and when the target needs Alex low, every Alex
    scene behind `alexCorruption2On` is a candidate that gets expanded,
    scheduled, found contradictory and rolled back. Do not: it was tried, and
    reordering the list that way fixed eight gates and broke eight others,
    because a single rung-gated +4 is often worth more than the three +1s that
    then crowd it out. The wasted tries are a budget problem, not a ranking
    problem -- `CHASE_TRIES` is the dial that fixes them."""
    if f in produced or f[0] in ("cor", "world", "option"): return 0
    return 1

# How many candidates a single chase tries before giving up on the gate, and how
# many rounds of chasing a run gets. Each try expands and schedules the whole
# run, so these are the expensive dials -- but a chase stops at its first
# success, so a run whose gates are easy never pays for the headroom. The
# original 3 and 3 left 34 run-scoped gates short; a cluster of contradictory
# rung-gated candidates could eat a whole chase, and one scene per round is not
# enough for a gate wanting 5 when most scenes pay +1. 40 and 12 costs about
# five seconds over the whole build and leaves 21.
CHASE_TRIES = 40
CHASE_ROUNDS = 12
# Which of a candidate's six ranking terms to weigh first. Split out so a
# permutation can be measured on the whole build rather than argued about, which
# is the only way to tell (landmine 60). Weighing "does it spend a sitting"
# straight after the chain cost -- ahead of the size of the boost -- is what this
# order does, and it is worth it: the same 14 gates end up short either way, but
# the plans spend 95 fewer sittings, because three automatic +1s that fire on
# their own beat one +2 that eats a slot.
CHASE_ORDER = (0, 3, 1, 2, 4, 5)

def chase_gate(p, target_key, placed, prior, var, consumers):
    """Schedule one more scene that raises `var`, prerequisites and all.

    `stat_topup` can only take scenes the run already reaches, so a gate whose
    remaining sources sit behind a quest item -- Alex's second breast expansion
    needs Haily's milk, or the hypnosis event -- stays short forever. Here the
    producer is added as a real visit and expanded like any other requirement.

    One candidate at a time, each kept only if the whole plan still works
    afterwards: the target still schedules, the new scene actually got a slot,
    and neither the contradictions nor the loose ends grew. Anything else is
    rolled back -- an unmet gate is a smaller problem than a broken itinerary.
    """
    on, produced = B.toggles_on(p.setup_cor), plan_facts(p, placed)
    deadline = gate_deadline(placed, consumers)
    planned = {p.visits[k].owner for k in list(placed) + list(prior)}
    used = p.used_slots(placed)
    held = lambda ev: guards_ok(ev["guards"], on, produced, p, [])
    # The run's *other* unmet gates, so a scene that closes two at once beats one
    # that pays the same into a single tally. Plenty of scenes pay several girls:
    # "Let's wrestle" is +1 Alex and +1 Haily, Saturday Breakfast is +1 Alex,
    # +1 Lisa and +1 Mood.
    short = {}
    for v2, (need2, cons2) in p.stats.items():
        if v2 == var or stat_scope(v2) != "run": continue
        dl2 = gate_deadline(placed, cons2)
        gap = need2 - gate_have(p, placed, v2, dl2, on, produced)
        if gap > 0: short[v2] = (gap, dl2)

    cands = []
    for e in PROD_STAT.get(var, ()):
        if e["owner"] in planned: continue
        picks = [B.clean(g["text"]) for g in e["guards"] if g["kind"] == "choice"]
        amt = route_gain(var, e["owner"], picks, held)
        if amt <= 0: continue
        # an automatic event costs no sitting, so a slot already spent is still
        # open to it
        slots = [d for d in candidate_dvs(e["owner"]) if d < deadline
                 and slots_taken(visit_cost(e["owner"], d, picks, set(p.setup_cor),
                                            p.banned_cor), d, used) is not None]
        if not slots: continue
        # cost it by everything it drags in, the map gates included -- the
        # scene's own guards alone make a badly-gated scene look free
        want = set(site_goals(e["guards"]))
        for c in nav_guards(e["owner"], slots[0], set(p.setup_cor), p.banned_cor):
            want |= set(atom_facts(c))
        cost = sum(fact_cost(f, produced, on) for f in want)
        # What else this one scene settles: the part of every other short gate it
        # pays, capped at the gap, and only where it lands before that gate's own
        # deadline.
        also = sum(min(gap, route_gain(v2, e["owner"], picks, held))
                   for v2, (gap, dl2) in sorted(short.items()) if slots[0] < dl2)
        # A scene that spends no sitting is close to free: the automatic events
        # fire at the top of the slot and hand the map back, so taking one leaves
        # the slot available for another gain.
        no_slot = visit_cost(e["owner"], slots[0], picks,
                             set(p.setup_cor), p.banned_cor) <= 0
        # cheapest chain first -- a boost that breaks the run is no boost -- then
        # the biggest gain, then what else it settles, then whether it costs a
        # sitting, ties on the rest of the route's Love + Mood
        cands.append((cost, -amt, -also, 0 if no_slot else 1,
                      -combo_gain(e["owner"], picks, var, held),
                      e["owner"], e, amt))
    # (chain cost, gain, what else it settles, does it spend a sitting,
    #  the rest of the route's Love + Mood, scene name)
    cands.sort(key=lambda x: tuple(x[i] for i in CHASE_ORDER))

    base_conf = len(cascade_conflicts(p, placed))
    for *_, e, amt in cands[:CHASE_TRIES]:
        # A prerequisite usually has several producers -- Haily's milk comes from
        # three different package scenes -- and the cheapest may want a slot this
        # run has already spent. Ban the one that jammed and try the same
        # candidate again rather than giving up on it.
        keep_banned = set(p.banned)
        for _try in range(3):
            snap, was, nun = p.snap(), set(p.prior), len(p.unresolved)
            before_keys = set(p.visits)
            v = p.add_visit(e)
            v.gives.append("+%d %s" % (amt, B.statname(var)))
            # the rest of what this route pays, same as a spare-slot top-up
            # reports -- a scene chased for Alex's Love that also pleases Haily
            # should say so on the row
            v.gives.extend(side_gains(
                e["owner"], [B.clean(g["text"]) for g in e["guards"]
                             if g["kind"] == "choice"], var, held))
            if p.expand(v.key, e["guards"], 2, set()):
                for c in consumers:
                    if c in p.visits and c != v.key: p.deps[c].add(v.key)
                for _ in range(2):      # schedule, fold the map gates in, again
                    p.prior = set(x for x in p.prior if x in p.visits)
                    got, gotp = p.schedule_all(target_key)
                    for k, dv in list(got.items()) + list(gotp.items()):
                        conds = nav_guards(p.visits[k].owner, dv, set(p.setup_cor),
                                           p.banned_cor)
                        if conds:
                            p.expand(k, [{"kind": "cond", "text": c} for c in conds],
                                     2, set())
                p.prior = set(x for x in p.prior if x in p.visits)
                got, gotp = p.schedule_all(target_key)
                if (target_key in got and v.key in got
                        and len(p.unresolved) <= nun
                        and len(cascade_conflicts(p, got)) <= base_conf):
                    return got, gotp
            # The blockage is one of the prerequisites this candidate just
            # dragged in, competing for a slot the run had already spent -- not
            # the scene that reports the failure. Ban the tightest newcomer.
            fresh = [k for k in set(p.visits) - before_keys
                     if k != v.key and p.site_of.get(k)
                     and p.site_of[k] not in p.banned]
            fresh.sort(key=lambda k: (len(candidate_dvs(p.visits[k].owner)), k))
            jammed = p.site_of[fresh[0]] if fresh else None
            p.restore(snap); p.prior = was
            if not jammed: break
            p.banned.add(jammed)
        p.banned = keep_banned
    return None

def stat_topup(plan, placed):
    """Fill spare timeslots with scenes that raise a required stat.

    Affection is checked when the gated scene begins, so only gains from
    *strictly earlier* slots count. Anything scheduled at or after the deadline
    is irrelevant no matter how large."""
    summary, extra_steps = [], []
    used = plan.used_slots(placed)
    on, produced = B.toggles_on(plan.setup_cor), plan_facts(plan, placed)

    for var, (need, consumers) in sorted(plan.stats.items()):
        # the earliest scene that tests this stat sets the deadline
        dls = [placed[c] for c in consumers if c in placed]
        deadline = min(dls) if dls else 22
        scope = stat_scope(var)

        if scope == "meta":
            summary.append({"var": B.statname(var), "need": need, "scope": "meta",
                            "met": None, "have": 0, "from": [], "slots": [],
                            "by": DVLABEL.get(deadline, "the end"), "byDv": deadline,
                            "note": "Counts the Nerve-tagged unlocks you have collected "
                                    "across all your runs, not anything in this one."})
            continue

        if scope == "slot":
            # must be raised inside the gated scene's own timeslot
            here = []
            for c in consumers:
                if c not in placed: continue
                owner = plan.visits[c].owner
                for e in PROD_STAT.get(var, ()):
                    if e["owner"] != owner: continue
                    if any(g["kind"] == "cond" for g in e["guards"]): continue
                    picks = [B.clean(g["text"]) for g in e["guards"] if g["kind"] == "choice"]
                    if picks: here.append("+%d for “%s”" % (e["amount"], " → ".join(picks)))
            summary.append({"var": B.statname(var), "need": need, "scope": "slot",
                            "met": None, "have": 0, "from": sorted(set(here)), "slots": [],
                            "by": DVLABEL.get(deadline, "the end"), "byDv": deadline,
                            "note": "Resets at the start of every timeslot, so it has to be "
                                    "built up inside this scene — take the flirtier options first."})
            continue

        have, why = 0, []
        for k, dv in placed.items():
            if dv >= deadline: continue          # too late to help
            v = plan.visits[k]
            for e in PROD_STAT.get(var, ()):
                if e["owner"] != v.owner: continue
                g = stat_gain(e, v.choices)
                if g and guards_ok(e["guards"], on, produced, plan, []):
                    have += g
                    if g > 0:
                        why.append("%s (%s)" % (B.sname(v.owner), DVLABEL.get(dv, dv)))

        # candidates: scenes not already in the plan, playable before the deadline.
        # Biggest boost first, ties settled by what else the route is worth.
        planned_owners = {plan.visits[k].owner for k in placed}
        held = lambda ev: guards_ok(ev["guards"], on, produced, plan, [])
        cands = []
        for e in PROD_STAT.get(var, ()):
            if e["owner"] in planned_owners: continue
            picks = [B.clean(g["text"]) for g in e["guards"] if g["kind"] == "choice"]
            amt = route_gain(var, e["owner"], picks, held)
            if amt <= 0: continue
            dvs = [d for d in candidate_dvs(e["owner"]) if d < deadline]
            if not dvs: continue
            cands.append((amt, combo_gain(e["owner"], picks, var, held),
                          B.sname(e["owner"]), e, dvs, picks))
        cands.sort(key=lambda x: (-x[0], -x[1], len(x[4]), x[2]))

        chosen, seen_scene = [], set()
        for amt, bonus, nm, e, dvs, picks in cands:
            if have >= need: break
            if e["owner"] in seen_scene: continue
            # an automatic event still fits a sitting the run has already spent
            free = [(d, visit_cost(e["owner"], d, picks, set(plan.setup_cor),
                                   plan.banned_cor)) for d in dvs]
            free = [(d, c) for d, c in free if slots_taken(c, d, used) is not None]
            # the first slot whose route into the scene the plan can promise
            slot, cost, avoid = None, 1, []
            for d, c in free:
                warn = []
                # the way in, and the menu option itself: `"Haily's party trick"
                # if hailyCorruption4On` is only on the menu some runs
                if (route_ok(e["owner"], d, on, produced, plan, warn)
                        and guards_ok(e["guards"], on, produced, plan, warn)):
                    slot, cost, avoid = d, c, warn; break
            if slot is None: continue
            # re-tot the route with the warnings captured, so a bump we are
            # counting on brings its own "don't do this first" into `avoid`
            noted = lambda ev: guards_ok(ev["guards"], on, produced, plan, avoid)
            gain = route_gain(var, e["owner"], picks, noted)
            seen_scene.add(e["owner"]); have += gain
            used.update(slots_taken(cost, slot, used) or [])
            chosen.append(slot)
            extra_steps.append({
                "dv": slot, "slot": DVLABEL.get(slot, "?"), "loop": 0,
                "scene": nm, "label": e["owner"],
                "nav": nav_for(e["owner"], slot, set(plan.setup_cor), plan.banned_cor),
                "choices": picks,
                "gives": (["+%d %s" % (gain, B.statname(var))]
                          + side_gains(e["owner"], picks, var, noted)),
                "avoid": sorted(set(avoid)), "target": False, "reason": "stat",
                "cost": cost,
                "auto": is_auto(e["owner"], slot, set(plan.setup_cor), plan.banned_cor),
                "explore": is_explore(e["owner"], slot),
                "place": place_for(e["owner"], slot, set(plan.setup_cor), plan.banned_cor),
            })
        row = {"var": B.statname(var), "need": need, "have": have,
               "from": sorted(set(why)), "met": have >= need, "scope": "run",
               "byDv": deadline, "by": DVLABEL.get(deadline, "the end"),
               "slots": sorted(chosen)}
        # cassidyLove is halved at the reset rather than cleared, so unlike
        # every other affection it carries between runs
        if var == "cassidyLove": row["carry"] = True
        summary.append(row)
    return summary, extra_steps

# ---------- nav for a visit at a slot ----------

def nav_guards(owner, dv, known_cor, banned=()):
    """The raw conditions guarding the map/picker route into a scene at a slot.
    These carry the corruption and Love gates, so they are requirements too."""
    path = route_path(owner, dv)
    if path is None: return []
    route = [EDGES[i] for i in path]
    conds = []
    for alt, _ in B.pick_alts(route, set(known_cor), banned):
        conds.extend(guard_conds(alt["guards"]))
    return conds

def nav_for(owner, dv, known_cor, banned=()):
    path = route_path(owner, dv)
    if path is None: return []
    route = [EDGES[i] for i in path]
    steps = []
    for edge, (alt, nalt) in zip(route, B.pick_alts(route, set(known_cor), banned)):
        ch = [B.clean(g["text"]) for g in alt["guards"] if g["kind"] == "choice"]
        steps.append({"to": B.sname(edge["dst"]), "pick": ch[0] if ch else None,
                      "alts": nalt})
    return steps

def place_for(owner, dv, known_cor, banned=()):
    """Which room on the cabin map this visit is entered from.

    The first place-carrying hop of the route is the click the player makes:
    everything after it (a picker menu, a scene that jumps on to another) all
    happens inside that room. Automatic events have no map click at all, so they
    have no place -- callers must not ask for one."""
    path = route_path(owner, dv)
    if path is None: return None
    route = [EDGES[i] for i in path]
    for alt, _ in B.pick_alts(route, set(known_cor), banned):
        if alt.get("place"): return B.place_name(alt["place"])
    return None

DVLABEL = {}
for _r in ROOTS.values():
    dv = _r.get("dateVar", 0)
    if 1 <= dv <= LAST_DV: DVLABEL[dv] = B.slot_label(_r)
DVLABEL.setdefault(22, "End of loop (mail)")

def off_requirements(guards):
    """Rungs these guards insist stay OFF -> (hard, soft).

    `hard` is what every way of satisfying the guard leaves off: a bare
    `not <rung>`, or a `not (A or B)` where both conjuncts are rungs. Nothing
    can be planned around it.

    `soft` is a *choice*. `AlexShareBed`'s
    `not (hailyCorruption2On and not (hailyCorruption3On and tempFlags[…] == 3))`
    is satisfied either by leaving Haily at Contact or by taking her to Hand
    Holding *and* earning the milking flag -- the first is a toggle the player
    is already setting, the second is more visits. Preferring the free one is a
    heuristic, so it is banned separately and `build_plan` drops the guesses
    before it drops the requirements."""
    hard_c, _ = B.flatten(guard_conds(guards))
    hard, soft = set(), set()
    for a in hard_c:
        alts = B.cor_clauses(B.unwrap(a.strip()))
        if not alts: continue
        rungs = [{v for v in x[1] if B.ladder_name(v)[0]} for x in alts]
        # only what every alternative leaves off is genuinely required
        if all(rungs): hard |= set.intersection(*rungs)
        # ...and the guess is the cheapest escape that is purely a matter of
        # where the ladders sit: no rung to switch on, nothing else to earn
        free = [r for r, x in zip(rungs, alts) if r and not x[0] and not x[2]]
        if free: soft |= min(free, key=lambda s: (len(s), sorted(s)))
    return hard, soft - hard

def attempt(target_event, banned, banned_cor=(), skip_scores=False):
    p = Plan(banned, banned_cor, skip_scores)
    tv = p.add_visit(target_event)
    tv.gives.append("the unlock")
    p.expand(tv.key, target_event["guards"], 1, set())
    # The target's own site can be the one gated on a session counter -- Jenny's
    # Grope wants her trance at 8 and the picks alone top out at 4 -- so it needs
    # the same treatment `resolve` gives every other site.
    p.fix_session(tv.key, 2, set())
    placed, prior = p.schedule_all(tv.key)
    # Getting to a scene has its own gates (the map button conditions). Those
    # depend on which slot we picked, so fold them in and reschedule.
    for _ in range(3):
        added = False
        for k, dv in list(placed.items()) + list(prior.items()):
            conds = nav_guards(p.visits[k].owner, dv, set(p.setup_cor), p.banned_cor)
            if not conds: continue
            before = (len(p.visits), dict(p.setup_cor), dict(p.stats))
            p.expand(k, [{"kind": "cond", "text": c} for c in conds], 2, set())
            if (len(p.visits), p.setup_cor, p.stats) != before: added = True
        if not added: break
        p.prior = set(x for x in p.prior if x in p.visits)
        placed, prior = p.schedule_all(tv.key)
    # A required affection gate is a goal, not spare-slot filler: if the run is
    # still short of one, go and earn it.
    for _ in range(CHASE_ROUNDS):
        on, produced = B.toggles_on(p.setup_cor), plan_facts(p, placed)
        changed = False
        for var, (need, consumers) in sorted(p.stats.items()):
            if stat_scope(var) != "run": continue
            dl = gate_deadline(placed, consumers)
            if gate_have(p, placed, var, dl, on, produced) >= need: continue
            got = chase_gate(p, tv.key, placed, prior, var, consumers)
            if got: placed, prior = got; changed = True
        if not changed: break
    # a chase candidate we tried and rejected leaves its failure behind; that is
    # not this plan's failure, and `solve` would ban a site over it
    if tv.key in placed: p.failed = None
    placed = p.prune(placed, tv.key)
    # anything we actually scheduled is not unresolved. Compare the facts, not
    # their prose: two different requirements often describe to the same choice
    # text, and matching on that silently swallows a real loose end.
    produced = {f for v in p.visits.values() for f in v.facts} | p.granted
    p.unresolved = [t for t, f in p.unresolved if f is None or f not in produced]
    return p, tv, placed, prior

def solve(target_event, banned_cor, skip_scores=False, banned_sites=()):
    # A producer that is only playable late can make the target unschedulable;
    # when that happens, ban that site and look for another way to satisfy it.
    banned = set(banned_sites)
    for _ in range(10):
        p, tv, placed, prior = attempt(target_event, banned, banned_cor, skip_scores)
        if tv.key in placed and p.failed is None:
            break
        cause = p.failed
        sid = p.site_of.get(cause) if cause else None
        if sid and sid not in banned:
            banned.add(sid); continue
        break
    if tv.key not in placed: return None
    return p, tv, placed, prior

def build_plan(target_event):
    # A run that switches on a rung a scene needs OFF is not a plan, it is a
    # contradiction -- and because the menu button for a rung switches on every
    # rung beneath it, that is easy to walk into. Forbid the offending rungs and
    # look for another route; keep the least-conflicted answer if there is none.
    # Drop the guesses before the requirements. `soft` is the escape we *chose*
    # from a compound that offered more than one, so it is the first thing to
    # give up when a target will not solve; `hard` is what the guard actually
    # insists on and giving it up means the plan contradicts itself. The old
    # code cleared both at once, which threw a real requirement away to rescue a
    # heuristic and left `cascade_conflicts` to notice, out of a budget of 4.
    hard_off, soft_off = off_requirements(target_event["guards"])
    tiers = [hard_off, set()]
    banned_cor = hard_off | soft_off
    best, tried, sites, skip_scores = None, set(), set(), False
    for _ in range(5):
        state = (frozenset(banned_cor), frozenset(sites), len(tiers))
        if state in tried: break
        tried.add(state)
        res = solve(target_event, banned_cor, skip_scores, sites)
        if res is None:
            if not tiers: break
            banned_cor, sites = tiers.pop(0), set(); continue   # impossible that way
        p, tv, placed, prior = res
        conflicts = cascade_conflicts(p, placed, prior)
        # Weigh a contradiction against a loose end: banning the site that
        # caused one can remove the only producer of something else. A loose end
        # comes first because it is the worse answer -- a toggle clash still
        # names every scene and choice and warns which rung fights it, while an
        # unresolved prerequisite means the run was never worked out. Banning a
        # rung to dodge a clash routinely lands there: Jenny's Hypnosis traded a
        # four-step plan carrying three clashes for a one-step plan carrying
        # none, which reads as the cleaner answer and tells the player nothing.
        cost = (len(p.unresolved), len(conflicts))
        if best is None or cost < best[0]:
            best = (cost, conflicts, res)
        # A soft ban is a guess, and a guess can spoil a plan without failing it:
        # the tier ladder only fires when nothing solves at all, so a loose end
        # it caused would otherwise stand. Give it one attempt without them --
        # `best` keeps whichever came out cleaner, so this cannot lose.
        if not conflicts and not (p.unresolved and banned_cor & soft_off): break
        # Only a rung that must be OFF can be banned; one that must be ON is the
        # opposite problem and banning it would guarantee failure. Either way,
        # ban the site that dragged the contradiction in -- a fact usually has
        # more than one producer, and another may sit at a compatible rung.
        banned_cor = (banned_cor - soft_off) | {c["var"] for c in conflicts
                                                if c["want"] == "off"}
        sites = sites | {c["_site"] for c in conflicts
                         if c["_site"] and c["_site"] != p.site_of.get(tv.key)}
    if best is None:
        # chaining the scene score boxed the scheduler in; report it instead
        res = solve(target_event, set(), skip_scores=True)
        if res is None: return None
        p, tv, placed, prior = res
        conflicts = cascade_conflicts(p, placed, prior)
        best = ((len(p.unresolved), len(conflicts)), conflicts, res)
    _, conflicts, (p, tv, placed, prior) = best
    seen, uniq = set(), []
    for c in conflicts:                     # one line per scene and rung
        c.pop("_site", None)
        k = (c["scene"], c["var"], c["want"])
        if k not in seen: seen.add(k); uniq.append(c)
    conflicts = uniq

    known = set(p.setup_cor)
    on_cor, have = B.toggles_on(p.setup_cor), plan_facts(p, placed)
    # Which hypnosis session this run actually sits in, so a step read in one of
    # its later labels knows whose picks decided its number.
    playing = set()
    for k in list(placed) + list(prior):
        ss = B.SESSION_AT.get(p.visits[k].owner, ())
        if len(ss) == 1: playing.add(ss[0])
    solved = {}
    # every rung this run switches on, in the prose `B.pretty` gives an avoid
    # line, so a step can recognise its own setup contradicting it
    clash_txt = {"NOT %s·%s ON" % B.ladder_name(v) for v in on_cor
                 if B.ladder_name(v)[0]}
    def render(mapping):
        out = []
        for k, dv in sorted(mapping.items(), key=lambda x: x[1]):
            v = p.visits[k]
            tr, covers = trance_for(p, k, dv, on_cor, have, playing)
            if tr and tr.get("ok"): solved[k] = tr
            out.append({
                "trance": tr,
                "dv": dv, "slot": DVLABEL.get(dv, "?"),
                "loop": p.prior_loop.get(k, 0),
                "scene": B.sname(v.owner), "label": v.owner,
                "nav": nav_for(v.owner, dv, known, p.banned_cor),
                "choices": v.choices,
                "gives": v.gives,
                # a threshold the session block above now spells out as a path is
                # not also a "must not already have" for the row to repeat
                # the ones the setup card above already contradicts, so the row
                # can say so where it bites instead of only in the warn card at
                # the bottom -- "avoid Sami·Love ON" under a setup reading
                # "Sami · C5 Composed" is a contradiction the reader has to
                # derive from the cascade before they can even see it
                "clash": sorted(clash_txt & set(dedup(
                    negatives(v.guards, dv, on_cor, have, p)
                    + nav_negatives(nav_guards(v.owner, dv, known, p.banned_cor),
                                    dv, on_cor, have, p)))),
                "avoid": [a for a in dedup(negatives(v.guards, dv, on_cor, have, p)
                                           + nav_negatives(
                    nav_guards(v.owner, dv, known, p.banned_cor), dv, on_cor, have, p))
                    if a not in covers],
                "target": k == tv.key,
                "cost": p.cost_of.get(k, 1),
                "auto": is_auto(v.owner, dv, known, p.banned_cor),
                "explore": is_explore(v.owner, dv),
                "gated": route_gated(v.owner, dv, known, p.banned_cor),
                "place": place_for(v.owner, dv, known, p.banned_cor),
            })
        # A split session (landmine 54) puts two rows on one scene, and nothing
        # but the threshold pill tells them apart. Mark both, not the second:
        # which of them the scheduler happens to place first means nothing.
        twice = {}
        for r in out:
            if r["trance"]: twice[r["label"]] = twice.get(r["label"], 0) + 1
        for r in out:
            if r["trance"] and twice[r["label"]] > 1: r["trance"]["repeat"] = True
        return out
    stats, extra = stat_topup(p, placed)
    steps = render(placed) + extra
    steps.sort(key=lambda x: x["dv"])
    # What the run leans on being switched OFF. Gathered from the whole plan --
    # this run and any earlier loop -- because the setup card is one card.
    ev = off_rungs(p, {**placed, **prior}, on_cor)   # visit keys are tuples
    forbidden = set(ev)
    # by construction: `off_rungs` only takes an alternative the run satisfies
    assert not (forbidden & on_cor), sorted(forbidden & on_cor)
    caps = roster(p, on_cor, forbidden, ev)
    return {
        "steps": steps,
        "conflicts": conflicts,
        "extra": unmodelled(p, placed, solved, playing),
        "prior": render(prior),
        "priorLoops": getattr(p, "prior_loops", 1),
        "setup": {
            "corruption": [{"char": B.ladder_name(c)[0], "level": B.ladder_name(c)[1], "var": c}
                           for c in minimal_setup(p.setup_cor) if B.ladder_name(c)[0]],
            "roster": caps,
            "world": p.setup_world,
            "options": [B.OPTNAME[o] for o in sorted(p.setup_opt)],
        },
        "stats": stats,
        "unresolved": sorted(set(p.unresolved)),
    }
