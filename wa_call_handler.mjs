const DEFAULT_DEDUPE_TTL_MS = 60 * 60 * 1000;
const DEFAULT_REJECT_TIMEOUT_MS = 5_000;

function maskJid(jid) {
  if (!jid || typeof jid !== 'string') return 'unknown';
  const [local = '', server = ''] = jid.split('@', 2);
  const visible = local.slice(-4);
  return `***${visible}${server ? `@${server}` : ''}`;
}

function normalizeCallBatch(payload) {
  if (Array.isArray(payload)) return payload;
  return payload && typeof payload === 'object' ? [payload] : [];
}

function pruneHandledCalls(handledCalls, now, ttlMs) {
  for (const [key, handledAt] of handledCalls) {
    if (now - handledAt >= ttlMs) handledCalls.delete(key);
  }
}

async function settleWithTimeout(promise, timeoutMs, operation) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error(`${operation} superó ${timeoutMs} ms`)),
          timeoutMs,
        );
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/**
 * Crea el handler del evento `call` de Baileys.
 *
 * Baileys entrega WACallEvent[], no un único objeto. Este handler también
 * tolera un objeto individual para facilitar pruebas y compatibilidad.
 */
export function createWhatsAppCallHandler({
  rejectCall,
  sendMessage,
  getCallMessage,
  readAudio,
  getLanguage = () => 'en',
  logger = console,
  now = () => Date.now(),
  dedupeTtlMs = DEFAULT_DEDUPE_TTL_MS,
  rejectTimeoutMs = DEFAULT_REJECT_TIMEOUT_MS,
  handledCalls = new Map(),
}) {
  if (typeof rejectCall !== 'function') throw new TypeError('rejectCall es requerido');
  if (typeof sendMessage !== 'function') throw new TypeError('sendMessage es requerido');
  if (typeof getCallMessage !== 'function') throw new TypeError('getCallMessage es requerido');
  if (typeof readAudio !== 'function') throw new TypeError('readAudio es requerido');

  async function handleOneCall(call) {
    if (!call || typeof call !== 'object') {
      return { status: 'ignored', reason: 'invalid_event' };
    }
    logger.info?.(
      `[WA CALL] Evento status=${call.status || 'missing'} from=${maskJid(call.from)} ` +
      `offline=${Boolean(call.offline)} video=${Boolean(call.isVideo)}`,
    );
    if (call.status !== 'offer') {
      return { status: 'ignored', reason: `status_${call.status || 'missing'}` };
    }
    if (!call.id || !call.from) {
      logger.warn?.('[WA CALL] Oferta ignorada: faltan id o from');
      return { status: 'ignored', reason: 'missing_identity' };
    }
    if (call.isGroup) {
      logger.info?.(`[WA CALL] Llamada grupal ignorada (${maskJid(call.from)})`);
      return { status: 'ignored', reason: 'group_call' };
    }

    const currentTime = now();
    pruneHandledCalls(handledCalls, currentTime, dedupeTtlMs);
    const dedupeKey = `${call.from}:${call.id}`;
    if (handledCalls.has(dedupeKey)) {
      logger.info?.(`[WA CALL] Oferta duplicada ignorada (${maskJid(call.from)})`);
      return { status: 'ignored', reason: 'duplicate' };
    }

    // Reclamar el evento antes del primer await evita respuestas simultáneas.
    handledCalls.set(dedupeKey, currentTime);

    const replyJid = call.chatId || call.callerPn || call.from;
    const result = {
      status: 'handled',
      callId: call.id,
      replyJid,
      reject: 'pending',
      text: 'skipped',
      audio: 'skipped',
    };

    logger.info?.(
      `[WA CALL] Oferta recibida de ${maskJid(call.from)}${call.isVideo ? ' (video)' : ''}`,
    );

    if (call.offline) {
      // Una oferta recibida desde la cola ya no representa una llamada activa.
      // Conservamos el aviso automático, pero evitamos un rechazo inútil.
      result.reject = 'skipped_offline';
      logger.info?.(`[WA CALL] Oferta offline; se omite el rechazo (${maskJid(call.from)})`);
    } else {
      try {
        await settleWithTimeout(
          Promise.resolve(rejectCall(call.id, call.from)),
          rejectTimeoutMs,
          'El rechazo de la llamada',
        );
        result.reject = 'sent';
      } catch (error) {
        result.reject = 'failed';
        logger.error?.(`[WA CALL] No se pudo rechazar: ${error.message}`);
      }
    }

    let lang = 'en';
    let callMessage = {};
    try {
      lang = getLanguage(call, replyJid) || 'en';
      callMessage = getCallMessage(lang) || {};
    } catch (error) {
      logger.error?.(`[WA CALL] No se pudo preparar la respuesta: ${error.message}`);
    }

    const text = typeof callMessage.text === 'string' ? callMessage.text.trim() : '';
    if (text) {
      try {
        await sendMessage(replyJid, { text });
        result.text = 'sent';
      } catch (error) {
        result.text = 'failed';
        logger.error?.(`[WA CALL] No se pudo enviar el texto: ${error.message}`);
      }
    }

    if (callMessage.audio) {
      try {
        const audioBuffer = await readAudio(callMessage.audio);
        if (audioBuffer) {
          await sendMessage(replyJid, {
            audio: audioBuffer,
            mimetype: 'audio/mpeg',
            ptt: false,
          });
          result.audio = 'sent';
        } else {
          result.audio = 'missing';
        }
      } catch (error) {
        result.audio = 'failed';
        logger.error?.(`[WA CALL] No se pudo enviar el audio: ${error.message}`);
      }
    }

    logger.info?.(
      `[WA CALL] Respuesta ${lang.toUpperCase()} completada para ${maskJid(replyJid)}`,
    );
    return result;
  }

  return async function handleCallBatch(payload) {
    const calls = normalizeCallBatch(payload);
    if (calls.length === 0) {
      logger.warn?.('[WA CALL] Payload vacío o inválido');
      return [];
    }

    const results = [];
    for (const call of calls) {
      try {
        results.push(await handleOneCall(call));
      } catch (error) {
        logger.error?.(`[WA CALL] Error inesperado: ${error.message}`);
        results.push({ status: 'failed', reason: 'unexpected_error' });
      }
    }
    return results;
  };
}
