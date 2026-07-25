import { DisconnectReason } from '@whiskeysockets/baileys';

const INVALID_SESSION_STATUSES = new Set([
  DisconnectReason.loggedOut,
  DisconnectReason.badSession,
  DisconnectReason.connectionReplaced,
  DisconnectReason.multideviceMismatch,
  DisconnectReason.forbidden,
]);

/** Invalid credentials require a fresh QR and must not leave a dead worker alive. */
export function classifyWhatsAppDisconnect(status) {
  const reauthRequired = INVALID_SESSION_STATUSES.has(status);
  return {
    reauthRequired,
    shouldReconnect: !reauthRequired,
    terminateWorker: reauthRequired,
    reason: reauthRequired
      ? (status === DisconnectReason.loggedOut ? 'logged_out' : 'session_invalid')
      : 'transient',
  };
}
