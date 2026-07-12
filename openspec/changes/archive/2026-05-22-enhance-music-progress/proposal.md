# Enhance Music Production Progress Bar — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enhance the music production pipeline's `ProcessTimeline.vue` with a visual horizontal progress bar, per-step mini progress bars, and a compact mode for the sidebar MusicCard.

**Architecture:** Single-component enhancement — add `overallPct` computed property, horizontal progress `<div>`, per-step mini bar in active row, and `compact` prop for condensed layout. Zero backend changes. Zero new dependencies. Pure Vue 3 + TypeScript + UnoCSS.

**Tech Stack:** Vue 3.5, TypeScript 5.7, UnoCSS 0.64, Pinia (unchanged)

**OpenSpec Change:** `openspec/changes/enhance-music-progress/`

---

### Task 1: Add Overall Progress Bar to ProcessTimeline

**Files:**
- Modify: `frontend/src/components/singing/ProcessTimeline.vue`

**Step 1: Add `overallPct` computed property**

```typescript
const stageOrder: PipelineStage[] = [
  'downloading', 'separating', 'transcribing',
  'waiting_lyrics', 'converting', 'mixing',
]

const overallPct = computed(() => {
  const currentIdx = stageOrder.indexOf(props.currentStage)
  if (currentIdx === -1) return 0
  const completedStages = currentIdx
  return Math.min(100, Math.round((completedStages * 100 + props.progress) / stageOrder.length))
})
```

**Step 2: Add horizontal progress bar in template**

Add BEFORE the existing step list `<div class="flex flex-col gap-2 py-2">`:

```html
<!-- Overall progress bar -->
<div class="w-full h-2 bg-c-accent/10 rounded-full overflow-hidden mb-3">
  <div
    class="h-full bg-c-accent rounded-full transition-all duration-500 ease-out"
    :style="{ width: overallPct + '%' }"
  />
</div>
```

**Step 3: Add percentage label next to bar**

Wrap the bar in a container with a percentage label:

```html
<div class="flex items-center gap-3 mb-2">
  <div class="flex-1 h-2 bg-c-accent/10 rounded-full overflow-hidden">
    <div
      class="h-full bg-c-accent rounded-full transition-all duration-500 ease-out"
      :style="{ width: overallPct + '%' }"
    />
  </div>
  <span class="text-xs text-c-text-dim font-mono w-10 text-right">{{ overallPct }}%</span>
</div>
```

---

### Task 2: Add Per-Step Mini Progress Bar

**Files:**
- Modify: `frontend/src/components/singing/ProcessTimeline.vue`

**Step 1: Add mini bar inside the active step's row**

Inside the `v-for` loop, after the step label and percentage, add a mini bar for the active step:

```html
<div
  v-if="stepStatus(step) === 'active' && progress > 0 && step.stage !== 'waiting_lyrics'"
  class="w-full h-1.5 bg-c-accent/10 rounded-full overflow-hidden mt-1"
>
  <div
    class="h-full bg-c-accent rounded-full transition-all duration-300 ease-out"
    :style="{ width: Math.round(progress) + '%' }"
  />
</div>
```

**Step 2: Handle `waiting_lyrics` special case**

For the `waiting_lyrics` step, show a waiting indicator instead:

```html
<div
  v-if="stepStatus(step) === 'active' && step.stage === 'waiting_lyrics'"
  class="mt-1 px-2 py-0.5 rounded text-xs"
  style="background: rgba(245, 200, 114, 0.1); color: #f0c060;"
>
  等待确认...
</div>
```

**Step 3: Adjust step row layout for mini bar**

The active step row needs `flex-col` layout when showing a mini bar. Update the row div:

```html
<div
  v-for="step in steps"
  :key="step.stage"
  class="px-2 py-1.5 rounded-lg text-xs transition-all"
  :class="{
    'flex flex-col gap-1': stepStatus(step) === 'active' && progress > 0,
    'flex items-center gap-3': !(stepStatus(step) === 'active' && progress > 0),
    ...
  }"
>
```

---

### Task 3: Add Compact Mode

**Files:**
- Modify: `frontend/src/components/singing/ProcessTimeline.vue`

**Step 1: Add `compact` prop**

```typescript
const props = defineProps<{
  currentStage: PipelineStage
  progress: number
  compact?: boolean  // NEW
}>()
```

**Step 2: Add compact template block**

Use `v-if="compact"` for the compact layout, keep existing for `v-else`:

```html
<template>
  <!-- Compact mode: single-row layout -->
  <div v-if="compact" class="flex flex-col gap-2 py-1">
    <!-- Overall progress bar (reuse computed) -->
    <div class="flex items-center gap-2">
      <div class="flex-1 h-1.5 bg-c-accent/10 rounded-full overflow-hidden">
        <div
          class="h-full bg-c-accent rounded-full transition-all duration-500 ease-out"
          :style="{ width: overallPct + '%' }"
        />
      </div>
      <span class="text-[10px] text-c-text-dim font-mono w-8 text-right">{{ overallPct }}%</span>
    </div>
    
    <!-- Icon step chain -->
    <div v-if="currentStage !== 'idle'" class="flex items-center gap-1 text-xs">
      <template v-for="(step, i) in steps" :key="step.stage">
        <span v-if="i > 0" class="text-c-text-dim/30">→</span>
        <span
          :class="{
            'text-c-text-dim/40': stepStatus(step) === 'pending',
            'text-c-accent': stepStatus(step) === 'active',
          }"
        >
          <span v-if="stepStatus(step) === 'done'">✅</span>
          <span v-else>{{ step.icon }}</span>
        </span>
      </template>
    </div>
  </div>

  <!-- Full mode: existing layout + enhancements -->
  <div v-else>
    <!-- ... existing template with overall bar + mini bars added above ... -->
  </div>
</template>
```

---

### Task 4: Update MusicCard to Use Compact Mode

**Files:**
- Modify: `frontend/src/components/singing/MusicCard.vue`

**Step 1: Read existing MusicCard.vue**

Read the file to locate `<ProcessTimeline>` usage.

**Step 2: Pass compact prop**

Change:
```html
<ProcessTimeline
  :current-stage="store.status"
  :progress="store.progress"
/>
```

To:
```html
<ProcessTimeline
  :current-stage="store.status"
  :progress="store.progress"
  :compact="true"
/>
```

---

### Task 5: Verification

**Step 1: TypeScript check**

```bash
cd frontend && pnpm vue-tsc --noEmit
```
Expected: No errors.

**Step 2: Manual visual verification**

1. Navigate to `/music`
2. Enter a B站 video URL, click "开始制作"
3. Observe the progress bar fills as stages progress
4. Verify `waiting_lyrics` shows the yellow waiting indicator
5. After completion, verify overall bar reaches 100%
6. Switch to sidebar, verify compact mode renders correctly

---

### Files Changed Summary

| File | Nature | Lines |
|------|--------|-------|
| `frontend/src/components/singing/ProcessTimeline.vue` | Add overall bar + mini bars + compact mode | +60 |
| `frontend/src/components/singing/MusicCard.vue` | Pass `:compact="true"` | +1 |

**Total: ~61 lines, 2 files, 0 backend changes.**
