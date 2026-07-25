const DEFAULT_DEDUPE_TTL_MS = 60 * 60 * 1000;
const DEFAULT_REJECT_TIMEOUT_MS = 5_000;
const SAFE_EVENT_STATUSES = new Set([
  'offer', 'ringing', 'preaccept', 'transport', 'relaylatency', 'terminate',
  'timeout', 'reject', 'accept', 'other', 'missing',
]);

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
  onCallMetric = () => {},
}) {
  if (typeof rejectCall !== 'function') throw new TypeError('rejectCall es requerido');
  if (typeof sendMessage !== 'function') throw new TypeError('sendMessage es requerido');
  if (typeof getCallMessage !== 'function') throw new TypeError('getCallMessage es requerido');
  if (typeof readAudio !== 'function') throw new TypeError('readAudio es requerido');

  function emitMetric(metric) {
    try {
      const pending = onCallMetric(metric);
      if (pending && typeof pending.catch === 'function') pending.catch(() => {});
    } catch {
      // Diagnostics are best-effort and must never alter call handling.
    }
  }

  function eventMetricContext(call) {
    const rawStatus = typeof call?.status === 'string' && call.status ? call.status : 'missing';
    return {
      event: SAFE_EVENT_STATUSES.has(rawStatus) ? rawStatus : 'other',
      offline: typeof call?.offline === 'boolean' ? call.offline : null,
      video: typeof call?.isVideo === 'boolean' ? call.isVideo : null,
      group: typeof call?.isGroup === 'boolean' ? call.isGroup : null,
    };
  }

  function finish(call, result, reason, delivery = {}) {
    emitMetric({
      type: 'outcome',
      ...eventMetricContext(call),
      outcome: result.status,
      reason,
      reject: delivery.reject || 'not_applicable',
      text: delivery.text || 'not_applicable',
      audio: delivery.audio || 'not_applicable',
    });
    return result;
  }

  async function handleOneCall(call) {
    if (!call || typeof call !== 'object') {
      return finish(call, { status: 'ignored', reason: 'invalid_event' }, 'invalid_event');
    }
    const metricContext = eventMetricContext(call);
    logger.info?.(
      `[WA CALL] Event status=${metricContext.event} ` +
      `offline=${Boolean(call.offline)} video=${Boolean(call.isVideo)}`,
    );
    if (call.status !== 'offer') {
      return finish(
        call,
        { status: 'ignored', reason: `status_${call.status || 'missing'}` },
        'non_offer',
      );
    }
    if (!call.id || !call.from) {
      logger.warn?.('[WA CALL] Oferta ignorada: faltan id o from');
      return finish(call, { status: 'ignored', reason: 'missing_identity' }, 'missing_identity');
    }
    if (call.isGroup) {
      logger.info?.('[WA CALL] Group call ignored');
      return finish(call, { status: 'ignored', reason: 'group_call' }, 'group_call');
    }

    const currentTime = now();
    pruneHandledCalls(handledCalls, currentTime, dedupeTtlMs);
    const dedupeKey = `${call.from}:${call.id}`;
    if (handledCalls.has(dedupeKey)) {
      logger.info?.('[WA CALL] Duplicate offer ignored');
      return finish(call, { status: 'ignored', reason: 'duplicate' }, 'duplicate');
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

    logger.info?.(`[WA CALL] Offer received${call.isVideo ? ' (video)' : ''}`);

    if (call.offline) {
      // Una oferta recibida desde la cola ya no representa una llamada activa.
      // Conservamos el aviso automático, pero evitamos un rechazo inútil.
      result.reject = 'skipped_offline';
      logger.info?.('[WA CALL] Offline offer; rejection skipped');
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
        logger.error?.('[WA CALL] Call rejection failed');
      }
    }

    let lang = 'en';
    let callMessage = {};
    try {
      lang = getLanguage(call, replyJid) || 'en';
      callMessage = getCallMessage(lang) || {};
    } catch (error) {
      logger.error?.('[WA CALL] Response preparation failed');
    }

    const text = typeof callMessage.text === 'string' ? callMessage.text.trim() : '';
    if (text) {
      try {
        await sendMessage(replyJid, { text });
        result.text = 'sent';
      } catch (error) {
        result.text = 'failed';
        logger.error?.('[WA CALL] Text delivery failed');
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
        logger.error?.('[WA CALL] Audio delivery failed');
      }
    }

    logger.info?.(`[WA CALL] ${lang.toUpperCase()} response completed`);
    return finish(call, result, 'completed', result);
  }

  return async function handleCallBatch(payload) {
    const calls = normalizeCallBatch(payload);
    emitMetric({
      type: 'batch',
      payload: Array.isArray(payload)
        ? 'array'
        : (payload && typeof payload === 'object' ? 'object' : 'invalid'),
      size: calls.length === 0 ? 'empty' : (calls.length === 1 ? 'one' : 'multiple'),
    });
    if (calls.length === 0) {
      logger.warn?.('[WA CALL] Payload vacío o inválido');
      return [];
    }

    const results = [];
    for (const call of calls) {
      try {
        results.push(await handleOneCall(call));
      } catch (error) {
        logger.error?.('[WA CALL] Unexpected handler failure');
        emitMetric({
          type: 'outcome',
          ...eventMetricContext(call),
          outcome: 'failed',
          reason: 'unexpected_error',
          reject: 'not_applicable',
          text: 'not_applicable',
          audio: 'not_applicable',
        });
        results.push({ status: 'failed', reason: 'unexpected_error' });
      }
    }
    return results;
  };
}
