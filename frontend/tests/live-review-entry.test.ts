// @vitest-environment node

import { access, readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { expect, it } from 'vitest'

it('standalone live page declares the existing favicon instead of requesting favicon.ico', async () => {
  const html = await readFile(resolve(process.cwd(), 'live.html'), 'utf8')

  expect(html).toMatch(/<link rel="icon" href="\/favicon\.svg"\s*\/>/)
})

it('uses the live page as the only TTS failover visual surface', async () => {
  const viteConfig = await readFile(resolve(process.cwd(), 'vite.config.ts'), 'utf8')

  expect(viteConfig).not.toContain('ttsFailover:')
  await expect(access(resolve(process.cwd(), 'tts-failover.html'))).rejects.toMatchObject({
    code: 'ENOENT',
  })
})

it('uses live.html as the only runtime live surface', async () => {
  const electronMain = await readFile(resolve(process.cwd(), 'electron/main.cjs'), 'utf8')
  const router = await readFile(resolve(process.cwd(), 'src/router/index.ts'), 'utf8')

  expect(electronMain).toContain("mainWindow.loadURL('http://localhost:3000/live.html')")
  expect(electronMain).not.toContain('/live-stream')
  expect(router).not.toContain('/live-stream')
  await expect(
    access(resolve(process.cwd(), 'src/views/LiveStreamPage.vue')),
  ).rejects.toMatchObject({
    code: 'ENOENT',
  })
})
