import { createHash, randomUUID } from 'node:crypto'
import { link, mkdir, readFile, readdir, rename, stat, unlink, writeFile } from 'node:fs/promises'
import { dirname, isAbsolute, join, relative, resolve } from 'node:path'
import { PNG } from 'pngjs'

export const EVIDENCE_SCHEMA_VERSION = 2 as const

export type AttemptOutcome = 'passed' | 'failed' | 'interrupted'
export type DecisionSource = 'automatic' | 'human'
export type ReviewProfile = 'full' | 'browser'

export interface ArtifactRecord {
  path: string
  sha256: string
  bytes: number
  captured_at: string
  width?: number
  height?: number
}

export interface AttemptSummary {
  scene_id: string
  attempt: number
  outcome: AttemptOutcome
  obs_screenshot: ArtifactRecord | null
  audio_wav?: ArtifactRecord | null
  backend_report?: ArtifactRecord | null
  evidence?: string
}

export interface ObservationRecord {
  name: string
  value: string | number | boolean
  unit?: string
}

export interface AttemptRecordV2 {
  schema_version: typeof EVIDENCE_SCHEMA_VERSION
  run_id: string
  scene_id: string
  attempt: number
  outcome: AttemptOutcome
  decision_source: DecisionSource
  human_verdict?: 'pass' | 'adjust' | 'redo'
  human_note?: string
  review_url: string
  assertions: readonly { name: string; passed: boolean; detail?: string }[]
  artifacts: {
    chrome_screenshot: ArtifactRecord | null
    chrome_stable_crop: ArtifactRecord | null
    obs_screenshot: ArtifactRecord | null
    playwright_trace: ArtifactRecord | null
    audio_wav?: ArtifactRecord | null
    backend_report?: ArtifactRecord | null
  }
  observations?: readonly ObservationRecord[]
  console_errors: readonly string[]
  page_errors: readonly string[]
  failed_requests: readonly { url: string; error: string }[]
  obs_mismatch_ratio: number | null
  started_at: string
  finished_at: string
}

export interface RunManifestV2 {
  schema_version: typeof EVIDENCE_SCHEMA_VERSION
  run_id: string
  feature_id: string
  profile: ReviewProfile
  decision_source: DecisionSource
  status: 'running' | AttemptOutcome
  workflow_fingerprint: string
  started_at: string
  finished_at: string | null
  failure?: { type: string; reason: string }
}

export interface ReviewSummaryV2 {
  schema_version: typeof EVIDENCE_SCHEMA_VERSION
  run_id: string
  feature_id: string
  profile: ReviewProfile
  decision_source: DecisionSource
  status: AttemptOutcome
  all_pass: boolean
  workflow_fingerprint: string
  stable_rounds: number
  scene_order: readonly string[]
  attempts: readonly AttemptSummary[]
  started_at: string
  finished_at: string
}

export function parseVerdict(_input: unknown): {
  verdict: 'pass' | 'adjust' | 'redo'
  humanNote: string
} {
  const aliases = new Map<string, 'pass' | 'adjust' | 'redo'>([
    ['pass', 'pass'],
    ['通过', 'pass'],
    ['adjust', 'adjust'],
    ['调整', 'adjust'],
    ['redo', 'redo'],
    ['重做', 'redo'],
  ])
  const value = String(_input ?? '').trim()
  const [rawVerdict, ...noteParts] = value.split(/\s*\+\s*/)
  const verdict = aliases.get(rawVerdict.toLowerCase())
  if (!verdict) throw new Error('Verdict must be pass, adjust, or redo')
  return { verdict, humanNote: noteParts.join(' + ').trim() }
}

export function createSemanticFingerprint(_value: unknown): string {
  const canonicalize = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(canonicalize)
    if (value && typeof value === 'object') {
      return Object.fromEntries(
        Object.entries(value)
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([key, entry]) => [key, canonicalize(entry)]),
      )
    }
    return value
  }
  return createHash('sha256')
    .update(JSON.stringify(canonicalize(_value)))
    .digest('hex')
}

export async function createRunDirectory(_rootDir: string, _runId: string): Promise<string> {
  await mkdir(_rootDir, { recursive: true })
  const runDir = join(_rootDir, _runId)
  try {
    await mkdir(runDir, { recursive: false })
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'EEXIST') {
      throw new Error(`Review run already exists: ${runDir}`, { cause: error })
    }
    throw error
  }
  return runDir
}

export async function appendAttemptV2<RecordType extends { scene_id: string; attempt: number }>(
  _runDir: string,
  _record: RecordType,
): Promise<string> {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(_record.scene_id)) {
    throw new Error(`Unsafe review scene id: ${_record.scene_id}`)
  }
  if (!Number.isInteger(_record.attempt) || _record.attempt < 1) {
    throw new Error(`Invalid review attempt: ${_record.attempt}`)
  }
  const attemptsDir = join(_runDir, 'attempts')
  await mkdir(attemptsDir, { recursive: true })
  const sequence = String(_record.attempt).padStart(3, '0')
  const filePath = join(attemptsDir, `${_record.scene_id}-${sequence}.json`)
  await writeJsonExclusive(filePath, _record)
  return filePath
}

export async function artifactFromFile(
  _runDir: string,
  _filePath: string,
  _capturedAt: string,
): Promise<ArtifactRecord> {
  const runRoot = resolve(_runDir)
  const absolutePath = resolve(_filePath)
  const relativePath = relative(runRoot, absolutePath)
  if (!relativePath || relativePath.startsWith('..') || isAbsolute(relativePath)) {
    throw new Error(`Artifact is outside review run: ${_filePath}`)
  }
  const fileStat = await stat(absolutePath)
  if (!fileStat.isFile()) throw new Error(`Artifact is not a file: ${_filePath}`)
  const bytes = await readFile(absolutePath)
  const record: ArtifactRecord = {
    path: relativePath.replaceAll('\\', '/'),
    sha256: createHash('sha256').update(bytes).digest('hex'),
    bytes: bytes.byteLength,
    captured_at: _capturedAt,
  }
  if (
    bytes.byteLength >= 8 &&
    bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
  ) {
    const png = PNG.sync.read(bytes)
    record.width = png.width
    record.height = png.height
  }
  return record
}

export function computeStableRounds(
  _previousSummaries: readonly ReviewSummaryV2[],
  _current: Omit<ReviewSummaryV2, 'stable_rounds'>,
): number {
  if (!isStableSummary(_current)) return 0
  let rounds = 1
  for (let index = _previousSummaries.length - 1; index >= 0; index -= 1) {
    const previous = _previousSummaries[index]
    if (
      !isStableSummary(previous) ||
      previous.workflow_fingerprint !== _current.workflow_fingerprint
    ) {
      break
    }
    rounds += 1
  }
  return rounds
}

export async function writeJsonAtomic(filePath: string, value: unknown): Promise<void> {
  await mkdir(dirname(filePath), { recursive: true })
  const temporaryPath = `${filePath}.${randomUUID()}.tmp`
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, {
    encoding: 'utf8',
    flag: 'wx',
  })
  try {
    await rename(temporaryPath, filePath)
  } catch (error) {
    await unlink(temporaryPath).catch(() => {})
    throw error
  }
}

export async function loadValidatedV2Summaries(
  artifactsRoot: string,
  excludedRunId?: string,
): Promise<ReviewSummaryV2[]> {
  await mkdir(artifactsRoot, { recursive: true })
  const entries = await readdir(artifactsRoot, { withFileTypes: true })
  const summaries: ReviewSummaryV2[] = []
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name === excludedRunId) continue
    const runDir = join(artifactsRoot, entry.name)
    try {
      const parsed = JSON.parse(await readFile(join(runDir, 'summary.json'), 'utf8')) as unknown
      if (!isReviewSummaryV2(parsed) || !(await validateSummaryArtifacts(runDir, parsed))) continue
      summaries.push(parsed)
    } catch {
      // Running, interrupted, v1, or damaged runs never contribute to stable history.
    }
  }
  return summaries.sort((left, right) => left.finished_at.localeCompare(right.finished_at))
}

async function writeJsonExclusive(filePath: string, value: unknown): Promise<void> {
  const temporaryPath = `${filePath}.${randomUUID()}.tmp`
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, {
    encoding: 'utf8',
    flag: 'wx',
  })
  try {
    await link(temporaryPath, filePath)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'EEXIST') {
      throw new Error(`Attempt evidence already exists: ${filePath}`, { cause: error })
    }
    throw error
  } finally {
    await unlink(temporaryPath).catch(() => {})
  }
}

function isStableSummary(
  summary: Omit<ReviewSummaryV2, 'stable_rounds'> | ReviewSummaryV2,
): boolean {
  if (
    summary.schema_version !== EVIDENCE_SCHEMA_VERSION ||
    summary.profile !== 'full' ||
    summary.decision_source !== 'automatic' ||
    summary.status !== 'passed' ||
    !summary.all_pass ||
    summary.scene_order.length !== summary.attempts.length
  ) {
    return false
  }
  return summary.attempts.every((attempt, index) => {
    const artifact = attempt.obs_screenshot
    const featureArtifactsComplete =
      summary.feature_id !== 'tts-failover' ||
      (attempt.audio_wav !== null &&
        attempt.audio_wav !== undefined &&
        attempt.backend_report !== null &&
        attempt.backend_report !== undefined)
    return (
      attempt.scene_id === summary.scene_order[index] &&
      attempt.outcome === 'passed' &&
      artifact !== null &&
      /^[a-f0-9]{64}$/.test(artifact.sha256) &&
      artifact.bytes > 0 &&
      artifact.width === 1080 &&
      artifact.height === 1920 &&
      featureArtifactsComplete
    )
  })
}

function isReviewSummaryV2(value: unknown): value is ReviewSummaryV2 {
  if (!value || typeof value !== 'object') return false
  const summary = value as Record<string, unknown>
  return (
    summary.schema_version === EVIDENCE_SCHEMA_VERSION &&
    typeof summary.run_id === 'string' &&
    typeof summary.feature_id === 'string' &&
    Array.isArray(summary.scene_order) &&
    Array.isArray(summary.attempts) &&
    typeof summary.finished_at === 'string'
  )
}

async function validateSummaryArtifacts(
  runDir: string,
  summary: ReviewSummaryV2,
): Promise<boolean> {
  if (!isStableSummary(summary)) return false
  for (const attempt of summary.attempts) {
    const sequence = String(attempt.attempt).padStart(3, '0')
    const evidencePath = join(runDir, 'attempts', `${attempt.scene_id}-${sequence}.json`)
    const record = JSON.parse(await readFile(evidencePath, 'utf8')) as AttemptRecordV2
    if (
      record.schema_version !== EVIDENCE_SCHEMA_VERSION ||
      record.scene_id !== attempt.scene_id ||
      record.attempt !== attempt.attempt ||
      record.outcome !== 'passed' ||
      record.artifacts.chrome_screenshot === null ||
      record.artifacts.chrome_stable_crop === null ||
      record.artifacts.playwright_trace === null ||
      record.artifacts.obs_screenshot === null ||
      (summary.feature_id === 'tts-failover' &&
        (record.artifacts.audio_wav == null || record.artifacts.backend_report == null))
    ) {
      return false
    }
    for (const artifact of [
      record.artifacts.chrome_screenshot,
      record.artifacts.chrome_stable_crop,
      record.artifacts.obs_screenshot,
      record.artifacts.playwright_trace,
      ...(record.artifacts.audio_wav ? [record.artifacts.audio_wav] : []),
      ...(record.artifacts.backend_report ? [record.artifacts.backend_report] : []),
    ]) {
      const actual = await artifactFromFile(
        runDir,
        join(runDir, artifact.path),
        artifact.captured_at,
      )
      if (
        actual.sha256 !== artifact.sha256 ||
        actual.bytes !== artifact.bytes ||
        actual.width !== artifact.width ||
        actual.height !== artifact.height
      ) {
        return false
      }
    }
  }
  return true
}
