-- Calls the fns bound from rust_binds/luau/demo_binds.rs (every fn there marked `#[bind]` is a global). Run: luaxite path src/bind_demo.luau
print(demo_add(2, 3))
print(demo_greet("Luau"))
print(pcall(demo_div, 1, 0))
demo_set_global("answer", 42) -- Rust got the mlua instance (`&mlua::Lua` first param) and set a global
print(answer)
