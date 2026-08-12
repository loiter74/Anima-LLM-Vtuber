<script setup lang="ts">
import { ref } from 'vue'
import LiveOperationsWorkspace from '@/components/dashboard/LiveOperationsWorkspace.vue'
import ValidationWorkspace from '@/components/dashboard/ValidationWorkspace.vue'
import TitleBar from '@/components/layout/TitleBar.vue'
import MemoryWorkspace from '@/components/memory/MemoryWorkspace.vue'
import ProgramWorkspace from '@/components/program/ProgramWorkspace.vue'
import SectionTabs, { type SectionTab } from '@/components/shared/SectionTabs.vue'

const tasks: readonly SectionTab[] = [
  { id: 'live', label: '现场', description: '监看直播健康、节目进度和执行链路' },
  { id: 'program', label: '节目', description: '编排脚本、制作唱歌内容和治理 Meme' },
  { id: 'memory', label: '记忆', description: '整理、检索和修正长期记忆' },
  { id: 'validation', label: '验证', description: '私密演练对话并重放弹幕事件' },
]

const activeTask = ref('live')
const programMode = ref('scripts')
const validationMode = ref('sandbox')
const sandboxDraft = ref('')

function sendMemoryToSandbox(content: string): void {
  sandboxDraft.value = content
  validationMode.value = 'sandbox'
  activeTask.value = 'validation'
}
</script>

<template>
  <div class="ops-shell flex h-full min-h-0 flex-col text-c-text" data-testid="dashboard-page">
    <TitleBar />
    <SectionTabs v-model="activeTask" :tabs="tasks" label="后台任务" />

    <LiveOperationsWorkspace
      v-if="activeTask === 'live'"
      id="后台任务-live-panel"
      role="tabpanel"
      aria-labelledby="后台任务-live-tab"
    />
    <ProgramWorkspace
      v-else-if="activeTask === 'program'"
      id="后台任务-program-panel"
      v-model="programMode"
      role="tabpanel"
      aria-labelledby="后台任务-program-tab"
    />
    <MemoryWorkspace
      v-else-if="activeTask === 'memory'"
      id="后台任务-memory-panel"
      role="tabpanel"
      aria-labelledby="后台任务-memory-tab"
      @send-to-sandbox="sendMemoryToSandbox"
    />
    <ValidationWorkspace
      v-else
      id="后台任务-validation-panel"
      v-model="validationMode"
      role="tabpanel"
      aria-labelledby="后台任务-validation-tab"
      :draft="sandboxDraft"
    />
  </div>
</template>
