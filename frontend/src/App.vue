<script setup lang="ts">
import { onMounted, ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ensureAuthenticatedSession, useSocket } from '@/composables/useSocket'
import { useConnectionStore } from '@/stores/connection'

useSocket() // Initialize Socket.IO connection
const connectionStore = useConnectionStore()
const route = useRoute()
const router = useRouter()

const STORAGE_KEY = 'animetta_background'
const bgSrc = ref('')
const authRequired = computed(
  () =>
    connectionStore.authStatus === 'unauthenticated' ||
    connectionStore.authStatus === 'unavailable',
)
const username = ref('admin')
const password = ref('')
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
})

watch(
  () => [connectionStore.authStatus, connectionStore.passwordChangeRequired, route.path] as const,
  ([status, passwordChangeRequired, path]) => {
    if (status === 'authenticated' && passwordChangeRequired && path !== '/account') {
      void router.replace('/account')
    }
  },
  { immediate: true },
)

async function login(): Promise<void> {
  authBusy.value = true
  authError.value = ''
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username.value, password: password.value }),
    })
    if (!response.ok) {
      connectionStore.setAuthStatus(response.status === 503 ? 'unavailable' : 'unauthenticated')
      authError.value =
        response.status === 429
          ? '尝试过于频繁，请稍后再试。'
          : response.status === 403
            ? '账号已被禁用。'
            : response.status === 503
              ? '登录服务不可用。'
              : '用户名或密码错误。'
      return
    }
    const status = await ensureAuthenticatedSession()
    if (status !== 'authenticated') {
      authError.value = status === 'unavailable' ? '登录服务不可用。' : '登录会话无效。'
    }
  } catch {
    connectionStore.setAuthStatus('unavailable')
    authError.value = '登录服务不可用。'
  } finally {
    password.value = ''
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
        <h1 class="mt-2 text-xl font-semibold">
          {{ connectionStore.authStatus === 'unavailable' ? '登录服务不可用' : '未登录' }}
        </h1>
        <p class="mt-2 text-sm text-c-text-muted">
          账号密码仅用于换取 8 小时 HttpOnly 会话，不会保存在浏览器存储中。
        </p>
        <label class="mt-5 block text-xs text-c-text-dim" for="auth-username">用户名</label>
        <input
          id="auth-username"
          v-model="username"
          class="input-field mt-2 w-full"
          type="text"
          name="username"
          autocomplete="username"
          required
        />
        <label class="mt-4 block text-xs text-c-text-dim" for="auth-password">密码</label>
        <input
          id="auth-password"
          v-model="password"
          class="input-field mt-2 w-full"
          type="password"
          name="password"
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
