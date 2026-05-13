import api as api_module
from config.settings_manager import SettingsManager
from engine.database import Database
from api import run_api
from llm import check_sidecar_health
import os
import sys
import discord
from discord.ext import commands
import threading
import asyncio
import subprocess
import aiohttp

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

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class MarkovLLMBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents)
        self.db = None
        self.settings_manager = None
        self.sidecar_process = None

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

        # Start Z.ai sidecar
        await self._start_sidecar()

        # Start keep-alive loop
        self.loop.create_task(self._keep_alive_loop())

    async def _start_sidecar(self):
        """Start the Z.ai Node.js sidecar as a subprocess."""
        sidecar_dir = os.path.join(CURRENT_DIR, "zai-sidecar")

        if not os.path.exists(os.path.join(sidecar_dir, "node_modules")):
            print("[SIDECAR] node_modules not found, skipping sidecar start.")
            print("[SIDECAR] Run these commands to set up:")
            print(f"  cd {sidecar_dir}")
            print(f"  npm install")
            return

        try:
            # Start sidecar as a subprocess
            log_file = open(os.path.join(sidecar_dir, "sidecar.log"), "a")
            self.sidecar_process = subprocess.Popen(
                ["node", "server.js"],
                cwd=sidecar_dir,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            print(f"[SIDECAR] Started Node.js sidecar (PID: {self.sidecar_process.pid})")

            # Wait a moment then health check
            await asyncio.sleep(3)
            if await check_sidecar_health():
                print("[SIDECAR] Health check passed - Z.ai features enabled!")
            else:
                print("[SIDECAR] Health check failed - Z.ai features will be unavailable")
                print("[SIDECAR] The bot will continue without vision/search/image-gen enhancements")
        except Exception as e:
            print(f"[SIDECAR] Failed to start: {e}")
            print("[SIDECAR] Bot will continue without Z.ai enhancements")

    async def _keep_alive_loop(self):
        port = int(os.environ.get("PORT", 10000))
        health_url = f"http://localhost:{port}/api/health"
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

            await asyncio.sleep(840)


bot = MarkovLLMBot()
api_module.bot_instance = bot

print("Starting API dashboard thread...")
threading.Thread(target=run_api, daemon=True).start()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("CRITICAL ERROR: DISCORD_TOKEN environment variable is missing!")
else:
    bot.run(TOKEN)
