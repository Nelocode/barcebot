import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';

import { PersistentInteractionState } from '../interaction_state.mjs';
import { createWhatsAppMessageHandler, describeInteraction } from '../wa_message_handler.mjs';
import { KeyedSerialQueue } from '../keyed_serial_queue.mjs';
import { detectLanguage } from '../language_detection.mjs';

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

test('imagen sin texto usa +57 provisional y un texto inglés posterior lo reemplaza', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-message-language-'));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  const deliveredLanguages = [];
  const handler = createWhatsAppMessageHandler({
    sendMessage: async () => {},
    routeInteraction: details => state.register(details),
    getResponseMessage: (language, key) => {
      deliveredLanguages.push([language, key]);
      return { text: key, audio: '' };
    },
    readAudio: async () => null,
    detectLanguage: text => text === 'hello' ? 'en' : null,
    logger: { info() {}, warn() {}, error() {} },
  });

  await handler({ type: 'notify', messages: [incoming('image', { imageMessage: {} })] });
  await handler({ type: 'notify', messages: [incoming('text', { conversation: 'hello' })] });

  assert.deepEqual(deliveredLanguages, [['es', 'step1'], ['en', 'step2']]);
});

test('caption con empate no confirma idioma y texto claro posterior lo reemplaza', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-message-tied-language-'));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  const deliveredLanguages = [];
  const handler = createWhatsAppMessageHandler({
    sendMessage: async () => {},
    routeInteraction: details => state.register(details),
    getResponseMessage: (language, key) => {
      deliveredLanguages.push([language, key]);
      return { text: key, audio: '' };
    },
    readAudio: async () => null,
    detectLanguage,
    logger: { info() {}, warn() {}, error() {} },
  });

  await handler({
    type: 'notify',
    messages: [incoming('photo-caption', { imageMessage: { caption: 'photo' } })],
  });
  await handler({
    type: 'notify',
    messages: [incoming('clear-english', { conversation: 'Are you available now' })],
  });

  assert.deepEqual(deliveredLanguages, [['es', 'step1'], ['en', 'step2']]);
});

test('un LID sin PN no se usa como supuesto código telefónico', async () => {
  let routed;
  const handler = createWhatsAppMessageHandler({
    sendMessage: async () => {},
    routeInteraction: details => {
      routed = details;
      return { duplicate: false, responseKey: 'step1', language: 'es', contactKey: 'opaque' };
    },
    getResponseMessage: () => ({ text: '', audio: '' }),
    readAudio: async () => null,
    detectLanguage: () => null,
    resolvePnForLid: async () => null,
    logger: { info() {}, warn() {}, error() {} },
  });

  await handler({
    type: 'notify',
    messages: [incoming('lid-only', { imageMessage: {} }, { remoteJid: '12345@lid' })],
  });
  assert.equal(routed.provisionalLanguage, null);
});

test('envia OGG/Opus como nota de voz cuando el lector lo proporciona', async (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-message-handler-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  const effects = [];
  const handler = createWhatsAppMessageHandler({
    sendMessage: async (jid, content) => effects.push([jid, content]),
    routeInteraction: details => state.register(details),
    getResponseMessage: () => ({ text: '', audio: 'step1.mp3' }),
    readAudio: async () => ({
      buffer: Buffer.from('opus'),
      mimetype: 'audio/ogg; codecs=opus',
      ptt: true,
    }),
    detectLanguage: () => 'es',
    logger: { info() {}, warn() {}, error() {} },
  });

  await handler({
    type: 'notify',
    messages: [incoming('voice-note-output', { conversation: 'hola' })],
  });

  assert.deepEqual(effects[0][1], {
    audio: Buffer.from('opus'),
    mimetype: 'audio/ogg; codecs=opus',
    ptt: true,
  });
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

  assert.equal(results[0].reason, 'duplicate');
  assert.equal(results[1].response, 'step1');
  assert.equal(effects.length, 2);
});

test('caption de hijo de álbum prevalece sobre el padre vacío sin duplicar respuesta', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-captioned-album-'));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  const deliveredLanguages = [];
  const handler = createWhatsAppMessageHandler({
    sendMessage: async () => {},
    routeInteraction: details => state.register(details),
    getResponseMessage: (language, key) => {
      deliveredLanguages.push([language, key]);
      return { text: key, audio: '' };
    },
    readAudio: async () => null,
    detectLanguage,
    logger: { info() {}, warn() {}, error() {} },
  });
  const parent = incoming('captioned-album', { albumMessage: { expectedImageCount: 1 } });
  const child = incoming('captioned-child', {
    imageMessage: { caption: 'Are you available now' },
    messageContextInfo: {
      messageAssociation: { parentMessageKey: { id: 'captioned-album' } },
    },
  });

  const results = await handler({ type: 'notify', messages: [parent, child] });

  assert.equal(results[0].reason, 'duplicate');
  assert.equal(results[1].response, 'step1');
  assert.deepEqual(deliveredLanguages, [['en', 'step1']]);
  const persisted = Object.values(state.contacts)[0];
  assert.equal(persisted.language, 'en');
  assert.equal(persisted.language_provisional, false);
});

test('álbumes de contactos distintos no colisionan aunque compartan parent id', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-cross-contact-album-'));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  const deliveries = [];
  const handler = createWhatsAppMessageHandler({
    sendMessage: async jid => deliveries.push(jid),
    routeInteraction: details => state.register(details),
    getResponseMessage: () => ({ text: 'respuesta', audio: '' }),
    readAudio: async () => null,
    detectLanguage,
    logger: { info() {}, warn() {}, error() {} },
  });
  const firstParent = incoming('same-parent', { albumMessage: { expectedImageCount: 1 } });
  const firstChild = incoming('first-child', {
    imageMessage: { caption: 'Are you available now' },
    messageContextInfo: {
      messageAssociation: { parentMessageKey: { id: 'same-parent' } },
    },
  });
  const secondParent = incoming(
    'same-parent',
    { albumMessage: { expectedImageCount: 1 } },
    { remoteJid: '447700900123@s.whatsapp.net' },
  );
  const secondChild = incoming('second-child', {
    imageMessage: {},
    messageContextInfo: {
      messageAssociation: { parentMessageKey: { id: 'same-parent' } },
    },
  }, { remoteJid: '447700900123@s.whatsapp.net' });

  const results = await handler({
    type: 'notify',
    messages: [firstParent, firstChild, secondParent, secondChild],
  });

  assert.equal(results[0].reason, 'duplicate');
  assert.equal(results[1].response, 'step1');
  assert.equal(results[2].reason, 'duplicate');
  assert.equal(results[3].response, 'step1');
  assert.equal(deliveries.length, 2);
  assert.equal(Object.keys(state.contacts).length, 2);
});

test('padre LID y child PN/LID comparten álbum y el caption inglés prevalece', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-lid-pn-album-'));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  const deliveredLanguages = [];
  const handler = createWhatsAppMessageHandler({
    sendMessage: async () => {},
    routeInteraction: details => state.register(details),
    getResponseMessage: (language, key) => {
      deliveredLanguages.push([language, key]);
      return { text: key, audio: '' };
    },
    readAudio: async () => null,
    detectLanguage,
    logger: { info() {}, warn() {}, error() {} },
  });
  const parent = incoming(
    'lid-pn-parent',
    { albumMessage: { expectedImageCount: 1 } },
    { remoteJid: '12345@lid' },
  );
  const child = incoming('lid-pn-child', {
    imageMessage: { caption: 'Are you available now' },
    messageContextInfo: {
      messageAssociation: { parentMessageKey: { id: 'lid-pn-parent' } },
    },
  }, {
    remoteJid: '573001234567@s.whatsapp.net',
    remoteJidAlt: '12345@lid',
  });

  const results = await handler({ type: 'notify', messages: [parent, child] });

  assert.equal(results[0].reason, 'duplicate');
  assert.equal(results[1].response, 'step1');
  assert.deepEqual(deliveredLanguages, [['en', 'step1']]);
  const persisted = Object.values(state.contacts)[0];
  assert.equal(persisted.language, 'en');
  assert.equal(persisted.language_provisional, false);
});

test('solapamientos transitivos LID→PN eligen un solo representante con caption', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-transitive-album-'));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  const deliveries = [];
  const handler = createWhatsAppMessageHandler({
    sendMessage: async () => deliveries.push('sent'),
    routeInteraction: details => state.register(details),
    getResponseMessage: () => ({ text: 'respuesta', audio: '' }),
    readAudio: async () => null,
    detectLanguage,
    logger: { info() {}, warn() {}, error() {} },
  });
  const parent = incoming(
    'transitive-parent',
    { albumMessage: { expectedImageCount: 2 } },
    { remoteJid: '67890@lid' },
  );
  const bridge = incoming('transitive-bridge', {
    imageMessage: {},
    messageContextInfo: {
      messageAssociation: { parentMessageKey: { id: 'transitive-parent' } },
    },
  }, {
    remoteJid: '573009876543@s.whatsapp.net',
    remoteJidAlt: '67890@lid',
  });
  const captioned = incoming('transitive-caption', {
    imageMessage: { caption: 'Are you available now' },
    messageContextInfo: {
      messageAssociation: { parentMessageKey: { id: 'transitive-parent' } },
    },
  }, { remoteJid: '573009876543@s.whatsapp.net' });

  const results = await handler({
    type: 'notify',
    messages: [parent, bridge, captioned],
  });

  assert.deepEqual(results.map(result => result.reason || result.response), [
    'duplicate',
    'duplicate',
    'step1',
  ]);
  assert.equal(deliveries.length, 1);
  assert.equal(Object.values(state.contacts)[0].language, 'en');
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

  assert.equal(results[0].reason, 'duplicate');
  assert.equal(results[1].response, 'step1');
  assert.equal(effects.length, 2);
});

test('parent vacío en callback previo no consume el caption de un callback posterior', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-split-album-'));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  const deliveredLanguages = [];
  const handler = createWhatsAppMessageHandler({
    sendMessage: async () => {},
    routeInteraction: details => state.register(details),
    getResponseMessage: (language, key) => {
      deliveredLanguages.push([language, key]);
      return { text: key, audio: '' };
    },
    readAudio: async () => null,
    detectLanguage,
    logger: { info() {}, warn() {}, error() {} },
  });
  const parent = incoming('split-parent', { albumMessage: { expectedImageCount: 1 } });
  const child = incoming('split-child', {
    imageMessage: { caption: 'Are you available now' },
    messageContextInfo: {
      messageAssociation: { parentMessageKey: { id: 'split-parent' } },
    },
  });

  const first = await handler({ type: 'notify', messages: [parent] });
  assert.equal(first[0].reason, 'album_placeholder');
  assert.deepEqual(deliveredLanguages, []);
  assert.equal(Object.keys(state.contacts).length, 0);

  const second = await handler({ type: 'notify', messages: [child] });
  assert.equal(second[0].response, 'step1');
  assert.deepEqual(deliveredLanguages, [['en', 'step1']]);
  const persisted = Object.values(state.contacts)[0];
  assert.equal(persisted.language, 'en');
  assert.equal(persisted.language_provisional, false);
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

test('marca la conversación como leída antes de iniciar la respuesta', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-message-read-order-'));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  const effects = [];
  const handler = createWhatsAppMessageHandler({
    sendMessage: async () => effects.push('send'),
    markRead: async key => effects.push(`read:${key.id}`),
    routeInteraction: details => state.register(details),
    getResponseMessage: () => ({ text: 'respuesta', audio: '' }),
    readAudio: async () => null,
    detectLanguage: () => 'es',
    logger: { info() {}, warn() {}, error() {} },
  });

  await handler({ type: 'notify', messages: [incoming('read-first', { conversation: 'hola' })] });

  assert.deepEqual(effects, ['read:read-first', 'send']);
});

test('una pausa previa no consume el evento ni avanza la fase de conversación', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-message-paused-state-'));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  let routed = 0;
  const common = {
    routeInteraction: details => {
      routed += 1;
      return state.register(details);
    },
    getResponseMessage: (_language, key) => ({ text: key, audio: '' }),
    readAudio: async () => null,
    detectLanguage: () => 'es',
    logger: { info() {}, warn() {}, error() {} },
  };
  const paused = createWhatsAppMessageHandler({
    ...common,
    deliveryAllowed: () => false,
    sendMessage: async () => assert.fail('delivery must remain blocked'),
  });

  const ignored = await paused({
    type: 'notify',
    messages: [incoming('paused-event', { conversation: 'hola' })],
  });
  assert.equal(ignored[0].reason, 'delivery_blocked');
  assert.equal(routed, 0);

  const effects = [];
  const resumed = createWhatsAppMessageHandler({
    ...common,
    sendMessage: async (_jid, content) => effects.push(content.text),
  });
  const delivered = await resumed({
    type: 'notify',
    messages: [incoming('resumed-event', { conversation: 'hola' })],
  });
  assert.equal(delivered[0].response, 'step1');
  assert.deepEqual(effects, ['step1']);
});
