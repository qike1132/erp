# mypy 门禁扩容与真实缺陷修复报告

> **执行时间**：2026-09-14
> **触发**：P0 建立的「渐进式 mypy 门禁」策略 —— 修复某文件的历史类型问题后纳入门禁
> **成果**：**从 services 层挖出 3 个真实运行时缺陷 + 1 处注解错误**，门禁从 102 → 105 文件

---

## TL;DR

原以为 services 层那 411 个 mypy 错误只是"类型噪音"。**挖下去发现 3 个真实缺陷**：

| # | 缺陷 | 影响 |
|---|---|---|
| 1 | `ocr/_extractors.py`：单例从未在模块级声明 | **OCR 功能 100% 不可用**（每次调用必 500），而依赖其实都已安装 |
| 2 | `bom_service.py:264`：`db.delete(role)` 漏 `await` | **BOM 角色删除静默失效**（协程被丢弃，数据不删） |
| 3 | `backup/incremental.py:393`：`invalidate_purchase_caches()` 漏 `await` | **恢复后采购缓存永不失效**，读到陈旧数据 |

**三个都是"测试全绿但功能坏掉"的类型。** 存量 1297 项测试一个都没拦住。

---

## 一、缺陷 1：OCR 功能整体不可用（最严重）

### 现象

`fastapi_app/services/ocr/_extractors.py` 中：

```python
def _get_pdf_extracter():
    global _pdf_extracter          # ← 只声明「赋值写回模块级」
    if _pdf_extracter is None:     # ← 但模块级从未声明过这个变量！
        ...
```

### 根因

**`global X` 只声明「函数内对 X 的赋值写回模块级」，它不创建变量。**
模块级从未出现 `_pdf_extracter = ...`，因此首次调用在 `if _pdf_extracter is None`
处直接抛：

```
NameError: name '_pdf_extracter' is not defined
```

**与依赖是否安装无关。** 实测三个第三方包**全部已安装**：

```
rapidocr_pdf / rapidocr / rapid_table  →  均可用
```

也就是说：**OCR 功能在依赖齐备的情况下 100% 不可用，每次调用必然 500。**

### 修复

在模块级显式声明三个单例（类型用 `Any` —— 提取器类来自可选的第三方包，惰性导入，静态类型不可得）：

```python
_pdf_extracter: Any = None
_img_extracter: Any = None
_table_extracter: Any = None
```

### 修复后证据

测试日志显示三个提取器**现在都能初始化成功**（这些日志此前根本到不了）：

```
RapidOCRPDF 提取器初始化成功
RapidOCR 图片识别器初始化成功
RapidTable (SLANet-plus) 表格识别器初始化成功
```

### ★ 为什么 1297 项测试没拦住

`test_ocr_import.py` 只覆盖**上传 / 进度查询 API**，mock 掉了
`create_progress` / `get_progress` / `import_staging_stockouts_from_file`，
**从不触碰提取器 getter**。

已新增 `fastapi_app/tests/test_ocr_extractors_singleton.py`（**11 项**）锁死该缺陷，
含「单例必须在模块命名空间中」与「getter 不得抛 NameError」两类断言。

---

## 二、缺陷 2：BOM 角色删除静默失效

```python
# fastapi_app/services/bom_service.py:264
db.add(ModificationLog(...))   # ← AsyncSession.add 是同步方法，正确
db.delete(role)                # ← AsyncSession.delete 是【协程】，漏了 await
```

**SQLAlchemy 2.0 的 `AsyncSession.delete()` 是 async 方法。** 漏 `await` 时：

- 协程对象被创建后立即丢弃
- **角色从未被删除**（无异常、无日志、无报错）
- 只留下一条 `ModificationLog` 说"已删除"

即**审计日志与实际数据不一致**：日志说删了，数据还在。

### 全库排查结论

| 模式 | 数量 |
|---|---|
| 漏 `await` 的 `session.delete(...)` | **1**（本处） |
| 正确 `await` 的 | **38** |

→ **孤立缺陷，非系统性问题**（其余 38 处写法正确）。

### 修复

```python
# AsyncSession.delete 是**协程**（SQLAlchemy 2.0 async API），
# 漏 await 会导致协程被丢弃、角色**静默不删除**。
# 同块内的 db.add() 是同步方法，故只有 delete 需 await。
await db.delete(role)
```

### ★★ 修复后一个存量测试失败了 —— 而根因是"不忠实的 mock"

加上 `await` 后，`test_bom_role.py::test_delete_role_not_in_payload` 立刻失败：

```
fastapi_app\services\bom_service.py:267: in save_bom
    await db.delete(role)
E   TypeError: object MagicMock can't be used in 'await' expression
```

**先别急着回退 —— 用实测确认哪边对：**

```python
inspect.iscoroutinefunction(AsyncSession.delete)  # → True   （是协程）
inspect.iscoroutinefunction(AsyncSession.add)     # → False  （是同步方法）
```

**结论：`await` 是对的，测试的 mock 是错的。**

排查发现：

| 位置 | 写法 | 判定 |
|---|---|---|
| `conftest.py` 的 `mock_db` fixture | `session.delete = AsyncMock()` | ✅ 正确 |
| `test_bom_role.py:122`、`:289` | `mock_db.delete = MagicMock()` | ❌ **把它降级了** |
| `test_backup_m2.py:87` | `db.delete = MagicMock()` | ❌ 同上 |

`MagicMock()` 是**同步** mock，调用它返回一个 MagicMock 并被丢弃 ——
**`db.delete(role)` 不加 `await` 也能"通过"**。这就是当初漏 `await` 没被测出来的原因。

**已修复三处**，统一改为 `AsyncMock()` 并加注释说明原因。

> **这是本轮第二个"过于宽容的 mock 掩盖真实缺陷"案例。**
> 一个不忠实于真实 API 的 mock，会把缺陷伪装成"已验证通过"。

---

## 三、缺陷 3：恢复后采购缓存永不失效

```python
# fastapi_app/services/backup/incremental.py:393
from fastapi_app.core.purchase_cache import invalidate_purchase_caches
invalidate_purchase_caches()      # ← 它是 async def，漏了 await
```

`invalidate_purchase_caches` 定义于 `core/purchase_cache.py:37`：

```python
async def invalidate_purchase_caches() -> int:
```

漏 `await` → 协程被丢弃 → **增量恢复后采购相关缓存永不失效**。
用户会读到恢复前的陈旧数据，直到缓存自然过期。

### 修复

```python
# invalidate_purchase_caches 是 async def，必须 await；
# 漏 await 会让协程被丢弃 → 恢复后采购缓存**永不失效**（读到陈旧数据）。
await invalidate_purchase_caches()
```

> 注意：这个 `try/except` 块本身是**正确的**（捕获 `RuntimeError/OSError/ValueError`
> 并降级为 warning），说明作者有意做容错 —— 但漏 `await` 让整个容错块变成空转。

---

## 四、缺陷 4：过宽的 `Container` 注解（类型问题）

```python
# batch_import_dedup.py
existing_keys: Container[Hashable] | Iterable[Hashable] = (),
...
seen_existing: set[Hashable] = set(existing_keys)
```

`Container` 只保证 `__contains__`，**不保证可迭代**。函数体要 `set(existing_keys)`，
所以这个联合类型**过宽** —— 传入一个非可迭代的 `Container` 会在运行时崩。

**有趣的连锁**：该注解原本因 `Container` **未 import** 而报 `name-defined`；
补上 import 后，`name-defined` 消失，**反而暴露出被它掩盖的真实 `arg-type` 错误**。

### 修复

两处（`batch_import_dedup.py:136` 与 `batch_import_core.py:84`）统一收窄为
`Iterable[Hashable]`，并移除已无用的 `Container` import。

---

## 五、缺陷 5：返回类型注解与实际不符

```python
# stock_inventory_service.py:382
def _build_inventory_filter_params(...) -> tuple[dict, dict]:   # ← 声明 2 个
    ...
    return params, clauses, pids_param                          # ← 实际 3 个
```

调用方 `params, clauses, pids_param = _build_inventory_filter_params(...)` 是对的，
**是注解写错了**。mypy 信任注解 → 反过来报调用方"解包数量不符"。

### 修复

```python
-> tuple[dict, dict, tuple[int, ...] | None]
```

> 这个案例说明：**mypy 报错的位置不一定是错的位置**。注解错会"倒打一耙"报在调用方。

---

## 六、mypy 门禁扩容

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 门禁覆盖文件 | **102** | **105** |
| services 层纳入 | 79 | **82** |
| services 剩余错误 | 411 / 77 文件 | **400 / 74 文件** |

新增纳入门禁：

- `fastapi_app/services/batch_import_core.py`
- `fastapi_app/services/batch_import_dedup.py`
- `fastapi_app/services/ocr/_extractors.py`

并更新了 `mypy.ini` 的策略注释块，**记录本门禁已发现的真实缺陷**
（而不只是文件清单），让后来者理解"为什么值得修这 400 个错误"。

---

## 七、验证结果

| 检查项 | 结果 |
|---|---|
| `mypy --config-file mypy.ini` | ✅ **Success: no issues found in 105 source files** |
| 新增测试 `test_ocr_extractors_singleton.py` | ✅ **11 passed** |
| 三处目标错误复核 | ✅ `unused-coroutine` 与 `stock_inventory_service.py:346` 均已消除 |
| mock 修复后受影响测试 | ✅ `test_bom_role.py` + `test_backup_m2.py` + OCR 共 **47 passed** |
| **全量后端回归** | ✅ **1308 passed, 1 skipped, 0 failed**（179.43s） |

> 回归总数 1297 → **1308**（+11，全部来自新增的 OCR 单例测试）。
> 期间曾出现 1 次失败（`test_bom_role.py::test_delete_role_not_in_payload`），
> 经实测判定为**测试 mock 不忠实**（非源码缺陷），修复 mock 后转绿 —— 详见 §二。

---

## 八、剩余工作

| 项 | 规模 | 说明 |
|---|---|---|
| services 层剩余类型错误 | **400 / 74 文件** | 按 ratchet 策略逐个修复后纳入 |
| 高信号类别（建议优先） | — | 见下 |

**建议下一批优先处理的类别**（这些比 `arg-type`/`assignment` 更可能藏真实缺陷）：

| 错误码 | 数量 | 为何优先 |
|---|---|---|
| `unused-coroutine` | 0（已清） | 漏 `await` → 静默空操作 |
| `misc` 中的 `"None" not callable` | 3 | 调用可选回调为 None → 运行时 TypeError |
| `return`（Missing return statement） | 2 | 函数可能落空返回 None |
| `misc` 中的字典推导类型不符 | 3 | 可能掩盖数据形状错误 |

具体位置：

```
numbering_sequence.py:49,90        "None" not callable
purchase_plan_common.py:82         "None" not callable
purchase_plan_staging.py:201       Missing return statement
purchase_plan_crud_ops.py:84       Missing return statement
```

---

## 九、经验教训

1. **★ 类型检查门禁的价值再次被具体案例证明。** P0 时它拦下一个功能失效
   （部位内联编辑）；本轮它挖出**三个运行时缺陷**，其中 OCR 是"功能整体不可用"级别。
   **411 个错误里藏着 3 个真 bug —— 这个比例足以证明修复它们的价值。**
2. **`global X` 不创建变量。** 这是 Python 里极易误解的一点：
   只写 `global X` 而模块级无 `X`，读 `X` 会 `NameError`。
3. **async API 的"同步/异步方法混排"是陷阱。** `AsyncSession.add()` 是同步、
   `AsyncSession.delete()` 是协程 —— 同一个类里两种语义，漏 `await` 完全静默。
   → 排查手段：搜 `unused-coroutine`。
4. **mypy 报错位置 ≠ 出错位置。** 注解写错会让 mypy 反过来报调用方。
   修之前先确认"是注解错还是实现错"。
5. **修一个错误可能暴露另一个被掩盖的错误。** `Container` 未 import 报
   `name-defined`，补 import 后暴露出真实的 `arg-type` —— **不要以为"错误数没降"就是白干**。
6. **测试覆盖率是"功能覆盖"而非"代码覆盖"。** 1297 项测试全绿，
   OCR 却整体不可用 —— 因为测试只覆盖了上传/进度 API，绕开了真正的提取路径。
7. **★ 不忠实的 mock 会把缺陷伪装成"已验证"。** 修复缺陷时打破了存量测试，
   **先别回退** —— 用 `inspect.iscoroutinefunction()` 实测哪边对。
   本轮实测证明 `await` 正确、mock 错误：三处把协程方法 `delete` mock 成了同步的
   `MagicMock`，于是漏 `await` 的调用"静默通过"。
   → **mock 必须忠实于被 mock 对象的同步/异步语义**；
     判断标准不是"测试是否通过"，而是"mock 是否与真实 API 同构"。
