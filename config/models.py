"""
config/models.py — Single source of truth for OpenRouter model IDs.

Every picker (dashboard API, dashboard HTML data comes from the API,
slash commands) and the LLM layer read their lists from here, so a model
retirement only has to be fixed in one place.

Why GPT-4o seemed to be "the only model that works": OpenRouter retires
and renames model IDs regularly. Most IDs that used to be hardcoded in
four separate files no longer exist in the catalog, so those requests
came back 404 before any generation happened. `openai/gpt-4o` was one of
the few survivors. Paid IDs below were checked against the live
OpenRouter catalog; free picks use the `openrouter/free` router or
current `:free` IDs so one provider going away does not break chat.

Guilds may already have a retired ID saved in their settings. Those are
transparently remapped by `normalize_model_id` at request time (see
LEGACY_MODEL_ALIASES), so existing servers heal without a settings reset.
"""

# Router that picks any currently-available free model. Used as the
# default because individual `:free` endpoints are retired/rate-limited
# far more often than paid ones.
DEFAULT_MODEL = "openrouter/free"

# Last-resort model when the requested one is unreachable (404/402/429/5xx).
FALLBACK_MODEL = "openrouter/free"

FREE_MODELS = [
    "openrouter/free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "minimax/minimax-m3.1-flash:free",
]

PAID_MODELS = [
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "openai/gpt-4.1",
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-opus-4.5",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-pro",
    "google/gemini-2.5-flash",
    "meta-llama/llama-4-maverick",
    "meta-llama/llama-4-scout",
    "deepseek/deepseek-chat-v3.1",
    "deepseek/deepseek-r1-0528",
    "mistralai/mistral-large-2512",
    "x-ai/grok-4.3",
    "openai/o3-mini",
    "openai/o4-mini",
    "microsoft/phi-4",
    "qwen/qwen3-235b-a22b-2507",
    "nvidia/nemotron-3-super-120b-a12b",
    "perplexity/sonar",
    "cohere/command-r-plus-08-2024",
]

ALL_MODELS = FREE_MODELS + PAID_MODELS

# Retired ID -> closest live replacement. Free retirements map to the
# free router (not a paid successor) so nobody silently starts paying;
# paid retirements map to the same family's current version.
LEGACY_MODEL_ALIASES = {
    # Free (all retired from the catalog)
    "meta-llama/llama-4-maverick:free": "openrouter/free",
    "google/gemma-3-27b-it:free": "google/gemma-4-31b-it:free",
    "google/gemma-3-12b-it:free": "google/gemma-4-26b-a4b-it:free",
    "qwen/qwen3-235b-a22b:free": "openrouter/free",
    "qwen/qwen3-32b:free": "openrouter/free",
    "microsoft/phi-4-reasoning-plus:free": "openrouter/free",
    "deepseek/deepseek-r1:free": "openrouter/free",
    "nvidia/llama-3.1-nemotron-70b-instruct:free": "nvidia/nemotron-3-super-120b-a12b:free",
    "mistralai/mistral-small-3.1-24b-instruct:free": "openrouter/free",
    "meta-llama/llama-3.3-70b-instruct:free": "openrouter/free",
    "google/gemini-2.0-flash-exp:free": "google/gemini-2.5-flash",
    # Paid (retired / renamed)
    "anthropic/claude-sonnet-4": "anthropic/claude-sonnet-4.5",
    "anthropic/claude-opus-4": "anthropic/claude-opus-4.5",
    "anthropic/claude-haiku-3.5": "anthropic/claude-haiku-4.5",
    "anthropic/claude-3.5-haiku": "anthropic/claude-haiku-4.5",
    "anthropic/claude-3.5-sonnet": "anthropic/claude-sonnet-4.5",
    "anthropic/claude-3.7-sonnet": "anthropic/claude-sonnet-4.5",
    "mistralai/mistral-large-2411": "mistralai/mistral-large-2512",
    "x-ai/grok-3": "x-ai/grok-4.3",
    "x-ai/grok-3-mini": "x-ai/grok-4.3",
    "perplexity/llama-3.1-sonar-huge-128k-online": "perplexity/sonar",
    "nvidia/llama-3.1-nemotron-ultra-253b": "nvidia/nemotron-3-super-120b-a12b",
    "qwen/qwen3-235b-a22b": "qwen/qwen3-235b-a22b-2507",
    "meta-llama/llama-3.1-405b-instruct": "meta-llama/llama-4-maverick",
    "deepseek/deepseek-chat-v3-0324": "deepseek/deepseek-chat-v3.1",
}


def normalize_model_id(model):
    """Map a retired model ID to its live replacement; pass others through."""
    if not model or not isinstance(model, str):
        return model
    return LEGACY_MODEL_ALIASES.get(model.strip(), model.strip())


# Models that burn completion tokens on hidden reasoning before any
# visible text. They need a much larger max_tokens floor than a plain
# chat model, or the reply comes back empty with finish_reason=length.
_REASONING_MARKERS = (
    "deepseek-r1",
    "reasoning",
    "thinking",
    "-o1",
    "/o1",
    "/o3",
    "/o4",
    "qwq",
    "qwen3",
    "gemini-2.5",
    "nemotron-3",
    "gemma-4",
    "minimax-m",
)


def is_reasoning_model(model) -> bool:
    lowered = f"/{(model or '').lower()}"
    return any(marker in lowered for marker in _REASONING_MARKERS)


def supports_temperature(model) -> bool:
    """OpenAI's o-series rejects `temperature`; most other models accept it."""
    lowered = (model or "").lower()
    return not any(
        lowered.startswith(prefix)
        for prefix in ("openai/o1", "openai/o3", "openai/o4")
    )
