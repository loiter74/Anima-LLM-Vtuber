import { createHash, randomUUID } from 'node:crypto';


function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}


function contentHash(value) {
  const encoded = JSON.stringify(canonicalize(value)).replace(
    /[\u0080-\uffff]/g,
    (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`,
  );
  return createHash('sha256')
    .update(encoded, 'utf8')
    .digest('hex');
}


function resourceId(value) {
  const normalized = String(value || '').trim().toLowerCase();
  return normalized.includes(':') ? normalized : `minecraft:${normalized}`;
}


function mappingEntries(value) {
  if (Array.isArray(value)) return value;
  if (value && typeof value === 'object') {
    return Object.entries(value).map(([key, entryValue]) => ({ key, value: entryValue }));
  }
  return [];
}


function completed(definition, progress) {
  const requirements = Array.isArray(definition?.requirements) ? definition.requirements : [];
  if (requirements.length === 0) return false;
  return requirements.some((group) => (
    Array.isArray(group)
    && group.length > 0
    && group.every((criterion) => progress?.get(String(criterion)) != null)
  ));
}


export function createAdvancementAdapterV2({
  runtimeInstanceId,
  captureObservation,
  emitEvent,
  makeId = () => `advancement-event-${randomUUID()}`,
  onError = () => {},
}) {
  if (!runtimeInstanceId) throw new TypeError('runtimeInstanceId is required');
  if (typeof captureObservation !== 'function') {
    throw new TypeError('captureObservation is required');
  }
  if (typeof emitEvent !== 'function') throw new TypeError('emitEvent is required');

  let definitions = new Map();
  let progressByAdvancement = new Map();
  let active = new Set();
  let transitionSequence = 0;
  let client = null;
  let queue = Promise.resolve();

  async function emitTransition(advancementId, action) {
    transitionSequence += 1;
    const observation = await captureObservation(
      `advancement:${transitionSequence}:${action}:${advancementId}`,
    );
    if (observation.runtime_instance_id && observation.runtime_instance_id !== runtimeInstanceId) {
      throw new Error('Advancement observation belongs to a different runtime instance');
    }
    if (observation.world_identity?.runtime_instance_id !== runtimeInstanceId) {
      throw new Error('Advancement observation world identity is stale');
    }
    const eventBase = {
      schema_version: '2',
      event_id: makeId(),
      runtime_instance_id: runtimeInstanceId,
      world_identity: observation.world_identity,
      advancement_id: advancementId,
      action,
      observation_id: observation.observation_id,
      observation_hash: observation.content_hash,
      observed_at_ms: observation.captured_at_ms,
      tick: observation.tick,
      source: 'version_adapter',
    };
    const event = { ...eventBase, content_hash: contentHash(eventBase) };
    await emitEvent(event);
    return event;
  }

  async function handlePacket(packet = {}) {
    const nextDefinitions = packet.reset ? new Map() : new Map(definitions);
    const nextProgress = packet.reset ? new Map() : new Map(
      [...progressByAdvancement].map(([key, value]) => [key, new Map(value)]),
    );
    const removed = packet.identifiers || packet.removedAdvancements || [];
    for (const rawId of removed) {
      const advancementId = resourceId(rawId);
      nextDefinitions.delete(advancementId);
      nextProgress.delete(advancementId);
    }
    for (const entry of mappingEntries(packet.advancementMapping || packet.advancements)) {
      nextDefinitions.set(resourceId(entry.key), entry.value || {});
    }
    for (const entry of mappingEntries(packet.progressMapping || packet.progress)) {
      const advancementId = resourceId(entry.key);
      const criterionProgress = nextProgress.get(advancementId) || new Map();
      for (const criterion of Array.isArray(entry.value) ? entry.value : []) {
        criterionProgress.set(
          String(criterion.criterionIdentifier),
          criterion.criterionProgress,
        );
      }
      nextProgress.set(advancementId, criterionProgress);
    }

    const nextActive = new Set(
      [...nextDefinitions]
        .filter(([id, definition]) => completed(definition, nextProgress.get(id)))
        .map(([id]) => id),
    );
    const transitions = [
      ...[...active].filter((id) => !nextActive.has(id)).sort().map((id) => [id, 'remove']),
      ...[...nextActive].filter((id) => !active.has(id)).sort().map((id) => [id, 'add']),
    ];
    definitions = nextDefinitions;
    progressByAdvancement = nextProgress;
    active = nextActive;

    const events = [];
    for (const [advancementId, action] of transitions) {
      events.push(await emitTransition(advancementId, action));
    }
    return events;
  }

  function attach(nextClient) {
    if (!nextClient || typeof nextClient.on !== 'function') {
      throw new TypeError('Minecraft protocol client is required');
    }
    if (client) throw new Error('Advancement adapter is already attached');
    client = nextClient;
    client.on('advancements', onAdvancements);
  }

  function onAdvancements(packet) {
    queue = queue.then(() => handlePacket(packet)).catch(onError);
  }

  function dispose() {
    client?.removeListener('advancements', onAdvancements);
    client = null;
  }

  return Object.freeze({
    attach,
    dispose,
    handlePacket,
    getActiveAdvancements: () => [...active].sort(),
    drain: () => queue,
  });
}
