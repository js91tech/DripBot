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
import aiohttp

# ==========================================
# BULLETPROOF PATH & FILE DIAGNOSTIC ENGINE
# ==========================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

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

# --- BOT INTENTS ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class MarkovLLMBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents)
        self.db = None
        self.settings_manager = None

    async def setup_hook(self):
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
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")
        # Start keep-alive loop after bot is ready
        self.loop.create_task(self._keep_alive_loop())

    async def _keep_alive_loop(self):
        """
        Self-ping the bot's own health endpoint every 14 minutes
        to prevent Render from spinning down the service.
        """
        port = int(os.environ.get("PORT", 10000))
        health_url = f"http://localhost:{port}/api/health"
        # Wait 60 seconds after startup before first ping
        await asyncio.sleep(60)

        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(health_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            print(f"[KEEP-ALIVE] Self-ping OK at {discord.utils.utcnow()}")
                        else:
                            print(f"[KEEP-ALIVE] Self-ping returned {resp.status}")
            except Exception as e:
                print(f"[KEEP-ALIVE] Self-ping failed: {e}")

            # Ping every 14 minutes (840 seconds)
            await asyncio.sleep(840)


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
