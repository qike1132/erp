---
name: print-preview-iframe
description: 项目打印预览统一使用隐藏 iframe 方式，禁止 window.open 弹窗打印
type: feedback
---

项目打印预览统一使用 `@/utils/print.ts` 中的 `printHtml()` / `printTable()` 函数。

**Why:** window.open 弹窗容易被浏览器拦截，且需要离开当前页面。隐藏 iframe 方式在当前页面内触发浏览器打印对话框，体验更好。

**How to apply:** 所有"打印预览"功能必须使用 `import { printHtml, printTable } from '@/utils/print'`，禁止使用 `window.open('', '_blank')` + `w.document.write()` + `w.print()` 模式。
