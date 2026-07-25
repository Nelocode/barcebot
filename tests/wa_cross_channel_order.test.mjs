import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';

import { PersistentInteractionState } from '../interaction_state.mjs';
import { KeyedSerialQueue } from '../keyed_serial_queue.mjs';
import { createWhatsAppCallHandler } from '../wa_call_handler.mjs';
import { createWhatsAppMessageHandler } from '../wa_message_handler.mjs';


test('una llamada en resolución conserva su turno frente a un mensaje posterior', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-cross-order-'));
  const state = new PersistentInteractionState({ filePath: path.join(directory, 'state.json') });
  const claimQueue = new KeyedSerialQueue();
  const deliveryQueue = new KeyedSerialQueue();
  const effects = [];
  const phoneJid = '573001234567@s.whatsapp.net';
  const shared = {
    routeInteraction: details => state.register(details),
    getResponseMessage: (_lang, key) => ({ text: key, audio: '' }),
    readAudio: async () => null,
    serializeClaim: operation => claimQueue.run('all-inbound', operation),
    serializeInteraction: (contactId, operation) => deliveryQueue.run(contactId, operation),
    logger: { info() {}, warn() {}, error() {} },
  };
  const callHandler = createWhatsAppCallHandler({
    ...shared,
    rejectCall: async () => {},
    sendMessage: async (_jid, content) => effects.push(content.text),
    getCallMessage: () => ({ text: 'legacy-call', audio: '' }),
    resolveContactId: async () => {
      await new Promise(resolve => setTimeout(resolve, 20));
      return phoneJid;
    },
  });
  const messageHandler = createWhatsAppMessageHandler({
    ...shared,
    sendMessage: async (_jid, content) => effects.push(content.text),
    detectLanguage: () => 'es',
  });

  const callPromise = callHandler([{
    id: 'call-first',
    from: '123@lid',
    chatId: '123@lid',
    status: 'offer',
    offline: false,
  }]);
  const messagePromise = messageHandler({
    type: 'notify',
    messages: [{
      key: { id: 'message-second', fromMe: false, remoteJid: phoneJid },
      message: { conversation: 'hola' },
    }],
  });

  const [callResult, messageResult] = await Promise.all([callPromise, messagePromise]);

  assert.equal(callResult[0].response, 'call');
  assert.equal(messageResult[0].response, 'step2');
  assert.deepEqual(effects, ['call', 'step2']);
});
