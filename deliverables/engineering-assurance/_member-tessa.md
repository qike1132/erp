# 测试策略与测试债评估（Tessa · 测试专家）

- 任务：#4「测试策略与测试债评估」
- 审计日：2026-09-17
- 环境：系统 Python `C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe`，**单文件跑**、`-p no:cacheprovider`（全量跑有 conftest event-loop 污染）
- 严重度口径：🔴 高 / 🟠 中 / 🟡 低 / 🟢 提示

---

## 0. 结论摘要

| # | 结论 | 严重度 |
|---|---|---|
| 1a | 备份健康检查「替身字段形状漂移」**已修（FIXED）** —— 生产者补发 `mtime`、消费者按 `mtime`/`filename` 取值、且已补**不 mock 生产者**的真实目录端到端测试（回滚修复后该测试变红，实测）。**残留**：测试注释与真实生产者形状矛盾（🟡）、integrity 路径仍 mock 生产者（🟡） | 修复✅ / 残留 🟡 |
| 1b | `AsyncMock()` 合成属性存在「隐式真值」假绿点（如 worker-online 替身靠默认真值），非零但影响有限 | 🟡 |
| 1c | 主测试套件（fastapi_app/tests）**全部 mock DB**；旧套件（tests/）虽连真库，但 schema 用 `create_all` 从**模型**直建、**绕过 Alembic** → **「代码已部署、迁移未执行」类故障现有测试无法发现** | 🟠 |
| 2 | 既有失败基线**不可复现**（今日实测集合与记录不同）；无失败分级治理 → 长期红使测试套件失去信号 | 🟠 |
| 3 | `.coverage` 仅含 2 个文件、coverage/pytest-cov **未安装**、addopts 无 `--cov`、无覆盖率门禁 → 覆盖率**未运作** | 🟠 |
| 4 | 契约快照机制**有效**（21 份快照 + 白名单守卫 + 需真后端比对），但**未覆盖备份端点** → 1a 类缺陷不被契约快照兜住 | 🟡 |
| 5 | 对抗性捕获力抽查**通过**：回滚 CORS 修复→8 失败；回滚登录限流阈值→2 失败（实测） | 健康 ✅ |

**一句话测试体系健康度**：核心路径单测密度高、断言质量总体好（1315 个用例、0 个 `assert True`），单元层是资产；但**「契约/集成」这一层是空的**——DB 全 mock、schema 从模型直建、契约快照不覆盖备份端点，导致 1a 这类「替身与真实生产者漂移」缺陷只能靠事后补的少数真实目录测试兜，体系整体**中度亚健康**。

---

## 1a. 最高优先级：替身字段形状漂移是否真已修 → **已修（FIXED）**

### 三选一结论：**已修**

关键问题是「测试替身伪造了一个真实生产者根本不返回的字段（`mtime`），使 1970-01-01 缺陷长期全绿」。逐键比对如下。

### 证据链

**(1) 真实生产者 —— 现在同时返回 `filename` + `mtime` + `size`**

`fastapi_app/services/backup/records.py:192` `def list_backup_files()`，返回结构在 **:216**：

```python
entry: dict = {'filename': f.name, 'mtime': stat.st_mtime, 'size': stat.st_size}
```

- 键名是 **`filename`**（不是 `name`）✅
- **`mtime` 确实存在**（:211 `stat = f.stat()` 有 try/except OSError 守卫）✅
- :195-203 docstring 明确写「返回条目同时携带 `filename` 与 `mtime`」，并点明历史缺陷。

**(2) 消费点 —— 按 `mtime` / `filename` 取值，且提供降级路径**

`fastapi_app/api/v1/endpoints/backup/validation.py`：

```python
# _check_last_backup  (:156-158)
latest_backup = max(backup_files, key=lambda x: x.get('mtime', 0))
latest_time   = datetime.fromtimestamp(latest_backup.get('mtime', 0))   # ← 缺 mtime 时退化为 0 → 1970-01-01
hours_since   = (datetime.now() - latest_time).total_seconds() / 3600
if hours_since > 24: issues.append(f'最近备份时间超过24小时（{round(hours_since,1)}小时前）')

# _check_backup_integrity  (:186)
filename = file_info.get('filename', '')
filepath = backup_service.BACKUP_DIR / filename
```

- `_check_last_backup` 的 `.get('mtime', 0)` 就是那个「降级路径」：**若生产者漏发 `mtime`，必然算出 1970-01-01 并恒报「超过24小时」**。这正是历史缺陷的根因，也是本次要求核验的真问题点。

**(3) 端到端测试已补（不 mock 生产者）**

`fastapi_app/tests/test_backup_validation_helpers.py`：

```python
class TestCheckLastBackup:
    @staticmethod
    def _use_real_dir(tmp_path, monkeypatch):          # :131
        import zipfile as _zipfile
        from fastapi_app.services.backup import records as _records
        monkeypatch.setattr(_records, 'BACKUP_DIR', tmp_path)                 # ← 真生产者读的模块级常量
        monkeypatch.setattr(validation.backup_service, 'BACKUP_DIR', tmp_path)
        return _zipfile

    def test_check_last_backup_recent_returns_healthy(self, tmp_path, monkeypatch):   # :143
        zipfile = self._use_real_dir(tmp_path, monkeypatch)
        p = tmp_path / 'erp_backup_recent.zip'
        with zipfile.ZipFile(p, 'w') as zf: zf.writestr('manifest.json', '{}')
        recent = time.time() - 2*3600; os.utime(p, (recent, recent))
        result, issues = validation._check_last_backup()       # ← 走真实 list_backup_files()
        assert result['status'] == 'healthy'
```

- 该用例**不 mock `list_backup_files`**：建真实 zip（命名符合 `_BACKUP_NAME_PREFIXES`）、`os.utime` 造真实 mtime、`monkeypatch` 把 **`records` 模块级 `BACKUP_DIR`** 指到 `tmp_path`，真实生产者扫描真实目录。
- 生产者 `list_backup_files` 读的正是模块级 `BACKUP_DIR`（records.py:206），故 monkeypatch 生效，链路真实打通。

**(4) 对抗验证 —— 回滚修复后测试是否变红（实测）**

将 `records.py:216` 的 `'mtime': stat.st_mtime,` 删除（回滚修复），单跑 `TestCheckLastBackup`：

```
=== RG_REVERTED_PRODUCER RC= 1
test_check_last_backup_recent_returns_healthy FAILED   ← 期望 healthy，实得 warning（1970→超24h）
  AssertionError: assert 'warning' == 'healthy'
1 failed, 3 passed
RESTORED_OK True
```

→ **该 E2E 测试是 `mtime` 字段的真实回归护栏**（把修复回滚即变红）。结论：**已修，且护栏有效。**

### 残留问题（不改变「已修」结论，但需登记）

| 残留 | 证据 | 严重度 |
|---|---|---|
| 测试注释与真实生产者**自相矛盾**：`_use_real_dir` docstring（:132-136）称真实生产者是 `{'filename','size'}`、**「无 mtime」**，并称用 `mtime` 是「历史教训」；但真实生产者 `records.py:216` **恰好返回 `mtime`**。注释所引行号 `records.py:166` 也已失效（当前 :166 是 `db.flush()`） | test 文件 :132-136 vs records.py:216 | 🟡（误导性文档，未来维护者可能据此「对齐」删掉生产者的 mtime，重引 1970 缺陷——好在 E2E 会变红） |
| integrity 路径**仍在 mock 生产者**：`test_check_backup_integrity_all_healthy`(:205)、`..._missing_file_returns_degraded`(:215) 用 `return_value=[{'filename': 'ok.zip', 'mtime': 0}]` 伪造。`_check_backup_integrity` 只消费 `filename`（:186），故 mock 的 `mtime` 属多余键，且此路径**无「不 mock 生产者」的端到端测试**——若生产者把 `filename` 改名，这两条仍绿 | test 文件 :205/:215 | 🟡 |

> 提示：test 文件顶部 `from datetime import datetime, timedelta`(:8) 在改造为 `os.utime` 方案后已无引用（未用导入）——轻微 lint 债。

---

## 1b. `AsyncMock()` 合成属性造成的「永远通过」

**现象**：`AsyncMock()` 会自动合成任意属性，`await mock.anything()` 默认返回**真值 AsyncMock**。当替身被当作「通过/在线」开关用时，其真值来自**默认值而非显式设定**，属于隐式假绿。

**实证**：`fastapi_app/tests/test_backup_m1.py:230-236`

```python
@pytest.fixture(autouse=True)
def _worker_online(self):
    with patch('...backup.actions._check_worker_online', new=AsyncMock()):
        yield
```

- `_check_worker_online` 被替换为裸 `AsyncMock()`，`await` 后返回**合成 AsyncMock → 真值**，被当作「worker 在线」。若 SUT 语义是 `if not await _check_worker_online(): 503`，此替身「碰巧」通过；一旦改写为显式布尔返回，替身语义就错。**建议**：改 `new=AsyncMock(return_value=True)` 显式声明意图。
- 同类：`:242 fake_pool = AsyncMock()`（`fake_pool.enqueue_job.call_args` 校验**是**有效断言，属 OK）。

**扫描结果（AST，1315 个用例）**：
- `assert True` / `pass-only`：**0 个** ✅（符合 L9 门禁「无 assert True」）
- **无任何 `assert`/`pytest.raises` 的用例：26 个**。其中多为合理的「does-not-raise」型（`test_audit_failure_does_not_raise`、`test_stockout_create_without_plan_rows_does_not_raise`），但下列偏弱、等价于「不崩即过」，对逻辑正确性无捕获力，建议补返回值/副作用断言：
  `test_validate_not_self_approval_passes`、`test_order_status_machine::test_valid_statuses`、`test_material_registration::test_computed_status_pending`、`test_product::test_delete_product_success`、`test_stock::test_delete_stockin_success`、`test_staging::test_delete_staging_order_success`、`test_purchase_center::test_get_products_statistics`。

**严重度：🟡**（数量可控，多为有意为之的 smoke）。

---

## 1c. `conftest.py` 无真实 DB fixture → 集成盲区（**关键**）

### 事实

**(A) 主套件 `fastapi_app/tests/conftest.py`：DB 100% mock。** `mock_db = AsyncMock()`，`override_deps`(:99) 用 mock 覆盖所有 DB 依赖，并在 :158-167 patch `fastapi_app.core.database.async_engine=None`、`_AsyncSessionLocal=None`。**主套件从不触真库**。少数文件另起 sqlite 内存库（如 `test_beile_orders.py:42`），但 sqlite 不编译 PG 专有类型（JSONB），且仅建局部表。

**(B) 旧套件 `tests/conftest.py`：连真库，但 schema **绕过 Alembic**。**

```python
# tests/conftest.py:142-171
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, ...)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)      # ← 从「模型」直建 schema
```

### 结论：**「代码已部署、迁移未执行」类故障，现有测试无法发现** 🟠

因为 `Base.metadata.create_all` 是**从当前模型对象反推建表**，与 Alembic 迁移链**完全解耦**：
- 场景「代码已含新列、migration 未跑、生产库仍旧 schema」→ 测试库会用 `create_all` 建出**新列**，测试全绿；生产却抛 `UndefinedColumnError`。
- 唯一能兜住的手段是「跑 `alembic upgrade head` 后断言结果 schema == 模型」的**迁移一致性测试**，或对**已迁移真库**的 smoke。**当前默认套件两者皆无**（`test_adversarial_milestone_contracts.py:207` 等也只是 sqlite）。
- 注释本身（:163-164）提到 `create_all` 对旧表「不补新列导致列漂移（product.default_bom_label）」——**佐证历史上确实吃过这类亏**，但修法是「整库重建」，仍未解决「模型 vs 迁移」一致性。

**建议（可落地）**：新增 `tests/migration/test_schema_matches_models.py` —— 起临时库跑 `alembic upgrade head`，用 `inspect()` 对比 `Base.metadata` 的表/列集合，断言零差异；把它纳入默认门禁。这是唯一能在 CI 拦截该故障类的方式。

---

## 2. 既有失败复核 + 治理方案

### 记录基线（`deliverables/ERP_架构优化方案.md`）
> 全量 `fastapi_app/tests tests`：2706 passed / **12 failed / 2 errors**，均判为「既有环境依赖失败」，与本轮改动无关。

### 今日单文件实测（**与记录集合不一致**）

| 文件 | 记录 | 今日实测 |
|---|---|---|
| `tests/test_p4_deep_optimizations.py` | ✗3（TestRequestIdMiddleware×3） | **4 failed, 6 passed**（TestRequestIdMiddleware×3 + `TestDatabaseSlowQueryRegistration::test_module_imports_slow_query_setup`） |
| `tests/test_health_check.py` | 失败（需真服务） | **2 passed** ✅ |
| `tests/test_multi_sku_inventory_stats.py` | 失败（需真服务） | **4 passed** ✅ |
| `tests/test_numbering_sequence_integration.py` | 失败 | **2 errors**（collection/夹具错误） |
| `tests/qa/test_smoke.py` | 失败 | **28 passed** ✅ |
| `tests/qa/test_database.py` | 失败 | **1 failed, 9 passed**（`TestBatchInsert::test_insert_100_products`，SQLAlchemy 报错） |

**观察**：部分「既有失败」今日转绿（说明是**环境态**而非代码态，如在线服务是否在跑）；`test_p4` 反而多出 1 条红。**结论：基线不可复现，无法可靠区分「新失败 vs 既有失败」。**

### 是否有新增失败？
- 由于基线不可复现 + 全量跑有 event-loop 污染，**无法给出可信的「新增失败数」**。只能在单文件维度确认：`test_p4` 的 `test_module_imports_slow_query_setup` 是否属新增待单独定位（该用例名指向「模块导入触发 slow-query setup」，`create_all`/引擎 patch 变化敏感）。

### 治理方案：长期红 = 没有测试套件 → 转 `xfail(strict=True)`
1. **默认套件必须常绿**：把「需真库/真 nginx/真后端」的用例打 marker（如 `@pytest.mark.live`/`@pytest.mark.needs_db`），`pytest.ini` 默认 `addopts` 加 `-m "not live and not needs_db"`；CI 默认跑绿。
2. **已知环境依赖失败**：改 `@pytest.mark.xfail(strict=True, reason="needs live PG/nginx — issue #NNN")`。
   - `strict=True` 的意义：**一旦环境就绪、测试转为通过，xfail 会 fail**，强制有人回来摘掉标记——避免「红久了就没人看」。
   - 必须附 issue 链接（L9 门禁已要求「skip/xfail 须附 issue 跟踪链接」）。
3. **禁止无理由长期红**：`test_p4_deep_optimizations.py` 的 `TestRequestIdMiddleware`×3（隔离运行返回 400 而非 200）应就地修或 xfail 并立案，而不是留在「既有失败」桶里。
4. **基线快照化**：把「默认套件预期全绿」写入 CI 门禁（脚本 `scripts/quality_gate.py` 已存在，可复用），使「新增红」= 明确信号。

**严重度 🟠**：当前状态是「有一堆红但不影响发布决策」，即套件已部分丧失信号价值。

---

## 3. 覆盖率（读 `.coveragerc` 口径 + `.coverage` 实况）

- **口径**：`.coveragerc` `source = fastapi_app`，omit `*/tests/* */migrations/* */scripts/* */frontend/* …`；`report.exclude_lines` 含 `pragma: no cover` 等。分级阈值见 `evidence/gate_logs/L9/summary.md`：核心≥85% / 备份≥80% / 来料≥75% / 仪表盘≥70%。
- **实况（关键）**：
  - 根目录存在 `.coverage`（SQLite，coverage 7.13.5），但 `select path from file` **仅 2 条**：
    `fastapi_app/services/backup/records.py`、`fastapi_app/services/backup/verify/query_service.py`。
    → 这是**某次定点跑残留**，**不代表全量覆盖率**，若被当作「覆盖率证据」会严重误导。
  - 当前解释器 **未安装 `coverage` / `pytest_cov`**（`find_spec` 皆 False）→ 无法复算。
  - `pytest.ini` `addopts` **无 `--cov`**，**无 `--cov-fail-under`** → 覆盖率**不进任何门禁**。
- **判定**：**覆盖率目前「未运作」**，L9 的分级阈值只是纸面标准。🟠
- **建议**：CI 装 `pytest-cov`；`addopts` 增 `--cov=fastapi_app --cov-report=term-missing --cov-fail-under=<分级>`；把 `.coverage` 从版本库移出（gitignore），避免陈旧产物误导。

---

## 4. 契约快照有效性

- **机制**（`tests/contract/test_api_contract.py` + `scripts/contract_snapshot.py`）：唯一真相源是脚本的 `--check`，测试只断言其结论；三层守卫：
  1. `test_contract_snapshots_exist` —— 快照存在性（**21 份**快照实存：approvals_*/customers_list/dashboard_*/health/plans_*/products_*/purchase_center_*/reports_order_logs/stock_*/suppliers_list）；✅
  2. `test_snapshots_contain_no_raw_response_body` —— 白名单键守卫，防业务数据进 git；✅
  3. `test_contract_snapshots_match` —— `@needs_backend`，未设 `CONTRACT_BASE_URL` 整块 skip（**设计上正确**）。✅
- **有效性评价**：**机制是健康的**（白名单 + 单一真相源 + 变更指引齐备），远好于「手工维护两份规则」。
- **缺口**：快照**未覆盖备份端点**（无 `backup_list.json` 等）——正是 1a 的 `list_backup_files` 形状所在。若当年备份列表进了契约快照，`mtime`/`name` 漂移会被更早拦截。🟡
- **历史「4 处失真」**：追到 `_c4c.txt` 提交信息——`docs(bom-multi-role): 修正契约快照 4 处失真`，属**文档描述失真**（引用了不存在的 `docs/contract` 路径、对「已同步快照」的不实陈述），**非快照数据本身失真**，且已修正。当前快照数据未见失真证据。
- **建议**：把 `GET /backup/list` 等备份端点纳入契约快照，形成对 1a 类字段漂移的第二道护栏。

---

## 5. 对抗性测试捕获力抽查（判据：回滚修复后是否变红）

方法：临时改回修复前代码 → 单跑对应用例 → 立即还原（已校验 `restored=True`）。

| 对象 | 回滚动作 | 结果 | 判定 |
|---|---|---|---|
| `test_cors_origin_production_filter.py` | `config.py:_is_production_allowed_origin` 去掉内网 IP 放行（退回「仅 https + localhost」） | **8 failed, 9 passed** | ✅ 捕获力强 |
| `test_auth_helpers.py` | `auth.py:159` 把 `if _burst>LOGIN_BURST_LIMIT` / `if _attempts>LOGIN_ATTEMPT_LIMIT` 阈值调到 `10**9`（等于不限流） | **2 failed, 11 passed**（两条 429 用例变红） | ✅ 捕获力有效 |
| `test_backup_validation_helpers.py`（1a） | `records.py:216` 删 `'mtime'` | **1 failed**（recent→warning） | ✅ 有效 |

**结论**：这三个「有明确修复」的模块，测试都具备真实回归护栏，**不是「写得像测试」的空壳**。CORS 用例尤其扎实（含 `192.168.0.95.evil.com` 前缀仿冒、公网明文拒收等对抗项）。

**关于 skip**：全测试树仅 `test_cors_origin_production_filter.py:103`（`.env` 缺失时 skip 并说明原因）、`test_product_list_cache_qa.py:168`、`test_qa_prod_stack_regression.py`（3 处 live skipif）使用 skip —— 均带 reason，**未见静默通过**。`pytest.ini` 设 `filterwarnings = error`（除 UserWarning/DeprecationWarning）——质量门偏严，👍。

---

## 附录 · 证据文件（均为本次落盘）

| 文件 | 内容 |
|---|---|
| `deliverables/engineering-assurance/_t1a_run.txt` | `test_backup_validation_helpers.py` 全量单跑输出（**27 passed**） |
| `deliverables/engineering-assurance/_t2_baseline.txt` | 既有失败文件单文件复核输出（含 RC 与计数） |
| `_t3_diff.txt`（仓库根） | 1a 修复的完整 git diff（producer 加 `mtime`、consumer `name`→`filename`、test `name`→`filename`）|

### 关键 `文件:行` 索引
- 生产者：`fastapi_app/services/backup/records.py:192`（def）/ **:216**（entry 键）
- 消费者：`fastapi_app/api/v1/endpoints/backup/validation.py:156-158`（mtime）/ :186（filename）
- E2E 测试：`fastapi_app/tests/test_backup_validation_helpers.py:131`（_use_real_dir）/ :143（recent 用例）
- 残留：同文件 :132-136（陈旧 docstring）/ :205,:215（integrity 仍 mock）
- 真库绕过 Alembic：`tests/conftest.py:171`（`Base.metadata.create_all`）
- 主套件全 mock DB：`fastapi_app/tests/conftest.py:99`（override_deps）
- CORS 规则：`fastapi_app/core/config.py:85-106`
- 登录限流：`fastapi_app/api/v1/endpoints/auth.py:159-190`
- 契约：`tests/contract/test_api_contract.py` + `scripts/contract_snapshot.py`
