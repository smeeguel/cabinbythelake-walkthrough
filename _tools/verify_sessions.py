# Replay every trance path the app ships against the raw decompiled source.
#
# `build_app_data` reads the hypnosis menus and `plan` chooses a path through
# them; both would agree with each other even if the reading were wrong, and it
# was -- three scenes of very nearly the same shape were being summed as though
# their conditional and sub-menu bumps were the option's own (landmine 55). So
# this parses the `.rpy` again, from scratch and deliberately differently, and
# checks the shipped picks add up to the shipped totals and clear the shipped
# thresholds.
#
#     python _tools/verify_sessions.py     ->  "checked 38 paths, 0 problems"
import json, re, sys

sys.stdout.reconfigure(encoding="utf-8")

# Every session and the label that builds it. Kept as a literal on purpose: the
# point of this file is to not share the pipeline's idea of what a session is.
SRC = {
    "Hypnotising Jenny":   ("sceneC0Jenny.rpy", "label JennyGarden1Hypnosis:"),
    "Hypnotising Jenny 2": ("sceneCPJenny.rpy", "label JennyGardenPregHypnosis:"),
    "Hypnotising Lisa":    ("sceneC1Lisa.rpy",  "label LisaHypnosis:"),
}
COUNTER = {"Jenny's trance": "hypnosisA", "Lina's trance": "hypnosisB",
           "Lisa's trance": "hypnosisA"}

RE_OPT   = re.compile(r'^"(.*)":$')
RE_BUMP  = re.compile(r'^\$ (hypnosis[AB]) (\+|-)= (-?\d+)$')
RE_SCALE = re.compile(r'^\$ (hypnosis[AB]) = (int\()?hypnosis[AB]\*([\d.]+)\)?$')

def parse(fn, lab):
    """-> {option text: {counter: delta}}, [(counter, factor, truncated)]"""
    lines = open("_decompiled/" + fn, encoding="utf-8").read().split("\n")
    i = lines.index(lab)
    end = next((j for j in range(i + 1, len(lines))
                if lines[j].strip() and not lines[j].startswith(" ")), len(lines))
    opts, cur, mods = {}, None, []
    for j in range(i + 1, end):
        s = lines[j].strip()
        m = RE_OPT.match(s)
        if m: cur = m.group(1); opts.setdefault(cur, {})
        m = RE_BUMP.match(s)
        if m and cur:
            opts[cur][m.group(1)] = int(m.group(3)) * (1 if m.group(2) == "+" else -1)
        m = RE_SCALE.match(s)
        if m: mods.append((m.group(1), float(m.group(3)), bool(m.group(2))))
    return opts, mods

def main():
    data = json.load(open("_analysis/app_data.json", encoding="utf-8"))
    seen = bad = 0
    for t in data["targets"]:
        plan = t.get("plan") or {}
        for step in (plan.get("steps") or []) + (plan.get("prior") or []):
            tr = step.get("trance")
            if not tr: continue
            if not tr.get("ok"):
                print("UNSOLVED:", t["id"], tr["scene"]); bad += 1; continue
            if tr["scene"] not in SRC:
                print("UNKNOWN SCENE:", t["id"], tr["scene"]); bad += 1; continue
            seen += 1
            opts, mods = parse(*SRC[tr["scene"]])
            tot = {"hypnosisA": 0, "hypnosisB": 0}
            for pick in tr["picks"]:
                if pick["text"] not in opts:
                    print("NO SUCH OPTION:", t["id"], pick["text"]); bad += 1; continue
                for var, n in opts[pick["text"]].items(): tot[var] += n
                for add in pick["adds"]:      # the deltas the row prints
                    if opts[pick["text"]].get(COUNTER[add["name"]]) != add["amount"]:
                        print("WRONG DELTA:", t["id"], pick["text"], add); bad += 1
            # the multipliers the plan says apply, in the order the source runs
            # them -- the halving is not truncated and the boost is
            live = {round(m["factor"], 3) for m in tr["mods"] if m["applies"]}
            for var, factor, trunc in mods:
                if round(factor, 3) not in live: continue
                x = tot[var] * factor
                tot[var] = int(x) if trunc else x
            for need in tr["needs"]:
                got = tot[COUNTER[need["name"]]]
                if got < need["need"]:
                    print("MISSES THRESHOLD:", t["id"], need, "reached", got); bad += 1
            for shown in tr["totals"]:
                got = tot[COUNTER[shown["name"]]]
                if abs(got - shown["value"]) > 1e-9:
                    print("WRONG TOTAL:", t["id"], shown, "recomputed", got); bad += 1
    print("checked %d paths, %d problems" % (seen, bad))
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
