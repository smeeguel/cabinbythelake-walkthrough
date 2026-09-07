const fs=require('fs');
let s=fs.readFileSync('walkthrough.html','utf8');
s=s.replace('state = {who:"Alex", kind:"corruption", q:"", id:null}',
            'state = {who:"'+process.argv[2]+'", kind:"'+process.argv[3]+'", q:"", id:"'+process.argv[4]+'"}');
fs.writeFileSync('_analysis/preview.html',s);
