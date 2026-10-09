# 设计：ERP 3000 端口启用 HTTPS（自签内部 CA）

- 日期：2026-10-09
- 状态：待用户复核
- 作者：Claude Code（与用户共同）
- 关联记忆：`erp-production-topology-verified`、`deploy-verify-2026-10-08`、`erp-dev-stack-vs-nssm-services`

## 1. 背景与现状（实测，2026-10-09）

用户诉求原话："给我我的ERP系统上https" → 追问后明确为 **"3000 可以走 https 吗"** → 形态选定 **"3000 端口直接变 HTTPS"**。

**关键澄清：系统其实早已在 HTTPS 上。** 实测：

| 项 | 实测结果 |
|---|---|
| `https://192.168.0.95/` (443) | ✅ LISTENING、返回 200（nginx worker PID 6164/6364） |
| `http://192.168.0.95:3000/` | ✅ LISTENING、返回 200（同构 server 块） |
| 证书主体 | `CN=erp.binfa.internal, O=Binfa ERP, C=CN`，由 `CN=Binfa ERP Internal CA` 签发 |
| SAN | `erp.binfa.internal`、`localhost`、`127.0.0.1`、`192.168.0.95` |
| 有效期 | 2026-10-01 → 2029-09-30 |
| 证书落盘 | `config/tls/{ca.crt,ca.key,server.crt,server.key,...}`（在库；`ca.key`/`server.key` 为私钥） |
| 配置来源 | `config/nginx-windows.conf`（443 块 :51-236，3000 块 :238-414） |
| 线上是否认此配置 | 强证据：`logs/nginx-access-ssl.log` 11:37 仍在写、`logs/nginx-error-ssl.log` 存在 |

因此本任务**不是从零搭 HTTPS**，而是把已存在的 3000 明文 listener 改成 TLS listener。自签证书在未导入客户端的机器上会显示"不受信任"——这是独立问题，不在本改动范围内。

## 2. 目标 / 非目标

**目标**
- `https://192.168.0.95:3000` 可用，复用现有内部 CA 证书 `config/tls/server.crt`。
- 3000 只跑 TLS。

**非目标（明确排除）**
- ❌ 不申请/更换公信 CA 证书，不做公网暴露。
- ❌ 不关闭 3000，不留 301 跳转缓冲（用户已接受"旧链接失效"）。
- ❌ 不改 443 块、不改反代目标（后端仍 `127.0.0.1:5002`，仅回环，红线 #3 不动）。
- ❌ 不把 `ca.crt` 自动装进客户端信任根（客户端消除警告是独立运维项）。
- ❌ 不做"http 和 https 同端口"的折中（同端口无法双协议）。

## 3. 根因

无 bug。现状是"3000 明文 + 443 TLS 双入口"的历史过渡设计（见 3000 块顶部注释"过渡期 HTTP"）。用户希望入口统一为 HTTPS，故把 3000 也 TLS 化。

## 4. 决策（用户已拍板）

- **D1**：3000 直接变 TLS，`http://IP:3000` 立即失效，不做跳转缓冲。
- **D2**：两个内部健康探针（prod_runner、watchdog）改访问 https 后，**信任内部 CA 文件** `config/tls/ca.crt`（而非导系统信任库、也非不校验）。

## 5. 改动设计

### 5.1 `config/nginx-windows.conf`（核心）

3000 server 块（:239-414）：
- `listen 3000 default_server;` → `listen 3000 ssl default_server;`
- `listen [::]:3000 default_server;` → `listen [::]:3000 ssl default_server;`
- 新增证书指令，与 443 块逐字一致：
  ```
  ssl_certificate     D:/erp_system/config/tls/server.crt;
  ssl_certificate_key D:/erp_system/config/tls/server.key;
  ssl_protocols       TLSv1.2 TLSv1.3;
  ssl_session_cache   shared:SSL:10m;
  ssl_session_timeout 1d;
  ```
- 更新块顶部注释（"过渡期 HTTP" → "3000 已 TLS"）。

443 块**不动**。

### 5.2 内部健康探针（不改必误报）

线上 nginx 认仓库配置，3000 变 TLS 后 `http://127.0.0.1:3000` 会 TLS 握手失败：

- `fastapi_app/core/prod_runner.py`
  - `_frontend_probe_ok`（:545）URL `http://127.0.0.1:{web_port}/nginx-health` → `https://...`
  - `_OPENER_DIRECT`（:182）当前 `build_opener(ProxyHandler({}))` 用**默认 HTTPSHandler（会校验证书）**，需挂一个信任 `config/tls/ca.crt` 的 `ssl.SSLContext`。
  - 统一一处 `_internal_ca_context()` 供后端探针复用。
- `scripts/ops/watchdog.py`
  - `--web-url` 默认值（:389）`http://127.0.0.1:3000` → `https://...`
  - `http_get`（:125）`urlopen` 挂同一套 CA 信任 context。
- CA 文件路径：用项目根相对解析（`Path(__file__).resolve().parents[...]` / `ROOT`），**不硬编码** D:\ 绝对路径（红线：CI 在 Linux 跑）。文件缺失时降级：记录告警并回退不校验（保证探针不因缺文件而假死），或直接失败——见 §6 待定。

### 5.3 `.env`（运行时，不入库）

- `WATCHDOG_WEB_URL=http://127.0.0.1:3000` → `https://127.0.0.1:3000`
- `CORS_ORIGINS` 显式补 `https://192.168.0.95:3000`（https 来源本已自动放行，显式仅为可读性）
- `WS_ALLOWED_ORIGINS=192.168.0.95:3000` **无需改**：中间件拼成 `wss://192.168.0.95:3000`（`middleware.py:302`），改 TLS 后正好正确。

### 5.4 前端（预计零改动，已验证）

- API base 是相对路径：`request.ts:38` `baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1'` → 随页面协议自动 https。
- WebSocket 自动选协议：`useWebSocket.ts:50` `window.location.protocol === 'https:' ? 'wss:' : 'ws:'` → 自动 wss。
- CSP 的 `connect-src 'self' ws: wss:` 已覆盖 wss。
- `frontend-vite/vite.config.ts:159` 的 `img-src ... http://192.168.0.95:3000` 是 **dev-only 配置**（生产 CSP 来自 `config/security-headers.conf`，且生产 img-src 用 `'self'`），生产被 nginx 覆盖，**非阻塞**。

### 5.5 测试

- `test_qa_prod_stack_regression.py`、`test_prod_runner_frontend_failure.py`：若有依赖 3000 http 探针的断言需同步。
- `test_cors_origin_production_filter.py`：过滤规则不变（`https://` 本就自动放行），补一条 `https://192.168.0.95:3000` 用例。
- `test_request_body_limit_paths.py`（解析 nginx conf 取 location 的 `client_max_body_size`）：改 listen 指令不应影响其解析，回归确认。
- 新增：一个解析 `config/nginx-windows.conf` 断言 3000 块含 `listen 3000 ssl` 的守卫测试（防止回退）。
- **红线**：探针路径解析用相对/`ROOT`，保证 CI（Linux）通过。

## 6. 灰色区 / 待实现阶段验证的假设

1. **线上 nginx 确实由 NSSM `erp-web` 加载仓库 `config/nginx-windows.conf`**（间接证据强，但未直接读服务参数——`nssm get`/wmic 返回值在本机受限）。落地第一步先直接读一次再改。
2. **生产是否 `is_production=True`**（决定 `filter_cors_origins` 是否生效、middleware 是否用 wss：分支）。由 `.env` 的 `ENVIRONMENT`/`APP_ENV` 决定，落地时核对。
3. **CA 文件缺失时的降级策略**：探针"回退不校验"vs"直接失败"。倾向前者（可观测性探针不应自身脆弱），实现时定稿。
4. **ws origin 校验**：`_is_allowed_origin`（middleware.py:178-200）用的是 CORS/CSRF origin 集，不是 WS_ALLOWED_ORIGINS；改 TLS 后 Origin 变 `https://192.168.0.95:3000`，https 一律放行（config.py:102）→ 预计无影响，落地时以 WS 实测确认。
5. **限流 zone 共享**：443 与 3000 共用 `perip`/`authzone`（同 `$binary_remote_addr`）。两入口并行时同一客户端计数合并，理论更早触发 429。改后 3000 为唯一主要入口，风险极低，仅记录。

## 7. 部署与回滚手册（生产机变更运行手册）

**部署**
1. 备份现网配置：`config/nginx-windows.conf` → 带时间戳副本。
2. 落地代码改动（§5）。
3. **提权**校验：`nginx -p D:\erp_system -c config/nginx-windows.conf -t`（非提权会静默失败/退出码 0）。
4. **提权**重载：`nginx -s reload` 或 `nssm restart erp-web`。
5. 重启 `erp-prod`（让探针新代码生效）。

**回滚**（任一步失败）
- 还原 `config/nginx-windows.conf` 备份 → 提权 reload → 重启 erp-prod。因 3000 变 TLS 与 443 无关联，443 入口全程可用，回滚期间用户可走 443。

## 8. 验证闭环（用证据，非口头断言）

- `curl -k https://127.0.0.1:3000/nginx-health` → `{"status":"ok","service":"nginx"}`
- `curl http://127.0.0.1:3000/nginx-health` → 连接失败/协议错（预期，证明明文已关）
- 浏览器 `https://192.168.0.95:3000` 登录成功；WS 实时通知连通（DevTools 看 `wss://` 101）
- `logs/prod_runner.json`：`ready: true` 且 `frontend_ok: true`
- `python scripts/ops/watchdog.py --json`：web_entry 检查通过
- 相关 pytest 全绿（含新增 nginx 守卫测试）

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 非提权 reload 静默失败（退出码 0） | 部署步骤显式要求提权；验证以实测 443/3000 响应为准，不信退出码 |
| 探针假死致 `frontend_ok:false` 误报 | 同步改 prod_runner + watchdog，并加 CA 信任；验证闭环核对 `prod_runner.json` |
| 旧 `http://IP:3000` 链接失效 | 用户已知晓并接受；443 入口不受影响，可作过渡告知用户 |
| 证书不受信仍弹警告 | 独立项：分发 `config/tls/ca.crt` 到客户端信任根（非本改动） |
| 私钥 `config/tls/*.key` 在库 | 已有现状，本次不引入新风险；权限轮换属独立任务 |

## 10. 不做（YAGNI）

- 不引入 Let's Encrypt / 自动续期（内网 IP 无法签发）。
- 不做 HTTP/2、OCSP、HSTS 预载提交等增强。
- 不改 443 块、不改后端监听、不引入新服务。