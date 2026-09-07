# template.html is generated: edit _head.html (markup + CSS) and _app.js (logic),
# never template.html itself -- it is overwritten by this script.
head = open("_tools/_head.html", encoding="utf-8").read()
js = open("_tools/_app.js", encoding="utf-8").read()

out = (head
       + '<script id="data" type="application/json">__DATA__</script>\n'
       + '<script>\n' + js + '</script>\n')
open("_tools/template.html", "w", encoding="utf-8").write(out)
print("template.html  %.1f KB" % (len(out.encode("utf-8")) / 1024))
