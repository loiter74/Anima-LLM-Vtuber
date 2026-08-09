// @vitest-environment node

import { mkdtemp, readFile, readdir, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PNG } from 'pngjs'
import { describe, expect, it, vi } from 'vitest'
import {
  appendAttemptV2,
  artifactFromFile,
  computeStableRounds,
  createRunDirectory,
  createSemanticFingerprint,
  parseVerdict,
  type ReviewSummaryV2,
} from '../scripts/review/evidence'
import { comparePngRegion } from '../scripts/review/image-compare'
import { exitCodeForSummary, runReviewCli } from '../scripts/review/cli'
import { automaticDecision, interactiveDecision } from '../scripts/review/policies'

function summary(overrides: Partial<ReviewSummaryV2> = {}): ReviewSummaryV2 {
  return {
    schema_version: 2,
    run_id: 'run-1',
    feature_id: 'live',
    profile: 'full',
    decision_source: 'automatic',
    status: 'passed',
    all_pass: true,
    workflow_fingerprint: 'fingerprint-a',
    stable_rounds: 1,
    scene_order: ['empty', 'baseline'],
    attempts: [
      {
        scene_id: 'empty',
        attempt: 1,
        outcome: 'passed',
        obs_screenshot: {
          path: 'evidence/empty-001-obs.png',
          sha256: 'a'.repeat(64),
          bytes: 10,
          width: 1080,
          height: 1920,
          captured_at: '2026-07-25T00:00:00.000Z',
        },
      },
      {
        scene_id: 'baseline',
        attempt: 1,
        outcome: 'passed',
        obs_screenshot: {
          path: 'evidence/baseline-001-obs.png',
          sha256: 'b'.repeat(64),
          bytes: 10,
          width: 1080,
          height: 1920,
          captured_at: '2026-07-25T00:00:01.000Z',
        },
      },
    ],
    started_at: '2026-07-25T00:00:00.000Z',
    finished_at: '2026-07-25T00:01:00.000Z',
    ...overrides,
  }
}

describe('review decisions', () => {
  it('parses interactive verdict aliases without affecting automatic outcomes', () => {
    expect(parseVerdict('通过')).toEqual({ verdict: 'pass', humanNote: '' })
    expect(parseVerdict('调整 + 弹幕再高一点')).toEqual({
      verdict: 'adjust',
      humanNote: '弹幕再高一点',
    })
    expect(() => parseVerdict('skip')).toThrow(/pass, adjust, or redo/)
  })

  it('uses automatic outcomes by default', () => {
    expect(automaticDecision(true)).toEqual({
      outcome: 'passed',
      decisionSource: 'automatic',
    })
    expect(automaticDecision(false)).toEqual({
      outcome: 'failed',
      decisionSource: 'automatic',
    })
  })

  it('never lets the interactive gate override a failed technical assertion', async () => {
    const prompt = vi.fn()

    await expect(interactiveDecision(false, prompt)).resolves.toEqual({
      outcome: 'failed',
      decisionSource: 'automatic',
    })
    expect(prompt).not.toHaveBeenCalled()
  })
})

describe('evidence v2', () => {
  it('writes immutable attempt records atomically', async () => {
    const root = await mkdtemp(join(tmpdir(), 'animetta-review-v2-'))
    const runDir = await createRunDirectory(root, 'run-1')
    const record = {
      schema_version: 2,
      run_id: 'run-1',
      scene_id: 'empty',
      attempt: 1,
      outcome: 'passed',
    }

    const path = await appendAttemptV2(runDir, record)
    expect(JSON.parse(await readFile(path, 'utf8'))).toEqual(record)
    await expect(appendAttemptV2(runDir, record)).rejects.toThrow(/already exists/)
    expect((await readdir(join(runDir, 'attempts'))).some((name) => name.endsWith('.tmp'))).toBe(
      false,
    )
  })

  it('records file hashes and PNG dimensions and rejects paths outside the run', async () => {
    const root = await mkdtemp(join(tmpdir(), 'animetta-review-artifact-'))
    const runDir = await createRunDirectory(root, 'run-1')
    const evidenceDir = join(runDir, 'evidence')
    const imagePath = join(evidenceDir, 'capture.png')
    const png = new PNG({ width: 4, height: 3 })
    png.data.fill(255)
    await import('node:fs/promises').then(({ mkdir }) => mkdir(evidenceDir, { recursive: true }))
    await writeFile(imagePath, PNG.sync.write(png))

    await expect(
      artifactFromFile(runDir, join(root, 'outside.png'), '2026-07-25T00:00:00.000Z'),
    ).rejects.toThrow(/outside review run/)
    await expect(artifactFromFile(runDir, imagePath, '2026-07-25T00:00:00.000Z')).resolves.toEqual(
      expect.objectContaining({
        path: 'evidence/capture.png',
        sha256: expect.stringMatching(/^[a-f0-9]{64}$/),
        width: 4,
        height: 3,
        captured_at: '2026-07-25T00:00:00.000Z',
      }),
    )
  })

  it('uses semantic definitions rather than source-file order for fingerprints', () => {
    const first = createSemanticFingerprint({
      contractVersion: 2,
      viewport: { width: 1080, height: 1920 },
      scenes: ['empty', 'baseline'],
    })
    const same = createSemanticFingerprint({
      scenes: ['empty', 'baseline'],
      viewport: { height: 1920, width: 1080 },
      contractVersion: 2,
    })
    const changed = createSemanticFingerprint({
      contractVersion: 3,
      viewport: { width: 1080, height: 1920 },
      scenes: ['empty', 'baseline'],
    })

    expect(first).toBe(same)
    expect(first).not.toBe(changed)
  })

  it('counts only consecutive automatic full v2 runs with complete OBS attempts', () => {
    const current = summary({ run_id: 'run-2', stable_rounds: 0 })
    const { stable_rounds: _ignored, ...currentWithoutRounds } = current
    expect(_ignored).toBe(0)

    expect(computeStableRounds([summary()], currentWithoutRounds)).toBe(2)
    expect(computeStableRounds([summary()], { ...currentWithoutRounds, profile: 'browser' })).toBe(
      0,
    )
    expect(
      computeStableRounds([summary()], {
        ...currentWithoutRounds,
        attempts: currentWithoutRounds.attempts.map((attempt) => ({
          ...attempt,
          obs_screenshot: null,
        })),
      }),
    ).toBe(0)
  })

  it('keeps old v2 summaries readable and requires audio evidence only for TTS failover', () => {
    const legacy = summary({ run_id: 'legacy-v2' })
    const { stable_rounds: legacyRounds, ...legacyWithoutRounds } = legacy
    expect(legacyRounds).toBe(1)
    expect(computeStableRounds([], legacyWithoutRounds)).toBe(1)

    const ttsAttempt = {
      ...legacy.attempts[0],
      scene_id: 'billing-to-local',
    }
    const tts = {
      ...legacyWithoutRounds,
      feature_id: 'tts-failover',
      scene_order: ['billing-to-local'],
      attempts: [ttsAttempt],
    }
    expect(computeStableRounds([], tts)).toBe(0)
    expect(
      computeStableRounds([], {
        ...tts,
        attempts: [
          {
            ...ttsAttempt,
            audio_wav: {
              path: 'evidence/audio.wav',
              sha256: 'c'.repeat(64),
              bytes: 4800,
              captured_at: '2026-07-25T00:00:00.000Z',
            },
            backend_report: {
              path: 'evidence/backend.json',
              sha256: 'd'.repeat(64),
              bytes: 500,
              captured_at: '2026-07-25T00:00:00.000Z',
            },
          },
        ],
      }),
    ).toBe(1)
  })
})

describe('Chrome and OBS synchronization', () => {
  it('compares only the declared stable region', () => {
    const expected = new PNG({ width: 2, height: 2 })
    expected.data.fill(255)
    const actual = new PNG({ width: 4, height: 4 })
    actual.data.fill(0)
    for (let y = 1; y < 3; y += 1) {
      for (let x = 1; x < 3; x += 1) {
        const offset = (y * actual.width + x) * 4
        actual.data.fill(255, offset, offset + 4)
      }
    }

    expect(
      comparePngRegion(PNG.sync.write(expected), PNG.sync.write(actual), {
        x: 1,
        y: 1,
        width: 2,
        height: 2,
      }),
    ).toEqual({ mismatchRatio: 0, passed: true })
  })

  it('aligns fractional CSS boxes to the pixel dimensions Playwright captures', () => {
    const expected = new PNG({ width: 2, height: 2 })
    expected.data.fill(255)
    const actual = new PNG({ width: 4, height: 4 })
    actual.data.fill(0)
    for (let y = 1; y < 3; y += 1) {
      for (let x = 1; x < 3; x += 1) {
        const offset = (y * actual.width + x) * 4
        actual.data.fill(255, offset, offset + 4)
      }
    }

    expect(
      comparePngRegion(PNG.sync.write(expected), PNG.sync.write(actual), {
        x: 1.4,
        y: 1.4,
        width: 1.2,
        height: 1.2,
      }),
    ).toEqual({ mismatchRatio: 0, passed: true })
  })
})

describe('review CLI result', () => {
  it('resolves the canonical feature URL without inferring a router path', async () => {
    await expect(
      runReviewCli(['--feature', 'live', '--base-url', 'http://localhost', '--print-url']),
    ).resolves.toBe('http://localhost/live.html')
    await expect(runReviewCli(['--feature', 'unknown', '--print-url'])).rejects.toThrow(
      /Unknown review feature/,
    )
  })

  it('returns a URL before capability checks or review side effects', async () => {
    await expect(
      runReviewCli([
        '--feature',
        'live2d-performance',
        '--base-url',
        'http://localhost:8080/base/',
        '--no-obs',
        '--print-url',
      ]),
    ).resolves.toBe('http://localhost:8080/live.html')
  })

  it('returns a failing process status when any scene fails', () => {
    expect(exitCodeForSummary({ all_pass: true })).toBe(0)
    expect(exitCodeForSummary({ all_pass: false })).toBe(1)
  })
})
