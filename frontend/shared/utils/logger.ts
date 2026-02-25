/**
 * Frontend Logger Utility
 * Provides dynamic log level control with localStorage persistence
 */

export enum LogLevel {
  DEBUG = 0,
  INFO = 1,
  WARN = 2,
  ERROR = 3,
  SILENT = 4
}

export class Logger {
  private static instance: Logger
  private config: {
    level: LogLevel
    enableTimestamp: boolean
  }

  static getInstance(): Logger {
    if (!Logger.instance) {
      Logger.instance = new Logger()
    }
    return Logger.instance
  }

  // 从 localStorage 读取初始级别
  constructor() {
    // 检查是否在浏览器环境（避免 SSR 错误）
    const isBrowser = typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
    const saved = isBrowser ? localStorage.getItem('anima_log_level') : null
    this.config = {
      level: saved !== null ? parseInt(saved, 10) : LogLevel.INFO,
      enableTimestamp: true
    }
  }

  // 设置日志级别并持久化
  setLevel(level: LogLevel): void {
    this.config.level = level
    // 检查是否在浏览器环境
    if (typeof window !== 'undefined' && typeof window.localStorage !== 'undefined') {
      localStorage.setItem('anima_log_level', level.toString())
    }
  }

  // 获取当前日志级别
  getLevel(): LogLevel {
    return this.config.level
  }

  // 日志方法（根据级别过滤）
  debug(message: string, ...args: any[]): void {
    this.log(LogLevel.DEBUG, message, args)
  }

  info(message: string, ...args: any[]): void {
    this.log(LogLevel.INFO, message, args)
  }

  warn(message: string, ...args: any[]): void {
    this.log(LogLevel.WARN, message, args)
  }

  error(message: string, ...args: any[]): void {
    this.log(LogLevel.ERROR, message, args)
  }

  private log(level: LogLevel, message: string, args: any[]): void {
    if (level < this.config.level) return

    const timestamp = this.config.enableTimestamp
      ? `[${new Date().toISOString().split('T')[1].split('.')[0]}] `
      : ''

    const prefix = `[${this.getLevelName(level)}] `

    switch (level) {
      case LogLevel.DEBUG:
        console.log(timestamp + prefix + message, ...args)
        break
      case LogLevel.INFO:
        console.log(timestamp + prefix + message, ...args)
        break
      case LogLevel.WARN:
        console.warn(timestamp + prefix + message, ...args)
        break
      case LogLevel.ERROR:
        console.error(timestamp + prefix + message, ...args)
        break
    }
  }

  private getLevelName(level: LogLevel): string {
    return ['DEBUG', 'INFO', 'WARN', 'ERROR', 'SILENT'][level]
  }
}

// 导出单例
export const logger = Logger.getInstance()
