import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ConnectionStatus } from '@/types/socket-events'
import type { AuthSessionSnapshot, AuthStatus, AuthUser } from '@/auth/session'

export const useConnectionStore = defineStore('connection', () => {
  const status = ref<ConnectionStatus>('disconnected')
  const authStatus = ref<AuthStatus>('checking')
  const currentUser = ref<AuthUser | null>(null)
  const passwordChangeRequired = ref(false)
  const errorMessage = ref<string>('')

  function setStatus(s: ConnectionStatus, msg?: string) {
    status.value = s
    errorMessage.value = msg ?? ''
  }

  function setAuthStatus(status: AuthStatus) {
    authStatus.value = status
    if (status !== 'authenticated') {
      currentUser.value = null
      passwordChangeRequired.value = false
    }
  }

  function applyAuthSession(session: AuthSessionSnapshot) {
    authStatus.value = session.status
    currentUser.value = session.user
    passwordChangeRequired.value = session.passwordChangeRequired
  }

  return {
    status,
    authStatus,
    currentUser,
    passwordChangeRequired,
    errorMessage,
    setStatus,
    setAuthStatus,
    applyAuthSession,
  }
})
