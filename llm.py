import aiohttp
import os
import re
import base64
import random

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")


async def generate_llm_response(system_prompt, chat_history, model_name=None):
    """Sends the context to OpenRouter and gets a coherent response."""
    if not OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY is missing from environment variables!")
        return None

    # Fallback model if none specified
    if not model_name:
        if chat_history and "model" in chat_history[0]:
            model_name = chat_history[0]["model"]
            chat_history = chat_history[1:]
        else:
            model_name = "meta-llama/llama-3-8b-instruct"

    # Format messages - skip legacy model keys
    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history:
        if "model" in msg:
            continue
        messages.append(msg)

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://discord-bot.local",
    }

    data = {
        "model": model_name,
        "messages": messages,
        "max_tokens": 150,
        "temperature": 0.9,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    return content.strip() if content else None
                else:
                    error_text = await resp.text()
                    print(f"OpenRouter Error: {resp.status} - {error_text}")
                    return None
    except Exception as e:
        print(f"LLM API Error: {e}")
        return None


async def generate_image(prompt, model_name=None):
    """
    Generate an image using OpenRouter with modalities API.
    Falls back to Pollinations.ai if OpenRouter fails.
    Returns a URL string or None.
    """
    if not prompt or not prompt.strip():
        return None

    clean_prompt = prompt.strip()

    # --- ATTEMPT 1: OpenRouter with modalities ---
    if OPENROUTER_API_KEY:
        try:
            img = await _openrouter_image(clean_prompt, model_name)
            if img:
                return img
            print("[IMAGE] OpenRouter returned no image, trying fallback...")
        except Exception as e:
            print(f"[IMAGE] OpenRouter failed: {e}, trying fallback...")

    # --- ATTEMPT 2: Pollinations.ai (free, no API key needed) ---
    try:
        img = await _pollinations_image(clean_prompt)
        if img:
            return img
    except Exception as e:
        print(f"[IMAGE] Pollinations failed: {e}")

    print("[IMAGE] All image generation methods failed.")
    return None


async def _openrouter_image(prompt, model_name=None):
    """Generate image via OpenRouter chat completions with modalities: ['text','image']."""
    if not model_name:
        model_name = "openai/gpt-4o"

    # Only certain models support image output - restrict to known ones
    IMAGE_CAPABLE_MODELS = [
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "anthropic/claude-3.5-sonnet",
        "anthropic/claude-3.7-sonnet",
        "google/gemini-2.0-flash-exp:free",
        "google/gemini-2.0-flash-thinking-exp:free",
    ]

    if model_name not in IMAGE_CAPABLE_MODELS:
        model_name = "openai/gpt-4o"

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://discord-bot.local",
    }

    data = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": f"Generate an image based on this description: {prompt}"
            }
        ],
        "modalities": ["text", "image"],
        "max_tokens": 4096,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                print(f"[IMAGE] OpenRouter {resp.status}: {error_text[:300]}")
                return None

            result = await resp.json()
            choices = result.get("choices", [])
            if not choices:
                return None

            message = choices[0].get("message", {})
            content = message.get("content", "")

            # content can be a list of parts or a string
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        # Check for image_url format
                        if part.get("type") == "image_url":
                            img_url = part.get("image_url", {}).get("url", "")
                            if img_url:
                                return img_url
                        # Some models return base64 inline
                        if part.get("type") == "image" and part.get("data"):
                            return f"data:image/png;base64,{part['data']}"
            elif isinstance(content, str):
                # If the response contains a URL, extract it
                urls = re.findall(r'https?://[^\s"\'<>]+\.(?:png|jpg|jpeg|gif|webp)', content)
                if urls:
                    return urls[0]

    return None


async def _pollinations_image(prompt):
    """Generate image via Pollinations.ai - free, no API key needed."""
    # Pollinations.ai supports seed for reproducibility
    seed = random.randint(1, 999999)
    encoded_prompt = aiohttp.helpers.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&seed={seed}&nologo=true"

    # Verify the URL works by doing a HEAD request
    async with aiohttp.ClientSession() as session:
        async with session.head(url, timeout=aiohttp.ClientTimeout(total=15), allow_redirects=True) as resp:
            if resp.status == 200:
                return url
            else:
                print(f"[IMAGE] Pollinations returned status {resp.status}")
                return None


async def parse_settings_command(user_message):
    """
    Parse a natural language settings command and return (key, value) or None.
    Example: "switch to model meta-llama/llama-3-70b" -> ("llm_model", "meta-llama/llama-3-70b")
    """
    if not user_message or not user_message.strip():
        return None

    msg = user_message.lower().strip()

    # Model switching patterns
    model_patterns = [
        r'(?:switch|change|set|use)\s+(?:to\s+)?(?:llm\s+)?model\s+["\']?([a-z0-9\-_./]+)',
        r'model\s*[:=]\s*["\']?([a-z0-9\-_./]+)',
        r'use\s+["\']?([a-z0-9\-_./]+)',
        r'switch\s+(?:to\s+)?["\']?([a-z0-9\-_./]+)',
    ]

    known_model_keywords = [
        "llama", "claude", "gpt", "gemini", "mistral", "mixtral",
        "sonnet", "opus", "haiku", "hermes", "qwen", "deepseek",
        "anthropic", "openai", "meta-llama", "google",
    ]

    for pattern in model_patterns:
        match = re.search(pattern, msg)
        if match:
            candidate = match.group(1)
            # Verify it looks like a real model identifier
            if any(kw in candidate for kw in known_model_keywords):
                return ("llm_model", candidate)

    # Image model switching
    img_model_patterns = [
        r'(?:image|img)\s+(?:model|gen(?:eration)?)\s+(?:switch|change|set|use|to)\s+["\']?([a-z0-9\-_./]+)',
        r'switch\s+(?:image|img)\s+model\s+(?:to\s+)?["\']?([a-z0-9\-_./]+)',
    ]
    for pattern in img_model_patterns:
        match = re.search(pattern, msg)
        if match:
            candidate = match.group(1)
            if any(kw in candidate for kw in known_model_keywords):
                return ("image_model", candidate)

    # Brain mode switching
    if any(kw in msg for kw in ["markov mode", "switch to markov", "use markov"]):
        return ("brain_mode", "markov")
    if any(kw in msg for kw in ["llm mode", "switch to llm", "use llm", "ai mode"]):
        return ("brain_mode", "llm")

    # Boolean toggles
    bool_settings = {
        "response": "response_enabled",
        "responding": "response_enabled",
        "learning": "learning_enabled",
        "talking": "response_enabled",
        "silent": "response_enabled",
    }
    for keyword, setting_key in bool_settings.items():
        if keyword in msg:
            if any(w in msg for w in ["turn on", "enable", "start"]):
                return (setting_key, True)
            if any(w in msg for w in ["turn off", "disable", "stop"]):
                return (setting_key, False)

    # Cooldown adjustment
    cooldown_match = re.search(r'cooldown\s+(?:to\s+)?(\d+)', msg)
    if cooldown_match:
        return ("cooldown_seconds", int(cooldown_match.group(1)))

    # Personality/prefix
    prefix_match = re.search(r'(?:personality|prefix|style)\s+(?:to\s+)?["\'](.+)["\']', msg, re.IGNORECASE)
    if prefix_match:
        return ("personality_prefix", prefix_match.group(1))

    return None
