<script setup lang="ts">
import { ref, watch } from 'vue'
import ProgramReplayPanel from '@/components/program/ProgramReplayPanel.vue'
import SectionTabs, { type SectionTab } from '@/components/shared/SectionTabs.vue'
import ConversationSandbox from './ConversationSandbox.vue'

const props = defineProps<{
  modelValue: string
  draft?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const sandboxDraft = ref(props.draft ?? '')

watch(
  () => props.draft,
  (value) => {
    if (value !== undefined) sandboxDraft.value = value
  },
)

const modes: readonly SectionTab[] = [
  { id: 'sandbox', label: '对话沙盒', description: '使用当前模型私密演练并核对执行证据' },
  { id: 'replay', label: '弹幕重放', description: '用节目脚本或 JSONL 验证直播执行' },
]
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col" data-testid="validation-workspace">
    <SectionTabs
      :model-value="modelValue"
      :tabs="modes"
      label="验证工作区"
      @update:model-value="emit('update:modelValue', $event)"
    />

    <main
      v-if="modelValue === 'sandbox'"
      id="验证工作区-sandbox-panel"
      role="tabpanel"
      aria-labelledby="验证工作区-sandbox-tab"
      class="min-h-0 flex-1 overflow-hidden p-3 sm:p-4"
    >
      <ConversationSandbox v-model="sandboxDraft" />
    </main>
    <main
      v-else
      id="验证工作区-replay-panel"
      role="tabpanel"
      aria-labelledby="验证工作区-replay-tab"
      class="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3 sm:p-4"
    >
      <ProgramReplayPanel />
    </main>
  </div>
</template>
