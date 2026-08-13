import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'crypto';
import fs from 'fs';
import os from 'os';
import path from 'path';

import { PersistentInteractionState } from '../interaction_state.mjs';

function fingerprintForTest(namespace, value) {
  return crypto.createHash('sha256').update(`${namespace}\0${String(value)}`, 'utf8').digest('hex');
}

function createStore(directory, overrides = {}) {
  return new PersistentInteractionState({
    filePath: path.join(directory, 'state.json'),
    logger: { error() {} },
    ...overrides,
  });
}

test('cada llamada distinta usa call y el contenido posterior usa step2', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'interaction-state-'));
  const store = createStore(directory);

  const first = store.register({ contactId: 'a', eventId: 'call:1', kind: 'call' });
  const second = store.register({ contactId: 'a', eventId: 'call:2', kind: 'call' });
  const third = store.register({ contactId: 'a', eventId: 'message:3', kind: 'content' });

  assert.equal(first.responseKey, 'call');
  assert.equal(second.responseKey, 'call');
  assert.equal(third.responseKey, 'step2');
  assert.deepEqual([first.phase, second.phase, third.phase], [1, 2, 2]);
});

test('contenido, llamada y contenido producen step1, call y step2', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'interaction-state-'));
  const store = createStore(directory);

  const first = store.register({ contactId: 'a', eventId: 'message:1', kind: 'content' });
  const call = store.register({ contactId: 'a', eventId: 'call:2', kind: 'call' });
  const following = store.register({ contactId: 'a', eventId: 'message:3', kind: 'content' });

  assert.deepEqual(
    [first.responseKey, call.responseKey, following.responseKey],
    ['step1', 'call', 'step2'],
  );
  assert.deepEqual([first.phase, call.phase, following.phase], [1, 2, 2]);
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

test('un idioma provisional se persiste y el primer texto detectado lo reemplaza', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'interaction-state-'));
  const filePath = path.join(directory, 'state.json');
  const store = createStore(directory);

  const image = store.register({
    contactId: '573001234567@s.whatsapp.net',
    eventId: 'message:image',
    kind: 'content',
    provisionalLanguage: 'es',
  });
  assert.equal(image.language, 'es');
  assert.equal(Object.values(JSON.parse(fs.readFileSync(filePath, 'utf8')).contacts)[0]
    .language_provisional, true);

  const text = createStore(directory).register({
    contactId: '573001234567@s.whatsapp.net',
    eventId: 'message:text',
    kind: 'content',
    detectedLanguage: 'en',
  });
  assert.equal(text.language, 'en');
  const persisted = Object.values(JSON.parse(fs.readFileSync(filePath, 'utf8')).contacts)[0];
  assert.equal(persisted.language, 'en');
  assert.equal(persisted.language_provisional, false);
});

test('texto confirmado prevalece sobre indicios y sobre un provisional al fusionar PN/LID', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'interaction-state-'));
  const store = createStore(directory);
  store.register({
    contactId: '573001234567@s.whatsapp.net',
    eventId: 'call:1',
    kind: 'call',
    provisionalLanguage: 'es',
  });
  store.register({
    contactId: '123@lid',
    eventId: 'message:1',
    kind: 'content',
    detectedLanguage: 'en',
  });
  const merged = store.register({
    contactId: '573001234567@s.whatsapp.net',
    contactAliases: ['123@lid'],
    eventId: 'message:2',
    kind: 'content',
    provisionalLanguage: 'fr',
  });
  assert.equal(merged.language, 'en');
  assert.equal(Object.values(store.contacts)[0].language_provisional, false);
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
  }).responseKey, 'call');

  const reloaded = new PersistentInteractionState({ filePath });
  assert.equal(reloaded.register({
    contactId: '123@lid',
    eventId: 'message:3',
    kind: 'content',
  }).responseKey, 'step2');
  assert.equal(Object.keys(JSON.parse(fs.readFileSync(filePath, 'utf8')).contacts).length, 1);
});

test('un reset PN pendiente prevalece sobre historial LID en ambos órdenes de identidad', () => {
  for (const pendingFirst of [false, true]) {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'interaction-state-'));
    const filePath = path.join(directory, 'state.json');
    const lid = '123@lid';
    const pn = '573001234567@s.whatsapp.net';
    const store = new PersistentInteractionState({ filePath });

    store.register({
      contactId: lid,
      eventId: 'message:old-1',
      kind: 'content',
      detectedLanguage: 'es',
    });
    store.register({
      contactId: lid,
      eventId: 'message:old-2',
      kind: 'content',
      detectedLanguage: 'es',
    });

    const persisted = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    const lidKey = fingerprintForTest('contact', lid);
    const pnKey = fingerprintForTest('contact', pn);
    persisted.contacts[pnKey] = {
      phase: 0,
      language: 'en',
      recent_events: [],
      updated_at: 0,
      reset_pending: true,
    };
    persisted.aliases[pnKey] = pnKey;
    fs.writeFileSync(filePath, JSON.stringify(persisted), 'utf8');

    const reloaded = new PersistentInteractionState({ filePath });
    const first = reloaded.register({
      contactId: pendingFirst ? pn : lid,
      contactAliases: [pendingFirst ? lid : pn],
      eventId: 'message:new-1',
      kind: 'content',
      detectedLanguage: 'fr',
    });

    assert.equal(first.responseKey, 'step1');
    assert.equal(first.language, 'en');
    assert.equal(first.phase, 1);

    const afterMerge = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    assert.equal(Object.keys(afterMerge.contacts).length, 1);
    assert.equal(afterMerge.aliases[lidKey], afterMerge.aliases[pnKey]);
    const mergedState = Object.values(afterMerge.contacts)[0];
    assert.equal(mergedState.reset_pending, undefined);
    assert.equal(mergedState.recent_events.length, 1);

    const afterRestart = new PersistentInteractionState({ filePath });
    assert.equal(afterRestart.register({
      contactId: lid,
      contactAliases: [pn],
      eventId: 'message:new-1',
      kind: 'content',
    }).duplicate, true);
    const following = afterRestart.register({
      contactId: pn,
      eventId: 'message:new-2',
      kind: 'content',
      detectedLanguage: 'fr',
    });
    assert.equal(following.responseKey, 'step2');
    assert.equal(following.language, 'en');
  }
});

test('ignora un marcador reset_pending inválido fuera de fase cero', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'interaction-state-'));
  const filePath = path.join(directory, 'state.json');
  const contact = '573001234567@s.whatsapp.net';
  const contactKey = fingerprintForTest('contact', contact);
  fs.writeFileSync(filePath, JSON.stringify({
    version: 2,
    contacts: {
      [contactKey]: {
        phase: 2,
        language: 'es',
        recent_events: [],
        updated_at: 10,
        reset_pending: true,
      },
    },
    aliases: { [contactKey]: contactKey },
  }), 'utf8');

  const store = new PersistentInteractionState({ filePath });
  const decision = store.register({
    contactId: contact,
    eventId: 'message:new',
    kind: 'content',
    detectedLanguage: 'en',
  });
  assert.equal(decision.responseKey, 'step2');
  assert.equal(decision.language, 'es');
  assert.equal(JSON.parse(fs.readFileSync(filePath, 'utf8')).contacts[contactKey].reset_pending, undefined);
});

test('una llamada consume el reset pendiente con la semántica normal de fase cero', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'interaction-state-'));
  const filePath = path.join(directory, 'state.json');
  const contact = '573001234567@s.whatsapp.net';
  const contactKey = fingerprintForTest('contact', contact);
  fs.writeFileSync(filePath, JSON.stringify({
    version: 2,
    contacts: {
      [contactKey]: {
        phase: 0,
        language: 'en',
        recent_events: [],
        updated_at: 0,
        reset_pending: true,
      },
    },
    aliases: { [contactKey]: contactKey },
  }), 'utf8');

  const store = new PersistentInteractionState({ filePath });
  const call = store.register({ contactId: contact, eventId: 'call:new', kind: 'call' });
  assert.equal(call.responseKey, 'call');
  assert.equal(call.phase, 1);
  assert.equal(call.language, 'en');
  assert.equal(JSON.parse(fs.readFileSync(filePath, 'utf8')).contacts[contactKey].reset_pending, undefined);
  assert.equal(store.register({
    contactId: contact,
    eventId: 'message:after-call',
    kind: 'content',
  }).responseKey, 'step2');
});
