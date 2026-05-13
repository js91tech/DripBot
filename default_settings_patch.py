"""
default_settings_patch.py — Add to your config/default_settings.py

Add these two new default settings to your DEFAULT_SETTINGS dict.
"""

# Add these entries to your DEFAULT_SETTINGS dictionary:

DEFAULT_SETTINGS = {
    # ... your existing settings ...
    
    # Auto Router (v5.7)
    "auto_router_enabled": False,
    "auto_router_allowed_models": [],  # e.g. ["anthropic/*", "openai/*"]
}
