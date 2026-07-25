import test from 'node:test';
import assert from 'node:assert/strict';

import { createWhatsAppCallHandler } from '../wa_call_handler.mjs';

function createHarness(overrides = {}) {
  const effects = [];
  const metrics = [];
  const logger = { info() {}, warn() {}, error() {} };
  const handler = createWhatsAppCallHandler({
    rejectCall: async (id, from) => effects.push(['reject', id, from]),
    sendMessage: async (jid, content) => effects.push(['send', jid, content]),
    getCallMessage: () => ({ text: 'No podemos responder ahora.', audio: 'call.mp3' }),
    readAudio: async () => Buffer.from('audio'),
    getLanguage: () => 'es',
    logger,
    onCallMetric: (metric) => metrics.push(metric),
    ...overrides,
  });
  return { handler, effects, metrics };
}

function offer(overrides = {}) {
  return {
    id: 'call-1',
    from: '573001234567@s.whatsapp.net',
    chatId: '573001234567@s.whatsapp.net',
    status: 'offer',
    offline: false,
    isVideo: false,
    ...overrides,
  };
}

test('procesa el arreglo de llamadas que entrega Baileys', async () => {
  const { handler, effects } = createHarness();

  const result = await handler([offer()]);

  assert.equal(result[0].status, 'handled');
  assert.deepEqual(effects[0], ['reject', 'call-1', '573001234567@s.whatsapp.net']);
  assert.deepEqual(effects[1], [
    'send',
    '573001234567@s.whatsapp.net',
    { text: 'No podemos responder ahora.' },
  ]);
  assert.equal(effects[2][0], 'send');
  assert.equal(effects[2][2].mimetype, 'audio/mpeg');
  assert.deepEqual(effects[2][2].audio, Buffer.from('audio'));
});

test('procesa todas las ofertas del mismo lote de forma aislada', async () => {
  const { handler, effects } = createHarness();

  const result = await handler([
    offer(),
    offer({ id: 'call-2', from: '573009999999@s.whatsapp.net', chatId: '573009999999@s.whatsapp.net' }),
  ]);

  assert.equal(result.filter((item) => item.status === 'handled').length, 2);
  assert.equal(effects.filter(([kind]) => kind === 'reject').length, 2);
  assert.equal(effects.filter(([kind]) => kind === 'send').length, 4);
});

test('ignora estados que no son una oferta', async () => {
  const { handler, effects } = createHarness();

  const result = await handler([offer({ status: 'ringing' }), offer({ status: 'terminate' })]);

  assert.deepEqual(result.map((item) => item.status), ['ignored', 'ignored']);
  assert.equal(effects.length, 0);
});

test('responde una oferta offline sin intentar rechazar una llamada histórica', async () => {
  const { handler, effects } = createHarness();

  const result = await handler([offer({ offline: true })]);

  assert.equal(result[0].status, 'handled');
  assert.equal(result[0].reject, 'skipped_offline');
  assert.equal(effects.filter(([kind]) => kind === 'reject').length, 0);
  assert.equal(effects.filter(([kind]) => kind === 'send').length, 2);
});

test('ignora llamadas grupales para no responder dentro del grupo', async () => {
  const { handler, effects } = createHarness();

  const result = await handler([offer({ isGroup: true })]);

  assert.equal(result[0].status, 'ignored');
  assert.equal(result[0].reason, 'group_call');
  assert.equal(effects.length, 0);
});

test('deduplica la misma oferta en callbacks repetidos y concurrentes', async () => {
  const { handler, effects } = createHarness();

  await Promise.all([handler([offer()]), handler([offer()])]);
  await handler([offer()]);

  assert.equal(effects.filter(([kind]) => kind === 'reject').length, 1);
  assert.equal(effects.filter(([kind]) => kind === 'send').length, 2);
});

test('responde aunque falle el rechazo de la llamada', async () => {
  const { handler, effects } = createHarness({
    rejectCall: async () => {
      throw new Error('call already ended');
    },
  });

  const result = await handler([offer()]);

  assert.equal(result[0].reject, 'failed');
  assert.equal(result[0].text, 'sent');
  assert.equal(result[0].audio, 'sent');
  assert.equal(effects.filter(([kind]) => kind === 'send').length, 2);
});

test('un rechazo bloqueado vence y la respuesta continúa', async () => {
  const { handler, effects } = createHarness({
    rejectCall: () => new Promise(() => {}),
    rejectTimeoutMs: 5,
  });

  const result = await handler([offer()]);

  assert.equal(result[0].reject, 'failed');
  assert.equal(result[0].text, 'sent');
  assert.equal(result[0].audio, 'sent');
  assert.equal(effects.filter(([kind]) => kind === 'send').length, 2);
});

test('un fallo enviando texto no impide intentar el audio', async () => {
  const effects = [];
  const { handler } = createHarness({
    sendMessage: async (jid, content) => {
      effects.push(['send', jid, content]);
      if (content.text) throw new Error('text unavailable');
    },
  });

  const result = await handler([offer()]);

  assert.equal(result[0].text, 'failed');
  assert.equal(result[0].audio, 'sent');
  assert.equal(effects.length, 2);
  assert.ok(effects[1][2].audio);
});

test('un audio ausente no impide enviar el texto', async () => {
  const { handler, effects } = createHarness({ readAudio: async () => null });

  const result = await handler([offer()]);

  assert.equal(result[0].text, 'sent');
  assert.equal(result[0].audio, 'missing');
  assert.equal(effects.filter(([kind]) => kind === 'send').length, 1);
});

test('usa chatId para responder y from para rechazar', async () => {
  const { handler, effects } = createHarness();

  await handler([
    offer({
      from: '12345@lid',
      chatId: '573001234567@s.whatsapp.net',
    }),
  ]);

  assert.deepEqual(effects[0], ['reject', 'call-1', '12345@lid']);
  assert.equal(effects[1][1], '573001234567@s.whatsapp.net');
  assert.equal(effects[2][1], '573001234567@s.whatsapp.net');
});

test('prefiere callerPn para responder cuando chatId es un LID', async () => {
  const { handler, effects, metrics } = createHarness();

  await handler([
    offer({
      from: '12345@lid',
      chatId: '12345@lid',
      callerPn: '573001234567@s.whatsapp.net',
    }),
  ]);

  assert.deepEqual(effects[0], ['reject', 'call-1', '12345@lid']);
  assert.equal(effects[1][1], '573001234567@s.whatsapp.net');
  assert.equal(effects[2][1], '573001234567@s.whatsapp.net');
  const outcome = metrics.find((metric) => metric.type === 'outcome');
  assert.equal(outcome.target, 'caller_pn');
  assert.equal(outcome.targetKind, 'pn');
});

test('ignora callerPn malformado y cae a chatId', async () => {
  const { handler, effects, metrics } = createHarness();

  await handler([
    offer({
      from: '12345@lid',
      chatId: '573001234567@s.whatsapp.net',
      callerPn: 'not-a-phone@lid',
    }),
  ]);

  assert.equal(effects[1][1], '573001234567@s.whatsapp.net');
  assert.equal(effects[2][1], '573001234567@s.whatsapp.net');
  const outcome = metrics.find((metric) => metric.type === 'outcome');
  assert.equal(outcome.target, 'chat_id');
  assert.equal(outcome.targetKind, 'pn');
});

test('tolera payload vacío o un objeto individual', async () => {
  const { handler, effects } = createHarness();

  assert.deepEqual(await handler(null), []);
  const result = await handler(offer());

  assert.equal(result[0].status, 'handled');
  assert.equal(effects.filter(([kind]) => kind === 'reject').length, 1);
});

test('emite diagnostico anonimizado por lote y resultado', async () => {
  const { handler, metrics } = createHarness();

  await handler([offer()]);

  assert.equal(metrics[0].type, 'batch');
  assert.deepEqual(metrics[0], { type: 'batch', payload: 'array', size: 'one' });
  assert.equal(metrics[1].type, 'outcome');
  assert.equal(metrics[1].event, 'offer');
  assert.equal(metrics[1].outcome, 'handled');
  assert.equal(metrics[1].reason, 'completed');
  assert.equal(metrics[1].reject, 'sent');
  assert.equal(metrics[1].text, 'sent');
  assert.equal(metrics[1].audio, 'sent');

  const serialized = JSON.stringify(metrics);
  assert.doesNotMatch(serialized, /573001234567|@s\.whatsapp\.net|call-1|call\.mp3|No podemos/);
});

test('un observador de diagnostico defectuoso no altera la respuesta', async () => {
  const { handler, effects } = createHarness({
    onCallMetric: () => {
      throw new Error('diagnostic unavailable');
    },
  });

  const result = await handler([offer()]);

  assert.equal(result[0].status, 'handled');
  assert.equal(effects.filter(([kind]) => kind === 'send').length, 2);
});

test('cada rama ignorada emite una razon de cardinalidad cerrada', async () => {
  const { handler, metrics } = createHarness();

  await handler([
    offer({ status: 'future_status_with_private_data_573001234567' }),
    offer({ id: '' }),
    offer({ id: 'call-2', isGroup: true }),
  ]);

  const outcomes = metrics.filter((metric) => metric.type === 'outcome');
  assert.deepEqual(outcomes.map((metric) => metric.reason), [
    'non_offer',
    'missing_identity',
    'group_call',
  ]);
  assert.doesNotMatch(JSON.stringify(outcomes), /573001234567|@s\.whatsapp\.net|call-/);
});
