import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { AssertionRecord, StructuredObservation } from './browser'
import type { ReviewAttemptContext } from './registry'

export interface MinecraftHarnessResponse {
  binding: {
    binding_state: 'following'
    confirmed: true
    username: string
    target: string
    attempt: number
    reason: string
  }
  report: {
    completed: true
    elapsed_seconds: number
    deaths: number
    iron_gear_complete: true
    iron_gear_achieved: Record<string, boolean>
    phase_results: Array<{ phase: string; success: boolean }>
  }
  gameplay_report: string
}

export interface PreparedMinecraftReview {
  payload: MinecraftHarnessResponse
  gameplayReport: string
}

type Fetcher = (input: string | URL, init?: RequestInit) => Promise<Response>

export const MINECRAFT_REVIEW_RUN_TIMEOUT_MS = 47 * 60 * 1_000
export const MINECRAFT_HARNESS_READY_TIMEOUT_MS = 8.5 * 60 * 1_000

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function parseMinecraftHarnessResponse(value: unknown): MinecraftHarnessResponse {
  if (!isRecord(value) || !isRecord(value.binding) || !isRecord(value.report)) {
    throw new Error('Minecraft harness did not satisfy its acceptance contract')
  }
  const payload = value as unknown as MinecraftHarnessResponse
  const valid =
    payload.binding.binding_state === 'following' &&
    payload.binding.confirmed === true &&
    payload.binding.username === 'LUN077' &&
    payload.binding.target === 'AnimettaBot' &&
    Number.isInteger(payload.binding.attempt) &&
    payload.binding.attempt > 0 &&
    payload.report.completed === true &&
    payload.report.iron_gear_complete === true &&
    Number.isFinite(payload.report.elapsed_seconds) &&
    payload.report.elapsed_seconds >= 0 &&
    Number.isInteger(payload.report.deaths) &&
    payload.report.deaths >= 0 &&
    isRecord(payload.report.iron_gear_achieved) &&
    Object.keys(payload.report.iron_gear_achieved).length > 0 &&
    Object.values(payload.report.iron_gear_achieved).every((achieved) => achieved === true) &&
    Array.isArray(payload.report.phase_results) &&
    payload.report.phase_results.length > 0 &&
    payload.report.phase_results.every(
      (phase) => isRecord(phase) && typeof phase.phase === 'string' && phase.success === true,
    ) &&
    typeof payload.gameplay_report === 'string' &&
    payload.gameplay_report.startsWith('/artifacts/')
  if (!valid) throw new Error('Minecraft harness did not satisfy its acceptance contract')
  return payload
}

export class MinecraftReviewClient {
  constructor(
    readonly baseUrl: string,
    private readonly token: string,
    private readonly fetcher: Fetcher = fetch,
  ) {}

  async assertReady(): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/ready`, {
      method: 'POST',
      headers: this.headers(),
      signal: AbortSignal.timeout(MINECRAFT_HARNESS_READY_TIMEOUT_MS),
    })
    if (!response.ok) {
      throw new Error(`Minecraft review harness readiness failed (${response.status})`)
    }
    const payload = (await response.json()) as { ready?: boolean }
    if (payload.ready !== true) throw new Error('Minecraft review harness is not ready')
  }

  async run(context: ReviewAttemptContext): Promise<PreparedMinecraftReview> {
    const deadline = Date.now() + MINECRAFT_REVIEW_RUN_TIMEOUT_MS
    let method: 'POST' | 'GET' = 'POST'
    let response: Response
    while (true) {
      response = await this.fetcher(`${this.baseUrl}/v1/review/run`, {
        method,
        headers: this.headers(),
        signal: AbortSignal.timeout(10_000),
      })
      if (response.status !== 202) break
      if (Date.now() >= deadline) throw new Error('Minecraft review scenario timed out')
      method = 'GET'
      await new Promise((resolve) => globalThis.setTimeout(resolve, 1_000))
    }
    if (!response.ok) {
      const failure = (await response.json().catch(() => null)) as {
        category?: unknown
        phase?: unknown
        failure_category?: unknown
        failure_code?: unknown
        failure_item?: unknown
        missing_count?: unknown
        inventory_oak_log?: unknown
        inventory_oak_planks?: unknown
        inventory_stick?: unknown
        inventory_crafting_table?: unknown
      } | null
      const details = [
        failure?.category,
        failure?.phase,
        failure?.failure_category,
        failure?.failure_code,
        failure?.failure_item,
        failure?.missing_count,
        failure?.inventory_oak_log,
        failure?.inventory_oak_planks,
        failure?.inventory_stick,
        failure?.inventory_crafting_table,
      ]
        .filter((value): value is string => typeof value === 'string')
        .join('/')
      throw new Error(
        `Minecraft review scenario failed (${response.status}${details ? `: ${details}` : ''})`,
      )
    }
    const payload = parseMinecraftHarnessResponse(await response.json())
    const reportResponse = await this.fetcher(new URL(payload.gameplay_report, this.baseUrl), {
      headers: this.headers(),
      signal: AbortSignal.timeout(30_000),
    })
    if (!reportResponse.ok) throw new Error('Minecraft gameplay report could not be downloaded')
    const evidenceDir = join(context.runDir, 'evidence')
    await mkdir(evidenceDir, { recursive: true })
    const gameplayReport = join(
      evidenceDir,
      `${context.sceneId}-${String(context.attempt).padStart(3, '0')}-gameplay.json`,
    )
    await writeFile(gameplayReport, Buffer.from(await reportResponse.arrayBuffer()))
    return { payload, gameplayReport }
  }

  async close(): Promise<void> {
    await this.fetcher(`${this.baseUrl}/shutdown`, {
      method: 'POST',
      headers: this.headers(),
      signal: AbortSignal.timeout(120_000),
    }).catch(() => undefined)
  }

  private headers(): { authorization: string } {
    return { authorization: `Bearer ${this.token}` }
  }
}

export function minecraftReviewAssertions(
  payload: MinecraftHarnessResponse,
): readonly AssertionRecord[] {
  return [
    {
      name: 'viewer:following-confirmed',
      passed: payload.binding.binding_state === 'following' && payload.binding.confirmed === true,
    },
    {
      name: 'survival-iron:completed',
      passed: payload.report.completed === true && payload.report.iron_gear_complete === true,
    },
    {
      name: 'survival-iron:all-phases-successful',
      passed: payload.report.phase_results.every(({ success }) => success),
    },
  ]
}

export function minecraftReviewObservations(
  payload: MinecraftHarnessResponse,
): readonly StructuredObservation[] {
  return [
    { name: 'binding_state', value: payload.binding.binding_state },
    { name: 'binding_attempt', value: payload.binding.attempt },
    { name: 'binding_reason', value: payload.binding.reason },
    { name: 'iron_elapsed', value: payload.report.elapsed_seconds, unit: 'seconds' },
    { name: 'iron_deaths', value: payload.report.deaths },
  ]
}
