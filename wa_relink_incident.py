"""Persistent, fail-closed state for private WhatsApp relink incidents.

The recovery bearer is deterministic for one incident but is never persisted.
Only its SHA-256 digest and non-sensitive lifecycle metadata reach disk.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path


INCIDENT_VERSION = 1
_INCIDENT_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_DIGEST_RE = re.compile(r"^[a-f0-9]{64}$")
_ALLOWED_REASONS = {"logged_out", "session_invalid"}
_ALLOWED_STATUSES = {"open", "recovered"}
_NOTIFICATION_KINDS = {"outage", "recovered"}
_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


class RelinkStateError(RuntimeError):
    """Base class for fail-closed relink state errors."""


class RelinkStateCorrupt(RelinkStateError):
    """The persisted state exists but cannot be trusted."""


class RelinkTokenInvalid(RelinkStateError):
    """The supplied recovery token is malformed or does not match state."""


class RelinkTokenConsumed(RelinkStateError):
    """The supplied recovery token was already exchanged for a capability."""


class RelinkTokenExpired(RelinkStateError):
    """The supplied recovery token is no longer valid."""


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def _urlsafe(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _number_or_none(value) -> bool:
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


class WhatsAppRelinkIncidentStore:
    """Atomic single-incident store for one deployed WhatsApp service."""

    def __init__(self, path: Path, app_secret: str, *, link_ttl_seconds: int = 900):
        if not isinstance(app_secret, str) or len(app_secret) < 32:
            raise ValueError("A stable application secret of at least 32 characters is required")
        self.path = Path(path)
        self._secret = app_secret.encode("utf-8")
        self.link_ttl_seconds = max(300, min(int(link_ttl_seconds), 3_600))
        self._lock = _lock_for(self.path)

    def derive_token(self, incident_id: str) -> str:
        if not _INCIDENT_ID_RE.fullmatch(str(incident_id or "")):
            raise ValueError("Invalid incident id")
        signature = hmac.new(
            self._secret,
            f"wa-relink-v1\0{incident_id}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{incident_id}.{_urlsafe(signature)}"

    @staticmethod
    def token_digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _empty_notification() -> dict:
        return {
            "attempts": 0,
            "sent_at": None,
            "next_attempt_at": 0.0,
            "inflight_until": None,
        }

    def _validate_notification(self, value, field: str) -> None:
        if not isinstance(value, dict):
            raise RelinkStateCorrupt(f"Invalid {field} notification state")
        if not isinstance(value.get("attempts"), int) or value["attempts"] < 0:
            raise RelinkStateCorrupt(f"Invalid {field} notification attempts")
        for key in ("sent_at", "next_attempt_at", "inflight_until"):
            if not _number_or_none(value.get(key)):
                raise RelinkStateCorrupt(f"Invalid {field} notification timestamp")

    def _validate(self, value) -> dict:
        if not isinstance(value, dict) or value.get("version") != INCIDENT_VERSION:
            raise RelinkStateCorrupt("Invalid relink state version")
        if not _INCIDENT_ID_RE.fullmatch(str(value.get("incident_id") or "")):
            raise RelinkStateCorrupt("Invalid relink incident id")
        if value.get("status") not in _ALLOWED_STATUSES:
            raise RelinkStateCorrupt("Invalid relink incident status")
        if value.get("reason") not in _ALLOWED_REASONS:
            raise RelinkStateCorrupt("Invalid relink incident reason")
        if not _DIGEST_RE.fullmatch(str(value.get("token_hash") or "")):
            raise RelinkStateCorrupt("Invalid relink token digest")
        service_name = value.get("service_name")
        if not isinstance(service_name, str) or not service_name or len(service_name) > 80:
            raise RelinkStateCorrupt("Invalid relink service name")
        for key in ("opened_at", "link_expires_at"):
            if not _number_or_none(value.get(key)) or value.get(key) is None:
                raise RelinkStateCorrupt("Invalid relink incident timestamp")
        for key in ("token_consumed_at", "recovered_at"):
            if not _number_or_none(value.get(key)):
                raise RelinkStateCorrupt("Invalid relink incident timestamp")
        self._validate_notification(value.get("outage_notification"), "outage")
        self._validate_notification(value.get("recovery_notification"), "recovery")
        return value

    def _load_unlocked(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RelinkStateCorrupt("WhatsApp relink state is unreadable") from exc
        return self._validate(parsed)

    def load(self) -> dict | None:
        with self._lock:
            state = self._load_unlocked()
            return copy.deepcopy(state)

    def _save_unlocked(self, state: dict) -> None:
        self._validate(state)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(state, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, self.path)

    def ensure_open(
        self,
        *,
        reason: str,
        service_name: str,
        now: float | None = None,
    ) -> tuple[dict, bool]:
        if reason not in _ALLOWED_REASONS:
            raise ValueError("Only terminal WhatsApp session failures open relink incidents")
        service_name = str(service_name or "").strip()
        if not service_name or len(service_name) > 80:
            raise ValueError("A short service name is required")
        observed_at = float(time.time() if now is None else now)
        with self._lock:
            current = self._load_unlocked()
            if current and current["status"] == "open":
                return copy.deepcopy(current), False
            incident_id = secrets.token_hex(16)
            token = self.derive_token(incident_id)
            state = {
                "version": INCIDENT_VERSION,
                "incident_id": incident_id,
                "status": "open",
                "reason": reason,
                "service_name": service_name,
                "opened_at": observed_at,
                "link_expires_at": observed_at + self.link_ttl_seconds,
                "token_hash": self.token_digest(token),
                "token_consumed_at": None,
                "recovered_at": None,
                "outage_notification": self._empty_notification(),
                "recovery_notification": self._empty_notification(),
            }
            self._save_unlocked(state)
            return copy.deepcopy(state), True

    def consume_token(self, token: str, *, now: float | None = None) -> dict:
        supplied = str(token or "")
        if len(supplied) > 256 or "." not in supplied:
            raise RelinkTokenInvalid("Invalid recovery token")
        incident_id = supplied.split(".", 1)[0]
        if not _INCIDENT_ID_RE.fullmatch(incident_id):
            raise RelinkTokenInvalid("Invalid recovery token")
        try:
            expected_token = self.derive_token(incident_id)
        except ValueError as exc:
            raise RelinkTokenInvalid("Invalid recovery token") from exc
        if not hmac.compare_digest(supplied, expected_token):
            raise RelinkTokenInvalid("Invalid recovery token")
        observed_at = float(time.time() if now is None else now)
        with self._lock:
            state = self._load_unlocked()
            if not state or state["status"] != "open" or state["incident_id"] != incident_id:
                raise RelinkTokenInvalid("Invalid recovery token")
            if not hmac.compare_digest(self.token_digest(supplied), state["token_hash"]):
                raise RelinkTokenInvalid("Invalid recovery token")
            if state["token_consumed_at"] is not None:
                raise RelinkTokenConsumed("Recovery token already consumed")
            if observed_at >= float(state["link_expires_at"]):
                raise RelinkTokenExpired("Recovery token expired")
            state["token_consumed_at"] = observed_at
            self._save_unlocked(state)
            return copy.deepcopy(state)

    def claim_notification(
        self,
        kind: str,
        *,
        now: float | None = None,
        max_attempts: int = 3,
        lease_seconds: int = 60,
    ) -> dict | None:
        if kind not in _NOTIFICATION_KINDS:
            raise ValueError("Invalid notification kind")
        observed_at = float(time.time() if now is None else now)
        field = "outage_notification" if kind == "outage" else "recovery_notification"
        expected_status = "open" if kind == "outage" else "recovered"
        with self._lock:
            state = self._load_unlocked()
            if not state or state["status"] != expected_status:
                return None
            if kind == "outage" and state["token_consumed_at"] is not None:
                return None
            if kind == "outage" and observed_at >= float(state["link_expires_at"]):
                return None
            notification = state[field]
            if notification["sent_at"] is not None or notification["attempts"] >= max_attempts:
                return None
            if float(notification.get("next_attempt_at") or 0) > observed_at:
                return None
            if float(notification.get("inflight_until") or 0) > observed_at:
                return None
            notification["attempts"] += 1
            notification["inflight_until"] = observed_at + max(10, int(lease_seconds))
            self._save_unlocked(state)
            return copy.deepcopy(state)

    def finish_notification(
        self,
        kind: str,
        *,
        success: bool,
        now: float | None = None,
    ) -> dict | None:
        if kind not in _NOTIFICATION_KINDS:
            raise ValueError("Invalid notification kind")
        observed_at = float(time.time() if now is None else now)
        field = "outage_notification" if kind == "outage" else "recovery_notification"
        with self._lock:
            state = self._load_unlocked()
            if not state:
                return None
            notification = state[field]
            notification["inflight_until"] = None
            if success:
                notification["sent_at"] = observed_at
                notification["next_attempt_at"] = 0.0
            else:
                delays = (30, 120, 300)
                index = min(max(notification["attempts"] - 1, 0), len(delays) - 1)
                notification["next_attempt_at"] = observed_at + delays[index]
            self._save_unlocked(state)
            return copy.deepcopy(state)

    def mark_recovered(self, *, now: float | None = None) -> dict | None:
        observed_at = float(time.time() if now is None else now)
        with self._lock:
            state = self._load_unlocked()
            if not state:
                return None
            if state["status"] == "open":
                state["status"] = "recovered"
                state["recovered_at"] = observed_at
                self._save_unlocked(state)
            return copy.deepcopy(state)
