import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { PrimeVueResolver } from 'unplugin-vue-components/resolvers'
import { VitePWA } from 'vite-plugin-pwa'
import { resolve } from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const isCapacitor = mode === 'capacitor'

  const pwaPlugin = VitePWA({
    registerType: 'autoUpdate',
    workbox: {
      globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
      runtimeCaching: [
        {
          urlPattern: /^https:\/\/fonts\.googleapis\.com\/.*/i,
          handler: 'CacheFirst',
          options: {
            cacheName: 'google-fonts-cache',
            expiration: { maxEntries: 10, maxAgeSeconds: 60 * 60 * 24 * 365 },
            cacheableResponse: { statuses: [0, 200] },
          },
        },
        {
          urlPattern: /^https:\/\/fonts\.gstatic\.com\/.*/i,
          handler: 'CacheFirst',
          options: {
            cacheName: 'gstatic-fonts-cache',
            expiration: { maxEntries: 10, maxAgeSeconds: 60 * 60 * 24 * 365 },
            cacheableResponse: { statuses: [0, 200] },
          },
        },
        {
          urlPattern: /\/api\/v1\//i,
          handler: 'NetworkFirst',
          options: {
            cacheName: 'api-cache',
            expiration: { maxEntries: 100, maxAgeSeconds: 60 * 5 },
            cacheableResponse: { statuses: [0, 200] },
            networkTimeoutSeconds: 10,
          },
        },
      ],
    },
    manifest: {
      name: '滨发协同系统',
      short_name: '滨发ERP',
      description: 'ERP协同管理系统',
      theme_color: '#f4f6fc',
      background_color: '#f4f6fc',
      display: 'standalone',
      start_url: '/dashboard',
      icons: [
        { src: '/logo_plush.png', sizes: '192x192', type: 'image/png' },
        { src: '/logo_plush.png', sizes: '512x512', type: 'image/png' },
      ],
    },
    disable: isCapacitor || mode === 'development',
  })

  return {
    plugins: [
      vue(),
      tailwindcss(),
      AutoImport({
        imports: ['vue', 'vue-router', 'pinia'],
        dts: 'src/auto-imports.d.ts',
      }),
      Components({
        dts: 'src/components.d.ts',
        resolvers: [PrimeVueResolver()],
      }),
      pwaPlugin,
    ],
    resolve: {
      alias: {
        '@': resolve(import.meta.dirname, 'src'),
      },
    },
    build: {
      cssCodeSplit: true,
      chunkSizeWarningLimit: 600,
      rollupOptions: {
        output: {
          exports: 'auto',
          // Vite 7 使用 Rollup 4 后端；代码分割依赖路由懒加载 + ECharts 异步导入
          manualChunks: {
            'vendor-echarts': ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers'],
            'vendor-vue': ['vue', 'vue-router', 'pinia', '@tanstack/vue-query'],
            'vendor-vueuse': ['@vueuse/core'],
            'vendor-fontawesome': ['@fortawesome/fontawesome-svg-core', '@fortawesome/free-solid-svg-icons'],
            'vendor-reka-ui': ['reka-ui'],
            'vendor-axios': ['axios'],
            'vendor-capacitor': ['@capacitor/core', '@capacitor/app', '@capacitor/filesystem', '@capacitor/share'],
          },
        },
      },
    },
    server: {
      host: '0.0.0.0',
      port: 3000,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:5002',
          changeOrigin: true,
          timeout: 120000,
          proxyTimeout: 120000,
        },
        '/ws': {
          target: 'ws://127.0.0.1:5002',
          ws: true,
        },
      },
    },
    preview: {
      host: '0.0.0.0',
      port: 3000,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:5002',
          changeOrigin: true,
          timeout: 120000,
          proxyTimeout: 120000,
        },
        '/ws': {
          target: 'ws://127.0.0.1:5002',
          ws: true,
        },
      },
    },
    optimizeDeps: {
      noDiscovery: true,
      include: [
        'vue',
        'vue-router',
        'pinia',
        '@tanstack/vue-query',
        'axios',
        '@vueuse/core',
        'reka-ui',
        'web-vitals',
        'echarts/core',
        'echarts/charts',
        'echarts/components',
        'echarts/renderers',
        '@fortawesome/fontawesome-svg-core',
        '@fortawesome/free-solid-svg-icons',
        '@capacitor/app',
        '@capacitor/filesystem',
        '@capacitor/share',
      ],
    },
  }
})
