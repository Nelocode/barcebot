/** Serialize network delivery per customer without blocking unrelated chats. */
export class KeyedSerialQueue {
  constructor() {
    this.tails = new Map();
  }

  run(key, operation) {
    const previous = this.tails.get(key) || Promise.resolve();
    const current = previous.catch(() => {}).then(operation);
    this.tails.set(key, current);
    const cleanup = () => {
      if (this.tails.get(key) === current) this.tails.delete(key);
    };
    current.then(cleanup, cleanup);
    return current;
  }
}

export async function settleWithTimeout(promise, timeoutMs, operation = 'La operación') {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error(`${operation} superó ${timeoutMs} ms`)),
          timeoutMs,
        );
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}
