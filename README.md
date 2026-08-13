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

### Modo de prueba de conversaciones

El panel incluye un modo de prueba reversible para repetir el flujo completo con
el mismo celular:

1. Vincula y confirma los canales desde el navegador administrador.
2. Para Telegram, o si quieres usar el atajo de actividad reciente, envía una
   interacción desde el celular de prueba para que sea la conversación más reciente.
3. Activa **Modo de prueba de conversaciones** en el panel.
4. Elige detección automática, español, inglés o francés. Seleccionar un idioma
   permite probar una llamada como primera interacción, aunque no contenga texto.
5. Reinicia la conversación más reciente de Telegram, WhatsApp o ambas. En
   WhatsApp también puedes indicar directamente el número internacional del
   celular cliente, incluso antes de su primera interacción.
6. La siguiente interacción de ese celular empezará nuevamente en **Paso 1** y
   usará el idioma seleccionado o lo detectará desde el próximo texto.

El reinicio no desvincula cuentas ni elimina credenciales. Antes de cambiar un
archivo existente, conserva una copia en `/app/data/test_mode_backups`. El número
específico sólo se normaliza en memoria para calcular los mismos identificadores
hash que usa WhatsApp: nunca se escribe en texto legible ni se devuelve al
navegador. El atajo de
"conversación más reciente" no debe usarse mientras haya tráfico real de otros
clientes.

### Salud operativa de WhatsApp

Las respuestas de WhatsApp aplican pausas acotadas de lectura y preparación,
presencia `composing`/`recording`, límites globales de frecuencia, backoff y un
circuit breaker. El panel muestra un indicador de riesgo operativo sin guardar
teléfonos, JID, mensajes ni errores sin filtrar. Un `403` pausa los envíos hasta
que un administrador confirme explícitamente la revisión; un `429` activa un
enfriamiento temporal. Estas medidas reducen ráfagas y ayudan a responder ante
fallos, pero no garantizan ni prometen influir en decisiones de Meta.

Los valores predeterminados son conservadores y pueden ajustarse mediante:
`WA_PRESENCE_ENABLED`, `WA_READ_RECEIPTS_ENABLED`, `WA_READ_DELAY_MIN_MS`,
`WA_READ_DELAY_MAX_MS`, `WA_TEXT_DELAY_MIN_MS`, `WA_TEXT_DELAY_MAX_MS`,
`WA_TEXT_MS_PER_CHAR`, `WA_AUDIO_DELAY_MIN_MS`, `WA_AUDIO_DELAY_MAX_MS`,
`WA_UX_JITTER_RATIO`, `WA_MIN_SEND_INTERVAL_MS`,
`WA_MAX_SENDS_PER_MINUTE`, `WA_MAX_PENDING_SENDS`,
`WA_QUEUE_WAIT_TIMEOUT_MS`, `WA_AUXILIARY_TIMEOUT_MS`,
`WA_BACKOFF_BASE_MS`, `WA_BACKOFF_MAX_MS`,
`WA_CIRCUIT_FAILURE_THRESHOLD`, `WA_CIRCUIT_FAILURE_WINDOW_MS`,
`WA_CIRCUIT_OPEN_MS`, `WA_FORBIDDEN_CIRCUIT_OPEN_MS`,
`WA_SAFE_SEND_TIMEOUT_MS`, `WA_RECONNECT_BASE_MS`, `WA_RECONNECT_MAX_MS` y
`WA_RECONNECT_STABLE_MS`.

---

## 🛠️ Arquitectura Técnica

- **Base Container:** Python 3.12 + Node.js 20 + FFmpeg.
- **Panel Web:** Flask + Gunicorn corriendo en el puerto 5000.
- **Bot WhatsApp:** Node.js (Baileys v7).
- **Bot Telegram:** Python (Telethon / python-telegram-bot).
- **Orquestación:** `entrypoint.sh` inicia todos los procesos de forma paralela y resiliente.
