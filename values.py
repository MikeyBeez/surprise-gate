"""Comparing two answers, which is where a gate like this quietly goes wrong.

Two rules, both learned from watching real replies:

A number that is nearly the same number is the same ANSWER. 117 and 117.3 are
rounding, not a knowledge gap, and treating them as different would store a
fact the generator already has.

A reply that volunteers a SECOND value has not answered the question -- it has
told you the question did not pick one. Measured: asked "what speed did
DFlash2 reach?" of a finding holding both 117 and 75, the model replied "117
tokens per second on code prompts and 75 tokens per second on prose prompts"
six times out of six. A first-number match scores that as correct and the
ambiguity goes unnoticed. Requiring no extra values catches it.
"""

from __future__ import annotations

import re

NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
REL_TOL = 0.02


def numbers(s: str) -> list:
    return [x.replace(",", "") for x in NUM.findall(s or "")]


def tidy(s: str) -> str:
    """Lowercase, drop markdown and trailing punctuation. Deliberately does
    NOT try to pull a short answer out of a sentence -- that is a rabbit hole
    that invents matches. Containment below handles decorated replies."""
    s = re.sub(r"[*_`]", "", s or "").strip().lower()
    return " ".join(s.rstrip(".!").split())


def key(s: str) -> str:
    """A comparable form: the first number if there is one, else tidied text.
    Used for grouping samples, not for deciding hits."""
    n = numbers(s)
    return n[0] if n else tidy(s)


def as_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def same(a: str, b: str, rel_tol=REL_TOL) -> bool:
    """Loose match: is this reply giving our answer at all?"""
    ka, kb = key(a), key(b)
    if ka == kb:
        return True
    xa, xb = as_float(ka), as_float(kb)
    if xa is not None and xb is not None:
        return abs(xa - xb) / max(abs(xa), abs(xb), 1e-9) <= rel_tol
    ta, tb = tidy(a), tidy(b)
    if ta and tb and (ta in tb or tb in ta) and min(len(ta), len(tb)) >= 3:
        return True
    return False


def recovers(reply: str, answer: str) -> tuple:
    """Strict match, for the open-book check: the reply must give our answer
    and NOTHING else. Returns (ok, why)."""
    ra, aa = numbers(reply), numbers(answer)
    if aa:
        if not any(a in ra for a in aa):
            return False, "answer-absent"
        extra = [x for x in ra if x not in aa]
        if extra:
            return False, "extra-values:" + ",".join(extra[:3])
        return True, "clean"
    ta, tr = tidy(answer), tidy(reply)
    if not ta:
        return False, "empty-answer"
    return (ta in tr, "text" if ta in tr else "answer-absent")
