# 分析方法与历史踩坑（按需阅读）

> 本文是 `AGENTS.md` §6 的外置细节：**动手分析本仓代码前读它**。
> 根文件只留"每次都要看见的"（红线、拓扑、门禁、运维护栏），分析方法的坑放这里。

## 1. 解析 Python 结构必须用 `ast`

导入关系、迁移依赖图、`__init__.py` 聚合等结构信息，**必须用 `ast` 解析**，不要用正则或 shell 文本匹配。

代价实例：曾因此得出「15 个迁移 head」「48 个端点模块未接线」两个**纯解析伪影**——真相是**单 head、零孤儿**。当时若据此动手"修"，会删掉正在用的模块。

## 2. 判断死代码要按全仓导入

不能只看是否被 `fastapi_app/api/v1/router.py` 直接引用——`backup/`、`purchase_center/` 等是通过 `__init__.py` 聚合接入的，直接引用看不到。判"没被引用"就删，等于删掉生产在用的端点。

## 3. 文档与报告的结论可能已过期

`deliverables/`、`*.md` 报告里的结论是**写作当时的快照**，可能早已失效（实例：某报告称 `utils.redis_cache` 不存在，实际它一直在被 `fastapi_app/main.py` 使用）。**以代码为准**，文档只作为线索。

## 4. 本机 shell 是 Windows PowerShell 5.1（不是 pwsh 7）

- `-Encoding utf8` 会写 BOM；
- 没有 `Get-Content -AsByteStream`；
- 把内联 `if(){...}else{...}` 塞进字符串插值会触发 `MissingEndParenthesisInExpression`，并让**整段脚本一行都不执行**（静默！）——分步写、先赋值再输出。

## 5. git-bash 里 `python` 常常不在 PATH

`C:\Program Files\Git\bin\bash.exe` 环境下 `python` 通常不可见，钩子靠**绝对路径**兜底。写脚本给 agent 或钩子用时，别假设 PATH 里有 python。

## 6. `scripts/` 下一次性运维脚本的超长函数不是技术债

`scripts/check_function_length.py` 的默认扫描面是 `fastapi_app` + `server_manager` + 仓库根顶层 `.py`，**不含 `scripts/`**——故 `scripts/` 里的 >80 行函数不进质量门禁。这些多为一次性运维/诊断脚本（跑一次即弃），拆它们没有收益，反而增加改动面与回归风险。

- 2026-10-11 复核（`REVIEW-VERIFICATION.md` §2.7 ⑦）的处置：`scripts/prod_audit/**` 是**维护中的门禁框架**，11 条超长函数已全部拆到 ≤80 行；其余 17 条一次性脚本**按原样保留**（进 `check_function_length.py scripts` 的统计，但非门禁增量）。
- 别因为「看到超长函数」就去拆 `scripts/` 下的一次性脚本；要拆只拆 `prod_audit` 这类被持续维护的框架代码。
- 复核命令：`command .venv/Scripts/python.exe scripts/check_function_length.py scripts`。

## 7. 两种 pytest 假红形态（本机实测）

- **并发互撞**：`tests/conftest.py` 收尾 `DROP SCHEMA public CASCADE`，两进程共用同一测试库 `erp_system_test`。相隔 ~70s 重叠跑两次全量 → `8 failed / 7 errors`，报错 `asyncpg UniqueViolationError` 违反 `stock_out_stockout_no_key`、冲突值 `(stockout_no)=(SO-PERF-0000)`（来源 `tests/test_stock_routes.py` 硬编码 `f"SO-PERF-{i:04d}"`）。独占单跑即全绿。**全量 pytest 必须独占单实例**。
- **`--basetemp` 越界**：`fastapi_app/tasks/batch_tasks.py` 的 `ALLOWED_UPLOAD_DIRS = [tempfile.gettempdir(), <repo>/static/uploads]` + `realpath+commonpath` 守卫；把 `--basetemp` 指到 `%TEMP%` 之外 → `test_batch_tasks_semantics.py` 4 条必假红（默认 basetemp 下 5 passed）。
- 判别法：报错涉及**别的测试文件**的固定夹具值、或临时目录白名单守卫时，先怀疑跑法（并发 / 临时目录），而不是代码回归。

---

## 关联

- 运维护栏（红线之外的第二道人防）在 `AGENTS.md` §6.1——**常驻**，动手前必看。
- 本文的坑若再犯，按 `AGENTS.md` §8 把新根因追加到这里，而不是塞回根文件。
