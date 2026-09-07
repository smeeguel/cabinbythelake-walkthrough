# Build the shipped bundle: targets, per-slot routes, and a full run plan each.
import json, os, time
import build_app_data as B
import plan as P

def score(pl):
    """Fewest loose ends, then fewest earlier loops, then shortest run.

    A toggle clash counts as a loose end: a run that switches a rung the wrong
    way for one of its own scenes is not a working plan, so a site that avoids
    one is worth preferring even if it costs an extra step."""
    return (len(pl["unresolved"]) + len(pl["conflicts"]),
            pl.get("priorLoops", 1) if pl["prior"] else 0,
            len(pl["prior"]), len(pl["steps"]))

def main():
    t0 = time.time()
    targets, colors = B.build_targets()
    planned = 0
    for t in targets:
        best = None
        for ev in t.pop("_events", [])[:4]:
            try:
                pl = P.build_plan(ev)
            except RecursionError:
                pl = None
            except Exception:
                pl = None
            if pl and (best is None or score(pl) < score(best)):
                best = pl
        t["plan"] = best
        if best: planned += 1
        # the plan replaces the old per-slot route list; keep only the summary
        # of which sittings the final scene can be played at
        t["sittings"] = sorted({r["slot"] for r in t["routes"]},
                               key=lambda s: [r["dateVar"] for r in t["routes"]
                                              if r["slot"] == s][0])
        t.pop("routes", None)

    json.dump({"targets": targets, "colors": colors},
              open("_analysis/app_data.json", "w", encoding="utf-8"),
              separators=(",", ":"))

    clean = sum(1 for t in targets if t["plan"] and not t["plan"]["unresolved"])
    loops = sum(1 for t in targets if t["plan"] and t["plan"]["prior"])
    # a plan that switches on a rung one of its own scenes needs off is a
    # contradiction, not a plan; this should always print 0
    clash = sum(1 for t in targets if t["plan"] and t["plan"]["conflicts"])
    # A row must never ask for a position its own cap forbids, and must never
    # switch a modifier on and off at once. `off_rungs` only takes escapes the
    # run already satisfies, so this should always print 0.
    def rowbad(r):
        if r["min"] and r["cap"] is not None:
            allowed = set()
            for x in r["cap"]: allowed |= B.CASCADE_ON.get(x["var"], {x["var"]})
            if r["min"]["var"] not in allowed: return True
        st = {}
        for m in r["mods"]:
            if st.setdefault(m["var"], m["state"]) != m["state"]: return True
        return False
    caps = sum(1 for t in targets if t["plan"] and t["plan"]["setup"]["roster"])
    capbad = sum(1 for t in targets if t["plan"]
                 for r in t["plan"]["setup"]["roster"] if rowbad(r))
    gates = [s for t in targets if t["plan"] for s in t["plan"]["stats"]]
    print("targets      : %d" % len(targets))
    print("with a plan  : %d (%d fully resolved)" % (planned, clean))
    print("need earlier loops: %d" % loops)
    print("toggle clashes: %d" % clash)
    print("setup roster : %d plans (%d contradictions)" % (caps, capbad))
    print("affection gates: %d (%d run-scoped not covered)"
          % (len(gates), sum(1 for s in gates
                             if s["scope"] == "run" and not s["met"])))
    print("size         : %.2f MB" % (os.path.getsize("_analysis/app_data.json") / 1048576))
    print("elapsed      : %.1fs" % (time.time() - t0))

if __name__ == "__main__":
    main()
