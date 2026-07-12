import { copyFile, mkdir, readdir, rename, rm } from 'node:fs/promises'
import { resolve } from 'node:path'

const root = process.cwd()
const buildDirectory = resolve(root, 'dist')
const clientDirectory = resolve(buildDirectory, 'client')
const serverDirectory = resolve(root, 'dist', 'server')

await rm(clientDirectory, { recursive: true, force: true })
await mkdir(clientDirectory, { recursive: true })

for (const entry of await readdir(buildDirectory, { withFileTypes: true })) {
  if (['.openai', 'client', 'server'].includes(entry.name)) continue
  await rename(
    resolve(buildDirectory, entry.name),
    resolve(clientDirectory, entry.name),
  )
}

await mkdir(serverDirectory, { recursive: true })
await copyFile(
  resolve(root, 'worker', 'sites-static.mjs'),
  resolve(serverDirectory, 'index.js'),
)

console.log('[OK] Sites client assets and Worker entry point packaged')
