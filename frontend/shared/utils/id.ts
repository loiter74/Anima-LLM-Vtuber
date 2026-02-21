/**
 * ID Generation Utilities
 * Provides unique ID generation for messages and other entities
 */

let counter = 0

export function generateId(prefix: string = 'id'): string {
  counter++
  return `${prefix}-${Date.now()}-${counter}`
}

export function resetIdCounter(): void {
  counter = 0
}
