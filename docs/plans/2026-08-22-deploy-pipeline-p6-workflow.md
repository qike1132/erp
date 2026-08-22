# 部署发布流水线（P6）工作流

> 日期：2026-08-22 ｜ 设计文档：docs/designs/2026-08-22-deploy-pipeline-p6-design.md
> 预估：5~10 人日 ｜ 依赖：server_manager v6.0.0（DeployPage/消息队列/告警引擎已就绪）

## 任务分解

### D1 流水线骨架（~1.5 天）
- [ ] `DeployEngine` 状态机（idle/validating/backing_up/deploying/health_checking/done/failed）
- [ ] 步骤注册表 + 进度/日志消息协议（`deploy_step` → `_msg_queue`）
- [ ] `deploying` 态接入 `_mode` 互斥守卫（部署中禁用开发模式启动）
- [ ] 单测：状态机迁移、失败短路、消息协议
- 验证：伪造步骤函数跑通 idle→done 与 idle→failed 两条路径

### D2 校验 + 备份（~1.5 天）
- [ ] 环境校验器（python/nssm/git/npm/磁盘/工作区）
- [ ] 代码备份（git archive → backups/deploy_<ts>/code.zip）
- [ ] DB 备份（pg_dump，密码走 env；.env 凭据解析复用 `_get_env_value`）
- [ ] Mimosa 合规：git/pg_dump 经 `executable=` + 校验门
- 验证：备份产物存在且可校验（zip 完整性、dump 行数>0）

### D3 部署 + 重启（~2 天）
- [ ] `git pull`（冲突即失败）→ `npm ci && npm run build` → `alembic upgrade head`
- [ ] NSSM 重启 erp-prod/erp-arq（复用 `_service_cmd_sync`）
- [ ] 步骤级日志实时回传（复用 `_msg_queue` log 通道）
- 验证：演练环境真实部署一次成功

### D4 健康检查 + 回滚（~1.5 天）
- [ ] 健康轮询（/api/health × 30 + 前端 + Redis PING）
- [ ] 回滚：代码恢复 + alembic downgrade + DB dump 恢复 + 重启
- [ ] 回滚失败告警（AlertEngine `deploy_rollback_failed`）
- 验证：注入 ③ 失败 → 回滚 → 健康检查通过

### D5 UI 接入 + 历史（~1.5 天）
- [ ] Stepper 组件（圆点/连接线/当前步脉冲/失败标红）
- [ ] DeployPage：Stepper + 步骤日志区 + 发布历史表 + 移除 P6 占位告示
- [ ] `DeployHistory` 持久化（logs/deploy_history.json，保留 50 条）
- 验证：全流程 UI 走查 + 断电恢复提示（in-progress 标记检测）

### D6 演练验收（~1 天）
- [ ] 完整发布演练 + 失败回滚演练（设计文档 §6 验收标准 1~3）
- [ ] 更新 CHANGELOG 与 overview.md 实施记录

## 里程碑

| 节点 | 内容 |
| --- | --- |
| M1（D1-D2） | 骨架 + 备份可演练 |
| M2（D3-D4） | 真实部署 + 回滚闭环 |
| M3（D5-D6） | UI 完整 + 验收通过 |
