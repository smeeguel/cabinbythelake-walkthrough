# Minimal Ren'Py .rpyc (RPC2) AST extractor -> pseudo-.rpy source
import io, os, sys, zlib, pickle, struct

class Stub:
    _cls = "?"
    def __init__(self, *a, **k):
        if a: self.__dict__["_args"] = a
        if k: self.__dict__["_kwargs"] = k
    def __repr__(self):
        return "<%s %r>" % (self._cls, self.__dict__)

class PyExpr(str):
    # renpy PyExpr subclasses unicode; payload is arg 0. Pickled via NEWOBJ.
    def __new__(cls, s=u"", filename=None, linenumber=0, *a, **k):
        if isinstance(s, bytes): s = s.decode("utf-8", "replace")
        return str.__new__(cls, s)
    def __setstate__(self, state): pass
    def __getstate__(self): return None

class Sentinel(Stub):
    _cls = "Sentinel"

class PyCodeStub(Stub):
    # renpy PyCode.__getstate__ -> (1, source, location, mode)
    _cls = "renpy.ast.PyCode"
    def __setstate__(self, state):
        if isinstance(state, tuple) and len(state) >= 4:
            self.source, self.location, self.mode = state[1], state[2], state[3]
        elif isinstance(state, dict):
            self.__dict__.update(state)
        else:
            self.source = state

class RDict(dict):
    def __setstate__(self, st):
        if isinstance(st, dict): self.__dict__.update(st)
class RList(list):
    def __setstate__(self, st):
        if isinstance(st, dict): self.__dict__.update(st)
class RSet(set):
    def __setstate__(self, st):
        if isinstance(st, (list, tuple, set)): self.update(st)
        elif isinstance(st, dict): self.__dict__.update(st)

_cache = {}
def make(mod, name):
    key = mod + "." + name
    if name == "PyExpr":
        return PyExpr
    if name == "Sentinel":
        return Sentinel
    if name == "PyCode": return PyCodeStub
    if name == "RevertableDict": return RDict
    if name == "RevertableList": return RList
    if name == "RevertableSet": return RSet
    if key not in _cache:
        c = type(str(name), (Stub,), {"_cls": key})
        def setstate(self, state, _c=None):
            if isinstance(state, tuple) and len(state) == 2:
                d, s = state
                if d: self.__dict__.update(d)
                if s:
                    for k, v in s.items(): setattr(self, k, v)
            elif isinstance(state, dict):
                self.__dict__.update(state)
            else:
                self.__dict__["_state"] = state
        c.__setstate__ = setstate
        c.__reduce__ = None
        _cache[key] = c
    return _cache[key]

class U(pickle.Unpickler):
    def find_class(self, mod, name):
        if mod in ("__builtin__", "builtins"):
            if name in ("set", "frozenset", "list", "dict", "tuple", "object", "bytearray"):
                return getattr(__import__("builtins"), name)
        if mod == "collections" and name == "OrderedDict":
            import collections; return collections.OrderedDict
        return make(mod, name)
    def persistent_load(self, pid):
        return None

def load_rpyc(path):
    data = open(path, "rb").read()
    if data[:10] == b"RENPY RPC2":
        pos = 10
        slots = {}
        while True:
            slot, start, length = struct.unpack("<III", data[pos:pos+12])
            pos += 12
            if slot == 0: break
            slots[slot] = data[start:start+length]
        raw = zlib.decompress(slots[1])
    else:
        raw = zlib.decompress(data)
    return U(io.BytesIO(raw), encoding="latin1", errors="replace").load()

# ---------- rendering ----------

def cls(o):
    return getattr(type(o), "_cls", "")

def short(o):
    return cls(o).rsplit(".", 1)[-1]

def pycode(o):
    if o is None: return ""
    if isinstance(o, (str, bytes)):
        return o.decode("utf-8", "replace") if isinstance(o, bytes) else o
    src = getattr(o, "source", None)
    if src is None: src = getattr(o, "_state", None)
    if isinstance(src, bytes): src = src.decode("utf-8", "replace")
    if isinstance(src, (list, tuple)): src = "\n".join(str(x) for x in src)
    return src if isinstance(src, str) else repr(src)

def txt(s):
    if isinstance(s, bytes): return s.decode("utf-8", "replace")
    return s if s is not None else ""

def imspec(sp):
    if sp is None: return ""
    try:
        names = sp[0]
        out = " ".join(txt(x) for x in names)
        # at / behind / as / with
        if len(sp) > 2 and sp[2]: out += " as " + txt(sp[2])
        if len(sp) > 1 and sp[1]: out += " at " + ", ".join(pycode(x) for x in sp[1])
        return out
    except Exception:
        return repr(sp)

def dispname(o):
    n = getattr(type(o), "_cls", None) or getattr(o, "__name__", None) or ""
    n = str(n).rsplit(".", 1)[-1]
    return n[3:] if n.startswith("sl2") else n

def sl_render(children, out, ind=0):
    if not children: return
    pad = "    " * ind
    for c in children:
        t = short(c)
        d = getattr(c, "__dict__", {})
        if t == "SLDisplayable":
            name = dispname(d.get("displayable")) or (txt(d.get("style")) or "?")
            pos = " ".join(str(p) for p in (d.get("positional") or []))
            kw = " ".join("%s %s" % (k, v) for k, v in (d.get("keyword") or []))
            line = ("%s%s %s %s" % (pad, name, pos, kw)).rstrip()
            out.append(line)
            sl_render(d.get("children"), out, ind + 1)
        elif t == "SLIf":
            first = True
            for cond, blk in d.get("entries") or []:
                if cond is None:
                    out.append("%selse:" % pad)
                else:
                    out.append("%s%s %s:" % (pad, "if" if first else "elif", cond))
                first = False
                sl_render(getattr(blk, "children", None), out, ind + 1)
        elif t == "SLFor":
            out.append("%sfor %s in %s:" % (pad, txt(d.get("variable")), d.get("expression")))
            sl_render(d.get("children"), out, ind + 1)
        elif t == "SLPython":
            out.append("%s$ %s" % (pad, pycode(d.get("code")).replace("\n", "; ")))
        elif t == "SLDefault":
            out.append("%sdefault %s = %s" % (pad, txt(d.get("variable")), d.get("expression")))
        elif t == "SLUse":
            out.append("%suse %s %s" % (pad, d.get("target"), d.get("args") or ""))
        elif t == "SLShowIf":
            out.append("%sshowif:" % pad)
            sl_render(d.get("children"), out, ind + 1)
        elif t in ("SLBlock",):
            kw = " ".join("%s %s" % (k, v) for k, v in (d.get("keyword") or []))
            if kw: out.append("%s%s" % (pad, kw))
            sl_render(d.get("children"), out, ind)
        else:
            out.append("%s# <%s>" % (pad, t))
            sl_render(d.get("children"), out, ind + 1)

def render(block, out, ind=0):
    if not block: return
    pad = "    " * ind
    for n in block:
        t = short(n)
        d = n.__dict__
        ln = d.get("linenumber", "")
        try:
            if t == "Label":
                out.append("")
                out.append("%slabel %s:" % (pad, txt(d.get("name"))))
                render(d.get("block"), out, ind + 1)
            elif t == "Say":
                who = d.get("who")
                who = txt(who) if who else ""
                what = txt(d.get("what"))
                attrs = d.get("attributes") or ()
                a = (" " + " ".join(txt(x) for x in attrs)) if attrs else ""
                out.append('%s%s%s "%s"' % (pad, who, a, what.replace("\n", "\\n")))
            elif t == "Menu":
                out.append("%smenu:" % pad)
                if d.get("with_"): pass
                for item in d.get("items") or []:
                    lab, cond, blk = item[0], item[1], item[2]
                    c = pycode(cond)
                    if blk is None:
                        out.append('%s    "%s"   # caption' % (pad, txt(lab)))
                        continue
                    if c and c != "True":
                        out.append('%s    "%s" if %s:' % (pad, txt(lab), c))
                    else:
                        out.append('%s    "%s":' % (pad, txt(lab)))
                    render(blk, out, ind + 2)
            elif t == "If":
                first = True
                for cond, blk in d.get("entries") or []:
                    c = pycode(cond)
                    kw = "if" if first else ("else" if c == "True" else "elif")
                    first = False
                    if kw == "else":
                        out.append("%selse:" % pad)
                    else:
                        out.append("%s%s %s:" % (pad, kw, c))
                    render(blk, out, ind + 1)
            elif t == "While":
                out.append("%swhile %s:" % (pad, pycode(d.get("condition"))))
                render(d.get("block"), out, ind + 1)
            elif t == "Python":
                src = pycode(d.get("code"))
                lines = [l for l in src.split("\n")]
                if len(lines) == 1:
                    out.append("%s$ %s" % (pad, lines[0]))
                else:
                    out.append("%spython:" % pad)
                    for l in lines: out.append("%s    %s" % (pad, l))
            elif t == "Init":
                render(d.get("block"), out, ind)
            elif t == "Default":
                out.append("%sdefault %s = %s" % (pad, txt(d.get("varname")), pycode(d.get("code"))))
            elif t == "Define":
                out.append("%sdefine %s = %s" % (pad, txt(d.get("varname")), pycode(d.get("code"))))
            elif t == "Jump":
                out.append("%sjump %s%s" % (pad, "expression " if d.get("expression") else "", txt(d.get("target"))))
            elif t == "Call":
                out.append("%scall %s%s" % (pad, "expression " if d.get("expression") else "", txt(d.get("label"))))
            elif t == "Return":
                out.append("%sreturn %s" % (pad, pycode(d.get("expression")) or ""))
            elif t == "Scene":
                out.append("%sscene %s" % (pad, imspec(d.get("imspec"))))
            elif t == "Show":
                out.append("%sshow %s" % (pad, imspec(d.get("imspec"))))
            elif t == "Hide":
                out.append("%shide %s" % (pad, imspec(d.get("imspec"))))
            elif t == "With":
                out.append("%swith %s" % (pad, pycode(d.get("expr"))))
            elif t == "UserStatement":
                out.append("%s%s" % (pad, txt(d.get("line"))))
            elif t == "Pass":
                out.append("%spass" % pad)
            elif t in ("Translate", "EndTranslate", "TranslateString", "TranslateBlock"):
                if d.get("block"): render(d.get("block"), out, ind)
            elif t == "Screen":
                scr = d.get("screen")
                nm = txt(getattr(scr, "name", "")) if scr is not None else ""
                out.append("")
                out.append("%sscreen %s:" % (pad, nm))
                sl_render(getattr(scr, "children", None), out, ind + 1)
            elif t == "Style":
                out.append("%sstyle %s" % (pad, txt(d.get("style_name"))))
            elif t == "Image":
                out.append("%simage %s = %s" % (pad, imspec(d.get("imgname")) if not isinstance(d.get("imgname"), (list, tuple)) else " ".join(txt(x) for x in d.get("imgname")), pycode(d.get("code"))))
            elif t == "Transform":
                out.append("%stransform %s" % (pad, txt(d.get("varname"))))
            else:
                out.append("%s# <%s> %s" % (pad, t, {k: v for k, v in d.items() if k not in ("block", "next", "filename", "linenumber", "name", "col_offset")}))
                if d.get("block"): render(d.get("block"), out, ind + 1)
        except Exception as e:
            out.append("%s# ERROR rendering %s: %r" % (pad, t, e))

def main(src_dir, dst_dir):
    os.makedirs(dst_dir, exist_ok=True)
    files = sorted(f for f in os.listdir(src_dir) if f.endswith(".rpyc"))
    for f in files:
        try:
            data = load_rpyc(os.path.join(src_dir, f))
            stmts = data[1] if isinstance(data, tuple) else data
            out = []
            render(stmts, out, 0)
            open(os.path.join(dst_dir, f[:-5] + ".rpy"), "w", encoding="utf-8").write("\n".join(out))
            print("OK   %-40s %6d lines" % (f, len(out)))
        except Exception as e:
            print("FAIL %-40s %r" % (f, e))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
