import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  createWhatsAppDeliverySafety,
  readWhatsAppSafetyConfig,
  recordWhatsAppProviderSignal,
  WhatsAppDeliveryBlockedError,
} from '../wa_delivery_safety.mjs';
import { createWhatsAppSafetyHealth } from '../wa_safety_health.mjs';

function createHarness(t, overrides = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-delivery-safety-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const healthFile = path.join(directory, 'health.json');
  const controlFile = path.join(directory, 'control.json');
  let currentTime = 1_700_000_000_000;
  const delays = [];
  const health = createWhatsAppSafetyHealth({
    filePath: healthFile,
    controlFilePath: controlFile,
    now: () => currentTime,
    logger: { warn() {} },
  });
  const config = {
    ...readWhatsAppSafetyConfig({}),
    readDelayMinMs: 0,
    readDelayMaxMs: 0,
    textDelayMinMs: 0,
    textDelayMaxMs: 0,
    textMsPerCharacter: 0,
    audioDelayMinMs: 0,
    audioDelayMaxMs: 0,
    jitterRatio: 0,
    minimumSendIntervalMs: 0,
    auxiliaryTimeoutMs: 50,
    sendTimeoutMs: 100,
    ...overrides,
  };
  const sleep = async (ms, signal) => {
    if (signal?.aborted) throw signal.reason;
    delays.push(ms);
    currentTime += ms;
  };
  return {
    health,
    healthFile,
    controlFile,
    config,
    delays,
    sleep,
    now: () => currentTime,
    advance(ms) { currentTime += ms; },
  };
}

test('environment configuration remains bounded and keeps min/max pairs coherent', () => {
  const config = readWhatsAppSafetyConfig({
    WA_TEXT_DELAY_MIN_MS: '8000',
    WA_TEXT_DELAY_MAX_MS: '10',
    WA_MAX_PENDING_SENDS: '99999',
    WA_RECONNECT_STABLE_MS: '1',
  });
  assert.equal(config.textDelayMinMs, 8_000);
  assert.equal(config.textDelayMaxMs, 8_000);
  assert.equal(config.maxPendingSends, 500);
  assert.equal(config.reconnectStableMs, 5_000);
});

test('text and voice-note deliveries emit bounded composing/recording presence', async (t) => {
  const harness = createHarness(t, {
    textDelayMinMs: 100,
    textDelayMaxMs: 500,
    textMsPerCharacter: 10,
    audioDelayMinMs: 300,
    audioDelayMaxMs: 300,
  });
  const effects = [];
  const safety = createWhatsAppDeliverySafety({
    ...harness,
    random: () => 0.5,
    sendPresenceUpdate: async (presence, jid) => effects.push(['presence', presence, jid]),
    sendMessage: async (jid, content) => effects.push(['send', jid, content]),
  });

  await safety.send('contact-a', { text: 'hola' });
  await safety.send('contact-a', { audio: Buffer.alloc(4_800), ptt: true });

  assert.deepEqual(effects.map(item => item.slice(0, 2)), [
    ['presence', 'composing'],
    ['send', 'contact-a'],
    ['presence', 'paused'],
    ['presence', 'recording'],
    ['send', 'contact-a'],
    ['presence', 'paused'],
  ]);
  assert.equal(harness.delays.reduce((total, value) => total + value, 0), 440);
});

test('bounded pacing still applies when presence publication is disabled', async (t) => {
  const harness = createHarness(t, {
    presenceEnabled: false,
    textDelayMinMs: 300,
    textDelayMaxMs: 300,
  });
  let sent = false;
  const safety = createWhatsAppDeliverySafety({
    ...harness,
    sendMessage: async () => { sent = true; },
  });

  await safety.send('contact-a', { text: 'hola' });

  assert.equal(sent, true);
  assert.equal(harness.delays.reduce((total, value) => total + value, 0), 300);
});

test('read receipt waits before opening the conversation', async (t) => {
  const harness = createHarness(t, { readDelayMinMs: 400, readDelayMaxMs: 400 });
  const effects = [];
  const key = { id: 'message-1', remoteJid: 'contact-a' };
  const safety = createWhatsAppDeliverySafety({
    ...harness,
    sendMessage: async () => {},
    readMessages: async keys => effects.push(keys),
  });

  const result = await safety.markRead(key);

  assert.equal(result.status, 'read');
  assert.deepEqual(effects, [[key]]);
  assert.equal(harness.delays.reduce((total, value) => total + value, 0), 400);
});

test('a 403 pauses delivery until an operator explicitly reviews it', async (t) => {
  const harness = createHarness(t);
  const restricted = new Error('private provider details');
  restricted.output = { statusCode: 403 };
  const safety = createWhatsAppDeliverySafety({
    ...harness,
    sendMessage: async () => { throw restricted; },
  });

  await assert.rejects(safety.send('573001234567@s.whatsapp.net', { text: 'secret text' }));
  const snapshot = harness.health.snapshot();
  assert.equal(snapshot.level, 'high');
  assert.equal(snapshot.operator_paused, true);
  assert.equal(snapshot.delivery_blocked, true);
  await assert.rejects(
    safety.send('contact-b', { text: 'next' }),
    error => error instanceof WhatsAppDeliveryBlockedError && error.code === 'operator_paused',
  );
  const persisted = fs.readFileSync(harness.healthFile, 'utf8');
  assert.equal(persisted.includes('573001234567'), false);
  assert.equal(persisted.includes('secret text'), false);
  assert.equal(persisted.includes('private provider details'), false);
});

test('a 429 in read/presence signals activates backoff before content is sent', async (t) => {
  const harness = createHarness(t);
  const limited = new Error('limited');
  limited.output = { statusCode: 429 };
  let sent = false;
  const safety = createWhatsAppDeliverySafety({
    ...harness,
    readMessages: async () => { throw limited; },
    sendPresenceUpdate: async () => { throw limited; },
    sendMessage: async () => { sent = true; },
  });

  assert.equal((await safety.markRead({ id: 'one' })).status, 'skipped');
  await assert.rejects(
    safety.send('contact-a', { text: 'hola' }),
    error => error instanceof WhatsAppDeliveryBlockedError,
  );
  assert.equal(sent, false);
  assert.equal(harness.health.snapshot().level, 'high');
  assert.ok(harness.health.snapshot().backoff_until);
});

test('connection-level 403 and 429 use the same conservative health controls', (t) => {
  const forbiddenHarness = createHarness(t);
  assert.equal(recordWhatsAppProviderSignal({
    statusCode: 403,
    health: forbiddenHarness.health,
    config: forbiddenHarness.config,
    now: forbiddenHarness.now,
  }), 'forbidden');
  assert.equal(forbiddenHarness.health.snapshot().operator_paused, true);
  assert.equal(forbiddenHarness.health.snapshot().level, 'high');

  const limitedHarness = createHarness(t);
  assert.equal(recordWhatsAppProviderSignal({
    statusCode: 429,
    health: limitedHarness.health,
    config: limitedHarness.config,
    now: limitedHarness.now,
    attempt: 2,
  }), 'rate_limited');
  assert.ok(limitedHarness.health.snapshot().backoff_until);
  assert.equal(limitedHarness.health.snapshot().level, 'high');
});

test('global send gate makes the per-minute reservation atomic across contacts', async (t) => {
  const harness = createHarness(t, { presenceEnabled: false, maxSendsPerMinute: 1 });
  const effects = [];
  const safety = createWhatsAppDeliverySafety({
    ...harness,
    sendMessage: async jid => effects.push(jid),
  });

  const results = await Promise.allSettled([
    safety.send('contact-a', { text: 'one' }),
    safety.send('contact-b', { text: 'two' }),
  ]);

  assert.deepEqual(effects, ['contact-a']);
  assert.equal(results[0].status, 'fulfilled');
  assert.equal(results[1].status, 'rejected');
  assert.equal(results[1].reason.code, 'local_rate_limit');
});

test('pending queue is bounded before network work starts', async (t) => {
  const harness = createHarness(t, { presenceEnabled: false, maxPendingSends: 1 });
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const safety = createWhatsAppDeliverySafety({
    ...harness,
    sendMessage: async () => gate,
  });

  const first = safety.send('contact-a', { text: 'one' });
  await assert.rejects(
    safety.send('contact-b', { text: 'two' }),
    error => error instanceof WhatsAppDeliveryBlockedError && error.code === 'queue_full',
  );
  release();
  await first;
});

test('a timed-out transport keeps the global gate until its final outcome is known', async (t) => {
  const harness = createHarness(t, {
    presenceEnabled: false,
    sendTimeoutMs: 15,
    circuitOpenMs: 20,
  });
  const effects = [];
  let releaseTransport;
  let markStarted;
  const transportGate = new Promise(resolve => { releaseTransport = resolve; });
  const started = new Promise(resolve => { markStarted = resolve; });
  const safety = createWhatsAppDeliverySafety({
    ...harness,
    sendMessage: async jid => {
      effects.push(`start:${jid}`);
      markStarted();
      await transportGate;
      effects.push(`finish:${jid}`);
    },
  });

  const first = safety.send('contact-a', { text: 'one' });
  await started;
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.ok(harness.health.snapshot().circuit_open_until);

  harness.advance(21);
  let secondSettled = false;
  const second = safety.send('contact-b', { text: 'two' }).then(() => {
    secondSettled = true;
  });
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(secondSettled, false);
  assert.deepEqual(effects, ['start:contact-a']);

  releaseTransport();
  await assert.rejects(first, /send_timeout/);
  await second;
  assert.deepEqual(effects, [
    'start:contact-a',
    'finish:contact-a',
    'start:contact-b',
    'finish:contact-b',
  ]);
});

test('operator pause cannot consume the later socket-close release of an unknown transport', async (t) => {
  const harness = createHarness(t, {
    presenceEnabled: false,
    sendTimeoutMs: 15,
  });
  let markStarted;
  const started = new Promise(resolve => { markStarted = resolve; });
  const safety = createWhatsAppDeliverySafety({
    ...harness,
    sendMessage: async () => {
      markStarted();
      await new Promise(() => {});
    },
  });
  let settled = false;
  const outcome = safety.send('contact-a', { text: 'one' }).then(
    value => ({ value }),
    error => ({ error }),
  ).finally(() => { settled = true; });

  await started;
  await new Promise(resolve => setTimeout(resolve, 30));
  harness.health.setOperatorPaused(true);
  safety.refreshControls();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(settled, false);

  safety.cancelAll('connection_closed');
  const result = await outcome;
  assert.match(result.error.message, /send_timeout/);
});

test('a queued response expires instead of sending long after its handler gave up', async (t) => {
  const harness = createHarness(t, {
    presenceEnabled: false,
    textDelayMinMs: 2_000,
    textDelayMaxMs: 2_000,
    queueWaitTimeoutMs: 1_000,
  });
  const effects = [];
  const safety = createWhatsAppDeliverySafety({
    ...harness,
    sendMessage: async jid => effects.push(jid),
  });

  const results = await Promise.allSettled([
    safety.send('contact-a', { text: 'one' }),
    safety.send('contact-b', { text: 'two' }),
  ]);

  assert.deepEqual(effects, ['contact-a']);
  assert.equal(results[0].status, 'fulfilled');
  assert.equal(results[1].status, 'rejected');
  assert.equal(results[1].reason.code, 'queue_timeout');
});
