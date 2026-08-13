import test from 'node:test';
import assert from 'node:assert/strict';

import { provisionalLanguageFromWhatsAppIdentity } from '../whatsapp_language_hint.mjs';

test('deriva un idioma provisional desde prefijos telefónicos conocidos', () => {
  assert.equal(provisionalLanguageFromWhatsAppIdentity('573001234567@s.whatsapp.net'), 'es');
  assert.equal(provisionalLanguageFromWhatsAppIdentity('34600123456@hosted'), 'es');
  assert.equal(provisionalLanguageFromWhatsAppIdentity('33612345678@s.whatsapp.net'), 'fr');
  assert.equal(provisionalLanguageFromWhatsAppIdentity('447700900123@s.whatsapp.net'), 'en');
});

test('usa el prefijo más específico dentro del plan +1', () => {
  assert.equal(provisionalLanguageFromWhatsAppIdentity('17875550123@s.whatsapp.net'), 'es');
  assert.equal(provisionalLanguageFromWhatsAppIdentity('14155550123@s.whatsapp.net'), 'en');
});

test('no infiere idioma desde LID, grupos, texto libre ni códigos ambiguos', () => {
  assert.equal(provisionalLanguageFromWhatsAppIdentity('573001234567@lid'), null);
  assert.equal(provisionalLanguageFromWhatsAppIdentity('573001234567@g.us'), null);
  assert.equal(provisionalLanguageFromWhatsAppIdentity('+57 300 123 4567'), null);
  assert.equal(provisionalLanguageFromWhatsAppIdentity('41791234567@s.whatsapp.net'), null);
});

test('puede encontrar el PN en los alias sin tratar un LID como teléfono', () => {
  assert.equal(provisionalLanguageFromWhatsAppIdentity(
    '12345@lid',
    ['12345@lid', '573001234567@s.whatsapp.net'],
  ), 'es');
});
