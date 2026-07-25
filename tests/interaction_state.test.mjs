import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';

import { PersistentInteractionState } from '../interaction_state.mjs';

function createStore(directory, overrides = {}) {
  return new PersistentInteractionState({
    filePath: path.join(directory, 'state.json'),
    logger: { error() {} },
    ...overrides,
  });
}

test('primera llamada usa call y toda interacción posterior usa step2', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'interaction-state-'));
  const store = createStore(directory);

  const first = store.register({ contactId: 'a', eventId: 'call:1', kind: 'call' });
  const second = store.register({ contactId: 'a', eventId: 'call:2', kind: 'call' });
  const third = store.register({ contactId: 'a', eventId: 'message:3', kind: 'content' });

  assert.equal(first.responseKey, 'call');
  assert.equal(second.responseKey, 'step2');
  assert.equal(third.responseKey, 'step2');
  assert.deepEqual([first.phase, second.phase, third.phase], [1, 2, 2]);
});

test('primer contenido usa step1 y los contactos quedan aislados', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'interaction-state-'));
  const store = createStore(directory);

  assert.equal(store.register({ contactId: 'a', eventId: 'message:1', kind: 'content' }).responseKey, 'step1');
  assert.equal(store.register({ contactId: 'b', eventId: 'message:1', kind: 'content' }).responseKey, 'step1');
  assert.equal(store.register({ contactId: 'a', eventId: 'message:2', kind: 'content' }).responseKey, 'step2');
});

test('deduplicación y fase sobreviven un reinicio', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'interaction-state-'));
  const store = createStore(directory);
  store.register({ contactId: 'a', eventId: 'message:1', kind: 'content' });
  assert.equal(store.register({ contactId: 'a', eventId: 'message:1', kind: 'content' }).duplicate, true);

  const reloaded = createStore(directory);
  assert.equal(reloaded.register({ contactId: 'a', eventId: 'message:1', kind: 'content' }).duplicate, true);
  assert.equal(reloaded.register({ contactId: 'a', eventId: 'message:2', kind: 'content' }).responseKey, 'step2');
});

test('un evento sin texto usa idioma por defecto y el primer texto puede fijarlo', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'interaction-state-'));
  const store = createStore(directory, { defaultLanguage: 'es' });

  const call = store.register({ contactId: 'a', eventId: 'call:1', kind: 'call' });
  const text = store.register({
    contactId: 'a',
    eventId: 'message:2',
    kind: 'content',
    detectedLanguage: 'fr',
  });

  assert.equal(call.language, 'es');
  assert.equal(text.language, 'fr');
});

test('el archivo persistente no expone identificadores crudos', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'interaction-state-'));
  const store = createStore(directory);
  store.register({
    contactId: '573001234567@s.whatsapp.net',
    eventId: 'sensitive-event-id',
    kind: 'content',
  });

  const serialized = fs.readFileSync(path.join(directory, 'state.json'), 'utf8');
  assert.doesNotMatch(serialized, /573001234567|sensitive-event-id/);
});

test('fusiona LID y PN y conserva el alias después de reiniciar', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'interaction-state-'));
  const filePath = path.join(directory, 'state.json');
  const store = new PersistentInteractionState({ filePath });

  assert.equal(store.register({
    contactId: '123@lid',
    eventId: 'message:1',
    kind: 'content',
  }).responseKey, 'step1');
  assert.equal(store.register({
    contactId: '573001234567@s.whatsapp.net',
    contactAliases: ['123@lid', '573001234567@s.whatsapp.net'],
    eventId: 'call:2',
    kind: 'call',
  }).responseKey, 'step2');

  const reloaded = new PersistentInteractionState({ filePath });
  assert.equal(reloaded.register({
    contactId: '123@lid',
    eventId: 'message:3',
    kind: 'content',
  }).responseKey, 'step2');
  assert.equal(Object.keys(JSON.parse(fs.readFileSync(filePath, 'utf8')).contacts).length, 1);
});
