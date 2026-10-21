import unittest
from unittest.mock import patch

from llm import (
    DEFAULT_MODEL,
    LLMHandler,
    fold_system_into_user,
    provider_safe_messages,
    resolve_model,
    route_chat_messages,
)


def _ok(text="Rent went up again.", model="openai/gpt-4o"):
    return {
        "status": 200,
        "error": "",
        "text": text,
        "finish_reason": "stop",
        "model_used": model,
        "usage": {},
    }


def _fail(status, error, finish_reason=None):
    return {
        "status": status,
        "error": error,
        "text": "",
        "finish_reason": finish_reason,
        "model_used": "",
        "usage": {},
    }


class ResolveModelTests(unittest.TestCase):
    def test_retired_ids_map_to_live_models(self):
        self.assertEqual(
            resolve_model("meta-llama/llama-4-maverick:free"),
            "google/gemma-4-31b-it:free",
        )
        self.assertEqual(resolve_model("anthropic/claude-sonnet-4"), "anthropic/claude-sonnet-4.6")
        self.assertEqual(resolve_model("anthropic/claude-haiku-3.5"), "anthropic/claude-haiku-4.5")
        self.assertEqual(resolve_model("x-ai/grok-3"), "x-ai/grok-4.20")
        self.assertEqual(resolve_model("openai/gpt-4o"), "openai/gpt-4o")
        self.assertEqual(resolve_model(""), DEFAULT_MODEL)
        self.assertEqual(resolve_model("openrouter/auto"), "openrouter/auto")

    def test_route_uses_the_live_id(self):
        routed = route_chat_messages(
            "You are Hannah.",
            [{
                "role": "system",
                "content": "You are Hannah.",
                "model": "mistralai/mistral-large-2411",
                "auto_router": False,
            }],
        )
        self.assertEqual(routed["model"], "mistralai/mistral-large-2512")
        self.assertFalse(routed["auto_router"])


class ProviderMessageTests(unittest.TestCase):
    def test_time_gap_is_not_a_second_system_message(self):
        messages = provider_safe_messages([
            {"role": "system", "content": "You are Hannah. Answer in one sentence."},
            {"role": "user", "content": "Alex: earlier"},
            {"role": "system", "content": "--- A long time passes ---"},
            {"role": "user", "content": "Alex: what happened to rent?"},
        ])
        self.assertEqual([msg["role"] for msg in messages], ["system", "user"])
        self.assertEqual(messages[0]["content"], "You are Hannah. Answer in one sentence.")
        self.assertIn("Alex: earlier", messages[1]["content"])
        self.assertIn("A long time passes", messages[1]["content"])
        self.assertIn("what happened to rent?", messages[1]["content"])

    def test_system_role_can_be_folded_into_the_user_turn(self):
        folded = fold_system_into_user([
            {"role": "system", "content": "You are Hannah."},
            {"role": "user", "content": "hey"},
        ])
        self.assertEqual([msg["role"] for msg in folded], ["user"])
        self.assertIn("You are Hannah.", folded[0]["content"])
        self.assertIn("hey", folded[0]["content"])


class ChatRequestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.handler = LLMHandler()
        self.handler.api_key = "test-key"
        self.seen = []

    def _patch(self, responses):
        queue = list(responses)

        async def fake_post(body, headers):
            self.seen.append(body)
            if queue:
                return queue.pop(0)
            return _ok()

        return patch.object(self.handler, "_post_chat", fake_post)

    async def test_first_request_does_not_disable_reasoning(self):
        with self._patch([_ok(model="anthropic/claude-sonnet-4.6")]):
            result = await self.handler.chat(
                [{"role": "user", "content": "hey"}],
                model="anthropic/claude-sonnet-4",
                system_prompt="You are Hannah.",
                auto_router=False,
                max_tokens=80,
            )
        self.assertEqual(result["content"], "Rent went up again.")
        self.assertEqual(self.seen[0]["model"], "anthropic/claude-sonnet-4.6")
        self.assertNotIn("reasoning", self.seen[0])
        self.assertEqual(self.seen[0]["temperature"], 0.8)
        self.assertEqual(self.seen[0]["messages"][0]["role"], "system")

    async def test_gpt4o_request_stays_plain(self):
        with self._patch([_ok()]):
            await self.handler.chat(
                [{"role": "user", "content": "hey"}],
                model="openai/gpt-4o",
                auto_router=False,
            )
        self.assertEqual(self.seen[0]["model"], "openai/gpt-4o")
        self.assertNotIn("reasoning", self.seen[0])

    async def test_temperature_rejection_retries_without_it(self):
        with self._patch([
            _fail(400, "Unsupported parameter: 'temperature' is not supported with this model."),
            _ok(model="openai/o4-mini"),
        ]):
            result = await self.handler.chat(
                [{"role": "user", "content": "hey"}],
                model="openai/o4-mini",
                auto_router=False,
                temperature=0.8,
            )
        self.assertEqual(result["content"], "Rent went up again.")
        self.assertIn("temperature", self.seen[0])
        self.assertNotIn("temperature", self.seen[1])
        self.assertEqual(len(self.seen), 2)

    async def test_empty_reply_then_mandatory_reasoning_still_returns_a_sentence(self):
        with self._patch([
            _fail(200, "", finish_reason="length"),
            _fail(400, "Reasoning is mandatory for this endpoint and cannot be disabled."),
            _ok(model="google/gemini-2.5-pro"),
        ]):
            result = await self.handler.chat(
                [{"role": "user", "content": "hey"}],
                model="google/gemini-2.5-pro",
                auto_router=False,
                max_tokens=80,
            )
        self.assertEqual(result["content"], "Rent went up again.")
        self.assertNotIn("reasoning", self.seen[0])
        self.assertEqual(self.seen[1]["reasoning"], {"enabled": False})
        self.assertGreaterEqual(self.seen[1]["max_tokens"], 800)
        self.assertEqual(self.seen[2]["reasoning"], {"effort": "low"})

    async def test_unknown_reasoning_field_is_dropped(self):
        with self._patch([
            _fail(200, "", finish_reason="length"),
            _fail(400, "Unknown parameter: reasoning"),
            _ok(),
        ]):
            result = await self.handler.chat(
                [{"role": "user", "content": "hey"}],
                model="openai/gpt-4o",
                auto_router=False,
                max_tokens=80,
            )
        self.assertEqual(result["content"], "Rent went up again.")
        self.assertEqual(self.seen[1]["reasoning"], {"enabled": False})
        self.assertNotIn("reasoning", self.seen[2])
        self.assertGreaterEqual(self.seen[2]["max_tokens"], 800)

    async def test_system_role_rejection_folds_the_prompt(self):
        with self._patch([
            _fail(400, "System message is not supported by this model"),
            _ok(model="google/gemma-4-31b-it:free"),
        ]):
            result = await self.handler.chat(
                [{"role": "user", "content": "hey"}],
                model="google/gemma-4-31b-it:free",
                system_prompt="You are Hannah.",
                auto_router=False,
            )
        self.assertEqual(result["content"], "Rent went up again.")
        self.assertEqual(self.seen[1]["messages"][0]["role"], "user")
        self.assertIn("You are Hannah.", self.seen[1]["messages"][0]["content"])

    async def test_unknown_model_is_not_retried_forever(self):
        with self._patch([
            _fail(404, "No endpoints found for missing/model"),
        ]):
            result = await self.handler.chat(
                [{"role": "user", "content": "hey"}],
                model="missing/model",
                auto_router=False,
            )
        self.assertIsNone(result)
        self.assertEqual(len(self.seen), 1)


if __name__ == "__main__":
    unittest.main()
