"""
chat.py — Dripsletongue v5.8
Personality preset commands (!personality, !presets).
Loaded as a cog via bot.load_extension("chat").

NOTE: The main message handler (on_message with triggers, LLM, vision, web search,
LLM chat, memory, proactive, puppet mode) is in cogs/chat.py.
This cog handles only the personality management prefix commands.
"""

import logging
from discord.ext import commands
from config.default_settings import (
    PERSONALITY_PRESETS,
    build_personality_settings_update,
    normalize_personality_preset,
)

logger = logging.getLogger("dripsletongue.cog.chat")


class ChatCog(commands.Cog):
    """Chat commands for personality management."""

    def __init__(self, bot):
        self.bot = bot

    def _get_personality_preset(self, name: str):
        """Look up a personality preset by name. Returns dict or None."""
        preset_id = normalize_personality_preset(name)
        return PERSONALITY_PRESETS.get(preset_id) if preset_id else None

    @commands.command(name="presets")
    async def list_presets(self, ctx):
        """List all available personality presets."""
        lines = ["**Available Personality Presets:**\n"]
        for pid, preset in PERSONALITY_PRESETS.items():
            lines.append(f"- `{pid}` — {preset['name']}")
        lines.append("\nUse `!personality <name>` to apply one.")
        await ctx.send("\n".join(lines))

    @commands.command(name="personality", aliases=["persona"])
    async def set_personality(self, ctx, *, name: str = None):
        """Set a personality preset by name, or show current personality."""
        guild_id = ctx.guild.id if ctx.guild else 0
        sm = getattr(self.bot, "settings_manager", None)
        if not sm:
            await ctx.send("Settings manager not ready yet. Try again in a moment.")
            return

        settings = await sm.get_settings(guild_id)

        if not name:
            # Show current personality
            personality_name = settings.get("personality_name", "")
            personality_prompt = settings.get("personality_prompt", "")
            preset_name = settings.get("personality", {}).get("preset", "")

            if preset_name:
                preset = PERSONALITY_PRESETS.get(preset_name)
                display = preset["name"] if preset else preset_name
                await ctx.send(f"Current personality: **{display}**\nUse `!presets` to see all options.")
            elif personality_prompt:
                preview = personality_prompt[:200] + ("..." if len(personality_prompt) > 200 else "")
                await ctx.send(f"Current personality: **{personality_name or 'Custom'}**\n```\n{preview}\n```")
            else:
                await ctx.send("No personality set. Use `!presets` to see options or `!personality <name>` to set one.")
            return

        # Set personality
        preset_id = normalize_personality_preset(name)
        preset = PERSONALITY_PRESETS.get(preset_id) if preset_id else None
        if not preset:
            await ctx.send(f"Unknown preset: `{name}`.\nUse `!presets` to see available options.")
            return

        await sm.update_settings(guild_id, build_personality_settings_update(preset_id))

        await ctx.send(f"Personality set to **{preset['name']}**!")


async def setup(bot):
    await bot.add_cog(ChatCog(bot))
    logger.info("Chat cog loaded (personality commands)")
