/*
 * _amigamodule.c — native Amiga bindings for the Python 3.12 OS4 port.
 *
 * Baked in as a *static* builtin (see setup.local) so no dlopen is needed.
 * Wraps a handful of IExec / IDOS entry points directly, replacing the
 * `os.system()`-shell-out fallbacks in amiga_bindings/amiga/*.
 *
 * Built with -D__USE_INLINE__ so classic call names (FindTask, AvailMem,
 * Info, ...) work via inline4/*.h dispatching to IExec->FindTask() etc.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <exec/types.h>
#include <exec/memory.h>
#include <exec/tasks.h>
#include <proto/exec.h>
#include <proto/dos.h>
#include <proto/intuition.h>
#include <proto/graphics.h>
#include <intuition/intuition.h>
#include <intuition/intuitionbase.h>
#include <intuition/screens.h>
#include <graphics/text.h>
#include <graphics/rastport.h>
#include <graphics/view.h>
#include <utility/tagitem.h>


/* -lauto is supposed to auto-open these library-interface pairs, but
 * with CPython's link-line ordering the -lauto position is such that
 * the auto-opener object files aren't pulled in.  Declare + explicitly
 * open in PyInit__amiga() below. */
struct Library         *IntuitionBase = NULL;
struct IntuitionIFace  *IIntuition    = NULL;
struct Library         *GfxBase       = NULL;
struct GraphicsIFace   *IGraphics     = NULL;


/* --------------------------------------------------------------------- */
/* Exec                                                                   */
/* --------------------------------------------------------------------- */

/* Amiga node names are byte strings — often ASCII but sometimes hold
 * high-bit chars (e.g. via a copyrighted volume name).  Decode them
 * as latin-1-with-replace so Python never crashes on the return path. */
static PyObject *
py_str_safe(const char *s)
{
    if (!s) return PyUnicode_FromString("");
    return PyUnicode_DecodeLatin1(s, strlen(s), "replace");
}


static PyObject *
py_find_task(PyObject *self, PyObject *args)
{
    const char *name = NULL;
    if (!PyArg_ParseTuple(args, "|z", &name))
        return NULL;

    struct Task *t = FindTask((STRPTR)name);
    if (!t)
        Py_RETURN_NONE;

    const char *tname = (t->tc_Node.ln_Name != NULL) ? (const char *)t->tc_Node.ln_Name : "";
    PyObject *py_name = py_str_safe(tname);
    if (!py_name) return NULL;
    PyObject *ret = Py_BuildValue("(Nik)",
                                  py_name,
                                  (int)t->tc_Node.ln_Pri,
                                  (unsigned long)(uintptr_t)t);
    return ret;
}


static PyObject *
py_avail_mem(PyObject *self, PyObject *args)
{
    unsigned long flags = MEMF_ANY;
    if (!PyArg_ParseTuple(args, "|k", &flags))
        return NULL;
    return PyLong_FromUnsignedLong(AvailMem(flags));
}


static PyObject *
py_avail_mem_summary(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    /* Return a dict of common flag combos in one call, so Python doesn't
     * pay call overhead per query. */
    PyObject *d = PyDict_New();
    if (!d) return NULL;

    struct { const char *key; unsigned long flag; } items[] = {
        {"any",     MEMF_ANY},
        {"public",  MEMF_PUBLIC},
        {"chip",    MEMF_CHIP},
        {"fast",    MEMF_FAST},
        {"largest", MEMF_LARGEST},
        {NULL,      0},
    };
    for (int i = 0; items[i].key; i++) {
        PyObject *v = PyLong_FromUnsignedLong(AvailMem(items[i].flag));
        if (!v || PyDict_SetItemString(d, items[i].key, v) < 0) {
            Py_XDECREF(v);
            Py_DECREF(d);
            return NULL;
        }
        Py_DECREF(v);
    }
    return d;
}


static PyObject *
py_list_tasks(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    /* Walk SysBase->TaskReady + TaskWait under Forbid()/Permit() and
     * return a list of (name, priority, state) tuples. */
    PyObject *out = PyList_New(0);
    if (!out) return NULL;

    Forbid();
    struct ExecBase *sb = SysBase;
    for (int pass = 0; pass < 2; pass++) {
        struct List *lst = (pass == 0) ? &sb->TaskReady : &sb->TaskWait;
        const char *state = (pass == 0) ? "Ready" : "Wait";
        for (struct Node *n = lst->lh_Head; n->ln_Succ; n = n->ln_Succ) {
            struct Task *t = (struct Task *)n;
            const char *tname = (t->tc_Node.ln_Name != NULL)
                                ? (const char *)t->tc_Node.ln_Name : "";
            PyObject *py_name = py_str_safe(tname);
            if (!py_name) {
                Permit();
                Py_DECREF(out);
                return NULL;
            }
            PyObject *tup = Py_BuildValue("(Nis)", py_name,
                                          (int)t->tc_Node.ln_Pri, state);
            if (!tup) {
                Permit();
                Py_DECREF(out);
                return NULL;
            }
            if (PyList_Append(out, tup) < 0) {
                Permit();
                Py_DECREF(tup);
                Py_DECREF(out);
                return NULL;
            }
            Py_DECREF(tup);
        }
    }
    Permit();
    return out;
}


static PyObject *
py_list_libraries(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    PyObject *out = PyList_New(0);
    if (!out) return NULL;

    Forbid();
    struct ExecBase *sb = SysBase;
    for (struct Node *n = sb->LibList.lh_Head; n->ln_Succ; n = n->ln_Succ) {
        struct Library *lib = (struct Library *)n;
        const char *nm = (lib->lib_Node.ln_Name != NULL)
                          ? (const char *)lib->lib_Node.ln_Name : "";
        PyObject *py_name = py_str_safe(nm);
        if (!py_name) {
            Permit();
            Py_DECREF(out);
            return NULL;
        }
        PyObject *tup = Py_BuildValue("(Niii)",
                                      py_name,
                                      (int)lib->lib_Version,
                                      (int)lib->lib_Revision,
                                      (int)lib->lib_OpenCnt);
        if (!tup) {
            Permit();
            Py_DECREF(out);
            return NULL;
        }
        if (PyList_Append(out, tup) < 0) {
            Permit();
            Py_DECREF(tup);
            Py_DECREF(out);
            return NULL;
        }
        Py_DECREF(tup);
    }
    Permit();
    return out;
}


static PyObject *
py_list_ports(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    PyObject *out = PyList_New(0);
    if (!out) return NULL;

    Forbid();
    struct ExecBase *sb = SysBase;
    for (struct Node *n = sb->PortList.lh_Head; n->ln_Succ; n = n->ln_Succ) {
        const char *nm = (n->ln_Name != NULL) ? (const char *)n->ln_Name : "";
        PyObject *s = py_str_safe(nm);
        if (!s) {
            Permit();
            Py_DECREF(out);
            return NULL;
        }
        if (PyList_Append(out, s) < 0) {
            Permit();
            Py_DECREF(s);
            Py_DECREF(out);
            return NULL;
        }
        Py_DECREF(s);
    }
    Permit();
    return out;
}


/* --------------------------------------------------------------------- */
/* DOS                                                                    */
/* --------------------------------------------------------------------- */

static PyObject *
py_current_dir_name(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    char buf[512];
    BOOL ok = GetCliCurrentDirName((STRPTR)buf, sizeof(buf));
    if (!ok) Py_RETURN_NONE;
    return PyUnicode_FromString(buf);
}


static PyObject *
py_volume_info(PyObject *self, PyObject *args)
{
    const char *path;
    if (!PyArg_ParseTuple(args, "s", &path))
        return NULL;

    BPTR lock = Lock((STRPTR)path, SHARED_LOCK);
    if (!lock) Py_RETURN_NONE;

    struct InfoData id;
    LONG ok = Info(lock, &id);
    UnLock(lock);
    if (!ok) Py_RETURN_NONE;

    return Py_BuildValue("{sisisisisisi}",
                         "disk_state",      (int)id.id_DiskState,
                         "num_blocks",      (int)id.id_NumBlocks,
                         "num_blocks_used", (int)id.id_NumBlocksUsed,
                         "bytes_per_block", (int)id.id_BytesPerBlock,
                         "dos_type",        (int)id.id_DOSType,
                         "use_count",       (int)id.id_UseCount);
}


static PyObject *
py_version(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    /* Advertise which build this is. */
    return Py_BuildValue("(sss)",
                         "python-amigaos4 native _amiga bindings",
                         "0.2.0",
                         "phase 6 + real Intuition windows");
}


/* --------------------------------------------------------------------- */
/* Intuition — real windowed UI                                          */
/* --------------------------------------------------------------------- */

/* Opaque window handles are the address of struct Window* cast to an
 * unsigned long, which Python holds as an int.  The Amiga owns the
 * storage; Python is a bookkeeping layer. */

static PyObject *
py_open_window(PyObject *self, PyObject *args, PyObject *kwargs)
{
    static char *kw[] = {
        "title", "left", "top", "width", "height", "idcmp", "flags", NULL,
    };
    const char *title = "Python";
    int left = 100, top = 100, width = 400, height = 200;
    unsigned long idcmp = IDCMP_CLOSEWINDOW | IDCMP_VANILLAKEY;
    unsigned long flags = WFLG_SIZEGADGET | WFLG_DRAGBAR | WFLG_DEPTHGADGET
                        | WFLG_CLOSEGADGET | WFLG_ACTIVATE | WFLG_SIMPLE_REFRESH;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|siiiikk", kw,
            &title, &left, &top, &width, &height, &idcmp, &flags))
        return NULL;

    struct Window *w = OpenWindowTags(NULL,
        WA_Title,       (Tag)title,
        WA_Left,        left,
        WA_Top,         top,
        WA_InnerWidth,  width,
        WA_InnerHeight, height,
        WA_IDCMP,       idcmp,
        WA_Flags,       flags,
        WA_MinWidth,    100,
        WA_MinHeight,   50,
        WA_MaxWidth,    -1,
        WA_MaxHeight,   -1,
        TAG_END);

    if (!w) {
        PyErr_SetString(PyExc_RuntimeError, "OpenWindowTags returned NULL");
        return NULL;
    }
    return PyLong_FromUnsignedLong((unsigned long)(uintptr_t)w);
}


static PyObject *
py_close_window(PyObject *self, PyObject *args)
{
    unsigned long handle;
    if (!PyArg_ParseTuple(args, "k", &handle)) return NULL;
    struct Window *w = (struct Window *)(uintptr_t)handle;
    if (w) CloseWindow(w);
    Py_RETURN_NONE;
}


static PyObject *
py_window_geom(PyObject *self, PyObject *args)
{
    unsigned long handle;
    if (!PyArg_ParseTuple(args, "k", &handle)) return NULL;
    struct Window *w = (struct Window *)(uintptr_t)handle;
    if (!w) Py_RETURN_NONE;
    /* Return outer x,y,w,h + inner (drawing area) x,y,w,h */
    return Py_BuildValue("{sisisisisisisisi}",
                         "left",         (int)w->LeftEdge,
                         "top",          (int)w->TopEdge,
                         "width",        (int)w->Width,
                         "height",       (int)w->Height,
                         "border_left",  (int)w->BorderLeft,
                         "border_top",   (int)w->BorderTop,
                         "inner_width",  (int)(w->Width  - w->BorderLeft - w->BorderRight),
                         "inner_height", (int)(w->Height - w->BorderTop  - w->BorderBottom));
}


static PyObject *
py_clear_window(PyObject *self, PyObject *args, PyObject *kwargs)
{
    static char *kw[] = {"handle", "pen", NULL};
    unsigned long handle;
    unsigned long pen = 0;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "k|k", kw, &handle, &pen))
        return NULL;
    struct Window *w = (struct Window *)(uintptr_t)handle;
    if (!w) Py_RETURN_NONE;

    struct RastPort *rp = w->RPort;
    LONG old = rp->FgPen;
    SetAPen(rp, pen);
    RectFill(rp,
             w->BorderLeft, w->BorderTop,
             w->Width  - w->BorderRight  - 1,
             w->Height - w->BorderBottom - 1);
    SetAPen(rp, old);
    Py_RETURN_NONE;
}


static PyObject *
py_draw_text(PyObject *self, PyObject *args, PyObject *kwargs)
{
    static char *kw[] = {"handle", "x", "y", "text", "pen", NULL};
    unsigned long handle;
    int x, y;
    const char *text;
    unsigned long pen = 1;   /* default text pen */
    Py_ssize_t textlen;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "kiis#|k", kw,
            &handle, &x, &y, &text, &textlen, &pen))
        return NULL;

    struct Window *w = (struct Window *)(uintptr_t)handle;
    if (!w) Py_RETURN_NONE;

    struct RastPort *rp = w->RPort;
    LONG old = rp->FgPen;
    SetAPen(rp, pen);
    Move(rp, w->BorderLeft + x, w->BorderTop + y);
    Text(rp, (STRPTR)text, (LONG)textlen);
    SetAPen(rp, old);
    Py_RETURN_NONE;
}


/* Drain one IDCMP message.  Returns dict {class, code, qualifier,
 * mouse_x, mouse_y} or None if no message pending. */
static PyObject *
_msg_to_dict(struct IntuiMessage *msg)
{
    return Py_BuildValue("{sksksksisi}",
                         "class",     (unsigned long)msg->Class,
                         "code",      (unsigned long)msg->Code,
                         "qualifier", (unsigned long)msg->Qualifier,
                         "mouse_x",   (int)msg->MouseX,
                         "mouse_y",   (int)msg->MouseY);
}


static PyObject *
py_get_message(PyObject *self, PyObject *args)
{
    unsigned long handle;
    if (!PyArg_ParseTuple(args, "k", &handle)) return NULL;
    struct Window *w = (struct Window *)(uintptr_t)handle;
    if (!w) Py_RETURN_NONE;

    struct IntuiMessage *msg = (struct IntuiMessage *)GetMsg(w->UserPort);
    if (!msg) Py_RETURN_NONE;

    PyObject *d = _msg_to_dict(msg);
    ReplyMsg((struct Message *)msg);
    return d;
}


/* Block until an IDCMP message arrives OR timeout expires (in seconds).
 * timeout < 0 means forever.  Returns first message dict, or None on
 * timeout / broken window. */
static PyObject *
py_wait_message(PyObject *self, PyObject *args)
{
    unsigned long handle;
    double timeout = -1.0;
    if (!PyArg_ParseTuple(args, "k|d", &handle, &timeout)) return NULL;
    struct Window *w = (struct Window *)(uintptr_t)handle;
    if (!w) Py_RETURN_NONE;

    struct MsgPort *port = w->UserPort;
    ULONG win_sig = 1UL << port->mp_SigBit;

    if (timeout < 0) {
        /* Block forever on the window signal.  Release GIL so other
         * Python threads can run while we wait. */
        Py_BEGIN_ALLOW_THREADS
        Wait(win_sig);
        Py_END_ALLOW_THREADS
    } else {
        /* Poll every Delay(1) tick (20ms) until either a message
         * arrives or the timeout expires.  IsMsgPortEmpty is a
         * peek — doesn't consume. */
        int ticks = (int)(timeout * 50.0);
        if (ticks < 1) ticks = 1;
        Py_BEGIN_ALLOW_THREADS
        while (ticks-- > 0 && IsMsgPortEmpty(port)) {
            Delay(1);
        }
        Py_END_ALLOW_THREADS
    }

    /* Return the first pending message, if any. */
    struct IntuiMessage *msg = (struct IntuiMessage *)GetMsg(port);
    if (!msg) Py_RETURN_NONE;
    PyObject *d = _msg_to_dict(msg);
    ReplyMsg((struct Message *)msg);
    return d;
}


static PyObject *
py_active_window(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    struct IntuitionBase *ib = (struct IntuitionBase *)IntuitionBase;
    if (!ib || !ib->ActiveWindow) Py_RETURN_NONE;
    return PyLong_FromUnsignedLong((unsigned long)(uintptr_t)ib->ActiveWindow);
}


/* --------------------------------------------------------------------- */
/* Graphics primitives — line/rect/dot/circle for turtle-style drawing.  */
/* --------------------------------------------------------------------- */

static PyObject *
py_draw_line(PyObject *self, PyObject *args, PyObject *kwargs)
{
    static char *kw[] = {"handle", "x1", "y1", "x2", "y2", "pen", NULL};
    unsigned long handle;
    int x1, y1, x2, y2;
    unsigned long pen = 1;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "kiiii|k", kw,
            &handle, &x1, &y1, &x2, &y2, &pen))
        return NULL;
    struct Window *w = (struct Window *)(uintptr_t)handle;
    if (!w) Py_RETURN_NONE;

    struct RastPort *rp = w->RPort;
    LONG old = rp->FgPen;
    SetAPen(rp, pen);
    Move(rp, w->BorderLeft + x1, w->BorderTop + y1);
    Draw(rp, w->BorderLeft + x2, w->BorderTop + y2);
    SetAPen(rp, old);
    Py_RETURN_NONE;
}


static PyObject *
py_fill_rect(PyObject *self, PyObject *args, PyObject *kwargs)
{
    static char *kw[] = {"handle", "x1", "y1", "x2", "y2", "pen", NULL};
    unsigned long handle;
    int x1, y1, x2, y2;
    unsigned long pen = 1;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "kiiii|k", kw,
            &handle, &x1, &y1, &x2, &y2, &pen))
        return NULL;
    struct Window *w = (struct Window *)(uintptr_t)handle;
    if (!w) Py_RETURN_NONE;
    /* Normalise so x1<=x2, y1<=y2 (RectFill demands that on OS4). */
    if (x1 > x2) { int t = x1; x1 = x2; x2 = t; }
    if (y1 > y2) { int t = y1; y1 = y2; y2 = t; }
    struct RastPort *rp = w->RPort;
    LONG old = rp->FgPen;
    SetAPen(rp, pen);
    RectFill(rp,
             w->BorderLeft + x1, w->BorderTop + y1,
             w->BorderLeft + x2, w->BorderTop + y2);
    SetAPen(rp, old);
    Py_RETURN_NONE;
}


static PyObject *
py_dot(PyObject *self, PyObject *args, PyObject *kwargs)
{
    /* Draw a filled square as a stand-in for a circle — good enough
     * for the pixel-scale dots freegames wants. */
    static char *kw[] = {"handle", "x", "y", "size", "pen", NULL};
    unsigned long handle;
    int x, y, size;
    unsigned long pen = 1;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "kiii|k", kw,
            &handle, &x, &y, &size, &pen))
        return NULL;
    struct Window *w = (struct Window *)(uintptr_t)handle;
    if (!w || size <= 0) Py_RETURN_NONE;
    int r = size / 2;
    struct RastPort *rp = w->RPort;
    LONG old = rp->FgPen;
    SetAPen(rp, pen);
    RectFill(rp,
             w->BorderLeft + x - r, w->BorderTop + y - r,
             w->BorderLeft + x + r, w->BorderTop + y + r);
    SetAPen(rp, old);
    Py_RETURN_NONE;
}


/* Palette management: use ObtainBestPen against the window's screen
 * colormap so we get sensible colours on 8/16/32-bit Workbench screens
 * without stomping on the shared palette. */
static PyObject *
py_obtain_pen(PyObject *self, PyObject *args)
{
    unsigned long handle;
    int r, g, b;  /* 0..255 */
    if (!PyArg_ParseTuple(args, "kiii", &handle, &r, &g, &b))
        return NULL;
    struct Window *w = (struct Window *)(uintptr_t)handle;
    if (!w || !w->WScreen) Py_RETURN_NONE;

    struct ColorMap *cm = w->WScreen->ViewPort.ColorMap;
    ULONG R = ((ULONG)(r & 0xFF)) * 0x01010101UL;
    ULONG G = ((ULONG)(g & 0xFF)) * 0x01010101UL;
    ULONG B = ((ULONG)(b & 0xFF)) * 0x01010101UL;
    LONG pen = ObtainBestPen(cm, R, G, B,
                             OBP_Precision, PRECISION_GUI,
                             OBP_FailIfBad, FALSE,
                             TAG_END);
    if (pen < 0) Py_RETURN_NONE;
    return PyLong_FromLong(pen);
}


static PyObject *
py_release_pen(PyObject *self, PyObject *args)
{
    unsigned long handle;
    int pen;
    if (!PyArg_ParseTuple(args, "ki", &handle, &pen))
        return NULL;
    struct Window *w = (struct Window *)(uintptr_t)handle;
    if (!w || !w->WScreen || pen < 0) Py_RETURN_NONE;
    ReleasePen(w->WScreen->ViewPort.ColorMap, pen);
    Py_RETURN_NONE;
}


/* --------------------------------------------------------------------- */
/* Module definition                                                     */
/* --------------------------------------------------------------------- */

static PyMethodDef amiga_methods[] = {
    {"find_task",         py_find_task,         METH_VARARGS,
        "find_task([name]) -> (name, pri, addr) | None — wraps IExec->FindTask."},
    {"avail_mem",         py_avail_mem,         METH_VARARGS,
        "avail_mem([flags=MEMF_ANY]) -> int bytes."},
    {"avail_mem_summary", py_avail_mem_summary, METH_NOARGS,
        "avail_mem_summary() -> dict of {any,public,chip,fast,largest}."},
    {"list_tasks",        py_list_tasks,        METH_NOARGS,
        "list_tasks() -> [(name, priority, state)] — walks TaskReady + TaskWait."},
    {"list_libraries",    py_list_libraries,    METH_NOARGS,
        "list_libraries() -> [(name, version, revision, open_count)]."},
    {"list_ports",        py_list_ports,        METH_NOARGS,
        "list_ports() -> [name] of public MsgPorts."},
    {"current_dir_name",  py_current_dir_name,  METH_NOARGS,
        "current_dir_name() -> str via IDOS->GetCurrentDirName."},
    {"volume_info",       py_volume_info,       METH_VARARGS,
        "volume_info(path) -> dict from IDOS->Info on a volume lock."},
    {"version",           py_version,           METH_NOARGS,
        "version() -> (name, version, phase)."},

    /* Intuition — real windowed UI */
    {"open_window",       (PyCFunction)py_open_window,
                                                METH_VARARGS | METH_KEYWORDS,
        "open_window(title, left, top, width, height, idcmp, flags) -> handle."},
    {"close_window",      py_close_window,      METH_VARARGS,
        "close_window(handle)."},
    {"window_geom",       py_window_geom,       METH_VARARGS,
        "window_geom(handle) -> dict with left/top/width/height + inner_*."},
    {"clear_window",      (PyCFunction)py_clear_window,
                                                METH_VARARGS | METH_KEYWORDS,
        "clear_window(handle, pen=0) — fill drawing area with pen."},
    {"draw_text",         (PyCFunction)py_draw_text,
                                                METH_VARARGS | METH_KEYWORDS,
        "draw_text(handle, x, y, text, pen=1) — Text() into rastport."},
    {"get_message",       py_get_message,       METH_VARARGS,
        "get_message(handle) -> dict | None — non-blocking IDCMP drain."},
    {"wait_message",      py_wait_message,      METH_VARARGS,
        "wait_message(handle, timeout=-1) -> dict | None — block until event."},
    {"active_window",     py_active_window,     METH_NOARGS,
        "active_window() -> handle of the currently-active window."},

    /* Graphics primitives — turtle-style drawing */
    {"draw_line",         (PyCFunction)py_draw_line,
                                                METH_VARARGS | METH_KEYWORDS,
        "draw_line(handle, x1, y1, x2, y2, pen=1) — Move+Draw."},
    {"fill_rect",         (PyCFunction)py_fill_rect,
                                                METH_VARARGS | METH_KEYWORDS,
        "fill_rect(handle, x1, y1, x2, y2, pen=1) — RectFill."},
    {"dot",               (PyCFunction)py_dot,
                                                METH_VARARGS | METH_KEYWORDS,
        "dot(handle, x, y, size, pen=1) — filled square, size×size, centred."},
    {"obtain_pen",        py_obtain_pen,        METH_VARARGS,
        "obtain_pen(handle, r, g, b) -> pen index (0..255).  RGB is 8-bit each."},
    {"release_pen",       py_release_pen,       METH_VARARGS,
        "release_pen(handle, pen) — return pen to shared colormap."},

    {NULL, NULL, 0, NULL},
};


static struct PyModuleDef amigamodule = {
    PyModuleDef_HEAD_INIT,
    "_amiga",
    "Native AmigaOS bindings (Phase 6 — replaces os.system shell-outs).",
    -1,
    amiga_methods,
};


/* File-based init tracer — needed because Python's stdout isn't
 * usable during PyInit__amiga (init runs BEFORE sys.stdout is set up
 * for user code, and any fprintf(stderr) may be lost to the bridge
 * SCRIPT capture path).  Appends one line per stage to T:pyinit.log. */
static void
init_trace(const char *stage)
{
    FILE *f = fopen("T:pyinit.log", "a");
    if (f) {
        fprintf(f, "PyInit__amiga: %s\n", stage);
        fclose(f);
    }
}


PyMODINIT_FUNC
PyInit__amiga(void)
{
    init_trace("enter");
    PyObject *m = PyModule_Create(&amigamodule);
    if (!m) { init_trace("PyModule_Create returned NULL"); return NULL; }
    init_trace("module created");

    /* Explicitly open intuition.library + graphics.library and cache
     * their interfaces.  Uses the classic-style OpenLibrary/GetInterface
     * inlines that dispatch through IExec.  Silent-continue on failure —
     * the UI-only entry points will error at first use, exec/dos stay
     * usable. */
    if (!IntuitionBase) {
        IntuitionBase = OpenLibrary("intuition.library", 50);
        if (IntuitionBase) {
            IIntuition = (struct IntuitionIFace *)
                GetInterface(IntuitionBase, "main", 1, NULL);
        }
    }
    if (!GfxBase) {
        GfxBase = OpenLibrary("graphics.library", 50);
        if (GfxBase) {
            IGraphics = (struct GraphicsIFace *)
                GetInterface(GfxBase, "main", 1, NULL);
        }
    }

    /* Expose common MEMF_ constants so scripts don't need to hardcode. */
    PyModule_AddIntConstant(m, "MEMF_ANY",     MEMF_ANY);
    PyModule_AddIntConstant(m, "MEMF_PUBLIC",  MEMF_PUBLIC);
    PyModule_AddIntConstant(m, "MEMF_CHIP",    MEMF_CHIP);
    PyModule_AddIntConstant(m, "MEMF_FAST",    MEMF_FAST);
    PyModule_AddIntConstant(m, "MEMF_LARGEST", MEMF_LARGEST);
    PyModule_AddIntConstant(m, "MEMF_CLEAR",   MEMF_CLEAR);

    /* IDCMP flags — subset useful for Python callers. */
    PyModule_AddIntConstant(m, "IDCMP_CLOSEWINDOW",    IDCMP_CLOSEWINDOW);
    PyModule_AddIntConstant(m, "IDCMP_NEWSIZE",        IDCMP_NEWSIZE);
    PyModule_AddIntConstant(m, "IDCMP_REFRESHWINDOW",  IDCMP_REFRESHWINDOW);
    PyModule_AddIntConstant(m, "IDCMP_MOUSEBUTTONS",   IDCMP_MOUSEBUTTONS);
    PyModule_AddIntConstant(m, "IDCMP_MOUSEMOVE",      IDCMP_MOUSEMOVE);
    PyModule_AddIntConstant(m, "IDCMP_GADGETUP",       IDCMP_GADGETUP);
    PyModule_AddIntConstant(m, "IDCMP_GADGETDOWN",     IDCMP_GADGETDOWN);
    PyModule_AddIntConstant(m, "IDCMP_MENUPICK",       IDCMP_MENUPICK);
    PyModule_AddIntConstant(m, "IDCMP_RAWKEY",         IDCMP_RAWKEY);
    PyModule_AddIntConstant(m, "IDCMP_VANILLAKEY",     IDCMP_VANILLAKEY);
    PyModule_AddIntConstant(m, "IDCMP_ACTIVEWINDOW",   IDCMP_ACTIVEWINDOW);
    PyModule_AddIntConstant(m, "IDCMP_INACTIVEWINDOW", IDCMP_INACTIVEWINDOW);

    /* WFLG_ window-flags. */
    PyModule_AddIntConstant(m, "WFLG_SIZEGADGET",       WFLG_SIZEGADGET);
    PyModule_AddIntConstant(m, "WFLG_DRAGBAR",          WFLG_DRAGBAR);
    PyModule_AddIntConstant(m, "WFLG_DEPTHGADGET",      WFLG_DEPTHGADGET);
    PyModule_AddIntConstant(m, "WFLG_CLOSEGADGET",      WFLG_CLOSEGADGET);
    PyModule_AddIntConstant(m, "WFLG_ACTIVATE",         WFLG_ACTIVATE);
    PyModule_AddIntConstant(m, "WFLG_SIMPLE_REFRESH",   WFLG_SIMPLE_REFRESH);
    PyModule_AddIntConstant(m, "WFLG_SMART_REFRESH",    WFLG_SMART_REFRESH);

    return m;
}
