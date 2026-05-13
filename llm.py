"""
llm.py — Complete replacement for your existing llm.py

Features:
  - OpenRouter Auto Router (openrouter/auto) with optional allowed_models
  - Manual model fallback if auto-router is disabled
  - Z.ai sidecar integration (vision, image gen, web search)
  - Graceful degradation when sidecar is down

Drop this file in your project root, replacing the old llm.py.
"""

import aiohttp
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
        auto_router: bool = True,
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

    # ── Z.ai Sidecar: Image Analysis ──

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
            return ""
        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            return ""

    async def generate_image(self, prompt: str, size: str = "1024x1024") -> str:
        """Generate an image via Z.ai sidecar. Returns base64 PNG or empty string."""
        try:
            result = await self._sidecar_post("/generate", {"prompt": prompt, "size": size}, timeout=120)
            if result and "image_b64" in result:
                return result["image_b64"]
            return ""
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            return ""

    async def web_search(self, query: str, num: int = 5) -> list:
        """Search web via Z.ai sidecar. Returns list of result dicts."""
        try:
            result = await self._sidecar_post("/search", {"query": query, "num": num}, timeout=30)
            if result and "results" in result:
                return result["results"]
            return []
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return []
