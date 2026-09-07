# Horizontal-overflow probe.
#
#   python _tools/probe.py                 # 320, 360, 412, 480, 640, 768, 900
#   python _tools/probe.py 360             # one width
#
# Reads index.html, so run it after make_app.py.
#
# Prints one line per width; every one must read "0 findings". A finding is a box
# wider than the viewport, or a box with content scrolling sideways inside it --
# the two shapes of "this page scrolls sideways on a phone".
#
# Why an iframe: headless Chrome will not open a window narrower than about
# 500 CSS px on Windows, and `--window-size` below that is silently clamped. An
# iframe carries its own viewport, so `@media (max-width:…)` inside it evaluates
# against the iframe's width -- which is the only way to measure a 360px layout
# here. The 15px the iframe spends on its own scrollbar is added back, so the
# width asked for is the width measured.
#
# The sweep renders 90 targets (the three biggest plans per character per kind,
# so the sessions, the long avoid rows and the fullest setup rosters are all in
# it), plus the seven widest reward pages -- those have no plan at all, so the
# ranking above cannot reach them -- plus the empty state, and unions the
# findings.

import os, re, subprocess, sys, html

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "_analysis")
CHROME = os.environ.get("CHROME") or (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe")
WIDTHS = [320, 360, 412, 480, 640, 768, 900]
SCROLLBAR = 15

DETECTOR = r"""
<pre id="PROBE">pending</pre>
<script>
(function(){
function key(n){
  var cls = (typeof n.className === "string" ? n.className : "").trim().split(/\s+/).join(".");
  return n.tagName + (cls ? "." + cls : "");
}
var bad = {};
function scan(tag){
  var W = document.documentElement.clientWidth;
  var all = document.querySelectorAll("*");
  for (var i=0;i<all.length;i++){
    var n = all[i];
    if (n.tagName === "HTML" || n.tagName === "BODY" || n.id === "PROBE") continue;
    var r = n.getBoundingClientRect();
    if (r.width > W + 1){
      var k = "WIDE " + key(n);
      if (!bad[k]) bad[k] = "w=" + Math.round(r.width) + "/" + W + "  " + tag
        + " :: " + (n.textContent||"").slice(0,55).replace(/\s+/g," ");
    }
    if (n.scrollWidth - n.clientWidth > 1 && n.clientWidth > 0){
      var k2 = "OVERFLOW " + key(n) + " (overflow-x:" + getComputedStyle(n).overflowX + ")";
      if (!bad[k2]) bad[k2] = "sw=" + n.scrollWidth + " cw=" + n.clientWidth + "  " + tag
        + " :: " + (n.textContent||"").slice(0,55).replace(/\s+/g," ");
    }
  }
}
function run(){
  var ts = DATA.targets.filter(function(t){return t.plan;});
  var pick = [], seen = {};
  ts.slice().sort(function(a,b){
    return JSON.stringify(b.plan).length - JSON.stringify(a.plan).length;
  }).forEach(function(t){
    var k = t.char + "|" + t.kind;
    seen[k] = (seen[k]||0) + 1;
    if (seen[k] <= 3) pick.push(t);
  });
  pick = pick.slice(0, 90);
  /* A replay tile whose whole condition is corruption rungs has no plan at all,
     so the sweep above never reaches it -- and the widest thing either new tab
     draws is exactly that page: Sami's "All Tied Up" is five cross-link buttons
     on one row. Add the most-linked tiles and one that needs nothing. */
  DATA.targets.filter(function(t){ return t.requires && t.requires.length; })
    .sort(function(a,b){ return b.requires.length - a.requires.length; })
    .slice(0, 6).forEach(function(t){ pick.push(t); });
  var free = DATA.targets.filter(function(t){ return t.available; })[0];
  if (free) pick.push(free);
  pick.forEach(function(t){
    state.who = t.char; state.kind = t.kind; state.id = t.id;
    render(); scan(t.char + "/" + t.kind);
  });
  state.id = null; render(); scan("(no selection)");
  var out = Object.keys(bad).sort().map(function(k){ return k + "\n      " + bad[k]; });
  document.getElementById("PROBE").textContent =
    "=== " + out.length + " findings @" + document.documentElement.clientWidth
    + "px, doc.scrollWidth=" + document.documentElement.scrollWidth + " ===\n"
    + out.join("\n");
}
setTimeout(function(){
  try { run(); }
  catch(e){ document.getElementById("PROBE").textContent = "ERROR " + e.message; }
}, 900);
})();
</script>
"""

HOST = """<!doctype html><meta charset="utf-8">
<style>html,body{margin:0}iframe{width:%dpx;height:900px;border:0}</style>
<iframe id="f" src="probe-app.html"></iframe>
<pre id="OUT">pending</pre>
<script>
setTimeout(function(){
  try{
    var d = document.getElementById("f").contentWindow.document;
    document.getElementById("OUT").textContent = d.getElementById("PROBE").textContent;
  }catch(e){ document.getElementById("OUT").textContent = "HOST ERROR " + e.message; }
}, 5000);
</script>
"""


def build(width):
    """Write the two harness pages into _analysis/ for one viewport width."""
    os.makedirs(OUT, exist_ok=True)
    # index.html, not the fragment: a page with no doctype renders in quirks
    # mode, and measuring that would answer a question nobody asked.
    src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    app = src.replace("</body>", DETECTOR + "\n</body>")
    open(os.path.join(OUT, "probe-app.html"), "w", encoding="utf-8").write(app)
    open(os.path.join(OUT, "probe.html"), "w", encoding="utf-8").write(
        HOST % (width + SCROLLBAR))


def run(width):
    build(width)
    url = "file:///" + os.path.join(OUT, "probe.html").replace("\\", "/")
    dom = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--allow-file-access-from-files",
         "--window-size=900,1000", "--virtual-time-budget=20000", "--dump-dom", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    m = re.search(r'<pre id="OUT">(.*?)</pre>', dom, re.S)
    return html.unescape(m.group(1)) if m else "NO OUTPUT (chrome produced %d chars)" % len(dom)


if __name__ == "__main__":
    widths = [int(a) for a in sys.argv[1:]] or WIDTHS
    bad = 0
    for w in widths:
        report = run(w)
        first = report.split("\n", 1)[0]
        print("%4dpx  %s" % (w, first))
        if "0 findings" not in first:
            bad += 1
            print(report.split("\n", 1)[1] if "\n" in report else "")
    print("widths with findings:", bad)
    sys.exit(1 if bad else 0)
