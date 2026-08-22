# 部署发布流水线（P6）设计 — ERP 服务器管理器

> 日期：2026-08-22 ｜ 状态：立项（独立于 UI 重构 v6.0.0）
> 前置：server_manager v6.0.0 已交付 DeployPage 骨架与范围告示；本设计补齐后端流水线与 Stepper UI。

## 1. 背景与范围

UI 重构方案（docs/ui-redesign/ERP服务器管理器UI重构设计方案.md §6.6）定义了四步发布的终态交互，但
`server_manager.py` 中**不存在任何流水线后端能力**（现有仅为 NSSM 安装/卸载/启停）。P6 独立立项建设：

- **范围**：校验环境 → 备份现状 → 部署更新 → 健康检查 四步流水线；失败重试/回滚；发布历史持久化；DeployPage 接入 Stepper 组件。
- **不做**：多机部署、蓝绿/灰度、定时发布（未来扩展）。

## 2. 架构

```
DeployEngine（状态机，后台线程）
  idle → validating → backing_up → deploying → health_checking → done
                                                      ↓ (失败)
                                                   failed(可重试/可回滚)
每步产出: ('deploy_step', {step, state, progress, log_line}) → _msg_queue → 主线程渲染
```

- `DeployEngine`：步骤编排、失败捕获、进度上报。复用现有消息队列架构（后台线程绝不动 UI）。
- `DeployHistory`：`logs/deploy_history.json`，每次发布一条 `{ts, from_ver, to_ver, result, duration, backup_dir, steps[]}`，保留 50 条。
- **UI**：DeployPage 移除占位告示，接入 Stepper（圆点+连接线+当前步脉冲，见 ui-redesign 原型）+ 步骤日志区（复用日志渲染样式）+ 发布历史表。

## 3. 步骤定义

| 步骤 | 内容 | 失败判定 |
| --- | --- | --- |
| ① 校验环境 | Python/NSSM 存在、git 工作区状态、npm、磁盘剩余 >2GB、当前服务状态快照 | 任一工具缺失/磁盘不足/工作区脏（可选 --force） |
| ② 备份现状 | 代码：`git stash create` + `git archive` 到 `backups/deploy_<ts>/code.zip`；DB：`pg_dump`（凭据读 .env）；记录 alembic 当前版本 | 任一备份命令非零退出 |
| ③ 部署更新 | `git pull` → 前端 `npm ci && npm run build` → 后端依赖同步 → `alembic upgrade head` → NSSM 重启 erp-prod/erp-arq | 任一命令非零退出或服务未进入 RUNNING |
| ④ 健康检查 | `/api/health` 轮询（30 次 × 2s）+ 前端可达 + Redis PING | 超时未就绪 |

回滚 = 恢复 ② 的备份：代码 zip 解包覆盖（或 `git reset` 到备份 commit）→ `alembic downgrade <备份版本>` → 恢复 DB dump（仅迁移失败时）→ 重启服务。

## 4. 安全与工程约束（本仓库强制）

- **Mimosa 合规**（见 server_manager.py 文件头"安全约定"）：所有 subprocess argv[0] 用字面量（`'git'`/`'npm.cmd'`/`'pg_dump'`），运行时解析的绝对路径经 `executable=` 传入且先过存在性校验；文件写入走"绝对路径+禁 `..`+父目录存在"校验门。
- pg_dump 密码经 env 注入，不落命令行参数（进程列表可见）。
- 部署期间禁用"启动开发模式"等互斥操作（复用 `_mode` 守卫，新增 `deploying` 态）。
- 生产运行中允许发起部署（流程自身会重启服务），但 UI 明示"预计中断 1~3 分钟"。

## 5. 风险

| 风险 | 缓解 |
| --- | --- |
| alembic downgrade 链不完整导致回滚失败 | 校验步骤预检 downgrade 可达性；回滚失败时保留备份目录并告警 |
| pg_dump 大库耗时长 | 备份步显示进度；>10GB 提示改用基础备份 |
| 部署中途断电/崩溃 | 状态机持久化到 deploy_history（含 in-progress 标记），下次启动检测并提示恢复 |

## 6. 验收标准

1. 演练环境完整走通四步，发布历史正确记录。
2. 注入失败（③ 阶段 git 冲突）：步骤标红、可重试、可回滚，回滚后健康检查通过。
3. 全程主线程无卡顿（步骤命令均在后台线程）。
