import asyncio
import random
import re

import discord
from discord import app_commands
from discord.ext import commands


QUESTIONS_PER_TYPE = 5
QUESTION_SECONDS = 20
QUESTION_TYPES = ("multiple_choice", "true_false", "open_ended")
TYPE_LABELS = {
    "multiple_choice": "Multiple Choice",
    "true_false": "True or False",
    "open_ended": "Open Ended",
}


def normalize_answer(value):
    """Normalize free-text answers without changing meaningful letters or numbers."""
    return re.sub(r"[^\w\s]", "", str(value).casefold()).strip()


def answer_is_correct(question, answer):
    submitted = normalize_answer(answer)
    accepted = [
        normalize_answer(item)
        for item in str(question["answer"]).split("|")
        if normalize_answer(item)
    ]
    return bool(submitted) and submitted in accepted


def prepare_question(question_type, question, answer, options_text=""):
    question = (question or "").strip()
    answer = (answer or "").strip()
    if question_type not in QUESTION_TYPES:
        raise ValueError("Choose multiple choice, true/false, or open ended.")
    if not question or len(question) > 500:
        raise ValueError("The question must be between 1 and 500 characters.")
    if not answer or len(answer) > 200:
        raise ValueError("The answer must be between 1 and 200 characters.")

    options = []
    if question_type == "multiple_choice":
        options = [item.strip() for item in (options_text or "").split(",") if item.strip()]
        if not 2 <= len(options) <= 5:
            raise ValueError("Multiple-choice questions need 2 to 5 comma-separated options.")
        if len({normalize_answer(item) for item in options}) != len(options):
            raise ValueError("Multiple-choice options must be unique.")
        matching = [item for item in options if normalize_answer(item) == normalize_answer(answer)]
        if not matching:
            raise ValueError("The answer must exactly match one of the options.")
        answer = matching[0]
    elif question_type == "true_false":
        normalized = normalize_answer(answer)
        if normalized not in {"true", "false"}:
            raise ValueError("A true/false answer must be `true` or `false`.")
        answer = normalized.title()
    else:
        accepted = [item.strip() for item in answer.split("|") if item.strip()]
        if not accepted:
            raise ValueError("Provide at least one accepted answer.")
        answer = "|".join(accepted)

    return question, answer, options


class AnswerButton(discord.ui.Button):
    def __init__(self, game, question_index, label, value, style=discord.ButtonStyle.primary):
        super().__init__(label=label[:80], style=style)
        self.game = game
        self.question_index = question_index
        self.value = value

    async def callback(self, interaction):
        await self.game.submit_answer(interaction, self.question_index, self.value)


class OpenAnswerModal(discord.ui.Modal, title="Submit your answer"):
    answer = discord.ui.TextInput(
        label="Answer",
        placeholder="Type your answer here",
        min_length=1,
        max_length=200,
    )

    def __init__(self, game, question_index):
        super().__init__()
        self.game = game
        self.question_index = question_index

    async def on_submit(self, interaction):
        await self.game.submit_answer(interaction, self.question_index, str(self.answer))


class OpenAnswerButton(discord.ui.Button):
    def __init__(self, game, question_index):
        super().__init__(label="Type Answer", style=discord.ButtonStyle.primary, emoji="✍️")
        self.game = game
        self.question_index = question_index

    async def callback(self, interaction):
        if self.game.has_answered(interaction.user.id, self.question_index):
            await interaction.response.send_message(
                "You already answered this question.", ephemeral=True
            )
            return
        await interaction.response.send_modal(OpenAnswerModal(self.game, self.question_index))


class TriviaQuestionView(discord.ui.View):
    def __init__(self, game, question_index, question):
        super().__init__(timeout=None)
        if question["type"] == "multiple_choice":
            for index, option in enumerate(question["options"]):
                self.add_item(
                    AnswerButton(
                        game,
                        question_index,
                        f"{chr(65 + index)}. {option}",
                        option,
                    )
                )
        elif question["type"] == "true_false":
            self.add_item(
                AnswerButton(
                    game,
                    question_index,
                    "True",
                    "True",
                    discord.ButtonStyle.success,
                )
            )
            self.add_item(
                AnswerButton(
                    game,
                    question_index,
                    "False",
                    "False",
                    discord.ButtonStyle.danger,
                )
            )
        else:
            self.add_item(OpenAnswerButton(game, question_index))


class TriviaGame:
    def __init__(self, cog, channel, questions):
        self.cog = cog
        self.channel = channel
        self.questions = questions
        self.index = -1
        self.answers = {}
        self.scores = {}
        self.message = None
        self.view = None
        self.timer_task = None
        self.closed = False
        self.lock = asyncio.Lock()

    def has_answered(self, user_id, question_index):
        return self.index != question_index or user_id in self.answers

    async def start(self):
        await self.channel.send(
            "🎉 **Trivia is starting!** There are 15 questions: 5 multiple choice, "
            "5 true/false, and 5 open ended. You have 20 seconds per question."
        )
        await self.next_question()

    async def next_question(self):
        async with self.lock:
            if self.closed:
                return
            self.index += 1
            if self.index >= len(self.questions):
                self.closed = True
                finish = True
            else:
                finish = False
                self.answers = {}
                question = self.questions[self.index]
                self.view = TriviaQuestionView(self, self.index, question)
                embed = self._question_embed(question)

        if finish:
            await self.finish()
            return
        self.message = await self.channel.send(embed=embed, view=self.view)
        self.timer_task = asyncio.create_task(self._question_timer(self.index))

    def _question_embed(self, question):
        embed = discord.Embed(
            title=f"Question {self.index + 1}/{len(self.questions)}",
            description=question["question"],
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Type", value=TYPE_LABELS[question["type"]], inline=True)
        embed.add_field(name="Time", value=f"{QUESTION_SECONDS} seconds", inline=True)
        if question["type"] == "multiple_choice":
            choices = "\n".join(
                f"**{chr(65 + index)}.** {option}"
                for index, option in enumerate(question["options"])
            )
            embed.add_field(name="Choices", value=choices, inline=False)
        embed.set_footer(text="Answers are private until time expires.")
        return embed

    async def submit_answer(self, interaction, question_index, value):
        async with self.lock:
            if self.closed or self.index != question_index:
                message = "That question is already closed."
            elif interaction.user.id in self.answers:
                message = "You already answered this question."
            else:
                question = self.questions[self.index]
                correct = answer_is_correct(question, value)
                self.answers[interaction.user.id] = value
                if correct:
                    self.scores[interaction.user.id] = self.scores.get(interaction.user.id, 0) + 1
                message = "Answer locked in!"
        await interaction.response.send_message(message, ephemeral=True)

    async def _question_timer(self, question_index):
        await asyncio.sleep(QUESTION_SECONDS)
        await self.close_question(question_index)

    async def close_question(self, question_index):
        async with self.lock:
            if self.closed or self.index != question_index:
                return
            question = self.questions[self.index]
            answer_count = len(self.answers)
            for child in self.view.children:
                child.disabled = True
            view = self.view
            message = self.message

        try:
            if message:
                await message.edit(view=view)
        except discord.HTTPException:
            pass
        display_answer = str(question["answer"]).replace("|", " / ")
        await self.channel.send(
            f"⏰ **Time!** The answer was **{discord.utils.escape_markdown(display_answer)}**. "
            f"{answer_count} player(s) answered."
        )
        await asyncio.sleep(3)
        await self.next_question()

    async def finish(self):
        self.cog.games.pop(self.channel.id, None)
        if not self.scores:
            await self.channel.send("🏁 **Trivia finished!** No correct answers were submitted.")
            return
        ranking = sorted(self.scores.items(), key=lambda item: (-item[1], item[0]))
        lines = []
        for place, (user_id, score) in enumerate(ranking[:10], start=1):
            lines.append(f"**{place}.** <@{user_id}> — **{score}/{len(self.questions)}**")
        embed = discord.Embed(
            title="🏆 Trivia Results",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await self.channel.send(embed=embed)

    async def stop(self):
        async with self.lock:
            if self.closed:
                return
            self.closed = True
            if self.timer_task:
                self.timer_task.cancel()
            if self.view:
                for child in self.view.children:
                    child.disabled = True
        if self.message and self.view:
            try:
                await self.message.edit(view=self.view)
            except discord.HTTPException:
                pass
        self.cog.games.pop(self.channel.id, None)
        await self.channel.send("🛑 Trivia was stopped by an admin.")


class TriviaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.games = {}

    trivia = app_commands.Group(name="trivia", description="Create and play server trivia")

    @trivia.command(name="add", description="Add a question to this server's trivia bank")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        question_type="The kind of trivia question",
        question="The question to ask",
        answer="Correct answer; separate accepted open answers with |",
        options="Multiple choice only: 2-5 comma-separated choices",
    )
    @app_commands.choices(
        question_type=[
            app_commands.Choice(name="Multiple Choice", value="multiple_choice"),
            app_commands.Choice(name="True or False", value="true_false"),
            app_commands.Choice(name="Open Ended", value="open_ended"),
        ]
    )
    async def add_question(
        self,
        interaction: discord.Interaction,
        question_type: app_commands.Choice[str],
        question: str,
        answer: str,
        options: str = "",
    ):
        if not interaction.guild:
            await interaction.response.send_message("Trivia is only available in servers.", ephemeral=True)
            return
        try:
            clean_question, clean_answer, clean_options = prepare_question(
                question_type.value, question, answer, options
            )
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        question_id = await self.db.add_trivia_question(
            interaction.guild.id,
            question_type.value,
            clean_question,
            clean_answer,
            clean_options,
            interaction.user.id,
        )
        await interaction.response.send_message(
            f"Added **{TYPE_LABELS[question_type.value]}** question `#{question_id}`.",
            ephemeral=True,
        )

    @trivia.command(name="questions", description="List this server's trivia questions")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def list_questions(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Trivia is only available in servers.", ephemeral=True)
            return
        questions = await self.db.get_trivia_questions(interaction.guild.id)
        counts = {
            kind: sum(item["type"] == kind for item in questions) for kind in QUESTION_TYPES
        }
        lines = [
            f"**{TYPE_LABELS[kind]}:** {counts[kind]}/{QUESTIONS_PER_TYPE} required"
            for kind in QUESTION_TYPES
        ]
        if questions:
            lines.append("")
            for item in questions[:15]:
                preview = item["question"].replace("\n", " ")
                if len(preview) > 70:
                    preview = preview[:67] + "..."
                lines.append(f"`#{item['id']}` [{TYPE_LABELS[item['type']]}] {preview}")
            if len(questions) > 15:
                lines.append(f"…and {len(questions) - 15} more.")
        else:
            lines.append("\nNo questions have been added yet.")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @trivia.command(name="delete", description="Delete a trivia question by its ID")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(question_id="The ID shown by /trivia questions")
    async def delete_question(self, interaction: discord.Interaction, question_id: int):
        if not interaction.guild:
            await interaction.response.send_message("Trivia is only available in servers.", ephemeral=True)
            return
        deleted = await self.db.delete_trivia_question(interaction.guild.id, question_id)
        message = f"Deleted trivia question `#{question_id}`." if deleted else "Question not found."
        await interaction.response.send_message(message, ephemeral=True)

    @trivia.command(name="start", description="Start a 15-question trivia game in this channel")
    async def start_trivia(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Trivia is only available in servers.", ephemeral=True)
            return
        if interaction.channel_id in self.games:
            await interaction.response.send_message(
                "A trivia game is already running in this channel.", ephemeral=True
            )
            return
        bank = await self.db.get_trivia_questions(interaction.guild.id)
        selected = []
        missing = []
        for kind in QUESTION_TYPES:
            candidates = [item for item in bank if item["type"] == kind]
            if len(candidates) < QUESTIONS_PER_TYPE:
                missing.append(
                    f"{TYPE_LABELS[kind]}: {len(candidates)}/{QUESTIONS_PER_TYPE}"
                )
            else:
                selected.extend(random.sample(candidates, QUESTIONS_PER_TYPE))
        if missing:
            await interaction.response.send_message(
                "The question bank is not ready yet. Admins need to add:\n" + "\n".join(missing),
                ephemeral=True,
            )
            return
        random.shuffle(selected)
        game = TriviaGame(self, interaction.channel, selected)
        self.games[interaction.channel_id] = game
        await interaction.response.send_message("Starting trivia!", ephemeral=True)
        try:
            await game.start()
        except Exception:
            self.games.pop(interaction.channel_id, None)
            raise

    @trivia.command(name="stop", description="Stop the trivia game in this channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def stop_trivia(self, interaction: discord.Interaction):
        game = self.games.get(interaction.channel_id)
        if not game:
            await interaction.response.send_message(
                "There is no trivia game running in this channel.", ephemeral=True
            )
            return
        await interaction.response.send_message("Stopping trivia.", ephemeral=True)
        await game.stop()

    async def cog_unload(self):
        for game in list(self.games.values()):
            if game.timer_task:
                game.timer_task.cancel()

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            message = "You need the **Manage Server** permission to use that command."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return
        raise error


async def setup(bot):
    await bot.add_cog(TriviaCog(bot))
