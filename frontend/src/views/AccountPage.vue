<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import UserManagementPanel from '@/components/account/UserManagementPanel.vue'
import TitleBar from '@/components/layout/TitleBar.vue'
import { AuthApiError, changePassword, logout } from '@/auth/api'
import { ensureAuthenticatedSession } from '@/composables/useSocket'
import { useConnectionStore } from '@/stores/connection'

const store = useConnectionStore()
const router = useRouter()
const currentPassword = ref('')
const newPassword = ref('')
const confirmation = ref('')
const busy = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const currentUser = computed(() => store.currentUser)
const isAdmin = computed(() => currentUser.value?.role === 'admin' && !store.passwordChangeRequired)

function passwordBytes(value: string): number {
  return new TextEncoder().encode(value).length
}

function messageFor(error: unknown): string {
  if (!(error instanceof AuthApiError)) return '密码修改失败，请稍后再试。'
  if (error.code === 'CURRENT_PASSWORD_INVALID') return '当前密码不正确。'
  if (error.code === 'RATE_LIMITED') return '尝试过于频繁，请稍后再试。'
  if (error.code === 'AUTH_SESSION_STORE_UNAVAILABLE') return '登录服务不可用，请稍后重新登录。'
  if (error.code === 'AUTH_USER_STORE_UNAVAILABLE') return '用户服务不可用，请稍后再试。'
  return '新密码不符合要求，或与当前密码相同。'
}

async function submitPassword(): Promise<void> {
  errorMessage.value = ''
  successMessage.value = ''
  const byteLength = passwordBytes(newPassword.value)
  if (byteLength < 8 || byteLength > 1024) {
    errorMessage.value = '新密码需要包含 8–1024 个 UTF-8 字节。'
    return
  }
  if (newPassword.value !== confirmation.value) {
    errorMessage.value = '两次输入的新密码不一致。'
    return
  }
  busy.value = true
  try {
    await changePassword(currentPassword.value, newPassword.value)
    currentPassword.value = ''
    newPassword.value = ''
    confirmation.value = ''
    await ensureAuthenticatedSession()
    successMessage.value = '密码已更新，其他浏览器会话已撤销。'
  } catch (error) {
    errorMessage.value = messageFor(error)
  } finally {
    busy.value = false
  }
}

async function signOut(): Promise<void> {
  busy.value = true
  errorMessage.value = ''
  try {
    await logout()
  } catch {
    // A failed store lookup still clears the browser cookie server-side where possible.
  } finally {
    await ensureAuthenticatedSession()
    busy.value = false
    void router.replace('/dashboard')
  }
}
</script>

<template>
  <div class="ops-shell flex h-full min-h-0 flex-col text-c-text" data-testid="account-page">
    <TitleBar />
    <main class="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
      <div class="mx-auto flex w-full max-w-6xl flex-col gap-6">
        <header class="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p class="text-10px font-semibold tracking-[0.18em] text-c-accent">ACCOUNT</p>
            <h1 class="mt-2 text-2xl font-semibold">账号与安全</h1>
            <p class="mt-2 text-sm text-c-text-muted">管理当前账号、密码和浏览器会话。</p>
          </div>
          <button class="btn-ghost" type="button" :disabled="busy" @click="signOut">
            退出登录
          </button>
        </header>

        <section
          v-if="store.passwordChangeRequired"
          class="rounded-xl border border-c-warning/35 bg-c-warning/8 p-4"
          role="status"
          data-testid="password-required-notice"
        >
          <h2 class="text-sm font-semibold text-c-warning">首次登录需要修改密码</h2>
          <p class="mt-1 text-xs leading-relaxed text-c-text-dim">
            完成修改前不会连接 Dashboard 或直播 Socket，其他产品操作也会保持锁定。
          </p>
        </section>

        <div class="grid gap-6 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
          <section class="glass rounded-xl p-5">
            <div class="flex items-start justify-between gap-4">
              <div>
                <p class="text-xs text-c-text-muted">当前账号</p>
                <h2 class="mt-1 text-lg font-semibold">
                  {{ currentUser?.username ?? '正在读取…' }}
                </h2>
              </div>
              <span class="rounded-full border border-c-border px-3 py-1 text-10px text-c-text-dim">
                {{ currentUser?.role === 'admin' ? '管理员' : '普通用户' }}
              </span>
            </div>
            <dl class="mt-5 grid gap-3 text-xs">
              <div class="flex justify-between gap-4 border-t border-c-border pt-3">
                <dt class="text-c-text-muted">会话时长</dt>
                <dd class="text-c-text-dim">固定 8 小时</dd>
              </div>
              <div class="flex justify-between gap-4 border-t border-c-border pt-3">
                <dt class="text-c-text-muted">密码存储</dt>
                <dd class="text-c-text-dim">scrypt-v1 加盐哈希</dd>
              </div>
            </dl>
          </section>

          <section class="glass rounded-xl p-5">
            <h2 class="text-base font-semibold">修改密码</h2>
            <p class="mt-1 text-xs text-c-text-muted">至少 8 个 UTF-8 字节；成功后撤销其他会话。</p>
            <form class="mt-5 grid gap-4" @submit.prevent="submitPassword">
              <label class="grid gap-2 text-xs text-c-text-dim">
                当前密码
                <input
                  v-model="currentPassword"
                  class="input-field"
                  type="password"
                  autocomplete="current-password"
                  required
                />
              </label>
              <label class="grid gap-2 text-xs text-c-text-dim">
                新密码
                <input
                  v-model="newPassword"
                  class="input-field"
                  type="password"
                  autocomplete="new-password"
                  required
                />
              </label>
              <label class="grid gap-2 text-xs text-c-text-dim">
                再次输入新密码
                <input
                  v-model="confirmation"
                  class="input-field"
                  type="password"
                  autocomplete="new-password"
                  required
                />
              </label>
              <p v-if="errorMessage" class="text-xs text-c-error" role="alert">
                {{ errorMessage }}
              </p>
              <p v-if="successMessage" class="text-xs text-c-success" role="status">
                {{ successMessage }}
              </p>
              <button class="btn-accent justify-self-start" type="submit" :disabled="busy">
                {{ busy ? '正在更新…' : '更新密码' }}
              </button>
            </form>
          </section>
        </div>

        <UserManagementPanel v-if="isAdmin && currentUser" :current-user-id="currentUser.id" />
      </div>
    </main>
  </div>
</template>
