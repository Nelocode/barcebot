"""
Bot AutoReply Comercial — Telegram (User Bot via Telethon)
Flujo: mensaje inicial → msg1+audio → msg2+audio → loop msg3+audio
Idioma se detecta UNA VEZ al inicio y se queda fijo.
Timeout de 1 hora sin actividad resetea el estado.

User bot = sin /start, como un usuario normal.
Credenciales desde env vars o .env.local.
"""
import os
import re
import json
import time
import asyncio
import logging
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaDocument
from telethon.errors import SessionPasswordNeededError

# ── Config ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = DATA_DIR / "audios"
MESSAGES_FILE = DATA_DIR / "messages.json"
SESSION_FILE = str(DATA_DIR / "tg_session")  # Telethon session

RESET_TIMEOUT = 3600  # 1 hora

# Credenciales: de env vars o .env.local
API_ID = os.environ.get("TG_API_ID")
API_HASH = os.environ.get("TG_API_HASH")
PHONE = os.environ.get("TG_PHONE")

def _load_env_file():
    """Carga vars desde data/.env.local si no están en environment."""
    env_file = DATA_DIR / ".env.local"
    if not env_file.exists():
        return
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key in ("TG_API_ID", "TG_API_HASH", "TG_PHONE") and val:
                os.environ[key] = val

_load_env_file()

# Re-leer después de cargar .env.local
API_ID = int(os.environ["TG_API_ID"]) if os.environ.get("TG_API_ID") else None
API_HASH = os.environ.get("TG_API_HASH")
PHONE = os.environ.get("TG_PHONE")

if not API_ID or not API_HASH:
    raise RuntimeError(
        "Credenciales de user bot no configuradas.\n"
        "Configura TG_API_ID, TG_API_HASH, y TG_PHONE en el panel."
    )

# ── Mensajes ───────────────────────────────────────────────────────────
def load_messages() -> dict:
    with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    for lang, lang_data in data.items():
        steps = lang_data.get("steps", [])
        result[lang] = {
            "steps": [(s["text"], s["audio"]) for s in steps],
            "call": lang_data.get("call", {"text": "📞 Llamada recibida", "audio": ""})
        }
    return result

MESSAGES = load_messages()

# ── Estado por usuario ────────────────────────────────────────────────
user_state: dict[int, dict] = {}

# ── Detección de idioma ───────────────────────────────────────────────
LANG_KEYWORDS = {
    "es": re.compile(
        r"\b(hola|gracias|por\s*favor|buenos\s*días|quiero|necesito|ayuda|habla|"
        r"buenas|amigo|claro|vale|dale|listo|entiendo|puedes|hacer|"
        r"dónde|cuándo|cómo|cuál|quién|eso|esto|algo|nada|todo|más|menos|"
        r"está|estoy|estamos|están|tengo|tiene|tenemos|soy|eres|somos|son)\b",
        re.IGNORECASE,
    ),
    "en": re.compile(
        r"\b(hello|hi|thanks|thank\s*you|please|help|want|need|can\s*i|"
        r"yes|sure|fine|good|great|hey|would|could|should|"
        r"where|when|how|what|who|that|this|there|here|"
        r"is|are|am|have|has|do|does|did|will|may|might)\b",
        re.IGNORECASE,
    ),
    "fr": re.compile(
        r"\b(bonjour|merci|s'il\s*vous\s*plaît|aide|besoin|vouloir|"
        r"oui|d'accord|bien|tres|peux|peut|"
        r"où|quand|comment|quoi|qui|que|"
        r"est|suis|sommes|êtes|sont|ai|as|a|avons|avez|ont|"
        r"je|tu|il|elle|nous|vous|ils|elles|"
        r"ce|cet|cette|ces|mon|ton|son|ma|ta|sa)\b",
        re.IGNORECASE,
    ),
}

AMBIGUOUS = {"ok", "no", "si", "hey", "hi", "hello"}


def detect_lang(text: str) -> str:
    scores = {"es": 0, "en": 0, "fr": 0}
    for lang, pattern in LANG_KEYWORDS.items():
        matches = pattern.findall(text)
        for m in matches:
            if m.lower() not in AMBIGUOUS:
                scores[lang] += 1.0
    lang_markers = {
        "es": re.compile(r"\b(español|castellano|hablo español|hablo espanol)\b", re.IGNORECASE),
        "en": re.compile(r"\b(english|speak english)\b", re.IGNORECASE),
        "fr": re.compile(r"\b(français|francais|parle français|parle francais)\b", re.IGNORECASE),
    }
    for lang, marker in lang_markers.items():
        if marker.search(text):
            scores[lang] += 20
    if max(scores.values()) < 1:
        return "en"
    return max(scores, key=scores.get)


def is_expired(state: dict) -> bool:
    return time.time() - state.get("last_seen", 0) > RESET_TIMEOUT


def load_messages_fresh():
    """Recarga mensajes desde disco (para cambios desde el panel)."""
    global MESSAGES
    try:
        MESSAGES = load_messages()
    except Exception:
        pass


# ── Cliente Telethon ───────────────────────────────────────────────────
client = TelegramClient(SESSION_FILE, API_ID, API_HASH)


# ── Handlers ───────────────────────────────────────────────────────────

@client.on(events.NewMessage(incoming=True))
async def handle_message(event):
    """Maneja mensajes de texto entrantes (sin /start necesario)."""
    # Solo chats privados (no grupos/canales)
    if not event.is_private:
        return

    chat_id = event.chat_id
    text = (event.message.message or "").strip()
    if not text:
        return

    now = time.time()
    state = user_state.get(chat_id)

    # ── Comandos especiales ──
    if text.startswith("/start") or text.startswith("/"):
        return  # Ignorar comandos, sin respuesta

    # ── Nuevo ciclo o expired ──
    if state is None or is_expired(state):
        if state is not None:
            logging.info("[chat=%s] EXPIRED — new cycle", chat_id)
        load_messages_fresh()
        detected = detect_lang(text)
        state = {"lang": detected, "step": 0, "last_seen": now}
        user_state[chat_id] = state
        step_to_use = 0
    else:
        step_to_use = min(state["step"] + 1, 2)
        state["step"] = step_to_use
        state["last_seen"] = now

    lang = state["lang"]
    lang_data = MESSAGES.get(lang, MESSAGES["en"])
    msg_text, audio_file = lang_data["steps"][step_to_use]

    # Enviar texto
    await client.send_message(chat_id, msg_text)

    # Enviar audio
    audio_path = AUDIO_DIR / audio_file
    if audio_path.exists():
        await client.send_file(chat_id, str(audio_path), voice_note=False)

    logging.info(
        "[chat=%s lang=%s step=%s] %r → %r",
        chat_id, lang, step_to_use, text[:60], msg_text[:60],
    )


@client.on(events.NewMessage(incoming=True, func=lambda e: e.voice or e.video_note))
async def handle_media_call(event):
    """Responde a notas de voz / video (simula manejo de 'llamada')."""
    if not event.is_private:
        return

    chat_id = event.chat_id
    logging.info("[chat=%s] VOICE/VIDEO (call-like) received", chat_id)

    state = user_state.get(chat_id)
    if state and not is_expired(state):
        lang = state["lang"]
    else:
        lang = "en"

    lang_data = MESSAGES.get(lang, MESSAGES["en"])
    call_data = lang_data.get("call", {"text": "📞 Llamada recibida", "audio": ""})
    msg_text = call_data.get("text", "📞 Llamada recibida")
    audio_file = call_data.get("audio", "")

    try:
        await client.send_message(chat_id, msg_text)
    except Exception:
        pass

    if audio_file:
        audio_path = AUDIO_DIR / audio_file
        if audio_path.exists():
            try:
                await client.send_file(chat_id, str(audio_path), voice_note=False)
            except Exception:
                pass

    logging.info("[chat=%s lang=%s] CALL reply sent", chat_id, lang)


# ── Main ──────────────────────────────────────────────────────────────

async def main():
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.INFO,
    )

    logging.info("Starting Telegram User Bot...")
    await client.start(phone=PHONE or (lambda: os.environ.get("TG_CODE", "")))
    me = await client.get_me()
    logging.info("Logged in as @%s (%s %s)", me.username, me.first_name, me.last_name or "")
    logging.info("User bot ready — no /start needed.")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
