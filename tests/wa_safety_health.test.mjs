import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { createWhatsAppSafetyHealth } from '../wa_safety_health.mjs';

function harness(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-safety-health-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const filePath = path.join(directory, 'health.json');
  const controlFilePath = path.join(directory, 'control.json');
  let currentTime = 1_700_000_000_000;
  const health = createWhatsAppSafetyHealth({
    filePath,
    controlFilePath,
    now: () => currentTime,
    logger: { warn() {} },
  });
  return {
    filePath,
    controlFilePath,
    health,
    advance(ms) { currentTime += ms; },
  };
}

test('risk windows move from low to moderate and high with low-cardinality events', (t) => {
  const { health } = harness(t);
  assert.equal(health.snapshot().level, 'low');

  health.record('delivery_failure');
  health.record('delivery_failure');
  assert.equal(health.snapshot().level, 'moderate');
  assert.deepEqual(health.snapshot().reasons, ['delivery_failures']);

  for (let index = 0; index < 3; index += 1) health.record('delivery_failure');
  assert.equal(health.snapshot().level, 'high');
  assert.equal(health.snapshot().counts.delivery_failures_15m, 5);
});

test('worker heartbeat refreshes telemetry without adding traffic events', (t) => {
  const { filePath, health, advance } = harness(t);
  const before = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  advance(30_000);
  health.touch();
  const after = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  assert.equal(after.updated_at, before.updated_at + 30_000);
  assert.deepEqual(after.events, before.events);
});

test('operator pause is synchronized from the panel without exposing extra fields', (t) => {
  const { controlFilePath, health, advance } = harness(t);
  const control = JSON.parse(fs.readFileSync(controlFilePath, 'utf8'));
  control.operator_paused = true;
  control.pause_updated_at += 1;
  control.jid = '573001234567@s.whatsapp.net';
  control.message = 'private';
  fs.writeFileSync(controlFilePath, JSON.stringify(control));
  advance(2);

  const snapshot = health.snapshot();
  assert.equal(snapshot.operator_paused, true);
  assert.equal(snapshot.delivery_blocked, true);
  assert.equal(Object.hasOwn(snapshot, 'jid'), false);
  assert.equal(Object.hasOwn(snapshot, 'message'), false);
});

test('expired windows and automatic controls clear while an operator pause remains', (t) => {
  const { health, advance } = harness(t);
  health.record('rate_limited');
  health.setBackoffUntil(1_700_000_030_000);
  health.setCircuitOpenUntil(1_700_000_030_000);
  health.setOperatorPaused(true);
  assert.equal(health.snapshot().level, 'high');

  advance(61 * 60_000);
  const snapshot = health.snapshot();
  assert.equal(snapshot.level, 'moderate');
  assert.deepEqual(snapshot.reasons, ['operator_paused']);
  assert.equal(snapshot.backoff_until, null);
  assert.equal(snapshot.circuit_open_until, null);
  assert.equal(snapshot.operator_paused, true);
});

test('high-signal provider events survive a large volume of ordinary sends', (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-safety-retention-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const filePath = path.join(directory, 'health.json');
  const controlFilePath = path.join(directory, 'control.json');
  const currentTime = 1_700_000_000_000;
  fs.writeFileSync(filePath, JSON.stringify({
    schema_version: 1,
    updated_at: currentTime,
    operator_paused: false,
    pause_updated_at: currentTime,
    backoff_until: null,
    circuit_open_until: null,
    events: [
      { type: 'forbidden', at: currentTime - 10_000 },
      ...Array.from({ length: 700 }, (_, index) => ({
        type: 'outgoing',
        at: currentTime - 9_000 + index,
      })),
    ],
  }));

  const health = createWhatsAppSafetyHealth({
    filePath,
    controlFilePath,
    now: () => currentTime,
    logger: { warn() {} },
  });

  const snapshot = health.snapshot();
  assert.equal(snapshot.level, 'high');
  assert.equal(snapshot.counts.forbidden_60m, 1);
  assert.equal(snapshot.counts.outgoing_1m, 500);
});
