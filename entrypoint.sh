#!/bin/bash
# ─── Entrypoint: lanza los 3 procesos del Bot AutoReply ────────────────
# ─────────────────────────────────────────────────────────────────────────

echo "╔══════════════════════════════════════════════╗"
echo "║   Bot AutoReply — Iniciando servicios       ║"
echo "╚══════════════════════════════════════════════╝"

# ── 0. Preparar directorio de datos persistente ──────────────────────
mkdir -p /app/data/audios /app/data/wa_auth
# Copiar defaults si no existen en data/
[ -f /app/data/messages.json ] || cp /app/messages.json /app/data/messages.json
[ -f /app/data/.env.local ] || touch /app/data/.env.local
# Copiar audios por defecto si data/audios está vacío
if [ -z "$(ls -A /app/data/audios 2>/dev/null)" ]; then
    cp -r /app/audios/* /app/data/audios/ 2>/dev/null || true
fi

# ── 1. Bot Telegram ──────────────────────────────────────────────────
# Cargar credenciales desde .env.local si no están en environment
if [ -f /app/data/.env.local ]; then
    export $(grep -v '^#' /app/data/.env.local | grep -E '^TG_(API_ID|API_HASH|PHONE)=' | xargs)
fi

if [ -n "$TG_API_ID" ] && [ -n "$TG_API_HASH" ]; then
    echo "📱 Iniciando Bot Telegram (User Bot)..."
    nohup python bot.py > /tmp/bot_tg.log 2>&1 &
    echo "  → PID: $!"
else
    echo "⚠️  Credenciales de user bot no configuradas. Configura api_id, api_hash y phone desde el panel."
fi

# ── 2. Bot WhatsApp ──────────────────────────────────────────────────
if [ -d "/app/data/wa_auth" ] && [ "$(ls -A /app/data/wa_auth 2>/dev/null)" ]; then
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
