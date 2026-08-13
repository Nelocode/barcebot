"""
BotFather Bot — Telegram (Bot API)
Usa python-telegram-bot. Misma lógica de idioma y pasos que el user bot.
Requiere AUTOREPLY_BOT_TOKEN. Corre en paralelo con bot.py (Telethon).
"""
import os
import json
import time
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from language_detection import detect_language

# ── Config ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = DATA_DIR / "audios"
MESSAGES_FILE = DATA_DIR / "messages.json"
DEFAULT_MESSAGES_FILE = BASE_DIR / "messages.json"
RESET_TIMEOUT = 3600

BOT_TOKEN = os.environ.get("AUTOREPLY_BOT_TOKEN")

# ── Intentar cargar de .env.local si no está en environment ────────
def _load_env_file():
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
            if key == "AUTOREPLY_BOT_TOKEN" and val:
                os.environ[key] = val

_load_env_file()
BOT_TOKEN = os.environ.get("AUTOREPLY_BOT_TOKEN")  # Re-leer

if not BOT_TOKEN:
    logging.warning("AUTOREPLY_BOT_TOKEN not set. BotFather bot will not start.")
    # Don't crash — just log and exit gracefully

# ── Mensajes ───────────────────────────────────────────────────────────
def load_messages() -> dict:
    source = MESSAGES_FILE if MESSAGES_FILE.is_file() else DEFAULT_MESSAGES_FILE
    with open(source, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    for lang, lang_data in data.items():
        steps = lang_data.get("steps", [])
        result[lang] = {
            "steps": [(s["text"], s["audio"], s.get("loop", False)) for s in steps],
            "call": lang_data.get("call", {"text": "📞 Llamada recibida", "audio": ""})
        }
    return result

MESSAGES = load_messages()

# ── Estado por usuario ────────────────────────────────────────────────
user_state: dict[int, dict] = {}

def detect_lang(text: str) -> str | None:
    return detect_language(text)


def is_expired(state: dict) -> bool:
    return time.time() - state.get("last_seen", 0) > RESET_TIMEOUT


def update_user_language(
    state: dict | None,
    detected_language: str | None,
    *,
    now: float,
) -> tuple[dict, bool]:
    """Keep a fallback provisional until a message supplies evidence."""

    is_new = state is None or is_expired(state)
    if is_new:
        state = {
            "lang": detected_language or "es",
            "language_provisional": detected_language is None,
            "step": 0,
            "last_seen": now,
        }
    else:
        if detected_language and state.get("language_provisional") is True:
            state["lang"] = detected_language
            state["language_provisional"] = False
        state["last_seen"] = now
    return state, is_new


def load_messages_fresh():
    global MESSAGES
    try:
        MESSAGES = load_messages()
    except Exception:
        pass


# ── Handlers ──────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Silent start — no welcome, user's first message triggers lang detection."""
    chat_id = update.effective_chat.id
    if chat_id in user_state:
        del user_state[chat_id]


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = (update.message.text or update.message.caption or "").strip()
    detected = detect_lang(text) if text else None

    now = time.time()
    state = user_state.get(chat_id)
    had_state = state is not None

    state, is_new = update_user_language(state, detected, now=now)
    user_state[chat_id] = state

    if is_new:
        if had_state:
            logging.info("[BF chat=%s] EXPIRED — new cycle", chat_id)
        load_messages_fresh()
        step_to_use = 0
    else:
        step_to_use = min(state["step"] + 1, len(MESSAGES.get(state["lang"], MESSAGES["en"])["steps"]) - 1)
        state["last_seen"] = now

    lang = state["lang"]
    lang_data = MESSAGES.get(lang, MESSAGES["en"])
    msg_text, audio_file, is_loop = lang_data["steps"][step_to_use]

    if not is_loop:
        state["step"] = step_to_use

    await update.message.reply_text(msg_text)

    audio_path = AUDIO_DIR / audio_file
    if audio_path.exists():
        with open(audio_path, "rb") as f:
            await update.message.reply_audio(
                audio=f,
                title=f"AutoReply ({lang.upper()})",
                performer="AutoReply BotFather",
            )

    logging.info(
        "[BF chat=%s lang=%s step=%s] %r → %r",
        chat_id, lang, step_to_use, text[:60], msg_text[:60],
    )


async def handle_call(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Voice/video note treated as call."""
    chat_id = update.effective_chat.id
    logging.info("[BF chat=%s] VOICE/VIDEO received", chat_id)

    caption = (update.message.caption or "").strip()
    detected = detect_lang(caption) if caption else None
    state, _is_new = update_user_language(
        user_state.get(chat_id),
        detected,
        now=time.time(),
    )
    user_state[chat_id] = state
    lang = state["lang"]

    lang_data = MESSAGES.get(lang, MESSAGES["en"])
    call_data = lang_data.get("call", {"text": "📞 Llamada recibida", "audio": ""})
    msg_text = call_data.get("text", "📞 Llamada recibida")
    audio_file = call_data.get("audio", "")

    try:
        await update.message.reply_text(msg_text)
    except Exception:
        pass

    if audio_file:
        audio_path = AUDIO_DIR / audio_file
        if audio_path.exists():
            with open(audio_path, "rb") as f:
                try:
                    await update.message.reply_audio(
                        audio=f,
                        title=f"AutoReply ({lang.upper()}) - Call",
                        performer="AutoReply BotFather",
                    )
                except Exception:
                    pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error("[BF] Error: %s", context.error)


# ── Main ──────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        format="%(asctime)s [BF %(levelname)s] %(message)s",
        level=logging.INFO,
    )

    if not BOT_TOKEN:
        logging.warning("No AUTOREPLY_BOT_TOKEN — BotFather bot exiting.")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    content_filter = (
        filters.TEXT
        | filters.PHOTO
        | filters.ANIMATION
        | filters.VIDEO
        | filters.Document.ALL
        | filters.AUDIO
        | filters.Sticker.ALL
    ) & ~filters.COMMAND
    app.add_handler(MessageHandler(content_filter, handle_message))
    app.add_handler(MessageHandler(filters.VOICE | filters.VIDEO_NOTE, handle_call))
    app.add_error_handler(error_handler)

    logging.info("BotFather bot starting... (token=%s...)", BOT_TOKEN[:8])
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
