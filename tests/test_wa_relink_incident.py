import json
import tempfile
import unittest
from pathlib import Path

from wa_relink_incident import (
    RelinkStateCorrupt,
    RelinkTokenConsumed,
    RelinkTokenExpired,
    WhatsAppRelinkIncidentStore,
)


class WhatsAppRelinkIncidentStoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "relink.json"
        self.store = WhatsAppRelinkIncidentStore(
            self.path,
            "s" * 64,
            link_ttl_seconds=900,
        )

    def test_one_open_incident_has_deterministic_hash_only_token(self):
        first, created = self.store.ensure_open(
            reason="logged_out", service_name="Barcelona", now=1000
        )
        repeated, repeated_created = self.store.ensure_open(
            reason="session_invalid", service_name="Barcelona", now=1001
        )
        token = self.store.derive_token(first["incident_id"])
        on_disk = self.path.read_text(encoding="utf-8")

        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(first["incident_id"], repeated["incident_id"])
        self.assertNotIn(token, on_disk)
        self.assertIn(self.store.token_digest(token), on_disk)

    def test_token_is_consumed_once_and_expires(self):
        incident, _ = self.store.ensure_open(
            reason="logged_out", service_name="Barcelona", now=1000
        )
        token = self.store.derive_token(incident["incident_id"])
        consumed = self.store.consume_token(token, now=1001)
        self.assertEqual(1001, consumed["token_consumed_at"])
        with self.assertRaises(RelinkTokenConsumed):
            self.store.consume_token(token, now=1002)

        other_path = self.path.with_name("expired.json")
        other = WhatsAppRelinkIncidentStore(other_path, "s" * 64, link_ttl_seconds=300)
        expired, _ = other.ensure_open(
            reason="session_invalid", service_name="Barcelona", now=2000
        )
        with self.assertRaises(RelinkTokenExpired):
            other.consume_token(other.derive_token(expired["incident_id"]), now=2300)

    def test_notification_retries_keep_incident_and_token(self):
        incident, _ = self.store.ensure_open(
            reason="logged_out", service_name="Barcelona", now=1000
        )
        token = self.store.derive_token(incident["incident_id"])
        self.assertIsNotNone(self.store.claim_notification("outage", now=1001))
        self.store.finish_notification("outage", success=False, now=1001)
        self.assertIsNone(self.store.claim_notification("outage", now=1020))
        retried = self.store.claim_notification("outage", now=1031)
        self.assertEqual(incident["incident_id"], retried["incident_id"])
        self.assertEqual(token, self.store.derive_token(retried["incident_id"]))

    def test_expired_link_is_never_claimed_for_delivery(self):
        incident, _ = self.store.ensure_open(
            reason="logged_out", service_name="Barcelona", now=1000
        )

        self.assertIsNone(
            self.store.claim_notification(
                "outage",
                now=incident["link_expires_at"],
            )
        )

    def test_corrupt_state_fails_closed(self):
        self.path.write_text(json.dumps({"version": 1, "status": "open"}), encoding="utf-8")
        with self.assertRaises(RelinkStateCorrupt):
            self.store.ensure_open(reason="logged_out", service_name="Barcelona")


if __name__ == "__main__":
    unittest.main()
