export type ProgramPhase = 'qi' | 'cheng' | 'zhuan' | 'he'
export type MemoryMode = 'write' | 'probe' | 'none'
export type ThreadMode = 'shared' | 'isolated'

export interface ProgramOption {
  id: string
  label: string
  danmaku: string
  aliases: string[]
}

export interface ProgramBeat {
  id: string
  phase: ProgramPhase
  host_prompt: string | null
  input: {
    type: 'choice' | 'fixed'
    options: string | null
    save_as: string | null
    text: string | null
    exclude_slot: string | null
  }
  memory: MemoryMode
  thread: ThreadMode
  reply: { objective: string; max_sentences: number; max_chars: number }
  transition: { style: 'direct' | 'soft'; text: string | null }
  evaluator: {
    type: 'recall_slots' | 'latest_slot' | 'reject_false_premise' | 'composite_slots'
    slots: string[]
    false_values: string[]
    rejection_markers: string[]
  } | null
}

export interface ProgramScript {
  id: string
  title: string
  description: string
  template: 'aura_debut_memory' | null
  disclosure: string
  opening: string
  closing: string
  defaults: { reply_timeout_ms: number; memory_commit_timeout_ms: number }
  option_sets: Record<string, ProgramOption[]>
  beats: ProgramBeat[]
}

export interface ProgramScriptSummary {
  id: string
  title: string
  description: string
  builtin: boolean
  archived: boolean
  draft_revision: number | null
  versions: number[]
}

export interface ProgramScriptDraft {
  revision: number
  script: ProgramScript
}

export interface PublishedProgramScript {
  version: number
  content_hash: string
  created_at: string
  builtin: boolean
  script: ProgramScript
}

export interface ValidationIssue {
  path: string
  message: string
  code: string
}

export class ProgramApiError extends Error {
  constructor(
    message: string,
    readonly issues: ValidationIssue[] = [],
  ) {
    super(message)
    this.name = 'ProgramApiError'
  }
}

export interface ProgramRunSnapshot {
  run_id: string
  room_id: number
  creator_id: string
  actor_display_name: string
  script_id: string
  script_title: string
  script_version: number
  script_hash: string
  disclosure: string
  opening: string
  closing: string
  state: 'idle' | 'running' | 'paused' | 'completed' | 'stopped' | 'failed'
  current_index: number
  total_beats: number
  waiting_for: string
  error: string | null
  slots: Record<string, string>
  current_beat: {
    id: string
    phase: ProgramPhase
    lead_in: string | null
    host_prompt: string | null
    viewer_prompt: string | null
    input_type: 'choice' | 'fixed'
    memory: MemoryMode
    thread: ThreadMode
    transition: { style: 'direct' | 'soft'; text: string | null }
    options: Array<{ id: string; label: string; danmaku: string }>
  } | null
  records: Array<{
    beat_id: string
    input_text: string
    response_text: string
    turn_id: string
    memory_revision: number | null
    atom_id: string | null
    probe_result: 'matched' | 'not_matched' | 'inconclusive' | null
    degradation_reason: string | null
  }>
}

export interface ReplaySnapshot {
  replay_id: string
  room_id: number
  source: 'script' | 'jsonl'
  state: 'idle' | 'running' | 'paused' | 'completed' | 'stopped' | 'failed'
  speed: number
  cursor: number
  total_events: number
  error: string | null
  current_event: {
    sequence: number
    offset_ms: number
    event_type: string
    actor_id: string
    text: string
    payload: Record<string, unknown>
  } | null
}

export async function listProgramScripts(): Promise<ProgramScriptSummary[]> {
  const data = await api<{ scripts: ProgramScriptSummary[] }>('/api/program-scripts')
  return data.scripts
}

export function getProgramVersion(id: string, version: number): Promise<PublishedProgramScript> {
  return api(`/api/program-scripts/${encodeURIComponent(id)}/versions/${version}`)
}

export function getProgramDraft(id: string): Promise<ProgramScriptDraft> {
  return api(`/api/program-scripts/drafts/${encodeURIComponent(id)}`)
}

export function createProgramDraft(script: ProgramScript): Promise<ProgramScriptDraft> {
  return api('/api/program-scripts/drafts', { method: 'POST', body: JSON.stringify({ script }) })
}

export function saveProgramDraft(draft: ProgramScriptDraft): Promise<ProgramScriptDraft> {
  return api(`/api/program-scripts/drafts/${encodeURIComponent(draft.script.id)}`, {
    method: 'PUT',
    body: JSON.stringify(draft),
  })
}

export function validateProgramDraft(
  id: string,
): Promise<{ valid: boolean; issues: ValidationIssue[] }> {
  return api(`/api/program-scripts/drafts/${encodeURIComponent(id)}/validate`, {
    method: 'POST',
  })
}

export function publishProgramDraft(id: string, revision: number): Promise<PublishedProgramScript> {
  return api(`/api/program-scripts/drafts/${encodeURIComponent(id)}/publish`, {
    method: 'POST',
    body: JSON.stringify({ revision }),
  })
}

export function duplicateProgramVersion(
  id: string,
  version: number,
  newId?: string,
  title?: string,
): Promise<ProgramScriptDraft> {
  return api(`/api/program-scripts/${encodeURIComponent(id)}/versions/${version}/duplicate`, {
    method: 'POST',
    body: JSON.stringify({ new_id: newId || undefined, title: title || undefined }),
  })
}

export function archiveProgramScript(id: string): Promise<{ ok: boolean }> {
  return api(`/api/program-scripts/${encodeURIComponent(id)}/archive`, { method: 'POST' })
}

export function startProgramRun(payload: {
  script_id: string
  version: number
  room_id: number
  creator_id: string
}): Promise<ProgramRunSnapshot> {
  return api('/api/program-runs/start', { method: 'POST', body: JSON.stringify(payload) })
}

export async function getCurrentProgramRun(roomId: number): Promise<ProgramRunSnapshot | null> {
  const data = await api<{ run: ProgramRunSnapshot | null }>(
    `/api/program-runs/current?room_id=${roomId}`,
  )
  return data.run
}

export function getProgramRun(runId: string): Promise<ProgramRunSnapshot> {
  return api(`/api/program-runs/${encodeURIComponent(runId)}`)
}

export function submitProgramChoice(
  runId: string,
  beatId: string,
  optionId: string,
  creatorId: string,
): Promise<ProgramRunSnapshot> {
  return api(`/api/program-runs/${encodeURIComponent(runId)}/choice`, {
    method: 'POST',
    body: JSON.stringify({ beat_id: beatId, option_id: optionId, creator_id: creatorId }),
  })
}

export function controlProgramRun(
  runId: string,
  action: 'pause' | 'resume' | 'retry' | 'stop',
  creatorId: string,
): Promise<ProgramRunSnapshot> {
  return api(`/api/program-runs/${encodeURIComponent(runId)}/control`, {
    method: 'POST',
    body: JSON.stringify({ action, creator_id: creatorId }),
  })
}

export function startProgramReplay(payload: Record<string, unknown>): Promise<ReplaySnapshot> {
  return api('/api/program-replays/start', { method: 'POST', body: JSON.stringify(payload) })
}

export function getProgramReplay(replayId: string): Promise<ReplaySnapshot> {
  return api(`/api/program-replays/${encodeURIComponent(replayId)}`)
}

export function controlProgramReplay(
  replayId: string,
  action: 'pause' | 'resume' | 'step' | 'speed' | 'restart' | 'stop',
  creatorId: string,
  speed?: number,
): Promise<ReplaySnapshot> {
  return api(`/api/program-replays/${encodeURIComponent(replayId)}/control`, {
    method: 'POST',
    body: JSON.stringify({ action, creator_id: creatorId, speed }),
  })
}

async function api<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  const data = await response.json()
  if (!response.ok) {
    const issues = Array.isArray(data.issues)
      ? data.issues.map(normalizeIssue)
      : ([] as ValidationIssue[])
    throw new ProgramApiError(data.message || data.error || `HTTP ${response.status}`, issues)
  }
  return data as T
}

function normalizeIssue(issue: Record<string, unknown>): ValidationIssue {
  if (typeof issue.path === 'string') {
    return {
      path: issue.path,
      message: String(issue.message ?? '配置无效'),
      code: String(issue.code ?? 'validation_error'),
    }
  }
  const location = Array.isArray(issue.loc)
    ? issue.loc.filter((part) => part !== 'body').join('.')
    : 'script'
  return {
    path: location || 'script',
    message: String(issue.msg ?? '配置无效'),
    code: String(issue.type ?? 'validation_error'),
  }
}
