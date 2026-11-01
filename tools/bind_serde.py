#!/usr/bin/env python3
"""`#[bind(serde)]`: your own serde types as bound parameters and returns (S41; S42 adds Option / Vec / Result; S43: `raw` + `serde` on one fn is a `conflict`, decided in bind_gen.generate).
A parameter or return whose type is a plain path (`Config`, `crate::Config`, `a::b::Config`; no generics, no reference) that the other forms of tools/bind_gen.py do not know is copied through mlua's serde support: the closure takes an `mlua::Value` and the generated code calls `mlua::LuaSerdeExt::from_value(lua, v)?` before the call; a return goes through `mlua::LuaSerdeExt::to_value_with(lua, &r, OPTIONS)`.
The type is never written in the generated code: `from_value` gets its `T` by inference from the parameter of the fn it is passed to, so a type spelled `Config` in your module needs no import in `crate::luau`.
Such a type may also sit inside `Option<..>` and `Vec<..>` (nested too, `Vec<Option<Config>>`; not `Option<Option<..>>`), as an argument, as a return, or as the `T` of `Result<T, E>`; the WHOLE type is handed to serde (`from_value` infers `Option<Config>`), so nil is `None` and a Luau sequence is a `Vec`. A `Result`'s Err still raises a Luau error with E's text.
The user guarantees `serde::Deserialize` / `Serialize` (needs the `serialize` feature of mlua and a `serde` dependency, both in Cargo.toml).
Pure text helpers (no I/O): tools/bind_gen.py (`split_sig`, `statement`) calls them. `known(t)` is the generator's own check for the types it converts without serde.
"""
import re

import bind_scan

PATH = re.compile(r"(?:::)?[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*")
OPTION = re.compile(r"Option<(.*)>", re.S)
VEC = re.compile(r"(?:std::vec::)?Vec<(.*)>", re.S)
RESULT = re.compile(r"(?:anyhow::|mlua::|std::result::)?Result<(.*)>", re.S)
LUA = "mlua::LuaSerdeExt"
# mlua turns `None` and `()` into its `null` light userdata by default, which a script cannot compare with nil: here they become nil (a `None` inside a Vec leaves a hole in the Luau array).
OPTIONS = "mlua::serde::SerializeOptions::new().serialize_none_to_null(false).serialize_unit_to_null(false)"


def path_type(ty):
    """True for a plain path type: no generics, no reference, no tuple; `Self` and `()` are not."""
    return bool(PATH.fullmatch(ty)) and ty != "Self"


def leaf(ty):
    """The type inside any `Option<..>` / `Vec<..>` wrappers of `ty` (`Vec<Option<Config>>` -> `Config`); None for `Option<Option<..>>` (not a Luau shape). A type with no wrapper is its own leaf."""
    ty, last = ty.strip(), None
    while True:
        m = OPTION.fullmatch(ty)
        kind = "Option"
        if not m:
            m, kind = VEC.fullmatch(ty), "Vec"
        if not m:
            return ty
        if kind == "Option" and last == "Option":
            return None
        ty, last = m.group(1).strip(), kind


def unknown(ty, known):
    """True when `ty` is a plain path or an Option / Vec of one that the other forms do not take, so serde converts the whole type."""
    inner = leaf(ty)
    return not known(ty) and inner is not None and path_type(inner) and not known(inner)


def arg_type(ty, known):
    """The type of the closure parameter: `mlua::Value` for a serde argument, else None (the caller spells the type as usual)."""
    return "mlua::Value" if unknown(ty, known) else None


def arg_lines(args, names, known):
    """The `let aN = from_value(lua, aN)?;` statements (one line of text, each ending with a space) for the serde arguments of `args` ({name, ty}); "" when there are none."""
    return "".join(f"let {n} = {LUA}::from_value(lua, {n})?; " for n, a in zip(names, args) if unknown(a["ty"], known))


def ret_inner(ret):
    """The `T` of `Result<T, E>` / `Result<T>` (the first top-level type argument), else `ret` itself."""
    m = RESULT.fullmatch(ret)
    parts = bind_scan.split_top(m.group(1)) if m else []
    return parts[0].strip() if parts else ret


def ret_serde(ret, known):
    """True when the value returned (the `T` of a `Result<T, E>`) is a serde type: the return goes through `to_value`."""
    return unknown(ret_inner(ret), known)


def ret_lines(call, tail=""):
    """(statement text before the value, the value expression) for a serde return of `call`: `let r = call<tail>; ` and `to_value_with(lua, &r, OPTIONS)`; `tail` is the `.map_err(..)?` of a Result."""
    return f"let r = {call}{tail}; ", f"{LUA}::to_value_with(lua, &r, {OPTIONS})"
