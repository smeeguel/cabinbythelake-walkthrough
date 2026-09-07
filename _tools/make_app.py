# Inline app_data.json into the template to produce the shippable single file.
import json, os

tpl = open("_tools/template.html", encoding="utf-8").read()
data = open("_analysis/app_data.json", encoding="utf-8").read()

# The payload sits in a <script type="application/json">, so the only sequence
# that can break out of it is a literal "</script>"; JSON has no other escapes
# that matter here.
data = data.replace("</", "<\\/")

out = tpl.replace("__DATA__", data)
open("walkthrough.html", "w", encoding="utf-8").write(out)
print("walkthrough.html  %.1f KB" % (len(out.encode("utf-8")) / 1024))

# ---- index.html: the same app as a document that can stand on its own ----
#
# walkthrough.html is a *fragment*: the Artifact host wraps it in
# `<!doctype html><head>…</head><body>` at publish time, so it must not carry
# those tags itself. Opened straight off disk or served from a static host that
# is exactly what is missing -- and a page with no doctype renders in **quirks
# mode**, which is not the layout the artifact shows. So emit a second file that
# is a real document, for hosting anywhere else and for checking a layout
# question without the artifact's own chrome in the way.
#
# It is called `index.html` because that is the name a static host serves from a
# bare URL. Naming it anything else means renaming it by hand after every build,
# which is a step to forget.
#
# The split is at the first `</style>`: everything above it is the fragment's
# head material (charset, viewport, title, the font <link>s and the stylesheet),
# everything below is markup and scripts. Putting the head material in a real
# <head> rather than leaving it in <body> is the difference between "browsers
# forgive this" and "this is a valid document".
head, sep, body = out.partition("</style>")
assert sep, "template no longer has a <style> block -- fix the split in make_app"

doc = ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
       + head + sep + "\n</head>\n<body>\n"
       + body.lstrip("\n")
       + "\n</body>\n</html>\n")
open("index.html", "w", encoding="utf-8").write(doc)
print("index.html  %.1f KB" % (len(doc.encode("utf-8")) / 1024))
