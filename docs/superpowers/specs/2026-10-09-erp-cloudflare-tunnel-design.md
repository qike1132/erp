# 设计：ERP 经 Cloudflare Tunnel 对外暴露（外部伙伴浏览器访问）

- 日期：2026-10-09
- 状态：待用户复核
- 作者：Claude Code（与用户共同）
- 关联：`2026-10-09-erp-3000-https-design.md`、记忆 `network-topology`、`env-broken-aliases`

## 1. 背景与现状（实测，2026-10-09）

用户诉求：**把自建 ERP 暴露到公网，供外部伙伴用浏览器直接访问**（不装客户端）。

### 1.1 网络可达性（实测结论）

| 项 | 实测 | 结论 |
|---|---|---|
| 出口 IPv4 `14.120.102.7` | `tracert 114.114.114.114`：跳1 `192.168.0.1` → 跳2 `192.168.2.1` → **跳3 `100.64.0.1`** | **CGNAT**，非本线路专属公网 IP |
| IPv4 入站 | 外部探测 `:3000`/`:443`/`:18888` 全 timeout | **不可能**（电信大 NAT 之下） |
| 出口/NIC IPv6 | `240e:3b1:d04d:d0d1::/64`，RA+SLAAC，无 NAT | **真公网、端到端** |
| IPv6 入站 | **手机流量访问本机临时监听 `[240e:...::1014]:18899` 成功** | **可达** |

→ IPv4 端口映射（CPE"虚拟服务器"）在 CGNAT 下无效；IPv6 是唯一直连路径。**但**见 §4 D1：本方案不依赖 IPv6 入站。

### 1.2 ERP 运行栈（实测）

`erp-web`(NSSM) = `C:\nginx\nginx.exe -p D:\erp_system -c config/nginx-windows.conf`

- `nginx :3000`（**明文**，"过渡期 HTTP"）与 `:443`（TLS，`config/tls/server.crt`，`CN=erp.binfa.internal`，内部 CA 签发）**同构双入口**，均反代 `/api` `/ws` `/static` → `uvicorn 127.0.0.1:5002`。
- 前端标题「滨发协同系统」；后端 FastAPI + Postgres + Redis。
- 认证：Argon2id + JWT + Redis 限流 + token 黑名单（`fastapi_app/core/security.py`、`api/v1/endpoints/auth.py`）。
- 后端判定 HTTPS：`auth.py:209` `_is_https = request.url.scheme=="https" or request.headers.get("x-forwarded-proto")=="https"` → 决定登录 Cookie 的 `Secure`/`SameSite=None`。nginx 现用 `proxy_set_header X-Forwarded-Proto $scheme`。

### 1.3 当前暴露面（IPv6 无 NAT，`[::]` 监听即公网可见）

| 端口 | 服务 | 现状 |
|---|---|---|
| `3389` | **RDP**（`fDenyTSConnections=0`，监听 `::`） | 🔴 公网可达，勒索头号入口 |
| `445` / `135` | SMB / RPC | ⚠️ 监听 `::` |
| `3000` / `443` | nginx（ERP） | ⚠️ 公网可达 |
| `7863` | wb2api | ⚠️ 公网可达 |
| `3001` / `53` | AdGuardHome | ⚠️ 公网可达 |
| `5432` | Postgres | ✅ 已加固（仅 loopback，`TCPSTEALTH`） |

> 注：Windows 防火墙三档 `DefaultInboundAction=Block`（`EnableFirewall=1`），但 `:18899` 实测外部可达 → 存在显式 allow 机制，需提权枚举确认（§6）。

## 2. 目标 / 非目标

**目标**
- 外部伙伴经 `https://erp.<用户域名>`（Cloudflare 托管）用浏览器访问 ERP，无需装客户端。
- 源站（本机）不暴露于公网；不需要任何入站端口。
- 同时收敛 §1.3 的暴露面（尤其 RDP/SMB）。

**非目标（明确排除）**
- ❌ 不改后端监听（仍 `127.0.0.1:5002`，红线 #3 不动）。
- ❌ 不申请公网 CA 证书到本机（TLS 由 Cloudflare 边缘终结）。
- ❌ 不做 IPv4 端口映射 / frp / 公网 IP 申请（CGNAT 下无意义）。
- ❌ 不引入第二层自研登录（冲突 §1.2 自带认证）；边缘防护用 Cloudflare WAF，不用 Access 交互登录（避免双重登录）。
- ❌ 不实施 `2026-10-09-erp-3000-https-design.md`（独立任务；本方案与之解耦，见 §4 D2）。

## 3. 架构

```
外部伙伴浏览器
  │  HTTPS :443（公信证书，Cloudflare 签发）
  ▼
Cloudflare 边缘 ── WAF / 限流 / 隐藏源站 ──
  │  出站隧道（cloudflared 主动拨出，无需入站端口）
  ▼
本机 cloudflared ──▶ https://127.0.0.1:443  (nginx, noTLSVerify)
                          └─▶ uvicorn 127.0.0.1:5002 ─▶ Postgres/Redis
```

- 隧道目标 = **`https://127.0.0.1:443`**（理由见 §4 D2），`originRequest.noTLSVerify: true`（回环 + 内部自签 CA）。
- 内网员工照旧 `http://192.168.0.95:3000`（用户已选"内网直连保留"）。

## 4. 决策（用户已拍板）

- **D1**：方案 = **Cloudflare Tunnel**（用户选）。取"伙伴浏览器直接用、IPv4/IPv6 均可访问、隐藏源站、免 DDNS"。
- **D2**：隧道目标 = **443**（非 3000）。因 443 为 TLS（`$scheme=https` → `X-Forwarded-Proto` 正确 → Cookie 标志正确；且 443 块被 `3000-https` spec 明确"不动"，稳定）。指向明文 3000 会触发 Cookie 判定错误，且与该 spec 冲突。
- **D3**：暴露面收敛**首选路由器层**（锐捷 `192.168.0.1` 封全部 IPv6 入站，一次覆盖所有服务），Windows 防火墙做纵深兜底。
- **D4**：公网 RDP = **不需要**（用户确认）→ `3389` 公网入站必须关闭。
- **D5**：内网直连**保留**（用户确认）。
- **D6**：边缘**不加** Access 交互登录；只加 WAF 限流 + 扫描器拦截（认证由 ERP 自带承担）。

## 5. 改动设计

### 5.1 cloudflared（新增，核心）

- 落盘 `cloudflared.exe`（建议 `D:\erp_system\deploy\binaries\` 或 `C:\cloudflared\`）。
- `cloudflared tunnel login` → 授权 CF 账号，得 `cert.pem`。
- `cloudflared tunnel create erp` → 得 `<tunnel-id>.json` 凭据（权限收紧）。
- ingress 配置 `config.yml`：
  ```yaml
  tunnel: <tunnel-id>
  credentials-file: <path>\<tunnel-id>.json
  ingress:
    - hostname: erp.<用户域名>
      service: https://127.0.0.1:443
      originRequest:
        noTLSVerify: true
    - service: http_status:404
  ```
- DNS：`cloudflared tunnel route dns erp erp.<用户域名>`（自动建 CNAME → `<tunnel-id>.cfargotunnel.com`，**橙色云代理**）。
- 服务化：`cloudflared service install`（Windows 服务，开机自启），风格对齐现有 NSSM 服务。

### 5.2 nginx（预计零改动）

443 块已满足：`$scheme=https` → `proxy_set_header X-Forwarded-Proto $scheme` 传 `https` → §1.2 Cookie 逻辑正确。**仅需实测确认**，若不通过再评估。**不改 3000 块**（归 `3000-https` spec）。

### 5.2b `.env` 白名单（**方案跑通的前置，非可选**）

实测加载的 `.env`（`config.py:498` `env_file=".env"`，**只加载项目根 `.env`**）：

```
ALLOWED_HOSTS=["localhost","127.0.0.1","::1","192.168.0.95","DESKTOP-11111","desktop-11111"]
CORS_ORIGINS=http://localhost,http://localhost:5002,http://localhost:3000,http://192.168.0.95,http://192.168.0.95:3000,http://192.168.0.95:5002
WS_ALLOWED_ORIGINS=192.168.0.95:3000
APP_ENV=production
```

- `TrustedHostMiddleware(allowed_hosts=ALLOWED_HOSTS)`（`middleware.py:395`）**拒绝**不在列表的 `Host` → 伙伴访问 `erp.<域名>` 会被 **400**，连登录页都到不了。
- `WS_ALLOWED_ORIGINS` 不含新域名 → WebSocket 实时通知被拦。
- 生产环境 `filter_cors_origins` 过滤明文 HTTP 源（`config.py:112`）。

**必改三项**（改后需重启 `erp-prod`）：

| 键 | 现值 | 改为 |
|---|---|---|
| `ALLOWED_HOSTS` | 内网 IP/主机名 | 追加 `"erp.<域名>"` |
| `WS_ALLOWED_ORIGINS` | `192.168.0.95:3000` | 追加 `erp.<域名>` |
| `CORS_ORIGINS` | 仅 `http://` 源 | 追加 `https://erp.<域名>` |

> `.env` **不入库**（运行时配置）；`.env.production` 是模板，其 `ALLOWED_HOSTS=*` 在生产被 `config.py` 强校验禁止，勿误认。

### 5.3 暴露面收敛（见 §6，需提权）

- **路由器层**：锐捷 `192.168.0.1` → IPv6 防火墙 → 关闭"允许从 WAN 侧入站"。一次覆盖 `3389/445/135/3000/443/7863/3001/53`。
- **Windows 兜底**（提权）：对 `3389`、`445`、`135` 建 Block 入站规则；确认无覆盖性 allow 规则（§1.3 注）。

### 5.4 Cloudflare 侧（控制台）

- WAF：开启托管规则；对 `erp.<域名>` 加 rate limiting（对齐后端登录限流）。
- 关闭"Always Use HTTPS"以外的多余功能；源站由隧道天然隐藏。

## 6. 前置验证（落地第一步，需提权）

1. **枚举入站 allow 规则**：确认 `:18899` 为何外部可达——是 per-app allow 还是有 `Any` 规则。`Get-NetFirewallRule`/`netsh` 需管理员终端（当前会话 UAC 受限）。
2. **锐捷路由器 IPv6 防火墙**：确认存在"IPv6 入站"开关及其位置（品牌 UI 需实测）。
3. **`erp.<域名>`**：确认具体域名（用户提供），及其在 CF 的 NS 状态。
4. **443 反代实测**：`curl -k https://127.0.0.1/nginx-health` 是否 200。

## 7. 部署与回滚

**部署顺序**
- **P0（先做，独立）**：§5.3 收敛暴露面（路由器 + Windows 兜底），先堵 RDP/SMB。
- **P1**：改 `.env` 白名单（§5.2b）→ 重启 `erp-prod`。
- **P2**：安装并配置 cloudflared（§5.1）→ `cloudflared tunnel run erp` 前台验证 → `service install` 服务化。
- **P3**：手机流量访问 `https://erp.<域名>`，验证登录/Cookie/WS。
- **P4**：Cloudflare WAF/限流（§5.4）。

**回滚**
- 任一阶段：`cloudflared service uninstall` + 删 DNS 记录 → 外部立即不可达，内网不受影响。
- 收敛步骤回滚：路由器开关还原 / 删 Windows Block 规则。

## 8. 验证闭环（证据，非口头）

- `cloudflared tunnel info erp`：连接数 ≥1、无 error。
- 手机流量：`https://erp.<域名>` → **不被 400**（证 `ALLOWED_HOSTS` 生效）、出登录页、**登录成功**、DevTools 见 Cookie `Secure`+`SameSite=None`、WS `wss://` 101（证 `WS_ALLOWED_ORIGINS` 生效）。
- 反证 `ALLOWED_HOSTS` 生效：隧道命令中用 `--http-host-header` 伪造未知 Host → 应 400。
- 外网探测本机 IPv6/域名直连源站：`https://[240e:...]:443` 应**不可达**（隧道生效 + 收敛生效）。
- RDP：外部 `3389` 探测应 filtered/timeout。
- `logs/nginx-access-ssl.log` 出现经隧道的请求（`$http_cf_connecting_ip` 或 UA 含 `cloudflare`）。

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| Cookie 标志错误致登录失败 | 隧道指 443（TLS）→ `X-Forwarded-Proto=https`；P2 实测 Cookie |
| 隧道断 → 伙伴无法访问 | 服务化 + `--no-autoupdate`；监控 `tunnel info` |
| IPv6 地址轮换 | **本方案不依赖**（隧道出站）；无需 DDNS |
| RDP/SMB 收敛失败 | P0 优先；路由器层一次覆盖；提权 Windows 规则兜底 |
| 限流 zone 共享（443/3000 同 `$binary_remote_addr`） | 经隧道 `$remote_addr` 变 CF 回源，需评估 `CF-Connecting-IP` 透传（落地时定） |
| 私钥/凭据在库 | `cloudflared` 凭据与 `config/tls/*.key` 权限收紧，独立项 |

## 10. 不做（YAGNI）

- 不做 IPv4 映射 / frp / 公网 IP 申请。
- 不做 Access 交互登录（避免双重登录）。
- 不改后端、不改 443 块、不实施 `3000-https` spec。
- 不做 DDNS（隧道不依赖）。

## 11. 灰色区 / 待落地确认

1. `X-Forwarded-Proto` 经隧道后实际值（nginx `$scheme` 在 TLS 监听下应为 `https`）——P2 实测。
2. 限流键：经隧道后 `$binary_remote_addr` = 回环地址，**所有外部伙伴可能共用同一限流桶**，需改用 `CF-Connecting-IP`（`real_ip` 模块或 map）——落地时评估，可能需小改 nginx。
3. 锐捷路由器 IPv6 防火墙 UI 位置（§6.2）。
4. `erp.<域名>` 具体值 + 是否与内部 `erp.binfa.internal` 命名一致。