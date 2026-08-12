<script setup lang="ts">
import MemeWorkspace from '@/components/meme/MemeWorkspace.vue'
import MusicCard from '@/components/singing/MusicCard.vue'
import SectionTabs, { type SectionTab } from '@/components/shared/SectionTabs.vue'
import ProgramScriptEditor from './ProgramScriptEditor.vue'

defineProps<{ modelValue: string }>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const modes: readonly SectionTab[] = [
  { id: 'scripts', label: '脚本编排', description: '编辑、校验和发布结构化节目脚本' },
  { id: 'singing', label: '唱歌制作', description: '制作、核对并试听歌唱音轨' },
  { id: 'memes', label: 'Meme 梗库', description: '采集、分析和审核直播梗候选' },
]
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col" data-testid="program-workspace">
    <SectionTabs
      :model-value="modelValue"
      :tabs="modes"
      label="节目工作区"
      @update:model-value="emit('update:modelValue', $event)"
    />

    <main
      v-if="modelValue === 'scripts'"
      id="节目工作区-scripts-panel"
      role="tabpanel"
      aria-labelledby="节目工作区-scripts-tab"
      class="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3 sm:p-4"
    >
      <ProgramScriptEditor />
    </main>
    <main
      v-else-if="modelValue === 'singing'"
      id="节目工作区-singing-panel"
      role="tabpanel"
      aria-labelledby="节目工作区-singing-tab"
      class="min-h-0 flex-1 overflow-hidden p-3 sm:p-4"
    >
      <section class="glass h-full min-h-0 overflow-hidden">
        <MusicCard />
      </section>
    </main>
    <main
      v-else
      id="节目工作区-memes-panel"
      role="tabpanel"
      aria-labelledby="节目工作区-memes-tab"
      class="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3 sm:p-4"
    >
      <MemeWorkspace />
    </main>
  </div>
</template>
