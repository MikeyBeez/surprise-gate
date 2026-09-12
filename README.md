# surprise-gate

Decide what an agent should remember by checking whether the model already
knows it.

The rule, in one line: after the agent learns something, ask a **fresh context**
a question whose answer is that thing. If the fresh context answers correctly,
throw the memory away — you can always get it back out of the generator. If it
answers something else, keep it, because now you know something the weights
don't.

Nothing here runs during inference. Findings are spooled cheaply while work
happens; a separate job walks the day's spool later, when the GPU is idle, and
decides what survives.

## Why a fresh context

Asking the working model mid-task "what did you expect?" measures nothing — the
answer is already in its window. A clean context can't cheat. That one move is
the whole measurement.

## Why several samples instead of one

A single greedy answer is a coin flip. The same question can say 42 once and 37
the next time, and then the decision depends on which run you happened to get.
N draws give two numbers, and the second one turns out to be the useful one:

- **hit rate** — how often a clean context produces *our* answer. Does the
  generator already have this?
- **self-agreement** — how often it agrees with *itself*. Does it have any
  stable view at all?

Measured on an RTX 5070 Ti running Qwen3.8-27B at Q3_K_XL, thinking off,
temperature 0.8, n=8:

    capital of France      8/8 self-agreement, 1 distinct answer   skip
    degrees in a circle    8/8, 1                                  skip
    speed of light         8/8, 1                                  skip
    optimal seagulls       3/8, 5                                  store
    a private benchmark    1/8, 8                                  store

Known facts pin at 8/8. Anything the model has no view of scatters. The gap is
wide, so the 0.625 threshold sits in open space rather than on top of the data.

About 2.7 seconds per fact at n=8. That cost is exactly why this is a batch job.

## The hard part: the question

The probe needs a question and an answer. Getting that pair out of a free-text
finding is a generative step, and it's the part most likely to be quietly
wrong — a question with no determinate answer scatters in exactly the same way
as a fact the model has never heard of.

So the question is never trusted, it's tested, with an **open-book control**:
ask it again with the finding in context. A well-formed question has to recover
the answer when the answer is sitting right there. Measured, n=6:

    good, fully-qualified question         6/6 recover
    good question, two-value finding       6/6
    ambiguous ("what speed did it reach")  1/6   caught: extra-values:75
    too broad ("how fast is it")           3/6   caught: extra-values:75
    answer not in the finding              0/6   caught: answer-absent
    question points at the other value     0/6   caught: answer-absent
    good non-numeric question              6/6

All four bad shapes caught, both good shapes pass.

One detail earned that: a reply volunteering a *second* value hasn't answered
the question, it has told you the question didn't pick one. Asked "what speed
did DFlash2 reach?" of a finding holding both 117 and 75, the model replied
"117 on code prompts and 75 on prose prompts" six times out of six. Matching on
the first number scores that as correct and the ambiguity goes unnoticed.
Requiring *no extra values* catches it.

## Two stores, two clocks

The fast store is a day's JSONL spool. Appending to it costs nothing, never
calls a model, and never raises — it must not be the reason a task failed. It's
erasable on purpose: consolidation reads it, keeps what's worth keeping, and
deletes it.

The slow store is `kept.jsonl`, append-only, carrying each surviving fact with
its question, its answer, and the numbers behind the decision.

Promotion is the second clock. One day is an observation. A question that comes
back on several **separate** days is a pattern, and only then is it a candidate
for something that changes behaviour. One vivid day must not be able to write a
rule — that's the failure this arrangement exists to prevent.

    python3 consolidate.py --promotions --min-days 3

A promoted question whose answer has *changed* across days is flagged rather
than hidden.

## The order of the gates

1. **dedupe** — free. A fact noticed twenty times costs one probe, not twenty.
2. **form a question** — one model call.
3. **open-book check** — n calls. Fail here and nothing downstream is
   trustworthy, so stop.
4. **closed-book probe** — n calls. Does a fresh context already know it?

Cheapest and most certain first. Candidates that fail step 3 never reach step 4,
which is most of the saving on a messy day.

## Usage

While working — one line, microseconds, never throws. Spool generously; it's
the gate's job to throw things away, not yours:

```python
from record import note
note("DFlash2 reached 117 tokens/sec on code prompts", source="bench-12")
```

Or from a shell, which is how a finished job or a protocol records one:

```sh
python3 record.py "llama.cpp PR 27342 adds DFlash2 support" --source pr-watch
```

Later, when the card is free:

```sh
python3 consolidate.py                  # every finished day; today is left alone
python3 consolidate.py --day 2026-09-11
python3 consolidate.py --dry-run        # dedupe only, no model calls
python3 consolidate.py --promotions
```

A real pass, 7 findings spooled:

    2026-09-10: 7 spooled, 5 unique after dedupe
      DROP  redundant    What is the capital of France?  hit=1.0
      DROP  redundant    How many degrees are in a circle?  hit=1.0
      KEEP  model-has-no-stable-view   What was the throughput in tokens per second... = 117
      KEEP  model-has-no-stable-view   What is the optimal number of seagulls in a flock? = 42
      KEEP  model-has-no-stable-view   Which llama.cpp pull request number adds DFlash2... = 27342
    {"spooled": 7, "unique": 5, "kept": 3, "redundant": 2, "seconds": 28.72}

### Nightly

`nightly.sh` is the cron entry point. It adds two things a bare
`consolidate.py` doesn't have:

```
17 3 * * *  /path/to/surprise-gate/nightly.sh
```

A **lock** (mkdir, atomic) so a slow pass can't overlap the next night's and
probe the same spool twice.

A **GPU check on utilisation, not memory**. The first version of that script
checked `memory.used` and would have skipped every single night: a resident
`llama-server` holds about 15.8 of 16 GiB permanently, so by that measure the
card is never free. What matters is whether anything is *running*. Three
readings three seconds apart, because one sample catches an idle instant in the
middle of a busy run. Skips above 25% peak; `SG_FORCE=1` runs anyway.

A real night, seeded with three findings, two of them identical:

    2026-09-11T23:15:48-05:00 GPU idle (peak 0%)
    2026-09-11T23:15:48-05:00 start
    2026-09-09: 3 spooled, 2 unique after dedupe
      DROP  redundant    What is the capital of France?  hit=1.0
      KEEP  model-has-no-stable-view   What is the optimal number of seagulls in a flock? = 42
    2026-09-09: spool cleared
    {"spooled": 3, "unique": 2, "kept": 1, "redundant": 1, "seconds": 10.8}
    2026-09-11T23:15:59-05:00 done

## Two verdicts, not three

An early draft had a third verdict for the scattered case, calling it a weak
retrieval key. The first live run killed it: a well-posed question about a
private benchmark scattered in exactly the same way as a deliberately vague
one. The closed-book measurement cannot separate "the question is vague" from
"the model has never heard of this." Separating those is the open-book
control's job, not the probe's, so the probe doesn't pretend to. The scatter is
reported as a number; it isn't a judgement.

## Deleting, too

The same probe run later against a newer model gives a garbage-collection
criterion: a kept fact whose verdict has become `skip` is now redundant with
the weights and can go. Memory that shrinks as the model grows.

## Configuration

| variable | default | meaning |
|---|---|---|
| `SG_URL` | `http://127.0.0.1:8080/v1/chat/completions` | llama.cpp server |
| `SG_DIR` | `~/.surprise-gate` | spool and stores |
| `SG_N` | `8` | samples per probe |
| `SG_TEMP` | `0.8` | probe temperature |
| `SG_KNOWN` | `0.625` | hit rate at or above which a fact is redundant |
| `SG_CONSISTENT` | `0.625` | self-agreement at or above which the model has a view |
| `SG_KEEP_DROPPED` | unset | keep full text of dropped facts (debugging the gate) |
| `SG_TIMEOUT` | `120` | seconds per request |
| `SG_BUSY_PCT` | `25` | nightly.sh skips above this GPU utilisation |
| `SG_FORCE` | unset | `1` makes nightly.sh ignore the GPU check |
| `SG_LOGDIR` | `~/.surprise-gate` | nightly.sh log and lock |

Two request flags are load-bearing, not cosmetic. `cache_prompt: false`, or one
sample primes the next and N draws stop being independent. And
`enable_thinking: false` — Qwen3.8 is a reasoning model, and with thinking on
the chat endpoint puts the chain of thought in `reasoning_content` and the
answer in `content`, so a small `max_tokens` returns an empty string and every
probe reads as a miss. It's also right on the merits: a reasoning pass is the
model working the answer out, and what's being measured is what it already
holds.

## Failure direction

A probe that can't run returns **store**. Losing a real memory costs more than
keeping a redundant one.

## Tests

    tests/run_all.sh

72 tests. Every one stubs the model, so the suite needs no GPU and no server —
what's tested is the decision, not the network.
