import crypto from 'crypto';
import fs from 'fs';
import path from 'path';

const STATE_VERSION = 1;
const DEFAULT_RETRY_MS = 60 * 60 * 1000;
const RATE_LIMIT_RETRY_MS = 24 * 60 * 60 * 1000;
const MAX_ACCOUNTS = 12;

const inFlight = new Set();

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function normalizedAccountId(jid) {
  const value = String(jid || '').trim().toLowerCase();
  if (!value) return '';
  const [local, server = 's.whatsapp.net'] = value.split('@', 2);
  return `${local.split(':', 1)[0]}@${server}`;
}

function readState(statePath) {
  try {
    const parsed = JSON.parse(fs.readFileSync(statePath, 'utf8'));
    if (parsed?.version === STATE_VERSION && parsed.accounts && typeof parsed.accounts === 'object') {
      return parsed;
    }
  } catch {
    // Missing, stale or malformed state is rebuilt below.
  }
  return { version: STATE_VERSION, accounts: {} };
}

function writeStateAtomic(statePath, state) {
  const directory = path.dirname(statePath);
  const temporaryPath = `${statePath}.${process.pid}.${Date.now()}.tmp`;
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(temporaryPath, JSON.stringify(state), { encoding: 'utf8', mode: 0o600 });
  try {
    fs.renameSync(temporaryPath, statePath);
  } catch (error) {
    if (error?.code !== 'EEXIST' && error?.code !== 'EPERM') {
      fs.rmSync(temporaryPath, { force: true });
      throw error;
    }
    fs.rmSync(statePath, { force: true });
    fs.renameSync(temporaryPath, statePath);
  }
}

function trimAccounts(accounts) {
  const entries = Object.entries(accounts).sort(
    (left, right) => Number(right[1]?.attemptedAt || 0) - Number(left[1]?.attemptedAt || 0),
  );
  return Object.fromEntries(entries.slice(0, MAX_ACCOUNTS));
}

function isRateLimited(error) {
  const status = Number(error?.output?.statusCode ?? error?.data?.statusCode ?? error?.statusCode);
  const message = String(error?.message || error?.data || '').toLowerCase();
  return status === 429 || message.includes('rate-overlimit') || message.includes('rate limit');
}

export async function applyWhatsAppProfilePicture({
  jid,
  updateProfilePicture,
  imagePath,
  statePath,
  logger = console,
  now = Date.now,
}) {
  const accountId = normalizedAccountId(jid);
  if (!accountId || typeof updateProfilePicture !== 'function') {
    return { status: 'missing' };
  }
  if (!fs.existsSync(imagePath)) {
    logger.warn?.('[WA] Logo de perfil no disponible');
    return { status: 'missing' };
  }

  const accountHash = sha256(accountId);
  const key = `${path.resolve(statePath)}:${accountHash}`;
  if (inFlight.has(key)) return { status: 'pending' };
  inFlight.add(key);

  try {
    const image = fs.readFileSync(imagePath);
    const imageHash = sha256(image);
    const state = readState(statePath);
    const previous = state.accounts[accountHash];
    const timestamp = Number(now());

    if (previous?.status === 'applied' && previous?.imageHash === imageHash) {
      return { status: 'unchanged' };
    }
    if (
      previous?.status === 'failed'
      && previous?.imageHash === imageHash
      && timestamp < Number(previous.retryAfter || 0)
    ) {
      return { status: 'cooldown' };
    }

    state.accounts[accountHash] = {
      imageHash,
      status: 'pending',
      attemptedAt: timestamp,
    };
    state.accounts = trimAccounts(state.accounts);
    writeStateAtomic(statePath, state);

    try {
      await updateProfilePicture(jid, image, { width: 640, height: 640 });
      state.accounts[accountHash] = {
        imageHash,
        status: 'applied',
        attemptedAt: timestamp,
        appliedAt: Number(now()),
      };
      writeStateAtomic(statePath, state);
      logger.info?.('[WA] Logo de perfil aplicado');
      return { status: 'applied' };
    } catch (error) {
      const retryDelay = isRateLimited(error) ? RATE_LIMIT_RETRY_MS : DEFAULT_RETRY_MS;
      state.accounts[accountHash] = {
        imageHash,
        status: 'failed',
        attemptedAt: timestamp,
        retryAfter: timestamp + retryDelay,
      };
      writeStateAtomic(statePath, state);
      logger.warn?.('[WA] No fue posible aplicar el logo de perfil; se reintentará más adelante');
      return { status: 'failed' };
    }
  } finally {
    inFlight.delete(key);
  }
}
