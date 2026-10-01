# docs/audit-round2/scripts · 审计统计脚本归档

> 2026-10-01 第二轮审计（t5 安全/运维/可观测性）用于「权限点覆盖率」统计的两个脚本，归档执行者 docs-archivist。
> 归档时**只在文件头加了注释（来源 / SHA256 / 依赖 / 运行 / 输出），正文逐字未改**。

## 文件

| 文件 | 原始路径 | 原始行数 | 原始 SHA256 |
|---|---|---|---|
| [routes3.py](./routes3.py) | `%TEMP%\erp_audit_v2\routes3.py` | 71 | `22B4E595B00C57BC464A3CE3C259D940FDB729E77997467C5EFC2B1A8454A22D` |
| [routes4.py](./routes4.py) | `%TEMP%\erp_audit_v2\routes4.py` | 99 | `CB7BC413DF13E95AFAFF5AE5842907B43F669456B19DF6FD40BBDC433825E67E` |
| [normalize_deps.py](./normalize_deps.py) | 归档者自编（t9 修复 T8-1，非 t5 原始脚本） | — | —（本轮新增，无原始文件可比对） |

## 依赖与边界

- **Python 3 + 标准库**（`ast` / `json` / `os` / `io`），无第三方依赖；实测解释器 Python 3.13.13。
- **硬编码** `ROOT = r"D:\erp_system"`（归档副本 routes3.py:13、routes4.py:13 —— 原始文件中位于 :4 / :3，归档时头部插入 9 / 10 行注释后下移）与输出/只读目录 `%TEMP%\erp_audit_v2\`（routes3.py:14、routes4.py:14 写 JSON；normalize_deps.py:15 只读同一目录，其 `ROOT` 在同文件 :14）；换机器/换路径必须改这两行，且输出目录需预先存在。
- **只做 AST 静态解析**：不连数据库、不启动服务、不发起 HTTP 请求、不修改仓库；routes4.py 遍历时跳过 `.git` / `node_modules` / `__pycache__` / `frontend-vite` / `backups` / `logs`。
- **写入面**：只有 routes3.py / routes4.py 会把 JSON 写到 `%TEMP%\erp_audit_v2\`；`normalize_deps.py` 纯只读（读这两个 JSON 并打印，不写任何文件）。建议运行时设 `PYTHONDONTWRITEBYTECODE=1`，避免在仓库留下 `__pycache__`。

## 运行

```powershell
cd D:\erp_system
$env:PYTHONDONTWRITEBYTECODE='1'
python docs/audit-round2/scripts/routes3.py   # routes: 391 ; with param deps: 373 ; -> %TEMP%\erp_audit_v2\routes3.json
python docs/audit-round2/scripts/routes4.py   # routers: 48 ; files with includes: 6 ; -> %TEMP%\erp_audit_v2\routes4.json
python docs/audit-round2/scripts/normalize_deps.py   # 读上面两个 JSON（只读，不写文件）-> 52 / 12 / 11
```

## 用它们复算「52 条无权限点路由」

1. `routes3.json`：391 条 `@router.<http>` 装饰器行，每行含 `file` / `line` / `func` / `method` / `path` / `param_deps`（函数参数默认值里的 `Depends(X)`）/ `decorator_deps`（装饰器 `dependencies=`）/ `router_deps`（同模块 `APIRouter(dependencies=...)`）/ `annotations`。
2. `routes4.json`：`routers` / `includes` / `endpoint_include` 三段；`endpoint_include` 给出每个端点文件在 `fastapi_app/api/v1/router.py` 的 `include_router(..., dependencies=[...])` 挂载项（挂载层注入的 `get_current_user_id` 即认证依赖）。
3. 口径：非测试路由 = 391 行剔除 `file` 含 `tests` 的 9 行 → 382 条；对每条合并「`param_deps` + `decorator_deps` + 挂载层 `deps`」，**不含任何以 `require_` 开头的依赖**者 = **52** 条。
4. 2026-10-01 归档复算结论（**52 与 11 均已复现**，分布与原文逐项一致；t7 曾把「11」误判为待复现、可复算值 31，t9 已撤销该误判）见 [05-ops-security-observability.md](../05-ops-security-observability.md) §1.3 的「复算与口径标注」。

## 用 `normalize_deps.py` 复算「11 条既无权限点也无认证依赖」

1. **先复算 11 的前一步**：在 52 集内合并 `param_deps` + `decorator_deps` + `router_deps` + **挂载层 `include_router(dependencies=...)`**，不含 `get_current_user_id` 者 = **12** 条。合并口径见 `normalize_deps.py:41`（该行亦并入 `router_deps`）；实测 decorator / router / 挂载层三处 `require_*` 命中 **0** 条（330 条 `require_*` 全部来自路由函数的参数默认值），与文档所列三层口径的结果同为 **52**。
2. **再排除用户识别依赖**：`fastapi_app/core/health.py:82` GET `/api/health` 带 `Depends(_get_optional_user)`（源码 health.py:83，`user_id: int | None`，未登录为 `None`，不是认证门槛）→ 余 **11** 条，与 05 号 §1.3 第 60 行逐条一致。
3. 命令：`python docs/audit-round2/scripts/normalize_deps.py`（只读，不写任何文件；**前置**：先跑 routes3.py 与 routes4.py 生成 JSON）。预期输出末段为 `52 -> no-permission routes: 52`、`12 -> …`、`11 -> RESULT: 11`，并附 11 条明细。
4. **⚠️ key 归一化（t8 回归根因，必须注意）**：`routes3.py` 的 `file` 是**反斜杠**路径（`os.path.relpath`，归档副本 routes3.py:43/44/76），`routes4.py` 的 `endpoint_include[].file` 是**正斜杠**路径（归档副本 routes4.py:34 写入、:98/:106 输出）；两者**不归一化则 key 0 命中、挂载层 deps 全部丢失**，会把「无认证依赖」误算成 **31**（连带 27 / 43 也都是错误口径的产物）。归档原件按原文保留、**不修改脚本**，仅在本文档标注口径。

## 注意

- 两个脚本按基线 `aac4c43f`（2026-10-01 14:52:03）取证；归档复算在 HEAD `546401ec`（15:10:43）。两者之间只多了 1 个提交（mypy 覆盖 106→110 + 删 `staging_utils` 死代码），本轮复算的 **52 与 11** 均与基线一致（t9 已修正 t7 对「11」的误判）。
- 脚本**不产出** t4 finding 6 提到的 36 / 87 两个数字；那出自另一套未归档的等效实现，口径差异见 05 号 §1.3。
- 归档副本的正文与原始文件**逐字一致**（已按字节比对：routes3.py 跳过头部 9 行后 `body == 原始` 为 True；routes4.py 跳过头部 10 行后同样为 True —— 其头部多一行 `# 归档日期：2026-10-01`）。
- **行号偏移**：routes3.py **+9**（原始 `ROOT` 在 :4 → 归档副本 :13）；routes4.py **+10**（原始 :3 → 归档副本 :13）。引用行号时必须标明用的是归档副本还是 `%TEMP%` 原始文件。
