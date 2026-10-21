"""Model-compat regression tests.

Covers the Oct-2026 outage where every :free ID and most paid IDs in the
dashboard had been retired by OpenRouter, while llm.py additionally sent a
payload (reasoning=none + temperature + tiny max_tokens) that only gpt-4o
tolerated:

- build_chat_body() never sends `reasoning`, drops `temperature` and uses
  max_completion_tokens for fixed-sampling models, and floors thinker budgets.
- chat() retries once on unsupported-parameter 400s and falls back to
  DEFAULT_MODEL on retired (404) IDs instead of staying silent.
- The model lists in llm.py / api.py / dashboard.html / settings cog stay in
  sync so a stale ID cannot hide in one surface again.
"""

import os
import re
import unittest
from unittest.mock import AsyncMock, patch

from llm import (
    DEFAULT_MODEL,
    FREE_MODELS,
    PAID_MODELS,
    LLMHandler,
    _minimal_chat_body,
    _model_not_found,
    _unsupported_param_rejected,
    build_chat_body,
)


def _ok(text, model):
    return {
        "status": 200,
        "error": "",
        "text": text,
        "finish_reason": "stop",
        "model_used": model,
        "usage": {},
    }


class BodyBuilderTests(unittest.TestCase):
    def test_plain_model_keeps_simple_body_without_reasoning(self):
        body = build_chat_body(
            "openai/gpt-4o",
            [{"role": "user", "content": "hi"}],
            temperature=0.8,
            max_tokens=400,
        )
        self.assertNotIn("reasoning", body)
        self.assertEqual(body["temperature"], 0.8)
        self.assertEqual(body["max_tokens"], 400)

    def test_fixed_sampling_model_drops_temperature(self):
        for model in ("openai/o3-mini", "openai/o4-mini", "openai/gpt-5-mini"):
            body = build_chat_body(
                model, [{"role": "user", "content": "hi"}], temperature=0.8, max_tokens=400
            )
            self.assertNotIn("temperature", body, model)
            self.assertNotIn("reasoning", body, model)
            self.assertIn("max_completion_tokens", body, model)
            self.assertGreaterEqual(body["max_completion_tokens"], 1500)

    def test_thinker_gets_budget_floor(self):
        body = build_chat_body(
            "deepseek/deepseek-r1",
            [{"role": "user", "content": "hi"}],
            temperature=0.8,
            max_tokens=120,
        )
        self.assertGreaterEqual(body["max_tokens"], 2000)

    def test_minimal_body_uses_completion_tokens_for_fixed_sampling(self):
        body = _minimal_chat_body("openai/o3-mini", [], 120)
        self.assertIn("max_completion_tokens", body)
        self.assertNotIn("temperature", body)

    def test_error_classifiers(self):
        self.assertTrue(_unsupported_param_rejected(
            "Unsupported parameter: 'temperature' is not supported with this model."))
        self.assertTrue(_unsupported_param_rejected(
            "Unsupported parameter: 'max_tokens' is not supported. Use 'max_completion_tokens' instead."))
        self.assertTrue(_unsupported_param_rejected("Extra inputs are not permitted: reasoning"))
        self.assertFalse(_unsupported_param_rejected("Rate limit exceeded"))
        self.assertTrue(_model_not_found("No endpoints found for model: foo/bar:free"))
        self.assertFalse(_model_not_found("Rate limit exceeded"))


class ChatRetryTests(unittest.IsolatedAsyncioTestCase):
    async def _handler(self):
        handler = LLMHandler()
        handler.api_key = "test-key"
        return handler

    async def test_unsupported_param_400_retries_minimal_then_succeeds(self):
        handler = await self._handler()
        seen = []

        async def fake_post(body, headers):
            seen.append(dict(body))
            if len(seen) == 1:
                return {
                    "status": 400,
                    "error": "Unsupported parameter: 'temperature' is not supported",
                    "text": "",
                    "finish_reason": None,
                    "model_used": body.get("model"),
                    "usage": {},
                }
            return _ok("Rent went up again.", body.get("model"))

        with patch.object(handler, "_post_chat", side_effect=fake_post):
            result = await handler.chat(
                [{"role": "user", "content": "hi"}],
                model="openai/o4-mini",
                auto_router=False,
                temperature=0.8,
                max_tokens=120,
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["content"], "Rent went up again.")
        # First attempt must not carry temperature for fixed-sampling models.
        self.assertNotIn("temperature", seen[0])

    async def test_retired_model_falls_back_to_default(self):
        handler = await self._handler()
        seen_models = []

        async def fake_post(body, headers):
            seen_models.append(body.get("model"))
            if body.get("model") != DEFAULT_MODEL:
                return {
                    "status": 404,
                    "error": "No endpoints found for model: anthropic/claude-sonnet-4",
                    "text": "",
                    "finish_reason": None,
                    "model_used": body.get("model"),
                    "usage": {},
                }
            return _ok("Rent went up again.", body.get("model"))

        with patch.object(handler, "_post_chat", side_effect=fake_post):
            result = await handler.chat(
                [{"role": "user", "content": "hi"}],
                model="anthropic/claude-sonnet-4",
                auto_router=False,
            )
        self.assertIsNotNone(result)
        self.assertIn(DEFAULT_MODEL, seen_models)
        self.assertEqual(result["model_used"], DEFAULT_MODEL)


class ModelListParityTests(unittest.TestCase):
    def test_default_model_is_listed(self):
        self.assertIn(DEFAULT_MODEL, FREE_MODELS + PAID_MODELS)

    def test_no_duplicates(self):
        combined = FREE_MODELS + PAID_MODELS
        self.assertEqual(len(combined), len(set(combined)))

    def test_api_imports_canonical_lists(self):
        import api as dashboard_api

        self.assertEqual(dashboard_api.FREE_MODELS, FREE_MODELS)
        self.assertEqual(dashboard_api.PAID_MODELS, PAID_MODELS)

    def test_dashboard_html_matches(self):
        with open(
            os.path.join(os.path.dirname(__file__), "..", "dashboard.html"),
            encoding="utf-8",
        ) as f:
            html = f.read()
        for model_id in FREE_MODELS + PAID_MODELS:
            self.assertIn(f"'{model_id}'", html, f"{model_id} missing from dashboard.html")

    def test_settings_cog_choices_cover_lists(self):
        import cogs.settings_cog as settings_cog

        free_values = {c.value for c in settings_cog._model_choices(FREE_MODELS)}
        paid_values = {c.value for c in settings_cog._model_choices(PAID_MODELS)}
        self.assertEqual(free_values, set(FREE_MODELS))
        self.assertEqual(paid_values, set(PAID_MODELS))

    def test_default_settings_use_canonical_default(self):
        from config.default_settings import DEFAULT_SETTINGS

        self.assertEqual(DEFAULT_SETTINGS["llm_model"], DEFAULT_MODEL)
        self.assertEqual(DEFAULT_SETTINGS["model"], DEFAULT_MODEL)

    def test_no_known_retired_ids_remain(self):
        retired = [
            "meta-llama/llama-4-maverick:free",
            "google/gemma-3-27b-it:free",
            "qwen/qwen3-235b-a22b:free",
            "microsoft/phi-4-reasoning-plus:free",
            "deepseek/deepseek-r1:free",
            "anthropic/claude-sonnet-4",
            "anthropic/claude-opus-4",
            "anthropic/claude-haiku-3.5",
            "x-ai/grok-3",
            "x-ai/grok-3-mini",
            "mistralai/mistral-large-2411",
            "perplexity/llama-3.1-sonar-huge-128k-online",
            "nvidia/llama-3.1-nemotron-ultra-253b",
            "meta-llama/llama-3.1-405b-instruct",
        ]
        combined = FREE_MODELS + PAID_MODELS
        for dead in retired:
            self.assertNotIn(dead, combined, f"retired ID still listed: {dead}")

    def test_no_retired_ids_in_dashboard_or_cog_source(self):
        roots = [
            os.path.join(os.path.dirname(__file__), "..", "dashboard.html"),
            os.path.join(os.path.dirname(__file__), "..", "cogs", "settings_cog.py"),
        ]
        retired_re = re.compile(
            r"llama-4-maverick:free|gemma-3-27b-it:free|qwen3-235b-a22b:free|"
            r"phi-4-reasoning-plus:free|deepseek-r1:free|"
            r"claude-sonnet-4\"|claude-opus-4\"|claude-haiku-3\.5|"
            r"x-ai/grok-3\"|mistral-large-2411|sonar-huge|nemotron-ultra-253b|"
            r"405b-instruct\""
        )
        for path in roots:
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self.assertIsNone(
                retired_re.search(content), f"retired ID found in {path}"
            )


if __name__ == "__main__":
    unittest.main()
