"""
Trivia mode.

Admins build a question bank per server with /triviaadmin (multiple choice,
true/false, open ended). Anyone can run a round with /trivia start; by default
a round is 5 multiple choice, 5 true/false and 5 open ended questions.
"""

import asyncio
import logging
import random
import time
from typing import Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from engine.trivia import (
    MAX_CHOICES,
    MULTIPLE_CHOICE,
    OPEN_ENDED,
    QUESTION_TYPES,
    TRUE_FALSE,
    TYPE_LABELS,
    TriviaError,
    TriviaQuestion,
    TriviaStore,
    build_multiple_choice,
    build_open_ended,
    build_true_false,
    check_open_answer,
    pick_questions,
)

logger = logging.getLogger("dripsletongue.cog.trivia")

DEFAULT_COUNTS = {MULTIPLE_CHOICE: 5, TRUE_FALSE: 5, OPEN_ENDED: 5}
BUTTON_QUESTION_SECONDS = 20
OPEN_QUESTION_SECONDS = 30
POINTS = {MULTIPLE_CHOICE: 1, TRUE_FALSE: 1, OPEN_ENDED: 2}
MAX_PER_TYPE = 20
CHOICE_LETTERS = "ABCD"
EMBED_COLOR = 0x5865F2


def is_trivia_admin(member) -> bool:
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


class AnswerView(discord.ui.View):
    """Buttons for multiple choice / true-false. Each player gets one answer."""

    def __init__(self, labels: List[str], timeout: float):
        super().__init__(timeout=timeout)
        self.answers: Dict[int, int] = {}
        for index, label in enumerate(labels):
            self.add_item(AnswerButton(index, label))


class AnswerButton(discord.ui.Button):
    def __init__(self, index: int, label: str):
        super().__init__(label=label[:80], style=discord.ButtonStyle.primary)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: AnswerView = self.view
        if interaction.user.id in view.answers:
            await interaction.response.send_message(
                "You already locked in an answer for this one.", ephemeral=True
            )
            return
        view.answers[interaction.user.id] = self.index
        await interaction.response.send_message(
            f"Locked in **{self.label}**.", ephemeral=True
        )


class TriviaGame:
    def __init__(self, channel, starter_id: int, questions: List[TriviaQuestion]):
        self.channel = channel
        self.starter_id = starter_id
        self.questions = questions
        self.points: Dict[int, int] = {}
        self.correct: Dict[int, int] = {}
        self.task: Optional[asyncio.Task] = None

    def award(self, user_id: int, qtype: str):
        self.points[user_id] = self.points.get(user_id, 0) + POINTS[qtype]
        self.correct[user_id] = self.correct.get(user_id, 0) + 1


class TriviaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.store: Optional[TriviaStore] = None
        self.games: Dict[int, TriviaGame] = {}

    async def cog_load(self):
        self.store = TriviaStore(self.bot.db.conn)
        await self.store.ensure_schema()

    async def cog_unload(self):
        for game in list(self.games.values()):
            if game.task:
                game.task.cancel()

    def is_active(self, channel_id: int) -> bool:
        """True while a round is running in the channel (the chat cog stays quiet)."""
        return channel_id in self.games

    @staticmethod
    async def _require_admin(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Trivia only works in a server.", ephemeral=True
            )
            return False
        if not is_trivia_admin(interaction.user):
            await interaction.response.send_message(
                "Only admins (Manage Server or Administrator) can manage trivia questions.",
                ephemeral=True,
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Admin commands: /triviaadmin ...
    # ------------------------------------------------------------------

    admin = app_commands.Group(
        name="triviaadmin",
        description="Manage this server's trivia questions (admins only)",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    async def _save(self, interaction: discord.Interaction, data: dict):
        question = await self.store.add_question(
            interaction.guild.id, interaction.user.id, data
        )
        counts = await self.store.count_by_type(interaction.guild.id)
        await interaction.response.send_message(
            f"Added {TYPE_LABELS[question.qtype]} question **#{question.id}**.\n"
            f"Bank: {counts[MULTIPLE_CHOICE]} multiple choice, "
            f"{counts[TRUE_FALSE]} true/false, {counts[OPEN_ENDED]} open ended.",
            ephemeral=True,
        )

    @admin.command(name="add_mc", description="Add a multiple choice question")
    @app_commands.describe(
        question="The question",
        correct="The correct answer",
        wrong1="A wrong answer",
        wrong2="Another wrong answer (optional)",
        wrong3="Another wrong answer (optional)",
    )
    async def add_mc(
        self,
        interaction: discord.Interaction,
        question: str,
        correct: str,
        wrong1: str,
        wrong2: Optional[str] = None,
        wrong3: Optional[str] = None,
    ):
        if not await self._require_admin(interaction):
            return
        try:
            data = build_multiple_choice(question, correct, [wrong1, wrong2, wrong3])
        except TriviaError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await self._save(interaction, data)

    @admin.command(name="add_tf", description="Add a true/false question")
    @app_commands.describe(question="The statement", answer="Is the statement true or false?")
    @app_commands.choices(
        answer=[
            app_commands.Choice(name="True", value="true"),
            app_commands.Choice(name="False", value="false"),
        ]
    )
    async def add_tf(
        self,
        interaction: discord.Interaction,
        question: str,
        answer: app_commands.Choice[str],
    ):
        if not await self._require_admin(interaction):
            return
        try:
            data = build_true_false(question, answer.value == "true")
        except TriviaError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await self._save(interaction, data)

    @admin.command(name="add_open", description="Add an open ended question")
    @app_commands.describe(
        question="The question",
        answer="The correct answer",
        also_accept="Other accepted answers, separated by commas (optional)",
    )
    async def add_open(
        self,
        interaction: discord.Interaction,
        question: str,
        answer: str,
        also_accept: Optional[str] = None,
    ):
        if not await self._require_admin(interaction):
            return
        try:
            data = build_open_ended(question, answer, also_accept)
        except TriviaError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await self._save(interaction, data)

    @admin.command(name="list", description="List the trivia questions (with answers)")
    @app_commands.describe(type="Only show one type of question")
    @app_commands.choices(
        type=[app_commands.Choice(name=label, value=key) for key, label in TYPE_LABELS.items()]
    )
    async def list_questions(
        self,
        interaction: discord.Interaction,
        type: Optional[app_commands.Choice[str]] = None,
    ):
        if not await self._require_admin(interaction):
            return
        questions = await self.store.list_questions(
            interaction.guild.id, type.value if type else None
        )
        if not questions:
            await interaction.response.send_message(
                "No trivia questions yet. Add some with `/triviaadmin add_mc`, "
                "`add_tf` or `add_open`.",
                ephemeral=True,
            )
            return
        lines = []
        for q in questions:
            text = q.question if len(q.question) <= 90 else q.question[:87] + "..."
            lines.append(f"`#{q.id}` [{q.qtype.upper()}] {text} -> **{q.answer}**")
        chunks, current = [], ""
        for line in lines:
            if len(current) + len(line) + 1 > 1900:
                chunks.append(current)
                current = ""
            current += line + "\n"
        if current:
            chunks.append(current)
        await interaction.response.send_message(chunks[0], ephemeral=True)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)

    @admin.command(name="remove", description="Remove a trivia question by its ID")
    @app_commands.describe(question_id="The # shown in /triviaadmin list")
    async def remove_question(self, interaction: discord.Interaction, question_id: int):
        if not await self._require_admin(interaction):
            return
        removed = await self.store.remove_question(interaction.guild.id, question_id)
        message = (
            f"Removed question #{question_id}."
            if removed
            else f"No question #{question_id} in this server."
        )
        await interaction.response.send_message(message, ephemeral=True)

    @admin.command(name="clear", description="Delete all trivia questions (or one type)")
    @app_commands.describe(type="Only delete one type of question")
    @app_commands.choices(
        type=[app_commands.Choice(name=label, value=key) for key, label in TYPE_LABELS.items()]
    )
    async def clear_questions(
        self,
        interaction: discord.Interaction,
        type: Optional[app_commands.Choice[str]] = None,
    ):
        if not await self._require_admin(interaction):
            return
        n = await self.store.clear_questions(
            interaction.guild.id, type.value if type else None
        )
        await interaction.response.send_message(
            f"Deleted {n} question(s).", ephemeral=True
        )

    # ------------------------------------------------------------------
    # Player commands: /trivia ...
    # ------------------------------------------------------------------

    trivia = app_commands.Group(
        name="trivia", description="Play trivia", guild_only=True
    )

    @trivia.command(name="start", description="Start a trivia round in this channel")
    @app_commands.describe(
        multiple_choice="How many multiple choice questions (default 5)",
        true_false="How many true/false questions (default 5)",
        open_ended="How many open ended questions (default 5)",
    )
    async def start(
        self,
        interaction: discord.Interaction,
        multiple_choice: app_commands.Range[int, 0, MAX_PER_TYPE] = 5,
        true_false: app_commands.Range[int, 0, MAX_PER_TYPE] = 5,
        open_ended: app_commands.Range[int, 0, MAX_PER_TYPE] = 5,
    ):
        channel = interaction.channel
        if channel is None or interaction.guild is None:
            await interaction.response.send_message("Use this in a server channel.", ephemeral=True)
            return
        if channel.id in self.games:
            await interaction.response.send_message(
                "A trivia round is already running in this channel.", ephemeral=True
            )
            return

        wanted = {
            MULTIPLE_CHOICE: multiple_choice,
            TRUE_FALSE: true_false,
            OPEN_ENDED: open_ended,
        }
        pool = await self.store.list_questions(interaction.guild.id)
        questions = pick_questions(pool, wanted)
        if not questions:
            await interaction.response.send_message(
                "There are no trivia questions to play yet. An admin can add some with "
                "`/triviaadmin add_mc`, `add_tf` and `add_open`.",
                ephemeral=True,
            )
            return

        available = {t: sum(1 for q in questions if q.qtype == t) for t in QUESTION_TYPES}
        short = [
            f"{TYPE_LABELS[t]}: {available[t]}/{wanted[t]}"
            for t in QUESTION_TYPES
            if available[t] < wanted[t]
        ]
        game = TriviaGame(channel, interaction.user.id, questions)
        self.games[channel.id] = game

        intro = (
            f"**Trivia time!** {len(questions)} questions: "
            f"{available[MULTIPLE_CHOICE]} multiple choice, "
            f"{available[TRUE_FALSE]} true/false, {available[OPEN_ENDED]} open ended.\n"
            f"Buttons questions give 1 point ({BUTTON_QUESTION_SECONDS}s). "
            f"Open ended: first correct message in this channel wins "
            f"{POINTS[OPEN_ENDED]} points ({OPEN_QUESTION_SECONDS}s)."
        )
        if short:
            intro += "\n_Not enough questions in the bank for: " + ", ".join(short) + "._"
        await interaction.response.send_message(intro)
        game.task = asyncio.create_task(self._run_game(interaction.guild.id, game))

    @trivia.command(name="stop", description="Stop the trivia round in this channel")
    async def stop(self, interaction: discord.Interaction):
        game = self.games.get(interaction.channel_id)
        if game is None:
            await interaction.response.send_message(
                "No trivia round is running here.", ephemeral=True
            )
            return
        if interaction.user.id != game.starter_id and not is_trivia_admin(interaction.user):
            await interaction.response.send_message(
                "Only the person who started the round or an admin can stop it.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message("Stopping trivia...")
        if game.task:
            game.task.cancel()

    @trivia.command(name="leaderboard", description="All-time trivia leaderboard for this server")
    async def leaderboard(self, interaction: discord.Interaction):
        rows = await self.store.leaderboard(interaction.guild.id)
        if not rows:
            await interaction.response.send_message("Nobody has scored yet. Run `/trivia start`!")
            return
        lines = [
            f"**{i}.** <@{user_id}> - {points} pts ({correct} correct, {games} games)"
            for i, (user_id, points, correct, games) in enumerate(rows, 1)
        ]
        embed = discord.Embed(
            title="Trivia Leaderboard",
            description="\n".join(lines),
            color=EMBED_COLOR,
        )
        await interaction.response.send_message(
            embed=embed, allowed_mentions=discord.AllowedMentions.none()
        )

    @trivia.command(name="bank", description="How many trivia questions this server has")
    async def bank(self, interaction: discord.Interaction):
        counts = await self.store.count_by_type(interaction.guild.id)
        await interaction.response.send_message(
            f"Question bank: {counts[MULTIPLE_CHOICE]} multiple choice, "
            f"{counts[TRUE_FALSE]} true/false, {counts[OPEN_ENDED]} open ended.",
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # Game loop
    # ------------------------------------------------------------------

    async def _run_game(self, guild_id: int, game: TriviaGame):
        channel = game.channel
        stopped = False
        try:
            total = len(game.questions)
            for number, question in enumerate(game.questions, 1):
                await asyncio.sleep(2)
                if question.qtype == OPEN_ENDED:
                    await self._ask_open(channel, game, question, number, total)
                else:
                    await self._ask_buttons(channel, game, question, number, total)
        except asyncio.CancelledError:
            stopped = True
        except Exception:
            logger.exception("Trivia round crashed")
            try:
                await channel.send("Trivia hit an error and had to stop.")
            except discord.HTTPException:
                pass
            stopped = True
        finally:
            self.games.pop(channel.id, None)

        try:
            await self._finish(guild_id, game, stopped)
        except Exception:
            logger.exception("Failed to post trivia results")

    async def _finish(self, guild_id: int, game: TriviaGame, stopped: bool):
        results = {u: (p, game.correct.get(u, 0)) for u, p in game.points.items()}
        if results:
            await self.store.record_game(guild_id, results)
        ranking = sorted(game.points.items(), key=lambda kv: kv[1], reverse=True)
        if ranking:
            medals = ["1st", "2nd", "3rd"]
            lines = [
                f"**{medals[i] if i < 3 else f'{i + 1}th'}** <@{uid}> - {pts} pts "
                f"({game.correct.get(uid, 0)} correct)"
                for i, (uid, pts) in enumerate(ranking[:10])
            ]
            body = "\n".join(lines)
        else:
            body = "Nobody scored any points."
        embed = discord.Embed(
            title="Trivia stopped - scores so far" if stopped else "Trivia over - final scores",
            description=body,
            color=EMBED_COLOR,
        )
        await game.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    def _question_embed(self, question: TriviaQuestion, number: int, total: int, seconds: int):
        embed = discord.Embed(
            title=f"Question {number}/{total} - {question.label}",
            description=question.question,
            color=EMBED_COLOR,
        )
        embed.set_footer(
            text=f"{POINTS[question.qtype]} pt(s) - {seconds}s"
        )
        return embed

    async def _ask_buttons(self, channel, game, question, number, total):
        if question.qtype == MULTIPLE_CHOICE:
            choices = list(question.choices[:MAX_CHOICES])
            random.shuffle(choices)
            correct_index = choices.index(question.answer)
            labels = [f"{CHOICE_LETTERS[i]}. {c}" for i, c in enumerate(choices)]
        else:
            choices = ["True", "False"]
            correct_index = choices.index(question.answer)
            labels = choices

        embed = self._question_embed(question, number, total, BUTTON_QUESTION_SECONDS)
        if question.qtype == MULTIPLE_CHOICE:
            embed.description += "\n\n" + "\n".join(labels)
        button_labels = (
            list(CHOICE_LETTERS[: len(choices)])
            if question.qtype == MULTIPLE_CHOICE
            else labels
        )
        view = AnswerView(button_labels, BUTTON_QUESTION_SECONDS)
        message = await channel.send(embed=embed, view=view)
        await view.wait()
        view.stop()
        for item in view.children:
            item.disabled = True
        try:
            await message.edit(view=view)
        except discord.HTTPException:
            pass

        winners = [uid for uid, idx in view.answers.items() if idx == correct_index]
        for uid in winners:
            game.award(uid, question.qtype)
        answer_text = labels[correct_index]
        await channel.send(
            self._reveal_text(answer_text, winners, len(view.answers)),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _ask_open(self, channel, game, question, number, total):
        embed = self._question_embed(question, number, total, OPEN_QUESTION_SECONDS)
        embed.description += "\n\n_Type your answer in the chat!_"
        await channel.send(embed=embed)

        deadline = time.monotonic() + OPEN_QUESTION_SECONDS
        winner = None

        def check(m: discord.Message):
            return m.channel.id == channel.id and not m.author.bot

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=remaining)
            except asyncio.TimeoutError:
                break
            if check_open_answer(msg.content, question.answer, question.alt_answers):
                winner = msg.author
                break

        if winner:
            game.award(winner.id, question.qtype)
            await channel.send(
                f"{winner.mention} got it! The answer was **{question.answer}**. "
                f"(+{POINTS[question.qtype]} pts)",
                allowed_mentions=discord.AllowedMentions(users=[winner]),
            )
        else:
            await channel.send(f"Time's up! The answer was **{question.answer}**.")

    @staticmethod
    def _reveal_text(answer_text: str, winners: List[int], total_answers: int) -> str:
        if winners:
            names = ", ".join(f"<@{uid}>" for uid in winners[:15])
            return f"The answer was **{answer_text}**. Got it right: {names} (+1 pt)"
        if total_answers:
            return f"The answer was **{answer_text}**. Nobody got it right."
        return f"Time's up! The answer was **{answer_text}**."


async def setup(bot):
    await bot.add_cog(TriviaCog(bot))
    logger.info("Trivia cog loaded")
