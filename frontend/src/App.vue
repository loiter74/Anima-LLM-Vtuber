<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, computed } from 'vue'
import { ensureAuthenticatedSession, useSocket } from '@/composables/useSocket'

useSocket() // Initialize Socket.IO connection

const STORAGE_KEY = 'animetta_background'
const bgSrc = ref('')
const authRequired = ref(false)
const accessToken = ref('')
const authError = ref('')
const authBusy = ref(false)

const bgStyle = computed(() => {
  if (!bgSrc.value) return {}
  return {
    backgroundImage: 'url("' + bgSrc.value.replace(/"/g, '%22') + '")',
    backgroundSize: 'cover',
    backgroundPosition: 'center',
    backgroundRepeat: 'no-repeat',
  }
})

onMounted(() => {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) bgSrc.value = saved
  window.addEventListener('animetta:auth-required', showLogin)
  window.addEventListener('animetta:auth-ready', hideLogin)
})

onBeforeUnmount(() => {
  window.removeEventListener('animetta:auth-required', showLogin)
  window.removeEventListener('animetta:auth-ready', hideLogin)
})

function showLogin(): void {
  authRequired.value = true
}

function hideLogin(): void {
  authRequired.value = false
  authError.value = ''
}

async function login(): Promise<void> {
  authBusy.value = true
  authError.value = ''
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: accessToken.value }),
    })
    accessToken.value = ''
    if (!response.ok || !(await ensureAuthenticatedSession())) {
      authError.value = response.status === 429 ? '尝试过于频繁，请稍后再试。' : '访问令牌无效。'
    }
  } catch {
    authError.value = '无法连接到 Animetta 服务。'
  } finally {
    authBusy.value = false
  }
}

window.__setAppBg = (url: string) => {
  bgSrc.value = url
}
</script>

<template>
  <div class="flex flex-col h-screen w-screen overflow-hidden text-c-text relative">
    <!-- Background layer: lives at z-index 0 so the global preset image shows
         through the transparent .app-container / .stage. The root div carries
         no bg-c-bg itself — the body element keeps --c-bg as the ultimate
         fallback if the user clears the background. -->
    <div
      v-if="bgSrc"
      class="absolute inset-0"
      style="z-index: 0; pointer-events: none"
      :style="bgStyle"
    />
    <div class="relative flex flex-col h-full" style="z-index: 1">
      <router-view />
    </div>
    <div
      v-if="authRequired"
      class="absolute inset-0 z-50 grid place-items-center bg-c-bg/90 p-6 backdrop-blur-md"
      data-testid="auth-gate"
    >
      <form class="glass w-full max-w-md rounded-xl p-6" @submit.prevent="login">
        <p class="text-10px font-semibold tracking-[0.18em] text-c-accent">PRODUCTION ACCESS</p>
        <h1 class="mt-2 text-xl font-semibold">进入 Animetta 后台</h1>
        <p class="mt-2 text-sm text-c-text-muted">
          令牌仅用于换取 8 小时 HttpOnly 会话，不会保存在浏览器存储中。
        </p>
        <label class="mt-5 block text-xs text-c-text-dim" for="access-token">共享访问令牌</label>
        <input
          id="access-token"
          v-model="accessToken"
          class="input-field mt-2 w-full"
          type="password"
          autocomplete="current-password"
          required
        />
        <p v-if="authError" class="mt-3 text-xs text-c-error" role="alert">{{ authError }}</p>
        <button class="btn-accent mt-5 w-full" type="submit" :disabled="authBusy">
          {{ authBusy ? '验证中…' : '登录' }}
        </button>
      </form>
    </div>
  </div>
</template>
