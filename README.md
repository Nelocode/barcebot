# Bot AutoReply — Barcelona

Bot de respuestas automáticas comerciales para **WhatsApp** y **Telegram**, con un **Panel Web de Administración** integrado.

---

## 🚀 Despliegue en Easypanel

Este repositorio incluye una configuración lista para desplegar en **Easypanel** mediante Docker.

### Pasos para desplegar en Easypanel:

1. **Crear una nueva aplicación:**
   - En tu panel de Easypanel, crea un nuevo servicio de tipo **App**.
   - Asigna un nombre a tu proyecto (ej. `barcebot`).

2. **Configurar la Fuente (Source):**
   - **Build Method:** `Dockerfile`
   - **Repository:** `https://github.com/Nelocode/barcebot.git`
   - **Branch:** `main`

3. **Configurar Puerto y Red:**
   - **Port:** `5000` (Easypanel redirigirá el tráfico HTTP/HTTPS a este puerto).

4. **Configurar Volumen Persistente (Persistencia de Datos):**
   - **Mount Path:** `/app/data`
   - *¿Por qué es necesario?* En `/app/data` se guardan la sesión de WhatsApp (`wa_auth`), credenciales de Telegram, estado de interacciones, configuraciones y audios personalizados. Sin este volumen, la sesión de WhatsApp se desconectará al reiniciar la aplicación.

5. **Variables de Entorno (Opcionales):**
   - `AUTOREPLY_BOT_TOKEN`: Token de Telegram BotFather (si aplica).
   - `TG_API_ID` y `TG_API_HASH`: Credenciales de Telegram UserBot (si aplica).
   *(Nota: También puedes ingresar tus credenciales directamente desde el Panel Web una vez desplegado).*

6. **Desplegar:**
   - Haz clic en **Deploy**. Easypanel construirá la imagen Docker usando el `Dockerfile` y ejecutará los servicios automáticamente.

---

## 🖥️ Uso del Panel de Administración

Una vez desplegado:
1. Accede a la URL proporcionada por Easypanel (o `http://<IP_SERVIDOR>:5000`).
2. **WhatsApp:** Escanea el código QR proyectado en el panel para vincular la cuenta.
3. **Configuraciones:** Gestiona los mensajes en tiempo real, audios pregrabados y parámetros del bot.

---

## 🛠️ Arquitectura Técnica

- **Base Container:** Python 3.12 + Node.js 20 + FFmpeg.
- **Panel Web:** Flask + Gunicorn corriendo en el puerto 5000.
- **Bot WhatsApp:** Node.js (Baileys v7).
- **Bot Telegram:** Python (Telethon / python-telegram-bot).
- **Orquestación:** `entrypoint.sh` inicia todos los procesos de forma paralela y resiliente.
