/**
 * Logger Utilities
 * Provides structured logging capabilities
 */

type LogLevel = 'debug' | 'info' | 'warn' | 'error'

interface Logger {
  debug: (...args: unknown[]) => void
  info: (...args: unknown[]) => void
  warn: (...args: unknown[]) => void
  error: (...args: unknown[]) => void
}

class ConsoleLogger implements Logger {
  private prefix: string

  constructor(prefix: string = '[App]') {
    this.prefix = prefix
  }

  private log(level: LogLevel, ...args: unknown[]): void {
    const timestamp = new Date().toISOString()
    const prefix = `${timestamp} ${this.prefix}`

    switch (level) {
      case 'debug':
        console.debug(prefix, ...args)
        break
      case 'info':
        console.info(prefix, ...args)
        break
      case 'warn':
        console.warn(prefix, ...args)
        break
      case 'error':
        console.error(prefix, ...args)
        break
    }
  }

  debug(...args: unknown[]): void {
    this.log('debug', ...args)
  }

  info(...args: unknown[]): void {
    this.log('info', ...args)
  }

  warn(...args: unknown[]): void {
    this.log('warn', ...args)
  }

  error(...args: unknown[]): void {
    this.log('error', ...args)
  }
}

export const logger = new ConsoleLogger()

export function createLogger(prefix: string): Logger {
  return new ConsoleLogger(prefix)
}
