import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const livePath = resolve(process.cwd(), 'dist/live.html')
const html = await readFile(livePath, 'utf8')

if (!html.includes('/assets/live-')) {
  throw new Error('dist/live.html does not reference the compiled standalone live entry')
}
if (html.includes('/src/live/main.ts')) {
  throw new Error('dist/live.html still references the source TypeScript entry')
}
if (/https?:\/\/(?:cdn\.|[^/]*jsdelivr)/i.test(html)) {
  throw new Error('dist/live.html contains an external CDN dependency')
}

console.log('[OK] dist/live.html is compiled and self-hosted')
