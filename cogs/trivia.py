"""
cogs/trivia.py — Interactive Discord Trivia Mode & Admin Question Management
Supports Multiple Choice (with UI buttons and chat), True/False, and Open-Ended questions.
Admins can add, list, delete, and clear custom questions. Built-in 15 starter questions.
"""

import asyncio
import logging
import re
import time
from typing import List, Optional, Union

import discord
from discord import app_commands
from discord.ext import commands

from engine.trivia import (
    DEFAULT_QUESTIONS,
    MULTIPLE_CHOICE,
    OPEN_ENDED,
    TRUE_FALSE,
    TYPE_LABELS,
    TriviaManager,
    TriviaQuestion,
    TriviaSession,
    normalize_question_type,
)

logger = logging.getLogger("dripsletongue.cogs.trivia")


def is_admin(user: Union[discord.Member, discord.User], channel: Optional[discord.abc.GuildChannel] = None) -> bool:
    """Check if a user has administrator, manage_guild, or manage_channels permissions."""
    if isinstance(user, discord.Member):
        perms = user.guild_permissions
        if perms.administrator or perms.manage_guild or perms.manage_channels:
            return True
        if user.guild and user.guild.owner_id == user.id:
            return True
    return False


# ═══════════════════════════════════════════════════════════════
#  Discord UI Views for Multiple Choice & True/False
# ═══════════════════════════════════════════════════════════════

class MultipleChoiceView(discord.ui.View):
    """Interactive Discord buttons for Multiple Choice trivia questions."""

    def __init__(self, session: TriviaSession, question: TriviaQuestion, on_answer_callback, timeout: float = 30):
        super().__init__(timeout=timeout)
        self.session = session
        self.question = question
        self.on_answer_callback = on_answer_callback

        letters = ["A", "B", "C", "D", "E", "F", "G", "H"]
        for i, option in enumerate(question.options[:8]):
            letter = letters[i]
            label = f"{letter}) {option}"
            if len(label) > 75:
                label = label[:72] + "..."
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                custom_id=f"trivia_mc_{i}_{letter}",
            )
            button.callback = self._make_callback(letter, option)
            self.add_item(button)

    def _make_callback(self, letter: str, option: str):
        async def callback(interaction: discord.Interaction):
            await self.on_answer_callback(interaction, letter, option)
        return callback

    def disable_all(self, correct_idx: Optional[int] = None):
        """Disable all buttons and highlight the correct one in green."""
        for i, item in enumerate(self.children):
            if isinstance(item, discord.ui.Button):
                item.disabled = True
                if correct_idx is not None and i == correct_idx:
                    item.style = discord.ButtonStyle.success


class TrueFalseView(discord.ui.View):
    """Interactive Discord buttons for True/False trivia questions."""

    def __init__(self, session: TriviaSession, question: TriviaQuestion, on_answer_callback, timeout: float = 30):
        super().__init__(timeout=timeout)
        self.session = session
        self.question = question
        self.on_answer_callback = on_answer_callback

        true_button = discord.ui.Button(
            label="True",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id="trivia_tf_true",
        )
        true_button.callback = self._make_callback("True")
        self.add_item(true_button)

        false_button = discord.ui.Button(
            label="False",
            style=discord.ButtonStyle.danger,
            emoji="❌",
            custom_id="trivia_tf_false",
        )
        false_button.callback = self._make_callback("False")
        self.add_item(false_button)

    def _make_callback(self, value: str):
        async def callback(interaction: discord.Interaction):
            await self.on_answer_callback(interaction, value, value)
        return callback

    def disable_all(self, is_true: Optional[bool] = None):
        """Disable all buttons and highlight the correct one."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
                if is_true is not None:
                    if (item.label == "True" and is_true) or (item.label == "False" and not is_true):
                        item.style = discord.ButtonStyle.success
                    else:
                        item.style = discord.ButtonStyle.secondary


# ═══════════════════════════════════════════════════════════════
#  Trivia Cog
# ═══════════════════════════════════════════════════════════════

class TriviaCog(commands.Cog, name="Trivia"):
    """Trivia game mode with admin question management."""

    def __init__(self, bot, db, settings_manager=None):
        self.bot = bot
        self.db = db
        self.settings_manager = settings_manager
        self.manager = TriviaManager(db)
        bot.trivia_manager = self.manager

    # ═══════════════════════════════════════════════════════════════
    #  Chat Message Listener for Trivia Answers
    # ═══════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for trivia answers typed in active trivia channels."""
        if message.author.bot or not message.guild:
            return

        session = self.manager.get_session(message.channel.id)
        if not session or not session.is_active or session.question_answered:
            return

        content = (message.content or "").strip()
        if not content:
            return

        # Ignore bot commands
        prefix = getattr(self.bot, "command_prefix", "!")
        if isinstance(prefix, (str, tuple)):
            if content.startswith(prefix):
                return
        elif content.startswith("!"):
            return

        if content.startswith("/"):
            return

        current_q = session.current_question
        if not current_q:
            return

        # Check if message is a correct answer
        if current_q.check_answer(content):
            points = session.record_correct_answer(message.author.id, message.author.display_name)
            try:
                await message.add_reaction("🎉")
            except discord.HTTPException:
                pass

            await message.channel.send(
                f"🎉 **{message.author.mention}** got it right! The answer was {current_q.get_display_answer()} (+{points} pts)"
            )
        else:
            # If open-ended and looks like an earnest attempt, add a subtle reaction
            if current_q.question_type == OPEN_ENDED and len(content) >= 2:
                try:
                    await message.add_reaction("❌")
                except discord.HTTPException:
                    pass

    async def _handle_button_answer(
        self,
        interaction: discord.Interaction,
        choice_key: str,
        choice_text: str,
    ):
        """Handle button interaction answers for MC and TF."""
        session = self.manager.get_session(interaction.channel_id)
        if not session or not session.is_active or session.question_answered:
            await interaction.response.send_message(
                "This question has already been answered or timed out!",
                ephemeral=True,
            )
            return

        current_q = session.current_question
        if not current_q:
            await interaction.response.send_message("No active question.", ephemeral=True)
            return

        # Check either the letter/key or option text
        is_correct = current_q.check_answer(choice_key) or current_q.check_answer(choice_text)

        if is_correct:
            await interaction.response.defer()
            points = session.record_correct_answer(interaction.user.id, interaction.user.display_name)
            await interaction.channel.send(
                f"🎉 **{interaction.user.mention}** got it right! The answer was {current_q.get_display_answer()} (+{points} pts)"
            )
        else:
            await interaction.response.send_message(
                f"❌ **{choice_key}** is incorrect! Keep guessing!",
                ephemeral=True,
            )

    # ═══════════════════════════════════════════════════════════════
    #  Game Runner Loop
    # ═══════════════════════════════════════════════════════════════

    async def _run_game(self, session: TriviaSession, channel: discord.TextChannel):
        """Main game loop for a trivia session."""
        try:
            start_embed = discord.Embed(
                title="🎮 Trivia Game Starting!",
                description=(
                    f"**Rounds:** {session.total_questions}\n"
                    f"**Time Per Question:** {session.timeout_seconds}s\n"
                    f"**Points Per Question:** {session.points_per_question} pts\n\n"
                    "👉 **How to Play:** Click the buttons or type your answer directly in this channel!\n"
                    "First question starts in **3 seconds**..."
                ),
                color=discord.Color.blue(),
            )
            await channel.send(embed=start_embed)
            await asyncio.sleep(3)

            while not session.is_finished() and session.is_active:
                q = session.current_question
                if not q:
                    break

                # Build Question Embed
                embed = discord.Embed(
                    title=f"🧠 Question {session.current_index + 1} of {session.total_questions} — {TYPE_LABELS[q.question_type]}",
                    color=discord.Color.from_rgb(88, 101, 242),
                )
                embed.description = f"### {q.question}\n\n"

                view = None
                if q.question_type == MULTIPLE_CHOICE:
                    choices = q.get_formatted_choices()
                    choices_text = "\n".join(f"**{letter})** {text}" for letter, text in choices)
                    embed.description += choices_text
                    view = MultipleChoiceView(
                        session,
                        q,
                        self._handle_button_answer,
                        timeout=session.timeout_seconds,
                    )
                elif q.question_type == TRUE_FALSE:
                    embed.description += "🔘 *Click True or False below, or type your answer in chat!*"
                    view = TrueFalseView(
                        session,
                        q,
                        self._handle_button_answer,
                        timeout=session.timeout_seconds,
                    )
                elif q.question_type == OPEN_ENDED:
                    embed.description += "💬 *Type your answer directly in this channel!*"

                embed.set_footer(text=f"⏳ {session.timeout_seconds}s remaining • {session.points_per_question} pts")

                question_msg = await channel.send(embed=embed, view=view)
                session.active_message_id = question_msg.id
                session.current_view = view
                session.question_start_time = time.time()

                # Wait for an answer or timeout
                try:
                    await asyncio.wait_for(session.answer_event.wait(), timeout=session.timeout_seconds)
                except asyncio.TimeoutError:
                    session.record_timeout()

                if not session.is_active:
                    break

                # If nobody got it right, announce timeout
                if session.winner_id is None:
                    await channel.send(
                        f"⏰ **Time's up!** Nobody got it right. The correct answer was {q.get_display_answer()}."
                    )

                # Disable buttons on the original question message
                if view:
                    if q.question_type == MULTIPLE_CHOICE:
                        view.disable_all(q.get_correct_option_index())
                    elif q.question_type == TRUE_FALSE:
                        is_true = q.correct_answer.strip().lower() in {"true", "t", "yes", "1"}
                        view.disable_all(is_true)
                    try:
                        await question_msg.edit(view=view)
                    except Exception:
                        pass

                # Short intermission before next question
                if session.current_index + 1 < session.total_questions and session.is_active:
                    standings = session.get_standings()
                    leader_str = ""
                    if standings:
                        top = standings[0]
                        leader_str = f" • Current Leader: **{top[1]}** ({top[2]} pts)"
                    await channel.send(f"Next question in 4 seconds...{leader_str}")
                    await asyncio.sleep(4)
                    session.advance_to_next_question()
                else:
                    break

            # ── Final Results ──
            if session.is_active:
                standings = session.get_standings()
                final_embed = discord.Embed(
                    title="🏆 Trivia Game Finished — Final Scores!",
                    color=discord.Color.gold(),
                )

                if standings:
                    medals = ["🥇", "🥈", "🥉"]
                    lines = []
                    for i, (uid, uname, score, correct) in enumerate(standings):
                        medal = medals[i] if i < len(medals) else f"**#{i + 1}**"
                        lines.append(f"{medal} **{uname}** — {score} pts ({correct} correct)")
                    final_embed.description = "\n".join(lines)
                else:
                    final_embed.description = "No points were scored this game! Thanks for playing."

                final_embed.set_footer(text="Use /trivia leaderboard or !trivia leaderboard to view all-time server ranks!")
                await channel.send(embed=final_embed)

                # Save session scores to database
                await self.manager.save_session_results(session)

        except asyncio.CancelledError:
            logger.info(f"Trivia game in channel {channel.id} was cancelled.")
        except Exception as e:
            logger.error(f"Error during trivia session in channel {channel.id}: {e}", exc_info=True)
            await channel.send(f"⚠️ An error occurred during the trivia game: {e}")
        finally:
            self.manager.stop_session(channel.id)

    # ═══════════════════════════════════════════════════════════════
    #  Slash Commands (/trivia ...)
    # ═══════════════════════════════════════════════════════════════

    group = app_commands.Group(
        name="trivia",
        description="Play trivia or manage server trivia questions",
    )

    # ── /trivia start ──
    @group.command(name="start", description="Start an interactive trivia game in this channel")
    @app_commands.describe(
        rounds="Number of questions (default: 10)",
        question_type="Filter by question type (multiple choice, true/false, open-ended, or all)",
    )
    @app_commands.choices(
        question_type=[
            app_commands.Choice(name="All Types", value="all"),
            app_commands.Choice(name="Multiple Choice Only", value="multiple_choice"),
            app_commands.Choice(name="True / False Only", value="true_false"),
            app_commands.Choice(name="Open-Ended Only", value="open_ended"),
        ]
    )
    async def slash_trivia_start(
        self,
        interaction: discord.Interaction,
        rounds: Optional[int] = 10,
        question_type: Optional[app_commands.Choice[str]] = None,
    ):
        if not interaction.guild:
            await interaction.response.send_message("Trivia can only be played in a server channel.", ephemeral=True)
            return

        channel_id = interaction.channel_id
        if self.manager.is_channel_in_trivia(channel_id):
            await interaction.response.send_message(
                "A trivia game is already in progress in this channel! Use `/trivia stop` to end it.",
                ephemeral=True,
            )
            return

        guild_id = interaction.guild.id
        timeout = 30
        points = 10
        include_defaults = True

        if self.settings_manager:
            settings = await self.settings_manager.get_settings(guild_id)
            timeout = int(settings.get("trivia_timeout_seconds", 30))
            points = int(settings.get("trivia_points_per_question", 10))
            include_defaults = bool(settings.get("trivia_include_defaults", True))

        chosen_type = question_type.value if question_type and question_type.value != "all" else None
        num_rounds = min(max(1, rounds or 10), 50)

        try:
            session = await self.manager.start_session(
                guild_id=guild_id,
                channel_id=channel_id,
                rounds=num_rounds,
                question_type=chosen_type,
                timeout=timeout,
                points=points,
                include_defaults=include_defaults,
                started_by=interaction.user.id,
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Could not start trivia: {e}", ephemeral=True)
            return

        await interaction.response.send_message("🎲 Starting trivia game...", ephemeral=True)
        session.game_task = asyncio.create_task(self._run_game(session, interaction.channel))

    # ── /trivia stop ──
    @group.command(name="stop", description="Stop the active trivia game in this channel")
    async def slash_trivia_stop(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        session = self.manager.get_session(channel_id)
        if not session:
            await interaction.response.send_message("No active trivia game in this channel.", ephemeral=True)
            return

        if not is_admin(interaction.user, interaction.channel) and interaction.user.id != session.started_by:
            await interaction.response.send_message(
                "❌ Only server admins or the player who started the session can stop it.",
                ephemeral=True,
            )
            return

        self.manager.stop_session(channel_id)
        await interaction.response.send_message("🛑 The trivia game has been stopped.")

    # ── /trivia add_multiple_choice (Admin) ──
    @group.command(
        name="add_multiple_choice",
        description="[Admin] Add a custom multiple choice trivia question",
    )
    @app_commands.describe(
        question="The question prompt",
        options="Comma or pipe-separated options (e.g. 'Mars, Venus, Jupiter, Mercury')",
        correct_answer="The correct answer (option text or letter A/B/C/D)",
    )
    async def slash_add_mc(
        self,
        interaction: discord.Interaction,
        question: str,
        options: str,
        correct_answer: str,
    ):
        if not is_admin(interaction.user, interaction.channel):
            await interaction.response.send_message(
                "❌ Only server administrators or managers can add trivia questions.",
                ephemeral=True,
            )
            return

        # Parse options
        delimiter = "|" if "|" in options else ","
        opts = [o.strip() for o in options.split(delimiter) if o.strip()]
        if len(opts) < 2:
            await interaction.response.send_message(
                "❌ Please provide at least 2 options separated by commas or pipes (e.g. `Mars, Venus, Jupiter, Mercury`).",
                ephemeral=True,
            )
            return

        try:
            q = await self.manager.add_question(
                guild_id=interaction.guild.id,
                question_type=MULTIPLE_CHOICE,
                question=question,
                options=opts,
                correct_answer=correct_answer,
                created_by=interaction.user.id,
            )
            await interaction.response.send_message(
                f"✅ Added Multiple Choice Question **#{q.id}**!\n"
                f"**Question:** {q.question}\n"
                f"**Options:** {', '.join(q.options)}\n"
                f"**Answer:** {q.get_display_answer()}"
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to add question: {e}", ephemeral=True)

    # ── /trivia add_true_false (Admin) ──
    @group.command(
        name="add_true_false",
        description="[Admin] Add a custom True or False trivia question",
    )
    @app_commands.describe(
        question="The question prompt or statement",
        correct_answer="Is the statement True or False?",
    )
    @app_commands.choices(
        correct_answer=[
            app_commands.Choice(name="True", value="True"),
            app_commands.Choice(name="False", value="False"),
        ]
    )
    async def slash_add_tf(
        self,
        interaction: discord.Interaction,
        question: str,
        correct_answer: app_commands.Choice[str],
    ):
        if not is_admin(interaction.user, interaction.channel):
            await interaction.response.send_message(
                "❌ Only server administrators or managers can add trivia questions.",
                ephemeral=True,
            )
            return

        try:
            q = await self.manager.add_question(
                guild_id=interaction.guild.id,
                question_type=TRUE_FALSE,
                question=question,
                options=["True", "False"],
                correct_answer=correct_answer.value,
                created_by=interaction.user.id,
            )
            await interaction.response.send_message(
                f"✅ Added True/False Question **#{q.id}**!\n"
                f"**Question:** {q.question}\n"
                f"**Answer:** {q.get_display_answer()}"
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to add question: {e}", ephemeral=True)

    # ── /trivia add_open_ended (Admin) ──
    @group.command(
        name="add_open_ended",
        description="[Admin] Add a custom open-ended trivia question",
    )
    @app_commands.describe(
        question="The question prompt",
        correct_answer="The primary correct answer",
        alternate_answers="Optional alternate acceptable answers (comma or pipe-separated)",
    )
    async def slash_add_open(
        self,
        interaction: discord.Interaction,
        question: str,
        correct_answer: str,
        alternate_answers: Optional[str] = None,
    ):
        if not is_admin(interaction.user, interaction.channel):
            await interaction.response.send_message(
                "❌ Only server administrators or managers can add trivia questions.",
                ephemeral=True,
            )
            return

        alts = []
        if alternate_answers:
            delimiter = "|" if "|" in alternate_answers else ","
            alts = [a.strip() for a in alternate_answers.split(delimiter) if a.strip()]

        try:
            q = await self.manager.add_question(
                guild_id=interaction.guild.id,
                question_type=OPEN_ENDED,
                question=question,
                correct_answer=correct_answer,
                acceptable_answers=alts,
                created_by=interaction.user.id,
            )
            await interaction.response.send_message(
                f"✅ Added Open-Ended Question **#{q.id}**!\n"
                f"**Question:** {q.question}\n"
                f"**Answer:** {q.get_display_answer()}"
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to add question: {e}", ephemeral=True)

    # ── /trivia list ──
    @group.command(name="list", description="List custom trivia questions for this server")
    @app_commands.describe(question_type="Filter by question type")
    @app_commands.choices(
        question_type=[
            app_commands.Choice(name="All Types", value="all"),
            app_commands.Choice(name="Multiple Choice Only", value="multiple_choice"),
            app_commands.Choice(name="True / False Only", value="true_false"),
            app_commands.Choice(name="Open-Ended Only", value="open_ended"),
        ]
    )
    async def slash_list_questions(
        self,
        interaction: discord.Interaction,
        question_type: Optional[app_commands.Choice[str]] = None,
    ):
        guild_id = interaction.guild.id
        q_type = question_type.value if question_type and question_type.value != "all" else None
        custom = await self.manager.get_questions(guild_id, q_type, include_defaults=False)

        if not custom:
            await interaction.response.send_message(
                "No custom trivia questions found for this server yet.\n"
                "Admins can add questions using `/trivia add_multiple_choice`, `/trivia add_true_false`, or `/trivia add_open_ended`!",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"📋 Server Trivia Questions ({len(custom)} custom)",
            color=discord.Color.purple(),
        )

        lines = []
        for q in custom[:25]:
            type_label = TYPE_LABELS.get(q.question_type, q.question_type)
            lines.append(f"`#{q.id}` [{type_label}] **{q.question}** → {q.get_display_answer()}")

        embed.description = "\n".join(lines)
        if len(custom) > 25:
            embed.set_footer(text=f"Showing first 25 of {len(custom)} questions")

        await interaction.response.send_message(embed=embed)

    # ── /trivia remove (Admin) ──
    @group.command(name="remove", description="[Admin] Remove a custom trivia question by ID")
    @app_commands.describe(question_id="ID of the question to delete")
    async def slash_remove_question(self, interaction: discord.Interaction, question_id: int):
        if not is_admin(interaction.user, interaction.channel):
            await interaction.response.send_message(
                "❌ Only server administrators or managers can remove trivia questions.",
                ephemeral=True,
            )
            return

        try:
            deleted = await self.manager.delete_question(interaction.guild.id, question_id)
            if deleted:
                await interaction.response.send_message(f"🗑️ Successfully deleted question `#{question_id}`.")
            else:
                await interaction.response.send_message(f"❌ Question `#{question_id}` not found for this server.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to delete question: {e}", ephemeral=True)

    # ── /trivia clear (Admin) ──
    @group.command(name="clear", description="[Admin] Delete ALL custom trivia questions for this server")
    async def slash_clear_questions(self, interaction: discord.Interaction):
        if not is_admin(interaction.user, interaction.channel):
            await interaction.response.send_message(
                "❌ Only server administrators or managers can clear trivia questions.",
                ephemeral=True,
            )
            return

        count = await self.manager.clear_questions(interaction.guild.id)
        await interaction.response.send_message(f"🧹 Cleared all {count} custom trivia questions for this server.")

    # ── /trivia default_questions ──
    @group.command(name="default_questions", description="View the built-in starter questions (5 MC, 5 TF, 5 Open)")
    async def slash_default_questions(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🌟 Built-in Default Trivia Questions (15 Total)",
            description="These starter questions are available in every server automatically:",
            color=discord.Color.teal(),
        )

        mc = [q for q in DEFAULT_QUESTIONS if q.question_type == MULTIPLE_CHOICE]
        tf = [q for q in DEFAULT_QUESTIONS if q.question_type == TRUE_FALSE]
        op = [q for q in DEFAULT_QUESTIONS if q.question_type == OPEN_ENDED]

        mc_text = "\n".join(f"• **{q.question}** ({q.get_display_answer()})" for q in mc)
        tf_text = "\n".join(f"• **{q.question}** ({q.get_display_answer()})" for q in tf)
        op_text = "\n".join(f"• **{q.question}** ({q.get_display_answer()})" for q in op)

        embed.add_field(name="Multiple Choice (5)", value=mc_text, inline=False)
        embed.add_field(name="True / False (5)", value=tf_text, inline=False)
        embed.add_field(name="Open-Ended (5)", value=op_text, inline=False)

        await interaction.response.send_message(embed=embed)

    # ── /trivia leaderboard ──
    @group.command(name="leaderboard", description="View the server trivia leaderboard")
    @app_commands.describe(limit="Number of players to show (default: 10)")
    async def slash_leaderboard(self, interaction: discord.Interaction, limit: Optional[int] = 10):
        guild_id = interaction.guild.id
        scores = await self.manager.get_leaderboard(guild_id, limit=min(max(1, limit or 10), 25))

        if not scores:
            await interaction.response.send_message("No trivia games recorded yet! Start one with `/trivia start`.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🏆 {interaction.guild.name} Trivia Leaderboard",
            color=discord.Color.gold(),
        )

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, entry in enumerate(scores):
            uid = entry["user_id"]
            medal = medals[i] if i < len(medals) else f"**#{i + 1}**"
            member = interaction.guild.get_member(uid)
            uname = member.display_name if member else f"<@{uid}>"
            pts = entry["points"]
            correct = entry["correct_answers"]
            games = entry["games_played"]
            lines.append(f"{medal} **{uname}** — **{pts}** pts ({correct} correct, {games} games)")

        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    # ── /trivia status ──
    @group.command(name="status", description="Check trivia mode status and settings for this server")
    async def slash_status(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        channel_id = interaction.channel_id
        session = self.manager.get_session(channel_id)

        custom = await self.manager.get_questions(guild_id, include_defaults=False)
        custom_mc = sum(1 for q in custom if q.question_type == MULTIPLE_CHOICE)
        custom_tf = sum(1 for q in custom if q.question_type == TRUE_FALSE)
        custom_op = sum(1 for q in custom if q.question_type == OPEN_ENDED)

        embed = discord.Embed(
            title="🧠 Trivia Mode Status",
            color=discord.Color.blue(),
        )

        game_status = "Active game in this channel!" if session and session.is_active else "Idle (no active game in this channel)"
        embed.add_field(name="Channel Game Status", value=game_status, inline=False)

        pool_info = (
            f"**Total Custom Questions:** {len(custom)}\n"
            f"• Multiple Choice: {custom_mc}\n"
            f"• True/False: {custom_tf}\n"
            f"• Open-Ended: {custom_op}\n\n"
            f"**Built-in Defaults:** 15 questions (5 MC, 5 TF, 5 Open)\n"
            f"**Total Question Pool:** {len(custom) + 15} questions"
        )
        embed.add_field(name="Server Question Bank", value=pool_info, inline=False)

        await interaction.response.send_message(embed=embed)

    # ═══════════════════════════════════════════════════════════════
    #  Prefix Commands (!trivia ...)
    # ═══════════════════════════════════════════════════════════════

    @commands.group(name="trivia", invoke_without_command=True)
    async def prefix_trivia(self, ctx, *args):
        """Trivia root command. Displays help if no subcommand is given."""
        if not args:
            await self._send_prefix_help(ctx)
            return

        sub = args[0].lower()
        if sub in {"start", "play"}:
            rounds = 10
            q_type = None
            if len(args) > 1 and args[1].isdigit():
                rounds = int(args[1])
            if len(args) > 2:
                q_type = args[2]
            await self.cmd_start(ctx, rounds=rounds, question_type=q_type)
        elif sub in {"stop", "end", "cancel"}:
            await self.cmd_stop(ctx)
        elif sub in {"add", "create"}:
            await self.cmd_add(ctx, *args[1:])
        elif sub in {"list", "questions", "all"}:
            q_type = args[1] if len(args) > 1 else None
            await self.cmd_list(ctx, question_type=q_type)
        elif sub in {"remove", "delete", "del"}:
            if len(args) < 2 or not args[1].isdigit():
                await ctx.send("Usage: `!trivia remove <question_id>`")
                return
            await self.cmd_remove(ctx, int(args[1]))
        elif sub in {"clear", "reset_questions"}:
            await self.cmd_clear(ctx)
        elif sub in {"defaults", "default"}:
            await self.cmd_defaults(ctx)
        elif sub in {"leaderboard", "top", "scores"}:
            limit = int(args[1]) if len(args) > 1 and args[1].isdigit() else 10
            await self.cmd_leaderboard(ctx, limit=limit)
        elif sub in {"status", "info"}:
            await self.cmd_status(ctx)
        else:
            await self._send_prefix_help(ctx)

    async def _send_prefix_help(self, ctx):
        lines = [
            "🧠 **Trivia Mode Commands:**",
            "• `!trivia start [rounds] [type]` — Start a trivia game (e.g. `!trivia start 10`)",
            "• `!trivia stop` — Stop current trivia game",
            "• `!trivia leaderboard` — View server leaderboard",
            "• `!trivia defaults` — View 15 built-in starter questions",
            "• `!trivia status` — View trivia bank status",
            "",
            "👑 **Admin Question Management:**",
            "• `!trivia add mc <Question> | <Opt1, Opt2, Opt3, Opt4> | <Answer>`",
            "  *Example:* `!trivia add mc Red Planet? | Mars, Venus, Jupiter, Earth | Mars`",
            "• `!trivia add tf <Question> | <True/False>`",
            "  *Example:* `!trivia add tf Sharks are mammals. | False`",
            "• `!trivia add open <Question> | <Answer> [| <Alternate Answers>]`",
            "  *Example:* `!trivia add open Symbol for gold? | Au | gold`",
            "• `!trivia list [type]` — List custom questions",
            "• `!trivia remove <id>` — Delete a question by ID",
            "• `!trivia clear` — Delete all custom questions",
        ]
        await ctx.send("\n".join(lines))

    # ── !trivia start ──
    @prefix_trivia.command(name="start")
    async def cmd_start(self, ctx, rounds: int = 10, question_type: str = None):
        if not ctx.guild:
            await ctx.send("Trivia can only be played in a server channel.")
            return

        channel_id = ctx.channel.id
        if self.manager.is_channel_in_trivia(channel_id):
            await ctx.send("A trivia game is already in progress in this channel! Use `!trivia stop` to end it.")
            return

        guild_id = ctx.guild.id
        timeout = 30
        points = 10
        include_defaults = True

        if self.settings_manager:
            settings = await self.settings_manager.get_settings(guild_id)
            timeout = int(settings.get("trivia_timeout_seconds", 30))
            points = int(settings.get("trivia_points_per_question", 10))
            include_defaults = bool(settings.get("trivia_include_defaults", True))

        num_rounds = min(max(1, rounds), 50)
        canonical_type = normalize_question_type(question_type) if question_type else None

        try:
            session = await self.manager.start_session(
                guild_id=guild_id,
                channel_id=channel_id,
                rounds=num_rounds,
                question_type=canonical_type,
                timeout=timeout,
                points=points,
                include_defaults=include_defaults,
                started_by=ctx.author.id,
            )
        except Exception as e:
            await ctx.send(f"❌ Could not start trivia: {e}")
            return

        session.game_task = asyncio.create_task(self._run_game(session, ctx.channel))

    # ── !trivia stop ──
    @prefix_trivia.command(name="stop")
    async def cmd_stop(self, ctx):
        channel_id = ctx.channel.id
        session = self.manager.get_session(channel_id)
        if not session:
            await ctx.send("No active trivia game in this channel.")
            return

        if not is_admin(ctx.author, ctx.channel) and ctx.author.id != session.started_by:
            await ctx.send("❌ Only server admins or the player who started the session can stop it.")
            return

        self.manager.stop_session(channel_id)
        await ctx.send("🛑 The trivia game has been stopped.")

    # ── !trivia add ──
    @prefix_trivia.command(name="add")
    async def cmd_add(self, ctx, *args):
        if not is_admin(ctx.author, ctx.channel):
            await ctx.send("❌ Only server administrators or managers can add trivia questions.")
            return

        if not args:
            await ctx.send(
                "Usage:\n"
                "• `!trivia add mc <Question> | <Opt1, Opt2, Opt3, Opt4> | <Answer>`\n"
                "• `!trivia add tf <Question> | <True/False>`\n"
                "• `!trivia add open <Question> | <Answer> [| <Alts>]`"
            )
            return

        q_type_raw = args[0].lower()
        remainder = " ".join(args[1:]).strip()

        if not remainder:
            await ctx.send("Please provide the question prompt and answer separated by `|`.")
            return

        canonical_type = normalize_question_type(q_type_raw)
        if not canonical_type:
            await ctx.send(f"❌ Unknown question type: `{q_type_raw}`. Use `mc`, `tf`, or `open`.")
            return

        parts = [p.strip() for p in remainder.split("|") if p.strip()]

        if canonical_type == MULTIPLE_CHOICE:
            if len(parts) < 3:
                await ctx.send("❌ Usage: `!trivia add mc <Question> | <Opt1, Opt2, Opt3, Opt4> | <Answer>`")
                return
            question = parts[0]
            options_raw = parts[1]
            answer = parts[2]
            opts = [o.strip() for o in options_raw.split(",") if o.strip()]
            try:
                q = await self.manager.add_question(
                    guild_id=ctx.guild.id,
                    question_type=MULTIPLE_CHOICE,
                    question=question,
                    options=opts,
                    correct_answer=answer,
                    created_by=ctx.author.id,
                )
                await ctx.send(
                    f"✅ Added Multiple Choice Question **#{q.id}**!\n"
                    f"**Question:** {q.question}\n"
                    f"**Options:** {', '.join(q.options)}\n"
                    f"**Answer:** {q.get_display_answer()}"
                )
            except Exception as e:
                await ctx.send(f"❌ Failed to add question: {e}")

        elif canonical_type == TRUE_FALSE:
            if len(parts) < 2:
                await ctx.send("❌ Usage: `!trivia add tf <Question> | <True/False>`")
                return
            question = parts[0]
            answer = parts[1]
            try:
                q = await self.manager.add_question(
                    guild_id=ctx.guild.id,
                    question_type=TRUE_FALSE,
                    question=question,
                    options=["True", "False"],
                    correct_answer=answer,
                    created_by=ctx.author.id,
                )
                await ctx.send(
                    f"✅ Added True/False Question **#{q.id}**!\n"
                    f"**Question:** {q.question}\n"
                    f"**Answer:** {q.get_display_answer()}"
                )
            except Exception as e:
                await ctx.send(f"❌ Failed to add question: {e}")

        elif canonical_type == OPEN_ENDED:
            if len(parts) < 2:
                await ctx.send("❌ Usage: `!trivia add open <Question> | <Answer> [| <Alternate Answers>]`")
                return
            question = parts[0]
            answer = parts[1]
            alts = [a.strip() for a in parts[2].split(",") if a.strip()] if len(parts) > 2 else []
            try:
                q = await self.manager.add_question(
                    guild_id=ctx.guild.id,
                    question_type=OPEN_ENDED,
                    question=question,
                    correct_answer=answer,
                    acceptable_answers=alts,
                    created_by=ctx.author.id,
                )
                await ctx.send(
                    f"✅ Added Open-Ended Question **#{q.id}**!\n"
                    f"**Question:** {q.question}\n"
                    f"**Answer:** {q.get_display_answer()}"
                )
            except Exception as e:
                await ctx.send(f"❌ Failed to add question: {e}")

    # ── !trivia list ──
    @prefix_trivia.command(name="list")
    async def cmd_list(self, ctx, question_type: str = None):
        guild_id = ctx.guild.id
        canonical_type = normalize_question_type(question_type) if question_type else None
        custom = await self.manager.get_questions(guild_id, canonical_type, include_defaults=False)

        if not custom:
            await ctx.send(
                "No custom trivia questions found for this server yet.\n"
                "Admins can add questions using `!trivia add mc ...`, `!trivia add tf ...`, or `!trivia add open ...`!"
            )
            return

        embed = discord.Embed(
            title=f"📋 Server Trivia Questions ({len(custom)} custom)",
            color=discord.Color.purple(),
        )

        lines = []
        for q in custom[:25]:
            type_label = TYPE_LABELS.get(q.question_type, q.question_type)
            lines.append(f"`#{q.id}` [{type_label}] **{q.question}** → {q.get_display_answer()}")

        embed.description = "\n".join(lines)
        if len(custom) > 25:
            embed.set_footer(text=f"Showing first 25 of {len(custom)} questions")

        await ctx.send(embed=embed)

    # ── !trivia remove ──
    @prefix_trivia.command(name="remove")
    async def cmd_remove(self, ctx, question_id: int):
        if not is_admin(ctx.author, ctx.channel):
            await ctx.send("❌ Only server administrators or managers can remove trivia questions.")
            return

        deleted = await self.manager.delete_question(ctx.guild.id, question_id)
        if deleted:
            await ctx.send(f"🗑️ Successfully deleted question `#{question_id}`.")
        else:
            await ctx.send(f"❌ Question `#{question_id}` not found for this server.")

    # ── !trivia clear ──
    @prefix_trivia.command(name="clear")
    async def cmd_clear(self, ctx):
        if not is_admin(ctx.author, ctx.channel):
            await ctx.send("❌ Only server administrators or managers can clear trivia questions.")
            return

        count = await self.manager.clear_questions(ctx.guild.id)
        await ctx.send(f"🧹 Cleared all {count} custom trivia questions for this server.")

    # ── !trivia defaults ──
    @prefix_trivia.command(name="defaults")
    async def cmd_defaults(self, ctx):
        embed = discord.Embed(
            title="🌟 Built-in Default Trivia Questions (15 Total)",
            description="These starter questions are available in every server automatically:",
            color=discord.Color.teal(),
        )

        mc = [q for q in DEFAULT_QUESTIONS if q.question_type == MULTIPLE_CHOICE]
        tf = [q for q in DEFAULT_QUESTIONS if q.question_type == TRUE_FALSE]
        op = [q for q in DEFAULT_QUESTIONS if q.question_type == OPEN_ENDED]

        mc_text = "\n".join(f"• **{q.question}** ({q.get_display_answer()})" for q in mc)
        tf_text = "\n".join(f"• **{q.question}** ({q.get_display_answer()})" for q in tf)
        op_text = "\n".join(f"• **{q.question}** ({q.get_display_answer()})" for q in op)

        embed.add_field(name="Multiple Choice (5)", value=mc_text, inline=False)
        embed.add_field(name="True / False (5)", value=tf_text, inline=False)
        embed.add_field(name="Open-Ended (5)", value=op_text, inline=False)

        await ctx.send(embed=embed)

    # ── !trivia leaderboard ──
    @prefix_trivia.command(name="leaderboard")
    async def cmd_leaderboard(self, ctx, limit: int = 10):
        guild_id = ctx.guild.id
        scores = await self.manager.get_leaderboard(guild_id, limit=min(max(1, limit), 25))

        if not scores:
            await ctx.send("No trivia games recorded yet! Start one with `!trivia start`.")
            return

        embed = discord.Embed(
            title=f"🏆 {ctx.guild.name} Trivia Leaderboard",
            color=discord.Color.gold(),
        )

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, entry in enumerate(scores):
            uid = entry["user_id"]
            medal = medals[i] if i < len(medals) else f"**#{i + 1}**"
            member = ctx.guild.get_member(uid)
            uname = member.display_name if member else f"<@{uid}>"
            pts = entry["points"]
            correct = entry["correct_answers"]
            games = entry["games_played"]
            lines.append(f"{medal} **{uname}** — **{pts}** pts ({correct} correct, {games} games)")

        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    # ── !trivia status ──
    @prefix_trivia.command(name="status")
    async def cmd_status(self, ctx):
        guild_id = ctx.guild.id
        channel_id = ctx.channel.id
        session = self.manager.get_session(channel_id)

        custom = await self.manager.get_questions(guild_id, include_defaults=False)
        custom_mc = sum(1 for q in custom if q.question_type == MULTIPLE_CHOICE)
        custom_tf = sum(1 for q in custom if q.question_type == TRUE_FALSE)
        custom_op = sum(1 for q in custom if q.question_type == OPEN_ENDED)

        embed = discord.Embed(
            title="🧠 Trivia Mode Status",
            color=discord.Color.blue(),
        )

        game_status = "Active game in this channel!" if session and session.is_active else "Idle (no active game in this channel)"
        embed.add_field(name="Channel Game Status", value=game_status, inline=False)

        pool_info = (
            f"**Total Custom Questions:** {len(custom)}\n"
            f"• Multiple Choice: {custom_mc}\n"
            f"• True/False: {custom_tf}\n"
            f"• Open-Ended: {custom_op}\n\n"
            f"**Built-in Defaults:** 15 questions (5 MC, 5 TF, 5 Open)\n"
            f"**Total Question Pool:** {len(custom) + 15} questions"
        )
        embed.add_field(name="Server Question Bank", value=pool_info, inline=False)

        await ctx.send(embed=embed)


async def setup(bot):
    cog = TriviaCog(bot, bot.db, getattr(bot, "settings_manager", None))
    await bot.add_cog(cog)
