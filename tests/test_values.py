import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from values import key, numbers, recovers, same, tidy


class Tidy(unittest.TestCase):
    def test_markdown_and_case(self):
        self.assertEqual(tidy("The capital is **Paris**."), "the capital is paris")

    def test_does_not_mine_words_out_of_sentences(self):
        # Deliberate: pulling "the answer" out of prose invents matches.
        self.assertNotEqual(tidy("the capital is paris"), "paris")

    def test_none(self):
        self.assertEqual(tidy(None), "")


class Key(unittest.TestCase):
    def test_first_number_wins(self):
        self.assertEqual(key("about 360 degrees"), "360")

    def test_thousands_separators_collapse(self):
        self.assertEqual(key("299,792,458"), key("299792458"))

    def test_text_when_no_number(self):
        self.assertEqual(key("**Paris**"), "paris")


class Same(unittest.TestCase):
    def test_exact(self):
        self.assertTrue(same("42", "42"))

    def test_rounding_is_not_a_knowledge_gap(self):
        self.assertTrue(same("117", "117.3"))

    def test_far_apart(self):
        self.assertFalse(same("42", "28"))

    def test_decorated(self):
        self.assertTrue(same("The answer is **42**.", "42"))

    def test_word_containment(self):
        self.assertTrue(same("Paris, France", "Paris"))

    def test_one_letter_does_not_match_a_word(self):
        self.assertFalse(same("a", "apple"))

    def test_zero_does_not_divide_by_zero(self):
        self.assertTrue(same("0", "0"))
        self.assertFalse(same("0", "5"))


class Recovers(unittest.TestCase):
    """The strict matcher. Every case here is a real reply measured on pop."""

    def test_clean_hit(self):
        ok, why = recovers("117 tokens per second", "117")
        self.assertTrue(ok); self.assertEqual(why, "clean")

    def test_extra_value_is_an_ambiguous_question(self):
        # The reply the model actually gave 6/6 when the question did not say
        # which prompt type: it volunteered both, which is not an answer.
        ok, why = recovers(
            "117 tokens per second on code prompts and 75 on prose prompts",
            "117")
        self.assertFalse(ok); self.assertTrue(why.startswith("extra-values"))

    def test_answer_absent(self):
        ok, why = recovers("75 tokens per second", "117")
        self.assertFalse(ok); self.assertEqual(why, "answer-absent")

    def test_non_numeric_hit(self):
        ok, _ = recovers("Serenity", "Serenity")
        self.assertTrue(ok)

    def test_non_numeric_miss(self):
        ok, why = recovers("Tranquility", "Serenity")
        self.assertFalse(ok); self.assertEqual(why, "answer-absent")

    def test_empty_answer_is_never_a_hit(self):
        ok, why = recovers("anything", "")
        self.assertFalse(ok); self.assertEqual(why, "empty-answer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
