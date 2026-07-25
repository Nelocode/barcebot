/**
 * WhatsApp Bot — AutoReply Comercial
 * Usa Baileys (protocolo WhatsApp Web, sin API de Meta)
 * Misma lógica de messages.json, detección de idioma, y estado
 */
import makeWASocket, { useMultiFileAuthState, DisconnectReason } from '@whiskeysockets/baileys';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { Boom } from '@hapi/boom';
import QRCode from 'qrcode';
import { createWhatsAppCallHandler } from './wa_call_handler.mjs';
import { createWhatsAppCallHealth } from './wa_call_health.mjs';
import { PersistentInteractionState } from './interaction_state.mjs';
import { createWhatsAppMessageHandler } from './wa_message_handler.mjs';
import { KeyedSerialQueue } from './keyed_serial_queue.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE_DIR = path.resolve(process.env.BOT_DIR || __dirname);
const AUDIO_DIR = path.join(BASE_DIR, 'data', 'audios');
const MESSAGES_FILE = path.join(BASE_DIR, 'data', 'messages.json');
const AUTH_DIR = path.join(BASE_DIR, 'data', 'wa_auth');
const CALL_HEALTH_FILE = path.join(BASE_DIR, 'data', 'wa_call_health.json');
const INTERACTION_STATE_FILE = path.join(BASE_DIR, 'data', 'wa_interaction_state.json');
const configuredDefaultLanguage = String(process.env.AUTOREPLY_DEFAULT_LANG || 'es').toLowerCase();
const DEFAULT_LANGUAGE = ['es', 'en', 'fr'].includes(configuredDefaultLanguage)
  ? configuredDefaultLanguage
  : 'es';
const callHealth = createWhatsAppCallHealth({ filePath: CALL_HEALTH_FILE, logger: console });
const interactionState = new PersistentInteractionState({
  filePath: INTERACTION_STATE_FILE,
  defaultLanguage: DEFAULT_LANGUAGE,
  logger: console,
});
// El reclamo global conserva el orden exacto de llegada antes de cualquier
// resolución LID/PN. La entrega sigue aislada por contacto.
const interactionClaimQueue = new KeyedSerialQueue();
const deliveryQueue = new KeyedSerialQueue();
const RECONNECT_DELAY_MS = 2_000;

let activeSocket = null;
let reconnectTimer = null;
let shuttingDown = false;

function scheduleReconnect() {
  if (shuttingDown || reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    if (shuttingDown) return;
    startBot().catch(() => {
      console.error('[WA] Reconnection setup failed');
      scheduleReconnect();
    });
  }, RECONNECT_DELAY_MS);
}

// ── Cargar mensajes ──
function loadMessages() {
  const raw = fs.readFileSync(MESSAGES_FILE, 'utf-8');
  const data = JSON.parse(raw);
  const result = {};
  for (const [lang, langData] of Object.entries(data)) {
    if (!Array.isArray(langData.steps) || langData.steps.length < 2) {
      throw new Error(`[WA] El idioma ${lang} necesita Paso 1 y Paso 2`);
    }
    result[lang] = {
      steps: langData.steps.map(s => ({ text: s.text, audio: s.audio, loop: s.loop || false })),
      call: langData.call || { text: '📞 Llamada recibida', audio: '' }
    };
  }
  return result;
}

let MESSAGES = loadMessages();

// ── Watch messages.json para recargar en caliente (cuando admin panel guarda) ──
fs.watchFile(MESSAGES_FILE, () => {
  try {
    MESSAGES = loadMessages();
    console.log(`[WA] messages.json recargado — ${Object.keys(MESSAGES).length} idiomas`);
  } catch (e) {
    console.error('[WA] Error recargando messages.json:', e.message);
  }
});

// ── Detección de idioma (misma lógica que bot.py) ──
const LANG_PATTERNS = {
  es: /\b(hola|gracias|por\s*favor|buenos\s*días|quiero|necesito|ayuda|habla|precio|precios|tarifa|tarifas|reserva|reservas|foto|fotos|vídeo|vídeos|video|videos|buenas|amigo|claro|vale|dale|listo|entiendo|puedes|hacer|dónde|cuándo|cómo|cuál|quién|eso|esto|algo|nada|todo|más|menos|está|estoy|estamos|están|tengo|tiene|tenemos|soy|eres|somos|son)\b/gi,
  en: /\b(hello|hi|thanks|thank\s*you|please|help|want|need|can\s*i|price|prices|rate|rates|book|booking|photo|photos|video|videos|yes|sure|fine|good|great|hey|would|could|should|where|when|how|what|who|that|this|there|here|is|are|am|have|has|do|does|did|will|may|might)\b/gi,
  fr: /\b(bonjour|merci|s'il\s*vous\s*plaît|aide|besoin|vouloir|prix|tarif|tarifs|réservation|réserver|photo|photos|vidéo|vidéos|oui|d'accord|bien|tres|peux|peut|où|quand|comment|quoi|qui|que|est|suis|sommes|êtes|sont|ai|as|a|avons|avez|ont|je|tu|il|elle|nous|vous|ils|elles|ce|cet|cette|ces|mon|ton|son|ma|ta|sa)\b/gi,
};
const LANG_MARKERS = {
  es: /\b(español|castellano|hablo español|hablo espanol)\b/i,
  en: /\b(english|speak english)\b/i,
  fr: /\b(français|francais|parle français|parle francais)\b/i,
};
const AMBIGUOUS = new Set(['ok', 'no', 'si', 'hey']);

function detectLang(text) {
  const scores = { es: 0, en: 0, fr: 0 };

  for (const [lang, pattern] of Object.entries(LANG_PATTERNS)) {
    const matches = text.match(pattern);
    if (matches) {
      for (const m of matches) {
        if (!AMBIGUOUS.has(m.toLowerCase())) {
          scores[lang] += 1;
        }
      }
    }
  }

  // Markers explícitos
  for (const [lang, marker] of Object.entries(LANG_MARKERS)) {
    if (marker.test(text)) {
      scores[lang] += 20;
    }
  }

  if (Math.max(...Object.values(scores)) < 1) return null;
  return Object.entries(scores).sort((a, b) => b[1] - a[1])[0][0];
}

// ── Estado por usuario ──
// ── Obtener mensaje para un paso ──
function getMessage(lang, step) {
  const data = MESSAGES[lang] || MESSAGES['en'];
  const idx = Math.min(step, data.steps.length - 1);
  return data.steps[idx];
}

function getCallMessage(lang) {
  const data = MESSAGES[lang] || MESSAGES['en'];
  return data.call || { text: '📞 Llamada recibida', audio: '' };
}

function getResponseMessage(lang, responseKey) {
  if (responseKey === 'call') return getCallMessage(lang);
  return getMessage(lang, responseKey === 'step1' ? 0 : 1);
}

// ── Leer archivo de audio como buffer ──
function readAudio(filename) {
  const audioPath = path.join(AUDIO_DIR, filename);
  if (fs.existsSync(audioPath)) {
    return fs.readFileSync(audioPath);
  }
  return null;
}

// ── Iniciar conexión WhatsApp ──
async function startBot() {
  // Crear directorio de autenticación si no existe
  if (!fs.existsSync(AUTH_DIR)) {
    fs.mkdirSync(AUTH_DIR, { recursive: true });
  }

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

  callHealth.record({ type: 'connection', state: 'connecting' });

  const sock = makeWASocket({
    auth: state,
    syncFullHistory: false,
    markOnlineOnConnect: true,
    browser: ['AutoReply Bot', 'Chrome', '120.0'],
  });
  activeSocket = sock;

  // Observe only that a raw call stanza arrived. Never persist its payload.
  if (typeof sock.ws?.on === 'function') {
    sock.ws.on('CB:call', () => callHealth.record({ type: 'raw_call' }));
    callHealth.record({ type: 'raw_listener', state: 'registered' });
  } else {
    callHealth.record({ type: 'raw_listener', state: 'unavailable' });
  }

  // Register immediately: call events are not buffered by Baileys.
  const handleCallBatch = createWhatsAppCallHandler({
    rejectCall: (callId, callFrom) => sock.rejectCall(callId, callFrom),
    sendMessage: (jid, content) => sock.sendMessage(jid, content),
    getCallMessage,
    getResponseMessage,
    routeInteraction: details => interactionState.register(details),
    resolveContactId: async (jid) => {
      if (!jid.endsWith('@lid') && !jid.endsWith('@hosted.lid')) return jid;
      return sock.signalRepository?.lidMapping?.getPNForLID
        ? (await sock.signalRepository.lidMapping.getPNForLID(jid)) || jid
        : jid;
    },
    serializeClaim: operation => interactionClaimQueue.run('all-inbound', operation),
    serializeInteraction: (contactId, operation) => deliveryQueue.run(contactId, operation),
    readAudio,
    logger: console,
    onCallMetric: callHealth.record,
  });
  sock.ev.on('call', handleCallBatch);
  callHealth.record({ type: 'listener_registered' });

  // ── Guardar credenciales cuando se actualicen ──
  sock.ev.on('creds.update', saveCreds);

  // ── Manejar conexión / reconexión ──
  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      // Guardar QR como imagen PNG para el panel web
      const qrPath = path.join(BASE_DIR, 'wa_qr.png');
      QRCode.toFile(qrPath, qr, { type: 'png', width: 400, margin: 2 }, (err) => {
        if (err) console.error('[WA] Error guardando QR:', err.message);
        else console.log(`[WA] QR guardado en ${qrPath}`);
      });
      console.log('\n╔══════════════════════════════════════════════╗');
      console.log('║      ESCANEA EL QR EN EL PANEL ADMIN      ║');
      console.log('║   http://localhost:5000                    ║');
      console.log('╚══════════════════════════════════════════════╝\n');
    }

    if (connection === 'close') {
      if (activeSocket !== sock) return;
      activeSocket = null;
      callHealth.record({ type: 'connection', state: 'closed' });
      const shouldReconnect = (lastDisconnect?.error instanceof Boom)
        ? lastDisconnect.error.output.statusCode !== DisconnectReason.loggedOut
        : true;

      console.log(`[WA] Conexión cerrada. Reconnect: ${shouldReconnect}`);

      if (shouldReconnect) {
        scheduleReconnect();
      } else {
        console.log('[WA] Sesión cerrada. Vuelve a escanear QR borrando wa_auth/');
      }
    }

    if (connection === 'open') {
      if (activeSocket !== sock) return;
      callHealth.record({ type: 'connection', state: 'open' });
      console.log('[WA] Connected');
    }
  });

  // Un único manejador cuenta texto y cualquier multimedia en el mismo estado
  // que las llamadas. Los eventos de sincronización y control se descartan.
  const handleMessageBatch = createWhatsAppMessageHandler({
    sendMessage: (jid, content) => sock.sendMessage(jid, content),
    routeInteraction: details => interactionState.register(details),
    getResponseMessage,
    readAudio,
    detectLanguage: detectLang,
    resolvePnForLid: async (lid) => (
      sock.signalRepository?.lidMapping?.getPNForLID
        ? sock.signalRepository.lidMapping.getPNForLID(lid)
        : null
    ),
    serializeClaim: operation => interactionClaimQueue.run('all-inbound', operation),
    serializeInteraction: (contactId, operation) => deliveryQueue.run(contactId, operation),
    logger: console,
  });
  sock.ev.on('messages.upsert', handleMessageBatch);

}

// ── Main ──
console.log('🚀 WhatsApp Bot AutoReply iniciando...');
console.log(`📁 Directorio: ${BASE_DIR}`);
console.log(`📁 Auth: ${AUTH_DIR}`);
console.log(`🔑 Escanea el QR con tu WhatsApp`);
console.log('────────────────────────────────────────\n');

function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = null;
  callHealth.record({ type: 'connection', state: 'closed' });
  console.log(`[WA] Shutting down (${signal})`);
  try {
    activeSocket?.end(new Error(signal));
  } catch {
    // Process shutdown must continue even if the socket is already closed.
  }
  process.exit(0);
}

process.once('SIGINT', () => shutdown('SIGINT'));
process.once('SIGTERM', () => shutdown('SIGTERM'));

startBot().catch(() => {
  console.error('[WA] Initial connection setup failed');
  scheduleReconnect();
});
