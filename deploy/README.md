# ERP 离线便携包（一键部署）

本目录把「裸机 → 可用生产」压缩成**三步**：在**源机（当前生产）**构建一个口令加密的便携包，
经可信通道拷到**目标机**，用管理员跑安装脚本即可完成从装基础软件到服务验收的全流程。

> 与主 [部署手册第 4 章](../docs/PROJECT_MANUAL.md#4-在新服务器上完整部署生产) 的关系：
> 第 4 章是**逐条人工步骤**（理解与排障参考）；本目录是**自动化一键路径**，二者等价。
> 全流程脚本为 **Windows PowerShell 5.1**（命令写 `powershell.exe`，不是 `pwsh`）。

涉及脚本：

| 脚本 | 角色 | 运行位置 |
|---|---|---|
| [`build_package.ps1`](build_package.ps1) | 构建离线便携包（**只读**） | 源机（生产） |
| [`install_package.ps1`](install_package.ps1) | 装配到目标机（**管理员**） | 目标机 |
| `_lib.ps1` | 共用函数（被上面两者 dot-source） | 随包/随仓 |

> 🖱️ **不想敲命令？双击启动器**：源机双击 [`build.cmd`](build.cmd)；目标机**右键** [`install.cmd`](install.cmd) →
> 「以管理员身份运行」。它们以 `-ExecutionPolicy Bypass` 调对应脚本，并在结束时 **`pause` 停住窗口**
> （不再「闪退」，报错能看清）。要带参数（如 `-DryRun`）就在 cmd 里 `build.cmd -DryRun`，或给快捷方式加参数。
> 注：`.cmd` 内为纯 ASCII（cmd.exe 按 OEM 代码页读取，中文会乱码）；中文输出由 PowerShell 脚本负责。
> 也可双击**中文名** [`一键构建.cmd`](一键构建.cmd) / [`一键安装.cmd`](一键安装.cmd)——它们是上面两个的转发壳。
> 注：本目录 `.ps1` **一律带 UTF-8 BOM**——zh-CN 下 PowerShell 5.1 读「无 BOM 且含中文」的 `.ps1` 会按 GBK 解码而解析失败。

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
| `-PyDir` | 自动探测 | 源机**系统 Python 3.13** 的目录（用于拷运行时并装依赖）。默认探测 `%LOCALAPPDATA%\Programs\Python\Python313` 与 `C:\Python313`，都不在时**硬 FAIL** |
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

**构建前置（缺一即 FAIL；`-DryRun` 仅对 `deploy\binaries\` 缺件宽容，其余项同样强制）**：

- 源机存在：`.env`、`config\jwt\private_v2.pem`、`config\uploads-signing.conf`、`frontend-vite\dist\index.html`；
- 源机有**系统 Python 3.13**（用于拷运行时并装依赖；默认探测 `%LOCALAPPDATA%\Programs\Python\Python313` 与 `C:\Python313`，缺失即 FAIL，可用 `-PyDir` 指定）；
- `pg_dump` / `psql` 可被探测到（`PG_TOOLS_BIN` / PATH / 约定目录，含 PG18）；
- **工作区干净**（`git status --porcelain` 为空）——不打包未提交改动；
- `deploy\binaries\` 已放齐下列 6 个安装包（下一步；`-DryRun` 例外）。

### 1.1 先往 `deploy\binaries\` 放 6 个安装包

构建与安装都依赖本目录里的 6 个官方安装包。文件名需能被脚本的匹配式命中：

| 组件 | 版本 | 期望文件名匹配 | 官方下载来源 |
|---|---|---|---|
| PostgreSQL | **18**（EDB 安装器） | `pg18*` | https://www.enterprisedb.com/downloads/postgres-postgresql-downloads |
| Redis for Windows | **5.0.14.1**（tporadowski 发行版） | `Redis-x64-5.0.14.1*` | https://github.com/tporadowski/redis/releases |
| Nginx for Windows | 官方 Windows zip | `nginx*zip` | https://nginx.org/en/download.html |
| NSSM | **2.24** | `nssm*zip` | https://nssm.cc/download |
| Node.js | **LTS x64 msi** | `node*.msi` | https://nodejs.org |
| VC++ 运行库 | **2015–2022 x64** | `vc_redist*`（**官方下载的是 `.exe`**；exe 或 zip 均可） | https://aka.ms/vs/17/release/vc_redist.x64.exe |

> Python **不在**此清单：运行时（Python 3.13）已随包携带，目标机**无需**单独装 Python。
> Redis 必须是 tporadowski 的 **5.0.14.1**，不要换 7.x/8.x 的第三方 Windows 构建。

---

## 步骤 2 —— 传输（经可信通道）

把上一步的两个产物（`.tar.gz.enc` 及其 `.sha256`）经**可信通道**送到目标机：内网共享/USB 均可，
**不要**放公网。目标机可用 `Get-FileHash -Algorithm SHA256` 手工比对 `.sha256`；
安装脚本在解密前也会**自动比对**与包同目录的 `<包名>.sha256`（缺失仅告警，不一致即 FAIL）。

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
# 在「仓库根」或「解包后的包根」运行 —— 二者都含一个 deploy\ 子目录，
# 且其中 install_package.ps1 与 _lib.ps1 必须**同处一目录**（脚本按 $PSScriptRoot 找 _lib.ps1，
# 所以只看两文件是否并排，与运行时的当前目录无关）。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\install_package.ps1 `
    -Package D:\erp_portable_20261008_1200.tar.gz.enc `
    -ServerIP 192.168.1.97
# -PgSuperPassword 可省略：脚本先取包内 settings\.env 的 PG_SUPER_PASSWORD，取不到再退到交互式隐藏输入。
# 显式传参会进 PowerShell 历史与进程列表（脚本启动时也会就此告警）。
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `-Package` | **必填** | 便携包路径（`.tar.gz.enc`） |
| `-TargetDir` | `D:\erp_system` | 目标部署路径，**默认与源机同路径** |
| `-ServerIP` | `192.168.1.97` | 目标机对外 IP，用于改写 `ALLOWED_HOSTS` / `CORS_ORIGINS` / `WS_ALLOWED_ORIGINS` |
| `-PgSuperPassword` | 包内 `settings\.env` 的 `PG_SUPER_PASSWORD`，再退交互式 | 连接 `postgres` 超级用户建库/建角色用。**可省略**；命令行/包内/交互式三者都拿不到才 FAIL。显式传参会进 PowerShell 历史与进程列表，不推荐 |
| `-AdminPassword` | 交互式提示 | **仅 `-Blank` 时**：新超管 `admin` 口令（Argon2id 哈希后写入；不落命令行/日志）。显式传参会进历史与进程列表 |
| `-EncryptKey` | 交互式提示 | 包口令；省略则交互式隐藏输入（推荐） |
| `-NginxDir` / `-RedisDir` / `-Nssm` | `C:\nginx` / `C:\Redis` / `C:\nssm\nssm.exe` | 基础软件落位，按需覆盖 |
| `-Blank` | 关 | **空库起步**：`alembic upgrade head` → `init_permissions` → `seed_nav` → 建超管 `admin`（项目无内置用户种子，必须建一个否则装完无法登录） |
| `-Force` | 关 | **覆盖**目标机已有部署（同路径目录 / 同名五服务 / 同库）：无此开关时**检测到冲突即拒绝**（不覆盖既有库/服务；基础软件步骤是幂等「已装跳过」，若冲突发生在该步之后，基础软件可能已先装上） |
| `-SkipVerify` | 关 | 跳过第 11 步验收（`:5002`/`:3000` 健康、`prod_runner.json`、ARQ 哨兵键、运行模式探针） |

**目标机要求**：

- **管理员权限**（安装服务、写 `C:\`、改防火墙、注册计划任务）；
- 目标盘可用空间 **≥ 8 GB**（脚本会实测，不足即 FAIL）；
- 目标路径默认 **`D:\erp_system`（与源机同路径）**——全仓多处绝对路径（`config/nginx-windows.conf`、
  `config/nssm-services.json`）按此写好，换路径由脚本自动改写 nginx conf；
- Windows 10 1809+（需自带 `tar.exe`）。

**分阶段续跑**：安装流程**幂等**——每步先检测是否已完成（基础软件已装/库已存在/服务已注册……）
再决定是否执行，中断后重跑同一命令即可从断点续做。
但注意：一旦目标机已存在 `TargetDir`、同名 `erp_system` 库或同名五服务，重跑会在冲突检测处 `Write-Fail`
（不覆盖既有库/服务），**必须显式加 `-Force` 才会覆盖重建**——即「续跑」只在尚未产生这些冲突时成立。

**两种数据来源**：

- 默认（全量镜像）：从包内 `data\erp_system.dump` 用 `pg_restore` 恢复整库，再对恢复后的库跑
  `alembic upgrade head`，把 dump 对应的迁移版本（078）对齐到代码 head（079）；随后做镜像哨兵
  校验（`"user"` 表行数 ≥ 1，否则判恢复不完整）。
- `-Blank`（空库起步）：跳过 dump，直接建库 → `alembic upgrade head` → 种子权限/导航 → 建 `admin`。

**装完**：入口为 `http://<ServerIP>:3000`。请**立即删除源包**，并确认 `%TEMP%` 已无明文解包残留。
验收对 `http://127.0.0.1:3000/api/health`、`logs\prod_runner.json` 的 `ready`/`frontend_ok` 与 ARQ 哨兵键
均**重试约 30 秒后仍失败即 FAIL**（不再把「半可用」当成功）；若 `scripts\diag\runtime_mode_probe.py` 存在，
还会跑一次运行模式探针，判定非 `prod` 同样 FAIL。

---

## 常见问题

- **构建报「工作区不干净」**：先提交或清理改动，便携包只打已提交内容。
- **构建报「deploy\binaries\ 缺 …」**：按 §1.1 放齐 6 个安装包（`-DryRun` 可容忍缺失用于自检）。
- **安装报「已存在，-Force 覆盖」**：目标机已有同路径目录或同名五服务；确认无误后加 `-Force`。
- **安装报「目标盘可用空间不足 8GB」**：清理目标盘后重试。
- **验收 `:3000` 未就绪**：现为**硬 FAIL**（重试 30s 后仍失败）——多为前端 `dist` 或 nginx conf 问题，查 `logs\erp-web.log`。
- **验收「ARQ 哨兵键缺失」**：`erp-arq` 未在线（`arq:queue:health-check @6380` 不新鲜）——查 `logs\erp-arq.log` 与 broker `:6380`；定时备份会静默停摆，务必解决。

## 回滚（安装失败 / 装坏后恢复）

安装器在覆盖前自动生成回滚物料（`install_package.ps1:393-415`，任一产物缺失即
fail-fast 中止安装，物料齐全才继续）：

- `backups\preinstall-<时间戳>\`：五服务注册表导出（.reg）+ `config\` + `.env` 快照
- `-AllowDropDatabase` 删库前另强制 `backups\preinstall-*-db.sql`（pg_dump 基线，
  dump 失败拒绝删库）

恢复顺序（管理员 PowerShell，全部在目标机）：

1. **停服务**：`nssm stop erp-prod erp-arq erp-web`（依赖序：先停依赖方；
   Redis 两服务按需）。
2. **还原文件**：把 `preinstall-*` 快照里的 `config\` 与 `.env` 覆盖回仓库根
   （先备份当前坏状态的这两份，便于事后归因）。
3. **还原服务注册**：导入 `preinstall-*\*.reg`（提权双击或
   `reg import <文件>`）——服务 ImageFile/ AppDirectory 指回旧版本目录。
4. **数据库**：仅当装坏了库结构/数据时：先建空库再
   `psql -U erp_app -d erp_system -v ON_ERROR_STOP=1 -f backups\preinstall-*-db.sql`
   （`install_package.ps1` 生成的是**纯文本 SQL**，不是 `pg_dump -Fc` 自定义格式，
   因此不能用 `pg_restore`；凭据同 .env；**不要**对正常库跑这句）。
5. **拉起**：`nssm start erp-redis-broker erp-redis erp-web erp-arq erp-prod`
   （按启动序），然后核 `logs\prod_runner.json` 的 `ready:true` +
   `frontend_ok:true`（AGENTS §3 健康判据）。

> I2-08（2026-10-24 审计）：本节补齐「物料在、动作没人写过」的缺口。
> 回滚是**恢复到安装前状态**，不是卸载升级版重装；若要重装，走「步骤 3」。
