import {
  getContentType,
  jidNormalizedUser,
  normalizeMessageContent,
} from '@whiskeysockets/baileys';
import { settleWithTimeout } from './keyed_serial_queue.mjs';

const DEFAULT_CONTACT_RESOLUTION_TIMEOUT_MS = 5_000;
const DEFAULT_SEND_TIMEOUT_MS = 20_000;

const INTERACTION_TYPES = new Set([
  'conversation',
  'extendedTextMessage',
  'imageMessage',
  'videoMessage',
  'ptvMessage',
  'audioMessage',
  'documentMessage',
  'stickerMessage',
  'lottieStickerMessage',
  'stickerPackMessage',
  'albumMessage',
  'contactMessage',
  'contactsArrayMessage',
  'locationMessage',
  'liveLocationMessage',
  'productMessage',
  'orderMessage',
  'invoiceMessage',
  'buttonsResponseMessage',
  'listResponseMessage',
  'templateButtonReplyMessage',
  'interactiveResponseMessage',
  'pollCreationMessage',
  'requestPhoneNumberMessage',
]);

function isPnJid(jid) {
  return typeof jid === 'string'
    && (jid.endsWith('@s.whatsapp.net') || jid.endsWith('@hosted'));
}

function isLidJid(jid) {
  return typeof jid === 'string'
    && (jid.endsWith('@lid') || jid.endsWith('@hosted.lid'));
}

function isGroupJid(jid) {
  return typeof jid === 'string' && jid.endsWith('@g.us');
}

function normalizeJid(jid) {
  if (typeof jid !== 'string' || !jid) return '';
  try {
    return jidNormalizedUser(jid);
  } catch {
    return jid;
  }
}

export async function selectDirectMessageTarget(msg, resolvePnForLid = async () => null) {
  const remoteJid = normalizeJid(msg?.key?.remoteJid || '');
  const alternateJid = normalizeJid(msg?.key?.remoteJidAlt || '');
  if (isGroupJid(remoteJid) || isGroupJid(alternateJid) || remoteJid === 'status@broadcast') {
    return '';
  }
  if (isPnJid(remoteJid)) return remoteJid;
  if (isPnJid(alternateJid)) return alternateJid;
  if (!isLidJid(remoteJid)) return '';

  try {
    const mapped = normalizeJid(await resolvePnForLid(remoteJid));
    if (isPnJid(mapped)) return mapped;
  } catch {
    // The LID itself remains a valid direct-chat fallback.
  }
  return remoteJid;
}

export function describeInteraction(message) {
  if (message?.editedMessage || message?.groupStatusMessage || message?.groupStatusMessageV2) {
    return null;
  }
  const content = normalizeMessageContent(message);
  const contentType = getContentType(content);
  if (!content || !contentType || !INTERACTION_TYPES.has(contentType)) return null;

  const typedContent = content[contentType];
  const textCandidates = [
    content.conversation,
    content.extendedTextMessage?.text,
    content.imageMessage?.caption,
    content.videoMessage?.caption,
    content.ptvMessage?.caption,
    content.documentMessage?.caption,
    typedContent?.selectedDisplayText,
    typedContent?.title,
  ];
  const text = textCandidates.find(value => typeof value === 'string' && value.trim())?.trim() || '';
  return { contentType, text };
}

export function interactionEventId(msg, contentType) {
  const messageId = msg?.key?.id;
  if (!messageId) return '';
  const normalized = normalizeMessageContent(msg?.message);
  const typedContent = normalized?.[getContentType(normalized)];
  const parentId = msg?.message?.messageContextInfo?.messageAssociation?.parentMessageKey?.id
    || normalized?.messageContextInfo?.messageAssociation?.parentMessageKey?.id
    || typedContent?.contextInfo?.messageAssociation?.parentMessageKey?.id;
  if (parentId) return `album:${parentId}`;
  return contentType === 'albumMessage' ? `album:${messageId}` : `message:${messageId}`;
}

function messageTimestampMs(msg) {
  const raw = msg?.messageTimestamp;
  let value;
  if (typeof raw === 'number') value = raw;
  else if (typeof raw === 'bigint') value = Number(raw);
  else if (raw && typeof raw.toNumber === 'function') value = raw.toNumber();
  else value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) return null;
  return value < 1_000_000_000_000 ? value * 1000 : value;
}

export function createWhatsAppMessageHandler({
  sendMessage,
  routeInteraction,
  getResponseMessage,
  readAudio,
  detectLanguage,
  resolvePnForLid = async () => null,
  serializeClaim = async operation => operation(),
  serializeInteraction = async (_contactId, operation) => operation(),
  now = () => Date.now(),
  maxOfflineAgeMs = 15 * 60 * 1000,
  contactResolutionTimeoutMs = DEFAULT_CONTACT_RESOLUTION_TIMEOUT_MS,
  sendTimeoutMs = DEFAULT_SEND_TIMEOUT_MS,
  logger = console,
}) {
  if (typeof sendMessage !== 'function') throw new TypeError('sendMessage is required');
  if (typeof routeInteraction !== 'function') throw new TypeError('routeInteraction is required');
  if (typeof getResponseMessage !== 'function') throw new TypeError('getResponseMessage is required');
  if (typeof readAudio !== 'function') throw new TypeError('readAudio is required');
  if (typeof detectLanguage !== 'function') throw new TypeError('detectLanguage is required');
  if (typeof serializeClaim !== 'function') {
    throw new TypeError('serializeClaim must be a function');
  }
  if (typeof serializeInteraction !== 'function') {
    throw new TypeError('serializeInteraction must be a function');
  }
  if (typeof now !== 'function') throw new TypeError('now must be a function');
  if (!Number.isFinite(maxOfflineAgeMs) || maxOfflineAgeMs < 0) {
    throw new TypeError('maxOfflineAgeMs must be non-negative');
  }
  if (!Number.isFinite(contactResolutionTimeoutMs) || contactResolutionTimeoutMs <= 0) {
    throw new TypeError('contactResolutionTimeoutMs must be positive');
  }
  if (!Number.isFinite(sendTimeoutMs) || sendTimeoutMs <= 0) {
    throw new TypeError('sendTimeoutMs must be positive');
  }

  async function deliverResponse({ jid, decision }) {
    const response = getResponseMessage(decision.language, decision.responseKey) || {};
    const result = {
      status: 'handled',
      response: decision.responseKey,
      text: 'skipped',
      audio: 'skipped',
    };

    const text = typeof response.text === 'string' ? response.text.trim() : '';
    if (text) {
      try {
        await settleWithTimeout(
          Promise.resolve(sendMessage(jid, { text })),
          sendTimeoutMs,
          'El envío de texto de WhatsApp',
        );
        result.text = 'sent';
      } catch {
        result.text = 'failed';
        logger.error?.('[WA] Text delivery failed');
      }
    }

    if (response.audio) {
      try {
        const audioBuffer = await readAudio(response.audio);
        if (audioBuffer) {
          await settleWithTimeout(
            Promise.resolve(sendMessage(jid, {
              audio: audioBuffer,
              mimetype: 'audio/mpeg',
              ptt: false,
            })),
            sendTimeoutMs,
            'El envío de audio de WhatsApp',
          );
          result.audio = 'sent';
        } else {
          result.audio = 'missing';
        }
      } catch {
        result.audio = 'failed';
        logger.error?.('[WA] Audio delivery failed');
      }
    }

    logger.info?.(`[WA] Response completed type=${decision.responseKey}`);
    return result;
  }

  async function processOne(msg, type) {
    if (msg?.key?.fromMe) {
      return { status: 'ignored', reason: 'outgoing' };
    }
    if (type === 'append') {
      const timestamp = messageTimestampMs(msg);
      const age = timestamp === null ? Number.POSITIVE_INFINITY : now() - timestamp;
      if (age < -5 * 60 * 1000 || age > maxOfflineAgeMs) {
        return { status: 'ignored', reason: 'historical_append' };
      }
    }

    const interaction = describeInteraction(msg.message);
    if (!interaction) {
      return { status: 'ignored', reason: 'non_interaction' };
    }

    const eventId = interactionEventId(msg, interaction.contentType);
    if (!eventId) {
      logger.warn?.('[WA] Inbound interaction without message id ignored');
      return { status: 'ignored', reason: 'missing_event_id' };
    }

    let claimed;
    try {
      claimed = await serializeClaim(async () => {
        let jid;
        try {
          jid = await settleWithTimeout(
            selectDirectMessageTarget(msg, resolvePnForLid),
            contactResolutionTimeoutMs,
            'La resolución de identidad de WhatsApp',
          );
        } catch {
          logger.warn?.('[WA] Contact mapping timed out; using direct-chat fallback');
          jid = await selectDirectMessageTarget(msg, async () => null);
        }
        if (!jid) return { ignored: { status: 'ignored', reason: 'non_direct' } };

        const decision = await routeInteraction({
          contactId: jid,
          contactAliases: [
            normalizeJid(msg?.key?.remoteJid || ''),
            normalizeJid(msg?.key?.remoteJidAlt || ''),
            jid,
          ].filter(Boolean),
          eventId,
          kind: 'content',
          detectedLanguage: interaction.text ? detectLanguage(interaction.text) : null,
        });
        return { jid, decision };
      });
    } catch {
      logger.error?.('[WA] Interaction state failed');
      return { status: 'failed', reason: 'interaction_state_failed' };
    }

    if (claimed.ignored) return claimed.ignored;
    if (claimed.decision.duplicate) {
      return { status: 'ignored', reason: 'duplicate' };
    }

    return serializeInteraction(
      claimed.decision.contactKey || claimed.jid,
      () => deliverResponse({ jid: claimed.jid, decision: claimed.decision }),
    );
  }

  return async function handleMessageBatch({ messages = [], type } = {}) {
    if (!['notify', 'append'].includes(type) || !Array.isArray(messages)) return [];
    return Promise.all(messages.map(msg => processOne(msg, type)));
  };
}
