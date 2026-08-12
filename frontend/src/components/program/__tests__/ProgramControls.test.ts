import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ProgramRunPanel from '@/components/program/ProgramRunPanel.vue'
import ProgramReplayPanel from '@/components/program/ProgramReplayPanel.vue'
import ProgramScriptEditor from '@/components/program/ProgramScriptEditor.vue'
import unoConfig from '../../../../uno.config'

const api = vi.hoisted(() => ({
  listProgramScripts: vi.fn(),
  getProgramVersion: vi.fn(),
  getProgramDraft: vi.fn(),
  createProgramDraft: vi.fn(),
  saveProgramDraft: vi.fn(),
  validateProgramDraft: vi.fn(),
  publishProgramDraft: vi.fn(),
  duplicateProgramVersion: vi.fn(),
  archiveProgramScript: vi.fn(),
  startProgramRun: vi.fn(),
  getCurrentProgramRun: vi.fn(),
  getProgramRun: vi.fn(),
  submitProgramChoice: vi.fn(),
  controlProgramRun: vi.fn(),
  startProgramReplay: vi.fn(),
  getProgramReplay: vi.fn(),
  controlProgramReplay: vi.fn(),
}))

vi.mock('@/services/programScripts', () => ({
  ...api,
  ProgramApiError: class extends Error {
    issues = []
  },
}))

const programScript = {
  id: 'aura-copy',
  title: 'Aura 首播记忆游戏副本',
  description: '十二轮记忆回归',
  template: 'aura_debut_memory' as const,
  disclosure: '这是 AI 公开测试。',
  opening: '开始十二问。',
  closing: '十二问结束。',
  defaults: { reply_timeout_ms: 30000, memory_commit_timeout_ms: 15000 },
  option_sets: {
    nickname: [{ id: 'xiaolan', label: '小岚', danmaku: '以后叫我小岚吧', aliases: ['小岚'] }],
  },
  beats: [
    {
      id: 'q01',
      phase: 'qi' as const,
      host_prompt: '我以后怎么称呼你？',
      input: {
        type: 'choice' as const,
        options: 'nickname',
        save_as: 'nickname',
        text: null,
        exclude_slot: null,
      },
      memory: 'write' as const,
      thread: 'shared' as const,
      reply: { objective: '自然确认称呼', max_sentences: 2, max_chars: 60 },
      transition: { style: 'direct' as const, text: null },
      evaluator: null,
    },
  ],
}

const summary = {
  id: 'aura-debut-memory',
  title: 'Aura 首播记忆游戏',
  description: '十二轮记忆回归',
  builtin: true,
  archived: false,
  draft_revision: null,
  versions: [1],
}

function replay(state: 'running' | 'paused' | 'completed' = 'running') {
  return {
    replay_id: 'replay-1',
    room_id: 1,
    source: 'script' as const,
    state,
    speed: 1,
    cursor: state === 'running' ? 0 : 1,
    total_events: 12,
    error: null,
    current_event: {
      sequence: 0,
      offset_ms: 0,
      event_type: 'danmaku',
      actor_id: '首播测试观众',
      text: '以后叫我小岚吧',
      payload: {},
    },
  }
}

function plain<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

async function flushPromises() {
  for (let index = 0; index < 10; index += 1) await Promise.resolve()
}

describe('dashboard program controls', () => {
  beforeEach(() => {
    for (const mock of Object.values(api)) mock.mockReset()
    api.listProgramScripts.mockResolvedValue([summary])
    api.getProgramVersion.mockResolvedValue({
      version: 1,
      content_hash: 'a'.repeat(64),
      created_at: '2026-08-12T00:00:00Z',
      builtin: true,
      script: programScript,
    })
    api.duplicateProgramVersion.mockResolvedValue({ revision: 1, script: plain(programScript) })
    api.saveProgramDraft.mockImplementation(async (value) => ({
      revision: value.revision + 1,
      script: plain(value.script),
    }))
    api.validateProgramDraft.mockResolvedValue({ valid: true, issues: [] })
    api.publishProgramDraft.mockResolvedValue({
      version: 2,
      content_hash: 'b'.repeat(64),
      created_at: '2026-08-12T00:00:00Z',
      builtin: false,
      script: programScript,
    })
    api.startProgramReplay.mockResolvedValue(replay())
    api.getProgramReplay.mockResolvedValue(replay())
    api.controlProgramReplay.mockImplementation(async (_id, action) =>
      replay(action === 'pause' || action === 'step' ? 'paused' : 'running'),
    )
    api.getCurrentProgramRun.mockResolvedValue(null)
  })

  it('keeps unavailable actions visibly disabled with an enabling explanation', async () => {
    const shortcuts = unoConfig.shortcuts as Record<string, string>
    expect(shortcuts['btn-accent']).toContain('disabled:cursor-not-allowed')
    expect(shortcuts['btn-ghost']).toContain('disabled:cursor-not-allowed')

    const runPanel = mount(ProgramRunPanel)
    const replayPanel = mount(ProgramReplayPanel)
    const editor = mount(ProgramScriptEditor)
    await flushPromises()

    expect(runPanel.text()).toContain('开始节目后可使用暂停和停止')
    expect(replayPanel.text()).toContain('开始重放后可使用暂停、调速和重新开始')
    expect(editor.text()).toContain('填写“新草稿 ID”后可复制或新建')
    runPanel.unmount()
    replayPanel.unmount()
    editor.unmount()
  })

  it('requires a published script before replay can start', async () => {
    api.listProgramScripts.mockResolvedValueOnce([])
    const wrapper = mount(ProgramReplayPanel)
    await flushPromises()

    const start = wrapper.findAll('button').find((button) => button.text() === '开始')
    expect(start!.attributes()).toHaveProperty('disabled')
    expect(wrapper.text()).toContain('选择并加载已发布脚本后即可开始重放')
    wrapper.unmount()
  })

  it('copies, edits, previews, validates, and publishes a structured script', async () => {
    const wrapper = mount(ProgramScriptEditor)
    await flushPromises()
    const idInput = wrapper
      .findAll('input')
      .find((input) => input.attributes('placeholder') === 'weekend-talk-v1')
    await idInput!.setValue('aura-custom-v1')
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '复制所选版本')!
      .trigger('click')
    await flushPromises()

    await wrapper.get('[data-path="title"]').setValue('Aura 周末特别版')
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '顺序预览')!
      .trigger('click')
    expect(wrapper.get('[aria-label="观众视角顺序预览"]').text()).toContain('不调用模型')
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '校验')!
      .trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('后端完整校验通过')
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '发布')!
      .trigger('click')
    await flushPromises()

    expect(api.saveProgramDraft).toHaveBeenCalled()
    expect(api.publishProgramDraft).toHaveBeenCalledWith('aura-copy', 3)
    expect(wrapper.text()).toContain('已发布 v2')
    wrapper.unmount()
  })

  it('controls replay through pause, step, speed, restart, and stop boundaries', async () => {
    const wrapper = mount(ProgramReplayPanel)
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '开始')!
      .trigger('click')
    await flushPromises()

    for (const label of ['暂停', '单步', '应用速度', '重新开始', '停止']) {
      await wrapper
        .findAll('button')
        .find((button) => button.text() === label)!
        .trigger('click')
      await flushPromises()
    }

    expect(api.controlProgramReplay.mock.calls.map((call) => call[1])).toEqual([
      'pause',
      'step',
      'speed',
      'restart',
      'stop',
    ])
    wrapper.unmount()
  })
})
