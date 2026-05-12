from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn
import os
import asyncio

# ==========================================
# MODULE-LEVEL REFERENCES (set by bot.py)
# ==========================================
bot_instance = None
bot_loop = None
bot_ready = False

app = FastAPI(title="Discord Bot Dashboard", docs_url=None, redoc_url=None)


# ==========================================
# HELPERS
# ==========================================
def _run_async(coro):
    """Run an async coroutine from the bot's event loop."""
    if not bot_loop or not bot_ready:
        raise HTTPException(503, "Bot not ready yet")
    future = asyncio.run_coroutine_threadsafe(coro, bot_loop)
    return asyncio.wrap_future(future)


# ==========================================
# PYDANTIC MODELS
# ==========================================
class SettingsUpdate(BaseModel):
    updates: dict


class MemoryAdd(BaseModel):
    user_id: int
    note: str


# ==========================================
# HEALTH CHECK — Render needs this
# ==========================================
@app.get("/api/health")
async def health():
    return {
        "status": "ok" if bot_ready else "starting",
        "ready": bot_ready,
        "guilds": len(bot_instance.guilds) if bot_instance and bot_ready else 0
    }


# ==========================================
# DASHBOARD HTML
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "dashboard.html"
    )
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse(
            "<h1>dashboard.html not found</h1>"
        )


# ==========================================
# GUILD ENDPOINTS
# ==========================================
@app.get("/api/guilds")
async def list_guilds():
    if not bot_instance or not bot_ready:
        raise HTTPException(503, "Bot not ready yet")
    return [
        {"id": g.id, "name": g.name}
        for g in bot_instance.guilds
    ]


@app.get("/api/guilds/{guild_id}/channels")
async def list_channels(guild_id: int):
    if not bot_instance or not bot_ready:
        raise HTTPException(503, "Bot not ready yet")
    guild = bot_instance.get_guild(guild_id)
    if not guild:
        raise HTTPException(404, "Guild not found")
    return [
        {"id": ch.id, "name": f"#{ch.name}"}
        for ch in guild.text_channels
    ]


# ==========================================
# SETTINGS ENDPOINTS
# ==========================================
@app.get("/api/guilds/{guild_id}/settings")
async def get_settings(guild_id: int):
    settings = _run_async(
        bot_instance.settings_manager.get_settings(guild_id)
    )
    return await settings


@app.put("/api/guilds/{guild_id}/settings")
async def update_settings(guild_id: int, body: SettingsUpdate):
    if not body.updates:
        raise HTTPException(400, "No updates provided")
    await _run_async(
        bot_instance.settings_manager.update_settings(
            guild_id, body.updates
        )
    )
    return {"status": "ok"}


# ==========================================
# STATS ENDPOINTS
# ==========================================
@app.get("/api/guilds/{guild_id}/stats")
async def get_stats(guild_id: int):
    stats = _run_async(
        bot_instance.db.get_stats(guild_id)
    )
    return await stats


# ==========================================
# MEMORY ENDPOINTS
# ==========================================
@app.get("/api/guilds/{guild_id}/memories")
async def get_memories(guild_id: int):
    memories = _run_async(
        bot_instance.db.get_all_memories(guild_id)
    )
    return await memories


@app.post("/api/guilds/{guild_id}/memories")
async def add_memory(guild_id: int, body: MemoryAdd):
    await _run_async(
        bot_instance.db.add_memory(
            guild_id, body.user_id, body.note
        )
    )
    return {"status": "ok"}


@app.delete("/api/guilds/{guild_id}/memories/{user_id}")
async def delete_memories(guild_id: int, user_id: int):
    await _run_async(
        bot_instance.db.forget_memories(guild_id, user_id)
    )
    return {"status": "ok"}


@app.get("/api/guilds/{guild_id}/consolidated")
async def get_consolidated(guild_id: int):
    data = _run_async(
        bot_instance.db.get_consolidated_memory(guild_id)
    )
    return await data


# ==========================================
# SERVER RUNNER
# ==========================================
def run_api():
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
