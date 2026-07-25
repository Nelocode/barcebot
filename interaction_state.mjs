import crypto from 'crypto';
import fs from 'fs';
import path from 'path';

const VALID_LANGUAGES = new Set(['es', 'en', 'fr']);
const VALID_KINDS = new Set(['call', 'content']);

function fingerprint(namespace, value) {
  return crypto.createHash('sha256').update(`${namespace}\0${String(value)}`, 'utf8').digest('hex');
}

export class PersistentInteractionState {
  constructor({
    filePath,
    defaultLanguage = 'es',
    maxRecentEvents = 256,
    now = () => Date.now(),
    logger = console,
  }) {
    if (!filePath) throw new TypeError('filePath is required');
    if (!VALID_LANGUAGES.has(defaultLanguage)) {
      throw new TypeError('defaultLanguage must be es, en, or fr');
    }
    if (!Number.isInteger(maxRecentEvents) || maxRecentEvents < 1) {
      throw new TypeError('maxRecentEvents must be a positive integer');
    }

    this.filePath = filePath;
    this.defaultLanguage = defaultLanguage;
    this.maxRecentEvents = maxRecentEvents;
    this.now = now;
    this.logger = logger;
    this.contacts = {};
    this.aliases = {};
    this.load();
  }

  load() {
    if (!fs.existsSync(this.filePath)) return;
    try {
      const parsed = JSON.parse(fs.readFileSync(this.filePath, 'utf8'));
      if (!parsed.contacts || typeof parsed.contacts !== 'object' || Array.isArray(parsed.contacts)) {
        throw new TypeError('contacts is not an object');
      }

      for (const [contactKey, raw] of Object.entries(parsed.contacts)) {
        if (!raw || typeof raw !== 'object' || ![0, 1, 2].includes(raw.phase)) continue;
        this.contacts[contactKey] = {
          phase: raw.phase,
          language: VALID_LANGUAGES.has(raw.language) ? raw.language : null,
          recent_events: Array.isArray(raw.recent_events)
            ? raw.recent_events.filter(item => typeof item === 'string').slice(-this.maxRecentEvents)
            : [],
          updated_at: Number.isFinite(raw.updated_at) ? raw.updated_at : 0,
        };
      }
      if (parsed.aliases && typeof parsed.aliases === 'object' && !Array.isArray(parsed.aliases)) {
        for (const [aliasKey, contactKey] of Object.entries(parsed.aliases)) {
          if (typeof contactKey === 'string' && this.contacts[contactKey]) {
            this.aliases[aliasKey] = contactKey;
          }
        }
      }
    } catch {
      this.logger.error?.('[STATE] Interaction state could not be loaded; starting empty');
      this.contacts = {};
      this.aliases = {};
    }
  }

  save() {
    try {
      fs.mkdirSync(path.dirname(this.filePath), { recursive: true });
      const temporaryPath = `${this.filePath}.tmp`;
      fs.writeFileSync(
        temporaryPath,
        JSON.stringify({ version: 2, contacts: this.contacts, aliases: this.aliases }),
        'utf8',
      );
      fs.renameSync(temporaryPath, this.filePath);
      return true;
    } catch {
      this.logger.error?.('[STATE] Interaction state could not be persisted');
      return false;
    }
  }

  register({
    contactId,
    contactAliases = [],
    eventId,
    kind,
    detectedLanguage = null,
  }) {
    if (contactId === undefined || contactId === null || contactId === '') {
      throw new TypeError('contactId is required');
    }
    if (eventId === undefined || eventId === null || eventId === '') {
      throw new TypeError('eventId is required');
    }
    if (!VALID_KINDS.has(kind)) throw new TypeError('kind must be call or content');
    if (!VALID_LANGUAGES.has(detectedLanguage)) detectedLanguage = null;

    const identityValues = [contactId, ...(Array.isArray(contactAliases) ? contactAliases : [])]
      .filter(value => value !== undefined && value !== null && value !== '');
    const identityKeys = [...new Set(identityValues.map(value => fingerprint('contact', value)))];
    const primaryKey = identityKeys[0];
    const eventKey = fingerprint('event', eventId);
    const resolvedKeys = [...new Set(identityKeys.map(key => this.aliases[key] || key))];
    const existingKeys = resolvedKeys.filter(key => this.contacts[key]);
    const canonicalKey = existingKeys[0] || primaryKey;
    const states = existingKeys.map(key => this.contacts[key]);
    const state = states[0] || {
      phase: 0,
      language: null,
      recent_events: [],
      updated_at: 0,
    };

    // When a PN and a LID are finally observed together, merge both histories
    // and persist every alias to one canonical state.
    for (const candidate of states.slice(1)) {
      state.phase = Math.max(state.phase, candidate.phase);
      state.language ||= candidate.language;
      state.updated_at = Math.max(state.updated_at, candidate.updated_at);
      state.recent_events = [...new Set([
        ...state.recent_events,
        ...candidate.recent_events,
      ])].slice(-this.maxRecentEvents);
    }
    for (const oldKey of existingKeys.slice(1)) delete this.contacts[oldKey];
    for (const [aliasKey, targetKey] of Object.entries(this.aliases)) {
      if (existingKeys.includes(targetKey)) this.aliases[aliasKey] = canonicalKey;
    }
    for (const identityKey of identityKeys) this.aliases[identityKey] = canonicalKey;
    this.contacts[canonicalKey] = state;

    if (state.recent_events.includes(eventKey)) {
      const persisted = this.save();
      return {
        duplicate: true,
        phase: state.phase,
        responseKey: null,
        language: state.language || this.defaultLanguage,
        contactKey: canonicalKey,
        persisted,
      };
    }

    if (!state.language && detectedLanguage) state.language = detectedLanguage;
    const language = state.language || this.defaultLanguage;

    let responseKey;
    if (state.phase === 0) {
      responseKey = kind === 'call' ? 'call' : 'step1';
      state.phase = 1;
    } else {
      responseKey = 'step2';
      state.phase = 2;
    }

    state.recent_events.push(eventKey);
    if (state.recent_events.length > this.maxRecentEvents) {
      state.recent_events.splice(0, state.recent_events.length - this.maxRecentEvents);
    }
    state.updated_at = this.now();
    const persisted = this.save();

    return {
      duplicate: false,
      phase: state.phase,
      responseKey,
      language,
      contactKey: canonicalKey,
      persisted,
    };
  }
}
