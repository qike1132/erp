# BUG-HMR-WS-LOGIN-20260427 修复记录

- **修复时间**: 2026-04-27
- **Git Commit**: 待提交
- **根因分析**:
  1. HMR WebSocket 失败：Next.js 开发服务器通过局域网 IP `192.168.0.95:3000` 访问时，缺少 `allowedDevOrigins` 配置，且 CSP `connect-src` 不允许 `ws:` WebSocket 协议
  2. 登录潜在问题：`.env.development` 缺少 `CORS_ORIGINS` 配置，默认值仅含 `localhost`，局域网 IP 访问时后端 CORS 和前端 CSP 均会阻止跨域请求
- **影响范围**: 开发环境通过局域网 IP 访问时的 HMR 热更新和登录功能
- **修复方案**:
  1. `frontend-nextjs/next.config.ts`: 添加 `allowedDevOrigins` 配置，CSP `connect-src` 增加 `ws:` 和 `http://192.168.0.95:5002`
  2. `.env.development`: 添加 `CORS_ORIGINS` 环境变量，包含局域网 IP 相关来源
- **验证结果**: 代码审查通过，需重启 Next.js 和 FastAPI 服务验证
- **健康端点**: http://localhost:5002/health
