import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module
from interaction_state import PersistentInteractionState
from test_mode import (
    interaction_state_summary,
    normalize_whatsapp_phone,
    reset_latest_interaction,
    reset_whatsapp_interaction_by_number,
)


class TestModeStateTests(unittest.TestCase):
    def test_whatsapp_phone_normalization_is_strict_and_international(self):
        self.assertEqual("573001234567", normalize_whatsapp_phone("+57 300-123-4567"))
        for invalid in (
            "573001234567",
            "+0123456789",
            "+57abc3001234567",
            "+573001234567@s.whatsapp.net",
            "+57\n3001234567",
            "+123456",
        ):
            with self.subTest(invalid=invalid):
                self.assertIsNone(normalize_whatsapp_phone(invalid))

    def test_specific_whatsapp_number_resolves_alias_without_persisting_number(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "wa_interaction_state.json"
            phone = "+573001234567"
            from hashlib import sha256

            pn_hash = sha256(b"contact\x00573001234567@s.whatsapp.net").hexdigest()
            canonical = "canonical-contact-hash"
            original = {
                "version": 2,
                "contacts": {
                    canonical: {
                        "phase": 2,
                        "language": "es",
                        "recent_events": ["event-hash"],
                        "updated_at": 50,
                    },
                },
                "aliases": {pn_hash: canonical},
            }
            state_path.write_text(json.dumps(original), encoding="utf-8")

            result = reset_whatsapp_interaction_by_number(
                state_path,
                backup_dir=root / "backups",
                phone=phone,
                language="en",
            )

            serialized = state_path.read_text(encoding="utf-8")
            current = json.loads(serialized)
            self.assertTrue(result["reset"])
            self.assertEqual(0, current["contacts"][canonical]["phase"])
            self.assertEqual("en", current["contacts"][canonical]["language"])
            self.assertEqual([], current["contacts"][canonical]["recent_events"])
            self.assertIs(current["contacts"][canonical]["reset_pending"], True)
            self.assertNotIn("573001234567", serialized)
            self.assertNotIn(phone, json.dumps(result))

    def test_unknown_whatsapp_number_is_preconfigured_with_only_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "wa_interaction_state.json"
            result = reset_whatsapp_interaction_by_number(
                state_path,
                backup_dir=root / "backups",
                phone="+573009876543",
                language=None,
            )

            serialized = state_path.read_text(encoding="utf-8")
            current = json.loads(serialized)
            self.assertTrue(result["reset"])
            self.assertEqual(2, current["version"])
            self.assertEqual(1, len(current["contacts"]))
            self.assertEqual(2, len(current["aliases"]))
            self.assertIsNone(next(iter(current["contacts"].values()))["language"])
            self.assertIs(next(iter(current["contacts"].values()))["reset_pending"], True)
            self.assertNotIn("573009876543", serialized)
            self.assertIsNone(result["backup"])

    def test_specific_reset_fails_closed_on_malformed_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "wa_interaction_state.json"
            malformed = "{not-json"
            state_path.write_text(malformed, encoding="utf-8")

            with self.assertRaises(OSError):
                reset_whatsapp_interaction_by_number(
                    state_path,
                    backup_dir=root / "backups",
                    phone="+573009876543",
                    language="en",
                )

            self.assertEqual(malformed, state_path.read_text(encoding="utf-8"))
            self.assertFalse((root / "backups").exists())

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

    def assert_private_headers(self, response):
        self.assertEqual("no-store, private", response.headers["Cache-Control"])
        self.assertEqual("no-cache", response.headers["Pragma"])
        self.assertEqual("no-referrer", response.headers["Referrer-Policy"])

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
        self.assert_private_headers(anonymous)

        self.authorize()
        missing_csrf = self.client.post("/api/test_mode", json={"enabled": True})
        self.assertEqual(403, missing_csrf.status_code)
        self.assert_private_headers(missing_csrf)

        enabled = self.client.post(
            "/api/test_mode",
            json={"enabled": True},
            headers=self.headers(),
        )
        self.assertEqual(200, enabled.status_code)
        enabled_payload = enabled.get_json()
        self.assertTrue(enabled_payload["enabled"])
        self.assertEqual({"ok", "enabled", "can_manage"}, set(enabled_payload))

        public_state = self.client.get("/api/test_mode")
        self.assertEqual({"ok", "enabled", "can_manage"}, set(public_state.get_json()))
        self.assertNotIn("conversation_count", public_state.get_data(as_text=True))

    def test_reset_is_blocked_until_test_mode_is_enabled(self):
        self.authorize()
        response = self.client.post(
            "/api/test_mode/reset",
            json={"channel": "both", "confirm": True},
            headers=self.headers(),
        )
        self.assertEqual(409, response.status_code)
        self.assertEqual("test_mode_disabled", response.get_json()["error_code"])
        self.assert_private_headers(response)

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
        self.assertEqual("no-store, private", response.headers["Cache-Control"])
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

    def test_specific_whatsapp_number_can_be_preconfigured_without_enumeration(self):
        self.authorize()
        self.client.post(
            "/api/test_mode",
            json={"enabled": True},
            headers=self.headers(),
        )
        phone = "+573009876543"

        with (
            patch.object(app_module, "_test_mode_switch_conflict", return_value=None),
            patch.object(app_module, "_wa_process_running", return_value=False),
        ):
            response = self.client.post(
                "/api/test_mode/reset",
                json={
                    "channel": "whatsapp",
                    "target": "number",
                    "whatsapp_number": phone,
                    "language": "en",
                    "confirm": True,
                },
                headers=self.headers(),
            )

        self.assertEqual(200, response.status_code)
        data = response.get_json()
        self.assertTrue(data["results"]["whatsapp"]["reset"])
        self.assertNotIn("remaining", data["results"]["whatsapp"])
        self.assertNotIn("backup_created", data["results"]["whatsapp"])
        self.assertNotIn("state", data)
        self.assertNotIn(phone, response.get_data(as_text=True))
        self.assertNotIn("found", response.get_data(as_text=True).lower())
        self.assertNotIn("contact_created", response.get_data(as_text=True).lower())
        serialized = app_module.WA_INTERACTION_STATE_FILE.read_text(encoding="utf-8")
        self.assertNotIn("573009876543", serialized)
        contact = next(iter(json.loads(serialized)["contacts"].values()))
        self.assertEqual(0, contact["phase"])
        self.assertEqual("en", contact["language"])

        with (
            patch.object(app_module, "_test_mode_switch_conflict", return_value=None),
            patch.object(app_module, "_wa_process_running", return_value=False),
        ):
            existing_response = self.client.post(
                "/api/test_mode/reset",
                json={
                    "channel": "whatsapp",
                    "target": "number",
                    "whatsapp_number": phone,
                    "language": "en",
                    "confirm": True,
                },
                headers=self.headers(),
            )
        self.assertEqual(data, existing_response.get_json())

    def test_specific_number_rejects_invalid_input_before_touching_worker(self):
        self.authorize()
        self.client.post(
            "/api/test_mode",
            json={"enabled": True},
            headers=self.headers(),
        )
        with patch.object(app_module, "_wa_process_running") as process_running:
            response = self.client.post(
                "/api/test_mode/reset",
                json={
                    "channel": "whatsapp",
                    "target": "number",
                    "whatsapp_number": "+57ext123456789",
                    "confirm": True,
                },
                headers=self.headers(),
            )
        self.assertEqual(400, response.status_code)
        self.assert_private_headers(response)
        process_running.assert_not_called()
        self.assertFalse(app_module.WA_INTERACTION_STATE_FILE.exists())

    def test_reset_holds_all_coordination_locks_through_mutation_and_restart(self):
        self.authorize()
        self.client.post(
            "/api/test_mode",
            json={"enabled": True},
            headers=self.headers(),
        )
        observed = {}
        locks = (
            app_module._test_mode_lock,
            app_module._telegram_switch_lock,
            app_module._wa_switch_lock,
            app_module._wa_process_lock,
        )

        def record(stage):
            observed[stage] = all(lock._is_owned() for lock in locks)

        real_reset = app_module.reset_whatsapp_interaction_by_number

        def conflict(_channels):
            record("conflict")
            return None

        def stop(_pid_file):
            record("stop")

        def reset(*args, **kwargs):
            record("reset")
            return real_reset(*args, **kwargs)

        def restart():
            record("restart")
            return 123

        with (
            patch.object(app_module, "_test_mode_switch_conflict", side_effect=conflict),
            patch.object(app_module, "_wa_process_running", return_value=True),
            patch.object(app_module, "_stop_wa_process", side_effect=stop),
            patch.object(app_module, "reset_whatsapp_interaction_by_number", side_effect=reset),
            patch.object(app_module, "restart_wa_bot", side_effect=restart),
        ):
            response = self.client.post(
                "/api/test_mode/reset",
                json={
                    "channel": "whatsapp",
                    "target": "number",
                    "whatsapp_number": "+573009876543",
                    "language": "en",
                    "confirm": True,
                },
                headers=self.headers(),
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"conflict": True, "stop": True, "reset": True, "restart": True},
            observed,
        )

    def test_reset_both_rolls_back_both_states_if_second_write_fails(self):
        self.authorize()
        self.client.post(
            "/api/test_mode",
            json={"enabled": True},
            headers=self.headers(),
        )
        self.seed_state(app_module.TG_INTERACTION_STATE_FILE, 1)
        self.seed_state(app_module.WA_INTERACTION_STATE_FILE, 2)
        telegram_before = app_module.TG_INTERACTION_STATE_FILE.read_bytes()
        whatsapp_before = app_module.WA_INTERACTION_STATE_FILE.read_bytes()
        real_reset = app_module.reset_latest_interaction

        def reset_with_failure(path, *, channel, backup_dir, language):
            if channel == "whatsapp":
                raise OSError("simulated second write failure")
            return real_reset(
                path,
                channel=channel,
                backup_dir=backup_dir,
                language=language,
            )

        with (
            patch.object(app_module, "_test_mode_switch_conflict", return_value=None),
            patch.object(app_module, "_tracked_telegram_pid", return_value=None),
            patch.object(app_module, "_wa_process_running", return_value=False),
            patch.object(app_module, "reset_latest_interaction", side_effect=reset_with_failure),
        ):
            response = self.client.post(
                "/api/test_mode/reset",
                json={"channel": "both", "language": "fr", "confirm": True},
                headers=self.headers(),
            )

        self.assertEqual(500, response.status_code)
        self.assert_private_headers(response)
        self.assertTrue(response.get_json()["rollback_complete"])
        self.assertEqual({}, response.get_json()["results"])
        self.assertEqual(telegram_before, app_module.TG_INTERACTION_STATE_FILE.read_bytes())
        self.assertEqual(whatsapp_before, app_module.WA_INTERACTION_STATE_FILE.read_bytes())


if __name__ == "__main__":
    unittest.main()
