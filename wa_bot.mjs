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

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE_DIR = path.resolve(process.env.BOT_DIR || __dirname);
const AUDIO_DIR = path.join(BASE_DIR, 'data', 'audios');
const MESSAGES_FILE = path.join(BASE_DIR, 'data', 'messages.json');
const AUTH_DIR = path.join(BASE_DIR, 'data', 'wa_auth');
const RESET_TIMEOUT = 3600 * 1000; // 1 hora en ms

// ── Cargar mensajes ──
function loadMessages() {
  const raw = fs.readFileSync(MESSAGES_FILE, 'utf-8');
  const data = JSON.parse(raw);
  const result = {};
  for (const [lang, langData] of Object.entries(data)) {
    result[lang] = {
      steps: langData.steps.map(s => ({ text: s.text, audio: s.audio })),
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
  es: /\b(hola|gracias|por\s*favor|buenos\s*días|quiero|necesito|ayuda|habla|buenas|amigo|claro|vale|dale|listo|entiendo|puedes|hacer|dónde|cuándo|cómo|cuál|quién|eso|esto|algo|nada|todo|más|menos|está|estoy|estamos|están|tengo|tiene|tenemos|soy|eres|somos|son)\b/gi,
  en: /\b(hello|hi|thanks|thank\s*you|please|help|want|need|can\s*i|yes|sure|fine|good|great|hey|would|could|should|where|when|how|what|who|that|this|there|here|is|are|am|have|has|do|does|did|will|may|might)\b/gi,
  fr: /\b(bonjour|merci|s'il\s*vous\s*plaît|aide|besoin|vouloir|oui|d'accord|bien|tres|peux|peut|où|quand|comment|quoi|qui|que|est|suis|sommes|êtes|sont|ai|as|a|avons|avez|ont|je|tu|il|elle|nous|vous|ils|elles|ce|cet|cette|ces|mon|ton|son|ma|ta|sa)\b/gi,
};
const LANG_MARKERS = {
  es: /\b(español|castellano|hablo español|hablo espanol)\b/i,
  en: /\b(english|speak english)\b/i,
  fr: /\b(français|francais|parle français|parle francais)\b/i,
};
const AMBIGUOUS = new Set(['ok', 'no', 'si', 'hey', 'hi', 'hello']);

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

  if (Math.max(...Object.values(scores)) < 1) return 'en';
  return Object.entries(scores).sort((a, b) => b[1] - a[1])[0][0];
}

// ── Estado por usuario ──
const userState = new Map();

function isExpired(state) {
  return Date.now() - state.lastSeen > RESET_TIMEOUT;
}

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

  const sock = makeWASocket({
    auth: state,
    syncFullHistory: false,
    markOnlineOnConnect: true,
    browser: ['AutoReply Bot', 'Chrome', '120.0'],
  });

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
      const shouldReconnect = (lastDisconnect?.error instanceof Boom)
        ? lastDisconnect.error.output.statusCode !== DisconnectReason.loggedOut
        : true;

      console.log(`[WA] Conexión cerrada. Reconnect: ${shouldReconnect}`);

      if (shouldReconnect) {
        startBot();
      } else {
        console.log('[WA] Sesión cerrada. Vuelve a escanear QR borrando wa_auth/');
      }
    }

    if (connection === 'open') {
      console.log(`[WA] ✅ Conectado como ${sock.user?.name || sock.user?.id}`);
    }
  });

  // ── Manejar llamadas entrantes ──
  sock.ev.on('call', async (call) => {
    if (call.status === 'offer') {
      const jid = call.from;
      console.log(`[WA ${jid}] CALL received (offer)`);

      // Rechazar la llamada para que no siga sonando
      try {
        await sock.rejectCall(call.id, call.from);
      } catch(e) {
        console.error('[WA] Error rejecting call:', e.message);
      }

      // Detectar idioma
      let lang = 'en';
      const state = userState.get(jid);
      if (state && !isExpired(state)) {
        lang = state.lang;
      }

      const callMsg = getCallMessage(lang);
      console.log(`[WA ${jid} lang=${lang}] CALL reply: "${callMsg.text.slice(0, 40)}"`);

      // Enviar texto
      await sock.sendMessage(jid, { text: callMsg.text });

      // Enviar audio si existe
      if (callMsg.audio) {
        const audioBuffer = readAudio(callMsg.audio);
        if (audioBuffer) {
          try {
            await sock.sendMessage(jid, {
              audio: audioBuffer,
              mimetype: 'audio/mpeg',
              ptt: false,
            });
          } catch (err) {
            console.error(`[WA] Error enviando audio de llamada a ${jid}:`, err.message);
          }
        }
      }
    }
  });

  // ── Manejar mensajes entrantes ──
  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    console.log(`[WA] messages.upsert type=${type} count=${messages.length}`);
    for (const m of messages) {
      console.log(`[WA]   msg key=${JSON.stringify(m.key)} fromMe=${m.key.fromMe} hasMsg=${!!m.message} type=${type}`);
    }

    for (const msg of messages) {
      // Ignorar mensajes propios, status, grupos
      if (msg.key.fromMe) continue;
      const remoteJid = msg.key.remoteJid || '';
      const altJid = msg.key.remoteJidAlt || '';
      if (remoteJid.endsWith('@g.us') || altJid.endsWith('@g.us')) continue; // ignorar grupos
      
      // Aceptar tanto @s.whatsapp.net como @lid (nuevo formato WhatsApp)
      const isDirectMessage = remoteJid.endsWith('@s.whatsapp.net') 
                           || remoteJid.endsWith('@lid')
                           || altJid.endsWith('@s.whatsapp.net');
      if (!isDirectMessage) {
        console.log(`[WA]   skipped — not a DM: remoteJid=${remoteJid} altJid=${altJid}`);
        continue;
      }

      // Usar el JID alternativo si el principal es @lid
      const jid = remoteJid.endsWith('@s.whatsapp.net') ? remoteJid : altJid;
      if (!jid) continue;
      
      const text = (msg.message?.conversation || msg.message?.extendedTextMessage?.text || '').trim();

      if (!text) {
        // Podría ser un audio/imagen — ignoramos por ahora (solo texto)
        continue;
      }

      const now = Date.now();
      let state = userState.get(jid);

      // ── Nuevo ciclo o expired ──
      let stepToUse;
      if (!state || isExpired(state)) {
        if (state) {
          console.log(`[WA ${jid}] EXPIRED (${(now - state.lastSeen) / 1000}s idle) — new cycle`);
        }
        const lang = detectLang(text);
        state = { lang, step: 0, lastSeen: now };
        userState.set(jid, state);
        stepToUse = 0;
      } else {
        stepToUse = Math.min(state.step + 1, 2);
        state.step = stepToUse;
        state.lastSeen = now;
      }

      const lang = state.lang;
      const msgData = getMessage(lang, stepToUse);

      // ── Enviar texto ──
      await sock.sendMessage(jid, { text: msgData.text });
      console.log(`[WA ${jid} lang=${lang} step=${stepToUse}] "${text.slice(0, 40)}" → "${msgData.text.slice(0, 40)}"`);

      // ── Enviar audio (si existe) ──
      const audioBuffer = readAudio(msgData.audio);
      if (audioBuffer) {
        try {
          await sock.sendMessage(jid, {
            audio: audioBuffer,
            mimetype: 'audio/mpeg',
            ptt: false, // true = nota de voz
          });
        } catch (err) {
          console.error(`[WA] Error enviando audio a ${jid}:`, err.message);
        }
      }
    }
  });

  // ── Mantener proceso vivo ──
  process.on('SIGINT', () => {
    console.log('[WA] Cerrando conexión...');
    sock.end(new Error('SIGINT'));
    process.exit(0);
  });
}

// ── Main ──
console.log('🚀 WhatsApp Bot AutoReply iniciando...');
console.log(`📁 Directorio: ${BASE_DIR}`);
console.log(`📁 Auth: ${AUTH_DIR}`);
console.log(`🔑 Escanea el QR con tu WhatsApp`);
console.log('────────────────────────────────────────\n');

startBot().catch(err => {
  console.error('[WA] Error fatal:', err);
  process.exit(1);
});
