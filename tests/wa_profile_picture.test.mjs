import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { applyWhatsAppProfilePicture } from '../wa_profile_picture.mjs';

function fixture() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-profile-picture-'));
  const imagePath = path.join(directory, 'logo.jpg');
  const statePath = path.join(directory, 'state.json');
  fs.writeFileSync(imagePath, Buffer.from('test-logo'));
  return { directory, imagePath, statePath };
}

test('applies the logo once per account and stores no raw phone number', async t => {
  const files = fixture();
  t.after(() => fs.rmSync(files.directory, { recursive: true, force: true }));
  const calls = [];
  const options = {
    jid: '573001234567:4@s.whatsapp.net',
    updateProfilePicture: async (...args) => calls.push(args),
    imagePath: files.imagePath,
    statePath: files.statePath,
    logger: {},
    now: () => 1_000,
  };

  assert.deepEqual(await applyWhatsAppProfilePicture(options), { status: 'applied' });
  assert.deepEqual(await applyWhatsAppProfilePicture(options), { status: 'unchanged' });
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], options.jid);
  assert.deepEqual(calls[0][2], { width: 640, height: 640 });
  assert.equal(fs.readFileSync(files.statePath, 'utf8').includes('573001234567'), false);
});

test('a different logo is applied again', async t => {
  const files = fixture();
  t.after(() => fs.rmSync(files.directory, { recursive: true, force: true }));
  let calls = 0;
  const options = {
    jid: '573001234567@s.whatsapp.net',
    updateProfilePicture: async () => { calls += 1; },
    imagePath: files.imagePath,
    statePath: files.statePath,
    logger: {},
    now: () => calls + 1_000,
  };

  await applyWhatsAppProfilePicture(options);
  fs.writeFileSync(files.imagePath, Buffer.from('replacement-logo'));
  assert.deepEqual(await applyWhatsAppProfilePicture(options), { status: 'applied' });
  assert.equal(calls, 2);
});

test('profile update failures are contained and put on cooldown', async t => {
  const files = fixture();
  t.after(() => fs.rmSync(files.directory, { recursive: true, force: true }));
  let calls = 0;
  const options = {
    jid: '573001234567@s.whatsapp.net',
    updateProfilePicture: async () => {
      calls += 1;
      const error = new Error('rate-overlimit');
      error.output = { statusCode: 429 };
      throw error;
    },
    imagePath: files.imagePath,
    statePath: files.statePath,
    logger: {},
    now: () => 1_000,
  };

  assert.deepEqual(await applyWhatsAppProfilePicture(options), { status: 'failed' });
  assert.deepEqual(await applyWhatsAppProfilePicture(options), { status: 'cooldown' });
  assert.equal(calls, 1);
});

test('missing image does not call WhatsApp', async t => {
  const files = fixture();
  t.after(() => fs.rmSync(files.directory, { recursive: true, force: true }));
  fs.rmSync(files.imagePath);
  let called = false;

  const result = await applyWhatsAppProfilePicture({
    jid: '573001234567@s.whatsapp.net',
    updateProfilePicture: async () => { called = true; },
    imagePath: files.imagePath,
    statePath: files.statePath,
    logger: {},
  });

  assert.deepEqual(result, { status: 'missing' });
  assert.equal(called, false);
});
