"""The one line anything calls to put a finding in front of the gate.

Deliberately tiny. Spooling has to be cheap enough that a caller never has to
think about whether a finding is worth recording -- that judgement is the
gate's job, later, when the GPU is free. Spool generously; the nightly pass
throws most of it away.

From code:

    from record import note
    note("DFlash2 reached 117 tokens/sec on code prompts", source="bench-12")

From a shell, which is how a protocol or a finished job records one:

    python3 record.py "llama.cpp PR 27342 adds DFlash2 support" --source pr-watch

Returns/exits false-ish on failure and never raises. A memory system that can
break the thing it is observing is worse than no memory system.
"""

from __future__ import annotations

import argparse
import sys

from spool import Spool


def note(fact: str, source=None, root=None, **extra) -> bool:
    return Spool(root).add(fact, source=source, **extra)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Spool one finding for the gate.")
    ap.add_argument("fact", nargs="+")
    ap.add_argument("--source", default=None)
    ap.add_argument("--root", default=None)
    a = ap.parse_args(argv)
    ok = note(" ".join(a.fact), source=a.source, root=a.root)
    if not ok:
        print("could not spool", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
