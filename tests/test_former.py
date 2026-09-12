import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from former import form, open_book, question_for

TWO = ("DFlash2 reached 117 tokens per second on code prompts and 75 tokens "
       "per second on prose prompts.")


def script(seq):
    box = {"i": 0}

    def fn(_s, _u, **kw):
        v = seq[min(box["i"], len(seq) - 1)]
        box["i"] += 1
        if isinstance(v, Exception):
            raise v
        return v
    return fn


class Form(unittest.TestCase):
    def test_plain_json(self):
        r = form("x", chat_fn=script(['{"question": "Q?", "answer": "42"}']))
        self.assertEqual((r["question"], r["answer"]), ("Q?", "42"))

    def test_json_with_chatter_around_it(self):
        r = form("x", chat_fn=script(['Sure:\n{"question":"Q?","answer":"42"}\ndone']))
        self.assertEqual(r["answer"], "42")

    def test_no_json_is_an_error_not_a_crash(self):
        self.assertEqual(form("x", chat_fn=script(["I cannot"]))["error"], "no-json")

    def test_unterminated_json_has_no_braces_to_find(self):
        # No closing brace, so nothing matches at all -- a different path from
        # malformed-but-bracketed, and worth keeping them apart.
        self.assertEqual(form("x", chat_fn=script(['{"question":']))["error"],
                         "no-json")

    def test_malformed_json_inside_braces(self):
        r = form("x", chat_fn=script(['{"question": , "answer": 1}']))
        self.assertIn("bad-json", r["error"])

    def test_empty_field(self):
        r = form("x", chat_fn=script(['{"question":"","answer":"42"}']))
        self.assertEqual(r["error"], "empty-field")

    def test_non_string_answer_is_coerced(self):
        r = form("x", chat_fn=script(['{"question":"Q?","answer":42}']))
        self.assertEqual(r["answer"], "42")


class OpenBook(unittest.TestCase):
    """Each case is a reply shape measured against pop, not invented."""

    def test_clean_question_passes(self):
        r = open_book(TWO, "speed on code prompts?", "117", n=6,
                      chat_fn=script(["117 tokens per second"]))
        self.assertTrue(r["ok"]); self.assertEqual(r["rate"], 1.0)

    def test_ambiguous_question_is_caught(self):
        r = open_book(TWO, "what speed did it reach?", "117", n=6,
                      chat_fn=script(["117 on code and 75 on prose"]))
        self.assertFalse(r["ok"])
        self.assertTrue(any(w.startswith("extra-values") for w in r["why"]))

    def test_answer_not_in_finding_is_caught(self):
        r = open_book(TWO, "what speed did MTP reach?", "97", n=6,
                      chat_fn=script(["117 tokens per second"]))
        self.assertFalse(r["ok"])
        self.assertIn("answer-absent", r["why"])

    def test_probe_failure_is_not_usable(self):
        r = open_book(TWO, "q", "117", n=4,
                      chat_fn=script([ConnectionError("down")]))
        self.assertFalse(r["ok"]); self.assertIn("probe-failed", r["why"])

    def test_mixed_replies_at_the_line(self):
        # 4 of 6 is exactly the 0.625 threshold from below: not usable.
        r = open_book(TWO, "q", "117", n=6, chat_fn=script(
            ["117", "117", "117", "117", "75", "75"]))
        self.assertEqual(r["rate"], 0.667)
        self.assertTrue(r["ok"])


class QuestionFor(unittest.TestCase):
    def test_form_failure_short_circuits(self):
        r = question_for("x", chat_fn=script(["nope"]))
        self.assertFalse(r["usable"]); self.assertEqual(r["stage"], "form")

    def test_good_pipeline(self):
        r = question_for(TWO, n=4, chat_fn=script(
            ['{"question":"speed on code prompts?","answer":"117"}',
             "117", "117", "117", "117"]))
        self.assertTrue(r["usable"])
        self.assertEqual(r["answer"], "117")

    def test_bad_question_rejected_before_the_probe(self):
        r = question_for(TWO, n=4, chat_fn=script(
            ['{"question":"how fast?","answer":"117"}',
             "117 on code and 75 on prose"]))
        self.assertFalse(r["usable"])
        self.assertEqual(r["stage"], "open-book")


if __name__ == "__main__":
    unittest.main(verbosity=2)
