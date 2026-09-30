# 运行看门狗（watchdog）

> 优化方案 S2 的落地件。用途：在没有 Prometheus/Grafana 运行体的情况下，
> 用**纯标准库**脚本每 5 分钟主动巡检，异常时走**既有告警通道**通知。
> 相关：`scripts/ops/watchdog.py`、`scripts/ops/watchdog_task.cmd`、
> `scripts/ops/install_watchdog_task.ps1`、`config/README.md`。

## 1. 它检查什么

| key | 检查 | 判定 |
|---|---|---|
| `backend_health` | `GET {WATCHDOG_BACKEND_URL}/api/health` | 非 200 = fail |
| `backend_ready` | `GET {WATCHDOG_BACKEND_URL}/api/health/ready` | 非 200 = fail |
| `arq_worker` | `GET {WATCHDOG_BACKEND_URL}/api/health/arq` | 200=running；503 `not_running` = fail；`probe_unknown` = warn |
| `web_entry` | `GET {WATCHDOG_WEB_URL}`（nginx / vite） | 非 200 = fail |
| `backup_freshness` | `BACKUP_DIR` 下最新**归档**文件（按 `ARCHIVE_SUFFIXES` 白名单，不把 `backup_metrics_*.json` 当备份） | 超过 `WATCHDOG_BACKUP_MAX_AGE_MINUTES`（默认 90）= fail |
| `disk_free` | C: / D: 剩余空间 | 低于 `max(WATCHDOG_MIN_FREE_SPACE_GB, BACKUP_MIN_FREE_SPACE_GB, 20)` = fail |
| `services` | `sc.exe query` 查 NSSM 服务状态 | 仅当 `WATCHDOG_EXPECT_SERVICES=true` 时才检查（dev 形态请保持 false） |

退出码：`0` 全绿；`1` 有 fail/warn；`2` 脚本自身异常。

## 2. 告警怎么发

复用备份子系统既有的两个通道（**不新增依赖、不写数据库**）：

- Webhook：`BACKUP_ALERT_WEBHOOK_ENABLED=true` + `BACKUP_ALERT_WEBHOOK_URL`；
- 邮件：`BACKUP_ALERT_EMAIL_ENABLED=true` + `BACKUP_ALERT_SMTP_*`。

**冷却去重**：同一检查项在 `WATCHDOG_ALERT_COOLDOWN_MINUTES`（默认 30）内只告警一次，
状态记在 `WATCHDOG_STATE_FILE`（默认 `logs/watchdog_state.json`）；恢复后再次异常会重新告警。

当前 `.env` 里两个通道都是 `false`/空 ⇒ 看门狗**只写日志不通知**。
这是有意的：避免误配造成告警风暴。要真收到通知，二选一：

```ini
; .env
BACKUP_ALERT_WEBHOOK_ENABLED=true
BACKUP_ALERT_WEBHOOK_URL=https://<你的群机器人 webhook>
```

## 3. 安装计划任务（**需要管理员权限**）

创建计划任务在非提权会话下会被拒绝（`ERROR: Access is denied.`），
所以这一步必须在**以管理员身份运行**的 PowerShell 里执行：

```powershell
# 默认：SYSTEM 账户，每 5 分钟一次，开机即生效，不需要登录
powershell -ExecutionPolicy Bypass -File D:\erp_system\scripts\ops\install_watchdog_task.ps1

# 若不想用 SYSTEM（例如需要访问映射盘）：仅在当前用户登录时运行
powershell -ExecutionPolicy Bypass -File D:\erp_system\scripts\ops\install_watchdog_task.ps1 -AsCurrentUser

# 卸载
powershell -ExecutionPolicy Bypass -File D:\erp_system\scripts\ops\install_watchdog_task.ps1 -Uninstall
```

等价的手写命令（`.cmd` 包一层是为了避开 `schtasks /TR` 的引号转义）：

```cmd
schtasks.exe /Create /TN erp-watchdog /TR "D:\erp_system\scripts\ops\watchdog_task.cmd" ^
  /SC MINUTE /MO 5 /RU SYSTEM /RL HIGHEST /F
```

## 4. 验证

```powershell
schtasks.exe /Run /TN erp-watchdog          # 立刻跑一次，不必等 5 分钟
Get-Content D:\erp_system\logs\watchdog.log -Tail 20
Get-Content D:\erp_system\logs\watchdog_state.json
```

人工验证告警链路（不动生产配置，临时指向本机假 webhook）：

```powershell
python D:\erp_system\_qa_tmp\s2_webhook_probe.py
```

期望：第一次运行收到 1 次 POST（`task_name=watchdog`、`severity=critical`、
`error` 里含各失败项），第二次运行**不发**（冷却生效）。

验收标准（S2）：`nssm stop erp-arq` 后，15 分钟内收到告警。
**注**：`erp-arq` 在本机当前已处于停止状态（2026-09-30 实测），
即 `arq_worker=fail` 会持续告警——这本身就是它应该报的真实事故。

## 5. 调参（`.env`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `WATCHDOG_BACKEND_URL` | `http://127.0.0.1:5002` | 后端地址 |
| `WATCHDOG_WEB_URL` | `http://127.0.0.1:3000` | Web 入口（nginx 或 vite） |
| `WATCHDOG_BACKUP_DIR` | `BACKUP_DIR` | 备份目录 |
| `WATCHDOG_BACKUP_MAX_AGE_MINUTES` | `90` | 备份新鲜度阈值 |
| `WATCHDOG_MIN_FREE_SPACE_GB` | `20` | 磁盘水位（与 `BACKUP_MIN_FREE_SPACE_GB` 取大） |
| `WATCHDOG_ALERT_COOLDOWN_MINUTES` | `30` | 同类告警冷却 |
| `WATCHDOG_TIMEOUT_SECONDS` | `10` | 单次 HTTP 超时 |
| `WATCHDOG_EXPECT_SERVICES` | `false` | `true` 时额外检查 NSSM 服务；**生产应为 true** |
| `WATCHDOG_SERVICES` | `erp-web,erp-prod,erp-arq,erp-redis,erp-redis-broker` | 要检查的服务名 |
| `WATCHDOG_STATE_FILE` | `logs/watchdog_state.json` | 冷却状态 |
| `WATCHDOG_LOG_FILE` | `logs/watchdog.log` | 巡检日志 |

## 6. 排错

- **中文乱码**：`watchdog_task.cmd` 已设 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1`；
  手工在控制台跑时也要设，否则是控制台代码页问题、不是文件损坏。
- **备份新鲜度一直 fail**：先看 `erp-arq` 是否在跑——ARQ 是备份的唯一调度器；
  再看 `backups/server` 下最新 `.zip.enc` 的时间。
- **`.cmd` 文件不要写中文注释**：cmd.exe 按 OEM 代码页（zh-CN 为 GBK）读取 `.cmd`，
  UTF-8 中文会破坏命令行解析（实测会把 `python` 解析成 `hon`）。
  同理 `.ps1` 在 Windows PowerShell 5.1 下无 BOM 时按 ANSI 解码，也请保持纯 ASCII。
