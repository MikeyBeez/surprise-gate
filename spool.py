"""The fast store: a day's candidate facts, appended and forgotten.

This is the half that runs while work is happening, so its only job is to be
cheap and to never be the reason a task failed. One line appended to a JSONL
file, every error swallowed. No model call, no probe, no thinking -- the gate
costs about 2.7 seconds a fact, and paying that during inference would be a
tax on every task. It is paid once, later, when the GPU is idle.

Erasable on purpose. A spool file is the day's scratch; consolidate.py reads
it, decides what is worth keeping, and removes it. Anything that mattered is
in the kept store by then. That is the point of having two stores at different
speeds: the fast one can be wide open because losing it costs nothing.
"""

from __future__ import annotations

import datetime
import json
import os

DIR = os.path.expanduser(os.environ.get("SG_DIR", "~/.surprise-gate"))


def today() -> str:
    return datetime.date.today().isoformat()


class Spool:
    def __init__(self, root=None):
        self.root = os.path.expanduser(root or DIR)
        self.spool_dir = os.path.join(self.root, "spool")

    def path(self, day=None) -> str:
        return os.path.join(self.spool_dir, f"{day or today()}.jsonl")

    def add(self, fact: str, source=None, day=None, **extra) -> bool:
        """Append one candidate. Returns False rather than raising, ever."""
        if not (fact or "").strip():
            return False
        try:
            os.makedirs(self.spool_dir, exist_ok=True)
            rec = {"ts": __import__("time").time(), "fact": fact.strip(),
                   "source": source, **extra}
            with open(self.path(day), "a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
            return True
        except Exception:
            return False

    def read(self, day=None) -> list:
        p = self.path(day)
        if not os.path.isfile(p):
            return []
        out = []
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue          # a torn last line must not kill the pass
        return out

    def days(self) -> list:
        if not os.path.isdir(self.spool_dir):
            return []
        return sorted(f[:-6] for f in os.listdir(self.spool_dir)
                      if f.endswith(".jsonl"))

    def drop(self, day=None) -> bool:
        try:
            os.remove(self.path(day))
            return True
        except Exception:
            return False
