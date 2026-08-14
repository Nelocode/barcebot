import unittest
import json
from pathlib import Path

from language_detection import (
    detect_language,
    detect_language_evidence,
    tokenize_language_text,
)


CONTRACT = json.loads(
    (Path(__file__).parents[1] / "language_contract_cases.json").read_text(encoding="utf-8")
)
CONTRACT_CASES = CONTRACT["cases"]


class LanguageDetectionTests(unittest.TestCase):
    def test_shared_evidence_contract_corpus(self):
        for contract_case in CONTRACT_CASES:
            with self.subTest(contract_case["id"]):
                self.assertEqual(
                    contract_case["expected"],
                    detect_language_evidence(contract_case["text"]),
                )

    def test_unicode_codepoint_limit_matches_javascript(self):
        for generated_case in CONTRACT["generated_cases"]:
            with self.subTest(generated_case["id"]):
                text = generated_case["prefix"] * generated_case["repeat"] + generated_case["suffix"]
                self.assertEqual(generated_case["expected"], detect_language_evidence(text))

    def test_unicode_normalisation_limits_and_exact_evidence_shape(self):
        self.assertEqual(["rubi", "francais"], tokenize_language_text("RUBI\u0301 — français"))
        self.assertEqual(256, len(tokenize_language_text("x " * 400 + "hola")))
        self.assertEqual(
            {"language", "strong", "explicit", "score", "margin"},
            set(detect_language_evidence("hola")),
        )

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
