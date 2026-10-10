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

---

## 关联

- 运维护栏（红线之外的第二道人防）在 `AGENTS.md` §6.1——**常驻**，动手前必看。
- 本文的坑若再犯，按 `AGENTS.md` §8 把新根因追加到这里，而不是塞回根文件。
