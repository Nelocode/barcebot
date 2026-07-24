"""
Bot AutoReply Comercial — Telegram
Flujo: mensaje inicial → msg1+audio → msg2+audio → loop msg3+audio
Idioma se detecta UNA VEZ al inicio y se queda fijo.
Timeout de 1 hora sin actividad resetea el estado.
"""

import os
import re
import json
import time
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ── Config ────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("AUTOREPLY_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Set AUTOREPLY_BOT_TOKEN env var")

AUDIO_DIR = Path(__file__).parent / "data" / "audios"
RESET_TIMEOUT = 3600  # 1 hora en segundos

# ── Mensajes (desde JSON externo) ─────────────────────────────────────
MESSAGES_FILE = Path(__file__).parent / "data" / "messages.json"

def load_messages() -> dict:
    """Carga mensajes desde messages.json. Cada idioma tiene steps con text y audio, y opcionalmente 'call'."""
    with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Convertir a formato interno
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
# { chat_id: {"lang": "es", "step": 0, "last_seen": 1234567890} }
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

# Palabras que existen en varios idiomas — se ignoran para detección
AMBIGUOUS = {"ok", "no", "si", "hey", "hi", "hello"}


def detect_lang(text: str) -> str:
    """Detect language from user message. Solo se usa en el primer mensaje.
    Returns 'es', 'en', or 'fr'. Defaults to 'en'."""
    scores = {"es": 0, "en": 0, "fr": 0}

    for lang, pattern in LANG_KEYWORDS.items():
        matches = pattern.findall(text)
        for m in matches:
            if m.lower() not in AMBIGUOUS:
                scores[lang] += 1.0

    # Explicit language markers
    lang_markers = {
        "es": re.compile(r"\b(español|castellano|hablo español|hablo espanol)\b", re.IGNORECASE),
        "en": re.compile(r"\b(english|speak english)\b", re.IGNORECASE),
        "fr": re.compile(r"\b(français|francais|parle français|parle francais)\b", re.IGNORECASE),
    }
    for lang, marker in lang_markers.items():
        if marker.search(text):
            scores[lang] += 20

    if max(scores.values()) < 1:
        return "en"  # fallback

    return max(scores, key=scores.get)


def is_expired(state: dict) -> bool:
    """Check if state has expired (more than RESET_TIMEOUT since last msg)."""
    return time.time() - state.get("last_seen", 0) > RESET_TIMEOUT


# ── Handlers ──────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in user_state:
        del user_state[chat_id]
    # Silent start — no welcome message.
    # Language detection happens on the user's first real message.
    # Deep link: t.me/hmsg_bot?start=silent


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if not text:
        return

    now = time.time()
    state = user_state.get(chat_id)

    # ── Nuevo ciclo o expired ──
    if state is None or is_expired(state):
        if state is not None:
            logging.info("[chat=%s] EXPIRED (%.0fs idle) — new cycle", chat_id, now - state["last_seen"])
        detected = detect_lang(text)
        state = {"lang": detected, "step": 0, "last_seen": now}
        user_state[chat_id] = state
        step_to_use = 0  # msg1

    # ── Ciclo existente — idioma FIJO, solo avanza step ──
    else:
        step_to_use = min(state["step"] + 1, 2)
        state["step"] = step_to_use
        state["last_seen"] = now

    lang = state["lang"]
    lang_data = MESSAGES.get(lang, MESSAGES["en"])
    msg_text, audio_file = lang_data["steps"][step_to_use]

    # Send text
    await update.message.reply_text(msg_text)

    # Send audio
    audio_path = AUDIO_DIR / audio_file
    if audio_path.exists():
        with open(audio_path, "rb") as f:
            await update.message.reply_audio(
                audio=f,
                title=f"Bot AutoReply ({lang.upper()})",
                performer="AutoReply Bot",
            )

    logging.info(
        "[chat=%s lang=%s step=%s] %r → %r",
        chat_id, lang, step_to_use, text[:60], msg_text[:60],
    )


async def handle_call(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde cuando alguien intenta llamar por Telegram."""
    chat_id = update.effective_chat.id
    logging.info("[chat=%s] CALL received", chat_id)

    # Detectar idioma del usuario (por último estado conocido o mensaje)
    state = user_state.get(chat_id)
    if state and not is_expired(state):
        lang = state["lang"]
    else:
        lang = "en"  # Default si no hay historial

    lang_data = MESSAGES.get(lang, MESSAGES["en"])
    call_data = lang_data.get("call", {"text": "📞 Llamada recibida", "audio": ""})
    msg_text = call_data.get("text", "📞 Llamada recibida")
    audio_file = call_data.get("audio", "")

    # Enviar texto
    try:
        await update.message.reply_text(msg_text)
    except:
        pass  # Puede que no haya chat activo

    # Enviar audio si existe
    if audio_file:
        audio_path = AUDIO_DIR / audio_file
        if audio_path.exists():
            with open(audio_path, "rb") as f:
                try:
                    await update.message.reply_audio(
                        audio=f,
                        title=f"Bot AutoReply ({lang.upper()}) - Llamada",
                        performer="AutoReply Bot",
                    )
                except:
                    pass

    logging.info("[chat=%s lang=%s] CALL reply sent: %s", chat_id, lang, msg_text[:60])


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error("Exception while handling an update: %s", context.error)


# ── Main ──────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.INFO,
    )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE | filters.VIDEO_NOTE | filters.ChatAction, handle_call))
    app.add_error_handler(error_handler)

    logging.info("Bot AutoReply starting... (token=%s...)", BOT_TOKEN[:8])
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
