<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ProgramApiError,
  archiveProgramScript,
  createProgramDraft,
  duplicateProgramVersion,
  getProgramDraft,
  listProgramScripts,
  publishProgramDraft,
  saveProgramDraft,
  validateProgramDraft,
  type ProgramBeat,
  type ProgramOption,
  type ProgramScript,
  type ProgramScriptDraft,
  type ProgramScriptSummary,
  type ValidationIssue,
} from '@/services/programScripts'

const scripts = ref<ProgramScriptSummary[]>([])
const draft = ref<ProgramScriptDraft | null>(null)
const selectedVersion = ref('')
const newId = ref('')
const newTitle = ref('')
const issues = ref<ValidationIssue[]>([])
const notice = ref('')
const error = ref('')
const loading = ref(false)
const previewOpen = ref(false)
const draggedBeat = ref<number | null>(null)

const phaseLabels = { qi: '起', cheng: '承', zhuan: '转', he: '合' } as const
const phaseOptions = Object.entries(phaseLabels) as Array<[ProgramBeat['phase'], string]>
const publishedChoices = computed(() =>
  scripts.value.flatMap((script) =>
    script.archived
      ? []
      : script.versions.map((version) => ({
          key: `${script.id}@${version}`,
          id: script.id,
          version,
          label: `${script.title} · v${version}${script.builtin ? ' · 内置模板' : ''}`,
        })),
  ),
)
const draftChoices = computed(() => scripts.value.filter((script) => script.draft_revision))
const optionSetIds = computed(() => Object.keys(draft.value?.script.option_sets ?? {}))
const selectedSummary = computed(() => {
  const choice = publishedChoices.value.find((item) => item.key === selectedVersion.value)
  return scripts.value.find((script) => script.id === choice?.id) ?? null
})
const slotIds = computed(() => {
  const slots = draft.value?.script.beats.flatMap((beat) => beat.input.save_as || []) ?? []
  return [...new Set(slots)]
})
const creationHint = computed(() => {
  if (loading.value) return '正在处理脚本，请稍候。'
  if (!newId.value.trim()) return '填写“新草稿 ID”后可复制或新建。'
  return '可以复制所选版本，或创建一个四轮通用草稿。'
})

onMounted(() => void refreshScripts())

async function refreshScripts() {
  await act(async () => {
    scripts.value = await listProgramScripts()
    selectedVersion.value ||= publishedChoices.value[0]?.key ?? ''
  })
}

async function loadDraft(id: string) {
  if (!id) return
  await act(async () => {
    draft.value = await getProgramDraft(id)
    issues.value = []
    previewOpen.value = false
    notice.value = `已加载草稿 r${draft.value.revision}`
  })
}

async function copyPublished() {
  const choice = publishedChoices.value.find((item) => item.key === selectedVersion.value)
  if (!choice || !newId.value.trim()) return
  await act(async () => {
    draft.value = await duplicateProgramVersion(
      choice.id,
      choice.version,
      newId.value.trim(),
      newTitle.value.trim() || undefined,
    )
    notice.value = `已复制为草稿 ${draft.value.script.id}`
    issues.value = []
    await refreshScriptsWithoutBusyState()
  })
}

async function createFourRound() {
  if (!newId.value.trim()) return
  const script = fourRoundStarter(newId.value.trim(), newTitle.value.trim())
  await act(async () => {
    draft.value = await createProgramDraft(script)
    notice.value = `已创建四轮通用草稿 ${script.id}`
    issues.value = []
    await refreshScriptsWithoutBusyState()
  })
}

async function archiveSelected() {
  const choice = publishedChoices.value.find((item) => item.key === selectedVersion.value)
  if (!choice || selectedSummary.value?.builtin) return
  await act(async () => {
    await archiveProgramScript(choice.id)
    notice.value = `已归档 ${choice.id}`
    selectedVersion.value = ''
    await refreshScriptsWithoutBusyState()
  })
}

async function save() {
  if (!draft.value) return
  await act(async () => {
    draft.value = await saveProgramDraft(draft.value!)
    notice.value = `草稿已保存为 r${draft.value.revision}`
    issues.value = []
    await refreshScriptsWithoutBusyState()
  })
}

async function validate() {
  if (!draft.value) return
  await act(async () => {
    draft.value = await saveProgramDraft(draft.value!)
    const result = await validateProgramDraft(draft.value.script.id)
    issues.value = result.issues
    notice.value = result.valid
      ? '后端完整校验通过，可以发布'
      : `发现 ${result.issues.length} 个问题`
  })
}

async function publish() {
  if (!draft.value) return
  await act(async () => {
    draft.value = await saveProgramDraft(draft.value!)
    const result = await validateProgramDraft(draft.value.script.id)
    issues.value = result.issues
    if (!result.valid) {
      notice.value = `发布已阻止：还有 ${result.issues.length} 个问题`
      return
    }
    const published = await publishProgramDraft(draft.value.script.id, draft.value.revision)
    notice.value = `已发布 v${published.version} · ${published.content_hash.slice(0, 12)}…`
    draft.value = null
    previewOpen.value = false
    await refreshScriptsWithoutBusyState()
  })
}

async function refreshScriptsWithoutBusyState() {
  scripts.value = await listProgramScripts()
  selectedVersion.value ||= publishedChoices.value[0]?.key ?? ''
}

function addOptionSet() {
  if (!draft.value) return
  let index = Object.keys(draft.value.script.option_sets).length + 1
  let id = `options_${index}`
  while (draft.value.script.option_sets[id]) id = `options_${++index}`
  draft.value.script.option_sets[id] = [newOption('option_1')]
}

function renameOptionSet(oldId: string, event: Event) {
  if (!draft.value) return
  const nextId = (event.target as HTMLInputElement).value.trim()
  if (!nextId || nextId === oldId || draft.value.script.option_sets[nextId]) return
  const sets = draft.value.script.option_sets
  sets[nextId] = sets[oldId]
  delete sets[oldId]
  for (const beat of draft.value.script.beats) {
    if (beat.input.options === oldId) beat.input.options = nextId
  }
}

function removeOptionSet(id: string) {
  if (!draft.value) return
  delete draft.value.script.option_sets[id]
}

function addOption(setId: string) {
  if (!draft.value) return
  const options = draft.value.script.option_sets[setId]
  options.push(newOption(`option_${options.length + 1}`))
}

function updateAliases(option: ProgramOption, event: Event) {
  option.aliases = (event.target as HTMLInputElement).value
    .split(/[，,]/)
    .map((alias) => alias.trim())
    .filter(Boolean)
}

function addBeat() {
  if (!draft.value) return
  const index = draft.value.script.beats.length + 1
  draft.value.script.beats.push(newBeat(`beat_${index}`, 'he'))
}

function duplicateBeat(index: number) {
  if (!draft.value) return
  const copy = structuredClone(draft.value.script.beats[index])
  copy.id = uniqueBeatId(`${copy.id}_copy`)
  draft.value.script.beats.splice(index + 1, 0, copy)
}

function removeBeat(index: number) {
  draft.value?.script.beats.splice(index, 1)
}

function moveBeat(index: number, offset: number) {
  if (!draft.value) return
  const target = index + offset
  if (target < 0 || target >= draft.value.script.beats.length) return
  const [beat] = draft.value.script.beats.splice(index, 1)
  draft.value.script.beats.splice(target, 0, beat)
}

function dropBeat(target: number) {
  if (draggedBeat.value == null || !draft.value || draggedBeat.value === target) return
  const [beat] = draft.value.script.beats.splice(draggedBeat.value, 1)
  draft.value.script.beats.splice(target, 0, beat)
  draggedBeat.value = null
}

function changeInputType(beat: ProgramBeat) {
  if (beat.input.type === 'choice') {
    beat.input.options = optionSetIds.value[0] ?? null
    beat.input.save_as ||= 'answer'
    beat.input.text = null
  } else {
    beat.input.options = null
    beat.input.save_as = null
    beat.input.text ||= '测试观众的固定弹幕'
    beat.input.exclude_slot = null
    if (beat.memory === 'write') beat.memory = 'none'
  }
}

function changeMemory(beat: ProgramBeat) {
  if (beat.memory !== 'probe') {
    beat.thread = 'shared'
    beat.evaluator = null
  }
}

function toggleEvaluator(beat: ProgramBeat) {
  beat.evaluator = beat.evaluator
    ? null
    : {
        type: 'recall_slots',
        slots: slotIds.value.slice(0, 1),
        false_values: [],
        rejection_markers: ['不是', '不对', '没有', '记错'],
      }
}

function focusIssue(path: string) {
  document.querySelector<HTMLElement>(`[data-path="${CSS.escape(path)}"]`)?.scrollIntoView({
    behavior: 'smooth',
    block: 'center',
  })
}

function uniqueBeatId(base: string) {
  const ids = new Set(draft.value?.script.beats.map((beat) => beat.id))
  let id = base
  let index = 2
  while (ids.has(id)) id = `${base}_${index++}`
  return id
}

function newOption(id: string): ProgramOption {
  return { id, label: '新选项', danmaku: '我的选择是新选项', aliases: ['新选项'] }
}

function newBeat(id: string, phase: ProgramBeat['phase']): ProgramBeat {
  return {
    id,
    phase,
    host_prompt: 'Aura 的固定提问',
    input: {
      type: 'fixed',
      options: null,
      save_as: null,
      text: '测试观众的固定弹幕',
      exclude_slot: null,
    },
    memory: 'none',
    thread: 'shared',
    reply: { objective: '自然回应本轮弹幕，不要擅自推进节目', max_sentences: 2, max_chars: 80 },
    transition: { style: 'direct', text: null },
    evaluator: null,
  }
}

function fourRoundStarter(id: string, title: string): ProgramScript {
  return {
    id,
    title: title || '四轮节目草稿',
    description: '不绑定 Aura 专项规则的四轮线性节目。',
    template: null,
    disclosure: '本环节由 AI 实时生成。',
    opening: '欢迎来到今天的小环节。',
    closing: '四轮结束，谢谢参与。',
    defaults: { reply_timeout_ms: 30000, memory_commit_timeout_ms: 15000 },
    option_sets: {},
    beats: [
      newBeat('q01', 'qi'),
      newBeat('q02', 'cheng'),
      newBeat('q03', 'zhuan'),
      newBeat('q04', 'he'),
    ],
  }
}

async function act(operation: () => Promise<void>) {
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    await operation()
  } catch (reason) {
    if (reason instanceof ProgramApiError && reason.issues.length) issues.value = reason.issues
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="space-y-3" aria-label="节目脚本编辑器">
    <div class="glass p-4">
      <div class="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(260px,1fr)_auto_auto_auto]">
        <label class="text-xs text-c-text-dim">
          已发布版本（只读）
          <select v-model="selectedVersion" class="form-control mt-1">
            <option v-for="choice in publishedChoices" :key="choice.key" :value="choice.key">
              {{ choice.label }}
            </option>
          </select>
        </label>
        <label class="text-xs text-c-text-dim">
          新草稿 ID
          <input v-model="newId" class="form-control mt-1" placeholder="weekend-talk-v1" />
        </label>
        <button
          class="btn-ghost self-end border border-c-border"
          :disabled="loading || !newId.trim()"
          aria-describedby="program-script-create-hint"
          @click="copyPublished"
        >
          复制所选版本
        </button>
        <button
          class="btn-ghost self-end border border-c-border"
          :disabled="loading || !newId.trim()"
          aria-describedby="program-script-create-hint"
          @click="createFourRound"
        >
          新建四轮草稿
        </button>
        <button
          v-if="selectedSummary && !selectedSummary.builtin"
          class="btn-ghost self-end border border-c-error/40 text-c-error"
          :disabled="loading"
          @click="archiveSelected"
        >
          归档脚本
        </button>
      </div>
      <p id="program-script-create-hint" class="mt-2 text-xs text-c-text-muted" aria-live="polite">
        {{ creationHint }}
      </p>
      <div class="mt-3 flex flex-wrap items-end gap-3">
        <label class="min-w-64 flex-1 text-xs text-c-text-dim">
          新草稿名称（可选）
          <input v-model="newTitle" class="form-control mt-1" placeholder="周末聊天小环节" />
        </label>
        <label class="min-w-64 flex-1 text-xs text-c-text-dim">
          已有草稿
          <select
            class="form-control mt-1"
            @change="loadDraft(($event.target as HTMLSelectElement).value)"
          >
            <option value="">选择草稿…</option>
            <option v-for="item in draftChoices" :key="item.id" :value="item.id">
              {{ item.title }} · r{{ item.draft_revision }}
            </option>
          </select>
        </label>
      </div>
    </div>

    <template v-if="draft">
      <div class="glass p-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 class="text-sm font-semibold">基本信息</h2>
            <p class="mt-1 text-xs text-c-text-muted">
              草稿 r{{ draft.revision }} · 发布后版本不可修改
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              class="btn-ghost border border-c-border"
              :disabled="loading"
              @click="previewOpen = !previewOpen"
            >
              {{ previewOpen ? '关闭预览' : '顺序预览' }}
            </button>
            <button class="btn-ghost border border-c-border" :disabled="loading" @click="save">
              保存
            </button>
            <button class="btn-ghost border border-c-border" :disabled="loading" @click="validate">
              校验
            </button>
            <button class="btn-accent" :disabled="loading" @click="publish">发布</button>
          </div>
        </div>

        <div class="mt-4 grid gap-3 md:grid-cols-2">
          <label class="text-xs text-c-text-dim"
            >脚本 ID<input
              v-model="draft.script.id"
              data-path="id"
              class="form-control mt-1"
              readonly
          /></label>
          <label class="text-xs text-c-text-dim"
            >名称<input v-model="draft.script.title" data-path="title" class="form-control mt-1"
          /></label>
          <label class="text-xs text-c-text-dim md:col-span-2"
            >说明<textarea
              v-model="draft.script.description"
              data-path="description"
              class="form-control mt-1 min-h-18"
            />
          </label>
          <label class="text-xs text-c-text-dim md:col-span-2"
            >AI 公开测试标识<input
              v-model="draft.script.disclosure"
              data-path="disclosure"
              class="form-control mt-1"
          /></label>
          <label class="text-xs text-c-text-dim"
            >开场文案<textarea
              v-model="draft.script.opening"
              data-path="opening"
              class="form-control mt-1 min-h-18"
            />
          </label>
          <label class="text-xs text-c-text-dim"
            >结束文案<textarea
              v-model="draft.script.closing"
              data-path="closing"
              class="form-control mt-1 min-h-18"
            />
          </label>
        </div>
      </div>

      <section v-if="previewOpen" class="glass p-4" aria-label="观众视角顺序预览">
        <div class="flex items-center justify-between gap-3">
          <div>
            <h2 class="text-sm font-semibold">观众视角顺序预览</h2>
            <p class="mt-1 text-xs text-c-text-muted">纯本地展开，不调用模型、不写入记忆</p>
          </div>
          <span class="rounded-xl bg-c-accent-soft px-2 py-1 text-xs text-c-accent"
            >{{ draft.script.beats.length }} 轮</span
          >
        </div>
        <p class="mt-4 rounded-xl bg-c-panel/40 p-3 text-sm">{{ draft.script.opening }}</p>
        <ol class="mt-3 grid gap-3 md:grid-cols-2">
          <li
            v-for="(beat, index) in draft.script.beats"
            :key="beat.id"
            class="rounded-xl border border-c-border bg-c-panel/30 p-3"
          >
            <div class="flex items-center gap-2 text-xs">
              <span class="text-c-accent">{{ phaseLabels[beat.phase] }}</span
              ><span class="font-mono text-c-text-muted">{{ index + 1 }} · {{ beat.id }}</span>
            </div>
            <p class="mt-2 text-sm font-medium">Aura：{{ beat.host_prompt || '（无固定提问）' }}</p>
            <p class="mt-2 text-xs text-c-text-secondary">
              观众：{{
                beat.input.type === 'fixed' ? beat.input.text : `从 ${beat.input.options} 选择`
              }}
            </p>
            <p class="mt-2 text-xs text-c-text-muted">回复目标：{{ beat.reply.objective }}</p>
            <p v-if="beat.transition.style === 'soft'" class="mt-2 text-xs text-c-accent">
              转场：{{ beat.transition.text }}
            </p>
          </li>
        </ol>
        <p class="mt-3 rounded-xl bg-c-panel/40 p-3 text-sm">{{ draft.script.closing }}</p>
      </section>

      <section class="glass p-4" aria-label="选项集编辑器">
        <div class="flex items-center justify-between gap-3">
          <div>
            <h2 class="text-sm font-semibold">选项集</h2>
            <p class="mt-1 text-xs text-c-text-muted">ID、公开弹幕文本与语义别名共用同一配置</p>
          </div>
          <button class="btn-ghost border border-c-border" @click="addOptionSet">新增选项集</button>
        </div>
        <div class="mt-4 space-y-3">
          <article
            v-for="(options, setId) in draft.script.option_sets"
            :key="setId"
            class="rounded-xl border border-c-border bg-c-panel/30 p-3"
          >
            <div class="flex flex-wrap items-end gap-2">
              <label class="min-w-44 flex-1 text-xs text-c-text-dim"
                >选项集 ID<input
                  :value="setId"
                  class="form-control mt-1"
                  @change="renameOptionSet(String(setId), $event)"
              /></label>
              <button class="btn-ghost border border-c-border" @click="addOption(String(setId))">
                添加选项
              </button>
              <button
                class="btn-ghost border border-c-error/40 text-c-error"
                @click="removeOptionSet(String(setId))"
              >
                删除集合
              </button>
            </div>
            <div class="mt-3 space-y-2">
              <div
                v-for="(option, optionIndex) in options"
                :key="optionIndex"
                class="grid gap-2 rounded-xl bg-c-card/45 p-3 md:grid-cols-[0.7fr_1fr_1.5fr_1.5fr_auto]"
              >
                <label class="text-10px text-c-text-muted"
                  >选项 ID<input v-model="option.id" class="form-control mt-1"
                /></label>
                <label class="text-10px text-c-text-muted"
                  >显示名称<input v-model="option.label" class="form-control mt-1"
                /></label>
                <label class="text-10px text-c-text-muted"
                  >实际弹幕<input v-model="option.danmaku" class="form-control mt-1"
                /></label>
                <label class="text-10px text-c-text-muted"
                  >语义别名（逗号分隔）<input
                    :value="option.aliases.join('，')"
                    class="form-control mt-1"
                    @change="updateAliases(option, $event)"
                /></label>
                <button
                  class="btn-ghost self-end text-c-error"
                  :aria-label="`删除选项 ${option.label}`"
                  @click="options.splice(optionIndex, 1)"
                >
                  删除
                </button>
              </div>
            </div>
          </article>
          <p v-if="!optionSetIds.length" class="text-xs text-c-text-muted">
            当前脚本没有选项集；固定弹幕节目可以直接编辑问题。
          </p>
        </div>
      </section>

      <section class="glass p-4" aria-label="问题列表编辑器">
        <div class="flex items-center justify-between gap-3">
          <div>
            <h2 class="text-sm font-semibold">问题列表</h2>
            <p class="mt-1 text-xs text-c-text-muted">
              拖动或使用上下按钮排序；下一题始终是列表中的下一项
            </p>
          </div>
          <button class="btn-accent" @click="addBeat">新增问题</button>
        </div>
        <div class="mt-4 space-y-3">
          <article
            v-for="(beat, index) in draft.script.beats"
            :key="`${beat.id}-${index}`"
            :data-path="`beats.${index}`"
            draggable="true"
            class="rounded-xl border border-c-border bg-c-panel/30 p-4"
            @dragstart="draggedBeat = index"
            @dragend="draggedBeat = null"
            @dragover.prevent
            @drop="dropBeat(index)"
          >
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div class="flex items-center gap-2">
                <span class="cursor-grab text-c-text-muted">⋮⋮</span
                ><strong class="text-sm">{{ index + 1 }}. {{ beat.id }}</strong
                ><span class="rounded-xl bg-c-accent-soft px-2 py-1 text-xs text-c-accent">{{
                  phaseLabels[beat.phase]
                }}</span>
              </div>
              <div class="flex gap-1">
                <button
                  class="btn-ghost"
                  :disabled="index === 0"
                  aria-label="上移问题"
                  @click="moveBeat(index, -1)"
                >
                  ↑
                </button>
                <button
                  class="btn-ghost"
                  :disabled="index === draft.script.beats.length - 1"
                  aria-label="下移问题"
                  @click="moveBeat(index, 1)"
                >
                  ↓
                </button>
                <button class="btn-ghost" @click="duplicateBeat(index)">复制</button>
                <button class="btn-ghost text-c-error" @click="removeBeat(index)">删除</button>
              </div>
            </div>

            <div class="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <label class="text-xs text-c-text-dim"
                >问题 ID<input v-model="beat.id" class="form-control mt-1"
              /></label>
              <label class="text-xs text-c-text-dim"
                >阶段<select v-model="beat.phase" class="form-control mt-1">
                  <option v-for="[value, label] in phaseOptions" :key="value" :value="value">
                    {{ label }}
                  </option>
                </select></label
              >
              <label class="text-xs text-c-text-dim md:col-span-2"
                >Aura 固定提问<input v-model="beat.host_prompt" class="form-control mt-1"
              /></label>
              <label class="text-xs text-c-text-dim"
                >输入方式<select
                  v-model="beat.input.type"
                  class="form-control mt-1"
                  @change="changeInputType(beat)"
                >
                  <option value="choice">Creator 选择</option>
                  <option value="fixed">固定弹幕</option>
                </select></label
              >
              <template v-if="beat.input.type === 'choice'">
                <label class="text-xs text-c-text-dim"
                  >选项集<select v-model="beat.input.options" class="form-control mt-1">
                    <option v-for="id in optionSetIds" :key="id" :value="id">{{ id }}</option>
                  </select></label
                >
                <label class="text-xs text-c-text-dim"
                  >答案槽<input v-model="beat.input.save_as" class="form-control mt-1"
                /></label>
                <label class="text-xs text-c-text-dim"
                  >排除旧槽值（可选）<select
                    v-model="beat.input.exclude_slot"
                    class="form-control mt-1"
                  >
                    <option :value="null">不排除</option>
                    <option v-for="slot in slotIds" :key="slot" :value="slot">{{ slot }}</option>
                  </select></label
                >
              </template>
              <label v-else class="text-xs text-c-text-dim md:col-span-2 xl:col-span-3"
                >固定弹幕<input
                  v-model="beat.input.text"
                  :data-path="`beats.${index}.input.text`"
                  class="form-control mt-1"
              /></label>
              <label class="text-xs text-c-text-dim"
                >记忆行为<select
                  v-model="beat.memory"
                  class="form-control mt-1"
                  @change="changeMemory(beat)"
                >
                  <option value="write">写入</option>
                  <option value="probe">探测</option>
                  <option value="none">不处理</option>
                </select></label
              >
              <label class="text-xs text-c-text-dim"
                >对话<select
                  v-model="beat.thread"
                  class="form-control mt-1"
                  :disabled="beat.memory !== 'probe'"
                >
                  <option value="shared">共享对话</option>
                  <option value="isolated">隔离对话</option>
                </select></label
              >
              <label class="text-xs text-c-text-dim md:col-span-2"
                >本轮回复目标<input v-model="beat.reply.objective" class="form-control mt-1"
              /></label>
              <label class="text-xs text-c-text-dim"
                >最多句数<input
                  v-model.number="beat.reply.max_sentences"
                  type="number"
                  min="1"
                  max="5"
                  class="form-control mt-1"
              /></label>
              <label class="text-xs text-c-text-dim"
                >最多字数<input
                  v-model.number="beat.reply.max_chars"
                  type="number"
                  min="20"
                  max="500"
                  class="form-control mt-1"
              /></label>
              <label class="text-xs text-c-text-dim"
                >转场<select
                  v-model="beat.transition.style"
                  class="form-control mt-1"
                  @change="
                    beat.transition.text =
                      beat.transition.style === 'soft'
                        ? beat.transition.text || '自然接到下一题。'
                        : null
                  "
                >
                  <option value="direct">直接闭环后提问</option>
                  <option value="soft">柔和引导</option>
                </select></label
              >
              <label v-if="beat.transition.style === 'soft'" class="text-xs text-c-text-dim"
                >柔和转场固定文案<input v-model="beat.transition.text" class="form-control mt-1"
              /></label>
            </div>

            <div
              v-if="beat.memory === 'probe'"
              class="mt-3 rounded-xl border border-c-border bg-c-card/35 p-3"
            >
              <div class="flex items-center justify-between gap-3">
                <div>
                  <h3 class="text-xs font-medium">记忆评估器（可选）</h3>
                  <p class="mt-1 text-10px text-c-text-muted">
                    只记录 matched / not_matched / inconclusive 与原始问答
                  </p>
                </div>
                <button class="btn-ghost border border-c-border" @click="toggleEvaluator(beat)">
                  {{ beat.evaluator ? '移除评估器' : '添加评估器' }}
                </button>
              </div>
              <div v-if="beat.evaluator" class="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <label class="text-xs text-c-text-dim"
                  >类型<select v-model="beat.evaluator.type" class="form-control mt-1">
                    <option value="recall_slots">召回答案槽</option>
                    <option value="latest_slot">最新槽值</option>
                    <option value="reject_false_premise">拒绝错误前提</option>
                    <option value="composite_slots">组合召回</option>
                  </select></label
                >
                <label class="text-xs text-c-text-dim"
                  >答案槽（逗号分隔）<input
                    :value="beat.evaluator.slots.join('，')"
                    class="form-control mt-1"
                    @change="
                      beat.evaluator!.slots = ($event.target as HTMLInputElement).value
                        .split(/[，,]/)
                        .map((value) => value.trim())
                        .filter(Boolean)
                    "
                /></label>
                <label class="text-xs text-c-text-dim"
                  >错误值（逗号分隔）<input
                    :value="beat.evaluator.false_values.join('，')"
                    class="form-control mt-1"
                    @change="
                      beat.evaluator!.false_values = ($event.target as HTMLInputElement).value
                        .split(/[，,]/)
                        .map((value) => value.trim())
                        .filter(Boolean)
                    "
                /></label>
                <label class="text-xs text-c-text-dim"
                  >拒绝词（逗号分隔）<input
                    :value="beat.evaluator.rejection_markers.join('，')"
                    class="form-control mt-1"
                    @change="
                      beat.evaluator!.rejection_markers = ($event.target as HTMLInputElement).value
                        .split(/[，,]/)
                        .map((value) => value.trim())
                        .filter(Boolean)
                    "
                /></label>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section
        v-if="issues.length"
        class="glass border border-c-error/40 p-4"
        aria-label="脚本校验结果"
      >
        <h2 class="text-sm font-semibold text-c-error">校验结果</h2>
        <ol class="mt-3 space-y-2">
          <li v-for="issue in issues" :key="`${issue.path}-${issue.code}`">
            <button
              class="w-full rounded-xl bg-c-error/10 px-3 py-2 text-left text-xs text-c-error"
              @click="focusIssue(issue.path)"
            >
              <span class="font-mono">{{ issue.path }}</span> · {{ issue.message }}
            </button>
          </li>
        </ol>
      </section>
    </template>

    <div v-else class="glass grid min-h-56 place-items-center p-6 text-center">
      <div>
        <p class="text-sm text-c-text-secondary">先复制一个已发布版本，或创建四轮通用草稿</p>
        <p class="mt-1 text-xs text-c-text-muted">直播中的已发布快照不会被草稿编辑影响</p>
      </div>
    </div>

    <p
      v-if="notice"
      class="rounded-xl border border-c-success/40 bg-c-success/10 px-3 py-2 text-xs text-c-success"
      role="status"
    >
      {{ notice }}
    </p>
    <p
      v-if="error"
      class="rounded-xl border border-c-error/40 bg-c-error/10 px-3 py-2 text-xs text-c-error"
      role="alert"
    >
      {{ error }}
    </p>
  </section>
</template>

<style scoped>
.form-control {
  width: 100%;
  border: 1px solid var(--c-border);
  border-radius: var(--r-xl);
  background: var(--c-panel);
  padding: 0.5rem 0.75rem;
  color: var(--c-text);
  font-size: 0.875rem;
  outline: none;
  transition: border-color 200ms var(--ease-out-expo);
}

.form-control:focus {
  border-color: var(--c-border-accent);
}
</style>
