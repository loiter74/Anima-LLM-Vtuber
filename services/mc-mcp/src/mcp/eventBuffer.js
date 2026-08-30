export class RuntimeEventBuffer {
  constructor(capacity = 512) {
    if (!Number.isInteger(capacity) || capacity < 1) throw new TypeError('capacity must be positive');
    this.capacity = capacity;
    this.sequence = 0;
    this.events = [];
    this.listeners = new Set();
  }

  append(event) {
    const record = { cursor: ++this.sequence, event: structuredClone(event) };
    this.events.push(record);
    if (this.events.length > this.capacity) this.events.shift();
    for (const listener of this.listeners) listener(structuredClone(record));
    return structuredClone(record);
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  listAfter(cursor = 0, limit = 100) {
    const normalizedCursor = Number.isInteger(cursor) && cursor >= 0 ? cursor : 0;
    const normalizedLimit = Math.min(Math.max(Number(limit) || 100, 1), 500);
    const oldestCursor = this.events[0]?.cursor ?? this.sequence + 1;
    const events = this.events
      .filter((record) => record.cursor > normalizedCursor)
      .slice(0, normalizedLimit)
      .map((record) => structuredClone(record));
    return {
      events,
      next_cursor: events.at(-1)?.cursor ?? normalizedCursor,
      overflowed: normalizedCursor > 0 && normalizedCursor < oldestCursor - 1,
    };
  }
}
