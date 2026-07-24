#!/bin/bash
# ─── Entrypoint: lanza los 3 procesos del Bot AutoReply ────────────────
# ─────────────────────────────────────────────────────────────────────────

echo "╔══════════════════════════════════════════════╗"
echo "║   Bot AutoReply — Iniciando servicios       ║"
echo "╚══════════════════════════════════════════════╝"

# ── 1. Bot Telegram ──────────────────────────────────────────────────
if [ -n "$AUTOREPLY_BOT_TOKEN" ] && [ "$AUTOREPLY_BOT_TOKEN" != "TU_TOKEN_AQUI" ]; then
    echo "📱 Iniciando Bot Telegram..."
    nohup python bot.py > /tmp/bot_tg.log 2>&1 &
    echo "  → PID: $!"
else
    echo "⚠️  AUTOREPLY_BOT_TOKEN no configurado. Se configura desde el panel."
fi

# ── 2. Bot WhatsApp ──────────────────────────────────────────────────
if [ -d "wa_auth" ] && [ "$(ls -A wa_auth 2>/dev/null)" ]; then
    echo "💬 Iniciando Bot WhatsApp..."
    nohup node wa_bot.mjs > /tmp/bot_wa.log 2>&1 &
    echo "  → PID: $!"
else
    echo "⚠️  WhatsApp no vinculado. Se vincula desde el panel."
fi

# ── 3. Panel Admin ───────────────────────────────────────────────────
echo "🖥️  Iniciando Panel Admin..."
cd /app
exec gunicorn -w 2 -b 0.0.0.0:5000 --access-logfile - --error-logfile - --timeout 120 app:app
