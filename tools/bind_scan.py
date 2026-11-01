#!/usr/bin/env python3
"""List Rust fns under rust/ and rust_binds/ that are marked `#[bind]` for Luau binding.

There are no per-file modes: a fn is bound when it carries `#[bind]` (or `#[bind(serde)]`, see tools/bind_attrs.py). The only `//BIND` line is
line 1 of rust/main.rs, `//BIND TNAME name`, which names the global table the fns under rust/ go into (table_name()). Any other `//BIND` line is
ignored with a `warn` on stderr (the old `//BIND pub|all|macro` modes are gone). Output: one `path:line fn` line per selected fn, or with
--json a list of {file, line, fn, params: [{name, ty}], ret, vis, cfgs, raw, serde} (ret "" = unit).
`serde` is true for `#[bind(serde)]` (tools/bind_serde.py: unknown path types are copied through mlua's serde support);
`raw` is true when the attribute also names `raw` (only so that bind_gen.py can report `raw` + `serde` as a conflict; tools/bind_attrs.py).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bind_attrs  # noqa: E402

HEADER = re.compile(r"//\s*BIND\b")
TNAME = re.compile(r"//\s*BIND\s+TNAME\b(?:\s+(\S+))?")
# Luau's reserved words: a table cannot be named by one (`local`, `end`, ... would not parse as a global's name).
RESERVED = (
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function", "if", "in",
    "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while",
)
NAME = re.compile(r"^(?!(?:" + "|".join(RESERVED) + r")$)[A-Za-z_][A-Za-z0-9_]*$")
# String/char literals: blanked like comments so braces and `fn` inside stay inert.
LITERAL = re.compile(
    r'b?r(#*)".*?"\1'
    r'|b?"(?:\\.|[^"\\])*"'
    r"|b?'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|.)|[^\\'\n])'",
    re.S,
)
FN = re.compile(
    r"\b(?P<pub>pub\b(?:\s*\([^)]*\))?\s+)?"
    r"(?P<mods>(?:(?:const|async|unsafe|extern)\b\s*)*)"
    r"fn\s+(?P<name>[A-Za-z_]\w*)"
)
BIND_ATTR = re.compile(r"(?:\w+\s*::\s*)*bind(?:\s*\(.*\))?", re.S)


def blank(text):
    return re.sub(r"[^\n]", " ", text)


def mask(src):
    """Same length and same line breaks as src; comments and literals become spaces."""
    out = []
    i, n = 0, len(src)
    while i < n:
        two = src[i : i + 2]
        if two == "//":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(blank(src[i:j]))
            i = j
        elif two == "/*":
            depth, j = 0, i
            while j < n:
                pair = src[j : j + 2]
                if pair == "/*":
                    depth, j = depth + 1, j + 2
                elif pair == "*/":
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
                if depth == 0:
                    break
            out.append(blank(src[i:j]))
            i = j
        else:
            m = LITERAL.match(src, i) if src[i] in "br\"'" else None
            if m:
                out.append(blank(m.group()))
                i = m.end()
            else:
                out.append(src[i])
                i += 1
    return "".join(out)


OPEN, CLOSE = "([{<", ")]}>"


def walk(text, start=0):
    """Yield (index, char, depth) over ()[]{}<>; the `>` of `->` is not a closer.

    An opener and its closer both carry the depth outside them.
    """
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c in CLOSE and not (c == ">" and text[i - 1 : i] == "-"):
            depth -= 1
        yield i, c, depth
        if c in OPEN:
            depth += 1


def squash(s):
    return re.sub(r"\s+", " ", s).strip()


def close_of(text, pos):
    """Index of the closer matching the opener at text[pos], or -1."""
    for i, c, d in walk(text, pos):
        if i > pos and d == 0 and c in CLOSE:
            return i
    return -1


def split_top(text, sep=","):
    parts, last = [], 0
    for i, c, d in walk(text):
        if c == sep and d == 0:
            parts.append(text[last:i])
            last = i + 1
    parts.append(text[last:])
    return [p for p in map(squash, parts) if p]


def parse_param(piece):
    for i, c, d in walk(piece):
        if c == ":" and d == 0 and piece[i - 1 : i] != ":" and piece[i + 1 : i + 2] != ":":
            name, ty = squash(piece[:i]), squash(piece[i + 1 :])
            break
    else:
        name, ty = piece, ""
    if re.search(r"(?:^|\s|&)self$", name):
        return {"name": "self", "ty": ""}
    return {"name": re.sub(r"^mut\s+", "", name), "ty": ty}


def signature(text, pos):
    """(params, ret, body, generic) of the fn whose name ends at text[pos].

    body is the index of the body `{` (-1 when the fn has none); generics are skipped.
    """
    ws = re.compile(r"\s*")
    pos = ws.match(text, pos).end()
    generic = text[pos : pos + 1] == "<"
    if generic:
        end = close_of(text, pos)
        pos = ws.match(text, pos if end < 0 else end + 1).end()
    if text[pos : pos + 1] != "(" or close_of(text, pos) < 0:
        return [], "", -1, generic
    end = close_of(text, pos)
    params = [parse_param(p) for p in split_top(text[pos + 1 : end])]
    stop, body = len(text), -1
    for i, c, d in walk(text, end + 1):
        if d == 0 and c in "{;":
            stop, body = i, i if c == "{" else -1
            break
    rest = ws.match(text, end + 1).end()
    if text[rest : rest + 2] != "->":
        return params, "", body, generic
    start, ret_end = rest + 2, stop
    for i, c, d in walk(text, start):
        if i >= stop:
            break
        if d == 0 and c == "w" and re.match(r"where\b", text[i:]) and not re.match(r"\w", text[i - 1 : i]):
            ret_end = i
            break
    return params, squash(text[start:ret_end]), body, generic


def attrs_before(text, pos, orig=None):
    """Bodies of the `#[...]` attributes stacked directly above text[pos]; `text` is mask()ed, `orig` (same length) is where the bodies are read from, so literals survive."""
    attrs, src = [], text if orig is None else orig
    head = text[:pos].rstrip()
    while head.endswith("]"):
        depth, k = 0, len(head) - 1
        while k >= 0:
            depth += (head[k] == "]") - (head[k] == "[")
            if depth == 0:
                break
            k -= 1
        before = head[:k].rstrip()
        if k < 0 or not before.endswith("#"):
            break
        attrs.append(src[k + 1 : len(head) - 1].strip())
        head = before[:-1].rstrip()
    return attrs


def header_warning(src, label):
    """A `//BIND` line 1 that is not rust/main.rs's `//BIND TNAME name` selects nothing any more: say so (stderr line or None)."""
    first = src.lstrip("\ufeff").split("\n", 1)[0]
    if not HEADER.match(first):
        return None
    if label == "rust/main.rs" and TNAME.match(first):
        return None
    return f"warn {label}:1 `//BIND` line ignored: files have no modes (mark fns `#[bind]`); only rust/main.rs line 1 may be `//BIND TNAME name`"


def brace_kind(text, pos, bodies):
    """`fn` for a fn body, `cfg_test` when its item header has #[cfg(test)], else `other`."""
    if pos in bodies:
        return "fn"
    header = text[max(text.rfind(c, 0, pos) for c in ";{}") + 1 : pos]
    return "cfg_test" if re.search(r"#\s*\[\s*cfg\s*\(\s*test\s*\)\s*\]", header) else "other"


def enclosing(text, starts, bodies):
    """{start: kinds of the braces open at text[start]} for the ascending positions in starts."""
    out, stack, todo = {}, [], iter(starts)
    nxt = next(todo, None)
    for m in re.finditer(r"[{}]", text):
        while nxt is not None and nxt < m.start():
            out[nxt], nxt = set(stack), next(todo, None)
        if m.group() == "{":
            stack.append(brace_kind(text, m.start(), bodies))
        elif stack:
            stack.pop()
    while nxt is not None:
        out[nxt], nxt = set(stack), next(todo, None)
    return out


def skip_reason(attrs, kinds, mods, generic, params):
    """Why a selected fn cannot be bound, or "" (first match wins)."""
    if "cfg_test" in kinds or any(re.fullmatch(r"cfg\s*\(\s*test\s*\)|test", a) for a in attrs):
        return "cfg_test"
    if "fn" in kinds:
        return "nested"
    if re.search(r"\basync\b", mods):
        return "async"
    if generic:
        return "generic"
    if any(p["name"] == "self" for p in params):
        return "self"
    # inside an impl / trait / inline mod / extern block: the generated `crate::<file module>::name` would not name it
    return "inner" if "other" in kinds else ""


def scan_text(src, label):
    warning = header_warning(src, label)
    if warning:
        print(warning, file=sys.stderr)
    text = mask(src)
    found = [(m, *signature(text, m.end())) for m in FN.finditer(text)]
    bodies = {body for _m, _p, _r, body, _g in found if body >= 0}
    kinds = enclosing(text, [m.start() for m, *_ in found], bodies)
    for m, params, ret, _body, generic in found:
        attrs = attrs_before(text, m.start(), src)
        if not any(BIND_ATTR.fullmatch(a) for a in attrs):
            continue
        line, name = text.count("\n", 0, m.start()) + 1, m.group("name")
        why = skip_reason(attrs, kinds[m.start()], m.group("mods"), generic, params)
        if why:
            print(f"skip {label}:{line} {name} {why}", file=sys.stderr)
            continue
        vis = bool(m.group("pub")) and not re.fullmatch(r"pub\s*\(\s*self\s*\)", m.group("pub").strip())
        cfgs = [a for a in attrs if re.match(r"cfg\s*\(", a)]
        opts = bind_attrs.parse(attrs)
        yield label, line, name, params, ret, {"vis": vis, "cfgs": cfgs, "raw": opts["raw"], "serde": opts["serde"]}


def table_name(root):
    """The global table name from line 1 of rust/main.rs (`//BIND TNAME name`), or None when there is no TNAME.

    Raises ValueError for a missing or invalid name: it must match NAME (`^(?!RESERVED$)[A-Za-z_][A-Za-z0-9_]*$`, RESERVED = Luau keywords).
    """
    path = Path(root) / "rust" / "main.rs"
    if not path.is_file():
        return None
    first = path.read_text(errors="replace").lstrip("\ufeff").split("\n", 1)[0]
    m = TNAME.match(first)
    if not m:
        return None
    name = m.group(1)
    if name is None:
        raise ValueError("rust/main.rs:1 TNAME needs a name")
    if not NAME.match(name):
        why = "a Luau keyword" if name in RESERVED else f"not a valid name ({NAME.pattern})"
        raise ValueError(f"rust/main.rs:1 TNAME {name!r} is {why}")
    return name


def scan_root(root):
    for name in ("rust", "rust_binds"):  # rust/ = your code, rust_binds/ = the glue (and its sample)
        base = Path(root) / name
        for path in sorted(base.rglob("*.rs")) if base.is_dir() else []:
            if "target" in path.relative_to(base).parts:
                continue
            label = path.relative_to(root).as_posix()
            yield from scan_text(path.read_text(errors="replace"), label)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true", help="JSON list with params and ret")
    args = ap.parse_args()
    found = list(scan_root(args.root))
    if args.json:
        keys = ("file", "line", "fn", "params", "ret")
        print(json.dumps([{**dict(zip(keys, f)), **f[5]} for f in found], indent=2))
        return
    for label, line, name, *_ in found:
        print(f"{label}:{line} {name}")


if __name__ == "__main__":
    main()
