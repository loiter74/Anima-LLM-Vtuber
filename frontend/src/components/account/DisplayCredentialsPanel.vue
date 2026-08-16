<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  AuthApiError,
  approveDisplayPairing,
  listDisplayCredentials,
  revokeDisplayCredential,
  type DisplayCredential,
} from '@/auth/api'

const credentials = ref<DisplayCredential[]>([])
const code = ref('')
const name = ref('B站直播场景')
const loading = ref(false)
const approving = ref(false)
const revokingId = ref('')
const errorMessage = ref('')
const notice = ref('')

function formatTime(value: number | null): string {
  return value === null ? '尚未连接' : new Date(value * 1000).toLocaleString('zh-CN')
}

function errorText(error: unknown): string {
  if (!(error instanceof AuthApiError)) return '直播设备操作失败，请刷新后重试。'
  const messages: Record<string, string> = {
    DISPLAY_PAIRING_INVALID: '配对码无效，请核对后重试。',
    DISPLAY_PAIRING_EXPIRED: '配对码已过期，请让直播页面重新生成。',
    DISPLAY_CREDENTIAL_LIMIT: '已达到 5 个直播设备上限，请先撤销旧设备。',
    AUTH_DISPLAY_STORE_UNAVAILABLE: '直播配对服务不可用，请稍后重试。',
    PASSWORD_CHANGE_REQUIRED: '请先完成首次密码修改。',
    ACCOUNT_ADMIN_REQUIRED: '当前账号没有直播设备管理权限。',
    RATE_LIMITED: '尝试过于频繁，请稍后重试。',
  }
  return messages[error.code] ?? '直播设备操作失败，请刷新后重试。'
}

async function refresh(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    credentials.value = await listDisplayCredentials()
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    loading.value = false
  }
}

async function approve(): Promise<void> {
  approving.value = true
  errorMessage.value = ''
  notice.value = ''
  try {
    await approveDisplayPairing(code.value, name.value)
    code.value = ''
    notice.value = '配对已批准，直播场景将在下一次轮询后自动连接。'
    await refresh()
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    approving.value = false
  }
}

async function revoke(credential: DisplayCredential): Promise<void> {
  if (!window.confirm(`确认撤销直播设备“${credential.name}”？当前场景会立即断开。`)) return
  revokingId.value = credential.id
  errorMessage.value = ''
  notice.value = ''
  try {
    await revokeDisplayCredential(credential.id)
    notice.value = '直播设备已撤销。'
    await refresh()
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    revokingId.value = ''
  }
}

onMounted(refresh)
</script>

<template>
  <section class="glass rounded-xl p-5" aria-labelledby="display-credentials-title">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h2 id="display-credentials-title" class="text-base font-semibold">直播设备</h2>
        <p class="mt-1 text-xs text-c-text-muted">
          为本机 B站浏览器场景签发只读展示凭证，不共享你的登录 Cookie。
        </p>
      </div>
      <button class="btn-ghost" type="button" :disabled="loading" @click="refresh">刷新</button>
    </div>

    <form
      class="mt-5 grid gap-3 rounded-xl border border-c-border bg-c-panel/45 p-4 md:grid-cols-[1fr_1.5fr_auto]"
      @submit.prevent="approve"
    >
      <label class="grid gap-2 text-xs text-c-text-dim">
        一次性配对码
        <input
          v-model="code"
          class="input-field font-mono uppercase tracking-widest"
          autocomplete="off"
          maxlength="9"
          placeholder="ABCD-EFGH"
          required
        />
      </label>
      <label class="grid gap-2 text-xs text-c-text-dim">
        设备名称
        <input v-model="name" class="input-field" autocomplete="off" maxlength="64" required />
      </label>
      <button class="btn-accent self-end" type="submit" :disabled="approving">
        {{ approving ? '批准中…' : '批准配对' }}
      </button>
    </form>

    <p v-if="errorMessage" class="mt-4 text-xs text-c-error" role="alert">{{ errorMessage }}</p>
    <p v-if="notice" class="mt-4 text-xs text-c-success" role="status">{{ notice }}</p>

    <div
      v-if="loading"
      class="mt-5 rounded-xl border border-c-border p-5 text-sm text-c-text-muted"
    >
      正在读取直播设备…
    </div>
    <div
      v-else-if="credentials.length === 0"
      class="mt-5 rounded-xl border border-c-border p-5 text-sm text-c-text-muted"
    >
      暂无已配对的直播设备。
    </div>
    <div v-else class="mt-5 grid gap-3">
      <article
        v-for="credential in credentials"
        :key="credential.id"
        class="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-c-border bg-c-card/55 p-4"
      >
        <div>
          <h3 class="text-sm font-semibold">{{ credential.name }}</h3>
          <p class="mt-2 text-10px text-c-text-muted">
            签发：{{ formatTime(credential.issued_at) }} · 到期：{{
              formatTime(credential.expires_at)
            }}
          </p>
          <p class="mt-1 text-10px text-c-text-muted">
            最近连接：{{ formatTime(credential.last_seen_at) }} · {{ credential.bound_origin }}
          </p>
        </div>
        <button
          class="btn-ghost"
          type="button"
          :disabled="revokingId === credential.id"
          @click="revoke(credential)"
        >
          {{ revokingId === credential.id ? '撤销中…' : '撤销' }}
        </button>
      </article>
    </div>
  </section>
</template>
