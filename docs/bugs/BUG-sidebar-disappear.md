# BUG-sidebar-disappear 修复记录

- **修复时间**: 2026-04-27
- **现象**: Dashboard 左侧导航栏在功能区点击多次后或放大缩小 UI 后消失不见
- **根因分析**:
  1. `.sidebar` 缺少 `flex-shrink: 0`，作为 flex 子项，viewport 缩小时被压缩至 0 宽度
  2. `.sidebar` 缺少 `min-width`，无宽度下限保护
  3. 无任何响应式处理（无 @media、无 resize 监听），缩放页面后 flex 布局无法适配
  4. `.app-layout` 的 `overflow: hidden` 直接裁剪被压缩的 sidebar
- **影响范围**: 所有使用 DefaultLayout 的页面，在 viewport 变小（缩放、小屏）时均可能出现导航栏消失
- **修复方案**:
  - AppSidebar.vue: 添加 `flex-shrink: 0` + `min-width: 68px`，防止 flex 压缩
  - AppSidebar.vue: 添加 `@media (max-width: 767px)` 移动端适配（position: fixed + collapsed 时 width:0 隐藏）
  - DefaultLayout.vue: 添加 `windowWidth` + `isMobileOverlay` 响应式状态
  - DefaultLayout.vue: 添加 `handleResize` 监听，小屏自动折叠 sidebar
  - DefaultLayout.vue: 添加 `.sidebar-overlay` 遮罩层，移动端点击遮罩关闭 sidebar
  - DefaultLayout.vue: 添加 `watch(route.path)` 移动端路由切换时自动收起
  - DefaultLayout.vue: `.main-content` 添加 `min-width: 0` 防止 flex 溢出
- **修改文件**:
  - `frontend-vite/src/layouts/components/AppSidebar.vue` (CSS: +8 行)
  - `frontend-vite/src/layouts/DefaultLayout.vue` (template+script+CSS: +25 行)
- **验证结果**: TypeScript 类型检查通过, 构建成功, ESLint 无新增错误
- **回滚命令**:
  ```bash
  git checkout HEAD -- frontend-vite/src/layouts/DefaultLayout.vue frontend-vite/src/layouts/components/AppSidebar.vue
  ```
