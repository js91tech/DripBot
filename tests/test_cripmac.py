import unittest

from api import _personality_presets_payload
from cogs.settings_cog import _personality_choices
from config.default_settings import (
    PERSONALITY_ALIASES,
    PERSONALITY_PRESETS,
    build_personality_settings_update,
    normalize_personality_preset,
)
from people import (
    build_image_prompt,
    find_person,
    find_person_for_image_request,
    is_image_request,
    is_nsfw_request,
    load_profiles,
    people_prompt_block,
    profile_from_image_subject,
)
from utils import extract_image_prompt


class CripMacCloneTests(unittest.TestCase):
    def test_preset_exists_and_configured(self):
        self.assertIn("cripmac", PERSONALITY_PRESETS)
        preset = PERSONALITY_PRESETS["cripmac"]
        self.assertEqual(preset["name"], "Crip Mac")
        self.assertIn("55th street", preset["description"].lower())
        self.assertIn("never commit suicide", preset["description"].lower())

    def test_prompt_voice_and_rules(self):
        prompt = PERSONALITY_PRESETS["cripmac"]["prompt"]
        lower_prompt = prompt.lower()
        self.assertIn("55th street", lower_prompt)
        self.assertIn("never commit suicide", lower_prompt)
        self.assertIn("custer", lower_prompt)
        self.assertIn("loc", lower_prompt)
        self.assertIn("no racial slurs", lower_prompt)
        self.assertIn("CRITICAL RULE: NEVER include user names", prompt)

    def test_alias_normalization(self):
        aliases = [
            "cripmac",
            "crip_mac",
            "crip mac",
            "Crip Mac",
            "CRIP MAC",
            "c-mac",
            "C-Mac",
            "cmac",
            "c_mac",
            "trevor",
            "trevor hurd",
            "Trevor Hurd",
            "55th street",
            "55th_street",
            "55",
        ]
        for alias in aliases:
            with self.subTest(alias=alias):
                self.assertEqual(normalize_personality_preset(alias), "cripmac")

    def test_build_settings_update(self):
        for name in ("cripmac", "crip mac", "c-mac", "trevor"):
            update = build_personality_settings_update(name)
            self.assertIsNotNone(update)
            self.assertEqual(update["personality_name"], "Crip Mac")
            self.assertEqual(update["personality"]["preset"], "cripmac")
            self.assertEqual(update["personality_prompt"], PERSONALITY_PRESETS["cripmac"]["prompt"])

    def test_slash_command_choices_include_cripmac(self):
        choices = _personality_choices()
        choice_values = [c.value for c in choices]
        self.assertIn("cripmac", choice_values)
        cripmac_choice = next(c for c in choices if c.value == "cripmac")
        self.assertIn("Crip Mac", cripmac_choice.name)
        self.assertIn("55th Street", cripmac_choice.name)
        # Discord limit is 25 choices max
        self.assertLessEqual(len(choices), 25)

    def test_api_presets_payload_includes_cripmac(self):
        payload = _personality_presets_payload()
        preset_ids = [p["id"] for p in payload]
        self.assertIn("cripmac", preset_ids)
        item = next(p for p in payload if p["id"] == "cripmac")
        self.assertEqual(item["name"], "Crip Mac")
        self.assertIn("55th street", item["description"].lower())

    def test_people_profile_loads(self):
        profiles = {p["id"]: p for p in load_profiles(force=True)}
        self.assertIn("cripmac", profiles)
        p = profiles["cripmac"]
        self.assertEqual(p["name"], "Crip Mac")
        self.assertIn("55", p["appearance"])
        self.assertIn("cripmac", p["aliases"])
        self.assertIn("crip mac", p["aliases"])

    def test_find_person_by_various_phrases(self):
        self.assertEqual(find_person("crip mac")["id"], "cripmac")
        self.assertEqual(find_person("draw cripmac")["id"], "cripmac")
        self.assertEqual(find_person("can you draw c-mac please")["id"], "cripmac")
        self.assertEqual(find_person("picture of c mac")["id"], "cripmac")

    def test_image_request_detection(self):
        self.assertTrue(is_image_request("draw cripmac on 55th street"))
        self.assertIsNotNone(find_person_for_image_request("draw crip mac eating pizza"))
        self.assertIsNone(find_person_for_image_request("crip mac said keep it 55th street"))

        subject = extract_image_prompt("draw crip mac on 55th street")
        self.assertEqual(profile_from_image_subject(subject)["id"], "cripmac")

    def test_image_prompt_preserves_likeness(self):
        profile = find_person("cripmac")
        prompt = build_image_prompt(profile, "draw crip mac eating pizza")
        self.assertIn("Crip Mac", prompt)
        self.assertIn("photorealistic", prompt.lower())
        self.assertIn("55", prompt)
        self.assertIn("eating pizza", prompt)

    def test_nsfw_refusal(self):
        self.assertTrue(is_nsfw_request("draw cripmac nude"))
        self.assertTrue(is_nsfw_request("draw crip mac naked"))
        self.assertFalse(is_nsfw_request("draw cripmac in a blue bandana"))

    def test_people_prompt_block(self):
        block = people_prompt_block()
        self.assertIn("Crip Mac", block)
        self.assertIn("55th Street", block)


if __name__ == "__main__":
    unittest.main()
