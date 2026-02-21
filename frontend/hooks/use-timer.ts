/**
 * Timer Hook
 * Provides elapsed time tracking functionality
 */

import { useState, useEffect, useRef } from "react"

export interface UseTimerOptions {
  interval?: number // Update interval in milliseconds
  autoStart?: boolean
}

export interface UseTimerReturn {
  elapsedTime: number // Elapsed time in seconds
  isRunning: boolean
  start: () => void
  stop: () => void
  reset: () => void
}

/**
 * Hook for timer functionality
 */
export function useTimer(options: UseTimerOptions = {}): UseTimerReturn {
  const { interval = 1000, autoStart = false } = options

  const [elapsedTime, setElapsedTime] = useState(0)
  const [isRunning, setIsRunning] = useState(autoStart)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startTimeRef = useRef<number | null>(null)

  // Start timer
  const start = () => {
    if (!isRunning) {
      startTimeRef.current = Date.now() - elapsedTime * 1000
      setIsRunning(true)
    }
  }

  // Stop timer
  const stop = () => {
    if (isRunning) {
      setIsRunning(false)
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }

  // Reset timer
  const reset = () => {
    setElapsedTime(0)
    setIsRunning(false)
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    startTimeRef.current = null
  }

  // Update elapsed time
  useEffect(() => {
    if (isRunning) {
      intervalRef.current = setInterval(() => {
        if (startTimeRef.current !== null) {
          setElapsedTime(Math.floor((Date.now() - startTimeRef.current) / 1000))
        }
      }, interval)

      return () => {
        if (intervalRef.current) {
          clearInterval(intervalRef.current)
        }
      }
    }
  }, [isRunning, interval])

  return {
    elapsedTime,
    isRunning,
    start,
    stop,
    reset,
  }
}
