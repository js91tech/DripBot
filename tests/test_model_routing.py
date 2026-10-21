import copy
import unittest

import llm
from config.models import (
    DEFAULT_MODEL,
    FREE_MODELS,
    IMAGE_MODELS,
    PAID_MODELS,
    RETIRED_MODELS,
    resolve_model,
)
from config.settings_manager import SettingsManager
from llm import LLMHandler, REASONING_MIN_TOKENS, image_from_completion, route_chat_messages


def _ok(text):
    return {"status": 200, "error": "", "text": text, "finish_reason": "stop", "usage": {}}


def _fail(status, error=""):
    return {"status": status, "error": error, "text": "", "finish_reason": None, "usage": {}}


class _ScriptedHandler(LLMHandler):
    """Replays canned OpenRouter results and records every request body."""

    def __init__(self, results):
        super().__init__()
        self.api_key = "test-key"
        self.results = list(results)
        self.bodies = []

    async def _post_chat(self, body, headers):
        self.bodies.append(copy.deepcopy(body))
        return self.results.pop(0)


class ChatRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        llm._thinking_models.clear()

    async def _chat(self, handler, model="google/gemma-4-31b-it:free", max_tokens=80):
        return await handler.chat(
            [{"role": "user", "content": "hey"}],
            model=model,
            system_prompt="You are Hannah.",
            auto_router=False,
            max_tokens=max_tokens,
        )

    async def test_working_model_is_one_request(self):
        handler = _ScriptedHandler([_ok("hey yourself")])
        result = await self._chat(handler, model="openai/gpt-4o")
        self.assertEqual(result["content"], "hey yourself")
        self.assertEqual(len(handler.bodies), 1)

    async def test_retired_model_id_is_swapped_before_sending(self):
        handler = _ScriptedHandler([_ok("hi")])
        await self._chat(handler, model="meta-llama/llama-4-maverick:free")
        self.assertEqual(handler.bodies[0]["model"], DEFAULT_MODEL)

    async def test_unknown_model_falls_back_to_the_free_router(self):
        handler = _ScriptedHandler([
            _fail(404, '{"error":{"message":"No endpoints found for some/old-model:free."}}'),
            _ok("still here"),
        ])
        result = await self._chat(handler, model="some/old-model:free")
        self.assertEqual(result["content"], "still here")
        self.assertEqual(handler.bodies[1]["model"], DEFAULT_MODEL)

    async def test_invalid_model_id_400_falls_back(self):
        handler = _ScriptedHandler([
            _fail(400, '{"error":{"message":"x-ai/grok-9 is not a valid model ID"}}'),
            _ok("ok"),
        ])
        result = await self._chat(handler, model="x-ai/grok-9")
        self.assertEqual(result["content"], "ok")
        self.assertEqual(handler.bodies[1]["model"], DEFAULT_MODEL)

    async def test_privacy_block_does_not_switch_models(self):
        handler = _ScriptedHandler([
            _fail(404, "No endpoints found matching your data policy (Free model publication)"),
        ])
        result = await self._chat(handler)
        self.assertIsNone(result)
        self.assertEqual(len(handler.bodies), 1)

    async def test_mandatory_reasoning_gets_a_real_budget_and_is_remembered(self):
        handler = _ScriptedHandler([
            _fail(400, "Reasoning is mandatory for this endpoint and cannot be disabled."),
            _ok("answer"),
        ])
        result = await self._chat(handler, model="openai/o4-mini")
        self.assertEqual(result["content"], "answer")
        retry = handler.bodies[1]
        self.assertNotIn("reasoning", retry)
        self.assertGreaterEqual(retry["max_tokens"], REASONING_MIN_TOKENS)

        handler = _ScriptedHandler([_ok("second")])
        await self._chat(handler, model="openai/o4-mini")
        self.assertGreaterEqual(handler.bodies[0]["max_tokens"], REASONING_MIN_TOKENS)

    async def test_reply_lost_to_thinking_is_retried_with_room(self):
        handler = _ScriptedHandler([_ok(""), _ok("finally")])
        result = await self._chat(handler, max_tokens=60)
        self.assertEqual(result["content"], "finally")
        retry = handler.bodies[1]
        self.assertGreaterEqual(retry["max_tokens"], REASONING_MIN_TOKENS)
        self.assertEqual(retry["reasoning"], {"effort": "low"})

    async def test_rejected_effort_after_budget_retry_drops_reasoning(self):
        handler = _ScriptedHandler([
            _ok(""),
            _fail(400, "reasoning effort 'low' is not supported"),
            _ok("there it is"),
        ])
        result = await self._chat(handler)
        self.assertEqual(result["content"], "there it is")
        self.assertNotIn("reasoning", handler.bodies[2])

    async def test_rate_limit_is_retried_once(self):
        llm_sleep = llm.asyncio.sleep

        async def no_sleep(_):
            return None

        llm.asyncio.sleep = no_sleep
        try:
            handler = _ScriptedHandler([_fail(429, "rate limited"), _fail(429, "rate limited")])
            result = await self._chat(handler)
        finally:
            llm.asyncio.sleep = llm_sleep
        self.assertIsNone(result)
        self.assertEqual(len(handler.bodies), 2)

    async def test_retired_model_and_mandatory_reasoning_both_recover(self):
        handler = _ScriptedHandler([
            _fail(404, "No endpoints found for x/y."),
            _fail(400, "Reasoning is mandatory for this endpoint"),
            _ok("done"),
        ])
        result = await self._chat(handler, model="x/y")
        self.assertEqual(result["content"], "done")
        self.assertEqual(handler.bodies[2]["model"], DEFAULT_MODEL)
        self.assertNotIn("reasoning", handler.bodies[2])


class ModelListTests(unittest.TestCase):
    def test_route_resolves_retired_models(self):
        routed = route_chat_messages(
            "prompt",
            [{"role": "system", "content": "p", "model": "anthropic/claude-sonnet-4"}],
        )
        self.assertEqual(routed["model"], "anthropic/claude-sonnet-5.5")

    def test_route_without_model_uses_default(self):
        self.assertEqual(route_chat_messages("p", [])["model"], DEFAULT_MODEL)

    def test_pickers_fit_discord_choice_limit(self):
        for entries in (FREE_MODELS, PAID_MODELS, IMAGE_MODELS):
            self.assertLessEqual(len(entries), 25)

    def test_retired_ids_are_not_offered(self):
        offered = {model_id for _, model_id in FREE_MODELS + PAID_MODELS}
        self.assertFalse(offered & set(RETIRED_MODELS))

    def test_resolve_leaves_current_ids_alone(self):
        self.assertEqual(resolve_model("openai/gpt-4o"), "openai/gpt-4o")


class _DB:
    def __init__(self, saved):
        self.saved = saved
        self.writes = []

    async def get_settings(self, guild_id):
        return dict(self.saved)

    async def save_settings(self, guild_id, settings):
        self.writes.append(dict(settings))


class SavedSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_retired_models_are_replaced(self):
        db = _DB({
            "llm_model": "deepseek/deepseek-r1:free",
            "model": "deepseek/deepseek-r1:free",
            "image_model": "openai/gpt-4o",
        })
        settings = await SettingsManager(db).get_settings(1)
        self.assertEqual(settings["llm_model"], DEFAULT_MODEL)
        self.assertEqual(settings["model"], DEFAULT_MODEL)
        self.assertEqual(settings["image_model"], "google/gemini-2.5-flash-image")
        self.assertTrue(db.writes)


class ImageParsingTests(unittest.TestCase):
    def test_images_field(self):
        data = {"choices": [{"message": {
            "content": "Here you go",
            "images": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}],
        }}]}
        self.assertEqual(image_from_completion(data), "data:image/png;base64,AAAA")

    def test_inline_data_url(self):
        data = {"choices": [{"message": {"content": "![img](data:image/png;base64,QUJD)"}}]}
        self.assertEqual(image_from_completion(data), "data:image/png;base64,QUJD")

    def test_null_content_has_no_image(self):
        self.assertEqual(image_from_completion({"choices": [{"message": {"content": None}}]}), "")


if __name__ == "__main__":
    unittest.main()
