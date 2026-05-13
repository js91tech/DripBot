"""
api.py — FastAPI dashboard API for Dripsletongue v5.8

Endpoints:
  GET  /                     -> dashboard HTML
  GET  /api/guilds           -> list of guilds the bot is in (for server selector)
  GET  /api/profile          -> bot username, avatar, guild count
  POST /api/profile          -> upload new avatar (updates Discord too)
  GET  /api/personality      -> active preset + custom prompt
  POST /api/personality      -> set preset by name or custom prompt
  GET  /api/models           -> active model + free/paid lists
  POST /api/model            -> set active model (for manual mode)
  GET  /api/settings         -> all settings as JSON
  POST /api/settings         -> update a single setting key/value
  GET  /api/health           -> bot status + latency

All per-guild endpoints accept ?guild_id=xxx query parameter.
If not provided, uses the first guild (backward compatible).
"""

import logging
import os
from typing import Optional

from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Query
from fastapi.responses import HTMLResponse
from config.default_settings import PERSONALITY_PRESETS, DEFAULTS

logger = logging.getLogger("dripsletongue.api")


# -- Model Lists --
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
    """Get settings manager from bot instance. Returns (sm, error_response)."""
    sm = getattr(bot_instance, "settings_manager", None)
    if not sm:
        return None, HTTPException(503, detail="Settings manager not ready")
    if not sm.settings:
        return None, HTTPException(503, detail="No guilds loaded yet -- bot may still be starting")
    return sm, None


def _resolve_guild_id(bot_instance, sm, guild_id: Optional[str] = None):
    """Resolve which cached guild key to use.

    Dashboard requests send guild IDs as strings, while the settings cache is
    populated with Discord's integer guild IDs. Compare by string but return
    the original cache key so existing settings lookups keep working.
    """
    if guild_id is not None and str(guild_id).strip():
        requested = str(guild_id)
        for cached_gid in sm.settings:
            if str(cached_gid) == requested:
                return cached_gid
        raise HTTPException(404, detail=f"Unknown guild_id: {guild_id}")
    if not sm.settings:
        raise HTTPException(503, detail="No guilds loaded yet -- bot may still be starting")
    # Fallback to first available guild
    return next(iter(sm.settings))


def create_api(bot_instance):
    """Create and configure the FastAPI app."""
    app = FastAPI(title="Dripsletongue API")

    # -- Dashboard --
    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
        if os.path.exists(html_path):
            with open(html_path, "r", encoding="utf-8") as f:
                return HTMLResponse(f.read())
        return HTMLResponse("<h1>dashboard.html not found</h1>", status_code=500)

    # -- Guilds (Server Selector) --
    @app.get("/api/guilds")
    async def get_guilds():
        """Return list of guilds the bot is in, for the server selector dropdown."""
        try:
            guilds = []
            for g in bot_instance.guilds:
                icon_url = ""
                if g.icon:
                    icon_url = f"https://cdn.discordapp.com/icons/{g.id}/{g.icon}.png?size=64"
                guilds.append({
                    "id": str(g.id),
                    "name": g.name,
                    "icon": icon_url,
                    "member_count": g.member_count,
                })
            return {"guilds": guilds}
        except Exception as e:
            logger.error(f"Guilds list error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    # -- Profile --
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
        try:
            if avatar is None:
                raise HTTPException(400, detail="No avatar file provided")
            contents = await avatar.read()
            if not contents:
                raise HTTPException(400, detail="Empty file")
            if len(contents) > 512 * 1024:
                raise HTTPException(400, detail="Image must be under 512KB")

            # discord.py runs on the bot's event loop, but uvicorn is in a
            # separate thread. Use run_coroutine_threadsafe to bridge them.
            import asyncio
            loop = bot_instance.loop

            try:
                future = asyncio.run_coroutine_threadsafe(
                    bot_instance.user.edit(avatar=contents), loop
                )
                future.result(timeout=15)
            except Exception as discord_err:
                logger.error(f"Discord avatar update failed: {discord_err}", exc_info=True)
                raise HTTPException(500, detail=f"Discord rejected avatar: {discord_err}")

            # Refresh user object to get new avatar hash
            try:
                future = asyncio.run_coroutine_threadsafe(
                    bot_instance.user.fetch(), loop
                )
                future.result(timeout=10)
            except Exception:
                pass  # Non-critical -- avatar was already uploaded

            avatar_url = ""
            if bot_instance.user.avatar:
                avatar_url = f"https://cdn.discordapp.com/avatars/{bot_instance.user.id}/{bot_instance.user.avatar}.png?size=256"
            return {"success": True, "avatar_url": avatar_url}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Profile update error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    # -- Personality --
    @app.get("/api/personality")
    async def get_personality(guild_id: Optional[str] = Query(None)):
        try:
            sm, err = _get_settings_manager(bot_instance)
            if err:
                raise err
            gid = _resolve_guild_id(bot_instance, sm, guild_id)
            personality = sm.settings[gid].get("personality", {})
            return {
                "active_preset": personality.get("preset", ""),
                "custom_prompt": personality.get("custom", ""),
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Personality get error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    @app.post("/api/personality")
    async def set_personality(request: Request):
        try:
            body = await request.json()
            sm, err = _get_settings_manager(bot_instance)
            if err:
                raise err
            gid_param = body.get("guild_id")
            gid = _resolve_guild_id(bot_instance, sm, gid_param)
            settings = sm.settings[gid]

            if "personality" not in settings:
                settings["personality"] = {}

            preset_name = body.get("name")
            custom_prompt = body.get("custom")

            if preset_name:
                if preset_name not in PERSONALITY_PRESETS:
                    raise HTTPException(400, detail=f"Unknown preset: {preset_name}")
                settings["personality"]["preset"] = preset_name
                settings["personality"]["custom"] = ""
                settings["personality"]["system_prompt"] = PERSONALITY_PRESETS[preset_name]["prompt"]
                # Also set the flat key used by cogs/chat.py on_message handler
                settings["personality_prompt"] = PERSONALITY_PRESETS[preset_name]["prompt"]
                settings["personality_name"] = PERSONALITY_PRESETS[preset_name]["name"]
            elif custom_prompt:
                settings["personality"]["preset"] = ""
                settings["personality"]["custom"] = custom_prompt
                settings["personality"]["system_prompt"] = custom_prompt
                # Sync flat key for cog compat
                settings["personality_prompt"] = custom_prompt
                settings["personality_name"] = "Custom"

            await sm.save_settings(gid)
            return {"success": True, "personality": settings["personality"]}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Personality set error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    # -- Models --
    @app.get("/api/models")
    async def get_models(guild_id: Optional[str] = Query(None)):
        try:
            sm, err = _get_settings_manager(bot_instance)
            if err:
                raise err
            active = "meta-llama/llama-4-maverick:free"
            if sm and sm.settings:
                gid = _resolve_guild_id(bot_instance, sm, guild_id)
                # Read llm_model first (used by cogs), fall back to model (used by dashboard)
                active = sm.settings[gid].get("llm_model") or sm.settings[gid].get("model", active)
            return {"active_model": active, "free_models": FREE_MODELS, "paid_models": PAID_MODELS}
        except HTTPException:
            raise
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
            sm, err = _get_settings_manager(bot_instance)
            if err:
                raise err
            gid_param = body.get("guild_id")
            # If guild_id specified, update only that guild; otherwise update all
            # Sync both 'model' (dashboard) and 'llm_model' (cogs) so GUI
            # changes actually take effect in message responses.
            if gid_param is not None and str(gid_param).strip():
                gid = _resolve_guild_id(bot_instance, sm, gid_param)
                sm.settings[gid]["model"] = model
                sm.settings[gid]["llm_model"] = model
                await sm.save_settings(gid)
            else:
                for gid in sm.settings:
                    sm.settings[gid]["model"] = model
                    sm.settings[gid]["llm_model"] = model
                    await sm.save_settings(gid)
            return {"success": True, "model": model}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Model set error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    # -- Settings --
    @app.get("/api/settings")
    async def get_settings(guild_id: Optional[str] = Query(None)):
        try:
            sm, err = _get_settings_manager(bot_instance)
            if err:
                raise err
            gid = _resolve_guild_id(bot_instance, sm, guild_id)
            return sm.settings[gid]
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Settings get error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    @app.post("/api/settings")
    async def update_setting(request: Request):
        try:
            body = await request.json()
            key = body.get("key")
            if key is None or "value" not in body:
                raise HTTPException(400, detail="key and value required")
            value = body["value"]
            sm, err = _get_settings_manager(bot_instance)
            if err:
                raise err
            gid_param = body.get("guild_id")
            # If guild_id specified, update only that guild; otherwise update all
            if gid_param is not None and str(gid_param).strip():
                gid = _resolve_guild_id(bot_instance, sm, gid_param)
                sm.settings[gid][key] = value
                await sm.save_settings(gid)
            else:
                for gid in sm.settings:
                    sm.settings[gid][key] = value
                    await sm.save_settings(gid)
            return {"success": True, "key": key, "value": value}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Settings update error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    # -- Health --
    @app.get("/api/health")
    async def health():
        return {
            "status": "online",
            "guilds": len(bot_instance.guilds),
            "latency_ms": round(bot_instance.latency * 1000, 1) if hasattr(bot_instance, "latency") else 0,
        }

    return app
