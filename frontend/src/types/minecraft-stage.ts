export type StageLifecycle = 'pending' | 'running' | 'passed' | 'failed' | 'blocked' | 'skipped'

export interface EvidenceRefView {
  artifact_id: string
  json_pointer: string
}

export interface PredicateView {
  predicate_id: string
  expected: unknown
  actual?: unknown
  status: 'pass' | 'fail' | 'unknown'
}

export interface CheckpointView {
  checkpoint_id: string
  lifecycle: StageLifecycle
  verifier?: string | null
  predicates?: readonly PredicateView[]
}

export interface StageIOView {
  schema_version: '2'
  run_id: string
  mission_id: string
  stage_id: string
  ordinal: number
  gameplay_evidence_eligible: boolean
  lifecycle: StageLifecycle
  started_at_ms?: number | null
  finished_at_ms?: number | null
  input_refs?: readonly EvidenceRefView[]
  decision_source?: string | null
  reason_code?: string | null
  selected_strategy?: string | null
  selected_capability?: string | null
  budget_ref?: EvidenceRefView | null
  output_refs?: readonly EvidenceRefView[]
  state_deltas?: readonly { path: string; before?: unknown; after?: unknown }[]
  verifier?: string | null
  predicates?: readonly PredicateView[]
  checkpoints?: readonly CheckpointView[]
  evidence_refs?: readonly EvidenceRefView[]
  media?: readonly { evidence_ref: EvidenceRefView; captured_at_ms: number }[]
  failure?: { code: string; layer: string; operator_action: string } | null
}

export function isStageIOView(value: unknown): value is StageIOView {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false
  const stage = value as Record<string, unknown>
  return (
    stage.schema_version === '2' &&
    typeof stage.run_id === 'string' &&
    typeof stage.mission_id === 'string' &&
    typeof stage.stage_id === 'string' &&
    typeof stage.ordinal === 'number' &&
    typeof stage.gameplay_evidence_eligible === 'boolean' &&
    ['pending', 'running', 'passed', 'failed', 'blocked', 'skipped'].includes(
      String(stage.lifecycle),
    )
  )
}
