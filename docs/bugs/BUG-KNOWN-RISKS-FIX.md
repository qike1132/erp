# BUG-KNOWN-RISKS-FIX 修复记录

- **修复时间**: 2026-04-20
- **Git Commit**: d9765077edf2365b64bfd24b68b0d39fafd47928
- **根因分析**:
  1. xlrd 1.2.0 CVE-2019-19276 (XXE 漏洞)
  2. werkzeug.security 跨框架耦合 (FastAPI 直接依赖 Flask 生态)
  3. CSRF /ws/ 冗余豁免 (WebSocket scope 不经过 HTTP middleware)
  4. Host Header Trust 导致 CSRF 可绕过 (Origin/Referer 校验锚定客户端 Host)
- **影响范围**: 安全: xlrd XXE + Host Header Injection CSRF 绕过 | 兼容性: .xls 弃用, werkzeug 旧哈希兼容 | 架构: 密码工具解耦, TrustedHost + ALLOWED_HOSTS 防线
- **修复方案**:
  1. 移除 xlrd, .xls 格式弃用并提示用户转换 .xlsx (涉及 10+ 文件)
  2. 新建 fastapi_app/core/security.py, 使用 bcrypt 替换 werkzeug.security, 兼容旧哈希 (pbkdf2 + scrypt)
  3. /ws/ 冗余豁免已在前轮清理, 无需操作
  4. Host Header Trust 三重修复:
     - config.py: 新增 ALLOWED_HOSTS 配置项 (默认 localhost,127.0.0.1,erp-app)
     - main.py: CSRF 中间件用 ALLOWED_HOSTS 校验替代 Host 头; 添加 TrustedHostMiddleware
     - nginx.conf: 添加 default_server 拒绝未知 Host; 统一使用 security-headers.conf include
- **验证结果**: L1~L5 全部通过
- **健康端点**: http://localhost:5002/health
