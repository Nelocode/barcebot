import test from 'node:test';
import assert from 'node:assert/strict';

import { detectLanguage } from '../language_detection.mjs';

test('solo confirma idioma cuando el puntaje máximo es único', () => {
  assert.equal(detectLanguage('photo'), null);
  assert.equal(detectLanguage('video'), null);
  assert.equal(detectLanguage('ok'), null);
  assert.equal(detectLanguage('Are you available now'), 'en');
});

test('los marcadores explícitos resuelven palabras compartidas', () => {
  assert.equal(detectLanguage('photo, speak English'), 'en');
  assert.equal(detectLanguage('video en español'), 'es');
  assert.equal(detectLanguage('photo en français'), 'fr');
});
