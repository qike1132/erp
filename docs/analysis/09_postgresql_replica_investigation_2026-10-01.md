# postgresql-replica 半成品调查结论（OPT-16a，2026-10-01）

> 起因：`docs/optimization-plan-audit-2026-10-01.md` BLOCKER B2——主库上发现 `replicator` 用户的 walreceiver 连接与 `postgresql-replica` Windows 服务，与评估报告"PG 无从库"的判定冲突。本次只读调查给出定性。

## 1. 事实清单（全部实证）

| 项 | 证据 |
|---|---|
| 副本服务存在且自启 | 注册表：`postgresql-replica` → `pg_ctl.exe runservice -N postgresql-replica -D D:\PostgreSQL\replica_data -w`，Start=2（自动），与主库 `postgresql-x64-18`（-D D:\PostgreSQL\data）并列 |
| 副本数据目录完整 | `D:\PostgreSQL\replica_data` 为完整 PGDATA：`PG_VERSION`、`standby.signal` 存在、`postgresql.conf.bak-20260821_213655`（2026-08-21 配置痕迹） |
| 流复制参数 | `postgresql.auto.conf`：`port=5433`、`hot_standby=on`、`listen_addresses='localhost'`、`primary_conninfo = user=replicator port=5432`（**未指定 host → 走本地 socket**，故主库 pg_stat_replication 里 client_addr 为 NULL；**未配置 primary_slot_name**） |
| 复制正在工作 | 副本日志 `log/postgresql-2026-10-01_000000.log` 当日 restartpoint 持续推进（LSN 3/7C44A038 → 3/7D7ADEB8），恢复源源不断——**热备在实时跟流** |
| 主库侧连接 | `pg_stat_replication` 恒有 1 行 walreceiver（usename=replicator）；`pg_replication_slots` = 0（无物理槽）；`max_wal_senders=10` |
| 应用已接入副本 | `.env` 的 `ASYNC_DATABASE_REPLICA_URL` 已配置且指向 5433——**只读读流量已在走热备**（database.py 有"未配置只读副本，读取操作将使用主库"的降级日志，说明该链路是受支持的设计） |
| replicator 角色 | `rolcanlogin=true, rolreplication=true` |

## 2. 修正的判定

- ❌ 评估报告《architecture-review-2026-10-01》"PG 无从库、整机单点即全灭数据"——**不成立**：同机热备副本已运行三周+（08-21 起）且应用读流量已接入。
- ✅ 仍然成立的单点风险（修订后）：副本与主库**同机同盘**（宿主机/磁盘故障仍全灭）；无复制槽；无副本延迟监控。异常时主库 `pg_stat_replication` 里 NULL-state 行即是该副本的连接痕迹，勿当故障误报。

## 3. 遗留风险与修订后的 OPT-16（从 2-3 天缩为 0.5-1 天）

1. **无复制槽（当前最大隐患）**：`primary_conninfo` 未配 `primary_slot_name` 且主库无槽——主库 WAL 被回收先于副本消费时，副本会断流并需要重新 basebackup。修复：主库 `SELECT pg_create_physical_replication_slot('erp_replica_slot')` + 副本 `postgresql.auto.conf` 加 `primary_slot_name='erp_replica_slot'`（或设 `wal_keep_size` 下限）。注意槽会在副本停机期间滞留主库 WAL——需配合磁盘监控。
2. **副本延迟无监控**：建议接入既有告警通道（backup/metrics/alert_service），阈值如 `pg_last_wal_replay_lag` > 5 分钟告警。
3. **同机同盘**：真正的灾备仍是异机副本——`config/postgres/init-replica.sh`（docker 方案）可作为第二台主机上的落地方案；同机副本仅覆盖"PG 实例故障"，不覆盖主机故障。
4. **演练缺口**：副本存在但从未做过"提升/切换"演练——建议纳入季度备份演练（OPT-22）一并执行。

## 4. 待确认（需业务方回答）

- 该副本是否为团队已知设施（配置日期 2026-08-21）？若为历史遗留试验，按 §3.1-3.2 收编；若为在管设施，仅补 §3.1 槽位与 §3.2 监控。
