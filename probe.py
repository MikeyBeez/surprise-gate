"""The write gate: store only what the generator cannot recall.

Mikey's rule, in his words: the agent finds the optimal X is 42; ask a FRESH
context what the optimal X is; if it says 42 do not store it, you can always
retrieve it from the generator; if it says 28, store it, because now you know
something the weights do not.

WHY A FRESH CONTEXT. Asking the working model mid-task what it expected is
worthless -- the answer is sitting in the window. A clean context cannot cheat.

WHY N SAMPLES. One greedy answer is a coin flip: the same question can say 42
once and 37 the next time, and the decision would depend on which run you got.
N draws give two numbers, and the second is the useful one -- hit rate (does
the generator have OUR answer) and self-agreement (does it have any stable
view at all).

Measured on pop, Qwen3.8-27B Q3_K_XL, thinking off, temp 0.8, n=8:

    capital of France      8/8 self-agreement, 1 distinct  -> skip
    degrees in a circle    8/8, 1                          -> skip
    speed of light         8/8, 1                          -> skip
    optimal seagulls       3/8, 5                          -> store
    a private benchmark    1/8, 8                          -> store

Known facts pin at 8/8 and unknown ones scatter, so the 0.625 line sits in
open space rather than on top of the data. ~2.7s per fact at n=8, which is why
this runs in a nightly batch and not in the inference path.

TWO VERDICTS, NOT THREE. An early draft had a third for the scattered case,
calling it a weak retrieval key. The first live run killed it: a well-posed
question about a private benchmark scattered exactly like a deliberately vague
one. Separating those needs the open-book control in former.py, not this
measurement, so this one does not pretend to.

FAIL-SAFE: a probe that cannot run returns store. Losing a real memory costs
more than keeping a redundant one.

THE SAME PROBE DELETES: re-run it later against a newer model. A kept fact
whose verdict has become skip is now redundant with the weights and can go.
Memory that shrinks as the model grows.
"""

from __future__ import annotations

import collections
import os
import time

from llm import chat
from values import key, same

N = int(os.environ.get("SG_N", "8"))
TEMP = float(os.environ.get("SG_TEMP", "0.8"))
CONSISTENT = float(os.environ.get("SG_CONSISTENT", "0.625"))
KNOWN = float(os.environ.get("SG_KNOWN", "0.625"))

SYSTEM = ("Answer with the value only -- a number or a few words. "
          "No sentence, no units, no markdown, no explanation.")


def probe(question: str, answer: str, n=N, temp=TEMP, chat_fn=None) -> dict:
    chat_fn = chat_fn or chat
    t0 = time.time()
    samples, errors = [], []
    for _ in range(max(1, n)):
        try:
            samples.append(chat_fn(SYSTEM, question, temp=temp, max_tokens=32))
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")

    if not samples:
        return {"verdict": "store", "reason": "probe-failed",
                "detail": "the clean-context probe could not run, so this "
                          "could not be shown redundant; storing is the safe "
                          "direction",
                "question": question, "answer": answer, "n": 0,
                "errors": errors[:3], "seconds": round(time.time() - t0, 2)}

    keys = [key(s) for s in samples]
    counts = collections.Counter(keys)
    mode, mode_n = counts.most_common(1)[0]
    agreement = mode_n / len(keys)
    hits = sum(1 for s in samples if same(s, answer))
    hit_rate = hits / len(samples)

    if hit_rate >= KNOWN:
        verdict, reason = "skip", "already-in-the-weights"
        detail = (f"a clean context produced this answer {hits}/{len(samples)} "
                  f"times; retrievable from the generator")
    elif agreement >= CONSISTENT:
        verdict, reason = "store", "model-is-confidently-wrong"
        detail = (f"a clean context reliably says {mode!r} "
                  f"({mode_n}/{len(keys)}), not {key(answer)!r}")
    else:
        verdict, reason = "store", "model-has-no-stable-view"
        detail = (f"a clean context scattered across {len(counts)} answers in "
                  f"{len(keys)} tries (mode {mode!r}, {mode_n}); not "
                  f"retrievable")

    return {"verdict": verdict, "reason": reason, "detail": detail,
            "question": question, "answer": answer,
            "hit_rate": round(hit_rate, 3),
            "self_agreement": round(agreement, 3),
            "distinct": len(counts), "mode": mode, "n": len(samples),
            "samples": samples, "errors": errors[:3],
            "seconds": round(time.time() - t0, 2)}


def should_store(question: str, answer: str, **kw) -> bool:
    return probe(question, answer, **kw)["verdict"] != "skip"
