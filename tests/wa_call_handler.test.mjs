import test from 'node:test';
import assert from 'node:assert/strict';

import { createWhatsAppCallHandler } from '../wa_call_handler.mjs';

function createHarness(overrides = {}) {
  const effects = [];
  const logger = { info() {}, warn() {}, error() {} };
  const handler = createWhatsAppCallHandler({
    rejectCall: async (id, from) => effects.push(['reject', id, from]),
    sendMessage: async (jid, content) => effects.push(['send', jid, content]),
    getCallMessage: () => ({ text: 'No podemos responder ahora.', audio: 'call.mp3' }),
    readAudio: async () => Buffer.from('audio'),
    getLanguage: () => 'es',
    logger,
    ...overrides,
  });
  return { handler, effects };
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

test('tolera payload vacío o un objeto individual', async () => {
  const { handler, effects } = createHarness();

  assert.deepEqual(await handler(null), []);
  const result = await handler(offer());

  assert.equal(result[0].status, 'handled');
  assert.equal(effects.filter(([kind]) => kind === 'reject').length, 1);
});
