import unittest

from language_detection import detect_language


class LanguageDetectionTests(unittest.TestCase):
    def test_only_a_unique_top_score_confirms_language(self):
        self.assertIsNone(detect_language("photo"))
        self.assertIsNone(detect_language("video"))
        self.assertIsNone(detect_language("ok"))
        self.assertEqual("en", detect_language("Are you available now"))

    def test_explicit_marker_resolves_shared_words(self):
        self.assertEqual("en", detect_language("photo, speak English"))
        self.assertEqual("es", detect_language("video en español"))
        self.assertEqual("fr", detect_language("photo en français"))


if __name__ == "__main__":
    unittest.main()
