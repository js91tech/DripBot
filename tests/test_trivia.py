"""
tests/test_trivia.py — Comprehensive tests for Trivia Mode
Verifies Question Bank, Answer Checking, TriviaManager, Database, and Session logic.
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from engine.database import Database
from engine.trivia import (
    DEFAULT_QUESTIONS,
    MULTIPLE_CHOICE,
    OPEN_ENDED,
    TRUE_FALSE,
    TriviaManager,
    TriviaQuestion,
    TriviaSession,
    clean_text,
    normalize_question_type,
)
from cogs.trivia import TriviaCog, is_admin


class TriviaDefaultQuestionsTests(unittest.TestCase):
    def test_default_question_counts(self):
        """Verify the exact requested distribution: 5 MC, 5 TF, 5 Open-Ended."""
        self.assertEqual(len(DEFAULT_QUESTIONS), 15)

        mc = [q for q in DEFAULT_QUESTIONS if q.question_type == MULTIPLE_CHOICE]
        tf = [q for q in DEFAULT_QUESTIONS if q.question_type == TRUE_FALSE]
        op = [q for q in DEFAULT_QUESTIONS if q.question_type == OPEN_ENDED]

        self.assertEqual(len(mc), 5, "Must have exactly 5 multiple choice questions")
        self.assertEqual(len(tf), 5, "Must have exactly 5 true/false questions")
        self.assertEqual(len(op), 5, "Must have exactly 5 open-ended questions")

    def test_default_questions_structure(self):
        """Ensure all default questions have valid content and answers."""
        for q in DEFAULT_QUESTIONS:
            self.assertTrue(len(q.question) > 5)
            self.assertTrue(q.is_default)
            self.assertTrue(bool(q.correct_answer))

            if q.question_type == MULTIPLE_CHOICE:
                self.assertGreaterEqual(len(q.options), 2)
                self.assertIsNotNone(q.get_correct_option_index())
            elif q.question_type == TRUE_FALSE:
                self.assertIn(q.correct_answer.lower(), {"true", "false"})
            elif q.question_type == OPEN_ENDED:
                self.assertGreaterEqual(len(q.acceptable_answers), 1)


class TriviaAnswerCheckingTests(unittest.TestCase):
    def test_multiple_choice_checks(self):
        q = TriviaQuestion(
            question_type=MULTIPLE_CHOICE,
            question="What is the capital of France?",
            options=["Paris", "London", "Berlin", "Madrid"],
            correct_answer="Paris",
        )
        # Option text matching
        self.assertTrue(q.check_answer("Paris"))
        self.assertTrue(q.check_answer("paris"))
        self.assertTrue(q.check_answer("  paris  "))

        # Letter matching
        self.assertTrue(q.check_answer("A"))
        self.assertTrue(q.check_answer("a"))
        self.assertTrue(q.check_answer("a)"))
        self.assertTrue(q.check_answer("A. Paris"))

        # Number matching (1-based)
        self.assertTrue(q.check_answer("1"))

        # Incorrect answers
        self.assertFalse(q.check_answer("B"))
        self.assertFalse(q.check_answer("London"))
        self.assertFalse(q.check_answer("Rome"))
        self.assertFalse(q.check_answer(""))

    def test_true_false_checks(self):
        q_true = TriviaQuestion(
            question_type=TRUE_FALSE,
            question="Sound travels faster in water than in air.",
            options=["True", "False"],
            correct_answer="True",
        )
        self.assertTrue(q_true.check_answer("True"))
        self.assertTrue(q_true.check_answer("true"))
        self.assertTrue(q_true.check_answer("t"))
        self.assertTrue(q_true.check_answer("yes"))
        self.assertTrue(q_true.check_answer("1"))

        self.assertFalse(q_true.check_answer("False"))
        self.assertFalse(q_true.check_answer("f"))
        self.assertFalse(q_true.check_answer("no"))
        self.assertFalse(q_true.check_answer("maybe"))

        q_false = TriviaQuestion(
            question_type=TRUE_FALSE,
            question="Sharks are mammals.",
            options=["True", "False"],
            correct_answer="False",
        )
        self.assertTrue(q_false.check_answer("False"))
        self.assertTrue(q_false.check_answer("false"))
        self.assertTrue(q_false.check_answer("f"))
        self.assertTrue(q_false.check_answer("no"))
        self.assertFalse(q_false.check_answer("True"))

    def test_open_ended_checks(self):
        q = TriviaQuestion(
            question_type=OPEN_ENDED,
            question="Who painted the Mona Lisa?",
            correct_answer="Leonardo da Vinci",
            acceptable_answers=["Leonardo da Vinci", "da Vinci", "Leonardo"],
        )
        # Exact and case-insensitive
        self.assertTrue(q.check_answer("Leonardo da Vinci"))
        self.assertTrue(q.check_answer("leonardo da vinci"))
        self.assertTrue(q.check_answer("da Vinci"))
        self.assertTrue(q.check_answer("leonardo"))

        # Leading articles stripped
        self.assertTrue(q.check_answer("The Leonardo da Vinci"))

        # Minor fuzzy typo matching
        self.assertTrue(q.check_answer("Lenardo da Vinci"))

        # Wrong answers
        self.assertFalse(q.check_answer("Michelangelo"))
        self.assertFalse(q.check_answer("Picasso"))

    def test_open_ended_numeric_requires_exact(self):
        q = TriviaQuestion(
            question_type=OPEN_ENDED,
            question="In what year did humans land on the moon?",
            correct_answer="1969",
            acceptable_answers=["1969", "'69"],
        )
        self.assertTrue(q.check_answer("1969"))
        self.assertTrue(q.check_answer(" 1969 "))
        self.assertFalse(q.check_answer("1968"))
        self.assertFalse(q.check_answer("1970"))


class TriviaDatabaseAndManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db = Database()
        self.db.db_path = os.path.join(self.test_dir, "test_bot.db")
        await self.db.init()
        self.manager = TriviaManager(self.db)
        self.guild_id = 123456789

    async def asyncTearDown(self):
        await self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_add_and_get_custom_questions(self):
        # 1. Add Multiple Choice
        q_mc = await self.manager.add_question(
            guild_id=self.guild_id,
            question_type=MULTIPLE_CHOICE,
            question="What is the capital of Canada?",
            options=["Ottawa", "Toronto", "Vancouver", "Montreal"],
            correct_answer="Ottawa",
            created_by=999,
        )
        self.assertIsNotNone(q_mc.id)
        self.assertEqual(q_mc.question_type, MULTIPLE_CHOICE)
        self.assertEqual(q_mc.options[0], "Ottawa")

        # 2. Add True/False
        q_tf = await self.manager.add_question(
            guild_id=self.guild_id,
            question_type=TRUE_FALSE,
            question="Bananas are berries botanically.",
            correct_answer="True",
            created_by=999,
        )
        self.assertIsNotNone(q_tf.id)
        self.assertEqual(q_tf.question_type, TRUE_FALSE)

        # 3. Add Open-Ended
        q_open = await self.manager.add_question(
            guild_id=self.guild_id,
            question_type=OPEN_ENDED,
            question="What is the largest mammal on Earth?",
            correct_answer="Blue Whale",
            acceptable_answers=["Blue Whale", "Whale"],
            created_by=999,
        )
        self.assertIsNotNone(q_open.id)
        self.assertEqual(q_open.question_type, OPEN_ENDED)

        # Retrieve all custom questions for this guild
        all_custom = await self.manager.get_questions(self.guild_id, include_defaults=False)
        self.assertEqual(len(all_custom), 3)

        # Filter by type
        mc_only = await self.manager.get_questions(self.guild_id, question_type=MULTIPLE_CHOICE)
        self.assertEqual(len(mc_only), 1)
        self.assertEqual(mc_only[0].question, "What is the capital of Canada?")

        # Include defaults
        with_defaults = await self.manager.get_questions(self.guild_id, include_defaults=True)
        self.assertEqual(len(with_defaults), 3 + 15)

    async def test_validation_errors_when_adding(self):
        # MC with fewer than 2 options
        with self.assertRaises(ValueError):
            await self.manager.add_question(
                guild_id=self.guild_id,
                question_type=MULTIPLE_CHOICE,
                question="Bad MC?",
                options=["Only One"],
                correct_answer="Only One",
            )

        # MC answer doesn't match options
        with self.assertRaises(ValueError):
            await self.manager.add_question(
                guild_id=self.guild_id,
                question_type=MULTIPLE_CHOICE,
                question="Bad MC?",
                options=["Apple", "Banana"],
                correct_answer="Orange",
            )

        # TF with invalid answer
        with self.assertRaises(ValueError):
            await self.manager.add_question(
                guild_id=self.guild_id,
                question_type=TRUE_FALSE,
                question="Bad TF?",
                correct_answer="Maybe",
            )

        # Open-ended with empty answer
        with self.assertRaises(ValueError):
            await self.manager.add_question(
                guild_id=self.guild_id,
                question_type=OPEN_ENDED,
                question="Bad Open?",
                correct_answer="",
            )

    async def test_delete_and_clear_questions(self):
        q = await self.manager.add_question(
            guild_id=self.guild_id,
            question_type=TRUE_FALSE,
            question="Spiders have 8 legs.",
            correct_answer="True",
        )
        q_id = q.id

        # Delete single question
        deleted = await self.manager.delete_question(self.guild_id, q_id)
        self.assertTrue(deleted)

        remaining = await self.manager.get_questions(self.guild_id)
        self.assertEqual(len(remaining), 0)

        # Add two and clear
        await self.manager.add_question(
            guild_id=self.guild_id,
            question_type=TRUE_FALSE,
            question="Q1?",
            correct_answer="True",
        )
        await self.manager.add_question(
            guild_id=self.guild_id,
            question_type=TRUE_FALSE,
            question="Q2?",
            correct_answer="False",
        )
        cleared_count = await self.manager.clear_questions(self.guild_id)
        self.assertEqual(cleared_count, 2)
        self.assertEqual(len(await self.manager.get_questions(self.guild_id)), 0)

    async def test_trivia_leaderboard_tracking(self):
        # Update scores
        await self.db.update_trivia_score(self.guild_id, user_id=101, points=30, correct_answers=3, games_played=1)
        await self.db.update_trivia_score(self.guild_id, user_id=102, points=10, correct_answers=1, games_played=1)
        await self.db.update_trivia_score(self.guild_id, user_id=101, points=20, correct_answers=2, games_played=1)

        board = await self.manager.get_leaderboard(self.guild_id)
        self.assertEqual(len(board), 2)
        # User 101 should be #1 with 50 points
        self.assertEqual(board[0]["user_id"], 101)
        self.assertEqual(board[0]["points"], 50)
        self.assertEqual(board[0]["correct_answers"], 5)
        self.assertEqual(board[0]["games_played"], 2)

        # User 102 should be #2 with 10 points
        self.assertEqual(board[1]["user_id"], 102)
        self.assertEqual(board[1]["points"], 10)


class TriviaSessionTests(unittest.TestCase):
    def test_session_lifecycle(self):
        questions = DEFAULT_QUESTIONS[:3]
        session = TriviaSession(
            guild_id=123,
            channel_id=456,
            questions=questions,
            timeout_seconds=30,
            points_per_question=10,
        )

        self.assertEqual(session.current_index, 0)
        self.assertEqual(session.total_questions, 3)
        self.assertFalse(session.is_finished())

        # Q1 answered correctly by User A
        pts = session.record_correct_answer(user_id=1, user_name="Alice")
        self.assertGreaterEqual(pts, 10)
        self.assertTrue(session.question_answered)
        self.assertEqual(session.winner_id, 1)

        # Advance to Q2
        session.advance_to_next_question()
        self.assertEqual(session.current_index, 1)
        self.assertFalse(session.question_answered)

        # Q2 timed out
        session.record_timeout()
        self.assertTrue(session.question_answered)
        self.assertIsNone(session.winner_id)

        # Advance to Q3
        session.advance_to_next_question()
        self.assertEqual(session.current_index, 2)
        session.record_correct_answer(user_id=2, user_name="Bob")

        # Advance past end
        session.advance_to_next_question()
        self.assertTrue(session.is_finished())

        standings = session.get_standings()
        self.assertEqual(len(standings), 2)
        # Alice and Bob both have points
        self.assertIn(standings[0][0], {1, 2})


class TriviaCogPermissionsAndChatTests(unittest.IsolatedAsyncioTestCase):
    def test_is_admin_check(self):
        # Admin member
        admin_member = MagicMock(spec=discord.Member)
        admin_member.guild_permissions.administrator = True
        admin_member.guild_permissions.manage_guild = True
        admin_member.guild_permissions.manage_channels = True
        self.assertTrue(is_admin(admin_member))

        # Manage Guild member
        mgr_member = MagicMock(spec=discord.Member)
        mgr_member.guild_permissions.administrator = False
        mgr_member.guild_permissions.manage_guild = True
        mgr_member.guild_permissions.manage_channels = False
        self.assertTrue(is_admin(mgr_member))

        # Regular user
        reg_member = MagicMock(spec=discord.Member)
        reg_member.guild_permissions.administrator = False
        reg_member.guild_permissions.manage_guild = False
        reg_member.guild_permissions.manage_channels = False
        reg_member.guild.owner_id = 999
        reg_member.id = 111
        self.assertFalse(is_admin(reg_member))

        # Guild owner
        owner_member = MagicMock(spec=discord.Member)
        owner_member.guild_permissions.administrator = False
        owner_member.guild_permissions.manage_guild = False
        owner_member.guild_permissions.manage_channels = False
        owner_member.guild.owner_id = 999
        owner_member.id = 999
        self.assertTrue(is_admin(owner_member))

    async def test_on_message_evaluates_trivia_answer(self):
        db = MagicMock()
        bot = MagicMock()
        cog = TriviaCog(bot, db)

        # Create active session in channel 100
        q = TriviaQuestion(
            question_type=OPEN_ENDED,
            question="Chemical symbol for gold?",
            correct_answer="Au",
            acceptable_answers=["Au", "gold"],
        )
        session = TriviaSession(
            guild_id=1,
            channel_id=100,
            questions=[q],
        )
        cog.manager.active_sessions[100] = session

        # Simulate user typing "Au"
        message = MagicMock(spec=discord.Message)
        message.author.bot = False
        message.author.id = 555
        message.author.display_name = "PlayerOne"
        message.author.mention = "<@555>"
        message.guild.id = 1
        message.channel.id = 100
        message.channel.send = AsyncMock()
        message.add_reaction = AsyncMock()
        message.content = "Au"

        await cog.on_message(message)

        # Should record correct answer
        self.assertTrue(session.question_answered)
        self.assertEqual(session.winner_id, 555)
        message.channel.send.assert_called_once()
        sent_text = message.channel.send.call_args[0][0]
        self.assertIn("<@555>", sent_text)
        self.assertIn("got it right", sent_text)

    async def test_button_answer_handling(self):
        db = MagicMock()
        bot = MagicMock()
        cog = TriviaCog(bot, db)

        q = TriviaQuestion(
            question_type=MULTIPLE_CHOICE,
            question="Which planet is the Red Planet?",
            options=["Mars", "Venus", "Jupiter", "Mercury"],
            correct_answer="Mars",
        )
        session = TriviaSession(
            guild_id=1,
            channel_id=200,
            questions=[q],
        )
        cog.manager.active_sessions[200] = session

        # Incorrect button click
        interaction_bad = MagicMock(spec=discord.Interaction)
        interaction_bad.channel_id = 200
        interaction_bad.user.id = 777
        interaction_bad.user.display_name = "PlayerBad"
        interaction_bad.response.send_message = AsyncMock()

        await cog._handle_button_answer(interaction_bad, "B", "Venus")
        self.assertFalse(session.question_answered)
        interaction_bad.response.send_message.assert_called_once()
        self.assertIn("incorrect", interaction_bad.response.send_message.call_args[0][0].lower())

        # Correct button click
        interaction_good = MagicMock(spec=discord.Interaction)
        interaction_good.channel_id = 200
        interaction_good.user.id = 888
        interaction_good.user.display_name = "PlayerGood"
        interaction_good.user.mention = "<@888>"
        interaction_good.channel.send = AsyncMock()
        interaction_good.response.defer = AsyncMock()

        await cog._handle_button_answer(interaction_good, "A", "Mars")
        self.assertTrue(session.question_answered)
        self.assertEqual(session.winner_id, 888)
        interaction_good.channel.send.assert_called_once()
        self.assertIn("<@888>", interaction_good.channel.send.call_args[0][0])

    async def test_trivia_channel_skips_ambient_llm(self):
        from cogs.chat import Chat

        bot = MagicMock()
        db = MagicMock()
        sm = MagicMock()
        sm.get_settings = AsyncMock(return_value={"response_enabled": True, "response_chance": 1.0})

        trivia_mgr = MagicMock()
        trivia_mgr.is_channel_in_trivia.return_value = True
        bot.trivia_manager = trivia_mgr

        chat_cog = Chat(bot, db, sm)
        # Mock direct address to return False (ambient chatter)
        chat_cog._is_direct_address = MagicMock(return_value=(False, False, False))

        message = MagicMock(spec=discord.Message)
        message.author.bot = False
        message.guild.id = 1
        message.channel.id = 12345
        message.content = "random trivia guess"

        with patch.object(chat_cog, "_try_send_reply", new_callable=AsyncMock) as mock_reply:
            await chat_cog.on_message(message)
            # Should have returned early and NOT attempted any reply
            mock_reply.assert_not_called()

    async def test_prefix_add_and_list_commands(self):
        db = Database()
        test_dir = tempfile.mkdtemp()
        db.db_path = os.path.join(test_dir, "test_prefix.db")
        await db.init()

        bot = MagicMock()
        cog = TriviaCog(bot, db)

        # Context mock for admin
        ctx = MagicMock()
        ctx.guild.id = 555
        ctx.guild.name = "Test Guild"
        ctx.channel.id = 10
        ctx.author = MagicMock(spec=discord.Member)
        ctx.author.id = 123
        ctx.author.guild_permissions.administrator = True
        ctx.author.guild = ctx.guild
        ctx.send = AsyncMock()

        # Add MC
        await cog.cmd_add.callback(cog, ctx, "mc", "Which is hottest? | Venus, Mars, Mercury, Neptune | Venus")
        ctx.send.assert_called_once()
        self.assertIn("Added Multiple Choice Question", ctx.send.call_args[0][0])
        ctx.send.reset_mock()

        # Add TF
        await cog.cmd_add.callback(cog, ctx, "tf", "Water boils at 100C at sea level. | True")
        self.assertIn("Added True/False Question", ctx.send.call_args[0][0])
        ctx.send.reset_mock()

        # Add Open
        await cog.cmd_add.callback(cog, ctx, "open", "Capital of Germany? | Berlin | berlin")
        self.assertIn("Added Open-Ended Question", ctx.send.call_args[0][0])
        ctx.send.reset_mock()

        # List
        await cog.cmd_list.callback(cog, ctx)
        self.assertEqual(ctx.send.call_args[1]["embed"].title, "📋 Server Trivia Questions (3 custom)")
        ctx.send.reset_mock()

        # Defaults
        await cog.cmd_defaults.callback(cog, ctx)
        self.assertIn("Built-in Default Trivia Questions", ctx.send.call_args[1]["embed"].title)
        ctx.send.reset_mock()

        # Status
        await cog.cmd_status.callback(cog, ctx)
        self.assertEqual(ctx.send.call_args[1]["embed"].title, "🧠 Trivia Mode Status")
        ctx.send.reset_mock()

        # Non-admin rejection
        non_admin_ctx = MagicMock()
        non_admin_ctx.author = MagicMock(spec=discord.Member)
        non_admin_ctx.author.guild_permissions.administrator = False
        non_admin_ctx.author.guild_permissions.manage_guild = False
        non_admin_ctx.author.guild_permissions.manage_channels = False
        non_admin_ctx.author.guild.owner_id = 999
        non_admin_ctx.author.id = 888
        non_admin_ctx.send = AsyncMock()

        await cog.cmd_add.callback(cog, non_admin_ctx, "mc", "Q | A, B | A")
        self.assertIn("Only server administrators", non_admin_ctx.send.call_args[0][0])
        non_admin_ctx.send.reset_mock()

        await cog.cmd_clear.callback(cog, non_admin_ctx)
        self.assertIn("Only server administrators", non_admin_ctx.send.call_args[0][0])

        await db.close()
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
