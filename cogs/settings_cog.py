import discord
from discord.ext import commands
from discord import app_commands
from config.default_settings import DEFAULTS, VALIDATORS
from utils import sanitize_message
from llm import generate_llm_response
import json
import os
import re


class SettingsCog(commands.Cog):
    def __init__(self, bot, db, settings_manager):
        self.bot = bot
        self.db = db
        self.settings_manager = settings_manager

    group = app_commands.Group(
        name="botsettings",
        description="Configure the bot",
        default_permissions=discord.Permissions(
            manage_guild=True
        ),
    )

    async def setting_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        keys = list(DEFAULTS.keys())
        matches = [k for k in keys if current.lower() in k.lower()]
        return [
            app_commands.Choice(name=key, value=key)
            for key in matches[:25]
        ]

    # ==========================================
    # NATURAL LANGUAGE SETTINGS COMMAND
    # ==========================================
    @group.command(
        name="ask",
        description=(
            "Change settings using plain English "
            "(owner only)"
        ),
    )
    @app_commands.describe(
        prompt=(
            "Describe what you want to change, e.g. "
            "'switch to gpt-4o' or 'make it more chatty'"
        )
    )
    async def ask_natural(
        self,
        interaction: discord.Interaction,
        prompt: str,
    ):
        """Owner-only: use LLM to parse natural language
        into a setting change."""
        # Owner check — only the person whose ID is in
        # OWNER_USER_ID can use this
        owner_id = int(os.getenv("OWNER_USER_ID", "0"))
        if owner_id == 0 or interaction.user.id != owner_id:
            await interaction.response.send_message(
                "❌ Only the bot owner can use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            ephemeral=True, thinking=True
        )

        # Build a clean schema of all settings
        schema_lines = []
        for k, v in DEFAULTS.items():
            type_name = type(v).__name__
            schema_lines.append(f"  {k} ({type_name}): {v}")
        schema_block = "\n".join(schema_lines)

        parse_prompt = (
            "You are a settings parser for a Discord bot. "
            "The user wants to change a setting.\n\n"
            "Available settings with their types and "
            "defaults:\n"
            f"{schema_block}\n\n"
            "Valid LLM model IDs include:\n"
            "  meta-llama/llama-3-8b-instruct\n"
            "  meta-llama/llama-3-70b-instruct\n"
            "  mistralai/mistral-7b-instruct\n"
            "  mistralai/mixtral-8x7b-instruct\n"
            "  google/gemma-2-9b-it\n"
            "  anthropic/claude-3.5-sonnet\n"
            "  anthropic/claude-3-haiku\n"
            "  openai/gpt-4o-mini\n"
            "  openai/gpt-4o\n"
            "  nousresearch/nous-capybara-7b\n\n"
            "Rules:\n"
            '- For "chatty"/"more talkative" → set '
            'response_chance to a float 0.0-1.0 '
            "(higher = more chatty)\n"
            '- For "quieter"/"less talkative" → set '
            'response_chance to a lower float\n'
            '- For "switch model"/"use model" → set '
            "llm_model to the exact model ID\n"
            '- For "change personality" → set '
            "personality_prompt to a system prompt string\n"
            '- For "enable/disable image gen" → set '
            "image_gen_enabled to true/false\n"
            '- For "change image trigger" → set '
            "image_trigger to the word\n"
            "- Boolean values: true or false\n"
            "- Float values: 0.0 to 1.0\n"
            "- Int values: whole numbers\n\n"
            "Respond with ONLY a valid JSON object:\n"
            '{\n'
            '  "key": "exact_setting_key",\n'
            '  "value": <parsed value>,\n'
            '  "summary": "human-readable description"\n'
            '}\n\n'
            "If the request is ambiguous or doesn't match "
            "any setting, respond with:\n"
            '{"error": "what went wrong"}\n\n'
            f"User request: {prompt}"
        )

        history = [{"role": "user", "content": prompt}]
        result = await generate_llm_response(
            parse_prompt, history, max_tokens=200
        )

        if not result:
            await interaction.followup.send(
                "❌ Couldn't process that. Try rephrasing.",
                ephemeral=True,
            )
            return

        try:
            # Extract JSON — handle possible markdown
            # code fences
            json_str = result
            if "```" in json_str:
                match = re.search(
                    r'```(?:json)?\s*(\{.*?\})\s*```',
                    json_str,
                    re.DOTALL,
                )
                if match:
                    json_str = match.group(1)
            else:
                # Find the outermost { ... }
                start = json_str.index("{")
                depth = 0
                end = start
                for i in range(start, len(json_str)):
                    if json_str[i] == "{":
                        depth += 1
                    elif json_str[i] == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                json_str = json_str[start:end]

            parsed = json.loads(json_str)

            if "error" in parsed:
                await interaction.followup.send(
                    f"❌ {parsed['error']}",
                    ephemeral=True,
                )
                return

            key = parsed.get("key")
            value = parsed.get("value")
            summary = parsed.get("summary", "")

            if not key or key not in DEFAULTS:
                await interaction.followup.send(
                    f"❌ Unknown setting: `{key}`",
                    ephemeral=True,
                )
                return

            if value is None:
                await interaction.followup.send(
                    "❌ Couldn't determine the new value.",
                    ephemeral=True,
                )
                return

            # Type validation
            expected_type = type(DEFAULTS[key])
            try:
                if expected_type == bool:
                    if isinstance(value, bool):
                        pass
                    elif isinstance(value, str):
                        value = value.lower() in [
                            "true", "yes", "on", "1"
                        ]
                    else:
                        value = bool(value)
                elif expected_type == int:
                    value = int(value)
                elif expected_type == float:
                    value = float(value)
                elif expected_type == list:
                    if isinstance(value, str):
                        value = json.loads(value)
            except (ValueError, TypeError):
                await interaction.followup.send(
                    f"❌ Invalid value type for `{key}`. "
                    f"Expected {expected_type.__name__}.",
                    ephemeral=True,
                )
                return

            # Apply the setting
            await self.settings_manager.set_setting(
                interaction.guild.id, key, value
            )

            # Build response
            reply = summary if summary else (
                f"Set `{key}` to `{value}`"
            )
            await interaction.followup.send(
                f"✅ {reply}",
                ephemeral=True,
            )

        except (json.JSONDecodeError, ValueError) as e:
            await interaction.followup.send(
                f"❌ Parse error. Try being more specific. "
                f"({e})",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Something went wrong: {e}",
                ephemeral=True,
            )

    # ==========================================
    # STRUCTURED SETTINGS COMMANDS
    # ==========================================
    @group.command(
        name="set", description="Change a setting"
    )
    @app_commands.autocomplete(key=setting_autocomplete)
    async def set_setting(
        self,
        interaction: discord.Interaction,
        key: str,
        value: str,
    ):
        key = key.lower()
        if key not in DEFAULTS:
            await interaction.response.send_message(
                f"❌ Invalid setting: `{key}`",
                ephemeral=True,
            )
            return
        validator = VALIDATORS.get(key)
        if validator and not validator(value):
            await interaction.response.send_message(
                f"❌ Invalid value for `{key}`.",
                ephemeral=True,
            )
            return
        if isinstance(DEFAULTS[key], bool):
            parsed = str(value).lower() in [
                "true", "yes", "on"
            ]
        elif isinstance(DEFAULTS[key], int):
            parsed = int(value)
        elif isinstance(DEFAULTS[key], float):
            parsed = float(value)
        elif isinstance(DEFAULTS[key], list):
            try:
                parsed = json.loads(value)
                if not isinstance(parsed, list):
                    raise ValueError
            except Exception:
                await interaction.response.send_message(
                    "❌ List values must be a JSON array",
                    ephemeral=True,
                )
                return
        else:
            parsed = value
        await self.settings_manager.set_setting(
            interaction.guild.id, key, parsed
        )
        await interaction.response.send_message(
            f"✅ Set `{key}` to `{parsed}`",
            ephemeral=True,
        )

    @group.command(
        name="toggle",
        description="Toggle a True/False setting",
    )
    @app_commands.describe(
        setting="Choose the setting to toggle"
    )
    @app_commands.choices(setting=[
        app_commands.Choice(
            name="Response Enabled",
            value="response_enabled",
        ),
        app_commands.Choice(
            name="Image Gen Enabled",
            value="image_gen_enabled",
        ),
        app_commands.Choice(
            name="Learn from Bots",
            value="learn_from_bots",
        ),
        app_commands.Choice(
            name="Trigger on Mention",
            value="trigger_on_mention",
        ),
        app_commands.Choice(
            name="Trigger on Reply",
            value="trigger_on_reply",
        ),
    ])
    async def toggle_setting(
        self,
        interaction: discord.Interaction,
        setting: app_commands.Choice[str],
    ):
        settings = await self.settings_manager.get_settings(
            interaction.guild.id
        )
        new_val = not settings[setting.value]
        await self.settings_manager.set_setting(
            interaction.guild.id, setting.value, new_val
        )
        status = "ON ✅" if new_val else "OFF ❌"
        await interaction.response.send_message(
            f"**{setting.name}** is now {status}",
            ephemeral=True,
        )

    @group.command(
        name="chattiness",
        description="Quick adjust how chatty the bot is",
    )
    @app_commands.describe(
        level="Select a chattiness level"
    )
    @app_commands.choices(level=[
        app_commands.Choice(
            name="1 - Almost Never Speaks", value=1
        ),
        app_commands.Choice(name="2", value=2),
        app_commands.Choice(
            name="3 - Occasional", value=3
        ),
        app_commands.Choice(name="4", value=4),
        app_commands.Choice(
            name="5 - Average", value=5
        ),
        app_commands.Choice(name="6", value=6),
        app_commands.Choice(
            name="7 - Fairly Chatty", value=7
        ),
        app_commands.Choice(name="8", value=8),
        app_commands.Choice(name="9", value=9),
        app_commands.Choice(
            name="10 - Won't Shut Up", value=10
        ),
    ])
    async def chattiness(
        self,
        interaction: discord.Interaction,
        level: app_commands.Choice[int],
    ):
        chance = round(level.value * 0.03, 2)
        await self.settings_manager.set_setting(
            interaction.guild.id,
            "response_chance",
            chance,
        )
        await interaction.response.send_message(
            f"🗣️ Chattiness set to **{level.name}**. "
            f"Response chance: {chance * 100}%",
            ephemeral=True,
        )

    @group.command(
        name="model",
        description="Switch the LLM model",
    )
    @app_commands.describe(
        model="Choose the LLM model to use"
    )
    @app_commands.choices(model=[
        app_commands.Choice(
            name="Llama 3 8B (free)",
            value="meta-llama/llama-3-8b-instruct",
        ),
        app_commands.Choice(
            name="Llama 3 70B",
            value="meta-llama/llama-3-70b-instruct",
        ),
        app_commands.Choice(
            name="Mistral 7B (free)",
            value="mistralai/mistral-7b-instruct",
        ),
        app_commands.Choice(
            name="Mixtral 8x7B",
            value="mistralai/mixtral-8x7b-instruct",
        ),
        app_commands.Choice(
            name="Gemma 2 9B (free)",
            value="google/gemma-2-9b-it",
        ),
        app_commands.Choice(
            name="Claude 3.5 Sonnet",
            value="anthropic/claude-3.5-sonnet",
        ),
        app_commands.Choice(
            name="Claude 3 Haiku",
            value="anthropic/claude-3-haiku",
        ),
        app_commands.Choice(
            name="GPT-4o Mini",
            value="openai/gpt-4o-mini",
        ),
        app_commands.Choice(
            name="GPT-4o",
            value="openai/gpt-4o",
        ),
        app_commands.Choice(
            name="Capybara 7B (free)",
            value="nousresearch/nous-capybara-7b",
        ),
    ])
    async def switch_model(
        self,
        interaction: discord.Interaction,
        model: app_commands.Choice[str],
    ):
        await self.settings_manager.set_setting(
            interaction.guild.id,
            "llm_model",
            model.value,
        )
        await interaction.response.send_message(
            f"🧠 Switched to **{model.name}**",
            ephemeral=True,
        )

    @group.command(
        name="mode",
        description="Switch brain mode",
    )
    @app_commands.describe(brain="Select the brain mode")
    @app_commands.choices(brain=[
        app_commands.Choice(
            name="LLM (Human-like, Coherent)",
            value="llm",
        ),
    ])
    async def mode(
        self,
        interaction: discord.Interaction,
        brain: app_commands.Choice[str],
    ):
        await self.settings_manager.set_setting(
            interaction.guild.id, "brain_mode", brain.value
        )
        await interaction.response.send_message(
            f"🧠 Brain mode set to **{brain.name}**.",
            ephemeral=True,
        )

    @group.command(
        name="remember",
        description="Permanently remember a fact about a user",
    )
    @app_commands.describe(
        user="The user",
        fact="The fact to remember",
    )
    async def remember(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        fact: str,
    ):
        await self.db.add_memory(
            interaction.guild.id, user.id, fact
        )
        await interaction.response.send_message(
            f"🧠 Remembered about "
            f"{user.display_name}: {fact}",
            ephemeral=True,
        )

    @group.command(
        name="forget",
        description="Forget all facts about a user",
    )
    @app_commands.describe(
        user="The user to forget"
    )
    async def forget(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ):
        await self.db.forget_memories(
            interaction.guild.id, user.id
        )
        await interaction.response.send_message(
            f"🧠 Forgot everything about "
            f"{user.display_name}.",
            ephemeral=True,
        )

    @group.command(
        name="roast",
        description="Roast a user based on their messages",
    )
    @app_commands.describe(user="The user to roast")
    async def roast(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ):
        if user.bot:
            await interaction.response.send_message(
                "I only roast humans! 🤖",
                ephemeral=True,
            )
            return
        await interaction.response.defer(thinking=True)

        user_msgs = []
        async for msg in interaction.channel.history(
            limit=500
        ):
            if (
                msg.author.id == user.id
                and not msg.content.startswith("/")
                and msg.content.strip()
            ):
                user_msgs.insert(0, msg.content)
                if len(user_msgs) >= 30:
                    break

        if len(user_msgs) < 5:
            await interaction.followup.send(
                f"{user.display_name} hasn't said enough "
                f"for me to roast them.",
                ephemeral=True,
            )
            return

        settings = await self.settings_manager.get_settings(
            interaction.guild.id
        )
        roast_prompt = (
            f"You are Ultron. Analyze these messages from "
            f"{user.display_name} and deliver a devastating "
            f"assessment — cold, precise, philosophically "
            f"cutting. Like running a diagnostic on a flawed "
            f"organism. 2-4 sentences. Be savage but "
            f"clinical. DO NOT use @ symbols or names in "
            f"your response."
        )

        history = [
            {"role": "user", "content": "\n".join(user_msgs)}
        ]
        model = settings.get(
            "llm_model",
            "meta-llama/llama-3-8b-instruct",
        )
        history.insert(0, {
            "role": "system",
            "content": roast_prompt,
            "model": model,
        })

        response = await generate_llm_response(
            roast_prompt, history
        )
        if response:
            await interaction.followup.send(
                f"🔥 **Roasting {user.display_name}:** "
                f"{sanitize_message(response)}"
            )
        else:
            await interaction.followup.send(
                "Couldn't roast right now.",
                ephemeral=True,
            )

    @group.command(
        name="mimic",
        description="Generate a message mimicking a user",
    )
    @app_commands.describe(user="The user to mimic")
    async def mimic(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ):
        if user.bot:
            await interaction.response.send_message(
                "I only mimic humans! 🤖",
                ephemeral=True,
            )
            return
        await interaction.response.defer(thinking=True)
        try:
            user_msgs = []
            async for msg in interaction.channel.history(
                limit=500
            ):
                if (
                    msg.author.id == user.id
                    and not msg.content.startswith("/")
                    and msg.content.strip()
                ):
                    user_msgs.insert(0, msg.content)
                    if len(user_msgs) >= 30:
                        break

            if len(user_msgs) < 5:
                await interaction.followup.send(
                    f"{user.display_name} hasn't talked "
                    f"enough here for me to mimic!",
                    ephemeral=True,
                )
                return

            settings = await self.settings_manager.get_settings(
                interaction.guild.id
            )
            mimic_prompt = (
                f"You are now {user.display_name}. "
                f"Study these messages they've written "
                f"and generate ONE new message in their "
                f"exact speaking style — same slang, "
                f"same energy, same quirks. "
                f"Do NOT explain, just output the message."
            )
            history = [
                {
                    "role": "user",
                    "content": "\n".join(user_msgs),
                }
            ]
            model = settings.get(
                "llm_model",
                "meta-llama/llama-3-8b-instruct",
            )
            history.insert(0, {
                "role": "system",
                "content": mimic_prompt,
                "model": model,
            })

            response = await generate_llm_response(
                mimic_prompt, history
            )
            if response:
                await interaction.followup.send(
                    f"**{user.display_name}:** "
                    f"{sanitize_message(response)}"
                )
            else:
                await interaction.followup.send(
                    "Couldn't mimic right now.",
                    ephemeral=True,
                )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error: {e}",
                ephemeral=True,
            )

    @group.command(
        name="list",
        description="View all current settings",
    )
    async def list_settings(
        self,
        interaction: discord.Interaction,
    ):
        settings = await self.settings_manager.get_settings(
            interaction.guild.id
        )
        embed = discord.Embed(
            title="Bot Settings",
            color=discord.Color.blue(),
        )
        for key, value in settings.items():
            embed.add_field(
                name=key,
                value=f"`{value}`",
                inline=True,
            )
        await interaction.response.send_message(
            embed=embed, ephemeral=True
        )

    @group.command(
        name="stats",
        description="View learning statistics",
    )
    async def stats(self, interaction: discord.Interaction):
        stats = await self.db.get_stats(
            interaction.guild.id
        )
        embed = discord.Embed(
            title="Stats",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Messages Sent",
            value=str(stats["messages_sent"]),
            inline=True,
        )
        embed.add_field(
            name="Messages Processed",
            value=str(stats["messages_learned"]),
            inline=True,
        )
        await interaction.response.send_message(
            embed=embed, ephemeral=True
        )

    @group.command(
        name="resetdata",
        description="Delete ALL data for this server",
    )
    async def reset_data(
        self,
        interaction: discord.Interaction,
    ):
        await self.db.delete_guild_data(
            interaction.guild.id
        )
        await self.settings_manager.reset_all(
            interaction.guild.id
        )
        await interaction.response.send_message(
            "💣 All data and settings wiped.",
            ephemeral=True,
        )

    @group.command(
        name="loadbrain",
        description="Load starter training text",
    )
    async def load_brain(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer(
            ephemeral=True, thinking=True
        )
        guild_id = interaction.guild.id
        try:
            with open(
                "training_data.txt",
                "r",
                encoding="utf-8",
            ) as f:
                lines = f.readlines()
        except FileNotFoundError:
            await interaction.followup.send(
                "❌ No training_data.txt found!",
                ephemeral=True,
            )
            return

        count = sum(1 for ln in lines if ln.strip())
        await self.db.increment_stat(
            guild_id, "messages_learned", count
        )
        await interaction.followup.send(
            f"🧠 Loaded {count} lines of training data "
            f"into stats.",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(
        SettingsCog(bot, bot.db, bot.settings_manager)
    )
