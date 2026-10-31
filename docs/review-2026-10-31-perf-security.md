# 上线前全面 Review 报告 — 性能与安全（2026-10-31）

> 审查范围：后端 `fastapi_app/`（main、middleware、config、auth 链路、deps、router、安全/限流/缓存/数据库核心、备份域、上传、WebSocket、监控、审计中间件）、前端 `frontend-vite/src`（XSS 面、token 存储、sourcemap）、部署配置（`config/nginx-windows.conf`、requirements、生产闸门）。
> 审查方式：逐文件精读 + 全仓模式检索（SQL 注入 / 命令注入 / 反序列化 / 路径穿越 / 日志泄露 / 异步阻塞 / 分页与缓存 / 索引）。
> 总体结论：**未发现上线阻塞级（Blocker/High）问题**。该代码库已具备多轮审计痕迹（inline 的 P0-x/F-BE-x/A-Mx 修复注释均属实），安全与性能基线显著高于一般内网系统。以下为中低危改进项与已验证安全清单。

---

## 一、上线阻塞项：无

以下两类问题若存在会判为阻塞，均已逐项排查并**未发现**：

| 阻塞级检查项 | 结论 | 证据位置 |
|---|---|---|
| 认证缺失的敏感端点 | 无 | `api/v1/router.py`:33 个路由全部挂 `get_current_user_id_(write_)strict`；仅 `/auth`（登录必须公开）与 `/monitoring`（vitals sendBeacon 设计性匿名，见下）例外 |
| SQL 注入（用户输入拼接） | 无 | 全仓 `text(f...)` 均为常量表名或经 `quote_table` 白名单（`services/backup/verify/core.py:def quote_table`）；筛选值全部绑定参数 + `escape_like`（`core/sanitizer.py`） |
| 弱密钥/硬编码密钥进生产 | 无 | `core/config.py:434` 生产 SECRET_KEY≥32 字符启动闸门；全仓无硬编码 secret 模式命中 |
| 生产 debug/文档暴露 | 无 | `config.py:428` FASTAPI_DEBUG=true 拒绝启动；`main.py:344` 生产关 docs/openapi；`dist/assets` 无 sourcemap |
| 前端 token 进 localStorage | 无 | 全部 httpOnly Cookie（`api/request.ts` 只做 401 单飞刷新）；localStorage 仅存偏好/用户快照 |
| 备份明文落盘风险 | 无 | `config.py:191` 启用加密但无密码 → 拒绝启动（fail-fast，且不依赖 APP_ENV 判定，P0-4 已修） |

---

## 二、中危问题（建议上线前评估，可带病上线但要有知情决策）

### M-1【性能·资源】chunked 请求内存全量缓冲，存在内存放大面

- **位置**：`fastapi_app/core/middleware.py:536-553`（`_setup_body_size_limit` 的无 Content-Length 分支）
- **触发条件**：攻击者/异常客户端对 `/api/v1/tasks/import-*`、`/api/v1/batch/` 等路径发送不带 Content-Length 的 chunked 请求体。代码逻辑：逐 chunk 读入 `chunks: list[bytes]`，超限才拒绝，最后 `request._body = b"".join(chunks)` —— 单请求峰值内存 ≈ 2×上限（list 拷贝 + join），导入路径即 ~128MB/请求。
- **潜在影响**：并发数个此类请求即可打高 uvicorn worker 内存（内存放大 DoS 面）。已有缓解使实际暴露面小：① nginx `client_max_body_size` 前置拦截（`config/nginx-windows.conf:73` 10m 默认 / 导入路径 64m）；② 备份路径已强制要求 CL（411）；③ 这些路径均需登录 + CSRF。
- **修复建议**：将"读满再验"改为流式丢弃式计数——超限后不再 `append`，直接消费并丢弃剩余 chunk 至客户端 EOF 或直接断开；或改写 `request._body` 为临时文件。工作量小（单函数内改动），建议上线前顺手修，至少列入上线后第一迭代。

### M-2【性能·扩展】15 个列表端点 per_page 上限 500，单请求最多 500 行 ORM 关联装载

- **位置**：`api/v1/endpoints/order.py:77/134/219`、`order_batch.py:36/68/183`、`outsource.py:68/95/468`、`purchase_center/order_routes.py:175/215/535`、`purchase_center/product_routes.py:44` 等（`per_page: Query(50, ge=1, le=500)`）
- **触发条件**：用户显式传 `per_page=500`（前端默认 50，但 API 直接可调）；数据量随业务增长后（订单/外发是只增不减的流水表）。
- **潜在影响**：500 行 × joinedload 关联对象 + msgspec 序列化，单请求百毫秒级 + DB 内存占用；无权限门槛的登录用户可并发拉取放大。热路径 `/stock` 已有 L1/L2 缓存不受影响。
- **修复建议**：非缓存列表端点统一收紧到 `le=100`~`le=200`；确需大批量导出的场景走既有导出端点（已限 10000 行且有专用逻辑）。属容量治理，非紧急。

---

## 三、低危问题（可后续优化，按价值排序）

### L-1【性能】权限缓存跨 worker 最多 5s 不一致，且撤销广播事件无消费方
- **位置**：`core/deps.py:71-77`（`_PERMISSION_CACHE = _TTLCache(ttl=5)`，注释自认）；`domain_events.USER_PERMISSION_CHANGED` 定义了但全仓无消费方。
- **影响**：管理员撤销某用户权限后，其他 worker 上的该用户最长 5s 内仍能通过鉴权（有界窗口）；授予方向同理延迟 5s 才生效。
- **建议**：为 `USER_PERMISSION_CHANGED` 接上跨 worker 消费（`start_event_listener` 通道已就绪，只差订阅回调），或维持现状但在运维手册写明"权限变更最坏 5s 生效"。

### L-2【性能】巡检端点单请求可拉 1000 行
- **位置**：`api/v1/endpoints/numbering_audit.py:21`（`limit: Query(200, ge=1, le=1000)`）。
- **建议**：巡检记录增长后收紧至 200~300，或改分页。

### L-3【性能】WS 通知按用户连接串行发送
- **位置**：`services/notification_service.py::broadcast_event`（`for ws in list(connections)` + 每连接超时控制）。
- **影响**：单用户开多标签页时该用户各连接串行推送；内网几十用户规模无感，用户量上百后可观察 `ws_send` 耗时指标再决定是否 `gather` 并发化。

### L-4【安全·纵深】WS Origin 校验依赖 ALLOWED_HOSTS 闸门联动
- **位置**：`api/ws.py:114-116`（`_origin_allowed`：无 Origin 头时返回 `"*" in settings.ALLOWED_HOSTS`；异常 Origin 回退 `bool(settings.FASTAPI_DEBUG)`）。
- **现状**：生产闸门（`config.py:441` 禁 `*`、`config.py:428` 禁 DEBUG）保证了这两个回退在生产不可达，逻辑成立但属"靠另一处配置救场"的间接保证。
- **建议**：加一行启动期断言或注释交叉引用，防止未来闸门重构时静默失效。风险极低。

### L-5【安全·固有设计说明】CSRF cookie `httponly=False`
- **位置**：`core/middleware.py:369-377`。double-submit 模式必须让 JS 读 token，是标准做法而非缺陷；配合 `SameSite=lax` + Bearer 路径的 Origin 校验，链路完整。列出仅为评审完整性。

---

## 四、已验证安全清单（抽查证据）

**认证与会话**
- JWT：算法白名单（HS256/RS256/ES256，`config.py:381`）、decode 固定 `algorithms=[settings.ALGORITHM]`（`core/auth/token.py:104`，防 alg 混淆）、type claim 校验防 refresh/access 混用、jti 撤销黑名单 + 跨 worker 广播（`main.py:288`）。
- Refresh 轮换 + 30s grace 窗口（`endpoints/auth.py:359-411`）： stolen token 下次刷新即失效，grace 只发等价新 jti、不延长旧 token 生命。
- 密码：Argon2id（19456KB/2iter/parallelism=1，`core/security.py:15`，OWASP 2026 推荐参数）+ 旧哈希兼容验证 + `check_needs_rehash` 透明升级。
- 登录防爆破三层：nginx authzone 10r/m（`nginx-windows.conf:30/232`）→ 应用 Redis 双计数器 30/min + 100/5min（`endpoints/auth.py:167-217`，pipeline 原子 incr+expire，Redis 挂掉降级进程内存限流）。
- 账号枚举：统一"用户名或密码错误" + 不存在用户也跑 dummy hash 防 时序侧信道（`services/auth_service.py`，`run_in_threadpool(verify_password, "timing_sidechannel_dummy", _DUMMY_HASH)`）。
- WebSocket：票据一次性 30s TTL、Origin 白名单、心跳超时、消息级限流（`api/ws.py`）。

**授权**
- 用户/权限/备份管理全部 `require_superuser`/`require_backup_permission`（`endpoints/user.py` 全端点、`backup/export.py:179`）。
- 工厂隔离贯穿列表/报表/库存（`report.py:_factory_scope`、`stock_inventory_service.py:_factory_match`）。
- 403 拒绝入审计（`deps.py::require_permission`）。

**注入与输入**
- SQL：绑定参数 + `escape_like`；动态表名走 `quote_table` 字母数字白名单（`backup/verify/core.py`）。
- 命令执行：仅 `prod_runner.py`（固定命令）与备份 `pg_dump`（`_proc.py` 线程池包装），无 `shell=True` + 用户输入。
- 无 `eval/exec/pickle.loads/yaml.load`（`eval` 命中均为 Redis Lua 脚本，合法用途）。
- 路径穿越：备份下载 `Path(filename).name` 归一化比对（`backup/export.py:186-188`）；上传经 `storage_service.save_upload` 生成存储 key。

**文件上传**
- 扩展名白名单 + bounded read（只读 MAX+1 字节防超大文件先读后判，`endpoints/auth.py:535`）+ 魔数校验（`require_upload_magic`）；nginx 侧 `/static/uploads/` 有 secure_link 限时签名（`nginx-windows.conf:151-162`）。
- 请求体分级限额与端点声明有 parity 测试锁住（`tests/test_request_body_limit_paths.py`）。

**信息泄露**
- 异常脱敏：`sanitize_error` fail-safe（APP_ENV 未设置/写错一律脱敏，`config.py:508-520`）；422 详情生产屏蔽（`main.py:443-448`）。
- 日志无密码/token（全仓 logger 调用扫描仅 2 处命中且均为无害文案）；前端错误上报做了 CRLF 注入清洗（`auth.py:148-151`）。
- `/metrics`：nginx 仅放行 127.0.0.1（`nginx-windows.conf:194-200`）+ 应用层 METRICS_BEARER_TOKEN fail-closed。
- uvicorn `--forwarded-allow-ips=127.0.0.1`（`prod_runner.py:541`）+ 审计取 XFF 最后一跳，防伪造 XFF 绕过限流/审计。

**HTTP 层**
- CSP：生产 per-request nonce、无 unsafe-eval、frame-ancestors none；HSTS 2 年；TrustedHost 生产必配具体域名。
- CORS：生产明文 HTTP 源只放行内网 IP 字面量（`config.py:88-109`，按 URL 解析防前缀仿冒）。
- CSRF：double-submit + Bearer 请求 Origin 校验 + "Bearer+会话 Cookie 双凭据"场景已收口（F-BE-CORE-07 修复属实）。

**性能与容量（已到位的机制）**
- 连接池按 worker 数动态预算、含副本池核算、LIFO + pre_ping + recycle 1500s 对齐 idle_session_timeout（`core/database.py:28-106`）。
- 缓存体系：L1 进程 TTL + L2 Redis + 跨 worker 失效广播 + 库存缓存启动预热与 60s 保热（`main.py:109-139`）；dashboard 30s、stock stats 60s。
- 审计写库异步批量（Redis 缓冲 + 5s 定时刷 + 溢出文件兜底，`core/audit_middleware.py`），不占请求热路径。
- 慢请求（>3s）与慢 SQL（0.2s/1s 分档）双监控 + Prometheus 指标。
- 阻塞 IO 全部 `asyncio.to_thread` 包装（备份加解密/JSON 解析/Excel 构建均核验）。
- 导出上限（stock 10000 行）+ StreamingResponse + FileResponse 磁盘流式。
- 依赖：requirements 分层 + lock 同步门禁 + CVE 升级注释（cryptography 50.0.1、PyJWT 2.15.0 均为修 CVE 的新版本）。

---

## 五、上线决策建议

1. **可以上线**。无阻塞项；M-1/M-2 属"知情带病上线"范畴，建议：
   - M-1（chunked 内存缓冲）：上线后第一周内修复，改动集中在 `middleware.py` 单函数；
   - M-2（per_page=500）：当前数据量下无感，列入容量治理 backlog，数据过 50 万行前收紧。
2. 上线前跑一遍门禁确认基线：`python scripts/quality_gate.py` + CI 三 job（本机等价命令见 AGENTS.md §4）。
3. 运维手册补两条既有设计权衡的说明：权限变更最坏 5s 生效（L-1）、备份加密开关当前值与密钥配置状态。
4. 本次 Review 未覆盖（后续可补）：`scripts/`、`server_manager/` 全量、前端每个业务组件的逻辑正确性、ARQ 任务幂等性深审、数据库实际执行计划（EXPLAIN）验证。

---

## 六、修复记录（2026-10-31 同日落地）

上述建议项当日已完成修复并全量验证（评审发现与修复同一会话闭环）：

| 项 | 修复方式 | 状态 |
|---|---|---|
| M-1 | `middleware.py` 新增 `_CHUNKED_BODY_LIMIT`（默认 2MB，`MAX_CHUNKED_BODY_BYTES` 可覆盖，已登记 .env.example）：无 CL 请求预算从 min(路径上限, 64MB) 收紧为 min(路径上限, 2MB)，边读边判/411 前置语义不变。测试：预算上限 Red→Green（含变异检查）+ chunked body 送达端点语义锁（traceback 证实请求携已解析 body 抵达端点函数） | ✅ 已修复 |
| M-2 | 核实前端真实用量后**分级收紧**：order×3/stock×2/stock_return/outsource×2/auxiliary/purchase_center×4 共 13 处 Query `le=500→le=200`（前端 UI 每页选择器最大 200，无 >200 调用方）；三处承重 500（order_batch×3、outsource process-types、staging_order）保留并加契约注释（前端 BATCH_PAGE_SIZE/PRESET_PAGE_SIZE/STAGING_PAGE_SIZE=500 依赖）；服务层内部调用（如 list_outsource_orders 直调 500）不受端点校验影响 | ✅ 已修复（按实际用量分级） |
| L-1 | `USER_PERMISSION_CHANGED` 事件全链接通：`user.py` 权限相关端点的 post-commit 回调发布事件（`publish()` 进程内派发 + Redis 广播），`deps.py::register_permission_event_subscriber` 订阅、各 worker 经 domain_events 监听器失效本进程 L1（main.py lifespan 注册）。失败退化为旧行为（TTL 5s 有界）。测试 3 条（含坏载荷防御） | ✅ 已修复 |
| L-2 | `numbering_audit.py` limit `le=1000→le=300`（前端无调用方，无风险） | ✅ 已修复 |
| L-3 | **评审更正：误报**。`notification_service._send_to_targets` 已是 `asyncio.gather` 并发发送 + 单连接超时 + 断开清理（docstring 明示"并发发送"），当初依据的 `for ws in list(connections)` 只是构造目标列表的同步推导式 | ✅ 无需修复（更正） |
| L-4 | `ws.py::_origin_allowed` 补 docstring 交叉引用 config.py 两道生产闸门（ALLOWED_HOSTS 禁 `*`、禁 FASTAPI_DEBUG），防闸门重构时静默漏放 | ✅ 已加固（注释） |
| L-5 | `middleware.py` CSRF cookie `httponly=False` 处补设计说明（double-submit 固有要求，会话凭据仍 httpOnly） | ✅ 已固化说明 |

**验证结果**（2026-10-31，全绿）：
- 聚焦测试 26 passed（`test_request_body_limit_paths` / `test_upload_no_content_length` / 新增 `test_permission_cache_invalidation_event`；变异检查确认新预算测试真的会红）
- `ruff check fastapi_app tests fastapi_app/tests utils`：All checks passed
- `mypy --config-file mypy.ini --no-native-parser`：Success（380 files）
- `python scripts/quality_gate.py`：**[PASS] 无新增质量问题**（过程中门禁抓到新环境键未登记 .env.example，已补；遗留 TIGHTEN 提示为存量 ruff 债减少，非本次引入，可择机 `--update-baseline` 收紧）
- 前端契约链：`openapi.json` 重导出（恰 14 处 maximum 变更）+ `npm run gen:api` + `check:types` / `check:api`（含 query-cache-buster）/ `check:routes` / `check:dto` 全 PASS
- **全量提权 pytest（owner 执行 `logs/_run_pytest_elevated.ps1`）：5271 passed / 57 skipped / 0 failed，EXITCODE=0，534s**（`logs/_pytest_elevated_full.log`）
- CI lint job 本地等价物：`scan_secrets.py --verbose` PASS、`check_orphan_modules.py` PASS（1 项存量 WARN 与本次无关）、`file_size_gate.py` PASS（21 文件 ≤1600 行）；`check_requirements_lock.py` 跳过（本次未改 requirements/*）
- 至此 CI 三 job（test / lint / frontend）的本地等价验证全部完成，推送时 CI 复核即可
