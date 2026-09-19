import json
from pathlib import Path
import tempfile
import unittest

from interaction_state import PersistentInteractionState


class PersistentInteractionStateTests(unittest.TestCase):
    @staticmethod
    def evidence(language, *, strong=False, score=4, margin=4):
        return {
            "language": language,
            "strong": strong,
            "explicit": False,
            "score": score,
            "margin": margin,
        }

    def test_preview_does_not_consume_interaction_before_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = PersistentInteractionState(state_path)

            preview = state.preview(
                contact_id="customer",
                event_id="call:1",
                kind="call",
            )

            self.assertEqual("call", preview.response_key)
            self.assertFalse(state_path.exists())
            committed = state.register(
                contact_id="customer",
                event_id="call:1",
                kind="call",
            )
            self.assertEqual("call", committed.response_key)

    def make_store(self, directory: str, **kwargs) -> PersistentInteractionState:
        return PersistentInteractionState(Path(directory) / "state.json", **kwargs)

    def test_every_distinct_call_is_call_and_later_content_is_step2(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)

            first = store.register(contact_id=1, event_id="call:1", kind="call")
            second = store.register(contact_id=1, event_id="call:2", kind="call")
            third = store.register(contact_id=1, event_id="message:3", kind="content")

            self.assertEqual("call", first.response_key)
            self.assertEqual("call", second.response_key)
            self.assertEqual("step2", third.response_key)
            self.assertEqual([1, 2, 2], [first.phase, second.phase, third.phase])

    def test_call_after_content_is_call_and_following_content_is_step2(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)

            first = store.register(contact_id=1, event_id="message:1", kind="content")
            call = store.register(contact_id=1, event_id="call:2", kind="call")
            following = store.register(
                contact_id=1,
                event_id="message:3",
                kind="content",
            )

            self.assertEqual("step1", first.response_key)
            self.assertEqual("call", call.response_key)
            self.assertEqual("step2", following.response_key)
            self.assertEqual([1, 2, 2], [first.phase, call.phase, following.phase])

    def test_first_content_is_step1_for_text_voice_image_or_file(self):
        with tempfile.TemporaryDirectory() as directory:
            for index, label in enumerate(("text", "voice", "image", "document"), start=1):
                store = self.make_store(directory + label)
                decision = store.register(
                    contact_id=index,
                    event_id=f"message:{index}",
                    kind="content",
                    detected_language="es",
                )
                self.assertEqual("step1", decision.response_key)

    def test_duplicate_does_not_advance_and_survives_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            first = store.register(contact_id=10, event_id="message:1", kind="content")
            duplicate = store.register(contact_id=10, event_id="message:1", kind="content")
            reloaded = self.make_store(directory)
            duplicate_after_restart = reloaded.register(
                contact_id=10,
                event_id="message:1",
                kind="content",
            )
            second = reloaded.register(contact_id=10, event_id="message:2", kind="content")

            self.assertEqual("step1", first.response_key)
            self.assertTrue(duplicate.duplicate)
            self.assertTrue(duplicate_after_restart.duplicate)
            self.assertEqual("step2", second.response_key)

    def test_contacts_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            one = store.register(contact_id="one", event_id="message:a", kind="content")
            two = store.register(contact_id="two", event_id="message:a", kind="content")
            one_again = store.register(contact_id="one", event_id="message:b", kind="content")

            self.assertEqual("step1", one.response_key)
            self.assertEqual("step1", two.response_key)
            self.assertEqual("step2", one_again.response_key)

    def test_language_can_be_detected_after_an_initial_non_text_event(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory, default_language="es")
            call = store.register(contact_id=1, event_id="call:1", kind="call")
            text = store.register(
                contact_id=1,
                event_id="message:2",
                kind="content",
                detected_language="fr",
            )

            self.assertEqual("es", call.language)
            self.assertEqual("fr", text.language)
            self.assertEqual("step2", text.response_key)

    def test_provisional_language_survives_reload_and_detected_text_replaces_it(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            store = PersistentInteractionState(state_path)
            first = store.register(
                contact_id=1,
                event_id="call:1",
                kind="call",
                provisional_language="es",
            )
            self.assertEqual("es", first.language)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(next(iter(saved["contacts"].values()))["language_provisional"])

            text = PersistentInteractionState(state_path).register(
                contact_id=1,
                event_id="message:2",
                kind="content",
                language_evidence=self.evidence("en", strong=True, score=7, margin=7),
            )
            self.assertEqual("en", text.language)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            contact = next(iter(saved["contacts"].values()))
            self.assertEqual("en", contact["language"])
            self.assertFalse(contact["language_provisional"])

    def test_confirmed_language_is_not_replaced_by_a_later_hint(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            first = store.register(
                contact_id=1,
                event_id="message:1",
                kind="content",
                detected_language="fr",
                provisional_language="es",
            )
            following = store.register(
                contact_id=1,
                event_id="message:2",
                kind="content",
                provisional_language="en",
            )
            self.assertEqual("fr", first.language)
            self.assertEqual("fr", following.language)

    def test_state_file_does_not_contain_raw_customer_or_event_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            store.register(
                contact_id="573001234567@s.whatsapp.net",
                event_id="sensitive-event-id",
                kind="content",
            )
            serialized = (Path(directory) / "state.json").read_text(encoding="utf-8")

            self.assertNotIn("573001234567", serialized)
            self.assertNotIn("sensitive-event-id", serialized)
            self.assertEqual(1, json.loads(serialized)["version"])

    def test_valid_json_with_wrong_root_shape_does_not_crash_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            state_file.write_text("[]", encoding="utf-8")

            store = self.make_store(directory)
            decision = store.register(contact_id=1, event_id="message:1", kind="content")

            self.assertEqual("step1", decision.response_key)

    def test_weak_candidate_needs_two_events_and_survives_reload_and_non_text(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            store = PersistentInteractionState(state_path)
            store.register(
                contact_id=1,
                event_id="message:es",
                kind="content",
                language_evidence=self.evidence("es", strong=True, score=7, margin=7),
            )
            before_preview = state_path.read_bytes()
            preview = store.preview(
                contact_id=1,
                event_id="message:en-1",
                kind="content",
                language_evidence=self.evidence("en"),
            )
            self.assertEqual("es", preview.language)
            self.assertEqual(before_preview, state_path.read_bytes())

            first = store.register(
                contact_id=1,
                event_id="message:en-1",
                kind="content",
                language_evidence=self.evidence("en"),
            )
            self.assertEqual("es", first.language)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            contact = next(iter(saved["contacts"].values()))
            self.assertEqual("en", contact["language_candidate"])
            self.assertEqual(1, contact["language_candidate_streak"])

            duplicate_bytes = state_path.read_bytes()
            duplicate = store.register(
                contact_id=1,
                event_id="message:en-1",
                kind="content",
                language_evidence=self.evidence("fr", strong=True, score=7, margin=7),
            )
            self.assertTrue(duplicate.duplicate)
            self.assertEqual(duplicate_bytes, state_path.read_bytes())

            reloaded = PersistentInteractionState(state_path)
            reloaded.register(contact_id=1, event_id="call:1", kind="call")
            after_call = json.loads(state_path.read_text(encoding="utf-8"))
            contact = next(iter(after_call["contacts"].values()))
            self.assertEqual("en", contact["language_candidate"])
            second = reloaded.register(
                contact_id=1,
                event_id="message:en-2",
                kind="content",
                language_evidence=self.evidence("en"),
            )
            self.assertEqual("en", second.language)
            final_contact = next(iter(json.loads(state_path.read_text(encoding="utf-8"))["contacts"].values()))
            self.assertEqual("detected", final_contact["language_source"])
            self.assertIsNone(final_contact["language_candidate"])

    def test_different_weak_language_immediately_replaces_provisional(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            store.register(
                contact_id=1,
                event_id="image:1",
                kind="content",
                provisional_language="fr",
            )
            first = store.register(
                contact_id=1,
                event_id="message:es-1",
                kind="content",
                language_evidence=self.evidence("es"),
            )
            saved = json.loads((Path(directory) / "state.json").read_text(encoding="utf-8"))
            provisional = next(iter(saved["contacts"].values()))
            self.assertTrue(provisional["language_provisional"])
            self.assertEqual("provisional", provisional["language_source"])
            self.assertEqual("es", provisional["language_candidate"])
            self.assertEqual(1, provisional["language_candidate_streak"])
            reloaded = self.make_store(directory)
            second = reloaded.register(
                contact_id=1,
                event_id="message:es-2",
                kind="content",
                language_evidence=self.evidence("es"),
            )
            self.assertEqual("es", first.language)
            self.assertEqual("es", second.language)

    def test_strong_evidence_overrides_operator_seed_and_clears_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            contact_key = PersistentInteractionState._fingerprint("contact", 1)
            state_path.write_text(json.dumps({
                "version": 1,
                "contacts": {
                    contact_key: {
                        "phase": 0,
                        "language": "fr",
                        "language_source": "operator_seed",
                        "language_provisional": False,
                        "language_candidate": "en",
                        "language_candidate_streak": 1,
                        "recent_events": [],
                        "updated_at": 0,
                    }
                },
            }), encoding="utf-8")
            decision = PersistentInteractionState(state_path).register(
                contact_id=1,
                event_id="message:es",
                kind="content",
                language_evidence=self.evidence("es", strong=True, score=11, margin=11),
            )
            self.assertEqual("es", decision.language)
            contact = next(iter(json.loads(state_path.read_text(encoding="utf-8"))["contacts"].values()))
            self.assertEqual("detected", contact["language_source"])
            self.assertIsNone(contact["language_candidate"])

    def test_malformed_evidence_fails_closed_and_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            store = PersistentInteractionState(state_path)
            store.register(
                contact_id=1,
                event_id="message:es",
                kind="content",
                language_evidence=self.evidence("es", strong=True, score=7, margin=7),
            )
            malformed = self.evidence("fr", strong=True, score=7, margin=7)
            malformed["raw_text"] = "sensitive-customer-content"
            decision = store.register(
                contact_id=1,
                event_id="message:invalid",
                kind="content",
                language_evidence=malformed,
            )

            serialized = state_path.read_text(encoding="utf-8")
            self.assertEqual("es", decision.language)
            self.assertNotIn("raw_text", serialized)
            self.assertNotIn("sensitive-customer-content", serialized)


if __name__ == "__main__":
    unittest.main()
