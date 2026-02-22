/**
 * Audio processing utilities
 */

/**
 * Convert Float32Array to Int16Array
 * @param data - Float32 audio data (-1.0 to 1.0)
 * @returns Int16 audio data (-32768 to 32767)
 */
export function float32ToInt16(data: Float32Array): Int16Array {
  const int16Data = new Int16Array(data.length)
  for (let i = 0; i < data.length; i++) {
    const s = Math.max(-1, Math.min(1, data[i]))
    int16Data[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  return int16Data
}

/**
 * Convert base64 string to Blob
 * @param base64 - Base64 encoded string (may include data URL prefix)
 * @param type - MIME type of the blob
 * @returns Blob object
 */
export function base64ToBlob(base64: string, type: string): Blob {
  // Remove data URL prefix if present (e.g., "data:audio/mp3;base64,")
  let cleanBase64 = base64
  if (base64.includes(',')) {
    cleanBase64 = base64.split(',')[1]
  }

  // Trim whitespace
  cleanBase64 = cleanBase64.trim()

  // Validate base64 string
  if (!cleanBase64 || cleanBase64.length === 0) {
    throw new Error('Invalid base64 data: empty string after cleaning')
  }

  // Check for valid base64 characters
  const base64Regex = /^[A-Za-z0-9+/]*={0,2}$/
  if (!base64Regex.test(cleanBase64)) {
    // Log problematic characters for debugging
    const invalidChars = cleanBase64.split('').filter(c => !base64Regex.test(c))
    throw new Error(`Invalid base64 data: contains invalid characters: ${invalidChars.slice(0, 10).join(', ')}`)
  }

  try {
    // Decode base64
    const binaryString = atob(cleanBase64)
    const byteLength = binaryString.length

    // Validate decoded size
    if (byteLength === 0) {
      throw new Error('Decoded data is empty')
    }

    // Convert to Uint8Array
    const bytes = new Uint8Array(byteLength)
    for (let i = 0; i < byteLength; i++) {
      bytes[i] = binaryString.charCodeAt(i)
    }

    // Create and return blob
    const blob = new Blob([bytes], { type })

    // Validate blob was created correctly
    if (blob.size !== byteLength) {
      console.warn(`[base64ToBlob] Blob size mismatch: expected ${byteLength}, got ${blob.size}`)
    }

    return blob
  } catch (e) {
    if (e instanceof Error) {
      throw new Error(`Failed to decode base64: ${e.message}`)
    }
    throw new Error(`Failed to decode base64: ${String(e)}`)
  }
}

/**
 * Create object URL from blob
 * @param blob - Blob object
 * @returns Object URL string
 */
export function blobToUrl(blob: Blob): string {
  const url = URL.createObjectURL(blob)
  // Log for debugging
  console.debug(`[blobToUrl] Created blob URL: ${url}, blob size: ${blob.size}, type: ${blob.type}`)
  return url
}

/**
 * Revoke object URL to free memory
 * @param url - Object URL to revoke
 */
export function revokeBlobUrl(url: string): void {
  if (url && url.startsWith('blob:')) {
    URL.revokeObjectURL(url)
    console.debug(`[revokeBlobUrl] Revoked blob URL: ${url}`)
  }
}

/**
 * Apply gain to audio data
 * @param data - Float32 audio data
 * @param gain - Gain multiplier (e.g., 2.0 for doubling amplitude)
 * @returns New Float32Array with gain applied
 */
export function applyGain(data: Float32Array, gain: number): Float32Array {
  const result = new Float32Array(data.length)
  for (let i = 0; i < data.length; i++) {
    let s = data[i] * gain
    result[i] = Math.max(-1, Math.min(1, s))
  }
  return result
}
