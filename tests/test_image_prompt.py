import unittest

from llm import build_pollinations_url
from utils import extract_image_prompt


class ExtractImagePromptTests(unittest.TestCase):
    def test_strips_hannah_address_so_subject_is_the_cat(self):
        self.assertEqual(extract_image_prompt("hannah draw a cat"), "a cat")

    def test_conversational_request(self):
        self.assertEqual(
            extract_image_prompt("Hannah, can you draw me a red dragon"),
            "a red dragon",
        )

    def test_short_draw_a_cat_still_works(self):
        self.assertEqual(extract_image_prompt("draw a cat"), "a cat")

    def test_draw_me_a_cat(self):
        self.assertEqual(extract_image_prompt("draw me a cat"), "a cat")

    def test_mention_stripped(self):
        self.assertEqual(
            extract_image_prompt("<@123> draw a sunset over the ocean"),
            "a sunset over the ocean",
        )

    def test_keeps_hannah_when_she_is_the_subject(self):
        self.assertEqual(
            extract_image_prompt("draw hannah montana on stage"),
            "hannah montana on stage",
        )

    def test_false_positives(self):
        self.assertIsNone(extract_image_prompt("imagine that"))
        self.assertIsNone(extract_image_prompt("i can imagine a better ending"))
        self.assertIsNone(extract_image_prompt("that's a nice drawing of a cat"))

    def test_empty_draw_is_ignored(self):
        self.assertIsNone(extract_image_prompt("draw"))
        self.assertIsNone(extract_image_prompt("hannah draw me something"))

    def test_pollinations_encodes_spaces(self):
        url = build_pollinations_url("a red dragon")
        self.assertIn("/prompt/a%20red%20dragon?", url)
        self.assertNotIn("/prompt/a red dragon", url)


if __name__ == "__main__":
    unittest.main()
