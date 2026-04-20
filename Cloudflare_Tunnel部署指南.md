# Cloudflare Tunnel 详细部署教程 — 滨发协同系统

> 域名：`erp.leishen7.dpdns.org` | 成本：¥0 | 预计耗时：20-30分钟

---

## 前置条件

- 你的 ERP 系统已通过 Docker Compose 正常运行
- 你的域名 `leishen7.dpdns.org` 已在 Cloudflare 上（NS 已指向 Cloudflare）
- 你的服务器能访问外网（cloudflared 需要出站连接 Cloudflare）

---

## 第 1 步：登录 Cloudflare 并确认域名

### 1.1 登录 Cloudflare

1. 打开浏览器，访问 https://dash.cloudflare.com
2. 输入你的账号密码登录（如果还没有账号，点击 Sign up 注册，选择 Free 计划）

### 1.2 确认域名在 Cloudflare 上

1. 登录后，你会在首页看到你的网站列表
2. 找到 `leishen7.dpdns.org`，点击进入
3. 确认状态显示为 **Active**（绿色），说明 DNS 已正确托管

> 如果列表中没有该域名，说明 NS 还没指向 Cloudflare。请先到 DigitalPlat 面板修改 NS 记录为 Cloudflare 提供的 NS 服务器。

---

## 第 2 步：注册 Zero Trust（首次使用必须）

### 2.1 进入 Zero Trust

1. 在 Cloudflare 首页，点击左侧菜单的 **Zero Trust**（图标是一个盾牌）
2. 首次使用会提示你设置团队名称

### 2.2 设置团队名称

1. 输入团队名称，如 `binfa-erp`（随意取，只用于管理标识）
2. 选择 **Free 计划**（$0/月）
3. 点击 **Continue** 完成注册

> Zero Trust 免费计划包含：最多 50 名用户、无限 Tunnel、基本访问策略。完全满足 ERP 系统需求。

---

## 第 3 步：创建 Cloudflare Tunnel

### 3.1 进入 Tunnel 管理页面

1. 在 Zero Trust 左侧菜单中，点击 **Networks** 展开子菜单
2. 点击 **Tunnels**

### 3.2 创建新 Tunnel

1. 点击右上角的 **Create a tunnel** 按钮
2. 选择 tunnel 类型：选择 **Cloudflared**（第一个选项，带橙色云图标）
3. 点击 **Next**

### 3.3 命名 Tunnel

1. 在 Name your tunnel 输入框中填写：`erp-tunnel`
2. 点击 **Save tunnel**

### 3.4 获取 Token（关键步骤！）

创建后，页面会显示安装命令。你只需要 **Token 部分**：

```
示例页面内容：
┌─────────────────────────────────────────────────────┐
│  Install and run connector                          │
│                                                     │
│  Debian/Ubuntu:                                     │
│  sudo cloudflared service install eyJhIjoi...      │
│                                ^^^^^^^^^^^^         │
│                                这就是你的 Token      │
└─────────────────────────────────────────────────────┘
```

**复制这个 Token**（格式类似 `eyJhIjoiY2YwN...` 很长一串）

> 重要：Token 不会再次显示！请立即复制保存到记事本。如果丢失，需要删除 Tunnel 重新创建。

### 3.5 暂时跳过安装命令页面

不要在服务器上执行页面上的命令，我们用 Docker 方式运行。直接点击 **Next** 继续。

---

## 第 4 步：配置 Tunnel 路由

### 4.1 添加 Public Hostname

在 Route tunnel 页面，点击 **Add a public hostname**：

**填写以下信息：**

| 字段 | 填写内容 | 说明 |
|------|---------|------|
| Subdomain | `erp` | 子域名前缀 |
| Domain | 选择 `leishen7.dpdns.org` | 下拉选择你的域名 |
| Type | `HTTP` | 注意选 HTTP 不是 HTTPS |
| URL | `nginx:80` | Docker 内网 Nginx 地址 |

填写后的效果：

```
┌──────────────────────────────────────────────────┐
│  Public hostname                                 │
│                                                  │
│  Subdomain: [erp      ] . [leishen7.dpdns.org▼] │
│                                                  │
│  Service                                         │
│  Type: [HTTP▼]   URL: [nginx:80            ]    │
│                                                  │
│  + Add a public hostname                         │
└──────────────────────────────────────────────────┘
```

### 4.2 为什么选 HTTP 而不是 HTTPS？

```
用户浏览器 ──HTTPS──→ Cloudflare CDN ──HTTP──→ cloudflared ──HTTP──→ nginx

Cloudflare 边缘已经提供了 HTTPS（自动证书），
cloudflared 到 nginx 是 Docker 内网通信，不需要加密。
```

### 4.3 保存

点击 **Save tunnel** 完成。

此时 Cloudflare 会自动在你的 DNS 中创建一条 CNAME 记录：
```
erp.leishen7.dpdns.org → <tunnel-uuid>.cfargotunnel.com（橙色云代理）
```

---

## 第 5 步：将 Token 填入配置文件

### 5.1 编辑 .env.production

用文本编辑器打开 `d:\erp_system\.env.production`，在文件末尾找到：

```bash
# Cloudflare Tunnel Token（从 Cloudflare Zero Trust 面板获取后填入）
# CLOUDFLARE_TUNNEL_TOKEN=
```

修改为（粘贴你复制的实际 Token）：

```bash
# Cloudflare Tunnel Token
CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoiY2YwN...（粘贴你的完整Token）
```

> 注意：Token 前面不要有空格，Token 很长（约200-300字符），确保完整粘贴。

---

## 第 6 步：启动服务

### 6.1 启动所有 Docker 容器

```bash
cd d:\erp_system
docker compose up -d
```

### 6.2 确认 cloudflared 容器运行正常

```bash
docker ps | findstr cloudflared
```

应看到类似输出：
```
erp-system-cloudflared   cloudflare/cloudflared:latest   Up 30 seconds
```

### 6.3 查看 cloudflared 日志

```bash
docker logs erp-system-cloudflared
```

**正常输出应包含：**
```
INF Connection ... registered connIndex=0 ...
INF Connection ... registered connIndex=1 ...
INF Connection ... registered connIndex=2 ...
INF Connection ... registered connIndex=3 ...
```

看到 4 个 `registered` 表示 Tunnel 已成功连接到 Cloudflare 全球网络。

**如果看到错误：**
```
ERR error="failed to login to Cloudflare"
```
说明 Token 不正确，请重新检查第 5 步。

---

## 第 7 步：验证服务

### 7.1 浏览器访问 ERP

1. 在任意设备（手机/电脑）打开浏览器
2. 访问：**https://erp.leishen7.dpdns.org/**
3. 应看到 ERP 系统的登录页面

> 首次访问可能需要 10-30 秒（DNS 缓存刷新），之后会很快。

### 7.2 测试 API 健康

浏览器访问：**https://erp.leishen7.dpdns.org/api/health**

应返回：
```json
{"status": "ok"}
```

### 7.3 测试 WebSocket

在浏览器按 F12 打开开发者工具 → Console 标签，粘贴执行：

```javascript
ws = new WebSocket('wss://erp.leishen7.dpdns.org/ws/notifications?token=test')
ws.onopen = () => console.log('WebSocket 连接成功!')
ws.onerror = (e) => console.log('WebSocket 错误:', e)
ws.onclose = (e) => console.log('WebSocket 关闭:', e.code, e.reason)
```

预期结果：
- 如果看到 `WebSocket 关闭: 4001 未认证` — **路由正确**（token=test 无效所以被拒绝，但说明链路通了）
- 如果看到 `WebSocket 连接成功!` — 完美（极少数情况）
- 如果一直无输出或网络错误 — 检查下面的排错章节

### 7.4 测试完整登录流程

1. 在浏览器访问 `https://erp.leishen7.dpdns.org/`
2. 输入用户名密码登录
3. 确认页面正常加载、API 数据正常

---

## 第 8 步：更新 Android App

### 8.1 确认代码已更新

以下文件已经预置了新域名，确认内容正确：

**`android-app/app/build.gradle.kts` 第 73 行：**
```kotlin
buildConfigField("String", "BASE_URL", "\"https://erp.leishen7.dpdns.org\"")
```

**`android-app/.../network_security_config.xml`：**
```xml
<domain includeSubdomains="true">leishen7.dpdns.org</domain>
```

### 8.2 构建 APK

```bash
cd d:\erp_system\android-app
gradlew assembleRelease
```

### 8.3 安装测试

1. 将生成的 APK 安装到手机
2. 打开 App，输入用户名密码登录
3. 确认数据加载正常、WebSocket 通知能收到

---

## 排错指南

### 问题 1：浏览器访问显示 502 Bad Gateway

**原因**：cloudflared 连上了 Cloudflare，但 Nginx 或后端服务未就绪

**排查**：
```bash
# 检查所有容器是否运行
docker ps

# 检查 Nginx 日志
docker logs erp-system-nginx --tail 50

# 检查 ERP 主应用是否健康
docker logs erp-system-app --tail 50
```

### 问题 2：浏览器访问显示 ERR_NAME_NOT_RESOLVED

**原因**：DNS 记录未生效

**排查**：
```bash
# 检查 DNS 解析
nslookup erp.leishen7.dpdns.org
```

如果无法解析：
1. 登录 Cloudflare → 选择 `leishen7.dpdns.org` → DNS
2. 确认有一条 CNAME 记录：`erp` → `<tunnel-uuid>.cfargotunnel.com`，代理状态为橙色云
3. 如果没有，手动添加该 CNAME 记录

### 问题 3：cloudflared 容器无法启动

**排查**：
```bash
# 查看详细错误
docker logs erp-system-cloudflared
```

常见错误：
- `invalid token` → Token 不正确，重新复制
- `connection refused` → 服务器出站被防火墙拦截，需开放 7844 端口（出站）

### 问题 4：WebSocket 连接失败

**排查**：
1. 确认 Nginx 有 `/ws/` location 配置（已在前面添加）
2. 检查 Nginx 日志是否有 `/ws/` 请求：
```bash
docker exec erp-system-nginx cat /var/log/nginx/access.log | findstr ws
```
3. 确认 Cloudflare 面板中该域名开启了 WebSocket 支持（默认开启）

### 问题 5：国内访问很慢

Cloudflare 国内节点较少，可能延迟较高。优化方案：

1. **开启 Cloudflare 速度优化**：Cloudflare 面板 → Speed → Optimization → 开启 Auto Minify 和 Brotli
2. **设置缓存规则**：Cloudflare 面板 → Caching → Configuration → 设置静态资源缓存
3. **考虑备用方案**：EasyTier mesh VPN 用于国内设备间直连（零延迟）

### 问题 6：云服务器出站端口被封锁

cloudflared 默认使用以下出站端口连接 Cloudflare：
- **7844**（QUIC，首选）
- **443**（HTTPS，备用）

如果服务器出站端口受限，在 docker-compose.yml 的 cloudflared 服务中添加：
```yaml
cloudflared:
  image: cloudflare/cloudflared:latest
  container_name: erp-system-cloudflared
  restart: unless-stopped
  command: tunnel --no-autoupdate --protocol http2 run --token ${CLOUDFLARE_TUNNEL_TOKEN:-REPLACE_WITH_YOUR_TOKEN}
  networks:
    - erp-network
  depends_on:
    nginx:
      condition: service_healthy
```

`--protocol http2` 强制使用 HTTPS 443 端口出站，避免 QUIC 7844 被封。

---

## Windows 非部署方式运行（可选）

如果你不在 Docker 中运行，而是用 Windows 生产模式（`start_production_optimized.py`），可以单独安装 cloudflared：

### 方式 A：直接运行

1. 下载 cloudflared：https://github.com/cloudflare/cloudflared/releases/latest
   - 选择 `cloudflared-windows-amd64.msi` 安装，或 `cloudflared-windows-amd64.exe` 免安装
2. 打开命令提示符，运行：
```cmd
cloudflared service install eyJhIjo...（你的Token）
```
3. cloudflared 会注册为 Windows 服务并自动启动

### 方式 B：手动运行（调试用）

```cmd
cloudflared tunnel --no-autoupdate run --token eyJhIjo...
```

> 注意：非 Docker 方式下，cloudflared 默认连接 `http://localhost:80`（Nginx 端口）。如果 Nginx 也在运行，这可以直接工作。

---

## 安全加固建议（可选）

### 1. 启用 Cloudflare Access 保护（免费）

如果你不想让 ERP 系统对全网开放，可以在 Zero Trust 中添加访问策略：

1. Zero Trust → Access → Applications → Add an application
2. 选择 Self-hosted
3. 填写域名：`erp.leishen7.dpdns.org`
4. 添加策略：如要求邮箱登录才能访问
5. 这样未授权用户即使知道域名也无法访问

### 2. 启用 WAF 防火墙（免费）

1. Cloudflare 面板 → Security → WAF
2. 开启 Managed Rules（Free 计划包含基本规则集）
3. 这可以自动拦截 SQL 注入、XSS 等常见攻击

---

## 完整架构图

```
  手机/电脑(任意网络)
        │
        │ HTTPS
        ▼
  ┌───────────────────┐
  │  Cloudflare CDN   │  ← 自动 HTTPS 证书
  │  全球 Anycast 网络  │  ← DDoS 防护 + WAF
  └────────┬──────────┘
           │ QUIC (出站, 无需开放入站端口)
           ▼
  ┌───────────────────┐
  │  cloudflared 容器  │  ← Docker 内网
  └────────┬──────────┘
           │ HTTP
           ▼
  ┌───────────────────┐
  │   Nginx 容器 :80   │  ← 路由分发
  └──┬──────┬──────┬──┘
     │      │      │
     ▼      ▼      ▼
  Flask  FastAPI  Grafana
  :5003   :5002   :3000
  (页面)  (API)   (监控)
         (WebSocket)
```

---

## 检查清单

部署完成后，逐项确认：

- [ ] `docker ps` 显示 cloudflared 容器运行中
- [ ] `docker logs erp-system-cloudflared` 显示 4 个 registered
- [ ] 浏览器访问 `https://erp.leishen7.dpdns.org/` 能打开 ERP
- [ ] 浏览器访问 `https://erp.leishen7.dpdns.org/api/health` 返回 ok
- [ ] WebSocket 连接 `wss://erp.leishen7.dpdns.org/ws/` 可达
- [ ] Android App 可登录并收通知

全部打勾即部署成功！
