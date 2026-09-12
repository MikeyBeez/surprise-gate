"""The one place this package talks to a model.

Everything here runs against a local llama.cpp server, and two flags are
load-bearing rather than cosmetic:

cache_prompt False -- otherwise one sample primes the next and N samples stop
being N independent draws, which is the whole point of taking N.

enable_thinking False -- Qwen3.8 is a reasoning model. With thinking ON the
chat endpoint puts the chain of thought in reasoning_content and the ANSWER in
content, so a small max_tokens returns an empty string and every probe reads
as a miss. That cost an hour. It is also the right call on the merits: a
reasoning pass is the model working an answer out, and what the probe measures
is what it already holds. 9 tokens instead of 35.
"""

from __future__ import annotations

import json
import os
import urllib.request

URL = os.environ.get("SG_URL", "http://127.0.0.1:8080/v1/chat/completions")
TIMEOUT = float(os.environ.get("SG_TIMEOUT", "120"))


def chat(system: str, user: str, temp=0.8, max_tokens=40, url=None,
         timeout=None) -> str:
    body = json.dumps({
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": temp, "top_p": 0.95, "max_tokens": max_tokens,
        "cache_prompt": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(url or URL, body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as r:
        d = json.load(r)
    return (d["choices"][0]["message"].get("content") or "").strip()
