<script setup lang="ts">
import { nextTick, onBeforeUpdate } from 'vue'
import type { ComponentPublicInstance } from 'vue'

export interface SectionTab {
  id: string
  label: string
  description?: string
}

const props = defineProps<{
  tabs: readonly SectionTab[]
  modelValue: string
  label: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const tabRefs = new Map<string, HTMLButtonElement>()

onBeforeUpdate(() => tabRefs.clear())

function setTabRef(id: string, element: Element | ComponentPublicInstance | null): void {
  if (element instanceof HTMLButtonElement) tabRefs.set(id, element)
}

function selectTab(id: string, focus = false): void {
  emit('update:modelValue', id)
  if (focus) void nextTick(() => tabRefs.get(id)?.focus())
}

function handleKeydown(event: KeyboardEvent): void {
  const currentIndex = props.tabs.findIndex((tab) => tab.id === props.modelValue)
  if (currentIndex < 0) return

  let nextIndex = currentIndex
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
    nextIndex = (currentIndex + 1) % props.tabs.length
  } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
    nextIndex = (currentIndex - 1 + props.tabs.length) % props.tabs.length
  } else if (event.key === 'Home') {
    nextIndex = 0
  } else if (event.key === 'End') {
    nextIndex = props.tabs.length - 1
  } else {
    return
  }

  event.preventDefault()
  const tab = props.tabs[nextIndex]
  if (tab) selectTab(tab.id, true)
}
</script>

<template>
  <nav
    class="flex shrink-0 gap-1 overflow-x-auto bg-c-surface/65 px-3 py-2 sm:px-4"
    :aria-label="label"
    role="tablist"
    @keydown="handleKeydown"
  >
    <button
      v-for="tab in tabs"
      :key="tab.id"
      :ref="(element) => setTabRef(tab.id, element)"
      type="button"
      class="cursor-pointer rounded-xl px-3 py-2 text-left text-xs font-medium transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-c-accent"
      :class="
        modelValue === tab.id
          ? 'bg-c-accent-soft text-c-accent'
          : 'text-c-text-dim hover:bg-c-panel/70 hover:text-c-text'
      "
      role="tab"
      :id="`${label}-${tab.id}-tab`"
      :aria-controls="`${label}-${tab.id}-panel`"
      :aria-selected="modelValue === tab.id"
      :tabindex="modelValue === tab.id ? 0 : -1"
      :aria-label="tab.description ? `${tab.label}：${tab.description}` : tab.label"
      @click="selectTab(tab.id)"
    >
      {{ tab.label }}
    </button>
  </nav>
</template>
