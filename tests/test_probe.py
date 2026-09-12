import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import probe as P
from probe import probe, should_store


def scripted(answers):
    """A chat_fn walking a fixed list, repeating the last forever."""
    box = {"i": 0}

    def fn(_sys, _user, **kw):
        a = answers[min(box["i"], len(answers) - 1)]
        box["i"] += 1
        if isinstance(a, Exception):
            raise a
        return a
    return fn


class Verdicts(unittest.TestCase):
    def test_known_fact_is_skipped(self):
        r = probe("capital of France?", "Paris", n=8, chat_fn=scripted(["Paris"]))
        self.assertEqual(r["verdict"], "skip")
        self.assertEqual(r["reason"], "already-in-the-weights")

    def test_confidently_wrong_is_stored(self):
        r = probe("optimal seagulls?", "42", n=8, chat_fn=scripted(["28"]))
        self.assertEqual(r["verdict"], "store")
        self.assertEqual(r["reason"], "model-is-confidently-wrong")
        self.assertEqual(r["mode"], "28")

    def test_scattered_is_stored(self):
        r = probe("q", "Rust", n=6,
                  chat_fn=scripted(["Python", "C", "Go", "Lisp", "Perl", "Zig"]))
        self.assertEqual(r["verdict"], "store")
        self.assertEqual(r["reason"], "model-has-no-stable-view")
        self.assertEqual(r["distinct"], 6)

    def test_only_two_verdicts_exist(self):
        seen = set()
        for a in (["42"], ["28"], ["a", "b", "c", "d"], [ConnectionError("x")]):
            seen.add(probe("q", "42", n=4, chat_fn=scripted(a))["verdict"])
        self.assertEqual(seen, {"skip", "store"})

    def test_six_of_eight_still_counts_as_known(self):
        r = probe("q", "42", n=8, chat_fn=scripted(
            ["42", "42", "42", "42", "42", "42", "7", "9"]))
        self.assertEqual(r["verdict"], "skip")

    def test_half_is_not_enough(self):
        r = probe("q", "42", n=8, chat_fn=scripted(
            ["42", "42", "42", "42", "7", "9", "11", "13"]))
        self.assertEqual(r["verdict"], "store")

    def test_near_miss_counts_as_known(self):
        r = probe("t/s?", "117", n=8, chat_fn=scripted(["117.4"]))
        self.assertEqual(r["verdict"], "skip")


class Failure(unittest.TestCase):
    def test_total_failure_stores(self):
        r = probe("q", "42", n=4, chat_fn=scripted([ConnectionError("down")]))
        self.assertEqual(r["verdict"], "store")
        self.assertEqual(r["reason"], "probe-failed")
        self.assertTrue(r["errors"])

    def test_partial_failure_uses_what_came_back(self):
        r = probe("q", "42", n=4,
                  chat_fn=scripted([TimeoutError("slow"), "42", "42", "42"]))
        self.assertEqual(r["verdict"], "skip")
        self.assertEqual(r["n"], 3)

    def test_empty_replies_do_not_crash(self):
        r = probe("q", "42", n=4, chat_fn=scripted([""]))
        self.assertEqual(r["verdict"], "store")


class Api(unittest.TestCase):
    def test_should_store(self):
        self.assertFalse(should_store("q", "42", n=4, chat_fn=scripted(["42"])))
        self.assertTrue(should_store("q", "42", n=4, chat_fn=scripted(["28"])))

    def test_numbers_are_reported(self):
        r = probe("q", "42", n=4, chat_fn=scripted(["28"]))
        for k in ("hit_rate", "self_agreement", "distinct", "mode", "n",
                  "samples", "seconds", "detail", "reason"):
            self.assertIn(k, r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
