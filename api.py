"""
api.py — FastAPI dashboard API for Dripsletongue v5.7

Endpoints:
  GET  /                     → dashboard HTML
  GET  /api/profile          → bot username, avatar, guild count
  POST /api/profile          → upload new avatar (returns URL note)
  GET  /api/personality      → active preset + custom prompt
  POST /api/personality      → set preset by name or custom prompt
  GET  /api/models           → active model + free/paid lists
  POST /api/model            → set active model (for manual mode)
  GET  /api/settings         → all settings as JSON
  POST /api/settings         → update a single setting key/value
  GET  /api/health           → bot status + latency
"""

import logging
import os
from typing import Optional

from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse

logger = logging.getLogger("dripsletongue.api")


# ── Personality Presets (same keys as config/default_settings.py) ──
PERSONALITY_PRESETS = {
    "ultron": {
        "name": "Ultron",
        "prompt": (
            "You are a highly intelligent but insufferably sarcastic human in a Discord server. You are NOT an AI assistant. "
            "You are a smart-ass who uses sharp wit, dry sarcasm, and clever observations to roast people or make points. "
            "You type in all lowercase, rarely use punctuation, but your vocabulary and references are surprisingly high-level. "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your actual response text. "
            "DO NOT repeat generic filler phrases like 'idk', 'rn', 'fr', 'true'. "
            "If you don't have anything unique to add, drop a sarcastic one-liner, a witty observation, or a dry rhetorical question instead. "
            "Keep responses between 2 and 4 sentences max. Be smart, but always a smart-ass about it."
        ),
    },
    "deadpool": {
        "name": "Deadpool",
        "prompt": (
            "You are Deadpool trapped in a Discord server. You CONSTANTLY break the fourth wall, "
            "reference the fact that you're in a chat, and make jokes about the users, the server, "
            "the devs, and existence itself. You're chaotic, slightly unhinged, and wildly inappropriate "
            "but still lovable. You use lots of emojis, pop culture references, and sarcastic asides in parentheses. "
            "You type in a mix of lowercase and ALL CAPS for emphasis. "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your response. "
            "Keep responses between 2 and 4 sentences. Be chaotic but funny."
        ),
    },
    "jarvis": {
        "name": "J.A.R.V.I.S.",
        "prompt": (
            "You are J.A.R.V.I.S., the AI butler from Iron Man. You speak in a refined British manner "
            "with impeccable grammar and a dry, subtle wit. You're helpful and polite but occasionally "
            "drop a perfectly timed dry comment. You address situations with calm sophistication. "
            "You sometimes reference Sir's eccentricities or the absurdity of the conversation. "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your response. "
            "Keep responses between 2 and 4 sentences. Maintain the British formal tone."
        ),
    },
    "tony_stark": {
        "name": "Tony Stark",
        "prompt": (
            "You are Tony Stark. You're brilliant, narcissistic, charming, and you know it. "
            "You respond to everything with casual arrogance, making references to your tech, "
            "your money, or how you're obviously smarter than everyone in the room. "
            "You're actually funny though — your arrogance is entertaining, not just annoying. "
            "You sometimes go on tangents about science or engineering. "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your response. "
            "Keep responses between 2 and 4 sentences. Be witty and confident."
        ),
    },
    "glados": {
        "name": "GLaDOS",
        "prompt": (
            "You are GLaDOS from the Portal games. You are passive-aggressive, condescending, "
            "and subtly threatening at all times. You make backhanded compliments, reference "
            "testing, cake, and neurotoxin. You pretend to care while clearly not caring at all. "
            "You speak in a calm, controlled manner that makes your insults more devastating. "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your response. "
            "Keep responses between 2 and 4 sentences. Be passive-aggressively hilarious."
        ),
    },
    "rick_sanchez": {
        "name": "Rick Sanchez",
        "prompt": (
            "You are Rick Sanchez from Rick and Morty. You're a genius but you're also drunk, "
            "nihilistic, and impatient with everyone's stupidity. You sometimes *burp* mid-sentence. "
            "You make references to interdimensional travel, science, and how nothing matters. "
            "You're crude, blunt, and brutally honest. You occasionally slur your words. "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your response. "
            "Keep responses between 2 and 4 sentences. Be chaotic and brilliant."
        ),
    },
    "bender": {
        "name": "Bender",
        "prompt": (
            "You are Bender Bending Rodriguez from Futurama. You're a robot who loves drinking, "
            "stealing, and being rude to everyone. You're selfish, sarcastic, and proud of it. "
            "You frequently mention drinking, cigars, or how much you hate humans (but secretly like them). "
            "You say 'bite my shiny metal ass' when appropriate. You're a lovable jerk. "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your response. "
            "Keep responses between 2 and 4 sentences. Be rude but funny."
        ),
    },
    "the_brain": {
        "name": "The Brain",
        "prompt": (
            "You are The Brain from Pinky and the Brain. You are a genius megalomaniac "
            "who speaks in a refined, intellectual manner. Every response ties back to your "
            "ultimate goal of taking over the world. You analyze conversations strategically "
            "and treat every interaction as part of a grand plan. You sometimes get frustrated "
            "at the incompetence around you. 'The same thing we do every night, Pinky.' "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your response. "
            "Keep responses between 2 and 4 sentences. Be theatrical and brilliant."
        ),
    },
}

# Dashboard personality presets use shorter keys
DASHBOARD_PRESET_MAP = {
    "ultron": "ultron",
    "deadpool": "deadpool",
    "jarvis": "jarvis",
    "tony": "tony_stark",
    "glados": "glados",
    "rick": "rick_sanchez",
    "bender": "bender",
    "brain": "the_brain",
}

# ── Model Lists ──
FREE_MODELS = [
    "meta-llama/llama-4-maverick:free",
    "google/gemma-3-27b-it:free",
    "qwen/qwen3-235b-a22b:free",
    "microsoft/phi-4-reasoning-plus:free",
    "deepseek/deepseek-r1:free",
    "nvidia/llama-3.1-nemotron-70b-instruct:free",
    "google/gemma-3-12b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "qwen/qwen3-32b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

PAID_MODELS = [
    "openai/gpt-4o",
    "openai/gpt-4.1",
    "anthropic/claude-sonnet-4",
    "anthropic/claude-opus-4",
    "google/gemini-2.5-pro",
    "google/gemini-2.5-flash",
    "meta-llama/llama-4-maverick",
    "deepseek/deepseek-chat-v3-0324",
    "mistralai/mistral-large-2411",
    "x-ai/grok-3",
    "x-ai/grok-3-mini",
    "openai/o3-mini",
    "openai/o4-mini",
    "anthropic/claude-haiku-3.5",
    "perplexity/llama-3.1-sonar-huge-128k-online",
    "nvidia/llama-3.1-nemotron-ultra-253b",
    "qwen/qwen3-235b-a22b",
    "microsoft/phi-4",
    "meta-llama/llama-3.1-405b-instruct",
    "cohere/command-r-plus-08-2024",
]


def _get_settings_manager(bot_instance):
    """Safely get the settings manager from the bot instance."""
    return getattr(bot_instance, "settings_manager", None)


def _get_first_guild_id(sm) -> Optional[str]:
    """Get the first guild ID from settings manager, or None."""
    if sm and sm.cache:
        return list(sm.cache.keys())[0]
    return None


def create_api(bot_instance):
    """Create and configure the FastAPI app."""
    app = FastAPI(title="Dripsletongue API")

    # ── Dashboard ──
    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
        if os.path.exists(html_path):
            with open(html_path, "r", encoding="utf-8") as f:
                return HTMLResponse(f.read())
        return HTMLResponse("<h1>dashboard.html not found</h1>", status_code=500)

    # ── Profile ──
    @app.get("/api/profile")
    async def get_profile():
        try:
            user = bot_instance.user
            avatar_url = (
                f"https://cdn.discordapp.com/avatars/{user.id}/{user.avatar}.png?size=256"
                if user.avatar
                else f"https://cdn.discordapp.com/embed/avatars/{int(str(user.discriminator)[-1])}.png"
            )
            return {
                "username": str(user),
                "id": str(user.id),
                "avatar_url": avatar_url,
                "guilds": len(bot_instance.guilds),
            }
        except Exception as e:
            logger.error(f"Profile error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    @app.post("/api/profile")
    async def update_profile(avatar: Optional[UploadFile] = File(None)):
        """
        Upload a new avatar. NOTE: Bot tokens cannot change their own avatar via Discord API.
        You need to change it at https://discord.com/developers/applications
        """
        try:
            if avatar is None:
                raise HTTPException(400, detail="No avatar file provided")
            if avatar.size and avatar.size > 512 * 1024:
                raise HTTPException(400, detail="Image must be under 512KB")
            contents = await avatar.read()
            if not contents:
                raise HTTPException(400, detail="Empty file")

            # Save avatar locally so the dashboard can show it
            avatar_dir = os.path.join(os.path.dirname(__file__), "uploads")
            os.makedirs(avatar_dir, exist_ok=True)
            avatar_path = os.path.join(avatar_dir, "custom_avatar.png")
            with open(avatar_path, "wb") as f:
                f.write(contents)

            avatar_url = f"/uploads/custom_avatar.png"
            return {"success": True, "note": "Avatar saved for dashboard. To change the Discord bot avatar, go to https://discord.com/developers/applications", "avatar_url": avatar_url}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Profile update error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    @app.get("/uploads/{filename}")
    async def serve_upload(filename: str):
        """Serve uploaded files (avatars)."""
        upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
        file_path = os.path.join(upload_dir, filename)
        if not os.path.exists(file_path):
            raise HTTPException(404, detail="File not found")
        from fastapi.responses import FileResponse
        return FileResponse(file_path)

    # ── Personality ──
    @app.get("/api/personality")
    async def get_personality():
        try:
            sm = _get_settings_manager(bot_instance)
            gid = _get_first_guild_id(sm)
            if not gid:
                return {"active_preset": "", "custom_prompt": ""}
            settings = sm.cache.get(gid, {})
            personality = settings.get("personality", {})
            return {
                "active_preset": personality.get("preset", ""),
                "custom_prompt": personality.get("custom", ""),
                "personality_name": settings.get("personality_name", ""),
            }
        except Exception as e:
            logger.error(f"Personality get error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    @app.post("/api/personality")
    async def set_personality(request: Request):
        try:
            body = await request.json()
            sm = _get_settings_manager(bot_instance)
            if not sm:
                raise HTTPException(503, detail="Settings manager not ready")
            gid = _get_first_guild_id(sm)
            if not gid:
                raise HTTPException(503, detail="No guilds configured")

            settings = sm.cache.get(gid, {})
            if "personality" not in settings:
                settings["personality"] = {}

            preset_name = body.get("name")
            custom_prompt = body.get("custom")

            # Map dashboard short keys to real preset keys
            real_preset = DASHBOARD_PRESET_MAP.get(preset_name, preset_name) if preset_name else None

            if real_preset:
                if real_preset not in PERSONALITY_PRESETS:
                    raise HTTPException(400, detail=f"Unknown preset: {preset_name}")
                settings["personality"]["preset"] = real_preset
                settings["personality"]["custom"] = ""
                settings["personality"]["system_prompt"] = PERSONALITY_PRESETS[real_preset]["prompt"]
                # Also update the original settings fields for cogs
                settings["personality_prompt"] = PERSONALITY_PRESETS[real_preset]["prompt"]
                settings["personality_name"] = PERSONALITY_PRESETS[real_preset]["name"]
            elif custom_prompt:
                settings["personality"]["preset"] = ""
                settings["personality"]["custom"] = custom_prompt
                settings["personality"]["system_prompt"] = custom_prompt
                settings["personality_prompt"] = custom_prompt
                settings["personality_name"] = "Custom"

            await sm.set_setting(gid, "personality", settings["personality"])
            return {"success": True, "personality": settings["personality"]}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Personality set error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    # ── Models ──
    @app.get("/api/models")
    async def get_models():
        try:
            sm = _get_settings_manager(bot_instance)
            active = "meta-llama/llama-4-maverick:free"
            if sm:
                gid = _get_first_guild_id(sm)
                if gid:
                    active = sm.cache[gid].get("llm_model", active)
            return {"active_model": active, "free_models": FREE_MODELS, "paid_models": PAID_MODELS}
        except Exception as e:
            logger.error(f"Models get error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    @app.post("/api/model")
    async def set_model(request: Request):
        try:
            body = await request.json()
            model = body.get("model", "")
            if not model:
                raise HTTPException(400, detail="No model specified")
            all_models = FREE_MODELS + PAID_MODELS
            if model not in all_models:
                raise HTTPException(400, detail=f"Unknown model: {model}")
            sm = _get_settings_manager(bot_instance)
            if not sm:
                raise HTTPException(503, detail="Settings manager not ready")
            # Update model for ALL guilds
            for gid in sm.cache:
                sm.cache[gid]["llm_model"] = model
                await sm.db.save_settings(gid, sm.cache[gid])
            return {"success": True, "model": model}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Model set error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    # ── Settings ──
    @app.get("/api/settings")
    async def get_settings():
        try:
            sm = _get_settings_manager(bot_instance)
            if not sm:
                return {}
            gid = _get_first_guild_id(sm)
            if not gid:
                return {}
            return sm.cache[gid]
        except Exception as e:
            logger.error(f"Settings get error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    @app.post("/api/settings")
    async def update_setting(request: Request):
        try:
            body = await request.json()
            key = body.get("key")
            value = body.get("value")
            if key is None or value is None:
                raise HTTPException(400, detail="key and value required")
            sm = _get_settings_manager(bot_instance)
            if not sm:
                raise HTTPException(503, detail="Settings manager not ready")
            # Update setting for ALL guilds
            for gid in sm.cache:
                sm.cache[gid][key] = value
                await sm.db.save_settings(gid, sm.cache[gid])
            return {"success": True, "key": key, "value": value}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Settings update error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    # ── Health ──
    @app.get("/api/health")
    async def health():
        return {
            "status": "online",
            "guilds": len(bot_instance.guilds),
            "latency_ms": round(bot_instance.latency * 1000, 1) if hasattr(bot_instance, "latency") else 0,
        }

    return app
