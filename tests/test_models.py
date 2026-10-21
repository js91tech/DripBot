import unittest

from config.models import (
    ALL_MODELS,
    DEFAULT_MODEL,
    FREE_MODELS,
    LEGACY_MODEL_ALIASES,
    PAID_MODELS,
    is_reasoning_model,
    normalize_model_id,
    supports_temperature,
)
from llm import LLMHandler


class ModelCatalogTests(unittest.TestCase):
    def test_default_model_is_a_listed_free_model(self):
        self.assertIn(DEFAULT_MODEL, FREE_MODELS)

    def test_no_listed_model_is_a_retired_alias_key(self):
        for model in ALL_MODELS:
            self.assertNotIn(model, LEGACY_MODEL_ALIASES)

    def test_alias_targets_are_listed_or_routers(self):
        for target in LEGACY_MODEL_ALIASES.values():
            self.assertTrue(
                target in ALL_MODELS or target.startswith("openrouter/"),
                target,
            )

    def test_retired_ids_normalize_to_live_ones(self):
        self.assertEqual(
            normalize_model_id("meta-llama/llama-4-maverick:free"), "openrouter/free"
        )
        self.assertEqual(
            normalize_model_id("anthropic/claude-sonnet-4"),
            "anthropic/claude-sonnet-4.5",
        )
        self.assertEqual(normalize_model_id("openai/gpt-4o"), "openai/gpt-4o")

    def test_model_traits(self):
        self.assertTrue(is_reasoning_model("openai/o4-mini"))
        self.assertTrue(is_reasoning_model("deepseek/deepseek-r1-0528"))
        self.assertFalse(is_reasoning_model("openai/gpt-4o"))
        self.assertFalse(supports_temperature("openai/o3-mini"))
        self.assertTrue(supports_temperature("openai/gpt-4o"))


def _ok(text="Hello there."):
    return {
        "status": 200,
        "error": "",
        "text": text,
        "finish_reason": "stop",
        "model_used": "fake",
        "usage": {},
    }


def _err(status, error):
    return {
        "status": status,
        "error": error,
        "text": "",
        "finish_reason": None,
        "model_used": "fake",
        "usage": {},
    }


class ChatRequestTests(unittest.IsolatedAsyncioTestCase):
    def _handler(self, responses):
        handler = LLMHandler()
        handler.api_key = "test-key"
        bodies = []

        async def fake_post(body, headers):
            bodies.append(dict(body))
            return responses.pop(0)

        handler._post_chat = fake_post
        return handler, bodies

    async def test_gpt4o_gets_temperature_and_no_reasoning_field(self):
        handler, bodies = self._handler([_ok()])
        result = await handler.chat(
            [{"role": "user", "content": "hi"}],
            model="openai/gpt-4o", auto_router=False, max_tokens=120,
        )
        self.assertEqual(result["content"], "Hello there.")
        self.assertEqual(bodies[0]["temperature"], 0.8)
        self.assertNotIn("reasoning", bodies[0])
        self.assertEqual(bodies[0]["max_tokens"], 120)

    async def test_o_series_gets_no_temperature_and_a_reasoning_budget(self):
        handler, bodies = self._handler([_ok()])
        await handler.chat(
            [{"role": "user", "content": "hi"}],
            model="openai/o3-mini", auto_router=False, max_tokens=120,
        )
        self.assertNotIn("temperature", bodies[0])
        self.assertGreaterEqual(bodies[0]["max_tokens"], 1024)

    async def test_rejected_temperature_is_dropped_and_retried(self):
        handler, bodies = self._handler([
            _err(400, "temperature is not supported for this model"),
            _ok(),
        ])
        result = await handler.chat(
            [{"role": "user", "content": "hi"}],
            model="google/gemini-2.5-flash", auto_router=False, max_tokens=120,
        )
        self.assertIsNotNone(result)
        self.assertIn("temperature", bodies[0])
        self.assertNotIn("temperature", bodies[1])

    async def test_rejected_reasoning_is_dropped_and_retried(self):
        handler, bodies = self._handler([
            _err(400, "Unsupported parameter: reasoning"),
            _ok(),
        ])
        result = await handler.chat(
            [{"role": "user", "content": "hi"}],
            model="google/gemini-2.5-flash", auto_router=False, max_tokens=120,
        )
        self.assertIsNotNone(result)
        self.assertIn("reasoning", bodies[0])
        self.assertNotIn("reasoning", bodies[1])

    async def test_retired_model_id_is_remapped_before_sending(self):
        handler, bodies = self._handler([_ok()])
        await handler.chat(
            [{"role": "user", "content": "hi"}],
            model="anthropic/claude-sonnet-4", auto_router=False,
        )
        self.assertEqual(bodies[0]["model"], "anthropic/claude-sonnet-4.5")

    async def test_dead_model_falls_back_to_the_free_router(self):
        handler, bodies = self._handler([
            _err(404, "model not found"),
            _ok("Fallback reply."),
        ])
        result = await handler.chat(
            [{"role": "user", "content": "hi"}],
            model="openai/gpt-4.1", auto_router=False,
        )
        self.assertEqual(result["content"], "Fallback reply.")
        self.assertEqual(bodies[1]["model"], "openrouter/free")

    async def test_auto_router_uses_the_plugin_not_a_top_level_field(self):
        handler, bodies = self._handler([_ok()])
        await handler.chat(
            [{"role": "user", "content": "hi"}],
            auto_router=True, allowed_models=["anthropic/claude-sonnet-4"],
        )
        self.assertNotIn("allowed_models", bodies[0])
        self.assertEqual(
            bodies[0]["plugins"],
            [{"id": "auto-router", "allowed_models": ["anthropic/claude-sonnet-4.5"]}],
        )


if __name__ == "__main__":
    unittest.main()
