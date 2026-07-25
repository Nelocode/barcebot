import test from 'node:test';
import assert from 'node:assert/strict';

import { KeyedSerialQueue } from '../keyed_serial_queue.mjs';

test('serializa el mismo contacto sin bloquear otro contacto', async () => {
  const queue = new KeyedSerialQueue();
  const order = [];
  let releaseA;
  const blockedA = new Promise(resolve => { releaseA = resolve; });

  const firstA = queue.run('a', async () => {
    order.push('a1:start');
    await blockedA;
    order.push('a1:end');
  });
  const secondA = queue.run('a', async () => order.push('a2'));
  const contactB = queue.run('b', async () => order.push('b'));
  await contactB;

  assert.deepEqual(order, ['a1:start', 'b']);
  releaseA();
  await Promise.all([firstA, secondA]);
  assert.deepEqual(order, ['a1:start', 'b', 'a1:end', 'a2']);
});

test('un fallo no bloquea la siguiente operación del mismo contacto', async () => {
  const queue = new KeyedSerialQueue();
  await assert.rejects(queue.run('a', async () => { throw new Error('failure'); }));
  assert.equal(await queue.run('a', async () => 'recovered'), 'recovered');
});
