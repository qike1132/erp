# ERP 离线便携包一键部署 — 设计文档

- 日期：2026-10-08（v3，经两轮 opus 评审 + 用户拍板 7 项未决后定稿）
- 状态：待用户最终评审
- 相关：`README.md` §3/§4、`AGENTS.md`、`scripts/migrate/*`（历史迁移脚本，**不复用其骨架**）

## 1. 背景与目标

现状：新服务器从零部署依赖 `README.md` §3（开发）+ §4（生产）两份**人工 runbook**，约 15 步、2–4 小时，踩坑多（2026-10-08 两阶段问题记录：`ALLOWED_HOSTS` JSON / `CORS_ORIGINS` 逗号、redis 模板占位口令、nginx 绝对路径与 temp 目录、`nssm start` 不重载、PG15+ owner 等）。

目标：**一条命令构建、一条命令安装**的离线便携包，把「本机正在运行的 ERP」整套（代码 + 运行环境 + 开发环境 + 数据 + 上传文件 + 配置 + 密钥 + 基础软件）复制到新 Windows 服务器；安装后功能与数据与源机一致。

成功标准：
1. 源机一条命令产出**单个加密包**；
2. 目标机（管理员）一条命令跑完，`README §4.14` 六项验收全过、能登录、能跑通一笔业务、上传图片刷新可见、手动备份产出新鲜产物；
3. 安装端**完全离线**；
4. 幂等：可重复执行、失败可续跑、失败不留明文。

## 2. 非目标（YAGNI）

容器化 / CI 发布、增量包、多目标批量分发、跨操作系统（仅 Windows）、包内嵌套密钥体系。

## 3. 关键决策（已与用户确认）

| # | 决策 | 取值 |
|---|---|---|
| D1 | 形态 | 离线便携包（构建端 + 安装端） |
| D2 | 数据 | 全镜像：`erp_system` 库 + `static/`（uploads/releases/files） |
| D3 | 环境 | 运行 + 开发都装（base+dev+test **+ocr** 依赖随包；OCR 属「功能不能少」） |
| D4 | 基础软件 | 包内附官方安装包，安装端静默/解压装齐 |
| D5 | 包保护 | 口令加密：**PowerShell/.NET `Aes`（AES-256-CBC + PBKDF2-SHA256, 300k iters）流式加解密** —— 零外部二进制（见 §5.8/§6.2）；不用 openssl |
| D6 | 实现 | 混合：新写 `deploy/` 两脚本；复用 `install_on_target.ps1` 已验证片段（`.env` ALLOWED_HOSTS/CORS 改写、NSSM `AppEnvironmentExtra` 一变量一元素） |
| D7 | 全镜像路径 | `pg_restore` 恢复 dump（schema+数据保真）**→ 随后 `alembic upgrade head`** 对齐代码；`-Blank` 才走 alembic+`init_permissions.py`+`seed_nav.py`+建 admin |

> D7 说明：`pg_dump` 为**单库** dump，只保 schema+数据；**不含集群级角色（如只读副本角色）与 ACL**（`--no-owner --no-privileges`）——这些在新机由脚本重建。**恢复后必须 `alembic upgrade head`**：实测生产库 `alembic_version=pg_standalone_078_stock_nav_rename`，而仓库 head=`pg_standalone_079_report_flow_row_action_permissions`，不升则代码面对旧 schema。

## 4. 架构与目录

新增（与 `scripts/migrate/` 分离）：

```
deploy/
  build_package.ps1     # 源机（本机=生产，只读）运行
  install_package.ps1   # 目标机（管理员）运行
  README.md             # 构建→传输→安装 三步说明
  binaries/             # 离线基础软件落位目录（构建端需先放入）
  manifest.schema.md
```

包结构（解包后）：

```
app/                   代码（排除见下）
runtime/python313/     冻结 Python（含 base+dev+test 依赖）
frontend/dist/         前端产物（拷现成的 frontend-vite/dist，**不在源机构建**，见 §5.3）
data/erp_system.dump   pg_dump -Fc
data/static/           源机 static/ 全量（uploads+releases+files，约 45MB）
settings/              .env / jwt/ / uploads-signing.conf / nginx-windows.conf /
                       redis*.conf / security-headers.conf / log_policy.json /
                       nssm-services.json / pgbouncer/ /（otel/promtail/prometheus/alert 可选）
binaries/              PG18 安装器 / Redis-x64-5.0.14.1.zip / nginx zip /
                       nssm-2.24.zip / node msi / vc_redist.x64.exe
                       （**无需 openssl**：包加解密用 .NET Aes）
deploy/install_package.ps1
manifest.txt           构建时间/Python 版本/各目录大小/文件数/dump 的 alembic_version/sha256
最终：erp_portable_<yyyyMMdd_HHmm>.tar.gz.enc  +  .sha256
```

`app/` 排除清单（robocopy `/XD`+`/XF`）：`.git`、`.venv`、`node_modules`、`__pycache__`、`.pytest_cache`、`.mypy_cache`、`.ruff_cache`、`logs`、`temp`、`build`、`evidence`、`backups`、`dist`（根级）、**`_ops/`（凭据，绝不入包）**、`config/pgbouncer/userlist.txt`（明文口令），以及 `AGENTS.md §7` 的 15+ 个 AI 痕迹目录（`.claude/ .graphflow*` 等）；`/XF` 另排 `*.pyc *.pyo *.log *.tmp *.pid`。

## 5. 构建端流程（`build_package.ps1`，源机生产，只读）

参数：`-ProjectDir`(默认 `D:\erp_system`)、`-OutDir`、`-PyDir`(默认自动定位**系统** Python 3.13)、`-SkipZip`、`-BuildFrontend`(默认关，见 §5.3)。

1. **预检**：`.env`、`config/jwt/private_v2.pem`、`config/uploads-signing.conf`、`frontend-vite/dist/index.html` 均存在（缺则 FAIL）；`pg_dump` 可定位（`PG_TOOLS_BIN`→PATH→约定目录，**须含 18**）；`deploy/binaries/` 六件套齐全（缺则列清单+官方 URL 后 FAIL，不停在半个包上）。
2. **记录 git 状态**：`git rev-parse HEAD`、`git status --porcelain` 必须干净；记入 manifest。**不打包未提交改动**。
3. **前端**：默认**只拷现成的 `frontend-vite/dist`**；缺失或明显过旧 → FAIL 并提示「先在开发机 `npm run build:atomic`」（**禁止在生产机上构建**：本机 `%TEMP%` EPERM + nginx 句柄 rename 锁，且会换掉在役 dist）。仅显式 `-BuildFrontend` 才构建（供非生产源机用）。
4. **`pg_dump -Fc`** → `data/erp_system.dump`；同时读 `alembic_version` 记入 manifest。
5. **拷 runtime**：从 `-PyDir`（**真·系统 Python 3.13 安装目录，不是 `.venv`**——`.venv` 的 `pyvenv.cfg` 指回外部 Python，拷走失效）robocopy 到 `runtime/python313`，然后 `runtime\python313\python.exe -m pip install -r requirements/base.txt -r requirements/dev.txt -r requirements/test.txt -r requirements/ocr.txt` 灌依赖（OCR 含 RapidOCR，约 500MB）。
6. **自检**（**FAIL 即停，不 WARN**）：`runtime\python313\python.exe -c "import fastapi,uvicorn,sqlalchemy,asyncpg,pytest,ruff"`。
7. **拷代码 + settings + `data/static/`**（robocopy，排除见 §4）。`.env` 拷自 `settings/.env`（明文，最终被加密）。
8. **写 manifest + sha256**，然后 `tar -czf pkg.tar.gz <内容>`（**用 `-czf`，不要靠 `-a` 推扩展名**）→ 用 .NET `Aes`（AES-256-CBC + PBKDF2-SHA256/300k，随机 salt+IV 写入包头）**流式加密** `pkg.tar.gz` → `erp_portable_<stamp>.tar.gz.enc` → 写 `.sha256` → 删中间 `pkg.tar.gz`。**不依赖 openssl。**
9. **危险路径守卫**（照 `build_portable.ps1:61`）：拒绝 `OutDir` 为盘根 / 等于 / 包含 `ProjectDir`。
10. **只读承诺的诚实边界**：`pg_dump`、读文件为只读；拷 `static/` 时若业务正在写文件，则包内该文件是某一时点快照（可接受；文档注明）。构建端**不** `npm`、**不**停/启服务。

## 6. 安装端流程（`install_package.ps1`，目标机管理员）

参数：`-Package`、`-TargetDir`(默认 `D:\erp_system`)、`-ServerIP`、`-PgSuperPassword`、`-NginxDir`(默认 `C:\nginx`)、`-Force`、`-Blank`、`-EncryptKey`(优先 `Read-Host -AsSecureString`)、`-WithNodeModules`、阶段开关 `-OnlyXxx/-SkipXxx`。

> **目标机路径（用户已定）**：与源机**同路径 `D:\erp_system`**。故 §6.6/§6.7/§6.10 的路径改写**默认跳过**；仅当 `-TargetDir ≠ D:\erp_system` 时才执行（脚本保留该能力，作为健壮性兜底）。

**全程包在 `try { ... } finally { 清 %TEMP% 明文 }`**。每步 `[OK]/[WARN]/[FAIL]`，FAIL 即停并给修复提示。

1. **提权校验** + `ServerIP` 合法性 + **磁盘空间预检**（≥ 包解压体积 + 落盘体积，manifest 里有各目录大小）。
2. **解密解包**：用 .NET `Aes` 解密（口令优先 `Read-Host -AsSecureString`，见 §7）→ `tar -xzf` 到 `%TEMP%\erp_pkg_<guid>\` → 校 `sha256`。**不依赖 openssl。**
3. **装基础软件**（已装则跳过）：VC++（`vc_redist` 返回 1638=已装更高版本→**判成功**）→ PostgreSQL 18 静默（`--mode unattended --superpassword`；失败给官方 URL 与手动步骤）→ Redis（解压 `C:\Redis`）→ Nginx（解压 `-NginxDir`）→ NSSM（`C:\nssm\nssm.exe`）→ Node（msi 静默）。提示 Defender 可能隔离新 `python.exe`（加排除）。
4. **建库**：`CREATE ROLE erp_app LOGIN PASSWORD '<包内 .env 的 DB_PASSWORD>'`（无则建/有则同步口令）+ `CREATE DATABASE erp_system WITH OWNER = erp_app`（**PG15+ owner 必须 erp_app**）。口令取自包内 `.env`，保证应用连得上。
5. **部署代码**：`app/ → TargetDir`；`runtime/ → TargetDir\runtime\python313`；`frontend/dist → TargetDir\frontend-vite\dist`；`data/static → TargetDir\static`；建 `logs/`、`backups/`、`temp\`（NSSM AppStdout 写 `logs\<svc>.log`；`STRICT_CONFIG_CHECK` 校验 `BACKUP_DIR` 可写）。
6. **写 `.env`**（以包内 `settings/.env` 为底，**幂等追加式**；用**字节写 UTF-8 无 BOM**，不用 `Set-Content`）改写：
   - `ALLOWED_HOSTS`（JSON 数组，追加 `-ServerIP`）
   - `CORS_ORIGINS`（逗号串，追加 `http://<-ServerIP>:3000`）
   - `WS_ALLOWED_ORIGINS`（追加 `<-ServerIP>:3000`；**漏改则全部 WebSocket 403**）
   - `JWT_PRIVATE_KEY_PATH` / `JWT_PUBLIC_KEY_PATH`（改为 `<-TargetDir>\config\jwt\...`；**路径不存在则 RS256 启动直接失败**，`config.py:431`）
   - 注释掉 `ASYNC_DATABASE_REPLICA_URL`
   - `DATABASE_URL` / `ASYNC_DATABASE_URL`：**整行删除**（留空会覆盖兜底致 URL 解析失败）
7. **改写 nginx + 生成 conf**：`config/nginx-windows.conf` 里 `D:/erp_system` → `<-TargetDir>`（正斜杠形式，18 处）；`include C:/nginx/conf/mime.types` 的 nginx 安装路径按 `-NginxDir` 替换；**按内容定位并注释 443 server 块**（找 `listen 443 ssl` 所在 server 块，不用行号）；建 `temp\{client_body,proxy,fastcgi,uwsgi,scgi}_temp`。替换计数打印，末尾 `nginx -t` 兜底。
8. **生成 `config/uploads-signing.conf`**：取 `.env` 的 `UPLOAD_URL_SIGNING_SECRET`，照 `uploads-signing.conf.example` 格式（注意 `.example` 里 secret 前有空格，逐字对齐）落位。
9. **数据**：
   - 非 `-Blank`：`pg_restore --no-owner --no-privileges -j 4 data/erp_system.dump`（连 erp_app/erp_system）**→ 用 `<TargetDir>\runtime\python313\python.exe -m alembic -c migrations\alembic.ini upgrade head`**（把 078→079 对齐代码）；若目标库已非空 → 需 `-Force` 或报错。
   - `-Blank`：`alembic upgrade head` + `init_permissions.py --yes` + `seed_nav.py` + **建 admin**（README §4.10B：系统无内置种子，不建则装完无法登录）。
10. **注册 NSSM 五服务**（一律指向**包内 runtime** `<TargetDir>\runtime\python313\python.exe`；`config/nssm-services.json` 的 `D:\erp_system` 字面量**改由脚本按 `-TargetDir` 生成**，不照抄快照）：
    - `erp-prod` → `-m fastapi_app.core.prod_runner --no-arq`，依赖 `erp-redis`
    - `erp-arq` → `-m arq fastapi_app.core.arq_app.WorkerSettings`，依赖 `erp-redis-broker`
    - `erp-web` → `<NginxDir>\nginx.exe -p <TargetDir> -c <TargetDir>\config\nginx-windows.conf`
    - `erp-redis` → `C:\Redis\redis-server.exe C:\Redis\redis.windows-service.conf --requirepass <口令>`（AppDirectory `C:\Redis`）
    - `erp-redis-broker` → `C:\Redis\redis-server.exe <TargetDir>\config\redis-broker.conf --requirepass <口令>`
    - redis conf 落位时**删除任何生效的 `requirepass` 行**（口令只经 `--requirepass`）
    - `AppEnvironmentExtra` **一变量一元素**：`APP_ENV=production`/`FASTAPI_DEBUG=false`/`PYTHONPATH=<TargetDir>`/`PYTHONUTF8=1`/`PYTHONUNBUFFERED=1`/`UVICORN_WORKERS=4`
11. **装看门狗计划任务**：`install_watchdog_task.ps1`，并把 `scripts/ops/watchdog_task.cmd` 里的系统 Python 绝对路径改写为 `<TargetDir>\runtime\python313\python.exe`（否则看门狗必坏）。
12. **防火墙**：放行入站 TCP 3000（443 若启用）。
13. **启动**：`erp-redis → erp-redis-broker → erp-prod → erp-arq → erp-web`（`start` 仅首次；已存在服务改配置后须 `restart`——`start` 对运行中的服务返回 1 且不重载）。
14. **验收**（README §4.14）：`/api/health`、nginx 托管四条判据、`runtime_mode_probe.py`、ARQ 哨兵键、`logs/prod_runner.json` 的 `ready/frontend_ok`。
15. 打印入口 `http://<ServerIP>:3000` + 提示**立即删除源包**并已清 `%TEMP%`。

## 7. 加密与安全

- 包用 .NET `Aes`（AES-256-CBC + PBKDF2-SHA256, 300k iters, 随机 salt+IV）流式加密；**零外部二进制**（全新 Windows 必带 .NET，解包第一步即可用）。不用 openssl。
- 口令：优先 `Read-Host -AsSecureString`；`-EncryptKey` 参数**会进 PowerShell 历史与进程列表**，脚本对此显式告警。
- 包内含 `.env`（SECRET_KEY/DB/Redis/备份加密口令）、`config/jwt/private_v2.pem`、全量数据 → 最高敏感级；README 写明「内网/USB 可信通道传输，安装完**立即删除**源包与临时目录」。
- **不入包**：`_ops/credentials/**`、`config/pgbouncer/userlist.txt`（明文口令，硬排除）。
- `%TEMP%` 明文解包目录在 **finally** 中递归删除（成功/失败都删）。
- 构建端不改生产（只读）。

## 8. 幂等与失败处理

- 服务：装前 `nssm stop` + `nssm remove confirm`（存在时）。
- PG：role/db 探测后建或跳过；`pg_restore` 前若目标库非空 → 要求 `-Force`（避免覆盖并存部署）。
- nginx/.env：追加式改写，已改则跳过（不重复追加 IP/origin）。
- 全局 `$ErrorActionPreference="Stop"`；`-OnlyXxx/-SkipXxx` 支持续跑。
- **失败不留明文**：finally 清 `%TEMP%` + 移除 `Env:PGPASSWORD`。

## 9. 测试策略（诚实边界）

- 本机可做：`powershell.exe -NoProfile -Command '[scriptblock]::Create(...)'` 解析校验语法（**本机只有 PS 5.1，无 `pwsh`**）；构建端 **dry-run**（`-SkipZip`，输出到仓内 `<repo>\.claude\tmp\pkg_dry`，核对清单/校验和）；安装端 `-Skip*` 空跑。
- **端到端安装必须在另一台机/VM 验证**——本机是生产，绝不能当目标机。**需要用户提供一台目标机（或 VM/快照）**。
- 不引入 PowerShell 测试框架（本仓无此基建）。

## 10. 风险

| 风险 | 缓解 |
|---|---|
| dump 版本落后于代码（实测 078 vs 079） | 恢复后强制 `alembic upgrade head`；manifest 记录 dump 版本 |
| 目标机基线未知（.NET/权限/已装同款软件） | 每步探测 + 明确提示；`-Force`；分阶段续跑 |
| PG18/Node 静默安装参数随版本变化 | `-PgBinDir` 兜底；失败给官方 URL 与手动步骤；msi 1638 判成功 |
| `pg_restore` 版本/扩展差异 | `--no-owner --no-privileges`；连接串走 `.env`；扩展随 dump |
| nginx 绝对路径/mime.types 漏改、443 定位脆 | 替换后 `nginx -t`；按内容定位 443 块；计数打印 |
| 包内含密钥外泄 / 半途失败残留明文 | 口令加密 + finally 清 `%TEMP%` + 「传完即删」；`-EncryptKey` 告警 |
| 看门狗指向不存在的系统 Python | 改写 `watchdog_task.cmd` 指向包内 runtime |
| 与 `scripts/migrate/*` 双真相源 | **保留旧脚本**（用户定），在脚本头/README 标 deprecated 指向 `deploy/` |
| 覆盖目标机已有旧 ERP（用户定「覆盖」） | 破坏性：须显式 `-Force`；先停+删旧五服务再落文件 |

## 11. 已决问题（用户 2026-10-08 拍板）

1. **目标机路径**：与源机**同路径 `D:\erp_system`** → 路径改写默认跳过（§6 保留能力作兜底）。
2. **`scripts/migrate/*`**：**保留**；在脚本头/README 标 deprecated 指向 `deploy/`（新权威）。
3. **OCR**：算「功能不能少」→ runtime 含 `requirements/ocr.txt`（RapidOCR，约 500MB）。
4. **`backups/`**：**不进包**（目标机只建空目录满足 `BACKUP_DIR` 可写校验）。
5. **目标机已有旧 ERP**：**覆盖**（停→删旧五服务→落文件；破坏性，须显式 `-Force`）。
6. **前端离线开发**：**默认不带 `node_modules`**，加 `-WithNodeModules` 开关（生产只需 dist；开发在目标机 `npm ci` 一次；真要全离线开箱即开发再开开关）。
7. **openssl**：**不用**——包加解密改用 .NET `Aes`（零外部二进制，§5.8/§6.2）。

> 仍待落实（实施阶段，非设计阻塞）：目标机（或 VM/快照）必须由用户提供才能做端到端验证。

## 12. 验收标准

- 构建端：单命令产出 `erp_portable_*.tar.gz.enc` + `.sha256`，**源机生产零影响**（服务不停、库不写、不在源机构建前端）。
- 安装端：目标机单命令跑完，§6.14 六项验收全绿；能浏览器从另一台机登录并跑通业务；上传图片刷新可见；手动备份产出新鲜产物；看门狗首轮通过。
- 加密：错误口令无法解包；无口令包不可读；失败路径不留明文。
