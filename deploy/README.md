# ERP 离线便携包（一键部署）

本目录把「裸机 → 可用生产」压缩成**三步**：在**源机（当前生产）**构建一个口令加密的便携包，
经可信通道拷到**目标机**，用管理员跑安装脚本即可完成从装基础软件到服务验收的全流程。

> 与主 [README 第 4 章](../README.md#4-在新服务器上完整部署生产) 的关系：
> 第 4 章是**逐条人工步骤**（理解与排障参考）；本目录是**自动化一键路径**，二者等价。
> 全流程脚本为 **Windows PowerShell 5.1**（命令写 `powershell.exe`，不是 `pwsh`）。

涉及脚本：

| 脚本 | 角色 | 运行位置 |
|---|---|---|
| [`build_package.ps1`](build_package.ps1) | 构建离线便携包（**只读**） | 源机（生产） |
| [`install_package.ps1`](install_package.ps1) | 装配到目标机（**管理员**） | 目标机 |
| `_lib.ps1` | 共用函数（被上面两者 dot-source） | 随包/随仓 |

---

## 步骤 1 —— 构建（在源机，也只在本机生产）

源机就是当前这台生产机。构建**只读**：仅做 `pg_dump` 快照 + 读文件，**不停/启服务、不跑 `npm`**，
只往输出目录写东西。

```powershell
# 在仓库根目录运行；口令为交互式隐藏输入（推荐）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\build_package.ps1

# 等价完整参数
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\build_package.ps1 `
    -OutDir D:\erp_portable `
    -ServerIP 192.168.1.97
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `-ProjectDir` | `D:\erp_system` | 源项目路径 |
| `-OutDir` | `D:\erp_portable` | 组装目录（须为安全路径，脚本会拒绝 ProjectDir 的子孙目录以防误删库子树） |
| `-ServerIP` | `192.168.1.97` | 写进 manifest，作为目标机对外地址 |
| `-EncryptKey` | 交互式提示 | 包加密口令。**省略**则交互式隐藏输入（推荐）；若显式传参会进 PowerShell 历史与进程列表 |
| `-WithNodeModules` | 关 | 额外打包 `frontend-vite\node_modules`（目标机要**做前端开发**才需要；纯生产只需 `dist`，默认不含） |
| `-SkipZip` | 关 | 只组装出 `OutDir` 目录，**跳过** tar+加密+sha256 |
| `-DryRun` | 关 | 只做编排自检（预检/排除/pg_dump/manifest），容忍 `deploy\binaries\` 缺件、跳过依赖安装与打包加密 |

**产物**（写在 `-OutDir` 的同级目录）：

```text
erp_portable_<yyyyMMdd_HHmm>.tar.gz.enc     # 口令加密后的便携包
erp_portable_<yyyyMMdd_HHmm>.tar.gz.enc.sha256   # sha256 校验值
```

**构建前置（缺一即 FAIL，`-DryRun` 例外）**：

- 源机存在：`.env`、`config\jwt\private_v2.pem`、`config\uploads-signing.conf`、`frontend-vite\dist\index.html`；
- `pg_dump` / `psql` 可被探测到（`PG_TOOLS_BIN` / PATH / 约定目录，含 PG18）；
- **工作区干净**（`git status --porcelain` 为空）——不打包未提交改动；
- `deploy\binaries\` 已放齐下列 6 个安装包（下一步）。

### 1.1 先往 `deploy\binaries\` 放 6 个安装包

构建与安装都依赖本目录里的 6 个官方安装包。文件名需能被脚本的匹配式命中：

| 组件 | 版本 | 期望文件名匹配 | 官方下载来源 |
|---|---|---|---|
| PostgreSQL | **18**（EDB 安装器） | `pg18*` | https://www.enterprisedb.com/downloads/postgres-postgresql-downloads |
| Redis for Windows | **5.0.14.1**（tporadowski 发行版） | `Redis-x64-5.0.14.1*` | https://github.com/tporadowski/redis/releases |
| Nginx for Windows | 官方 Windows zip | `nginx*zip` | https://nginx.org/en/download.html |
| NSSM | **2.24** | `nssm*zip` | https://nssm.cc/download |
| Node.js | **LTS x64 msi** | `node*.msi` | https://nodejs.org |
| VC++ 运行库 | **2015–2022 x64** | `vc_redist*zip*`（可放 exe 或 zip） | https://aka.ms/vs/17/release/vc_redist.x64.exe |

> Python **不在**此清单：运行时（Python 3.13）已随包携带，目标机**无需**单独装 Python。
> Redis 必须是 tporadowski 的 **5.0.14.1**，不要换 7.x/8.x 的第三方 Windows 构建。

---

## 步骤 2 —— 传输（经可信通道）

把上一步的两个产物（`.tar.gz.enc` 及其 `.sha256`）经**可信通道**送到目标机：内网共享/USB 均可，
**不要**放公网。目标机可用 `Get-FileHash -Algorithm SHA256` 比对 `.sha256`。

> ⚠️ **包里是什么，决定了传输与处置纪律**：便携包内含 **`.env`（数据库口令、Redis 口令）、
> JWT 私钥 `private_v2.pem`、上传签名密钥，以及**整库 `pg_dump` 与全部用户上传的静态文件**。
> 整包虽已口令加密，但**安装完成后必须立即删除源包**（`.tar.gz.enc` / `.tar.gz` / 解包中间物），
> 不留副本。安装脚本会在 `finally` 里自动清掉 `%TEMP%` 下的明文解包目录与 `PGPASSWORD` 环境变量，
> 但**源包本身**要人手动删。

---

## 步骤 3 —— 安装（在目标机，管理员）

目标机以**管理员**身份运行（提权 → 解包 → 装基础软件 → 建库 → 部署文件 → `.env` 改写 →
导入数据 → 注册五服务 → 防火墙 → 看门狗 → 验收）。

```powershell
# 在包含 deploy\install_package.ps1 与 _lib.ps1 的目录运行
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\install_package.ps1 `
    -Package D:\erp_portable_20261008_1200.tar.gz.enc `
    -ServerIP 192.168.1.97 `
    -PgSuperPassword <postgres 超级用户口令>
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `-Package` | **必填** | 便携包路径（`.tar.gz.enc`） |
| `-TargetDir` | `D:\erp_system` | 目标部署路径，**默认与源机同路径** |
| `-ServerIP` | `192.168.1.97` | 目标机对外 IP，用于改写 `ALLOWED_HOSTS` / `CORS_ORIGINS` / `WS_ALLOWED_ORIGINS` |
| `-PgSuperPassword` | **必填** | 连接 `postgres` 超级用户建库/建角色用；为空即 FAIL |
| `-AdminPassword` | 交互式提示 | **仅 `-Blank` 时**：新超管 `admin` 口令（Argon2id 哈希后写入；不落命令行/日志） |
| `-EncryptKey` | 交互式提示 | 包口令；省略则交互式隐藏输入（推荐） |
| `-NginxDir` / `-RedisDir` / `-Nssm` | `C:\nginx` / `C:\Redis` / `C:\nssm\nssm.exe` | 基础软件落位，按需覆盖 |
| `-Blank` | 关 | **空库起步**：`alembic upgrade head` → `init_permissions` → `seed_nav` → 建超管 `admin`（项目无内置用户种子，必须建一个否则装完无法登录） |
| `-Force` | 关 | **覆盖**目标机已有部署（同路径目录 / 同名五服务 / 同库）：无此开关时**检测到冲突即拒绝且不改动任何现场** |
| `-SkipVerify` | 关 | 跳过第 11 步验收（`/api/health`、`:3000`、`prod_runner.json` 检查） |

**目标机要求**：

- **管理员权限**（安装服务、写 `C:\`、改防火墙、注册计划任务）；
- 目标盘可用空间 **≥ 8 GB**（脚本会实测，不足即 FAIL）；
- 目标路径默认 **`D:\erp_system`（与源机同路径）**——全仓多处绝对路径（`config/nginx-windows.conf`、
  `config/nssm-services.json`）按此写好，换路径由脚本自动改写 nginx conf；
- Windows 10 1809+（需自带 `tar.exe`）。

**分阶段续跑**：安装流程**幂等**——每步先检测是否已完成（基础软件已装/库已存在/服务已注册……）
再决定是否执行；中断后**重跑同一命令即为续跑**，已完成项自动跳过，无需额外开关。

**两种数据来源**：

- 默认（全量镜像）：从包内 `data\erp_system.dump` 用 `pg_restore` 恢复整库，再对恢复后的库跑
  `alembic upgrade head`，把 dump 对应的迁移版本（078）对齐到代码 head（079）；随后做镜像哨兵
  校验（`"user"` 表行数 ≥ 1，否则判恢复不完整）。
- `-Blank`（空库起步）：跳过 dump，直接建库 → `alembic upgrade head` → 种子权限/导航 → 建 `admin`。

**装完**：入口为 `http://<ServerIP>:3000`。请**立即删除源包**，并确认 `%TEMP%` 已无明文解包残留。

---

## 常见问题

- **构建报「工作区不干净」**：先提交或清理改动，便携包只打已提交内容。
- **构建报「deploy\binaries\ 缺 …」**：按 §1.1 放齐 6 个安装包（`-DryRun` 可容忍缺失用于自检）。
- **安装报「已存在，-Force 覆盖」**：目标机已有同路径目录或同名五服务；确认无误后加 `-Force`。
- **安装报「目标盘可用空间不足 8GB」**：清理目标盘后重试。
- **验收 `:3000` 未就绪但 `:5002` 正常**：多为前端 `dist` 或 nginx conf 问题，查 `logs\erp-web.log`。
