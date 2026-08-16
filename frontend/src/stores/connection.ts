import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ConnectionStatus } from '@/types/socket-events'
import type { AuthStatus } from '@/auth/session'

export const useConnectionStore = defineStore('connection', () => {
  const status = ref<ConnectionStatus>('disconnected')
  const authStatus = ref<AuthStatus>('checking')
  const errorMessage = ref<string>('')

  function setStatus(s: ConnectionStatus, msg?: string) {
    status.value = s
    errorMessage.value = msg ?? ''
  }

  function setAuthStatus(status: AuthStatus) {
    authStatus.value = status
  }

  return { status, authStatus, errorMessage, setStatus, setAuthStatus }
})
