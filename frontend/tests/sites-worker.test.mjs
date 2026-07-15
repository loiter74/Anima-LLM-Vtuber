import assert from 'node:assert/strict'
import test from 'node:test'

import worker from '../worker/sites-static.mjs'

function createAssets(responses) {
  const requests = []
  return {
    requests,
    binding: {
      async fetch(request) {
        const url = new URL(request.url)
        requests.push(url.pathname)
        return responses.get(url.pathname) ?? new Response('not found', { status: 404 })
      },
    },
  }
}

test('serves an existing static asset without rewriting its path', async () => {
  const assets = createAssets(new Map([['/assets/app.js', new Response('app', { status: 200 })]]))

  const response = await worker.fetch(new Request('https://animetta.example/assets/app.js'), {
    ASSETS: assets.binding,
  })

  assert.equal(response.status, 200)
  assert.deepEqual(assets.requests, ['/assets/app.js'])
})

test('falls back to index.html for a client-side route', async () => {
  const assets = createAssets(
    new Map([
      [
        '/index.html',
        new Response('<main>Animetta</main>', {
          headers: { 'content-type': 'text/html; charset=utf-8' },
          status: 200,
        }),
      ],
    ]),
  )

  const response = await worker.fetch(new Request('https://animetta.example/settings'), {
    ASSETS: assets.binding,
  })

  assert.equal(response.status, 200)
  assert.match(await response.text(), /Animetta/)
  assert.deepEqual(assets.requests, ['/settings', '/index.html'])
})
