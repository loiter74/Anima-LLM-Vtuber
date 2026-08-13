import { randomUUID } from 'node:crypto'
import { readFile, stat } from 'node:fs/promises'
import { dirname, join, relative, resolve } from 'node:path'
import { stdin, stdout } from 'node:process'
import { createInterface, type Interface } from 'node:readline/promises'
import { fileURLToPath } from 'node:url'
import OBSWebSocket from 'obs-websocket-js'
import { chromium, type Browser } from 'playwright'
import {
  appendAttemptV2,
  artifactFromFile,
  computeStableRounds,
  createRunDirectory,
  createSemanticFingerprint,
  EVIDENCE_SCHEMA_VERSION,
  loadValidatedV2Summaries,
  parseVerdict,
  writeJsonAtomic,
  type ArtifactRecord,
  type AttemptRecordV2,
  type AttemptSummary,
  type ReviewSummaryV2,
  type RunManifestV2,
} from './evidence'
import {
  assertHardwareWebGl,
  buildReviewBrowserArgs,
  captureBrowserAttempt,
  type BrowserAttemptResult,
} from './browser'
import { ObsPreviewAdapter, type ObsClient, type ReviewObsAdapter } from './obs'
import { runReviewWorkflow } from './orchestrator'
import { parseReviewOptions } from './options'
import { automaticDecision, interactiveDecision } from './policies'
import {
  getReviewPlugin,
  REVIEW_FEATURE_IDS,
  validateReviewCapabilities,
  type ReviewRunContext,
} from './registry'
import { cleanupPluginRun, executePluginAttempt } from './lifecycle'
import { acquireViteServerLease, type ServerLease } from './server-lease'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const frontendDir = resolve(scriptDir, '..', '..')
const repositoryDir = resolve(frontendDir, '..')
const artifactsRoot = join(repositoryDir, 'artifacts', 'live-review')

function runId(): string {
  return `${new Date()
    .toISOString()
    .replaceAll(':', '-')
    .replace(/\.\d{3}Z$/, 'Z')}-${randomUUID().slice(0, 8)}`
}

function relativePath(root: string, filePath: string): string {
  return relative(root, filePath).replaceAll('\\', '/')
}

function canonicalReviewUrl(featureId: string, baseUrl: string): string {
  return new URL(getReviewPlugin(featureId).definition.route, baseUrl).href
}

async function hostTtsConfigured(): Promise<boolean> {
  if (process.env.QWEN_TTS_API_KEY?.trim()) return true
  try {
    const envFile = await readFile(join(repositoryDir, '.env'), 'utf8')
    return /^QWEN_TTS_API_KEY\s*=\s*\S+/m.test(envFile)
  } catch {
    return false
  }
}

async function optionalArtifact(
  runDir: string,
  filePath: string | null,
  capturedAt: string,
): Promise<ArtifactRecord | null> {
  if (!filePath) return null
  try {
    const fileStat = await stat(filePath)
    if (!fileStat.isFile()) return null
    return artifactFromFile(runDir, filePath, capturedAt)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw error
  }
}

async function promptVerdict(terminal: Interface, title: string, observe: string) {
  stdout.write(`\n[${title}] ${observe}\n`)
  for (;;) {
    try {
      return parseVerdict(await terminal.question('结论（pass / adjust + 说明 / redo + 原因）: '))
    } catch (error) {
      stdout.write(`${error instanceof Error ? error.message : String(error)}\n`)
    }
  }
}

export async function runReviewCli(
  args = process.argv.slice(2),
): Promise<ReviewSummaryV2 | string> {
  const options = parseReviewOptions(args)
  if (options.printUrl) return canonicalReviewUrl(options.featureId, options.baseUrl)
  const plugin = getReviewPlugin(options.featureId)
  validateReviewCapabilities(plugin, {
    requireObs: options.requireObs,
    interactive: options.interactive,
    headed: options.headed,
    hostTtsAvailable: await hostTtsConfigured(),
  })
  const currentRunId = runId()
  const runDir = await createRunDirectory(artifactsRoot, currentRunId)
  const startedAt = new Date().toISOString()
  const profile = options.requireObs ? 'full' : 'browser'
  const decisionSource = options.interactive ? 'human' : 'automatic'
  const fingerprint = createSemanticFingerprint({
    featureId: plugin.definition.id,
    contractVersion: plugin.definition.contractVersion,
    route: plugin.definition.route,
    viewport: plugin.definition.viewport,
    scenes: plugin.definition.scenes,
    evidenceSchemaVersion: EVIDENCE_SCHEMA_VERSION,
    profile,
  })
  const manifest: RunManifestV2 = {
    schema_version: EVIDENCE_SCHEMA_VERSION,
    run_id: currentRunId,
    feature_id: plugin.definition.id,
    profile,
    decision_source: decisionSource,
    status: 'running',
    workflow_fingerprint: fingerprint,
    started_at: startedAt,
    finished_at: null,
  }
  await writeJsonAtomic(join(runDir, 'run.json'), manifest)
  const runContext: ReviewRunContext = {
    runId: currentRunId,
    runDir,
    repositoryDir,
    baseUrl: options.baseUrl,
  }

  let server: ServerLease | null = null
  let browser: Browser | null = null
  let preview: ReviewObsAdapter | null = null
  let terminal: Interface | null = null
  let interrupted = false
  let cleanupPromise: Promise<void> | null = null
  let pluginState: unknown
  let cleanupPlugin = cleanupPluginRun(plugin, runContext, pluginState)
  const cleanup = (): Promise<void> => {
    cleanupPromise ??= (async () => {
      terminal?.close()
      await browser?.close().catch(() => {})
      await preview?.dispose().catch(() => {})
      await cleanupPlugin().catch(() => {})
      await server?.dispose().catch(() => {})
    })()
    return cleanupPromise
  }
  const onSignal = (): void => {
    interrupted = true
    void cleanup()
  }
  process.once('SIGINT', onSignal)
  process.once('SIGTERM', onSignal)

  try {
    stdout.write(`Animetta 自动评审 ${currentRunId}\n`)
    stdout.write(`Feature: ${plugin.definition.id}; profile: ${profile}\n`)
    stdout.write(`场景顺序：${plugin.definition.scenes.map(({ title }) => title).join(' → ')}\n`)
    server = await acquireViteServerLease(options.baseUrl, frontendDir)
    if (options.requireObs) {
      const obsClient = new OBSWebSocket() as unknown as ObsClient
      const obsOptions = {
        url: options.obsUrl,
        password: process.env.OBS_WEBSOCKET_PASSWORD,
        sceneName: options.obsSceneName,
        sourceName: options.obsSourceName,
        width: plugin.definition.viewport.width,
        height: plugin.definition.viewport.height,
        enableAudioMonitoring: plugin.enableObsAudioMonitoring,
      }
      preview =
        plugin.createObsAdapter?.(obsClient, obsOptions) ??
        new ObsPreviewAdapter(obsClient, obsOptions)
      await preview.prepare()
    }
    pluginState = await plugin.prepareRun?.(runContext)
    cleanupPlugin = cleanupPluginRun(plugin, runContext, pluginState)
    browser = await chromium.launch({
      headless: !options.headed,
      args: buildReviewBrowserArgs({
        requireObs: options.requireObs,
        enableObsAudioMonitoring: plugin.enableObsAudioMonitoring === true,
      }),
    })
    if (plugin.capabilities?.requireHardwareWebgl) await assertHardwareWebGl(browser)
    if (options.interactive) {
      terminal = createInterface({ input: stdin, output: stdout })
    }

    const attemptSummaries: AttemptSummary[] = []
    const result = await runReviewWorkflow<unknown, BrowserAttemptResult>({
      definition: plugin.definition,
      interactive: options.interactive,
      execute: (scene, attempt) => {
        const attemptContext = {
          ...runContext,
          sceneId: scene.id,
          attempt,
        }
        return executePluginAttempt(plugin, attemptContext, pluginState, (preparation) =>
          captureBrowserAttempt({
            browser: browser!,
            runDir,
            runId: currentRunId,
            scene,
            attempt,
            baseUrl: options.baseUrl,
            pageAdapter: plugin.pageAdapter,
            pageParams: preparation?.pageParams,
            initialAssertions: preparation?.assertions,
            preview: preview ?? undefined,
          }),
        )
      },
      decide: (technicalPassed) =>
        options.interactive
          ? interactiveDecision(technicalPassed, async () => {
              const scene = plugin.definition.scenes.find(
                ({ id }) =>
                  !attemptSummaries.some(
                    (attempt) => attempt.scene_id === id && attempt.outcome === 'passed',
                  ),
              )
              return options.verdict
                ? parseVerdict(options.verdict)
                : promptVerdict(
                    terminal!,
                    scene?.title ?? '当前场景',
                    scene?.observe ?? '检查最终画面。',
                  )
            })
          : Promise.resolve(automaticDecision(technicalPassed)),
      persist: async ({ sceneId, attempt, execution, decision }) => {
        const capturedAt = execution.finishedAt
        const audioSamples = Object.fromEntries(
          await Promise.all(
            Object.entries(execution.pluginArtifacts?.audioSamples ?? {}).map(
              async ([name, sample]) => [
                name,
                {
                  audio_wav: await optionalArtifact(runDir, sample.audioWav, capturedAt),
                  backend_report: await optionalArtifact(runDir, sample.backendReport, capturedAt),
                },
              ],
            ),
          ),
        )
        const [
          chromeScreenshot,
          chromeStableCrop,
          obsScreenshot,
          playwrightTrace,
          audioWav,
          backendReport,
          gameplayReport,
        ] = await Promise.all([
          optionalArtifact(runDir, execution.chromeScreenshot, capturedAt),
          optionalArtifact(runDir, execution.chromeStableCrop, capturedAt),
          optionalArtifact(runDir, execution.obsScreenshot, capturedAt),
          optionalArtifact(runDir, execution.playwrightTrace, capturedAt),
          optionalArtifact(runDir, execution.pluginArtifacts?.audioWav ?? null, capturedAt),
          optionalArtifact(runDir, execution.pluginArtifacts?.backendReport ?? null, capturedAt),
          optionalArtifact(runDir, execution.pluginArtifacts?.gameplayReport ?? null, capturedAt),
        ])
        const record: AttemptRecordV2 = {
          schema_version: EVIDENCE_SCHEMA_VERSION,
          run_id: currentRunId,
          scene_id: sceneId,
          attempt,
          outcome: decision.outcome,
          decision_source: decision.decisionSource,
          ...(decision.humanVerdict ? { human_verdict: decision.humanVerdict } : {}),
          ...(decision.humanNote ? { human_note: decision.humanNote } : {}),
          review_url: execution.reviewUrl,
          assertions: execution.assertions,
          artifacts: {
            chrome_screenshot: chromeScreenshot,
            chrome_stable_crop: chromeStableCrop,
            obs_screenshot: obsScreenshot,
            playwright_trace: playwrightTrace,
            ...(execution.pluginArtifacts
              ? {
                  audio_wav: audioWav,
                  backend_report: backendReport,
                  gameplay_report: gameplayReport,
                  ...(Object.keys(audioSamples).length > 0 ? { audio_samples: audioSamples } : {}),
                }
              : {}),
          },
          ...(execution.observations ? { observations: execution.observations } : {}),
          console_errors: execution.consoleErrors,
          page_errors: execution.pageErrors,
          failed_requests: execution.failedRequests,
          obs_mismatch_ratio: execution.obsMismatchRatio,
          started_at: execution.startedAt,
          finished_at: execution.finishedAt,
        }
        const evidencePath = await appendAttemptV2(runDir, record)
        attemptSummaries.push({
          scene_id: sceneId,
          attempt,
          outcome: decision.outcome,
          obs_screenshot: obsScreenshot,
          ...(execution.pluginArtifacts
            ? {
                audio_wav: audioWav,
                backend_report: backendReport,
                gameplay_report: gameplayReport,
                ...(Object.keys(audioSamples).length > 0 ? { audio_samples: audioSamples } : {}),
              }
            : {}),
          evidence: relativePath(runDir, evidencePath),
        })
      },
    })

    const summaryWithoutRounds: Omit<ReviewSummaryV2, 'stable_rounds'> = {
      schema_version: EVIDENCE_SCHEMA_VERSION,
      run_id: currentRunId,
      feature_id: plugin.definition.id,
      profile,
      decision_source: decisionSource,
      status: result.allPass ? 'passed' : 'failed',
      all_pass: result.allPass,
      workflow_fingerprint: fingerprint,
      scene_order: plugin.definition.scenes.map(({ id }) => id),
      attempts: attemptSummaries,
      started_at: startedAt,
      finished_at: new Date().toISOString(),
    }
    const previousSummaries = await loadValidatedV2Summaries(artifactsRoot, currentRunId)
    const summary: ReviewSummaryV2 = {
      ...summaryWithoutRounds,
      stable_rounds: computeStableRounds(previousSummaries, summaryWithoutRounds),
    }
    await writeJsonAtomic(join(runDir, 'summary.json'), summary)
    await writeJsonAtomic(join(runDir, 'run.json'), {
      ...manifest,
      status: summary.status,
      finished_at: summary.finished_at,
    })
    stdout.write(
      `评审结束：${summary.all_pass ? '全部通过' : '存在失败'}；稳定轮次 ${summary.stable_rounds}/2\n`,
    )
    stdout.write(`报告：${join(runDir, 'summary.json')}\n`)
    return summary
  } catch (error) {
    const finishedAt = new Date().toISOString()
    await writeJsonAtomic(join(runDir, 'run.json'), {
      ...manifest,
      status: interrupted ? 'interrupted' : 'failed',
      finished_at: finishedAt,
      failure: {
        type: error instanceof Error ? error.name : 'Error',
        reason: error instanceof Error ? error.message : String(error),
      },
    })
    throw error
  } finally {
    process.off('SIGINT', onSignal)
    process.off('SIGTERM', onSignal)
    await cleanup()
  }
}

function help(): string {
  return `Usage: pnpm review -- --feature <id> [options]

Features: ${REVIEW_FEATURE_IDS.join(', ')}

Options:
  --feature <id>       Review feature (default: live)
  --base-url <url>     Local page origin (default: http://127.0.0.1:3000)
  --interactive        Headed mode with pass / adjust / redo gate
  --headed             Show Playwright browser without human gate
  --no-obs             Browser-only diagnostics; excluded from stable rounds
  --obs-url <url>      OBS WebSocket URL
  --obs-scene <name>   Dedicated OBS scene
  --obs-source <name>  Dedicated OBS Browser Source
  --print-url          Print the feature URL without starting review services
  --help               Show this help`
}

export function exitCodeForSummary(summary: Pick<ReviewSummaryV2, 'all_pass'>): number {
  return summary.all_pass ? 0 : 1
}

const isEntrypoint = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)
if (isEntrypoint) {
  if (process.argv.includes('--help')) {
    stdout.write(`${help()}\n`)
  } else {
    runReviewCli()
      .then((result) => {
        if (typeof result === 'string') {
          stdout.write(`${result}\n`)
          return
        }
        process.exitCode = exitCodeForSummary(result)
      })
      .catch((error) => {
        console.error(error)
        process.exitCode = 1
      })
  }
}
