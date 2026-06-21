<script setup lang="ts">
/**
 * MemoryGraphControls — toolbar at top of the knowledge graph.
 *
 * Left: zoom in/out/reset. Center: search input. Right: category filter.
 * Stacks vertically on mobile (sm breakpoint).
 */
defineProps<{
  searchQuery: string
  selectedCategory: string | null
  categories: string[]
}>()

const emit = defineEmits<{
  'update:searchQuery': [value: string]
  'update:selectedCategory': [value: string | null]
  zoomIn: []
  zoomOut: []
  zoomReset: []
}>()
</script>

<template>
  <div class="graph-controls">
    <!-- Left: zoom controls -->
    <div class="graph-controls-left flex items-center gap-1 shrink-0">
      <button
        class="w-7 h-7 flex items-center justify-center rounded-lg
               bg-c-bg/40 text-c-text-dim hover:text-c-text hover:bg-c-bg/60 transition-colors"
        title="Zoom in"
        @click="emit('zoomIn')"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8" />
          <path d="M21 21l-4.35-4.35" />
          <path d="M8 11h6M11 8v6" />
        </svg>
      </button>
      <button
        class="w-7 h-7 flex items-center justify-center rounded-lg
               bg-c-bg/40 text-c-text-dim hover:text-c-text hover:bg-c-bg/60 transition-colors"
        title="Zoom out"
        @click="emit('zoomOut')"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8" />
          <path d="M21 21l-4.35-4.35" />
          <path d="M8 11h6" />
        </svg>
      </button>
      <button
        class="w-7 h-7 flex items-center justify-center rounded-lg
               bg-c-bg/40 text-c-text-dim hover:text-c-text hover:bg-c-bg/60 transition-colors"
        title="Reset zoom"
        @click="emit('zoomReset')"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
          <path d="M3 3v5h5" />
        </svg>
      </button>
    </div>

    <!-- Center: search -->
    <div class="graph-controls-center flex-1 min-w-0 relative">
      <input
        :value="searchQuery"
        type="text"
        placeholder="Search nodes..."
        class="w-full pl-7 pr-2 py-1 rounded-lg bg-c-bg/60 border border-c-border/30 text-10px text-c-text
               placeholder:text-c-text-muted focus:outline-none focus:border-c-accent/50 transition-colors"
        @input="emit('update:searchQuery', ($event.target as HTMLInputElement).value)"
      />
      <svg
        class="absolute left-2 top-1/2 -translate-y-1/2 text-c-text-muted"
        width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
      >
        <circle cx="11" cy="11" r="8" />
        <path d="M21 21l-4.35-4.35" />
      </svg>
    </div>

    <!-- Right: category filter -->
    <div class="graph-controls-right shrink-0">
      <select
        :value="selectedCategory ?? ''"
        class="px-2 py-1 rounded-lg bg-c-bg/60 border border-c-border/30 text-10px text-c-text
               focus:outline-none focus:border-c-accent/50 transition-colors cursor-pointer"
        @change="emit('update:selectedCategory', ($event.target as HTMLSelectElement).value || null)"
      >
        <option value="">All categories</option>
        <option v-for="cat in categories" :key="cat" :value="cat">
          {{ cat }}
        </option>
      </select>
    </div>
  </div>
</template>
