#!/usr/bin/env python3
"""arexx_demo.py — ARexx from Python on AmigaOS 4.1.

Text-mode smoke test.  What it exercises:

  * _amiga.list_rexx_ports()     — enumerate ARexx-capable apps that
                                   are currently running.
  * _amiga.rexx_execute(script)  — hand an inline REXX script to the
                                   interpreter and capture its RESULT.
  * _amiga.rexx_send(port, cmd)  — send a single command string to a
                                   remote ARexx port (e.g. AmigaAmp).

Companion GUI: rexx_console.py — clickable port picker + free-form
command entry, built on amiga.ui.
"""
import sys

try:
    import _amiga
except ImportError:
    print("_amiga native module not available — this is an OS4-only demo.")
    sys.exit(1)


def hr(title):
    print()
    print("=" * 60)
    print(f" {title}")
    print("=" * 60)


def probe_rexx_ports():
    hr("Public ports that look like ARexx targets")
    if not hasattr(_amiga, "list_rexx_ports"):
        print("this _amiga build doesn't expose list_rexx_ports() — "
              "need a rebuild with the ARexx patch.")
        return []
    ports = _amiga.list_rexx_ports()
    if not ports:
        print("(none — no ARexx-aware apps currently running)")
        return []
    for p in ports:
        print(f"  {p}")
    return ports


def probe_rexx_interpreter():
    hr("REXX interpreter (rexxmast)")
    if not hasattr(_amiga, "rexx_execute"):
        print("this build lacks rexx_execute()")
        return
    try:
        r = _amiga.rexx_execute(
            "/* smoke */ x = 6 * 7 ; say 'from python: answer is ' || x ; return x"
        )
        print(f"  script returned: {r!r}")
    except RuntimeError as e:
        if "REXX port not found" in str(e):
            print("  REXX port isn't running — start rexxmast from the shell first:")
            print("    > SYS:System/RexxMast  (or add to your Startup-Sequence)")
        else:
            print(f"  REXX error: {e}")


def probe_amigaamp(ports):
    """If AmigaAmp is running, ping it. Otherwise skip."""
    amp = next((p for p in ports if p.upper().startswith(("AMIGAAMP",
                                                            "TUNENET",
                                                            "MULTIVIEW"))),
               None)
    hr(f"App probe: {amp or '(no known media app found)'}")
    if not amp:
        print("  Try launching AmigaAmp / TuneNet / MultiView and re-run.")
        return
    # Very generic — most ARexx-aware apps understand STATUS or VERSION.
    for cmd in ("VERSION", "STATUS"):
        try:
            r = _amiga.rexx_send(amp, cmd)
            print(f"  {cmd:10s} -> {r!r}")
        except Exception as e:
            print(f"  {cmd:10s} -> ERR: {e}")


def main():
    print("ARexx demo — Python 3.12.7 / AmigaOS 4.1 PPC")
    print(f"_amiga methods: {sorted(m for m in dir(_amiga) if not m.startswith('_'))}")

    ports = probe_rexx_ports()
    probe_rexx_interpreter()
    probe_amigaamp(ports)

    print()
    print("For interactive use: DH1:python-os4 DH1:pytests/examples/rexx_console.py")


if __name__ == "__main__":
    main()
