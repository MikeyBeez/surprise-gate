"""The nightly pass: walk a day's spool and decide what to keep.

This is the half that needs a GPU, and the reason it is a separate job is
arithmetic. The gate costs about 2.7 seconds a fact; a day that spools 200
candidates would add ten minutes to the working day if the gate ran inline,
and adds nothing at all if it runs at 3am against an idle card.

Running it as a batch buys two things beyond the latency. Duplicates collapse
BEFORE any model call, so a fact noticed twenty times costs one probe instead
of twenty. And the spool gives a day count for free, which is exactly the
signal the slow store needs: one day is an observation, several separate days
is a pattern.

THE ORDER OF THE GATES, and why it is this order:

  1. dedupe          free. Collapse identical facts, keep the count.
  2. form a question  one call. The finding is free text; the probe needs a
                      (question, answer) pair.
  3. open-book check  n calls. Can the question recover the answer with the
                      finding in front of it? If not, the question is unusable
                      and nothing downstream can be trusted -- drop it here
                      rather than let a bad question scatter and look like a
                      discovery.
  4. closed-book probe n calls. Does a FRESH context already know the answer?
                      If yes, the generator has it and the memory is redundant.

Cheapest and most certain first. A candidate that fails step 3 never reaches
step 4, which is most of the saving on a messy day.

    python3 consolidate.py                 # yesterday and earlier, for real
    python3 consolidate.py --day 2026-09-11
    python3 consolidate.py --dry-run       # no model calls, just the dedupe
    python3 consolidate.py --promotions
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import sys
import time

from former import question_for
from probe import probe
from spool import DIR, Spool, today
from store import Store
from values import tidy


def group(records: list) -> list:
    """Collapse identical findings, keeping how many times each was seen.
    Free, and it is where most of the day's volume goes on a repetitive run."""
    by = collections.OrderedDict()
    for r in records:
        f = (r.get("fact") or "").strip()
        if not f:
            continue
        k = tidy(f)
        e = by.setdefault(k, {"fact": f, "count": 0, "sources": set(),
                              "first_ts": r.get("ts")})
        e["count"] += 1
        if r.get("source"):
            e["sources"].add(str(r["source"]))
    out = []
    for e in by.values():
        e["sources"] = sorted(e["sources"])
        out.append(e)
    return out


def consolidate_day(day: str, root=None, n=6, dry_run=False, log=print) -> dict:
    spool = Spool(root)
    store = Store(spool.root)
    records = spool.read(day)
    groups = group(records)

    summary = {"day": day, "spooled": len(records), "unique": len(groups),
               "kept": 0, "dropped": 0, "bad_question": 0, "redundant": 0,
               "errors": 0, "seconds": 0.0}
    t0 = time.time()
    if not records:
        log(f"{day}: nothing spooled")
        return summary
    log(f"{day}: {len(records)} spooled, {len(groups)} unique after dedupe")
    if dry_run:
        for g in groups:
            log(f"  x{g['count']:<3} {g['fact'][:90]}")
        summary["seconds"] = round(time.time() - t0, 2)
        return summary

    for g in groups:
        fact, count = g["fact"], g["count"]
        q = question_for(fact, n=n)
        if not q.get("usable"):
            summary["bad_question"] += 1
            summary["dropped"] += 1
            store.drop({"day": day, "fact": fact, "count": count,
                        "outcome": "bad-question", "stage": q.get("stage"),
                        "why": q.get("why") or q.get("error"),
                        "open_book_rate": q.get("open_book_rate"),
                        "question": q.get("question"),
                        "answer": q.get("answer")})
            log(f"  DROP  bad-question  {fact[:64]}  ({q.get('why') or q.get('error')})")
            continue

        p = probe(q["question"], q["answer"], n=n)
        if p["errors"]:
            summary["errors"] += 1
        if p["verdict"] == "skip":
            summary["redundant"] += 1
            summary["dropped"] += 1
            store.drop({"day": day, "fact": fact, "count": count,
                        "outcome": "redundant", "reason": p["reason"],
                        "question": q["question"], "answer": q["answer"],
                        "hit_rate": p["hit_rate"],
                        "self_agreement": p["self_agreement"]})
            log(f"  DROP  redundant    {q['question'][:64]}  hit={p['hit_rate']}")
        else:
            summary["kept"] += 1
            store.keep({"day": day, "fact": fact, "count": count,
                        "sources": g["sources"],
                        "question": q["question"], "answer": q["answer"],
                        "reason": p["reason"], "detail": p["detail"],
                        "hit_rate": p["hit_rate"],
                        "self_agreement": p["self_agreement"],
                        "distinct": p["distinct"], "mode": p["mode"],
                        "open_book_rate": q["open_book_rate"], "n": p["n"]})
            log(f"  KEEP  {p['reason']:26s} {q['question'][:56]} = {q['answer'][:24]}")

    summary["seconds"] = round(time.time() - t0, 2)
    return summary


def run(root=None, day=None, n=6, dry_run=False, keep_spool=False,
        log=print) -> list:
    """Consolidate one day, or every spooled day strictly before today.

    Today's spool is left alone by default: the day is not over, and a pass
    that ran at noon would have to run again anyway.
    """
    spool = Spool(root)
    days = [day] if day else [d for d in spool.days() if d < today()]
    out = []
    for d in days:
        s = consolidate_day(d, root=root, n=n, dry_run=dry_run, log=log)
        out.append(s)
        if not dry_run and not keep_spool and s["spooled"]:
            # The fast store is erasable by design. Everything that survived is
            # in kept.jsonl and every decision is in dropped.jsonl.
            spool.drop(d)
            log(f"{d}: spool cleared")
    if not days:
        log("no completed days to consolidate")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--day")
    ap.add_argument("--root", default=None)
    ap.add_argument("-n", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-spool", action="store_true")
    ap.add_argument("--promotions", action="store_true")
    ap.add_argument("--min-days", type=int, default=3)
    a = ap.parse_args(argv)

    if a.promotions:
        store = Store(Spool(a.root).root)
        rows = store.promotions(min_days=a.min_days)
        if not rows:
            print(f"nothing kept on {a.min_days}+ separate days yet")
            return 0
        for r in rows:
            flag = "stable" if r["stable"] else "CHANGED"
            print(f"{r['day_count']} days  [{flag}]  {r['question'][:70]}")
            print(f"          answers={r['answers']}  days={r['days']}")
        return 0

    res = run(root=a.root, day=a.day, n=a.n, dry_run=a.dry_run,
              keep_spool=a.keep_spool)
    for s in res:
        print(json.dumps(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
