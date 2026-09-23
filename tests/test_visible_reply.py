import unittest
from unittest.mock import patch

import discord

from cogs.chat import Chat
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

    def test_planning_trace_is_not_the_reply(self):
        payload = {
            "choices": [{
                "finish_reason": "length",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning": "The user asked about rent. I should keep it to one sentence.",
                },
            }]
        }
        self.assertEqual(visible_reply_from_completion(payload), "")

    def test_sentence_lives_in_reasoning_when_content_is_empty(self):
        payload = {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": (
                        "The user wants a take on rent.\n"
                        "Rent hits working people first."
                    ),
                },
            }]
        }
        self.assertEqual(
            visible_reply_from_completion(payload),
            "Rent hits working people first.",
        )

    def test_reply_that_starts_with_ill_is_kept(self):
        payload = {
            "choices": [{
                "message": {
                    "content": None,
                    "reasoning": "I'll be there.",
                },
            }]
        }
        self.assertEqual(visible_reply_from_completion(payload), "I'll be there.")

    def test_reasoning_details_text_is_used(self):
        payload = {
            "choices": [{
                "message": {
                    "content": "",
                    "reasoning_details": [
                        {"type": "reasoning.text", "text": "Let me think about the bill."},
                        {"type": "reasoning.text", "text": "Parents feel that every week."},
                    ],
                },
            }]
        }
        self.assertEqual(
            visible_reply_from_completion(payload),
            "Parents feel that every week.",
        )

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

    def test_empty_model_text_is_not_replaced_with_a_quote(self):
        self.assertEqual(self.chat._text_to_send(""), "")
        self.assertEqual(self.chat._text_to_send(None), "")

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
        self.assertEqual(self.chat._text_to_send(again), "")

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

    async def test_empty_reply_does_not_send_a_fallback(self):
        message = _Message()
        sent = await self.chat._try_send_reply(message, None, False)
        self.assertIsNone(sent)
        self.assertEqual(message.channel.sent, [])

    async def test_reference_failure_still_sends_the_sentence(self):
        message = _Message(fail_reference=True)
        sent = await self.chat._try_send_reply(message, "Rent went up again.", True)
        self.assertEqual(sent, "Rent went up again.")
        self.assertEqual(message.channel.sent, ["Rent went up again."])

    async def test_slowmode_waits_and_still_sends_the_sentence(self):
        class _SlowChannel(_Channel):
            def __init__(self):
                super().__init__()
                self.slowmode_delay = 0
                self.calls = 0

            async def send(self, content=None, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise discord.errors.HTTPException(
                        _FakeResponse(),
                        {"code": 20016, "message": "Slowmode is enabled"},
                    )
                self.sent.append(content)
                return content

        message = _Message()
        message.channel = _SlowChannel()
        sent = await self.chat._try_send_reply(message, "Rent went up again.", False)
        self.assertEqual(sent, "Rent went up again.")
        self.assertEqual(message.channel.sent, ["Rent went up again."])


class _Typing:
    def __init__(self, log):
        self.log = log

    async def __aenter__(self):
        self.log.append("typing")

    async def __aexit__(self, exc_type, exc, tb):
        self.log.append("typing-end")
        return False


class _LiveChannel:
    id = 5

    def __init__(self):
        self.sent = []
        self.log = []

    def typing(self):
        return _Typing(self.log)

    def history(self, limit=20):
        async def _empty():
            if False:
                yield None
        return _empty()

    async def send(self, content=None, **kwargs):
        self.log.append("send")
        self.sent.append(content)
        return content


class _LiveMessage:
    def __init__(self, channel):
        self.channel = channel
        self.guild = type("Guild", (), {"id": 7})()
        self.author = type("Author", (), {"id": 3, "bot": False, "display_name": "Alex"})()
        self.content = "hey are you around"
        self.id = 11
        self.attachments = []
        self.reference = None


class _MentionUser:
    id = 99
    bot = True
    display_name = "Hannah"

    def mentioned_in(self, message):
        return True


class _Settings:
    async def get_settings(self, guild_id):
        return {
            "response_enabled": True,
            "ignored_channels": [],
            "allowed_channels": [],
            "ignored_users": [],
            "learn_from_bots": False,
            "memory_enabled": False,
            "trigger_on_mention": True,
            "trigger_on_reply": True,
            "reaction_chance": 0,
            "gif_chance": 0,
            "random_mention_chance": 0,
            "cooldown_seconds": 5,
            "personality_prompt": "You are Hannah.",
            "llm_model": "test",
            "auto_router_enabled": False,
            "vision_enabled": False,
            "web_search_enabled": False,
        }


class _DB:
    async def increment_stat(self, *args, **kwargs):
        return None


class OnMessageSentenceTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, llm_result):
        channel = _LiveChannel()
        message = _LiveMessage(channel)
        bot = type("Bot", (), {"user": _MentionUser()})()
        chat = Chat(bot, _DB(), _Settings())

        async def fake_llm(*args, **kwargs):
            return llm_result

        async def fake_world():
            return "Today is Wednesday."

        with patch("cogs.chat.generate_llm_response", fake_llm), patch(
            "cogs.chat.world_context_line", fake_world
        ):
            await chat.on_message(message)
        return channel

    async def test_real_sentence_is_sent_after_typing_starts(self):
        channel = await self._run("Rent went up again.")
        self.assertEqual(channel.sent, ["Rent went up again."])
        self.assertEqual(channel.log, ["typing", "send", "typing-end"])

    async def test_empty_model_does_not_start_typing(self):
        channel = await self._run(None)
        self.assertEqual(channel.sent, [])
        self.assertNotIn("typing", channel.log)


if __name__ == "__main__":
    unittest.main()
