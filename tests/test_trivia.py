import random
import unittest

from engine.trivia import (
    SEED_QUESTIONS,
    check_answer,
    check_mc_answer,
    check_open_answer,
    check_tf_answer,
    format_correct_answer,
    normalize_text,
    parse_mc_answer_index,
    parse_true_false,
    pick_game_questions,
    validate_mcq,
    validate_open,
    validate_tf,
)


class NormalizeTests(unittest.TestCase):
    def test_normalize_strips_punctuation_and_case(self):
        self.assertEqual(normalize_text("  Pacific-Ocean!! "), "pacific ocean")
        self.assertEqual(normalize_text("CO2"), "co2")

    def test_parse_mc_letters_and_numbers(self):
        self.assertEqual(parse_mc_answer_index("A"), 0)
        self.assertEqual(parse_mc_answer_index("d"), 3)
        self.assertEqual(parse_mc_answer_index("2"), 1)
        self.assertIsNone(parse_mc_answer_index("Z"))

    def test_parse_true_false_synonyms(self):
        for yes in ("true", "T", "yes", "y", "1"):
            self.assertTrue(parse_true_false(yes))
        for no in ("false", "F", "no", "n", "0"):
            self.assertFalse(parse_true_false(no))
        self.assertIsNone(parse_true_false("maybe"))


class ValidateTests(unittest.TestCase):
    def test_validate_mcq_accepts_letter_or_option_text(self):
        cleaned = validate_mcq("Capital city?", ["a", "b", "c", "d"], "B")
        self.assertEqual(cleaned["answer_index"], 1)
        cleaned = validate_mcq("Capital city?", ["London", "Paris", "Rome", "Madrid"], "paris")
        self.assertEqual(cleaned["answer_index"], 1)

    def test_validate_mcq_rejects_duplicates_and_bad_answer(self):
        with self.assertRaises(ValueError):
            validate_mcq("Pick one?", ["same", "same", "c", "d"], "A")
        with self.assertRaises(ValueError):
            validate_mcq("Pick one?", ["a", "b", "c", "d"], "Z")

    def test_validate_tf_and_open(self):
        self.assertTrue(validate_tf("Sky blue?", "true")["answer"])
        self.assertFalse(validate_tf("Sky blue?", "no")["answer"])
        with self.assertRaises(ValueError):
            validate_tf("Sky blue?", "maybe")
        cleaned = validate_open("Ocean?", "Pacific Ocean", ["Pacific"])
        self.assertEqual(cleaned["alternates"], ["Pacific"])
        with self.assertRaises(ValueError):
            validate_open("Ocean?", "")


class CheckAnswerTests(unittest.TestCase):
    def test_mc_letter_and_full_text(self):
        q = validate_mcq(
            "Capital of France?",
            ["London", "Paris", "Rome", "Madrid"],
            "B",
        )
        self.assertTrue(check_mc_answer(q, "B"))
        self.assertTrue(check_mc_answer(q, "b"))
        self.assertTrue(check_mc_answer(q, "Paris"))
        self.assertTrue(check_mc_answer(q, "paris!!!"))
        self.assertFalse(check_mc_answer(q, "A"))
        self.assertFalse(check_mc_answer(q, "London"))

    def test_tf_synonyms(self):
        q = {"qtype": "true_false", "answer": True}
        self.assertTrue(check_tf_answer(q, "true"))
        self.assertTrue(check_tf_answer(q, "T"))
        self.assertTrue(check_tf_answer(q, "yes"))
        self.assertFalse(check_tf_answer(q, "false"))
        q2 = {"qtype": "true_false", "answer": False}
        self.assertTrue(check_tf_answer(q2, "false"))
        self.assertTrue(check_tf_answer(q2, "n"))

    def test_open_exact_alternate_and_typo(self):
        q = {"qtype": "open", "answer": "Pacific Ocean", "alternates": ["Pacific"]}
        self.assertTrue(check_open_answer(q, "Pacific Ocean"))
        self.assertTrue(check_open_answer(q, "pacific"))
        self.assertTrue(check_open_answer(q, "Pacfic Ocean"))  # minor typo
        self.assertFalse(check_open_answer(q, "Atlantic"))
        self.assertFalse(check_open_answer(q, ""))

    def test_dispatch(self):
        mc = validate_mcq("Pick one?", ["a", "b", "c", "d"], "A")
        self.assertTrue(check_answer(mc, "a"))
        tf = {"qtype": "true_false", "answer": True}
        self.assertTrue(check_answer(tf, "yes"))
        op = {"qtype": "open", "answer": "piano"}
        self.assertTrue(check_answer(op, "Piano!"))
        self.assertFalse(check_answer({"qtype": "bogus"}, "x"))

    def test_format_correct_answer(self):
        mc = validate_mcq("Pick one?", ["London", "Paris", "Rome", "Madrid"], "B")
        self.assertIn("Paris", format_correct_answer(mc))
        self.assertEqual(format_correct_answer({"qtype": "true_false", "answer": True}), "True")
        self.assertEqual(
            format_correct_answer({"qtype": "open", "answer": "piano"}), "piano"
        )


class PickTests(unittest.TestCase):
    def test_pick_shuffles_and_limits(self):
        questions = [{"id": i} for i in range(20)]
        picked = pick_game_questions(questions, 5, rng=random.Random(0))
        self.assertEqual(len(picked), 5)
        # Input not mutated in order.
        self.assertEqual([q["id"] for q in questions], list(range(20)))

    def test_seed_has_five_of_each(self):
        kinds = [q["qtype"] for q in SEED_QUESTIONS]
        self.assertEqual(kinds.count("multiple_choice"), 5)
        self.assertEqual(kinds.count("true_false"), 5)
        self.assertEqual(kinds.count("open"), 5)
        # Every seed validates.
        for seed in SEED_QUESTIONS:
            if seed["qtype"] == "multiple_choice":
                validate_mcq(seed["question"], seed["options"], seed["answer"])
            elif seed["qtype"] == "true_false":
                validate_tf(seed["question"], seed["answer"])
            else:
                validate_open(seed["question"], seed["answer"], seed.get("alternates", []))


if __name__ == "__main__":
    unittest.main()
