import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from values import abstains, key, numbers, recovers, same, tidy


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


class Negation(unittest.TestCase):
    """The failure that cost the most. Asked the merge status of a pull
    request the model answered "Merged" 8/8; the truth was "unmerged". Plain
    substring containment made that a HIT, so the gate concluded the model
    already knew and threw away the best kind of memory there is -- one where
    the model is confidently and exactly wrong."""

    def test_merged_is_not_unmerged(self):
        self.assertFalse(same("Merged", "unmerged"))

    def test_merged_is_still_merged(self):
        self.assertTrue(same("Merged", "merged"))

    def test_other_negations(self):
        for a, b in (("stable", "unstable"), ("secure", "insecure"),
                     ("possible", "impossible"), ("legal", "illegal"),
                     ("regular", "irregular"), ("agree", "disagree")):
            self.assertFalse(same(a, b), f"{a!r} must not match {b!r}")

    def test_word_boundary_not_mere_prefix(self):
        self.assertFalse(same("cat", "category"))
        self.assertTrue(same("cat", "the cat sat"))


class Lists(unittest.TestCase):
    """An answer that is a list is a set. The real reply differed from the
    stored answer by one conjunction and exact containment failed 6/6."""

    ANSWER = "edit_line, insert_lines, patch and rewrite_function"

    def test_commas_instead_of_and(self):
        ok, why = recovers("edit_line, insert_lines, patch, rewrite_function",
                           self.ANSWER)
        self.assertTrue(ok); self.assertEqual(why, "list")

    def test_any_order(self):
        ok, _ = recovers("patch, rewrite_function, edit_line, insert_lines",
                         self.ANSWER)
        self.assertTrue(ok)

    def test_a_missing_item_is_caught(self):
        ok, why = recovers("edit_line, insert_lines, patch", self.ANSWER)
        self.assertFalse(ok); self.assertTrue(why.startswith("missing:"))

    def test_same_stays_conservative_about_lists(self):
        # same() does NOT do set logic, on purpose: a comma does not reliably
        # mean a list ("Paris, France" is one answer). A false hit here throws
        # a fact away; a false miss only stores one that did not need storing.
        # So reordered lists read as a miss, and that is the safe direction.
        self.assertFalse(same("patch, edit_line", "edit_line and patch"))
        self.assertTrue(same("Paris, France", "Paris"))


class Identifiers(unittest.TestCase):
    """Underscores are markdown emphasis only when they wrap a word. This
    system is mostly told about code, so identifiers must survive."""

    def test_internal_underscores_survive(self):
        self.assertEqual(tidy("reasoning_content"), "reasoning_content")
        self.assertEqual(tidy("mutating_tool_names"), "mutating_tool_names")

    def test_wrapping_underscores_are_emphasis(self):
        self.assertEqual(tidy("_important_"), "important")

    def test_two_identifiers_do_not_collide(self):
        self.assertNotEqual(tidy("a_b"), tidy("ab"))


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


class Abstains(unittest.TestCase):
    def test_refusals(self):
        for s in ("Unknown", "not found", "N/A", "I don't know.", "404",
                  "Cannot determine", "**None**", "not specified"):
            self.assertTrue(abstains(s), s)

    def test_answers_are_not_refusals(self):
        for s in ("Paris", "42", "merged", "the unknown soldier",
                  "none of the above is 3"):
            self.assertFalse(abstains(s), s)
