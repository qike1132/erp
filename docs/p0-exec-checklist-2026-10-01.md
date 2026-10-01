# P0 前四项：可执行改动清单（2026-10-01）

> 对应 `docs/optimization-plan-2026-10-01-round3.md` 的 **P0-1 / P0-3 / P0-4 / P0-7**。
> 本文所有"实测/现状"数据均为 2026-10-01 在本机（`DESKTOP-11111`、`D:\erp_system`、HEAD `546401ec`）现场取证；命令为 PowerShell，写操作需管理员。
> 每项统一五段：**现状 / 改动 / 验证 / 回滚 / 工时**。文末 `§5` 是顺序执行的一页清单。
> 本文**不含任何密钥值**：`.env` 只引用行号与键名，凭据文件只做等值比较、不打印内容。

## 0. 一页速览

| 项 | 改动面 | 风险 | 需重启 | 工时 |
|---|---|---|---|---|
| **P0-7** 门禁旁路 | 1 脚本 + 1 基线 + 1 文档 + 3 行注释 | 极低 | 否 | 0.5 人日 |
| **P0-4** 审批时钟 | 2 行（`shared_models/approval.py:61,:130`） | 低 | 服务重启后生效 | 0.5 |
| **P0-3** 提交失败仪表 | 2 文件 + 1 新单测 | 低 | erp-prod | 0.5 |
| **P0-1** 凭据/ACL | ACL 7 个目标 + 凭据目录搬迁 + 分簇轮换（**无代码改动**） | 中（轮换顺序错会起不来） | 是 | 0.5–1 |

**建议执行顺序**：`P0-7` → `P0-4` → `P0-3`（三项互不冲突：分别只碰 `scripts/`、`shared_models/`、`core/`，可同一窗口做完）→ `P0-1`（唯一要碰 `.env` 并重启服务的项，单独窗口）。

**⚠️ 对 round3 计划 P0-7 的一处更正（重要）**：计划里写"验证：仍为 9 处 FAIL（= 基线，无新增）"，**这个口径实测不成立**。删掉 `independent-transaction` 白名单后，被静默豁免的 3 处会重新可见，FAIL 由 **9 → 12**，因此必须同批把 `scripts/gate_baseline.json:8` 的 `service_commit` 由 `9` 上调为 `12`（一次性、可见、需在提交信息中说明理由）。**切勿用 `python scripts/quality_gate.py --update-baseline`** 达成此事：`scripts/quality_gate.py:189-199` 的 `save_baseline()` 会把**所有**门禁计数按"当前结果"整体重写，静默吸收其它门禁的漂移。详见 §4。

---

## 1. P0-1 凭据与文件权限收口

### 1.1 现状（本轮实测）

**ACL（`icacls` 实测，目标上全部是"继承"ACE，即这些文件/目录没有自己的显式 ACE）**

| 目标 | 需要处理的 ACE | 备注 |
|---|---|---|
| `D:\erp_system\.env` | `NT AUTHORITY\Authenticated Users:(I)(M)`、`BUILTIN\Users:(I)(RX)`、`S-1-4-164373294-948540808:(I)(W,D,DC)` | 六个凭据键都在此文件 |
| `D:\erp_system\.env.production` | 同上 | |
| `D:\erp_system\.env.development` | 同上 | |
| `D:\erp_system\_ops\credentials\` | 同上 + `Everyone:(I)(CI)(DENY)(S,DC)` | 4 个凭据文件 |
| `D:\erp_system\logs\` | 同上 | 生产日志含请求上下文 |
| `D:\erp_system\backups\` | 同上 | 含明文 `.zip` 备份 |
| `D:\erp_system\config\jwt\` | 同上 | `private_v2.pem`(232B)、`public_v2.pem`(182B) = RS256 私钥 |

**不存在（计划里列了、实际无需处理）**：`config\pgbouncer\userlist.txt`（`git ls-files config/pgbouncer` 只剩 `pgbouncer.ini` / `pgbouncer.windows.ini` / `userlist.txt.example` ⇒ S2 泄露已止血，值仍按 runbook §2.2 轮换）、`certs\`、`backups\.backup_encryption.key`。

**服务账户**：`erp-web` / `erp-prod` / `erp-arq` / `erp-redis` / `erp-redis-broker` 全部 `Running` + **`LocalSystem`** ⇒ 收紧后保留 `NT AUTHORITY\SYSTEM:(F)` 已足够，**不需要**给 `NETWORK SERVICE` 写权限。

**`_ops\credentials\` 内容与"是否仍是现役值"（只做等值比较，不打印值）**

| 文件 | 大小 | 与 `.env` 现值的关系 |
|---|---|---|
| `_metrics_bearer_token.txt` | 43B | **等于** `.env:192` 现值 ⇒ **现役凭据的明文副本** |
| `_backup_encryption_password.txt` | 827B | 不含 `.env:117` 现值 ⇒ 旧口令残留（仍须销毁） |
| `.env.bak-20260911` | 4798B | `.env` 历史副本（含历史密钥） |
| `.env.bak-20260927-085022` | 7664B | `.env` 历史副本（含历史密钥） |

**`.env` 键行号（不含值）**：`DB_PASSWORD:10`(32 字符)、`REDIS_PASSWORD:30`(32)、`SECRET_KEY:48`(64)、`PG_SUPER_PASSWORD:50`(32)、`ALLOWED_HOSTS:57`、`CORS_ORIGINS:68`、`BACKUP_ENCRYPTION_PASSWORD:117`(43)、`METRICS_BEARER_TOKEN:192`(43)。

**无需改 `.gitignore`**：`D:\erp_system\.gitignore:30-35` 覆盖 `.env*`，`:38-43` 覆盖 `config/jwt/*.pem` 与 `backups/*.key`，`:337 /_ops/`（注释在 `:334`）覆盖凭据目录。

**代码零消费者**：全仓 grep `_ops/credentials` 只命中 `AGENTS.md:29`、`AGENTS.md:70` 与 `docs/**`；**没有任何 `.py` 读取它** ⇒ 第 ④ 步搬迁不需要改代码。

**已有手册（不要重复劳动）**：`docs/ops/2026-09-30-credential-rotation-runbook.md`（222 行）已覆盖 S1 `PG_SUPER_PASSWORD`、S2 pgbouncer 三账号、S3 `BACKUP_ENCRYPTION_PASSWORD`，含前置快照（§1.1）、影响面确认（§1.2）、轮换后自查清单（§3.1）。本清单**只补它没覆盖的部分**：ACL 收紧、凭据目录搬迁、以及另外 4 个应用键（`METRICS_BEARER_TOKEN`/`DB_PASSWORD`/`REDIS_PASSWORD`/`SECRET_KEY`）的轮换顺序与验证。

### 1.2 附带发现（需你确认，不属于原 P0-1 范围）

```
D:\erp_system                     ->  Mandatory Label\Low Mandatory Level:(OI)(CI)(NW)
D:\                               ->  (no label)
D:\ww                             ->  (no label)
D:\ww\resources                   ->  (no label)
C:\Users\Administrator\Documents ->  (no label)
```

即**只有本仓库树**被打上"低完整性"标签。含义要说清，别误判：`NW`（No-Write-Up）约束的是"完整性**低于**该对象"的主体，所以它**不是写保护** —— Administrators 与 `LocalSystem` 服务（Medium/System 及以上）照常可写；真正的副作用是**低完整性进程（沙箱化浏览器等）也能写入仓库**，且非标准主体 `S-1-4-164373294-948540808` 对整棵树持有 `(W,D,DC)`。来源很可能是某次沙箱/隔离实验的遗留（`D:\` 与其它目录均无此标签）。

- 清理命令（可选，低优先级，**执行前先确认来源**）：`icacls D:\erp_system /setintegritylevel Medium`；顺带审掉该主体：`icacls D:\erp_system /remove:g "*S-1-4-164373294-948540808"`。
- 风险：若某工具（沙箱/隔离器）依赖此配置，清理会破坏它的隔离语义 —— 所以先确认，再清。

### 1.3 改动（按序 7 步）

**① 备份 ACL（可回滚的基础）**

```powershell
New-Item -ItemType Directory -Force D:\erp_acl_backup | Out-Null
icacls D:\erp_system /save D:\erp_acl_backup\erp_system.acl /T
```

`/save` 只写 ACL 描述（不含文件内容、不含密钥），落盘在仓库外。

**② 三个 `.env`：断继承、只留三个主体**

```powershell
foreach ($f in 'D:\erp_system\.env','D:\erp_system\.env.production','D:\erp_system\.env.development') {
  icacls $f /inheritance:r /grant:r "BUILTIN\Administrators:F" "NT AUTHORITY\SYSTEM:F" "DESKTOP-11111\Administrator:F"
}
```

说明：`/inheritance:r` 删除**全部**继承 ACE（含 `Authenticated Users`/`Users`/`Everyone-DENY`/`S-1-4-*`），`/grant:r` 用列出的 ACE 替换显式 ACE。**不给 `NETWORK SERVICE`**（服务是 `LocalSystem`）；将来若真的改用 NETWORK SERVICE 托管，再补 `"NT AUTHORITY\NETWORK SERVICE:M"`。

**③ 四个目录：同理，但加 `(OI)(CI)` 让新文件继续继承**

```powershell
foreach ($d in 'D:\erp_system\logs','D:\erp_system\backups','D:\erp_system\config\jwt','D:\erp_system\_ops\credentials') {
  icacls $d /inheritance:r /grant:r "BUILTIN\Administrators:(OI)(CI)F" "NT AUTHORITY\SYSTEM:(OI)(CI)F" "DESKTOP-11111\Administrator:(OI)(CI)F"
}
```

⚠️ `logs`/`backups` 是服务运行期高频写入目录：本步做完**立即**执行 §5 的验证 2（服务仍在 Running 且仍在写日志），不要把验证推到轮换之后。

**④ `_ops/credentials` 整体移出工作区**

```powershell
New-Item -ItemType Directory -Force D:\erp_secrets | Out-Null
Move-Item D:\erp_system\_ops\credentials\* D:\erp_secrets\ -Force
Remove-Item D:\erp_system\_ops\credentials -Recurse -Force
icacls D:\erp_secrets /inheritance:r /grant:r "BUILTIN\Administrators:(OI)(CI)F" "DESKTOP-11111\Administrator:(OI)(CI)F"
```

- **代码改动：无**（见 §1.1"代码零消费者"）。
- **文档改动（需你确认，属流程规范变更）**：`AGENTS.md:29`（`_ops/credentials/` 凭据存放处）与 `AGENTS.md:70`（不要把 `config/pgbouncer/userlist.txt` 或 `_ops/credentials/**` 加回版本库）应指向新位置 `D:\erp_secrets\`。
- 提醒：移出仓库 **≠** 不再敏感。`D:\erp_secrets` 仍是本机明文凭据存放处，且其中 `_metrics_bearer_token.txt` 是**现役**值；真正的收尾在第 ⑤ 步之后（更新或销毁）。

**⑤ 轮换：分簇、每簇一次、改完立刻验证**

| 序 | 键（`.env` 行号，长度） | 消费者（grep 实测） | 影响面 | 需重启 |
|---|---|---|---|---|
| 1 | `METRICS_BEARER_TOKEN`（`:192`，43） | `fastapi_app/core/health.py:208`、`fastapi_app/core/config.py:260-262` | `/metrics` 抓取凭据；未配则 503（fail-closed） | erp-prod |
| 2 | `DB_PASSWORD`（`:10`，32） | asyncpg 引擎（`fastapi_app/core/config.py` 的 DB_\* 构造）；psql 登录 `erp_app` | 应用连库口令 | erp-prod、erp-arq |
| 3 | `REDIS_PASSWORD`（`:30`，32） | `fastapi_app/main.py:102`、`fastapi_app/core/arq_app.py:37`、`fastapi_app/core/redis_client.py:44-47`、`fastapi_app/core/purchase_cache.py:118-120` | 缓存/队列；须与 redis 实例 `requirepass` 同步 | erp-redis → erp-prod、erp-arq、erp-redis-broker |
| 4 | `SECRET_KEY`（`:48`，64） | JWT 签发/校验（`fastapi_app/core/config.py:394-430` 生产要求 ≥32） | **所有在位会话立即失效**，全员重新登录 | erp-prod |
| 5 | `BACKUP_ENCRYPTION_PASSWORD`（`:117`，43） | `fastapi_app/services/backup/crypto.py:39-66`（唯一读取点） | 改后**旧 `.enc` 永久不可读** | erp-prod、erp-arq |

- 第 5 项必须在 P0-2（恢复演练）之后，或明确接受"历史加密备份弃置"（runbook §2.3 记录你此前已接受）。
- 每一簇的固定流程：改权威位置（PostgreSQL / redis）→ 改 `.env` 对应**一行**（手工编辑，别脚本批量写）→ 重启相关服务 → 跑本簇验证 → 再动下一簇。
- `PG_SUPER_PASSWORD`（`:50`，32）不在应用链路（死键，应用用 `DB_USER=erp_app`），按 runbook §2.1 在库侧 `ALTER ROLE postgres WITH PASSWORD ...` 轮换。
- `_metrics_bearer_token.txt` 必须在第 1 簇验证通过后**同步更新**或销毁（它是现役值的副本）。

**⑥ 给死键加注**（runbook §2.1 建议）：`.env:50` 等非应用读取的键加行尾注释 `# 非应用读取，仅运维手工使用`，避免下一个人误以为应用依赖。

**⑦ 销毁临时快照**：`.env.bak-20260911`、`.env.bak-20260927-085022`、`_backup_encryption_password.txt`（旧值），以及 runbook §1.1 的 `%TEMP%` 快照（按 runbook §3.4）。建议先移到 `D:\erp_secrets\retired\` 保留一个观察期再删除，避免"想回滚时无路可走"。

### 1.4 验证

```powershell
# 1) 目标上不再有宽主体（期望：无输出）
icacls D:\erp_system\.env | Select-String 'Authenticated Users|BUILTIN\\Users|S-1-4-'
# 2) 服务都活着 + 监督器就绪
Get-Service erp-prod,erp-arq,erp-redis,erp-redis-broker,erp-web | Format-Table Name,Status
(Get-Content D:\erp_system\logs\prod_runner.json -Raw | ConvertFrom-Json).ready        # 期望 True
# 3) 日志目录仍可写（服务在写即为证）
Get-ChildItem D:\erp_system\logs -Filter *.log | Sort-Object LastWriteTime -Descending | Select-Object -First 3 Name,LastWriteTime
# 4) 指标端点可用（新 token；直连后端 5002，避开 nginx 的 allow 127.0.0.1）
curl.exe -s -o NUL -w "%{http_code}" -H "Authorization: Bearer <新 METRICS_BEARER_TOKEN>" http://127.0.0.1:5002/metrics
# 5) 非管理员读被拒（在非管理员会话中执行）
#    type D:\erp_system\.env        → 期望 "拒绝访问"
```

验收口径：1) 无宽主体；2) 五服务 Running 且 `ready:true`；3) 日志仍在更新；4) HTTP 200；5) 非管理员读取被拒。

### 1.5 回滚

```powershell
icacls D:\erp_system /restore D:\erp_acl_backup\erp_system.acl
Move-Item D:\erp_secrets\* D:\erp_system\_ops\credentials\ -Force      # ④ 的反向操作
```

`.env` 回滚用 runbook §1.1 的快照（或 `.env.bak-20260927-085022`）。**回滚 `.env` 前先确认库/redis 侧也已回退**，只回 `.env` 会制造"配置与权威口令不一致"的更难排查的故障。

工时：ACL + 搬迁 ≈ 0.3 人日；轮换 ≈ 0.3–0.7 人日（取决于是否存在其它机器/脚本复用同一口令 —— 见 runbook §1.2 的人工确认项）。

---

## 2. P0-3 给"响应已发出、提交失败"装仪表

### 2.1 现状（实测）

- `fastapi_app/core/database.py:203 async def get_async_db()` —— **无 `request` 参数**；`:226-240` 的 commit 收尾**只有** `logger.error` + `rollback` + `raise`，没有任何计数器 ⇒ 无法告警、无法统计"静默丢失"。
- 该依赖被 **151 处** `Depends(get_async_db)` 使用，其中 **3 处是无参直调**，加"必填参数"会直接打断它们：
  - `fastapi_app/core/database.py:345 async for session in get_async_db():`（`get_async_read_db` 未配副本时的回退路径）
  - `fastapi_app/core/database.py:359 async for primary_session in get_async_db():`（副本不可用时的降级路径）
  - `fastapi_app/main.py:127 async for db in get_async_db():`（启动预热库存缓存）
  ⇒ 新参数**必须带默认值**：`request: Request | None = None`。
- `request_id` 来源：`fastapi_app/core/middleware.py:107-110` 的 `request_id_middleware` 写入 `request.state.request_id`（`:110`）；`fastapi_app/core/audit_middleware.py:99-100` 另有兜底生成。
- 指标基建：`fastapi_app/core/metrics.py:39 _get_or_create_counter(name, doc, labelnames=None)`（防热重载 `Duplicated timeseries`）；现有指标名**不带** `erp_` 前缀（`:83 http_requests_total`、`:102 domain_event_publish_failures_total`）；未装 `prometheus_client` 时降级为 `_NoOpMetric`（`:18-33`），所以调用侧无需判空。
- 函数长度门禁阈值 `max_function_length = 80`（`D:\erp_system\pyproject.toml:15`），当前 `get_async_db` 为 `database.py:203-240`（38 行）⇒ 加 ~10 行仍安全。

### 2.2 改动

**改动 1 — `fastapi_app/core/metrics.py`：在 `DB_POOL_WAITING`（`:140-144`）之后新增**

```python
DB_COMMIT_FAILURES = _get_or_create_counter(
    'db_commit_failures_total',
    '事务提交失败次数（响应已发送但数据未落库）',
    ['path'],
)
```

**改动 2 — `fastapi_app/core/database.py`：加可选 `request`**

```python
# 顶部 import 区（当前 :16 起是 sqlalchemy，:21 是 config）
from fastapi import Request          # 新增

# :203
async def get_async_db(request: Request | None = None):
    """（原 docstring 原样保留）"""
```

**改动 3 — 同文件 `:228-240` 的 commit 收尾段整体替换**

```python
        try:
            await session.commit()
        except (RuntimeError, OSError, ValueError, SQLAlchemyError):
            try:
                from fastapi_app.core.metrics import DB_COMMIT_FAILURES
                DB_COMMIT_FAILURES.labels(path=request.url.path).inc()
            except Exception:  # 指标写入失败绝不能影响主流程（此处已在异常路径上）
                logger.debug("提交失败计数写入失败", exc_info=True)
            logger.error(
                "事务提交失败：响应已发送但数据未落库（静默丢失风险）"
                " request_id=%s path=%s db=%s",
                getattr(getattr(request, 'state', None), 'request_id', None),
                request.url.path if request is not None else '<background>',
                os.getenv('DB_NAME', 'erp_system'),
                exc_info=True,
            )
            try:
                await session.rollback()
            except (RuntimeError, OSError, ValueError, SQLAlchemyError):
                logger.warning("Session rollback failed (may be broken after psql restore)", exc_info=True)
            raise
```

落地注意：

1. **不要写 `settings.DB_NAME`** —— `fastapi_app/core/config.py` 里 `DB_NAME` 只是 `:31`/`:42` 两个函数内的局部变量（`db_name = os.getenv("DB_NAME", "erp_system")`），`Settings`（`:286`，实例在 `:472`）并没有该字段（全仓 grep `settings.DB_\*` 零命中）。用 `os.getenv('DB_NAME', 'erp_system')`，`database.py:12` 已 import `os`。
2. label 用 `request.url.path`（路由模板未展开）⇒ 约 373 个路由 ⇒ 基数有限，可接受；**不要**用带 query 的完整 URL（基数无界）。
3. `request` 为 `None` 的 3 处（`database.py:345`/`:359`、`main.py:127`）会走 `'<background>'` 分支，不报错。
4. 待定（本项不做，建议登记为 P1）：`fastapi_app/core/database.py:246` 的 `get_async_db_context()`（ARQ/后台任务专用）是否有对称的提交失败路径与日志 —— 需先读 `:246-300` 确认，再决定是否复用同一计数器。

### 2.3 验证

**新增单测 `fastapi_app/tests/test_db_commit_failure_metric.py`**

```python
"""P0-3：commit 失败必须计数 + 仍向上抛。"""
from types import SimpleNamespace

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.exc import SQLAlchemyError

import fastapi_app.core.database as dbmod

PROBE_PATH = '/api/v1/p0-3-probe'


class _FailingSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def rollback(self):
        return None

    async def commit(self):
        raise SQLAlchemyError('boom')


@pytest.mark.asyncio
async def test_commit_failure_counted_and_reraised(monkeypatch):
    async def _noop():
        return None

    monkeypatch.setattr(dbmod, 'ensure_engine_for_current_loop', _noop)
    monkeypatch.setattr(dbmod, '_AsyncSessionLocal', lambda: _FailingSession())
    request = SimpleNamespace(
        url=SimpleNamespace(path=PROBE_PATH),
        state=SimpleNamespace(request_id='t-1'),
    )

    before = REGISTRY.get_sample_value('db_commit_failures_total', {'path': PROBE_PATH}) or 0
    agen = dbmod.get_async_db(request)
    await agen.__anext__()                       # 进入依赖体（yield 之前）
    with pytest.raises(SQLAlchemyError):
        await agen.__anext__()                   # 收尾 → commit 抛错
    after = REGISTRY.get_sample_value('db_commit_failures_total', {'path': PROBE_PATH})
    assert after == before + 1
```

（`_AsyncSessionLocal` 是 `database.py` 模块级全局，由 `init_async_engine()` 赋值 ⇒ 可 monkeypatch。）

```powershell
# 单测
python -m pytest fastapi_app/tests/test_db_commit_failure_metric.py -q
# 相关回归
python -m pytest fastapi_app/tests -k "database or commit or metrics" -q
# 门禁（新增 ~10 行，函数长度闸 80 行仍安全；跑全量防漂移）
python scripts/quality_gate.py
# 重启后在真实 /metrics 上确认指标名存在（直连 5002）
curl.exe -s -H "Authorization: Bearer <token>" http://127.0.0.1:5002/metrics | Select-String db_commit_failures_total
nssm restart erp-prod
(Get-Content D:\erp_system\logs\prod_runner.json -Raw | ConvertFrom-Json).ready     # 期望 True
```

### 2.4 回滚

```powershell
git checkout -- fastapi_app/core/database.py fastapi_app/core/metrics.py
Remove-Item fastapi_app\tests\test_db_commit_failure_metric.py
```

纯新增；回退即删（指标名消失不影响任何既有抓取）。

---

## 3. P0-4 统一审批域时钟

### 3.1 现状（实测）

- `fastapi_app/shared_models/approval.py:21-22`：`def _utcnow() -> datetime: return datetime.now(UTC).replace(tzinfo=None)`，注释写明"naive UTC: DB 列类型为 TIMESTAMP WITHOUT TIME ZONE"。
- 同一张表两套时钟：
  - `:56` `request_time = mapped_column(DateTime, default=_utcnow, index=True, ...)` ← UTC
  - `:61` `updated_at = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, ...)` ← **本地时间**
  - `:128` `action_time = mapped_column(DateTime, default=_utcnow, index=True, ...)` ← UTC
  - `:130` `updated_at = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, ...)` ← **本地时间**
- 全 `fastapi_app/shared_models/` 只有这 **2 处** `default=datetime.now`（grep 证实）⇒ 修复面就是这两行，不会漏。
- 影响面很小但语义污染：`ApprovalRequest.to_dict()`（`approval.py:85-103`）**不输出 `updated_at`**，所以前端看不到它；受影响的是数据库/运维/审计读取（同一操作的两个时间戳差 8 小时，无法作为证据链）。

### 3.2 改动（2 行）

`fastapi_app/shared_models/approval.py:61` 与 `:130` 统一为：

```python
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow, comment='更新时间')
```

- `datetime` 导入（`:6 from datetime import UTC, datetime`）**不用动**：`_utcnow` 与类型注解仍需要它。
- ⚠️ 别再引入 `datetime.now(UTC)`（**带 tzinfo**）作为列默认值：列是 `TIMESTAMP WITHOUT TIME ZONE`，带时区的值写库会出问题；`_utcnow()` 已经做了 `.replace(tzinfo=None)`。
- 落地前顺手确认无外部读取点：`grep -rn "updated_at" fastapi_app/api/v1/endpoints/approval.py`（`to_dict` 不输出该列，预期无命中）。

### 3.3 验证

**新增 `fastapi_app/tests/test_approval_clock_consistency.py`**（要点）

```python
# 用仓库现有 test client / session fixture 建一条 ApprovalRequest + 一条 ApprovalLog，
# 提交后断言同一操作的两个时间戳同源：
assert abs((row.updated_at - row.request_time).total_seconds()) < 60
assert abs((log.updated_at - log.action_time).total_seconds()) < 60
```

```powershell
python -m pytest fastapi_app/tests -k "approval" -q
```

**历史数据核对（证明修复前后差异、且不谎报历史已修）**

```sql
-- 修复前跑：应看到大量 8 小时偏差的历史行
SELECT count(*) FROM approval_request
 WHERE updated_at IS NOT NULL AND abs(extract(epoch FROM (updated_at - request_time))) > 14400;
-- 修复后：只统计"修复时刻之后"的行，应全部落回 < 60s
SELECT count(*) FROM approval_request
 WHERE updated_at > now() - interval '1 day'
   AND abs(extract(epoch FROM (updated_at - request_time))) > 60;
```

### 3.4 回滚

还原 `:61`、`:130` 两行（`git checkout -- fastapi_app/shared_models/approval.py`）。

**边界（必须写进变更说明）**：本项只消除"同表两套时钟"；**历史行仍是旧语义（naive 本地时间）**，不改写历史数据。完整修复（naive → `timestamptz` + 迁移 + 展示层时区约定）属 **P2-9**。

---

## 4. P0-7 封堵事务门禁的注释旁路

### 4.1 现状（实测，**含对 round3 计划的一处更正**）

- `D:\erp_system\scripts\check_service_commit.py:32-39` 的 `ALLOWED_PATTERNS` 共 6 条：
  `:33 nested\.commit\(`、`:34 short_session\.commit\(`、`:35 _session\.commit\(`、`:36 #.*commit\(`、`:37 ^\s*#`、`:38 #\s*independent[-_]transaction`。
- `:38` 就是"注释即豁免"；`:36` 同样是宽规则（行内任何 `#` 之后出现 `commit(` 即跳过）。
- **模拟重放（用当前脚本规则逐行复算全 `fastapi_app/services/**`）的结论**：

  | 规则集 | FAIL 数 | 被静默豁免的行 |
  |---|---|---|
  | 现状（6 条） | **9** | 3 处（仅被 `:38` 命中） |
  | 只删 `:36` | 9 | 同上（`:36` 当前**零命中**，是惰性漏洞） |
  | 只删 `:38` | **12** | 0（3 处重新可见） |
  | 两条都删 | **12** | 0 |

  被静默豁免的 3 处：`fastapi_app/services/backup/cleanup/service.py:599`、`fastapi_app/services/backup/metrics/alert_service.py:222`、`fastapi_app/services/backup/orchestration/policy_service.py:544`，原始行均为：
  `await db.commit()  # independent-transaction; manual-tx: try/except 内显式事务控制`。
- `docs/TRANSACTION_BOUNDARY_GUIDE.md:40-48`（§2.2）规定**官方例外标注是 `# manual-tx: <为什么必须现在提交>`**，并在 `:48` 明确写"脚本**不会**因为该注释而跳过（这是有意的——例外应当被持续看见）" ⇒ `:38` 与指南**直接冲突**，且 3 处豁免行**本来就已经带了 `manual-tx:` 标注**，它们不需要"新机制"，只需要**重新可见**。
- 门禁读数链路：`scripts/quality_gate.py:123 COUNT_RE = re.compile(r"\[FAIL\][^\d]*(\d+)\s*(?:处|个)")`，`:168-173` 匹配不到计数时"含 `[PASS]` 记 0，否则视为异常（保守失败）" ⇒ **改脚本的告警文案会直接改门禁读数**，本项**不要动文案格式**。
- 基线：`D:\erp_system\scripts\gate_baseline.json:8 "service_commit": 9`。
- `docs/TRANSACTION_BOUNDARY_GUIDE.md:72-85`（§4"当前已接受的存量（基线 9 处）"）**行号已漂移**，且**漏列**上述 3 处：

  | 指南写法 | 实际行号 | 状态 |
  |---|---|---|
  | `services/auth_service.py:63,72` | `auth_service.py:63,72` | 正确 |
  | `services/backup/incremental.py:385` | `incremental.py:397` | 漂移 |
  | `services/backup/restore.py:265` | `restore.py:267` | 漂移 |
  | `services/backup/strategies.py:133` | `strategies.py:133` | 正确 |
  | `services/backup/orchestration/recovery_test_service.py:572` | `recovery_test_service.py:573` | 漂移 |
  | `services/backup/records.py:594,608,624` | `records.py:757,769,788` | 漂移 |
  | — | `backup/cleanup/service.py:599`、`metrics/alert_service.py:222`、`orchestration/policy_service.py:544` | **未登记** |

- 全仓 `grep independent[-_]transaction` 仅命中那 3 行代码（无其它引用）。

### 4.2 改动

**改动 1 — `scripts/check_service_commit.py`：删掉两条宽规则**

```python
# 允许的 commit 模式（忽略）
ALLOWED_PATTERNS = [
    r"nested\.commit\(",         # 嵌套事务 / savepoint
    r"short_session\.commit\(",  # 独立短 session
    r"_session\.commit\(",       # 下划线开头的 session
    r"^\s*#",                     # 整行注释（不含代码）
]
```

（即删除 `:36 #.*commit\(` 与 `:38 #\s*independent[-_]transaction`。`:38` 是本次修复的目标；`:36` 当前零命中但留着就是下一颗地雷，一并删。）

**改动 2 — 加"防退化"自测（这是让修复长期成立的关键）**

在脚本内新增（仅 `--self-test` 时运行，`quality_gate` 的常规调用不受影响）：

```python
SELF_TEST_CASES = [
    # (代码行, 是否应被判为违规)
    ("await db.commit()  # independent-transaction", True),   # 注释不能当豁免
    ("await db.commit()  # manual-tx: 理由", True),            # §2.2：标注≠免检
    ("await db.commit()  # 见 add_commit() 说明", False),      # 注释里出现 commit( 不误伤
    ("await row_nested.commit()  # savepoint", False),
    ("# await db.commit() 整行注释示例", False),
]
```

断言 `is_allowed(line) == (not should_flag)`；`--self-test` 时不匹配则 exit 1。**注意**：自测输出**不得**包含形如 `[FAIL] … N 处` 的字符串（`quality_gate.py:123` 的正则会误读），用 `[SELFTEST]` 前缀。

**改动 3 — 三处注释按 §2.2 写清"为什么必须现在提交"**

```python
# backup/cleanup/service.py:599
await db.commit()  # manual-tx: 清理动作按批独立提交，避免长事务跨批持锁；单批失败不阻断其余批
# backup/metrics/alert_service.py:222
await db.commit()  # manual-tx: 告警需在触发时刻立即落库，若并入调用方事务会随失败一起回滚
# backup/orchestration/policy_service.py:544
await db.commit()  # manual-tx: 策略保存需在后续编排步骤前对其它会话可见
```

（即去掉 `independent-transaction;` 前缀，保留并具体化 `manual-tx:` 理由。）

**改动 4 — 基线一次性上调 9 → 12（可见的、需说明的动作）**

`scripts/gate_baseline.json:8`：`"service_commit": 9` → `"service_commit": 12`。

- 理由写在提交信息里：**"门禁白名单收窄：原本被 `# independent-transaction` 静默豁免的 3 处重新可见，基线由 9 上调为 12（编制不变，仅可见性纠正）"**。
- **不要**运行 `python scripts/quality_gate.py --update-baseline`：`scripts/quality_gate.py:189-199` 会按当前结果重写 **全部** 计数（`n_plus_one`/`bare_except`/`function_length`/`vue_component_length`/`bom`/`alembic_heads`/`env_drift`），等于把其它门禁的漂移一并静默冻结。
- 棘轮语义（`gate_baseline.json:2`"数字只允许下调"、"只允许减少，不允许增加"）在这里是**例外**：本次上调是"把隐藏违规显式化"，必须留在提交历史与评审记录里，后续只能往下调。

**改动 5 — 同步修正 `docs/TRANSACTION_BOUNDARY_GUIDE.md` §4**

把 `:72` 标题改为"§4 当前已接受的存量（基线 12 处）"，逐行改用 §4.1 表中的**实**测行号，并补上 3 条新登记（理由取改动 3 的文案）。

### 4.3 验证

```powershell
# 1) 正常模式：期望 [FAIL] 在 service 层发现 12 处非法 commit()，且输出里【不出现】那 3 行
python scripts/check_service_commit.py
# 2) 自测：注释不再能当豁免
python scripts/check_service_commit.py --self-test        # 期望 exit 0 + [SELFTEST] ok
# 3) 反向测试：临时在 auth_service.py 某行加 "# tx-exempt: 尝试绕过" 之类注释，重跑 1)
#    期望该行【仍然出现在 FAIL 列表】（注释不再影响判定）→ 测试后撤销
# 4) 门禁整体（基线已是 12）
python scripts/quality_gate.py --only service_commit       # 期望 [PASS]/计数相等
python scripts/quality_gate.py                              # 全量，确认其它门禁无漂移
```

### 4.4 回滚

```powershell
git checkout -- scripts/check_service_commit.py scripts/gate_baseline.json docs/TRANSACTION_BOUNDARY_GUIDE.md
git checkout -- fastapi_app/services/backup/cleanup/service.py fastapi_app/services/backup/metrics/alert_service.py fastapi_app/services/backup/orchestration/policy_service.py
```

### 4.5 附注（本项不做）

AST 化（把"逐行正则"换成 `ast.parse` + 遍历 `Call` 节点判定，避免字符串/注释/多行调用误判）属计划 P0-7 的"中期"项，建议放 P1；本项只做"白名单收窄 + 防退化自测 + 基线可见化 + 文档对齐"。

---

## 5. 一页执行清单（建议顺序）

**窗口 A（不停服，代码 + 门禁）**

- [ ] P0-7 ① 删 `scripts/check_service_commit.py:36`、`:38` 两条宽规则
- [ ] P0-7 ② 加 `--self-test` 与 5 条断言（输出用 `[SELFTEST]` 前缀）
- [ ] P0-7 ③ 三处注释改为具体 `manual-tx:` 理由
- [ ] P0-7 ④ `scripts/gate_baseline.json:8` 9 → 12（提交信息说明）
- [ ] P0-7 ⑤ 修 `docs/TRANSACTION_BOUNDARY_GUIDE.md` §4（基线 12 + 实测行号 + 补 3 条）
- [ ] P0-7 ⑥ 验证：`python scripts/check_service_commit.py` = 12 处且无那 3 行；`--self-test` 通过；`python scripts/quality_gate.py` 全绿
- [ ] P0-4 ① `fastapi_app/shared_models/approval.py:61,:130` 改 `default=_utcnow, onupdate=_utcnow`
- [ ] P0-4 ② 新增 `fastapi_app/tests/test_approval_clock_consistency.py`；`python -m pytest fastapi_app/tests -k approval -q`
- [ ] P0-3 ① `fastapi_app/core/metrics.py` 加 `DB_COMMIT_FAILURES`（`db_commit_failures_total`，label `path`）
- [ ] P0-3 ② `fastapi_app/core/database.py:203` 加 `request: Request | None = None` + `from fastapi import Request`
- [ ] P0-3 ③ `:228-240` 加计数 + `request_id`/`path`/`DB_NAME` 结构化日志（用 `os.getenv('DB_NAME', 'erp_system')`）
- [ ] P0-3 ④ 新增 `fastapi_app/tests/test_db_commit_failure_metric.py`；`python -m pytest fastapi_app/tests -k "database or commit or metrics" -q`
- [ ] A-验证：`python scripts/quality_gate.py`、`nssm restart erp-prod` → `prod_runner.json ready:true`、`/metrics` 里能看到 `db_commit_failures_total`

**窗口 B（需停服/重启，凭据 + ACL）**

- [ ] P0-1 ① `icacls /save` 备份 ACL 到 `D:\erp_acl_backup\erp_system.acl`
- [ ] P0-1 ② 三个 `.env` 断继承 + 只留 Administrators/SYSTEM/Administrator
- [ ] P0-1 ③ `logs`/`backups`/`config\jwt`/`_ops\credentials` 四个目录同理（带 `(OI)(CI)`）→ 立即验证服务仍在写日志
- [ ] P0-1 ④ `_ops/credentials` → `D:\erp_secrets\`（代码零改动；`AGENTS.md:29,:70` 指向新位置待你确认）
- [ ] P0-1 ⑤ 按 §1.3 表顺序逐簇轮换：`METRICS_BEARER_TOKEN` → `DB_PASSWORD` → `REDIS_PASSWORD` → `SECRET_KEY` → `BACKUP_ENCRYPTION_PASSWORD`（最后，且 P0-2 演练之后）；`PG_SUPER_PASSWORD` 按 runbook §2.1
- [ ] P0-1 ⑥ 死键加注（`.env:50` 等）
- [ ] P0-1 ⑦ 销毁/归档旧凭据副本与快照（`.env.bak-*`、`_backup_encryption_password.txt`、`%TEMP%` 快照）
- [ ] B-验证：`icacls` 无宽主体；五服务 Running；`ready:true`；`/metrics` 200；非管理员读 `.env` 被拒

**收尾**

- [ ] 更新 `docs/optimization-plan-2026-10-01-round3.md` `§7` 进度表（P0-1/P0-3/P0-4/P0-7 状态与日期），并落一次提交说明"依据 `docs/p0-exec-checklist-2026-10-01.md` 执行"
- [ ] 顺带把计划 P0-7 的"验证：仍为 9 处"那句更正为 12（本文 §0 已给出正确口径）
