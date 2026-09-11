import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { PrimeVueResolver } from 'unplugin-vue-components/resolvers'
import { VitePWA } from 'vite-plugin-pwa'
import { resolve } from 'path'

export default defineConfig(({ mode }) => {
  return {
    base: '/',
    // 生产构建移除 console.* 调用与 debugger 语句（已确认无依赖 console 副作用的代码）
    esbuild: {
      drop: mode === 'production' ? ['console', 'debugger'] : [],
    },
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
      VitePWA({
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
              urlPattern: /\/api\/v1\/(dashboard|products|stock|report|customer)\/.*/i,
              method: 'GET',
              handler: 'StaleWhileRevalidate',
              options: {
                cacheName: 'api-read-cache',
                expiration: { maxEntries: 200, maxAgeSeconds: 60 * 2 },
                cacheableResponse: { statuses: [0, 200] },
              },
            },
            {
              urlPattern: /\/api\/v1\/(order|stock|batch|purchase)\/.*/i,
              handler: 'NetworkOnly',
            },
            {
              urlPattern: /\/api\/v1\//i,
              handler: 'NetworkFirst',
              options: {
                cacheName: 'api-cache',
                expiration: { maxEntries: 50, maxAgeSeconds: 60 },
                cacheableResponse: { statuses: [0, 200] },
                // 后端故障时 1.5s 内回退到缓存，避免停留在"加载中"等待过久
                networkTimeoutSeconds: 1.5,
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
        // PWA 彻底禁用：http 内网访问下 Service Worker 无法注册（非安全上下文），
        // 且旧 Workbox SW 会预缓存 index.html/静态资源导致"加载中"卡死与旧资源串用。
        // 与项目长期约定"禁用 PWA"保持一致，避免再生成 sw.js/registerSW.js。
        disable: true,
      }),
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
          manualChunks(id: string) {
            const chunks: Record<string, string[]> = {
              'vendor-echarts': ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers'],
              'vendor-vue': ['vue', 'vue-router', 'pinia'],
              'vendor-query': ['@tanstack/vue-query'],
              'vendor-vueuse': ['@vueuse/core'],
              'vendor-fontawesome': ['@fortawesome/fontawesome-svg-core', '@fortawesome/free-solid-svg-icons'],
              'vendor-reka-ui': ['reka-ui'],
              'vendor-axios': ['axios'],
              'vendor-primevue': ['primevue'],
            }
            for (const [name, deps] of Object.entries(chunks)) {
              for (const dep of deps) {
                if (id.includes(`node_modules/${dep}`)) return name
              }
            }
          },
        },
      },
    },
    server: {
      host: '0.0.0.0',
      port: 3000,
      allowedHosts: true,
      headers: {
        'Content-Security-Policy': [
          "default-src 'self'",
          "script-src 'self' 'unsafe-inline'",
          "style-src 'self' 'unsafe-inline'",
          "img-src 'self' data: blob: http://127.0.0.1:5002 http://192.168.0.95:3000 http://192.168.0.95:5002",
          "font-src 'self'",
          "connect-src 'self' ws: wss: http://127.0.0.1:5002 https:",
          "frame-ancestors 'none'",
          "base-uri 'self'",
          "form-action 'self'",
        ].join('; '),
      },
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:5002',
          changeOrigin: true,
          timeout: 120000,
          proxyTimeout: 120000,
        },
        '/static': {
          target: 'http://127.0.0.1:5002',
          changeOrigin: true,
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
        '/static': {
          target: 'http://127.0.0.1:5002',
          changeOrigin: true,
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
      ],
    },
  }
})
