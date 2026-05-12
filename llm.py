import aiohttp
import os
from urllib.parse import quote

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")


async def generate_llm_response(
    system_prompt,
    chat_history,
    model_name=None,
    max_tokens=150,
):
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
        "max_tokens": max_tokens,
        "temperature": 0.3 if max_tokens > 300 else 0.9,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, headers=headers, json=data
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    content = (
                        result.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                    return content.strip() if content else None
                else:
                    error_text = await resp.text()
                    print(
                        f"OpenRouter Error: "
                        f"{resp.status} - {error_text}"
                    )
                    return None
    except Exception as e:
        print(f"LLM API Error: {e}")
        return None


async def generate_image(prompt, model_name=None):
    """Generate an image via Pollinations.ai (free, no API key).

    Returns bytes (PNG) or None on failure.
    """
    encoded = quote(prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1024&height=1024&nologo=true"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
                else:
                    error_text = await resp.text()
                    print(
                        f"Pollinations Error: "
                        f"{resp.status} - {error_text[:200]}"
                    )
                    return None
    except Exception as e:
        print(f"Image Gen Error: {e}")
        return None
