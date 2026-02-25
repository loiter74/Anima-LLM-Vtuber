/**
 * ID Generation Utilities
 * Provides unique ID generation for messages and other entities
 */

let counter = 0

/**
 * Generate a unique ID with counter-based approach
 * @param prefix - Prefix for the ID (default: 'id')
 * @returns Unique ID string with format: {prefix}-{timestamp}-{counter}
 */
export function generateId(prefix: string = 'id'): string {
  counter++
  return `${prefix}-${Date.now()}-${counter}`
}

/**
 * Reset the ID counter (useful for testing)
 */
export function resetIdCounter(): void {
  counter = 0
}

/**
 * Generate a unique ID with random approach
 * @param prefix - Optional prefix for the ID
 * @returns Unique ID string with format: {prefix-}{timestamp}-{random}
 */
export function generateRandomId(prefix?: string): string {
  const id = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
  return prefix ? `${prefix}-${id}` : id
}

/**
 * Generate a UUID v4
 * @returns UUID string in standard format
 */
export function generateUUID(): string {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === "x" ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}
