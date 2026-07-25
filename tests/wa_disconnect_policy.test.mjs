import test from 'node:test';
import assert from 'node:assert/strict';
import { DisconnectReason } from '@whiskeysockets/baileys';
import { classifyWhatsAppDisconnect } from '../wa_disconnect_policy.mjs';

test('logged-out credentials stop the dead worker and require a new QR', () => {
  assert.deepEqual(classifyWhatsAppDisconnect(DisconnectReason.loggedOut), {
    reauthRequired: true,
    shouldReconnect: false,
    terminateWorker: true,
    reason: 'logged_out',
  });
});

test('other invalid sessions also stop instead of appearing alive', () => {
  for (const status of [
    DisconnectReason.badSession,
    DisconnectReason.connectionReplaced,
    DisconnectReason.multideviceMismatch,
    DisconnectReason.forbidden,
  ]) {
    const decision = classifyWhatsAppDisconnect(status);
    assert.equal(decision.reauthRequired, true);
    assert.equal(decision.shouldReconnect, false);
    assert.equal(decision.terminateWorker, true);
    assert.equal(decision.reason, 'session_invalid');
  }
});

test('transient transport failures keep the reconnect loop enabled', () => {
  assert.deepEqual(classifyWhatsAppDisconnect(DisconnectReason.connectionClosed), {
    reauthRequired: false,
    shouldReconnect: true,
    terminateWorker: false,
    reason: 'transient',
  });
});
