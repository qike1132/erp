# ERP 系统前端 - Next.js

基于 Next.js 16 的现代化前端应用，提供完整的 ERP 业务界面。

## 本地开发环境

### 前置要求

- Node.js 18+ （推荐 22）
- npm/yarn/pnpm/bun 任一包管理器

### 启动后端服务

Next.js 前端依赖 FastAPI 后端 API，需要先启动后端：

```bash
# 在项目根目录
cd fastapi_app
uvicorn main:app --reload --host 0.0.0.0 --port 5002
```

后端默认运行在 `http://localhost:5002`。

### 启动前端开发服务器

```bash
cd frontend-nextjs
npm install  # 首次运行需要安装依赖
npm run dev
```

前端默认运行在 `http://localhost:3000`。

### 开发说明

- Next.js 通过 `next.config.ts` 的 rewrites 将 `/api/*` 请求代理到 FastAPI 后端
- 开发环境默认后端地址为 `http://localhost:5002`
- 前端 API 客户端（`src/lib/api-client.ts`）使用 `credentials: include` 自动携带 cookie
- 认证流程：登录 → 设置 httpOnly cookie → 调用 `/api/v1/auth/me` 获取用户信息

### 环境变量（可选）

如需自定义后端地址，可创建 `.env.local` 文件：

```env
# 仅在非同源场景需要（如独立部署）
NEXT_PUBLIC_API_URL=http://your-backend-host:5002

# 服务端 rewrites 用（通常不需要改，默认 localhost:5002）
BACKEND_INTERNAL_URL=http://localhost:5002
```

本地开发通常无需配置，使用默认值即可。

## 测试

### E2E 测试

```bash
npm run test:e2e
```

使用 Playwright 进行端到端测试，默认会自动启动开发服务器。

### 带界面运行测试

```bash
npm run test:e2e:headed
```

## 构建

```bash
npm run build
```

构建产物位于 `.next/standalone` 目录（Docker 部署使用此输出模式）。

## 技术栈

- **框架**: Next.js 16 (App Router)
- **UI 组件**: shadcn/ui + Tailwind CSS 4
- **状态管理**: Zustand
- **数据获取**: TanStack Query
- **表单**: React Hook Form + Zod
- **图标**: Lucide React
- **测试**: Playwright

## 与 FastAPI 集成

### API 通信

- 前端通过 `src/lib/api-client.ts` 封装 API 调用
- 所有请求自动添加 `/api/v1` 前缀
- 使用 `credentials: include` 携带认证 cookie
- 401 自动跳转登录页

### 认证流程

1. 用户提交用户名密码到 `/api/v1/auth/login`
2. 后端返回 httpOnly cookie `access_token`
3. 前端调用 `/api/v1/auth/me` 获取用户信息和权限
4. 用户信息存入 Zustand store (`src/stores/auth-store.ts`)

### 路由守卫

- `src/middleware.ts` 检查 `access_token` cookie
- 未登录访问受保护页面自动跳转 `/login`
- 已登录访问 `/login` 自动跳转 `/dashboard`
