"""
config/default_settings.py — Dripsletongue v5.7
Default settings for new guilds.
Drop-in replacement.
"""

DEFAULT_SETTINGS = {
    # ── Core Chat ──
    "response_enabled": True,
    "model": "meta-llama/llama-4-maverick:free",

    # ── Auto Router (v5.7) ──
    "auto_router_enabled": False,
    "auto_router_allowed_models": [],

    # ── Personality ──
    "personality": {},

    # ── Features ──
    "markov_enabled": True,
    "memory_enabled": True,
    "proactive_enabled": False,

    # ── Z.ai Integration ──
    "vision_enabled": False,
    "web_search_enabled": False,
    "zai_image_gen_enabled": False,
}
