/**
 * Live2D 配置加载服务
 * 从 public/config/live2d.json 加载配置
 */

import type { Live2DConfig } from '../types'

let configCache: Live2DConfig | null = null

/**
 * 加载 Live2D 配置
 * @returns Promise<Live2DConfig>
 */
export async function loadLive2DConfig(): Promise<Live2DConfig> {
  if (configCache) {
    return configCache
  }

  try {
    const response = await fetch('/config/live2d.json')
    if (!response.ok) {
      throw new Error(`Failed to load Live2D config: ${response.statusText}`)
    }

    configCache = await response.json()
    return configCache
  } catch (error) {
    console.error('[ConfigLoader] Failed to load config:', error)
    // 返回默认配置
    return getDefaultConfig()
  }
}

/**
 * 获取默认配置（fallback）
 */
function getDefaultConfig(): Live2DConfig {
  return {
    enabled: true,
    model: {
      path: '/live2d/haru/haru_greeter_t03.model3.json',
      scale: 1.0,
      position: {
        x: 0,
        y: 0,
        yOffsetPercent: 0,
        xOffsetPercent: 0,
        scaleMultiplier: 1.0,
      },
    },
    expressions: {
      idle: 0,
      listening: 1,
      thinking: 2,
      speaking: 3,
      surprised: 4,
      sad: 5,
    },
    lipSync: {
      enabled: true,
      sensitivity: 2.0,
      smoothing: 0.2,
      minThreshold: 0.01,
      maxValue: 1.0,
      useMouthForm: false,
    },
  }
}

/**
 * 清除配置缓存（用于测试或重新加载）
 */
export function clearConfigCache(): void {
  configCache = null
}

/**
 * 同步获取配置（需要先调用 loadLive2DConfig）
 * @throws 如果配置未加载
 */
export function getConfigSync(): Live2DConfig {
  if (!configCache) {
    throw new Error('Config not loaded. Call loadLive2DConfig() first.')
  }
  return configCache
}
