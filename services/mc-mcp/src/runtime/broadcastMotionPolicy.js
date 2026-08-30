import { createHash } from 'node:crypto';


export const PRESENTATION_MODES = Object.freeze(['off', 'visual_only', 'full']);
export const PRESENTATION_TEMPOS = Object.freeze(['brisk', 'normal', 'calm']);
export const DEFAULT_PRESENTATION_SEED = 'animetta-live-v1';

const DEADLINE_SETTLEMENT_RESERVE_MS = 2_000;
const TEMPO = Object.freeze({
  brisk: Object.freeze({ capMs: 600 }),
  normal: Object.freeze({ capMs: 900 }),
  calm: Object.freeze({ capMs: 1_100 }),
});
const BEAT_RANGES = Object.freeze({
  scan: Object.freeze([90, 160]),
  pre_action: Object.freeze([100, 180]),
  post_result: Object.freeze([120, 220]),
  recovery: Object.freeze([180, 320]),
});
const EMPTY_USAGE = Object.freeze({ anchorCount: 0, dwellMs: 0 });


function boolEnv(value) {
  return String(value || '').trim().toLowerCase() === 'true';
}


function strictMode(value) {
  if (PRESENTATION_MODES.includes(value)) return value;
  throw new TypeError(`Invalid presentation mode: ${String(value)}`);
}


function strictTempo(value) {
  if (PRESENTATION_TEMPOS.includes(value)) return value;
  throw new TypeError(`Invalid presentation tempo: ${String(value)}`);
}


export function resolvePresentationConfig({
  mode = process.env.GAMEBOT_PRESENTATION_MODE ?? 'off',
  tempo = process.env.GAMEBOT_PRESENTATION_TEMPO ?? 'normal',
  seed = process.env.GAMEBOT_PRESENTATION_SEED ?? DEFAULT_PRESENTATION_SEED,
  forceOff = process.env.MC_MCP_PRESENTATION_FORCE_OFF,
} = {}) {
  const normalizedSeed = String(seed);
  if (typeof seed !== 'string' || normalizedSeed.trim().length < 1 || normalizedSeed.length > 128) {
    throw new TypeError('Presentation seed must be a non-empty string of at most 128 characters');
  }
  const configuredMode = strictMode(mode);
  return Object.freeze({
    mode: boolEnv(forceOff) ? 'off' : configuredMode,
    tempo: strictTempo(tempo),
    seed: normalizedSeed,
  });
}


export function presentationSeedDigest(seed) {
  return createHash('sha256').update(String(seed), 'utf8').digest('hex');
}


function fraction(seed) {
  const digest = createHash('sha256').update(seed, 'utf8').digest();
  return digest.readUInt32BE(0) / 0xffffffff;
}


export function deterministicPresentationValue({
  seed,
  correlationId,
  capability,
  phase,
  ordinal,
  minimum,
  maximum,
}) {
  const unit = fraction([seed, correlationId, capability, phase, ordinal].join('|'));
  return minimum + ((maximum - minimum) * unit);
}


function plainPosition(position) {
  if (!position || !['x', 'y', 'z'].every((axis) => Number.isFinite(position[axis]))) {
    return null;
  }
  return Object.freeze({
    x: Number(position.x),
    y: Number(position.y),
    z: Number(position.z),
  });
}


function targetAngles(snapshot, target) {
  const position = plainPosition(snapshot.position);
  const eyeHeight = snapshot.eyeHeight;
  if (!position || !Number.isFinite(eyeHeight)) return null;
  const dx = target.x - position.x;
  const dy = target.y - (position.y + eyeHeight);
  const dz = target.z - position.z;
  const horizontal = Math.hypot(dx, dz);
  return Object.freeze({
    yaw: Math.atan2(-dx, -dz),
    pitch: Math.atan2(dy, Math.max(0.001, horizontal)),
  });
}


function beatKind(phase) {
  if (['assessing', 'locating', 'moving'].includes(phase)) return 'scan';
  if (['verifying', 'completed'].includes(phase)) return 'post_result';
  if (['recovering', 'failed', 'cancelled'].includes(phase)) return 'recovery';
  return 'pre_action';
}


function normalizeUsage(usage) {
  const anchorCount = Number(usage?.anchorCount);
  const dwellMs = Number(usage?.dwellMs);
  if (
    !Number.isInteger(anchorCount)
    || anchorCount < 0
    || !Number.isFinite(dwellMs)
    || dwellMs < 0
  ) return EMPTY_USAGE;
  return Object.freeze({ anchorCount, dwellMs });
}


function skipped(reason, usage, safety = null) {
  return Object.freeze({
    applied: false,
    reason,
    safety,
    nextUsage: usage,
    commands: Object.freeze([]),
  });
}


export function presentationSafetyState(snapshot, capability) {
  const remainingMs = snapshot?.remainingMs;
  const fallDistance = snapshot?.fallDistance;
  const health = snapshot?.health;
  const food = snapshot?.food;
  if (
    !snapshot
    || snapshot.connected !== true
    || snapshot.cancelled !== false
    || !Number.isFinite(remainingMs)
    || remainingMs < DEADLINE_SETTLEMENT_RESERVE_MS
    || !plainPosition(snapshot.position)
    || !Number.isFinite(snapshot.eyeHeight)
    || !Number.isFinite(snapshot.yaw)
    || snapshot.onGround !== true
    || !Number.isFinite(fallDistance)
    || fallDistance > 0.5
    || !Number.isFinite(health)
    || health < 6
    || !Number.isFinite(food)
    || food < 6
    || snapshot.environmentKnown !== true
    || typeof snapshot.inFluid !== 'boolean'
    || snapshot.inFluid
    || typeof snapshot.headObstructed !== 'boolean'
    || snapshot.headObstructed
    || typeof snapshot.nearbyHostile !== 'boolean'
    || snapshot.nearbyHostile
  ) return 'hazard_or_urgent';

  const owners = snapshot.owners;
  if (
    !owners
    || owners.unknown === true
    || capability === 'attack'
    || owners.combat === true
    || owners.dig === true
    || owners.container === true
    || owners.navigation === true
    || owners.controls === true
    || remainingMs < 5_000
  ) return 'owned_or_constrained';
  return 'safe_window';
}


export class BroadcastMotionPolicy {
  constructor(config = resolvePresentationConfig()) {
    this.config = resolvePresentationConfig(config);
    Object.freeze(this);
  }

  decideFocus({
    snapshot,
    usage = EMPTY_USAGE,
    correlationId,
    capability,
    phase,
    ordinal = 0,
    target = null,
    heldItemName = null,
  }) {
    const normalizedUsage = normalizeUsage(usage);
    if (this.config.mode === 'off') return skipped('mode_off', normalizedUsage);

    let angles;
    let anchor;
    if (heldItemName !== null) {
      if (
        typeof heldItemName !== 'string'
        || heldItemName.length < 1
        || snapshot?.heldItemName !== heldItemName
      ) return skipped('no_true_held_item', normalizedUsage);
      const yaw = snapshot?.yaw;
      if (!Number.isFinite(yaw)) return skipped('unknown_orientation', normalizedUsage);
      angles = Object.freeze({ yaw, pitch: -0.65 });
      anchor = Object.freeze({ kind: 'held_item', name: heldItemName });
    } else {
      anchor = plainPosition(target);
      if (!anchor) return skipped('no_true_target', normalizedUsage);
      angles = targetAngles(snapshot || {}, anchor);
      if (!angles) return skipped('unknown_orientation', normalizedUsage);
    }

    const safety = presentationSafetyState(snapshot, capability);
    if (safety !== 'safe_window') return skipped(safety, normalizedUsage, safety);
    if (normalizedUsage.anchorCount >= 2) {
      return skipped('anchor_budget_exhausted', normalizedUsage, safety);
    }

    const duration = (minimum, maximum, suffix) => Math.round(
      deterministicPresentationValue({
        seed: this.config.seed,
        correlationId,
        capability,
        phase,
        ordinal: `${ordinal}:${suffix}`,
        minimum,
        maximum,
      }),
    );
    const orientMs = duration(80, 140, 'orient');
    const beat = beatKind(phase);
    const [beatMinimum, beatMaximum] = BEAT_RANGES[beat];
    const holdMs = duration(beatMinimum, beatMaximum, beat);
    const plannedMs = orientMs + holdMs;
    const available = Math.max(0, TEMPO[this.config.tempo].capMs - normalizedUsage.dwellMs);
    const settlementReserveMs = snapshot.settlementReserveMs;
    if (
      !Number.isFinite(settlementReserveMs)
      || settlementReserveMs < DEADLINE_SETTLEMENT_RESERVE_MS
      || plannedMs > available
      || snapshot.remainingMs <= plannedMs + settlementReserveMs
    ) return skipped('presentation_budget_unavailable', normalizedUsage, safety);

    const yawOffset = deterministicPresentationValue({
      seed: this.config.seed,
      correlationId,
      capability,
      phase,
      ordinal: `${ordinal}:yaw`,
      minimum: -0.045,
      maximum: 0.045,
    });
    const pitchOffset = deterministicPresentationValue({
      seed: this.config.seed,
      correlationId,
      capability,
      phase,
      ordinal: `${ordinal}:pitch`,
      minimum: -0.025,
      maximum: 0.025,
    });
    const nextUsage = Object.freeze({
      anchorCount: normalizedUsage.anchorCount + 1,
      dwellMs: normalizedUsage.dwellMs + plannedMs,
    });
    const commands = Object.freeze([
      Object.freeze({
        type: 'look',
        yaw: angles.yaw + yawOffset,
        pitch: angles.pitch + pitchOffset,
        force: true,
      }),
      Object.freeze({ type: 'wait', delayMs: orientMs, reserveMs: settlementReserveMs }),
      Object.freeze({
        type: 'look',
        yaw: angles.yaw,
        pitch: angles.pitch,
        force: true,
      }),
      Object.freeze({ type: 'wait', delayMs: holdMs, reserveMs: settlementReserveMs }),
    ]);
    return Object.freeze({
      applied: true,
      orient_ms: orientMs,
      beat_ms: holdMs,
      target: anchor,
      safety,
      beat,
      nextUsage,
      commands,
    });
  }
}
