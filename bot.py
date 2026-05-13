"""
Dripsletongue v5.8 — bot.py
Main entry point. Fixed: cog loading, Database init, proper trigger wiring.
Nothing removed — all v5.7 features preserved + puppet mode enabled via cogs.
"""

import asyncio
import logging
import os
import subprocess
import sys
import threading
import time

import discord
from discord.ext import commands

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("dripsletongue")

# ── Config ──
TOKEN = os.environ.get("DISCORD_TOKEN", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
BOT_PREFIX = os.environ.get("BOT_PREFIX", "!")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", 8080))
SIDECAR_PORT = int(os.environ.get("ZAI_SIDECAR_PORT", 3456))

if not TOKEN:
    logger.error("DISCORD_TOKEN not set!")
    sys.exit(1)

# ── Intents ──
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

# ── Bot Instance ──
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents, help_command=None)

# ═══════════════════════════════════════════════════════════════
#  Z.ai Sidecar Startup (Pure Python — NO Node.js needed)
# ═══════════════════════════════════════════════════════════════

sidecar_process = None

try:
    sidecar_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zai_sidecar.py")
    if os.path.exists(sidecar_script):
        sidecar_process = subprocess.Popen(
            [sys.executable, sidecar_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
        time.sleep(2)
        if sidecar_process.poll() is None:
            logger.info(f"Z.ai sidecar started on port {SIDECAR_PORT} (PID: {sidecar_process.pid})")
        else:
            _, stderr = sidecar_process.communicate(timeout=5)
            logger.warning(f"Z.ai sidecar crashed on start: {stderr.decode()[:300]}")
            sidecar_process = None
    else:
        logger.warning("zai_sidecar.py not found — Z.ai features (vision/search/image gen) disabled")
except Exception as e:
    logger.warning(f"Z.ai sidecar failed to start: {e}")
    sidecar_process = None


# Drain sidecar pipes in background to prevent 64KB buffer deadlock
def _drain_sidecar():
    if sidecar_process:
        try:
            sidecar_process.stdout.read()
            sidecar_process.stderr.read()
        except Exception:
            pass


if sidecar_process:
    threading.Thread(target=_drain_sidecar, daemon=True).start()


# ═══════════════════════════════════════════════════════════════
#  Database & Settings Manager
# ═══════════════════════════════════════════════════════════════

from engine.database import Database
from config.settings_manager import SettingsManager

db = Database()
settings_manager = SettingsManager(db)

# Attach to bot so cogs and api.py can find them
bot.db = db
bot.settings_manager = settings_manager


# ═══════════════════════════════════════════════════════════════
#  Bot Events
# ═══════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guild(s)")

    # Initialize database (creates tables, starts write worker)
    await db.init()

    # Pre-load settings for all guilds
    saved_status = ""
    for guild in bot.guilds:
        settings = await settings_manager.get_settings(guild.id)
        if not saved_status:
            saved_status = settings.get("personality_status", "")

    if saved_status:
        try:
            await bot.change_presence(activity=discord.Game(name=saved_status))
            logger.info(f"Applied saved bot status: {saved_status}")
        except Exception as e:
            logger.warning(f"Failed to apply saved bot status: {e}")

    # ── Load cogs ──
    cog_load_errors = []

    try:
        await bot.load_extension("cogs.chat")
        logger.info("Loaded cog: cogs.chat (message handler, proactive, puppet mode)")
    except Exception as e:
        cog_load_errors.append(f"cogs.chat: {e}")
        logger.error(f"Failed to load cogs.chat: {e}", exc_info=True)

    try:
        await bot.load_extension("cogs.settings_cog")
        logger.info("Loaded cog: cogs.settings_cog (slash commands)")
    except Exception as e:
        cog_load_errors.append(f"cogs.settings_cog: {e}")
        logger.error(f"Failed to load cogs.settings_cog: {e}", exc_info=True)

    try:
        await bot.load_extension("chat")
        logger.info("Loaded cog: chat (personality preset commands)")
    except Exception as e:
        cog_load_errors.append(f"chat: {e}")
        logger.error(f"Failed to load chat cog: {e}", exc_info=True)

    # Sync slash commands to Discord
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash commands")
    except Exception as e:
        logger.error(f"Slash command sync failed: {e}")

    # Start dashboard in background thread
    start_dashboard()

    if cog_load_errors:
        logger.warning(f"Cogs with errors: {cog_load_errors}")
    logger.info("Bot fully loaded and ready")


@bot.event
async def on_message(message):
    """
    Minimal bot-level on_message.
    Only routes prefix commands (!ping, !model, !imagine, !reset).
    All message handling (triggers, responses, image gen, puppet mode)
    is done by cogs/chat.py's on_message listener.
    """
    if message.author.bot:
        return
    # Process prefix commands so !ping, !model, !imagine, !reset still work.
    # The cog's on_message listener also fires and handles everything else.
    await bot.process_commands(message)


# ═══════════════════════════════════════════════════════════════
#  Prefix Commands
# ═══════════════════════════════════════════════════════════════

@bot.command(name="ping")
async def ping(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(f"Pong! `{latency}ms`")


@bot.command(name="model")
async def show_model(ctx):
    guild_id = ctx.guild.id if ctx.guild else 0
    settings = await settings_manager.get_settings(guild_id)
    model = settings.get("llm_model") or settings.get("model", "meta-llama/llama-4-maverick:free")
    await ctx.send(f"Current model: `{model}`")


@bot.command(name="imagine", aliases=["image", "img", "draw"])
async def imagine(ctx, *, prompt: str = None):
    """Generate an image using Z.ai sidecar, Pollinations, or OpenRouter."""
    if not prompt:
        await ctx.send("Give me a prompt! Usage: `!imagine a sunset over mountains`")
        return

    from llm import generate_image

    guild_id = ctx.guild.id if ctx.guild else 0
    settings = await settings_manager.get_settings(guild_id)
    image_model = settings.get("image_model", "zai-sidecar")

    await ctx.send("Generating image...")
    try:
        image_url = await generate_image(prompt, model_name=image_model)
        if image_url:
            import base64
            import io
            from discord import File

            if image_url.startswith("data:image/"):
                header, encoded = image_url.split(",", 1)
                ext = header.split("/")[1].split(";")[0]
                img_data = base64.b64decode(encoded)
                await ctx.send(file=File(fp=io.BytesIO(img_data), filename=f"image.{ext}"))
            else:
                await ctx.send(image_url)
        else:
            await ctx.send("Failed to generate image. The sidecar might not be running.")
    except Exception as e:
        logger.error(f"!imagine error: {e}")
        await ctx.send(f"Image generation failed: `{e}`")


@bot.command(name="reset")
async def reset_personality(ctx):
    """Reset personality to default."""
    guild_id = ctx.guild.id if ctx.guild else 0
    await settings_manager.update_settings(guild_id, {
        "personality_prompt": "",
        "personality_name": "Ultron",
        "personality": {},
    })
    await ctx.send("Personality reset to default.")


# ═══════════════════════════════════════════════════════════════
#  Dashboard (FastAPI in background thread)
# ═══════════════════════════════════════════════════════════════

def start_dashboard():
    """Start the FastAPI dashboard in a background thread."""
    import uvicorn
    from api import create_api

    app = create_api(bot)
    thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": "0.0.0.0", "port": DASHBOARD_PORT, "log_level": "warning"},
        daemon=True,
    )
    thread.start()
    logger.info(f"Dashboard running on port {DASHBOARD_PORT}")


# ═══════════════════════════════════════════════════════════════
#  Keep-Alive (self-ping for Render free tier)
# ═══════════════════════════════════════════════════════════════

def keep_alive():
    """Ping self every 14 minutes to prevent Render spin-down."""
    import urllib.request

    url = os.environ.get("KEEP_ALIVE_URL", f"http://localhost:{DASHBOARD_PORT}/api/health")
    while True:
        try:
            urllib.request.urlopen(url, timeout=10)
        except Exception:
            pass
        time.sleep(840)  # 14 minutes


# ═══════════════════════════════════════════════════════════════
#  Run
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Start keep-alive in background
    keep_thread = threading.Thread(target=keep_alive, daemon=True)
    keep_thread.start()

    # Run the bot
    bot.run(TOKEN)
