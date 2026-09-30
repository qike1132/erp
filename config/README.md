# config/ 目录说明：哪些是**运行时**配置，哪些不是

> 结论先写：本目录里**只有 4 类文件在运行时真正生效**，其余是「灾备随包分发件」或
> 「未接线的死配置」。判断「监控现状」时**不要**读本目录的 prometheus / grafana / otel /
> promtail / alertmanager 文件 —— 它们没有运行体（见下）。真实的可观测性入口是
> `scripts/ops/watchdog.py` + `logs/`。

## 一、运行时真正生效（Windows + NSSM 部署形态）

| 文件 | 被谁加载 | 证据 |
|---|---|---|
| `nginx-windows.conf` | NSSM 服务 `erp-web`：`nginx.exe -p D:\erp_system -c D:\erp_system\config\nginx-windows.conf` | 注册表 `HKLM\SYSTEM\CurrentControlSet\Services\erp-web\Parameters\AppParameters` |
| `security-headers.conf` | 被 `nginx-windows.conf` 以绝对路径 `include`（server 级 + 各 location） | nginx-windows.conf:44 等 |
| `redis-broker.conf` | NSSM 服务 `erp-redis-broker`：`redis-server.exe config/redis-broker.conf`（端口 6380，ARQ 队列） | 同上，`erp-redis-broker\Parameters` |
| `jwt/private_v2.pem`、`jwt/public_v2.pem` | `.env` 的 `JWT_PRIVATE_KEY_PATH` / `JWT_PUBLIC_KEY_PATH` | `.env` |

注意：`erp-redis`（端口 6379，业务缓存）用的是 **`C:\Redis\redis.windows-service.conf`**，
**不是**本目录的 `redis.production.conf`。

## 二、不参与运行，但**必须保留**：灾备随包分发件

`fastapi_app/services/backup/_constants.py:89-104 config_files_to_package()` 会把下面这些
文件打进**加密备份包**，供灾难恢复时还原：

- `nginx.conf`（归档内 `nginx.conf`）—— 这是 Docker/Linux 形态的 nginx 配置，
  本机运行时不加载它，但它是灾备件；
- `redis.production.conf`（归档内 `redis.production.conf`）；
- `.env.production`（归档内 `.env.production`）；
- 现役 JWT 密钥（按 `settings` 推导，随轮换自动跟进）；
- 项目根的 `.env`（归档内 `root/.env`）。

⚠️ 因此**不要**因为「本机没在跑」就把 `nginx.conf` / `redis.production.conf` /
`.env.production` 删掉 —— 删掉等于把灾备包里的配置一并挖空。

## 三、未接线（死配置）：没有任何运行体

以下文件全部按 **Docker 主机名**编写（`app:5002`、`nginx:80`、`loki:3100`、
`postgres:5432` 等），而本仓库内**既无 Dockerfile 也无 docker-compose**，
本机也没有对应的容器/进程在跑；全仓库 Python 代码对这些文件**零引用**（唯一命中是
`scripts/prod_audit/layers/l8_observability.py:663` 里一个报告文件名常量）。

| 文件 | 状态 |
|---|---|
| `prometheus.yml` | 无运行体，无抓取目标在线 |
| `alert_rules.yml` | 7 条告警规则，因 Prometheus 未运行而**从未被求值** |
| `alertmanager.yml` | 同上 |
| `otel-collector.yaml` | `.env` 中 `OTEL_ENABLED=false` |
| `promtail.yml` | 无 Loki |
| `grafana/dashboards/*.json`、`grafana/provisioning/**` | 无 Grafana |

**不要据此判断「本系统有监控」。** 真实可观测性现状：

- 应用日志：`logs/fastapi_YYYYMMDD.log`（JSON，按天轮转，保留 14 天，见 `core/logger.py`）；
- nginx 日志：`logs/nginx-*.log`；
- 存活/就绪/ARQ 探针：`GET /api/health`、`/api/health/ready`、`/api/health/arq`；
- 主动巡检与告警：`scripts/ops/watchdog.py`（Windows 计划任务每 5 分钟一次，
  覆盖服务存活、探针、备份新鲜度、磁盘水位，复用 `BACKUP_ALERT_WEBHOOK_URL` / SMTP 通道）；
- 指标抓取：`GET /metrics`（仅本机；生产还需 `METRICS_BEARER_TOKEN`，见 `core/health.py:206-213`）。

## 四、已备好但当前未部署

| 目录 | 说明 |
|---|---|
| `pgbouncer/` | `.env` 未启用 `PGBOUNCER_ENABLED`，本机无 pgbouncer 进程；`pgbouncer.windows.ini` 已按 Windows 路径写好 |
| `postgres/init-replica.sh`、`init-replication.sh` | 只读副本的**一次性**搭建脚本，非持续运行件 |

## 五、环境变量：单一来源与漂移检查

本目录的 `.env.production` 是**灾备随包分发件**（第二节），运行时**不被加载**；
运行时唯一被加载的是项目根的 `.env`。改配置、查漂移、灾备恢复顺序见
[docs/runbooks/env-config.md](../docs/runbooks/env-config.md)（含 S3 新增的生产启动强校验说明）。
