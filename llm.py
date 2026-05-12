import aiohttp
import base64
import os

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")


async def generate_llm_response(system_prompt, chat_history, model_name=None):
    """Sends the context to OpenRouter and gets a coherent response."""
    if not OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY is missing from environment variables!")
        return None

    # Fallback model if none specified
    if not model_name:
        # Legacy: check if old code passed model in first message
        if chat_history and "model" in chat_history[0]:
            model_name = chat_history[0]["model"]
            chat_history = chat_history[1:]  # strip it out
        else:
            model_name = "meta-llama/llama-3-8b-instruct"

    # Format the messages for the API — skip any legacy model keys
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
        "max_tokens": 150,  # Keep it short like a Discord message
        "temperature": 0.9  # A little creative
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
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
    """Generate an image via OpenRouter image generation endpoint.

    Returns bytes (PNG/JPEG) or None on failure.
    """
    if not OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY is missing!")
        return None

    if not model_name:
        model_name = "stability-ai/stable-diffusion-xl-1024-v1-0"

    url = "https://openrouter.ai/api/v1/image/generations"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://discord-bot.local",
    }

    data = {
        "model": model_name,
        "prompt": prompt,
        "n": 1,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, headers=headers, json=data,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    images = result.get("data", [])
                    if images:
                        img_url = images[0].get("url")
                        if img_url:
                            # Download the image bytes
                            async with session.get(
                                img_url,
                                timeout=aiohttp.ClientTimeout(
                                    total=30
                                )
                            ) as img_resp:
                                if img_resp.status == 200:
                                    return await img_resp.read()
                                else:
                                    print(f"Image download failed: {img_resp.status}")
                                    return None
                        # Some models return base64 directly
                        b64 = images[0].get("b64_json")
                        if b64:
                            return base64.b64decode(b64)
                    print("Image generation returned no data")
                    return None
                else:
                    error_text = await resp.text()
                    print(f"Image Gen Error: {resp.status} - {error_text}")
                    return None
    except Exception as e:
        print(f"Image Gen API Error: {e}")
        return None
