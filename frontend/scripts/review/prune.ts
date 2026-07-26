import { lstat, readdir, readFile, realpath, rm } from 'node:fs/promises'
import { resolve, sep } from 'node:path'

const RUN_ID = /^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z-[A-Za-z0-9]+$/
const DEFAULT_ROOT = resolve(process.cwd(), '..', 'artifacts', 'live-review')

export interface ReviewPruneCandidate {
  runId: string
  status: string
  files: number
  bytes: number
}

export interface ReviewPrunePlan {
  root: string
  kept: Array<{ runId: string; reason: 'keep-run' }>
  candidates: ReviewPruneCandidate[]
  files: number
  bytes: number
}

export interface ReviewPruneOptions {
  root?: string
  keepRuns?: readonly string[]
  statuses?: readonly string[]
  deleteSupersededPassed?: boolean
}

async function measureDirectory(directory: string): Promise<{ files: number; bytes: number }> {
  let files = 0
  let bytes = 0
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = resolve(directory, entry.name)
    const stat = await lstat(path)
    if (stat.isSymbolicLink()) throw new Error(`Review run contains a link: ${entry.name}`)
    if (stat.isDirectory()) {
      const nested = await measureDirectory(path)
      files += nested.files
      bytes += nested.bytes
    } else if (stat.isFile()) {
      files += 1
      bytes += stat.size
    }
  }
  return { files, bytes }
}

async function readRunStatus(directory: string): Promise<string> {
  for (const filename of ['summary.json', 'run.json']) {
    try {
      const value = JSON.parse(await readFile(resolve(directory, filename), 'utf8')) as {
        status?: unknown
      }
      if (typeof value.status === 'string') return value.status
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT' && error instanceof SyntaxError) {
        return 'unknown'
      }
    }
  }
  return 'unknown'
}

function validateRunIds(runIds: readonly string[]): void {
  for (const runId of runIds) {
    if (!RUN_ID.test(runId)) throw new Error(`Invalid review run identifier: ${runId}`)
  }
}

export async function planReviewPrune(options: ReviewPruneOptions = {}): Promise<ReviewPrunePlan> {
  const root = resolve(options.root ?? DEFAULT_ROOT)
  const keepRuns = [...new Set(options.keepRuns ?? [])]
  validateRunIds(keepRuns)
  const keep = new Set(keepRuns)
  const statuses = new Set(options.statuses ?? ['failed', 'running'])
  const rootReal = await realpath(root)
  const candidates: ReviewPruneCandidate[] = []
  const kept: ReviewPrunePlan['kept'] = []

  for (const entry of await readdir(root, { withFileTypes: true })) {
    if (entry.isSymbolicLink() && RUN_ID.test(entry.name)) {
      throw new Error(`Review run is a link: ${entry.name}`)
    }
    if (!entry.isDirectory() || !RUN_ID.test(entry.name)) continue
    const directory = resolve(root, entry.name)
    const stat = await lstat(directory)
    if (stat.isSymbolicLink()) throw new Error(`Review run is a link: ${entry.name}`)
    const directoryReal = await realpath(directory)
    if (!directoryReal.startsWith(`${rootReal}${sep}`)) {
      throw new Error(`Review run escapes the review root: ${entry.name}`)
    }
    const status = await readRunStatus(directory)
    if (keep.has(entry.name)) {
      kept.push({ runId: entry.name, reason: 'keep-run' })
      continue
    }
    if (!statuses.has(status) && !(options.deleteSupersededPassed && status === 'passed')) continue
    const measured = await measureDirectory(directory)
    candidates.push({ runId: entry.name, status, ...measured })
  }
  candidates.sort((left, right) => left.runId.localeCompare(right.runId))
  kept.sort((left, right) => left.runId.localeCompare(right.runId))
  return {
    root,
    kept,
    candidates,
    files: candidates.reduce((sum, candidate) => sum + candidate.files, 0),
    bytes: candidates.reduce((sum, candidate) => sum + candidate.bytes, 0),
  }
}

export async function applyReviewPrune(plan: ReviewPrunePlan): Promise<ReviewPrunePlan> {
  const root = resolve(plan.root)
  const rootReal = await realpath(root)
  for (const candidate of plan.candidates) {
    validateRunIds([candidate.runId])
    const target = resolve(root, candidate.runId)
    const targetReal = await realpath(target).catch((error: NodeJS.ErrnoException) => {
      if (error.code === 'ENOENT') return null
      throw error
    })
    if (targetReal === null) continue
    if (!targetReal.startsWith(`${rootReal}${sep}`)) {
      throw new Error(`Review run escapes the review root: ${candidate.runId}`)
    }
    const stat = await lstat(target)
    if (stat.isSymbolicLink() || !stat.isDirectory()) {
      throw new Error(`Review prune target is not a direct run directory: ${candidate.runId}`)
    }
    await rm(target, { recursive: true })
  }
  return plan
}

interface CliOptions extends ReviewPruneOptions {
  apply: boolean
}

function parseCli(args: readonly string[]): CliOptions {
  const keepRuns: string[] = []
  const statuses: string[] = []
  let apply = false
  let deleteSupersededPassed = false
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index]
    if (argument === '--apply') apply = true
    else if (argument === '--delete-superseded-passed') deleteSupersededPassed = true
    else if (argument === '--keep-run') keepRuns.push(args[++index] ?? '')
    else if (argument === '--status') statuses.push(args[++index] ?? '')
    else throw new Error(`Unknown review prune option: ${argument}`)
  }
  return {
    apply,
    keepRuns,
    statuses: statuses.length > 0 ? statuses : undefined,
    deleteSupersededPassed,
  }
}

async function main(): Promise<void> {
  const options = parseCli(process.argv.slice(2))
  const plan = await planReviewPrune(options)
  if (options.apply) await applyReviewPrune(plan)
  process.stdout.write(
    `${JSON.stringify({ mode: options.apply ? 'apply' : 'dry-run', ...plan }, null, 2)}\n`,
  )
}

if (process.argv[1]?.replaceAll('\\', '/').endsWith('/scripts/review/prune.ts')) {
  void main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`)
    process.exitCode = 1
  })
}
