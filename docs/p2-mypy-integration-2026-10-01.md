# P2-A6 mypy 渐进棘轮扩围：144 → 370（集成记录）

- 日期：2026-10-02
- 任务：t51（kind=integration，写者 gatekeeper，attempt_id dc189e7c-3296-4973-8c7c-5d912e033e5d）
- inScope：`mypy.ini`、`docs/p2-mypy-integration-2026-10-01.md`（本文件）
- 纪律：未执行任何 git 写操作；未传 sandbox_permissions；未改 `scripts/gate_baseline.json`

## 1. 批次背景

P2-A 把 `fastapi_app/` 下的类型问题按四片分批清零，再由本任务一次性并入渐进棘轮：

| 批次 | 任务 | 内容 | 结果 |
| --- | --- | --- | --- |
| 分片 1/4 | t46 | 24 模块 124 处 error | 显式路径 mypy exit 0 |
| 分片 2/4 | t47 | 24 模块 124 处 error | 显式路径 mypy exit 0（3 处跨片残余转 t52） |
| 分片 3/4 | t48 | 25 模块 124 处 error | 显式路径 mypy exit 0 |
| 分片 4/4 | t49 | 24 模块 123 处 error | 显式路径 mypy exit 0 |
| 跨片真修复 | t52 | Date→date 9 处、Numeric→Decimal 5 处、approval backref、approval_log_service 会话注解 | 226 路径 495 errors/97 files → 0 |
| 独立验证 | t50 | 4 片 + 全量 pytest/mypy/门禁复核 | round 2 verdict = pass |
| 测试口径 | t53 | numbering sequence 集成用例（round-1 假红灯） | 已修复并被 t50 round 2 复验 |

## 2. 370 集合的构造与自证

- A = `mypy.ini` 扩围前的 `files` 名单（实测 144 项，去重后 144）
- B = `logs/_cap_mypy_residual_list.txt`（captain 实测的 fastapi_app 下未列入棘轮的非测试 `.py`，226 项）
- C = 仓库实际集合 = `fastapi_app/**` 下全部非测试 `.py`（排除 `fastapi_app/tests/**` 与 `__pycache__`）

派单口径要求的三组数字（脚本实跑输出）：

```text
|144 list|=144  |226 residual list|=226  |144 n 226|=0  |144 u 226|=370
actual non-test .py under fastapi_app = 370
(144 u 226) ^ actual = []
226 - actual = []
```

结论：`|A|`=144、`|B|`=226、`|A ∩ B|`=0、`|A ∪ B|`=370；`(A ∪ B) △ C = ∅`（0 差集），且 `B ⊆ C`。名单无重复（144 项 → 144 唯一，370 项 → 370 唯一）。

契约自带的集合比对命令（见 §4）同样输出 `listed 370 actual 370 diff 0`。

## 3. mypy.ini 的改法

- 只改 `files` 块：370 条路径按**字典序**排列，保持 `files = <第一条>,` + 每行 4 空格缩进 `fastapi_app/...,`、末项无逗号的既有风格；`:files` 块之前追加一段**纯 ASCII** 的 P2-A 记录（批次、片切分、144→370、政策不变、验证依据）。
- 配置项一律未动：`python_version = 3.13`、`warn_unused_configs`、`pretty`、`show_error_codes`、`check_untyped_defs`、`ignore_missing_imports`、`follow_imports = silent` 与 `exclude = (?x)(^\.archive/|^tests/|^fastapi_app/tests/)` 原样保留。
- 未放宽任何设置：无 `ignore_errors`、无 `disable_error_code`、无逐模块 `[mypy-...]` section、无 `# type: ignore`（`[mypy]` 是文件里唯一的 section；`ignore_errors`/`disable_error_code` 只出现在说明它们「未被新增」的注释里）。
- 编码：文件仍为**纯 ASCII**（非 ASCII 字符集合为空），避免 configparser 按 locale(cp936) 读取时炸 UnicodeDecodeError；行尾保持 LF（与扩围前一致）。

diff 摘要（`git diff HEAD --numstat -- mypy.ini`）：

```text
295     51      mypy.ini
```

新增行只含：ASCII 注释块 + `files = <第一条>,` + 路径行；删除的 51 行是原 144 项名单中未按字典序排列的部分（**重排**，非删除条目：144 项全部包含在 370 项内，`A ⊆ A ∪ B`）。

## 4. 实测命令与退出码

### 4.1 全量 mypy（370 文件）

```text
.venv\Scripts\python.exe -m mypy --config-file mypy.ini
```

- exit code：**0**
- 末行：`Success: no issues found in 370 source files`
- 证据：`%TEMP%\t3-gatekeeper\t51\v1_mypy_370.out` / `.rc`

### 4.2 质量门禁复核

```text
.venv\Scripts\python.exe scripts\quality_gate.py --verbose
```

- exit code：**0**，末行 `[PASS] 无新增质量问题。`
- 十类计数与基线一致（0/5/51/7/12/0/0/0/60/0）：

```text
OK  N+1 查询（循环内 execute/scalar/scalars）: 0 处（与基线一致）
OK  裸 except / 宽泛 except Exception: 5 处（与基线一致）
OK  后端超长函数: 51 处（与基线一致）
OK  前端巨型 Vue 组件: 7 处（与基线一致）
OK  service 层手动 commit(): 12 处（与基线一致）
OK  以 UTF-8 BOM 开头的 .py（AST 工具会静默跳过）: 0 处（与基线一致）
OK  Alembic 迁移图形状（单 head / root 数不增）: 0 处（与基线一致）
OK  环境变量漂移（代码引用 与 .env.example 模板）: 0 处（与基线一致）
OK  ruff 违规（scripts/ + server_manager/，ruff.toml 口径）: 60 处（与基线一致）
OK  pip-audit 豁免策略（[[tool.code-quality.pip-audit-ignores]]）: 0 处（与基线一致）
```

- `scripts/gate_baseline.json` 未改：`git status --porcelain -- scripts/gate_baseline.json` 输出为空。
- 证据：`%TEMP%\t3-gatekeeper\t51\v2_qg_verbose.out` / `.rc`

### 4.3 集合比对（契约 verify[2] 原文）

```text
.venv\Scripts\python.exe -c "import io,os,re;t=io.open('mypy.ini',encoding='utf-8').read();b=t.split('files =',1)[1].split('exclude =',1)[0];f=[x.strip().rstrip(',') for x in b.split() if x.strip().rstrip(',').endswith('.py')];r=[];[r.append(os.path.relpath(os.path.join(d,n),'.').replace(chr(92),'/')) for d,_,fs in os.walk('fastapi_app') for n in fs if n.endswith('.py') and 'tests' not in d.split(os.sep)];print('listed',len(f),'actual',len(set(r)),'diff',len(set(r)^set(f)))"
```

- exit code：**0**
- 输出：`listed 370 actual 370 diff 0`
- 证据：`%TEMP%\t3-gatekeeper\t51\v3_setcmp.out`

## 5. 残余与声明

- 残余（沿用 t50 报告，均 low、不阻塞）：R-t50-2、R-t50-3。
- 声明：本任务未改动 `scripts/gate_baseline.json`；未放宽任何 mypy 设置；未新增豁免；未删除名单中任何已列文件（`A ⊆ A ∪ B`）。
- 扩围后如新增 error，按派单要求「不得删名单、不得加豁免」，直接回报 captain —— 本轮未出现该情形（`Success: no issues found in 370 source files`）。
