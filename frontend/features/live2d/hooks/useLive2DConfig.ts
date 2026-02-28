/**
 * Live2D 配置 Hook
 * 从配置文件加载 Live2D 配置
 */

import { useState, useEffect } from 'react'
import { loadLive2DConfig } from '../services/ConfigLoader'
import type { Live2DConfig } from '../types'

export function useLive2DConfig() {
  const [config, setConfig] = useState<Live2DConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    let cancelled = false

    const loadConfig = async () => {
      try {
        setLoading(true)
        const loadedConfig = await loadLive2DConfig()
        if (!cancelled) {
          setConfig(loadedConfig)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err as Error)
          console.error('[useLive2DConfig] Failed to load config:', err)
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadConfig()

    return () => {
      cancelled = true
    }
  }, [])

  return { config, loading, error }
}
