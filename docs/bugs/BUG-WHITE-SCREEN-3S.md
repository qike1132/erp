# BUG-WHITE-SCREEN-3S 修复记录

- **修复时间**: 2026-04-29
- **Git Commit**: 8bf683d5a796516bb7e7481406c2be0322cae1b7 (修复前基线)
- **根因分析**: 前端页面首次加载时存在约3秒纯白屏，由以下4个因素叠加导致：
  1. `index.html` 中 `<div id="app"></div>` 无任何内联加载指示器，JS 未执行前用户看到纯白页面
  2. `main.ts` 同步导入 `@fortawesome/fontawesome-free/css/all.min.css`（200-500KB），阻塞首次渲染
  3. `authStore.init()` 中 `fetchUser()` 和 `fetchNavSections()` 串行 await，两次 API 请求延迟叠加
  4. `router/index.ts` 的 `beforeEach` 中动态 `import('@/stores/auth')`，每次导航增加模块加载开销
- **影响范围**: 所有用户首次访问页面时的加载体验
- **修复方案**:
  | 编号 | 修复项 | 文件 | 变更说明 |
  |------|--------|------|----------|
  | P1-01 | 添加内联加载指示器 | `frontend-vite/index.html` | 在 `#app` 内添加纯CSS加载动画，HTML返回后立即可见 |
  | P1-02 | FontAwesome 异步加载 | `frontend-vite/src/main.ts` | 将同步 `import` 改为 `import()` 动态导入，不阻塞首次渲染 |
  | P1-03 | 导航数据非阻塞加载 | `frontend-vite/src/stores/auth.ts` | `fetchNavSections()` 改为 fire-and-forget，不阻塞首屏渲染 |
  | P2-01 | auth store 静态导入 | `frontend-vite/src/router/index.ts` | 将动态 `import()` 改为顶层静态 `import`，消除每次导航的动态加载开销 |
- **验证结果**:
  - Vite 构建成功，FontAwesome CSS 已分离为独立 chunk
  - TypeScript 类型检查通过（修改文件无新增错误）
  - 内联加载指示器在构建产物中正确保留
  - 预期首屏体验改善：白屏 → 加载动画(0ms) → 页面渲染(~1s内)

- **迭代审核记录**:

  **第1轮审核（修复后）**:
  - 发现 P1：`fetchNavSections().catch(() => {})` 静默吞没错误 → 已修复为 `.catch((e) => console.error('[Auth] 导航数据加载失败:', e))`
  - 发现 P2：`main.ts` 中加载指示器淡出逻辑操作已脱离DOM的节点（Vue mount同步替换#app内容） → 已移除无效代码
  - 发现 P2：`index.html` 中 `.fade-out` CSS类已无使用者 → 已移除

  **第2轮审核（修复后）**:
  - 6维度扫描全部PASS
  - 4条执行路径追踪全部PASS：未登录首次访问、已登录首次访问、fetchNavSections失败、FontAwesome加载失败
  - 无循环依赖、无资源泄漏、无状态不一致
  - Vite build验证通过，构建产物包含正确的内联加载指示器
- **性能对比预估**:
  | 指标 | 修复前 | 修复后 |
  |------|--------|--------|
  | 首次可见内容(FCP) | ~1.5-3s（白屏） | ~0ms（加载动画立即可见） |
  | 首次有意义内容(FMP) | ~2-3s | ~1-1.5s |
  | FontAwesome 阻塞 | 是（同步导入） | 否（异步导入） |
  | API 串行延迟 | fetchUser + fetchNavSections | 仅 fetchUser（导航数据后台加载） |
