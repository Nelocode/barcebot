import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';

import { PersistentInteractionState } from '../interaction_state.mjs';
import { createWhatsAppMessageHandler, describeInteraction } from '../wa_message_handler.mjs';
import { KeyedSerialQueue } from '../keyed_serial_queue.mjs';

function incoming(id, message, overrides = {}) {
  return {
    key: {
      id,
      fromMe: false,
      remoteJid: '573001234567@s.whatsapp.net',
      ...overrides,
    },
    message,
  };
}

function createHarness() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-message-handler-'));
  const state = new PersistentInteractionState({
    filePath: path.join(directory, 'state.json'),
    logger: { error() {} },
  });
  const effects = [];
  const handler = createWhatsAppMessageHandler({
    sendMessage: async (jid, content) => effects.push([jid, content]),
    routeInteraction: details => state.register(details),
    getResponseMessage: (_lang, key) => ({ text: key, audio: `${key}.mp3` }),
    readAudio: async filename => Buffer.from(filename),
    detectLanguage: text => text === 'bonjour' ? 'fr' : 'es',
    logger: { info() {}, warn() {}, error() {} },
  });
  return { handler, effects, state };
}

test('texto, voz, imagen y archivo se reconocen como interacciones', () => {
  const messages = [
    { conversation: 'hola' },
    { audioMessage: { ptt: true } },
    { ptvMessage: {} },
    { imageMessage: { caption: '' } },
    { documentMessage: { fileName: 'x.pdf' } },
    { albumMessage: { expectedImageCount: 2 } },
    { associatedChildMessage: { message: { imageMessage: {} } } },
    { ephemeralMessage: { message: { videoMessage: { caption: 'hola' } } } },
  ];

  for (const message of messages) assert.ok(describeInteraction(message));
  assert.equal(describeInteraction({ protocolMessage: { type: 0 } }), null);
  assert.equal(describeInteraction({ reactionMessage: { text: '👍' } }), null);
  assert.equal(describeInteraction({
    editedMessage: { message: { conversation: 'texto editado' } },
  }), null);
});

test('primera multimedia usa Paso 1 y todas las posteriores Paso 2', async () => {
  const { handler, effects } = createHarness();

  const results = await handler({
    type: 'notify',
    messages: [
      incoming('1', { imageMessage: {} }),
      incoming('2', { audioMessage: { ptt: true } }),
      incoming('3', { documentMessage: { fileName: 'x.pdf' } }),
    ],
  });

  assert.deepEqual(results.map(result => result.response), ['step1', 'step2', 'step2']);
  assert.deepEqual(
    effects.filter(([, content]) => content.text).map(([, content]) => content.text),
    ['step1', 'step2', 'step2'],
  );
});

test('imagen con descripción cuenta una sola vez y fija el idioma', async () => {
  const { handler, effects } = createHarness();

  await handler({
    type: 'notify',
    messages: [incoming('1', { imageMessage: { caption: 'bonjour' } })],
  });

  assert.equal(effects.length, 2);
  assert.equal(effects[0][1].text, 'step1');
});

test('el mismo id repetido no responde ni avanza dos veces', async () => {
  const { handler, effects } = createHarness();
  const message = incoming('same', { conversation: 'hola' });

  await handler({ type: 'notify', messages: [message] });
  const duplicate = await handler({ type: 'notify', messages: [message] });
  const next = await handler({ type: 'notify', messages: [incoming('next', { conversation: 'hola' })] });

  assert.equal(duplicate[0].reason, 'duplicate');
  assert.equal(next[0].response, 'step2');
  assert.equal(effects.length, 4);
});

test('ignora salientes, grupos, estados y eventos técnicos', async () => {
  const { handler, effects } = createHarness();
  const results = await handler({
    type: 'notify',
    messages: [
      incoming('1', { conversation: 'hola' }, { fromMe: true }),
      incoming('2', { conversation: 'hola' }, { remoteJid: '123@g.us' }),
      incoming('3', { conversation: 'hola' }, { remoteJid: 'status@broadcast' }),
      incoming('4', { protocolMessage: { type: 0 } }),
    ],
  });

  assert.equal(results.every(result => result.status === 'ignored'), true);
  assert.equal(effects.length, 0);
});

test('resuelve un LID al número para compartir identidad y responder', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-message-handler-'));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  const effects = [];
  const handler = createWhatsAppMessageHandler({
    sendMessage: async (jid, content) => effects.push([jid, content]),
    routeInteraction: details => state.register(details),
    getResponseMessage: (_lang, key) => ({ text: key, audio: '' }),
    readAudio: async () => null,
    detectLanguage: () => 'es',
    resolvePnForLid: async () => '573001234567@s.whatsapp.net',
    logger: { info() {}, warn() {}, error() {} },
  });

  await handler({
    type: 'notify',
    messages: [incoming('1', { conversation: 'hola' }, { remoteJid: '123@lid' })],
  });

  assert.equal(effects[0][0], '573001234567@s.whatsapp.net');
});

test('normaliza el sufijo de dispositivo para conservar una sola identidad', async () => {
  const { handler, effects } = createHarness();

  await handler({
    type: 'notify',
    messages: [incoming('1', { conversation: 'hola' }, {
      remoteJid: '573001234567:4@s.whatsapp.net',
    })],
  });

  assert.equal(effects[0][0], '573001234567@s.whatsapp.net');
});

test('un padre de álbum y sus hijos cuentan como una sola interacción', async () => {
  const { handler, effects } = createHarness();
  const parent = incoming('album-1', { albumMessage: { expectedImageCount: 1 } });
  const child = incoming('child-1', {
    imageMessage: {},
    messageContextInfo: {
      messageAssociation: { parentMessageKey: { id: 'album-1' } },
    },
  });

  const results = await handler({ type: 'notify', messages: [parent, child] });

  assert.equal(results[0].response, 'step1');
  assert.equal(results[1].reason, 'duplicate');
  assert.equal(effects.length, 2);
});

test('un hijo de álbum envuelto conserva el id del padre', async () => {
  const { handler, effects } = createHarness();
  const parent = incoming('album-2', { albumMessage: { expectedImageCount: 1 } });
  const child = incoming('child-2', {
    associatedChildMessage: {
      message: {
        imageMessage: {},
        messageContextInfo: {
          messageAssociation: { parentMessageKey: { id: 'album-2' } },
        },
      },
    },
  });

  const results = await handler({ type: 'notify', messages: [parent, child] });

  assert.equal(results[0].response, 'step1');
  assert.equal(results[1].reason, 'duplicate');
  assert.equal(effects.length, 2);
});

test('la resolución LID lenta no invierte Paso 1 y Paso 2', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-message-order-'));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  const claimQueue = new KeyedSerialQueue();
  const deliveryQueue = new KeyedSerialQueue();
  const effects = [];
  const phoneJid = '573001234567@s.whatsapp.net';
  const handler = createWhatsAppMessageHandler({
    sendMessage: async (_jid, content) => effects.push(content.text),
    routeInteraction: details => state.register(details),
    getResponseMessage: (_lang, key) => ({ text: key, audio: '' }),
    readAudio: async () => null,
    detectLanguage: () => 'es',
    resolvePnForLid: async () => {
      await new Promise(resolve => setTimeout(resolve, 20));
      return phoneJid;
    },
    serializeClaim: operation => claimQueue.run('all-inbound', operation),
    serializeInteraction: (contactId, operation) => deliveryQueue.run(contactId, operation),
    logger: { info() {}, warn() {}, error() {} },
  });
  const first = incoming('first', { conversation: 'hola' }, { remoteJid: '123@lid' });
  const second = incoming('second', { conversation: 'hola' }, { remoteJid: phoneJid });

  const results = await handler({ type: 'notify', messages: [first, second] });

  assert.deepEqual(results.map(result => result.response), ['step1', 'step2']);
  assert.deepEqual(effects, ['step1', 'step2']);
});

test('procesa append reciente pero ignora historial antiguo', async () => {
  const { handler, effects } = createHarness();
  const currentSeconds = Math.floor(Date.now() / 1000);

  const recent = incoming('recent', { conversation: 'hola' });
  recent.messageTimestamp = currentSeconds;
  const old = incoming('old', { conversation: 'hola' });
  old.messageTimestamp = currentSeconds - 3600;
  const recentResult = await handler({ type: 'append', messages: [recent] });
  const oldResult = await handler({ type: 'append', messages: [old] });

  assert.equal(recentResult[0].response, 'step1');
  assert.equal(oldResult[0].reason, 'historical_append');
  assert.equal(effects.length, 2);
});

test('un contacto bloqueado no detiene otro del mismo lote', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-message-handler-'));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  const queue = new KeyedSerialQueue();
  const completed = [];
  let releaseFirst;
  const firstGate = new Promise(resolve => { releaseFirst = resolve; });
  const handler = createWhatsAppMessageHandler({
    sendMessage: async (jid) => {
      if (jid.startsWith('573001')) await firstGate;
      completed.push(jid);
    },
    routeInteraction: details => state.register(details),
    getResponseMessage: () => ({ text: 'x', audio: '' }),
    readAudio: async () => null,
    detectLanguage: () => 'es',
    serializeInteraction: (contactId, operation) => queue.run(contactId, operation),
    logger: { info() {}, warn() {}, error() {} },
  });
  const first = incoming('1', { conversation: 'hola' });
  const second = incoming('2', { conversation: 'hola' }, {
    remoteJid: '573009999999@s.whatsapp.net',
  });

  const pending = handler({ type: 'notify', messages: [first, second] });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(completed, ['573009999999@s.whatsapp.net']);
  releaseFirst();
  await pending;
});

test('un envío sin respuesta vence y no bloquea al contacto para siempre', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-message-timeout-'));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  const queue = new KeyedSerialQueue();
  let sendCount = 0;
  const handler = createWhatsAppMessageHandler({
    sendMessage: async () => {
      sendCount += 1;
      if (sendCount === 1) return new Promise(() => {});
      return undefined;
    },
    routeInteraction: details => state.register(details),
    getResponseMessage: (_lang, key) => ({ text: key, audio: '' }),
    readAudio: async () => null,
    detectLanguage: () => 'es',
    serializeInteraction: (contactId, operation) => queue.run(contactId, operation),
    sendTimeoutMs: 15,
    logger: { info() {}, warn() {}, error() {} },
  });

  const first = handler({
    type: 'notify',
    messages: [incoming('timeout-1', { conversation: 'hola' })],
  });
  const second = handler({
    type: 'notify',
    messages: [incoming('timeout-2', { conversation: 'hola' })],
  });
  const [firstResult, secondResult] = await Promise.all([first, second]);

  assert.equal(firstResult[0].text, 'failed');
  assert.equal(secondResult[0].text, 'sent');
  assert.equal(secondResult[0].response, 'step2');
});
