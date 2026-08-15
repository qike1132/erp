---
design_type: feature
created_at: 2026-08-14
---

# Server Manager 生产模式精简与状态实时性修复

## Intent Contract

```
intent: 精简 server_manager GUI——删除「生产模式（手动排障）」入口，仅保留「开发模式」与「生产模式」（原「生产托管」），
       并修复生产模式面板状态显示非实时（服务已停但残留状态文件导致显示矛盾）的 BUG
constraints:
  - 不改变对外访问方式（http://<host>:3000 / 后端 5002）
  - 不改变生产服务本身（erp-prod / erp-arq NSSM 服务、prod_runner 监督器）行为
  - 开发模式（前后端）行为保持不变
  - GUI 布局与既有暗色 UI 风格保持一致
success_criteria:
  - GUI 顶部仅剩两张卡：开发模式 + 生产模式（手动排障卡消失）
  - 「生产托管」面板改名为「生产模式」，功能与按钮不变
  - 服务 STOPPED 时面板显示「已停止」且不再显示残留的 ready/pid 旧数据
  - 服务 RUNNING 时面板显示真实状态（后端/ARQ/前端/Redis/就绪）
  - server_manager.py 语法校验通过，重新打包 EXE 成功
risk_level: medium
```

## Verification Contract

```
verify_steps:
  - run: python -m py_compile server_manager.py
  - check: 删除 dual_prod 后无残留引用（grep dual_prod）
  - check: 状态文件 mtime 超时（>15s）时诊断行提示「文件过期」，服务未运行时明细行为「已停止」
  - confirm: 重新打包 EXE，GUI 顶部两张卡、生产模式面板状态正确
```

### 执行结果 (2026-08-14)

| 步骤 | 结果 |
|---|---|
| `python -m py_compile server_manager.py` | ✅ SYNTAX_OK |
| 删除 dual_prod/手动生产死代码 | ✅ 已删除 26 处引用（入口方法、prod 分支、_mode_label、_update_all_ui、check_server_status 等） |
| 生产托管 → 生产模式改名 | ✅ 面板标题、分区注释、日志文案均已改 |
| 状态实时性修复 | ✅ `_refresh_hosting_status` 重写为「服务状态优先」：服务未运行时不读 prod_runner.json（避免残留旧数据）；服务运行时校验文件新鲜度（mtime>15s 提示过期）；Redis 改为实时探测 |
| 布局 | ✅ 开发模式卡 columnspan=2 占满整行 |
| 重新打包 EXE | ✅ `pyinstaller --clean server_manager.spec` |

## Governance Contract

```
approval_gates:
  - 本设计获批后实现
  - 重新打包 EXE 前由用户确认（打包会锁定 EXE）
rollback: git revert；GUI 与打包文件均可逆
ownership: 当前会话
```

## Scope

| In | Out |
|---|---|
| 删除 dual_prod 卡与关联方法/分支 | 删除开发模式（dual_dev） |
| 生产托管面板改名「生产模式」 | 修改 erp-prod / erp-arq 服务定义 |
| 状态刷新改为「服务状态优先」+ 文件新鲜度校验 | 修改 prod_runner.py 状态落盘 |
| server_manager.py 重打包 EXE | 修改生产服务运行行为 |

## Decisions

| # | 决策 | 说明 |
|---|---|---|
| 1 | 删除 dual_prod 手动排障卡 | 生产已由 NSSM 服务托管，手动模式造成混乱与状态矛盾 |
| 2 | 生产托管面板改名「生产模式」 | 语义统一，用户心智模型为一对模式 |
| 3 | 状态以 `sc query` 服务状态为权威 | 服务未运行则不读 prod_runner.json（避免残留旧数据），解决「服务已停但显示 ready」矛盾 |
| 4 | 服务运行中校验 prod_runner.json 新鲜度 | mtime 距今 >15s 视为文件过期，诊断行提示，避免读半写/陈旧文件 |

## Surface

- **Components**：`server_manager.py`（GUI 布局、dual_prod 删除、状态刷新逻辑重写）
- **Files-touched**：`server_manager.py`、`server_manager.spec`（无改动）

## Risks & Open Questions

- dual_prod 删除后 `_start_dual_thread` 的 prod 分支成为死代码，应一并删除保持整洁
- 状态文件在服务启动瞬间可能尚未写入，需在 RUNNING 判定后容忍短暂空文件（显示「读取中」而非报错）
