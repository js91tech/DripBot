import unittest
from unittest.mock import patch

from cogs.chat import (
    AVATAR_APPEARANCE_CACHE_LIMIT,
    Chat,
    author_custom_avatar_url,
    is_dr_umar_personality,
)


class _Asset:
    def __init__(self, url, key="abc"):
        self.url = url
        self.key = key

    def replace(self, size=256):
        return _Asset(f"{self.url}?size={size}", key=self.key)


class DrUmarPersonalityGateTests(unittest.TestCase):
    def test_preset_dict_and_name(self):
        self.assertTrue(is_dr_umar_personality({"personality": {"preset": "dr_umar"}}))
        self.assertTrue(is_dr_umar_personality({"personality_name": "Dr. Umar"}))
        self.assertTrue(is_dr_umar_personality({"personality": "dr_umar"}))

    def test_other_personalities_are_skipped(self):
        self.assertFalse(is_dr_umar_personality({}))
        self.assertFalse(is_dr_umar_personality(None))
        self.assertFalse(is_dr_umar_personality({"personality": {"preset": "hannah"}}))
        self.assertFalse(is_dr_umar_personality({"personality_name": "Hannah"}))


class AvatarUrlTests(unittest.TestCase):
    def test_default_avatar_is_skipped(self):
        author = type(
            "Author",
            (),
            {"id": 1, "avatar": None, "guild_avatar": None, "display_avatar": None},
        )()
        self.assertEqual(author_custom_avatar_url(author), (None, None))

    def test_custom_avatar_url_and_cache_key(self):
        avatar = _Asset("https://cdn.discordapp.com/avatars/1/abc.png", key="abc")
        author = type(
            "Author",
            (),
            {"id": 1, "avatar": avatar, "guild_avatar": None, "display_avatar": avatar},
        )()
        url, key = author_custom_avatar_url(author)
        self.assertEqual(url, "https://cdn.discordapp.com/avatars/1/abc.png?size=256")
        self.assertEqual(key, "1:abc")


class AvatarAppearanceContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.chat = Chat(bot=None, db=None, settings_manager=None)
        avatar = _Asset("https://cdn.discordapp.com/avatars/3/face.png", key="face")
        self.message = type(
            "Message",
            (),
            {
                "author": type(
                    "Author",
                    (),
                    {
                        "id": 3,
                        "avatar": avatar,
                        "guild_avatar": None,
                        "display_avatar": avatar,
                    },
                )()
            },
        )()

    async def test_non_umar_skips_vision(self):
        with patch("cogs.chat.analyze_image_vision") as vision:
            note = await self.chat._get_author_appearance_context(
                self.message, {"personality": {"preset": "hannah"}, "vision_enabled": True}
            )
        self.assertIsNone(note)
        vision.assert_not_called()

    async def test_vision_off_skips_umar(self):
        with patch("cogs.chat.analyze_image_vision") as vision:
            note = await self.chat._get_author_appearance_context(
                self.message,
                {"personality": {"preset": "dr_umar"}, "vision_enabled": False},
            )
        self.assertIsNone(note)
        vision.assert_not_called()

    async def test_umar_reads_custom_pfp_and_caches(self):
        async def fake_vision(url, prompt=""):
            self.assertIn("avatars/3/face.png", url)
            self.assertIn("apparent race", prompt.lower())
            return "Adult man with dark brown skin and short black hair."

        settings = {"personality": {"preset": "dr_umar"}, "vision_enabled": True}
        with patch("cogs.chat.analyze_image_vision", fake_vision):
            first = await self.chat._get_author_appearance_context(self.message, settings)
            second = await self.chat._get_author_appearance_context(self.message, settings)
        self.assertEqual(first, "Adult man with dark brown skin and short black hair.")
        self.assertEqual(second, first)
        self.assertEqual(len(self.chat._avatar_appearance_cache), 1)

    async def test_cache_evicts_oldest_when_full(self):
        self.chat._avatar_appearance_cache = {
            f"old:{i}": f"note {i}" for i in range(AVATAR_APPEARANCE_CACHE_LIMIT)
        }
        self.chat._remember_avatar_appearance("new:face", "new note")
        self.assertEqual(len(self.chat._avatar_appearance_cache), AVATAR_APPEARANCE_CACHE_LIMIT)
        self.assertNotIn("old:0", self.chat._avatar_appearance_cache)
        self.assertEqual(self.chat._avatar_appearance_cache["new:face"], "new note")

    async def test_history_includes_appearance_note(self):
        channel = type(
            "Channel",
            (),
            {
                "history": lambda self, limit=20: _empty_history(),
            },
        )()
        message = type(
            "Message",
            (),
            {
                "id": 11,
                "content": "what do you see",
                "author": type("Author", (), {"id": 3, "display_name": "Alex"})(),
                "guild": type("Guild", (), {"id": 7})(),
                "channel": channel,
                "reference": None,
                "attachments": [],
            },
        )()
        message.channel = channel
        history, names = await self.chat._build_chat_history(
            message,
            avatar_description="Adult woman with light brown skin and curly hair.",
        )
        trigger = history[-1]["content"][0]["text"]
        self.assertIn("Speaker profile picture appearance:", trigger)
        self.assertIn("light brown skin", trigger)
        self.assertIn("Alex", names)


async def _empty_history():
    if False:
        yield None


if __name__ == "__main__":
    unittest.main()
