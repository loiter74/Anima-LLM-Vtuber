import type { Socket } from 'socket.io-client'

let socket: Socket | null = null

export function getSocket(): Socket | null {
  return socket
}

export function setSocket(value: Socket | null): void {
  socket = value
}
