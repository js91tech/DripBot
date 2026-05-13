"""
llm.py — Complete LLM handler for Dripsletongue v5.8

Features:
  - OpenRouter chat completions (manual model + auto router)
  - OpenRouter image generation via modalities API
  - Z.ai sidecar integration (vision, image gen, web search)
  - Pollinations.ai fallback for image gen
  - Module-level wrapper functions for cog compatibility

Drop this file in your project root, replacing the old llm.py.
"""

import aiohttp
import hashlib
import json
import logging
import os
from typing import Optional, List

logger = logging.getLogger("dripsletongue.llm")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
SIDECAR_URL = os.environ.get("ZAI_SIDECAR_URL", "http://localhost:3456")

# Default model (used when auto-router is off)
DEFAULT_MODEL = "meta-llama/llama-4-maverick:free"


class LLMHandler:
    def __init__(self):
        self.api_key = OPENROUTER_API_KEY
        self.default_model = DEFAULT_MODEL

    # ── OpenRouter Chat (with Auto Router) ──

    async def chat(
        self,
        messages: list,
        model: str = None,
        system_prompt: str = None,
        auto_router: bool = False,
        allowed_models: List[str] = None,
        temperature: float = 0.8,
        max_tokens: int = 2048,
    ) -> dict:
        """
        Send a chat completion to OpenRouter.
        If auto_router=True, uses 'openrouter/auto' which picks the best model.
        Otherwise uses the specified model or DEFAULT_MODEL.
        Returns dict with 'content' and 'model_used' keys, or None on failure.
        """
        if not self.api_key:
            logger.error("No OPENROUTER_API_KEY set")
            return None

        # Build the messages list
        final_messages = []
        if system_prompt:
            final_messages.append({"role": "system", "content": system_prompt})
        final_messages.extend(messages)

        # Determine model
        if auto_router:
            effective_model = "openrouter/auto"
        elif model:
            effective_model = model
        else:
            effective_model = self.default_model

        # Build request body
        body = {
            "model": effective_model,
            "messages": final_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Add allowed_models filter for auto-router
        if auto_router and allowed_models:
            body["allowed_models"] = allowed_models

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/dripsletongue",
            "X-Title": "Dripsletongue Bot",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{OPENROUTER_BASE}/chat/completions",
                    json=body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=90),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"OpenRouter {resp.status}: {error_text[:300]}")
                        return None

                    data = await resp.json()

                    content = ""
                    if data.get("choices"):
                        content = data["choices"][0].get("message", {}).get("content", "")

                    return {
                        "content": content,
                        "model_used": data.get("model", effective_model),
                        "usage": data.get("usage", {}),
                    }

        except aiohttp.ClientError as e:
            logger.error(f"OpenRouter request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return None

    # ── OpenRouter Image Generation (via modalities) ──

    async def generate_image_openrouter(self, prompt: str, model: str = "openai/gpt-4o",
                                        size: str = "1024x1024") -> str:
        """
        Generate an image via OpenRouter using the modalities API.
        Returns a data:image URL or empty string on failure.
        """
        if not self.api_key:
            logger.error("No OPENROUTER_API_KEY set")
            return ""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/dripsletongue",
            "X-Title": "Dripsletongue Bot",
        }

        body = {
            "model": model,
            "messages": [{"role": "user", "content": f"Generate an image: {prompt}"}],
            "modalities": ["text", "image"],
            "temperature": 0.7,
            "max_tokens": 2048,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{OPENROUTER_BASE}/chat/completions",
                    json=body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"OpenRouter image gen {resp.status}: {error_text[:300]}")
                        return ""

                    data = await resp.json()

                    # OpenRouter returns images in different formats depending on the model.
                    # Some return markdown ![image](data:...) in the content.
                    # Some return separate content blocks.
                    content = ""
                    if data.get("choices"):
                        message = data["choices"][0].get("message", {})
                        content = message.get("content", "")

                    # Check for inline data:image in content
                    if "data:image" in content:
                        import re
                        match = re.search(r'(data:image/[^;]+;base64,[A-Za-z0-9+/=]+)', content)
                        if match:
                            return match.group(1)

                    # Check for image_url in response (some models)
                    if data.get("choices"):
                        message = data["choices"][0].get("message", {})
                        if isinstance(message, dict) and "content" in message:
                            # Some models return a list of content blocks
                            c = message["content"]
                            if isinstance(c, list):
                                for block in c:
                                    if isinstance(block, dict) and block.get("type") == "image_url":
                                        return block.get("image_url", {}).get("url", "")

                    logger.warning(f"OpenRouter image gen returned no image. Content: {content[:200]}")
                    return ""

        except aiohttp.ClientError as e:
            logger.error(f"OpenRouter image gen failed: {e}")
            return ""
        except Exception as e:
            logger.error(f"Image gen error: {e}")
            return ""

    # ── Z.ai Sidecar: Generic request ──

    async def _sidecar_post(self, endpoint: str, data: dict, timeout: int = 60) -> Optional[dict]:
        """Send request to local Z.ai sidecar."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{SIDECAR_URL}{endpoint}",
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        body = await resp.text()
                        logger.error(f"Sidecar {endpoint} returned {resp.status}: {body[:200]}")
                        return None
        except aiohttp.ClientError:
            logger.debug(f"Sidecar not reachable ({endpoint}) — is it running?")
            return None
        except Exception as e:
            logger.error(f"Sidecar error ({endpoint}): {e}")
            return None

    # ── Z.ai Sidecar: Vision ──

    async def analyze_image(
        self, image_url: str = None, image_b64: str = None, prompt: str = "Describe this image in detail."
    ) -> str:
        """Analyze an image via Z.ai sidecar. Returns description text or empty string."""
        try:
            data = {"prompt": prompt}
            if image_b64:
                data["image_b64"] = image_b64
            elif image_url:
                data["image_url"] = image_url
            else:
                return ""

            result = await self._sidecar_post("/vision", data, timeout=90)
            if result and "content" in result:
                return result["content"]
            elif result and "error" in result:
                logger.error(f"Sidecar vision error: {result['error']}")
            return ""
        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            return ""

    # ── Z.ai Sidecar: Image Generation ──

    async def generate_image_sidecar(self, prompt: str, size: str = "1024x1024") -> str:
        """Generate an image via Z.ai sidecar. Returns base64 PNG or empty string."""
        try:
            logger.info(f"[SIDECAR] Generating image: prompt=\"{prompt[:80]}\", size={size}")
            result = await self._sidecar_post("/generate", {"prompt": prompt, "size": size}, timeout=120)
            if result and "image_b64" in result:
                b64_len = len(result["image_b64"])
                logger.info(f"[SIDECAR] Image generated successfully (base64 len: {b64_len})")
                return result["image_b64"]
            elif result and "error" in result:
                logger.error(f"[SIDECAR] Image gen error: {result['error']}")
            else:
                logger.error(f"[SIDECAR] Image gen returned unexpected response: {str(result)[:200]}")
            return ""
        except Exception as e:
            logger.error(f"[SIDECAR] Image generation exception: {e}")
            return ""

    # ── Z.ai Sidecar: Web Search ──

    async def web_search(self, query: str, num: int = 5) -> list:
        """Search web via Z.ai sidecar. Returns list of result dicts."""
        try:
            result = await self._sidecar_post("/search", {"query": query, "num": num}, timeout=30)
            if result and "results" in result:
                return result["results"]
            elif result and "error" in result:
                logger.error(f"[SIDECAR] Search error: {result['error']}")
            return []
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return []


# ═══════════════════════════════════════════════════════════════
#  Module-level singleton
# ═══════════════════════════════════════════════════════════════

_llm_handler = LLMHandler()


# ═══════════════════════════════════════════════════════════════
#  Cog-compatible wrapper functions
#  (cogs/chat.py and cogs/settings_cog.py import these by name)
# ═══════════════════════════════════════════════════════════════

async def generate_llm_response(system_prompt: str, messages: list) -> Optional[str]:
    """
    Wrapper for cogs. Takes system_prompt + messages list.
    Messages may contain a system message with embedded 'model' key
    (the cog embeds the model there for routing).
    Returns the response content string, or None on failure.
    """
    model = None
    auto_router = False
    allowed_models = None
    clean_messages = []
    actual_system_prompt = system_prompt
    system_prompt_consumed = False

    for msg in messages:
        if msg.get("role") == "system":
            # Extract routing metadata if embedded by the cog.
            if "model" in msg:
                model = msg["model"]
            if "auto_router" in msg:
                auto_router = bool(msg["auto_router"])
            if "allowed_models" in msg and msg["allowed_models"]:
                allowed_models = msg["allowed_models"]

            # The first system message is the prompt. Additional system messages
            # (for example timeline separators) should stay in the conversation
            # instead of replacing the personality/system prompt.
            content = msg.get("content", "")
            if content and not system_prompt_consumed:
                actual_system_prompt = content
                system_prompt_consumed = True
            elif content:
                clean_messages.append({"role": "system", "content": content})
        else:
            clean_messages.append(msg)

    if not model:
        model = "meta-llama/llama-4-maverick:free"

    result = await _llm_handler.chat(
        clean_messages,
        model=model,
        system_prompt=actual_system_prompt,
        auto_router=auto_router,
        allowed_models=allowed_models,
    )
    return result.get("content") if result else None


async def generate_image(prompt: str, model_name: str = "zai-sidecar") -> Optional[str]:
    """
    Generate an image. Returns a data:image URL or a regular URL.

    Supported model_name values:
      - "zai-sidecar"    → Z.ai sidecar (free, local)
      - "pollinations"   → Pollinations.ai (free, always works)
      - any other string → OpenRouter with modalities (paid, best quality)
    """
    logger.info(f"[IMG] generate_image called: model={model_name}, prompt=\"{prompt[:80]}\"")

    if model_name == "pollinations":
        # Pollinations.ai — always free, no API key needed
        try:
            encoded = hashlib.md5(prompt.encode()).hexdigest()[:8]
            url = (
                f"https://image.pollinations.ai/prompt/"
                f"{prompt}?seed={encoded}&width=1024&height=1024&nologo=true"
            )
            # Verify the URL is reachable
            async with aiohttp.ClientSession() as session:
                async with session.head(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        logger.info(f"[IMG] Pollinations URL: {url[:100]}")
                        return url
            logger.info(f"[IMG] Pollinations URL (no head check): {url[:100]}")
            return url  # Return anyway — the image will be generated on fetch
        except Exception as e:
            logger.error(f"[IMG] Pollinations failed: {e}")
            return None

    elif model_name == "zai-sidecar":
        # Z.ai sidecar
        b64 = await _llm_handler.generate_image_sidecar(prompt)
        if b64:
            return f"data:image/png;base64,{b64}"
        logger.warning("[IMG] Sidecar image gen returned nothing, falling back to Pollinations")
        # Fallback to Pollinations
        encoded = hashlib.md5(prompt.encode()).hexdigest()[:8]
        return f"https://image.pollinations.ai/prompt/{prompt}?seed={encoded}&width=1024&height=1024&nologo=true"

    else:
        # OpenRouter with modalities (model_name is an actual LLM model ID)
        logger.info(f"[IMG] Trying OpenRouter image gen with model={model_name}")
        b64_or_url = await _llm_handler.generate_image_openrouter(prompt, model=model_name)
        if b64_or_url:
            return b64_or_url
        logger.warning(f"[IMG] OpenRouter image gen ({model_name}) failed, falling back to Pollinations")
        encoded = hashlib.md5(prompt.encode()).hexdigest()[:8]
        return f"https://image.pollinations.ai/prompt/{prompt}?seed={encoded}&width=1024&height=1024&nologo=true"


async def analyze_image_vision(image_url: str, prompt: str = "Describe this image in detail.") -> str:
    """
    Analyze an image via Z.ai sidecar vision endpoint.
    Returns the description text, or empty string on failure.
    """
    return await _llm_handler.analyze_image(image_url=image_url, prompt=prompt)


async def web_search_zai(query: str, num: int = 5) -> list:
    """
    Search the web via Z.ai sidecar.
    Returns list of result dicts with 'url', 'name', 'snippet', etc.
    """
    return await _llm_handler.web_search(query, num=num)


async def parse_settings_command(prompt: str):
    """
    Parse a natural language settings command using the LLM.
    Returns a (key, value) tuple, or None if parsing fails.

    Examples:
      "switch model to gpt-4o"        → ("llm_model", "openai/gpt-4o")
      "turn off responses"            → ("response_enabled", False)
      "set cooldown to 15"            → ("cooldown_seconds", 15)
      "switch to markov mode"         → ("brain_mode", "markov")
    """
    system_prompt = (
        "You are a settings parser for a Discord bot. Given a user's natural language request, "
        "extract the setting key and value.\n"
        "Return ONLY a JSON object with exactly two fields: \"key\" and \"value\". "
        "No other text, no markdown formatting.\n\n"
        "Valid setting keys and their expected value types:\n"
        "- llm_model: string (model ID, e.g. \"openai/gpt-4o\", \"anthropic/claude-sonnet-4\")\n"
        "- brain_mode: string (\"markov\" or \"llm\")\n"
        "- response_enabled: boolean\n"
        "- learning_enabled: boolean\n"
        "- cooldown_seconds: integer\n"
        "- trigger_on_mention: boolean\n"
        "- trigger_on_reply: boolean\n"
        "- vision_enabled: boolean\n"
        "- web_search_enabled: boolean\n"
        "- image_model: string (\"zai-sidecar\", \"pollinations\", or a model ID)\n"
        "- response_chance: float (0.0 to 1.0)\n"
        "- personality_prefix: string\n"
        "- markov_order: integer\n"
        "- min_response_words: integer\n"
        "- max_response_words: integer\n"
        "- gif_chance: float (0.0 to 1.0)\n"
        "- reaction_chance: float (0.0 to 1.0)\n"
        "- random_reply_chance: float (0.0 to 1.0)\n"
        "- random_mention_chance: float (0.0 to 1.0)\n"
        "- indirect_reply_chance: float (0.0 to 1.0)\n"
        "- learn_from_bots: boolean\n\n"
        "Examples:\n"
        "- \"switch model to gpt-4o\" → {\"key\": \"llm_model\", \"value\": \"openai/gpt-4o\"}\n"
        "- \"turn off responses\" → {\"key\": \"response_enabled\", \"value\": false}\n"
        "- \"set cooldown to 15\" → {\"key\": \"cooldown_seconds\", \"value\": 15}\n"
        "- \"switch to markov mode\" → {\"key\": \"brain_mode\", \"value\": \"markov\"}\n"
    )

    result = await _llm_handler.chat(
        [{"role": "user", "content": prompt}],
        system_prompt=system_prompt,
        model=DEFAULT_MODEL,
        auto_router=False,
        temperature=0,
        max_tokens=150,
    )
    if not result or not result.get("content"):
        return None

    try:
        content = result["content"].strip()
        # Strip markdown code fences if the LLM added them
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        parsed = json.loads(content)
        key = parsed.get("key")
        value = parsed.get("value")
        if key and value is not None:
            return (key, value)
        return None
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.debug(f"Failed to parse settings command result: {e}")
        return None
