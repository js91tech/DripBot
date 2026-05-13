"""
Dripsletongue v5.7 — bot.py
Main entry point. Drop-in replacement.
"""

import asyncio
import logging
import os
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

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
        # Give it a moment to bind the port
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


# ═══════════════════════════════════════════════════════════════
#  LLM Handler (import after bot is created)
# ═══════════════════════════════════════════════════════════════

from llm import LLMHandler

llm_handler = LLMHandler()


# ═══════════════════════════════════════════════════════════════
#  Settings Manager
# ═══════════════════════════════════════════════════════════════

import aiosqlite
import json
from config.default_settings import DEFAULT_SETTINGS


class SettingsManager:
    def __init__(self, db_path="settings.db"):
        self.db_path = db_path
        self.settings = {}  # {guild_id: {key: value, ...}}

    async def init(self):
        """Load all settings from DB, filling defaults for missing keys."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT guild_id, settings FROM guild_settings") as cursor:
                async for row in cursor:
                    gid, raw = row
                    saved = json.loads(raw) if raw else {}
                    merged = {**DEFAULT_SETTINGS, **saved}
                    self.settings[str(gid)] = merged
            await db.execute(
                "CREATE TABLE IF NOT EXISTS guild_settings (guild_id TEXT PRIMARY KEY, settings TEXT)"
            )
            await db.commit()

    async def get_settings(self, guild_id: str) -> dict:
        if guild_id not in self.settings:
            self.settings[guild_id] = dict(DEFAULT_SETTINGS)
            await self.save_settings(guild_id)
        return self.settings[guild_id]

    async def save_settings(self, guild_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO guild_settings (guild_id, settings) VALUES (?, ?)",
                (guild_id, json.dumps(self.settings.get(guild_id, {}))),
            )
            await db.commit()


settings_manager = SettingsManager()


# ═══════════════════════════════════════════════════════════════
#  Memory Manager
# ═══════════════════════════════════════════════════════════════

class MemoryManager:
    def __init__(self, db_path="memory.db"):
        self.db_path = db_path

    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS memories
                   (user_id TEXT, guild_id TEXT, content TEXT, timestamp TEXT,
                    PRIMARY KEY (user_id, guild_id, timestamp))"""
            )
            await db.commit()

    async def add_memory(self, user_id: str, guild_id: str, content: str):
        import datetime
        ts = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO memories (user_id, guild_id, content, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, guild_id, content[:500], ts),
            )
            # Keep only last 50 memories per user per guild
            await db.execute(
                """DELETE FROM memories WHERE user_id = ? AND guild_id = ?
                   AND timestamp NOT IN (
                       SELECT timestamp FROM memories
                       WHERE user_id = ? AND guild_id = ?
                       ORDER BY timestamp DESC LIMIT 50
                   )""",
                (user_id, guild_id, user_id, guild_id),
            )
            await db.commit()

    async def get_memories(self, user_id: str, guild_id: str, limit: int = 10) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT content FROM memories WHERE user_id = ? AND guild_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, guild_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
                return [r[0] for r in reversed(rows)]


memory_manager = MemoryManager()


# ═══════════════════════════════════════════════════════════════
#  Markov Chain
# ═══════════════════════════════════════════════════════════════

class MarkovChain:
    def __init__(self):
        self.chain = {}

    def add_text(self, text: str):
        words = text.lower().split()
        for i in range(len(words) - 2):
            key = (words[i], words[i + 1])
            self.chain.setdefault(key, []).append(words[i + 2])

    def generate(self, max_words: int = 30) -> str:
        import random
        if not self.chain:
            return ""
        key = random.choice(list(self.chain.keys()))
        words = list(key)
        for _ in range(max_words - 2):
            next_words = self.chain.get(tuple(words[-2:]))
            if not next_words:
                break
            words.append(random.choice(next_words))
        return " ".join(words).capitalize()


markov = MarkovChain()


# ═══════════════════════════════════════════════════════════════
#  Bot Events
# ═══════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guild(s)")

    # Initialize settings for all guilds
    await settings_manager.init()
    await memory_manager.init()

    for guild in bot.guilds:
        await settings_manager.get_settings(str(guild.id))

    # Start dashboard in background thread
    start_dashboard()

    # Start proactive messaging loop
    bot.loop.create_task(proactive_loop())

    logger.info("Bot fully loaded and ready")


@bot.event
async def on_message(message):
    """Main message handler."""
    if message.author.bot:
        return

    # Don't respond to bot commands
    if message.content.startswith(BOT_PREFIX):
        await bot.process_commands(message)
        return

    guild_id = str(message.guild.id) if message.guild else "dm"
    settings = await settings_manager.get_settings(guild_id)

    if not settings.get("response_enabled", True):
        return

    # ── Build context ──
    messages = []

    # Add memory context
    if settings.get("memory_enabled", False):
        memories = await memory_manager.get_memories(str(message.author.id), guild_id, limit=5)
        if memories:
            mem_text = "\n".join(f"- {m}" for m in memories)
            messages.append({
                "role": "system",
                "content": f"Previous messages from this user:\n{mem_text}",
            })

    # Add current message
    messages.append({
        "role": "user",
        "content": message.content or "[Image or attachment]",
    })

    # ── Vision: check for image attachments ──
    if message.attachments:
        for attachment in message.attachments:
            if attachment.filename and attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                if settings.get("vision_enabled", False):
                    try:
                        description = await llm_handler.analyze_image(
                            image_url=attachment.url,
                            prompt="Describe this image in detail for context.",
                        )
                        if description:
                            messages.append({
                                "role": "user",
                                "content": f"[Image: {attachment.filename}]\n{description}",
                            })
                    except Exception as e:
                        logger.error(f"Vision error: {e}")

    # ── Web Search: enrich context ──
    if settings.get("web_search_enabled", False) and message.content:
        try:
            results = await llm_handler.web_search(message.content[:100], num=3)
            if results:
                context = "\n".join(
                    f"- {r.get('name', 'Untitled')}: {r.get('snippet', '')[:150]}"
                    for r in results
                )
                messages.insert(0, {
                    "role": "system",
                    "content": f"Web search context (use if relevant):\n{context}",
                })
        except Exception as e:
            logger.error(f"Web search error: {e}")

    # ── System prompt ──
    personality = settings.get("personality", {})
    system_prompt = personality.get("system_prompt", "")

    # ── Chat call with Auto Router ──
    auto_router = settings.get("auto_router_enabled", False)
    allowed_models = settings.get("auto_router_allowed_models", [])
    model = settings.get("model", "meta-llama/llama-4-maverick:free")

    result = await llm_handler.chat(
        messages,
        model=model,
        system_prompt=system_prompt,
        auto_router=auto_router,
        allowed_models=allowed_models if allowed_models else None,
    )

    response_text = ""
    if result and result.get("content"):
        response_text = result["content"]
        model_used = result.get("model_used", model)
        if auto_router:
            logger.info(f"AutoRouter selected: {model_used}")

    # ── Markov fallback ──
    if not response_text and settings.get("markov_enabled", False):
        response_text = markov.generate()

    # ── Send response ──
    if response_text:
        # Discord limit
        if len(response_text) > 2000:
            response_text = response_text[:1997] + "..."
        await message.reply(response_text)

        # Save to memory
        if settings.get("memory_enabled", False):
            await memory_manager.add_memory(
                str(message.author.id), guild_id, message.content[:500]
            )
            await memory_manager.add_memory(
                str(bot.user.id), guild_id, response_text[:500]
            )

    # Feed markov
    if message.content:
        markov.add_text(message.content)


# ═══════════════════════════════════════════════════════════════
#  Proactive Messaging
# ═══════════════════════════════════════════════════════════════

async def proactive_loop():
    """Periodically send messages to guilds with proactive enabled."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            for guild in bot.guilds:
                gid = str(guild.id)
                settings = await settings_manager.get_settings(gid)
                if not settings.get("proactive_enabled", False):
                    continue

                # Find a channel to send in
                channel = None
                for ch in guild.text_channels:
                    if ch.permissions_for(guild.me).send_messages:
                        channel = ch
                        break
                if not channel:
                    continue

                # Generate a proactive message
                personality = settings.get("personality", {})
                system_prompt = personality.get("system_prompt", "You are a friendly chatbot.")
                auto_router = settings.get("auto_router_enabled", False)
                allowed_models = settings.get("auto_router_allowed_models", [])
                model = settings.get("model", "meta-llama/llama-4-maverick:free")

                result = await llm_handler.chat(
                    [
                        {"role": "user", "content": "Send a brief, casual message to the chat. Something interesting, funny, or thought-provoking. Keep it under 2 sentences."}
                    ],
                    model=model,
                    system_prompt=system_prompt,
                    auto_router=auto_router,
                    allowed_models=allowed_models if allowed_models else None,
                    temperature=1.2,
                )
                if result and result.get("content"):
                    text = result["content"][:2000]
                    await channel.send(text)
                    logger.info(f"Proactive message sent to {guild.name}")

            # Wait between proactive messages (30 min default)
            await asyncio.sleep(1800)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Proactive loop error: {e}")
            await asyncio.sleep(300)


# ═══════════════════════════════════════════════════════════════
#  Commands
# ═══════════════════════════════════════════════════════════════

@bot.command(name="ping")
async def ping(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(f"Pong! `{latency}ms`")


@bot.command(name="model")
async def show_model(ctx):
    guild_id = str(ctx.guild.id) if ctx.guild else "dm"
    settings = await settings_manager.get_settings(guild_id)
    auto = settings.get("auto_router_enabled", False)
    model = settings.get("model", "meta-llama/llama-4-maverick:free")
    if auto:
        await ctx.send(f"**Auto Router** is ON — model is selected automatically per prompt.\nManual fallback: `{model}`")
    else:
        await ctx.send(f"Current model: `{model}`")


@bot.command(name="imagine")
async def imagine(ctx, *, prompt: str = None):
    """Generate an image using Z.ai."""
    guild_id = str(ctx.guild.id) if ctx.guild else "dm"
    settings = await settings_manager.get_settings(guild_id)
    if not settings.get("zai_image_gen_enabled", False):
        await ctx.send("Image generation is disabled. Enable it in the dashboard settings.")
        return
    if not prompt:
        await ctx.send("Give me a prompt! Usage: `!imagine a sunset over mountains`")
        return

    await ctx.send("Generating image...")
    b64 = await llm_handler.generate_image(prompt)
    if b64:
        import base64, io
        from discord import File
        img_bytes = base64.b64decode(b64)
        await ctx.send(file=File(fp=io.BytesIO(img_bytes), filename="generated.png"))
    else:
        await ctx.send("Failed to generate image. The Z.ai sidecar might not be running.")


@bot.command(name="reset")
async def reset_personality(ctx):
    """Reset personality to default."""
    guild_id = str(ctx.guild.id) if ctx.guild else "dm"
    settings = await settings_manager.get_settings(guild_id)
    settings["personality"] = {}
    await settings_manager.save_settings(guild_id)
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
