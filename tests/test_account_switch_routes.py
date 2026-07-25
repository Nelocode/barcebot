import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module


class AccountSwitchRoutesTestCase(unittest.TestCase):
    CSRF = "c" * 48

    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

        self.data_dir = Path(self.temporary.name) / "data"
        self.wa_auth_dir = self.data_dir / "wa_auth"
        self.wa_identity_file = self.data_dir / "wa_identity.json"
        self.wa_switch_dir = self.data_dir / "wa_switch"

        replacements = {
            "DATA_DIR": self.data_dir,
            "WA_CALL_HEALTH_FILE": self.data_dir / "wa_call_health.json",
            "WA_AUTH_DIR": self.wa_auth_dir,
            "WA_IDENTITY_FILE": self.wa_identity_file,
            "WA_SWITCH_DIR": self.wa_switch_dir,
            "WA_SWITCH_AUTH_DIR": self.wa_switch_dir / "candidate_auth",
            "WA_SWITCH_QR_FILE": self.wa_switch_dir / "qr.png",
            "WA_SWITCH_HEALTH_FILE": self.wa_switch_dir / "health.json",
            "WA_SWITCH_IDENTITY_FILE": self.wa_switch_dir / "identity.json",
            "WA_SWITCH_PID_FILE": self.wa_switch_dir / "worker.pid",
            "WA_SWITCH_OPERATION_FILE": self.wa_switch_dir / "operation.json",
            "WA_SWITCH_RECOVERY_ROOT": self.data_dir / ".wa_switch_recovery",
        }
        for name, value in replacements.items():
            patcher = patch.object(app_module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def authorize_browser(self):
        with self.client.session_transaction() as browser_session:
            browser_session["wa_admin"] = True
            browser_session["channel_csrf"] = self.CSRF

    def mutation_headers(self, token=None):
        return {"X-Channel-CSRF": token or self.CSRF}

    def seed_active_whatsapp(self, contents="old-account-session"):
        self.wa_auth_dir.mkdir(parents=True, exist_ok=True)
        credentials = self.wa_auth_dir / "creds.json"
        credentials.write_text(contents, encoding="utf-8")
        return credentials

    def test_channel_mutations_require_admin_browser_and_valid_csrf(self):
        with patch.object(app_module, "restart_wa_bot") as restart:
            anonymous = self.client.post(
                "/api/restart_wa_bot",
                headers=self.mutation_headers(),
            )
            self.assertEqual(403, anonymous.status_code)
            self.assertEqual("admin_required", anonymous.get_json()["error_code"])

            self.authorize_browser()
            missing_csrf = self.client.post("/api/restart_wa_bot")
            invalid_csrf = self.client.post(
                "/api/restart_wa_bot",
                headers=self.mutation_headers("x" * 48),
            )

        self.assertEqual(403, missing_csrf.status_code)
        self.assertEqual("csrf_invalid", missing_csrf.get_json()["error_code"])
        self.assertEqual(403, invalid_csrf.status_code)
        self.assertEqual("csrf_invalid", invalid_csrf.get_json()["error_code"])
        restart.assert_not_called()

    def test_restart_whatsapp_preserves_active_auth_directory(self):
        credentials = self.seed_active_whatsapp()
        self.authorize_browser()

        with (
            patch.object(app_module, "_stop_wa_process") as stop,
            patch.object(app_module, "_start_wa_process", return_value=4321) as start,
        ):
            response = self.client.post(
                "/api/restart_wa_bot",
                headers=self.mutation_headers(),
            )

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual("old-account-session", credentials.read_text(encoding="utf-8"))
        stop.assert_called_once_with(self.data_dir / "wa_bot.pid")
        self.assertEqual(self.wa_auth_dir, start.call_args.kwargs["auth_dir"])
        self.assertFalse(start.call_args.kwargs["link_only"])

    def test_whatsapp_status_requires_an_open_socket_not_only_a_live_pid(self):
        self.seed_active_whatsapp()
        with (
            patch.object(app_module, "_wa_process_running", return_value=True),
            patch.object(
                app_module,
                "_read_wa_call_health",
                return_value={"connection": "closed"},
            ),
        ):
            self.assertFalse(app_module.wa_is_running())

        with (
            patch.object(app_module, "_wa_process_running", return_value=True),
            patch.object(
                app_module,
                "_read_wa_call_health",
                return_value={"connection": "open"},
            ),
        ):
            self.assertTrue(app_module.wa_is_running())

    def test_legacy_reset_endpoint_is_gone_and_cannot_delete_session(self):
        credentials = self.seed_active_whatsapp()

        with patch.object(app_module, "_stop_wa_process") as stop:
            response = self.client.post("/api/reset_wa")

        self.assertEqual(410, response.status_code)
        self.assertEqual(
            "use_transactional_switch",
            response.get_json()["error_code"],
        )
        self.assertEqual("old-account-session", credentials.read_text(encoding="utf-8"))
        stop.assert_not_called()

    def test_whatsapp_switch_start_and_cancel_leave_old_account_active(self):
        credentials = self.seed_active_whatsapp()
        self.authorize_browser()

        with (
            patch.object(app_module, "_start_wa_process", return_value=9876) as start,
            patch.object(app_module, "_stop_wa_process") as stop,
        ):
            started = self.client.post(
                "/api/switch_wa",
                json={"confirm": True},
                headers=self.mutation_headers(),
            )

            self.assertEqual(202, started.status_code)
            self.assertEqual("preparing", started.get_json()["state"])
            self.assertEqual("old-account-session", credentials.read_text(encoding="utf-8"))
            self.assertTrue(app_module.WA_SWITCH_AUTH_DIR.is_dir())

            operation = json.loads(
                app_module.WA_SWITCH_OPERATION_FILE.read_text(encoding="utf-8")
            )
            self.assertIn("token_hash", operation)
            self.assertNotIn("token", operation)
            with self.client.session_transaction() as browser_session:
                attempt_token = browser_session.get("wa_switch_token")
            self.assertIsInstance(attempt_token, str)
            self.assertNotIn(attempt_token, app_module.WA_SWITCH_OPERATION_FILE.read_text(encoding="utf-8"))

            cancelled = self.client.post(
                "/api/switch_wa/cancel",
                headers=self.mutation_headers(),
            )

        self.assertEqual(200, cancelled.status_code)
        self.assertTrue(cancelled.get_json()["ok"])
        self.assertEqual("old-account-session", credentials.read_text(encoding="utf-8"))
        self.assertFalse(self.wa_switch_dir.exists())
        with self.client.session_transaction() as browser_session:
            self.assertNotIn("wa_switch_token", browser_session)
        self.assertEqual(app_module.WA_SWITCH_AUTH_DIR, start.call_args.kwargs["auth_dir"])
        self.assertTrue(start.call_args.kwargs["link_only"])
        stop.assert_called_with(app_module.WA_SWITCH_PID_FILE)

    def test_switch_requires_explicit_confirmation_before_starting_worker(self):
        self.authorize_browser()
        with patch.object(app_module, "_start_wa_process") as start:
            response = self.client.post(
                "/api/switch_wa",
                json={"confirm": False},
                headers=self.mutation_headers(),
            )

        self.assertEqual(400, response.status_code)
        self.assertFalse(response.get_json()["ok"])
        start.assert_not_called()

    def test_pending_recovery_blocks_another_whatsapp_switch(self):
        self.seed_active_whatsapp()
        self.authorize_browser()
        recovery = app_module.WA_SWITCH_RECOVERY_ROOT / "preserved"
        recovery.mkdir(parents=True)
        (recovery / "creds.json").write_text("backup", encoding="utf-8")

        with patch.object(app_module, "_start_wa_process") as start:
            response = self.client.post(
                "/api/switch_wa",
                json={"confirm": True},
                headers=self.mutation_headers(),
            )

        self.assertEqual(409, response.status_code)
        self.assertEqual("recovery_required", response.get_json()["error_code"])
        start.assert_not_called()
        self.assertEqual("backup", (recovery / "creds.json").read_text(encoding="utf-8"))
        self.assertFalse(self.wa_switch_dir.exists())

    def test_status_is_read_only_and_commit_promotes_once(self):
        self.seed_active_whatsapp()
        self.authorize_browser()
        with patch.object(app_module, "_start_wa_process", return_value=9876):
            started = self.client.post(
                "/api/switch_wa",
                json={"confirm": True},
                headers=self.mutation_headers(),
            )
        self.assertEqual(202, started.status_code)

        def promote_and_finish_operation():
            # La promoción real elimina el intento y su token de navegador. El
            # doble POST debe encontrar el cambio ya consumido, no promoverlo
            # una segunda vez.
            app_module._cleanup_wa_switch_candidate()
            return True, "cambiada", {}, True, True

        with (
            patch.object(app_module, "_wa_connection_open", return_value=True),
            patch.object(
                app_module,
                "_promote_wa_candidate",
                side_effect=promote_and_finish_operation,
            ) as promote,
        ):
            first_status = self.client.get("/api/switch_wa/status")
            second_status = self.client.get("/api/switch_wa/status")
            self.assertEqual("scanned", first_status.get_json()["state"])
            self.assertEqual("scanned", second_status.get_json()["state"])
            promote.assert_not_called()

            committed = self.client.post(
                "/api/switch_wa/commit",
                headers=self.mutation_headers(),
            )
            repeated_commit = self.client.post(
                "/api/switch_wa/commit",
                headers=self.mutation_headers(),
            )

        self.assertEqual(200, committed.status_code)
        self.assertEqual("ready", committed.get_json()["state"])
        self.assertEqual(404, repeated_commit.status_code)
        promote.assert_called_once_with()

    def test_abandoned_whatsapp_candidate_expires_without_polling(self):
        credentials = self.seed_active_whatsapp()
        self.authorize_browser()
        with (
            patch.object(app_module, "WA_SWITCH_TIMEOUT_SECONDS", 0.05),
            patch.object(app_module, "_start_wa_process", return_value=9876),
        ):
            started = self.client.post(
                "/api/switch_wa",
                json={"confirm": True},
                headers=self.mutation_headers(),
            )
            self.assertEqual(202, started.status_code)
            deadline = time.monotonic() + 1
            while self.wa_switch_dir.exists() and time.monotonic() < deadline:
                time.sleep(0.01)

        self.assertFalse(self.wa_switch_dir.exists())
        self.assertEqual("old-account-session", credentials.read_text(encoding="utf-8"))

    def test_channels_summary_does_not_expose_credentials_or_raw_identifiers(self):
        telegram_api_id = "87654321"
        telegram_api_hash = "0123456789abcdef0123456789abcdef"
        telegram_phone = "+573001234567"
        whatsapp_secret = "noise-key-material-should-never-leave-disk"
        whatsapp_phone = "573009876543"

        self.seed_active_whatsapp(
            json.dumps({"noiseKey": whatsapp_secret, "me": {"id": whatsapp_phone}})
        )
        self.wa_identity_file.write_text(
            json.dumps({"display_name": "Cuenta comercial", "phone_hint": "••••6543"}),
            encoding="utf-8",
        )
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "tg_identity.json").write_text(
            json.dumps({"display_name": "Telegram comercial", "username": "marca"}),
            encoding="utf-8",
        )
        self.authorize_browser()

        with (
            patch.dict(
                os.environ,
                {
                    "TG_API_ID": telegram_api_id,
                    "TG_API_HASH": telegram_api_hash,
                    "TG_PHONE": telegram_phone,
                },
                clear=True,
            ),
            patch.object(app_module, "_telegram_session_is_authorized", return_value=True),
            patch.object(app_module, "bot_is_running", return_value=False),
            patch.object(app_module, "wa_is_running", return_value=False),
            patch.object(app_module, "_wa_connection_open", return_value=False),
            patch.object(app_module, "_load_wa_switch_operation", return_value=None),
        ):
            response = self.client.get("/api/channels")

        self.assertEqual(200, response.status_code)
        data = response.get_json()
        body = response.get_data(as_text=True)
        for secret in (
            telegram_api_id,
            telegram_api_hash,
            telegram_phone,
            whatsapp_secret,
            whatsapp_phone,
            "creds.json",
            "noiseKey",
        ):
            self.assertNotIn(secret, body)

        self.assertEqual(
            {"ok", "csrf", "can_manage", "telegram", "whatsapp"},
            set(data),
        )
        self.assertFalse({"api_id", "api_hash", "phone", "token"} & set(data["telegram"]))
        self.assertFalse({"credentials", "jid", "phone", "token"} & set(data["whatsapp"]))
        self.assertEqual("••••4567", data["telegram"]["phone_hint"])
        self.assertEqual("••••6543", data["whatsapp"]["phone_hint"])

    def test_telegram_interaction_health_is_allowlisted_and_identifier_free(self):
        secret_id = "573001234567"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "tg_interaction_health.json").write_text(
            json.dumps({
                "schema_version": 1,
                "worker_revision": "00000000-0000-4000-8000-000000000001",
                "connection": "open",
                "raw_phone_revision": "00000000-0000-4000-8000-000000000002",
                "phone_subtype": "discarded",
                "phone_revisions": {
                    "requested": "00000000-0000-4000-8000-000000000004",
                    "discarded": "00000000-0000-4000-8000-000000000005",
                    "caller": secret_id,
                },
                "service_call_status": "processed",
                "service_peer_source": "update_entities",
                "missed_call_poll": "healthy",
                "classified_revision": "00000000-0000-4000-8000-000000000003",
                "last_kind": "call",
                "last_response": "call",
                "delivery": {
                    "peer_resolution": "sent",
                    "text": "sent",
                    "audio": "sent",
                },
                "caller_id": secret_id,
                "message": "private content",
            }),
            encoding="utf-8",
        )

        with patch.object(app_module, "bot_is_running", return_value=True):
            response = self.client.get("/api/tg_interaction_health")

        self.assertEqual(200, response.status_code)
        body = response.get_data(as_text=True)
        self.assertNotIn(secret_id, body)
        self.assertNotIn("private content", body)
        data = response.get_json()
        self.assertEqual("discarded", data["phone_subtype"])
        self.assertEqual(
            "00000000-0000-4000-8000-000000000004",
            data["phone_revisions"]["requested"],
        )
        self.assertEqual(
            "00000000-0000-4000-8000-000000000005",
            data["phone_revisions"]["discarded"],
        )
        self.assertNotIn("caller", data["phone_revisions"])
        self.assertEqual("processed", data["service_call_status"])
        self.assertEqual("update_entities", data["service_peer_source"])
        self.assertEqual("healthy", data["missed_call_poll"])
        self.assertEqual("sent", data["delivery"]["audio"])


if __name__ == "__main__":
    unittest.main()
