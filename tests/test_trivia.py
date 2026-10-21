import asyncio
import random
import unittest

import aiosqlite

from engine.trivia import (
    MULTIPLE_CHOICE,
    OPEN_ENDED,
    TRUE_FALSE,
    TriviaError,
    TriviaStore,
    build_multiple_choice,
    build_open_ended,
    build_true_false,
    check_open_answer,
    normalize_answer,
    pick_questions,
)


class AnswerCheckTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_answer("  The Eiffel   Tower! "), "eiffel tower")
        self.assertEqual(normalize_answer("Café"), "cafe")

    def test_exact_and_alt(self):
        self.assertTrue(check_open_answer("paris", "Paris"))
        self.assertTrue(check_open_answer("NYC", "New York", ["nyc", "new york city"]))
        self.assertFalse(check_open_answer("london", "Paris"))
        self.assertFalse(check_open_answer("", "Paris"))

    def test_typo_tolerance_only_for_longer_answers(self):
        self.assertTrue(check_open_answer("Mississipi", "Mississippi"))
        self.assertFalse(check_open_answer("cot", "cat"))
        self.assertFalse(check_open_answer("Rome", "Rose"))


class BuilderTests(unittest.TestCase):
    def test_multiple_choice(self):
        data = build_multiple_choice("Q?", "A", ["B", "C", None])
        self.assertEqual(data["choices"], ["A", "B", "C"])
        self.assertEqual(data["answer"], "A")

    def test_multiple_choice_validation(self):
        with self.assertRaises(TriviaError):
            build_multiple_choice("Q?", "A", [None, ""])
        with self.assertRaises(TriviaError):
            build_multiple_choice("Q?", "A", ["a"])
        with self.assertRaises(TriviaError):
            build_multiple_choice("Q?", "A", ["B", "C", "D", "E"])
        with self.assertRaises(TriviaError):
            build_multiple_choice("", "A", ["B"])

    def test_true_false_and_open(self):
        self.assertEqual(build_true_false("Q", True)["answer"], "True")
        self.assertEqual(build_true_false("Q", False)["answer"], "False")
        data = build_open_ended("Q", "Paris", "city of light, paname")
        self.assertEqual(data["alt_answers"], ["city of light", "paname"])


class StoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await aiosqlite.connect(":memory:")
        self.store = TriviaStore(self.conn)
        await self.store.ensure_schema()

    async def asyncTearDown(self):
        await self.conn.close()

    async def test_add_list_remove_scoped_by_guild(self):
        q = await self.store.add_question(1, 99, build_true_false("Sky is blue", True))
        await self.store.add_question(2, 99, build_open_ended("Capital of France?", "Paris"))
        self.assertEqual([x.id for x in await self.store.list_questions(1)], [q.id])
        self.assertFalse(await self.store.remove_question(2, q.id))
        self.assertTrue(await self.store.remove_question(1, q.id))
        self.assertEqual(await self.store.list_questions(1), [])

    async def test_roundtrip_and_counts(self):
        await self.store.add_question(1, 5, build_multiple_choice("Q", "A", ["B", "C"]))
        await self.store.add_question(1, 5, build_open_ended("Q2", "X", "y"))
        mc = (await self.store.list_questions(1, MULTIPLE_CHOICE))[0]
        self.assertEqual(mc.choices, ["A", "B", "C"])
        op = (await self.store.list_questions(1, OPEN_ENDED))[0]
        self.assertEqual(op.alt_answers, ["y"])
        counts = await self.store.count_by_type(1)
        self.assertEqual(counts, {MULTIPLE_CHOICE: 1, TRUE_FALSE: 0, OPEN_ENDED: 1})
        self.assertEqual(await self.store.clear_questions(1, OPEN_ENDED), 1)

    async def test_pick_questions_5_5_5(self):
        for i in range(7):
            await self.store.add_question(1, 5, build_multiple_choice(f"mc{i}", "A", ["B"]))
        for i in range(5):
            await self.store.add_question(1, 5, build_true_false(f"tf{i}", True))
        for i in range(2):
            await self.store.add_question(1, 5, build_open_ended(f"op{i}", "x"))
        pool = await self.store.list_questions(1)
        picked = pick_questions(
            pool, {MULTIPLE_CHOICE: 5, TRUE_FALSE: 5, OPEN_ENDED: 5}, random.Random(1)
        )
        kinds = [q.qtype for q in picked]
        self.assertEqual(kinds.count(MULTIPLE_CHOICE), 5)
        self.assertEqual(kinds.count(TRUE_FALSE), 5)
        self.assertEqual(kinds.count(OPEN_ENDED), 2)
        self.assertEqual(kinds, sorted(kinds, key=[MULTIPLE_CHOICE, TRUE_FALSE, OPEN_ENDED].index))

    async def test_leaderboard_accumulates(self):
        await self.store.record_game(1, {10: (3, 2), 11: (1, 1)})
        await self.store.record_game(1, {10: (2, 1)})
        rows = await self.store.leaderboard(1)
        self.assertEqual(rows[0], (10, 5, 3, 2))
        self.assertEqual(rows[1], (11, 1, 1, 1))


if __name__ == "__main__":
    unittest.main()
