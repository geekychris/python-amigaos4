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

#include <string.h>
#include <stdlib.h>

#include <exec/types.h>
#include <exec/memory.h>
#include <exec/tasks.h>
#include <exec/ports.h>
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

/* rexxsyslib.library — ARexx interpreter + IPC. Its proto header on
 * OS4 declares RexxSysBase as `struct RxsLib *`, so use the same
 * type here to avoid a redeclaration mismatch. */
#include <rexx/errors.h>
#include <rexx/storage.h>
#include <rexx/rxslib.h>
#include <proto/rexxsyslib.h>


/* -lauto is supposed to auto-open these library-interface pairs, but
 * with CPython's link-line ordering the -lauto position is such that
 * the auto-opener object files aren't pulled in.  Declare + explicitly
 * open in PyInit__amiga() below. */
struct Library         *IntuitionBase = NULL;
struct IntuitionIFace  *IIntuition    = NULL;
struct Library         *GfxBase       = NULL;
struct GraphicsIFace   *IGraphics     = NULL;
struct Library         *RexxSysBase   = NULL;
struct RexxSysIFace    *IRexxSys      = NULL;


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
/* Composite modal dialogs (StringGadgets + OK/Cancel buttons).           */
/*                                                                        */
/* py_open_dialog(title, fields) opens a small window with one            */
/* StringGadget per field plus OK / Cancel buttons at the bottom.  Users  */
/* fill the fields, click OK (or press Return), we harvest each           */
/* StringInfo->Buffer into a Python dict and return it.  Cancel returns   */
/* None.  This replaces the wizardy chain of individual RequestString     */
/* popups in earlier apps.                                                */
/* --------------------------------------------------------------------- */

#define DIALOG_MAX_FIELDS   16
#define DIALOG_GADGET_H     14
#define DIALOG_ROW_SPACING  6
#define DIALOG_LABEL_W      110

#define GID_OK        1000
#define GID_CANCEL    1001
#define GID_FIELD_BASE 1

/* Local strdup — newlib's isn't visible without a POSIX feature-test
 * macro we don't set.  Uses AllocVec so both label and buffer free
 * paths in close_dialog can go through FreeVec. */
static char *
dup_str(const char *s)
{
    if (!s) return NULL;
    size_t n = strlen(s);
    char *r = AllocVec(n + 1, MEMF_ANY);
    if (r) memcpy(r, s, n + 1);
    return r;
}

typedef struct DlgField {
    char             *label;         /* strdup'd */
    struct Gadget    *gadget;
    struct StringInfo *sinfo;
    char             *buffer;        /* alloc'd, maxlen+1 */
    char             *undo;          /* alloc'd, maxlen+1 */
    int               maxlen;
} DlgField;

typedef struct Dialog {
    struct Window *win;
    DlgField       fields[DIALOG_MAX_FIELDS];
    int            n_fields;
    struct Gadget *g_ok;
    struct Gadget *g_cancel;
    char          *ok_text;      /* strdup'd */
    char          *cancel_text;
} Dialog;


static struct StringInfo *
mk_string_info(char *buffer, char *undo, int maxlen)
{
    struct StringInfo *si = AllocVec(sizeof(struct StringInfo), MEMF_ANY | MEMF_CLEAR);
    if (!si) return NULL;
    si->Buffer     = (UBYTE *)buffer;
    si->UndoBuffer = (UBYTE *)undo;
    /* MaxChars in StringInfo is total buffer bytes including the null.
     * Callers allocate maxlen+1, so pass maxlen+1 here. */
    si->MaxChars   = maxlen + 1;
    /* Place cursor at end of any pre-filled text so the user is editing
     * *after* the existing content, and set NumChars accordingly —
     * without this Intuition thinks the pre-filled buffer is empty and
     * key input has no effect. */
    int len = buffer ? (int)strlen(buffer) : 0;
    si->BufferPos  = len;
    si->NumChars   = len;
    si->DispPos    = 0;
    return si;
}


static struct Gadget *
mk_string_gadget(struct Gadget *prev, int x, int y, int w, int h,
                 int gid, struct StringInfo *si)
{
    struct Gadget *g = AllocVec(sizeof(struct Gadget), MEMF_ANY | MEMF_CLEAR);
    if (!g) return NULL;
    g->NextGadget    = NULL;
    g->LeftEdge      = x;
    g->TopEdge       = y;
    g->Width         = w;
    g->Height        = h;
    g->Flags         = GFLG_GADGHCOMP;
    g->Activation    = GACT_RELVERIFY | GACT_STRINGCENTER;
    g->GadgetType    = GTYP_STRGADGET;
    g->SpecialInfo   = (APTR)si;
    g->GadgetID      = gid;
    if (prev) prev->NextGadget = g;
    return g;
}


static struct Gadget *
mk_bool_gadget(struct Gadget *prev, int x, int y, int w, int h,
               int gid, const char *label, struct IntuiText *itext_storage)
{
    struct Gadget *g = AllocVec(sizeof(struct Gadget), MEMF_ANY | MEMF_CLEAR);
    if (!g) return NULL;
    itext_storage->FrontPen  = 1;
    itext_storage->BackPen   = 0;
    itext_storage->DrawMode  = JAM1;
    itext_storage->LeftEdge  = 4;
    itext_storage->TopEdge   = 3;
    itext_storage->ITextFont = NULL;
    itext_storage->IText     = (STRPTR)label;
    itext_storage->NextText  = NULL;

    g->NextGadget    = NULL;
    g->LeftEdge      = x;
    g->TopEdge       = y;
    g->Width         = w;
    g->Height        = h;
    g->Flags         = GFLG_GADGHCOMP;
    g->Activation    = GACT_RELVERIFY;
    g->GadgetType    = GTYP_BOOLGADGET;
    g->GadgetText    = itext_storage;
    g->GadgetID      = gid;
    if (prev) prev->NextGadget = g;
    return g;
}


/* Storage for OK/Cancel IntuiTexts — one per dialog. */
typedef struct DlgButtonText {
    struct IntuiText ok, cancel;
} DlgButtonText;


static PyObject *
py_open_dialog(PyObject *self, PyObject *args, PyObject *kwargs)
{
    static char *kw[] = {"title", "fields", "ok_label", "cancel_label",
                         "left", "top", NULL};
    const char *title = "Dialog";
    PyObject *fields_list = NULL;
    const char *ok_label = "OK";
    const char *cancel_label = "Cancel";
    int left = 100, top = 60;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "sO|ssii", kw,
            &title, &fields_list, &ok_label, &cancel_label, &left, &top))
        return NULL;

    if (!PyList_Check(fields_list) && !PyTuple_Check(fields_list)) {
        PyErr_SetString(PyExc_TypeError, "fields must be list of (label, default, maxlen)");
        return NULL;
    }
    Py_ssize_t n = PySequence_Length(fields_list);
    if (n < 1 || n > DIALOG_MAX_FIELDS) {
        PyErr_Format(PyExc_ValueError,
                     "fields must have 1..%d entries", DIALOG_MAX_FIELDS);
        return NULL;
    }

    Dialog *dlg = AllocVec(sizeof(Dialog), MEMF_ANY | MEMF_CLEAR);
    if (!dlg) { PyErr_NoMemory(); return NULL; }
    dlg->n_fields    = (int)n;
    dlg->ok_text     = dup_str(ok_label);
    dlg->cancel_text = dup_str(cancel_label);
    DlgButtonText *dbt = AllocVec(sizeof(DlgButtonText), MEMF_ANY | MEMF_CLEAR);

    /* Parse each field spec + build the gadget chain. */
    struct Gadget *chain_head = NULL;
    struct Gadget *chain_tail = NULL;
    int y_cursor = 22;
    for (Py_ssize_t i = 0; i < n; i++) {
        PyObject *spec = PySequence_GetItem(fields_list, i);
        const char *label;
        const char *default_text = "";
        int maxlen = 128;
        if (!PyArg_ParseTuple(spec, "s|si", &label, &default_text, &maxlen)) {
            Py_DECREF(spec);
            FreeVec(dlg);
            return NULL;
        }
        Py_DECREF(spec);
        if (maxlen < 4) maxlen = 4;
        if (maxlen > 512) maxlen = 512;

        DlgField *f = &dlg->fields[i];
        f->label  = dup_str(label);
        f->maxlen = maxlen;
        f->buffer = AllocVec(maxlen + 1, MEMF_ANY | MEMF_CLEAR);
        f->undo   = AllocVec(maxlen + 1, MEMF_ANY | MEMF_CLEAR);
        if (default_text && *default_text) {
            int len = (int)strlen(default_text);
            if (len > maxlen) len = maxlen;
            memcpy(f->buffer, default_text, len);
            f->buffer[len] = '\0';
        }
        f->sinfo  = mk_string_info(f->buffer, f->undo, maxlen);
        f->gadget = mk_string_gadget(chain_tail,
                                     DIALOG_LABEL_W, y_cursor,
                                     360, DIALOG_GADGET_H,
                                     GID_FIELD_BASE + (int)i, f->sinfo);
        if (!chain_head) chain_head = f->gadget;
        chain_tail = f->gadget;
        y_cursor += DIALOG_GADGET_H + DIALOG_ROW_SPACING;
    }

    /* OK / Cancel row */
    y_cursor += DIALOG_ROW_SPACING;
    dlg->g_ok = mk_bool_gadget(chain_tail, DIALOG_LABEL_W, y_cursor,
                                80, DIALOG_GADGET_H + 4,
                                GID_OK, dlg->ok_text, &dbt->ok);
    if (chain_tail) chain_tail->NextGadget = dlg->g_ok;
    else            chain_head = dlg->g_ok;
    dlg->g_cancel = mk_bool_gadget(dlg->g_ok, DIALOG_LABEL_W + 100, y_cursor,
                                    80, DIALOG_GADGET_H + 4,
                                    GID_CANCEL, dlg->cancel_text, &dbt->cancel);

    int win_h = y_cursor + DIALOG_GADGET_H + 30;
    int win_w = DIALOG_LABEL_W + 380;

    dlg->win = OpenWindowTags(NULL,
        WA_Title,       (Tag)title,
        WA_Left,        left,
        WA_Top,         top,
        WA_InnerWidth,  win_w,
        WA_InnerHeight, win_h,
        WA_IDCMP,       IDCMP_CLOSEWINDOW | IDCMP_GADGETUP | IDCMP_VANILLAKEY,
        WA_Flags,       WFLG_DRAGBAR | WFLG_DEPTHGADGET | WFLG_CLOSEGADGET
                        | WFLG_ACTIVATE | WFLG_SIMPLE_REFRESH,
        WA_Gadgets,     chain_head,
        WA_MinWidth,    win_w,
        WA_MinHeight,   win_h,
        TAG_END);

    if (!dlg->win) {
        PyErr_SetString(PyExc_RuntimeError, "OpenWindowTags failed for dialog");
        FreeVec(dlg);
        return NULL;
    }

    /* Draw the labels to the left of each string gadget. */
    struct RastPort *rp = dlg->win->RPort;
    SetAPen(rp, 1);
    for (int i = 0; i < dlg->n_fields; i++) {
        int ly = 22 + i * (DIALOG_GADGET_H + DIALOG_ROW_SPACING);
        Move(rp, dlg->win->BorderLeft + 8,
                 dlg->win->BorderTop + ly + DIALOG_GADGET_H - 3);
        Text(rp, (STRPTR)dlg->fields[i].label,
                 (LONG)strlen(dlg->fields[i].label));
    }

    /* Auto-activate the first string gadget so the user can start
     * typing immediately without an extra click.  This also forces
     * a refresh which recomputes cursor position from BufferPos. */
    if (dlg->n_fields > 0 && dlg->fields[0].gadget) {
        ActivateGadget(dlg->fields[0].gadget, dlg->win, NULL);
    }

    return PyLong_FromUnsignedLong((unsigned long)(uintptr_t)dlg);
}


static PyObject *
py_run_dialog(PyObject *self, PyObject *args)
{
    unsigned long handle;
    if (!PyArg_ParseTuple(args, "k", &handle)) return NULL;
    Dialog *dlg = (Dialog *)(uintptr_t)handle;
    if (!dlg || !dlg->win) Py_RETURN_NONE;

    struct MsgPort *port = dlg->win->UserPort;
    ULONG sig = 1UL << port->mp_SigBit;

    int result = -1;   /* -1 = still running, 0 = cancel, 1 = OK */
    while (result < 0) {
        Py_BEGIN_ALLOW_THREADS
        Wait(sig);
        Py_END_ALLOW_THREADS

        struct IntuiMessage *msg;
        while ((msg = (struct IntuiMessage *)GetMsg(port))) {
            ULONG cls = msg->Class;
            struct Gadget *g = (struct Gadget *)msg->IAddress;
            UWORD code = msg->Code;
            ReplyMsg((struct Message *)msg);

            if (cls == IDCMP_CLOSEWINDOW) {
                result = 0;
                break;
            }
            if (cls == IDCMP_GADGETUP && g) {
                if (g->GadgetID == GID_OK)     { result = 1; break; }
                if (g->GadgetID == GID_CANCEL) { result = 0; break; }
                /* String gadget confirmed with Return — treat as OK */
                if (g->GadgetType == GTYP_STRGADGET) { result = 1; break; }
            }
            if (cls == IDCMP_VANILLAKEY && code == 27) {
                result = 0;
                break;
            }
        }
    }

    if (result != 1) Py_RETURN_NONE;

    /* Harvest field text into a dict. */
    PyObject *d = PyDict_New();
    if (!d) return NULL;
    for (int i = 0; i < dlg->n_fields; i++) {
        DlgField *f = &dlg->fields[i];
        PyObject *v = PyUnicode_DecodeLatin1(f->buffer,
                                              strlen(f->buffer), "replace");
        if (!v || PyDict_SetItemString(d, f->label, v) < 0) {
            Py_XDECREF(v);
            Py_DECREF(d);
            return NULL;
        }
        Py_DECREF(v);
    }
    return d;
}


static PyObject *
py_close_dialog(PyObject *self, PyObject *args)
{
    unsigned long handle;
    if (!PyArg_ParseTuple(args, "k", &handle)) return NULL;
    Dialog *dlg = (Dialog *)(uintptr_t)handle;
    if (!dlg) Py_RETURN_NONE;

    if (dlg->win) {
        CloseWindow(dlg->win);
        dlg->win = NULL;
    }
    for (int i = 0; i < dlg->n_fields; i++) {
        DlgField *f = &dlg->fields[i];
        if (f->label)  FreeVec(f->label);
        if (f->gadget) FreeVec(f->gadget);
        if (f->sinfo)  FreeVec(f->sinfo);
        if (f->buffer) FreeVec(f->buffer);
        if (f->undo)   FreeVec(f->undo);
    }
    if (dlg->g_ok)     FreeVec(dlg->g_ok);
    if (dlg->g_cancel) FreeVec(dlg->g_cancel);
    if (dlg->ok_text)     FreeVec(dlg->ok_text);
    if (dlg->cancel_text) FreeVec(dlg->cancel_text);
    FreeVec(dlg);
    Py_RETURN_NONE;
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
/* ARexx — send commands to any public MsgPort speaking the ARexx        */
/*         protocol; also drive the REXX interpreter itself.             */
/* --------------------------------------------------------------------- */

/* Send a single RXCOMM message to `port_name` and block until the
 * reply comes back.  On success returns the RESULT string (empty
 * string if the host didn't set one).  On failure raises RuntimeError
 * or ValueError with the ARexx severity/error pair.
 *
 * `port_name` is the public MsgPort name (case-sensitive on OS4;
 * classic ARexx uppercases them).  `command` is the raw ARexx
 * command string as the target app would parse it (e.g. "PLAY",
 * "QUIT", "GETATTR STEM ATTR VALUE VAR result", etc). */
static PyObject *
py_rexx_send(PyObject *self, PyObject *args)
{
    const char *port_name;
    const char *command;
    if (!PyArg_ParseTuple(args, "ss", &port_name, &command))
        return NULL;

    if (!RexxSysBase || !IRexxSys) {
        PyErr_SetString(PyExc_RuntimeError,
                        "rexxsyslib.library not open — _amiga init failed to open it");
        return NULL;
    }

    /* Find the target port.  Public-port list needs Forbid()/Permit(). */
    struct MsgPort *target = NULL;
    Forbid();
    target = FindPort((STRPTR)port_name);
    Permit();
    if (!target) {
        PyErr_Format(PyExc_ValueError, "ARexx port '%s' not found", port_name);
        return NULL;
    }

    /* Fresh reply port for this exchange — using our own port keeps
     * the exchange strictly synchronous (no chance of colliding with
     * a background reply from an earlier call). */
    struct MsgPort *reply = CreateMsgPort();
    if (!reply) {
        return PyErr_NoMemory();
    }

    struct RexxMsg *msg = CreateRexxMsg(reply, NULL, (STRPTR)port_name);
    if (!msg) {
        DeleteMsgPort(reply);
        return PyErr_NoMemory();
    }

    msg->rm_Args[0] = CreateArgstring((STRPTR)command, strlen(command));
    if (!msg->rm_Args[0]) {
        DeleteRexxMsg(msg);
        DeleteMsgPort(reply);
        return PyErr_NoMemory();
    }
    msg->rm_Action = RXCOMM | RXFF_RESULT;

    /* Fire and wait. */
    PutMsg(target, (struct Message *)msg);
    WaitPort(reply);
    struct RexxMsg *rpl = (struct RexxMsg *)GetMsg(reply);

    PyObject *result = NULL;
    if (rpl->rm_Result1 == RC_OK) {
        if (rpl->rm_Result2) {
            result = py_str_safe((const char *)rpl->rm_Result2);
            DeleteArgstring((STRPTR)rpl->rm_Result2);
        } else {
            result = PyUnicode_FromString("");
        }
    } else {
        PyErr_Format(PyExc_RuntimeError,
                     "ARexx returned severity=%ld error=%ld for port '%s'",
                     (long)rpl->rm_Result1, (long)rpl->rm_Result2, port_name);
    }

    DeleteArgstring((STRPTR)rpl->rm_Args[0]);
    DeleteRexxMsg(rpl);
    DeleteMsgPort(reply);

    return result;
}


/* Execute an ARexx script string via the REXX interpreter port.
 * Convenience wrapper: sends `command` to port "REXX" with RXFF_STRING
 * so the interpreter treats it as an inline script rather than a
 * disk-loaded .rexx file.  Returns the RESULT the script emitted
 * (via RESULT after `options results`), or empty string. */
static PyObject *
py_rexx_execute(PyObject *self, PyObject *args)
{
    const char *script;
    if (!PyArg_ParseTuple(args, "s", &script))
        return NULL;

    if (!RexxSysBase || !IRexxSys) {
        PyErr_SetString(PyExc_RuntimeError,
                        "rexxsyslib.library not open");
        return NULL;
    }

    struct MsgPort *rexx_port = NULL;
    Forbid();
    rexx_port = FindPort((STRPTR)"REXX");
    Permit();
    if (!rexx_port) {
        PyErr_SetString(PyExc_RuntimeError,
                        "REXX port not found — is the rexxmast server running?");
        return NULL;
    }

    struct MsgPort *reply = CreateMsgPort();
    if (!reply) return PyErr_NoMemory();

    struct RexxMsg *msg = CreateRexxMsg(reply, (STRPTR)"rexx", (STRPTR)"REXX");
    if (!msg) {
        DeleteMsgPort(reply);
        return PyErr_NoMemory();
    }

    msg->rm_Args[0] = CreateArgstring((STRPTR)script, strlen(script));
    if (!msg->rm_Args[0]) {
        DeleteRexxMsg(msg);
        DeleteMsgPort(reply);
        return PyErr_NoMemory();
    }
    msg->rm_Action = RXCOMM | RXFF_STRING | RXFF_RESULT;

    PutMsg(rexx_port, (struct Message *)msg);
    WaitPort(reply);
    struct RexxMsg *rpl = (struct RexxMsg *)GetMsg(reply);

    PyObject *result = NULL;
    if (rpl->rm_Result1 == RC_OK) {
        if (rpl->rm_Result2) {
            result = py_str_safe((const char *)rpl->rm_Result2);
            DeleteArgstring((STRPTR)rpl->rm_Result2);
        } else {
            result = PyUnicode_FromString("");
        }
    } else {
        PyErr_Format(PyExc_RuntimeError,
                     "REXX script error severity=%ld error=%ld",
                     (long)rpl->rm_Result1, (long)rpl->rm_Result2);
    }

    DeleteArgstring((STRPTR)rpl->rm_Args[0]);
    DeleteRexxMsg(rpl);
    DeleteMsgPort(reply);

    return result;
}


/* Return the list of public MsgPort names that *look* like ARexx
 * ports — heuristic: an ARexx-aware Amiga app publishes a port
 * whose name is all uppercase (classic convention).  Filters
 * IExec-owned ports (SERIAL, PARALLEL, ...) that aren't ARexx targets.
 *
 * Not perfect — a rogue app can publish a lowercase ARexx port and
 * a system port might be uppercase — but a useful cut of the noise
 * for a "which apps can I talk to" listing.  Callers who want the
 * raw list should use list_ports(). */
static PyObject *
py_list_rexx_ports(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    PyObject *out = PyList_New(0);
    if (!out) return NULL;

    static const char *SYS_PORTS[] = {
        "input.device", "timer.device", "console.device", "audio.device",
        "trackdisk.device", "serial.device", "parallel.device",
        "gameport.device", "keyboard.device", "printer.device",
        NULL,
    };

    Forbid();
    struct ExecBase *sb = (struct ExecBase *)SysBase;
    for (struct Node *n = sb->PortList.lh_Head; n->ln_Succ; n = n->ln_Succ) {
        const char *name = (n->ln_Name != NULL) ? (const char *)n->ln_Name : "";
        if (!*name) continue;

        /* Uppercase-only heuristic. */
        int ok = 1;
        for (const char *p = name; *p; p++) {
            unsigned char c = (unsigned char)*p;
            if (c >= 'a' && c <= 'z') { ok = 0; break; }
        }
        if (!ok) continue;

        /* Skip well-known system devices. */
        for (const char **s = SYS_PORTS; *s; s++) {
            if (strcmp(name, *s) == 0) { ok = 0; break; }
        }
        if (!ok) continue;

        PyObject *py_name = py_str_safe(name);
        if (!py_name) { Permit(); Py_DECREF(out); return NULL; }
        if (PyList_Append(out, py_name) < 0) {
            Permit();
            Py_DECREF(py_name);
            Py_DECREF(out);
            return NULL;
        }
        Py_DECREF(py_name);
    }
    Permit();

    return out;
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

    /* Composite dialog with StringGadgets */
    {"open_dialog",       (PyCFunction)py_open_dialog,
                                                METH_VARARGS | METH_KEYWORDS,
        "open_dialog(title, fields=[(label, default, maxlen), ...], "
        "ok_label='OK', cancel_label='Cancel', left=100, top=60) -> handle."},
    {"run_dialog",        py_run_dialog,        METH_VARARGS,
        "run_dialog(handle) -> {label: text} on OK, None on Cancel."},
    {"close_dialog",      py_close_dialog,      METH_VARARGS,
        "close_dialog(handle) — free gadgets + close window."},

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

    /* ARexx — send commands to remote ports + drive the REXX interpreter */
    {"rexx_send",         py_rexx_send,         METH_VARARGS,
        "rexx_send(port, command) -> result_str — send RXCOMM to an ARexx port."},
    {"rexx_execute",      py_rexx_execute,      METH_VARARGS,
        "rexx_execute(script) -> result_str — run inline REXX via the REXX port."},
    {"list_rexx_ports",   py_list_rexx_ports,   METH_NOARGS,
        "list_rexx_ports() -> [name] of public ports that look like ARexx targets."},

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
    if (!RexxSysBase) {
        RexxSysBase = OpenLibrary("rexxsyslib.library", 44);
        if (RexxSysBase) {
            IRexxSys = (struct RexxSysIFace *)
                GetInterface(RexxSysBase, "main", 1, NULL);
            if (!IRexxSys) {
                CloseLibrary(RexxSysBase);
                RexxSysBase = NULL;
            }
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
