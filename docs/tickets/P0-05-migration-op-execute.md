# P0-05　新库初始化迁移 1,213 条 `op.execute` 无法执行

| 字段 | 值 |
|---|---|
| 严重度 | 🔴 高（新环境无法建库） |
| 类型 | 缺陷 · 迁移脚本 |
| 模块 | `migrations/versions/pg_standalone_001_pg_standalone_initial_schema.py`（1,243 行） |
| 预估工时 | **10 min**（修复已生成并验证，直接套用即可；原估 4 h 已压缩） |
| 批次 | B |
| 依赖 | 无 |

## 前置确认（必做）

先确认生产库到底走哪条路径：

```bash
psql -U erp_app -d erp_system -c "SELECT version_num FROM alembic_version;"
```

- 返回 `659467a97350` → 生产库是 `stamp` 进来的，**不会执行本迁移**，故当前生产**未受影响**（所以问题长期未暴露）
- 此时本工单**不紧急但仍必修** —— 任何"新 PostgreSQL 部署"都会在第一条语句上直接失败

文档中的两条路径（本文件 docstring 亦载明）：

```
For NEW PostgreSQL deployments:      alembic upgrade pg_standalone_001@head
For EXISTING PostgreSQL deployments: alembic stamp 659467a97350
```

## 定位

`migrations/versions/pg_standalone_001_pg_standalone_initial_schema.py:27+`

```python
def upgrade():
    # Create all tables from ORM models (PG-compatible types only)
    op.execute('CREATE TABLE product (')
    op.execute('	id SERIAL NOT NULL,')
    op.execute('	name VARCHAR(100) NOT NULL,')
    op.execute('	barcode VARCHAR(50),')
    ...
    op.execute(')')
    op.execute(';')
    op.execute('CREATE INDEX ix_product_barcode ON product (barcode);')
```

规模统计（已核对）：全文 **1,211** 次 `op.execute` 位于 `upgrade()`（另有 2 次在 `downgrade()`，合计 1,213）。

## 根因

`alembic` 的 `op.execute(str)` **每次只下发一条独立语句**（`migrations/env.py` 中无任何多语句包装，已核实）。

因此 `op.execute('CREATE TABLE product (')` 会被原样发给 PostgreSQL —— 而 PG 收到一条**未闭合的** `CREATE TABLE`，必然报：

```
syntax error at end of input
```

**结论：`upgrade()` 的第 1 条语句即失败，新库完全无法建立。**

> 附带问题：141 条 `CREATE INDEX` / `CREATE TABLE` 均无 `IF NOT EXISTS`，中断后重跑不可重入。

## 🔬 已验证：这不是推测

我用 **PostgreSQL 官方解析器**（`pglast` 封装 `libpg_query`，即 PG 自身的前端）把新旧实现逐条送进解析器，结果：

```
① 原实现（1,211 条 op.execute 逐条解析，模拟 alembic 行为）
   可解析: 561   失败: 650  / 共 1211 条
   首条失败语句: 'CREATE TABLE product ('
   错误: syntax error at end of input
   → 诊断成立 ✅

② 修复版（561 条完整语句）
   可解析: 561   失败: 0  / 共 561 条
   → 561/561 全部通过 PostgreSQL 解析器 ✅

③ 修复版 downgrade
   2/2 条通过 ✅
```

复现命令（工单自带工具，可重复执行）：

```bash
C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe \
  docs/tickets/tools/rebuild_migration.py \
  migrations/versions/pg_standalone_001_pg_standalone_initial_schema.py \
  docs/tickets/artifacts/pg_standalone_001_pg_standalone_initial_schema.fixed.py
```

## 修复方案（已完成，直接套用）

### 现成产物

| 文件 | 说明 |
|---|---|
| `docs/tickets/artifacts/pg_standalone_001_pg_standalone_initial_schema.fixed.py` | **修复后的迁移文件**，已验证可用，62,656 bytes / 561 条语句 |
| `docs/tickets/tools/rebuild_migration.py` | 生成工具（基于 `ast`，可重复运行、幂等） |

### 套用方式

```bash
cd /d/erp_system
# 1) 备份原文件
cp migrations/versions/pg_standalone_001_pg_standalone_initial_schema.py \
   backups/pg_standalone_001.orig.py
# 2) 替换
cp docs/tickets/artifacts/pg_standalone_001_pg_standalone_initial_schema.fixed.py \
   migrations/versions/pg_standalone_001_pg_standalone_initial_schema.py
# 3) 语法门禁
python -m py_compile migrations/versions/pg_standalone_001_pg_standalone_initial_schema.py
```

### 修复后的形态

```python
_UPGRADE_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE product (
	id SERIAL NOT NULL,
	name VARCHAR(100) NOT NULL,
	...
	PRIMARY KEY (id)
);""",
    """CREATE INDEX ix_product_barcode ON product (barcode);""",
    ...
)

_DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    """DROP SCHEMA public CASCADE;""",
    """CREATE SCHEMA public;""",
)


def upgrade():
    # 逐条下发完整 DDL（此前每条语句被拆成多行导致语法错误）
    for _stmt in _UPGRADE_STATEMENTS:
        op.execute(_stmt)


def downgrade():
    for _stmt in _DOWNGRADE_STATEMENTS:
        op.execute(_stmt)
```

**为什么选"逐条下发"而不是"整包一次下发"**：
1. 每条语句本身完整合法，不依赖驱动的多语句支持（避免 `text()` 多语句的灰色地带）
2. alembic 报错能直接指出**是哪一条 DDL** 失败
3. 为后续加 `IF NOT EXISTS` 幂等化留出逐条处理的空间

**为什么不用 `op.create_table()` 原生 API**：1211 行 DDL 手工转成 `op.create_table/create_index` 约需 4 h 且易引入人为错误；
本方案是**无损机械变换**（已校验），风险更低。若要长期维护性最优，可另开工单用 `alembic autogenerate` 从 ORM 重新生成。

## 验收标准

1. **语法/语义校验**（工单工具自带）
   ```bash
   C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe \
     docs/tickets/tools/rebuild_migration.py <原文件> <输出>
   ```
   期望输出含：`升级 561/561 条通过 PG 解析`、`downgrade 2/2`、`无损校验通过`
2. **无损性**：工具已校验「去空白后逐字符一致」，即**没有任何 SQL 内容被改动或丢失**
3. **真机冒烟（强烈建议）**——在**临时/scratch 库**上跑一次完整建库：
   ```bash
   createdb -U erp_app erp_migration_smoke
   psql -U erp_app -d erp_migration_smoke -c "CREATE SCHEMA public;"   # 若需要
   alembic -x db_url=postgresql+asyncpg://erp_app@127.0.0.1/erp_migration_smoke \
           upgrade pg_standalone_001@head
   psql -U erp_app -d erp_migration_smoke -c "\dt" | wc -l              # 期望 ~60 张表
   dropdb -U erp_app erp_migration_smoke
   ```
   ⚠️ **严禁在 `erp_system` 生产库上执行 `alembic upgrade` / `downgrade`**。

## 发布动作

迁移文件不随 FastAPI 进程加载，**无需重启 `erp-prod`**。改动在下次执行 `alembic upgrade` 时生效。

## 回归风险

**低**（对现网零影响）：生产库已 `stamp`，不会执行本迁移。
风险面仅在"未来新建库"这条路径上 —— 而那条路径**当前 100% 失败**，故本工单是纯改善。

## 后续建议（另开工单）

1. **幂等化**：给 141 条 `CREATE INDEX` 加 `IF NOT EXISTS`，避免中断重跑失败
2. **纳入 CI**：把"迁移脚本能在空库上跑通"加入 CI —— 本工单的教训是**迁移脚本从未在空库上验证过**。
   建议最小实现：CI 起一个临时 PG 容器 → `alembic upgrade head` → `alembic downgrade base` → 通过则绿灯
3. **`migrations/env.py` 加防呆**：检测到 `op.execute()` 的 SQL 未以 `;` 结尾或括号不闭合时直接报错，
   防止后人再次写出同类脚本
