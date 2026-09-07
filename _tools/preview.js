// node _tools/preview.js <Who> <kind> <id>  ->  _analysis/preview.html, pre-selected.
//
// Reads index.html, not the fragment: walkthrough.html carries no doctype
// (the Artifact host supplies one), so a browser opening it off disk renders it
// in quirks mode -- which is not the layout the artifact shows, and so not a
// layout worth screenshotting.
const fs=require('fs');
let s=fs.readFileSync('index.html','utf8');
s=s.replace('state = {who:"Alex", kind:"corruption", q:"", id:null}',
            'state = {who:"'+process.argv[2]+'", kind:"'+process.argv[3]+'", q:"", id:"'+process.argv[4]+'"}');
fs.writeFileSync('_analysis/preview.html',s);
