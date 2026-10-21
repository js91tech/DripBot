import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import llm
from config.settings_manager import SettingsManager
from model_catalog import (
    DEFAULT_MODEL,
    FALLBACK_MODEL,
    FREE_MODELS,
    LEGACY_MODEL_MAP,
    PAID_MODELS,
    canonical_model,
)


def _ok(text="hello"):
    return {"status": 200, "error": "", "text": text, "finish_reason": "stop",
            "model_used": FALLBACK_MODEL, "usage": {}}


def _fail(status, error=""):
    return {"status": status, "error": error, "text": "", "finish_reason": None,
            "model_used": None, "usage": {}}


class CatalogTests(unittest.TestCase):
    def test_slash_command_lists_fit_discord_limit(self):
        self.assertLessEqual(len(FREE_MODELS), 25)
        self.assertLessEqual(len(PAID_MODELS), 25)

    def test_legacy_targets_are_never_legacy(self):
        for old, new in LEGACY_MODEL_MAP.items():
            self.assertNotIn(new, LEGACY_MODEL_MAP, old)

    def test_retired_slugs_are_remapped(self):
        self.assertEqual(canonical_model("deepseek/deepseek-r1:free"), "nvidia/nemotron-3-super-120b-a12b:free")
        self.assertEqual(canonical_model("anthropic/claude-sonnet-4"), "anthropic/claude-sonnet-5.5")
        self.assertEqual(canonical_model("openai/gpt-4o"), "openai/gpt-4o")
        self.assertEqual(canonical_model(None), DEFAULT_MODEL)

    def test_route_chat_messages_remaps_saved_model(self):
        routed = llm.route_chat_messages(
            "sys", [{"role": "system", "content": "sys", "model": "meta-llama/llama-4-maverick:free"}]
        )
        self.assertEqual(routed["model"], canonical_model("meta-llama/llama-4-maverick:free"))


class FallbackTests(unittest.TestCase):
    def _chat(self, results, model="some/dead-model"):
        handler = llm.LLMHandler()
        handler.api_key = "key"
        post = AsyncMock(side_effect=results)
        with patch.object(handler, "_post_chat", post):
            out = asyncio.run(handler.chat([{"role": "user", "content": "hi"}], model=model, auto_router=False))
        return out, post

    def test_dead_model_falls_back_instead_of_failing(self):
        out, post = self._chat([_fail(404, "No endpoints found for some/dead-model"), _ok()])
        self.assertEqual(out["content"], "hello")
        self.assertEqual(post.call_args_list[1].args[0]["model"], FALLBACK_MODEL)

    def test_out_of_credits_falls_back(self):
        out, _ = self._chat([_fail(402, "insufficient credits"), _ok()], model="openai/gpt-5.5")
        self.assertEqual(out["content"], "hello")

    def test_working_model_is_not_replaced(self):
        out, post = self._chat([_ok()], model="openai/gpt-4o")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[0]["model"], "openai/gpt-4o")


class SettingsMigrationTests(unittest.TestCase):
    def test_stale_saved_models_are_upgraded(self):
        manager = SettingsManager(db=None)
        settings = {"llm_model": "deepseek/deepseek-r1:free", "model": "deepseek/deepseek-r1:free"}
        self.assertTrue(manager._normalize_model_settings(settings))
        self.assertEqual(settings["llm_model"], "nvidia/nemotron-3-super-120b-a12b:free")
        self.assertEqual(settings["model"], "nvidia/nemotron-3-super-120b-a12b:free")
        self.assertFalse(manager._normalize_model_settings(settings))


if __name__ == "__main__":
    unittest.main()
