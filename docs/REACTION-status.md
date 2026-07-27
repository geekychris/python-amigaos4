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

Even with the WM_OPEN NULL arg fix + `OpenClass("window.class", 52,
&cls)` producing a valid `Class *` handle that we now pass into
`NewObject`, the window still does not open. WM_OPEN returns 0.

**Shipped and confirmed working:**
- `_amiga.open_class(name, version)` returns non-zero handle.
- `new_object(handle, tags)` accepts the handle.
- The Python wrapper mirrors the C incantation from
  [os4coding.net trixie blog][1] step-for-step.

**What's still wrong (theories, not confirmed):**
- Missing `WINDOW_ParentGroup` prerequisite. We do pass a
  `layout.gadget` root, but window.class may want children attached
  after open, not before.
- Missing `WA_PubScreen`/`WA_PubScreenName` on OS4 default —
  window.class silently fails to attach to the default pub screen.
- Interface pointer mismatch. Something is picking up the wrong
  `IIntuition` (e.g. `Class *` was OpenClass'd through one interface
  but `IDoMethod` dispatches through another). This would need to be
  ruled out with a small C reproducer built by the same toolchain.

Next real progress needs (a) a working ReAction-from-C reference we
can diff against byte for byte, or (b) QEMU's GDB stub attached with
symbols so we can step into `window.class`'s WM_OPEN handler and
watch it reject the object.

Not going to keep guessing from Python. Landed the primitives so the
fix, when it comes, is a two-line Python change.

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

## Next steps

1. **Build a minimal reaction-window-from-C reproducer** with the
   same toolchain (`walkero/amigagccondocker:os4-gcc11`). If the C
   version opens a window, diff the setup against what `_amiga` does.
   If the C version *also* fails, the answer is toolchain/runtime.
2. **Attach QEMU's GDB stub** (`scripts/start-qemu-os4.sh --gdb`)
   and put a breakpoint in window.class's WM_OPEN handler. Watch
   what it rejects.
3. **Fix `open_dialog` label draw** on-target — probably by not
   caring about `g->TopEdge` and instead re-using the `y_cursor`
   variable that was used to position the gadget in the first place,
   combined with the window's `BorderTop` at draw time (post-open).
