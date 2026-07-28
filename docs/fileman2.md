# fileman2 — dual-pane file manager (ReAction)

A working dual-pane file manager for AmigaOS 4 running native
CPython 3.12 through the `_amiga` C extension. Local filesystem in
one pane, S3 (MinIO / AWS) in the other, with click, double-click,
multi-select, copy, delete, refresh, mkbucket, and multi-profile
S3 configuration.

Runs on QEMU sam460ex OS4.1 or real PowerPC hardware.
Source: `examples/fileman2.py`. Launcher: `tools/s3cli/fileman2`.

## Screen layout

```
+----- window.class (resizable) -------------------------------+
| +---- LEFT listbrowser ----+  +---- RIGHT listbrowser ----+  |
| | Name       | Size        |  | Name       | Size        |  |
| | ..         | <DIR>       |  | ..         | <DIR>       |  |
| | Clipboards | <DIR>       |  | hello.txt  | 6           |  |
| | pyio.log   | 3828        |  | subdir/    | <DIR>       |  |
| | ...        | ...         |  | world.txt  | 6           |  |
| +--------------------------+  +--------------------------+  |
|  Set  Copy  Delete  Refresh  MkBucket  S3 Config  Quit      |
+--------------------------------------------------------------+
```

Both panes are BOOPSI listbrowsers inside a horizontal `layout.gadget`
inside a `window.class`. Events are dispatched via `WM_HANDLEINPUT` —
listbrowser clicks route through window.class's internal handler, so
raw IDCMP_GADGETUP never fires. See "Gadget event routing" below.

## Launch

Local S3 (MinIO on the Mac reachable at `10.0.2.2:9000` from QEMU):

```
execute DH1:s3cli/fileman2
```

Custom paths (defaults are `RAM:` left, `s3://` right):

```
execute DH1:s3cli/fileman2 LEFT=DH1:Work RIGHT=s3://test/photos
```

The launcher sources `DH1:s3cli/s3-env-local` (sets S3_ENDPOINT etc)
and `setenv S3_TIME_SKEW 14400` (see "OS4 clock skew" below).

## Buttons

- **Set** — prompt for a new path for the focused pane. Accepts
  local paths (`DH1:`, `RAM:T`) or `s3://` (bucket list) or
  `s3://bucket[/prefix]`.
- **Copy** — copy every selected file from the focused pane to the
  other pane. Skips directories and `..`. Refreshes the destination
  once at the end so per-file S3 list traffic doesn't compound the
  openssl-subprocess flakiness.
- **Delete** — delete every selected file in the focused pane.
  Refuses directories and `..`. No confirmation dialog (yet).
- **Refresh** — re-list both panes and rebuild both listbrowsers.
- **MkBucket** — prompt for a bucket name, create it on the active
  S3 endpoint. Only meaningful when the focused pane is S3.
- **S3 Config** — see "S3 profiles" below.
- **Quit** — WM_CLOSE the window, tear down objects.

## Selection

- **Single-click** — selects a row. Shown as highlight
  (`LISTBROWSER_ShowSelected=TRUE`).
- **Double-click on a directory** — descend (or on `..`, ascend).
  Detected via `LISTBROWSER_RelEvent == LBRE_DOUBLECLICK (16)`.
  Local dirs use `os.listdir`; S3 "dirs" are prefix-derived from the
  key list.
- **Shift/Ctrl-click** — add rows to the selection. Enabled by
  `LISTBROWSER_MultiSelect=TRUE`. Copy and Delete iterate over all
  selected files (see `_amiga.lb_selected_indices`).
- **`..` entry** — always present except at drive root / `s3://`
  bucket list.

## S3 profiles

Multiple named S3 endpoints (dev, prod, local-MinIO, ...) can be
stored and switched between.

- **File**: `ENVARC:s3-profiles.json` — one dict mapping
  `name → {S3_ENDPOINT, S3_ACCESS, S3_SECRET, S3_INSECURE, S3_TIME_SKEW}`.
  ENVARC: survives reboot; ENV: is a session copy that the s3 CLI
  scripts (`s3-env-local`, `mc`, `aws --endpoint-url ...`) also see.
- **Add/edit**: click **S3 Config**, type a name at the picker (new
  or existing), fill in the fields, hit **Save+Activate**. Fields
  pre-fill from the existing profile if the name matches; otherwise
  from the current environment.
- **Switch active**: click **S3 Config**, type an existing name, hit
  Save+Activate without changing anything. Copies its values back
  into ENV:/ENVARC:.
- **Interop with CLI**: because active values live in ENV:, the
  s3-env-local script and any `mc` / `aws` calls the user runs from
  the shell see the same endpoint automatically. No re-source needed.

## Busy pointer

Copy / Delete / Refresh call `_amiga.set_busy(intuiwin, True)` on
entry and `False` on exit. Under the hood:

```c
SetWindowPointer(win, WA_BusyPointer, TRUE, WA_PointerDelay, TRUE, TAG_END)
```

`WA_PointerDelay` avoids flickering when the operation completes in
under ~0.25s.

## OS4 clock skew

Python's `time.time()` on OS4 returns wall-clock + local TZ offset
instead of true UTC (newlib's TZ handling treats Amiga's UTC-based
system clock as if it were local). SigV4-signed S3 requests refuse
skew >5 min.

- **Symptom**: `S3Error 403 RequestTimeTooSkewed`
- **Workaround**: `setenv S3_TIME_SKEW 14400` (for EDT: 4h × 3600s).
  The S3 client subtracts this from `time.time()` before building
  the `x-amz-date` header. See `S3Client(time_skew_seconds=...)`.

The fileman2 launcher sets this automatically. A proper fix wants a
python-os4 rebuild with newlib TZ set to UTC.

## Gadget event routing (why WM_HANDLEINPUT matters)

`window.class` swallows all IDCMP messages into its own dispatcher.
Raw `IDCMP_GADGETUP` messages do NOT arrive at the port for BOOPSI
gadgets like listbrowser and button — the app MUST call

```
result = IDoMethod(win, WM_HANDLEINPUT, &code)
```

in a drain loop. `_amiga.wm_handleinput(win)` wraps this and returns
`(result, code)` or `None` when the drain is complete. Each result
carries a WMHI class and gadget ID:

- `WMHI_GADGETUP | GA_ID` — a button/listbrowser fired
- `WMHI_CLOSEWINDOW` — user clicked close gadget
- `WMHI_RAWKEY | keycode` — key press
- `WMHI_NEWSIZE` — window resized (fileman2 issues `WM_RETHINK`)

Additional gotchas discovered building fileman2:

- **`GA_RelVerify=TRUE`** on the listbrowser is what tells it to emit
  GADGETUP on mouse release. Without it, clicks visibly select rows
  but never propagate.
- **Initial `LISTBROWSER_Labels`** must be passed at gadget creation
  time. Setting labels only via later `SetAttrs` leaves the gadget's
  click-dispatch subsystem uninitialised and no clicks fire.
- **Per-listbrowser `ColumnInfo`** — do not share one `ColumnInfo`
  pointer across two listbrowsers. Each mutates the widths and the
  columns end up in inconsistent widths (right pane got clipped to
  4 chars).
- **`LISTBROWSER_AutoFit=FALSE`** — AutoFit sizes columns to fit
  initial content, which produces asymmetric pane widths when the
  two panes start with different-length data.
- **Do not set `WA_IDCMP`** on window.class — let it derive its own
  IDCMP mask from the union of what its child gadgets need. Setting
  a restrictive mask blocks gadget dispatch entirely.

## Kill / restart

The daemon can send CTRL_C to any Amiga task by CLI number:

```
break 6 C
```

The python-os4 build honours CTRL_C in `wait_message` and
`wm_handleinput`, so a running fileman2 exits cleanly. If Python is
already blocked in a native library (e.g. an openssl subprocess) or
sitting on GrimReaper after a crash, CTRL_C isn't seen and the
current workaround is killing QEMU. A `STOP|HARD` verb using
`RemoveTask()` is coded in `amiga-bridge/src/protocol_handler.c` but
not yet deployed to the target — that'd fix the GrimReaper case at
the cost of leaked resources.

## Known limitations

- S3 refresh occasionally returns 0 entries on the first attempt
  (openssl subprocess race). Mitigated with one retry + 0.5s pause
  in `S3Pane.refresh` — enough for MinIO on localhost. A native TLS
  layer in `_amiga` would remove this entirely.
- No confirmation dialog before Delete. `_amiga.run_dialog` only
  supports multi-field forms via `open_dialog`, not a plain
  yes/no requester.
- Directory copy not implemented — Copy only handles files.
- No progress bar for multi-file copy; log-only.
- MkBucket blocks the UI (no threading). Uses the busy pointer.
