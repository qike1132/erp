import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { dirname, resolve } from 'path'
import { fileURLToPath } from 'url'

// 自定义 vitest 配置（不依赖 vite.config.ts 的回调形式，避开 mergeConfig 兼容问题）
// P2（2026-10-24）：package.json 是 "type": "module"，本文件按 ESM 加载，__dirname 不存在
// （原先一跑 `vitest -c vitest.bugfix.config.ts` 就 ReferenceError）。
const _dirname = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(_dirname, 'src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
})
