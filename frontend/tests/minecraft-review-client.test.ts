// @vitest-environment node

import { mkdtemp, readFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it, vi } from 'vitest'

import {
  MINECRAFT_HARNESS_READY_TIMEOUT_MS,
  MINECRAFT_REVIEW_RUN_TIMEOUT_MS,
  MinecraftReviewClient,
  parseMinecraftHarnessResponse,
} from '../scripts/review/minecraft-review-client'

const accepted = {
  binding: {
    binding_state: 'following',
    confirmed: true,
    username: 'LUN077',
    target: 'AnimettaBot',
    attempt: 2,
    reason: 'viewer_joined',
  },
  report: {
    completed: true,
    elapsed_seconds: 42.5,
    deaths: 0,
    iron_gear_complete: true,
    iron_gear_achieved: { iron_chestplate: true },
    phase_results: [{ phase: 'iron_gear', success: true }],
  },
  gameplay_report: '/artifacts/survival-iron-report.json',
}

describe('parseMinecraftHarnessResponse', () => {
  it('accepts only confirmed complete iron runs', () => {
    expect(parseMinecraftHarnessResponse(accepted)).toEqual(accepted)
    expect(() =>
      parseMinecraftHarnessResponse({
        ...accepted,
        binding: { ...accepted.binding, confirmed: false },
      }),
    ).toThrow(/acceptance contract/)
    expect(() =>
      parseMinecraftHarnessResponse({
        ...accepted,
        report: { ...accepted.report, iron_gear_complete: false },
      }),
    ).toThrow(/acceptance contract/)
  })
})

describe('MinecraftReviewClient', () => {
  it('allows a cold Paper runtime to finish its bounded eight minute startup', () => {
    expect(MINECRAFT_HARNESS_READY_TIMEOUT_MS).toBeGreaterThan(8 * 60 * 1_000)
  })

  it('keeps the polling budget beyond viewer wait plus the 35 minute run budget', () => {
    expect(MINECRAFT_REVIEW_RUN_TIMEOUT_MS).toBeGreaterThan(45 * 60 * 1_000)
  })

  it('runs the scenario and downloads authenticated evidence', async () => {
    const runDir = await mkdtemp(join(tmpdir(), 'minecraft-review-client-'))
    const fetcher = vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      expect(init?.headers).toEqual(
        expect.objectContaining({ authorization: 'Bearer review-token' }),
      )
      if (url.endsWith('/v1/review/run')) {
        return new Response(JSON.stringify(accepted), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      return new Response(JSON.stringify(accepted.report), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    })
    const client = new MinecraftReviewClient('http://127.0.0.1:49152', 'review-token', fetcher)

    const result = await client.run({
      runId: 'run',
      runDir,
      repositoryDir: 'C:/workspace',
      baseUrl: 'http://127.0.0.1:3012',
      sceneId: 'survival-iron',
      attempt: 1,
    })

    expect(JSON.parse(await readFile(result.gameplayReport, 'utf8'))).toEqual(accepted.report)
    expect(result.payload.binding.confirmed).toBe(true)
  })
})
