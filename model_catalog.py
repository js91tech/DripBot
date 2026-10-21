"""
Single source of truth for the OpenRouter models the bot offers.

OpenRouter retires model slugs regularly, and a retired slug returns
404 "No endpoints found". Keep this list in sync with
https://openrouter.ai/api/v1/models and add the retired slug to
LEGACY_MODEL_MAP so servers that saved it keep working.
"""

DEFAULT_MODEL = "openrouter/free"
FALLBACK_MODEL = "openrouter/free"

FREE_MODELS = [
    "openrouter/free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "minimax/minimax-m3.1-flash:free",
    "thinkingmachines/inkling:free",
    "thinkingmachines/inkling-small:free",
    "poolside/laguna-s-2.1:free",
]

PAID_MODELS = [
    "openai/gpt-4o",
    "openai/gpt-4.1",
    "openai/gpt-5.4-mini",
    "openai/gpt-5.5",
    "openai/o4-mini",
    "anthropic/claude-sonnet-5.5",
    "anthropic/claude-opus-5.5",
    "anthropic/claude-haiku-5.5",
    "google/gemini-2.5-pro",
    "google/gemini-2.5-flash",
    "google/gemini-3.8-flash",
    "meta-llama/llama-4-maverick",
    "deepseek/deepseek-chat-v3-0324",
    "deepseek/deepseek-v4-flash",
    "mistralai/mistral-large-2512",
    "x-ai/grok-4.3",
    "x-ai/grok-4.7",
    "qwen/qwen3.7-plus",
    "perplexity/sonar-pro",
    "cohere/command-a",
    "microsoft/phi-4",
]

LEGACY_MODEL_MAP = {
    "meta-llama/llama-4-maverick:free": "openrouter/free",
    "google/gemma-3-27b-it:free": "google/gemma-4-31b-it:free",
    "google/gemma-3-12b-it:free": "google/gemma-4-26b-a4b-it:free",
    "qwen/qwen3-235b-a22b:free": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "qwen/qwen3-32b:free": "nvidia/nemotron-3.5-lightning:free",
    "microsoft/phi-4-reasoning-plus:free": "thinkingmachines/inkling-small:free",
    "deepseek/deepseek-r1:free": "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/llama-3.1-nemotron-70b-instruct:free": "nvidia/nemotron-3-super-120b-a12b:free",
    "mistralai/mistral-small-3.1-24b-instruct:free": "openrouter/free",
    "meta-llama/llama-3.3-70b-instruct:free": "openrouter/free",
    "google/gemini-2.0-flash-exp:free": "google/gemma-4-31b-it:free",
    "anthropic/claude-sonnet-4": "anthropic/claude-sonnet-5.5",
    "anthropic/claude-opus-4": "anthropic/claude-opus-5.5",
    "anthropic/claude-haiku-3.5": "anthropic/claude-haiku-5.5",
    "anthropic/claude-3.5-sonnet": "anthropic/claude-sonnet-5.5",
    "anthropic/claude-3.7-sonnet": "anthropic/claude-sonnet-5.5",
    "x-ai/grok-3": "x-ai/grok-4.3",
    "x-ai/grok-3-mini": "x-ai/grok-4.3",
    "mistralai/mistral-large-2411": "mistralai/mistral-large-2512",
    "perplexity/llama-3.1-sonar-huge-128k-online": "perplexity/sonar-pro",
    "nvidia/llama-3.1-nemotron-ultra-253b": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "qwen/qwen3-235b-a22b": "qwen/qwen3.7-plus",
    "meta-llama/llama-3.1-405b-instruct": "meta-llama/llama-4-maverick",
}


def canonical_model(model):
    """Map a retired model slug to its live replacement; unknown slugs pass through."""
    if not model:
        return DEFAULT_MODEL
    return LEGACY_MODEL_MAP.get(model, model)
