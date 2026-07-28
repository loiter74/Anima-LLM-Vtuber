// @vitest-environment node

import { describe, expect, it, vi } from 'vitest'
import { cleanupPluginRun, executePluginAttempt } from '../scripts/review/lifecycle'
import type { NodeReviewPlugin, ReviewAttemptContext } from '../scripts/review/registry'

const definition = {
  id: 'test',
  contractVersion: 1,
  route: '/test.html',
  viewport: { width: 1080, height: 1920 },
  scenes: [
    {
      id: 'one',
      title: 'one',
      observe: 'one',
      readyTexts: [],
      timeline: [],
    },
  ],
}

const context: ReviewAttemptContext = {
  runId: 'run-1',
  runDir: 'C:\\review\\run-1',
  repositoryDir: 'C:\\repo',
  baseUrl: 'http://127.0.0.1:3000',
  sceneId: 'one',
  attempt: 1,
}

describe('review plugin lifecycle', () => {
  it('prepares, executes, collects artifacts, then cleans the attempt', async () => {
    const calls: string[] = []
    const plugin: NodeReviewPlugin = {
      definition,
      pageAdapter: {} as never,
      prepareAttempt: async () => {
        calls.push('prepare')
        return {
          pageParams: { audio: 'http://127.0.0.1/audio.wav' },
          assertions: [{ name: 'billing', passed: true }],
          observations: [{ name: 'rtf', value: 0.2 }],
        }
      },
      artifacts: async () => {
        calls.push('artifacts')
        return {
          audioWav: 'evidence/audio.wav',
          backendReport: 'evidence/report.json',
          audioSamples: {
            calm: {
              audioWav: 'evidence/calm-audio.wav',
              backendReport: 'evidence/calm-report.json',
            },
          },
        }
      },
      cleanupAttempt: async () => {
        calls.push('cleanup')
      },
    }

    const result = await executePluginAttempt(plugin, context, {}, async (preparation) => {
      calls.push('execute')
      return { technicalPassed: true, preparation }
    })

    expect(calls).toEqual(['prepare', 'execute', 'artifacts', 'cleanup'])
    expect(result.pluginArtifacts).toEqual({
      audioWav: 'evidence/audio.wav',
      backendReport: 'evidence/report.json',
      audioSamples: {
        calm: {
          audioWav: 'evidence/calm-audio.wav',
          backendReport: 'evidence/calm-report.json',
        },
      },
    })
    expect(result.observations).toEqual([{ name: 'rtf', value: 0.2 }])
  })

  it('cleans an attempt and run exactly once after failure', async () => {
    const cleanupAttempt = vi.fn().mockResolvedValue(undefined)
    const cleanupRun = vi.fn().mockResolvedValue(undefined)
    const plugin: NodeReviewPlugin = {
      definition,
      pageAdapter: {} as never,
      cleanupAttempt,
      cleanupRun,
    }

    await expect(
      executePluginAttempt(plugin, context, {}, async () => {
        throw new Error('capture failed')
      }),
    ).rejects.toThrow('capture failed')
    const cleanup = cleanupPluginRun(plugin, context, {})
    await cleanup()
    await cleanup()

    expect(cleanupAttempt).toHaveBeenCalledOnce()
    expect(cleanupRun).toHaveBeenCalledOnce()
  })
})
