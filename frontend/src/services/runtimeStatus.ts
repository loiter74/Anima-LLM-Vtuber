import type { RuntimeReadiness } from '@/types/runtime-status'

export async function fetchRuntimeStatus(
  fetcher: typeof fetch = window.fetch.bind(window),
): Promise<RuntimeReadiness> {
  const response = await fetcher('/ready', {
    headers: { accept: 'application/json' },
  })
  const payload = await response.json()
  if (!payload || typeof payload !== 'object' || !('components' in payload)) {
    throw new Error('Runtime readiness payload is invalid')
  }
  return payload as RuntimeReadiness
}
