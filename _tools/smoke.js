// Render every target through the app's own script in a minimal DOM shim.
//
// Two passes, because they break in different places. `renderPlan` is the page
// for one selected target; `render` is the whole rail -- the kind tabs with
// their counts, the list, the grouping headings and every row button. A new
// tab that crashed the rail used to print `failures: 0` here, because only the
// plan was ever driven.
const fs = require("fs");
const src = fs.readFileSync("walkthrough.html", "utf8");

const script = src.split(/<script>\s*"use strict";/)[1].split("</script>")[0];
const json = src.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1]
                .replace(/<\\\//g, "</");

class E {
  constructor(tag){ this.tag=tag; this.children=[]; this.className=""; this.dataset={};
    this.style={}; this._text=null; this.attrs={}; this.classList={
      add:c=>{this.className=(this.className+" "+c).trim();},
      contains:c=>this.className.split(/\s+/).includes(c)}; }
  set textContent(v){ this._text=v; this.children=[]; }
  get textContent(){ return this._text!=null?this._text
    :this.children.map(c=>c.textContent??"").join(""); }
  append(...n){ for(const x of n) this.children.push(typeof x==="string"?{textContent:x}:x); }
  appendChild(n){ this.children.push(n); n.parentElement=this; return n; }
  setAttribute(k,v){ this.attrs[k]=v; }
  // Real enough for the class selectors the app uses (".kind", ".n", ".who").
  // Returning [] and null hid `renderKinds`, which reads `.n` off each tab.
  querySelectorAll(sel){
    const cls = String(sel).replace(/^\./,"");
    const out = [];
    (function walk(n){
      for(const k of n.children||[]){
        if(k instanceof E){
          if(k.className.split(/\s+/).includes(cls)) out.push(k);
          walk(k);
        }
      }
    })(this);
    return out;
  }
  querySelector(sel){ return this.querySelectorAll(sel)[0] || null; }
}
const byId = {};
global.document = {
  createElement: t => new E(t),
  createTextNode: t => ({ textContent: String(t) }),
  getElementById: id => byId[id] || (byId[id] = new E("div")),
  querySelector: s => { const k = s.replace("#",""); return byId[k] || (byId[k] = new E("div")); },
};
byId.data = { textContent: json };

// capture the roster/list/plan containers so we can drive selection by hand
const fn = new Function(script
  + "\n;return {DATA,state,render,renderList,renderPlan,visible,current};");
let api;
try { api = fn(); }
catch (e) { console.error("SCRIPT LOAD FAILED:", e.message); process.exit(1); }

const { DATA, state } = api;
let ok = 0, fail = [];
for (const t of DATA.targets) {
  state.who = t.char; state.kind = t.kind; state.id = t.id;
  try { api.renderPlan(); ok++; }
  catch (e) { fail.push(t.id + ": " + e.message); }
}

// every (character, tab) pair, including the empty ones -- Lun has a single dot
// and nothing else, so four of her five tabs are the "nothing of this kind" path
const CHARS = [...new Set(DATA.targets.map(t => t.char))];
const KINDS = [...new Set(DATA.targets.map(t => t.kind))];
let rails = 0, rows = 0;
for (const who of CHARS) for (const kind of KINDS) {
  state.who = who; state.kind = kind; state.id = null; state.q = "";
  try {
    api.render();
    rows += api.visible().length;
    rails++;
    // and again through the search box, which is a different code path in
    // `renderList` (the "nothing matches" branch) and in `matchWhy`
    state.q = "a"; api.renderList(); api.renderPlan();
    state.q = "";
  } catch (e) { fail.push(who + "/" + kind + ": " + e.message); }
}

console.log("rendered ok:", ok);
console.log("rails ok:", rails, "rows:", rows);
console.log("failures:", fail.length);
fail.slice(0, 10).forEach(f => console.log("  ", f));
