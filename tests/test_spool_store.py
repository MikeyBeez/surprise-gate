import os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import store as S
from spool import Spool
from store import Store, qkey


class SpoolTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.s = Spool(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_add_and_read(self):
        self.assertTrue(self.s.add("a fact", source="test", day="2026-09-11"))
        recs = self.s.read("2026-09-11")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["fact"], "a fact")
        self.assertEqual(recs[0]["source"], "test")

    def test_blank_is_refused(self):
        self.assertFalse(self.s.add("   ", day="2026-09-11"))

    def test_add_never_raises(self):
        bad = Spool("/proc/nope/cannot-create")
        self.assertFalse(bad.add("x"))          # no exception

    def test_read_missing_day_is_empty(self):
        self.assertEqual(self.s.read("1999-01-01"), [])

    def test_torn_line_does_not_kill_the_pass(self):
        self.s.add("good", day="2026-09-11")
        with open(self.s.path("2026-09-11"), "a") as fh:
            fh.write('{"fact": "truncated\n')
        self.assertEqual(len(self.s.read("2026-09-11")), 1)

    def test_days_and_drop(self):
        self.s.add("x", day="2026-09-10")
        self.s.add("y", day="2026-09-11")
        self.assertEqual(self.s.days(), ["2026-09-10", "2026-09-11"])
        self.assertTrue(self.s.drop("2026-09-10"))
        self.assertEqual(self.s.days(), ["2026-09-11"])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.st = Store(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_keep_adds_a_qkey(self):
        self.st.keep({"question": "Q?", "answer": "42", "day": "2026-09-11"})
        self.assertEqual(self.st.kept()[0]["qkey"], qkey("Q?"))

    def test_qkey_is_stable_across_casing_and_spacing(self):
        self.assertEqual(qkey("What  is X?"), qkey("what is x?"))

    def test_dropped_truncates_content_by_default(self):
        self.st.drop({"fact": "x" * 300, "outcome": "redundant",
                      "samples": ["a", "b"]})
        d = self.st.dropped()[0]
        self.assertLess(len(d["fact"]), 130)
        self.assertNotIn("samples", d)

    def test_keep_dropped_env_keeps_everything(self):
        saved = S.KEEP_DROPPED
        S.KEEP_DROPPED = True
        try:
            self.st.drop({"fact": "y" * 300, "samples": ["a"]})
            d = self.st.dropped()[0]
            self.assertEqual(len(d["fact"]), 300)
            self.assertIn("samples", d)
        finally:
            S.KEEP_DROPPED = saved


class Promotion(unittest.TestCase):
    """One vivid day must not be able to write a rule."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.st = Store(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_one_day_does_not_promote(self):
        self.st.keep({"question": "Q?", "answer": "42", "day": "2026-09-11"})
        self.assertEqual(self.st.promotions(min_days=3), [])

    def test_same_day_twice_does_not_promote(self):
        for _ in range(5):
            self.st.keep({"question": "Q?", "answer": "42", "day": "2026-09-11"})
        self.assertEqual(self.st.promotions(min_days=3), [])

    def test_three_separate_days_promotes(self):
        for d in ("2026-09-09", "2026-09-10", "2026-09-11"):
            self.st.keep({"question": "Q?", "answer": "42", "day": d})
        p = self.st.promotions(min_days=3)
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]["day_count"], 3)
        self.assertTrue(p[0]["stable"])

    def test_a_changed_answer_is_flagged_not_hidden(self):
        self.st.keep({"question": "Q?", "answer": "42", "day": "2026-09-09"})
        self.st.keep({"question": "Q?", "answer": "42", "day": "2026-09-10"})
        self.st.keep({"question": "Q?", "answer": "28", "day": "2026-09-11"})
        p = self.st.promotions(min_days=3)[0]
        self.assertFalse(p["stable"])
        self.assertEqual(p["answers"], ["28", "42"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
