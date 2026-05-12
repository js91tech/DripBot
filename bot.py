import api as api_module
from config.settings_manager import SettingsManager
from engine.database import Database
from api import run_api
import os
import sys
import discord
from discord.ext import commands
import threading
import asyncio

# ==========================================
# PATH SETUP
# ==========================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# Verify core files exist
required_files = ['api.py']
missing_files = [f for f in required_files if not os.path.exists(os.path.join(CURRENT_DIR, f))]

if missing_files:
    print(f"CRITICAL ERROR: Missing files in {CURRENT_DIR}: {', '.join(missing_files)}")
    sys.exit(1)

if not os.path.exists(os.path.join(CURRENT_DIR, 'engine', 'database.py')):
    print("CRITICAL ERROR: Missing engine/database.py!")
    sys.exit(1)

if not os.path.exists(os.path.join(CURRENT_DIR, 'config', 'settings_manager.py')):
    print("CRITICAL ERROR: Missing config/settings_manager.py!")
    sys.exit(1)

# ==========================================
# BOT INTENTS
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# FIX: Use "!" prefix instead of "/" which conflicts with Discord slash commands
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")


class MarkovLLMBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=COMMAND_PREFIX,
            intents=intents
        )
        self.db = None
        self.settings_manager = None

    async def setup_hook(self):
        """Runs automatically before the bot connects to Discord."""
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

    async def on_ready(self):
        """Runs when the bot successfully connects to Discord."""
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")


# --- INITIALIZE AND RUN ---
bot = MarkovLLMBot()
api_module.bot_instance = bot

print("Starting API dashboard thread...")
threading.Thread(target=run_api, daemon=True).start()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("CRITICAL ERROR: DISCORD_TOKEN environment variable is missing!")
else:
    bot.run(TOKEN)
