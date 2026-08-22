"""Private Telegram Bot API delivery for WhatsApp relink incidents."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


class RelinkConfigurationError(ValueError):
    """The opt-in relink notification configuration is incomplete or unsafe."""


@dataclass(frozen=True)
class TelegramRelinkConfig:
    public_base_url: str
    chat_id: str
    bot_token: str
    service_name: str

    def recovery_link(self, token: str) -> str:
        return f"{self.public_base_url}/wa-relink#{token}"


def relink_enabled(environment=None) -> bool:
    values = os.environ if environment is None else environment
    return values.get("WA_RELINK_ENABLED") == "1"


def load_telegram_relink_config(environment=None) -> TelegramRelinkConfig:
    values = os.environ if environment is None else environment
    base_url = str(values.get("WA_RELINK_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    chat_id = str(values.get("WA_RELINK_TELEGRAM_CHAT_ID") or "").strip()
    dedicated_token = str(values.get("WA_RELINK_TELEGRAM_BOT_TOKEN") or "").strip()
    fallback_token = str(values.get("AUTOREPLY_BOT_TOKEN") or "").strip()
    bot_token = dedicated_token or fallback_token
    service_name = str(values.get("WA_RELINK_SERVICE_NAME") or "").strip()

    parsed = urllib.parse.urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RelinkConfigurationError("WA_RELINK_PUBLIC_BASE_URL must be a clean HTTPS URL")
    if not re.fullmatch(r"-?[1-9][0-9]{0,19}", chat_id):
        raise RelinkConfigurationError("WA_RELINK_TELEGRAM_CHAT_ID must be explicit")
    if not bot_token or len(bot_token) > 512:
        raise RelinkConfigurationError("A Telegram bot token is required")
    if not service_name or len(service_name) > 80 or any(ord(char) < 32 for char in service_name):
        raise RelinkConfigurationError("WA_RELINK_SERVICE_NAME must be a short printable label")
    return TelegramRelinkConfig(base_url, chat_id, bot_token, service_name)


def _send_telegram_message(
    config: TelegramRelinkConfig,
    text: str,
    *,
    timeout_seconds: float = 10,
    opener=None,
) -> bool:
    """Send without logging request URLs, chat identifiers, response bodies or text."""

    payload = json.dumps({
        "chat_id": config.chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{urllib.parse.quote(config.bot_token, safe='')}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    transport = opener or urllib.request.urlopen
    try:
        response = transport(request, timeout=timeout_seconds)
        with response:
            raw = response.read(64 * 1024)
        parsed = json.loads(raw.decode("utf-8"))
        return bool(isinstance(parsed, dict) and parsed.get("ok") is True)
    except (OSError, TimeoutError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError):
        return False


def send_relink_alert(
    config: TelegramRelinkConfig,
    recovery_link: str,
    *,
    opener=None,
) -> bool:
    message = (
        f"{config.service_name}: WhatsApp necesita volver a vincularse.\n"
        "Abre este enlace privado y confirma para generar un único QR:\n"
        f"{recovery_link}\n"
        "El enlace no completa el proceso por sí solo: debes escanear el QR en WhatsApp."
    )
    return _send_telegram_message(config, message, opener=opener)


def send_recovered_alert(config: TelegramRelinkConfig, *, opener=None) -> bool:
    return _send_telegram_message(
        config,
        f"{config.service_name}: WhatsApp está nuevamente en línea.",
        opener=opener,
    )
