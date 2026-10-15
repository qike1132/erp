# 滨发协同系统（binfa-erp）上线前问题优化方案

> 配套文档：[ERP_上线前代码质量审查报告.md](./ERP_上线前代码质量审查报告.md)
> 编制日期：2026-09-28 ｜ 基线：`main` @ `9fe2d0a2`（工作区含未提交的 multi-SKU 重构）
> 所有"定位"均已实地核对；所有代码片段均按当前文件真实内容书写，可直接套用。

---

## 0. 执行原则与决策点

### 0.1 三条执行原则

1. **止血优先**：能在 30 分钟内做完、且不需要回滚预案的，先做（§1）。
2. **高风险改动单独开分支 + 单独验证**：涉及 git 历史重写、迁移语义、鉴权语义的，**不与止血项混在同一个提交/窗口**（§5 §6）。
3. **每个改动必须有"可执行的验证命令"**，不接受"看起来对了"。本文每条都给了验证方式。

### 0.2 需要先拍板的 5 个决策点

| # | 决策 | 选项 | 建议 | 影响范围 |
|---|---|---|---|---|
| **D-1** | 未提交的 multi-SKU 重构怎么处理？ | ① 收口（补导出/修消费方）② 从发布分支剥离、另开分支继续 | **①** —— 实测 HEAD 干净、工作区只差 11 处生产源码引用，收口成本 2–4h，剥离反而让后续重复冲突 | §5 |
| **D-2** | git 历史里的密钥是否清除？ | ① `git filter-repo` 全量清除 + 强推 ② 仅确认轮换、接受残留 | **①**（若仓库曾被 fork/外借则必须①） | §6 |
| **D-3** | 三套可观测性栈保留哪套？ | ① Sentry + Prometheus ② OTel 全保留 ③ 只留 Sentry | **①** —— OTel 收敛为按需开关，省掉原生 grpcio 依赖 | §4 P2-8 |
| **D-4** | 前端状态/徽章统一是否本轮做？ | ① 本轮 ② 延后 | **②延后**至 P2 | §4 |
| **D-5** | 发布通道是否封掉 `build:fast`？ | ① 重命名+警告 ② 删除 ③ 保持不变 | **①**（改名 `build:unchecked` 并在 runbook 禁用） | §2 P0-1 |

> D-1 与 D-2 是**唯一需要外部协调**的两项（D-2 需要通知所有持有克隆的人）。

---

## 1. 止血清单（建议今天做完，合计 ≤ 1 小时，零回滚风险）

| # | 动作 | 命令/改法 | 验证 |
|---|---|---|---|
| 1 | 回退被误删的数据一致性决策 | 见 §2 P0-2（精确到行） | `python -m pytest fastapi_app/tests/test_qa_prod_stack_regression.py -q` → 2 条转绿 |
| 2 | 修 PowerShell 输出编码（迁出 8 条中最易的一条） | 见 §2 P0-3 ② | `pytest tests/test_migrate_erp_web_dryrun.py -q` → 转绿 |
| 3 | 给 `server_manager.py` 卸载流程加二次确认 | 见 §2 P0-6 | 手动点一次，弹出确认框 |
| 4 | 把 `.superpowers/`、`.claude/` 加入 `.gitignore` | `printf '\n.superpowers/\n.claude/\n' >> .gitignore` | `git check-ignore -v .claude/settings.local.json` |
| 5 | 把前端 `.env*` 加入 `frontend-vite/.gitignore` | 追加 `.env*` + `!.env.example` | `git check-ignore -v frontend-vite/.env.production` |

> 这 5 项都是"改一行、验一条命令"，**不涉及语义变更，不会引入新风险**。建议现在做。

---

## 2. P0 — 上线前必须闭环（阻断项）

### P0-1 ｜收口 multi-SKU 重构，让类型检查归零

**定位**
- 生产源码报错 11 处：`frontend-vite/src/views/beile-order/components/BeileOrderDetailDialog.vue`（L32、L86–90，共 6 处）、`frontend-vite/src/views/pattern-room/PatternRoomView.vue`（L27、L99、L170、L253、L260，共 5 处）。
- 缺失导出：`skuIsOrdered` / `skuOrderQty` / `skuProductionQty` / `rowTotalOrderQty` / `rowTotalProductionQty` / `SkuQtyFields` / `NOT_ORDERED_TIP` / `NOT_ORDERED_TOAST`（原在 `views/beile-order/composables/useBeileOrders.ts`，本改动删除）。
- test 报错 11 处：`BeileQuantityNullGuard.test.ts`、`BeileOrderRow.*.test.ts`、`QaAdversarial.beileSync.test.ts`。

> 注（2026-10-15）：本节引用的 `BeileOrderDetailDialog.vue` 已随「订单详情弹窗」整体删除；文中定位与代码片段为当时记录，保留原貌。

**根因**：删除导出时未同步消费方 —— 消费方 `BeileOrderDetailDialog.vue` **未被修改**，仍引用旧 API。

**改法（二选一，推荐 A）**

**A. 补齐导出（保留兼容层，最小改动）** —— 在 `useBeileOrders.ts` 中把被删符号按新语义重新导出：
```ts
// useBeileOrders.ts —— 恢复对外契约（内部实现可改为多 SKU 语义）
export type SkuQtyFields = { skuIsOrdered: boolean; skuOrderQty: number; skuProductionQty: number }

export const NOT_ORDERED_TIP = '该 SKU 尚未下单'
export const NOT_ORDERED_TOAST = '存在尚未下单的 SKU，请先下单'

/** 单 SKU 行合计；多 SKU 下由调用方传入 skuIndex 维度 */
export function rowTotalOrderQty(row: BeileOrderRow): number { /* 新实现 */ }
export function rowTotalProductionQty(row: BeileOrderRow): number { /* 新实现 */ }
export function skuIsOrdered(row: BeileOrderRow, skuIndex: number): boolean { /* 新实现 */ }
export function skuOrderQty(row: BeileOrderRow, skuIndex: number): number { /* 新实现 */ }
export function skuProductionQty(row: BeileOrderRow, skuIndex: number): number { /* 新实现 */ }
```
然后修 `BeileOrderDetailDialog.vue:32` 的 `row.is_ordered` → 走 `skuIsOrdered(...)`。

**B. 暂缓该分支**：`git stash push -u -m "wip-multi-sku"` 后从干净的 HEAD 发版。
> ⚠️ 若选 B，**不要用裸 `git stash`** —— 见 §5 的注意事项与项目内既有教训。

**验证**
```bash
cd frontend-vite && npx vue-tsc --noEmit          # 期望 exit 0
npx vitest run src/test/BeileQuantityNullGuard.test.ts src/test/QaAdversarial.beileSync.test.ts
```

**同时封堵发布通道（决策 D-5）**：`frontend-vite/package.json`
```jsonc
// 旧:  "build:fast": "vite build --logLevel info"
// 新:  改名并在 runbook 中禁用，避免绕过类型检查的产物上线
"build:unchecked": "vite build --logLevel info"
```
并在 `docs/runbooks/` 的发布步骤中明确：**发布只允许 `npm run build:atomic`**。

**工时** 2–4 h ｜ **风险** 低（收口后可回归验证）

---

### P0-2 ｜回退被误删的「API 不缓存」决策（含精确 diff）

**定位** `frontend-vite/vite.config.ts:57-81`

**根因** 这不是"手滑加的缓存"——**HEAD 里有一段明确的决策注释被删掉了**：
```ts
// HEAD 原文（被本次改动删除）：
// ERP 为数据一致性敏感系统：全部 API 请求一律 NetworkOnly（不缓存）。
// 此前读接口用 StaleWhileRevalidate / 兜底 NetworkFirst，Service Worker
// 会返回陈旧业务数据；且 dev 禁用、prod 启用，制造「生产与 debug 表现不一致」。
{ urlPattern: /\/api\//i, handler: 'NetworkOnly' },
```
本次改动把它**换回**了被否决的方案，且同时触发项目自建的守卫测试
`fastapi_app/tests/test_qa_prod_stack_regression.py:449,455`（要求 `/api/` 为 `NetworkOnly`、且全文件不得出现这两个 handler）。

**改法**：把 L57–81 三段替换回 HEAD 的单段：
```ts
{
  urlPattern: /\/api\//i,
  handler: 'NetworkOnly',
},
```
> ⚠️ **同一文件还有第二处改动**：本次改动**删除了 FontAwesome 图标预构建清单**（`fontAwesomeLoaderSource` / `fontAwesomeIconIncludes`，原用于修复 "dev 下图标空白"）。
> **不要**图省事 `git checkout HEAD -- vite.config.ts` —— 会连带回退这处。请**只回退 runtimeCaching 那一段**，并单独确认 FA 预构建是有意移除还是误删（若是误删，dev 环境图标会空白）。

**验证**
```bash
cd frontend-vite && npx vitest run src/../..   # 或直接跑守卫：
cd /d/erp_system && python -m pytest fastapi_app/tests/test_qa_prod_stack_regression.py::TestD6ViteConfigConsistency -q
```
期望 3 条全绿（含 `test_two_configs_equivalent_on_caching`）。

**工时** 0.5–1 h ｜ **风险** 极低

---

### P0-3 ｜修 5 个确定性失败的已提交测试

#### ① `tests/test_migration_timezone.py`（3 条）—— 守卫在 Alembic 上下文外调用 `op.get_bind()`

**定位** `migrations/_legacy_base_guard.py:54`
```python
def table_columns(table_name: str):
    inspector = sa_inspect(op.get_bind())   # ← 测试直接调 upgrade() 时无 ops 代理
```

**根因**（实测调用链）：
测试用 `mod.op = capture` 替换**迁移模块内**的 `op`，但 `table_columns` 用的是 `_legacy_base_guard` 模块里 `from alembic import op` 的那个全局符号 —— 未被替换，于是访问 Alembic 的真实 ops 代理，而该代理在"直接调用 `upgrade()`"场景下**尚未建立**，抛
`NameError: Can't invoke function 'get_bind', as the proxy object has not yet been established`。

**改法（推荐 A：测试侧注入真实 ops 上下文，不动生产代码）**
```python
# tests/test_migration_timezone.py
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import migrations._legacy_base_guard as guard

@pytest.fixture
def stub_pg(monkeypatch):
    """用 sqlite 内存库模拟「表与列都已存在」，让守卫放行并记录 DDL。"""
    eng = sa.create_engine('sqlite://')
    with eng.begin() as conn:
        for table, cols in _TABLES_FOR_TEST.items():      # 由 mod._COLUMNS 反推
            conn.exec_driver_sql(f'CREATE TABLE "{table}" ({", ".join(f\'"{c}" TEXT\' for c in cols)})')
    ctx = MigrationContext.configure(eng.connect())
    monkeypatch.setattr(guard, 'op', Operations(ctx))     # ★ 关键：让守卫看到真实 bind
    yield
```
> 若不想搭 sqlite 表，**B 方案**：让 `table_columns` 在无上下文时返回 `None`（即"列未就绪，跳过"）—— 但这样迁移就不产出 DDL，测试断言 `len(capture.executed) == len(_COLUMNS)` 会失败，**故 B 不可行，须走 A**。

**② `tests/test_migrate_erp_web_dryrun.py`（2 条）—— PowerShell 输出被 UTF-8 解码失败吞掉**

**定位** `tests/test_migrate_erp_web_dryrun.py:16-18`
**根因（已实测复现）**：脚本用 `Write-Host` 输出**中文**，Windows PowerShell 5.1 按 **GBK(cp936)** 写 stdout；测试用 `text=True`（默认 UTF-8）解码，字节 `0xd2` 非法 → `UnicodeDecodeError` **在读取线程内被静默吞掉** → `stdout=''`、`returncode=0` → `assert 'nssm stop erp-prod' in ''` 失败。
> 这正是项目 CHANGELOG 里已记录并**已在别处修过**的同一类 bug（`server_manager._run_capture` 的"中文 Windows + PYTHONUTF8=1 解码 sc/nssm 输出抛异常、stdout 丢失"）。可直接照抄既有修法。

**改法**
```python
import sys, subprocess

@pytest.mark.skipif(sys.platform != "win32", reason="迁移脚本仅在 Windows 生产机执行")
def test_dryrun_prints_sequence() -> None:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-Command", f"[Console]::OutputEncoding=[Text.Encoding]::UTF8; & '{SCRIPT}' -DryRun"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
```
> **两点都必须**：① 强制 PowerShell 以 UTF-8 输出；② `encoding="utf-8", errors="replace"` 兜底。
> 缺 ① 仍会因 cp936 字节导致解码失败被吞；缺 ② 一旦脚本输出异常编码会再抛 `UnicodeDecodeError`。
> 另：原测试**硬编码 `powershell` 且无 OS 守卫** —— 在 CI 的 `ubuntu-latest` 上必然 `FileNotFoundError`。必须加 `skipif`。

**验证**
```bash
python -m pytest tests/test_migration_timezone.py tests/test_migrate_erp_web_dryrun.py -q
```

**工时** 2–4 h ｜ **风险** 低（① 只加测试夹具；② 只改测试解码与守卫）

---

### P0-4 ｜恢复前端生产错误可见性（Sentry）

**定位** `frontend-vite/src/main.ts:47-71`（`captureException` 在 L55，`unhandledrejection` 在 L69）
**根因** 全仓**不存在 `Sentry.init()`**（实测：`grep -rn "Sentry.init" frontend-vite/src/` 为空，引用 sentry 的文件仅 `main.ts`）→ 所有上报是 no-op；且生产 `esbuild.drop:['console']` 会把 L51/L70 的 `console.error` 一并剥离。

**改法**
```ts
// main.ts —— 在 createApp 之后、mount 之前
import * as Sentry from '@sentry/vue'

const dsn = import.meta.env.VITE_SENTRY_DSN
if (dsn) {
  Sentry.init({
    app,
    dsn,
    environment: import.meta.env.MODE,          // production / staging
    release: import.meta.env.VITE_APP_VERSION,  // 便于定位发版引入的回归
    tracesSampleRate: 0.05,                     // 内网低频采样即可
    // ★ PII 脱敏：不采集 cookie/请求头，避免把 token 送出去
    beforeSend(event) {
      if (event.request) { delete event.request.cookies; delete event.request.headers }
      return event
    },
  })
}
```
并把 L69 的 `unhandledrejection` 接上：
```ts
window.addEventListener('unhandledrejection', (event) => {
  if (dsn) Sentry.captureException(event.reason)
})
```
**替代方案**：若决定不引入 Sentry（D-3 选 ③ 之外），则应**移除 `@sentry/vue` 依赖与 L55 代码**，避免"以为有监控其实没有"的假象。

**验证**
1. 设置 `VITE_SENTRY_DSN` 后 `npm run build`，本地起 dist，手动 `throw new Error('probe')`，确认 Sentry 面板收到；
2. 不设 DSN 时构建，确认无报错、无多余请求；
3. 确认 `beforeSend` 生效（事件里无 cookies/headers）。

**工时** 1–2 h ｜ **风险** 低（受 DSN 开关保护，未配置时行为与现在一致）

---

### P0-5 ｜清除 git 历史中的密钥（详见 §6）

**定位**（实测 `git log --all --diff-filter=A`）
`.env.production`、`config/.env.production`、`config/jwt/private.pem`、`android-app/release.keystore`

**现状**：HEAD 已干净（`git ls-files` 仅 `.env*.example`），且已换 ES256 + 轮换口令；但历史 blob 仍可被任何克隆方提取。

**工时** 4–8 h（含协调）｜ **风险** 高（改写历史）→ 见 §6 的分步方案

---

### P0-6 ｜运维 GUI 破坏性操作加二次确认

**定位** `server_manager.py:3102-3119`
```python
def _uninstall_services(self):
    ...
    self._gate.start('卸载生产服务', self._uninstall_services_flow, nssm)   # ← 直接执行

def _uninstall_services_flow(self, nssm):
    for name in (_SVC_API, _SVC_ARQ, _SVC_WEB):
        self._run_capture([nssm, 'stop', name], timeout=30)
        code, out = self._run_capture([nssm, 'remove', name, 'confirm'], timeout=30)   # ★ 拆生产
```
**根因** 全文件 `askyesno`/`messagebox.ask` 出现 **0 次** —— 卸载/批量停服没有任何确认环节。

**改法**：在 `_uninstall_services`（以及 `_stop_services`、`_restart_services` 的"全部服务"路径）入口加：
```python
def _uninstall_services(self):
    if not messagebox.askyesno(
        '确认卸载生产服务',
        f'即将停止并卸载以下 NSSM 服务：\n  {_SVC_API}\n  {_SVC_ARQ}\n  {_SVC_WEB}\n\n'
        '卸载后生产站点将不可访问，需重新「安装服务」才能恢复。\n\n确定继续？',
        icon='warning', default='no',          # ★ 默认停在"否"
    ):
        self._msg_queue.put(('log', {'text': '已取消卸载'}))
        return
    ...
```
> `default='no'` 很关键：让误触回车不会拆生产。

**验证**：手工点一次"卸载服务"，应弹确认框；选"否"后服务仍在（`nssm status erp-prod`）。

**工时** 1–2 h ｜ **风险** 极低

---

## 3. P1 — 上线后 1 个月内

> 完整清单见审查报告 §5.2。此处给出**优先级最高的 4 项**的具体改法。

### P1-1 ｜重新开启限流

**定位** `fastapi_app/core/limiter.py:23-31`
```python
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],
    enabled=False,                    # ★ 全局限流关闭 → 所有 @limiter.limit 失效
    storage_uri=os.getenv("REDIS_CACHE_URL") or "memory://",
    in_memory_fallback_enabled=True,
)
```
**改法**（分级放行，避免内网正常操作被误拦）
```python
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"] if _LIMITER_ENABLED else [],
    enabled=_LIMITER_ENABLED,                       # 改为环境开关，默认 True
    storage_uri=os.getenv("REDIS_CACHE_URL") or "memory://",
    in_memory_fallback_enabled=True,
    in_memory_fallback=["60/minute"],
)
```
其中 `_LIMITER_ENABLED = os.getenv('RATE_LIMIT_ENABLED', 'true').lower() == 'true'`。
**必须同时**给重端点单独设限（否则全局 60/min 对导出仍过宽）：
```python
# endpoints/stock.py、report.py、daily_production.py、purchase_center/export_utils.py
@limiter.limit("5/minute")
```
**内网过渡建议**：先只对**导出/导入/报表**上 `5/minute`，观察一周无误拦再开全局。
**验证**：`for i in $(seq 1 10); do curl -s -o /dev/null -w '%{http_code}\n' -X POST .../export; done` → 第 6 次起 429。
**工时** 3–4 h

### P1-2 ｜把 `*_strict` 接到敏感路由（修"失败开放"）

**定位** `fastapi_app/core/deps.py:235,268` —— 两个函数**已定义、已导出，零调用点**。
**改法**：把敏感路由的 `router.py` 级依赖改为 strict 版；最小侵入是在 `router.py` 的 `include_router(...)` 处替换：
```python
# fastapi_app/api/v1/router.py —— 对 admin/backup/user/权限类路由
from fastapi_app.core.deps import get_current_user_id_strict
api_router.include_router(
    backup_router, prefix="/backup", tags=["备份"],
    dependencies=[Depends(get_current_user_id_strict)],     # ← 由 non-strict 改为 strict
)
```
**验证**：模拟 Redis 不可用（`redis-cli shutdown` 或断开 `REDIS_CACHE_URL`），用**已登出**的 token 请求敏感端点 → 期望 401（改前可能放行）。
**工时** 2 h

### P1-3 ｜refresh token 轮换 + 重用检测

**定位** `fastapi_app/api/v1/endpoints/auth.py:344-397` —— 只签发新 access token，**不签发/吊销 refresh**。
**改法**
```python
# 1) 校验通过、确认用户可用之后：
new_refresh = create_refresh_token(token_data)          # 新 refresh
await revoke_token(payload['jti'], payload['exp'])      # ★ 旧 refresh 立即失效
# 2) 设置新 refresh cookie（与 access cookie 同属性：httponly/samesite/secure）
response.set_cookie(key="refresh_token", value=new_refresh, max_age=REFRESH_TTL,
                    httponly=True, samesite=_samesite, secure=_secure, path="/")
# 3) 重用检测：若某 jti 已被吊销却又被使用 → 该会话疑似被窃，吊销该用户全部活跃 refresh
if await is_token_revoked(jti):
    await revoke_all_user_tokens(user_id)               # 需新增：按 sub 批量吊销
    raise HTTPException(401, "刷新令牌已失效")
```
**验证**：单测覆盖"刷新两次用同一 refresh → 第二次 401"、"刷新后用旧 refresh → 401"。
**工时** 4 h

### P1-4 ｜登出时清理 Service Worker 的 API 缓存

**定位** `frontend-vite/src/stores/auth.ts:230-240`（`logout()` 只清 sessionStorage + Vue Query）
**改法**（在 P0-2 回退之后，此项作为**纵深防御**保留 —— 防止将来再引入缓存）
```ts
async function logout() {
  authGeneration += 1
  user.value = null
  navSections.value = []
  loaded.value = false
  clearCsrfCache()
  try { sessionStorage.removeItem(USER_SNAPSHOT_KEY) } catch { /* 静默 */ }
  clearUserCaches()
  // ★ 清掉 Workbox 运行时缓存，避免共用终端跨账号读到前一用户的响应
  if ('caches' in window) {
    for (const name of await caches.keys()) {
      if (name.startsWith('api-')) await caches.delete(name)
    }
  }
}
```
**工时** 2–3 h ｜ **依赖**：必须先做 P0-2（否则清除的正是那条会被重新填充的缓存）

### P1-5 ｜补备份/还原链路测试（**最高价值的一项**）

**定位** 覆盖率实测：`services/backup/dump.py` 7.2%、`incremental.py` 8.8%、`cleanup/service.py` 10.7%、`endpoints/backup/restore.py` 12.7%、`backup_tasks.py` 13.9%。
**改法**（按"最不可逆"排序，先做还原）
1. **端到端还原演练（人工，一次性）**：在一台隔离机用生产备份包执行完整还原，记录耗时与校验结果。**这是唯一能证明"备份可用"的手段**，优先级高于任何单测。
2. `restore.py` 加接口级测试：正常还原、损坏包、密码错误、版本不兼容 → 期望 4xx/5xx 与不产生半成品状态。
3. `dump.py::restore_database_via_psql`（cx=184/256 行）先按"事务边界"拆函数再补测。
4. `incremental.py` 补"增量链断裂"用例。
**工时** 16–24 h（其中人工演练 4–8 h）

---

## 4. P2 — 上线后 3 个月内（结构性偿还）

| # | 专项 | 定位 | 改法要点 | 工时 |
|---|---|---|---|---|
| P2-1 | 拆超长函数 | `backup/orchestration/core.py:148`(cx326/253L)、`bom_service.py:643`(cx317/217L)、`dump.py:158`、`dashboard/mobile.py:41` | 按**阶段边界**切：`校验 → 加锁 → 执行 → 校验 → 清理 → 写审计`，每段可单独测 | 24–40 h |
| P2-2 | 完成 multi-SKU 迁移 | 95 处 `TODO(multi-sku-order)`，注释写明"当前依赖首 item 兼容值" | 见 §5 | 需专项 spec |
| P2-3 | 分页单点化 | 39 处/26 文件 `(page - 1) * per_page` | 新增 `paginate(stmt, page, per_page)`，统一钳制 `per_page` 上限 | 4–6 h |
| P2-4 | 错误处理统一 | 276 处 `raise HTTPException` vs 58 处 `AppError` | 服务层抛类型化异常 + 端点一个 `map_app_error` 装饰器 | 6–8 h |
| P2-5 | 状态语义单点化 | 22 处标签函数 + 17 套徽章样式，无 `utils/status.ts` | 新建 `src/utils/status.ts`；`UiStatusBadge` 直接吃 `status` | 8–10 h |
| P2-6 | 拆 `useSummaryModal.ts`(931L) | 损耗率数学 + HTML 构建 + 导出 + 状态混在一处 | 拆 `utils/lossRate.ts` + `utils/summaryExport.ts` | 6–8 h |
| P2-7 | 删死代码 | `utils/{notification,batch_import_handler,reports,batch_handler,date_utils}.py` 实测 0 活引用 | `git rm` 5 个文件（~2100 行） | 2–4 h |
| P2-8 | 收敛依赖 | `otel-instrumentation-requests` 未用、`rollup-plugin-visualizer` 未接线、`@capacitor/*` 未声明、无 Python lock | 按 D-3 收敛可观测性栈 | 16–32 h |
| P2-9 | 前端工具收敛 | 日期格式化 9 处重复、防抖三件套 5 处重复、4 个列表抽象 3 个闲置 | 新建 `status.ts`/`useSearchPage()`，删闲置抽象 | 8–11 h |
| P2-10 | 备份域下沉 | `endpoints/backup/validation.py`(835L) 含 zip/解密/sha256 | 迁入 `services/backup/verify/`，端点变薄 | 16–24 h |

> **P2-5 注意**：这是**界面/排版类改动**，按既有偏好应**先出 HTML 对比稿选定方案再动代码**，不要直接改。

---

## 5. 专项 A ｜multi-SKU 重构收口方案

**背景**：95 处 `TODO(multi-sku-order)` 横跨 `order / approval / inventory / purchase / report / shipment / shared_models`，注释统一写明
"`order.quantity`/`product_id` 为**首 item 兼容值**"（如 `order.py:269`、`approval_service.py:320`、`order/commands.py:206`）。

**风险本质**：多 SKU 单据下，所有以"首 item"近似整单的逻辑（库存扣减、审批数量、报表展开、出货计算）都会**静默算错**，而不是报错。

**建议分 4 步走（严禁一把梭）**
1. **写一个"多 SKU 正确性"测试集**（先红）：构造 ≥2 个 item 的订单，断言库存扣减、审批数量、报表合计均按 item 维度。这是收口的验收基准。
2. **统一读取入口**：新增 `order_items_of(order)` 之类的唯一访问器，禁止业务代码直接读 `order.quantity`。
3. **按模块逐个迁移**，每迁一个模块删除对应 TODO，并跑第 1 步的测试集。
4. **最后删除兼容值**，并在 `shared_models/order.py` 移除"首 item 兼容"分支。

**并行策略**：本次未提交的前端改动（`useBeileOrders.ts` 系列）属于同一迁移的前端部分 —— 建议**先按 P0-1 收口使其可发布**，再按上述步骤做后端语义迁移。

> ⚠️ **不要用裸 `git stash` 保存这批在建改动**。项目内已有教训（工作区里存在 `never-stash-user-worktree-changes` 一类的记忆，且此前一次误 stash 造成过困扰）。如需暂存请用 `git stash push -u -m "<唯一标签>"`，并立即 `git stash list --format='%H %gs'` 记下 SHA，恢复用 `git stash apply <sha>` 而非 `pop`。

---

## 6. 专项 B ｜git 历史密钥清除方案（高风险，需协调）

**已泄露（历史）**：`.env.production`（`DB_PASSWORD` / `SECRET_KEY` / `REDIS_PASSWORD`）、`config/.env.production`、`config/jwt/private.pem`（RSA-4096 私钥）、`android-app/release.keystore`。
**已做**：HEAD 已移除；口令已轮换；JWT 已切 ES256。
**未做**：历史 blob 仍在，任何克隆方可 `git show <old-sha>:config/jwt/private.pem` 取回。

**执行步骤（务必按序）**
1. **先确认轮换完整性**（比清历史更优先）：
   - [ ] DB 口令、Redis 口令、只读副本口令、`SECRET_KEY` 全部已换？
   - [ ] RSA 私钥已作废（ES256 生效后旧 RS256 token 不能验签）？
   - [ ] **`release.keystore` 是否需要重新生成并重发 APK**？（keystore 泄露 = 他人可签同名包；Android 的 keystore 无法"轮换"，只能换包名或接受风险）
2. **冻结写入**：通知所有协作者停止 push，或直接封仓库写权限。
3. **备份**：`git clone --mirror . ../erp-backup.git`（**必须**先镜像备份）。
4. **清除**：
   ```bash
   git filter-repo --force \
     --path .env.production --path config/.env.production \
     --path config/jwt/private.pem --path config/jwt/public.pem \
     --path android-app/release.keystore --invert-paths
   ```
5. **推送**：`git push --force --all && git push --force --tags`。
6. **收尾**：通知所有持有克隆的人**重新克隆**（旧克隆仍含旧历史）；在 `.gitignore` 中确认 `*.pem`、`.env*`、`*.keystore` 已覆盖；在 CI 加 `gitleaks` 防止复发（见 P1-10）。

**替代方案（若 D-2 选②）**：不清历史，则须做到 —— 仓库只保留私有远端、禁止 fork/外借、并在 runbook 中记录"历史密钥已被轮换、残留仅为旧值"的结论与责任人。

**工时** 4–8 h ｜ **风险** 高（改写历史 + 需全员重新克隆）

---

## 7. 专项 C ｜测试套件密闭化（让门禁重新可信）

**问题**：同一命令在有无负载时给出**不同结果**（实测：并发时 16 failed/110 errors，单独跑全绿；`test_multi_sku_inventory_stats.py` 单跑 9 passed、全量会话内 2 failed）。**绿灯不能证明通过**。

**三步走**
1. **量化**：CI 增加"跑两次、比对结果集"的临时步骤，产出**不稳定用例清单**（这是后续所有工作的输入）。
2. **隔离**（逐个消除污染源）：
   - 共享 DB 的写入型用例 → 每个用例独立事务 + 回滚，或独立 schema；
   - 事件循环类（`RuntimeError: Event loop is closed`）→ 统一 `asyncio_mode` 与 fixture 作用域，禁止用例自行 `new_event_loop`；
   - 文件系统/时间依赖（backup 系列）→ 用 `tmp_path` + 冻结时间（`freezegun`）；
   - 全局状态（缓存单例）→ 已有 autouse fixture 清 L1 缓存，扩展到其余单例。
3. **设卡**：CI 要求 **连续 3 次跑批结果一致** 才放行；把不稳定用例显式 `@pytest.mark.flaky_quarantine` 并记录技术债，禁止静默 skip。

**顺带处理**（低成本高收益）
- 删/改 **55 个"自证式"测试**（`tests/test_user_management.py`、`test_stock_management.py`、`test_routes_coverage.py`、`test_shipment_limit.py` —— 实测各自 `declarative_base()` 建 sqlite 表、**不导入生产模型**）→ 改为对生产 service/model 断言，或删除。
- 前端：`vitest.config.ts` 增加 `coverage.thresholds`（当前 0 门禁、实测 12%）；把 16 个断言 `style`/`className`/`innerHTML` 的用例改为断言用户可见行为。

**工时** 12–30 h（密闭化）+ 16–30 h（自证式测试清理）

---

## 8. 上线前验收 Checklist（逐条可执行）

**构建与静态检查**
- [ ] `cd frontend-vite && npx vue-tsc --noEmit` → **0 错误**（P0-1）
- [ ] `cd frontend-vite && npm run build:atomic` → 成功
- [ ] `python scripts/quality_gate.py` → `[PASS]`
- [ ] `python scripts/file_size_gate.py` → 通过

**测试**
- [ ] `python -m pytest tests fastapi_app/tests -q --ignore=tests/qa --ignore=tests/e2e --ignore=tests/stress --ignore=tests/performance -m "not flask_legacy"` → **0 failed**（P0-3 后应达标）
- [ ] `cd frontend-vite && npx vitest run` → 0 failed（P0-1 后应达标）
- [ ] 串行跑批 **连续两次结果一致**（若尚不稳定，则明确记录为"已知不可信"，不得据此判断可上线 —— §7）

**安全**
- [ ] `python -m pip_audit -r requirements/base.txt` → 0 漏洞（当前已达标）
- [ ] `cd frontend-vite && npm audit --omit=dev` → 0 漏洞（当前已达标）
- [ ] `git ls-files | grep -iE '\.pem$|\.env$|keystore'` → 空
- [ ] P0-6 确认框生效；P1-2 的 `*_strict` 至少接到备份/用户/权限路由

**数据安全（最高优先级）**
- [ ] **完成一次真实的全量还原演练并留证**（备份/还原覆盖率仅 7–16%，这是唯一不可逆的链路）
- [ ] `alembic -c migrations/alembic.ini heads` → 恰好 1 个 head
- [ ] 确认最近一次自动备份可用（`/api/health` 的 `backup.age_hours` 在期望范围内）

**部署**
- [ ] 回滚预案经过验证（`dist-old` 或镜像备份可回退）
- [ ] 发布走 `build:atomic`，`build:fast`/`build:unchecked` 不在发布脚本中出现

---

## 9. 建议排期

| 窗口 | 内容 | 人力 |
|---|---|---|
| **D0（今天，≤1h）** | §1 止血 5 项 | 0.1 人日 |
| **D1–D3** | P0-1（收口重构）、P0-2、P0-3、P0-4、P0-6 | 1.5–2.5 人日 |
| **D3–D5（与开发并行）** | P0-5 密钥清除 + 通知；**人工还原演练** | 1–1.5 人日 |
| **上线** | 走 §8 checklist | — |
| **上线后 1 个月** | P1-1…P1-5 + §7 密闭化；仓库瘦身、CI 加 gitleaks | 12–18 人日 |
| **上线后 3 个月** | §4 P2-1…P2-10 + §5 multi-SKU 专项 | 90–140 人日 |

**关键判据**：§8 中只要「构建 0 错误」「测试 0 failed」「还原演练成功」三条未同时满足，就**不应放行**。

---

## 附：本文档中所有代码改动的定位索引

| 编号 | 文件 | 行 | 类型 |
|---|---|---|---|
| P0-1 | `frontend-vite/src/views/beile-order/composables/useBeileOrders.ts` | 导出区 | 新增兼容导出 |
| P0-1 | `frontend-vite/src/views/beile-order/components/BeileOrderDetailDialog.vue` | 32, 86–90 | 修引用 |
| P0-1 | `frontend-vite/src/views/pattern-room/PatternRoomView.vue` | 27, 99, 170, 253, 260 | 修引用 |
| P0-1 | `frontend-vite/package.json` | `build:fast` | 改名+禁用 |

> 注（2026-10-15）：上表 P0-1 的 `BeileOrderDetailDialog.vue` 已随「订单详情弹窗」整体删除，该行定位为当时记录。
| P0-2 | `frontend-vite/vite.config.ts` | 57–81 | 回退 runtimeCaching |
| P0-3① | `tests/test_migration_timezone.py` | 52–139 | 加夹具 |
| P0-3② | `tests/test_migrate_erp_web_dryrun.py` | 16–18 | 改解码 + OS 守卫 |
| P0-4 | `frontend-vite/src/main.ts` | 47–71 | 加 `Sentry.init` |
| P0-6 | `server_manager.py` | 3102–3119 | 加确认框 |
| P1-1 | `fastapi_app/core/limiter.py` | 23–31 | 开限流 |
| P1-1 | `endpoints/{stock,report,daily_production}.py` | 导出端点 | 加 `@limiter.limit` |
| P1-2 | `fastapi_app/api/v1/router.py` | 备份/用户/权限路由 | 换 strict 依赖 |
| P1-3 | `fastapi_app/api/v1/endpoints/auth.py` | 344–397 | refresh 轮换 |
| P1-4 | `frontend-vite/src/stores/auth.ts` | 230–240 | 登出清 SW 缓存 |
| P1-11 | `scripts/file_size_gate.py` | 36 | `SCAN_DIRS` 补根目录 |

---

## 附录 C · 执行记录与再评估（2026-09-28 起）

实施过程中若干条经**实测**后被修正或缩减。按本文档"所有结论均需基于实际分析"的原则，一并记录：

### 已完成并独立复审

| 项 | 结果 | 复审结论 |
|---|---|---|
| P0-1 | beile 收口 + 恢复 558 行被删测试 | vue-tsc 22→0；前端全绿 |
| P0-2 | vite 回退 4 处被误删的修复 | 守卫 5 绿 |
| P0-3 | PowerShell 解码 + Alembic ops 上下文 | 11 passed |
| P0-4 | Sentry 初始化（含**复审抓出的 `attachProps` PII 外送**） | 16 测试，mutation 验证 |
| P0-5 | 全仓密钥扫描 + CI + 行级抑制 | 55 单测；2300+ 文件干净 |
| P1-1 | 限流开关（装饰器本就存在，只是被 `enabled=False` 架空） | 0 处非预期 429 |
| P1-2 | `/backup` 接 fail-closed 鉴权（**收窄**，见下） | mutation 验证有牙齿 |
| P1-4 | 登出清 SW 的 api-* 缓存 | 3 单测 |
| P2-7 | 删死代码 **12 文件 / 3165 行** | 复审 Ready；漏掉的兄弟文件已补删 |
| — | `redis_cache` 客户端自愈（P 前置） | 4 轮复审各抓一个真 bug |
| P1-3 | refresh 轮换 + 幂等重放 grace 窗口 | 复审抓出**登出后 60 分钟未授权访问**真 bug，已修 |

### 经实测后**缩减或跳过**的项（重要，勿据原文重提）

**P2-3 分页单点化 —— 跳过。** 原文判断为 "39 处/26 文件，可修 off-by-one/limit bug"。实测推翻：

* 端点层**已强制** `page >= 1` / `per_page >= 1`（`Query(1, ge=1)`），**无 bug 可修**；
* 原文"8 处 `page` 无下界"是 **grep 假阳性**——那 8 处是 Pydantic 响应模型字段与内部函数签名，不是查询参数；
* 给 `per_page` 加**上限**会破坏真实用法：前端请求 `per_page: 1000`/`500`，`tests/test_report.py:158` 期望 `5000`。

结论：**纯外观性去重、零行为收益**，26 文件改动的风险与收益不成比例。若将来有人重提，请先反驳以上三点。

**P1-2 收窄到 `/backup`。** 原方案对 `/users`、`/permissions`、`/backup` 三个前缀都接 strict。复审指出
`redis_cache.init_app()` 失败后**永不重试**，故「Redis 启动即不可用」会让 strict 路由**永久 401**；
而本仓库有过开机顺序事故史。故只保留 `/backup`（其还原路径本就对 Redis fail-closed，不引入新锁死），
`/users`、`/permissions` 保留 fail-open 并在代码里注明理由。**前置条件（客户端自愈）现已完成**，
三前缀统一 strict 可作为后续独立项（建议先上线观察自愈）。

**P1-1 的全局默认值改为"不设"。** 原码 `default_limits=["60/minute"]` 从未在真实流量下验证（限流长期被关闭），
实测单次测试会话即 172 次 429。故默认不设，只让作者本就写好的端点级 `@limiter.limit` 生效，
留 `RATE_LIMIT_DEFAULT` 供观察后显式开启。

### 仍未做 / 需产品决策

* **P0-6 卸载确认框** —— `server_manager.py` 长期被并发会话占用，未动。
* **`enter_maintenance()`/`exit_maintenance()` 无生产调用方** —— 还原流程用的是 `acquire_restore_lock`，
  「还原期间禁止写入」这一保证**目前不存在**。接线是产品决策（长时间禁写是大事），已在
  `core/maintenance.py` docstring 写明。
* **`maintenance` 中间件每写请求一次 Redis 往返** —— 已改为自愈客户端 + 日志节流；
  但若要做得更彻底需合并到还原锁的判断里，属后续。
* **P1-5 备份/还原测试** —— 代码层可补；**「真还原演练」必须在隔离机由人执行**，是本项目最有价值的未做项。
* **P2 其余 9 项**（拆超长函数、错误处理统一、状态语义统一、三套可观测性栈收敛等）—— 量级 90+ 人日。

---

## 附录 D · P1-5 备份域实测发现（2026-09-28，直连生产库）

> 方法：直连 `localhost:5432/erp_system` 查询 `backup_schedule` / `backup_record`。
> **本节推翻了审查报告与优化方案原文中"每周 disaster_recovery_test 执行真实还原"的说法。**

### 发现 1（最高优先级）：**三种保护性排期在生产库中不存在**

代码支持 5 种排期任务，且迁移 `036`/`037` **本已播种全部 5 种**；但线上 `backup_schedule` **只有 2 行**：

| 任务类型 | 代码支持 | 线上 | 后果 |
|---|---|---|---|
| `full` | ✅ | ✅ `0 2 * * *` | 正常 |
| `incremental` | ✅ | ✅ `0 2 * * *`（名字/cron 与播种值不同 → 被界面改过） | 正常 |
| `integrity_check` | ✅ | ❌ | **备份从不校验** |
| `cleanup` | ✅ | ❌ | **备份从不清理 → 磁盘终将写满** |
| `disaster_recovery_test` | ✅ | ❌ | **可恢复性从未被证明**（`backup_record` 中 `recovery_test` 记录 **0 条**） |

排期表有完整 CRUD（`POST/PUT/DELETE /api/v1/backup/schedule`），所以行是被**界面删/改**掉的；
存活两行的 `created_at` 为 2026-09-16/17。**迁移播种是一次性的，之后被改动没有任何守卫。**

**建议**：
1. **立即**经界面（或 SQL）补回 `integrity_check` / `cleanup` / `disaster_recovery_test` 三条排期；
2. `cleanup` 缺失意味着**磁盘会持续增长**——上线前请确认磁盘余量；
3. 加一道守卫（健康检查或启动自检）：期望的排期类型缺失时告警，避免再次静默消失。

### 发现 2：`backup_schedule.last_status` 滞留 `running`

两条排期的 `last_run_at` 均为 2026-09-28 02:00，`last_status` 至今（20 小时后）仍是 `running`，
而 `backup_record` 显示 02:00:09 已 `success`。即**排期行的状态回写失效或滞后**，会让运维误判"任务卡住"。

### 发现 3（正面）：备份本身是好的

`backup_record`：`full` 28 条成功、`incremental` 15 条成功，无失败记录。

### 本次补的代码级测试

`fastapi_app/tests/test_backup_verify_core.py`（21 条）覆盖 `services/backup/verify/core.py` 的
**动态表名注入防线**（`quote_table` 接受/拒绝边界、`query_table_rows` 在构造 SQL 前拒绝危险表名、
`since` 走绑定参数、行值序列化）。该模块覆盖率 16% → 25%（仅本文件；合并既有备份测试更高）。
