import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';

import {
  detectLanguage,
  detectLanguageEvidence,
  tokenizeLanguageText,
} from '../language_detection.mjs';

const contract = JSON.parse(
  fs.readFileSync(new URL('../language_contract_cases.json', import.meta.url), 'utf8'),
);
const contractCases = contract.cases;

test('cumple el corpus compartido exacto de evidencia', () => {
  for (const contractCase of contractCases) {
    assert.deepEqual(
      detectLanguageEvidence(contractCase.text),
      contractCase.expected,
      contractCase.id,
    );
  }
});

test('cuenta puntos de cÃ³digo Unicode igual que Python cerca del lÃ­mite', () => {
  for (const generatedCase of contract.generated_cases) {
    const text = generatedCase.prefix.repeat(generatedCase.repeat) + generatedCase.suffix;
    assert.deepEqual(detectLanguageEvidence(text), generatedCase.expected, generatedCase.id);
  }
});

test('normaliza Unicode y limita texto/tokens sin retener contenido', () => {
  assert.deepEqual(tokenizeLanguageText('RUBI\u0301 — français'), ['rubi', 'francais']);
  assert.equal(tokenizeLanguageText(`${'x '.repeat(400)}hola`).length, 256);
  assert.deepEqual(Object.keys(detectLanguageEvidence('hola')).sort(), [
    'explicit', 'language', 'margin', 'score', 'strong',
  ]);
});

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
