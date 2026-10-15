import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { assertPublicViteEnv } from './config/env-security.js'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  assertPublicViteEnv(env, mode)
  const proxyTarget = env.VITE_API_PROXY_TARGET
  const appBasePath = env.VITE_APP_BASE_PATH || '/'
  if (!appBasePath.startsWith('/') || !appBasePath.endsWith('/')) {
    throw new Error('VITE_APP_BASE_PATH must start and end with /')
  }
  return {
    base: appBasePath,
    plugins: [react()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    build: {
      rolldownOptions: {
        output: {
          codeSplitting: {
            groups: [
              {
                name: 'chart-renderer',
                test: /node_modules[\\/]zrender[\\/]/,
                priority: 20,
              },
              {
                name: 'chart-core',
                test: /node_modules[\\/]echarts[\\/]/,
                priority: 10,
              },
            ],
          },
        },
      },
    },
    server: proxyTarget
      ? {
          proxy: {
            '/api': { target: proxyTarget, changeOrigin: true, secure: false },
          },
        }
      : undefined,
  }
})
