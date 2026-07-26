import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module
from interaction_state import PersistentInteractionState
from test_mode import interaction_state_summary, reset_latest_interaction


class TestModeStateTests(unittest.TestCase):
    def test_reset_latest_whatsapp_keeps_identity_aliases_and_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "wa_interaction_state.json"
            original = {
                "version": 2,
                "contacts": {
                    "older": {"phase": 2, "updated_at": 10},
                    "latest": {"phase": 2, "updated_at": 20},
                },
                "aliases": {
                    "older-alias": "older",
                    "latest-phone": "latest",
                    "latest-lid": "latest",
                },
            }
            state_path.write_text(json.dumps(original), encoding="utf-8")

            result = reset_latest_interaction(
                state_path,
                channel="whatsapp",
                backup_dir=root / "backups",
                language="fr",
            )

            current = json.loads(state_path.read_text(encoding="utf-8"))
            backup = json.loads(Path(result["backup"]).read_text(encoding="utf-8"))
            self.assertTrue(result["reset"])
            self.assertEqual(2, result["remaining"])
            self.assertEqual(0, current["contacts"]["latest"]["phase"])
            self.assertEqual("fr", current["contacts"]["latest"]["language"])
            self.assertEqual([], current["contacts"]["latest"]["recent_events"])
            self.assertEqual(original["aliases"], current["aliases"])
            self.assertEqual(original, backup)

    def test_empty_or_missing_state_is_a_safe_noop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = reset_latest_interaction(
                root / "missing.json",
                channel="telegram",
                backup_dir=root / "backups",
            )
            self.assertEqual({"reset": False, "remaining": 0, "backup": None}, result)
            self.assertEqual(
                {"conversation_count": 0, "latest_updated_at": None},
                interaction_state_summary(root / "missing.json"),
            )

    def test_reset_makes_same_telegram_contact_receive_step_one_in_selected_language(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "tg_interaction_state.json"
            state = PersistentInteractionState(state_path)
            state.register(contact_id=451, event_id="first", kind="content", detected_language="es")
            state.register(contact_id=451, event_id="second", kind="content", detected_language="es")

            reset_latest_interaction(
                state_path,
                channel="telegram",
                backup_dir=root / "backups",
                language="en",
            )
            decision = PersistentInteractionState(state_path).register(
                contact_id=451,
                event_id="after-reset",
                kind="content",
                detected_language="fr",
            )

            self.assertEqual("step1", decision.response_key)
            self.assertEqual("en", decision.language)


class TestModeRoutesTests(unittest.TestCase):
    CSRF = "t" * 48

    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name) / "data"
        replacements = {
            "DATA_DIR": self.data_dir,
            "TG_INTERACTION_STATE_FILE": self.data_dir / "tg_interaction_state.json",
            "WA_INTERACTION_STATE_FILE": self.data_dir / "wa_interaction_state.json",
            "TEST_MODE_FILE": self.data_dir / "test_mode.json",
            "TEST_MODE_BACKUP_DIR": self.data_dir / "test_mode_backups",
        }
        for name, value in replacements.items():
            patcher = patch.object(app_module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def authorize(self):
        with self.client.session_transaction() as browser_session:
            browser_session["telegram_admin"] = True
            browser_session["channel_csrf"] = self.CSRF

    def headers(self):
        return {"X-Channel-CSRF": self.CSRF}

    def seed_state(self, path: Path, version: int):
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": version,
            "contacts": {"tester-hash": {"phase": 2, "updated_at": 50}},
        }
        if version == 2:
            payload["aliases"] = {"tester-phone-hash": "tester-hash"}
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_enable_requires_admin_and_csrf(self):
        anonymous = self.client.post(
            "/api/test_mode",
            json={"enabled": True},
            headers=self.headers(),
        )
        self.assertEqual(403, anonymous.status_code)

        self.authorize()
        missing_csrf = self.client.post("/api/test_mode", json={"enabled": True})
        self.assertEqual(403, missing_csrf.status_code)

        enabled = self.client.post(
            "/api/test_mode",
            json={"enabled": True},
            headers=self.headers(),
        )
        self.assertEqual(200, enabled.status_code)
        self.assertTrue(enabled.get_json()["enabled"])

    def test_reset_is_blocked_until_test_mode_is_enabled(self):
        self.authorize()
        response = self.client.post(
            "/api/test_mode/reset",
            json={"channel": "both", "confirm": True},
            headers=self.headers(),
        )
        self.assertEqual(409, response.status_code)
        self.assertEqual("test_mode_disabled", response.get_json()["error_code"])

    def test_reset_both_keeps_backups_and_restarts_only_active_workers(self):
        self.authorize()
        self.client.post(
            "/api/test_mode",
            json={"enabled": True},
            headers=self.headers(),
        )
        self.seed_state(app_module.TG_INTERACTION_STATE_FILE, 1)
        self.seed_state(app_module.WA_INTERACTION_STATE_FILE, 2)

        with (
            patch.object(app_module, "_test_mode_switch_conflict", return_value=None),
            patch.object(app_module, "_tracked_telegram_pid", return_value=101),
            patch.object(app_module, "_is_telegram_worker_pid", return_value=True),
            patch.object(app_module, "_stop_telegram_worker") as stop_telegram,
            patch.object(app_module, "restart_telegram_worker", return_value=(True, "ok")) as restart_telegram,
            patch.object(app_module, "_wa_process_running", return_value=True),
            patch.object(app_module, "_stop_wa_process") as stop_whatsapp,
            patch.object(app_module, "restart_wa_bot", return_value=202) as restart_whatsapp,
        ):
            response = self.client.post(
                "/api/test_mode/reset",
                json={"channel": "both", "language": "en", "confirm": True},
                headers=self.headers(),
            )

        self.assertEqual(200, response.status_code)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["results"]["telegram"]["backup_created"])
        self.assertTrue(data["results"]["whatsapp"]["backup_created"])
        telegram_state = json.loads(app_module.TG_INTERACTION_STATE_FILE.read_text(encoding="utf-8"))
        whatsapp_state = json.loads(app_module.WA_INTERACTION_STATE_FILE.read_text(encoding="utf-8"))
        self.assertEqual(0, telegram_state["contacts"]["tester-hash"]["phase"])
        self.assertEqual("en", telegram_state["contacts"]["tester-hash"]["language"])
        self.assertEqual(0, whatsapp_state["contacts"]["tester-hash"]["phase"])
        self.assertEqual("en", whatsapp_state["contacts"]["tester-hash"]["language"])
        stop_telegram.assert_called_once()
        restart_telegram.assert_called_once()
        stop_whatsapp.assert_called_once_with(self.data_dir / "wa_bot.pid")
        restart_whatsapp.assert_called_once()


if __name__ == "__main__":
    unittest.main()
