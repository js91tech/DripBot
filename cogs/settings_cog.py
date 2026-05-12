import discord
from discord.ext import commands
from discord import app_commands
from config.default_settings import DEFAULTS, VALIDATORS
from utils import sanitize_message
from llm import generate_llm_response
import json


class SettingsCog(commands.Cog):
    def __init__(self, bot, db, settings_manager):
        self.bot = bot
        self.db = db
        self.settings_manager = settings_manager

    group = app_commands.Group(
        name="botsettings",
        description="Configure the bot",
        default_permissions=discord.Permissions(
            manage_guild=True),
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

    @group.command(name="set", description="Change a setting")
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
            parsed = str(value).lower() in ["true", "yes", "on"]
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
    @app_commands.describe(setting="Choose the setting to toggle")
    @app_commands.choices(setting=[
        app_commands.Choice(
            name="Response Enabled",
            value="response_enabled",
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
    @app_commands.describe(level="Select a chattiness level")
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
            interaction.guild.id, "response_chance", chance
        )
        await interaction.response.send_message(
            f"🗣️ Chattiness set to **{level.name}**. "
            f"Response chance: {chance * 100}%",
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
            f"🧠 Remembered about {user.display_name}: {fact}",
            ephemeral=True,
        )

    @group.command(
        name="forget",
        description="Forget all facts about a user",
    )
    @app_commands.describe(user="The user to forget")
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
        async for msg in interaction.channel.history(limit=500):
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
            f"You are a ruthless, sarcastic smart-ass. "
            f"Analyze these messages from "
            f"{user.display_name} and deliver a "
            f"devastating, witty roast. "
            f"Keep it 2-4 sentences. Be savage but "
            f"clever. DO NOT use @ symbols or names "
            f"in your response."
        )

        history = [
            {"role": "user", "content": "\n".join(user_msgs)}
        ]
        model = settings.get(
            "llm_model", "meta-llama/llama-3-8b-instruct"
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
            async for msg in interaction.channel.history(limit=500):
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
                {"role": "user", "content": "\n".join(user_msgs)}
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
                "training_data.txt", "r", encoding="utf-8"
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
