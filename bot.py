import os
import sys
import discord
from discord.ext import commands
import threading
import asyncio
import aiohttp

# ==========================================
# BULLETPROOF PATH & FILE DIAGNOSTIC ENGINE
# ==========================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Force Python to look IN THIS EXACT FOLDER for imports
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# Verify the core files and subfolders exist before we even try to import them
required_files = ['api.py']
missing_files = [
    f for f in required_files
    if not os.path.exists(os.path.join(CURRENT_DIR, f))
]

if missing_files:
    print(
        f"CRITICAL ERROR: Missing files in "
        f"{CURRENT_DIR}: {', '.join(missing_files)}"
    )
    sys.exit(1)

if not os.path.exists(
    os.path.join(CURRENT_DIR, 'engine', 'database.py')
):
    print("CRITICAL ERROR: Missing engine/database.py!")
    sys.exit(1)

if not os.path.exists(
    os.path.join(CURRENT_DIR, 'config', 'settings_manager.py')
):
    print(
        "CRITICAL ERROR: Missing config/settings_manager.py!"
    )
    sys.exit(1)
# ==========================================


# IMPORT FROM YOUR EXACT FOLDERS
from config.settings_manager import SettingsManager
from engine.database import Database
import api as api_module
from api import run_api

# --- BOT INTENTS ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# --- BOT CLASS ---


class MarkovLLMBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="/",
            intents=intents,
        )
        self.db = None
        self.settings_manager = None

    async def setup_hook(self):
        """Runs automatically before the bot connects."""
        # Capture event loop for cross-thread API access
        api_module.bot_loop = asyncio.get_running_loop()

        print("Initializing Database...")
        self.db = Database()
        await self.db.init()

        print("Initializing Settings Manager...")
        self.settings_manager = SettingsManager(self.db)

        print("Loading Cogs...")
        await self.load_extension("cogs.chat")
        await self.load_extension("cogs.settings_cog")

        # MIGRATION: auto-fix any markov-era settings
        print("Running settings migration...")
        await self.settings_manager.migrate_all_guilds()

    async def on_ready(self):
        """Runs when the bot successfully connects."""
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")
        # Signal the dashboard that the bot is fully online
        api_module.bot_ready = True
        print("Dashboard: bot ready flag set")
        # Start the keep-alive self-ping
        self.loop.create_task(self._keep_alive())

    async def _keep_alive(self):
        """Ping our own health endpoint every 14 minutes.

        Render free tier spins down web services after 15 min
        of zero inbound HTTP traffic. The Discord WebSocket
        doesn't count, so we self-ping to stay warm.
        """
        await self.wait_until_ready()
        port = int(os.environ.get("PORT", 10000))
        url = f"http://localhost:{port}/api/health"
        # Wait 2 minutes after boot before first ping
        await asyncio.sleep(120)
        while not self.is_closed():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        timeout=aiohttp.ClientTimeout(
                            total=10
                        ),
                    ) as resp:
                        pass
            except Exception:
                pass
            # Ping every 14 minutes (Render timeout is 15)
            await asyncio.sleep(840)


# --- INITIALIZE AND RUN ---

bot = MarkovLLMBot()
api_module.bot_instance = bot

print("Starting API dashboard thread...")
threading.Thread(target=run_api, daemon=True).start()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print(
        "CRITICAL ERROR: DISCORD_TOKEN environment variable "
        "is missing!"
    )
else:
    bot.run(TOKEN)
