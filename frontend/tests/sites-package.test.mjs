import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { access, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import test from 'node:test'

const execFileAsync = promisify(execFile)
const packageScript = fileURLToPath(new URL('../scripts/package-sites-worker.mjs', import.meta.url))

test('packages Vite assets under dist/client for the Sites asset binding', async () => {
  const root = await mkdtemp(join(tmpdir(), 'animetta-sites-package-'))

  try {
    await mkdir(join(root, 'dist', 'assets'), { recursive: true })
    await mkdir(join(root, 'worker'), { recursive: true })
    await writeFile(join(root, 'dist', 'index.html'), '<main>Animetta</main>')
    await writeFile(join(root, 'dist', 'assets', 'app.js'), 'export {}')
    await writeFile(join(root, 'worker', 'sites-static.mjs'), 'export default {}')

    await execFileAsync(process.execPath, [packageScript], { cwd: root })

    await access(join(root, 'dist', 'client', 'index.html'))
    await access(join(root, 'dist', 'client', 'assets', 'app.js'))
    await access(join(root, 'dist', 'server', 'index.js'))
    await assert.rejects(access(join(root, 'dist', 'index.html')))
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})
