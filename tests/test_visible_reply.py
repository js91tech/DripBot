import unittest

import discord

from cogs.chat import FALLBACK_QUOTES, Chat
from llm import (
    content_to_visible_text,
    flatten_text_content,
    route_chat_messages,
    visible_reply_from_completion,
)
from utils import sanitize_message, strip_leading_address


class VisibleReplyTests(unittest.TestCase):
    def test_string_content_is_kept(self):
        self.assertEqual(content_to_visible_text("Rent went up again."), "Rent went up again.")

    def test_null_and_list_content(self):
        self.assertEqual(content_to_visible_text(None), "")
        self.assertEqual(
            content_to_visible_text([
                {"type": "thinking", "text": "draft the take first"},
                {"type": "text", "text": "Rent hits working people first."},
            ]),
            "Rent hits working people first.",
        )

    def test_closed_think_block_leaves_the_sentence(self):
        raw = "<think>the user asked about rent</think>\n\nRent hits working people first."
        self.assertEqual(content_to_visible_text(raw), "Rent hits working people first.")

    def test_unclosed_think_block_is_not_a_sentence(self):
        self.assertEqual(
            content_to_visible_text("<think>still deciding what the practical problem is"),
            "",
        )

    def test_completion_payload_uses_visible_text_only(self):
        payload = {
            "choices": [{
                "finish_reason": "length",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning": "long hidden chain of thought",
                },
            }]
        }
        self.assertEqual(visible_reply_from_completion(payload), "")

    def test_text_only_blocks_become_a_string(self):
        self.assertEqual(
            flatten_text_content([{"type": "text", "text": "Alex: hey"}]),
            "Alex: hey",
        )
        self.assertIsNone(
            flatten_text_content([{"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}])
        )

    def test_time_gap_does_not_replace_the_personality_prompt(self):
        routed = route_chat_messages(
            "ignored default",
            [
                {
                    "role": "system",
                    "content": "You are Hannah. Answer in one sentence.",
                    "model": "meta-llama/llama-4-maverick:free",
                    "auto_router": False,
                },
                {"role": "system", "content": "--- A long time passes ---"},
                {"role": "user", "content": [{"type": "text", "text": "Alex: what happened to rent?"}]},
            ],
        )
        self.assertEqual(routed["system_prompt"], "You are Hannah. Answer in one sentence.")
        self.assertEqual(routed["messages"][0]["content"], "--- A long time passes ---")
        self.assertEqual(routed["messages"][1]["content"], "Alex: what happened to rent?")
        self.assertFalse(routed["auto_router"])


class OutgoingReplyTests(unittest.TestCase):
    def setUp(self):
        self.chat = Chat(bot=None, db=None, settings_manager=None)

    def test_practical_sentence_with_a_colon_is_kept(self):
        text = "Here's the practical problem: rent went up and parents feel it every week."
        self.assertEqual(strip_leading_address(text, ["Alex"]), text)

    def test_name_label_is_still_removed(self):
        self.assertEqual(
            strip_leading_address("Alex: rent went up.", ["Alex"]),
            "rent went up.",
        )

    def test_empty_model_text_still_sends_a_sentence(self):
        sent = self.chat._text_to_send("")
        self.assertTrue(sent)
        self.assertIn(sent, FALLBACK_QUOTES)

    def test_accepts_a_real_sentence_and_rejects_a_duplicate(self):
        first = self.chat._accept_llm_text(
            "Rent hits working people first.",
            guild_id=1,
            speaker_names={"Alex"},
        )
        self.assertEqual(first, "Rent hits working people first.")
        again = self.chat._accept_llm_text(
            "Rent hits working people first.",
            guild_id=1,
            speaker_names={"Alex"},
        )
        self.assertIsNone(again)
        self.assertTrue(self.chat._text_to_send(again))

    def test_long_reply_ends_on_a_sentence(self):
        sentence = "Rent went up and working people feel that bill every single week."
        text = " ".join([sentence] * 6)
        trimmed = self.chat._trim_reply(text)
        self.assertLessEqual(len(trimmed), 200)
        self.assertTrue(trimmed.endswith("."))

    def test_sanitize_none_is_empty(self):
        self.assertEqual(sanitize_message(None), "")


class _FakeResponse:
    status = 400
    reason = "Bad Request"


class _Channel:
    def __init__(self, fail_reference=False):
        self.fail_reference = fail_reference
        self.sent = []

    async def send(self, content=None, **kwargs):
        if self.fail_reference and kwargs.get("reference") is not None:
            raise discord.errors.HTTPException(_FakeResponse(), "Missing Access")
        self.sent.append(content)
        return content


class _Message:
    def __init__(self, fail_reference=False):
        self.channel = _Channel(fail_reference=fail_reference)


class SendAfterTypingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.chat = Chat(bot=None, db=None, settings_manager=None)

    async def test_empty_reply_still_sends_a_sentence(self):
        message = _Message()
        sent = await self.chat._try_send_reply(message, None, False)
        self.assertIn(sent, FALLBACK_QUOTES)
        self.assertEqual(message.channel.sent, [sent])

    async def test_reference_failure_still_sends_the_sentence(self):
        message = _Message(fail_reference=True)
        sent = await self.chat._try_send_reply(message, "Rent went up again.", True)
        self.assertEqual(sent, "Rent went up again.")
        self.assertEqual(message.channel.sent, ["Rent went up again."])


if __name__ == "__main__":
    unittest.main()
