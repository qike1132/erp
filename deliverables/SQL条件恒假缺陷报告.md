# SQL 条件恒假缺陷报告（两处"删除守卫"失效）

> **发现时间**：2026-09-14
> **发现路径**：mypy 门禁 `arg-type` 报错 → 顺藤摸瓜实测 SQL
> **严重程度**：**高**（数据完整性守卫完全失效）

---

## TL;DR

两处「存在关联数据则拒绝删除」的守卫**从未生效过**：

```python
select(func.count()).where(Order.customer == name, not Order.is_deleted)
```

`not Order.is_deleted` 是 **Python 的 `not` 运算符**，走 `__bool__`，
求值为**普通布尔 `False`** —— 不是 SQL 表达式。放进 `where()` 后：

```sql
-- 实际生成（连 customer = :name 都被优化掉了）
SELECT count(*) FROM "order" WHERE false
```

→ **计数永远为 0 → 守卫永不触发。**

| 位置 | 失效的守卫 | 后果 |
|---|---|---|
| `services/customer_service.py` `delete_customer` | 「客户有相关单据则拒绝删除」 | **可删除仍有订单的客户** |
| `services/user_service.py` `delete_user` | 「用户锁定了订单则拒绝删除」 | **可删除仍锁定订单的用户** |

**`Order.customer` 是名称字符串（非外键，无 DB 约束）**，所以删客户会**直接成功**，
把订单变成指向不存在客户的**孤儿数据** —— 数据库层不会拦。

---

## 一、缺陷详情

### 1.1 `customer_service.py` — 删客户守卫失效

```python
# 修复前
select(func.count()).where(Order.customer == customer.name, not Order.is_deleted)
                                                                  ^^^^^^^^^^^^^^^^^^^
                                                                  Python 布尔 False
```

该查询是 `delete_customer` 的**核心守卫**：它统计 10 类关联单据（订单/备货/出货/
访问日志/采购订单/采购计划/包装记录/生产计划/皮套入仓/皮套出仓），
只要有一类非零就抛 `ValueError("该客户已有相关单据，无法删除！")`。

**其中「订单」这一类的计数恒为 0**，其余 9 类写法正确 —— 所以守卫**部分失效**：
只按订单关联的客户可以被删除。

### 1.2 `user_service.py` — 删用户守卫失效

```python
# 修复前
select(func.count()).select_from(Order).where(
    Order.locked_by_id == user_id,
    Order.is_locked,
    not Order.is_deleted,      # ← 同上，使整个 WHERE 恒假
)
```

→ `locked_order_count` 恒为 0 → 「该用户锁定了 N 个订单，无法删除」永不触发。

---

## 二、★ 为什么 1297 项测试一个都没拦住

`test_customer.py::test_delete_customer_with_orders`：

```python
mock_db.execute = AsyncMock(side_effect=[mock_order_result, mock_empty_result, mock_empty_result])
with pytest.raises(ValueError, match="相关单据"):
    await delete_customer(mock_db, 1)
```

**它 mock 掉了 `db.execute`，从不执行真实 SQL。**

测试断言的是"当 mock 返回真值时抛异常" —— 这与"真实 SQL 是否恒假"**完全无关**。
mock 让测试**绕过了唯一能暴露该缺陷的层面（SQL 生成）**。

> 这是本项目**第三次**遇到"mock 掩盖真实缺陷"：
> 前两次是 `AsyncSession.delete` 被 mock 成同步方法（掩盖漏 `await`）。

---

## 三、修复

### 3.1 正确写法

`Order.is_deleted` 的列定义是 `Mapped[bool | None]`（**可空**）。
项目既有惯例是 **`Order.is_deleted.isnot(True)`** ——
已在 `dashboard/customer.py`、`dashboard/mobile.py`、`dashboard/stats.py`、
`order/beile.py`（×3）、`order/queries.py`（×5）等处使用。

**NULL 语义**：`isnot(True)` 让 NULL 也视为"未删除"（`NULL IS NOT TRUE` → TRUE），
比 `is_(False)` 更安全（后者会把历史 NULL 行排除）。

两处已统一改为 `Order.is_deleted.isnot(True)`。

### 3.2 顺带修复

`user_service.py` 的 `Order.is_locked`（裸列）改为 `Order.is_locked.is_(True)` ——
裸列虽可运行，但列可空时语义不清晰，且 mypy 不接受。

---

## 四、★ 新增护栏（本报告最有价值的部分）

新增 `fastapi_app/tests/test_sql_condition_sanity.py`（**4 项**），
分两个层次 —— **都不依赖 DB，因此不会被 mock 掩盖**：

| 层次 | 断言 |
|---|---|
| **行为层** | 正确写法编译出的 SQL **不含** `WHERE false`、**含** `is_deleted IS NOT true`；错误写法确实生成恒假 |
| **静态层** | **AST 扫描 `services/` 全目录**，禁止出现 `not <大写名>.<属性>`（判定为模型类列），一旦出现即失败并给出修正建议 |

静态护栏已**验证有效**（用合成片段测试）：

| 输入 | 结果 |
|---|---|
| `where(..., not Order.is_deleted)` | ✅ 命中（修复前写法） |
| `where(..., Order.is_deleted.isnot(True))` | ✅ 放行 |
| `if not user.is_active:` | ✅ 放行（实例属性，小写） |
| `if not result:` | ✅ 放行 |

> **一个从不触发的护栏等于没有** —— 所以专门验证了它能抓到目标模式。

---

## 五、⚠️ 需要你确认的数据完整性风险

守卫失效意味着**历史上可能已经删掉了仍有订单的客户**，产生孤儿数据。
建议在生产库执行以下**只读**检查：

```sql
-- 订单指向的客户名已不存在于 customer 表
SELECT o.customer AS orphan_customer, count(*) AS order_count
FROM "order" o
LEFT JOIN customer c ON c.name = o.customer
WHERE c.id IS NULL AND o.is_deleted IS NOT TRUE
GROUP BY o.customer
ORDER BY order_count DESC;
```

同类检查可扩展到 `stock_in` / `stock_out` / `packaging_record` 等
以客户名做字符串引用的表。

> **修复后的行为变化**：现在这些客户会**被拒绝删除**并返回明确提示
> （`该客户已有相关单据，无法删除！建议禁用该客户。`）。
> 如果业务上确实需要删除此类客户，应改用「禁用」（`toggle-status`）而非删除。

---

## 六、验证结果

| 检查项 | 结果 |
|---|---|
| 两处目标错误 | ✅ 消除 |
| `customer_service.py` / `user_service.py` | ✅ **两文件零错误，已纳入 mypy 门禁** |
| `mypy --config-file mypy.ini` | ✅ **Success: no issues found in 107 source files**（105 → 107） |
| services 剩余错误 | 380 → **376**（68 文件） |
| 新增护栏测试 | ✅ **4 passed**（含静态 AST 扫描） |
| **全量后端回归** | ✅ **1312 passed, 1 skipped, 0 failed** |

---

## 七、经验教训

1. **★ `not <SQLAlchemy 列>` 不是 SQL 取反。** 它走 Python 的 `__bool__`，
   求值为普通布尔。放进 `where()` 会生成恒假条件。
   正确写法：`col.isnot(True)` / `col.is_(False)` / `~col`。
   → **静态护栏已加入测试，防止复发。**
2. **★ mock 掉的层面 = 测试的盲区。** 本次缺陷藏在"SQL 生成"这一层，
   而 mock 恰好把这一层整个替换掉了。**凡是被 mock 替换的边界，都应有
   至少一个不 mock 的测试**（如本次的"编译 SQL 并断言"）。
3. **恒假条件是最危险的 bug 形态之一**：不报错、不抛异常、不留日志，
   只是让守卫**静默失效**。相比之下，抛异常的 bug 反而安全。
4. **mypy 的 `arg-type` 是线索而非结论，但值得追。**
   本次正是从 `where() 的 bool 参数类型不符`这条报错追到了真实缺陷。
