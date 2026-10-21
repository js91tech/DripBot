import os
import random
import tempfile
import unittest
from types import SimpleNamespace

from engine.database import Database
from trivia import (
    BUSY,
    EXAMPLE_QUESTIONS,
    ADMIN_HELP_TEXT,
    HELP_TEXT,
    NONE_RUNNING,
    PLAYER_HELP_TEXT,
    PUBLIC_HELP_TEXT,
    help_text,
    MAX_BANK,
    TriviaError,
    TriviaSession,
    bank_summary,
    build_round,
    chat_should_stay_quiet,
    empty_bank_message,
    find_duplicate,
    format_answer,
    judge,
    kind_counts,
    parse_round_count,
    parse_trivia_add,
    question_card,
    should_cancel_task,
    start_announcement,
    validate_question,
)


class TriviaParseTests(unittest.TestCase):
    def test_multiple_choice_letter_answer(self):
        parsed = parse_trivia_add(
            "mc What is the capital of France? | Paris | London | Berlin | Madrid | a"
        )
        self.assertEqual(parsed["kind"], "multiple_choice")
        self.assertEqual(parsed["choices"], ["Paris", "London", "Berlin", "Madrid"])
        self.assertEqual(parsed["answer"], "Paris")

    def test_multiple_choice_text_answer(self):
        parsed = parse_trivia_add(
            "mc Which planet is known as the Red Planet? | Venus | Mars | Jupiter | mars"
        )
        self.assertEqual(parsed["answer"], "Mars")

    def test_true_false_and_open(self):
        tf = parse_trivia_add("tf Octopuses have three hearts | TRUE")
        self.assertEqual(tf["kind"], "true_false")
        self.assertEqual(tf["answer"], "true")
        opened = parse_trivia_add(
            "open Who wrote Romeo and Juliet? | Shakespeare | William Shakespeare"
        )
        self.assertEqual(opened["kind"], "open")
        self.assertEqual(opened["answer"], "Shakespeare")
        self.assertEqual(opened["accepted"], ["William Shakespeare"])

    def test_rejects_bad_shapes(self):
        with self.assertRaises(TriviaError):
            parse_trivia_add("essay What is a question without a type? | nope")
        with self.assertRaises(TriviaError):
            parse_trivia_add("mc What color is the sky today? | blue | blue | red | a")
        with self.assertRaises(TriviaError):
            parse_trivia_add("tf Is this a statement long enough | maybe")
        with self.assertRaises(TriviaError):
            parse_trivia_add("open hi | x")

    def test_strips_everyone_mention(self):
        parsed = parse_trivia_add("open What should we never ping here?? | @everyone")
        self.assertNotIn("@everyone", parsed["answer"])
        self.assertIn("everyone", parsed["answer"])
        ping = parse_trivia_add("open Who should this question never ping? | <@123>")
        self.assertNotIn("<@123>", ping["answer"])


class TriviaGradeTests(unittest.TestCase):
    def _kind(self, kind):
        return next(question for question in EXAMPLE_QUESTIONS if question["kind"] == kind)

    def test_example_pack_shape(self):
        self.assertEqual(len(EXAMPLE_QUESTIONS), 15)
        self.assertEqual(kind_counts(EXAMPLE_QUESTIONS), {
            "multiple_choice": 5,
            "true_false": 5,
            "open": 5,
        })
        self.assertLess(len(HELP_TEXT), 1900)
        self.assertLess(len(help_text(True)), 1900)
        self.assertLess(len(PUBLIC_HELP_TEXT), 1900)
        self.assertIn("!trivia add mc", ADMIN_HELP_TEXT)
        self.assertIn("!trivia add tf", ADMIN_HELP_TEXT)
        self.assertIn("!trivia add open", ADMIN_HELP_TEXT)
        self.assertIn("Paris | London | Berlin | Madrid", ADMIN_HELP_TEXT)
        self.assertIn("Also accept", ADMIN_HELP_TEXT)
        self.assertIn("loadexamples", ADMIN_HELP_TEXT)
        self.assertIn("/trivia help", PLAYER_HELP_TEXT)
        self.assertNotIn("!trivia", help_text(False))
        for public_text in (
            PUBLIC_HELP_TEXT,
            help_text(False),
            empty_bank_message(),
            start_announcement(10, 15, 10),
            BUSY,
            NONE_RUNNING,
        ):
            self.assertNotIn("!", public_text)
        self.assertEqual(MAX_BANK, 200)

    def test_examples_grade_their_own_answers(self):
        for question in EXAMPLE_QUESTIONS:
            self.assertIs(judge(question, question["answer"]), True)
            for extra in question["accepted"]:
                self.assertIs(judge(question, extra), True)
            if question["kind"] == "multiple_choice":
                index = question["choices"].index(question["answer"])
                self.assertIs(judge(question, chr(ord("a") + index)), True)
                wrong = "b" if index == 0 else "a"
                self.assertIs(judge(question, wrong), False)
            if question["kind"] == "true_false":
                opposite = "false" if question["answer"] == "true" else "true"
                self.assertIs(judge(question, opposite), False)

    def test_multiple_choice_forms(self):
        question = self._kind("multiple_choice")
        while question["answer"] != "Mars":
            question = next(
                item for item in EXAMPLE_QUESTIONS
                if item["kind"] == "multiple_choice" and item["answer"] == "Mars"
            )
            break
        self.assertIs(judge(question, "B"), True)
        self.assertIs(judge(question, "b)"), True)
        self.assertIs(judge(question, "answer b"), True)
        self.assertIs(judge(question, "mars"), True)
        self.assertIs(judge(question, "venus"), False)
        self.assertIsNone(judge(question, "lol"))
        self.assertIsNone(judge(question, "I have no idea"))

    def test_true_false_synonyms(self):
        question = next(item for item in EXAMPLE_QUESTIONS if item["answer"] == "true")
        self.assertIs(judge(question, "YES"), True)
        self.assertIs(judge(question, "yeah"), True)
        self.assertIs(judge(question, "nope"), False)
        self.assertIsNone(judge(question, "maybe"))

    def test_open_matching(self):
        ocean = next(item for item in EXAMPLE_QUESTIONS if "ocean" in item["question"].lower())
        gas = next(item for item in EXAMPLE_QUESTIONS if "photosynthesis" in item["question"])
        self.assertIs(judge(ocean, "the pacific ocean"), True)
        self.assertIs(judge(ocean, "Pacific"), True)
        self.assertIs(judge(gas, "CO2"), True)
        self.assertIs(judge(gas, "co 2"), True)
        self.assertIsNone(judge(ocean, "lol"))
        self.assertIs(judge(ocean, "atlantis"), False)
        self.assertIsNone(judge(ocean, "pacific " + ("blah " * 40)))

        hearts = validate_question(
            "open",
            "How many hearts does an octopus have?",
            [],
            "3",
            ["three"],
        )
        self.assertIs(judge(hearts, "three"), True)
        self.assertIs(judge(hearts, "3"), True)
        self.assertIs(judge(hearts, "three hearts are wild"), False)

    def test_open_card_hides_the_answer(self):
        for question in EXAMPLE_QUESTIONS:
            if question["kind"] != "open":
                continue
            card = question_card(question, 1, 5)
            self.assertNotIn(question["answer"].lower(), card["description"].lower())
            self.assertIn("2 points", card["footer"])
            self.assertIn("35 seconds", card["footer"])

    def test_round_mixes_kinds(self):
        selected = build_round(EXAMPLE_QUESTIONS, 6, rng=random.Random(1))
        self.assertEqual(
            [question["kind"] for question in selected],
            ["multiple_choice", "true_false", "open"] * 2,
        )
        self.assertEqual(len(build_round(EXAMPLE_QUESTIONS, None)), 10)
        self.assertEqual(len(build_round(EXAMPLE_QUESTIONS, 50)), 15)
        self.assertEqual(build_round([], 5), [])
        only_open = [question for question in EXAMPLE_QUESTIONS if question["kind"] == "open"]
        self.assertTrue(all(question["kind"] == "open" for question in build_round(only_open, 3)))

    def test_round_count_and_announcement(self):
        self.assertIsNone(parse_round_count(None))
        self.assertEqual(parse_round_count("all"), 50)
        self.assertEqual(parse_round_count("10"), 10)
        with self.assertRaises(TriviaError):
            parse_round_count("0")
        text = start_announcement(10, 15, 10)
        self.assertIn("10", text)
        self.assertIn("15 saved", text)
        short = start_announcement(8, 8, 10)
        self.assertIn("only has 8", short)

    def test_session_scores_first_correct_answer(self):
        ocean = next(item for item in EXAMPLE_QUESTIONS if "ocean" in item["question"].lower())
        planet = next(item for item in EXAMPLE_QUESTIONS if item["answer"] == "8")
        session = TriviaSession(1, 99, [ocean, planet])
        self.assertEqual(session.submit(1, "Ada", "Pacific")["status"], "closed")
        session.open_question()
        self.assertEqual(session.submit(1, "Ada", "lol")["status"], "ignore")
        self.assertEqual(session.submit(1, "Ada", "atlantis")["status"], "wrong")
        correct = session.submit(1, "Ada", "pacific ocean")
        self.assertEqual(correct["status"], "correct")
        self.assertEqual(correct["points"], 2)
        self.assertEqual(session.submit(2, "Bo", "pacific")["status"], "closed")
        session.advance()
        session.open_question()
        self.assertEqual(session.submit(2, "Bo", "b")["status"], "correct")
        board = session.leaderboard()
        self.assertEqual([row["name"] for row in board], ["Ada", "Bo"])
        self.assertEqual([row["points"] for row in board], [2, 1])

    def test_duplicate_and_quiet_chat(self):
        bank = [{"id": 4, "question": "What is the capital of France?"}]
        self.assertEqual(find_duplicate(bank, "  What is the capital of France?? ")["id"], 4)
        self.assertIsNone(find_duplicate(bank, "What is the capital of Spain?"))
        self.assertTrue(chat_should_stay_quiet("  !Trivia start", False, "!"))
        self.assertTrue(chat_should_stay_quiet("!triviaadd", False, "!"))
        self.assertFalse(chat_should_stay_quiet("! wow", False, "!"))
        self.assertFalse(chat_should_stay_quiet("hello", False, "!"))
        self.assertTrue(chat_should_stay_quiet("hello", True, "!"))
        self.assertTrue(chat_should_stay_quiet("?trivia", False, "?"))

        class Task:
            def __init__(self, finished=False):
                self.finished = finished

            def done(self):
                return self.finished

        current = Task()
        other = Task()
        self.assertFalse(should_cancel_task(current, current))
        self.assertFalse(should_cancel_task(Task(True), current))
        self.assertTrue(should_cancel_task(other, current))

    def test_answer_display_and_summary(self):
        mars = next(item for item in EXAMPLE_QUESTIONS if item["answer"] == "Mars")
        self.assertEqual(format_answer(mars), "B) Mars")
        summary = bank_summary(EXAMPLE_QUESTIONS)
        self.assertIn("15", summary)
        self.assertIn("5 multiple choice", summary)
        self.assertIn("loadexamples", empty_bank_message())


class TriviaDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "bot.db"))
        await self.db.init()

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def test_questions_round_trip_and_stay_per_server(self):
        sample = EXAMPLE_QUESTIONS[0]
        question_id = await self.db.add_trivia_question(
            10,
            sample["kind"],
            sample["question"],
            sample["choices"],
            sample["answer"],
            sample["accepted"],
            7,
        )
        other = EXAMPLE_QUESTIONS[-1]
        await self.db.add_trivia_question(
            11,
            other["kind"],
            other["question"],
            other["choices"],
            other["answer"],
            other["accepted"],
            7,
        )
        saved = await self.db.list_trivia_questions(10)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["id"], question_id)
        self.assertEqual(saved[0]["choices"], sample["choices"])
        self.assertEqual(saved[0]["answer"], sample["answer"])
        self.assertTrue(await self.db.delete_trivia_question(10, question_id))
        self.assertFalse(await self.db.delete_trivia_question(10, question_id))
        self.assertEqual(await self.db.list_trivia_questions(10), [])
        self.assertEqual(len(await self.db.list_trivia_questions(11)), 1)

        await self.db.add_trivia_question(11, "open", "What is two plus two?", [], "4", ["four"], 1)
        removed = await self.db.clear_trivia_questions(11)
        self.assertEqual(removed, 2)
        self.assertEqual(await self.db.list_trivia_questions(11), [])

    async def test_guild_wipe_removes_trivia(self):
        await self.db.add_trivia_question(5, "true_false", "Ice is solid water.", [], "true", [], 1)
        await self.db.add_trivia_question(6, "true_false", "Fire is cold to the touch.", [], "false", [], 1)
        await self.db.delete_guild_data(5)
        await self.db.queue.join()
        self.assertEqual(await self.db.list_trivia_questions(5), [])
        self.assertEqual(len(await self.db.list_trivia_questions(6)), 1)


class _Channel:
    def __init__(self):
        self.id = 42
        self.sent = []

    async def send(self, content=None, *, embed=None):
        self.sent.append((content, embed))


class _Author:
    def __init__(self, user_id, name):
        self.id = user_id
        self.display_name = name
        self.bot = False


class _Message:
    def __init__(self, channel, author, content):
        self.channel = channel
        self.author = author
        self.guild = SimpleNamespace(id=1)
        self.content = content
        self.reactions = []

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)


class TriviaRoundFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "bot.db"))
        await self.db.init()
        from cogs.trivia import Trivia

        self.cog = Trivia(SimpleNamespace(db=self.db, command_prefix="!"))
        self.channel = _Channel()

    async def asyncTearDown(self):
        self.cog.cog_unload()
        await self.db.close()
        self.tmp.cleanup()

    async def test_sample_pack_loads_once_and_a_round_can_be_won(self):
        loaded = await self.cog._load_examples(1, 9)
        self.assertIn("15", loaded)
        self.assertIn("already", await self.cog._load_examples(1, 9))
        summary = await self.cog._summary(1)
        self.assertIn("5 multiple choice", summary)
        self.assertIn("5 true/false", summary)
        self.assertIn("5 open ended", summary)

        async def announce(text):
            await self.channel.send(text)

        await self.cog._begin(self.channel, 1, 5, 1, announce)
        session = self.cog.sessions[self.channel.id]
        question = session.current()
        wrong = _Message(self.channel, _Author(3, "Ada"), "zzzznotananswer")
        await self.cog._grade_message(wrong)
        answer = _Message(self.channel, _Author(3, "Ada"), question["answer"])
        await self.cog._grade_message(answer)

        self.assertNotIn(self.channel.id, self.cog.sessions)
        texts = [content for content, _embed in self.channel.sent if content]
        self.assertTrue(any("got it" in text for text in texts))
        self.assertTrue(any("Trivia over" in text for text in texts))
        self.assertIn("Ada", texts[-1])


class TriviaCommandRegistrationTests(unittest.TestCase):
    def test_prefix_and_slash_commands_register(self):
        import discord
        from discord.ext import commands

        from cogs.trivia import Trivia

        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        cog = Trivia(bot)
        self.assertEqual({command.name for command in cog.get_commands()}, {"trivia", "help"})
        prefix = {command.name for command in cog.trivia.walk_commands()}
        self.assertTrue({"start", "add", "loadexamples", "clear", "list"} <= prefix)

        app_commands = cog.get_app_commands()
        app_names = {command.name for command in app_commands}
        self.assertEqual(app_names, {"trivia", "help"})
        trivia_group = next(command for command in app_commands if command.name == "trivia")
        slash_commands = list(trivia_group.walk_commands())
        slash_names = {command.name for command in slash_commands}
        self.assertTrue({"start", "add", "loadexamples", "remove"} <= slash_names)
        self.assertLessEqual(len(slash_commands), 25)
        for command in slash_commands:
            self.assertLessEqual(len(command.description), 100)
            self.assertLessEqual(len(command.parameters), 25)
            for param in command.parameters:
                choices = getattr(param, "choices", None) or []
                self.assertLessEqual(len(choices), 25)
                self.assertLessEqual(len(getattr(param, "description", "") or ""), 100)

        with open("cogs/chat.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("chat_should_stay_quiet", source)
        with open("bot.py", encoding="utf-8") as handle:
            bot_source = handle.read()
        self.assertIn('load_extension("cogs.trivia")', bot_source)
        self.assertIn("message.delete()", bot_source)
        self.assertNotIn("PrivatePrefixContext", bot_source)


if __name__ == "__main__":
    unittest.main()
