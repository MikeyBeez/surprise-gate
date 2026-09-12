"""Comparing two answers, which is where a gate like this quietly goes wrong.

Three rules, all learned from watching real replies:

A number that is nearly the same number is the same ANSWER. 117 and 117.3 are
rounding, not a knowledge gap, and treating them as different would store a
fact the generator already has.

A reply that volunteers a SECOND value has not answered the question -- it has
told you the question did not pick one. Measured: asked "what speed did
DFlash2 reach?" of a finding holding both 117 and 75, the model replied "117
tokens per second on code prompts and 75 tokens per second on prose prompts"
six times out of six. A first-number match scores that as correct and the
ambiguity goes unnoticed. Requiring no extra values catches it.

Text containment must respect WORD boundaries, and this one was found the
expensive way. Asked the merge status of a pull request, the model answered
"Merged" eight times out of eight. The truth was "unmerged". Plain substring
containment says "merged" is inside "unmerged", so the gate scored hit=1.0,
concluded the generator already had the fact, and threw it away -- discarding
the single most valuable thing this system can find, a case where the model is
confidently and exactly wrong. Every negation does this: stable/unstable,
secure/insecure, possible/impossible. A word-boundary match gets it right,
because "merged" as a WORD does not occur in "unmerged".

And an answer that is a LIST is a set, not a string. Asked for four tool names,
the model replied "edit_line, insert_lines, patch, rewrite_function" against a
stored answer ending "patch and rewrite_function". One conjunction, and exact
containment failed six times out of six on a perfect answer. Split on commas
and "and", then require every item to be present.
"""

from __future__ import annotations

import re

NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
REL_TOL = 0.02

# A leading negation turns an answer into its opposite while leaving the
# original as a substring. Word-boundary matching already handles these; the
# list is kept only to make the intent searchable.
_NEGATIONS = ("un", "in", "im", "il", "ir", "non", "dis", "not")


def _contains_word(haystack: str, needle: str) -> bool:
    """Containment on word boundaries, so \'merged\' is not found in
    \'unmerged\' and \'stable\' is not found in \'unstable\'."""
    if not needle:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])",
                     haystack) is not None


def items(s: str) -> list:
    """Split a list-shaped answer into its parts. Not a list -> one part."""
    parts = re.split(r",|\band\b|;|/", tidy(s))
    return [p.strip() for p in parts if p.strip()]


def numbers(s: str) -> list:
    return [x.replace(",", "") for x in NUM.findall(s or "")]


def tidy(s: str) -> str:
    """Lowercase, drop markdown and trailing punctuation. Deliberately does
    NOT try to pull a short answer out of a sentence -- that is a rabbit hole
    that invents matches. Containment below handles decorated replies."""
    s = re.sub(r"[*`]", "", s or "").strip().lower()
    # Underscores are markdown emphasis only when they WRAP a word. Stripping
    # them everywhere mangles every identifier this system is likely to be
    # told about -- edit_line, reasoning_content, mutating_tool_names.
    s = re.sub(r"(?<![a-z0-9])_+|_+(?![a-z0-9])", "", s)
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
    if not (ta and tb):
        return False
    # Deliberately NO list handling here. A comma does not reliably mean a
    # list: "Paris, France" is one answer and "edit_line, patch" is two, and
    # nothing in the string says which. Guessing wrong in THIS function is the
    # expensive direction -- a false hit means "the model already knows it"
    # and the fact is discarded. A false miss only means the fact is stored
    # when it did not need to be, which costs a line in a file. So this stays
    # conservative and the list logic lives in recovers(), where the answer's
    # shape is known and a miss merely rejects the question.
    if min(len(ta), len(tb)) < 3:
        return False
    return _contains_word(tb, ta) or _contains_word(ta, tb)


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
    want = items(ta)
    if len(want) > 1:
        missing = [w for w in want if not _contains_word(tr, w) and w not in tr]
        if missing:
            return False, "missing:" + ",".join(missing[:3])
        return True, "list"
    ok = _contains_word(tr, ta) or (len(ta) >= 3 and ta in tr and
                                    _contains_word(tr, ta))
    return (ok, "text" if ok else "answer-absent")
