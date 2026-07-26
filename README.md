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
2. Envía una interacción desde el celular de prueba para que sea la conversación
   más reciente del canal.
3. Activa **Modo de prueba de conversaciones** en el panel.
4. Elige detección automática, español, inglés o francés. Seleccionar un idioma
   permite probar una llamada como primera interacción, aunque no contenga texto.
5. Reinicia la conversación más reciente de Telegram, WhatsApp o ambas.
6. La siguiente interacción de ese celular empezará nuevamente en **Paso 1** y
   usará el idioma seleccionado o lo detectará desde el próximo texto.

El reinicio no desvincula cuentas ni elimina credenciales. Antes de cambiar el
estado, conserva una copia en `/app/data/test_mode_backups`. Como el sistema no
guarda números de clientes en claro, esta herramienta identifica la conversación
por su actividad más reciente; no debe usarse mientras haya tráfico real de otros
clientes.

---

## 🛠️ Arquitectura Técnica

- **Base Container:** Python 3.12 + Node.js 20 + FFmpeg.
- **Panel Web:** Flask + Gunicorn corriendo en el puerto 5000.
- **Bot WhatsApp:** Node.js (Baileys v7).
- **Bot Telegram:** Python (Telethon / python-telegram-bot).
- **Orquestación:** `entrypoint.sh` inicia todos los procesos de forma paralela y resiliente.
