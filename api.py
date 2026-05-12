from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn
import os
import asyncio
import discord
from discord import ActivityType

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


class StatusUpdate(BaseModel):
    status: str  # online, idle, dnd, invisible
    text: str = ""
    activity_type: str = "playing"  # playing, listening, watching, competing


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
# BOT PROFILE ENDPOINTS
# ==========================================
@app.get("/api/bot/profile")
async def get_profile():
    """Return bot's current avatar, status, and name."""
    if not bot_instance or not bot_ready:
        raise HTTPException(503, "Bot not ready yet")
    user = bot_instance.user
    avatar_url = (
        user.avatar.url if user.avatar else ""
    )
    status_map = {
        discord.Status.online: "online",
        discord.Status.idle: "idle",
        discord.Status.dnd: "dnd",
        discord.Status.invisible: "invisible",
    }
    status_str = status_map.get(
        user.status, "online"
    )
    activity_text = ""
    activity_type = ""
    if user.activity:
        activity_text = user.activity.name
        type_map = {
            ActivityType.playing: "playing",
            ActivityType.listening: "listening",
            ActivityType.watching: "watching",
            ActivityType.competing: "competing",
        }
        activity_type = type_map.get(
            user.activity.type, "playing"
        )
    return {
        "username": user.name,
        "avatar_url": avatar_url,
        "status": status_str,
        "activity_text": activity_text,
        "activity_type": activity_type,
    }


@app.post("/api/bot/avatar")
async def set_avatar(file: UploadFile = File(...)):
    """Upload a new avatar for the bot."""
    if not bot_instance or not bot_ready:
        raise HTTPException(503, "Bot not ready yet")
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            400, "Image must be under 10MB"
        )
    try:
        await _run_async(
            bot_instance.user.edit(avatar=content)
        )
        return {"status": "ok"}
    except discord.errors.HTTPException as e:
        raise HTTPException(
            400, f"Discord error: {e.text}"
        )
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/bot/status")
async def set_status(body: StatusUpdate):
    """Set the bot's presence status and activity."""
    if not bot_instance or not bot_ready:
        raise HTTPException(503, "Bot not ready yet")
    valid_statuses = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
        "invisible": discord.Status.invisible,
    }
    status_val = valid_statuses.get(body.status)
    if not status_val:
        raise HTTPException(
            400, f"Invalid status: {body.status}"
        )
    type_map = {
        "playing": ActivityType.playing,
        "listening": ActivityType.listening,
        "watching": ActivityType.watching,
        "competing": ActivityType.competing,
    }
    act_type = type_map.get(
        body.activity_type, ActivityType.playing
    )
    activity = None
    if body.text:
        activity = discord.Activity(
            type=act_type, name=body.text
        )
    try:
        await _run_async(
            bot_instance.change_presence(
                status=status_val, activity=activity
            )
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/llm/models")
async def list_llm_models():
    """Return curated list of LLM models on OpenRouter."""
    return [
        {
            "id": "meta-llama/llama-3-8b-instruct",
            "name": "Llama 3 8B",
            "desc": "Fast, cheap, general-purpose chat",
            "tag": "free",
        },
        {
            "id": "meta-llama/llama-3-70b-instruct",
            "name": "Llama 3 70B",
            "desc": "Smarter than 8B, good balance of speed and quality",
            "tag": "popular",
        },
        {
            "id": "mistralai/mistral-7b-instruct",
            "name": "Mistral 7B",
            "desc": "Fast lightweight model, great at following instructions",
            "tag": "free",
        },
        {
            "id": "mistralai/mixtral-8x7b-instruct",
            "name": "Mixtral 8x7B",
            "desc": "Mixture-of-experts, strong reasoning",
            "tag": "popular",
        },
        {
            "id": "google/gemma-2-9b-it",
            "name": "Gemma 2 9B",
            "desc": "Google's efficient model, good at creative tasks",
            "tag": "free",
        },
        {
            "id": "anthropic/claude-3.5-sonnet",
            "name": "Claude 3.5 Sonnet",
            "desc": "Top-tier intelligence, great at nuance and long context",
            "tag": "premium",
        },
        {
            "id": "anthropic/claude-3-haiku",
            "name": "Claude 3 Haiku",
            "desc": "Fast Anthropic model, smart and responsive",
            "tag": "premium",
        },
        {
            "id": "openai/gpt-4o-mini",
            "name": "GPT-4o Mini",
            "desc": "OpenAI's efficient model, fast and capable",
            "tag": "popular",
        },
        {
            "id": "openai/gpt-4o",
            "name": "GPT-4o",
            "desc": "OpenAI's flagship model, best overall quality",
            "tag": "premium",
        },
        {
            "id": "nousresearch/nous-capybara-7b",
            "name": "Capybara 7B",
            "desc": "Creative and conversational, good for roleplay",
            "tag": "free",
        },
    ]


# ==========================================
# SERVER RUNNER
# ==========================================
def run_api():
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
