import { describe, expect, it } from 'vitest'

import { mountMinecraftGameplayShell } from './page'

describe('minecraft gameplay preview shell', () => {
  it('renders only the broadcast surfaces required by the approved composition', () => {
    const handle = mountMinecraftGameplayShell(document, new URLSearchParams('preview=1'))

    expect(handle.element.dataset.mode).toBe('preview')
    expect(handle.element.style.getPropertyValue('--broadcast-width')).toBe('1920px')
    expect(handle.element.style.getPropertyValue('--screen-width')).toBe('1488px')
    expect(document.querySelector('[aria-label="Minecraft 游戏画面"]')).not.toBeNull()
    expect(document.querySelector('[aria-label="实时弹幕"]')).not.toBeNull()
    expect(document.querySelector('[aria-label="直播字幕"]')).not.toBeNull()
    expect(document.querySelector('[aria-label="虹色 Mao 主播"]')).not.toBeNull()
    expect(document.querySelector('[aria-label="附身状态"]')?.textContent).toContain('等待 LUN077')
    expect(document.body.textContent).not.toContain('BotDashboard')
    expect(document.body.textContent).not.toContain('表情调试')

    handle.dispose()
    expect(document.querySelector('.minecraft-gameplay')).toBeNull()
  })

  it('turns the game aperture into a transparent OBS hole in overlay mode', () => {
    const handle = mountMinecraftGameplayShell(document, new URLSearchParams('overlay=1'))

    expect(handle.element.dataset.mode).toBe('overlay')
    expect(handle.element.querySelector('.game-aperture')?.getAttribute('data-transparent')).toBe(
      'true',
    )

    handle.dispose()
  })

  it('disposes idempotently', () => {
    const handle = mountMinecraftGameplayShell(document, new URLSearchParams('preview=1'))

    handle.dispose()
    expect(() => handle.dispose()).not.toThrow()
  })

  it('renders confirmed attachment and bounded review audio parameters', () => {
    const handle = mountMinecraftGameplayShell(
      document,
      new URLSearchParams({
        overlay: '1',
        review: '1',
        bindingState: 'following',
        confirmed: 'true',
        target: 'AnimettaBot',
        attempt: '2',
        reason: 'viewer_joined',
        audio: 'http://127.0.0.1:49152/artifacts/review.wav',
        mouthTimeline: '[0,0.3,0.8,0.1]',
        subtitle: '铁装流程开始，本小姐要认真起来了。',
      }),
    )

    const status = document.querySelector<HTMLElement>('[aria-label="附身状态"]')
    expect(status?.dataset.confirmed).toBe('true')
    expect(status?.dataset.bindingState).toBe('following')
    expect(status?.textContent).toContain('已附身 LUN077 → AnimettaBot')
    expect(document.querySelector('[aria-label="直播字幕"]')?.textContent).toContain('铁装流程开始')
    const runtime = document.querySelector<HTMLElement>('.minecraft-review-runtime')
    expect(runtime?.dataset.mouthTimeline).toBe('[0,0.3,0.8,0.1]')
    expect(runtime?.querySelector('audio')?.src).toBe('http://127.0.0.1:49152/artifacts/review.wav')

    handle.dispose()
  })

  it('rejects untrusted review audio origins and invalid mouth samples', () => {
    const handle = mountMinecraftGameplayShell(
      document,
      new URLSearchParams({
        review: '1',
        audio: 'https://example.com/private.wav',
        mouthTimeline: '[0,-1,2]',
      }),
    )

    expect(document.querySelector('.minecraft-review-runtime')).toBeNull()
    handle.dispose()
  })

  it('renders the adaptive evidence timeline with current run identity', () => {
    const handle = mountMinecraftGameplayShell(
      document,
      new URLSearchParams({
        preview: '1',
        timeline: '1',
        runId: 'showcase-run-001',
        missionId: 'adaptive-showcase-001',
        stage: 'construction',
        completed: 'scenario-setup,capture-readiness,dialogue,mission-admission',
      }),
    )

    const timeline = document.querySelector<HTMLElement>('[aria-label="任务证据时间线"]')
    expect(timeline?.querySelectorAll('.showcase-stage')).toHaveLength(12)
    expect(timeline?.textContent).toContain('showcase-run-001')
    expect(timeline?.textContent).toContain('adaptive-showcase-001')
    expect(timeline?.textContent).toContain('场景布置不计入任务成绩')
    expect(timeline?.querySelector('[aria-current="step"]')?.textContent).toContain('建造验证')
    expect(timeline?.querySelectorAll('[data-stage-state="completed"]')).toHaveLength(4)

    handle.dispose()
  })

  it('renders StageIO v2 details and checkpoints without copying raw artifacts', () => {
    const stageIO = [
      {
        schema_version: '2',
        run_id: 'showcase-run-001',
        mission_id: 'adaptive-showcase-001',
        stage_id: 'combat',
        ordinal: 5,
        gameplay_evidence_eligible: true,
        lifecycle: 'passed',
        started_at_ms: 100,
        finished_at_ms: 240,
        input_refs: [
          {
            schema_version: '1',
            artifact_id: 'mission',
            artifact_kind: 'mission',
            json_pointer: '/objectives/0',
            content_hash: 'a'.repeat(64),
          },
        ],
        decision_source: 'voyager-controller',
        reason_code: 'VERIFIED',
        selected_capability: 'attack',
        output_refs: [
          {
            schema_version: '1',
            artifact_id: 'receipts',
            artifact_kind: 'receipts',
            json_pointer: '/0',
            content_hash: 'b'.repeat(64),
          },
        ],
        state_deltas: [{ path: '/entities/zombie', before: 'alive', after: 'defeated' }],
        verifier: 'EntityDefeated',
        predicates: [
          {
            predicate_id: 'combat-verified',
            expected: true,
            actual: { defeated_types: ['zombie', 'skeleton', 'spider'] },
            status: 'pass',
          },
        ],
        checkpoints: [
          {
            schema_version: '1',
            checkpoint_id: 'zombie',
            label: 'zombie',
            lifecycle: 'passed',
            verifier: 'EntityDefeated',
            predicates: [],
            input_refs: [],
            output_refs: [],
            evidence_refs: [],
          },
        ],
        evidence_refs: [],
        media: [],
      },
    ]
    const handle = mountMinecraftGameplayShell(
      document,
      new URLSearchParams({
        preview: '1',
        timeline: '1',
        stage: 'combat',
        stageIO: JSON.stringify(stageIO),
      }),
    )

    const combat = document.querySelector<HTMLElement>('[data-stage-id="combat"]')
    expect(combat?.dataset.stageState).toBe('passed')
    expect(combat?.textContent).toContain('100 → 240 ms')
    expect(combat?.textContent).toContain('mission#/objectives/0')
    expect(combat?.textContent).toContain('voyager-controller · VERIFIED · attack')
    expect(combat?.textContent).toContain('/entities/zombie: "alive" → "defeated"')
    expect(combat?.textContent).toContain('EntityDefeated · pass')
    expect(combat?.textContent).toContain('zombie · passed')
    expect(combat?.textContent).not.toContain('private_reasoning')

    handle.dispose()
  })
})
