# P2 管理员动作执行实录与终验（2026-10-01 晚）

四个管理员动作全部执行完毕，本文档是执行实录与终验数据（交接文档 `p2-admin-handoff-2026-10-01.md` 的闭环篇）。

## 终验快照（2026-10-01 18:57）

| 项 | 结果 |
|---|---|
| 443 TLS | `https://127.0.0.1/api/health` = 200，TLSv1.3，自签证书（指纹 acc68ec9…） |
| 限流 | dry_run 观察期生效（60 连发全 200，日志记录中；3-7 天无误伤后改 enforce） |
| 签名 URL | `UPLOAD_URL_SIGNING_SECRET` 已入 .env，erp-prod 重启后端到端 sign/verify 通过；nginx secure_link 留待 7 天兼容期后启用（存量图片直链保护） |
| 复制槽 | **`erp_replica_slot` active=true, has_lsn=true**——副本断流不再需要重建，主库 WAL 受槽保护 |
| 副本 | streaming（async），lag 27s（恢复过渡值，将回落至秒级）；应用读流量已回切 5433 |
| 延迟监控 | `replica_lag_task` 已随 ARQ cron 生效（每 10 分钟，>5min 告警） |
| 业务 | prod_runner ready、双端口 health 200、备份链正常 |

## 执行实录（踩坑记录，供未来同类操作参考）

1. **nginx reload**：`nginx -s reload` 对 NSSM 托管的 nginx 永远 `Access denied`（Global 事件归 LocalSystem，管理员会话也无法打开）——正确路径是 `nssm restart erp-web`（停机 1-2 秒）。
2. **UAC 提权的有效性必须验证**：`Start-Process -Verb RunAs` 的弹窗可能被取消/超时/焦点抢占，脚本跑在 Medium 完整性令牌下（日志出现 `Mandatory Label\Medium` 即证据）。可靠做法：脚本内自检 `whoami /groups`（Administrators 应为"组已启用"而非"仅用于拒绝"），或让用户用**资源管理器双击**（走 secure desktop）。
3. **.bat 文件必须纯 ASCII**：cmd 用 OEM 代码页解析，UTF-8 中文注释会把命令撕碎。
4. **PG 数据目录 ACL**：管理员可追加写 `postgresql.auto.conf`，但 **`pg_ctl start` 以 Administrator 身份启动的 postgres 无法在 NetworkService 所有的 PGDATA 里创建 `postmaster.pid`/写日志**（静默退出，pg_ctl rc=0 是假象）——副本启停**必须走 SCM**（`sc start`），以服务配置的 NetworkService 身份运行。
5. **`postgresql-replica` 是原生服务**：`nssm restart` 不适用（OpenService 拒绝），`Restart-Service`/`net stop` 在验证过提升有效的会话里可用。
6. **副本轮换安全网验证**：副本停机约 15 分钟期间，应用读流量自动回落主库（database.py 内建降级），业务零影响。

## 遗留事项

- 7 天后（2026-10-08）：观察限流 dry_run 日志 → 改 enforce；确认存量图片直链过期 → 启用 nginx secure_link（取消注释两处 + reload）。
- 季度：副本"提升为主库"切换演练（与备份解密演练合并做）。
- 可选：wal_keep_size 主库兜底（已有槽，优先级降低）。
