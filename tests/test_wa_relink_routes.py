import json
import os
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import app as app_module
from wa_relink_notifier import (
    RelinkConfigurationError,
    TelegramRelinkConfig,
    load_telegram_relink_config,
    relink_enabled,
)


class WhatsAppRelinkRoutesTestCase(unittest.TestCase):
    CSRF = "r" * 48

    def setUp(self):
        app_module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
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
            "WA_RELINK_STATE_FILE": self.data_dir / "wa_relink_incident.json",
        }
        for name, value in replacements.items():
            patcher = patch.object(app_module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @property
    def config(self):
        return TelegramRelinkConfig(
            "https://recover.example.test",
            "-1001234567890",
            "123456:private-token",
            "Barcelona",
        )

    @contextmanager
    def configured_relink(self):
        with (
            patch.object(app_module, "relink_enabled", return_value=True),
            patch.object(
                app_module,
                "load_telegram_relink_config",
                return_value=self.config,
            ),
        ):
            yield

    def open_incident(self):
        store = app_module._wa_relink_store()
        incident, _ = store.ensure_open(
            reason="logged_out",
            service_name="Barcelona",
        )
        return store, incident, store.derive_token(incident["incident_id"])

    def grant_capability(self, incident, *, client=None, consume=True):
        browser = client or self.client
        store = app_module._wa_relink_store()
        if consume and store.load()["token_consumed_at"] is None:
            store.consume_token(store.derive_token(incident["incident_id"]))
        with browser.session_transaction() as browser_session:
            browser_session["wa_relink_capability"] = {
                "incident_id": incident["incident_id"],
                "expires_at": time.time() + 600,
            }
            browser_session["wa_relink_csrf"] = self.CSRF

    def seed_owned_candidate(self, incident, *, client=None, owner="owner-token"):
        browser = client or self.client
        app_module.WA_SWITCH_AUTH_DIR.mkdir(parents=True, exist_ok=True)
        app_module._save_wa_switch_operation({
            "version": 1,
            "operation_id": "a" * 32,
            "source": "relink",
            "incident_id": incident["incident_id"],
            "token_hash": app_module._wa_switch_token_digest(owner),
            "started_at": time.time(),
            "status": "preparing",
        })
        with browser.session_transaction() as browser_session:
            browser_session["wa_switch_token"] = owner

    @staticmethod
    def write_creds(auth_dir, account_id):
        auth_dir.mkdir(parents=True, exist_ok=True)
        creds = auth_dir / "creds.json"
        creds.write_text(
            json.dumps({"registered": True, "me": {"id": account_id}}),
            encoding="utf-8",
        )
        return creds

    def test_get_preview_does_not_consume_token_or_generate_qr(self):
        store, _incident, token = self.open_incident()

        with self.configured_relink(), patch.object(app_module, "_start_wa_process") as start:
            response = self.client.get("/wa-relink")

        self.assertEqual(200, response.status_code)
        self.assertIn("El enlace privado aún no ha generado ningún QR", response.get_data(as_text=True))
        self.assertNotIn(token, response.get_data(as_text=True))
        self.assertIsNone(store.load()["token_consumed_at"])
        self.assertFalse(app_module.WA_SWITCH_QR_FILE.exists())
        self.assertFalse(self.wa_switch_dir.exists())
        start.assert_not_called()
        self.assertEqual("no-store, private", response.headers["Cache-Control"])
        self.assertEqual("no-referrer", response.headers["Referrer-Policy"])

    def test_confirm_token_is_one_use_but_same_capability_can_retry_start_failure(self):
        store, incident, token = self.open_incident()
        second_browser = app_module.app.test_client()

        with (
            self.configured_relink(),
            patch.object(app_module, "_schedule_wa_switch_expiry"),
            patch.object(app_module, "_start_wa_process", side_effect=[None, 8123]) as start,
        ):
            failed = self.client.post(
                "/api/wa-relink/confirm",
                json={"token": token},
                headers={"Sec-Fetch-Site": "same-origin"},
            )
            csrf = failed.get_json()["csrf"]
            replayed = second_browser.post(
                "/api/wa-relink/confirm",
                json={"token": token},
                headers={"Sec-Fetch-Site": "same-origin"},
            )
            retried = self.client.post(
                "/api/wa-relink/confirm",
                json={},
                headers={
                    "Sec-Fetch-Site": "same-origin",
                    "X-WA-Relink-CSRF": csrf,
                },
            )

        self.assertEqual(503, failed.status_code)
        self.assertEqual("candidate_start_failed", failed.get_json()["error_code"])
        self.assertEqual(410, replayed.status_code)
        self.assertEqual("token_consumed", replayed.get_json()["error_code"])
        self.assertEqual(202, retried.status_code)
        self.assertFalse(retried.get_json()["reused"])
        self.assertEqual(2, start.call_count)
        self.assertIsNotNone(store.load()["token_consumed_at"])
        with self.client.session_transaction() as browser_session:
            self.assertEqual(incident["incident_id"], browser_session["wa_relink_capability"]["incident_id"])
            self.assertNotIn("wa_admin", browser_session)

    def test_mutations_require_capability_csrf_and_reject_cross_site_exchange(self):
        _store, incident, _token = self.open_incident()
        self.grant_capability(incident)
        self.seed_owned_candidate(incident)

        with (
            self.configured_relink(),
            patch.object(app_module, "_wa_process_running", return_value=True),
            patch.object(app_module, "_start_wa_process") as start,
            patch.object(app_module, "_promote_wa_candidate") as promote,
            patch.object(app_module, "_cleanup_wa_switch_candidate") as cleanup,
        ):
            status = self.client.get("/api/wa-relink/status")
            confirm = self.client.post("/api/wa-relink/confirm", json={})
            commit = self.client.post(
                "/api/wa-relink/commit",
                headers={"X-WA-Relink-CSRF": "wrong"},
            )
            cancel = self.client.post("/api/wa-relink/cancel")
            cross_site = app_module.app.test_client().post(
                "/api/wa-relink/confirm",
                json={"token": "unused"},
                headers={"Sec-Fetch-Site": "cross-site"},
            )

        self.assertEqual(200, status.status_code)
        self.assertEqual(self.CSRF, status.get_json()["csrf"])
        for response in (confirm, commit, cancel):
            self.assertEqual(403, response.status_code)
            self.assertEqual("csrf_invalid", response.get_json()["error_code"])
        self.assertEqual(403, cross_site.status_code)
        self.assertEqual("cross_site_denied", cross_site.get_json()["error_code"])
        start.assert_not_called()
        promote.assert_not_called()
        cleanup.assert_not_called()

    def test_same_candidate_is_reused_and_other_browser_cannot_claim_it(self):
        _store, incident, _token = self.open_incident()
        self.grant_capability(incident)
        self.seed_owned_candidate(incident)
        other_browser = app_module.app.test_client()
        self.grant_capability(incident, client=other_browser, consume=False)

        with (
            self.configured_relink(),
            patch.object(app_module, "_wa_process_running", return_value=True),
            patch.object(app_module, "_wa_connection_open", return_value=False),
            patch.object(app_module, "_start_wa_process") as start,
        ):
            reused = self.client.post(
                "/api/wa-relink/confirm",
                json={},
                headers={"X-WA-Relink-CSRF": self.CSRF},
            )
            conflict = other_browser.post(
                "/api/wa-relink/confirm",
                json={},
                headers={"X-WA-Relink-CSRF": self.CSRF},
            )

        self.assertEqual(200, reused.status_code)
        self.assertTrue(reused.get_json()["reused"])
        self.assertEqual("preparing", reused.get_json()["state"])
        self.assertEqual(409, conflict.status_code)
        self.assertEqual("candidate_owned_elsewhere", conflict.get_json()["error_code"])
        start.assert_not_called()

    def test_different_active_candidate_is_a_conflict_and_never_replaced(self):
        _store, incident, _token = self.open_incident()
        self.grant_capability(incident)
        self.seed_owned_candidate(incident)
        operation = app_module._load_wa_switch_operation()
        operation["source"] = "admin"
        operation.pop("incident_id")
        app_module._save_wa_switch_operation(operation)

        with (
            self.configured_relink(),
            patch.object(app_module, "_wa_process_running", return_value=True),
            patch.object(app_module, "_start_wa_process") as start,
        ):
            response = self.client.post(
                "/api/wa-relink/confirm",
                json={},
                headers={"X-WA-Relink-CSRF": self.CSRF},
            )

        self.assertEqual(409, response.status_code)
        self.assertEqual("switch_in_progress", response.get_json()["error_code"])
        self.assertEqual("admin", app_module._load_wa_switch_operation()["source"])
        start.assert_not_called()

    def test_qr_is_private_non_cacheable_and_never_requires_admin(self):
        _store, incident, _token = self.open_incident()
        self.grant_capability(incident)
        self.seed_owned_candidate(incident)
        png = b"\x89PNG\r\n\x1a\nprivate-qr"
        app_module.WA_SWITCH_QR_FILE.write_bytes(png)

        with self.configured_relink():
            response = self.client.get("/api/wa-relink/qr")

        self.assertEqual(200, response.status_code)
        self.assertEqual(png, response.data)
        self.assertEqual("image/png", response.mimetype)
        self.assertEqual("no-store, private", response.headers["Cache-Control"])
        self.assertEqual("no-cache", response.headers["Pragma"])
        self.assertEqual("no-referrer", response.headers["Referrer-Policy"])
        self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
        self.assertEqual("DENY", response.headers["X-Frame-Options"])
        with self.client.session_transaction() as browser_session:
            self.assertNotIn("wa_admin", browser_session)

    def prepare_commit(self, current_account=None, candidate_account=None):
        _store, incident, _token = self.open_incident()
        self.grant_capability(incident)
        self.seed_owned_candidate(incident)
        if current_account is not None:
            self.write_creds(self.wa_auth_dir, current_account)
        if candidate_account is not None:
            self.write_creds(app_module.WA_SWITCH_AUTH_DIR, candidate_account)
        return incident

    def test_commit_uses_full_creds_match_and_does_not_escalate_admin(self):
        self.prepare_commit(
            "573001234567:1@s.whatsapp.net",
            "573001234567:8@s.whatsapp.net",
        )
        self.wa_identity_file.write_text(
            json.dumps({"phone_hint": "••••1111"}), encoding="utf-8"
        )
        app_module.WA_SWITCH_IDENTITY_FILE.write_text(
            json.dumps({"phone_hint": "••••9999"}), encoding="utf-8"
        )

        with (
            self.configured_relink(),
            patch.object(app_module, "_wa_connection_open", return_value=True),
            patch.object(
                app_module,
                "_promote_wa_candidate",
                return_value=(True, "WhatsApp nuevamente en línea.", {}, True, True),
            ) as promote,
        ):
            response = self.client.post(
                "/api/wa-relink/commit",
                headers={"X-WA-Relink-CSRF": self.CSRF},
            )

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.get_json()["ok"])
        promote.assert_called_once_with(grant_admin=False)
        with self.client.session_transaction() as browser_session:
            self.assertNotIn("wa_admin", browser_session)
            self.assertNotIn("wa_relink_capability", browser_session)
            self.assertNotIn("wa_relink_csrf", browser_session)

    def test_commit_rejects_full_creds_mismatch_even_when_hints_match(self):
        self.prepare_commit(
            "573001234567:1@s.whatsapp.net",
            "573009999999:1@s.whatsapp.net",
        )
        same_hint = json.dumps({"phone_hint": "••••4567"})
        self.wa_identity_file.write_text(same_hint, encoding="utf-8")
        app_module.WA_SWITCH_IDENTITY_FILE.write_text(same_hint, encoding="utf-8")

        with (
            self.configured_relink(),
            patch.object(app_module, "_wa_connection_open", return_value=True),
            patch.object(app_module, "_promote_wa_candidate") as promote,
        ):
            response = self.client.post(
                "/api/wa-relink/commit",
                headers={"X-WA-Relink-CSRF": self.CSRF},
            )

        self.assertEqual(409, response.status_code)
        self.assertEqual("identity_mismatch", response.get_json()["error_code"])
        promote.assert_not_called()
        self.assertTrue(app_module.WA_SWITCH_AUTH_DIR.exists())

    def test_commit_fails_closed_when_either_full_identity_is_unverified(self):
        for missing in ("current", "candidate"):
            with self.subTest(missing=missing):
                with tempfile.TemporaryDirectory() as isolated:
                    current = Path(isolated) / "current"
                    candidate = Path(isolated) / "candidate"
                    if missing != "current":
                        self.write_creds(current, "573001234567:1@s.whatsapp.net")
                    if missing != "candidate":
                        self.write_creds(candidate, "573001234567:2@s.whatsapp.net")
                    with (
                        patch.object(app_module, "WA_AUTH_DIR", current),
                        patch.object(app_module, "WA_SWITCH_AUTH_DIR", candidate),
                        self.configured_relink(),
                        patch.object(app_module, "_wa_connection_open", return_value=True),
                        patch.object(app_module, "_promote_wa_candidate") as promote,
                    ):
                        if not app_module.WA_SWITCH_OPERATION_FILE.exists():
                            _store, incident, _token = self.open_incident()
                            self.grant_capability(incident, consume=False)
                            self.seed_owned_candidate(incident)
                        response = self.client.post(
                            "/api/wa-relink/commit",
                            headers={"X-WA-Relink-CSRF": self.CSRF},
                        )

                    self.assertEqual(409, response.status_code)
                    self.assertEqual("identity_unverified", response.get_json()["error_code"])
                    promote.assert_not_called()

    def test_cancel_removes_only_candidate_and_preserves_old_auth(self):
        _store, incident, _token = self.open_incident()
        self.grant_capability(incident)
        self.seed_owned_candidate(incident)
        old_creds = self.write_creds(
            self.wa_auth_dir,
            "573001234567:1@s.whatsapp.net",
        )
        old_bytes = old_creds.read_bytes()
        self.write_creds(
            app_module.WA_SWITCH_AUTH_DIR,
            "573001234567:2@s.whatsapp.net",
        )

        with self.configured_relink(), patch.object(app_module, "_stop_wa_process") as stop:
            response = self.client.post(
                "/api/wa-relink/cancel",
                headers={"X-WA-Relink-CSRF": self.CSRF},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(old_bytes, old_creds.read_bytes())
        self.assertFalse(self.wa_switch_dir.exists())
        stop.assert_called_once_with(app_module.WA_SWITCH_PID_FILE)
        with self.client.session_transaction() as browser_session:
            self.assertNotIn("wa_relink_capability", browser_session)
            self.assertNotIn("wa_relink_csrf", browser_session)
            self.assertNotIn("wa_admin", browser_session)

    def test_supervisor_sends_one_outage_and_one_recovered_alert(self):
        self.write_creds(self.wa_auth_dir, "573001234567:1@s.whatsapp.net")
        runtime = {
            "running": False,
            "health": {"reauth_required": True, "disconnect_reason": "logged_out"},
        }

        with (
            self.configured_relink(),
            patch.object(app_module, "_wa_process_running", side_effect=lambda _path: runtime["running"]),
            patch.object(app_module, "_read_wa_call_health", side_effect=lambda *_args: runtime["health"]),
            patch.object(app_module, "send_relink_alert", return_value=True) as outage,
            patch.object(app_module, "send_recovered_alert", return_value=True) as recovered,
            patch.object(app_module, "restart_wa_bot") as restart,
        ):
            app_module._supervise_whatsapp_service_once()
            app_module._supervise_whatsapp_service_once()
            runtime["running"] = True
            runtime["health"] = {"connection": "open"}
            app_module._supervise_whatsapp_service_once()
            app_module._supervise_whatsapp_service_once()

        outage.assert_called_once()
        recovered.assert_called_once_with(self.config)
        restart.assert_not_called()
        link = outage.call_args.args[1]
        self.assertTrue(link.startswith("https://recover.example.test/wa-relink#"))
        state = app_module._wa_relink_store().load()
        self.assertEqual("recovered", state["status"])
        self.assertEqual(1, state["outage_notification"]["attempts"])
        self.assertEqual(1, state["recovery_notification"]["attempts"])

    def test_supervisor_does_not_alert_on_terminal_reason_without_reauth_flag(self):
        self.write_creds(self.wa_auth_dir, "573001234567:1@s.whatsapp.net")
        health = {
            "connection": "closed",
            "reauth_required": False,
            "disconnect_reason": "logged_out",
        }

        with (
            self.configured_relink(),
            patch.object(app_module, "_wa_process_running", return_value=False),
            patch.object(app_module, "_read_wa_call_health", return_value=health),
            patch.object(app_module, "send_relink_alert") as alert,
            patch.object(app_module, "restart_wa_bot") as restart,
        ):
            app_module._supervise_whatsapp_service_once()

        alert.assert_not_called()
        restart.assert_called_once_with()
        self.assertFalse(app_module.WA_RELINK_STATE_FILE.exists())

    def test_worker_environment_scrubs_panel_authority_and_notifier_config_is_strict(self):
        source = {
            "FLASK_SECRET": "flask-secret",
            "BILLING_CONTROL_PLANE_ADMIN_TOKEN": "billing-secret",
            "WA_RELINK_TELEGRAM_BOT_TOKEN": "relink-secret",
            "AUTOREPLY_BOT_TOKEN": "runtime-bot-token",
            "SAFE_MARKER": "kept",
        }
        with patch.dict(os.environ, source, clear=True):
            worker = app_module._channel_worker_environment({"WA_LINK_ONLY": "1"})
            self.assertEqual("relink-secret", os.environ["WA_RELINK_TELEGRAM_BOT_TOKEN"])

        self.assertNotIn("FLASK_SECRET", worker)
        self.assertNotIn("BILLING_CONTROL_PLANE_ADMIN_TOKEN", worker)
        self.assertNotIn("WA_RELINK_TELEGRAM_BOT_TOKEN", worker)
        self.assertNotIn("AUTOREPLY_BOT_TOKEN", worker)
        with patch.dict(os.environ, source, clear=True):
            botfather = app_module._channel_worker_environment(
                keep_autoreply_token=True,
            )
        self.assertEqual("runtime-bot-token", botfather["AUTOREPLY_BOT_TOKEN"])
        self.assertNotIn("FLASK_SECRET", botfather)
        self.assertEqual("kept", worker["SAFE_MARKER"])
        self.assertEqual("1", worker["WA_LINK_ONLY"])

        valid = {
            "WA_RELINK_ENABLED": "1",
            "WA_RELINK_PUBLIC_BASE_URL": "https://recover.example.test/base/",
            "WA_RELINK_TELEGRAM_CHAT_ID": "-1001234567890",
            "WA_RELINK_TELEGRAM_BOT_TOKEN": "dedicated",
            "AUTOREPLY_BOT_TOKEN": "fallback",
            "WA_RELINK_SERVICE_NAME": "Barcelona",
        }
        config = load_telegram_relink_config(valid)
        self.assertTrue(relink_enabled(valid))
        self.assertEqual("dedicated", config.bot_token)
        self.assertEqual(
            "https://recover.example.test/base/wa-relink#opaque",
            config.recovery_link("opaque"),
        )
        fallback = dict(valid)
        fallback.pop("WA_RELINK_TELEGRAM_BOT_TOKEN")
        self.assertEqual("fallback", load_telegram_relink_config(fallback).bot_token)
        self.assertFalse(relink_enabled({"WA_RELINK_ENABLED": "true"}))

        invalid_urls = (
            "http://recover.example.test",
            "https://user:pass@recover.example.test",
            "https://recover.example.test?token=leak",
            "https://recover.example.test#fragment",
        )
        for invalid_url in invalid_urls:
            with self.subTest(invalid_url=invalid_url):
                invalid = dict(valid, WA_RELINK_PUBLIC_BASE_URL=invalid_url)
                with self.assertRaises(RelinkConfigurationError):
                    load_telegram_relink_config(invalid)


if __name__ == "__main__":
    unittest.main()
