#!/bin/bash
# ─── Entrypoint: lanza los 3 procesos del Bot AutoReply ────────────────
# Panel Admin (Flask/Gunicorn), Bot Telegram, Bot WhatsApp
# ─────────────────────────────────────────────────────────────────────────

set -e

echo "╔══════════════════════════════════════════════╗"
echo "║   Bot AutoReply — Iniciando servicios       ║"
echo "╚══════════════════════════════════════════════╝"

# ── 1. Bot Telegram ──────────────────────────────────────────────────
if [ -n "$AUTOREPLY_BOT_TOKEN" ] && [ "$AUTOREPLY_BOT_TOKEN" != "TU_TOKEN_AQUI" ]; then
    echo "📱 Iniciando Bot Telegram..."
    python bot.py > /tmp/bot_tg.log 2>&1 &
    BOT_TG_PID=$!
    echo "  → PID: $BOT_TG_PID"
else
    echo "⚠️  AUTOREPLY_BOT_TOKEN no configurado. Bot Telegram omitido."
    echo "   Configúralo desde el panel en ⚙️ Configurar > Telegram"
fi

# ── 2. Bot WhatsApp ──────────────────────────────────────────────────
if [ -d "wa_auth" ] && [ "$(ls -A wa_auth 2>/dev/null)" ]; then
    echo "💬 Iniciando Bot WhatsApp..."
    node wa_bot.mjs > /tmp/bot_wa.log 2>&1 &
    BOT_WA_PID=$!
    echo "  → PID: $BOT_WA_PID"
else
    echo "⚠️  WhatsApp no vinculado. El QR aparecerá en el panel."
    echo "   Ve a ⚙️ Configurar > WhatsApp y haz click en 'Vincular WhatsApp'"
fi

# ── 3. Panel Admin ───────────────────────────────────────────────────
echo "🖥️  Iniciando Panel Admin (Gunicorn)..."
exec gunicorn -w 2 -b 0.0.0.0:5000 --access-logfile - --error-logfile - app:app
