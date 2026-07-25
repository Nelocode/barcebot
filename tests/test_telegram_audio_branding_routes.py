import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module


class TelegramAudioBrandingRoutesTests(unittest.TestCase):
    CSRF = "b" * 48

    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.settings_file = Path(self.temporary.name) / "telegram_audio_branding.json"

        settings_patcher = patch.object(
            app_module,
            "TG_AUDIO_BRANDING_SETTINGS_FILE",
            self.settings_file,
        )
        settings_patcher.start()
        self.addCleanup(settings_patcher.stop)

        environment_patcher = patch.dict(
            os.environ,
            {"TG_AUDIO_TITLE": "", "TG_AUDIO_PERFORMER": ""},
        )
        environment_patcher.start()
        self.addCleanup(environment_patcher.stop)

    def authorize_browser(self):
        with self.client.session_transaction() as browser_session:
            browser_session["telegram_admin"] = True
            browser_session["channel_csrf"] = self.CSRF

    def headers(self, token=None):
        return {"X-Channel-CSRF": token or self.CSRF}

    def test_get_returns_packaged_barcelona_value_without_internal_paths(self):
        response = self.client.get("/api/telegram_audio_branding")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"ok": True, "title": "Las Fiesteras", "performer": "Caché Barcelona"},
            response.get_json(),
        )
        self.assertEqual("no-store", response.headers["Cache-Control"])

    def test_write_requires_admin_browser_and_csrf(self):
        anonymous = self.client.post(
            "/api/telegram_audio_branding",
            json={"performer": "No autorizado"},
            headers=self.headers(),
        )
        self.assertEqual(403, anonymous.status_code)
        self.assertEqual("admin_required", anonymous.get_json()["error_code"])
        self.assertFalse(self.settings_file.exists())

        self.authorize_browser()
        missing_csrf = self.client.post(
            "/api/telegram_audio_branding",
            json={"performer": "Sin CSRF"},
        )
        self.assertEqual(403, missing_csrf.status_code)
        self.assertEqual("csrf_invalid", missing_csrf.get_json()["error_code"])
        self.assertFalse(self.settings_file.exists())

    def test_write_trims_persists_and_applies_without_restarting_workers(self):
        self.authorize_browser()
        with (
            patch.object(app_module, "restart_telegram_worker") as restart_telegram,
            patch.object(app_module, "restart_wa_bot") as restart_whatsapp,
        ):
            response = self.client.post(
                "/api/telegram_audio_branding",
                json={"performer": "  Mi Caché Barcelona  "},
                headers=self.headers(),
            )

        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual("Mi Caché Barcelona", payload["performer"])
        self.assertEqual(
            {"performer": "Mi Caché Barcelona"},
            json.loads(self.settings_file.read_text(encoding="utf-8")),
        )
        restart_telegram.assert_not_called()
        restart_whatsapp.assert_not_called()

    def test_invalid_value_does_not_replace_previous_setting(self):
        self.settings_file.write_text(
            json.dumps({"performer": "Caché Barcelona"}, ensure_ascii=False),
            encoding="utf-8",
        )
        original = self.settings_file.read_bytes()
        self.authorize_browser()

        response = self.client.post(
            "/api/telegram_audio_branding",
            json={"performer": "Barcelona\nTG_API_HASH=injected"},
            headers=self.headers(),
        )

        self.assertEqual(400, response.status_code)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(original, self.settings_file.read_bytes())


if __name__ == "__main__":
    unittest.main()
