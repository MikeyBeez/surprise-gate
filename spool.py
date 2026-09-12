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

# The day rolls over at 5am, not midnight, and that is not a detail.
#
# A working session that runs from 10pm to 3am is ONE session. Under a
# calendar day it lands in two spool files, split at an arbitrary point in the
# middle of the work, and the half after midnight is not eligible for
# consolidation until a full day later. Worse, a consolidation job scheduled
# for the small hours would be sitting INSIDE the night it is supposed to be
# tidying up, looking at a file that is still being written.
#
# So: anything before the cutoff belongs to the previous date. Pick a cutoff
# after you stop working and before the job runs.
CUTOFF_HOUR = int(os.environ.get("SG_DAY_CUTOFF", "5"))


def today() -> str:
    """The current WORKING day, which is not always the calendar date."""
    now = datetime.datetime.now()
    if now.hour < CUTOFF_HOUR:
        now -= datetime.timedelta(days=1)
    return now.date().isoformat()


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
