"""Turn a raw finding into a retrieval question, then check the question.

The probe needs a (question, answer) pair. Getting that pair out of a free-text
finding is a generative step, so it is the part of this system most likely to
be quietly wrong -- and a bad question poisons everything downstream, because a
question with no determinate answer scatters exactly like a fact the model has
never heard of.

So the question is never trusted, it is TESTED, with an open-book control: ask
it again with the finding IN CONTEXT. A well-formed question must recover the
answer when the answer is sitting right there. Measured on pop (Qwen3.8-27B,
n=6):

    good, fully-qualified question        6/6 recover
    good question, two-value finding      6/6
    ambiguous ("what speed did it reach") 1/6   caught: extra-values:75
    too broad ("how fast is it")          3/6   caught: extra-values:75
    answer not in the finding             0/6   caught: answer-absent
    question points at the other value    0/6   caught: answer-absent
    good non-numeric question             6/6

All four bad shapes are caught and both good shapes pass, so the control has
teeth. Note that it does NOT judge whether a question is silly in the world --
"what is the optimal number of seagulls in a flock" passes, because given the
finding it does retrieve 42, and retrieval is the only thing that matters here.
"""

from __future__ import annotations

import json
import re

from llm import chat
from values import recovers

FORM_SYSTEM = (
    "You turn a finding into ONE retrieval question.\n"
    'Reply with JSON only: {"question": "...", "answer": "..."}\n'
    "The question must be answerable ONLY by the single most specific value in "
    "the finding, and must carry enough detail that it could not be confused "
    "with a similar measurement. The answer must be that value, copied "
    "verbatim, nothing else."
)

OPEN_SYSTEM = ("Use ONLY the finding below. Answer with the value only, "
               "nothing else.")


def form(fact: str, temp=0.3, chat_fn=None) -> dict:
    """fact -> {"question":..., "answer":...}, or {"error":...}."""
    chat_fn = chat_fn or chat
    raw = chat_fn(FORM_SYSTEM, "Finding: " + fact, temp=temp, max_tokens=160)
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return {"error": "no-json", "raw": (raw or "")[:200]}
    try:
        d = json.loads(m.group(0))
    except Exception as e:
        return {"error": f"bad-json: {e}", "raw": m.group(0)[:200]}
    q, a = str(d.get("question", "")).strip(), str(d.get("answer", "")).strip()
    if not q or not a:
        return {"error": "empty-field", "raw": json.dumps(d)[:200]}
    return {"question": q, "answer": a}


def open_book(fact: str, question: str, answer: str, n=6, temp=0.8,
              chat_fn=None) -> dict:
    """Can the question recover the answer with the finding in front of it?"""
    chat_fn = chat_fn or chat
    user = f"Finding: {fact}\n\nQuestion: {question}"
    replies, errors = [], []
    for _ in range(max(1, n)):
        try:
            replies.append(chat_fn(OPEN_SYSTEM, user, temp=temp, max_tokens=40))
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")
    if not replies:
        return {"ok": False, "rate": 0.0, "why": ["probe-failed"],
                "errors": errors[:3], "n": 0}
    res = [recovers(r, answer) for r in replies]
    hits = sum(1 for ok, _ in res if ok)
    rate = hits / len(replies)
    return {"ok": rate >= 0.625, "rate": round(rate, 3), "n": len(replies),
            "why": sorted({w for ok, w in res if not ok}),
            "replies": replies, "errors": errors[:3]}


def question_for(fact: str, n=6, chat_fn=None) -> dict:
    """form + open-book in one call. `usable` is the only field a caller needs."""
    f = form(fact, chat_fn=chat_fn)
    if "error" in f:
        return {"usable": False, "stage": "form", **f}
    ob = open_book(fact, f["question"], f["answer"], n=n, chat_fn=chat_fn)
    return {"usable": bool(ob["ok"]), "stage": "open-book",
            "question": f["question"], "answer": f["answer"],
            "open_book_rate": ob["rate"], "why": ob["why"],
            "replies": ob.get("replies", []), "errors": ob.get("errors", [])}
