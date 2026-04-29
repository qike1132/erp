# BUG-CFG-ENGINEERING 修复记录

- **修复时间**: 2026-04-27
- **Git Commit**: 8bf683d5a796516bb7e7481406c2be0322cae1b7
- **根因分析**: 项目初期快速搭建，未配置工程化基础设施（ESLint/Prettier/EditorConfig/Git Hooks/环境变量/构建优化）
- **影响范围**: 全前端项目代码质量、构建性能、开发体验

## 修复清单

| # | BUG ID | 修复内容 | 状态 |
|---|--------|----------|------|
| 1 | CFG-001 | ESLint + Prettier + EditorConfig 配置 | ✅ |
| 2 | CFG-002 | husky + lint-staged Git 提交门禁 | ✅ |
| 3 | CFG-003 | vite.config.ts build.target + env proxy | ✅ |
| 4 | CFG-004 | .env.development / .env.production / .env.example | ✅ |
| 5 | CFG-005 | 清理未使用依赖 (vxe-table/xe-utils/autoprefixer/postcss/unplugin-element-plus) | ✅ |
| 6 | CFG-006 | package.json 添加 lint/format/type-check 脚本 | ✅ |
| 7 | CFG-007 | favicon.ico → logo_plush.png 修复 | ✅ |
| 8 | CFG-008 | .gitignore 覆盖 node_modules/dist/.tmp | ✅ |

## 已知限制

- manualChunks 在 Vite 8 Rolldown 下暂不生效，520KB chunk gzip 后 174KB 可接受
- ESLint 首次运行会有大量格式 warning，可通过 `npm run lint:fix` + `npm run format` 统一修复

## 验证结果

- vue-tsc 类型检查: 通过 (1 个预存在 TS 错误在 ReportView.vue:199)
- vite build: 通过
- ESLint: 正常运行，检测 warnings
- Prettier: 正常运行，检测格式差异

## 新增/修改文件

- `frontend-vite/vite.config.ts` — 修改：env proxy + build.target
- `frontend-vite/package.json` — 修改：添加脚本+依赖+lint-staged，移除冗余依赖
- `frontend-vite/eslint.config.js` — 新增
- `frontend-vite/.prettierrc` — 新增
- `frontend-vite/.editorconfig` — 新增
- `frontend-vite/.env.development` — 新增
- `frontend-vite/.env.production` — 新增
- `frontend-vite/.env.example` — 新增
- `frontend-vite/index.html` — 修改：favicon 路径
- `.husky/pre-commit` — 新增
- `.gitignore` — 修改：添加前端目录规则
