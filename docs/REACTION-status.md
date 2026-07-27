# Real ReAction UI from Python — current status

**Short version:** the BOOPSI object model is exposed and works.
Actually **rendering** a ReAction window from Python needs one more
`_amiga` entry point (`OpenClass`) that I haven't shipped yet. There's
also a rendering bug in `open_dialog`'s label placement that surfaced
when it was exercised with 4+ fields.

## What works today

`boopsi_probe.py` demonstrates the object plumbing:

- `_amiga.new_object("button.gadget", {tags})` → handle
- `_amiga.new_object_multi("layout.gadget", [(tag, val), ...])` → handle
  (list-of-tuples form; needed because `LAYOUT_AddChild` repeats and
  Python dict keys can't)
- `_amiga.set_attrs(obj, {tags}, window_handle=0)` → updates attrs
- `_amiga.get_attr(obj, tag)` → int
- `_amiga.do_method(obj, method_id, *args)` → int (wraps `IDoMethod`)
- `_amiga.dispose_object(obj)` → free

Tested against `button.gadget`, `string.gadget`, `integer.gadget`,
`layout.gadget`, `listbrowser.gadget`, `chooser.gadget`. All allocate
+ dispose cleanly.

## What doesn't work yet

### 1. `WM_OPEN` on `window.class` returns 0

Even with the WM_OPEN NULL arg fix (from the OS4 wiki), the window
never actually opens.

Root cause (per [os4coding.net trixie blog][1]): OS4 wants
`OpenClass("window.class", 52, &WindowClass)` first, then
`NewObject(WindowClass, NULL, tags)`. Class-scanner lookup by string
name (`NewObject(NULL, "window.class", tags)`) is unreliable and
should be avoided.

Fix path: add `_amiga.open_class(name, version)` that returns a
`Class *` handle, then extend `new_object` / `new_object_multi` to
accept a class-pointer int as the first arg instead of a string.
That's ~30 lines of C + one rebuild.

### 2. `open_dialog` labels misalign with 4+ fields

The label draw code was reworked to line up with `g->TopEdge`, but
in practice the labels still appear one row off from their string
gadgets. Two theories that need on-target testing:

- OS4 Intuition may adjust `Gadget.TopEdge` on window-open (inner
  vs outer coordinates), so reading it back gives a different value
  than we set.
- `ActivateGadget()` on the first field may trigger a redraw that
  overlaps or clips the label text.

Either way, `open_dialog` currently works OK with 1-2 fields
(planner.py's simple prompts) but shows the bug clearly with the
4-field `reaction_form.py`.

## References

- [ReAction wiki][2] — official AmigaOS 4 docs on the object model
- [Programming AmigaOS 4: GUI Toolkit ReAction][3] — tag-list tutorial
- [Recommended Practice in OS4 ReAction Programming][1] — the
  os4coding.net post that finally answered "why is WM_OPEN failing"

[1]: https://os4coding.net/blog/trixie/recommended-practice-os4-reaction-programming
[2]: https://wiki.amigaos.net/wiki/ReAction
[3]: https://wiki.amigaos.net/wiki/Programming_AmigaOS_4:_GUI_Toolkit_ReAction

## Next steps (both need a `_amigamodule.c` rebuild)

1. **Add `open_class(name, version)` + accept class pointer in
   `new_object` / `new_object_multi`.** Once that's in, retry
   `reaction_form.py`'s ReAction path with the class-pointer form.
2. **Fix `open_dialog` label draw** on-target — probably by not
   caring about `g->TopEdge` and instead re-using the `y_cursor`
   variable that was used to position the gadget in the first place,
   combined with the window's `BorderTop` at draw time (post-open).
