<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  AuthApiError,
  createUser,
  listUsers,
  resetUserPassword,
  revokeUserSessions,
  updateUser,
  type ManagedUser,
} from '@/auth/api'
import type { AccountRole } from '@/auth/session'

defineProps<{ currentUserId: string }>()
const users = ref<ManagedUser[]>([])
const loading = ref(true)
const actionUserId = ref('')
const errorMessage = ref('')
const notice = ref('')
const createBusy = ref(false)
const newUsername = ref('')
const newRole = ref<AccountRole>('user')
const newTemporaryPassword = ref('')
const resetTarget = ref<ManagedUser | null>(null)
const resetPassword = ref('')

function bytes(value: string): number {
  return new TextEncoder().encode(value).length
}

function formatTime(value: number | null): string {
  if (value === null) return '尚未登录'
  return new Date(value * 1000).toLocaleString('zh-CN')
}

function errorText(error: unknown): string {
  if (!(error instanceof AuthApiError)) return '操作失败，请稍后再试。'
  const messages: Record<string, string> = {
    USERNAME_CONFLICT: '该用户名已经存在。',
    LAST_ACTIVE_ADMIN: '必须保留至少一个启用的管理员。',
    SELF_ADMIN_MUTATION_FORBIDDEN: '不能修改自己的角色、状态或临时密码。',
    PASSWORD_POLICY_VIOLATION: '用户名或密码不符合要求。',
    AUTH_SESSION_STORE_UNAVAILABLE: '登录服务不可用。',
    AUTH_USER_STORE_UNAVAILABLE: '用户服务不可用。',
    ACCOUNT_ADMIN_REQUIRED: '当前账号没有用户管理权限。',
  }
  return messages[error.code] ?? '操作失败，请刷新后重试。'
}

async function refresh(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    users.value = await listUsers()
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    loading.value = false
  }
}

async function submitCreate(): Promise<void> {
  errorMessage.value = ''
  notice.value = ''
  const passwordBytes = bytes(newTemporaryPassword.value)
  if (passwordBytes < 8 || passwordBytes > 1024) {
    errorMessage.value = '临时密码需要包含 8–1024 个 UTF-8 字节。'
    return
  }
  createBusy.value = true
  try {
    await createUser({
      username: newUsername.value,
      role: newRole.value,
      temporaryPassword: newTemporaryPassword.value,
    })
    newUsername.value = ''
    newTemporaryPassword.value = ''
    newRole.value = 'user'
    notice.value = '用户已创建，首次登录时需要修改临时密码。'
    await refresh()
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    createBusy.value = false
  }
}

async function changeRole(user: ManagedUser, event: Event): Promise<void> {
  const role = (event.target as HTMLSelectElement).value as AccountRole
  if (role === user.role) return
  if (
    !window.confirm(
      `确认将 ${user.username} 的角色改为${role === 'admin' ? '管理员' : '普通用户'}？`,
    )
  ) {
    ;(event.target as HTMLSelectElement).value = user.role
    return
  }
  await perform(user, () => updateUser(user.id, { role }), '用户角色已更新。')
}

async function toggleEnabled(user: ManagedUser): Promise<void> {
  const action = user.enabled ? '禁用' : '恢复'
  if (!window.confirm(`确认${action}账号 ${user.username}？`)) return
  await perform(user, () => updateUser(user.id, { enabled: !user.enabled }), `账号已${action}。`)
}

async function revokeSessions(user: ManagedUser): Promise<void> {
  if (!window.confirm(`确认撤销 ${user.username} 的全部浏览器会话？`)) return
  await perform(user, () => revokeUserSessions(user.id), '浏览器会话已撤销。')
}

function openReset(user: ManagedUser): void {
  resetTarget.value = user
  resetPassword.value = ''
  errorMessage.value = ''
}

function closeReset(): void {
  resetTarget.value = null
  resetPassword.value = ''
}

async function submitReset(): Promise<void> {
  const target = resetTarget.value
  if (!target) return
  if (bytes(resetPassword.value) < 8 || bytes(resetPassword.value) > 1024) {
    errorMessage.value = '临时密码需要包含 8–1024 个 UTF-8 字节。'
    return
  }
  await perform(
    target,
    () => resetUserPassword(target.id, resetPassword.value),
    '临时密码已重置，全部旧会话已撤销。',
  )
  if (!errorMessage.value) closeReset()
}

async function perform(
  user: ManagedUser,
  action: () => Promise<void>,
  success: string,
): Promise<void> {
  actionUserId.value = user.id
  errorMessage.value = ''
  notice.value = ''
  try {
    await action()
    notice.value = success
    await refresh()
  } catch (error) {
    await refresh()
    errorMessage.value = errorText(error)
  } finally {
    actionUserId.value = ''
  }
}

onMounted(refresh)
</script>

<template>
  <section class="glass rounded-xl p-5" aria-labelledby="user-management-title">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h2 id="user-management-title" class="text-base font-semibold">用户管理</h2>
        <p class="mt-1 text-xs text-c-text-muted">创建独立账号，控制角色、状态和浏览器会话。</p>
      </div>
      <button class="btn-ghost" type="button" :disabled="loading" @click="refresh">刷新</button>
    </div>

    <form
      class="mt-5 grid gap-3 rounded-xl border border-c-border bg-c-panel/45 p-4 md:grid-cols-[1fr_140px_1fr_auto]"
      @submit.prevent="submitCreate"
    >
      <label class="grid gap-2 text-xs text-c-text-dim">
        用户名
        <input v-model="newUsername" class="input-field" autocomplete="off" required />
      </label>
      <label class="grid gap-2 text-xs text-c-text-dim">
        角色
        <select v-model="newRole" class="input-field">
          <option value="user">普通用户</option>
          <option value="admin">管理员</option>
        </select>
      </label>
      <label class="grid gap-2 text-xs text-c-text-dim">
        临时密码
        <input
          v-model="newTemporaryPassword"
          class="input-field"
          type="password"
          autocomplete="new-password"
          required
        />
      </label>
      <button class="btn-accent self-end" type="submit" :disabled="createBusy">
        {{ createBusy ? '创建中…' : '创建用户' }}
      </button>
    </form>

    <p v-if="errorMessage" class="mt-4 text-xs text-c-error" role="alert">{{ errorMessage }}</p>
    <p v-if="notice" class="mt-4 text-xs text-c-success" role="status">{{ notice }}</p>

    <div
      v-if="loading"
      class="mt-5 rounded-xl border border-c-border p-5 text-sm text-c-text-muted"
    >
      正在读取用户…
    </div>
    <div
      v-else-if="users.length === 0"
      class="mt-5 rounded-xl border border-c-border p-5 text-sm text-c-text-muted"
    >
      暂无用户。
    </div>
    <div v-else class="mt-5 grid gap-3">
      <article
        v-for="user in users"
        :key="user.id"
        class="grid gap-4 rounded-xl border border-c-border bg-c-card/55 p-4 lg:grid-cols-[minmax(0,1fr)_180px_auto] lg:items-center"
      >
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-2">
            <h3 class="truncate text-sm font-semibold">{{ user.username }}</h3>
            <span
              v-if="user.id === currentUserId"
              class="rounded-full bg-c-accent-soft px-2 py-1 text-10px text-c-accent"
              >当前账号</span
            >
            <span
              class="rounded-full border px-2 py-1 text-10px"
              :class="
                user.enabled
                  ? 'border-c-success/35 text-c-success'
                  : 'border-c-error/35 text-c-error'
              "
            >
              {{ user.enabled ? '已启用' : '已禁用' }}
            </span>
            <span
              v-if="user.must_change_password"
              class="rounded-full border border-c-warning/35 px-2 py-1 text-10px text-c-warning"
            >
              待改密
            </span>
          </div>
          <p class="mt-2 text-10px text-c-text-muted">
            最近登录：{{ formatTime(user.last_login_at) }} · 有效会话 {{ user.active_sessions }}
          </p>
        </div>

        <label class="grid gap-2 text-10px text-c-text-muted">
          角色
          <select
            class="input-field"
            :value="user.role"
            :disabled="user.id === currentUserId || actionUserId === user.id"
            :aria-label="`${user.username} 的角色`"
            @change="changeRole(user, $event)"
          >
            <option value="user">普通用户</option>
            <option value="admin">管理员</option>
          </select>
        </label>

        <div class="flex flex-wrap gap-2 lg:justify-end">
          <button
            class="btn-ghost"
            type="button"
            :disabled="user.id === currentUserId || actionUserId === user.id"
            @click="toggleEnabled(user)"
          >
            {{ user.enabled ? '禁用' : '恢复' }}
          </button>
          <button
            class="btn-ghost"
            type="button"
            :disabled="user.id === currentUserId || actionUserId === user.id"
            @click="openReset(user)"
          >
            重置密码
          </button>
          <button
            class="btn-ghost"
            type="button"
            :disabled="actionUserId === user.id"
            @click="revokeSessions(user)"
          >
            撤销会话
          </button>
        </div>
      </article>
    </div>
  </section>

  <div
    v-if="resetTarget"
    class="fixed inset-0 z-50 grid place-items-center bg-c-bg/85 p-5 backdrop-blur-md"
    role="dialog"
    aria-modal="true"
    aria-labelledby="reset-password-title"
  >
    <form class="glass-strong w-full max-w-md rounded-xl p-5" @submit.prevent="submitReset">
      <h2 id="reset-password-title" class="text-base font-semibold">
        重置 {{ resetTarget.username }} 的密码
      </h2>
      <p class="mt-2 text-xs leading-relaxed text-c-text-muted">
        该密码是一次性临时密码。保存后会撤销全部旧会话，并要求用户首次登录改密。
      </p>
      <label class="mt-5 grid gap-2 text-xs text-c-text-dim">
        新临时密码
        <input
          v-model="resetPassword"
          class="input-field"
          type="password"
          autocomplete="new-password"
          autofocus
          required
        />
      </label>
      <div class="mt-5 flex justify-end gap-2">
        <button class="btn-ghost" type="button" @click="closeReset">取消</button>
        <button class="btn-accent" type="submit" :disabled="actionUserId === resetTarget.id">
          {{ actionUserId === resetTarget.id ? '正在重置…' : '确认重置' }}
        </button>
      </div>
    </form>
  </div>
</template>
