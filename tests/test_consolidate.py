"""End to end, with the model stubbed out. What is tested is the PASS."""
import os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import consolidate as C
import former, probe
from consolidate import consolidate_day, group, run
from spool import Spool
from store import Store


class Group(unittest.TestCase):
    def test_identical_facts_collapse_with_a_count(self):
        g = group([{"fact": "X is 1"}, {"fact": "x is 1  "}, {"fact": "Y is 2"}])
        self.assertEqual(len(g), 2)
        self.assertEqual(g[0]["count"], 2)

    def test_sources_are_unioned(self):
        g = group([{"fact": "X", "source": "a"}, {"fact": "X", "source": "b"}])
        self.assertEqual(g[0]["sources"], ["a", "b"])

    def test_blank_facts_are_dropped(self):
        self.assertEqual(group([{"fact": "  "}, {}]), [])


class Pass(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.spool = Spool(self.root)
        self.store = Store(self.root)
        self._qf, self._pr = former.question_for, probe.probe
        C.question_for, C.probe = None, None

    def tearDown(self):
        former.question_for, probe.probe = self._qf, self._pr
        C.question_for, C.probe = self._qf, self._pr
        shutil.rmtree(self.root, ignore_errors=True)

    def wire(self, qf, pr):
        C.question_for, C.probe = qf, pr

    def test_redundant_fact_is_dropped(self):
        self.spool.add("Paris is the capital of France", day="2026-09-11")
        self.wire(lambda f, n=6: {"usable": True, "question": "capital?",
                                 "answer": "Paris", "open_book_rate": 1.0},
                  lambda q, a, n=6: {"verdict": "skip",
                                     "reason": "already-in-the-weights",
                                     "hit_rate": 1.0, "self_agreement": 1.0,
                                     "errors": [], "detail": "", "distinct": 1,
                                     "mode": "paris", "n": n})
        s = consolidate_day("2026-09-11", root=self.root, log=lambda *a: None)
        self.assertEqual((s["kept"], s["redundant"]), (0, 1))
        self.assertEqual(self.store.kept(), [])
        self.assertEqual(self.store.dropped()[0]["outcome"], "redundant")

    def test_novel_fact_is_kept(self):
        self.spool.add("DFlash2 hit 117 t/s on code", day="2026-09-11")
        self.wire(lambda f, n=6: {"usable": True, "question": "t/s on code?",
                                 "answer": "117", "open_book_rate": 1.0},
                  lambda q, a, n=6: {"verdict": "store",
                                     "reason": "model-has-no-stable-view",
                                     "hit_rate": 0.0, "self_agreement": 0.2,
                                     "errors": [], "detail": "d", "distinct": 7,
                                     "mode": "1", "n": n})
        s = consolidate_day("2026-09-11", root=self.root, log=lambda *a: None)
        self.assertEqual(s["kept"], 1)
        k = self.store.kept()[0]
        self.assertEqual(k["answer"], "117")
        self.assertEqual(k["day"], "2026-09-11")

    def test_bad_question_never_reaches_the_probe(self):
        self.spool.add("two values in here", day="2026-09-11")
        called = []
        self.wire(lambda f, n=6: {"usable": False, "stage": "open-book",
                                  "why": ["extra-values:75"],
                                  "question": "how fast?", "answer": "117",
                                  "open_book_rate": 0.16},
                  lambda q, a, n=6: called.append(1) or {})
        s = consolidate_day("2026-09-11", root=self.root, log=lambda *a: None)
        self.assertEqual(s["bad_question"], 1)
        self.assertEqual(called, [])          # the expensive step was skipped
        self.assertEqual(self.store.dropped()[0]["outcome"], "bad-question")

    def test_duplicates_cost_one_probe(self):
        for _ in range(20):
            self.spool.add("the same finding", day="2026-09-11")
        calls = []
        self.wire(lambda f, n=6: {"usable": True, "question": "q?",
                                  "answer": "1", "open_book_rate": 1.0},
                  lambda q, a, n=6, **kw: calls.append(1) or {
                      "verdict": "store", "reason": "model-has-no-stable-view",
                      "hit_rate": 0.0, "self_agreement": 0.1, "errors": [],
                      "detail": "", "distinct": 6, "mode": "x", "n": 6})
        s = consolidate_day("2026-09-11", root=self.root, log=lambda *a: None)
        self.assertEqual((s["spooled"], s["unique"]), (20, 1))
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.store.kept()[0]["count"], 20)

    def test_dry_run_makes_no_model_calls(self):
        self.spool.add("x", day="2026-09-11")
        self.wire(lambda *a, **k: 1 / 0, lambda *a, **k: 1 / 0)
        s = consolidate_day("2026-09-11", root=self.root, dry_run=True,
                            log=lambda *a: None)
        self.assertEqual(s["unique"], 1)
        self.assertEqual(s["kept"], 0)

    def test_empty_day(self):
        s = consolidate_day("1999-01-01", root=self.root, log=lambda *a: None)
        self.assertEqual(s["spooled"], 0)


class SpoolLifecycle(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.spool = Spool(self.root)
        self._qf, self._pr = former.question_for, probe.probe

    def tearDown(self):
        C.question_for, C.probe = self._qf, self._pr
        shutil.rmtree(self.root, ignore_errors=True)

    def test_todays_spool_is_left_alone(self):
        from spool import today
        self.spool.add("today's fact")
        C.question_for = lambda *a, **k: 1 / 0
        run(root=self.root, log=lambda *a: None)
        self.assertIn(today(), self.spool.days())

    def test_a_finished_day_is_cleared_after_the_pass(self):
        self.spool.add("old fact", day="2026-09-01")
        C.question_for = lambda f, n=6: {"usable": True, "question": "q?",
                                         "answer": "1", "open_book_rate": 1.0}
        C.probe = lambda q, a, n=6: {"verdict": "skip", "reason": "r",
                                     "hit_rate": 1.0, "self_agreement": 1.0,
                                     "errors": [], "detail": "", "distinct": 1,
                                     "mode": "1", "n": n}
        run(root=self.root, log=lambda *a: None)
        self.assertNotIn("2026-09-01", self.spool.days())

    def test_keep_spool_leaves_it(self):
        self.spool.add("old fact", day="2026-09-01")
        C.question_for = lambda f, n=6: {"usable": False, "stage": "form",
                                         "error": "no-json"}
        run(root=self.root, keep_spool=True, log=lambda *a: None)
        self.assertIn("2026-09-01", self.spool.days())


if __name__ == "__main__":
    unittest.main(verbosity=2)
