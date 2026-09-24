import os
import unittest
from unittest.mock import patch

from config.default_settings import (
    DEFAULT_SETTINGS,
    PERSONALITY_PRESETS,
    build_personality_settings_update,
    normalize_personality_preset,
)
from people import (
    CLONE_LOOKBACK,
    analyze_message_style,
    build_clone_personality_prompt,
    build_image_prompt,
    decode_snowflake,
    extract_emojis_from_text,
    favorites_from_settings,
    find_person,
    find_person_for_image_request,
    is_image_request,
    is_nsfw_request,
    maybe_spice_with_emoji,
    people_prompt_block,
    profile_from_image_subject,
    rank_favorites,
)
from utils import extract_image_prompt


class PeopleDatasetTests(unittest.TestCase):
    def test_hannah_and_panda_profiles_load(self):
        hannah = find_person("can you draw Hannah please")
        panda = find_person("draw panda")
        self.assertIsNotNone(hannah)
        self.assertEqual(hannah["name"], "Hannah")
        self.assertTrue(os.path.exists(hannah["image_path"]))
        self.assertIsNotNone(panda)
        self.assertEqual(panda["id"], "panda")
        self.assertEqual(panda["source"]["message_id"], "1552791353153421444")

    def test_image_request_uses_subject_not_address(self):
        self.assertTrue(is_image_request("draw panda as a wizard"))
        self.assertFalse(is_image_request("panda is in the chat"))
        self.assertIsNotNone(find_person_for_image_request("make an image of panda"))
        self.assertIsNone(find_person_for_image_request("panda said hi"))

        cat = extract_image_prompt("hannah draw a cat")
        self.assertEqual(cat, "a cat")
        self.assertIsNone(profile_from_image_subject(cat))

        panda_subject = extract_image_prompt("draw panda")
        self.assertEqual(panda_subject, "panda")
        self.assertEqual(profile_from_image_subject(panda_subject)["id"], "panda")

        hannah_subject = extract_image_prompt("draw hannah as a barista")
        self.assertIsNotNone(profile_from_image_subject(hannah_subject))
        self.assertEqual(profile_from_image_subject(hannah_subject)["id"], "hannah")

    def test_hannah_montana_is_not_the_real_hannah(self):
        subject = extract_image_prompt("draw hannah montana on stage")
        self.assertEqual(subject, "hannah montana on stage")
        self.assertIsNone(profile_from_image_subject(subject))

    def test_nsfw_blocked(self):
        self.assertTrue(is_nsfw_request("draw panda nude"))
        self.assertFalse(is_nsfw_request("draw panda at the park"))

    def test_image_prompt_keeps_likeness(self):
        profile = find_person("panda")
        prompt = build_image_prompt(profile, "draw panda as a barista")
        self.assertIn("Panda", prompt)
        self.assertIn("reference photo", prompt)
        self.assertIn("barista", prompt)

    def test_people_block_mentions_both(self):
        block = people_prompt_block()
        self.assertIn("Hannah", block)
        self.assertIn("Panda", block)

    def test_panda_personality_preset(self):
        self.assertEqual(normalize_personality_preset("panda"), "panda")
        self.assertIn("panda", PERSONALITY_PRESETS)
        update = build_personality_settings_update("panda")
        self.assertEqual(update["personality_name"], "Panda")
        self.assertEqual(update["personality"]["preset"], "panda")
        self.assertIn("You are Panda", update["personality_prompt"])
        self.assertIn("NEVER include user names", update["personality_prompt"])
        self.assertIn("favorite emojis and stickers", update["personality_prompt"])


class StyleCloneTests(unittest.TestCase):
    def test_clone_lookback_is_400(self):
        self.assertEqual(CLONE_LOOKBACK, 400)
        self.assertEqual(DEFAULT_SETTINGS["sticker_chance"], 0.18)
        self.assertEqual(DEFAULT_SETTINGS["clone_favorites"], {"emojis": [], "stickers": []})
        self.assertEqual(find_person("panda")["source"].get("lookback"), 400)

    def test_extract_emojis_from_text(self):
        found = extract_emojis_from_text("yeth 😭 and <:panda:123456789012345678> plus 💀")
        self.assertIn("😭", found)
        self.assertIn("💀", found)
        self.assertIn("<:panda:123456789012345678>", found)

    def test_rank_favorites(self):
        ranked = rank_favorites(["😭", "💀", "😭", "🔥", "😭", "💀"], 2)
        self.assertEqual(ranked, ["😭", "💀"])

    def test_analyze_message_style(self):
        report = analyze_message_style([
            "ngl that's wild",
            "fr",
            "lowkey want snacks rn",
            "What",
            "yeth 😭",
        ])
        self.assertEqual(report["sample_count"], 5)
        self.assertIn("ngl", report["slang"])
        self.assertIn("😭", report["favorite_emojis"])
        prompt = build_clone_personality_prompt("Panda", report)
        self.assertIn("You are Panda", prompt)
        self.assertIn("observed texting rhythm", prompt)
        self.assertIn("😭", prompt)

    def test_clone_prompt_includes_favorite_stickers(self):
        report = analyze_message_style(
            ["fr 💀"],
            sticker_counts={
                "99": {"id": "99", "name": "wave", "count": 4},
                "88": {"id": "88", "name": "pal", "count": 1},
            },
        )
        self.assertEqual(report["favorite_stickers"][0]["name"], "wave")
        prompt = build_clone_personality_prompt("Panda", report)
        self.assertIn("wave", prompt)
        self.assertIn("favorite emojis", prompt)

    def test_maybe_spice_with_emoji(self):
        class Always:
            def random(self):
                return 0.0

            def choice(self, seq):
                return seq[0]

        class Never:
            def random(self):
                return 1.0

            def choice(self, seq):
                return seq[0]

        self.assertEqual(maybe_spice_with_emoji("hey", ["😭"], rng=Always()), "hey 😭")
        self.assertEqual(maybe_spice_with_emoji("hey 💀", ["😭"], rng=Always()), "hey 💀")
        self.assertEqual(maybe_spice_with_emoji("hey", ["😭"], rng=Never()), "hey")
        self.assertEqual(maybe_spice_with_emoji("hey", [], rng=Always()), "hey")

    def test_favorites_from_settings_prefers_guild_then_profile(self):
        emojis, stickers = favorites_from_settings({
            "clone_favorites": {
                "emojis": ["😭"],
                "stickers": [{"id": "1", "name": "wave"}],
            }
        })
        self.assertEqual(emojis, ["😭"])
        self.assertEqual(stickers[0]["name"], "wave")

        with patch("people.find_person", return_value={
            "favorite_emojis": ["🔥"],
            "favorite_stickers": [{"id": "9", "name": "clap"}],
        }):
            emojis, stickers = favorites_from_settings({"personality_name": "Someone"})
        self.assertEqual(emojis, ["🔥"])
        self.assertEqual(stickers[0]["name"], "clap")

        empty_emojis, empty_stickers = favorites_from_settings({})
        self.assertEqual(empty_emojis, [])
        self.assertEqual(empty_stickers, [])

    def test_decode_source_snowflake(self):
        info = decode_snowflake(1552791353153421444)
        self.assertTrue(info["sent_at"].startswith("2026-09-24T21:18:28"))
        self.assertEqual(info["worker"], 1)


class _Perms:
    view_channel = True
    read_message_history = True


class _Sticker:
    def __init__(self, sid, name):
        self.id = sid
        self.name = name
        self.format = type("Fmt", (), {"name": "png"})()


class _HistMsg:
    def __init__(self, author_id, content="", stickers=None):
        self.author = type("Author", (), {"id": author_id})()
        self.content = content
        self.stickers = stickers or []


class _HistChannel:
    def __init__(self, cid, messages):
        self.id = cid
        self._messages = messages

    def permissions_for(self, me):
        return _Perms()

    def history(self, limit=400):
        async def _gen():
            for msg in self._messages[:limit]:
                yield msg
        return _gen()


class CollectLookbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_collects_last_400_and_ranks_favorites(self):
        from people_clone import collect_user_messages

        user_id = 42
        newest_first = [_HistMsg(1, "noise")] * 400
        newest_first[10] = _HistMsg(user_id, "yeth 😭")
        newest_first[11] = _HistMsg(user_id, "fr 😭 <:panda:99>")
        newest_first[12] = _HistMsg(user_id, "", stickers=[_Sticker(7, "wave")])
        newest_first[13] = _HistMsg(user_id, "again", stickers=[_Sticker(7, "wave")])
        # Older than the 400-message window — must be ignored.
        too_old = [_HistMsg(user_id, "too old 🔥", stickers=[_Sticker(8, "old")])]
        channel = _HistChannel(1, newest_first + too_old)
        guild = type("Guild", (), {"me": object(), "text_channels": [channel]})()

        texts, favorites = await collect_user_messages(guild, user_id, lookback=CLONE_LOOKBACK)
        self.assertEqual(len(texts), 3)
        self.assertNotIn("too old 🔥", texts)
        self.assertEqual(favorites["emojis"][0], "😭")
        self.assertEqual(favorites["stickers"][0]["id"], "7")
        self.assertEqual(favorites["stickers"][0]["name"], "wave")
        self.assertEqual(favorites["stickers"][0]["count"], 2)
        self.assertFalse(any(s.get("id") == "8" for s in favorites["stickers"]))


if __name__ == "__main__":
    unittest.main()
