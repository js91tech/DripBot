"""Trivia mode.

Admins with Manage Server add multiple choice, true/false, and open-ended
questions. Anyone in the channel can start a round and answer in chat.
"""

import asyncio
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils import prefix_command_allowed, prefix_owner_ids
from trivia import (
    BETWEEN,
    BUSY,
    DENIED,
    EXAMPLE_QUESTIONS,
    HELP_TEXT,
    PUBLIC_HELP_TEXT,
    MAX_ROUND,
    NONE_RUNNING,
    NOT_READY,
    TriviaError,
    TriviaSession,
    bank_summary,
    build_round,
    empty_bank_message,
    examples_loaded_message,
    find_duplicate,
    format_answer,
    format_bank,
    format_leaderboard,
    kind_label,
    parse_round_count,
    parse_trivia_add,
    public_name,
    question_card,
    seconds_for,
    should_cancel_task,
    start_announcement,
    validate_question,
    MAX_BANK,
)

logger = logging.getLogger("dripsletongue.cog.trivia")

_KIND_COLOR = {
    "multiple_choice": 0x5865F2,
    "true_false": 0x57F287,
    "open": 0xFEE75C,
}


def _correct_line(name, result):
    points = result["points"]
    total = result["total"]
    point_word = "point" if points == 1 else "points"
    total_word = "point" if total == 1 else "points"
    return (
        f"**{public_name(name)}** got it (+{points} {point_word}). "
        f"Answer: `{result['display']}`. Total: {total} {total_word}."
    )


class Trivia(commands.Cog):
    """Play trivia and let admins build the question bank."""

    def __init__(self, bot):
        self.bot = bot
        self.sessions = {}
        self.timers = {}

    def cog_unload(self):
        for channel_id in list(self.timers):
            self._cancel_timer(channel_id)
        self.sessions.clear()

    def is_channel_active(self, channel_id):
        return channel_id in self.sessions

    def _db(self):
        db = getattr(self.bot, "db", None)
        if db is None or getattr(db, "conn", None) is None:
            return None
        return db

    def _is_admin(self, member):
        perms = getattr(member, "guild_permissions", None)
        if perms is None:
            return False
        return bool(perms.administrator or perms.manage_guild)

    def _prefix(self):
        prefix = getattr(self.bot, "command_prefix", "!")
        return prefix if isinstance(prefix, str) and prefix else "!"

    def _cancel_timer(self, channel_id):
        task = self.timers.get(channel_id)
        if task is None:
            return
        if should_cancel_task(task, asyncio.current_task()):
            task.cancel()
        self.timers.pop(channel_id, None)

    def _arm_timer(self, channel, token, delay):
        self._cancel_timer(channel.id)
        self.timers[channel.id] = asyncio.create_task(self._expire(channel, token, delay))

    def _embed(self, question, number, total):
        card = question_card(question, number, total)
        embed = discord.Embed(
            title=card["title"],
            description=card["description"],
            color=_KIND_COLOR.get(question["kind"], 0x5865F2),
        )
        embed.set_footer(text=card["footer"])
        return embed

    async def _expire(self, channel, token, delay):
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        session = self.sessions.get(channel.id)
        if session is None or session.token != token or session.locked:
            return
        question = session.current()
        if question is None:
            return
        session.locked = True
        try:
            await self._after_question(
                channel,
                f"Time's up. The answer was `{format_answer(question)}`.",
            )
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Trivia timer failed")

    async def _after_question(self, channel, line):
        session = self.sessions.get(channel.id)
        game_id = session.game_id if session is not None else None
        if session is not None:
            session.advance()
        await channel.send(line)
        await asyncio.sleep(2)
        current = self.sessions.get(channel.id)
        if current is None or current.game_id != game_id:
            return
        try:
            await self._post_question(channel)
        except Exception:
            logger.exception("Failed to post trivia question")
            self.sessions.pop(channel.id, None)
            self._cancel_timer(channel.id)

    async def _post_question(self, channel):
        session = self.sessions.get(channel.id)
        if session is None:
            return
        question = session.current()
        if question is None:
            await self._end(channel, None)
            return
        token = session.open_question()
        await channel.send(embed=self._embed(question, session.index + 1, len(session.questions)))
        self._arm_timer(channel, token, seconds_for(question["kind"]))

    async def _end(self, channel, closing_line):
        session = self.sessions.pop(channel.id, None)
        self._cancel_timer(channel.id)
        if session is None:
            return False
        if closing_line:
            await channel.send(closing_line)
        await channel.send(format_leaderboard(session.leaderboard(), heading="Trivia over"))
        return True

    async def _begin(self, channel, guild_id, host_id, requested, announce):
        if channel.id in self.sessions:
            await announce(BUSY)
            return
        db = self._db()
        if db is None:
            await announce(NOT_READY)
            return
        bank = await db.list_trivia_questions(guild_id)
        if not bank:
            await announce(empty_bank_message())
            return
        selected = build_round(bank, requested)
        if not selected:
            await announce(empty_bank_message())
            return
        session = TriviaSession(channel.id, host_id, selected)
        self.sessions[channel.id] = session
        try:
            await announce(start_announcement(len(selected), len(bank), requested))
            await self._post_question(channel)
        except Exception:
            self.sessions.pop(channel.id, None)
            self._cancel_timer(channel.id)
            raise
        logger.info("Trivia round started in channel %s with %s questions", channel.id, len(selected))

    async def _stop(self, channel, requester_id, is_admin):
        session = self.sessions.get(channel.id)
        if session is None:
            return NONE_RUNNING
        if requester_id != session.host_id and not is_admin:
            return DENIED
        await self._end(channel, "Trivia stopped.")
        return None

    async def _skip(self, channel, requester_id, is_admin):
        session = self.sessions.get(channel.id)
        if session is None:
            return NONE_RUNNING
        if requester_id != session.host_id and not is_admin:
            return DENIED
        question = session.current()
        if question is None or session.locked:
            return BETWEEN
        session.locked = True
        self._cancel_timer(channel.id)
        await self._after_question(channel, f"Skipped. The answer was `{format_answer(question)}`.")
        return None

    def _score_text(self, channel):
        session = self.sessions.get(channel.id)
        if session is None:
            return NONE_RUNNING
        return format_leaderboard(session.leaderboard(), heading="Score so far")

    async def _summary(self, guild_id):
        db = self._db()
        if db is None:
            return NOT_READY
        return bank_summary(await db.list_trivia_questions(guild_id))

    async def _pages(self, guild_id):
        db = self._db()
        if db is None:
            return None
        return format_bank(await db.list_trivia_questions(guild_id))

    async def _save_question(self, guild_id, user_id, question):
        db = self._db()
        if db is None:
            return NOT_READY
        existing = await db.list_trivia_questions(guild_id)
        if len(existing) >= MAX_BANK:
            return (
                f"The trivia bank is full ({MAX_BANK} questions). "
                "Remove one with `/trivia remove`."
            )
        duplicate = find_duplicate(existing, question["question"])
        if duplicate is not None:
            return f"That question is already saved as `#{duplicate['id']}`."
        question_id = await db.add_trivia_question(
            guild_id,
            question["kind"],
            question["question"],
            question["choices"],
            question["answer"],
            question["accepted"],
            user_id,
        )
        return f"Added {kind_label(question['kind']).lower()} question `#{question_id}`."

    async def _remove_question(self, guild_id, question_id):
        db = self._db()
        if db is None:
            return NOT_READY
        removed = await db.delete_trivia_question(guild_id, question_id)
        if removed:
            return f"Removed trivia question `#{question_id}`."
        return f"No trivia question `#{question_id}` in this server."

    async def _load_examples(self, guild_id, user_id):
        db = self._db()
        if db is None:
            return NOT_READY
        existing = await db.list_trivia_questions(guild_id)
        added = 0
        skipped = 0
        for sample in EXAMPLE_QUESTIONS:
            if find_duplicate(existing, sample["question"]) is not None or len(existing) >= MAX_BANK:
                skipped += 1
                continue
            question_id = await db.add_trivia_question(
                guild_id,
                sample["kind"],
                sample["question"],
                sample["choices"],
                sample["answer"],
                sample["accepted"],
                user_id,
            )
            existing.append({"id": question_id, "question": sample["question"]})
            added += 1
        return examples_loaded_message(added, skipped)

    async def _clear_bank(self, guild_id, confirmed, hint):
        if not confirmed:
            return hint
        db = self._db()
        if db is None:
            return NOT_READY
        removed = await db.clear_trivia_questions(guild_id)
        if removed:
            word = "question" if removed == 1 else "questions"
            return f"Deleted **{removed}** trivia {word}."
        return "The trivia bank was already empty."

    async def _finish_deferred(self, interaction, message):
        if message:
            await interaction.followup.send(message, ephemeral=True)
            return
        try:
            await interaction.delete_original_response()
        except Exception:
            pass

    async def _reply(self, interaction, content, ephemeral=False):
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content, ephemeral=ephemeral)

    async def _need_guild(self, interaction):
        if interaction.guild is None or interaction.channel is None:
            await self._reply(interaction, "Trivia works in a server channel.", ephemeral=True)
            return None
        return interaction.guild

    # ── Prefix commands ──────────────────────────────────────────

    @commands.group(name="trivia", invoke_without_command=True)
    async def trivia(self, ctx):
        """Show trivia help."""
        await ctx.send(HELP_TEXT)

    @trivia.command(name="help")
    async def trivia_help(self, ctx):
        """Show trivia help."""
        await ctx.send(HELP_TEXT)

    @trivia.command(name="start", aliases=["play"])
    @commands.guild_only()
    async def trivia_start(self, ctx, count: str = None):
        """Start a trivia round. Optional count, or `all`."""
        requested = parse_round_count(count)
        await self._begin(ctx.channel, ctx.guild.id, ctx.author.id, requested, ctx.send)

    @trivia.command(name="stop", aliases=["end"])
    @commands.guild_only()
    async def trivia_stop(self, ctx):
        """Stop the round. Host or admin."""
        message = await self._stop(ctx.channel, ctx.author.id, self._is_admin(ctx.author))
        if message:
            await ctx.send(message)

    @trivia.command(name="skip")
    @commands.guild_only()
    async def trivia_skip(self, ctx):
        """Skip the current question. Host or admin."""
        message = await self._skip(ctx.channel, ctx.author.id, self._is_admin(ctx.author))
        if message:
            await ctx.send(message)

    @trivia.command(name="score")
    @commands.guild_only()
    async def trivia_score(self, ctx):
        """Show scores for the current round."""
        await ctx.send(self._score_text(ctx.channel))

    @trivia.command(name="count")
    @commands.guild_only()
    async def trivia_count(self, ctx):
        """Show how many questions are saved."""
        await ctx.send(await self._summary(ctx.guild.id))

    @trivia.command(name="add")
    @commands.guild_only()
    async def trivia_add(self, ctx, *, payload: str):
        """Add a multiple choice, true/false, or open-ended question."""
        question = parse_trivia_add(payload)
        await ctx.send(await self._save_question(ctx.guild.id, ctx.author.id, question))

    @trivia.command(name="list", aliases=["bank"])
    @commands.guild_only()
    async def trivia_list(self, ctx):
        """DM the question bank, including answers."""
        pages = await self._pages(ctx.guild.id)
        if pages is None:
            await ctx.send(NOT_READY)
            return
        try:
            for page in pages:
                await ctx.author.send(page)
        except discord.Forbidden:
            await ctx.send("I couldn't DM you the bank. Allow DMs from server members and try again.")
            return
        word = "message" if len(pages) == 1 else "messages"
        await ctx.send(f"Sent the trivia bank to your DMs ({len(pages)} {word}).")

    @trivia.command(name="remove", aliases=["delete"])
    @commands.guild_only()
    async def trivia_remove(self, ctx, question_id: int):
        """Delete one question by id."""
        await ctx.send(await self._remove_question(ctx.guild.id, question_id))

    @trivia.command(name="loadexamples", aliases=["examples", "seed"])
    @commands.guild_only()
    async def trivia_loadexamples(self, ctx):
        """Add 5 multiple choice, 5 true/false, and 5 open-ended samples."""
        await ctx.send(await self._load_examples(ctx.guild.id, ctx.author.id))

    @trivia.command(name="clear")
    @commands.guild_only()
    async def trivia_clear(self, ctx, confirm: str = None):
        """Delete the whole bank. Requires the word confirm."""
        confirmed = (confirm or "").strip().lower() == "confirm"
        hint = (
            "This deletes every trivia question in this server. "
            "Run `!trivia clear confirm` if you mean it."
        )
        await ctx.send(await self._clear_bank(ctx.guild.id, confirmed, hint))

    async def cog_command_error(self, ctx, error):
        original = getattr(error, "original", error)
        author_id = getattr(getattr(ctx, "author", None), "id", None)
        if not prefix_command_allowed(author_id, prefix_owner_ids(getattr(ctx, "bot", None))):
            return
        if isinstance(original, commands.MissingPermissions):
            await ctx.send("Only server admins (Manage Server) can change the trivia bank.")
            return
        if isinstance(original, commands.NoPrivateMessage):
            await ctx.send("Trivia works in a server channel.")
            return
        if isinstance(original, commands.MissingRequiredArgument):
            await ctx.send("That command is missing something. Try `!trivia help`.")
            return
        if isinstance(original, commands.BadArgument):
            await ctx.send("I couldn't read that. Try `!trivia help`.")
            return
        if isinstance(original, TriviaError):
            await ctx.send(str(original))
            return
        logger.exception("Trivia command failed", exc_info=original)
        await ctx.send("Trivia hit an error. Try again in a moment.")

    # ── Slash commands ───────────────────────────────────────────

    slash = app_commands.Group(
        name="trivia",
        description="Play trivia and manage custom questions",
        guild_only=True,
    )

    @slash.command(name="start", description="Start a trivia round in this channel")
    @app_commands.describe(count="How many questions, from 1 to 50. Defaults to 10.")
    async def slash_start(self, interaction: discord.Interaction, count: Optional[int] = None):
        guild = await self._need_guild(interaction)
        if guild is None:
            return
        if count is not None and not 1 <= count <= MAX_ROUND:
            await self._reply(
                interaction,
                f"A round can be from 1 to {MAX_ROUND} questions.",
                ephemeral=True,
            )
            return
        await self._begin(
            interaction.channel,
            guild.id,
            interaction.user.id,
            count,
            interaction.response.send_message,
        )

    @slash.command(name="stop", description="Stop the trivia round in this channel")
    async def slash_stop(self, interaction: discord.Interaction):
        guild = await self._need_guild(interaction)
        if guild is None:
            return
        await interaction.response.defer()
        message = await self._stop(
            interaction.channel,
            interaction.user.id,
            self._is_admin(interaction.user),
        )
        await self._finish_deferred(interaction, message)

    @slash.command(name="skip", description="Skip the current trivia question")
    async def slash_skip(self, interaction: discord.Interaction):
        guild = await self._need_guild(interaction)
        if guild is None:
            return
        await interaction.response.defer()
        message = await self._skip(
            interaction.channel,
            interaction.user.id,
            self._is_admin(interaction.user),
        )
        await self._finish_deferred(interaction, message)

    @slash.command(name="score", description="Show scores for the current round")
    async def slash_score(self, interaction: discord.Interaction):
        guild = await self._need_guild(interaction)
        if guild is None:
            return
        await interaction.response.send_message(self._score_text(interaction.channel))

    @slash.command(name="count", description="Show how many trivia questions are saved")
    async def slash_count(self, interaction: discord.Interaction):
        guild = await self._need_guild(interaction)
        if guild is None:
            return
        await interaction.response.send_message(await self._summary(guild.id))

    @slash.command(name="help", description="How to play trivia and add questions")
    async def slash_help(self, interaction: discord.Interaction):
        await self._reply(interaction, PUBLIC_HELP_TEXT, ephemeral=True)

    @slash.command(name="add", description="Add a trivia question to this server")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        question_type="Multiple choice, true or false, or open ended",
        question="The question players will see",
        answer="Correct answer. For multiple choice, a letter or the exact choice.",
        choices="Multiple choice only. Separate choices with |",
        also_accept="Open ended only. Other accepted answers, separated by |",
    )
    @app_commands.choices(
        question_type=[
            app_commands.Choice(name="Multiple choice", value="multiple_choice"),
            app_commands.Choice(name="True or false", value="true_false"),
            app_commands.Choice(name="Open ended", value="open"),
        ]
    )
    async def slash_add(
        self,
        interaction: discord.Interaction,
        question_type: str,
        question: str,
        answer: str,
        choices: Optional[str] = None,
        also_accept: Optional[str] = None,
    ):
        guild = await self._need_guild(interaction)
        if guild is None:
            return
        choice_list = [part.strip() for part in (choices or "").split("|") if part.strip()]
        extra_list = [part.strip() for part in (also_accept or "").split("|") if part.strip()]
        built = validate_question(question_type, question, choice_list, answer, extra_list)
        message = await self._save_question(guild.id, interaction.user.id, built)
        await self._reply(interaction, message, ephemeral=True)

    @slash.command(name="list", description="List saved questions and answers")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_list(self, interaction: discord.Interaction):
        guild = await self._need_guild(interaction)
        if guild is None:
            return
        pages = await self._pages(guild.id)
        if pages is None:
            await self._reply(interaction, NOT_READY, ephemeral=True)
            return
        await interaction.response.send_message(pages[0], ephemeral=True)
        for page in pages[1:5]:
            await interaction.followup.send(page, ephemeral=True)
        if len(pages) > 5:
            await interaction.followup.send(
                "That's the first part of the bank. Remove old questions if you need the rest.",
                ephemeral=True,
            )

    @slash.command(name="remove", description="Delete one saved trivia question")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(question_id="The id from /trivia list")
    async def slash_remove(self, interaction: discord.Interaction, question_id: int):
        guild = await self._need_guild(interaction)
        if guild is None:
            return
        await self._reply(
            interaction,
            await self._remove_question(guild.id, question_id),
            ephemeral=True,
        )

    @slash.command(
        name="loadexamples",
        description="Load 5 multiple choice, 5 true/false, and 5 open-ended questions",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_loadexamples(self, interaction: discord.Interaction):
        guild = await self._need_guild(interaction)
        if guild is None:
            return
        await interaction.response.send_message(await self._load_examples(guild.id, interaction.user.id))

    @slash.command(name="clear", description="Delete every trivia question in this server")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(confirm="Set true to delete the whole bank")
    async def slash_clear(self, interaction: discord.Interaction, confirm: bool = False):
        guild = await self._need_guild(interaction)
        if guild is None:
            return
        hint = "This deletes every trivia question in this server. Set confirm to true to delete them."
        await self._reply(
            interaction,
            await self._clear_bank(guild.id, confirm, hint),
            ephemeral=True,
        )

    async def cog_app_command_error(self, interaction, error):
        original = getattr(error, "original", error)
        if isinstance(original, app_commands.MissingPermissions) or isinstance(error, app_commands.MissingPermissions):
            await self._reply(interaction, "Only server admins (Manage Server) can change the trivia bank.", ephemeral=True)
            return
        if isinstance(original, TriviaError):
            await self._reply(interaction, str(original), ephemeral=True)
            return
        logger.exception("Trivia slash command failed", exc_info=original)
        await self._reply(interaction, "Trivia hit an error. Try again in a moment.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            await self._grade_message(message)
        except Exception:
            logger.exception("Trivia answer handling failed")

    async def _grade_message(self, message):
        if message.author.bot or message.guild is None:
            return
        session = self.sessions.get(message.channel.id)
        if session is None:
            return
        content = (message.content or "").strip()
        if not content:
            return
        if content.lower().startswith(self._prefix().lower()) or content.startswith("/"):
            return
        result = session.submit(message.author.id, message.author.display_name, content)
        if result["status"] == "correct":
            self._cancel_timer(message.channel.id)
            await self._after_question(message.channel, _correct_line(message.author.display_name, result))
        elif result["status"] == "wrong":
            try:
                await message.add_reaction("\u274c")
            except Exception:
                pass


async def setup(bot):
    await bot.add_cog(Trivia(bot))
    logger.info("Trivia cog loaded")
