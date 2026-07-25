#!/bin/bash
# ─── Entrypoint: lanza los 3 procesos del Bot AutoReply ────────────────
# ─────────────────────────────────────────────────────────────────────────

echo "╔══════════════════════════════════════════════╗"
echo "║   Bot AutoReply — Iniciando servicios       ║"
echo "╚══════════════════════════════════════════════╝"

# ── 0. Instalar dependencias faltantes si es necesario ───────────────
pip install 'python-telegram-bot>=21.0' 2>/dev/null || true
if [ ! -d /app/node_modules/@whiskeysockets/baileys ]; then
    cd /app && npm ci --omit=dev --ignore-scripts
fi

# ── 0b. Preparar directorio de datos persistente ─────────────────────
mkdir -p /app/data/audios /app/data/wa_auth
# Copiar defaults si no existen en data/
[ -f /app/data/messages.json ] || cp /app/messages.json /app/data/messages.json
[ -f /app/data/.env.local ] || touch /app/data/.env.local
python /app/message_schema.py /app/data/messages.json /app/messages.json
# Sembrar sólo los audios que falten; nunca sobrescribir los personalizados.
for source_audio in /app/audios/*; do
    [ -f "$source_audio" ] || continue
    destination_audio="/app/data/audios/$(basename "$source_audio")"
    [ -f "$destination_audio" ] || cp "$source_audio" "$destination_audio"
done
# Corregir únicamente el M4A histórico conocido que tenía extensión .mp3.
# El migrador compara hashes, crea respaldo y no toca audios personalizados.
python /app/audio_migrations.py /app/data/audios /app/audios

# ── 1. Bot Telegram (User Bot - Telethon) ────────────────────────────
# Cargar credenciales desde .env.local si no están en environment
if [ -f /app/data/.env.local ]; then
    export $(grep -v '^#' /app/data/.env.local | grep -E '^TG_(API_ID|API_HASH|PHONE)=' | xargs)
fi

if [ -n "$TG_API_ID" ] && [ -n "$TG_API_HASH" ] \
   && [ -s /app/data/tg_session.session ] \
   && [ -s /app/data/tg_session_authorized.json ]; then
    echo "📱 Iniciando Bot Telegram (User Bot)..."
    nohup python bot.py > /tmp/bot_tg.log 2>&1 &
    echo $! > /app/data/tg_userbot.pid
    echo "  → PID: $!"
elif [ -n "$TG_API_ID" ] && [ -n "$TG_API_HASH" ]; then
    echo "⚠️  Credenciales de Telegram presentes, pero falta autorizar la sesión desde el panel."
else
    echo "⚠️  Credenciales de user bot no configuradas. Configura api_id, api_hash y phone desde el panel."
fi

# ── 1b. Bot Telegram (BotFather - Bot API) ───────────────────────────
# Cargar token desde .env.local si no está en environment
if [ -f /app/data/.env.local ]; then
    export $(grep -v '^#' /app/data/.env.local | grep -E '^AUTOREPLY_BOT_TOKEN=' | xargs)
fi

if [ -n "$AUTOREPLY_BOT_TOKEN" ]; then
    echo "🤖 Iniciando BotFather Bot..."
    nohup python botfather_bot.py > /tmp/bot_bf.log 2>&1 &
    echo $! > /app/data/botfather.pid
    echo "  → PID: $!"
else
    echo "⚠️  AUTOREPLY_BOT_TOKEN no configurado. El BotFather bot no arrancará."
fi

# ── 2. Bot WhatsApp ──────────────────────────────────────────────────
if [ -d "/app/data/wa_auth" ] && [ "$(ls -A /app/data/wa_auth 2>/dev/null)" ]; then
    echo "💬 Iniciando Bot WhatsApp..."
    nohup node wa_bot.mjs > /tmp/bot_wa.log 2>&1 &
    echo $! > /app/data/wa_bot.pid
    echo "  → PID: $!"
else
    echo "⚠️  WhatsApp no vinculado. Se vincula desde el panel."
fi

# ── 3. Panel Admin ───────────────────────────────────────────────────
echo "🖥️  Iniciando Panel Admin..."
cd /app
exec gunicorn -w 1 -b 0.0.0.0:5000 --access-logfile - --error-logfile - --timeout 120 app:app
