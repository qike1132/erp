import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
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
    disable: isCapacitor,
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
      rolldownOptions: {
        output: {
          exports: 'auto',
          // Vite 8 已知问题：内部 codeSplitting: 'advance' 可能覆盖此配置
          // 待 Vite 修复后 advancedChunks 参数将完全生效
          // 当前代码分割主要依赖路由懒加载 + ECharts 异步导入
          advancedChunks: {
            minShareCount: 2,
            minSize: 10000,
            groups: [
              { name: 'vendor-echarts', test: /node_modules\/.*(echarts|zrender)/ },
              { name: 'vendor-vue', test: /node_modules\/.*(\/vue\/|\/pinia\/|\/vue-router\/|\/@tanstack\/)/ },
              { name: 'vendor-vueuse', test: /node_modules\/.*\/@vueuse\// },
              { name: 'vendor-fontawesome', test: /node_modules\/.*\/@fortawesome\// },
              { name: 'vendor-reka-ui', test: /node_modules\/.*\/reka-ui\// },
              { name: 'vendor-axios', test: /node_modules\/.*\/axios\// },
              { name: 'vendor-capacitor', test: /node_modules\/.*\/@capacitor\// },
            ],
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
  }
})
