# scripts/archive —— 历史一次性脚本（归档区，不是门禁区）

**这里的任何文件都不参与门禁、CI、pytest、启动流程。** 保留它们的唯一理由是历史追溯；
新增自动化不得 `import` 或调用本目录内的任何脚本。

`quality_gate.py` / `ruff check scripts/` 仍会扫到本目录（同一 ruff 口径），
所以归档不等于"可以不遵守 lint"。

## 为什么叫 `check_*` 的脚本会被归档

2026-10-17 审计 TEST 区点出 5 个「假门禁」：它们放在 `scripts/` 下、名字是 `check_*`，
读起来像质量门禁，实际是**一次性数据排查探针**：

- `check_duplicate_country.py`（同客户+产品的重复定制单排查）
- `check_order_type.py`（`order_type` 取值分布）
- `check_penguin_filter.py` / `check_penguin.py`（某产品入库/生产记录缺 `product_id` 排查）
- `check_usa_combos.py`（美国定制单产品+客户组合核对）

共同特征（也是必须归档的理由）：

1. **零引用**：`git grep` 全仓 0 处引用（package.json / CI / 其它脚本都不调用它）；
2. **没有判定语义**：只 `print`，不返回退出码、不断言 —— 跑通和跑挂对流水线没有区别，
   放在门禁链路上只会制造"已检查"的错觉；
3. **硬编码本机路径**：`sys.path.insert(0, r'd:\erp_system')`，换机器即失效；
4. **直连应用配置库**：用 `fastapi_app.core.database._AsyncSessionLocal`，在本机（生产机）
   一跑就是打**生产库**。这与「本机即生产机」的事实叠加后风险不可接受。

真门禁必须满足：可判定（失败有非零退出码/明确信号）、有调用方（CI 或 `quality_gate.py`）、
有自检（`scripts/_selftest_gate.py` 验证它在该失败时真的失败）。

## 重新启用一条归档脚本的前提

先把它改造成门禁：给出退出码与断言 → 加进 `quality_gate.py` 或 CI → 在
`scripts/_selftest_gate.py` 补一条"改坏它必须变红"的自检。只是"再跑一次看看"，
请用只读连接并显式确认目标库不是生产库。
