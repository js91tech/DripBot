import os
import tempfile
import unittest

from cogs.trivia import answer_is_correct, normalize_answer, prepare_question
from engine.database import Database


class TriviaQuestionTests(unittest.TestCase):
    def test_multiple_choice_requires_answer_in_options(self):
        question, answer, options = prepare_question(
            "multiple_choice",
            "Which planet is known as the Red Planet?",
            "mars",
            "Earth, Mars, Venus, Jupiter",
        )
        self.assertEqual(question, "Which planet is known as the Red Planet?")
        self.assertEqual(answer, "Mars")
        self.assertEqual(options, ["Earth", "Mars", "Venus", "Jupiter"])

        with self.assertRaisesRegex(ValueError, "match one of the options"):
            prepare_question("multiple_choice", "Question?", "Saturn", "Earth, Mars")

    def test_true_false_validation(self):
        _, answer, options = prepare_question(
            "true_false", "The Earth orbits the Sun.", "TRUE"
        )
        self.assertEqual(answer, "True")
        self.assertEqual(options, [])

        with self.assertRaisesRegex(ValueError, "true` or `false"):
            prepare_question("true_false", "Question?", "maybe")

    def test_open_ended_accepts_alternative_spellings(self):
        _, answer, _ = prepare_question(
            "open_ended", "Who painted the Mona Lisa?", "Leonardo da Vinci|Da Vinci"
        )
        question = {"answer": answer}
        self.assertTrue(answer_is_correct(question, "Leonardo da Vinci!"))
        self.assertTrue(answer_is_correct(question, "da vinci"))
        self.assertFalse(answer_is_correct(question, "Michelangelo"))

    def test_normalize_answer_ignores_case_and_punctuation(self):
        self.assertEqual(normalize_answer("  Hello, World! "), "hello world")


class TriviaDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database()
        self.db.db_path = os.path.join(self.temp_dir.name, "trivia.db")
        await self.db.init()

    async def asyncTearDown(self):
        await self.db.close()
        self.temp_dir.cleanup()

    async def test_questions_are_scoped_to_guild_and_deletable(self):
        question_id = await self.db.add_trivia_question(
            10,
            "multiple_choice",
            "What is 2 + 2?",
            "4",
            ["3", "4", "5"],
            99,
        )
        await self.db.add_trivia_question(
            20,
            "true_false",
            "Water is wet.",
            "True",
            [],
            88,
        )

        guild_questions = await self.db.get_trivia_questions(10)
        self.assertEqual(len(guild_questions), 1)
        self.assertEqual(guild_questions[0]["id"], question_id)
        self.assertEqual(guild_questions[0]["options"], ["3", "4", "5"])

        self.assertTrue(await self.db.delete_trivia_question(10, question_id))
        self.assertFalse(await self.db.delete_trivia_question(10, question_id))
        self.assertEqual(await self.db.get_trivia_questions(10), [])


if __name__ == "__main__":
    unittest.main()
