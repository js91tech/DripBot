"""
OpenRouter model IDs offered by the bot.

OpenRouter retires model IDs (free ones especially) without notice, and a
retired ID fails every request. Keep these lists in sync with
https://openrouter.ai/api/v1/models — `scripts/check_models.py` does that.
"""

# Free router: OpenRouter picks whichever free model is currently up, so this
# ID keeps working when individual :free models are pulled.
DEFAULT_MODEL = "openrouter/free"

# (display name, model id). Discord allows at most 25 choices per command.
FREE_MODELS = [
    ("Auto (best free model available)", "openrouter/free"),
    ("Gemma 4 31B (Free)", "google/gemma-4-31b-it:free"),
    ("Gemma 4 26B (Free)", "google/gemma-4-26b-a4b-it:free"),
    ("Nemotron 3 Super 120B (Free)", "nvidia/nemotron-3-super-120b-a12b:free"),
    ("Nemotron 3 Ultra 550B (Free)", "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ("Nemotron 3.5 Lightning (Free)", "nvidia/nemotron-3.5-lightning:free"),
    ("MiniMax M3.1 Flash (Free)", "minimax/minimax-m3.1-flash:free"),
    ("Inkling (Free)", "thinkingmachines/inkling:free"),
    ("Inkling Small (Free)", "thinkingmachines/inkling-small:free"),
    ("Dots 3 Note (Free)", "dots-studio/dots-3-note-preview:free"),
]

PAID_MODELS = [
    ("GPT-4o", "openai/gpt-4o"),
    ("GPT-4o Mini", "openai/gpt-4o-mini"),
    ("GPT-4.1", "openai/gpt-4.1"),
    ("GPT-5.4 Mini", "openai/gpt-5.4-mini"),
    ("GPT-5.5", "openai/gpt-5.5"),
    ("o4-mini", "openai/o4-mini"),
    ("Claude Haiku 5.5", "anthropic/claude-haiku-5.5"),
    ("Claude Sonnet 5.5", "anthropic/claude-sonnet-5.5"),
    ("Claude Opus 5.5", "anthropic/claude-opus-5.5"),
    ("Gemini 2.5 Flash", "google/gemini-2.5-flash"),
    ("Gemini 3.8 Flash", "google/gemini-3.8-flash"),
    ("Gemini 3.1 Pro", "google/gemini-3.1-pro-preview"),
    ("Grok 4.7", "x-ai/grok-4.7"),
    ("DeepSeek V3.2", "deepseek/deepseek-v3.2"),
    ("DeepSeek Chat V3", "deepseek/deepseek-chat-v3-0324"),
    ("Llama 4 Maverick", "meta-llama/llama-4-maverick"),
    ("Llama 3.3 70B", "meta-llama/llama-3.3-70b-instruct"),
    ("Mistral Large 3", "mistralai/mistral-large-2512"),
    ("Qwen3.8 Flash", "qwen/qwen3.8-flash"),
    ("Perplexity Sonar (web)", "perplexity/sonar"),
]

# Only models whose output modalities include "image" can draw.
IMAGE_MODELS = [
    ("Z.ai Sidecar (Free)", "zai-sidecar"),
    ("Gemini 2.5 Flash Image", "google/gemini-2.5-flash-image"),
    ("Gemini 3.1 Flash Image", "google/gemini-3.1-flash-image"),
    ("Gemini 3 Pro Image", "google/gemini-3-pro-image"),
    ("GPT-5 Image Mini", "openai/gpt-5-image-mini"),
    ("GPT-5 Image", "openai/gpt-5-image"),
    ("Pollinations (Always Free)", "pollinations"),
]
DEFAULT_IMAGE_MODEL = "google/gemini-2.5-flash-image"

# Saved settings still hold these. Each maps to the closest current model at a
# similar or lower price, so a server never moves to a pricier tier on its own.
RETIRED_MODELS = {
    "meta-llama/llama-4-maverick:free": DEFAULT_MODEL,
    "google/gemma-3-27b-it:free": "google/gemma-4-31b-it:free",
    "google/gemma-3-12b-it:free": "google/gemma-4-26b-a4b-it:free",
    "qwen/qwen3-235b-a22b:free": DEFAULT_MODEL,
    "qwen/qwen3-32b:free": DEFAULT_MODEL,
    "microsoft/phi-4-reasoning-plus:free": DEFAULT_MODEL,
    "deepseek/deepseek-r1:free": DEFAULT_MODEL,
    "nvidia/llama-3.1-nemotron-70b-instruct:free": "nvidia/nemotron-3-super-120b-a12b:free",
    "mistralai/mistral-small-3.1-24b-instruct:free": DEFAULT_MODEL,
    "meta-llama/llama-3.3-70b-instruct:free": DEFAULT_MODEL,
    "google/gemini-2.0-flash-exp:free": DEFAULT_MODEL,
    "anthropic/claude-sonnet-4": "anthropic/claude-sonnet-5.5",
    "anthropic/claude-opus-4": "anthropic/claude-opus-5.5",
    "anthropic/claude-haiku-3.5": "anthropic/claude-haiku-5.5",
    "anthropic/claude-3.5-sonnet": "anthropic/claude-sonnet-5.5",
    "anthropic/claude-3.7-sonnet": "anthropic/claude-sonnet-5.5",
    "mistralai/mistral-large-2411": "mistralai/mistral-large-2512",
    "x-ai/grok-3": "x-ai/grok-4.7",
    "x-ai/grok-3-mini": "x-ai/grok-4.3",
    "openai/o3-mini": "openai/o4-mini",
    "perplexity/llama-3.1-sonar-huge-128k-online": "perplexity/sonar",
    "nvidia/llama-3.1-nemotron-ultra-253b": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "qwen/qwen3-235b-a22b": "qwen/qwen3-235b-a22b-2507",
    "meta-llama/llama-3.1-405b-instruct": "meta-llama/llama-3.3-70b-instruct",
}

# Old image picks were chat models that cannot output images.
RETIRED_IMAGE_MODELS = {
    "openai/gpt-4o": DEFAULT_IMAGE_MODEL,
    "openai/gpt-4o-mini": DEFAULT_IMAGE_MODEL,
    "anthropic/claude-3.5-sonnet": DEFAULT_IMAGE_MODEL,
    "anthropic/claude-3.7-sonnet": DEFAULT_IMAGE_MODEL,
    "google/gemini-2.0-flash-exp:free": DEFAULT_IMAGE_MODEL,
}

FREE_MODEL_IDS = [model_id for _, model_id in FREE_MODELS]
PAID_MODEL_IDS = [model_id for _, model_id in PAID_MODELS]


def resolve_model(model_id):
    """Swap a retired chat model ID for its replacement."""
    if not model_id:
        return DEFAULT_MODEL
    return RETIRED_MODELS.get(model_id, model_id)


def resolve_image_model(model_id):
    if not model_id:
        return "zai-sidecar"
    return RETIRED_IMAGE_MODELS.get(model_id, model_id)
