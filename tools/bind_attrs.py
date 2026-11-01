#!/usr/bin/env python3
"""The options of a `#[bind(..)]` attribute that tools/bind_scan.py reads (S41: `serde`; S43: `raw`, read only so that `raw` + `serde` can be reported as a conflict).
`#[bind]`, `#[bind(serde)]`, `#[bind(raw, serde)]` (also as `zenpel_bind::bind`): the comma-separated items are looked at one by one, in any order. Any other item (a string, `ret = ".."`, ..) is ignored, and the fn is still selected as before (this tree has no Luau names: a fn is a global of its own name).
`raw` is not a bind mode in this tree: alone it changes nothing; with `serde` on the same attribute the fn is a `conflict` (tools/bind_gen.py).
Pure text helper: tools/bind_scan.py (`scan_text`) calls `parse`.
"""
import re

CALL = re.compile(r"(?:\w+\s*::\s*)*bind\s*\((.*)\)", re.S)
EMPTY = {"raw": False, "serde": False}


def items(inner):
    """The comma-separated items of the text inside `bind(..)` (commas inside a string do not split), stripped; one trailing comma is fine."""
    out, cur, quoted = [], "", False
    for ch in inner:
        quoted ^= ch == '"'
        if ch == "," and not quoted:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out[:-1] if out[-1] == "" else out


def one(attr):
    """{"raw": bool, "serde": bool} for one attribute body, or None when it is not a `bind(..)` naming `raw` or `serde`."""
    m = CALL.fullmatch(attr)
    if not m:
        return None
    its = items(m.group(1))
    opts = {k: k in its for k in EMPTY}
    return opts if opts != EMPTY else None


def parse(attrs):
    """{"raw": bool, "serde": bool} from the bodies of the `#[..]` attributes above a fn (the first `bind(..)` that names `raw` or `serde` wins; all False when none does)."""
    for a in attrs:
        got = one(a)
        if got:
            return got
    return dict(EMPTY)
