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

import asyncio
import aiohttp
import base64
import hashlib
import json
import logging
import os
import re
from typing import Optional, List
from urllib.parse import quote

logger = logging.getLogger("dripsletongue.llm")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
SIDECAR_URL = os.environ.get("ZAI_SIDECAR_URL", "http://localhost:3456")

# Default model (used when auto-router is off)
DEFAULT_MODEL = "meta-llama/llama-4-maverick:free"

# Discord replies are one or two sentences. Reasoning models will spend a
# small max_tokens budget on hidden thinking and return an empty `content`,
# which shows up in chat as typing with no message. Ask for no reasoning
# unless the provider rejects that.
_THINK_BLOCK_RE = re.compile(
    r"<(?:think|thinking|reasoning)\b[^>]*>.*?</(?:think|thinking|reasoning)>",
    re.IGNORECASE | re.DOTALL,
)
_UNCLOSED_THINK_RE = re.compile(
    r"<(?:think|thinking|reasoning)\b[^>]*>.*\Z",
    re.IGNORECASE | re.DOTALL,
)
_SKIP_CONTENT_TYPES = {
    "thinking",
    "reasoning",
    "reasoning_text",
    "redacted_thinking",
}
# Planning lines are not a chat reply. A finished sentence after them is.
_COT_LINE_RE = re.compile(
    r"^(?:"
    r"the user|i should|i need to|let me|first,|okay, so|analysis|"
    r"reasoning|step \d|to answer|looking at|the question"
    r")\b",
    re.IGNORECASE,
)


def strip_model_thinking(text: str) -> str:
    """Remove chain-of-thought wrappers so only the chat sentence remains."""
    if not text:
        return ""
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _UNCLOSED_THINK_RE.sub("", cleaned)
    return cleaned.strip()


def content_to_visible_text(content) -> str:
    """
    Normalize provider content to the user-visible reply.

    Accepts a string or a list of content blocks. Thinking blocks are dropped.
    An unfinished <think> with no answer becomes an empty string so the caller
    can retry instead of posting the thought.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        raw = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "text").lower()
            if block_type in _SKIP_CONTENT_TYPES:
                continue
            text = block.get("text")
            if text is None and isinstance(block.get("content"), str):
                text = block["content"]
            if isinstance(text, str) and text.strip():
                parts.append(text)
        raw = "\n".join(parts)
    else:
        raw = str(content)
    return strip_model_thinking(raw).strip()


def reply_from_reasoning(text: str) -> str:
    """
    Pull a chat sentence out of a reasoning trace.

    Some OpenRouter models leave `content` empty and put the actual reply in
    `reasoning` / `reasoning_content`. Planning lines are skipped. The last
    leftover paragraph is the sentence the bot should send.
    """
    cleaned = strip_model_thinking(text or "")
    if not cleaned:
        return ""
    paragraphs = [part.strip() for part in re.split(r"\n+", cleaned) if part.strip()]
    for paragraph in reversed(paragraphs):
        if _COT_LINE_RE.match(paragraph):
            continue
        if len(paragraph) > 600:
            continue
        return paragraph
    return ""


def _message_reasoning_text(message: dict) -> str:
    chunks = []
    for key in ("reasoning", "reasoning_content"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            chunks.append(value.strip())
    details = message.get("reasoning_details")
    if isinstance(details, list):
        for item in details:
            if isinstance(item, str) and item.strip():
                chunks.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            for key in ("text", "summary", "content"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    chunks.append(value.strip())
                    break
    return "\n".join(chunks)


def visible_reply_from_completion(data) -> str:
    """Pull the visible assistant sentence out of a chat-completions payload."""
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        return ""
    visible = content_to_visible_text(message.get("content"))
    if visible:
        return visible
    return reply_from_reasoning(_message_reasoning_text(message))


def flatten_text_content(content):
    """
    Turn text-only content blocks into a plain string.

    Returns None when a block is multimodal so the original payload is kept.
    Free chat models often 400 on text wrapped as a content array, and that
    failure used to stop the bot after it had already started typing.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            return None
        block_type = str(block.get("type") or "text").lower()
        if block_type not in {"text", "input_text"}:
            return None
        text = block.get("text")
        if text is None:
            text = block.get("content")
        if not isinstance(text, str):
            return None
        parts.append(text)
    return "\n".join(parts)


def flatten_message(msg):
    if not isinstance(msg, dict):
        return msg
    flattened = flatten_text_content(msg.get("content"))
    if flattened is None:
        return msg
    return {**msg, "content": flattened}


def route_chat_messages(system_prompt, messages, auto_router=False, allowed_models=None):
    """
    Split the cog's embedded routing system message from the transcript.

    A later system note such as "--- A long time passes ---" must not replace
    the personality prompt, or the model ignores the instruction to actually
    answer and the visible reply comes back empty.
    """
    model = None
    clean_messages = []
    actual_system_prompt = system_prompt
    use_auto = bool(auto_router)
    allowed = list(allowed_models) if allowed_models else None

    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        is_routing = msg.get("role") == "system" and (
            "model" in msg or "auto_router" in msg or "allowed_models" in msg
        )
        if is_routing:
            if msg.get("model"):
                model = msg["model"]
            if "auto_router" in msg:
                use_auto = bool(msg["auto_router"])
            if msg.get("allowed_models"):
                allowed = list(msg["allowed_models"])
            content = msg.get("content") or ""
            if isinstance(content, str) and content.strip():
                actual_system_prompt = content
            continue
        clean_messages.append(flatten_message(msg))

    if not model:
        model = DEFAULT_MODEL
    return {
        "model": model,
        "system_prompt": actual_system_prompt,
        "messages": clean_messages,
        "auto_router": use_auto,
        "allowed_models": allowed,
    }


def _reasoning_request_rejected(error_text: str) -> bool:
    lowered = (error_text or "").lower()
    return "reasoning" in lowered


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

        # Build the messages list. Text-only blocks become strings so
        # providers that reject content arrays still return a sentence.
        final_messages = []
        if system_prompt:
            final_messages.append({"role": "system", "content": system_prompt})
        final_messages.extend(flatten_message(msg) for msg in messages)

        # Determine model
        if auto_router:
            effective_model = "openrouter/auto"
        elif model:
            effective_model = model
        else:
            effective_model = self.default_model

        # Build request body. effort=none keeps the token budget on the
        # visible sentence instead of an empty content field.
        body = {
            "model": effective_model,
            "messages": final_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "reasoning": {"effort": "none"},
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

        result = await self._post_chat(body, headers)
        if result["status"] == 400 and _reasoning_request_rejected(result["error"]):
            logger.warning("Provider rejected reasoning=none; retrying without it")
            body = dict(body)
            body.pop("reasoning", None)
            body["max_tokens"] = max(int(body.get("max_tokens") or 0), 800)
            result = await self._post_chat(body, headers)
        elif result["status"] in {429, 500, 502, 503, 504}:
            logger.warning(f"OpenRouter {result['status']}; retrying once")
            await asyncio.sleep(1.0)
            result = await self._post_chat(body, headers)
        elif result["status"] == 200 and not result["text"]:
            # Tokens were spent before a sentence existed (usually reasoning
            # or a cut-off <think> block). Give the answer a larger budget.
            logger.warning(
                "OpenRouter returned no visible reply (finish_reason=%s); retrying",
                result.get("finish_reason"),
            )
            body = dict(body)
            body["max_tokens"] = max(int(body.get("max_tokens") or 0) * 3, 800)
            body["reasoning"] = {"effort": "minimal"}
            result = await self._post_chat(body, headers)

        if result["status"] != 200 or not result["text"]:
            if result["status"] == 200:
                logger.warning("OpenRouter reply stayed empty after retry")
            return None

        return {
            "content": result["text"],
            "model_used": result.get("model_used") or effective_model,
            "usage": result.get("usage") or {},
        }

    async def _post_chat(self, body: dict, headers: dict) -> dict:
        """POST one completion. Never raises; status 0 means a transport error."""
        empty = {
            "status": 0,
            "error": "",
            "text": "",
            "finish_reason": None,
            "model_used": body.get("model"),
            "usage": {},
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{OPENROUTER_BASE}/chat/completions",
                    json=body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=90),
                ) as resp:
                    raw = await resp.text()
                    status = resp.status
        except aiohttp.ClientError as e:
            logger.error(f"OpenRouter request failed: {e}")
            empty["error"] = str(e)
            return empty
        except Exception as e:
            logger.error(f"Chat error: {e}")
            empty["error"] = str(e)
            return empty

        if status != 200:
            empty["status"] = status
            empty["error"] = raw
            logger.error(f"OpenRouter {status}: {raw[:300]}")
            return empty

        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            empty["status"] = status
            empty["error"] = raw[:300]
            return empty

        finish_reason = None
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            finish_reason = choices[0].get("finish_reason")
        return {
            "status": status,
            "error": "",
            "text": visible_reply_from_completion(data),
            "finish_reason": finish_reason,
            "model_used": data.get("model", body.get("model")),
            "usage": data.get("usage") or {},
        }

    # ── OpenRouter Image Generation (via modalities) ──

    async def generate_image_openrouter(self, prompt: str, model: str = "openai/gpt-4o",
                                        size: str = "1024x1024",
                                        reference_data_url: str = None) -> str:
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

        text = (
            "Create an image of this subject, exactly as described. "
            "Do not substitute a different person or character:\n"
            f"{prompt}"
        )
        if reference_data_url:
            user_content = [
                {"type": "text", "text": text + "\nMatch the attached reference photo's face and likeness."},
                {"type": "image_url", "image_url": {"url": reference_data_url}},
            ]
        else:
            user_content = text

        body = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": user_content,
            }],
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

async def generate_llm_response(
    system_prompt: str,
    messages: list,
    auto_router: bool = False,
    allowed_models: list = None,
    max_tokens: int = 120,
    temperature: float = 0.8,
) -> Optional[str]:
    """
    Wrapper for cogs. Takes system_prompt + messages list.
    Messages may contain a system message with embedded 'model' /
    'auto_router' / 'allowed_models' keys (the cog embeds routing there).
    Defaults to the configured model (not openrouter/auto) and a small
    max_tokens budget so short Discord replies stay cheap.
    Returns the response content string, or None on failure.
    """
    routed = route_chat_messages(
        system_prompt,
        messages,
        auto_router=auto_router,
        allowed_models=allowed_models,
    )

    result = await _llm_handler.chat(
        routed["messages"],
        model=routed["model"],
        system_prompt=routed["system_prompt"],
        auto_router=routed["auto_router"],
        allowed_models=routed["allowed_models"],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    text = content_to_visible_text(result.get("content")) if result else ""
    return text or None


def build_pollinations_url(prompt: str) -> str:
    """URL-encode the full subject so Discord does not fetch only the first word."""
    seed = hashlib.md5(prompt.encode()).hexdigest()[:8]
    encoded_prompt = quote(prompt.strip(), safe="")
    return (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?seed={seed}&width=1024&height=1024&nologo=true"
    )


def reference_image_data_url(image_path):
    """Encode a local reference photo as a data URL for likeness-matched image gen."""
    if not image_path or not os.path.exists(image_path):
        return None
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    ext = os.path.splitext(image_path)[1].lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    return f"data:{mime};base64,{encoded}"


async def generate_image(prompt: str, model_name: str = "zai-sidecar",
                         reference_path: str = None) -> Optional[str]:
    """
    Generate an image. Returns a data:image URL or a regular URL.

    Supported model_name values:
      - "zai-sidecar"    → Z.ai sidecar (free, local)
      - "pollinations"   → Pollinations.ai (free, always works)
      - any other string → OpenRouter with modalities (paid, best quality)

    When reference_path is set, prefer OpenRouter so the likeness can be matched.
    """
    logger.info(f"[IMG] generate_image called: model={model_name}, prompt=\"{prompt[:80]}\"")
    reference_url = reference_image_data_url(reference_path)

    if reference_url and _llm_handler.api_key:
        ref_model = model_name if model_name not in {"zai-sidecar", "pollinations", ""} else "google/gemini-2.5-flash-image"
        logger.info(f"[IMG] Trying OpenRouter likeness gen with model={ref_model}")
        b64_or_url = await _llm_handler.generate_image_openrouter(
            prompt, model=ref_model, reference_data_url=reference_url
        )
        if b64_or_url:
            return b64_or_url
        logger.warning("[IMG] Reference-photo OpenRouter gen failed; falling through")

    if model_name == "pollinations":
        # Pollinations.ai — always free, no API key needed
        try:
            url = build_pollinations_url(prompt)
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
        return build_pollinations_url(prompt)

    else:
        # OpenRouter with modalities (model_name is an actual LLM model ID)
        logger.info(f"[IMG] Trying OpenRouter image gen with model={model_name}")
        b64_or_url = await _llm_handler.generate_image_openrouter(
            prompt, model=model_name, reference_data_url=reference_url
        )
        if b64_or_url:
            return b64_or_url
        logger.warning(f"[IMG] OpenRouter image gen ({model_name}) failed, falling back to Pollinations")
        return build_pollinations_url(prompt)


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
      "switch personality to hannah"  → ("personality", "hannah")
    """
    system_prompt = (
        "You are a settings parser for a Discord bot. Given a user's natural language request, "
        "extract the setting key and value.\n"
        "Return ONLY a JSON object with exactly two fields: \"key\" and \"value\". "
        "No other text, no markdown formatting.\n\n"
        "Valid setting keys and their expected value types:\n"
        "- llm_model: string (model ID, e.g. \"openai/gpt-4o\", \"anthropic/claude-sonnet-4\")\n"
        "- response_enabled: boolean\n"
        "- cooldown_seconds: integer\n"
        "- trigger_on_mention: boolean\n"
        "- trigger_on_reply: boolean\n"
        "- vision_enabled: boolean\n"
        "- web_search_enabled: boolean\n"
        "- image_model: string (\"zai-sidecar\", \"pollinations\", or a model ID)\n"
        "- personality: string (preset ID/name, e.g. \"ultron\", \"deadpool\", \"tony_stark\", \"charlie_kirk\", \"donald_trump\", \"nicki_minaj\", \"dr_umar\", \"panda\")\n"
        "- response_chance: float (0.0 to 1.0)\n"
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
        "- \"switch personality to hannah\" → {\"key\": \"personality\", \"value\": \"hannah\"}\n"
        "- \"switch personality to deadpool\" → {\"key\": \"personality\", \"value\": \"deadpool\"}\n"
        "- \"switch personality to charlie kirk\" → {\"key\": \"personality\", \"value\": \"charlie_kirk\"}\n"
        "- \"switch personality to trump\" → {\"key\": \"personality\", \"value\": \"donald_trump\"}\n"
        "- \"switch personality to nicki minaj\" → {\"key\": \"personality\", \"value\": \"nicki_minaj\"}\n"
        "- \"switch personality to nikki\" → {\"key\": \"personality\", \"value\": \"nicki_minaj\"}\n"
        "- \"switch personality to dr umar\" → {\"key\": \"personality\", \"value\": \"dr_umar\"}\n"
        "- \"switch personality to panda\" → {\"key\": \"personality\", \"value\": \"panda\"}\n"
    )

    result = await _llm_handler.chat(
        [{"role": "user", "content": prompt}],
        system_prompt=system_prompt,
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
