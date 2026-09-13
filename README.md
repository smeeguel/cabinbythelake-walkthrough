# Cabin Loop Atlas

A walkthrough planner for **Cabin by the Lake 0.62d**, a Ren'Py visual novel by
Nunu. Pick a character and something you want unlocked — a corruption level, a
mail, or any of the 497 collection dots — and get back the corruption toggles to
set at the end-of-loop menu, plus a full timeslot-by-timeslot itinerary of the
exact choices to make.

Everything is derived by decompiling the game's shipped `.rpyc` bytecode and
analysing it statically. Nothing is hand-authored, so a new game version is a
re-run rather than a rewrite.

---

## ⚠️ Adult content — 18+

**The game this describes is an adult visual novel.** The tool names its scenes
and quotes its menu options and in-game hint text verbatim, so the generated
pages carry explicit sexual language throughout. Recurring themes include
pregnancy and breeding, lactation, body transformation, and hypnosis used as a
sexual mechanic.

It is **text only** — there are no images, no audio, and no game files anywhere
in this repository or on the published site. All characters are adults, and none
are related to the player character.

The published site opens on a landing page that says all of this and asks for an
age confirmation before it hands anyone on to the atlas itself.

## Not an official product

*Cabin by the Lake* is the work of its author, Nunu. **This is an unofficial fan
tool made by a player, and is not affiliated with, endorsed by, or connected to
the author in any way.**

No game assets — art, audio, script files, or the game itself — are hosted or
redistributed here. The repository contains only structural data derived from the
game's compiled scripts (scene and branch names, menu-choice text, and the
conditions that gate them) in order to describe how to play it. The game install
the pipeline reads from is deliberately excluded by `.gitignore`.

If you are the author and would like something changed or removed, please [open
an issue](https://github.com/smeeguel/cabinbythelake-walkthrough/issues) and it
will be dealt with.

---

## What's in the repo

| Path | |
|---|---|
| `index.html` | The landing page — disclaimer and age confirmation. Generated. |
| `atlas.html` | The app: one self-contained document, ~1.9 MB. Generated. |
| `_tools/` | The pipeline that builds both, plus its verification harnesses. |
| `robots.txt` | Nothing here asks to be indexed; both pages also carry `noindex`. |
| `CLAUDE.md` | The working notes' router: the rules, the build commands, and a map of what is where. |
| `_docs/` | The reasoning it routes to — how the game's loop works, how the analysis is done, and every landmine found along the way. |

Both built pages are tracked, unusually for generated output — GitHub Pages
serves what is committed, and nothing in the repo can rebuild them, since the
pipeline reads a game install that must never be committed here.

## Building

The build needs a copy of the game in `_game/`. See **Build pipeline** in
[`CLAUDE.md`](CLAUDE.md) for the full sequence; the short version is:

```bash
python _tools/rpyc_dump.py _game/game _decompiled   # decompile
python _tools/graph.py                              # scene graph
python _tools/ladders.py                            # corruption ladders
python _tools/mails.py                              # mail catalogue
PYTHONPATH=_tools python _tools/build_all.py        # plans
python _tools/make_template.py                      # assemble
python _tools/make_app.py                           # -> index.html + atlas.html
```

Then the checks, all of which must come back clean:

```bash
node _tools/smoke.js              # "failures: 0"
python _tools/verify_sessions.py  # "0 problems"
python _tools/probe.py            # "0 findings" at every width, both pages
```

## Licence

The tooling in `_tools/` and the generated pages' own markup, styles and script
are MIT-licensed — see [`LICENSE`](LICENSE).

**That licence covers this project's code only.** *Cabin by the Lake*, and the
in-game text quoted in the generated data, belong to the game's author and are
not licensed here.
