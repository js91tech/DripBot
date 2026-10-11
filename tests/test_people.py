import os
import unittest

from config.default_settings import (
    PERSONALITY_PRESETS,
    build_personality_settings_update,
    normalize_personality_preset,
)
from people import (
    analyze_message_style,
    build_clone_personality_prompt,
    build_image_prompt,
    decode_snowflake,
    find_person,
    find_person_for_image_request,
    is_image_request,
    is_nsfw_request,
    people_prompt_block,
    profile_from_image_subject,
)
from utils import extract_image_prompt


class PeopleDatasetTests(unittest.TestCase):
    def test_hannah_and_panda_profiles_load(self):
        hannah = find_person("can you draw Hannah please")
        panda = find_person("draw panda")
        cripmac = find_person("draw cripmac")
        crip_mac = find_person("draw crip mac")
        cmac = find_person("picture of c-mac")
        self.assertIsNotNone(hannah)
        self.assertEqual(hannah["name"], "Hannah")
        self.assertTrue(os.path.exists(hannah["image_path"]))
        self.assertIsNotNone(panda)
        self.assertEqual(panda["id"], "panda")
        self.assertEqual(panda["source"]["message_id"], "1552791353153421444")
        self.assertIsNotNone(cripmac)
        self.assertEqual(cripmac["id"], "cripmac")
        self.assertEqual(cripmac["name"], "Crip Mac")
        self.assertEqual(crip_mac["id"], "cripmac")
        self.assertEqual(cmac["id"], "cripmac")

    def test_image_request_uses_subject_not_address(self):
        self.assertTrue(is_image_request("draw panda as a wizard"))
        self.assertTrue(is_image_request("draw cripmac on 55th street"))
        self.assertFalse(is_image_request("panda is in the chat"))
        self.assertIsNotNone(find_person_for_image_request("make an image of panda"))
        self.assertIsNotNone(find_person_for_image_request("draw crip mac"))
        self.assertIsNone(find_person_for_image_request("panda said hi"))

        cat = extract_image_prompt("hannah draw a cat")
        self.assertEqual(cat, "a cat")
        self.assertIsNone(profile_from_image_subject(cat))

        panda_subject = extract_image_prompt("draw panda")
        self.assertEqual(panda_subject, "panda")
        self.assertEqual(profile_from_image_subject(panda_subject)["id"], "panda")

        cripmac_subject = extract_image_prompt("draw crip mac")
        self.assertEqual(cripmac_subject, "crip mac")
        self.assertEqual(profile_from_image_subject(cripmac_subject)["id"], "cripmac")

        hannah_subject = extract_image_prompt("draw hannah as a barista")
        self.assertIsNotNone(profile_from_image_subject(hannah_subject))
        self.assertEqual(profile_from_image_subject(hannah_subject)["id"], "hannah")

    def test_hannah_montana_is_not_the_real_hannah(self):
        subject = extract_image_prompt("draw hannah montana on stage")
        self.assertEqual(subject, "hannah montana on stage")
        self.assertIsNone(profile_from_image_subject(subject))

    def test_nsfw_blocked(self):
        self.assertTrue(is_nsfw_request("draw panda nude"))
        self.assertTrue(is_nsfw_request("draw cripmac naked"))
        self.assertFalse(is_nsfw_request("draw panda at the park"))
        self.assertFalse(is_nsfw_request("draw cripmac eating pizza"))

    def test_image_prompt_keeps_likeness(self):
        profile = find_person("panda")
        prompt = build_image_prompt(profile, "draw panda as a barista")
        self.assertIn("Panda", prompt)
        self.assertIn("reference photo", prompt)
        self.assertIn("barista", prompt)

        cmac_profile = find_person("cripmac")
        cmac_prompt = build_image_prompt(cmac_profile, "draw crip mac on 55th street")
        self.assertIn("Crip Mac", cmac_prompt)
        self.assertIn("55", cmac_prompt)
        self.assertIn("55th street", cmac_prompt)

    def test_people_block_mentions_both(self):
        block = people_prompt_block()
        self.assertIn("Hannah", block)
        self.assertIn("Panda", block)
        self.assertIn("Crip Mac", block)

    def test_panda_personality_preset(self):
        self.assertEqual(normalize_personality_preset("panda"), "panda")
        self.assertIn("panda", PERSONALITY_PRESETS)
        update = build_personality_settings_update("panda")
        self.assertEqual(update["personality_name"], "Panda")
        self.assertEqual(update["personality"]["preset"], "panda")
        self.assertIn("You are Panda", update["personality_prompt"])
        self.assertIn("NEVER include user names", update["personality_prompt"])

    def test_cripmac_personality_preset(self):
        self.assertEqual(normalize_personality_preset("cripmac"), "cripmac")
        self.assertEqual(normalize_personality_preset("crip mac"), "cripmac")
        self.assertEqual(normalize_personality_preset("c-mac"), "cripmac")
        self.assertIn("cripmac", PERSONALITY_PRESETS)
        update = build_personality_settings_update("cripmac")
        self.assertEqual(update["personality_name"], "Crip Mac")
        self.assertEqual(update["personality"]["preset"], "cripmac")
        self.assertIn("Crip Mac", update["personality_prompt"])
        self.assertIn("55th Street", update["personality_prompt"])
        self.assertIn("NEVER include user names", update["personality_prompt"])


class StyleCloneTests(unittest.TestCase):
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
        prompt = build_clone_personality_prompt("Panda", report)
        self.assertIn("You are Panda", prompt)
        self.assertIn("observed texting rhythm", prompt)

    def test_decode_source_snowflake(self):
        info = decode_snowflake(1552791353153421444)
        self.assertTrue(info["sent_at"].startswith("2026-09-24T21:18:28"))
        self.assertEqual(info["worker"], 1)


if __name__ == "__main__":
    unittest.main()
