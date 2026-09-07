# Cabin Loop Atlas — working notes

A walkthrough generator for **Cabin by the Lake 0.62d** (Ren'Py, by Nunu). Pick a
character and something you want unlocked (a corruption level, a mail, any of
the 497 collection dots grouped as the end-of-loop checklist groups them, or any
of the 80 Memory/Dream replay tiles); get back the corruption toggles to set at
the end-of-loop menu and a full timeslot-by-timeslot itinerary of the exact
choices to make.

Everything is derived by decompiling the shipped `.rpyc` bytecode and statically
analysing it. Nothing is hand-authored, so a new game version is a re-run, not a
rewrite.

Published artifact: <https://claude.ai/code/artifact/44eee8cd-7c41-4ab5-89a6-e5b880a545d2>
Republish with the `Artifact` tool on `walkthrough.html`, passing that `url` if
you are in a different conversation.

---

## Layout

```
_game/                 the whole Ren'Py install (input, never modified)
_game/game/            the .rpyc files everything is derived from
_decompiled/           generated .rpy pseudo-source (145 files, ~238k lines)
_analysis/             generated JSON: graph.json, ladders.json, mails.json,
                       rewards.json, app_data.json
_tools/                the pipeline (below)
index.html             the shippable single-file app (generated)
walkthrough.html       the same app as an Artifact fragment (generated)
.gitignore             deny-by-default: the repo root is the game install
```

`_decompiled/` and `_analysis/` are build artifacts — safe to delete and regenerate.

**The app ships as two files that differ only in their wrapper.** `make_app.py`
writes both from the same bytes:

- **`index.html`** is a whole document — doctype, `<html lang>`, a real `<head>`.
  This is the one to host (GitHub Pages, Netlify Drop, itch.io), to open off
  disk, and to measure a layout against. Named `index.html` because that is what
  a static host serves from a bare URL; any other name is a rename to forget
  after every build.
- **`walkthrough.html`** is a **fragment**. The Artifact host wraps it in
  `<!doctype html><head>…</head><body>` at publish time, so it must not carry
  those tags itself. That is also why it is the wrong file to open anywhere
  else: with no doctype a browser renders it in **quirks mode**, which is not
  the layout the artifact shows.

**The game sits in `_game/`, not at the repo root.** The whole Ren'Py
distribution moved there in one piece — `game/`, `lib/`, `renpy/` and the four
launchers — so the exe still finds its data directory beside it and saves are
untouched (Ren'Py keys the persistent save folder on `config.save_directory`,
not on the install path). Only a desktop shortcut to the old location would
break.

`.gitignore` is deny-by-default (`/*`, then `!` for the handful of paths the
atlas owns). `_game/` is 2.1 GB, GitHub refuses a push over 2 GB, and `git add
-A` is one keystroke. Both built HTML files *are* tracked, unusually for
generated output — Pages serves what is committed, and nothing in the repo can
rebuild them, since the pipeline reads `_game/game/`.

---

## Build pipeline

Run in order, from the project root. Everything but step 5 takes a few seconds;
step 5 takes about two and a half minutes, nearly all of it `chase_gate`
(`CHASE_ROUNDS` × `CHASE_TRIES` per gate — see landmine 60).

```bash
python _tools/rpyc_dump.py _game/game _decompiled   # 1. decompile -> _decompiled/*.rpy
python _tools/graph.py                        # 2. scene graph -> _analysis/graph.json
python _tools/ladders.py                      # 3. ladders     -> _analysis/ladders.json
python _tools/mails.py                        # 4. mails       -> _analysis/mails.json
python _tools/rewards.py                      # 4b. rewards    -> _analysis/rewards.json
PYTHONPATH=_tools python _tools/build_all.py  # 5. plans       -> _analysis/app_data.json
python _tools/make_template.py                # 6. assemble    -> _tools/template.html
python _tools/make_app.py                     # 7. inline data -> index.html + walkthrough.html
node _tools/smoke.js                          # 8. verify      -> "failures: 0"
python _tools/verify_sessions.py              # 9. verify      -> "0 problems"
python _tools/probe.py                        # 10. verify     -> "0 findings" x7
```

Step 5 needs `PYTHONPATH=_tools` because `build_all` imports `build_app_data`
and `plan` as modules. Steps 6–7 are independent of 1–5; if you only touched the
UI, run 6, 7, 8, 10. Step 9 reads `app_data.json`, so it only needs 1–5.
Step 4b must run **before** step 5: `build_app_data` loads `rewards.json` at
import time, beside `mails.json`.

### The tools

| File | Role |
|---|---|
| `rpyc_dump.py` | Ren'Py 7.4.8 `.rpyc` → readable pseudo-`.rpy`, including SL2 screens |
| `graph.py` | Builds the label/screen graph: containers, edges, events, per-slot routes |
| `analyze.py` | Older exploratory extractor. Only `context_chain` is still used (by `ladders.py`). Safe to keep as a scratch tool. |
| `ladders.py` | Extracts each character's corruption ladder (var → display name) and unlock sites |
| `mails.py` | Extracts the phone mail catalogue: `<Char>SMS<n>` → name, variant, in-game hint, grant sites |
| `rewards.py` | Extracts the phone's Memories and Dreams galleries: 80 replay tiles → name, hint, unlock condition, split into corruption cross-links and a plannable residue |
| `build_app_data.py` | Shared vocabulary: scene names, branch names, condition prettifying, boolean flattening, requirement parsing. Also `build_targets()`. |
| `plan.py` | The planner: backward chaining + slot scheduling |
| `build_all.py` | Driver: targets × planner → `app_data.json` |
| `make_template.py` | `_head.html` + `_app.js` → `template.html` |
| `make_app.py` | `template.html` + `app_data.json` → `walkthrough.html` (the Artifact fragment), and the same bytes wrapped in a real document as `index.html` |
| `smoke.js` | Drives the real app JS in a DOM shim: `renderPlan` for every target, then the whole rail (`render`/`visible`/`renderList`/`itemBtn`) for every character × tab. Catches runtime errors |
| `probe.py` | Layout check: sweeps 90 targets at seven viewport widths and reports every box wider than the screen. See **Phones** |
| `verify_sessions.py` | Replays every shipped trance path against the raw `.rpy`, with its own parser. See landmine 55 |
| `preview.js` | `node _tools/preview.js <Who> <kind> <id>` → `_analysis/preview.html` pre-selected, for screenshots. Reads `index.html`, not the fragment — a doctype-less page screenshots in quirks mode |

**Edit `_head.html` (markup + CSS) and `_app.js` (logic). Never edit
`template.html`** — `make_template.py` overwrites it.

### Screenshotting

Headless Chrome works and is the fastest way to check a layout:

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless --disable-gpu \
  "--screenshot=D:\path\out.png" --window-size=1400,1600 --hide-scrollbars \
  --virtual-time-budget=4000 "file:///D:/.../\_analysis/preview.html"
```

Add `--blink-settings=preferredColorScheme=1` to force light mode; headless
defaults to dark, so the light palette will not be exercised otherwise.

---

## How the game works

This is the domain knowledge that makes the analysis correct. Most of it is not
obvious from the source and cost real effort to establish.

### The loop

The game is a Groundhog-Day weekend. `label dayhandler` in
`_decompiled/screenDayhandler.rpy` dispatches on `dateVar`, and **that table is
the authoritative slot order**:

| dateVar | slot | | dateVar | slot |
|---|---|---|---|---|
| 1 | Friday Noon (car ride) | | 12 | Saturday Midnight |
| 2 | Friday Afternoon | | 13 | Sunday Early Morning |
| 3 | Friday Evening | | 14 | Sunday Morning |
| 4 | Friday Night | | 15 | Sunday Noon |
| 5 | Friday Midnight | | 16 | Sunday Afternoon |
| 6 | Saturday Early Morning | | 17 | Sunday Evening |
| 7 | Saturday Morning | | 18 | Sunday Night |
| 8 | Saturday Noon | | 19 | Sunday Midnight |
| 9 | Saturday Afternoon | | 20 | Monday Early Morning |
| 10 | Saturday Evening | | 21 | Monday Morning |
| 11 | Saturday Night | | 22 | `endRun` — end of loop, mail arrives |

You visit **one location per slot**. At the end of the run you spend collected
corruption at the end-of-loop menu, then the weekend restarts.

`gateFirstRun` is the first-playthrough flag. It starts `True` and the first
end-of-loop menu clears it permanently, so it is **always False in any run this
tool describes**. Eight slot labels open with `if gateFirstRun: jump
d<n><time>Default`, and nine of those Default scenes have no other way in — they
are the untainted first weekend and are not routable. `graph.py` marks such an
edge `firstRun` and never walks it.

### Some slots cost nothing, and one or two cost double

`dayhandler` spends a sitting by doing `dateVar += 1` *before* it dispatches. So
a scene that does `dateVar -= 1` on the way in is played and then hands the slot
straight back: the map for that timeslot is still to come. That is the whole
mechanism behind the game's **automatic events** — the Saturday wake-up crawls,
Haily's packages, the Sunday-night bedcrawls. They fire on their own at the top
of the slot, cost the player nothing, and still pay their Love, Mood and quest
items.

There are three shapes, and all three are read off the same `dateVar` arithmetic:

| where the `dateVar -= 1` sits | effect |
|---|---|
| in the slot label, before `jump <scene>` | automatic: no map click, no slot spent |
| unconditionally inside the scene | the scene is free however you entered it (`LinaC3Invite`, the five Lina wing-girl invites, `HailyPackage2`) |
| under a menu choice | that exit is free (the "Leave" option in every explorable room) |

The reverse exists too: `resolutions` and the hot tub's "Get thrown onto a bed
(Advances Time)" do `dateVar += 1`, so they eat the following sitting as well.

41 entrances are automatic, covering 36 scenes; 21 of those scenes pay a
run-scoped tally.

### Explore mode, and why most of it is free

Every timeslot map carries an **Explore** button (`ui/exploreoff_%s.png` in
`screen CommonMapOverlay`) that jumps to `exploreholder` → `screen exploremap`, a
second map over the same ten hotspots whose buttons open the ten *rooms* in
`sceneRooms.rpy`: `YourRoom`, `KitchenRoom`, `MasterRoom`, `LivingRoom`,
`BathRoom`, `GardenRoom`, `ForestRoom`, `LakeRoom`, `TwinBedroomRoom`,
`cBedroomRoom`. This is where the urn shards, the tarot cards, the King of
Hearts, Lisa's suitcase clue and the stolen panties live. `graph.py` makes
`exploremap` a root with `dateVar: 0`, so a room is reachable at every slot.

All ten rooms are one shape, and the shape is what makes them cheap:

```
label GardenRoom:
    label GardenRoomLoop:        # nested, so not a top-level container
    menu:
        "Search":  ...  jump GardenRoomLoop      # back to the menu
        "Leave":   $ dateVar -= 1                # the sitting, handed back
                   jump dayhandler
```

So a visit that only takes options returning to the room's own menu — search the
garden, dig up the Hermit tarot card, leave — **costs nothing**: `dayhandler`
spends the slot again and the player is back on the same timeslot's map. Several
Explore trips, and then a real scene, can all happen in one sitting.

Options that jump *out* of the room do forgo that refund and cost the slot like
any other scene: `LivingRoom`'s "Read the Red Book", `cBedroomRoom`'s "Cassidy's
panties", `TwinBedroomRoom`'s "Jenny's luggage", `MasterRoom`'s white suitcase,
`YourRoom`'s "Call Haily". Twelve containers are reachable *only* through
Explore: the ten rooms plus `HailyText1` (behind "Call Haily") and `linmessage0`
(behind `MasterRoom`'s Search).

The menu loop-back is the whole signal, and it has to be checked. `AlexForest1`
and `fuckfest` also have a refunding menu option, but nothing in them returns to
their own menu — the options fall through to a plain `jump dayhandler` at the
bottom of the scene — so their sitting is spent whatever the player wanted.
See `plan.py:exit_dv` and landmine 46.

### What survives a reset — the single most important fact

| State | Resets? | Where |
|---|---|---|
| `tempFlags[...]` (branch/decision flags) | **Never** | no reset exists anywhere |
| `commonEvents` (quest items) | Every loop | `script.rpy:413` |
| `<char>Love` | Every loop | `script.rpy` reset block |
| `cassidyLove` | Halved each loop | same block |
| `<char>Horny` | **Every timeslot** | `screenDayhandler.rpy:39-47` |
| `linaNerve` | Recomputed | counted from `activeCorruption` at the end-of-loop menu |
| `gateFirstRun` | Cleared for good | `sceneEndChoices.rpy:71` / `script.rpy:713` |

Consequences the planner depends on:

- A prerequisite that only sets a `tempFlag` **can be done in an earlier loop**.
  This is what makes otherwise-impossible chains feasible.
- Quest items and Love **must be earned in the same run** as the target.
- Horny **cannot be banked at all** — it must be raised inside the very timeslot
  that tests it.
- `linaNerve` is cross-run meta-progression, not something a run plan can affect.

### Corruption variables

Two variables per rung:

- `<char>CorruptionN` — **`False` means unlocked.** Defaults are `True` (locked).
  Exception: `...Moonstone` is inverted (`True` = unlocked), default `False`.
- `<char>CorruptionNOn` — whether it is switched on for the coming run.

Display names come from the end-of-loop menu screens. Per-character panels
(`sceneEndChoicesAlex.rpy` …) take priority over the legacy combined
`sceneEndChoices.rpy`. The reliable anchor for a rung's name is the guard
`if <var>On:` immediately above the `_textbutton` — the `SetVariable` cascades in
the button's action list are ordered differently per character and will mislead you.

### Corruption records

`totalCorruption` holds every unlockable; `addCor(...)` grants one. Format:

```
sceneID|t|tier|c|character|s|style|p|pregBool|f|pegBool|n|display name
```

`style` is Green/Red/Gold/Blue (the token icon). `addCor` is a no-op unless the
value is already in `totalCorruption`, so the `totalCorruption.add(...)` calls in
`_Init` blocks are the true catalogue — all 498 of them, and they are what the
**Events** tab lists, one row per record. `build_app_data.read_catalog()` reads
them; `parse_record()` splits one; `grant_sites()` indexes the `addCor` calls by
the exact string they award.

Three consequences the extraction depends on:

- **The record string is the identity, not the name.** Two dots can share a
  character, a name and a tier and differ only in the scene that pays them —
  Alex's Corruption 2 "Blowjob" is paid by *Moisturizing Alex* and by *Share Bed
  with Alex*, and there are 14 such pairs. Keying on anything shorter merges
  them and hides one.
- **The scene id is the MapBook page the dot is drawn on, and is not the label
  the `addCor` sits in.** "Photoshoot" is granted inside `AlexForest1` and files
  itself under `AlexForest1Photos`, "Forest with Alex (Photos)". `sname()`
  resolves all 251 distinct record scene ids.
- **Six records in 0.62d can never be earned.** The checklist and the line meant
  to award them spell the record differently — a scene id (`JennyGardenPregHypnosis`
  vs `linaAssertSnug` for Lina's "Pillow Fort") or a `p|` flag (the three
  `skippingstonespreg` ones) — and `addCor` ignores a record it does not already
  hold. They are listed with no plan and a line saying why, because the
  checklist still draws them. The mirror also exists: 16 `addCor` values are not
  in the catalogue at all, so a grant site matched by name rather than by string
  can plan a run for a dot that will not light.

Records named `New Mail: …` are the mails **that also pay out a token**. They are
not the mail catalogue — see below — but they *are* dots, so they are listed in
Events as well, flagged `mailDot` and shown as "New Mail: <name>".

**`tier` is a row on the end-of-loop panel, and the rows are not numbered 0-6.**
Every `sceneEndChoices<Char>.rpy` heads them `Uncorrupted:` (t|0),
`Corruption 1:`..`Corruption 5:` (t|1-5) and `Corruption Preg:` (t|6, drawn only
`if optionPreg`). Uniform across all eight per-character panels. So a badge
reading `C0` or `C6` names a row the game does not have, and roughly a third of
the targets carrying a tier sit on one of those two. `tierLabel()` in `_app.js`
is the single place that maps it, and it is also what heads each block of the
Events list. The player-facing word throughout is
**Corruption** — never "tier" or "level" — so the app's badges are `C1`..`C5`,
`C4-M`/`C4-D`, `Uncorr` and `Preg`.

The four styles are the game's own categories, spelled out in the MapBook's
**Key** sidebar (`screenMapBook.rpy:194-199`): Red = Sex, Green = Plot, Gold =
Unlock, Blue = Loop Event corruption points. The player meets them as pips —
hollow or filled — on each MapBook scene page, in the per-tier checklist on
every end-of-loop character panel, and in the phone-log line `addCor` pushes.

**The token is not the mail's, so the app does not badge a mail with it.**
`build_targets` folds a `New Mail:` record's `style`/`tier` onto the matching
mail, but the record and the `<Char>SMS<n> = True` are two rewards paid by the
same act: completing the path gives you a collection dot *and* a letter. Badging
the letter with the dot's colour states a relationship backwards, and the match
is by (character, name) rather than by grant site, so three records land on two
mail variables each (`AlexSMS20a`/`20b` both wore one "Underboob" token). The
fields stay in the data; `_app.js` shows the swatch and the token pill for
`kind === "unlock"` only. The borrowed `tier` **is** shown on mails, as the
`C4` list badge and the "Corruption 4" pill: unlike the style, it answers a
question the player is actually asking — which corruption this mail is filed
under — and it agrees with the mail's own in-game hint ("Corruption 4+: …").
The fold is taken from the catalogue, not from the grant sites, so a record the
game can never register lends nothing: Lin's "One for All" is granted by a
string `totalCorruption` does not hold, and its mail is left unbadged. That
leaves 99 of the 173 mails badged, so a mail with no badge means "no record
says", not "no requirement".

### Memories and Dreams — the replay galleries

The phone's end-of-loop panel draws **five** collections, not three: Corruption,
Mail, Events, and the two galleries of replay tiles. They are **not** a third and
fourth copy of the Mail system, and the difference decides the whole design:

- **No per-item boolean.** Mail is 175 `default <Char>SMS<n> = False`
  declarations. A Memory or Dream has none — its identity is the
  `Jump("<label>")` on its thumbnail.
- **No grant site, no `PushToLog`, no end-of-run sweep, no cheat layer.** A tile
  is unlocked when a *condition* holds, evaluated live as the panel draws.
- **Not reachable in a run.** All 80 scenes exist as containers and have **zero
  routes from any of the 39 roots**. They are replay tiles, not scenes you visit
  during a weekend.

So a tile's "plan" is a **prerequisite plan**, not an itinerary to the scene.

Both are inline sections of the `elif endmenuchascreen == "rewards":` branch of
each `screen endmenu<Char>`, one screen below the `use mail<Char>` call
`mails.py` parses. Section headings are a uniform literal —
`Text " Memories " size 18 at truecenter`, likewise `" Dreams "` — and **position
between those two headings is what says which gallery a tile is in**. That also
excludes the Mail panel Cassidy, Lin and Lisa fold into the same screen, which
sits above the Memories heading.

**40 Memories + 40 Dreams across 9 characters.** Per character (Mem/Dream):
Alex 3/6, Carla 6/2, Cassidy 4/5, Haily 7/4, Jenny 5/6, Lin 5/4, Lina 2/3,
Lisa 3/4, Sami 5/6.

Every distinct guard across all 80 falls into six families, and the planner
already models five of them:

| Guard shape | Fact | Treatment |
|---|---|---|
| `not <char>CorruptionN` (22 rungs) | — | **cross-link** to the existing `cor:<var>` target |
| `tempFlags["id"] >= 2` | `("branch", id)` | real itinerary |
| `<char>Love >= 6` | `("stat", var, 6)` | run-scoped gate, `chase_gate` earns it |
| `optionPreg` / `optionPegging` | `("option", …)` | setup card; both `default True` |
| `worldCorruption >= 80/100` | `("world", n)` | `setup_world`, reported |
| `csv` | `("flag","csv")` | granted at `sceneC4Cassidy.rpy:2581` |
| `True` / absent (24 tiles) | — | already available |

`endCyclePhone` is the plan's anchor, and it is right twice over: the panel
really is drawn at the end-of-loop menu, and `<char>Love` resets every loop, so a
`Love >= 6` gate must be met **by the end of the very run whose phone you are
checking**. dateVar 22 is exactly that deadline. The plans therefore end on a
step reading only "Checking your phone", the same shape mails granted by the
end-of-run sweep already produce.

### Sessions — the hypnosis scenes

Three scenes are built the same way and nothing else in the game is:
`JennyGarden1Hypnosis`, `JennyGardenPregHypnosis` and `LisaHypnosis`. Each opens
by zeroing its counters, runs **four `menu:` blocks back to back — one pick from
each** — and then reads the total once at the end to decide which command lands.

Jenny's two run **two counters side by side**. Nothing in the source names them:
they are `hypnosisA` and `hypnosisB`. But the blocks they gate say who is who —
`hypnosisA` pays `jennyLove` and Jenny's corruption records, `hypnosisB` pays
`linaLove`, `linaBE` and `LinaSMS27`. So `hypnosisA` is **Jenny's trance** and
`hypnosisB` is **Lina's**, sitting beside her and catching it. In `LisaHypnosis`
`hypnosisA` is Lisa's, which is why the attribution has to be scoped to the
session's own labels rather than counted globally.

Every option moves both, and often in opposite directions: `"Shooom Shooom
Shooom"` is −1 Jenny and +2 Lina. So the two are in genuine tension and the four
picks are one path, not a bag of points.

Then the multipliers, which decide whether a threshold is reachable at all:

| where | what |
|---|---|
| `JennyGarden1Hypnosis` only | `hypnosisA *= .5` unless Jenny is Prey or Predator — **not** truncated, so the counter can hold 2.5 |
| all three | `hypnosisA/B = int(x * 1.5)` if `HypnosisLesson or cassidyCorruption4On` |

The picks alone top out at 8, so **anything wanting 10 needs the ×1.5**, which
means either playing `CassidyHypnosisLesson` or switching Cassidy·Open on (and
her rung is padlocked on another girl being at her top rung — landmine 28). And
in Jenny's first session anything wanting more than 4 needs Prey or Predator on
to escape the halving. Both are real requirements, and `Plan.fix_session` chases
them like any other.

The counter outlives the label that built it: the session jumps to its own
`…Part2` and on into `linahypbj`, and the threshold is read there. `SESSION_AT`
walks forward from each session so a step lands on the picks that decided it.

**Some pairs of thresholds cannot be met in one sitting.** `New Mail: Bathing`
wants Jenny's trance at 10 *and* Lina's at 10, and no path reaches both — the
counters are zeroed on the way in. It is two visits, and it works only because
the two halves are `tempFlags`, which nothing resets. `Plan.add_visit` splits a
visit whose thresholds are jointly unreachable rather than claiming a pick path
that does not exist.

### Mails

The catalogue is the per-character booleans `<Char>SMS<n>`, declared as
`default <Char>SMS<n> = False` in `sceneEndPhone.rpy` (175 of them). Deriving
mails from `addCor("… New Mail: …")` instead finds only 103, because most mails
never award a token — Alex has 31 mail variables and 11 records.

Three things live only in the phone's Mail panel, inside each
`sceneEndChoices<Char>.rpy` (`screen mail<Char>:` for six of the girls; folded
straight into `endmenu<Char>` for Cassidy, Lin and Lisa):

- the **display name** — `Text "Underboob"` under a bare `if <var>:` guard
- the **in-game hint** — `Tip="…"` on the locked padlock button, which is the
  author's own description of how to earn it
- the **variant grouping** — a name cell guarded `if A or B:` covers two or four
  variables that are the same mail rewritten (usually a breast-expansion
  version). `AlexSMS17a`–`17d` share one cell four ways.

`mails.py` parses that panel, but takes each mail's *name* from the
`PushToLog`/`addCor` beside its grant, because only the announcement
distinguishes variants (`Mountains` vs `Mountains+`). Nearest line wins:
variants sit two or three lines apart in one if/else, so a widening search hands
a mail its sibling's name.

Grants come from two places:

1. `$ <Char>SMS<n> = True` inside a story scene, next to its `PushToLog`.
2. The end-of-run sweep at the top of `label endCyclePhone`, which awards mail
   from conditions evaluated once the weekend is over. That is dateVar 22, so it
   routes and plans like any other site; such a plan ends on a step that says
   only "Checking your phone".

Two sites must be ignored: `label cheatSMS1`/`cheatSMS2` in `sceneEndChoices.rpy`
(the unlock-everything cheat menu) and the save-shuffling at the top of
`Phone_Init`. `mails.py` records file+line for each real grant and
`build_app_data` matches graph events against exactly those.

`not AlexSMS4` guards a mail against being granted twice. It is bookkeeping, not
a player instruction, so `plan.py:negatives()` drops it from the "avoid" list.

### Decision flags

`flowVar(id, minval)` does `tempFlags[id] = max(minval, existing)`.

- `3` = the choice was taken
- `1`–`2` = the choice was offered/seen
- `0` = declared

Two naming sources, both needed:

1. **The scene that owns a branch id** comes from `label <Scene>_Init:` blocks,
   which declare every `flowVar` the scene uses alongside its own
   `sceneNameConv[...]` entry. This is exact.
2. **The player-facing text of a branch** comes from the in-game MapBook screens,
   which render each node as
   `Text "<choice text>" style choiceStyleHandler(tempFlags["<id>"])`.

### Scene names

`sceneNameConv["<label>"] = "<name>"` is the author's own table and covers 307
scenes. It is not the only source, and on its own it left a quarter of all plan
steps showing a raw dev label. Two more, in `sname()`'s order:

1. **The MapBook page title.** Every scene the phone can show has a
   `screen map<Scene>:` whose tree grid opens with the scene's title (474 of
   them). It is drawn three different ways — `Text … style "gridtextbold"`,
   `style "gridtexton"`, or a `_textbutton` inside a `Window` — so `book_title`
   anchors on the *first Text/textbutton widget in document order*, not on the
   style. Everything before it is `ui/treeblank.png` spacer art. Where both
   sources exist they agree on 252 of 287 names and the rest differ only in
   wording, so `sceneNameConv` keeping priority costs nothing.
2. **`currentScene`.** A sub-label that owns no page of its own says which page
   it belongs to by setting `$ currentScene = "X"` (402 labels do). That is what
   makes `HailyPackageWatch` "Mysterious Package: Saturday". The variable
   persists until something reassigns it, so a label that never sets one
   *inherits* it along its incoming edges — `HailyPicnicSuccess` is part of
   "Haily's Picnic" — accepted only when every way in agrees, so a sub-label
   shared by two scenes stays unnamed rather than taking one caller's name.

Together these leave 29 steps out of 1511 on a raw label. Do not extend this by
voting on which MapBook page mentions a scene's branch ids: pages cross-reference
each other's flags, and the vote confidently renames `d3eveningDefault` to
"Searching for Haily".

### Map locations

The cabin map is imagebuttons over ten hotspots, and the only thing naming one is
the glow art it draws:

```
_imagebutton auto "ui/glow garden_%s.png" focus_mask True action Jump("HailyText3") at gardenbutton
```

`at gardenbutton` is *not* reliable — exploremap's Forest button has no `at`
clause — so `graph.py` reads the image and hangs `place` on the edge (241 of
3570 carry one). `place_for` takes the first place along the route, because
that is the click the player makes: a picker menu or a scene that jumps on to
another all happen inside the room already entered. The ten tokens are garden,
lake, forest, livingroom, kitchen, bathroom, yourroom, cbedroom, twinroom,
masterbedroom; `B.PLACENAME` gives their display names.

159 non-automatic steps have no place, and that is correct — `endCyclePhone`,
the scripted slots (the dinners, the car ride, Monday morning) and the
free-but-not-automatic scenes like `LinaC3Invite` are jumped into from the slot
label with no map in between. The app shows the chip only when there is one.

---

## Pipeline internals

### 1. Decompiler (`rpyc_dump.py`)

`.rpyc` is `RENPY RPC2` + slot table; slot 1 is zlib-compressed pickle
(protocol 2, written by Python 2). It is unpickled with a stub `find_class` that
fabricates placeholder classes, then the AST is rendered back to pseudo-source.

Four classes need real implementations or unpickling fails:

- `PyExpr` — a `str` subclass pickled via `NEWOBJ`, so it must be a **type**
  accepting `(s, filename, linenumber)`, not a function.
- `PyCode` — `__getstate__` returns `(1, source, location, mode)`; unpack index 1
  for the source or you get a raw tuple where code should be.
- `RevertableDict` / `RevertableList` / `RevertableSet` — must subclass
  dict/list/set *and* accept instance attributes, so plain builtins won't do.

Screens are `renpy.sl2.slast` trees, rendered separately by `sl_render`. Without
this the MapBook files decompile to empty stubs and you lose all branch names.

The output is **pseudo-source for analysis, not runnable Ren'Py.** It is
indentation-faithful, which is what every downstream regex relies on.

### 2. Graph (`graph.py`)

Parses `_decompiled/*.rpy` into an indentation tree and emits:

- **containers** — every `label X:` and `screen X:` (2071)
- **edges** — `jump`/`call`/`Jump("X")` with the guard stack that reaches them
  (3570), each carrying `dv`, the net `dateVar` delta already applied on the path
  to that jump, `firstRun` when only a brand-new save can take it, and `place`
  when the jump is a map hotspot (241)
- **events** — things that happen, each with owner + guard stack (14215):

  | type | meaning |
  |---|---|
  | `cor` | `addCor(...)` — an unlock is granted |
  | `flag` | a `...Corruption...` variable assignment |
  | `setflag` | any other bool assignment |
  | `branch` | `flowVar(id, n)` / `tempFlags[id] = n` |
  | `item` | `commonEvents.append("...")` |
  | `stat` | `<stat> += n` — the affection vars plus bare `mood`, with `op` kept |
  | `note` | `PushToLog(...)` mail/unlock messages |
  | `time` | `dateVar += n` / `-= n` — the sitting spent or handed back (76) |

- **routesByRoot** — one BFS per timeslot: `root → container → [edge indices]`,
  ranked on `(hops, dateVar cost)` so a scene reachable both automatically and by
  a map click is recorded by the entrance that does not spend the slot
- **sceneNames / mapBook / currentScene** — the three naming sources above
  (307 / 474 / 402 entries)

Roots are the 21 slot labels plus their map screens, `exploremap` (day 0 =
reachable at any slot) and `endCyclePhone` (dateVar 22). `dayhandler`, `dayInit`
and the other loop hubs are **blocked** as transit nodes — routing through them
teleports between unrelated days and produces nonsense paths. Roots are also
never routed *through*, only entered.

### 3. Ladders (`ladders.py`)

Corruption rung names and the sites that unlock them.

### 3b. Rewards (`rewards.py`)

The Memories/Dreams panel walk, and the condition splitter that keeps the blast
radius at zero.

A **tile** is the minimal subtree holding both a `Jump(...)` and a
`Text "..." size 14` caption. Anchoring on the box instead loses four of the
eighty — see landmine 72. Within a tile:

- the **name** is the caption in the *unlocked* branch, never the `???` else;
- the **condition** is the positive guard stack down to that caption, which is
  the outer `if` wrapping the tile conjoined with the inner one on the
  imagebutton (several tiles have both);
- the **hint** is the `Tip=` on the padlock button — the author's own words;
- the **identity** is `(char, section, jump target)`, deduped per tile.

`split_cond` then divides the condition in two, and **this split is the whole
design**. `not alexCorruption5` is a *positive* requirement — the game's
corruption unlock vars are inverted, so `False` means unlocked. The obvious
implementation is to teach `atom_facts` an `("unlocked", var)` fact, and it is
the wrong one: that shape appears in scene guards throughout the game, so
minting a fact for it would change every one of the 732 pre-existing plans. So:

- conjuncts matching the unlock shape → `requires`, cross-links the planner
  never sees;
- the residue → a synthetic `{"type":"reward","owner":"endCyclePhone"}` event
  whose guards the planner reads like any other site's.

The planner therefore only ever sees conditions it already understands. No
change to `atom_facts`, `resolve`, `fact_cost`, `describe` or `atom_ok`, and the
732 existing plans stay **byte-identical** — which is the regression tripwire
(see landmine 73).

### 4. Vocabulary (`build_app_data.py`)

Shared helpers used by the planner. The important ones:

- `clean(s)` — strips Ren'Py text tags (`{image=...}`) from menu labels and
  unwraps MapBook titles broken across grid cells (`"Unloading\nCar"`)
- `sname(label)` — scene name: `sceneNameConv`, then the MapBook page title, then
  the same two through `currentScene` (own or inherited), with
  `d<day><time><place>picker` → "the Garden". See **Scene names** above
- `place_name(tok)` / `context(label)` — the map hotspot's display name, and a
  label's MapBook context
- `temp_desc(id)` — branch id → scene + player-facing choice
- `flatten(conds)` → `(conjunctive atoms, [alternative groups])`
- `pretty(cond)` — raw Ren'Py condition → readable text
- `pick_alts(route, known)` — choose which branch of an if/elif chain to report
- `SCORE_PARTS` / `SCORES` — a scene's on-the-spot tally read back to what each
  point is for. `SCORES` keeps only the counters with more than one contributor;
  `SCORE_PARTS` keeps them all, for naming the rivals in a contest (landmine 51)
- `SESSION` / `SESSION_AT` / `SESSION_CHAR` / `counter_name` — the hypnosis
  sessions: menus in order with both counters' deltas, the multipliers in source
  order with their `int()` truncation, every label a session's counters are
  still live in, and whose trance each counter is. See **Sessions** above

### 5. Planner (`plan.py`)

Backward chaining, then scheduling.

**Facts** are `("branch", id)`, `("item", name)`, `("flag", var)`,
`("stat", var, n)`, `("cor", var)`, `("world", n)`, `("option", name)`.
The first three are produced by *visits* (scene + choices); the rest are
end-of-loop setup or stat goals.

**Resolution** — `Plan.expand(owner, guards, …)` reads a site's guards, splits
them into hard requirements and OR-groups, and resolves each fact to a producing
visit, recursively (`MAXDEPTH = 6`). OR-groups try alternatives in cost order and
**roll back** via `snap()` / `restore()` if one fails, so a dead branch leaves no
residue. `resolve` takes the consuming visit so `stat` facts learn their deadline.
Two things come before the search for a scene to play: a **setup grant**
(`setup_grant`) — an unroutable site whose only conditions are end-of-loop
toggles, which is how Lisa's The Note hands every run the altered suitcase clue —
and, inside an OR-group, whichever alternatives `option_free` says the setup card
can pay for. Both are free; a scene is not.

**Sessions** — `solve_session` answers a hypnosis threshold outright rather than
reporting it. It enumerates the four menus (256 paths), applies the multipliers
the run can promise, and keeps the path that meets every threshold and leaves the
most on the other girl's counter. `fix_session` arranges what the picks alone
cannot reach — Cassidy's lesson, Jenny's Prey rung — and `joint_ok` decides when
two thresholds need two sittings. See **Sessions** above and landmine 54.

**Scheduling** — topological order, then a backward pass computing the latest
slot each visit may occupy, then a forward assignment. If the target cannot be
placed, persistent (branch-only) visits are demoted into earlier loops and it
retries. Demoted visits impose no ordering on this run, and their own
prerequisites are pulled into that earlier loop via a closure.
A prerequisite that costs **nothing** does not push its consumer to the next
slot: an automatic event is over before the slot's map is drawn and an Explore
trip hands the slot straight back, so `lo` stays at the producer's own slot. That
is what lets "steal the panties, then hide them" happen in one sitting. The
backward pass stays conservative (`latest[s] - 1`) — it only bounds how *late* a
producer may sit, so being a slot tight there never makes a plan wrong.

The forward assignment takes the **earliest** sitting a visit fits, with one
exception: a visit that **tests a run-scoped affection gate** takes the latest.
The stat is read the moment that scene begins, so every sitting before it can
bank affection and every sitting after it is wasted. Alex's Forest Handjob is
playable at Saturday Noon, Saturday Afternoon, Sunday Noon and Sunday Afternoon
and wants 4 of her Love; taking the earliest left seven slots to find it in and
the plan came up two short, while the latest meets it comfortably. The set is
read off `Plan.stats` (`{consumers of a run-scoped var}`) inside `schedule`, so
it grows as expansion discovers more gates. Everything else still takes the
earliest slot — that is what leaves room after it for its own consumers.

**What to avoid** — a step's `avoid` list is the negative half of its
requirements, and it comes from two places. `negatives(v.guards)` reads the
scene's own guards; `nav_negatives` reads the map route's, which is where the
game's `elif` chains live — reaching a scene often means the branches *above* it
did not fire. The route's guards are mostly rung negations the setup card has
already answered, so each one is put to `atom_ok` first and only what the run
cannot guarantee is reported. See landmines 49 and 50.

**Slot cost** — `visit_cost(label, dv, choices)` is
`1 + route_dv + scene_dv + exit_dv`, floored at 0: the sittings a visit actually
occupies. `route_dv` sums the `dv` of the alternatives `pick_alts` picks (not just
the ones BFS happened to record, or the plan would be costed from a branch it is
not taking), and `scene_dv` adds the deltas inside the scene that are certain —
unconditional, or hanging off a menu pick this visit is making anyway. A cost-0
visit shares its sitting with whatever the player then goes and does; a cost-2
visit reserves the slot after it as well.

`exit_dv(label, choices)` is the refund waiting on the way *out* of a scene the
visit never had to leave — the explorable rooms' "Leave" (see **Explore mode**
above). It applies only when all three hold: the scene offers a refunding exit
under a menu option, the scene loops back on itself (an out-edge to a label that
is *not* a top-level container, i.e. its own `<Room>Loop`), and the deepest menu
picks this visit makes return into that loop rather than jumping out. Judging the
*deepest* picks is what separates `cBedroomRoom` + "Search" (free) from
`cBedroomRoom` + "Search" → "Cassidy's panties" (jumps to `dayhandler`, costs the
sitting), while still letting `MasterRoom` + "Search" be free despite its
conditional exits.

`is_auto` is the narrower question of whether the slot label jumps straight in,
which is what decides whether there is any map navigation to describe.
`is_explore(label, dv)` is the sibling question for the other direction: the
route into this scene is the `exploremap` (dateVar 0) one rather than the
timeslot's own map, so the step is a three-part instruction. Both are put on the
step (`auto`, `explore`) and they are mutually exclusive — an Explore route has
`route_dv == 0`.

**Stat top-up** (`stat_topup`) fills spare slots with scenes that raise a
required stat, honouring `stat_scope`:

- `run` — bankable; only gains at slots **strictly before** the deadline count
- `slot` — `*Horny`; must be raised inside the gated scene itself
- `meta` — `linaNerve`; cross-run, nothing a plan can do

A candidate is a **route**, not a single bump: a scene plus the menu picks that
reach it. `route_gain` totals everything the route pays into the stat —
`AlexForest1` pays +1 for the choice and another +1 inside it — and every bump
is put to `guards_ok`, so conditions the run cannot promise contribute nothing.

Routes are then ranked by:

1. **the biggest boost to the stat we are short of**, among routes the run can
   actually reach (`route_ok`) and whose menu option it can promise;
2. **the highest total Love + Mood** on the same route, as the tiebreak — both
   are per-run tallies cleared at the reset (`combo_gain`), so a route that also
   pleases someone else is worth more than one that does not;
3. fewest playable slots, then scene name, so the result is deterministic.

The side gains are reported on the step (`side_gains`), which is why a top-up
reads `+2 Haily's Love, +1 Lisa's Love, +1 Mood`. `chase_gate` ranks the same
way, behind its own cost key — a boost that breaks the chain is no boost.

`chase_gate` is where nearly all of the affection now comes from (27 top-up
steps against 138 before it was widened), because a chased scene is a real
visit with its prerequisites expanded rather than opportunistic filler. It runs
`CHASE_ROUNDS` times per gate, adding at most one scene each round, and each
round tries `CHASE_TRIES` candidates before giving up. Both are budgets, and
both were far too small at 3: one round adds +1 in the common case, so a gate
wanting 5 could never be reached; and a cluster of same-cost candidates that all
need a rung the target forbids could eat a whole round without adding anything.
A chase stops at its first success, so the headroom costs a run with easy gates
nothing — 40 and 12 is about five seconds over the whole build and takes the
uncovered gates from 34 to 14. `fact_cost` scores a candidate's requirements;
see landmine 60 before touching it.

A candidate is ranked on six things, in `CHASE_ORDER`: what its own
requirements drag in, **whether it spends a sitting**, how much of this gate
it pays, how much of the run's *other* short gates it also pays, the rest of
the route's Love + Mood, and its name. Putting the sitting second is
deliberate and was measured: the same 14 gates end up short either way, but
the plans spend 95 fewer sittings, because three automatic +1s that fire on
their own beat one +2 that eats a slot. `also` is the other half of the same
idea -- most scenes pay several girls at once (“Let's wrestle” is +1 Alex and
+1 Haily, Saturday Breakfast is +1 Alex, +1 Lisa and +1 Mood), so a scene that
closes two gates beats one that pays the same into a single tally. A chased
visit reports its side gains on the row, the way a top-up always did.

### 6. App (`_head.html` + `_app.js`)

Vanilla JS, no dependencies. Data is inlined as
`<script id="data" type="application/json">`; `make_app.py` escapes `</` so the
payload cannot break out of the tag.

Design: night-lake palette, moonstone accent, Zilla Slab / Karla / IBM Plex Mono.
The four token colours (Green/Red/Gold/Blue) are reserved as data, and each
character's roster dot uses her real `who_color` from `characters.rpy`. Themed
for light, dark, and un-stamped system default — keep every colour token-defined
at `:root`, never only inside a media query.

The setup card is a **table**, one row per girl the run has anything to say
about, because the end-of-loop menu asks three separate questions per character
and a flat pill list ran them together into sentences that were wrong two ways
over. The columns are **Min corruption** (the ladder position to switch ON),
**Max corruption** (how far that ladder may go — shown only when something caps
it) and **Modifiers** (Package, Fertile, Pregnant, Prey — shown only when one
has to be on or off). A column is dropped entirely when no row uses it.

The cap used to be conveyed only by *not* listing a rung — indistinguishable, to
a player holding the menu, from "we had no opinion", and wrong often enough to
matter, because a girl one rung too high makes the game play a different scene.
Min and cap can never disagree: `off_rungs` only takes an escape the run already
satisfies, so the forbidden set is disjoint from the ON set by construction, and
`build_all` prints the count of violations as a must-be-zero tripwire.

`--on` and `--off` carry min and cap; the modifier pills reuse `.toggle` with an
`ON`/`OFF` badge. No new colour, and nothing added to the four reserved data
colours. Hovering a cap or an OFF modifier names the scene and slot that demand
it, and any other way round the run could have taken. See landmines 66-68 and
70; landmine 71 is why a clashing `avoid` pill is marked on the row as well.

Five tabs, matching the five collections the phone actually draws:
**Corruption** (the ladder rungs), **Mail** (the phone catalogue), **Events**
(the dots — every `totalCorruption` record), **Memories** and **Dreams** (the 80
replay tiles). The rail is only ~260px wide, so `.kinds` wraps
(`flex-wrap:wrap`, `.kind{flex:1 1 auto}`) rather than dividing into ~48px
buttons that clip "Corruption". Events is the big one,
497 rows against Jenny's 78, so it is not a flat list: it is grouped the way the
end-of-loop checklist the player is holding is grouped, **corruption row, then
scene**. `groupEvents()` walks the sorted list and emits a `.grp` heading per
tier (`tierLabel(n, true)` — "Uncorrupted", "Corruption 1".."5", "Corruption
Preg", with the row's count) and a `.sub` heading per `sceneName`. Both pin, at
`top:0` and `top:26px`, so a name halfway down the rail never loses either; both
need an opaque background *and* a `box-shadow: 0 3px 0 var(--sunk)`, because the
list is a 3px-gap flex column and a pinned heading does not paint its own gap.
Inside a scene the order is `seq` — the order the game's `_Init` block declares
the records — not the alphabet.

Selecting a row shows the same full plan every other target gets: the end-of-loop
toggles, any earlier loops, the whole weekend slot by slot, and the picks inside
the scene that reach the `addCor`. The header says where the dot lives in the
game's own terms ("A collection dot on the “Forest with Alex (Photos)” page,
filed under Uncorrupted"), which is the pair the player used to find it and the
pair they will check it off by. `sceneName` is in the search haystack too.

Lun is on the roster. She is not one of the girls — `addCor` gives her no mini
icon — but she owns one lore dot ("Circles"), and leaving her off hides it.

A Memory or Dream page is a different shape from every other target, because
what it needs is not always a weekend. Above the setup card sits
**`requiresCard`**: one clickable row per corruption rung the tile is gated on,
jumping to that rung's own Corruption-tab plan. It sets `state.who` as well as
`state.kind`/`state.id`, because `forWho()` filters by character and the rung
often belongs to a different girl — Lin's "Practice Date" wants *Carla's*
Corruption 4. An OR group renders as "either … or": Jenny's Maiden and Devourer
are alternative tops of one ladder. Five links stacked (Sami's "All Tied Up") is
five separate runs, and inlining five weekend itineraries whose setup cards
contradict each other would say nothing true — one target still means one run.
The card's lead says outright that **unlocking is not switching on**, or a page
reading "unlock Carla · Pregnant" above a setup row reading "Pregnant OFF" looks
like it contradicts itself when it does not (landmine 68's distinction again).
The 46 tiles with no residue have no plan and end on a one-line verdict:
"Available now" for the 24 that are ungated, "unlock the corruptions above" for
the rest. Where the author's `Tip=` disagrees with the guard — Jenny's dreams
are ungated but hinted "Corruption 4" — the guard governs and the hint is shown
as the author's stale note, marked as such. Same precedent as landmine 59: the
tab must agree with the panel the player is holding.

A step with `explore` set is rendered differently, because it is a different kind
of instruction — a mode you switch the map into, not a scene you click. It gets
`--explore` (a violet, deliberately clear of the four data colours and of the
moonstone accent) on the row's left edge, an `EXPLORE` pill in the header beside
the room, and its route line becomes one trail —
`EXPLORE → Twin Bedroom → “Search” → “Alex's luggage” → “Steal panties”` —
which folds in `step.choices`, so the separate `.picks` row is suppressed for
these rows rather than repeating them. Free Explore rows get the dotted left edge
that already marks a cost-0 step; the ones that do spend the sitting get a solid
edge and a note saying which option walks out of the room.

A step with `trance` set gets a panel of its own inside the row (`tranceBlock`),
because a chip row cannot carry an ordered path: the four picks are numbered,
each shows what it does to *both* counters, and the block ends on the totals it
reaches and on the multipliers being counted. It is deliberately quiet — a sunk
panel in the existing tokens, no new colour — because it sits inside a step
rather than beside one. A multiplier the run is not taking says nothing; a
halving says something either way, since a run that escapes it is switching
Jenny·Prey on for that reason and the setup card cannot explain itself.

A step's `avoid` list is **one quiet pill row**, not a stack (`avoidRow`). It
used to be a full-width red-barred `.warn` line apiece, and on a step with five
of them the negative half of the requirements outweighed the instruction it
belonged to — the scene name, the picks and the gains all sat under a wall of
red. Nearly all of it is already true before the player does anything: the setup
card fixes every toggle, and the route's `elif` negations are mostly rungs the
run never switches on. So it is metadata, and it is styled as such — the colour
is spent on the `AVOID` header alone and the pills are a step quieter than the
`.yield` gains row above them. Four pills are shown, truncated to 40 characters;
one `+N` button reveals the rest *and* the full text, using the same
`aria-expanded` idiom as `fold()`. The cap only applies from six entries up,
since hiding one pill behind a "+1" is worse than showing it. 83% of entries fit
a pill untruncated; the tail runs to 370 characters.

Two traps in shortening those strings. **`NOT (NOT x)` is a positive
requirement** — `not (not alexBurnt)` means Alex must *be* burnt out — so
stripping both negations and dropping the result under a header reading "Avoid"
states it backwards. `avoidPill` detects the second `NOT` and labels the pill
`must have …` instead (13 occurrences). And **the outer parens cannot be
stripped with a regex**: `(A) or (B)` would come back as `A) or (B`, so
`unwrapParens` checks that the leading `(` is the one the trailing `)` closes.
That normalisation is what makes `NOT “Read more” taken` and
`NOT (“Read more” taken)` — stored as two different strings, 24 and 30 times —
render as the same pill.

### Phones

The rule is that **nothing scrolls sideways**, and it is checked rather than
eyeballed. `python _tools/probe.py` renders `index.html` (the whole document —
measuring the fragment would measure quirks mode) in an
iframe of a chosen width, sweeps 90 targets through it and reports every box
wider than the viewport, at 320/360/412/480/640/768/900px. Every line must read
`0 findings`. The iframe is not decoration: headless Chrome will not open a
window narrower than about 500 CSS px, so an iframe — which carries its own
viewport, and so its own `@media (max-width:…)` evaluation — is the only way to
measure a 360px layout at all.

Three things were doing the damage, and each is worth knowing:

- **A bare `1fr` is `minmax(auto, 1fr)`**, so the widest unbreakable thing in a
  track — a scene name, a Ren'Py condition — becomes a floor the track cannot go
  under. `.shell`, `.row`, `.reqrow` and `.roster` all now spell out
  `minmax(0, …)`, and `.rail`/`.plan` carry `min-width:0`.
- **`overflow-wrap:anywhere`, not `break-word`.** Only `anywhere` shrinks an
  element's *min-content contribution*, and that contribution is what pushes the
  track wide in the first place. `break-word` looks identical and fixes nothing.
  It is set on `.plan` and `.rail` wholesale, which covers every quoted branch
  id and condition string at once.
- **`.item` had `width:100%` and, under a scene heading, `margin-left:10px`** —
  10px wider than the rail it sits in, which is a horizontal scrollbar in the
  Events list. The list is a column flex box; a row already stretches.

Two arrangements fold below their own breakpoints. The itinerary row stacks at
640px, and the status colour moves off `.slotcell`'s left border onto the whole
`.row` — in a stacked row the cell's border marks only the first line. The setup
roster stacks at 600px into a block per girl: `thead` goes away and each cell
repeats its column name through `data-label`, which `setupCard` sets from the
same `COL` object that writes the `<th>`s, so the two spellings cannot drift.
The cap and modifier tooltips become visible `.rwhy` lines there, because a
phone has no hover and that tooltip is the only place the card says *why* a girl
may go no higher.

Everything else is housekeeping: a `<meta name="viewport">` of its own (the
Artifact wrapper has one, a file opened off disk does not), `text-size-adjust`,
`dvh` beside every `vh`, `@media (pointer:coarse)` padding on every button, a
16px search field, and `revealPlan()` — under 900px the rail sits *above* the
plan, so tapping a row selects something a screen and a half below the finger.

---

## Landmines

Every one of these was a real bug. They will recur if the code is rewritten.

1. **If/elif chains reaching the same destination are alternatives, not
   requirements.** A map button often opens via four different conditions. Naive
   shortest-path reports whichever branch it walked as mandatory. `pick_alts`
   picks the branch consistent with what the target already needs.
2. **`A or B or C` is not three requirements.** `flatten` separates conjunctions
   (hard) from disjunctions (any-one-of). Getting this wrong turns one
   requirement into six.
3. **`not tempFlags[x] >= 3` is a negative requirement** — "must not already have
   done this" — not a positive one.
4. **Branch stems cannot be guessed by trimming digits.** `AlexForest10231`
   belongs to `AlexForest1`, not `AlexForest`. Use the `_Init` blocks.
5. **Map navigation carries the corruption and Love gates.** The scene's own
   guards do not mention them. The planner folds nav conditions back in and
   reschedules (up to 3 passes).
6. **Stat checks have deadlines.** A gain scheduled at or after the gated scene's
   slot is worthless. And see `stat_scope` above — Horny and Nerve are not
   per-run stats at all.
7. **A visit whose prerequisite failed to schedule must also fail.** Otherwise
   the scheduler silently emits a plan that violates its own ordering.
8. **Demoted (earlier-loop) visits must not constrain this run's windows** in the
   backward pass, or they make feasible plans look impossible.
9. **`commonEvents.append (` with a space** exists in the source. Regexes over the
   decompiled text need `\s*` in the obvious places.
10. **Menu labels contain `{image=...}` tags.** Always `clean()` before display.
11. **Some booleans start `True`.** `default GoodbyeEventCarla = True` means a
    condition on it is already satisfied on a fresh run; hunting for a producer
    invents work that does not exist. `DEFAULT_TRUE` in `plan.py` collects these
    from the `default` lines.
12. **Mails are `<Char>SMS<n>`, not `New Mail:` corruption records.** The records
    are the token-paying subset — under 60% of the catalogue, and only 11 of
    Alex's 31. See **Mails** above.
13. **A mail variant is named by the announcement beside its grant, and the
    nearest one wins.** `AlexSMS8` and `AlexSMS8b` sit three lines apart in one
    if/else; a widening search that takes the first `PushToLog` it finds gives
    both mails the name "Problem+".
14. **The panel's `if <var>:` name guard looks exactly like a button guard.**
    Match the name cell (guard immediately followed by a `Text`) first, or every
    display name is lost and mails fall back to their variable names.
15. **A condition the vocabulary does not recognise must not be dropped.**
    `atom_facts` returning `[]` used to mean "nothing to do", so `PuzzleHold >= 4`
    or `alexsex[0] >= 3` made a plan claim a scene it had not earned. They are
    collected by `unmodelled()` into the plan's `extra` list and shown. 135 plans
    have one.
16. **Scene scores are recoverable, and plannable.** `PuzzleHold`, `hypnosisA`
    and the room counters are zeroed at the top of a scene and then incremented
    once per clue held or option taken. `B.SCORES` reads that tally back, and
    where the points come from *conditions* — quest items, decision flags — the
    planner treats `PuzzleHold >= 4` as a `("score", var, n)` fact and chases
    four of the ten clues into real steps (`Plan.reach_score`). Where the points
    come from options inside the gated scene there is nothing to schedule, so it
    stays a note — unless the scene is a *session*, which is solved outright
    (see **Sessions** below and landmine 54). Some are scored as a contest rather
    than against a threshold — see landmine 51.
    Chasing a score can box the scheduler in — the four Haily photo trades all
    live behind one screen and want a slot each, though the game lets you make
    them in one sitting — so `build_plan` falls back to `skip_scores` and reports
    the score rather than returning no plan at all.
17. **Branch ids are not `\w+`.** Sixteen of them contain a hyphen
    (`AlexForest2ForestFun2-2111`, the Alex-pregnancy branches). With `\w+` the
    producer never registered *and* the requirement never parsed, so the
    pregnancy mails planned a run that never got anyone pregnant. Every branch-id
    regex in the pipeline uses `[\w-]+`.
18. **`("Item: King of Hearts") in commonEvents`** — the author's own parentheses.
    An item regex anchored on `"…" in commonEvents` misses it.
19. **Loose ends must be deduplicated by fact, not by prose.** Two different
    requirements often `describe()` to the same choice text, and filtering
    unresolved entries against the plan's `gives` strings silently swallowed real
    ones.
20. **Top-up scenes need their route checked.** The planner chases a *target's*
    prerequisites, but affection filler is dropped into spare slots and never
    revisited, so `stat_topup` must verify that the run it is part of can
    actually reach the scene — and that the menu option itself is on offer.
    Otherwise it fills the weekend with scenes the player cannot open.
21. **Switching a rung on switches on every rung below it.** So a scene guarded
    `not cassidyCorruption4On` is unplayable in a run with Cassidy·Together on.
    `B.CASCADE_ON` holds the closure; `cascade_conflicts` asserts no plan
    contradicts itself this way.
22. **`pick_alts` must not pick a branch that fights the rest of the route.** The
    window picker opens with `hailyCorruption2On` or with `not hailyCorruption2On`;
    the cheaper-looking negative one is useless when the next hop demands that
    rung ON. Contradicting what the route already needs outranks toggle count.
23. **`call screen X` is a jump to the screen**, not to a label named `screen`.
    Twenty-four of them; missing the keyword orphaned the photo-trading subtree.
24. **A label and a screen can share a name.** `label HailyPhotoTrading` calls
    `screen HailyPhotoTrading`. Keeping only the first node under that name drops
    the other body — and with it every button in the screen. `graph.build()`
    walks both.
25. **A guarded block that jumps away negates itself over everything after it.**
    `label CatchingUpCassidy:` opens with
    `if cassidyCorruption5On: jump CatchingUpModernCassidy`, so the whole rest of
    the scene silently carries `not cassidyCorruption5On` — the indentation says
    nothing about it. `graph.walk` tracks these fall-through conditions
    (`escapes()`) and adds them to the guard stack of every later sibling.
    Without it a plan will happily send you to a scene the game replaces.
    **And the jump is often not the block's last statement**, so reading only
    the tail misses it — see landmines 62 and 63.
    The `else` branch does the same thing with the sign flipped — landmine 62.
26. **Check the toggles both ways.** A scene needing a rung the setup never
    switches ON is as broken as one needing a rung the setup switches on; the
    player follows the toggle list exactly. `cascade_conflicts` reports both, and
    `build_all.score` counts a clash as a loose end so a cleaner site wins.
27. **`pick_alts` must also avoid rungs the target needs OFF.** Otherwise the
    route into a prerequisite demands the very rung the target forbids, and
    `resolve` refuses it in silence.
28. **Two rungs are padlocked on the rest of the roster.** Cassidy's *Together*
    cannot be switched on unless every other girl is at her top rung, and her
    *Open* needs at least one of them there. The menu draws the padlock under a
    guard shaped `not <rung> and not ( … )`; `B.RUNG_GATE` keeps that inner
    expression and `resolve` expands it, so listing Together drags seven more
    toggles into the setup. Without it the app hands you a menu state the game
    will not let you enter.
29. **Some rungs are mutually exclusive.** Jenny's Prey button clears Predator
    and vice versa (`B.CASCADE_OFF`). A setup asking for both is impossible, so
    `resolve` refuses the second and lets another alternative be tried.
30. **An `elif` carries the negation of every branch above it.** This is how the
    game picks between variants of a scene:

    ```
    if alexCorruption4On:    jump C4AlexBedroomVisit
    elif alexCorruption2On:  jump d2nightAlexBedroomC2    # "Moisturizing Alex"
    else:                    jump AlexYourBedroomN2C0
    ```

    Recording only `alexCorruption2On` makes the Corruption 2–3 scene look
    available at every rung, and a plan will send you to a scene the game
    replaces. `graph.walk` threads the chain so each branch also gets
    `not <earlier condition>`; `else` gets all of them. This is the same idea as
    landmine 25 but for siblings rather than fall-through, and it is what makes
    "higher or lower than the required range" checkable at all.
31. **Answering "unknown" to a negated compound throws away most of the
    affection.** With chain negations recorded the guards are full of
    `not (A and B)`. De Morgan in `atom_ok` — one failing conjunct is enough —
    recovered about 45 run-scoped gates that had gone uncovered.
32. **One location per timeslot, and no fallback.** `schedule()` used to drop a
    visit into an already-occupied slot when nothing was free, producing an
    itinerary that cannot be played -- two scenes at Saturday Noon. It now fails
    the visit instead, which lets the demote-to-an-earlier-loop machinery try.
    The one real exception is a visit that costs nothing (landmine 39); two
    targets still have no playable itinerary at all, which is the honest answer.
33. **A required affection gate is a goal, not filler.** `stat_topup` only takes
    scenes the run already reaches, so a gate whose remaining sources sit behind
    a quest item stays short forever -- Alex's second breast expansion needs
    Haily's milk (`HailyPackage3`, and so Haily·Package switched on) or the
    hypnosis event. `chase_gate` adds the producer as a real visit and expands
    it like any other requirement.
    It accepts **one candidate at a time**, keeping it only if the whole plan
    still works: the target still schedules, the new scene actually got a slot,
    and neither the contradictions nor the loose ends grew. An earlier version
    that added several at once and rolled back wholesale produced slot
    collisions, lost plans and ten times the toggle clashes. Cost candidates by
    what the *map gates* drag in too, not just the scene's own guards, or a
    badly-gated scene looks free. When a candidate fails to schedule, the
    blockage is one of the prerequisites it just dragged in competing for a slot
    the run had already spent -- not the scene that reports the failure. Ban the
    tightest newcomer and try the same candidate again: Haily's milk comes from
    three package scenes and the cheapest wants the same Saturday Morning as the
    Broken Pocket Watch.
34. **Set iteration order was leaking into the plans.** Two builds of the same
    input produced 614 and 615 plans. `deps` and `succ` are sets, and iterating
    them decided the topological order and therefore the slot assignment. Every
    such traversal is now sorted. If a count moves without an input change, look
    here first.
35. **`cassidyLove` is halved at the reset, not cleared** (`script.rpy:453`).
    It is the one affection that carries between runs, so a shortfall against it
    is much softer than the others -- the affection card says so.
36. **A contradiction is a reason to ban the site, not just the rung.** Most
    facts have several producers at different rungs: `AlexPornDate` has four.
    Banning only the rung re-picks the same producer and swaps one clash for
    another, so `build_plan` bans both — and weighs the result, since banning a
    site can remove the only producer of something else.
37. **A stat bump is signed, and `-=` is not a boost.** 244 of the 1840 stat
    events are losses (`alexLove -= 1` under "For masturbation") and 61 are plain
    `=` resets. Reading `amount` and ignoring `op` made a scene that *costs*
    affection rank as the best source of it. `stat_gain` returns a signed value
    and treats `=` as worth nothing — all but two of them assign 0, and those two
    are in the reset block.
38. **Rank a top-up on the route's total, but only what the guards allow.**
    Two mistakes that cancel out into a wrong answer either way. Scoring a
    candidate by its single bump undersells routes that pay twice; summing the
    scene's bumps without `guards_ok` oversells them — `AlexForest1` opens with
    `+1 alexLove` behind `tempFlags["HailyText312"] >= 3`, and counting it
    promised affection the run never collects. `route_gain` does both: sum the
    route, guard-check every term. Ignoring the guards here reads as a *better*
    result in `build_all`'s summary (33 uncovered gates fell to 30) while the
    plans got worse.
39. **Not every scene costs a timeslot, and the only evidence is `dateVar`
    arithmetic.** See "Some slots cost nothing" above. Treating an automatic
    event as one location per slot like anything else made the planner give up
    slots it never had to spend: the Broken Pocket Watch used to take Saturday
    Morning, which is why Alex's "Double Trouble ++" had to find a second milk
    source. The regex needs `^\$?\s*dateVar\s*(\+=|-=)\s*(\d+)$` — `$ dateVar-= 1`
    and `$ dateVar -=1` both occur — and the delta has to be threaded down into
    nested blocks, because the refund is often several lines above the jump it
    pays for (the Saturday wake-up decrements once, then opens a menu of three).
40. **Costing nothing is not permission to play a scene twice.** `LinaC3Invite`
    is free and offers five wing-girls, and a plan wanting two of them needs two
    loops, not one sitting. `schedule` keeps a `played` set of (scene, slot).
    Without it four LinaC3Invite visits piled into Friday Midnight and the plan
    read as feasible.
41. **`gateFirstRun` is `default True` but is never true in a run this tool
    describes.** Left in `DEFAULT_TRUE` it makes `not gateFirstRun` — the
    fall-through guard on most slot labels, and so on nearly every automatic
    event — look unsatisfiable, which hid all of them from the affection top-up.
    Worse in the other direction: a positive `gateFirstRun` guard passed silently,
    so 30 plans quietly routed through the first-playthrough default scenes.
    `ALWAYS_FALSE` in `plan.py` and the `firstRun` edge marker in `graph.py`
    handle the two halves.
42. **`mood` breaks every naming convention the stat regex relies on.** No
    character prefix, no `Love`/`Horny` suffix, so `graph.py`'s `STAT` whitelist
    has to name it outright. It is a genuine per-run tally, reset to 0 alongside
    the Love vars at `script.rpy:420`, which is what makes it comparable with
    them in the tiebreak. It is deliberately *not* in `build_app_data.RE_STAT`:
    `mood >= 10` is a running tally with no single producer to schedule, so it
    stays an "Also required" note (see the known limitations).
43. **A MapBook page's title is a *position*, not a style.** Anchoring on
    `style "gridtextbold"` finds 292 of the 474 pages; the rest title themselves
    with `style "gridtexton"` or a `_textbutton` in a `Window`, and
    `d2morningDefault` ("Saturday Breakfast") is one of them. Take the first
    Text/textbutton widget in the page instead.
44. **Do not name a scene by which MapBook page mentions its branch ids.** It
    looks exact and is not: pages cross-reference each other's flags as
    condition nodes, so the vote hands `d3eveningDefault` the name "Searching
    for Haily" and `linahypbj` "Hypnotising Jenny". `currentScene` — the game's
    own answer to the same question — is the source to use.
45. **The map hotspot is named by its art, not by its `at` clause.**
    exploremap's Forest button has no `at` clause at all, so `at (\w+)button`
    silently loses places. `ui/glow <place>_%s.png` is on every one of them.
46. **A refunding "Leave" is only collectible if the scene loops back on
    itself.** 21 labels have a menu option that does `dateVar -= 1` on the way
    out, but only the ten explorable rooms let the player *do something first and
    then take it*. `AlexForest1` has a refunding "Leave" and no menu loop: its
    other options fall through to a plain `jump dayhandler` at the bottom of the
    scene, so asking Alex about her pants costs the sitting. Reading the refund
    off the scene's own edges without checking for the loop makes six scenes look
    free that are not — `fuckfest` among them, which is a forced event.
    The loop is recognisable because a nested `label GardenRoomLoop:` is not a
    top-level container (`build()` only collects column-0 labels), so an out-edge
    whose `dst` is absent from `B.CONTAINERS` is a jump the scene makes to
    itself.
47. **Judge the picks at their deepest, not at any depth.** `cBedroomRoom` has an
    edge under `("Search",)` that returns to its loop *and* one under
    `("Search", "Cassidy's panties")` that jumps to `dayhandler`. "Any pick
    returns" calls the panty theft free; "every pick returns" makes
    `MasterRoom` + "Search" cost a slot it does not, because Search has
    conditional exits to `linmessage0` and `dayhandler` alongside its three
    returns. Only the longest chosen choice-tuple describes what the visit
    actually ends on.
48. **A visit that costs nothing must not push its consumer into the next
    slot.** `lo = placed[p] + 1` is right for a scene that spends the sitting and
    wrong for one that does not: the automatic event has already fired when the
    slot's map is drawn, and the Explore trip hands the slot back before it. Left
    unrelaxed, "steal Alex's panties" and "hide them in your bag" — two free
    Explore trips — burned two slots for nothing.
49. **The route's negations are requirements too, and they were being dropped.**
    Landmine 5's mirror. `avoid` used to come from `negatives(v.guards)` alone —
    the scene's own guards — but an `elif` chain lives on the *route* into a
    scene, and its negations are what decide whether the game takes you there at
    all. The Sunday dinner search reaches Lina's bedroom only because the two
    branches above it did not fire, so `LxL R025` read as "click Search for
    Haily" and left out the whole reason you end up in her room. `nav_negatives`
    now folds them in.
    They cannot simply be dumped in: the route's guards are thick with rung
    negations the setup card has already answered, and a raw dump more than
    tripled every plan's avoid list with things like `not (Haily·Contact ON
    and …)` that are true before the player does anything. `atom_ok` is the
    existing answer to "does the run guarantee this" — De Morgan and all
    (landmine 31) — so a negation it confirms is dropped, and the sub-atoms it
    parks in `avoid` on the way are the specific don'ts behind a compound.
    `dateVar` is the other thing to settle rather than print: "must not already
    have dateVar in [5,6,13,14,20,21,22]" on a row that already says Saturday
    Noon is noise, but it is often one conjunct of a compound that does say
    something, so `fix_dv` answers it from the step's own slot and lets the
    De Morgan pass use it.
50. **A negated conjunction has several ways to be true, and they are not
    equally cheap.** `not (A and B and C)` needs only one conjunct to fail, and
    `atom_ok` used to take the first that did — appending its "don't do this"
    even when a later conjunct was a rung the setup never switches on and so
    already false for free. That told the player to avoid picking up
    `Quest: Winggirl Lina, Jenny` on 60 steps whose runs had Jenny·Prey off and
    could never have taken that branch. Prefer a conjunct settled with no avoid;
    fall back to the cheapest one that needs an instruction. The `or` side has
    the matching bug: `all(...)` short-circuits and leaves half its notes behind
    for a condition it then rejects, so collect and only commit on success.
    Neither changes what `atom_ok` *returns*, so no planning decision moves.
51. **A scene score is not always a threshold.** `C3DinnerHailySearchBedroom >=
    max(C3DinnerHailySearchHypnosis, C3DinnerHailySearchForest, 1)` is a
    contest: the Sunday search follows whichever theory you gave the most weight
    to. `A_SCORE` wants an integer on the right, so this fell through `score_of`
    as an unexplained expression and the plan said nothing about how to steer
    the search. `A_CONTEST` reads the `max()` form, takes the integer inside it
    as the floor and the other counters as rivals, and the note spells out what
    each of them is worth — the points you must *not* pick up matter as much as
    the ones you must. Rivals are looked up in `B.SCORE_PARTS`, not `B.SCORES`:
    a tally with one contributor is not a score worth reporting on its own, but
    Forest has exactly one clue behind it and is still worth naming.
    **A contest is really a menu, so show the menu.** Counters alone are not an
    instruction: the player is standing in front of a list of clues, and the
    tallies never say which option *stops the asking*. `B.SCORE_MENUS` records,
    for each counter, the `menu:` its options sit in, every option of that menu
    in order, and the counters each option's block feeds (nested branches
    included, so "When you talked with Carla" shows the Hypnosis point from its
    sub-menu). `_menu_exit` reads the loop's terminator off the enclosing nested
    label -- `label C3DinnerHailySearch:` opens `if eventTimer >= 4: jump
    …Resolve` then `$ eventTimer += 1`, so the search gives four picks and any
    option bumping the counter by `at - per` ends it on the spot. That is what
    marks "That's all" as the way out. Report every counter the menu feeds, not
    just the ones being compared: `Success >= 4` is tested one `elif` *above*
    this branch, so an option building it sends the search somewhere else, and
    "Follow your hunch" listed as adding nothing is exactly the misreading that
    hides it. And mind the operator -- `>=` means Bedroom at 1 beats Forest at 1;
    "more than" would send the player hunting points they do not need.
52. **A ladder is a position, not a set — so only list the toggles the player
    flips.** Landmine 21 the other way round. `setup_cor` accumulates whatever
    each requirement asked for, so a plan that needed Lina·Found Out for one
    scene and Lina·Open for another listed both, and the menu has no such state:
    switching Open on switches Found Out on, and the girl is simply at Open.
    `minimal_setup` drops any rung another listed rung already brings with it —
    the same `B.CASCADE_ON` closure, so the run is unchanged and only the
    instruction gets shorter (1768 toggles across the plans down to 1360, 214
    plans affected). The add-on rungs sit on nobody's ladder (Fertile, Package,
    Jenny's Prey/Predator axis), so they survive *beside* the ladder position
    rather than being folded into it — which is exactly what makes the closure,
    not a "highest rung wins" rule, the right thing to reduce by.
53. **A step whose *way in* is unmodelled must say so on the row.** The Sunday
    search reaches `HailyC3BedroomSearch` through a menu loop inside
    `d3eveningDefault`, and because the loop's labels are nested (not top-level
    containers) the graph flattens it: the edge carries the `elif` chain but not
    the menu. So the plan named the scene and the picks to make *in* it, and the
    first options on screen were a completely different menu — the row read as
    simply wrong even though its destination was right. `route_gated` asks
    whether any hard condition on the route resolves to no facts, and the row
    then points at the "Also required" card and says the picks listed come
    *after* that menu. 63 of 1511 steps carry it, across 20 distinct
    (scene, slot) pairs — `mood >= 10`, the `cassEvents` substring tests, the
    `carlablow[0]+…` tallies and this contest. Reporting a condition at the
    bottom of the page is not the same as warning the player at the point where
    it bites.
54. **A hypnosis threshold is a path, and the old note was wrong three ways
    over.** `hypnosisA >= 6` used to fall out as a scene score, so the plan
    listed every option that *adds* to that one counter and said "score at least
    6 from:". The picks are not free — four menus, one pick from each, so ten
    listed options are really four decisions. The list never said whose trance
    the number was. And it hid the other counter entirely, though the same pick
    moves it: `"Shooom Shooom Shooom"` is −1 Jenny and +2 Lina, and a run
    steering by Jenny's list alone would take it. Worse, the note left out the
    multipliers, and those decide whether the threshold is reachable *at all* —
    every target wanting 10 is really asking for Cassidy's hypnosis lesson.
    256 paths is nothing to enumerate, so `solve_session` enumerates them and
    names the four picks. Reproduce the arithmetic exactly: the halving is not
    truncated and the boost is, so `int(x*.5*1.5)` and `int(int(x*.5)*1.5)`
    differ, and a run can genuinely sit on a trance of 2.5.
    Rank the paths by the *other* counters, not by slack on the threshold —
    nothing here is random, so a margin buys nothing while a point of Lina's
    trance opens another branch.
55. **Only three scenes have that shape, and the near misses have to be
    rejected, not approximated.** The extractor is generic — a counter zeroed at
    the top of a label and rebuilt by a run of menus — and it also finds the
    `<char>Horny` build-ups. They look identical and are not:
    `AlexYourBedroomN2C0`'s `"Compliment breasts"` opens a *sub-menu* whose
    branches are `+= 1` and `= -1`, `HailyLaidBare`'s `"Weird is good"` scores
    `+1` four times behind four other girls' rungs, and `AlexOralDate` tests
    `alexHorny >= 2` halfway through and then keeps offering picks. Summing an
    option's whole block credited it points for a choice the plan never names;
    summing every menu counted picks made after the number had already been
    read. So `_opt_adds` counts only what sits at the option's own indent and
    refuses the session if anything assigns the counter, and `_session` refuses
    one whose counter is read before the last menu ends. Rejecting is the honest
    answer: a path is worth printing only if the number at the end of it is
    right. An independent replay of every shipped path against the raw
    `.rpy` is the check that caught all three (`0 problems`, 38 blocks) — the
    pipeline agreeing with itself proves nothing.
56. **`RE_BUMP` is unsigned, and a second regex is why.** The score tallies want
    `+=` only. A session needs both directions and both spellings — the sessions
    write `+= -1`, the Alex date writes `-=1` — so `RE_SBUMP` is separate.
    Sharing one regex either loses a pick that costs a point or changes what
    `SCORE_PARTS` reports for the Sunday search.
57. **`label after_load:` in `script.rpy` is not a grant site.** It re-awards a
    hundred-odd records from legacy `c<Char><Thing>` persistent flags when an
    old save is loaded — exactly the save-shuffling `mails.py` already ignores
    in `Phone_Init`, and exactly the same shape as a real `addCor`. Sixteen of
    its values are not in `totalCorruption` at all, so they are the author's
    stale spellings; `grant_sites()` drops the whole label rather than letting
    one be picked as a plan's final scene.
58. **A dot is identified by its record string, and merging by name loses
    scenes.** `build_targets` used to key unlock targets on
    `(char, name, tier, style, preg)`, which folded 14 pairs of genuinely
    different dots into one row — Alex's Corruption 2 "Blowjob" is paid both by
    *Moisturizing Alex* and by *Share Bed with Alex* — and then planned the
    survivor from whichever of the two sites happened to score better. Worse,
    the key came from the `addCor` calls rather than from `totalCorruption`, so
    a dead grant could supply the plan for a live dot. Build from the catalogue,
    key on the record, and match grants by the exact string.
59. **An unearnable dot must be listed, not filtered.** `targets` drops anything
    with no route, which is right for a ladder rung or a mail — unwired content
    with nothing to say — and wrong for a dot: the checklist draws it whether or
    not the game can light it, so hiding one makes the tab disagree with the
    panel the player is reading. The seven are kept and say why (six string
    mismatches, plus Alex's "First Grope", whose only sites are first-loop-only).
60. **A rung is free to a `chase_gate` candidate, and making it expensive costs
    more than it saves.** The symptom is real: when the target needs Alex low,
    every Alex scene behind `alexCorruption2On` sorts to the front of the
    candidate list (rungs cost nothing, so those scenes look free), gets
    expanded, scheduled, found contradictory and rolled back — and the try
    budget is gone before a +1 that needed nothing but Haily·Arrival is reached.
    Charging 2 for a rung the setup does not already hold fixes exactly eight
    gates and breaks eight others, because a single rung-gated +4 is often worth
    more than the three +1s that then crowd it out. It is a budget problem, not
    a ranking problem: leave `fact_cost` alone and raise `CHASE_TRIES`.
    Measure any change here on the whole build — `unmet` and total shortfall
    across every plan — not on the target that prompted it. Every ranking tweak
    tried so far helped one cluster and hurt another, and only the aggregate
    says which way it went.
61. **The earliest slot is the wrong slot for a scene with an affection gate.**
    `schedule` takes the first sitting in a visit's window, which is right for a
    producer and backwards for a consumer: the gate is read when the scene
    starts, so placing it early throws away the slots that would have paid for
    it. Alex's Forest Handjob wants 4 Love and is playable at four slots; at
    Saturday Noon the run has seven sittings to find it in and comes up short,
    at Sunday Afternoon it has fifteen and does not. Reversing the window for
    those visits alone took the uncovered gates from 21 to 14, and cost four
    more plans an earlier loop.
62. **An `else` that jumps away asserts its `if` over everything after it.**
    Landmine 25 read the other way round, and only half of it was implemented:
    `graph.walk` recorded `not <cond>` when an `if` branch escaped but recorded
    nothing when the `else` did. `AlexYourBedroomN3C0` opens
    `if alexLove >= 2: … else: <a page of dialogue> jump dayhandler`, so the menu
    below it — and the four collection dots behind that menu — all silently want
    2 of Alex's Love. Neither the indentation nor the menu option says so, and
    the plans for them listed no affection at all. 132 of the game's 18482
    `else:` blocks escape, carrying 40 affection thresholds and 188 other
    conditions between them. Mind the chain: after
    `if A: … elif B: … else: <jump>` what holds is `A or B`, not `A`.
63. **A stat comparison is not always a floor, and `>` is not `>=`.**
    `atom_facts` pulled the number out of `RE_STAT` and ignored the operator.
    `alexLove > 4` became "at least 4" — a plan one point short at exactly the
    scene it was written for — and `alexLove <= 0`, `jennyLove <= 0` and
    `hailyTalk == 0` became "at least 0", which turns a *ceiling* into a gate
    that is trivially met and then never mentioned again. `stat_fact` maps
    `>=` to n and `>` to n+1, and returns nothing for the other three so
    `unmodelled` reports them on the plan instead. 178 of the 217 comparisons in
    the guards are `>=`; every one of the other 39 was being read wrong in one
    direction or the other.
64. **The decompiler indents a narrator line one column too deep, and `parse`
    adopts the next sibling into the block above it.** `rpyc_dump.py:198` is
    `'%s%s%s "%s"'` — with an empty speaker the literal space before the quote
    shifts the line. 21001 lines in `_decompiled/` sit at a non-multiple-of-4
    indent and **every one of them is a narrator Say**; nothing else in the tree
    is misaligned. `graph.parse` pops with `while stack[-1].ind >= ind`, so such
    a line becomes a child of its own preceding sibling — and if that sibling is
    an `if`, it lands *after* the block's real `jump`. No non-narrator node is
    ever parented under a narrator and narrator lines carry no events, so
    `escapes()` is the only consumer the misalignment ever reached. That is why
    fixing `escapes()` is a complete fix and re-decompiling is not needed — and
    why `rpyc_dump.py:198` is deliberately left alone: correcting it would
    re-baseline every indentation-sensitive extractor (`_opt_adds`,
    `SCORE_MENUS`, `mails.py`, `verify_sessions.py`) for no gain.
65. **A `jump` need not be the block's last statement, and a `label` in the dead
    tail is a re-entry.** `escapes()` read only `body[-1]`, which missed 52
    blocks: 51 of them landmine 64's adopted siblings, and one — `AlexShareBed` —
    real dead code, `jump AlexHailyShareBed` followed by two unreachable
    `$ alexgrope[0] += 1` lines. The cost was concrete: the plans for that
    scene's three dots switched Haily's Arrival *on*, which is exactly the rung
    that makes the game play "Alex and Haily Share a bed" instead, and no
    conflict was reported. Scan the whole body. The one thing that is not dead
    code after a jump is a nested `label` — `sceneC5Alex` jumps back into
    `label AlexBBQFinalePost:`, so control resumes there and does fall out of the
    bottom. A `menu:` is not a re-entry, and `call` is not an escape.
66. **`not (A and B)` is a disjunction, and every rung test in the pipeline was
    written for a bare atom.** `A_COR.match` against a whole stripped string sees
    nothing in `not (hailyCorruption2On and …)`, so `off_requirements` never
    seeded `banned_cor` and `cascade_conflicts` never reported. Worse,
    `cor_vars` scanned the raw text with `negated_at` and read
    `not (alexCorruptionPregOn and hailyCorruptionPregOn)` as **demanding both
    rungs ON** — the exact opposite — and `pick_alts` scores route branches on
    that. `B.cor_clauses` returns one entry per alternative and the callers say
    what they want of it: a requirement is the *intersection* (`cor_vars`), an
    escape is the cheapest entry (`off_requirements`), a contradiction is *every*
    entry being dead (`cascade_conflicts`).
67. **A branch is not free just because it demands nothing.** Landmine 1's other
    half, and it bites the moment landmine 66 is fixed. The Sunday-afternoon
    Living Room button opens the *same* picker three ways, so the third `elif`
    carries `not (alexCorruption5On and hailyCorruption5On and
    cassidyCorruption5On)`. As a requirement that compound asks for nothing —
    correctly, since any one of the three failing satisfies it — so `cor_vars`
    reports it free and `pick_alts` happily walks a branch the game will never
    take, landing three phantom clashes on a run holding all three rungs.
    `cor_clash` is the per-alternative test that says so, and it is scored ahead
    of toggle cost. Judging only the `need_off` side is not enough: `known` is a
    lower bound, but where *every* alternative is purely about rungs, "not
    switched on" and "switched off" are the same sentence and the branch is
    definitely dead.
68. **A ceiling is the dual of a position, and the three things the card says
    are three different questions.** Landmine 52 the other way round. Compute
    which rungs a cap allows with the `B.CASCADE_ON` closure, never by rung
    number: `alexCorruptionPreg` closes over C1–C5 but `hailyCorruptionPreg`
    closes over itself alone, so a "highest number wins" rule ranks Haily's
    Pregnant above her Contact when the two are unrelated.
    But do **not** classify a rung by that closure. `_is_chain` asks which *row
    of the menu* a rung lives on, and the panel's rows are `Uncorrupted`,
    `Corruption 1`..`5`, then `Corruption Preg` on its own — so the numbered
    rungs are the ladder and everything else is a modifier. `samiCorruptionPreg`
    closes over C1–C5, so a closure test called it a ladder position and the
    card printed "Sami · C5 Composed MAX" — her top rung, forbidding nothing —
    while the constraint that mattered, Pregnant OFF, vanished.
    The three answers are `min` (the position to switch on), `cap` (how far that
    ladder may go, `None` for no limit and `[]` for none allowed) and `mods`
    (the modifiers that must be on or off), and they go in a table with a row
    per girl. As one pill row they read as contradictions: `Hypnotising Carla`
    needs Haily's *ladder* at Uncorrupted while `Haily·Package` is switched ON,
    and "Haily · Uncorrupted MAX" beside "Haily · Package ON" is nonsense to a
    reader even though the model is right. Drop a modifier the cap already
    excludes (Alex's Pregnant under a C4 cap) or it is said twice.
70. **A rung is switchable only where the menu draws a button for it, and the
    lock icon is not the only way it says no.** Landmine 28 is the visible half.
    The other half is silent: Haily's Package renders as a bare `Text` — no
    `_textbutton` at all — under
    `not Spy1 and not Spy2 and not hailyCorruption2On`, and her Fertile has a
    `_textbutton` whose `else` sets the rung *False*. Either way she cannot be
    switched on, and a plan asking for Package while holding Haily's ladder down
    is unplayable — which is exactly what the atlas shipped.
    So ask the real question: what conditions reach a button that sets this rung
    `True`? `_btn_paths` walks the if/elif chain to each one and `_required`
    keeps what is left after assuming every *unlock* flag is unlocked (`False`
    for the usual ones, `True` for the inverted Moonstone) and the rung itself
    off, enumerating the remaining `…On` variables to find what every path
    demands. That yields 19 requirements, including Haily·Package → C2,
    Haily·Fertile → C4, Sami·Workout → C2, every Preg and Fertile rung →
    `optionPreg`, and — as a cross-check on the old `smalllock` heuristic —
    Cassidy·Together's whole-roster padlock, which both methods find.
    Two traps in the substitution. Blank the string literals *first*, or the
    word pass rewrites the inside of `endmenuchascreen == "bio"` and the test
    silently inverts. And `\b(\w+?Corruption\w*?)\b(?!On)` does **not** exclude
    `hailyCorruption4On` — the lookahead sits past the whole token, so the regex
    happily eats the very variable the requirement is about and every gate comes
    back empty. Match the token, then check the suffix.
71. **An avoid line the setup contradicts has to say so on the row.** It is
    already counted as a toggle clash and printed in the warn card at the foot
    of the plan, but "Avoid Sami·Love ON" sitting under a setup reading
    "Sami · C5 Composed" asks the reader to apply the cascade in their head
    before they can even see the contradiction. `clash` marks those entries and
    `avoidRow` sorts them first, so one is never the pill hidden behind the
    "+3". 23 steps carry one.
72. **A reward tile is identified by its jump, not by its box.** 76 of the
    panel's `MultiBox ... xsize 240 ysize mailYSize` boxes exist and there are
    **80** tiles: Cassidy's four use different markup, and one of the 76 is the
    legacy panel's stray `TheProgression`. Anchoring the extractor on the box
    silently loses four Memories and Dreams, and the counts still look plausible.
    What every tile does have is a thumbnail that jumps and a caption under it,
    so `tiles()` takes the **minimal subtree holding both a `Jump` and a
    `Text "..." size 14`**. Minimal is the load-bearing word — every ancestor
    holds both too, so without it the enclosing `vpgrid` comes back as one tile
    covering the whole section.
73. **`not <char>CorruptionN` is a positive requirement, and teaching the
    planner that would rewrite every plan in the build.** The corruption unlock
    vars are inverted (`False` = unlocked), so the reward tiles are full of
    `not alexCorruption5` meaning "Alex's Corruption 5 is unlocked". Minting an
    `("unlocked", var)` fact for it in `atom_facts` is the obvious move and it is
    wrong: that shape appears in scene guards all over the game, so the fact
    would land in all 732 pre-existing targets and move every tripwire in
    `build_all`'s summary at once. Split the condition at extraction time
    instead (`rewards.split_cond`) — rungs become cross-links the planner never
    sees, residue becomes a synthetic event's guards. **The regression check is
    that the 732 non-reward targets are byte-identical**; diff `app_data.json`
    restricted to their ids before and after any change here. Landmine 70's trap
    applies to the matcher: match the token, *then* check for the `On` suffix —
    a `(?!On)` lookahead sits past the whole token and happily eats
    `alexCorruption5On`.
74. **One tile can jump to the same scene twice.** Carla's `CarlaSamiMovieNight`
    is an `if optionPreg`/`else` pair differing only in artwork
    (`sceneEndChoicesCarla.rpy:137` and `:142`). Identity is
    (char, section, jump target), so the second is the same tile — dedupe per
    tile or Carla's Memories come out 7 instead of 6, and the total 81 instead
    of 80. Take the condition from the **caption**, not from the button: the
    caption cell has one canonical guard where the button's is forked by
    artwork.
75. **A verifier that drives only the plan will pass a tab that crashes the
    rail.** `smoke.js` rendered every target through `renderPlan` and nothing
    else, so a new kind that broke `visible()`, `renderList()` or `itemBtn()`
    would still print `failures: 0`. It now also drives `render()` for every
    (character, tab) pair — 50 of them, including the empty ones — and the DOM
    shim's `querySelectorAll` returns real matching descendants rather than `[]`,
    because `renderKinds()` reads `.n` off each tab and a shim that returns
    `null` there means the counts are never exercised at all.
69. **A loose end is a worse answer than a toggle clash, so weigh it first.**
    `build_plan` scored `len(conflicts) + len(unresolved)`, which is a tie no
    longer worth taking once landmine 65 makes the real contradictions visible:
    Jenny's Hypnosis traded a four-step plan carrying three clashes for a
    one-step plan carrying none, and the one-step plan says nothing at all. A
    clash still names every scene, every choice and which rung fights it; an
    unresolved prerequisite means the run was never worked out. `cost` is
    `(len(unresolved), len(conflicts))`. Getting this backwards cost 7 fully
    resolved plans and 11 loose ends without changing a single toggle.

---

## Updating for a new game version

1. Drop the new install in `_game/`, replacing the old one. Keep the whole
   distribution together — `game/`, `lib/`, `renpy/` and the launchers — or the
   exe will not find its data directory.
2. `rm -rf _decompiled _analysis` and run the pipeline.
3. Check step 1 reports `0 fail`. A failure usually means a new Ren'Py version —
   compare `game/script_version.txt` (currently `(7, 4, 8)`) and expect another
   pickle-shim class in `rpyc_dump.py`.
4. Check step 2's `roots` count is 39 and the slot table still spans dateVar 1–21.
   If the author added a day, `DVLABEL`/`SLOTS` in `plan.py` and `_app.js` need
   the new entries, and `LAST_DV` changes.
   Also check the `dateVar` bookkeeping still looks like 0.62d's: 76 `time`
   events, 110 edges with a nonzero `dv`, 41 automatic entrances. A collapse to
   zero means the author changed how a timeslot is spent, and every plan's slot
   count is then wrong.
   Step 2 also prints **scene names 307, MapBook titles 474, currentScene 402**.
   A drop in the titles means the MapBook grid's markup changed and plans will
   start showing dev labels; check `book_title` against a `screen map*` block.
   Explore mode has its own invariants: `exploremap` must still be among the
   roots at `dateVar: 0`, and all ten rooms must still be loop-shaped. Check with
   `PYTHONPATH=_tools python -c "import plan as P; print(P.exit_dv('GardenRoom',
   ['Search']))"` — it must print `-1`. If the author replaced the `<Room>Loop`
   labels or dropped the "Leave" refund, every Explore step silently starts
   costing a slot again.
5. Re-verify the reset semantics in `script.rpy` and `dayhandler` — if the author
   ever starts resetting `tempFlags`, the earlier-loop logic becomes wrong and
   `Visit.persistent()` must return `False` always.
6. Check the ladder extraction printed by `ladders.py`: every rung should have a
   name and at least one site. `NO DIRECT SITE` means the unlock happens through
   a pattern the regex misses.
7. Check `mails.py`'s summary. `NO PANEL NAME` beyond the known handful means the
   Mail panel's markup changed; `NO GRANT SITE` beyond `LinaSMS28`/`LinSMS0`
   means a new way of awarding mail. Cross-check the per-character counts against
   the game's own Mail panel — that is how the 0.62d undercount was found.
7b. Check `rewards.py`'s summary. It must print **40 memories, 40 dreams,
   9 characters**, with no `ANOMALIES` block, and the per-character counts
   Alex 3/6, Carla 6/2, Cassidy 4/5, Haily 7/4, Jenny 5/6, Lin 5/4, Lina 2/3,
   Lisa 3/4, Sami 5/6. Cross-check two things against the panel itself: Carla
   must be 6 Memories, not 7 (the `CarlaSamiMovieNight` double-jump, landmine
   74), and `TheProgression` — the legacy panel's stray tile — must be absent.
   `cross-linked rungs: 22` and every one of them present in `ladders.json` is
   what makes the cross-links exact; a rung that is not there would render as a
   dead link. An `ANOMALIES` line naming a tile with no caption or two jump
   targets means the panel's markup changed — read the tile before trusting the
   record.
8. Watch `build_all.py`'s summary. It should read **812 targets, 757 with a
   plan, 744 fully resolved** for 0.62d, and `build_app_data.py` before it
   **812 targets: 497 unlock, 173 mail, 62 corruption, 40 memory, 40 dream**.
   The 497 is the size of
   the `totalCorruption` catalogue and must match
   `grep -ho 'totalCorruption\.add("[^"]*"' _decompiled/*.rpy | sort -u | wc -l`;
   a drop means `read_catalog` stopped seeing a file, and the Events tab is then
   quietly incomplete. Big drops in "fully resolved" mean a new
   condition shape is not being parsed. **"toggle clashes" is 37 in 0.62d** — a
   rise means plans are contradicting their own setup, which is nearly always a
   bug rather than new content. It was 12 before landmine 65 taught `escapes()`
   to see a jump that is not the block's last statement; the 26 it added are
   real contradictions the guards had never carried, so do not try to "restore"
   the old number. **"setup roster" must always print 0 contradictions** —
   a ceiling that names a rung the same card switches on is the card
   contradicting itself (landmines 66-68). **"run-scoped not covered" is 18 of
   189 in 0.62d**; a jump means candidates are being rejected as unreachable,
   usually a genuine change in the map gates — but check
   `CHASE_TRIES`/`CHASE_ROUNDS` first, since those budgets are what the number
   is most sensitive to (landmine 60).
   The structural counts in step 4 are **not** affected by any of this: guards
   move, nothing else does. If containers, edges, events, roots or the three
   naming counts shift when only `escapes()` has changed, something else broke.
   **And the 732 non-reward targets must stay byte-identical whenever only the
   reward path has changed** (landmine 73). Keep a copy of the previous
   `app_data.json` and count the rows that moved — it must be 0:

   ```python
   import json
   a = {t["id"]: t for t in json.load(open("old.json"))["targets"]}
   b = {t["id"]: t for t in json.load(open("_analysis/app_data.json"))["targets"]
        if t["kind"] not in ("memory", "dream")}
   d = lambda t: json.dumps(t, sort_keys=True)
   print(sum(1 for k in a if d(a[k]) != d(b[k])))
   ```
9. Check the sessions still extract, and that only the right ones do:
   `PYTHONPATH=_tools python -c "import build_app_data as B; print({k: (v['vars'],
   len(v['menus']), len(v['mods'])) for k, v in B.SESSION.items()})"` must print
   exactly the three hypnosis scenes, 4 menus each, with `JennyGarden1Hypnosis`
   carrying 3 multipliers and the other two 1 apiece. A fourth entry means the
   author wrote another scene of this shape — check it is really flat (landmine
   55) before trusting it. `SESSION_CHAR` must still read `hypnosisB` as Lina's.
10. `node _tools/smoke.js` must report `failures: 0`, and also
    `rails ok: 50 rows: 812` — 10 characters × 5 tabs, and every target appearing
    in exactly one list. A tab that crashes the rail passes the plan loop alone
    (landmine 75), so the rail line is the half that catches a new kind.
11. Replay every shipped trance path against the raw source. The pipeline
    agreeing with itself proves nothing; a separately-written parser of the
    `.rpy` is what caught the three near-miss scenes. `_tools/verify_sessions.py`
    must print `0 problems`.
12. Spot-check two or three plans against the decompiled source before publishing.
    This is the only real defence against confidently-wrong output.

---

## Current state (0.62d)

- 145/145 script files decompile
- 812 targets: 62 corruption levels, 173 mails, 497 events, 40 Memories,
  40 Dreams. The events are the whole `totalCorruption` catalogue, one row per
  dot — 102 of them `New Mail:` records, which are dots the game draws beside
  the letter and so belong here as well as folding onto the Mail tab.
- 757 have a plan; **744 fully resolved**, 13 with a reported loose end. 55 have
  none at all, and 46 of those are reward tiles that need no run: 24 are
  available on any save and 22 want only corruption rungs, which cross-link. Of
  the other nine: six records the game spells differently at the checklist and
  at the grant, so nothing can light them; Alex "First Grope", whose only sites
  are the first-loop-only `d2nightDefault`/`d3nightDefault`, the "skip the first
  loop" button and the cheat menu; and Lina "Hottub Sex" and "Failed Makeout",
  because every itinerary for them wanted two scenes in one slot.
- **The 732 non-reward targets are byte-identical to the build before Memories
  and Dreams were added.** That is the point of the condition splitter, and the
  check to run after any change to it (landmine 73).
- 53 need at least one earlier loop
- 358 free steps, and 6 that cost two sittings. 55 plans put two scenes in one
  slot, which is legal only because the first of them costs nothing — it is
  either automatic or an Explore trip that hands the sitting back.
  (Counts are over `plan.steps`; adding `plan.prior` gives 420 free steps out
  of 1974, 338 of them automatic events.)
- **80 replay tiles across two new tabs**, 40 Memories and 40 Dreams. 24 are
  available on any save past the first loop; 22 are gated purely on corruption
  rungs and cross-link to those rungs' own plans; 34 carry a real itinerary. 22
  distinct rungs are cross-linked, and all 22 resolve to an existing `cor:<var>`
  target with a plan behind it. The only guard families are the six in
  **Memories and Dreams** above — nothing in the panel needed a new fact.
- 76 Explore steps, 62 of them free. The 14 that are not take a room option that
  jumps out instead of returning to the room's menu. Every one of the 88 Explore
  steps in the file (`steps` + `prior`) names the room it is in.
- **731 plans carry a setup roster** — a table with a row per girl the run has
  anything to say about, replacing the old ON-only pill list. 2271 rows: 1432
  name a ladder position to switch on, 784 cap how far it may go (101 of those
  at "Uncorrupted", 31 forking two ways because Jenny's Maiden and Devourer are
  alternative tops), and 936 modifier pills — 389 ON (Package, Fertile), 547 OFF
  (Pregnant, Prey). Zero contradict themselves, and `build_all` prints that as a
  must-be-zero tripwire (landmines 66-68).
- 23 steps carry an `avoid` entry the run's own setup contradicts. Each is also
  a toggle clash in the warn card; the row marks it so the reader does not have
  to apply the cascade themselves to notice (landmine 71).
- 37 toggle clashes, all reported in the app: the best available site for these
  still needs a rung switched the other way from what the run requires. Six are
  variants of one thing - "Moisturizing Alex" is the Corruption 2-3 bedroom
  scene, and those runs need Alex higher for something else. Lina "Open" is the
  circular one: its cheapest route runs through `LinaC3Invite`, which is guarded
  `not linaCorruption4On` - the very rung being unlocked.
  **This was 12 before landmine 65.** The rise is the fix working, not a
  regression: 126 edges and 352 events gained a fall-through guard that had
  never been recorded, and contradictions that were silently violated are now
  named. Do not read a future rise the same way without checking that first.
  The 37th is Lin's "Milk on Tap" Memory, the only reward tile that carries one;
  the other 36 are the pre-existing set, unchanged.
- 223 affection gates (189 run-scoped, 22 slot-scoped Horny, 12 meta Nerve);
  18 run-scoped ones the planner cannot fully cover, most of those short by a
  single point
- nearly all of the affection is now earned by `chase_gate`, as real visits with
  their own prerequisites; only 20 steps are spare-slot top-up. 365 steps pay
  more than one tally, and the row names all of them
- 45 trance blocks across 39 targets, every one solved to four named picks and
  independently replayed against the raw `.rpy` (landmines 54-56). They used to
  be 33 unexplained "score at least N" notes at the bottom of the page.
- 169 plans carry an "Also required" note — a counter outside the fact model.
  These used to be dropped silently, which made plans read as complete when they
  were not. A handful of the 247 notes spell the counter out as a scene score;
  three of those are the Sunday search's contest and carry the whole clue menu
  with them (landmine 51). 137 steps warn on the row itself that their way in
  turns on one of these (landmine 53).
- 2347 "must not already have" lines across the 1974 steps. Half of them are the
  route's own `elif` negations, which used to be dropped (landmine 49). The
  count fell from 2812 because `negatives` now goes through `atom_ok` the way
  `nav_negatives` always did: once a scene's own fall-through negations are
  recorded its guards are as full of rung compounds as the route is, and
  `NOT (Haily·Arrival ON and NOT (Haily·Hand Holding ON and …))` is a double
  negative on a step whose setup card already answers it.
- every non-automatic step that has a map click shows the room to click it in;
  200 of them have no click to describe (see **Map locations**)
- the setup card lists one ladder position per girl plus any add-on rungs, never
  a rung another listed rung already switches on (landmine 52), and below it the
  ceiling row says what must stay off (landmine 68). Two of those add-ons pay
  out at the reset rather than in a scene — Lisa's The Note hands every run the
  altered suitcase clue, Alex's Past 1 her old photos — and `setup_grant` takes
  them in preference to going and earning the thing
- `index.html` and `walkthrough.html` ≈ 1969 KB each — the same app, one as a
  whole document and one as an Artifact fragment
- the layout is clean of horizontal overflow from 320px up: `python
  _tools/probe.py` prints `0 findings` at all seven widths

### Known limitations

- **774 of 4116 branch ids have no player-facing text** in the MapBook. Only a
  handful ever surface in a plan; those show the raw id.
- **32 of 1924 plan steps still show an internal label** — eight scenes, led by
  `d3eveningDefault` (the Sunday dinner hub, which simply has no MapBook page in
  0.62d) and `linaQuestLinsPanties`. All three naming sources come up empty for
  these; there is no better name to use.
- **`AlexForest3`** ("Forest with Alex Pregnant") has no incoming jump in 0.62d —
  it looks like unwired content, not an extraction failure.
- **Cassidy's "Huh?" Memory can never unlock in 0.62d.** The tile is guarded
  `cassidylove >= 6`, and `cassidylove` is a *different variable* from
  `cassidyLove` — `script.rpy:149` declares it, `script.rpy:454` resets it, and
  nothing anywhere increments it. It is the author's typo: the same tile under
  the other eight girls reads `<char>Love >= 6`. The atlas does not claim to
  earn it — the gate falls out of the fact model and is reported on the plan's
  "Also required" card (landmine 15) rather than silently assumed — but the page
  does not say outright that it is impossible, the way an unearnable dot does
  (landmine 59). If a later version spells it `cassidyLove`, this becomes an
  ordinary Love gate and the plan will fill itself in.
- **`LinaSMS28` and `LinSMS0`** are declared but never granted anywhere, so they
  have no plan and are dropped. `LinaSMS28` even has a panel cell; `LinSMS0` has
  nothing. Both look like unwired content. (`Phone_Init` also restores
  `HailySMS18a` from `HailySMS16a`, a typo of the author's that costs us
  nothing.)
- **All the bumps a route can reach in one scene are summed.** Each is
  guard-checked first, but two bumps whose guards both look satisfiable may in
  fact be mutually exclusive branches, in which case a banked total reads high.
- **12 plans have a loose end**, reported in the app rather than hidden: three
  need a branch called `Answer`, one `Quest: Note with Name`, two
  "Look into things for Cassidy", the two Lin "Panty Snatcher" rows need
  `Lisa Poker1 Round Cheat` and the "Mystery Text" scene, Lina "Hx" cannot place
  the producer of `Event: Haily's Top Stolen` before the map gate that demands
  it, and Haily "Contact" / "Selfie" need `tempHailyPhotos ≥ 3` — three photo
  trades that the game allows in one sitting but the scheduler can only give one
  slot each. Several are counted twice because a dot and the mail beside it are
  now separate rows.
- **Running tallies are reported, not planned.** `alexsex[0] >= 3`,
  `mood >= 10`, `TotalCorruptionLevels >= 7`, the `cassEvents` substring tests
  and the typed puzzle answers cannot be chained to a scene and a choice, so they
  appear in the plan's "Also required" card instead. Scene scores built from
  conditions *are* planned (landmine 16); the hypnosis sessions are solved
  outright (landmine 54); anything else built from options inside the gated
  scene is listed with what each option is worth.
- **Affection chasing is greedy and conservative.** `chase_gate` takes one
  candidate at a time, keeping it only if the whole plan still works, and
  `stat_topup` rejects any scene whose route, menu option or bump guards the run
  cannot promise — so both under-fill rather than over-promise. 18 run-scoped
  gates still end up short, most by a single point. What is left is mostly
  real content scarcity rather than a modelling gap: Haily "Arrival" wants
  `hailyLove ≥ 7` with only Haily·Corruption1 switched on and almost nothing
  Haily-shaped is open there, and several want a second breast
  expansion at a rung that offers one source.
  **Five Haily rows went short when landmine 70 landed, and that is the fix
  working.** Their old plans switched all eight girls to Pregnant and took the
  point from "Belly Club", but `hailyCorruptionPreg` needs `hailyCorruption5On`
  and those runs need Haily's ladder held at Uncorrupted — a setup the menu
  would never have offered. The point was never earnable; only the claim has
  gone. Neither pass will promise an
  automatic event it cannot guarantee fires, and their entry guards are usually
  affection thresholds, so hardly any get used.
- **Alex's "Double Trouble A+" needs `alexBE >= 2` and, because of the `elif`
  above it, `linaBE < 2`.** Only two of Alex's seven breast-expansion sources are
  open at Corruption 5; the plan earns the second from "Alex and Haily Can't
  Sleep" plus the Breast Expansion Hypnosis. "Double Trouble ++" needs both girls
  enlarged and gets Lina's the same way — the Broken Pocket Watch the hypnosis
  needs is an automatic event, so it no longer costs Saturday Morning and no
  second milk source is needed.
  **Alex "So... +" now comes up one short of `alexBE >= 2`, and that is
  correct.** Its run holds Alex, Haily and Cassidy all at Corruption 5, and the
  Sunday-afternoon Living Room button opens on `alexCorruption5On and
  hailyCorruption5On and cassidyCorruption5On` one `elif` *above* the hypnosis
  branch — so the game plays a different scene and the Breast Expansion Hypnosis
  is not on offer at all. The old plan scheduled it anyway because the `elif`
  chain's negation was never recorded (landmine 65). Losing the point is the
  honest answer, not a `chase_gate` failure: it is genuine scarcity of the kind
  the bullet above already describes.
- **36 targets have no contradiction-free route**, up from 12 once the missing
  fall-through negations were recorded (landmine 65). The originals are still
  there — Lisa "Delicious Cum", Carla "Hands On", Sami "Cunnilingus" and "Sex",
  Lina "LxS G01" (twice, dot and mail), Lina "Open" and the four that want
  "Moisturizing Alex" (the Corruption 2-3 bedroom scene) in a run that needs Alex
  higher — and the newcomers are the same shape: a rung switched on for one
  requirement and off for another. The largest cluster is Alex·Hedonist, which
  six plans need off for "Hypnotising Jenny" and on for something else.
  Reported as a toggle clash rather than papered over. Note the planner *does*
  try to route around one: `build_plan` bans the offending rung and the site that
  dragged it in, and keeps whichever attempt came out cleaner — with loose ends
  weighed ahead of clashes, because a plan that gives up says less than a plan
  with a warning (landmine 69).
- **A ceiling cannot express a joint constraint.**
  `not (alexCorruptionPregOn and hailyCorruptionPregOn)` needs only *one* of the
  two off, but the card is per character: it names the one the planner chose and
  puts the other in that row's tooltip as "or switch on …". So the card is
  sometimes stricter than the game, in a direction that is safe to follow.
- **A `tempFlag` lockout cannot be expressed at all.** `SamiExercise` carries
  `not (tempFlags["LinBedroom11_212"] == 3)`, and tempFlags never reset — so a
  player who ever took the Lin pegging branch, in any earlier loop, can never
  play this path again. The plan still lists it with an avoid line, which reads
  as advice when it is really a permanent lockout. Nothing in the fact model
  distinguishes the two.
- **Forced events that *do* cost a slot are not modelled.** The mirror of
  landmine 39: a slot label whose guards hold and which jumps in *without* a
  refund takes that sitting away from the player. Most such jumps refund
  internally, and most of the rest are `gateFirstRun` and so unreachable, which
  leaves `fuckfest`, `lisamaze`, `linaHoodie`, `C4AlexGoodbye` and the four
  fully-scripted slots (Friday Noon and the three dinners). Knowing whether one
  fires depends on the finished setup, so nothing reserves their slots yet.
- **One visit per room per slot, even for Explore.** `schedule`'s `played` set is
  keyed on (scene, slot) so that a free scene cannot be played twice over
  (landmine 40), and an explorable room is one scene however many of its menu
  options you take. So a plan wanting both "Search" and "Read the Red Book" from
  `LivingRoom` lists two rows at two slots, where the game would let you take
  both from the one menu. It costs the player nothing — the Search half is free
  either way — but it reads as two visits. The same rule is what lets a session
  that needs two sittings get them (landmine 54), and what makes `linahypbj`
  cost a second run of the hypnosis menus where the game reaches it inside the
  first.
- **`exit_dv` does not model a refund that hangs off a condition inside the
  chosen option.** `GardenRoom`'s "Behind the cabin" refunds under
  `if False: … else: dateVar -= 1`, but the delta sits in a nested block so it
  never reaches the edge, and `scene_dv` skips it because the guard is not a
  choice. The option is charged a sitting it does not take — conservative, and
  the branch is dead code in 0.62d, but a live one would cost a plan a slot.
- The planner finds *a* correct path, not the shortest. It does not attempt to
  satisfy several targets in one run.
