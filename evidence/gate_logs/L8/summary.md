# L8 可观测性审核

## 日志上下文
关键业务操作日志须含 request_id/user_id/业务 ID。

## 日志脱敏
日志参数不得含 password/secret/token/api_key 变量。

## 监控
须有 /health 与 /ready 健康检查端点。

## 链路追踪
core/telemetry.py 须配置 trace ID 传播与 DB span。

## 告警
告警规则须覆盖 error_rate/response_time/cpu/memory/disk 阈值。

## 指标
core/metrics.py 须覆盖核心接口/系统资源/业务关键指标,并暴露 /metrics 端点。
