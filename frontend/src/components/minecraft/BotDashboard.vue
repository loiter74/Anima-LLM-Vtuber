<script setup lang="ts">
import { computed } from 'vue'
import { useMinecraftStore } from '@/stores/minecraft'

const mc = useMinecraftStore()
const bs = computed(() => mc.botState)

// Health bar color
const healthColor = computed(() => {
  if (bs.value.health >= 16) return 'bg-green-500'
  if (bs.value.health >= 10) return 'bg-yellow-500'
  return 'bg-red-500'
})

// Food bar color
const foodColor = computed(() => {
  if (bs.value.food >= 16) return 'bg-green-500'
  if (bs.value.food >= 8) return 'bg-yellow-500'
  return 'bg-red-500'
})

// Action icon
const actionIcon = computed(() => {
  const icons: Record<string, string> = {
    idle: '⏸',
    mine_block: '⛏',
    chop_tree: '🪓',
    craft_item: '🔨',
    smelt_item: '🔥',
    goto: '🚶',
    place_block: '🧱',
    attack: '⚔',
    eat: '🍖',
    pickup_item: '📥',
  }
  return icons[bs.value.action] || '🤖'
})

// Top 9 inventory items (hotbar-like)
const hotbarItems = computed(() => {
  const items = bs.value.inventory.slice(0, 9)
  while (items.length < 9) {
    items.push({ name: '', count: 0, slot: items.length })
  }
  return items
})
</script>

<template>
  <div class="bot-dashboard glass rounded-2xl p-4 space-y-4 text-sm">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <h3 class="text-c-text font-bold text-base flex items-center gap-2">
        <span class="text-lg">🎮</span> Bot HUD
      </h3>
      <span class="text-xs text-c-text-secondary"> {{ bs.dimension }} · {{ bs.biome }} </span>
    </div>

    <!-- Vital Bars -->
    <div class="grid grid-cols-2 gap-3">
      <!-- Health -->
      <div class="space-y-1">
        <div class="flex justify-between text-xs">
          <span>❤️ Health</span>
          <span class="text-c-text-secondary">{{ bs.health }}/20</span>
        </div>
        <div class="h-2 bg-c-bg-secondary rounded-full overflow-hidden">
          <div
            class="h-full rounded-full transition-all duration-300"
            :class="healthColor"
            :style="{ width: `${(bs.health / 20) * 100}%` }"
          />
        </div>
      </div>

      <!-- Food -->
      <div class="space-y-1">
        <div class="flex justify-between text-xs">
          <span>🍖 Food</span>
          <span class="text-c-text-secondary">{{ bs.food }}/20</span>
        </div>
        <div class="h-2 bg-c-bg-secondary rounded-full overflow-hidden">
          <div
            class="h-full rounded-full transition-all duration-300"
            :class="foodColor"
            :style="{ width: `${(bs.food / 20) * 100}%` }"
          />
        </div>
      </div>
    </div>

    <!-- Position + Time -->
    <div class="grid grid-cols-2 gap-2 text-xs">
      <div class="flex items-center gap-1.5">
        <span>📍</span>
        <span class="text-c-text-secondary">
          {{ Math.floor(bs.position.x) }}, {{ Math.floor(bs.position.y) }},
          {{ Math.floor(bs.position.z) }}
        </span>
      </div>
      <div class="flex items-center gap-1.5">
        <span>⏰</span>
        <span class="text-c-text-secondary">{{ bs.time }} · {{ bs.weather }}</span>
      </div>
    </div>

    <!-- Current Action -->
    <div
      class="flex items-center gap-2 px-3 py-2 rounded-lg"
      :class="
        bs.action === 'idle' ? 'bg-c-bg-secondary/50' : 'bg-c-accent/10 border border-c-accent/20'
      "
    >
      <span class="text-lg">{{ actionIcon }}</span>
      <div class="flex-1 min-w-0">
        <div class="text-xs text-c-text-secondary">Current Action</div>
        <div class="font-medium truncate">
          {{ bs.action
          }}<span v-if="bs.actionTarget" class="text-c-accent"> → {{ bs.actionTarget }}</span>
        </div>
      </div>
      <div class="text-xs text-c-text-secondary truncate max-w-24">🖐 {{ bs.heldItem }}</div>
    </div>

    <!-- Hotbar (inventory preview) -->
    <div class="space-y-1.5">
      <div class="text-xs text-c-text-secondary">🎒 Hotbar</div>
      <div class="grid grid-cols-9 gap-1">
        <div
          v-for="(item, i) in hotbarItems"
          :key="i"
          class="aspect-square rounded border flex flex-col items-center justify-center text-center p-0.5"
          :class="
            item.name
              ? 'border-c-border bg-c-bg-secondary/80'
              : 'border-c-border/30 bg-c-bg-secondary/30'
          "
        >
          <span v-if="item.name" class="text-[10px] leading-tight truncate w-full">
            {{ item.name.replace('minecraft:', '').replace('_', ' ') }}
          </span>
          <span v-if="item.count > 1" class="text-[9px] text-c-accent font-bold">
            {{ item.count }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bot-dashboard {
  min-width: 280px;
  max-width: 360px;
}
</style>
