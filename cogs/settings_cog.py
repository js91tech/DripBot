import discord
from discord.ext import commands
from discord import app_commands
from config.default_settings import DEFAULTS, VALIDATORS, PERSONALITY_PRESETS
from engine.markov import MarkovChain
from utils import sanitize_message
from llm import generate_llm_response, parse_settings_command
import json
import os

DEFAULT_LLM_MODEL = "meta-llama/llama-4-maverick:free"


class SettingsCog(commands.Cog):
    def __init__(self, bot, db, settings_manager):
        self.bot = bot
        self.db = db
        self.settings_manager = settings_manager

    def _llm_route(self, settings):
        return {
            "model": settings.get("llm_model") or settings.get("model", DEFAULT_LLM_MODEL),
            "auto_router": bool(settings.get("auto_router_enabled", False)),
            "allowed_models": settings.get("auto_router_allowed_models") or [],
        }

    group = app_commands.Group(
        name="botsettings",
        description="Configure the bot",
        default_permissions=discord.Permissions(manage_guild=True))

    # ==========================================
    # /botsettings ask - Natural language settings
    # ==========================================
    @group.command(name="ask", description="Change settings using natural language")
    @app_commands.describe(prompt="Describe what setting you want to change")
    async def ask_setting(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer(thinking=True)
        result = await parse_settings_command(prompt)
        if not result:
            await interaction.followup.send(
                "I couldn't understand what setting you wanted to change. "
                "Try something like:\n"
                "- `switch model to meta-llama/llama-3-70b-instruct`\n"
                "- `turn off responses`\n"
                "- `set cooldown to 15`\n"
                "- `switch to markov mode`",
                ephemeral=True,
            )
            return
        key, value = result
        guild_id = interaction.guild.id
        try:
            settings = await self.settings_manager.set_setting(guild_id, key, value)
            await interaction.followup.send(f"Updated `{key}` to `{value}`", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Failed to update setting: {e}", ephemeral=True)

    # ==========================================
    # /botsettings personality - Quick personality preset picker
    # ==========================================
    @group.command(name="personality", description="Switch the bot's personality preset")
    @app_commands.describe(preset="Choose a personality preset")
    @app_commands.choices(preset=[
        app_commands.Choice(name="Ultron (Sarcastic Smart-Ass)", value="ultron"),
        app_commands.Choice(name="Deadpool (Chaotic 4th-Wall)", value="deadpool"),
        app_commands.Choice(name="J.A.R.V.I.S. (British Butler)", value="jarvis"),
        app_commands.Choice(name="Tony Stark (Arrogant Genius)", value="tony_stark"),
        app_commands.Choice(name="GLaDOS (Passive-Aggressive)", value="glados"),
        app_commands.Choice(name="Rick Sanchez (Drunk Genius)", value="rick_sanchez"),
        app_commands.Choice(name="Bender (Rude Robot)", value="bender"),
        app_commands.Choice(name="The Brain (Megalomaniac)", value="the_brain"),
    ])
    async def personality_switch(self, interaction: discord.Interaction, preset: app_commands.Choice[str]):
        preset_data = PERSONALITY_PRESETS.get(preset.value)
        if not preset_data:
            await interaction.response.send_message("Unknown preset.", ephemeral=True)
            return
        await self.settings_manager.update_settings(interaction.guild.id, {
            "personality_prompt": preset_data["prompt"],
            "personality_name": preset_data.get("name", preset.value),
            "personality": {
                "preset": preset.value,
                "custom": "",
                "system_prompt": preset_data["prompt"],
            },
        })
        await interaction.response.send_message(
            f"Personality switched to **{preset_data['name']}**!",
            ephemeral=True,
        )

    # ==========================================
    # /botsettings modelfree - Free LLM model picker
    # /botsettings modelpaid - Paid LLM model picker
    #
    # FIX v5.8: Discord limits slash command choices to 25 max.
    # The old /botsettings model had 29 choices which caused sync to fail
    # (HTTP 400), blocking ALL slash commands from registering.
    # Split into two commands, each well under the 25 limit.
    # ==========================================

    @group.command(name="modelfree", description="Switch to a free LLM model")
    @app_commands.describe(model="Choose a free LLM model")
    @app_commands.choices(model=[
        app_commands.Choice(name="Llama 4 Maverick (Free)", value="meta-llama/llama-4-maverick:free"),
        app_commands.Choice(name="Gemma 3 27B (Free)", value="google/gemma-3-27b-it:free"),
        app_commands.Choice(name="Qwen3 235B (Free)", value="qwen/qwen3-235b-a22b:free"),
        app_commands.Choice(name="Phi-4 Reasoning+ (Free)", value="microsoft/phi-4-reasoning-plus:free"),
        app_commands.Choice(name="DeepSeek R1 (Free)", value="deepseek/deepseek-r1:free"),
        app_commands.Choice(name="Nemotron 70B (Free)", value="nvidia/llama-3.1-nemotron-70b-instruct:free"),
        app_commands.Choice(name="Gemma 3 12B (Free)", value="google/gemma-3-12b-it:free"),
        app_commands.Choice(name="Mistral Small 3.1 (Free)", value="mistralai/mistral-small-3.1-24b-instruct:free"),
        app_commands.Choice(name="Qwen3 32B (Free)", value="qwen/qwen3-32b:free"),
        app_commands.Choice(name="Llama 3.3 70B (Free)", value="meta-llama/llama-3.3-70b-instruct:free"),
    ])
    async def modelfree_switch(self, interaction: discord.Interaction, model: app_commands.Choice[str]):
        await self.settings_manager.set_setting(interaction.guild.id, "llm_model", model.value)
        await self.settings_manager.set_setting(interaction.guild.id, "model", model.value)
        await interaction.response.send_message(
            f"Model switched to **{model.name}** (`{model.value}`)",
            ephemeral=True,
        )

    @group.command(name="modelpaid", description="Switch to a paid LLM model")
    @app_commands.describe(model="Choose a paid LLM model")
    @app_commands.choices(model=[
        app_commands.Choice(name="GPT-4o", value="openai/gpt-4o"),
        app_commands.Choice(name="GPT-4.1", value="openai/gpt-4.1"),
        app_commands.Choice(name="Claude Sonnet 4", value="anthropic/claude-sonnet-4"),
        app_commands.Choice(name="Claude Opus 4", value="anthropic/claude-opus-4"),
        app_commands.Choice(name="Gemini 2.5 Pro", value="google/gemini-2.5-pro"),
        app_commands.Choice(name="Gemini 2.5 Flash", value="google/gemini-2.5-flash"),
        app_commands.Choice(name="Llama 4 Maverick", value="meta-llama/llama-4-maverick"),
        app_commands.Choice(name="DeepSeek Chat V3", value="deepseek/deepseek-chat-v3-0324"),
        app_commands.Choice(name="Mistral Large", value="mistralai/mistral-large-2411"),
        app_commands.Choice(name="Grok 3", value="x-ai/grok-3"),
        app_commands.Choice(name="Grok 3 Mini", value="x-ai/grok-3-mini"),
        app_commands.Choice(name="o3-mini", value="openai/o3-mini"),
        app_commands.Choice(name="o4-mini", value="openai/o4-mini"),
        app_commands.Choice(name="Claude Haiku 3.5", value="anthropic/claude-haiku-3.5"),
    ])
    async def modelpaid_switch(self, interaction: discord.Interaction, model: app_commands.Choice[str]):
        await self.settings_manager.set_setting(interaction.guild.id, "llm_model", model.value)
        await self.settings_manager.set_setting(interaction.guild.id, "model", model.value)
        await interaction.response.send_message(
            f"Model switched to **{model.name}** (`{model.value}`)",
            ephemeral=True,
        )

    # ==========================================
    # /image — Slash command for image generation
    # FIX v5.8: Users kept typing /image which didn't exist.
    # Now it works just like !imagine but as a slash command.
    # ==========================================
    @app_commands.command(name="image", description="Generate an image from a text prompt")
    @app_commands.describe(prompt="Describe the image you want to generate")
    async def slash_image(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer(thinking=True)
        from llm import generate_image

        guild_id = interaction.guild.id if interaction.guild else 0
        settings = await self.settings_manager.get_settings(guild_id)
        image_model = settings.get("image_model", "zai-sidecar")

        try:
            image_url = await generate_image(prompt, model_name=image_model)
            if image_url:
                import base64
                import io
                if image_url.startswith("data:image/"):
                    header, encoded = image_url.split(",", 1)
                    ext = header.split("/")[1].split(";")[0]
                    img_data = base64.b64decode(encoded)
                    img_file = discord.File(io.BytesIO(img_data), f"image.{ext}")
                    await interaction.followup.send(file=img_file)
                else:
                    await interaction.followup.send(image_url)
            else:
                await interaction.followup.send(
                    "Image generation failed. The sidecar might not be running, or the model is unavailable.\n"
                    "Try switching image model with `/botsettings imgmodel` — **Pollinations** always works for free.",
                    ephemeral=True,
                )
        except Exception as e:
            await interaction.followup.send(f"Image generation error: `{e}`", ephemeral=True)

    # ==========================================
    # /botsettings imgmodel - Image model picker
    # ==========================================
    @group.command(name="imgmodel", description="Switch the image generation model")
    @app_commands.describe(model="Choose an image generation model")
    @app_commands.choices(model=[
        app_commands.Choice(name="Z.ai Sidecar (Free)", value="zai-sidecar"),
        app_commands.Choice(name="GPT-4o (Best Quality)", value="openai/gpt-4o"),
        app_commands.Choice(name="GPT-4o Mini (Cheaper)", value="openai/gpt-4o-mini"),
        app_commands.Choice(name="Claude 3.5 Sonnet", value="anthropic/claude-3.5-sonnet"),
        app_commands.Choice(name="Claude 3.7 Sonnet", value="anthropic/claude-3.7-sonnet"),
        app_commands.Choice(name="Gemini 2.0 Flash (Free)", value="google/gemini-2.0-flash-exp:free"),
        app_commands.Choice(name="Pollinations (Always Free)", value="pollinations"),
    ])
    async def imgmodel_switch(self, interaction: discord.Interaction, model: app_commands.Choice[str]):
        await self.settings_manager.set_setting(interaction.guild.id, "image_model", model.value)
        await interaction.response.send_message(
            f"Image model switched to **{model.name}** (`{model.value}`)",
            ephemeral=True,
        )

    # ==========================================
    # STANDARD SETTING COMMANDS
    # ==========================================
    async def setting_autocomplete(self, interaction: discord.Interaction, current: str) -> list:
        keys = list(DEFAULTS.keys())
        return [app_commands.Choice(name=key, value=key) for key in keys if current.lower() in key.lower()][:25]

    @group.command(name="set", description="Change a setting")
    @app_commands.autocomplete(key=setting_autocomplete)
    async def set_setting(self, interaction: discord.Interaction, key: str, value: str):
        key = key.lower()
        if key not in DEFAULTS:
            await interaction.response.send_message(f"Invalid setting key: `{key}`", ephemeral=True)
            return
        validator = VALIDATORS.get(key)
        if validator and not validator(value):
            await interaction.response.send_message(f"Invalid value for `{key}`.", ephemeral=True)
            return
        if isinstance(DEFAULTS[key], bool):
            parsed_val = str(value).lower() in ["true", "yes", "on", "1"]
        elif isinstance(DEFAULTS[key], int):
            parsed_val = int(value)
        elif isinstance(DEFAULTS[key], float):
            parsed_val = float(value)
        elif isinstance(DEFAULTS[key], list):
            try:
                parsed_val = json.loads(value)
                if not isinstance(parsed_val, list):
                    raise ValueError
            except Exception:
                await interaction.response.send_message("List values must be a JSON array", ephemeral=True)
                return
        else:
            parsed_val = value
        await self.settings_manager.set_setting(interaction.guild.id, key, parsed_val)
        await interaction.response.send_message(f"Set `{key}` to `{parsed_val}`", ephemeral=True)

    @group.command(name="toggle", description="Toggle a True/False setting on or off")
    @app_commands.describe(setting="Choose the setting to toggle")
    @app_commands.choices(setting=[
        app_commands.Choice(name="Response Enabled", value="response_enabled"),
        app_commands.Choice(name="Learning Enabled", value="learning_enabled"),
        app_commands.Choice(name="Learn From Bots", value="learn_from_bots"),
        app_commands.Choice(name="Trigger on Mention", value="trigger_on_mention"),
        app_commands.Choice(name="Trigger on Reply", value="trigger_on_reply"),
        app_commands.Choice(name="Vision (Z.ai)", value="vision_enabled"),
        app_commands.Choice(name="Web Search (Z.ai)", value="web_search_enabled"),
        app_commands.Choice(name="Z.ai Image Gen", value="zai_image_gen_enabled"),
    ])
    async def toggle_setting(self, interaction: discord.Interaction, setting: app_commands.Choice[str]):
        settings = await self.settings_manager.get_settings(interaction.guild.id)
        new_val = not settings[setting.value]
        await self.settings_manager.set_setting(interaction.guild.id, setting.value, new_val)
        status = "ON" if new_val else "OFF"
        await interaction.response.send_message(f"**{setting.name}** is now {status}", ephemeral=True)

    @group.command(name="chattiness", description="Quick adjust how chatty the bot is")
    @app_commands.describe(level="Select a chattiness level")
    @app_commands.choices(level=[
        app_commands.Choice(name="1 - Almost Never Speaks", value=1),
        app_commands.Choice(name="2", value=2),
        app_commands.Choice(name="3 - Occasional", value=3),
        app_commands.Choice(name="4", value=4),
        app_commands.Choice(name="5 - Average", value=5),
        app_commands.Choice(name="6", value=6),
        app_commands.Choice(name="7 - Fairly Chatty", value=7),
        app_commands.Choice(name="8", value=8),
        app_commands.Choice(name="9", value=9),
        app_commands.Choice(name="10 - Won't Shut Up", value=10),
    ])
    async def chattiness(self, interaction: discord.Interaction, level: app_commands.Choice[int]):
        chance = round(level.value * 0.03, 2)
        await self.settings_manager.set_setting(interaction.guild.id, "response_chance", chance)
        await interaction.response.send_message(
            f"Chattiness set to **{level.name}**. Response chance is now {chance * 100}%",
            ephemeral=True,
        )

    @group.command(name="mode", description="Switch between Markov and LLM")
    @app_commands.describe(brain="Select the brain mode")
    @app_commands.choices(brain=[
        app_commands.Choice(name="Markov (Free, Silly, Random)", value="markov"),
        app_commands.Choice(name="LLM (Costs Cents, Human-like, Coherent)", value="llm"),
    ])
    async def mode(self, interaction: discord.Interaction, brain: app_commands.Choice[str]):
        await self.settings_manager.set_setting(interaction.guild.id, "brain_mode", brain.value)
        await interaction.response.send_message(f"Brain mode set to **{brain.name}**.", ephemeral=True)

    @group.command(name="remember", description="Make the bot permanently remember a fact about a user")
    @app_commands.describe(user="The user this fact is about", fact="The fact to remember")
    async def remember(self, interaction: discord.Interaction, user: discord.Member, fact: str):
        await self.db.add_memory(interaction.guild.id, user.id, fact)
        await interaction.response.send_message(
            f"I'll remember that about {user.display_name}: {fact}",
            ephemeral=True,
        )

    @group.command(name="forget", description="Make the bot forget all facts about a user")
    @app_commands.describe(user="The user to forget")
    async def forget(self, interaction: discord.Interaction, user: discord.Member):
        await self.db.forget_memories(interaction.guild.id, user.id)
        await interaction.response.send_message(
            f"I've forgotten everything I knew about {user.display_name}.",
            ephemeral=True,
        )

    @group.command(name="roast", description="Roast a user based on their recent messages")
    @app_commands.describe(user="The user you want to roast")
    async def roast(self, interaction: discord.Interaction, user: discord.Member):
        if user.bot:
            await interaction.response.send_message("I only roast humans!", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        user_msgs = []
        async for msg in interaction.channel.history(limit=500):
            if msg.author.id == user.id and not msg.content.startswith("/") and msg.content.strip():
                user_msgs.insert(0, msg.content)
                if len(user_msgs) >= 30:
                    break
        if len(user_msgs) < 5:
            await interaction.followup.send(
                f"{user.display_name} hasn't said enough for me to roast them.",
                ephemeral=True,
            )
            return
        settings = await self.settings_manager.get_settings(interaction.guild.id)
        roast_prompt = (
            f"You are a ruthless, sarcastic smart-ass. Analyze these recent messages from {user.display_name} "
            f"and deliver a devastating, witty roast based on what they talk about and how they type. "
            f"Keep it 2-4 sentences. Be savage but clever. DO NOT use @ symbols or names in your response."
        )
        chat_history = [{"role": "user", "content": "\n".join(user_msgs)}]
        chat_history.insert(0, {"role": "system", "content": roast_prompt, **self._llm_route(settings)})
        response = await generate_llm_response(roast_prompt, chat_history)
        if response:
            await interaction.followup.send(f"**Roasting {user.display_name}:** {sanitize_message(response)}")
        else:
            await interaction.followup.send("Couldn't come up with a roast right now.", ephemeral=True)

    @group.command(name="mimic", description="Generate a message mimicking a specific user")
    @app_commands.describe(user="The user you want to mimic")
    async def mimic(self, interaction: discord.Interaction, user: discord.Member):
        if user.bot:
            await interaction.response.send_message("I only mimic humans!", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            temp_chain = MarkovChain(order=2)
            messages_found = 0
            exact_messages = set()
            async for msg in interaction.channel.history(limit=5000):
                if msg.author.id == user.id and not msg.content.startswith("/") and msg.content.strip():
                    temp_chain.learn(msg.content)
                    exact_messages.add(msg.content.lower().strip())
                    messages_found += 1
                    if messages_found >= 500:
                        break
            if messages_found < 5:
                await interaction.followup.send(
                    f"{user.display_name} hasn't talked enough here for me to mimic them!",
                    ephemeral=True,
                )
                return
            response = None
            for _ in range(5):
                generated = temp_chain.generate(min_words=4, max_words=40)
                if generated and generated.lower().strip() not in exact_messages:
                    response = generated
                    break
            if response:
                await interaction.followup.send(f"**{user.display_name}:** {sanitize_message(response)}")
            else:
                await interaction.followup.send(
                    f"I couldn't figure out how to mix up {user.display_name}'s words creatively!",
                    ephemeral=True,
                )
        except Exception as e:
            await interaction.followup.send(f"An error occurred while mimicking: {e}", ephemeral=True)

    @group.command(name="list", description="View all current settings")
    async def list_settings(self, interaction: discord.Interaction):
        settings = await self.settings_manager.get_settings(interaction.guild.id)
        embed = discord.Embed(title="Bot Settings", color=discord.Color.blue())
        for key, value in settings.items():
            embed.add_field(name=key, value=f"`{value}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="stats", description="View learning statistics")
    async def stats(self, interaction: discord.Interaction):
        stats = await self.db.get_stats(interaction.guild.id)
        embed = discord.Embed(title="Learning Stats", color=discord.Color.green())
        embed.add_field(name="Messages Learned", value=str(stats["messages_learned"]), inline=True)
        embed.add_field(name="Messages Sent", value=str(stats["messages_sent"]), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="resetdata", description="Delete ALL learned data for this server")
    async def reset_data(self, interaction: discord.Interaction):
        await self.db.delete_guild_data(interaction.guild.id)
        if interaction.guild.id in self.bot.get_cog("Chat").chains:
            del self.bot.get_cog("Chat").chains[interaction.guild.id]
        await self.settings_manager.reset_all(interaction.guild.id)
        await interaction.response.send_message("All learned data and settings have been wiped.", ephemeral=True)

    @group.command(name="loadbrain", description="Manually load the starter brain text file")
    async def load_brain(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id = interaction.guild.id
        try:
            with open("training_data.txt", "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            await interaction.followup.send("No `training_data.txt` file found!", ephemeral=True)
            return
        settings = await self.settings_manager.get_settings(guild_id)
        chat_cog = self.bot.get_cog("Chat")
        if not chat_cog:
            await interaction.followup.send("Chat cog not loaded.", ephemeral=True)
            return
        chain = await chat_cog.get_chain(guild_id, settings["markov_order"])
        learned_count = 0
        for line in lines:
            clean_line = line.strip()
            if clean_line:
                chain.learn(clean_line)
                learned_count += 1
        await self.db.save_full_chain(guild_id, chain.to_db_dict())
        await self.db.increment_stat(guild_id, "messages_learned", learned_count)
        await interaction.followup.send(
            f"Successfully loaded starter brain! Learned {learned_count} lines.",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(SettingsCog(bot, bot.db, bot.settings_manager))
