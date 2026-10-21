# 代码评审机制启用手册（Rollout）

> 目标：从「有标准」变成「每天真的在跑」。分三层启用，先手动、再播报、最后才阻断；
> 任何一层都能单独回滚，不影响生产运行期。
>
> 配套：[code-review-standard.md](code-review-standard.md)（审什么）· [code-review-process.md](code-review-process.md)（怎么走）

## 0. 今天就能跑（3 条命令）

```bash
python scripts/review_packet.py --out logs/review-packet.md   # 生成评审包（自动找远端 main）
python scripts/quality_gate.py                                # 机器门禁
# 打开 logs/review-packet.md，按「风险标记 → 评审重点 → 必跑命令」逐条走
```

本机注意：`.venv` 已损坏，`python` 用系统 3.13 或托管路径
（`C:/Users/Administrator/.workbuddy-ai/binaries/python/versions/3.13.12/python.exe`）；
`ruff` 在 PATH 上可用。

## 1. 三层启用顺序（不要一次全开）

| 层 | 内容 | 状态 | 会不会挡事 |
|---|---|---|---|
| **L1 人工** | 评审包 + PR 模板 + 标准 | **今天可用**（零依赖） | 不挡 |
| **L2 CI 播报** | PR 的 Step Summary 自动生成评审包（advisory） | **已接入** `.github/workflows/ci-cd.yml` lint job | 不挡（只写摘要） |
| **L3 CI 阻断** | `review_packet.py --fail-on-blocker` | 观察 2 周后再开 | 仅拦 Blocker（凭据文件 / 基线上调 / 后端绑 `0.0.0.0`） |
| **L4 提交钩子** | pre-commit 里强制评审 | **不做** | —— |

L4 不做有两个硬理由：① 钩子只能判「能不能提交」，判不了「该不该合并」；
② 本机 `.venv` 已坏、pre-commit 的 stash/restore 今天刚吞过一次并发会话的 21 个文件，
再往里加步骤只会增加故障面。

## 2. 首次启用：把文件入库（需要你确认）

待提交 7 个文件（其余 49 个改动属于并发会话，**不要**卷进来）：

```bash
git add AGENTS.md \
        docs/agents/code-review-standard.md \
        docs/agents/code-review-process.md \
        docs/agents/code-review-rollout.md \
        .github/pull_request_template.md \
        scripts/review_packet.py \
        .github/workflows/ci-cd.yml

git status --porcelain -- AGENTS.md docs/agents .github scripts/review_packet.py
git commit -m "docs(评审): 建立代码审查标准、流程与评审包工具" \
           -m "为什么：质量参差源于评审没有统一判定口径；把机器能判的与人审的分开，并把证据要求写进模板。"
```

**并发保护**（今天已发生过一次 stash 吞文件）：

```bash
SNAP=$(git stash create); echo "快照: $SNAP"        # 只读快照，不改工作区
git status --porcelain | wc -l                      # 提交前后各数一次，条数掉了就是被吞
```

回滚：`git revert <commit>`，无运行期影响。

## 3. 第一个真实 CL 怎么审（现状：审不了，必须拆）

今天实测 `fix/audit-2026-10-18` 相对 `erp/main`：

```
132 个提交 / 373 个文件 / 有效 +20093 -7780 行 / Blocker 0 / High 4
```

按标准（≤400 行/CL），这是 **70 倍超限**，当一个 CL 审必然退化成扫读。处置：

1. **记一次性例外**：PR 描述首行写 `exception: legacy audit branch`，写明理由与补审计划。
   例外只对这一个分支有效，不得复制到新分支。
2. **按层拆三批审**，每批只看一层：
   ```bash
   git diff erp/main...HEAD -- fastapi_app/ migrations/   # 后端 + 迁移
   git diff erp/main...HEAD -- frontend-vite/src/          # 前端
   git diff erp/main...HEAD -- scripts/ .githooks/ .github/ config/   # 运维 + 门禁
   ```
3. **4 条 High 逐条确认**（评审包已列出，必须有人回答）：
   - 迁移改动：单 head？破坏性 DDL？临时库 upgrade/downgrade 跑过？
   - 生产启动/运维路径（2 文件）：回滚路径？重启前在 main 吗？
   - 门禁/钩子/CI 配置（5 文件）：只收紧没放松？`--self-test` 跑过？
   - 删除了 2 个测试文件：对应行为有替代覆盖吗？
4. **新工作从 main 切分支**，按 400 行/CL 执行；老分支不再追加。

## 4. 每个 CL 的日常动作

| 角色 | 动作 | 完成标志 |
|---|---|---|
| 作者 | 跑门禁 + 聚焦测试 + 变异检查 → `review_packet.py` → 填 PR 模板 | PR 里五段证据齐全（门禁/测试/红→绿/变异/回滚） |
| 评审者 | 只读 diff + 需求；按标准 §3 逐维度；每条评论带级别 | 结论四选一 + 各级别条数；零发现须说明重点看了哪三处 |
| owner | 裁决分歧、批准例外、决定 hotfix 是否补审 | 例外有书面理由；同一模块 30 天 2 次 hotfix 触发复盘 |

评审时点不变：**推送前一次**审完整个 CL（merge-base 起的全部提交），零 High/Medium 才推。

## 5. 第一周试点与验收

选 **3 个新 CL**（不要拿老分支试点），满足全部 5 条才算「跑起来了」：

- [ ] 每个 CL 都生成了评审包（`logs/review-packet.md` 或 CI Step Summary）
- [ ] 每个 CL 的 PR 模板五段证据都填了，没有「我试了」「应该没问题」
- [ ] 至少 1 次要求作者做**变异检查**，并当场看到测试变红
- [ ] 至少 1 条评审意见被**证据驳回**（说明评审不是走过场）
- [ ] 零 High/Medium 才推送这条没被破例

不达标时的处理：先看是「工具不好用」还是「流程太重」——
工具问题改脚本，流程问题砍检查表（连续 6 个月零命中的条目删掉），**不要靠喊口号**。

## 6. 本机已知坑（今天实测，别再踩）

| 坑 | 现象 | 处置 |
|---|---|---|
| 远端名不是 `origin` | `--base origin/main` 报 `Not a valid object name` | 用 `erp/main`，或直接省略 `--base`（已支持自动解析） |
| `.venv` 损坏 | `pyvenv.cfg` 打不开、ruff 读不到配置 | 用系统/托管 Python；不要修 venv 去赌 |
| `/tmp` 在 Python 里不是 MSYS 的 `/tmp` | `open('/tmp/x')` 找不到文件 | `--out` 用仓内相对路径（`logs/...`） |
| 并发会话 | 工作区 49 个未提交改动；HEAD 会被别人推进 | 只 add 本任务文件；`--base` 固定到 ref 而不是 `HEAD~N` |
| pre-commit stash | 提交时未暂存改动被整体 stash，崩溃会丢 | 提交前 `git stash create` 留快照；提交后数 `git status` 条数 |

## 7. 回滚

| 改了什么 | 怎么退 |
|---|---|
| 文档/模板/脚本 | `git revert <commit>`，无运行期影响 |
| CI advisory 步骤 | 删掉 `Review packet (advisory, PR only)` 这一段即可，不影响其他 job |
| L3 阻断 | 去掉 `--fail-on-blocker` 参数即退回播报 |

## 8. 月度度量（从下月 1 号起，先测基线）

只记四个数，不做个人绩效：缺陷逃逸率（合并后 14 天内 hotfix/回滚占比）、
(Blocker+High)/千行有效 diff、变异检查未红的测试条数、评审等待中位数。
连续两个月逃逸率不降，说明检查表选错了维度，而不是「审得不够认真」。
