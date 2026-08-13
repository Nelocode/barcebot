"""Safe helpers for the panel's reversible conversation test mode."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import shutil
from typing import Any


def _read_object(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_object_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def load_test_mode(config_path: Path) -> bool:
    return _read_object(config_path).get("enabled") is True


def save_test_mode(config_path: Path, enabled: bool) -> None:
    _write_object_atomic(config_path, {"version": 1, "enabled": bool(enabled)})


def interaction_state_summary(state_path: Path) -> dict[str, int | float | None]:
    contacts = _read_object(state_path).get("contacts", {})
    if not isinstance(contacts, dict):
        contacts = {}
    updated_values = []
    for state in contacts.values():
        if not isinstance(state, dict):
            continue
        updated_at = state.get("updated_at")
        if isinstance(updated_at, (int, float)) and not isinstance(updated_at, bool):
            updated_values.append(float(updated_at))
    return {
        "conversation_count": len(contacts),
        "latest_updated_at": max(updated_values, default=None),
    }


def normalize_whatsapp_phone(value: Any) -> str | None:
    """Return E.164 digits without retaining the submitted representation."""

    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 32:
        return None
    # Accept familiar visual separators, but reject letters, JIDs, extensions,
    # control characters and a plus sign anywhere except the beginning.
    if not re.fullmatch(r"\+[1-9][0-9 ()\-.]*", candidate, flags=re.ASCII):
        return None
    digits = re.sub(r"[^0-9]", "", candidate, flags=re.ASCII)
    return digits if 7 <= len(digits) <= 15 else None


def _contact_fingerprint(value: str) -> str:
    material = f"contact\0{value}".encode("utf-8", errors="strict")
    return hashlib.sha256(material).hexdigest()


def _backup_state(state_path: Path, backup_dir: Path, channel: str) -> Path | None:
    if not state_path.is_file():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{channel}_interaction_state.previous.json"
    backup_temp = backup_path.with_suffix(backup_path.suffix + ".tmp")
    shutil.copyfile(state_path, backup_temp)
    try:
        os.chmod(backup_temp, 0o600)
    except OSError:
        pass
    os.replace(backup_temp, backup_path)
    return backup_path


def reset_whatsapp_interaction_by_number(
    state_path: Path,
    *,
    backup_dir: Path,
    phone: Any,
    language: str | None = None,
) -> dict[str, Any]:
    """Reset or preconfigure one WA contact without persisting its raw number.

    WhatsApp state v2 hashes every identity. Both PN forms used by Baileys are
    considered, and an existing alias is followed to its canonical contact.
    Unknown contacts are deliberately created in phase zero so the API never
    becomes a phone-number enumeration endpoint.
    """

    if language not in {None, "es", "en", "fr"}:
        raise ValueError("language must be es, en, fr, or None")
    digits = normalize_whatsapp_phone(phone)
    if digits is None:
        raise ValueError("invalid international WhatsApp number")

    if state_path.exists():
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise OSError("interaction state is unreadable") from exc
        if not isinstance(payload, dict):
            raise OSError("interaction state root is invalid")
    else:
        payload = {}
    contacts = payload.get("contacts", {})
    aliases = payload.get("aliases", {})
    if not isinstance(contacts, dict) or not isinstance(aliases, dict):
        raise OSError("interaction state structure is invalid")

    identity_keys = [
        _contact_fingerprint(f"{digits}@s.whatsapp.net"),
        _contact_fingerprint(f"{digits}@hosted"),
    ]

    def resolve_alias(key: str) -> str | None:
        seen: set[str] = set()
        current = key
        while current not in seen:
            seen.add(current)
            if current in contacts:
                return current
            target = aliases.get(current)
            if not isinstance(target, str):
                return None
            current = target
        return None

    matched_keys: list[str] = []
    for identity_key in identity_keys:
        for candidate in (identity_key, resolve_alias(identity_key)):
            if isinstance(candidate, str) and candidate in contacts and candidate not in matched_keys:
                matched_keys.append(candidate)
    canonical_key = matched_keys[0] if matched_keys else identity_keys[0]
    previous_timestamps = []
    for key in matched_keys:
        state = contacts.get(key)
        updated_at = state.get("updated_at", 0) if isinstance(state, dict) else 0
        if isinstance(updated_at, (int, float)) and not isinstance(updated_at, bool):
            previous_timestamps.append(updated_at)
    previous_updated_at = max(previous_timestamps, default=0)

    backup_path = _backup_state(state_path, backup_dir, "whatsapp")

    # Defensive repair for a state file where the two PN forms ended up in
    # separate contact records: all aliases are redirected to one reset state.
    duplicate_keys = set(matched_keys[1:])
    for duplicate_key in duplicate_keys:
        contacts.pop(duplicate_key, None)
    for alias_key, target_key in list(aliases.items()):
        if target_key in duplicate_keys:
            aliases[alias_key] = canonical_key
    for identity_key in identity_keys:
        aliases[identity_key] = canonical_key

    contacts[canonical_key] = {
        "phase": 0,
        "language": language,
        "recent_events": [],
        "updated_at": previous_updated_at,
        # The PN can still be separate from an older LID-only history.  The
        # Node state router consumes this marker on the first inbound event so
        # that its merge cannot resurrect the old phase or language.
        "reset_pending": True,
    }
    payload.update({"version": 2, "contacts": contacts, "aliases": aliases})
    _write_object_atomic(state_path, payload)
    return {
        "reset": True,
        "remaining": len(contacts),
        "language": language,
        "backup": str(backup_path) if backup_path else None,
    }


def reset_latest_interaction(
    state_path: Path,
    *,
    channel: str,
    backup_dir: Path,
    language: str | None = None,
) -> dict[str, Any]:
    """Return the latest contact to phase zero and keep one rollback copy."""

    if channel not in {"telegram", "whatsapp"}:
        raise ValueError("channel must be telegram or whatsapp")
    if language not in {None, "es", "en", "fr"}:
        raise ValueError("language must be es, en, fr, or None")

    payload = _read_object(state_path)
    contacts = payload.get("contacts", {})
    if not isinstance(contacts, dict) or not contacts:
        return {"reset": False, "remaining": 0, "backup": None}

    def updated_at(item: tuple[str, Any]) -> float:
        state = item[1]
        value = state.get("updated_at", 0) if isinstance(state, dict) else 0
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

    latest_key, _ = max(contacts.items(), key=updated_at)

    backup_path = _backup_state(state_path, backup_dir, channel)

    previous = contacts[latest_key] if isinstance(contacts[latest_key], dict) else {}
    contacts[latest_key] = {
        "phase": 0,
        "language": language,
        "recent_events": [],
        "updated_at": previous.get("updated_at", 0),
    }
    payload["contacts"] = contacts
    _write_object_atomic(state_path, payload)
    return {
        "reset": True,
        "remaining": len(contacts),
        "language": language,
        "backup": str(backup_path),
    }
