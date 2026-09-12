"""The slow store: what survived the gate, and the ledger that promotes it.

kept.jsonl is append-only. One line per fact that the gate decided the
generator could not recall, carrying the question, the answer, and the numbers
behind the decision -- because a threshold nobody can audit is one nobody
should trust.

dropped.jsonl is the tape for the other direction. By default it records the
DECISION and not the content: the reason, the numbers, and a short prefix of
the fact. That is deliberate. Writing the full text of everything the gate
threw away would mean nothing was ever actually deleted, and an erasable fast
store is half the design. SG_KEEP_DROPPED=1 keeps the whole text when you are
debugging the gate itself.

PROMOTION is the second clock. A fact kept on one day is one observation. A
question that comes back on several SEPARATE days is a pattern, and only then
is it a candidate for the slow store proper (a protocol, a rule, something
that changes behaviour). One vivid day should not be able to write a rule --
that is the failure mode this whole arrangement exists to prevent.
"""

from __future__ import annotations

import hashlib
import json
import os

from values import tidy

KEEP_DROPPED = os.environ.get("SG_KEEP_DROPPED", "") == "1"


def qkey(question: str) -> str:
    """A stable id for a question, so the same question asked on different
    days lands on the same ledger row."""
    return hashlib.sha1(tidy(question).encode()).hexdigest()[:16]


class Store:
    def __init__(self, root):
        self.root = os.path.expanduser(root)
        self.kept_path = os.path.join(self.root, "kept.jsonl")
        self.dropped_path = os.path.join(self.root, "dropped.jsonl")

    def _append(self, path, rec) -> bool:
        try:
            os.makedirs(self.root, exist_ok=True)
            with open(path, "a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
            return True
        except Exception:
            return False

    def keep(self, rec: dict) -> bool:
        rec = dict(rec)
        rec["qkey"] = qkey(rec.get("question", ""))
        return self._append(self.kept_path, rec)

    def drop(self, rec: dict) -> bool:
        rec = dict(rec)
        if not KEEP_DROPPED:
            f = rec.get("fact") or ""
            rec["fact"] = f[:120] + ("..." if len(f) > 120 else "")
            rec.pop("samples", None)
            rec.pop("replies", None)
        return self._append(self.dropped_path, rec)

    def kept(self) -> list:
        return _read(self.kept_path)

    def dropped(self) -> list:
        return _read(self.dropped_path)

    def promotions(self, min_days=3) -> list:
        """Questions kept on min_days or more SEPARATE days: the ones that have
        earned a look at the slow store. Returns newest-first by day count."""
        by_q = {}
        for r in self.kept():
            k = r.get("qkey") or qkey(r.get("question", ""))
            e = by_q.setdefault(k, {"qkey": k, "question": r.get("question"),
                                    "answers": set(), "days": set()})
            e["days"].add(r.get("day"))
            if r.get("answer"):
                e["answers"].add(str(r["answer"]))
        out = []
        for e in by_q.values():
            days = sorted(d for d in e["days"] if d)
            if len(days) >= min_days:
                out.append({"qkey": e["qkey"], "question": e["question"],
                            "answers": sorted(e["answers"]),
                            "days": days, "day_count": len(days),
                            "stable": len(e["answers"]) == 1})
        return sorted(out, key=lambda x: -x["day_count"])


def _read(path) -> list:
    if not os.path.isfile(path):
        return []
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    return out
