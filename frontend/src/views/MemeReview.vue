<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useMemeReviewStore } from '@/stores/memeReview'
import MemeCard from '@/components/meme/MemeCard.vue'
import { Events } from '@/constants/socket-events'

const store = useMemeReviewStore()
const router = useRouter()
const route = useRoute()
const visible = ref(false)
const collecting = ref(false)
const collectResult = ref('')

onMounted(() => {
  visible.value = true
  store.fetchMemes()
})
// Close overlay when navigating away (e.g., via TitleBar buttons)
watch(
  () => route.name,
  (name) => {
    if (name !== 'meme-review') visible.value = false
  },
)
function close() {
  router.push('/')
}

function triggerCollect() {
  if (!store.socket) return
  collecting.value = true
  collectResult.value = ''
  store.socket.emit(Events.MEME.COLLECT, {})
  store.socket.once(
    Events.MEME.COLLECT,
    (data: { ok: boolean; count?: number; error?: string }) => {
      collecting.value = false
      if (data.ok) {
        collectResult.value = `采集完成，新增 ${data.count ?? 0} 个梗候选`
        setTimeout(() => {
          collectResult.value = ''
          store.fetchMemes()
        }, 2000)
      } else {
        collectResult.value = data.error || '采集失败'
      }
    },
  )
  setTimeout(() => {
    if (collecting.value) {
      collecting.value = false
      collectResult.value = '采集超时，请重试'
    }
  }, 120000)
}
</script>

<template>
  <Transition name="panel">
    <div v-if="visible" class="fixed inset-0 z-50 flex justify-end">
      <div class="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-in" @click="close" />
      <div class="relative w-full max-w-[440px] h-full glass-strong flex flex-col overflow-hidden">
        <!-- Header -->
        <div class="relative flex items-center justify-between px-5 py-4 shrink-0">
          <div
            class="absolute bottom-0 left-3 right-3 h-px bg-gradient-to-r from-transparent via-c-accent/20 to-transparent"
          />
          <div class="flex items-center gap-2">
            <span class="text-lg">🔍</span>
            <h1 class="text-base font-semibold text-c-text">梗筛选器</h1>
          </div>
          <div class="flex items-center gap-2">
            <button
              class="px-3 py-1.5 text-xs rounded-lg transition-all"
              :class="
                collecting
                  ? 'bg-c-accent/20 text-c-accent animate-pulse'
                  : collectResult
                    ? 'bg-c-success/15 text-c-success'
                    : 'bg-gradient-to-r from-c-accent to-c-accent-hover text-white hover:shadow-[0_0_12px_rgba(232,121,168,0.4)]'
              "
              :disabled="collecting"
              @click="triggerCollect"
            >
              {{
                collecting
                  ? '⏳ 采集中…'
                  : collectResult
                    ? '✓ ' + collectResult.split('，')[0]
                    : '🔥 采集热梗'
              }}
            </button>
            <button
              class="w-8 h-8 flex items-center justify-center rounded-lg text-c-text-secondary hover:text-c-text hover:bg-c-surface transition-colors text-lg"
              @click="close"
            >
              ✕
            </button>
          </div>
        </div>

        <!-- Stats bar -->
        <div
          v-if="store.total > 0 && !store.isDone"
          class="px-5 py-2 border-b border-c-border/50 shrink-0"
        >
          <div class="flex justify-between text-xs text-c-text-secondary mb-1">
            <span>{{ store.progress }}</span>
            <span>
              <Transition name="pop" mode="out-in">
                <span :key="'g' + store.goodCount">👍 {{ store.goodCount }}</span>
              </Transition>
              <span class="mx-1">|</span>
              <Transition name="pop" mode="out-in">
                <span :key="'b' + store.badCount">👎 {{ store.badCount }}</span>
              </Transition>
            </span>
          </div>
          <div class="h-1 rounded-full bg-c-border overflow-hidden">
            <div
              class="h-full rounded-full bg-gradient-to-r from-c-accent to-c-accent-hover transition-all duration-300"
              :style="{ width: `${((store.currentIndex + 1) / store.total) * 100}%` }"
            />
          </div>
        </div>

        <!-- Content -->
        <div class="flex-1 overflow-y-auto px-5 py-4">
          <!-- Loading -->
          <div
            v-if="store.loading"
            class="flex flex-col items-center justify-center h-full text-c-text-secondary gap-2"
          >
            <span class="text-3xl animate-bounce">🔍</span>
            <p class="text-sm">正在加载梗列表…</p>
          </div>
          <!-- Empty -->
          <div
            v-else-if="store.total === 0"
            class="flex flex-col items-center justify-center h-full text-c-text-secondary gap-2"
          >
            <span class="text-4xl">📭</span>
            <p class="text-sm">暂无待筛选梗</p>
            <p class="text-xs opacity-50">点击「🔥 采集热梗」或等待自动采集</p>
            <button
              class="mt-3 px-4 py-1.5 text-xs rounded-lg bg-c-primary/10 text-c-primary hover:bg-c-primary/20 transition-colors"
              @click="store.fetchMemes()"
            >
              刷新列表
            </button>
          </div>
          <!-- Done -->
          <div
            v-else-if="store.isDone"
            class="flex flex-col items-center justify-center h-full text-c-text-secondary gap-2"
          >
            <span class="text-4xl">🎉</span>
            <p class="text-sm">全部筛选完成！</p>
            <p class="text-xs opacity-50">
              👍 {{ store.goodCount }} 个好梗 | 👎 {{ store.badCount }} 个烂梗
            </p>
            <div class="flex gap-2 mt-3">
              <button
                class="px-3 py-1.5 text-xs rounded-lg bg-c-primary/10 text-c-primary hover:bg-c-primary/20 transition-colors"
                @click="store.exportDataset()"
              >
                📦 导出数据集
              </button>
              <button
                class="px-3 py-1.5 text-xs rounded-lg border border-c-border text-c-text-secondary hover:text-c-text transition-colors"
                @click="store.fetchMemes()"
              >
                重新加载
              </button>
            </div>
          </div>
          <!-- Cards -->
          <template v-else>
            <Transition name="card" mode="out-in">
              <MemeCard
                :key="store.currentIndex"
                :meme="store.currentMeme!"
                :feedback="store.feedback"
                :feedback-visible="store.feedbackVisible"
              />
            </Transition>
            <div class="flex gap-3 mt-4">
              <button
                class="flex-1 py-3 rounded-xl text-sm font-medium transition-all duration-200 bg-c-success/15 text-c-success border border-c-success/20 hover:bg-c-success/25 hover:shadow-[0_0_8px_rgba(74,222,128,0.3)] active:scale-95"
                @click="store.voteGood()"
              >
                👍 好梗
              </button>
              <button
                class="flex-1 py-3 rounded-xl text-sm font-medium transition-all duration-200 bg-c-error/15 text-c-error border border-c-error/20 hover:bg-c-error/25 hover:shadow-[0_0_8px_rgba(248,113,113,0.3)] active:scale-95"
                @click="store.voteBad()"
              >
                👎 烂梗
              </button>
            </div>
            <div class="flex gap-2 mt-2 justify-center">
              <button
                class="px-2 py-1 text-xs rounded-lg bg-c-card/50 text-c-text-dim hover:bg-c-card border border-transparent disabled:opacity-30 transition-all"
                :disabled="store.currentIndex === 0"
                @click="store.prevMeme()"
              >
                ← 上一条
              </button>
              <button
                class="px-2 py-1 text-xs rounded-lg bg-c-card/50 text-c-text-dim hover:bg-c-card border border-transparent disabled:opacity-30 transition-all"
                :disabled="store.currentIndex >= store.total - 1"
                @click="store.nextMeme()"
              >
                跳过 →
              </button>
            </div>
          </template>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.panel-enter-active {
  animation: slideInRight 0.3s var(--ease-out-expo);
}
.panel-leave-active {
  animation: slideOutRight 0.25s var(--ease-out-expo);
}

.card-enter-active {
  animation: cardIn 0.3s var(--ease-out-expo);
}
.card-leave-active {
  animation: cardOut 0.2s var(--ease-out-expo);
}
.pop-enter-active {
  animation: popIn 0.25s var(--ease-back-soft);
}
.pop-leave-active {
  animation: popOut 0.15s var(--ease-out-expo);
}

@keyframes cardIn {
  from {
    opacity: 0;
    transform: translateX(30px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}
@keyframes cardOut {
  from {
    opacity: 1;
    transform: translateX(0);
  }
  to {
    opacity: 0;
    transform: translateX(-30px);
  }
}
@keyframes popIn {
  from {
    opacity: 0;
    transform: scale(0.5);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}
@keyframes popOut {
  from {
    opacity: 1;
    transform: scale(1);
  }
  to {
    opacity: 0;
    transform: scale(0.5);
  }
}
</style>
