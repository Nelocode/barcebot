import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module


class AccountSwitchPromotionTestCase(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name) / "data"
        self.switch_dir = self.data_dir / "wa_switch"
        replacements = {
            "DATA_DIR": self.data_dir,
            "TG_SESSION_BASE": self.data_dir / "tg_session",
            "TG_SWITCH_SESSION_BASE": self.data_dir / "tg_switch_session",
            "TG_SWITCH_ROLLBACK_DIR": self.data_dir / ".tg_switch_rollback",
            "WA_CALL_HEALTH_FILE": self.data_dir / "wa_call_health.json",
            "WA_AUTH_DIR": self.data_dir / "wa_auth",
            "WA_IDENTITY_FILE": self.data_dir / "wa_identity.json",
            "WA_SWITCH_DIR": self.switch_dir,
            "WA_SWITCH_AUTH_DIR": self.switch_dir / "candidate_auth",
            "WA_SWITCH_QR_FILE": self.switch_dir / "qr.png",
            "WA_SWITCH_HEALTH_FILE": self.switch_dir / "health.json",
            "WA_SWITCH_IDENTITY_FILE": self.switch_dir / "identity.json",
            "WA_SWITCH_PID_FILE": self.switch_dir / "worker.pid",
            "WA_SWITCH_OPERATION_FILE": self.switch_dir / "operation.json",
            "WA_SWITCH_RECOVERY_ROOT": self.data_dir / ".wa_switch_recovery",
        }
        for name, value in replacements.items():
            patcher = patch.object(app_module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def seed_telegram(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        primary = Path(f"{app_module.TG_SESSION_BASE}.session")
        candidate = Path(f"{app_module.TG_SWITCH_SESSION_BASE}.session")
        primary.write_text("old-session", encoding="utf-8")
        candidate.write_text("new-session", encoding="utf-8")
        (self.data_dir / ".env.local").write_text(
            "TG_API_ID=1\nTG_API_HASH=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\nTG_PHONE=+570000000001\n",
            encoding="utf-8",
        )
        (self.data_dir / "tg_session_authorized.json").write_text(
            '{"authorized":true}', encoding="utf-8"
        )
        (self.data_dir / "tg_interaction_state.json").write_text("old-state", encoding="utf-8")
        (self.data_dir / "tg_identity.json").write_text("old-identity", encoding="utf-8")
        return primary, candidate

    def test_telegram_success_promotes_candidate_and_resets_conversation_state(self):
        primary, candidate = self.seed_telegram()
        with (
            patch.dict(
                os.environ,
                {
                    "TG_API_ID": "1",
                    "TG_API_HASH": "a" * 32,
                    "TG_PHONE": "+570000000001",
                },
                clear=True,
            ),
            patch.object(app_module, "_telegram_session_has_auth_key", return_value=True),
            patch.object(app_module, "_stop_telegram_worker"),
            patch.object(app_module, "bot_is_running", return_value=True),
            patch.object(app_module, "restart_telegram_worker", return_value=(True, "ok")),
        ):
            result = app_module._promote_telegram_candidate(2, "b" * 32, "+570000000002")

        self.assertEqual((True, "Cuenta de Telegram cambiada y verificada.", True, True), result)
        self.assertEqual("new-session", primary.read_text(encoding="utf-8"))
        self.assertFalse(candidate.exists())
        self.assertFalse((self.data_dir / "tg_interaction_state.json").exists())
        self.assertFalse((self.data_dir / "tg_identity.json").exists())
        self.assertFalse(app_module.TG_SWITCH_ROLLBACK_DIR.exists())

    def test_telegram_failed_activation_restores_old_files_and_worker(self):
        primary, _candidate = self.seed_telegram()
        with (
            patch.dict(
                os.environ,
                {
                    "TG_API_ID": "1",
                    "TG_API_HASH": "a" * 32,
                    "TG_PHONE": "+570000000001",
                },
                clear=True,
            ),
            patch.object(app_module, "_telegram_session_has_auth_key", return_value=True),
            patch.object(app_module, "_telegram_session_is_authorized", return_value=True),
            patch.object(app_module, "_stop_telegram_worker"),
            patch.object(app_module, "bot_is_running", return_value=True),
            patch.object(
                app_module,
                "restart_telegram_worker",
                side_effect=[(False, "new failed"), (True, "old restored")],
            ),
        ):
            result = app_module._promote_telegram_candidate(2, "b" * 32, "+570000000002")

        self.assertFalse(result[0])
        self.assertTrue(result[2])
        self.assertTrue(result[3])
        self.assertEqual("old-session", primary.read_text(encoding="utf-8"))
        self.assertEqual(
            "old-state",
            (self.data_dir / "tg_interaction_state.json").read_text(encoding="utf-8"),
        )

    def seed_whatsapp(self):
        old_auth = app_module.WA_AUTH_DIR
        old_auth.mkdir(parents=True, exist_ok=True)
        (old_auth / "creds.json").write_text("old-account", encoding="utf-8")
        app_module.WA_SWITCH_AUTH_DIR.mkdir(parents=True, exist_ok=True)
        (app_module.WA_SWITCH_AUTH_DIR / "creds.json").write_text("new-account", encoding="utf-8")
        app_module.WA_SWITCH_IDENTITY_FILE.write_text(
            json.dumps({"display_name": "Nueva", "phone_hint": "••••2222"}),
            encoding="utf-8",
        )
        (self.data_dir / "wa_interaction_state.json").write_text("old-state", encoding="utf-8")
        app_module.WA_IDENTITY_FILE.write_text("old-identity", encoding="utf-8")
        token = "browser-token"
        operation = {
            "version": 1,
            "token_hash": app_module._wa_switch_token_digest(token),
            "started_at": 1,
            "status": "preparing",
        }
        app_module._save_wa_switch_operation(operation)
        return token

    def test_whatsapp_success_promotes_candidate_and_resets_conversation_state(self):
        token = self.seed_whatsapp()
        with app_module.app.test_request_context("/"):
            app_module.session["wa_switch_token"] = token
            with (
                patch.object(app_module, "_wa_connection_open", return_value=True),
                patch.object(app_module, "_wa_process_running", return_value=True),
                patch.object(app_module, "_stop_wa_process"),
                patch.object(app_module, "restart_wa_bot", return_value=777),
                patch.object(app_module, "_wait_until", return_value=True),
            ):
                result = app_module._promote_wa_candidate()

        self.assertTrue(result[0])
        self.assertEqual("new-account", (app_module.WA_AUTH_DIR / "creds.json").read_text(encoding="utf-8"))
        self.assertEqual(
            "Nueva",
            json.loads(app_module.WA_IDENTITY_FILE.read_text(encoding="utf-8"))["display_name"],
        )
        self.assertFalse((self.data_dir / "wa_interaction_state.json").exists())
        self.assertFalse(self.switch_dir.exists())

    def test_whatsapp_failed_activation_restores_old_account(self):
        token = self.seed_whatsapp()
        with app_module.app.test_request_context("/"):
            app_module.session["wa_switch_token"] = token
            with (
                patch.object(app_module, "_wa_connection_open", return_value=True),
                patch.object(app_module, "_wa_process_running", return_value=True),
                patch.object(app_module, "_stop_wa_process"),
                patch.object(app_module, "restart_wa_bot", return_value=None),
            ):
                result = app_module._promote_wa_candidate()

        self.assertFalse(result[0])
        self.assertTrue(result[3])
        self.assertFalse(result[4])
        self.assertEqual("old-account", (app_module.WA_AUTH_DIR / "creds.json").read_text(encoding="utf-8"))
        self.assertEqual(
            "old-state",
            (self.data_dir / "wa_interaction_state.json").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            "old-identity",
            app_module.WA_IDENTITY_FILE.read_text(encoding="utf-8"),
        )
        self.assertFalse(self.switch_dir.exists())


if __name__ == "__main__":
    unittest.main()
