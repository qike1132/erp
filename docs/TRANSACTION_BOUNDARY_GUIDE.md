# 事务边界规范（Transaction Boundary Guide）

> 状态：生效中
> 门禁：`python scripts/quality_gate.py --only service_commit`
> 检测脚本：`scripts/check_service_commit.py`
> 本文档被检测脚本的失败提示引用；若路径变更请同步修改 `scripts/check_service_commit.py:89`。

---

## 1. 唯一提交点

**Web 请求路径下，事务的提交点只有一个：`fastapi_app/core/database.py` 中的 `get_async_db` 依赖。**

- 请求进入 → `get_async_db` 开启会话
- 处理成功 → 由该依赖统一 `commit()`
- 处理抛错 → 由该依赖统一 `rollback()`

推论（这就是门禁要守的规则）：

| 层 | 允许 | 禁止 |
|---|---|---|
| `api/v1/endpoints/**` | 调用 service；把领域异常翻译为 HTTP 状态码 | `db.commit()` / `db.rollback()` / 直接操作 ORM |
| `services/**` | `await db.flush()`（拿到自增 ID / 触发约束） | `await db.commit()` |
| `core/tasks/**`（ARQ） | 自行管理会话与事务（无请求上下文） | — |

**为什么服务层只允许 `flush()`**：`flush()` 把 SQL 发给数据库但不结束事务，既能让后续逻辑读到自增主键、又能让约束错误在事务内暴露，从而被 `get_async_db` 的 rollback 覆盖，保证一个请求的写入要么全成、要么全败。一旦服务层自行 `commit()`，后续步骤失败就只回滚了后半段，产生**部分提交**——这类问题的表现是"数据静默不一致"，而不是报错，最难排查。

---

## 2. 豁免与标注

### 2.1 脚本自动豁免的代码形态

`scripts/check_service_commit.py` 识别以下模式并跳过，无需额外说明：

- `await nested.commit()` —— 嵌套事务 / savepoint
- `await short_session.commit()` —— 独立短会话（如编号生成器）
- 注释行、测试文件

### 2.2 需要人工标注的例外

确有必要在服务层独立提交时（典型场景：备份 dump/restore 天然跨独立事务、密码哈希迁移需要与登录流程解耦、逐条补录需要"成功即落库、失败不影响已成功项"），**必须在该行加行尾标注**：

```python
await db.commit()  # manual-tx: <为什么必须现在提交，不提交会怎样>
```

标注不是"免死金牌"：脚本**不会**因为该注释而跳过（这是有意的——例外应当被持续看见），但评审时以标注内容判断是否成立。当前已接受的存量见 §4。

### 2.3 端点层没有例外

端点层的 `commit()` / `rollback()` 一律视为违规，没有标注逃生通道。需要独立事务的端点应把逻辑下沉到服务层并走 §2.2。

---

## 3. 常见改造手法

| 原写法（端点层） | 改成 |
|---|---|
| `await db.commit()` | 删除；提交交给 `get_async_db` |
| `except Exception: await db.rollback(); raise HTTPException(500)` | `except DomainError as e: raise HTTPException(...)`；回滚交给依赖 |
| 写库后直接 `await redis.delete(...)` 失效缓存 | 下沉到 service，由调用方在**提交成功后**失效（顺序敏感：先提交后失效，不能反过来） |

| 原写法（服务层） | 改成 |
|---|---|
| 多步写 + 最后 `await db.commit()` | 全改 `await db.flush()`，由请求级依赖提交 |
| 循环内逐条 `add()` + `commit()` | 收集后批量写（`executemany` / `ON CONFLICT`），一次 flush |
| 需要"部分成功部分失败" | 用 `begin_nested()` savepoint；成功才累加计数，失败记入错误列表 |

---

## 4. 当前已接受的存量（基线 9 处）

这些是经评审接受、带 `manual-tx` 标注（或语义等价说明）的例外。**只允许减少，不允许增加**：

| 位置 | 理由 |
|---|---|
| `services/auth_service.py:63,72` | 密码迁移与登录流程解耦 |
| `services/backup/incremental.py:385` | try/except 内显式事务控制 |
| `services/backup/restore.py:265` | 组件还原后提交 |
| `services/backup/strategies.py:133` | try/except 内显式事务控制 |
| `services/backup/orchestration/recovery_test_service.py:572` | 与生产 JsonRestoreStrategy 行为一致 |
| `services/backup/records.py:594,608,624` | 每条补录/删除/修正成功后立即提交，避免后续失败回滚已成功项 |

> 说明：备份域占 6 处属合理——dump/restore 不运行在请求上下文里，没有 `get_async_db` 可依赖。

---

## 5. 如何验证

```bash
# 只看这一个门禁
python scripts/quality_gate.py --only service_commit

# 看完整报告（含原始违规清单）
python scripts/quality_gate.py --verbose
```

预期：违规数 **≤ 9**。新增任意一处 `db.commit()`（且非 §2.1 形态）都会让门禁报 `REGRESS` 并退出码 1。

改造完成后若违规数下降，执行 `python scripts/quality_gate.py --update-baseline` 收紧基线，防止回退。
