import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { RuntimeEventBuffer } from '../src/mcp/eventBuffer.js';

describe('RuntimeEventBuffer', () => {
  it('returns ordered cursor pages and reports overflow', () => {
    const buffer = new RuntimeEventBuffer(2);
    buffer.append({ type: 'one' });
    buffer.append({ type: 'two' });
    buffer.append({ type: 'three' });

    assert.deepEqual(buffer.listAfter(1, 10), {
      events: [
        { cursor: 2, event: { type: 'two' } },
        { cursor: 3, event: { type: 'three' } },
      ],
      next_cursor: 3,
      overflowed: false,
    });
    assert.equal(buffer.listAfter(0, 10).overflowed, false);
  });

  it('notifies subscribers with a cloned cursor record', () => {
    const buffer = new RuntimeEventBuffer();
    const seen = [];
    const unsubscribe = buffer.subscribe((record) => seen.push(record));
    const event = { type: 'viewer', nested: { confirmed: true } };

    buffer.append(event);
    event.nested.confirmed = false;
    unsubscribe();
    buffer.append({ type: 'ignored' });

    assert.deepEqual(seen, [
      { cursor: 1, event: { type: 'viewer', nested: { confirmed: true } } },
    ]);
  });

  it('advances the cursor only through the returned page', () => {
    const buffer = new RuntimeEventBuffer();
    buffer.append({ type: 'one' });
    buffer.append({ type: 'two' });
    buffer.append({ type: 'three' });

    const first = buffer.listAfter(0, 2);
    const second = buffer.listAfter(first.next_cursor, 2);

    assert.equal(first.next_cursor, 2);
    assert.deepEqual(second.events, [{ cursor: 3, event: { type: 'three' } }]);
    assert.equal(second.next_cursor, 3);
  });
});
