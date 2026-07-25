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
                         "0.1.0",
                         "phase 6 initial");
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
    {NULL, NULL, 0, NULL},
};


static struct PyModuleDef amigamodule = {
    PyModuleDef_HEAD_INIT,
    "_amiga",
    "Native AmigaOS bindings (Phase 6 — replaces os.system shell-outs).",
    -1,
    amiga_methods,
};


PyMODINIT_FUNC
PyInit__amiga(void)
{
    PyObject *m = PyModule_Create(&amigamodule);
    if (!m) return NULL;

    /* Expose common MEMF_ constants so scripts don't need to hardcode. */
    PyModule_AddIntConstant(m, "MEMF_ANY",     MEMF_ANY);
    PyModule_AddIntConstant(m, "MEMF_PUBLIC",  MEMF_PUBLIC);
    PyModule_AddIntConstant(m, "MEMF_CHIP",    MEMF_CHIP);
    PyModule_AddIntConstant(m, "MEMF_FAST",    MEMF_FAST);
    PyModule_AddIntConstant(m, "MEMF_LARGEST", MEMF_LARGEST);
    PyModule_AddIntConstant(m, "MEMF_CLEAR",   MEMF_CLEAR);

    return m;
}
