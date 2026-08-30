import { PublicLiveEvents } from '@/shared/contracts/socket-events'
import type {
  LivestreamNarrationEmotion,
  LivestreamNarrationStateEvent,
  LivestreamNarrationSpeechState,
  MinecraftActivityProjectionEvent,
  MinecraftPublicActivityFocus,
  MinecraftPublicActivityFocusKind,
  MinecraftPublicActivityIntent,
  MinecraftPublicActivityOutcome,
  MinecraftPublicActivityPhase,
  MinecraftPublicActivityProgress,
  MinecraftPublicActivityProgressUnit,
} from '@/shared/contracts/socket-events'
import type { LiveSocket } from '@/shared/transport/liveSocket'

const IDENTIFIER_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9:._/-]*$/
const CODE_PATTERN = /^[a-z][a-z0-9_-]*$/
const ACTIVITY_EVENT_PATTERN = /^activity:([1-9][0-9]*)$/
const PHASES = new Set<MinecraftPublicActivityPhase>([
  'planning',
  'observing',
  'committed',
  'acting',
  'checking',
  'recovering',
  'finished',
])
const INTENTS = new Set<MinecraftPublicActivityIntent>([
  'acquire',
  'craft',
  'build',
  'travel',
  'combat',
  'survive',
  'learn',
  'discover',
  'interact',
])
const FOCUS_KINDS = new Set<MinecraftPublicActivityFocusKind>([
  'item',
  'entity',
  'place',
  'structure',
  'condition',
])
const PROGRESS_UNITS = new Set<MinecraftPublicActivityProgressUnit>([
  'objectives',
  'items',
  'blocks',
  'actions',
])
const OUTCOMES = new Set<MinecraftPublicActivityOutcome>([
  'active',
  'succeeded',
  'failed',
  'cancelled',
  'blocked',
])
const NARRATION_EMOTIONS = new Set<LivestreamNarrationEmotion>([
  'thinking',
  'confident',
  'focused',
  'alert',
  'relieved',
])
const SPEECH_STATES = new Set<LivestreamNarrationSpeechState>([
  'none',
  'queued',
  'speaking',
  'completed',
  'cancelled',
])

const PHASE_LABELS: Readonly<Record<string, string>> = {
  plan: '计划',
  planning: '计划',
  observe: '观察',
  observing: '观察',
  observation: '观察',
  commit: '准备',
  commitment: '准备',
  committed: '确定',
  act: '执行',
  acting: '执行',
  action: '执行',
  check: '检查',
  checking: '检查',
  verify: '验证',
  verifying: '验证',
  recover: '调整',
  recovering: '调整',
  recovery: '调整',
  complete: '完成',
  completed: '完成',
  finished: '结果',
  terminal: '结果',
}

const INTENT_LABELS: Readonly<Record<string, string>> = {
  acquire: '收集',
  craft: '制作',
  build: '搭建',
  travel: '前往',
  combat: '应对',
  survive: '确保安全',
  learn: '学习',
  discover: '探索',
  interact: '处理',
}

const PROGRESS_UNIT_LABELS: Readonly<Record<string, string>> = {
  objectives: '目标',
  items: '件',
  blocks: '方块',
  actions: '步',
}

const OUTCOME_LABELS: Readonly<Record<MinecraftPublicActivityOutcome, string>> = {
  active: '进行中',
  succeeded: '已完成',
  failed: '未成功',
  cancelled: '已取消',
  blocked: '受阻',
}

const SPEECH_STATE_RANK: Readonly<Record<LivestreamNarrationSpeechState, number>> = {
  none: 0,
  queued: 1,
  speaking: 2,
  completed: 3,
  cancelled: 3,
}

export interface PublicActivityItem extends MinecraftActivityProjectionEvent {
  phaseLabel: string
  visualText: string
}

export interface PublicActivityView {
  renderPublicActivities(activities: readonly PublicActivityItem[]): void
  setPublicNarration(narration: LivestreamNarrationStateEvent | null): void
}

export interface PublicActivityController {
  readonly activities: readonly PublicActivityItem[]
  readonly narration: LivestreamNarrationStateEvent | null
  dispose(): void
}

export interface PublicActivityControllerOptions {
  maxActivities?: number
  onVisualCue?: (cue: PublicLive2DCue) => void
}

export interface PublicLive2DCue {
  sourceEventId: string
  phase: MinecraftPublicActivityPhase
  emotion: LivestreamNarrationEmotion
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function boundedText(value: unknown, maximumLength: number): string | null {
  if (typeof value !== 'string') return null
  const text = value.trim()
  return text && text.length <= maximumLength ? text : null
}

function identifier(value: unknown, maximumLength: number): string | null {
  const text = boundedText(value, maximumLength)
  return text && IDENTIFIER_PATTERN.test(text) ? text : null
}

function code(value: unknown, maximumLength = 64): string | null {
  const text = boundedText(value, maximumLength)
  return text && CODE_PATTERN.test(text) ? text : null
}

function optionalText(
  record: Record<string, unknown>,
  key: string,
  maximumLength: number,
): string | null | undefined {
  if (!(key in record)) return undefined
  if (record[key] === undefined || record[key] === null) return undefined
  return boundedText(record[key], maximumLength)
}

function parseFocus(value: unknown): MinecraftPublicActivityFocus | null {
  if (!isRecord(value)) return null
  const kind = code(value.kind)
  const label = boundedText(value.label, 64)
  return kind && FOCUS_KINDS.has(kind as MinecraftPublicActivityFocusKind) && label
    ? { kind: kind as MinecraftPublicActivityFocusKind, label }
    : null
}

function parseProgress(value: unknown): MinecraftPublicActivityProgress | null {
  if (!isRecord(value)) return null
  const { current, total } = value
  const unit = code(value.unit, 32)
  if (
    typeof current !== 'number' ||
    !Number.isFinite(current) ||
    !Number.isInteger(current) ||
    current < 0 ||
    typeof total !== 'number' ||
    !Number.isFinite(total) ||
    !Number.isInteger(total) ||
    total <= 0 ||
    current > total ||
    !unit ||
    !PROGRESS_UNITS.has(unit as MinecraftPublicActivityProgressUnit)
  ) {
    return null
  }
  return { current, total, unit: unit as MinecraftPublicActivityProgressUnit }
}

export function publicActivitySequence(eventId: string): number | null {
  const match = ACTIVITY_EVENT_PATTERN.exec(eventId)
  if (!match) return null
  const sequence = Number(match[1])
  return Number.isSafeInteger(sequence) ? sequence : null
}

export function parseMinecraftActivityProjection(
  value: unknown,
): MinecraftActivityProjectionEvent | null {
  if (
    !isRecord(value) ||
    value.schema_version !== '1' ||
    value.event !== 'minecraft.activity.projection' ||
    value.projection_kind !== 'activity' ||
    value.entity_id !== 'minecraft'
  ) {
    return null
  }
  const eventId = identifier(value.event_id, 512)
  const eventSequence = eventId ? publicActivitySequence(eventId) : null
  const missionId = optionalText(value, 'mission_id', 128)
  const projectionVersion = value.projection_version
  const occurredAt = value.occurred_at_ms
  const payload = value.payload
  if (
    !eventId ||
    eventSequence === null ||
    missionId === null ||
    !Number.isInteger(projectionVersion) ||
    (projectionVersion as number) <= 0 ||
    projectionVersion !== eventSequence ||
    !Number.isInteger(occurredAt) ||
    (occurredAt as number) < 0 ||
    !isRecord(payload)
  ) {
    return null
  }

  const phase = code(payload.phase)
  const rawIntent = payload.intent
  const intent =
    rawIntent === undefined || rawIntent === null
      ? undefined
      : code(rawIntent) && INTENTS.has(rawIntent as MinecraftPublicActivityIntent)
        ? (rawIntent as MinecraftPublicActivityIntent)
        : null
  const focus =
    payload.focus === undefined || payload.focus === null ? undefined : parseFocus(payload.focus)
  const progress =
    payload.progress === undefined || payload.progress === null
      ? undefined
      : parseProgress(payload.progress)
  const outcome = payload.outcome
  const terminalOutcome = outcome !== undefined && outcome !== 'active'
  if (
    !phase ||
    !PHASES.has(phase as MinecraftPublicActivityPhase) ||
    intent === null ||
    focus === null ||
    progress === null ||
    typeof outcome !== 'string' ||
    !OUTCOMES.has(outcome as MinecraftPublicActivityOutcome) ||
    terminalOutcome !== (phase === 'finished')
  ) {
    return null
  }

  return {
    schema_version: '1',
    event: 'minecraft.activity.projection',
    event_id: eventId,
    projection_kind: 'activity',
    projection_version: projectionVersion as number,
    occurred_at_ms: occurredAt as number,
    ...(missionId === undefined ? {} : { mission_id: missionId }),
    entity_id: 'minecraft',
    payload: {
      phase: phase as MinecraftPublicActivityPhase,
      ...(intent === undefined ? {} : { intent }),
      ...(focus === undefined ? {} : { focus }),
      ...(progress === undefined ? {} : { progress }),
      outcome: outcome as MinecraftPublicActivityOutcome,
    },
  }
}

export function parseLivestreamNarrationState(
  value: unknown,
): LivestreamNarrationStateEvent | null {
  if (!isRecord(value) || value.schema_version !== '1') return null
  const cueId = identifier(value.cue_id, 512)
  const sourceEventId = identifier(value.source_event_id, 512)
  const taskId = optionalText(value, 'task_id', 128)
  const phase = code(value.phase)
  const visualText = boundedText(value.visual_text, 80)
  const emotion = code(value.emotion, 32)
  const speechState = code(value.speech_state, 32)
  const occurredAt = value.occurred_at_ms
  if (
    !cueId ||
    !sourceEventId ||
    taskId === null ||
    !phase ||
    !PHASES.has(phase as MinecraftPublicActivityPhase) ||
    !visualText ||
    !emotion ||
    !NARRATION_EMOTIONS.has(emotion as LivestreamNarrationEmotion) ||
    !speechState ||
    !SPEECH_STATES.has(speechState as LivestreamNarrationSpeechState) ||
    !Number.isInteger(occurredAt) ||
    (occurredAt as number) < 0 ||
    publicActivitySequence(sourceEventId) === null
  ) {
    return null
  }
  return {
    schema_version: '1',
    cue_id: cueId,
    source_event_id: sourceEventId,
    ...(taskId === undefined ? {} : { task_id: taskId }),
    phase: phase as MinecraftPublicActivityPhase,
    visual_text: visualText,
    emotion: emotion as LivestreamNarrationEmotion,
    speech_state: speechState as LivestreamNarrationSpeechState,
    occurred_at_ms: occurredAt as number,
  }
}

export function publicActivityPhaseLabel(phase: string): string {
  return PHASE_LABELS[phase] ?? phase.replaceAll('_', ' ').replaceAll('-', ' ')
}

function progressText(progress: MinecraftPublicActivityProgress): string {
  return `${progress.current}/${progress.total} ${PROGRESS_UNIT_LABELS[progress.unit] ?? progress.unit}`
}

export function publicActivityVisualText(event: MinecraftActivityProjectionEvent): string {
  const { payload } = event
  const phaseLabel = publicActivityPhaseLabel(payload.phase)
  const details: string[] = []
  if (payload.intent) details.push(INTENT_LABELS[payload.intent] ?? payload.intent)
  if (payload.focus?.label && payload.focus.label !== payload.intent)
    details.push(payload.focus.label)
  if (payload.progress) details.push(progressText(payload.progress))
  if (payload.outcome && payload.outcome !== 'active') {
    details.push(OUTCOME_LABELS[payload.outcome])
  }
  return [phaseLabel, ...details].join(' · ')
}

function compareActivities(left: PublicActivityItem, right: PublicActivityItem): number {
  return (
    publicActivitySequence(left.event_id)! - publicActivitySequence(right.event_id)! ||
    left.occurred_at_ms - right.occurred_at_ms ||
    left.event_id.localeCompare(right.event_id)
  )
}

export function createPublicActivityController(
  socket: LiveSocket,
  view: PublicActivityView,
  options: PublicActivityControllerOptions = {},
): PublicActivityController {
  const maxActivities = Math.max(1, Math.min(100, options.maxActivities ?? 12))
  const activities: PublicActivityItem[] = []
  const seenActivityIds = new Set<string>()
  const seenActivityOrder: string[] = []
  const seenNarrationKeys = new Set<string>()
  const seenNarrationOrder: string[] = []
  const seenVisualCueSources = new Set<string>()
  const seenVisualCueOrder: string[] = []
  const maximumSeen = Math.max(128, maxActivities * 8)
  let narration: LivestreamNarrationStateEvent | null = null
  let disposed = false

  const remember = (key: string, seen: Set<string>, order: string[]): boolean => {
    if (seen.has(key)) return false
    seen.add(key)
    order.push(key)
    while (order.length > maximumSeen) {
      const oldest = order.shift()
      if (oldest) seen.delete(oldest)
    }
    return true
  }

  const onActivity = (value: unknown): void => {
    const parsed = parseMinecraftActivityProjection(value)
    if (!parsed || !remember(parsed.event_id, seenActivityIds, seenActivityOrder)) return
    activities.push({
      ...parsed,
      phaseLabel: publicActivityPhaseLabel(parsed.payload.phase),
      visualText: publicActivityVisualText(parsed),
    })
    activities.sort(compareActivities)
    if (activities.length > maxActivities) {
      activities.splice(0, activities.length - maxActivities)
    }
    view.renderPublicActivities(activities)
  }

  const onNarration = (value: unknown): void => {
    const parsed = parseLivestreamNarrationState(value)
    if (!parsed) return
    const key = `${parsed.cue_id}:${parsed.speech_state}`
    if (seenNarrationKeys.has(key)) return
    if (narration) {
      const sourceOrder =
        publicActivitySequence(parsed.source_event_id)! -
        publicActivitySequence(narration.source_event_id)!
      if (sourceOrder < 0) return
      if (sourceOrder === 0) {
        if (parsed.cue_id !== narration.cue_id) return
        if (narration.speech_state === 'completed' || narration.speech_state === 'cancelled') {
          return
        }
        const stateOrder =
          SPEECH_STATE_RANK[parsed.speech_state] - SPEECH_STATE_RANK[narration.speech_state]
        if (stateOrder < 0) return
      }
    }
    remember(key, seenNarrationKeys, seenNarrationOrder)
    narration = parsed
    view.setPublicNarration(narration)
    if (remember(parsed.source_event_id, seenVisualCueSources, seenVisualCueOrder)) {
      options.onVisualCue?.({
        sourceEventId: parsed.source_event_id,
        phase: parsed.phase,
        emotion: parsed.emotion,
      })
    }
  }

  socket.on(PublicLiveEvents.ACTIVITY_PROJECTION, onActivity)
  socket.on(PublicLiveEvents.NARRATION_STATE, onNarration)

  return {
    get activities(): readonly PublicActivityItem[] {
      return activities
    },
    get narration(): LivestreamNarrationStateEvent | null {
      return narration
    },
    dispose(): void {
      if (disposed) return
      disposed = true
      socket.off(PublicLiveEvents.ACTIVITY_PROJECTION, onActivity)
      socket.off(PublicLiveEvents.NARRATION_STATE, onNarration)
      activities.splice(0)
      narration = null
      seenVisualCueSources.clear()
      seenVisualCueOrder.splice(0)
      view.renderPublicActivities(activities)
      view.setPublicNarration(null)
    },
  }
}
