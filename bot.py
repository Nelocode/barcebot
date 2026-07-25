"""Bot AutoReply comercial para una cuenta de usuario de Telegram.

Reglas de conversación:
* primera llamada real: mensaje y audio de llamada;
* primer texto o multimedia: Paso 1;
* texto o multimedia posterior: Paso 2, sin límite;
* cualquier interacción posterior, incluida una llamada, recibe Paso 2.

El estado se persiste y los eventos se reclaman antes de enviar para evitar
respuestas dobles durante reconexiones o despliegues.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
import re
import time

from telethon import TelegramClient, events
from telethon.tl import types

from interaction_state import PersistentInteractionState
from message_schema import load_message_file
from telegram_events import (
    missed_call_interaction,
    new_message_interaction,
    requested_call_interaction,
)
from telegram_dispatcher import TelegramInteractionDispatcher


BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = DATA_DIR / "audios"
MESSAGES_FILE = DATA_DIR / "messages.json"
DEFAULT_MESSAGES_FILE = BASE_DIR / "messages.json"
SESSION_FILE = str(DATA_DIR / "tg_session")
HEALTH_FILE = DATA_DIR / "tg_userbot_health.json"
AUTHORIZED_MARKER_FILE = DATA_DIR / "tg_session_authorized.json"
INTERACTION_STATE_FILE = DATA_DIR / "tg_interaction_state.json"
TELEGRAM_SEND_TIMEOUT_SECONDS = 20


def _load_env_file() -> None:
    """Carga únicamente las credenciales permitidas desde data/.env.local."""
    env_file = DATA_DIR / ".env.local"
    if not env_file.exists():
        return
    with env_file.open("r", encoding="utf-8") as file_handle:
        for raw_line in file_handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key in {"TG_API_ID", "TG_API_HASH", "TG_PHONE"} and value:
                os.environ[key] = value


_load_env_file()

API_ID = int(os.environ["TG_API_ID"]) if os.environ.get("TG_API_ID") else None
API_HASH = os.environ.get("TG_API_HASH")
PHONE = os.environ.get("TG_PHONE")
DEFAULT_LANGUAGE = os.environ.get("AUTOREPLY_DEFAULT_LANG", "es").lower()
if DEFAULT_LANGUAGE not in {"es", "en", "fr"}:
    DEFAULT_LANGUAGE = "es"

if not API_ID or not API_HASH:
    raise RuntimeError(
        "Credenciales de user bot no configuradas.\n"
        "Configura TG_API_ID, TG_API_HASH y TG_PHONE en el panel."
    )


def load_messages() -> dict:
    data = load_message_file(MESSAGES_FILE, DEFAULT_MESSAGES_FILE)
    result = {}
    for language, language_data in data.items():
        steps = language_data.get("steps", [])
        result[language] = {
            "steps": [
                (step.get("text", ""), step.get("audio", ""), bool(step.get("loop")))
                for step in steps
            ],
            "call": language_data.get(
                "call",
                {"text": "📞 Llamada recibida", "audio": ""},
            ),
        }
    return result


MESSAGES = load_messages()
interaction_state = PersistentInteractionState(
    INTERACTION_STATE_FILE,
    default_language=DEFAULT_LANGUAGE,
)


LANG_KEYWORDS = {
    "es": re.compile(
        r"\b(hola|gracias|por\s*favor|buenos\s*días|quiero|necesito|ayuda|habla|"
        r"precio|precios|tarifa|tarifas|reserva|reservas|foto|fotos|vídeo|vídeos|video|videos|"
        r"buenas|amigo|claro|vale|dale|listo|entiendo|puedes|hacer|"
        r"dónde|cuándo|cómo|cuál|quién|eso|esto|algo|nada|todo|más|menos|"
        r"está|estoy|estamos|están|tengo|tiene|tenemos|soy|eres|somos|son)\b",
        re.IGNORECASE,
    ),
    "en": re.compile(
        r"\b(hello|hi|thanks|thank\s*you|please|help|want|need|can\s*i|"
        r"price|prices|rate|rates|book|booking|photo|photos|video|videos|"
        r"yes|sure|fine|good|great|hey|would|could|should|"
        r"where|when|how|what|who|that|this|there|here|"
        r"is|are|am|have|has|do|does|did|will|may|might)\b",
        re.IGNORECASE,
    ),
    "fr": re.compile(
        r"\b(bonjour|merci|s'il\s*vous\s*plaît|aide|besoin|vouloir|"
        r"prix|tarif|tarifs|réservation|réserver|photo|photos|vidéo|vidéos|"
        r"oui|d'accord|bien|tres|peux|peut|où|quand|comment|quoi|qui|que|"
        r"est|suis|sommes|êtes|sont|ai|as|a|avons|avez|ont|"
        r"je|tu|il|elle|nous|vous|ils|elles|"
        r"ce|cet|cette|ces|mon|ton|son|ma|ta|sa)\b",
        re.IGNORECASE,
    ),
}
AMBIGUOUS = {"ok", "no", "si", "hey"}
LANG_MARKERS = {
    "es": re.compile(r"\b(español|castellano|hablo español|hablo espanol)\b", re.IGNORECASE),
    "en": re.compile(r"\b(english|speak english)\b", re.IGNORECASE),
    "fr": re.compile(r"\b(français|francais|parle français|parle francais)\b", re.IGNORECASE),
}


def detect_lang(text: str) -> str | None:
    scores = {"es": 0.0, "en": 0.0, "fr": 0.0}
    for language, pattern in LANG_KEYWORDS.items():
        for match in pattern.findall(text):
            if match.lower() not in AMBIGUOUS:
                scores[language] += 1.0
    for language, marker in LANG_MARKERS.items():
        if marker.search(text):
            scores[language] += 20
    if max(scores.values()) < 1:
        return None
    return max(scores, key=scores.get)


def load_messages_fresh() -> None:
    global MESSAGES
    try:
        MESSAGES = load_messages()
    except Exception:
        logging.exception("No se pudo recargar messages.json; se conserva la versión anterior")


def _language_data(language: str) -> dict:
    if language in MESSAGES:
        return MESSAGES[language]
    if DEFAULT_LANGUAGE in MESSAGES:
        return MESSAGES[DEFAULT_LANGUAGE]
    if "en" in MESSAGES:
        return MESSAGES["en"]
    return next(iter(MESSAGES.values()), {"steps": [], "call": {}})


def get_response_message(language: str, response_key: str) -> tuple[str, str]:
    language_data = _language_data(language)
    if response_key == "call":
        call_data = language_data.get("call", {})
        return call_data.get("text", ""), call_data.get("audio", "")

    steps = language_data.get("steps", [])
    if not steps:
        return "", ""
    index = 0 if response_key == "step1" else min(1, len(steps) - 1)
    text, audio, _loop = steps[index]
    return text, audio


client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
self_user_id: int | None = None


def write_health(ready: bool) -> None:
    """Publica un heartbeat mínimo, sin teléfono ni identidad de la cuenta."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary_file = HEALTH_FILE.with_suffix(".tmp")
    temporary_file.write_text(
        json.dumps({"ready": ready, "updated_at": time.time()}),
        encoding="utf-8",
    )
    os.replace(temporary_file, HEALTH_FILE)


def write_authorized_marker() -> None:
    temporary_file = AUTHORIZED_MARKER_FILE.with_suffix(".tmp")
    temporary_file.write_text(
        json.dumps({"authorized": True, "updated_at": time.time()}),
        encoding="utf-8",
    )
    os.replace(temporary_file, AUTHORIZED_MARKER_FILE)


async def heartbeat() -> None:
    while True:
        write_health(True)
        await asyncio.sleep(15)


async def send_response(chat_id: int, response_key: str, language: str) -> None:
    load_messages_fresh()
    message_text, audio_file = get_response_message(language, response_key)

    if message_text:
        try:
            await asyncio.wait_for(
                client.send_message(chat_id, message_text),
                timeout=TELEGRAM_SEND_TIMEOUT_SECONDS,
            )
        except Exception:
            logging.exception("Telegram text delivery failed")

    if audio_file:
        audio_path = AUDIO_DIR / audio_file
        if audio_path.exists():
            try:
                await asyncio.wait_for(
                    client.send_file(chat_id, str(audio_path), voice_note=False),
                    timeout=TELEGRAM_SEND_TIMEOUT_SECONDS,
                )
            except Exception:
                logging.exception("Telegram audio delivery failed")
        else:
            logging.error("Telegram audio file is missing: %s", audio_file)


telegram_dispatcher = TelegramInteractionDispatcher(interaction_state, send_response)


async def process_interaction(
    *,
    chat_id: int,
    event_id: str,
    kind: str,
    detected_language: str | None = None,
) -> None:
    decision = await telegram_dispatcher.dispatch(
        chat_id=chat_id,
        event_id=event_id,
        kind=kind,
        detected_language=detected_language,
    )
    if decision.duplicate:
        logging.info("Telegram duplicate interaction ignored")
        return
    if not decision.persisted:
        logging.warning("Telegram interaction is only stored in memory")
    logging.info(
        "Telegram interaction processed kind=%s phase=%s response=%s lang=%s",
        kind,
        decision.phase,
        decision.response_key,
        decision.language,
    )


@client.on(events.NewMessage(incoming=True))
async def handle_message(event) -> None:
    """Maneja una vez cada texto, voz, imagen, documento o multimedia."""
    interaction = new_message_interaction(
        event.message,
        chat_id=event.chat_id,
        is_private=event.is_private,
    )
    if not interaction:
        return
    await process_interaction(
        chat_id=interaction.contact_id,
        event_id=interaction.event_id,
        kind=interaction.kind,
        detected_language=detect_lang(interaction.text) if interaction.text else None,
    )


@client.on(events.Raw(types.UpdatePhoneCall))
async def handle_phone_call(update) -> None:
    """Cuenta solicitudes de llamadas reales, no notas de voz."""
    interaction = requested_call_interaction(update, self_user_id=self_user_id)
    if not interaction:
        return
    await process_interaction(
        chat_id=interaction.contact_id,
        event_id=interaction.event_id,
        kind=interaction.kind,
    )


@client.on(events.Raw(types.UpdateNewMessage))
async def handle_missed_call_service(update) -> None:
    """Fallback para una llamada perdida recibida después de reconectar."""
    interaction = missed_call_interaction(update, self_user_id=self_user_id)
    if not interaction:
        return
    await process_interaction(
        chat_id=interaction.contact_id,
        event_id=interaction.event_id,
        kind=interaction.kind,
    )


async def main() -> None:
    global self_user_id
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.INFO,
    )

    logging.info("Starting Telegram User Bot...")
    await client.connect()
    if not await client.is_user_authorized():
        AUTHORIZED_MARKER_FILE.unlink(missing_ok=True)
        raise RuntimeError(
            "La sesión de Telegram no está autorizada; completa la vinculación en el panel."
        )

    me = await client.get_me()
    self_user_id = me.id
    write_authorized_marker()
    logging.info("Telegram session authorized; user bot ready.")
    write_health(True)
    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        await client.run_until_disconnected()
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        try:
            HEALTH_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
