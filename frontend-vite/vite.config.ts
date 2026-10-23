import { defineConfig } from 'vite'
import { readFileSync } from 'node:fs'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { PrimeVueResolver } from 'unplugin-vue-components/resolvers'
import { VitePWA } from 'vite-plugin-pwa'
import legacy from '@vitejs/plugin-legacy'
import { resolve } from 'path'

// FontAwesome 懒加载清单中的 CJS 图标子路径必须显式预构建：
// dev 下 optimizeDeps.noDiscovery=true 不会自动发现它们，
// 动态 import 会因 CJS 互操作失败导致图标空白。
const fontAwesomeLoaderSource = readFileSync(
  resolve(import.meta.dirname, 'src/utils/fontAwesomeLoader.ts'),
  'utf-8',
)
const fontAwesomeIconIncludes = [
  ...fontAwesomeLoaderSource.matchAll(/import\('@fortawesome\/free-solid-svg-icons\/([^']+)'\)/g),
].map((m) => `@fortawesome/free-solid-svg-icons/${m[1]}`)

export default defineConfig(({ mode }) => {
  // P2（2026-10-24）：删除未使用的 loadEnv 调用（原 `const env = loadEnv(...)` 赋值后
  // 从未使用，且第三参 '' 是「加载全部 env 含非 VITE_ 前缀」的宽口径）。
  const isCapacitor = mode === 'capacitor'

  return {
    base: '/',
    define: {
      __CAPACITOR_BUILD__: JSON.stringify(isCapacitor),
    },
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
      // 旧 Chromium 内核兼容（第 1 层：JS）。
      // Vite 7 默认编译目标是 'baseline-widely-available'(Chrome107/Edge107/Firefox104/
      // Safari16)：旧内核解析 ??= / ||= / 类字段等语法即抛 SyntaxError —— 入口 chunk
      // 失败=整页白屏，懒加载路由 chunk 失败=点菜单空白。本插件据此把现代 bundle 降到
      // modernTargets，并只补缺失的运行时 API（Object.hasOwn / Array.at / replaceAll 等）。
      // renderLegacyChunks:false —— 目标浏览器(≥Chrome61)已支持 <script type="module">，
      // 无需 SystemJS/nomodule 回退；也避免注入内联脚本，与 SPA 入口 CSP
      // `script-src 'self'`(无 'unsafe-inline') 不冲突
      // （守卫测试 fastapi_app/tests/test_spa_csp_no_inline_scripts.py）。
      // 注意：本插件会接管 build.target（覆盖 vite.config 里手写的值），故降级目标只在此声明。
      legacy({
        // 与 plugin-legacy 内置默认一致(edge79/firefox67/chrome64/safari12/chromeAndroid64/iOS12)，
        // 显式写出以便日后按现场内核收紧/放宽。注意勿漏 chromeAndroid/iOS —— 本项目有移动端 UI。
        modernTargets: [
          'chrome >= 64',
          'chromeAndroid >= 64',
          'edge >= 79',
          'firefox >= 67',
          'safari >= 12',
          'iOS >= 12',
        ],
        renderLegacyChunks: false,
        modernPolyfills: true,
      }),
      VitePWA({
        registerType: 'autoUpdate',
        workbox: {
          // 2026-10-14：SW 不再接管 HTML —— 发布后用户一直看到旧界面的根因。
          // 原状：generateSW 默认 navigateFallback='index.html' + 预缓存收 index.html，
          // 于是 SW 用预缓存的旧 index.html 应答所有导航（含 /report）→ 里面引用的还是
          // 旧入口 chunk → 整套旧代码；且无痕窗口的 SW 活到该窗口组全关为止，刷新无用。
          // 下面两行必须**成对**存在，缺一即坏：
          //   · navigateFallback: null 关掉 NavigationRoute；只删 index.html 的预缓存
          //     会让它绑到不存在的 URL → createHandlerBoundToURL 抛 non-precached-url。
          //   · globIgnores 把 index.html 移出预缓存；只关 navigateFallback 的话，
          //     workbox 预缓存的 directoryIndex 默认 'index.html'，从根路径进站仍中招。
          // hashed 资源（js/css）照旧预缓存 CacheFirst，性能不受影响；导航一律回源。
          navigateFallback: null,
          globIgnores: ['**/index.html'],
          globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
          // 首装带宽尖峰：单个超过 2MB 的 chunk 不预缓存，改由下方运行时缓存按需填充
          maximumFileSizeToCacheInBytes: 2 * 1024 * 1024,
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
            // 超过预缓存上限的 chunk 走运行时缓存（不阻塞首装）。
            // 用 CacheFirst 而非 StaleWhileRevalidate：assets 是内容哈希，天然不可变；
            // 且仓库守卫禁止 SWR/NetworkFirst（会缓存陈旧业务数据）。
            {
              urlPattern: /\/assets\/.*\.(?:js|css)$/i,
              handler: 'CacheFirst',
              options: {
                cacheName: 'large-chunks',
                // 内容哈希每次部署换新，不设上限会永久累积
                expiration: { maxEntries: 30 },
              },
            },
            // ERP 为数据一致性敏感系统：全部 API 请求一律 NetworkOnly（不缓存）。
            // 此前读接口用 StaleWhileRevalidate / 兜底 NetworkFirst，Service Worker
            // 会返回陈旧业务数据；且 dev 禁用、prod 启用，制造「生产与 debug 表现
            // 不一致」。API 缓存条目整体移除，仅保留上方静态字体缓存。
            {
              urlPattern: /\/api\//i,
              handler: 'NetworkOnly',
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
        // Capacitor 构建禁用 PWA，开发模式也禁用
        disable: isCapacitor || mode === 'development',
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
            // Capacitor 构建：分离 Capacitor 依赖
            if (isCapacitor) {
              const capChunks: Record<string, string[]> = {
                'vendor-capacitor': ['@capacitor/core', '@capacitor/app', '@capacitor/filesystem', '@capacitor/share'],
              }
              for (const [name, deps] of Object.entries(capChunks)) {
                for (const dep of deps) {
                  if (id.includes(`node_modules/${dep}`)) return name
                }
              }
            }

            const chunks: Record<string, string[]> = {
              'vendor-echarts': ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers'],
              'vendor-vue': ['vue', 'vue-router', 'pinia'],
              'vendor-query': ['@tanstack/vue-query'],
              'vendor-vueuse': ['@vueuse/core'],
              'vendor-fontawesome': ['@fortawesome/fontawesome-svg-core', '@fortawesome/vue-fontawesome'],
              // 图标定义单独成 chunk：仅由 fontAwesomeLoader 动态 import 触发加载，
              // 若与上面的 core 合并会被 entry 静态引入，导致整套图标重回首屏。
              'vendor-fa-icons': ['@fortawesome/free-solid-svg-icons'],
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
      // 构建交换目录必须排除出 watcher（vite 的 ignored 是追加语义，不动默认项）：
      // dev server 只忽略 build.outDir（默认 dist），而 build:atomic 的 --outDir dist-new 是
      // CLI 参数、dev server 解析不到 → chokidar 持有 dist-new 句柄，swap-dist.mjs 的 rename
      // 必抛 EPERM；回滚副本 dist-old 同样落在 watch 树里被锁，回滚一并失败、dist 直接消失
      // （2026-09-28 实际踩到）。改暂存目录名时务必同步加一行；顺带消掉交换触发的重载噪声。
      watch: {
        ignored: ['**/dist-new/**', '**/dist-old/**', '**/dist-old-swap/**', '**/dist_prev_*/**'],
      },
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
        '@capacitor/app',
        '@capacitor/filesystem',
        '@capacitor/share',
        ...fontAwesomeIconIncludes,
      ],
    },
  }
})
