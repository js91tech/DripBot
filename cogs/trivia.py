"""Trivia mode — admins add their own questions, anyone can play.

Question types:
  - multiple_choice (A-D options)
  - true_false
  - open (open-ended, fuzzy matched so minor typos still count)

Chat usage (prefix, default ``!``):
  !trivia help
  !trivia addmc Question? | Option A | Option B | Option C | Option D | B
  !trivia addtf Is the sky blue? | true
  !trivia addopen Largest ocean? | Pacific Ocean | Pacific
  !trivia list [mc|tf|open] [page]
  !trivia remove <id>
  !trivia clear [mc|tf|open]
  !trivia seed              (adds 5 MCQ + 5 true/false + 5 open samples)
  !trivia start [count] [seconds] [all|mc|tf|open]
  !trivia stop
  !trivia leaderboard
  !trivia score

Slash equivalents live under /trivia (add_mcq, add_tf, add_open,
remove, list, clear, seed, start, stop, leaderboard, score).

Adding/removing/clearing/seeding questions requires Manage Server
(or Administrator). Starting a game is open to everyone; stopping one
needs the host or a mod.
"""

import asyncio
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from engine.trivia import (
    MC_LETTERS,
    SEED_QUESTIONS,
    check_answer,
    format_correct_answer,
    pick_game_questions,
    validate_mcq,
    validate_open,
    validate_tf,
)

logger = logging.getLogger("dripsletongue.cog.trivia")

TYPE_LABELS = {
    "multiple_choice": "Multiple Choice",
    "true_false": "True / False",
    "open": "Open Answer",
}

TYPE_EMOJI = {
    "multiple_choice": "🔤",
    "true_false": "⚖️",
    "open": "✏️",
}

CATEGORY_ALIASES = {
    "all": None,
    "mc": "multiple_choice",
    "mcq": "multiple_choice",
    "multiple_choice": "multiple_choice",
    "multiple-choice": "multiple_choice",
    "tf": "true_false",
    "true_false": "true_false",
    "true-false": "true_false",
    "truefalse": "true_false",
    "open": "open",
}


def _is_mod(member):
    """True when the member may manage trivia questions."""
    if member is None:
        return False
    perms = getattr(member, "guild_permissions", None)
    if perms is None:
        return False
    return bool(
        perms.administrator or perms.manage_guild or perms.manage_messages
    )


def _parse_pipe_args(raw, expected_parts):
    """Split ``a | b | c`` input. Returns list or None when the count is off."""
    parts = [p.strip() for p in str(raw or "").split("|")]
    parts = [p for p in parts if p != ""]
    if len(parts) != expected_parts:
        return None
    return parts


class TriviaGame:
    """One running game in one channel."""

    def __init__(self, guild_id, channel_id, questions, seconds_per_question, host_id):
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.questions = questions
        self.seconds_per_question = seconds_per_question
        self.host_id = host_id
        self.scores = {}
        self.winners = {}  # question index -> user_id
        self.started_at = time.time()
        self.cancelled = False
        self.task = None


class TriviaCog(commands.Cog):
    """Trivia questions + game loop."""

    trivia_group = app_commands.Group(
        name="trivia",
        description="Play trivia or manage trivia questions",
    )

    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self.games = {}
        if not hasattr(bot, "trivia_active_channels"):
            bot.trivia_active_channels = set()

    # ── helpers ──

    def _guild_id(self, ctx_or_interaction):
        guild = getattr(ctx_or_interaction, "guild", None)
        if guild is not None:
            return guild.id
        return 0

    def _question_embed(self, question, number, total, seconds):
        label = TYPE_LABELS.get(question.get("qtype"), question.get("qtype"))
        emoji = TYPE_EMOJI.get(question.get("qtype"), "❓")
        embed = discord.Embed(
            title=f"{emoji} Q{number}/{total} — {label} ({seconds}s)",
            description=f"**{question.get('question', '')}**",
            color=discord.Color.gold(),
        )
        if question.get("qtype") == "multiple_choice":
            lines = []
            for i, option in enumerate(question.get("options") or []):
                lines.append(f"**{MC_LETTERS[i]}.** {option}")
            embed.add_field(
                name="Reply with A, B, C, D (or the full answer)",
                value="\n".join(lines),
                inline=False,
            )
        elif question.get("qtype") == "true_false":
            embed.add_field(
                name="Reply with True or False",
                value="True ✅ / False ❌",
                inline=False,
            )
        else:
            embed.add_field(
                name="Reply with your answer",
                value="Closest answer counts — minor typos are OK.",
                inline=False,
            )
        embed.set_footer(text=f"Question id #{question.get('id')}")
        return embed

    async def _store_validated(self, guild_id, cleaned, created_by):
        qtype = cleaned["qtype"]
        if qtype == "multiple_choice":
            return await self.db.add_trivia_question(
                guild_id,
                qtype,
                cleaned["question"],
                cleaned["options"],
                cleaned["answer"],
                answer_index=cleaned["answer_index"],
                alternates=[],
                created_by=created_by,
            )
        if qtype == "true_false":
            return await self.db.add_trivia_question(
                guild_id,
                qtype,
                cleaned["question"],
                [],
                "true" if cleaned["answer"] else "false",
                created_by=created_by,
            )
        return await self.db.add_trivia_question(
            guild_id,
            qtype,
            cleaned["question"],
            [],
            cleaned["answer"],
            alternates=cleaned.get("alternates", []),
            created_by=created_by,
        )

    def _game_check(self, game):
        prefixes = ("!", "/", ".", "?", "$")

        def _check(message):
            if message.channel.id != game.channel_id:
                return False
            if message.author.bot:
                return False
            content = (message.content or "").strip()
            if not content or content.startswith(prefixes):
                return False
            return True

        return _check

    async def _run_game(self, channel, game):
        try:
            intro = discord.Embed(
                title="🎉 Trivia starting!",
                description=(
                    f"**{len(game.questions)} questions** • "
                    f"{game.seconds_per_question}s each • "
                    "first correct answer scores a point!"
                ),
                color=discord.Color.green(),
            )
            await channel.send(embed=intro)

            for index, question in enumerate(game.questions):
                if game.cancelled:
                    break
                await channel.send(
                    embed=self._question_embed(
                        question, index + 1, len(game.questions),
                        game.seconds_per_question,
                    )
                )
                deadline = time.monotonic() + game.seconds_per_question
                winner = None
                winner_msg = None
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        msg = await self.bot.wait_for(
                            "message", timeout=remaining, check=self._game_check(game)
                        )
                    except asyncio.TimeoutError:
                        break
                    if game.cancelled:
                        break
                    try:
                        if check_answer(question, msg.content):
                            winner = msg.author
                            winner_msg = msg
                            break
                    except Exception:
                        continue

                if game.cancelled:
                    break
                if winner is not None:
                    game.scores[winner.id] = game.scores.get(winner.id, 0) + 1
                    game.winners[index] = winner.id
                    await channel.send(
                        f"✅ {winner.mention} got it! "
                        f"The answer was **{format_correct_answer(question)}**."
                    )
                else:
                    await channel.send(
                        f"⏰ Time! The answer was **{format_correct_answer(question)}**."
                    )
                await asyncio.sleep(2)

            if game.cancelled:
                await channel.send("🛑 Trivia stopped.")
                return

            if not game.scores:
                await channel.send("No one scored this time. GG!")
                return

            ranked = sorted(game.scores.items(), key=lambda kv: kv[1], reverse=True)
            lines = []
            for rank, (user_id, points) in enumerate(ranked[:10], start=1):
                member = channel.guild.get_member(user_id) if channel.guild else None
                name = member.display_name if member else f"<@{user_id}>"
                lines.append(f"**{rank}.** {name} — {points} point(s)")
            end = discord.Embed(
                title="🏁 Trivia results",
                description="\n".join(lines),
                color=discord.Color.gold(),
            )
            top_id = ranked[0][0]
            top_member = channel.guild.get_member(top_id) if channel.guild else None
            top_name = top_member.display_name if top_member else "Winner"
            end.add_field(name="Winner", value=f"🎊 {top_name}!", inline=False)
            await channel.send(embed=end)

            for user_id, points in game.scores.items():
                try:
                    await self.db.add_trivia_points(game.guild_id, user_id, points)
                except Exception as e:
                    logger.warning(f"trivia score save failed: {e}")
            try:
                await self.db.add_trivia_win(game.guild_id, top_id)
            except Exception as e:
                logger.warning(f"trivia win save failed: {e}")
        except Exception as e:
            logger.error(f"trivia game error: {e}", exc_info=True)
            try:
                await channel.send(f"Trivia hit an error: `{e}`")
            except Exception:
                pass
        finally:
            self.games.pop(game.channel_id, None)
            active = getattr(self.bot, "trivia_active_channels", None)
            if active is not None:
                active.discard(game.channel_id)

    async def _start_game(self, guild_id, channel, host_id, count, seconds, category):
        if channel.id in self.games:
            return None, "A trivia game is already running in this channel!"
        seconds = max(10, min(60, int(seconds or 20)))
        count = max(1, min(25, int(count or 10)))
        qtype = CATEGORY_ALIASES.get(str(category or "all").lower(), None)
        if str(category or "all").lower() not in CATEGORY_ALIASES:
            return None, "Category must be `all`, `mc`, `tf`, or `open`."
        questions = await self.db.get_trivia_questions(guild_id, qtype)
        if not questions:
            counts = await self.db.count_trivia_questions(guild_id)
            hint = (
                "No trivia questions yet! Admins can add some with "
                "`/trivia add_mcq`, `/trivia add_tf`, `/trivia add_open` "
                "or `!trivia seed` for 5 MCQ + 5 true/false + 5 open samples."
            )
            if counts["total"]:
                hint = (
                    f"No `{qtype or 'all'}` questions stored "
                    f"({counts['total']} total). Try `all` or add more."
                )
            return None, hint
        picked = pick_game_questions(questions, count)
        game = TriviaGame(guild_id, channel.id, picked, seconds, host_id)
        self.games[channel.id] = game
        self.bot.trivia_active_channels.add(channel.id)
        game.task = asyncio.create_task(self._run_game(channel, game))
        return game, None

    # ══════════════════════════════════════════
    #  Prefix commands: !trivia ...
    # ══════════════════════════════════════════

    @commands.group(name="trivia", invoke_without_command=True)
    async def trivia(self, ctx):
        """Trivia mode. Use `!trivia help` for usage."""
        await ctx.send(
            "**🎲 Trivia mode**\n"
            "Play: `!trivia start [count] [seconds] [all|mc|tf|open]`\n"
            "Add (admin): `!trivia addmc`, `!trivia addtf`, `!trivia addopen` — "
            "see `!trivia help` for formats.\n"
            "Scores: `!trivia leaderboard`, `!trivia score`"
        )

    @trivia.command(name="help")
    async def trivia_help(self, ctx):
        await ctx.send(
            "**🎲 Trivia — admin question formats**\n"
            "```\n"
            "!trivia addmc Question? | Option A | Option B | Option C | Option D | B\n"
            "!trivia addtf Is the sky blue? | true\n"
            "!trivia addopen Largest ocean? | Pacific Ocean | Pacific\n"
            "```\n"
            "**Manage (needs Manage Server):** "
            "`!trivia list [mc|tf|open] [page]`, `!trivia remove <id>`, "
            "`!trivia clear [mc|tf|open]`, `!trivia seed`\n"
            "**Play:** `!trivia start [count, default 10] [seconds, default 20] "
            "[all|mc|tf|open]`, `!trivia stop`, `!trivia leaderboard`, `!trivia score`\n"
            "Slash commands under `/trivia` do the same thing with pop-up fields."
        )

    @trivia.command(name="addmc")
    async def trivia_addmc(self, ctx, *, raw: str = ""):
        """Add a multiple-choice question (admin)."""
        if not _is_mod(ctx.author):
            await ctx.send("You need **Manage Server** permission to add trivia questions.")
            return
        parts = _parse_pipe_args(raw, 6)
        if not parts:
            await ctx.send(
                "Usage: `!trivia addmc Question? | Option A | Option B | Option C | Option D | B`"
            )
            return
        try:
            cleaned = validate_mcq(parts[0], parts[1:5], parts[5])
        except ValueError as e:
            await ctx.send(f"Couldn't add that question: `{e}`")
            return
        qid = await self._store_validated(ctx.guild.id, cleaned, ctx.author.id)
        await ctx.send(f"Added multiple-choice question **#{qid}**: {cleaned['question']}")

    @trivia.command(name="addtf")
    async def trivia_addtf(self, ctx, *, raw: str = ""):
        """Add a true/false question (admin)."""
        if not _is_mod(ctx.author):
            await ctx.send("You need **Manage Server** permission to add trivia questions.")
            return
        parts = _parse_pipe_args(raw, 2)
        if not parts:
            await ctx.send("Usage: `!trivia addtf Is the sky blue? | true`")
            return
        try:
            cleaned = validate_tf(parts[0], parts[1])
        except ValueError as e:
            await ctx.send(f"Couldn't add that question: `{e}`")
            return
        qid = await self._store_validated(ctx.guild.id, cleaned, ctx.author.id)
        await ctx.send(f"Added true/false question **#{qid}**: {cleaned['question']}")

    @trivia.command(name="addopen")
    async def trivia_addopen(self, ctx, *, raw: str = ""):
        """Add an open-ended question (admin)."""
        if not _is_mod(ctx.author):
            await ctx.send("You need **Manage Server** permission to add trivia questions.")
            return
        parts = [p.strip() for p in str(raw or "").split("|")]
        parts = [p for p in parts if p != ""]
        if len(parts) < 2 or len(parts) > 3:
            await ctx.send(
                "Usage: `!trivia addopen Largest ocean? | Pacific Ocean | Pacific` "
                "(3rd part = accepted alternates, comma-separated, optional)"
            )
            return
        alternates = [a.strip() for a in parts[2].split(",")] if len(parts) == 3 else []
        try:
            cleaned = validate_open(parts[0], parts[1], alternates)
        except ValueError as e:
            await ctx.send(f"Couldn't add that question: `{e}`")
            return
        qid = await self._store_validated(ctx.guild.id, cleaned, ctx.author.id)
        await ctx.send(f"Added open question **#{qid}**: {cleaned['question']}")

    @trivia.command(name="list")
    async def trivia_list(self, ctx, category: str = "all", page: int = 1):
        """List stored questions."""
        if ctx.guild is None:
            await ctx.send("Trivia lists only work in a server.")
            return
        qtype = CATEGORY_ALIASES.get(str(category or "all").lower())
        if str(category or "all").lower() not in CATEGORY_ALIASES:
            await ctx.send("Category must be `all`, `mc`, `tf`, or `open`.")
            return
        questions = await self.db.get_trivia_questions(ctx.guild.id, qtype)
        if not questions:
            await ctx.send("No trivia questions stored yet. Admins: try `!trivia seed`.")
            return
        per_page = 8
        total_pages = (len(questions) + per_page - 1) // per_page
        page = max(1, min(total_pages, int(page or 1)))
        chunk = questions[(page - 1) * per_page: page * per_page]
        lines = []
        for q in chunk:
            lines.append(
                f"`#{q['id']}` [{TYPE_LABELS.get(q['qtype'], q['qtype'])}] "
                f"{q['question']} → *{format_correct_answer(q)}*"
            )
        embed = discord.Embed(
            title=f"🎲 Trivia questions ({len(questions)} total, page {page}/{total_pages})",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        await ctx.send(embed=embed)

    @trivia.command(name="remove", aliases=["del", "delete"])
    async def trivia_remove(self, ctx, question_id: int = 0):
        """Delete one question by id (admin)."""
        if not _is_mod(ctx.author):
            await ctx.send("You need **Manage Server** permission to remove trivia questions.")
            return
        ok = await self.db.delete_trivia_question(ctx.guild.id, int(question_id or 0))
        await ctx.send(
            f"Removed question **#{question_id}**." if ok
            else f"No question **#{question_id}** in this server."
        )

    @trivia.command(name="clear")
    async def trivia_clear(self, ctx, category: str = "all"):
        """Delete all (or one type of) questions (admin)."""
        if not _is_mod(ctx.author):
            await ctx.send("You need **Manage Server** permission to clear trivia questions.")
            return
        qtype = CATEGORY_ALIASES.get(str(category or "all").lower())
        if str(category or "all").lower() not in CATEGORY_ALIASES:
            await ctx.send("Category must be `all`, `mc`, `tf`, or `open`.")
            return
        removed = await self.db.clear_trivia_questions(ctx.guild.id, qtype)
        await ctx.send(f"Cleared **{removed}** trivia question(s).")

    @trivia.command(name="seed")
    async def trivia_seed(self, ctx):
        """Insert the 5 MCQ + 5 true/false + 5 open sample set (admin)."""
        if not _is_mod(ctx.author):
            await ctx.send("You need **Manage Server** permission to seed trivia questions.")
            return
        existing = await self.db.get_trivia_questions(ctx.guild.id)
        seen = {q["question"].strip().lower() for q in existing}
        added = 0
        for seed in SEED_QUESTIONS:
            if seed["question"].strip().lower() in seen:
                continue
            try:
                if seed["qtype"] == "multiple_choice":
                    cleaned = validate_mcq(seed["question"], seed["options"], seed["answer"])
                elif seed["qtype"] == "true_false":
                    cleaned = validate_tf(seed["question"], seed["answer"])
                else:
                    cleaned = validate_open(
                        seed["question"], seed["answer"], seed.get("alternates", [])
                    )
            except ValueError:
                continue
            await self._store_validated(ctx.guild.id, cleaned, ctx.author.id)
            added += 1
        counts = await self.db.count_trivia_questions(ctx.guild.id)
        await ctx.send(
            f"Seeded **{added}** sample question(s). "
            f"Now stored: {counts['multiple_choice']} MCQ + "
            f"{counts['true_false']} true/false + {counts['open']} open "
            f"= {counts['total']} total."
        )

    @trivia.command(name="start")
    async def trivia_start(self, ctx, count: int = 10, seconds: int = 20, category: str = "all"):
        """Start a trivia game in this channel."""
        if ctx.guild is None:
            await ctx.send("Trivia games only work in a server channel.")
            return
        game, error = await self._start_game(
            ctx.guild.id, ctx.channel, ctx.author.id, count, seconds, category
        )
        if error:
            await ctx.send(error)
            return
        await ctx.send(
            f"🎲 Trivia starting — **{len(game.questions)}** questions, "
            f"{game.seconds_per_question}s each. Good luck!"
        )

    @trivia.command(name="stop")
    async def trivia_stop(self, ctx):
        """Stop the running game in this channel (host or mod)."""
        game = self.games.get(ctx.channel.id)
        if game is None:
            await ctx.send("No trivia game is running here.")
            return
        if ctx.author.id != game.host_id and not _is_mod(ctx.author):
            await ctx.send("Only the host or a mod can stop this game.")
            return
        game.cancelled = True
        if game.task is not None:
            game.task.cancel()
        self.games.pop(ctx.channel.id, None)
        self.bot.trivia_active_channels.discard(ctx.channel.id)
        await ctx.send("🛑 Trivia stopped.")

    @trivia.command(name="leaderboard", aliases=["lb", "top"])
    async def trivia_leaderboard(self, ctx):
        """Show the all-time trivia leaderboard for this server."""
        rows = await self.db.get_trivia_leaderboard(ctx.guild.id, 10)
        if not rows:
            await ctx.send("No trivia scores yet — play a game with `!trivia start`!")
            return
        lines = []
        for rank, row in enumerate(rows, start=1):
            member = ctx.guild.get_member(row["user_id"])
            name = member.display_name if member else f"<@{row['user_id']}>"
            lines.append(
                f"**{rank}.** {name} — {row['points']} point(s), {row['wins']} win(s)"
            )
        embed = discord.Embed(
            title="🏆 Trivia leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await ctx.send(embed=embed)

    @trivia.command(name="score")
    async def trivia_score(self, ctx, member: discord.Member = None):
        """Show your (or someone's) trivia score."""
        target = member or ctx.author
        score = await self.db.get_trivia_score(ctx.guild.id, target.id)
        await ctx.send(
            f"**{target.display_name}**: {score['points']} point(s), "
            f"{score['wins']} win(s)."
        )

    # ══════════════════════════════════════════
    #  Slash commands: /trivia ...
    # ══════════════════════════════════════════

    @trivia_group.command(name="add_mcq", description="Add a multiple-choice trivia question (admin)")
    @app_commands.describe(
        question="The question text",
        option_a="Option A", option_b="Option B",
        option_c="Option C", option_d="Option D",
        correct="Correct option: A, B, C, or D",
    )
    async def slash_add_mcq(self, interaction: discord.Interaction, question: str,
                            option_a: str, option_b: str, option_c: str,
                            option_d: str, correct: str):
        if interaction.guild is None or not _is_mod(interaction.user):
            await interaction.response.send_message(
                "You need **Manage Server** permission to add trivia questions.",
                ephemeral=True,
            )
            return
        try:
            cleaned = validate_mcq(
                question, [option_a, option_b, option_c, option_d], correct
            )
        except ValueError as e:
            await interaction.response.send_message(f"Couldn't add that: `{e}`", ephemeral=True)
            return
        qid = await self._store_validated(interaction.guild.id, cleaned, interaction.user.id)
        await interaction.response.send_message(
            f"Added multiple-choice question **#{qid}**: {cleaned['question']}",
            ephemeral=True,
        )

    @trivia_group.command(name="add_tf", description="Add a true/false trivia question (admin)")
    @app_commands.describe(question="The question text", answer="True or False")
    @app_commands.choices(answer=[
        app_commands.Choice(name="True", value="true"),
        app_commands.Choice(name="False", value="false"),
    ])
    async def slash_add_tf(self, interaction: discord.Interaction, question: str,
                           answer: app_commands.Choice[str]):
        if interaction.guild is None or not _is_mod(interaction.user):
            await interaction.response.send_message(
                "You need **Manage Server** permission to add trivia questions.",
                ephemeral=True,
            )
            return
        try:
            cleaned = validate_tf(question, answer.value)
        except ValueError as e:
            await interaction.response.send_message(f"Couldn't add that: `{e}`", ephemeral=True)
            return
        qid = await self._store_validated(interaction.guild.id, cleaned, interaction.user.id)
        await interaction.response.send_message(
            f"Added true/false question **#{qid}**: {cleaned['question']}",
            ephemeral=True,
        )

    @trivia_group.command(name="add_open", description="Add an open-ended trivia question (admin)")
    @app_commands.describe(
        question="The question text",
        answer="The correct answer",
        alternates="Other accepted answers, comma-separated (optional)",
    )
    async def slash_add_open(self, interaction: discord.Interaction, question: str,
                             answer: str, alternates: str = ""):
        if interaction.guild is None or not _is_mod(interaction.user):
            await interaction.response.send_message(
                "You need **Manage Server** permission to add trivia questions.",
                ephemeral=True,
            )
            return
        alt_list = [a.strip() for a in (alternates or "").split(",") if a.strip()]
        try:
            cleaned = validate_open(question, answer, alt_list)
        except ValueError as e:
            await interaction.response.send_message(f"Couldn't add that: `{e}`", ephemeral=True)
            return
        qid = await self._store_validated(interaction.guild.id, cleaned, interaction.user.id)
        await interaction.response.send_message(
            f"Added open question **#{qid}**: {cleaned['question']}",
            ephemeral=True,
        )

    @trivia_group.command(name="remove", description="Delete a trivia question by id (admin)")
    @app_commands.describe(question_id="The #id shown by /trivia list")
    async def slash_remove(self, interaction: discord.Interaction, question_id: int):
        if interaction.guild is None or not _is_mod(interaction.user):
            await interaction.response.send_message(
                "You need **Manage Server** permission.", ephemeral=True
            )
            return
        ok = await self.db.delete_trivia_question(interaction.guild.id, int(question_id))
        await interaction.response.send_message(
            f"Removed question **#{question_id}**." if ok
            else f"No question **#{question_id}** in this server.",
            ephemeral=True,
        )

    @trivia_group.command(name="list", description="List stored trivia questions")
    @app_commands.describe(category="Which type to show", page="Page number")
    @app_commands.choices(category=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Multiple choice", value="mc"),
        app_commands.Choice(name="True/False", value="tf"),
        app_commands.Choice(name="Open", value="open"),
    ])
    async def slash_list(self, interaction: discord.Interaction,
                         category: app_commands.Choice[str] = None, page: int = 1):
        if interaction.guild is None:
            await interaction.response.send_message("Trivia lists only work in a server.", ephemeral=True)
            return
        key = category.value if category else "all"
        qtype = CATEGORY_ALIASES.get(key, None)
        questions = await self.db.get_trivia_questions(interaction.guild.id, qtype)
        if not questions:
            await interaction.response.send_message(
                "No trivia questions stored yet. Admins: try `/trivia seed`.",
                ephemeral=True,
            )
            return
        per_page = 8
        total_pages = (len(questions) + per_page - 1) // per_page
        page = max(1, min(total_pages, int(page or 1)))
        chunk = questions[(page - 1) * per_page: page * per_page]
        lines = [
            f"`#{q['id']}` [{TYPE_LABELS.get(q['qtype'], q['qtype'])}] "
            f"{q['question']} → *{format_correct_answer(q)}*"
            for q in chunk
        ]
        embed = discord.Embed(
            title=f"🎲 Trivia questions ({len(questions)} total, page {page}/{total_pages})",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @trivia_group.command(name="clear", description="Delete trivia questions (admin)")
    @app_commands.describe(category="Which type to clear")
    @app_commands.choices(category=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Multiple choice", value="mc"),
        app_commands.Choice(name="True/False", value="tf"),
        app_commands.Choice(name="Open", value="open"),
    ])
    async def slash_clear(self, interaction: discord.Interaction,
                          category: app_commands.Choice[str] = None):
        if interaction.guild is None or not _is_mod(interaction.user):
            await interaction.response.send_message(
                "You need **Manage Server** permission.", ephemeral=True
            )
            return
        key = category.value if category else "all"
        qtype = CATEGORY_ALIASES.get(key, None)
        removed = await self.db.clear_trivia_questions(interaction.guild.id, qtype)
        await interaction.response.send_message(
            f"Cleared **{removed}** trivia question(s).", ephemeral=True
        )

    @trivia_group.command(name="seed", description="Add 5 MCQ + 5 true/false + 5 open samples (admin)")
    async def slash_seed(self, interaction: discord.Interaction):
        if interaction.guild is None or not _is_mod(interaction.user):
            await interaction.response.send_message(
                "You need **Manage Server** permission.", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        existing = await self.db.get_trivia_questions(interaction.guild.id)
        seen = {q["question"].strip().lower() for q in existing}
        added = 0
        for seed in SEED_QUESTIONS:
            if seed["question"].strip().lower() in seen:
                continue
            try:
                if seed["qtype"] == "multiple_choice":
                    cleaned = validate_mcq(seed["question"], seed["options"], seed["answer"])
                elif seed["qtype"] == "true_false":
                    cleaned = validate_tf(seed["question"], seed["answer"])
                else:
                    cleaned = validate_open(
                        seed["question"], seed["answer"], seed.get("alternates", [])
                    )
            except ValueError:
                continue
            await self._store_validated(interaction.guild.id, cleaned, interaction.user.id)
            added += 1
        counts = await self.db.count_trivia_questions(interaction.guild.id)
        await interaction.followup.send(
            f"Seeded **{added}** sample question(s). "
            f"Now stored: {counts['multiple_choice']} MCQ + "
            f"{counts['true_false']} true/false + {counts['open']} open "
            f"= {counts['total']} total.",
            ephemeral=True,
        )

    @trivia_group.command(name="start", description="Start a trivia game in this channel")
    @app_commands.describe(
        count="How many questions (1-25, default 10)",
        seconds="Seconds per question (10-60, default 20)",
        category="Which type to play",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="All mixed", value="all"),
        app_commands.Choice(name="Multiple choice", value="mc"),
        app_commands.Choice(name="True/False", value="tf"),
        app_commands.Choice(name="Open", value="open"),
    ])
    async def slash_start(self, interaction: discord.Interaction, count: int = 10,
                          seconds: int = 20, category: app_commands.Choice[str] = None):
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message(
                "Trivia games only work in a server channel.", ephemeral=True
            )
            return
        game, error = await self._start_game(
            interaction.guild.id, interaction.channel, interaction.user.id,
            count, seconds, category.value if category else "all",
        )
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.send_message(
            f"🎲 Trivia starting — **{len(game.questions)}** questions, "
            f"{game.seconds_per_question}s each. Good luck!"
        )

    @trivia_group.command(name="stop", description="Stop the trivia game in this channel")
    async def slash_stop(self, interaction: discord.Interaction):
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("No game here.", ephemeral=True)
            return
        game = self.games.get(interaction.channel.id)
        if game is None:
            await interaction.response.send_message("No trivia game is running here.", ephemeral=True)
            return
        if interaction.user.id != game.host_id and not _is_mod(interaction.user):
            await interaction.response.send_message(
                "Only the host or a mod can stop this game.", ephemeral=True
            )
            return
        game.cancelled = True
        if game.task is not None:
            game.task.cancel()
        self.games.pop(interaction.channel.id, None)
        self.bot.trivia_active_channels.discard(interaction.channel.id)
        await interaction.response.send_message("🛑 Trivia stopped.")

    @trivia_group.command(name="leaderboard", description="Show the server trivia leaderboard")
    async def slash_leaderboard(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        rows = await self.db.get_trivia_leaderboard(interaction.guild.id, 10)
        if not rows:
            await interaction.response.send_message("No trivia scores yet!", ephemeral=True)
            return
        lines = []
        for rank, row in enumerate(rows, start=1):
            member = interaction.guild.get_member(row["user_id"])
            name = member.display_name if member else f"<@{row['user_id']}>"
            lines.append(
                f"**{rank}.** {name} — {row['points']} point(s), {row['wins']} win(s)"
            )
        embed = discord.Embed(
            title="🏆 Trivia leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    @trivia_group.command(name="score", description="Show a trivia score")
    @app_commands.describe(member="Whose score to show (default: you)")
    async def slash_score(self, interaction: discord.Interaction, member: discord.Member = None):
        if interaction.guild is None:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        target = member or interaction.user
        score = await self.db.get_trivia_score(interaction.guild.id, target.id)
        name = target.display_name if hasattr(target, "display_name") else str(target)
        await interaction.response.send_message(
            f"**{name}**: {score['points']} point(s), {score['wins']} win(s).",
            ephemeral=True,
        )


async def setup(bot):
    db = getattr(bot, "db", None)
    if db is None:
        from engine.database import Database

        db = Database()
        await db.init()
        bot.db = db
    await bot.add_cog(TriviaCog(bot, db))
    logger.info("Trivia cog loaded (trivia questions + game loop)")
