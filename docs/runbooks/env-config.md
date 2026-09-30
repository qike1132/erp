# 环境变量配置：单一来源、漂移检查与灾备重建

> 结论先写：**运行时只加载项目根的 `.env` 一个文件**。
> `config/.env.production` 是随加密备份包分发的**灾备底稿**，
> 根目录 `.env.production` 是**零消费方的人工参考件**——两者都不参与运行。
> 改配置的唯一正确入口是 `.env`（先改 `.env.example` 模板）。

## 一、五个 env 文件各自是谁

| 文件 | 是否被加载 | 谁在用 | 说明 |
|---|---|---|---|
| `.env` | **是（唯一）** | `fastapi_app/core/config.py:10 load_dotenv(override=False)`；`:279 SettingsConfigDict(env_file=".env")` | 权威配置。`override=False` 意味着**已存在的进程环境变量优先**，`.env` 不覆盖它们 |
| `.env.example` | 否 | 人 + `scripts/ops/check_env_drift.py` | **唯一权威模板**（已入库）。新增配置键必须先加到这里 |
| `config/.env.production` | 否 | 备份系统打包（`services/backup/_constants.py:101` → 归档内 `.env.production`） | 真值灾备底稿；恢复后用它重建 `.env` |
| `.env.production`（根） | 否 | 无人（全仓唯一读取者 `scripts/switch_env.py` 的生产分支**已被禁用**） | 人工参考件，键集合与模板对齐、值为占位/默认 |
| `.env.production.example` | 否 | 人（`prod_audit` 的 l11 会检查它） | 生产参考清单，与 `.env.example` 有重叠 |

`.env` 与两个 `.env.production` 均被 `.gitignore` 忽略（`.gitignore:28`、`:240`），
真实密钥不会入库；只有 `.env.example` 与 `.env.production.example` 是跟踪文件，
**里面只能写占位符**。

> ⚠️ 不要执行 `cp .env.production .env`。`scripts/switch_env.py:26-32` 已经禁用这条路径，
> 原因是根 `.env.production` 的 `DB_PASSWORD` / `SECRET_KEY` 等是占位语法，
> 覆盖后应用会拿着字面占位符启动。生产启动入口只有 `python start.py`。

## 二、漂移检查（S3）

```bash
# 全量（推荐人工巡检）：模板 ↔ .env ↔ 两个 .env.production，含"代码读了但模板没声明"
python scripts/ops/check_env_drift.py            # 退出码 1 = 存在 fail 级漂移
python scripts/ops/check_env_drift.py --verbose  # 列出全部条目（默认每组只显示 12 条）
python scripts/ops/check_env_drift.py --json

# 可移植模式（CI / 无 .env 的机器）：只比"代码引用 ↔ .env.example"
python scripts/ops/check_env_drift.py --ci
```

严重级别：

- **fail**：`.env.production` / `config/.env.production` 缺模板键 —— 灾备件不完整，
  恢复时会静默丢配置；以及"代码读了但模板没声明"（新人无法知道要配什么）。
- **warn**：`.env` 缺模板键（合法，走代码默认值）、模板里有但代码没读、以注释形式存在的键。

该脚本**只读，绝不改写任何 env 文件**。

已接入统一门禁：`scripts/quality_gate.py` 的 `env_drift` 项（以 `--ci` 运行，保证无 `.env` 的 CI 也能跑），
基线在 `scripts/gate_baseline.json`。手动跑门禁：

```bash
python scripts/quality_gate.py --only env_drift
```

## 三、生产启动强校验（S3，fail-fast）

`fastapi_app/core/config.py` 的 `Settings.__init__` 在所有既有生产闸门（SECRET_KEY 长度、
ALLOWED_HOSTS 不得含 `*`、CORS 不得含 `null`）**之后**新增了一组备份/监控校验。
开关：`STRICT_CONFIG_CHECK`（默认 `true`；`false`/`0`/`no`/`off` 关闭）。

**致命（拒绝启动）**

| 条件 | 理由 |
|---|---|
| `BACKUP_ENCRYPTION_ENABLED` 生效（默认 true）但 `BACKUP_ENCRYPTION_PASSWORD` 与 `BACKUP_ENCRYPTION_KEY` 都为空或是 `<...>` 占位 | 否则备份"静默降级为不加密"，加密承诺形同虚设 |
| `BACKUP_DIR` 已存在但不是目录、或目录不可写（真实写探测） | 备份会失败且可能到很晚才发现 |

**告警（仅 logger.warning，不阻断）**：`BACKUP_DIR` 未设置或不存在（`ensure_backup_dir()` 会建）、
缺 `BACKUP_STORAGE_LOCATION` / `BACKUP_FULL_CRON` / `BACKUP_INCREMENTAL_CRON`（有合理默认值）、
`METRICS_BEARER_TOKEN` 为空（`/metrics` 会 503 fail-closed）、
`BACKUP_ALERT_WEBHOOK_ENABLED=true` 但 URL 为空、`BACKUP_ALERT_EMAIL_ENABLED=true` 但 SMTP 主机为空。

> 测试进程（`pytest` 在 `sys.modules` 中）自动豁免这组校验：本仓库多处用例会伪造
> `APP_ENV=production` 去验证**其它**闸门，而 CI 上没有 `.env`。
> 生产进程（prod_runner / uvicorn / ARQ）从不导入 pytest。

排障时如被卡住：在 `.env` 里临时 `STRICT_CONFIG_CHECK=false`，**修好后必须改回 `true`**。

## 四、改配置的标准流程

1. 改 `.env.example`（**先动模板**：加键 + 写清默认值/语义/证据行）。
2. 改 `.env`（真实值；不要提交）。
3. 补齐两个 `.env.production`：`config/.env.production` 填真值（灾备底稿），
   根 `.env.production` 只填占位/默认值（见第五节）。
4. `python scripts/ops/check_env_drift.py` 必须 `[PASS]`（CI 用 `--ci`）。
5. 重启后端进程让新值生效（`load_dotenv` 只在进程启动时读一次）。

## 五、两个 `.env.production` 的写入规则

- `config/.env.production`：**灾备底稿，可以写真实值**（它本来就与 `.env` 同源，
  且被打进加密备份包）。缺键用 `.env` 的当前值补齐。
- 根 `.env.production`：**只写占位/默认值**。
  `scripts/prod_audit/layers/l11_deployment.py:328-353` 专门扫描该文件的硬编码密钥
  （rule_id `L11-HARDCODED-SECRET-001`，命中即 CRITICAL），往里塞真值会产生审计噪声。
- 两者都保留**文件头说明**（"不被加载 / 权威是 .env"），避免后人误用。

## 六、灾备恢复时的配置重建顺序

1. 取得备份加密口令（**不在备份包内**，见 `docs/ops/2026-09-30-credential-rotation-runbook.md`）。
2. 解密最新归档，取出归档内的 `root/.env` 与 `.env.production`（`config/.env.production` 的原件）。
3. 以 `root/.env` 重建目标机的 `.env`；若归档内没有，用 `.env.production` + `.env.example` 补齐。
4. 校验：`python scripts/ops/check_env_drift.py` 应 `[PASS]`；
   启动时不应出现"生产配置告警"或启动失败。
5. 再启动服务（`erp-redis`/`erp-redis-broker` → `erp-prod` → `erp-arq` → `erp-web`）。
6. 恢复后跑一次 `scripts/ops/watchdog.py --no-alert` 确认 6 项检查正常。

## 七、坑（踩过的）

- **`.cmd` 必须纯 ASCII**：cmd.exe 按 OEM 代码页（zh-CN = GBK）解析，UTF-8 中文注释会让
  命令行错位（实测把 `python` 解析成 `hon`）。
- **`.ps1` 在 Windows PowerShell 5.1 下无 BOM 时按 ANSI 解码**：中文注释会变乱码，同样建议纯英文。
- **`alembic.ini` 必须纯 ASCII**：alembic 以 `encoding="locale"` 读 ini，中文 Windows 的 locale 是 GBK，
  写中文注释直接 `UnicodeDecodeError`。
- **改 `.env` 后必须重启进程**：`load_dotenv` 与 `SettingsConfigDict(env_file=".env")` 都只在启动时读一次。
- **进程环境变量优先于 `.env`**（`override=False`）：排查"改了 `.env` 没生效"时先看是否有同名系统环境变量。
