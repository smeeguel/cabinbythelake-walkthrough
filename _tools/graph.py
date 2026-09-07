# Build a navigable graph: day/time map -> scene label -> menu choices -> unlock.
import os, re, json, sys
from collections import deque, defaultdict

SRC = "_decompiled"
OUT = "_analysis"

TIMES = ["earlymorning", "morning", "noon", "afternoon", "evening", "night", "midnight"]
DAYNAME = {1: "Friday", 2: "Saturday", 3: "Sunday", 4: "Monday"}
ROOT_RE = re.compile(r'^d([1-4])(%s)(map)?$' % "|".join(TIMES))

# `call screen HailyPhotoTrading` is a jump to the screen, not to a label
# named "screen" -- without the optional keyword the whole photo-trading
# subtree looks unreachable.
JUMP = re.compile(r'^(?:jump|call)\s+(?:screen\s+)?(\w+)$')
JUMPQ = re.compile(r'Jump\("(\w+)"\)')
CHOICE = re.compile(r'^"(.*?)"(?:\s+if\s+(.*?))?:$')
IFS = re.compile(r'^(?:el)?if\s+(.*?):$')
COR = re.compile(r'addCor\(\s*"([^"]*)"\s*\)')
SETVAR = re.compile(r'^(?:\$\s*)?(\w+)\s*=\s*(True|False)\s*$')
MAIL = re.compile(r'PushToLog\(\s*"(.*?)"\s*\)')
SCENENAME = re.compile(r'sceneNameConv\[\s*"(\w+)"\s*\]\s*=\s*"(.*?)"')
# `$ currentScene = "X"` is the game telling the phone's MapBook which entry the
# player is inside. It is the only link from a sub-label like HailyPackageWatch
# to the scene the player knows it as (`HailyPackage1`, "Mysterious Package").
CURSCENE = re.compile(r'^\$?\s*currentScene\s*=\s*"([\w.]+)"$')
# The MapBook page for a scene is `screen map<Scene>:`, and its root node -- the
# first Text/textbutton in the tree grid -- is the scene's player-facing title.
# It is drawn three different ways (`style "gridtextbold"`, `style "gridtexton"`,
# or a `_textbutton` in a Window), so anchor on the widget, not the style.
BOOKTITLE = re.compile(r'^(?:Text|_textbutton)\s+"(.*?)"')
ITEM = re.compile(r'commonEvents\s*\.\s*append\s*\(\s*"([^"]+)"')
TEMPSET = re.compile(r'flowVar\s*\(\s*"([\w-]+)"\s*,\s*(\d+)|'
                     r'tempFlags\[\s*"([\w-]+)"\s*\]\s*=\s*(\d+)')
# `mood` is the odd one out: no character prefix and no suffix, but it is a
# per-run tally reset alongside the Love vars (`script.rpy:420`), so it is
# comparable with them and is used to break ties between equal Love routes.
STAT = re.compile(r'^(?:\$\s*)?((?:\w*(?:Love|Horny|Nerve|Favor|Jealousy|Concern|Sus|Teach|Talk|BE))|mood)\s*(\+=|-=|=)\s*(-?\d+)$')
# `dayhandler` spends a timeslot by doing `dateVar += 1` before it dispatches, so
# a scene that does `dateVar -= 1` on the way in hands the slot back: the map for
# that sitting is still to come. That is how every automatic event works -- the
# Saturday wake-up crawls, Haily's packages, the Sunday-night bedcrawls -- and it
# is the only thing in the source that says so. `$ dateVar-= 1` (no space before
# the operator) and `$ dateVar -=1` both occur, hence the loose \s*.
DATEVAR = re.compile(r'^\$?\s*dateVar\s*(\+=|-=)\s*(\d+)$')
# A map click is an imagebutton over one of the cabin's ten hotspots, and the
# only thing naming the place is the glow art it draws:
#   _imagebutton auto "ui/glow garden_%s.png" ... action Jump("HailyText3")
# `at gardenbutton` is not reliable -- exploremap's Forest button has no `at`
# clause at all -- so the image is the anchor. Recorded on the edge so a plan
# can say which room to click.
PLACEBTN = re.compile(r'ui/glow\s+(\w+)_%s\.png')

SCENE_NAMES = {}
CURRENT_SCENE = {}

# ---------- parse into an indent tree ----------

class N:
    __slots__ = ("text", "ind", "kids", "file", "line")
    def __init__(self, text, ind, file, line):
        self.text, self.ind, self.file, self.line = text, ind, file, line
        self.kids = []

def parse(path, fn):
    root = N("", -1, fn, 0)
    stack = [root]
    for i, raw in enumerate(open(path, encoding="utf-8")):
        line = raw.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        ind = len(line) - len(line.lstrip(" "))
        node = N(line.strip(), ind, fn, i + 1)
        while stack[-1].ind >= ind:
            stack.pop()
        stack[-1].kids.append(node)
        stack.append(node)
    return root

# ---------- collect containers ----------

def build():
    """name -> node, plus every node claiming that name.

    `label HailyPhotoTrading` immediately calls `screen HailyPhotoTrading`, and
    the two share a name. Keeping only the first would drop the screen's buttons
    and with them the whole photo-trading subtree, so both bodies are walked
    under the one name."""
    containers, all_nodes = {}, {}
    for fn in sorted(os.listdir(SRC)):
        if not fn.endswith(".rpy"): continue
        root = parse(os.path.join(SRC, fn), fn)
        for n in root.kids:
            m = re.match(r'^(label|screen)\s+([\w.]+)\s*:?$', n.text)
            if m:
                containers.setdefault(m.group(2), n)
                all_nodes.setdefault(m.group(2), []).append(n)
    return containers, all_nodes

# ---------- walk a container, yielding edges and events ----------

LEAVES = re.compile(r'^(jump|return)\b')
# `call` is deliberately absent: it comes back to the next statement, so a block
# that calls has not left. (`JUMP` above *does* include it -- that is about edges,
# which is a different question. Do not unify the two.)
RE_LABEL = re.compile(r'^label\s+[\w.]+\s*:?$')

def _reentry(node):
    """A nested `label` anywhere under this statement. Something elsewhere can
    jump straight to it, so code after it is reachable and not dead."""
    return any(RE_LABEL.match(k.text) or _reentry(k) for k in node.kids)

def escapes(node):
    """Does control always leave this block? A scene that opens with
    `if cassidyCorruption5On: jump CatchingUpModernCassidy` never reaches its own
    body in a run with that rung on, and nothing in the indentation says so.

    Scan the whole body, not its last statement. Two different things put a
    `jump` somewhere other than the end, and neither is visible in the
    indentation:

    - real dead code. `label AlexShareBed:` opens
      `if hailyCorruption2On and …: jump AlexHailyShareBed` and then two
      unreachable `$ alexflash[0] += 1` lines, so the last statement is not the
      jump and the fall-through negation was never recorded -- the plans for
      that scene's three dots switched Haily's rung *on* and could not be played.
    - the decompiler. `rpyc_dump.py:198` writes a narrator Say one column too
      deep (the format string has a literal space where the speaker goes), so
      `parse` adopts the block's next *sibling* into it, below the jump. That is
      51 of the 52 blocks this rule newly catches, and it is why fixing this
      function fixes the defect outright: 21001 lines are misaligned, every one
      of them a narrator Say, and no non-narrator node is ever parented under
      one -- so `escapes` is the only place the misalignment reaches.

    The one genuine exception is a `label` after the jump: `sceneC5Alex` jumps
    back to `label AlexBBQFinalePost:` *inside* such a block, so control resumes
    there and does fall out of the bottom. A `menu:` is not a re-entry -- nothing
    reaches a menu except by falling into it."""
    out = False
    for k in node.kids:
        if not k.text.strip(): continue
        if RE_LABEL.match(k.text) or _reentry(k): out = False
        elif LEAVES.match(k.text):               out = True
    return out

def negate(cond):
    """Parenthesise only a compound: `not alexCorruption4On` stays readable and
    keeps matching the single-term patterns downstream."""
    c = cond.strip()
    return "not %s" % c if re.match(r'^[\w."\[\]]+$', c) else "not (%s)" % c

# `default gateFirstRun = True`, and the first end-of-loop menu clears it
# (`sceneEndChoices.rpy:71`). Every plan the atlas describes starts from that
# menu, so a jump that can only be taken while the flag still holds is not a
# route anyone can follow. Left traversable it quietly routes plans through the
# game's first-playthrough default scenes -- eight slot labels open with
# `if gateFirstRun: jump d<n><time>Default`.
def firstrun_only(guards):
    return any(g["kind"] == "cond" and g["text"].strip() == "gateFirstRun"
               for g in guards)

def walk(node, guards, edges, events, owner, dv=0):
    # conditions that have to be FALSE to get this far: each one guarded a block
    # that jumped away, so everything after it is the fall-through
    fell = []
    # net `dateVar` delta already applied on the path to here. It accumulates
    # across siblings in order and is inherited by every nested block, because
    # the refund is often several lines above the jump it pays for -- the
    # Saturday wake-up decrements once and then opens a menu of three scenes.
    # the conditions of earlier branches of the if/elif chain we are inside. An
    # `elif` is only reached when every one of them was false -- which is how the
    # game picks between variants of a scene, so it is a real requirement:
    #   if alexCorruption4On:   jump C4AlexBedroomVisit
    #   elif alexCorruption2On: jump d2nightAlexBedroomC2
    chain = []
    for k in node.kids:
        t = k.text
        g = guards + fell
        dm = DATEVAR.match(t)
        if dm:
            delta = int(dm.group(2)) * (1 if dm.group(1) == "+=" else -1)
            events.append({"type": "time", "delta": delta, "owner": owner,
                           "guards": g, "file": k.file, "line": k.line})
            dv += delta
            continue
        c = CHOICE.match(t)
        if c and (k.kids or True) and not t.startswith(("if ", "elif ")):
            lab, cond = c.group(1), c.group(2)
            g = g + [{"kind": "choice", "text": lab, "cond": cond,
                      "file": k.file, "line": k.line}]
            walk(k, g, edges, events, owner, dv)
            chain = []
            continue
        i = IFS.match(t)
        if i:
            if not t.startswith("elif"): chain = []
            prior = [{"kind": "cond", "text": negate(c0), "file": k.file,
                      "line": k.line} for c0 in chain]
            walk(k, g + prior + [{"kind": "cond", "text": i.group(1),
                                  "file": k.file, "line": k.line}],
                 edges, events, owner, dv)
            if escapes(k):
                fell.append({"kind": "cond", "text": negate(i.group(1)),
                             "file": k.file, "line": k.line})
            chain.append(i.group(1))
            continue
        if t == "else:":
            prior = [{"kind": "cond", "text": negate(c0), "file": k.file,
                      "line": k.line} for c0 in chain]
            walk(k, g + prior + [{"kind": "else", "text": "(otherwise)",
                                  "file": k.file, "line": k.line}],
                 edges, events, owner, dv)
            # An `else` that jumps away is the same trap as an `if` that does,
            # read the other way round: getting past the chain at all means one
            # of its conditions held. `AlexYourBedroomN3C0` opens
            # `if alexLove >= 2: … else: <a page of dialogue> jump dayhandler`,
            # so the menu below it -- and the four collection dots behind that
            # menu -- silently want 2 of Alex's Love, and neither the
            # indentation nor the menu itself says so.
            if escapes(k) and chain:
                fell.append({"kind": "cond", "file": k.file, "line": k.line,
                             "text": chain[0] if len(chain) == 1
                             else " or ".join("(%s)" % c for c in chain)})
            chain = []
            continue
        chain = []

        m = JUMP.match(t)
        tgts = []
        if m: tgts.append(m.group(1))
        tgts += JUMPQ.findall(t)
        pb = PLACEBTN.search(t)
        for tg in tgts:
            e = {"src": owner, "dst": tg, "guards": g, "dv": dv,
                 "file": k.file, "line": k.line}
            if firstrun_only(g): e["firstRun"] = True
            if pb: e["place"] = pb.group(1)
            edges.append(e)

        cm = COR.search(t)
        if cm:
            events.append({"type": "cor", "value": cm.group(1), "owner": owner,
                           "guards": g, "file": k.file, "line": k.line})
        im = ITEM.search(t)
        if im:
            events.append({"type": "item", "name": im.group(1), "owner": owner,
                           "guards": g, "file": k.file, "line": k.line})
        tf = TEMPSET.search(t)
        if tf:
            events.append({"type": "branch", "id": tf.group(1) or tf.group(3),
                           "val": int(tf.group(2) or tf.group(4) or 0),
                           "owner": owner, "guards": g,
                           "file": k.file, "line": k.line})
        sn = SCENENAME.search(t)
        if sn:
            SCENE_NAMES[sn.group(1)] = sn.group(2)
        cs = CURSCENE.match(t)
        if cs:
            CURRENT_SCENE.setdefault(owner, cs.group(1))
        sv = SETVAR.match(t)
        if sv:
            events.append({"type": "flag" if "Corruption" in sv.group(1) else "setflag",
                           "var": sv.group(1), "val": sv.group(2),
                           "owner": owner, "guards": g,
                           "file": k.file, "line": k.line})
        st = STAT.match(t)
        if st:
            events.append({"type": "stat", "var": st.group(1), "op": st.group(2),
                           "amount": int(st.group(3)), "owner": owner, "guards": g,
                           "file": k.file, "line": k.line})
        pm = MAIL.search(t)
        if pm and ("New Mail" in pm.group(1) or "Corruption Unlock" in pm.group(1)
                   or "New Memory" in pm.group(1)):
            events.append({"type": "note", "text": re.sub(r'\{[^}]*\}', '', pm.group(1)).strip(),
                           "owner": owner, "guards": g,
                           "file": k.file, "line": k.line})
        walk(k, g, edges, events, owner, dv)

def book_title(node):
    """The first Text/textbutton in a MapBook page, in document order: the tree's
    root node, which is the scene's title. Everything before it is spacer art."""
    for k in node.kids:
        m = BOOKTITLE.match(k.text)
        if m: return m.group(1)
        t = book_title(k)
        if t: return t
    return None

def main():
    os.makedirs(OUT, exist_ok=True)
    containers, all_nodes = build()
    edges, events = [], []
    for name, nodes in all_nodes.items():
        for node in nodes:
            walk(node, [], edges, events, name)

    # `label dayhandler` dispatches dateVar 1..21 to the timeslot labels; that
    # table is the authoritative slot order. dayhandler itself must not be a
    # transit node or BFS leaks between unrelated days.
    slots = {}
    dh = containers.get("dayhandler")
    if dh:
        for k in dh.kids:
            m = re.match(r'^(?:el)?if dateVar == (\d+):$', k.text)
            if not m: continue
            for kk in k.kids:                      # the jump is a child of the if
                j = JUMP.match(kk.text)
                if j:
                    slots[j.group(1)] = int(m.group(1))
                    break

    roots = {}
    for name, dv in slots.items():
        if name in ("endRun", "endCycleChoices"): continue
        m = ROOT_RE.match(name.lower())
        day = int(m.group(1)) if m else 1
        time = m.group(2) if m else "noon"
        roots[name] = {"day": day, "time": time, "dateVar": dv,
                       "label": "%s %s" % (DAYNAME[day], time)}
    # the map screens are entered from their slot label via `show screen`,
    # which is not a jump edge, so they need to be roots in their own right
    for name in containers:
        m = ROOT_RE.match(name.lower())
        if m and name not in roots:
            day, time = int(m.group(1)), m.group(2)
            roots[name] = {"day": day, "time": time,
                           "dateVar": slots.get("d%d%s" % (day, time), 0),
                           "label": "%s %s" % (DAYNAME[day], time)}

    # loop-restart / dispatcher hubs: routing through these jumps between runs
    # Explore mode is reachable from every timeslot via the map overlay, and
    # mail is delivered in a block at the end of the run -- both are entry
    # points in their own right rather than steps on a route.
    roots["exploremap"] = {"day": 0, "time": "explore", "dateVar": 0,
                           "label": "Explore (any timeslot)"}
    roots["endCyclePhone"] = {"day": 5, "time": "endofloop", "dateVar": 22,
                              "label": "End of loop (mail delivery)"}

    # loop-restart / dispatcher hubs: routing through these jumps between runs
    BLOCK = {"dayhandler", "dayInit", "endRun", "endCycleChoices", "endmenuholder",
             "ResetStats", "exitLoop", "startLoop", "explorereturn", "exploreholder"}

    # adjacency, by edge index so routes can be stored compactly
    adj = defaultdict(list)
    for i, e in enumerate(edges):
        adj[e["src"]].append(i)

    def bfs(starts):
        # ranked on (hops, dateVar cost), so a scene the slot label jumps into
        # for free is recorded by that entrance rather than by an equally short
        # map click. `d1midnightDefault` is reachable both ways from the same
        # root and only one of them hands the timeslot back.
        best = {s: ([], 0) for s in starts}
        dq = deque(starts)
        while dq:
            cur = dq.popleft()
            if cur in BLOCK: continue
            path, cost = best[cur]
            for ei in adj.get(cur, []):
                e = edges[ei]
                d = e["dst"]
                # roots are entry points only: never route *through* one into
                # another timeslot, and never through the dayhandler dispatcher
                if d not in containers or d in BLOCK or d in roots:
                    continue
                if e.get("firstRun"): continue     # only on a brand-new save
                cand = (path + [ei], cost + e.get("dv", 0))
                if d in best and (len(best[d][0]), best[d][1]) <= (len(cand[0]), cand[1]):
                    continue
                best[d] = cand
                dq.append(d)
        return {k: v[0] for k, v in best.items()}

    # one BFS per timeslot, so we learn every slot a scene can be entered at.
    # the root maps to itself with an empty path: unlocks that fire directly in
    # a slot label (end-of-loop mail, for instance) belong to that slot.
    routes_by_root = {r: bfs([r]) for r in roots}
    # combined reachability (any slot), used for coverage reporting
    route = bfs(list(roots))

    # every direct way into a container (a scene often has several entry points)
    incoming = defaultdict(list)
    for e in edges:
        if e["dst"] in containers:
            incoming[e["dst"]].append(e)

    book = {}
    for name, node in containers.items():
        if not name.startswith("map"): continue
        t = book_title(node)
        if t: book[name] = t

    json.dump({"roots": roots,
               "edges": edges,
               "events": events,
               "routesByRoot": routes_by_root,
               "incoming": incoming,
               "sceneNames": SCENE_NAMES,
               "mapBook": book,
               "currentScene": CURRENT_SCENE,
               "fileOf": {n: containers[n].file for n in containers},
               "containers": sorted(containers)},
              open(os.path.join(OUT, "graph.json"), "w", encoding="utf-8"))

    print("containers %d  edges %d  events %d  roots %d" %
          (len(containers), len(edges), len(events), len(roots)))
    print("scene names %d  MapBook titles %d  currentScene %d" %
          (len(SCENE_NAMES), len(book), len(CURRENT_SCENE)))
    print("reachable containers: %d / %d" % (len(route), len(containers)))
    ev_reach = sum(1 for e in events if e["owner"] in route)
    print("events in reachable containers: %d / %d" % (ev_reach, len(events)))
    print("\nroots:")
    for r, v in sorted(roots.items(), key=lambda x: (x[1].get("dateVar", 99), x[0])):
        print("   %-24s %s" % (r, v["label"]))

if __name__ == "__main__":
    main()
