import { resolve } from 'path'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import unocss from 'unocss/vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendUrl = env.ANIMETTA_BACKEND_URL || 'http://127.0.0.1:12394'

  return {
    root: resolve(__dirname),
    server: {
      port: 3000,
      strictPort: true,
      // Allow ngrok tunnels to access dev server
      allowedHosts: ['.ngrok-free.dev', '.ngrok.io'],
      proxy: {
        '/socket.io': {
          target: backendUrl,
          ws: true,
        },
        '/api': {
          target: backendUrl,
        },
        '/health': {
          target: backendUrl,
        },
        '/ready': {
          target: backendUrl,
        },
      },
    },
    build: {
      rollupOptions: {
        input: {
          app: resolve(__dirname, 'index.html'),
          live: resolve(__dirname, 'live.html'),
        },
      },
    },
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
      },
    },
    optimizeDeps: {
      include: [
        'pixi.js',
        'pixi-live2d-display',
        '@pixi/utils',
        '@pixi/math',
        '@pixi/core',
        '@pixi/display',
      ],
    },
    plugins: [vue(), unocss()],
  }
})
