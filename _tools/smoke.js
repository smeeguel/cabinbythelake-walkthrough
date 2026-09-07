// Render every target through the app's own script in a minimal DOM shim.
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
  querySelectorAll(){ return []; }
  querySelector(){ return null; }
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
const fn = new Function(script + "\n;return {DATA,state,render,renderPlan,current};");
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
console.log("rendered ok:", ok);
console.log("failures:", fail.length);
fail.slice(0, 10).forEach(f => console.log("  ", f));
