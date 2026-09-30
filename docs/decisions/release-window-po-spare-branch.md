# 发布窗口决策：`fix/po-spare-from-part-rates` 整支快进合并

## 状态

已决策（2026-09-30 晚）：**等采购 SKU 展开链收口后，整支快进合并到 `erp/main` 并推送；不拆发。**

## 背景

决策时分支拓扑（实测）：

- 本地领先上游 `erp/fix/po-spare-from-part-rates` **11 个提交，落后 0**（上游自建分支起未动过）。
- `erp/main` 与本分支的分叉点**就是** `erp/main` 的 tip（`c9fb8751`）——
  即任何时刻合并都是**干净快进**，不存在「错过 rebase 窗口」的风险，无需抢时间。

11 个提交分两类：

1. **运维/部署 3 个**（`f458012b` v5.34 桌面壳、`96635c84` 日志策略统一、`eb5f5a1b` runbook §5.6）
   —— 已在生产验证（五服务 RUNNING、健康 200、三方策略同源生效）。
2. **采购 SKU 展开链 8 个**（备品列 + 设计方案（自述待评审）+ 实施计划 + 4 个实现/修复提交）
   —— 决策时仍在活跃迭代（最后提交 23:49，工作区有未提交 WIP）。

## 为什么不拆发

把 3 个运维提交单独 cherry-pick 到 `erp/main` 推送，会让同一改动在历史里出现
**等价提交对**，日后整支合并时要么重复、要么需要 rebase 消解 —— 对一支
**落后 0、必然快进**的分支来说，拆发只增加历史噪声，不缩短任何等待
（运维改动本来就已经在生产上跑着了）。

## 合并就绪清单（全部满足才执行）

- [ ] 设计方案 `69a12d29` 完成评审（其自述「待评审」）
- [ ] 实施计划 `4e7de60e` 的 6 个任务全部落地，SKU 链无后续 fix 追加
- [ ] 工作区干净：`stock_inventory_service.py` 的备品柱状归属 WIP 及配套测试已提交
- [ ] 主检出全量门禁绿：`pytest -q`、`cd frontend-vite && npm run type-check && npm test`
- [ ] `git fetch erp` 后确认上游仍为落后 0（若上游动了，先评估是否仍是快进）

## 执行方式（就绪后）

```bash
git checkout main && git merge --ff-only fix/po-spare-from-part-rates
git push erp main
```

`--ff-only` 是护栏：上游若意外前进会直接失败而不是制造合并提交。

## 回滚

合并本身不改生产（生产跑的是 `D:\erp_system` 工作区 + NSSM 服务，部署与 git 合并解耦）。
若合并后需要回退代码，用 `git revert`（不重写已推送历史）；运行期回滚手段见
`docs/runbooks/service-lifecycle.md` 与 `D:\erp_system\dist\` 的 v5.34 回滚点。
