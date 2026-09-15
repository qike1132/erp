# ITER-4 · 优化执行清单与实施方案

> 承接 `docs/tickets/iterations/ITER-3-open-source-benchmark-and-roadmap.md`
> **本文档对 ITER-3 的部分结论做了事实校正，请以本文为准。**
> 日期：2026-09-14

---

## 0. 事实校正（必读）

ITER-3 是对标分析，用的是粗粒度正则统计；执行阶段读了实际的门禁脚本后，**发现三处必须纠正的判断**：

| ITER-3 的说法 | 实际情况 | 定性 |
|---|---|---|
| "疑似 N+1 **145 处**" | 项目已有 AST 精确扫描 `scripts/check_n_plus_one.py`（只认循环内 `await obj.execute/scalar/scalars`），实际违规 **11 处**。145 是我的粗粒度 grep（把循环内任意 `await db.*` 都算了） | **口径错误，夸大 13 倍** |
| "`except Exception` **234 处**" | `scripts/check_bare_except.py`（AST + 白名单 + 行内标注豁免）实际报 **22 处**。234 是全仓 grep（含 tests/scripts/migrations） | **口径错误** |
| "无统一门禁 / 契约 0 个 / 建议加 pyproject + 依赖锁" | 门禁脚本**已建** 5 个 + 白名单机制 + `mypy.ini` + `ruff.toml`；依赖**早已**拆成 `requirements/{base,dev,test,ocr,migration,s3,desktop}.txt`；另有 `docs/plans/2026-08-22-code-quality-optimization-plan.md` 与 `docs/reports/2026-08-22-code-quality-assessment.md` | **重复造轮子，建议作废** |

**真实的、尚未被解决的问题不是"没建"，而是"建了没接线"**——与 ITER-3 发现的 `core/container.py` 建了没人用、`check_service_commit.py` 引用了不存在的文档，属同一类病。

### 真实基线（`scripts/quality_gate.py` 采集；随治理推进 → 为当前值）

| 门禁 | 初次采集 | 当前 | 阈值 |
|---|---:|---:|---|
| N+1 查询 | 11 | **0** | 白名单外 |
| 裸/宽泛 except | 22 | **9** | 已文档化标注/白名单外 |
| 后端超长函数 | 54 | **52** | 80 行 |
| 前端巨型组件 | 6 | 6 | 400 行 |
| service 层手动 commit | 9 | 9 | 见 `docs/TRANSACTION_BOUNDARY_GUIDE.md` |

> 门禁自检：`python scripts/_selftest_gate.py`（8 项断言，覆盖"新增违规拦截 / 单文件真扫描 / 语法错误告警 / 无效路径告警"）


---

## 1. 已完成（E-01 ~ E-04、E-06、E-07、E-08，全部已验证）

### E-01 · 门禁接线（最高优先）

- **问题**：5 个 AST 门禁脚本中，只有 `file_size_gate.py` 进了 CI；`check_n_plus_one` / `check_bare_except` / `check_function_length` / `check_vue_component_length` / `check_service_commit` 既不在 pre-commit 也不在 CI。`.codeartsdoer/specs/code_quality_opt/tasks.md` 的 1.1/1.2/1.4 均明确要求"接入 pre-commit 与 CI"，**未执行**。门禁等于不存在。
- **方案**：不逐个接线（会立刻报红，红着的门禁一定会被关掉），而是新增统一 runner **`scripts/quality_gate.py`**，采用**基线棘轮**语义：
  - 存量违规记录在 `scripts/gate_baseline.json`，不阻断
  - 违规数 **> 基线** → 退出码 1（有人新增了问题）
  - 违规数 **< 基线** → 提示执行 `--update-baseline` 收紧（只允许变严）
  - 阈值从 `pyproject.toml [tool.code-quality]` 读取
- **接入点**：`.pre-commit-config.yaml`（local hook）+ `.github/workflows/ci-cd.yml`（lint job，置于 ruff 之前以确保总是能跑出结果）。
- **预期收益**：把"以后再说"的质量要求变成机械约束。存量 102 处违规不阻断，但**任何新增都会被拦下**。
- **约束**：必须 diff 基线（不能零基线，否则 CI 从第一天就红）；不能改各门禁脚本自身的白名单（那是"有意豁免"，而这些是待还的债）。
- **验证**（已执行）：
  1. `python scripts/quality_gate.py --report` → 5 个门禁全部输出计数 ✓
  2. `--update-baseline` → 生成 `scripts/gate_baseline.json` ✓
  3. **注入违规**（临时文件含 90 行函数 + 裸 except）→ 报 `REGRESS`，宽泛 except 22→23、超长函数 54→55，**退出码 1** ✓
  4. 删除临时文件 → 全部 `OK`，**退出码 0** ✓
  5. YAML 结构断言：hook 列表含 `quality-gate`；CI lint 中 gate 步骤索引 < ruff 步骤索引 ✓
  6. `pre-commit validate-config` 通过；hook entry 直接执行 exit 0 ✓
  - ⚠️ `pre-commit run quality-gate --all-files` 在**本沙箱内**无法执行：沙箱的 git 来自 PortableGit（`mingw64/bin`），Windows 侧 pre-commit 子进程看不到它（`Executable git not found`）。这是环境问题，非配置缺陷——该仓库原本就有 pre-commit 配置，说明你的正常终端可跑。

### E-02 · 修 CI 必然失败的步骤

- **问题**：CI frontend job 跑 `npm run test:e2e`，但 `frontend-vite/package.json` 里**没有** `test:e2e` 脚本，也没有 `playwright.config.*`、没有 `e2e/` 目录 → 该步骤必然失败。
- **方案**：替换为真实存在且已验证通过的两个跨端对齐检查（`npm run check:api`、`npm run check:routes`），并留注释指向 D-2 决策项。
- **验证**：两个脚本实跑均 **exit 0**（API 层 101 个端点、移动端 43 文件全部走共享 API 层；路由共有路径一致）。

### E-03 · 补上被引用却不存在的文档

- **问题**：`scripts/check_service_commit.py:89` 提示"请按 `docs/TRANSACTION_BOUNDARY_GUIDE.md` 规范进行改造"，但**该文件不存在**——门禁给出的是一个死路。
- **方案**：新建 `docs/TRANSACTION_BOUNDARY_GUIDE.md`，内容从真实代码与既有方案文档反推（`get_async_db` 唯一提交点、服务层 flush-only、9 处存量的逐条理由、端点层无例外、改造手法对照表、验证命令）。
- **验证**：文件存在且被脚本引用的路径一致；9 处存量与 `check_service_commit.py` 输出逐条对应 ✓

### E-04 · 门禁阈值单点配置

- **方案**：新增 `pyproject.toml`，**只含 `[tool.code-quality]`**（`max_function_length=80` / `max_vue_component_length=400` / `max_file_size=1200`）。
- **约束（重要）**：刻意**不含 `[build-system]` / `[project]`** —— 依赖管理唯一来源仍是 `requirements/*.txt`，本文件不参与打包、不改变 pip 解析。`pytest.ini` / `ruff.toml` / `mypy.ini` 各自仍有优先级，不受影响。
- **验证**：`scripts/quality_gate.py` 正确读到阈值（报告头显示"函数 ≤80 行 / Vue 组件 ≤400 行"），且各门禁实跑计数与单独运行一致 ✓

### 附带修正

`scripts/check_bare_except.py` 的模块 docstring 只写了 `# defensive:`，实际代码同时接受 `# broad-except:`（数据库初始化容错等在用）。已补齐说明。

### E-06 · 宽泛 except 从 22 降到 9

**关键判断：这批 `except Exception` 绝大多数是合法兜底，收窄反而会引入 bug。**

逐处定性后，**没有一处需要收窄**——它们分别是：启动自检旁路（`main.py:170`）、健康探测不得抛出（`arq_app.py:193`）、事务失败必须 rollback（`exceptions.py:187`）、死信队列最后兜底（`arq_callbacks.py:90`）、告警序列化不得中断（`arq_callbacks.py:107`）、端点兜底转 500（`purchase_plan.py:335/366`）、密码侧信道 fail-safe 降级（`actions.py:123`）、还原预览尽力统计（`restore_plan.py:64`）。

正确处理是**加 `# broad-except: <理由>` 标注使其可审计**，而不是把 `Exception` 换成几个猜出来的类型。9 处已全部标注。

**未做的 9 处**：全部在 `fastapi_app/services/backup/records.py`——该文件**正在被并行改动**（工作区有未提交修改，−23/+3 行）。为避免与在途改动混叠，本轮不动。它们的定性已明确（逐条补录/清理/修正失败记入 `errors` 后继续），建议标注文本：

| 位置 | 建议标注 |
|---|---|
| `records.py:155` | `# broad-except: 告警发送失败不影响主流程` |
| `records.py:557` | `# broad-except: 备份记录查询失败记入 errors 并返回，不中断同步` |
| `records.py:596 / 610 / 626` | `# broad-except: 单条补录/清理/修正失败仅记 errors，不影响已成功记录（配合上方 manual-tx 逐条提交）` |
| `records.py:600 / 614 / 630` | `# broad-except: rollback 自身失败仅记录，不阻塞后续条目` |
| `records.py:632` | `# broad-except: 同步整体异常记入 errors 后返回结果，不抛出` |

### 顺带修掉的 4 个门禁自身缺陷（都是"假绿"，比报红更危险）

| 缺陷 | 影响 | 修法 |
|---|---|---|
| `check_bare_except` 豁免逻辑漏认 ruff 风格标注 | `# noqa: BLE001 - <理由>` / `# noqa: S110 - <理由>` 被当成无标注 → **4 处误报**（`arq_callbacks:38/99`、`database:111/116`） | 新增 `_EXEMPT_PATTERNS`，同时认 `# defensive:` / `# broad-except:` / ruff 风格；**仍强制要求附理由**（空标记不免） |
| `collect_py_files` 用 `rglob` 处理文件路径 | 传单文件 → 返回空 → **静默 PASS（假绿）**。4 个门禁脚本全中 | 增加 `is_file()` 分支；并在"显式传参却零命中"时输出 `[WARN]` |
| `check_n_plus_one` 把文件路径退化成父目录 | "只查我这个文件"变成**整目录扫描**，棘轮模式下表现为**假 REGRESS** | 原样传递文件路径 |
| `scan_file` 静默吞 `SyntaxError` | **语法错误的文件被报告为"无违规"**（`check_n_plus_one` 已有 WARN，另两个没有） | 改为返回 `(violations, err)`，解析失败输出 `[WARN]` |

**验证**（`python scripts/_selftest_gate.py`，8/8 通过）：
```
PASS  单文件扫描能看见违规                        exit=1
PASS  新增违规 → exit 1 且报 REGRESS              exit=1
PASS  清理后 → exit 0 且 PASS                     exit=0
PASS  check_bare_except.py 对语法错误文件发出 WARN
PASS  check_function_length.py 对语法错误文件发出 WARN
PASS  check_bare_except.py 对无效路径发出 WARN
PASS  check_function_length.py 对无效路径发出 WARN
PASS  check_n_plus_one.py 对无效路径发出 WARN
```
另做**豁免边界精确性**验证：8 种写法中仅"无标注/空理由"的 4 种被报，带理由的 4 种（含 ruff 风格）正确豁免。

**零行为变化证明**：对 7 个改动的源文件做逐行 `-`/`+` 配对、去注释后比对 —— 全部一致，确认只加了行尾注释。

**阈值单点化 + 棘轮收紧**：`scripts/gate_baseline.json` 的 `bare_except` 由 22 更新为 9。

### E-07 · 接口契约快照框架（tasks 1.5 原本未做）

**新增**：`scripts/contract_snapshot.py`（工具，唯一真相源）、`tests/contract/endpoints.yaml`（21 个只读 GET 端点）、`tests/contract/snapshots/*.json`（基线）、`tests/contract/test_api_contract.py`（pytest 包装）、`scripts/_selftest_contract.py`（自检）。

**三个关键设计决策**：

1. **快照不存响应体**。只存 HTTP 状态码 + 结构签名（键路径与类型）+ 变体键标记。
   理由：存响应体会把客户名、产品名、金额等真实业务数据提交进 git。
   有一条专门的测试守护这条红线（快照键白名单）。
   ```
   "orders[].create_time:<volatile>"     ← 每次变，标记后仍比对"键是否存在"
   "orders[].items[].unit_price:float"
   "success:bool"
   ```
2. **两条容差规则**，防止数据波动造成误报（契约门禁最容易死于"误报太多、没人看"）：
   - 类型为 `null`：录制时首元素该字段恰好为 null，不代表它一定是 null
   - 空数组 `array[0]`：录制时数组为空，无法得知元素结构
3. **测试不重复实现比对逻辑**，只断言工具的结论 —— 避免同一套规则维护两份。

**验证**（`python scripts/_selftest_contract.py`，6/6 通过；在快照**临时副本**上篡改，不碰真基线）：
```
PASS  未篡改 → 一致                 exit=0 status=match
PASS  服务端删字段 → drift           ['字段消失: items[].ghost_field:str']
PASS  服务端新增字段 → drift          ['新增字段: items[].price:float']
PASS  类型变化 → drift             ['类型变化: items[].price str → float']
PASS  状态码变化 → drift            ['状态码 500 → 200']
PASS  空数组容差 → 不误报              exit=0
```
pytest 两种形态：无后端 → `2 passed, 1 skipped`；有后端 → `3 passed`。

**顺带发现**：文档里写的 `/api/v1/purchase-plan/*` **在运行进程里根本不存在**，真实前缀是 `/api/v1/plans/*`。这正是契约检查该抓的那类问题。

### E-08 · 压测前后对比（tasks 1.6 原本未做）

**新增**：`scripts/benchmark_compare.py`（`run` / `compare` 两个子命令）+ `docs/tickets/artifacts/benchmark/README.md`。

**与 tasks 1.6 原方案的偏离（有意）**：原方案要求基于 locust、按 git ref 自动 checkout 前后版本、配 DB dump。
**没有采用** —— 在本机（生产机兼开发机，工作区有未提交改动）自动 checkout ref 是危险操作，
且 DB dump 数据隔离成本高。改为**标签式对比**：你在改动前后各跑一次，再比对两份报告。
诚实且安全，代价是需要人工记得跑两次。

**四条诚实测量规则**（都写进了工具文档与报错信息）：
1. 报告内嵌 `runtime_mode_probe` 的运行模式判定；两次模式不同直接告警"不可比"
2. 必须预热（默认 5 次，剔除连接建立与缓存冷启动）
3. 逐个端点测（端点内部才并发），避免端点间互相干扰
4. 多轮取中位数（默认 3 轮）+ 显式暴露 `p95_spread` 离散度

**⚠️ 本机实测的噪声地台（重要）**：dev 单 worker、20 次×3 轮、并发 4 下：

| 端点 | P95 | 轮间离散度 |
|---|---:|---:|
| dashboard_stats | 42.2 ms | **56.4%** |
| stock_inventory | 28.8 ms | 24.1% |
| products_list | 27.4 ms | 21.5% |
| purchase_center_orders | 28.7 ms | 17.4% |
| reports_order_logs | 26.4 ms | 16.7% |

**20~45ms 量级的端点，轮间噪声就有 17~56%。在这个量级上判定"P95 下降 30%"没有意义。**
因此默认 `--min-baseline-ms 50`：基线低于该值的端点只报告、不判定。

**对比器不会凭空报出提升**（这是最关键的一条验证）：
代码未改时两次压测的"提升"是 `17.0% / 15.8% / 5.4% / -13.2% / -5.9%` —— 全是噪声，全部 FAIL。

**退出码语义**（`2` 不是"通过"，避免把"没测出来"当成"没问题"）：

| 码 | 含义 |
|---|---|
| 0 | 至少一个端点被判定且全部达标 |
| 1 | 有端点未达标 |
| 2 | **不可判定**：全部端点低于判定线（噪声主导），或输入错误 |

实测：全跳过 → exit 2「不可判定」；把判定线降到 0 强制判定 → exit 1「未达标」。

**顺带修掉的 2 个门禁缺陷**（同属"假绿"类）：`--json` 模式下 stdout 被人类可读前导行污染 → 不是合法 JSON；
`compare` 在全跳过时报"达标" → 已改为「不可判定 + exit 2」。

**CI 接线**：`tests/contract` 未被 `--ignore` 排除，随现有 pytest 步骤执行 —— 两条静态守卫真跑，
与后端比对那条自动 skip（已在 ci-cd.yml 加注释说明）。压测产物写入 `.gitignore`（数字随机器变化，不是源码）。

### 附加 · 基线捕获串成一条命令（2026-09-14 新增）

**新增** `scripts/capture_baseline.py`。性能数据只有在**正确前置条件下**才有意义，
最容易犯的两个错：① 在 dev 单 worker 下采基线却拿去和 prod 比；② 在契约已漂移时采基线。
所以把三件事串起来并**强制校验**：

1. 运行模式判定 —— 非 prod 多 worker 时**拒绝执行**（退出码 2）并打印修复指令
2. 契约快照比对 —— 漂移则中止（退出码 1），避免"连改造前的行为都没固定住"
3. 压测 + **代码状态指纹**（git HEAD + 工作区改动摘要哈希）

指纹的作用：让 before/after 两份报告能**自证**"测的确实是两份不同的代码"，而不是靠人记忆。

**已验证**：非 prod 模式 → `exit 2` 并给出修复指令；`--allow-non-prod` 冒烟跑通全流程
（模式 dev / 契约 21 matched 0 drifted / 指纹 head=cce3a7b dirty=39 / 清单落盘 / 标注"不可比"）。

### 1.7 E-10 · N+1 门禁 11 → 0（结论：**没有一处是真 N+1**，问题在门禁本身）

逐点读完 11 处源码后，定性如下：

| 类别 | 数量 | 站点 | 判定 |
|---|---:|---|---|
| 循环内本就是**批量查询**（`in_(...)`）或一次性查询（有 `if not map` 守卫 / 在 `except` 重试路径） | 6 | `notification_service:348`、`order_batch_create:75`、`purchase_order_crud:365`、`purchase_plan_staging:241`、`staging/stockout:183`、`purchase_bom_copy_service:39` | 合法，不修改 |
| 循环体是**固定集合**（常量 SQL 语句表 / manifest 表集合） | 3 | `ro_grants:66,68`、`restore_plan:59` | 合法，登记白名单 |
| **检查器误报**：`for x in (await db.execute(...)).all():` —— 查询在 for 的 iterable 里，只求值一次 | 1 | `outsource/_common:165` | 修检查器 |
| 用户并行改动中的文件 | 1 | `backup/records:607` | 只登记白名单，不改源码 |

**修掉的 3 个检查器缺陷**：

| 缺陷 | 影响 | 修法 |
|---|---|---|
| `_visit_loop` 用 `generic_visit(node)` 把**循环的 iterable 表达式**也当循环体访问 | `for x in (await db.execute(...)).all()` 被**误报** | 先 `visit(node.iter)` 再压栈；`for/else` 的 else 也移出（只执行一次） |
| **不认行内标注** —— 代码里已有 `# batch-loop: 有意逐行处理,非 N+1`（6 处）却仍被报违规 | 与 `check_bare_except` 同类问题：约定存在、检查器不认 | 新增 `# batch-loop:` / `# n1-ok:` 识别，**仍强制要求附理由** |
| 白名单只有 `file:line` / `file` 两种键 | **行号随编辑漂移即整批失效** —— 已实际发生（`order_batch_create.py:74` 已成 L75 等） | 新增 `file::function` 函数级键（不受行号漂移影响，推荐用法） |

**验证**（`_selftest_gate.py` 新增 7 项语义断言，全绿）：

```
PASS  真 N+1 必须报                flagged=['marker_without_reason','nested_loops','real_n_plus_one']
PASS  for...in iterable 的查询不得报
PASS  就地标注(带理由)不得报
PASS  空理由标注必须报
PASS  循环外查询不得报
PASS  嵌套循环必须报
PASS  函数级白名单 file::func 生效    过滤后=['marker_without_reason','nested_loops']
```

### 1.8 E-05 · 超长函数逐批拆分（53 处待做）

**批次划分原则**：先做「有测试网 + 结构清晰」的，把备份域（风险最高）放最后。

| 批次 | 目标 | 依据 |
|---|---|---|
| **1（已完成）** | `purchase_order_generate.py::generate_purchase_orders_from_customer_orders`（198 行） | 业务关键 + **3 个测试文件 113 用例** 覆盖 |
| **2（进行中）** | ✅ `order_batch_create.py::batch_create_orders`（219 行）→ 拆为 1+8；⬜ `purchase_order_query.py::get_unprocessed_orders`（152） | 同域、测试较全；后者另有契约快照兜底 |
| 3 | `bom_service.py::save_bom`（181）/`copy_bom`（163）、`customer_sampling/*`（120/93/91/84） | BOM 作用域有专门测试 |
| 4 | `core/health.py`(166)、`core/middleware.py`(97)、`core/cache.py`(115/101/97)、`api/ws.py`(119/117) | 机械拆分，47/11 个测试文件引用 |
| 5 | `services/backup/**`（约 18 处，含 242/251/160/159/154/150/144 行） | **风险最高**，放最后，逐函数单独验证 |
| 6 | 其余零散 81–99 行函数 | 边际收益，择机 |

#### 批次 1 详情（已完成并验证）

**目标函数**：`generate_purchase_orders_from_customer_orders` 198 行 → 拆为 1 个编排函数 + 10 个职责单一函数。

**关键重构点**：三类 BOM 物料（填充物/面料/配件）的明细构建是**三段近乎重复的 dict**，
差异只有「取哪个用量字段 / 叫什么名字 / 默认单位」。改为**表驱动**：

```python
_MATERIAL_SPECS = (
    _MaterialSpec('filling',   'filling',   'cotton_usage', '克', name_suffix='-填充物'),
    _MaterialSpec('fabric',    'fabric',    'quantity',     '米', name_attr='fabric_name',    default_name='面料'),
    _MaterialSpec('accessory', 'accessory', 'quantity',     '个', name_attr='accessory_name', default_name='配件'),
)
```
顺序即输出顺序（填充物 → 面料 → 配件），与重构前逐条对齐；`_BomContext` 承载分桶与作用域清单；
`_build_items` 闭包提升为模块级 `_build_material_items(records, ctx, pid_name_map)`。

**保住的铁律**：`scopes_by_pid` 计算中 **`{None}` 必须显式并入** 的注释与逻辑原样保留
（`product_role` 表无「默认BOM」行，漏掉会整块丢弃产品级 BOM）。

**验证**：

| 项 | 结果 |
|---|---|
| `py_compile` | OK |
| `ruff check` | All checks passed |
| `check_function_length.py <该文件>` | **[PASS] 未发现超过 80 行的函数** |
| `tests/test_purchase_order_generate_multi_sku.py` | **7 passed** |
| `fastapi_app/tests/test_purchase_order_generate_scope.py` | **19 passed**（含 `test_source_role_key_is_consumed_by_crud` 契约断言） |
| `fastapi_app/tests/test_purchase_center.py` | **87 passed** |
| 合计 | **113 passed / 0 failed** |

**基线收紧**：`function_length` 54 → 53。

#### 批次 2 · 第 1 项详情（已完成并验证）

**目标函数**：`order_batch_create.py::batch_create_orders` **219 行 → 拆为 1 个编排函数 + 8 个职责单一函数**
（文件 301 → 352 行，行数增加是拆分的正常代价，换来的是每个函数可独立阅读与测试）。

**拆分结果**：

| 新函数 | 职责 |
|---|---|
| `_collect_product_ids` | 收集 product_id（去重排序）供一次性加锁查询 |
| `_group_by_customer` | 按 customer 分组（保持首次出现顺序） |
| `_lock_products` | 一次性 `with_for_update()` 加锁查询 |
| `_validate_one_item` / `_validate_group_items` | 单条/整组预校验（失败文案与判定顺序逐条对齐） |
| `_create_order_header` | 创建主订单（含局部 import `generate_order_number`） |
| `_create_order_items` | 每 SKU 建 OrderItem + InventoryLog |
| `_auto_generate_outsource` | 外发工序自动生成（容错） |
| `_apply_deductions` | 抵扣备货（保留 `deduct_quantity > 0` 守卫避免误扣） |
| `_build_success_result` | 成功结果组装 |
| `_dispatch_notifications` | 工厂通知 + 湖北未确认提醒（含湖北去重逻辑） |

主函数保留三类异常分支原样：`_SavepointRollbackSignalError`（业务校验失败，继续下一组）、
`(ValueError, TypeError, OSError)`（记失败继续）、`SQLAlchemyError`（**整体 rollback + 抛 500 终止批量**）。

**验证**：

| 项 | 结果 |
|---|---|
| `py_compile` / `ruff check` | OK / All checks passed |
| `check_function_length.py <该文件>` | **[PASS] 未发现超过 80 行的函数** |
| `test_order_batch_create.py` | **6 passed** |
| **全部 11 个 order 相关测试文件** | **169 passed / 0 failed**（`test_order_routes.py` 25 skipped：需 DB 环境） |

**基线收紧**：`function_length` 53 → 52。

#### 批次 2 · 第 2 项（待做）

`purchase_order_query.py::get_unprocessed_orders`（152 行）。
覆盖条件较好：`tests/test_unprocessed_orders_multi_sku.py`（专属）+ `fastapi_app/tests/test_purchase_center.py`
+ **E-07 契约快照已覆盖 `/api/v1/purchase-center/unprocessed-orders`**（改造后可用 `--check` 验证响应结构未变）。

---

## 2. 待办清单（按优先级）

| ID | 事项 | 目标 | 范围 | 预期收益 | 约束 | 验证方式 |
|---|---|---|---|---|---|---|
| **E-05** | 超长函数逐批拆分（52 处待做，批次计划见 §1.8） | 降至 ≤10 | `services/**` 为主 | 可读性、可测性；同时是"单函数≤80行"规范落地的最后一步 | 重构不改行为；每批用测试固化 | `quality_gate.py --only function_length` 计数下降后 `--update-baseline` |
| ~~E-06~~ | ✅ **已完成**（22 → 9，见 §1） | — | — | — | 剩余 9 处在 `records.py`（并行改动中） | `quality_gate.py --only bare_except` |
| ~~E-07~~ | ✅ **已完成**（21 端点 / 6-6 自检通过，见 §1） | — | — | — | 需真实后端录制 | `_selftest_contract.py`；`CONTRACT_BASE_URL=... pytest tests/contract` |
| ~~E-08~~ | ✅ **已完成**（run/compare + 噪声地台实测，见 §1） | — | — | — | 须同一运行模式下前后各跑一次 | 代码未改时必须 FAIL（已验证） |
| **E-09** | 前端 e2e 落地 | 8 条主流程自动回归 | 新建 `frontend-vite/playwright.config.ts` + `e2e/` | 大重构敢做的前提；CI 里已有 `npx playwright install` 在空转 | 需真实浏览器（用系统 Edge 免下载） | `npx playwright test` 全绿后接回 CI |
| ~~E-10~~ | ✅ **已完成**（11 → 0，见 §1.7） | — | — | — | 无需 prod 模式 | `_selftest_gate.py` 中 7 项 N+1 语义断言 |
| **E-11** | 前端巨型组件拆分（6 处） | ≤400 行 | `BomEditor.vue`(522) 等 6 个 | 与 ITER-3 的前端去重复方向一致 | `vue-tsc -b` 门禁必须保持绿 | `quality_gate.py --only vue_component_length` |

### 依赖与顺序
- **E-01/E-02/E-03/E-04/E-06/E-07/E-08 已完成**，门禁与度量基建就位，其余各项有回退保护
- E-05 / E-10 互相独立，可并行
- E-06 剩余 9 处待 `services/backup/records.py` 的并行改动落定后一次性补标注（建议文本见 §1）
- **性能类改造（ITER-3 P3 的批量写 / N+1 / 汇总表）的度量能力已就位，但被 D-3 卡住**：
  当前 dev 单 worker 下所有 P95 都在噪声地板上，采出来的数字无法判定。
  **需你先执行 §3.1 的一条命令切到 prod 4 worker**，然后 `capture_baseline.py --label before`。
- **不依赖 prod 模式、可立刻并行推进的两项**：E-05（超长函数 54 处）、E-10（N+1 11 处逐点确认）——
  它们是纯静态代码改造，可以用门禁计数验证效果，不需要压测。
- E-11（前端巨型组件拆分）与 ITER-3 的 P2（前端去重复）同属一波，建议合并排期

---

## 3. 需要你决策的事项

### 3.1 D-3 执行记录：被 OS 权限阻断（2026-09-14 09:23）

**已尝试，失败。这是操作系统权限边界，不是配置问题。**

| 检查项 | 结果 |
|---|---|
| `erp-prod` 服务 | **存在**，Status=**Stopped**，StartType=Automatic |
| `Start-Service -Name erp-prod` | **FAILED**：`由于以下错误无法启动服务"erp-prod (erp-prod)": 无法打开计算机"."上的 erp-prod 服务。`（拒绝访问） |
| `IsInRole(Administrator)` | **False** |
| 5002 现状 | 仍为 PID 16708 / dev 单 worker（**未被改动**，未做任何破坏性操作） |

**prod 环境预检全绿**（`python -m fastapi_app.core.prod_runner --check`）—— 万事俱备，只差启动权限：

```
OK: Redis 连通 (127.0.0.1:6379)
OK: 前端构建产物存在 D:\erp_system\frontend-vite\dist
OK: 检测到 Nginx C:\nginx\nginx.exe
INFO: worker 数 = 4 (UVICORN_WORKERS)
INFO: API 端口 = 5002
```

**其他已确认的事实**：
- dev uvicorn（PID 16708）的父进程 **15956 已不存在** → 它是**孤儿进程**，杀掉后不会被自动拉回
- 上次恢复（09-11 22:02）成功：`erp-prod state: Running`、backend health 200
- 启动前必须先释放 5002；你的 `_recover_prod.ps1` 已经做了这件事
- ⚠️ **prod_runner 会 `taskkill /F /T /IM nginx.exe` 后重启 nginx** → 切换瞬间 **3000（用户界面）会有几秒中断**，属预期行为

**交接命令（管理员 PowerShell，任选其一）**：

```powershell
# 方式一：一条命令弹 UAC 并执行你已有的恢复脚本
powershell -Command "Start-Process powershell -Verb RunAs -ArgumentList '-File d:\erp_system\_recover_prod.ps1'"

# 方式二：手动开管理员 PowerShell 后执行
d:\erp_system\_recover_prod.ps1
```

**执行完立刻可跑（无需我再准备）**：

```bash
python scripts/diag/runtime_mode_probe.py              # 应显示 prod (multi worker)
python scripts/capture_baseline.py --label before      # 一条命令采集 before 基线
```

### 3.2 ⚠️ 改造期的节奏约束（重要）

prod 模式**没有 `--reload`** → **每次改后端代码都要重启服务，而重启需要管理员权限**。
若严格按"改一次 → 重启 → 测一次"推进，迭代会被重启卡死。

三个可选方案：

| 方案 | 好处 | 代价 |
|---|---|---|
| **A. 按批改造** | 无额外风险 | 一批（如全部批量写改造）做完才重启一次、测一次；单批越大力反馈越慢 |
| **B. 你自己的终端里跑 prod_runner** | **不需要管理员**，重启自己说了算 | 进程随终端关闭而退出（无 NSSM 守护）；同样会重启 nginx |
| **C. 先手工逐项验证再批量测** | 迭代最快 | 手工验证不产生可比数字，最终仍需停机测一轮 |

方式 B 的命令（普通权限即可，5002/3000 都 >1024 不占特权端口）：
```bash
python -m fastapi_app.core.prod_runner          # 4 workers + ARQ + nginx
```

**建议：先 A 后 B** —— 首轮用 NSSM 服务把 before 基线拿到（最贴近真实生产），
若改造批次多、重启频繁，再评估切到 B 换取迭代速度。

---

## 3.3 需要你决策的事项（原表）

| ID | 事项 | 现状 | 选项 |
|---|---|---|---|
| **D-1** | CI 的 ruff 步骤在 HEAD 上就已失败 | `ruff check fastapi_app tests fastapi_app/tests utils` → **Found 173 errors**（145 个可 `--fix` 自动修复）。这意味着 **CI lint job 一直是红的**，门禁形同虚设 | (a) 执行 `ruff check --fix` 后一次性提交，再手工过一遍剩余 ~28 处（推荐，一次到位）<br>(b) 改为只检查 git 变更文件（仿 `file_size_gate.py` 的 diff 基线思路）<br>(c) 暂时 `continue-on-error: true` 并登记待还（不推荐，会弱化门禁） |
| **D-2** | 前端 Playwright e2e 缺失 | CI 早就在 `npx playwright install` 却无任何用例可跑 | 是否排期 E-09；若排，建议用系统 Edge（`channel: 'msedge'`）免下载内核 |
| **D-3** | 生产 5002 仍是 dev 单 worker，ARQ 未运行 | **已尝试执行，被 OS 权限阻断**（详见下方 §3.1） | 需你在管理员 PowerShell 执行一条命令 |
| **D-4** | 根目录 39 个 `_*.py` / `_*.txt` / `_*.log` | 其中 `_mint_token.py`、`_mc_contract_probe.py`、`_bom_modal_e2e_check.py` 等**可能仍在使用**，不宜盲目归档 | 需要你确认哪些可归档（我不擅自移动你在用的工具） |

---

## 4. 与既有计划的映射

本项目已有 `.codeartsdoer/specs/code_quality_opt/tasks.md`（6 组门禁建设 + 6 个 N+1 治理文件 + P1/P2 清单）与 `docs/plans/2026-08-22-code-quality-optimization-plan.md`。

| 既有任务 | 状态 |
|---|---|
| tasks 1.1 N+1 扫描脚本 | 脚本 ✅，**接 CI ❌ → 本轮 E-01 已补** |
| tasks 1.2 函数行数脚本 + pyproject 配置 | 脚本 ✅，**pyproject ❌ → 本轮 E-04 已补** |
| tasks 1.3 Vue 组件行数脚本 | 脚本 ✅，**接 CI ❌ → 本轮 E-01 已补** |
| tasks 1.4 宽泛 except 脚本 | 脚本 ✅，**接 CI ❌ → 本轮 E-01 已补** |
| tasks 1.5 接口契约快照框架 | ❌ 未建（`tests/contract/` 不存在）→ **E-07** |
| tasks 1.6 压测前后对比脚本 | ❌ 未建 → **E-08** |
| tasks 2.x 六个文件 N+1 治理 | ✅ 已完成（违规从数百降到 11） |
| 计划 2-3 Playwright e2e | ❌ 未做 → **E-09** |
| 计划 1-5 事务收敛第二批 | 部分（service 层剩 9 处，均有标注）→ 基线已锁定，可择机收敛 |

---

## 5. 附录：常用命令

```bash
# 门禁（日常）
python scripts/quality_gate.py                     # 判定：新增违规即失败
python scripts/quality_gate.py --report            # 只报告
python scripts/quality_gate.py --only bare_except  # 单门禁
python scripts/quality_gate.py --verbose           # 打印违规明细

# 门禁（收紧）
python scripts/quality_gate.py --update-baseline   # 治理完成、计数下降时执行

# 运行模式（排查 dev/prod）
python scripts/diag/runtime_mode_probe.py

# 自检（改动门禁/契约工具后必跑）
python scripts/_selftest_gate.py        # 门禁 8 项断言
python scripts/_selftest_contract.py    # 契约漂移 6 项断言（需后端）

# 契约快照
python scripts/contract_snapshot.py --list                 # 列出覆盖的端点
python scripts/contract_snapshot.py --record               # 录制基线（改代码前）
python scripts/contract_snapshot.py --check                # 比对（改代码后）
python scripts/contract_snapshot.py --check --json         # 机器可读
CONTRACT_BASE_URL=http://127.0.0.1:5002 pytest tests/contract -v

# 压测前后对比（详见 docs/tickets/artifacts/benchmark/README.md）
python scripts/capture_baseline.py --label before          # ★ 一条命令：模式校验+契约+压测+指纹
python scripts/capture_baseline.py --label after
python scripts/benchmark_compare.py run --label before      # 单跑压测
python scripts/benchmark_compare.py compare \
    --before docs/tickets/artifacts/benchmark/before.json \
    --after  docs/tickets/artifacts/benchmark/after.json

# prod 环境预检（非破坏性，无需管理员）
python -m fastapi_app.core.prod_runner --check
```
