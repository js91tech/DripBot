import unittest

from config.default_settings import (
    PERSONALITY_PRESETS,
    build_personality_settings_update,
    normalize_personality_preset,
)


class PersonalityPresetTests(unittest.TestCase):
    def test_charlie_kirk_aliases(self):
        for alias in (
            "charlie_kirk",
            "charlie kirk",
            "Charlie Kirk",
            "charlie",
            "kirk",
            "charliekirk",
        ):
            self.assertEqual(normalize_personality_preset(alias), "charlie_kirk")

    def test_donald_trump_aliases(self):
        for alias in (
            "donald_trump",
            "donald trump",
            "Donald Trump",
            "trump",
            "donald",
            "donaldtrump",
            "the_donald",
        ):
            self.assertEqual(normalize_personality_preset(alias), "donald_trump")

    def test_new_presets_are_selectable(self):
        for preset_id in ("charlie_kirk", "donald_trump"):
            self.assertIn(preset_id, PERSONALITY_PRESETS)
            preset = PERSONALITY_PRESETS[preset_id]
            self.assertTrue(preset["name"])
            self.assertTrue(preset["description"])
            self.assertTrue(preset["prompt"])
            self.assertIn("NEVER include user names", preset["prompt"])

    def test_build_settings_update_for_new_presets(self):
        kirk = build_personality_settings_update("charlie")
        self.assertEqual(kirk["personality_name"], "Charlie Kirk")
        self.assertEqual(kirk["personality"]["preset"], "charlie_kirk")
        self.assertEqual(kirk["personality_prompt"], PERSONALITY_PRESETS["charlie_kirk"]["prompt"])

        trump = build_personality_settings_update("trump")
        self.assertEqual(trump["personality_name"], "Donald Trump")
        self.assertEqual(trump["personality"]["preset"], "donald_trump")
        self.assertEqual(trump["personality_prompt"], PERSONALITY_PRESETS["donald_trump"]["prompt"])


if __name__ == "__main__":
    unittest.main()
