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

    def test_nicki_minaj_aliases(self):
        for alias in (
            "nicki_minaj",
            "nicki minaj",
            "Nicki Minaj",
            "nikki minaj",
            "nikki",
            "nicki",
            "onika",
            "barbie",
        ):
            self.assertEqual(normalize_personality_preset(alias), "nicki_minaj")

    def test_dr_umar_aliases(self):
        for alias in (
            "dr_umar",
            "dr umar",
            "Dr. Umar",
            "Dr Umar Johnson",
            "doctor umar",
            "umar",
            "umar johnson",
        ):
            self.assertEqual(normalize_personality_preset(alias), "dr_umar")

    def test_charlie_kirk_is_practical(self):
        prompt = PERSONALITY_PRESETS["charlie_kirk"]["prompt"].lower()
        self.assertIn("practical", prompt)
        self.assertIn("jobs", prompt)
        self.assertNotIn("prove me wrong", prompt)
        self.assertNotIn("demand definitions", prompt)
        self.assertNotIn("folding-table", prompt)
        self.assertNotIn("debate", prompt)

    def test_panda_aliases(self):
        self.assertEqual(normalize_personality_preset("panda"), "panda")
        self.assertEqual(normalize_personality_preset("Panda"), "panda")

    def test_new_presets_are_selectable(self):
        for preset_id in ("charlie_kirk", "donald_trump", "nicki_minaj", "dr_umar", "panda"):
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

        nicki = build_personality_settings_update("nikki minaj")
        self.assertEqual(nicki["personality_name"], "Nicki Minaj")
        self.assertEqual(nicki["personality"]["preset"], "nicki_minaj")
        self.assertEqual(nicki["personality_prompt"], PERSONALITY_PRESETS["nicki_minaj"]["prompt"])

        umar = build_personality_settings_update("dr. umar")
        self.assertEqual(umar["personality_name"], "Dr. Umar")
        self.assertEqual(umar["personality"]["preset"], "dr_umar")
        self.assertEqual(umar["personality_prompt"], PERSONALITY_PRESETS["dr_umar"]["prompt"])

        panda = build_personality_settings_update("panda")
        self.assertEqual(panda["personality_name"], "Panda")
        self.assertEqual(panda["personality"]["preset"], "panda")
        self.assertEqual(panda["personality_prompt"], PERSONALITY_PRESETS["panda"]["prompt"])


if __name__ == "__main__":
    unittest.main()
