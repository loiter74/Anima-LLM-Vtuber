export interface LiveSocket {
  on(event: string, handler: (...args: unknown[]) => void): LiveSocket
  off(event: string, handler: (...args: unknown[]) => void): LiveSocket
}
