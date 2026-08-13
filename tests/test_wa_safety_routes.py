import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module


class WhatsAppSafetyRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.health_file = Path(self.temporary.name) / "wa_safety_health.json"
        self.control_file = Path(self.temporary.name) / "wa_safety_control.json"
        self.path_patches = [
            patch.object(app_module, "WA_SAFETY_HEALTH_FILE", self.health_file),
            patch.object(app_module, "WA_SAFETY_CONTROL_FILE", self.control_file),
        ]
        for path_patch in self.path_patches:
            path_patch.start()
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()
        self.csrf = "s" * 43

    def tearDown(self):
        for path_patch in reversed(self.path_patches):
            path_patch.stop()
        self.temporary.cleanup()

    def authorize(self):
        with self.client.session_transaction() as browser_session:
            browser_session["wa_admin"] = True
            browser_session["channel_csrf"] = self.csrf

    def write_health(self, **overrides):
        now_ms = int(time.time() * 1000)
        payload = {
            "schema_version": 1,
            "updated_at": now_ms,
            "operator_paused": False,
            "pause_updated_at": None,
            "backoff_until": None,
            "circuit_open_until": None,
            "events": [],
            **overrides,
        }
        self.health_file.write_text(json.dumps(payload), encoding="utf-8")
        return now_ms

    def test_public_health_is_allowlisted_and_identifier_free(self):
        now_ms = int(time.time() * 1000)
        self.write_health(events=[
            {
                "type": "forbidden",
                "at": now_ms,
                "jid": "573001234567@s.whatsapp.net",
                "message": "contenido privado",
                "raw_error": "token-secreto",
            },
            {"type": "not_allowed", "at": now_ms, "phone": "+573001234567"},
        ])

        response = self.client.get("/api/wa_safety_health")

        self.assertEqual(200, response.status_code)
        data = response.get_json()
        self.assertEqual("high", data["level"])
        self.assertEqual(1, data["counts"]["forbidden_60m"])
        self.assertIn("forbidden_response", data["reasons"])
        serialized = response.get_data(as_text=True)
        for forbidden in ("573001234567", "contenido privado", "token-secreto", "raw_error"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual("no-store, private", response.headers["Cache-Control"])

    def test_missing_or_corrupt_health_is_unknown_never_low(self):
        missing = self.client.get("/api/wa_safety_health").get_json()
        self.assertFalse(missing["available"])
        self.assertEqual("unknown", missing["level"])

        self.health_file.write_text("{not-json", encoding="utf-8")
        corrupt = self.client.get("/api/wa_safety_health").get_json()
        self.assertFalse(corrupt["available"])
        self.assertEqual("unknown", corrupt["level"])

    def test_stale_or_stopped_low_health_is_unknown(self):
        old = int(time.time() * 1000) - app_module.WA_SAFETY_STALE_AFTER_MS - 1
        self.write_health(updated_at=old)
        with patch.object(app_module, "_wa_process_running", return_value=True):
            stale = self.client.get("/api/wa_safety_health").get_json()
        self.assertFalse(stale["available"])
        self.assertFalse(stale["telemetry_fresh"])
        self.assertEqual("unknown", stale["level"])

        self.write_health()
        with patch.object(app_module, "_wa_process_running", return_value=False):
            stopped = self.client.get("/api/wa_safety_health").get_json()
        self.assertFalse(stopped["available"])
        self.assertFalse(stopped["worker_running"])
        self.assertEqual("unknown", stopped["level"])

    def test_pause_requires_admin_session_and_csrf(self):
        self.write_health()
        original_telemetry = self.health_file.read_text(encoding="utf-8")
        payload = {"paused": True, "confirm": True}

        anonymous = self.client.post("/api/wa_safety/pause", json=payload)
        self.assertEqual(403, anonymous.status_code)

        self.authorize()
        missing_csrf = self.client.post("/api/wa_safety/pause", json=payload)
        self.assertEqual(403, missing_csrf.status_code)

        accepted = self.client.post(
            "/api/wa_safety/pause",
            json=payload,
            headers={"X-Channel-CSRF": self.csrf},
        )
        self.assertEqual(200, accepted.status_code)
        self.assertTrue(accepted.get_json()["operator_paused"])
        persisted = json.loads(self.control_file.read_text(encoding="utf-8"))
        self.assertTrue(persisted["operator_paused"])
        self.assertIsInstance(persisted["pause_updated_at"], int)
        self.assertEqual(original_telemetry, self.health_file.read_text(encoding="utf-8"))

    def test_resume_requires_explicit_review_confirmation(self):
        self.write_health(operator_paused=True)
        self.authorize()
        headers = {"X-Channel-CSRF": self.csrf}

        rejected = self.client.post(
            "/api/wa_safety/pause",
            json={"paused": False, "confirm": True},
            headers=headers,
        )
        self.assertEqual(400, rejected.status_code)

        accepted = self.client.post(
            "/api/wa_safety/pause",
            json={"paused": False, "confirm": True, "review_confirmed": True},
            headers=headers,
        )
        self.assertEqual(200, accepted.status_code)
        self.assertFalse(accepted.get_json()["operator_paused"])


if __name__ == "__main__":
    unittest.main()
