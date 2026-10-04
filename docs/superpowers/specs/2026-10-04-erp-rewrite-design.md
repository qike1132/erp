# ERP 重写设计规格

**日期**：2026-10-04
**状态**：待用户审阅
**前置结论**：已确认重写，不考虑沉没成本；PC 是主战场，移动端为附属 PWA；内网单机 Windows；单人维护 + AI 编程；标准 CRUD 由配置生成，业务算法由代码实现；仅迁移主数据，业务流水清零。

---

## 0. 设计的第一原则

**约束：本系统的代码没有人类审阅者。**

评价标准不是"框架先进"，而是两个可测量的数：

1. AI 要写多少行代码 —— 每一行都是无人验证的
2. 机器能自动拦住多少错 —— 类型、测试、数据库约束拦得住；"看起来对但算错"，机器和你都拦不住

18 万行代码，即使每行 99.7% 正确，也有约 540 个 bug。已发生的审计结果表明，其中最贵的一类是**不报错但算错**：权限码错配、锁序死锁环、库存翻倍、汇总取错日期、Excel 日期解析走错分支。

**因此架构目标：让代码错到「动不了数据」为止。**

四条防线按此排序，不可交换：

| 层 | 拦什么 | 谁执行 |
|---|---|---|
| L1 类型 | 写错数据形状 | TS strict / Pydantic |
| L2 数据库约束 | 写进坏数据（重复、非法值、孤儿） | PostgreSQL |
| L3 账本重算 | 算错余额、汇总口径 | 应用 + 可重跑 |
| L4 权限单源 | 权限判断与导航不一致 | 代码生成 |

---

## 1. 真实约束

| 约束 | 值 | 对设计的影响 |
|---|---|---|
| 用户规模 | 7 | 排除分布式；单体足够且应当 |
| 部署 | 内网单台 Windows | 排除 K8s/微服务/服务网格；构建链越简单越好 |
| 维护者 | 1 人 + AI 编程 | 一次性的"魔法代码"要压到最少；不引入需学的约定 |
| 数据量 | 31MB / 29 张订单 | 余额可实时重算，无需缓存层 |
| 移动端 | 附属 PWA，扫码为主 | 不做第二套业务逻辑 |
| PC 端 | 主战场 | 复杂表格、批量操作、一致性校验是刚需 |
| 网络 | 内网，可能不稳 | 移动端离线优先 |
| 代码审查 | 无人类审阅 | 一切依赖自动化门禁 |

---

## 2. 技术栈

### 2.1 最终选定

| 层 | 选型 | 版本 | 理由 |
|---|---|---|---|
| 前端框架 | React | 19 | AI 训练语料压倒性最大；生态最大 |
| 前端语言 | TypeScript | 5.x，`strict: true` | 唯一能把"数据形状"变成编译期错误的选择 |
| 构建 | Vite | 7 | 与现状一致，构建简单可控 |
| UI | shadcn/ui（Radix + Tailwind 4） | - | **源码而非组件库**，类型由 `data` 推导，AI 改错立刻编译失败 |
| 表格 | TanStack Table | 8 | 行类型全推导，无手写泛型 |
| 服务端状态 | TanStack Query | 5 | 缓存/失效规则集中，AI 不必手写 |
| 表单 | React Hook Form + Zod | - | Zod schema 同时驱动前端校验**和**OpenAPI |
| 后端 | FastAPI + SQLAlchemy 2.0 + Pydantic v2 | 已验证版本 | **保持现状，不换** |
| 数据库 | PostgreSQL | 18 | 约束能力强，账本模式需要它 |
| 异步任务 | ARQ | 0.28 | 保持现状 |
| 迁移 | Alembic | 1.16 | 保持现状，单 head |
| 测试 | pytest + Vitest + Testing Library | - | 双端生态最厚 |

### 2.2 明确排除的方案及理由

| 排除 | 理由 |
|---|---|
| **NestJS / 全栈 TS** | OCR 是中文单据识别。TS 侧只能上 tesseract.js，中文准确率断崖下降。Excel 生态也弱一档。为类型统一牺牲识别准确率不划算。 |
| **Next.js / Nuxt SSR** | 内网 + 移动端弱网。SSR 服务端渲染对离线扫码场景是纯负担。 |
| **微服务 / K8s** | 7 用户单机。任何分布式都是负债，且要付的"单人维护"代价最高。 |
| **低代码平台** | 数据模型被平台绑死；且定制逻辑仍要写代码。 |
| **Django** | admin 后台有真实价值（你可在无人审阅下自查数据），但要引入 DRF 样板层 + Django 约定，与已验证的 FastAPI 栈并存无收益。**保留为将来选项。** |

### 2.3 关于"后端不变"的诚实说明

现状核实结果：`fastapi==0.137.1`、`pydantic==2.13.2`、`sqlalchemy==2.0.49`、`arq==0.28.0`、`alembic==1.16.0` —— **已经是我能推荐的最新稳定栈**。

**后端换栈的收益为零。** 重写的价值全部来自第 3-6 节的数据模型与架构改进，以及前端的类型强制力。

---

## 3. 数据模型：四大支柱

这是整个重写的核心，也是与现状差异最大的部分。

### 3.1 支柱一：库存/皮套统一为纯流水台账

#### 现状缺陷（已核实）

`fastapi_app/shared_models/inventory_log.py`：

```python
change_quantity: Mapped[int] = mapped_column(Integer, nullable=False)   # 无 CHECK
related_id: Mapped[str | None] = mapped_column(String(50))              # 无 UNIQUE
```

`related_id` 存"关联单据编号"字符串，**没有唯一约束**。同一张单导入两次，流水翻倍。这正是已审计出的"批量导入无幂等致库存翻倍"缺陷的根因。

`fastapi_app/shared_models/case_movement.py` 方向正确（统一台账，`movement_no` 有 `unique=True`），但 `quantity` 同样缺 `CHECK (> 0)`。

#### 新设计

```sql
CREATE TABLE stock_ledger (
    id            BIGSERIAL PRIMARY KEY,
    sku_id        BIGINT NOT NULL REFERENCES sku(id),
    qty_delta     INTEGER NOT NULL,
    txn_type      TEXT   NOT NULL,
    ref_type      TEXT   NOT NULL,
    ref_id        BIGINT NOT NULL,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    business_date DATE   NOT NULL,
    note          TEXT,

    CONSTRAINT uq_ledger_idem UNIQUE (ref_type, ref_id, sku_id),
    CONSTRAINT ck_ledger_qty  CHECK (qty_delta <> 0)
);
```

**`UNIQUE (ref_type, ref_id, sku_id)` 是整个重写里最值钱的五行。** 它一次性消灭三类 bug：

| 已发生的缺陷 | 现在的拦截方式 |
|---|---|
| 批量导入无幂等致库存翻倍 | 第二次插入违反唯一约束 → 跳过并记录，不报错为 500 |
| 读-改-写余额的并发丢失更新 | **不存余额**，无状态可丢 |
| 汇总口径写错 | 余额永远 `SUM(qty_delta)`，重跑即恢复 |

**不存余额。** 出库前的可用量校验用 `SELECT ... FOR UPDATE` 锁该 SKU 的流水行，或用 `EXCLUDE USING gist` 约束区间重叠。

#### 余额查询

7 用户 / 31MB —— **实时重算，不建汇总表。**

```sql
CREATE MATERIALIZED VIEW sku_balance AS
SELECT sku_id, SUM(qty_delta) AS on_hand
FROM stock_ledger
WHERE occurred_at <= now()
GROUP BY sku_id;

CREATE UNIQUE INDEX ON sku_balance(sku_id);   -- REFRESH CONCURRENTLY 必需
```

重建全表在 31MB 上是毫秒级。**判断标准：只要重算够快，就不缓存。** 当数据量增长到重算变慢时（预计远大于当前规模），再引入增量物化视图，届时设计不变。

#### 皮套台账

**不单开表。** 皮套是一类 SKU，其出入库就是 `stock_ledger` 的记录（`txn_type = 'case_in' / 'case_out'`）。

现状的 `case_movement` 已经是统一台账（已修复双真值漂移），新设计延续该方向，只是把它并入统一表。

### 3.2 支柱二：金额用 NUMERIC，时间分两列

#### 金额

```sql
amount NUMERIC(14,2)    -- 绝不用 REAL / FLOAT
```

SQLAlchemy 侧 `Mapped[Decimal] = mapped_column(Numeric(14, 2))`。

浮点累积误差会在汇总页变成"差 0.01"，而你无法判断哪个是对的 —— 这是典型的"不报错但算错"。

#### 时间

```sql
occurred_at    TIMESTAMPTZ NOT NULL,   -- 记录何时发生（系统时间）
business_date  DATE         NOT NULL,   -- 归属哪个业务期间（月结/汇总只看这个）
```

**两者必须分列。** 已审计出的两个缺陷同源：

- "皮套出库汇总只查当月 1 号" —— 拿 `occurred_at` 推导业务期间，月末数据落空
- "plan 日期解析是旧副本，Excel 真日期致整批丢弃" —— 同类问题

所有月结、周结、期间汇总**一律只读 `business_date`**，不碰 `occurred_at`。

### 3.3 支柱三：权限单源派生

#### 现状缺陷

`shared_models/permission.py` 已是单表（`code` + `url` + `is_nav` 同表），设计正确。

**但代码里仍手写权限字符串。** 后端路由装饰器写 `"purchase:write"`，前端菜单写 `"purchase:write"`，导航配置写 `"purchase.write"` —— 三处独立字符串。已审计出 5 处错配（导航码 vs 接口码），且均为"历史缺陷同类"。

#### 新设计

**权限码由实体定义派生，不手写。**

```python
# 元数据声明（唯一手写处）
class PurchaseOrder(Entity):
    name = "采购订单"
    permissions = {"read", "write", "approve", "delete"}   # 不写完整码
```

生成的权限码为 `purchase_order:read` / `purchase_order:write` / ... 前端菜单与后端路由**从同一份元数据生成**，类型层面不可能漂移。

导航可见性 = 该用户拥有 `read` 权限的实体清单。

#### 效果

**"分配了权限却 403"这一整类 bug 从结构上消失。** 分配权限的界面和校验逻辑都是生成物，不可能与实际检查的权限码不一致。

### 3.4 支柱四：主数据 / 流水分离

| 类别 | 内容 | 迁移策略 |
|---|---|---|
| **主数据** | `customer`、`supplier`、`sku`（含皮套）、`bom`、`bom_item`、`case_profile` | **搬入** |
| **业务流水** | 订单、出入库、生产记录、出货计划、审批记录、OCR 暂存 | **清零重开** |
| **系统表** | `permission`、`user`、`role`、编号计数器 | 重新初始化 |

理由：库仅 31MB / 29 张订单，主数据（客户、产品、BOM）是重开的成本项，必须搬。流水清零可避开全部迁移 bug，且能设计干净的数据模型。

---

## 4. 元数据驱动层：让 AI 少写代码

### 4.1 目标

**标准 CRUD、列表、搜索、分页、表单校验、权限判断全部由配置生成。AI 只写业务算法。**

这是"代码量即 bug 机会"的直接应用。

| AI 不写（配置生成） | AI 写（业务算法） |
|---|---|
| 增删改查 | BOM 展开 |
| 列表页 / 搜索 / 分页 | FIFO 库存分配 |
| 表单与校验 | 皮套台账登记 |
| 权限判断 | 汇总口径计算 |
| 单号生成 | 审批状态机 |

预期效果：AI 需编写的代码减少约一半，且被省下的部分恰是缺陷最密集的样板代码。

### 4.2 实体元数据定义

一份 Python 定义，驱动全部代码生成：

```python
class Sku(Entity):
    table      = "sku"
    name       = "产品"
    fields = [
        Field("code",     "TEXT",     required=True,  unique=True),
        Field("name",     "TEXT",     required=True),
        Field("category", "FK:category", required=True),
        Field("unit",     "TEXT",     required=True),
        Field("spec",     "JSONB"),
        Field("status",   "ENUM",     default="active"),
    ]
    permissions = {"read", "write", "delete"}
    list_columns = ["code", "name", "category", "status"]
    search_fields = ["code", "name"]
```

由此生成：

**后端**
- SQLAlchemy 模型
- Alembic 迁移
- CRUD 端点（含分页、搜索、排序）
- Pydantic 请求/响应 schema
- 权限依赖注入
- 编号序列

**前端**
- 列表页（TanStack Table + 分页 + 搜索 + 排序）
- 表单页（React Hook Form + Zod，校验规则由 `fields` 派生）
- 路由与导航项
- 类型定义（见 6.2）

### 4.3 关键设计：字段定义单源

`Field` 的 `required` / `unique` / `default` **同时**驱动：数据库约束、Pydantic 校验、前端表单规则。

**一处声明，三处一致。** AI 改一处不会漏改另一处 —— 这是消除"约束漂移"的结构性防护。

### 4.4 关于"魔法代码"的诚实评估

元数据层本身约 2000 行，是整个项目唯一一处"AI 写的复杂抽象"。风险必须承认：

- 它有 bug，整套 CRUD 一起坏
- 它是"隐式约定"，AI 可能不理解而绕开它

**缓解措施**：
- 元数据层必须有人工设计的骨架（不是 AI 自由发挥），AI 只按既定模式填充实体定义
- 每一类生成物都要有测试：断言"生成的分页端点行为符合约定"
- 禁止在生成层里写业务分支 —— 一旦出现，模型定义就不够用了

---

## 5. 模块边界

### 5.1 现状问题

- 37 个端点模块、80+ 服务文件
- `purchase` 一个域就拆了 20 个服务文件（`purchase_order_crud.py`、`purchase_order_query_helpers.py`、`purchase_plan_crud_ops.py`…）
- 命名靠缩写堆叠（`staging_*`、`outsource_*`、`craft_work`），新人无法判断边界

**这是典型的"AI 生成文件但没人做整体设计"的产物** —— 每次加功能长一个新文件，无人判断它该归哪里。

### 5.2 新结构：按业务能力划分

```
src/
  core/            # 基础设施：元数据引擎、DB、认证、错误处理、编号
  domains/         # 业务域，每个域一个目录，自成边界
    master_data/   # 客户、供应商、SKU、BOM、分类
    purchasing/    # 采购计划、采购订单、供应商
    sales/         # 客户订单、备货、寄售
    inventory/     # 流水台账、预留、盘点、调整
    production/    # 生产计划、日报、BOM 展开
    case_mgmt/     # 皮套档案、进出台账
    outsourcing/   # 外发工序
    approval/      # 审批流
    ocr/           # 单据识别、暂存、导入
  jobs/            # ARQ 任务
  api/             # 路由装配
```

### 5.3 边界规则（可机器检查）

1. **域之间只能通过显式接口通信**，禁止跨域直接 import 对方的模型或服务
2. **每个域暴露的写操作必须经过其台账**，不得旁路直改库存
3. **依赖方向单向**：`core ← domains`，域之间不允许循环依赖

**这三条由 CI 脚本强制**（`check:api`/`check:routes` 的重写版 + 依赖环检测）。违反即构建失败。

理由：你已踩过"域间直接引用导致双真值"的坑（`/case` 的 case_stock_in/case_stock_out/inventory_log 三表）。**机器检查的边界规则比注释可靠。**

---

## 6. 前端契约

### 6.1 关键原则：类型不得手写

现状风险：后端改字段，前端类型手写不同步 → 运行时 500 或界面错乱。已有 `check:api` 脚本检查漂移，但**检查漂移不如消除漂移的源头**。

### 6.2 类型从 OpenAPI 生成

```bash
npm run gen:api    # openapi-typescript → src/types/api.d.ts
```

生成的类型**只读**，任何手写修改会在 CI 被拦（文件头有 `// AUTO-GENERATED` 标记 + 校验哈希）。

**收益（对你最直接）**：AI 写前端代码时，接口字段拼错是编译错误而非运行时 500。这消除了当前 TS 类型"能编译但与后端不一致"的缺口。

### 6.3 错误处理统一

```python
# 所有错误经统一出口，禁止裸 SQLAlchemyError / OSError 直出
class AppError(Exception):
    code: str
    message: str   # 用户可读，不含路径/DB 拓扑

@app.exception_handler(AppError)
async def handle_app_error(request, exc):
    logger.exception(exc)          # 完整信息进日志
    return JSONResponse(           # 响应只给安全信息
        {"code": exc.code, "message": exc.message},
        status_code=exc.status_code,
    )
```

**现状已修此问题（10 处错误原文直出），新系统作为架构约束写入，而非事后补丁。**

### 6.4 移动端 PWA

**不写第二套业务逻辑。** 与 PC 共用同一套 React 应用、同一套 API、同一套业务规则。

设计要点：
- 路由级代码分割，扫码/查询/报工页面可离线加载
- Service Worker 缓存最近查看的 SKU/订单
- 离线操作进队列，恢复网络后幂等提交（靠 `uq_ledger_idem` 保证安全）

**移动端只做 PC 的高频子集**：扫码查库存、扫码报工、看板。**不做录入表单、不做汇总报表。**

---

## 7. 门禁：把"人工审阅"换成自动化

你的代码无人类审阅，门禁是唯一防线。**每道门都必须是二值判定（过/不过），不能有"警告但继续"。**

| 层 | 工具 | 判定 | 拦什么 |
|---|---|---|---|
| 类型 | `tsc --noEmit`（strict）、`mypy` | 0 错 | 形状错误 |
| 数据约束 | Alembic 迁移 + 约束测试 | 全部通过 | 坏数据 |
| 单元/集成 | `pytest`、`vitest` | 全绿 | 逻辑错误 |
| 契约 | `check:api`/`check:routes`/`gen:api` diff | 无漂移 | 前后端不同步 |
| 边界 | 依赖环检测脚本 | 无环 | 域间乱引用 |
| 权限 | 权限码单源校验 | 全覆盖 | 权限错配 |
| 体积 | `quality_gate` 棘轮 | 不超基线 | 巨型函数 |

### 7.1 优先级：先有测试，再有实现

**业务算法（BOM 展开、FIFO 分配、汇总口径）一律 TDD。** 这些是你看不懂、机器也难静态分析的部分 —— 唯一可靠的防护是测试。

CRUD 由元数据生成，**测试的是元数据引擎本身**，不是每个实体的 CRUD。

### 7.2 数据库约束必须有测试

每条约束配一个"违反它 → 断言报错"的测试。

理由：约束是 L2 防线。如果约束本身写错了（比如拼错字段名导致约束未生效），没有任何其他机制会发现。**必须有一个测试专门验证"坏数据确实被拒绝了"。**

---

## 8. 实施顺序

按"每一步都能独立验证"排列，非按模块完整度：

| 阶段 | 内容 | 验证方式 |
|---|---|---|
| 0 | 基础设施：DB 连接、认证、错误处理、编号、门禁 | 门禁全绿 |
| 1 | **元数据引擎**（2000 行，唯一高风险单元） | 生成的 CRUD 行为测试 + 约束测试 |
| 2 | 主数据域（客户/供应商/SKU/BOM） | 端到端可用 + 数据迁入 |
| 3 | **流水台账 + 余额视图** | 幂等测试：同单重放不翻倍 |
| 4 | 采购 + 销售域 | 端到端流程 |
| 5 | 生产 + 审批 + OCR | Excel/OCR 导入回归 |
| 6 | 皮套 + 外发 | 台账幂等测试 |
| 7 | 移动端 PWA 子集 | 离线场景实测 |
| 8 | 切换 | 双跑验证 → 切流量 → 旧系统只读 |

**阶段 3 必须在阶段 4-6 之前。** 台账是所有域的地基，先落地才能保证后续域不重复踩坑。

---

## 9. 成功标准

技术指标（二值可测）：

- 全部门禁通过，0 错 0 警告
- 幂等测试通过：任一单据重放 3 次，余额不变
- 约束测试通过：所有 `CHECK`/`UNIQUE` 均有违反用例
- 权限测试：随机抽取 10 个权限码，菜单可见性与 API 授权 100% 一致
- 前端 `api.d.ts` 零手写修改

业务指标：

- 主数据完整迁入（客户、供应商、SKU、BOM 无丢失）
- 7 个用户完成一次完整业务闭环（采购 → 入库 → 订单 → 出货 → 结算）
- OCR 与 Excel 导入准确率与现状持平

---

## 10. 明确不做（YAGNI）

| 不做 | 理由 |
|---|---|
| 微服务拆分 | 7 用户单机 |
| 多租户 | 单公司 |
| 高可用/集群 | 单机部署，可靠性靠备份而非冗余 |
| 缓存层（Redis 存业务数据） | 31MB 实时重算足够 |
| 全文检索（ES/PG FTS） | SKU 数千条，B-tree 足够 |
| 消息总线 | ARQ 已够 |
| 离线写冲突合并 | 移动端离线只读 + 队列提交，靠幂等键保证 |
| 分布式锁 | 单进程 + DB 约束足够 |

---

## 11. 风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| 元数据引擎自身有 bug，连带所有 CRUD 坏 | **高** | 唯一人工设计骨架；每类生成物有行为测试 |
| AI 绕过元数据层直接写端点 | 中 | CI 检测重复的 CRUD 模式；代码评审清单 |
| 领域知识丢失（业务流程只在旧代码里） | **高** | 按域逐个提取规则，TDD 固化；不并行重写多个域 |
| OCR/Excel 行为回归 | 中 | 保留现状实现作对照，逐用例比对 |
| 元数据层过度抽象 | 中 | 禁止在生成层写业务分支；出现即模型不足，需回到设计 |

---

## 12. 待定调事项

以下三项在本次设计中未决，需要真实业务数据才能定。**均不阻塞阶段 0-3 的实施**，但必须在对应阶段前确认。

### 12.1 预留与可用量的模型

FIFO 分配、订单备货、生产领料都会"预留"库存。当前设计的 `stock_ledger` 只记录实际出入库，**预留量无处存放**。

三个选项：

| 方案 | 说明 | 代价 |
|---|---|---|
| A. 独立 `reservation` 表 | 预留是独立生命周期（创建/释放/消耗），与流水分离 | 两张表需保持一致 |
| B. 流水增加 `txn_type='reserve'` | 预留也记流水，`on_hand` 与 `reserved` 同表算 | 语义混杂，取消预留要写反向流水 |
| C. 不做预留 | 只在实际出入库时校验 | 缺货风险（超卖） |

**倾向 A**：预留与实际出入库是不同生命周期，混在一张表会让"余额"定义再次模糊 —— 而余额定义的模糊正是账本模式要消灭的问题。

**需要的输入**：现行系统里"备货"（BH 记录）是否已经构成预留？如果备货只是记录意向而不锁库存，则选 C。

### 12.2 皮套与 SKU 的关系

第 3.1 节假定"皮套是一类 SKU"。但皮套有 `customer` 维度（`case_movement.customer` 字段）—— 同一个皮套可能按客户分别管理数量。

- 若皮套按客户独立计数 → 不能简单并入 `stock_ledger`，需要 `sku_id` 之外再加客户维度
- 若客户字段仅为记录用途、不影响数量计算 → 并入方案成立

**需要的输入**：皮套库存是否需要按客户分别核算？

### 12.3 BOM 的多层深度与成本口径

BOM 展开算法是 AI 要写的核心业务逻辑之一，其行为必须先确定：

- **深度**：单层 / 两层 / 无限递归？超过 3 层是否报错？
- **成本口径**：展开后按最近采购价、还是按加权平均、还是标准成本？
- **缺失物料**：BOM 引用了不存在的物料时，报错还是按 0 处理？

**需要的输入**：现行 BOM 的实际层数分布，以及成本计算的口径。**这一项不定，阶段 2 无法开始。**

---

## 附录 A：现状核实数据

| 项 | 实测值 |
|---|---|
| 后端 Python 文件 | 559 个 / 118,172 行 |
| 前端 Vue+TS 文件 | 584 个 / 64,963 行 |
| 端点模块 | 37 个 |
| 服务文件 | 80+ |
| 数据模型 | 36 个 |
| 数据表 | 65 张 |
| Alembic 迁移 | 105 个 |
| 测试 | pytest 3491 通过 |

## 附录 B：已确认的现状缺陷（新设计直接针对）

| 缺陷 | 位置 | 新设计对应 |
|---|---|---|
| 库存流水无幂等约束 | `inventory_log.related_id` 无 UNIQUE | `uq_ledger_idem` |
| 数量无正值约束 | `inventory_log.change_quantity`、`case_movement.quantity` | `ck_ledger_qty` |
| 权限码三处手写 | 路由装饰器 / 菜单 / 导航配置 | 元数据派生 |
| 业务日期与记录时间混用 | 多处 | `occurred_at` + `business_date` 分列 |
| 服务文件过度碎片化 | `purchase/` 20 个文件 | 域目录结构 + CI 边界检查 |