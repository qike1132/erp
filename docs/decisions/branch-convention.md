# 分支与提交约定

## 结论

`main` 是唯一长期分支。所有开发在 `feat/*`、`fix/*`、`refactor/*` 或工具生成的 `hotl/*` 上进行，验证通过后合并回 `main`。工具自动生成的 `merge/*` 和 `*-sentinel` 属于临时产物，合并或切换完成后立即清理，不进入远程。

## 背景

仓库当前的分支来源并不统一，同一批代码会同时出现在多条分支上：

- 远程 `erp`：`main`、`hotl/backup-restore-direct`、`fix/outsource-correctness-concurrency`。
- 本地：`main`（领先 `erp/main` 4 个提交）、`hotl/backup-restore-direct`、`merge/hotl-backup-restore-direct`（检出在独立工作区 `D:/erp_merge_hotl`）、`fix-v533-sentinel`。

其中 `hotl/*` 由 AI 工作流创建，`merge/*` 由合并工具在独立 worktree 中创建，`*-sentinel` 由 IDE 在切换分支前自动生成。三者都只是隔离改动或保存现场的手段，不代表代码被复制。约定需要明确它们的归属和生命周期，避免分支无限堆积。

## 分支命名

| 分支 | 来源 | 用途 | 生命周期 |
| --- | --- | --- | --- |
| `main` | 人工维护 | 唯一长期分支，可部署的稳定基线 | 长期 |
| `feat/<slug>` | 人工创建 | 新功能开发 | 合并后删除 |
| `fix/<slug>` | 人工创建 | 缺陷修复 | 合并后删除 |
| `refactor/<slug>` | 人工创建 | 不改变行为的结构调整 | 合并后删除 |
| `hotl/<slug>` | HOTL 工作流自动创建 | 承载一次独立改造 | 合并后删除 |
| `merge/hotl-<slug>` | 合并工具自动创建 | 在独立 worktree 中执行合并 | 合并后连同 worktree 删除 |
| `*-sentinel` | IDE 自动创建 | 切换分支前的现场快照 | 不推送，定期清理 |

`<slug>` 用小写英文和连字符，取自改造主题，例如 `backup-restore-direct`、`outsource-correctness-concurrency`。

## 合并方向

- 所有工作分支从 `main` 切出，完成后合回 `main`，不直接互相合并。
- 远程 `erp/main` 是团队基线。推送前先 `git fetch erp`，确认本地 `main` 已包含 `erp/main`。
- 合并使用 `--no-ff`，保留一次改造的整体记录，便于整条回退。
- 已合并的临时分支立即删除，包括对应的远程分支和 worktree。

## 提交信息

沿用仓库既有格式：

```text
<type>(<scope>): <中文描述>
```

- `type` 取值：`feat`、`fix`、`refactor`、`perf`、`test`、`docs`、`chore`。
- `scope` 取模块名，多个模块用逗号分隔，例如 `refactor(pattern-room,server-manager)`。
- 描述用中文，说明做了什么，必要时补充为什么。
- 一个提交只做一件事。避免 `chore: 同步工作区改动（…）` 这类把多个不相关改动打包的提交；确实需要打包时，在提交正文中列出清单。

既有示例：

```text
feat(purchase): 汇总下单按钮增加 loading 态
fix(cache): 订单/备货/出货写入后一并失效报表缓存
fix(backup): 备份时间戳归一化 + ARQ 健康哨兵键 + 文件名键契约
refactor(pattern-room,server-manager): pattern-room 组合式函数瘦身 + server_manager 固定 v5.33
```

## 日常流程

```powershell
git fetch erp
git switch main
git pull --ff-only erp main          # 本地 main 与基线对齐
git switch -c fix/<slug>

# 修改并提交
git add <具体文件>
git commit -m "fix(<scope>): <描述>"

git switch main
git merge --no-ff fix/<slug>
git push erp main
git branch -d fix/<slug>
```

清理工具产物：

```powershell
git worktree list                      # 查看额外工作区
git worktree remove D:/erp_merge_hotl  # 移除合并用工作区
git branch -d merge/hotl-<slug>
git branch -d <name>-sentinel          # 已确认无用的检查点分支
```

## 验收标准

- 远程只保留 `main` 和进行中的 `feat/*`、`fix/*`、`refactor/*`、`hotl/*`。
- 本地不存在遗留的 `*-sentinel` 和 `merge/*` 分支，`git worktree list` 只剩主工作区。
- 每次推送前，本地 `main` 已与 `erp/main` 同步，不出现长期领先。
- 新增提交符合 `<type>(<scope>): <中文描述>` 格式。
