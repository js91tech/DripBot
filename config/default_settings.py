# config/default_settings.py

# --- VALIDATORS ---
def is_bool(val):
    return str(val).lower() in [
        "true", "false", "yes", "no", "on", "off", "1", "0"
    ]


def is_int(val):
    try:
        int(val)
        return True
    except ValueError:
        return False


def is_float(val):
    try:
        float(val)
        return True
    except ValueError:
        return False


def is_valid_mode(val):
    return val.lower() == "llm"


# --- DEFAULTS ---
DEFAULTS = {
    "brain_mode": "llm",  # markov is dead, always llm
    "response_enabled": True,
    "cooldown_seconds": 10,
    "ignored_channels": [],
    "allowed_channels": [],
    "ignored_users": [],
    "learn_from_bots": False,
    "trigger_on_mention": True,
    "trigger_on_reply": True,
    "conversation_window_seconds": 120,
    "indirect_reply_chance": 0.40,
    "reaction_chance": 0.05,
    "random_reply_chance": 0.30,
    "random_mention_chance": 0.10,
    "gif_chance": 0.10,
    "personality_prefix": "",
    "personality_prompt": "",
    "llm_model": "meta-llama/llama-3-8b-instruct",
    "response_chance": 0.15,
    # Image generation
    "image_gen_enabled": True,
    "image_trigger": "imagine",
    "image_model": "stability-ai/stable-diffusion-xl-1024-v1-0",
}

VALIDATORS = {
    "brain_mode": is_valid_mode,
    "response_enabled": is_bool,
    "cooldown_seconds": is_int,
    "conversation_window_seconds": is_int,
    "indirect_reply_chance": is_float,
    "reaction_chance": is_float,
    "random_reply_chance": is_float,
    "random_mention_chance": is_float,
    "gif_chance": is_float,
    "response_chance": is_float,
    "learn_from_bots": is_bool,
    "trigger_on_mention": is_bool,
    "trigger_on_reply": is_bool,
}
