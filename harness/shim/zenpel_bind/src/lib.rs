//! `#[bind]`: marks a fn under `rust/` to be bound to the Luau state as a global of the same name.
//!
//! The attribute itself does nothing: it returns the item untouched. The binding is generated at build time, outside the compiler:
//! `build.rs` runs `tools/bind_gen.py` (which reads the fns `tools/bind_scan.py` selects) and `rust_binds/luau/mod.rs` includes the result.
//! The fns under `rust/` become fields of one global table named by `//BIND TNAME name` on line 1 of `rust/main.rs`.

use proc_macro::TokenStream;

/// Marks the fn for binding. Passthrough: the fn is emitted exactly as written.
#[proc_macro_attribute]
pub fn bind(_args: TokenStream, item: TokenStream) -> TokenStream {
    item
}
