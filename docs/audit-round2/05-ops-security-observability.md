# 05 · 安全、运维、部署与可观测性审计（t5 完整报告）

> **本文件元信息**（由 docs-archivist 于归档时统一添加，正文未改）
>
- **审计轮次**：2026-10-01 第二轮全面审计（binfa-ERP / D:\erp_system）
- **基线**：aac4c43f59a4374e05cdc5aee6c4aaa8afc99026（2026-10-01 14:52:03，成员取证时的 HEAD）
- **归档 HEAD**：546401ec6cfeb0bb14664d21ff5d06a618a4e060（2026-10-01 15:10:43，chore(types): mypy 覆盖 106→110（OPT-13 第一批），顺带删 staging_utils 死代码）
- **来源**：成员报告 `t5-ops-security.report.md（49,382 B）`（恢复件 49,382 B / 34,003 字符）
- **恢复方式**：captain 从 t5 成员会话转录恢复原报告全文，本文件逐字归档；仅把「## 0. 基线与方法（回应 captain 15:05 提示）」改为「## 0. 基线与方法（归档者整理）」以去掉过程性措辞，正文与 文件:行 未改。
- **完整性**：记为「完整」（168 行，8 个分节 + 可复现命令）。但报告自述取证基线为 aac4c43f、审计期工作树存在他进程并发改动（6 文件 M + 1 文件 D，与该报告证据文件零交集），归档 HEAD 又新增 1 提交。
- **只读声明**：全程只读静态审计：不改代码/配置/数据库，不重启服务、不装依赖、不发起任何攻击性请求；临时脚本仅写 %TEMP%\erp_audit_v2\。本文件是审计产物的**归档副本**，正文结论与 文件:行 证据保持成员原文。
- **归档时间**：2026-10-01（第二轮审计当日）

【硬性提醒】所有 文件:行 均相对基线 aac4c43f 取证；归档时仓库 HEAD = 546401ec6cfeb0bb14664d21ff5d06a618a4e060（2026-10-01 15:10:43）已在其上新增 1 个提交（mypy 覆盖 106→110、顺带删 staging_utils 死代码），行号可能已漂移，引用前请重新核对。

**归档者独立复核（本轮实测，非成员转述）**：抽查 t5 高价值结论：`fastapi_app/api/v1/endpoints/customer_sampling.py:63` 裸 `router = APIRouter()`（无 dependencies）、`:66` PERM='customer_sampling_manage'、9 个 GET 仅注 get_read_db（:71 起）→ 纵向越权读成立；`fastapi_app/core/deps.py:195-199` `_jwt_payload` 命中即 return、跳过撤销/禁用校验（V3）成立；`fastapi_app/core/auth/token.py:57-58` 注入 jti 与 type='access' 成立；`fastapi_app/core/health.py:200-214` /metrics 生产 fail-closed（未配 token 503、token 不符 401）成立；`fastapi_app/main.py:256-271` `_rate_limit_key` 匿名回落 `get_remote_address` 且 `limiter.key_func = _rate_limit_key` 成立；`fastapi_app/core/deps.py:363/383` resolve_production_view_scope / resolve_production_write_scope 空集 403 成立；`fastapi_app/api/v1/endpoints/backup/_deps.py:99` 未登记端点回落 `backup_manage`（fail-closed）成立。**未复核**：_ops/credentials、.env、NSSM 服务与端口运行态等需读敏感文件/运行态的证据，本轮未复现。

---

## t5 安全、运维、部署与可观测性审计（binfa-ERP / D:\erp_system）

## 0. 基线与方法（归档者整理）
- 基线：HEAD = aac4c43f59a4374e05cdc5aee6c4aaa8afc99026（git rev-parse HEAD，2026-10-01 15:08:10 核对），branch=main。
- 审计期工作树确有他进程改动（2026-10-01 15:08:10 git status --porcelain --untracked-files=no）：M fastapi_app/services/base_search_service.py、fifo_allocation.py、order_batch_create.py、order_deduction_service.py、order_utils.py、plan_utils.py；D(staged) fastapi_app/services/staging_utils.py；M mypy.ini。该脏集合与本报告引用的全部证据文件零交集（见下方 sha256/mtime 表），故本报告结论以 HEAD aac4c43f 为准；我未对 mypy.ini 或任何文件做任何修改。
- 只读纪律：仅读文件与只读命令（Get-Item / Get-FileHash / Get-Acl / Get-CimInstance / netstat / git status / git rev-parse / 日志读取）；未发起任何攻击性/扫描性测试，未写业务库，未重启任何服务，未安装依赖，未执行恢复。临时脚本仅落 百分号TEMP百分号\erp_audit_v2\。
- 结构解析用 ast（不用正则）：docs/audit-round2/scripts/routes3.py（路由与依赖提取）+ scripts/routes4.py（include_router 挂载链），二者已随本轮审计归档在原路径 `C:\Users\Administrator\AppData\Local\Temp\erp_audit_v2\`；归档副本头部插入了 9 行来源注释（routes4.py 为 10 行，多一行「# 归档日期」），故 `ROOT = r"D:\erp_system"` 从原 :4 / :3 下移到归档副本 routes3.py:13 / routes4.py:13。
- 证据文件指纹与读取时间窗 2026-10-01 14:07–15:08（sha256 前 16 位 / mtime）：
  - A98B9EC0AD02C698 fastapi_app/api/v1/endpoints/auth.py mtime 2026-09-28 22:09:34
  - 0CCDCD7600F82E86 fastapi_app/api/v1/router.py mtime 2026-09-29 16:17:13
  - 78F962F71C49A1EC fastapi_app/core/deps.py mtime 2026-09-30 19:22:59
  - 20257594AA82F753 fastapi_app/core/config.py mtime 2026-10-01 12:48:11
  - CB0EE48E731C9A87 fastapi_app/core/prod_runner.py mtime 2026-09-30 23:11:09
  - 9C29B0FEC5EC9614 fastapi_app/core/health.py mtime 2026-09-28 18:03:07
  - 5E58AD69E9BD2CF3 fastapi_app/core/logger.py mtime 2026-09-30 13:19:42
  - 002493766CACDDB5 fastapi_app/services/backup/crypto.py mtime 2026-08-24 08:26:42
  - 5BDD825C39146290 fastapi_app/api/v1/endpoints/backup/_deps.py mtime 2026-09-14 08:28:48
  - 80356E4F3B2C91E6 fastapi_app/services/backup/metrics/alert_service.py mtime 2026-08-20 10:36:16
  - 1497D79E99E5EC50 scripts/restore_drill.py mtime 2026-10-01 10:04:51
  - 6CCC769AC1686050 scripts/ops/watchdog.py mtime 2026-09-30 13:19:42
  - DE9E55B8EC784602 config/nginx-windows.conf mtime 2026-09-30 13:19:42
- 运行态取值时刻（只读）：服务/进程/端口 2026-10-01 14:40–15:05；.env 读取 14:3x（必须用 [System.IO.File]::ReadAllLines(path, [Text.Encoding]::UTF8)——PowerShell 5.1 默认编码会误读为 171 行，真值 204 行 / 8643B / mtime 2026-09-30 18:10:22）；日志与备份产物指纹 15:00–15:06。

## 1. 鉴权与权限模型静态审查

### 1.1 结论
- 认证基座合格（ES256 + jti/type 校验 + Argon2id + 刷新轮换 + cookie/Bearer 双通道 + 撤销黑名单）；问题不在加密算法，而在 ①权限点覆盖不完整（382 条非测试路由中 52 条无权限点，customer_sampling 存在同模块读写权限不一致的纵向越权读）②匿名限流键可被 XFF 伪造 ③若干取证/边界缺陷。
- 未发现远程未授权访问敏感数据的活路径：11 条无认证路由全部是匿名必需（login/logout/refresh）、探针（health/ws）或已 fail-closed 的 /metrics。

### 1.2 认证链（正面证据）
- JWT：fastapi_app/core/auth/token.py:57-58 create_access_token 注入 jti=uuid4().hex 与 type='access'；:83-97 _decode_jwt_token(token, expected_type=...) 校验 type claim，失败抛 401；_get_signing_key/_get_verify_key 支持 HS256/RS256/ES256。.env JWT_ALGORITHM=ES256（行 60 注释：2026-08-22 轮换，旧密钥曾泄漏至远端仓库 83af148）。
- 撤销：fastapi_app/core/auth/blacklist.py:61-81 revoke_token 以剩余有效期作 TTL；is_token_revoked(jti, fail_closed=False)（:102-139）Redis 不可用时 fail-open 并打限频 60s 的 critical 日志（:96-99）；fail_closed=True 抛 401。
- 口令：fastapi_app/core/security.py:13-20 Argon2id（m=19456, t=2, p=1, hash_len=32, salt_len=16），兼容 bcrypt/pbkdf2/scrypt 且登录时自动重哈希；fastapi_app/services/auth_service.py:19 _DUMMY_HASH，用户不存在/禁用时同样执行一次 verify 消除时间侧信道（auth_service.py:48/52）。
- 会话：fastapi_app/api/v1/endpoints/auth.py:198-213 _set_login_cookies（httpOnly + SameSite/Secure 自适应）；auth.py:345 REFRESH_ROTATION_GRACE_SECONDS=30.0、:410-422 复查新 jti 是否已吊销、:443-445 吊销旧 jti；登录限流 LOGIN_BURST_LIMIT=30/60s、LOGIN_ATTEMPT_LIMIT=100/300s（auth.py:27-30），/login 装饰 limiter.limit('100/minute')（auth.py:217）。
- 上传：auth.py:484-527 白名单 {png,jpg,jpeg,gif,webp} + MAX_UPLOAD_SIZE=5MB + 魔数校验 + 仅读 MAX+1 字节。
- 越权护栏正向设计：fastapi_app/core/deps.py:363/383 resolve_production_view_scope / resolve_production_write_scope 空集时 403（不降级为不过滤）；fastapi_app/api/v1/endpoints/backup/_deps.py:26-99 未登记端点名默认回落 backup_manage（fail-closed）。

### 1.3 权限点覆盖率（AST 全量，可复现）
- 口径：python routes3.py 提取 391 项 @router.<http> 装饰器（含 tests）；python routes4.py 解析 fastapi_app/api/v1/router.py 的 include_router(..., dependencies=[...]) 挂载认证依赖后聚合。
- 结果：非测试路由 382 条，其中 52 条无任何权限点；11 条既无权限点也无认证依赖（**52 与 11 均已在 2026-10-01 归档复算中复现，见下方「复算与口径标注」**）。
- 11 条无认证路由逐条：fastapi_app/api/v1/endpoints/auth.py:216 POST /login、auth.py:273 POST /logout、auth.py:372 POST /refresh、fastapi_app/api/v1/endpoints/monitoring.py:205 POST /vitals、fastapi_app/api/ws.py:107 WEBSOCKET /ws/notifications、fastapi_app/core/health.py:200 GET /metrics、health.py:218 /api/health/live、health.py:226 /api/health/ready、health.py:259 /api/health/startup、health.py:277 /api/health/arq、fastapi_app/main.py:415 GET /。合理性：monitoring.py:205 由 sendBeacon 上报无法带 Authorization 头（router.py:279-283 注释）；health 四探针供 prod_runner 3s 轮询；main.py:415 为根路由。
- /metrics 已 fail-closed：fastapi_app/core/health.py:209-211 生产且未配 METRICS_BEARER_TOKEN 返回 503「监控端点未启用」；token 不匹配返回 401（:212-213）。本部署 .env:192 METRICS_BEARER_TOKEN=<len:43> 已配 ⇒ 历史 A-M1（/metrics 无鉴权）已修复。
- 52 条「已认证但无权限点」分布：customer_sampling.py 9、daily_production.py 9、dashboard.py 8、auth.py 7、health.py 7、notification.py 5、monitoring.py 2、customer.py:197、numbering_audit.py:19、stock.py:422、main.py、ws.py。

#### 复算与口径标注（docs-archivist 于 2026-10-01 归档时补充；同日 t9 修正「11」的误降级，未改动上方任何数字）

- **脚本归档**：`docs/audit-round2/scripts/routes3.py`（原 71 行，SHA256 `22B4E595B00C57BC464A3CE3C259D940FDB729E77997467C5EFC2B1A8454A22D`）与 `docs/audit-round2/scripts/routes4.py`（原 99 行，SHA256 `CB7BC413DF13E95AFAFF5AE5842907B43F669456B19DF6FD40BBDC433825E67E`）。另有归档者自编的 `docs/audit-round2/scripts/normalize_deps.py`（**非 t5 原始脚本**，故无「原始 SHA256」；用于把上面两个 JSON 的 key 归一化后复算 52 与 11）。三者的共同边界：标准库 `ast`/`json`/`os`/`io`。**硬编码 `ROOT = r"D:\erp_system"`**（换机器需改这一行）；**只做 AST 静态解析，不连库、不启动服务、不写仓库**；输出写死到 `C:\Users\Administrator\AppData\Local\Temp\erp_audit_v2\routes3.json` / `routes4.json`（该目录需预先存在）。
- **运行命令**（PowerShell，工作目录 `D:\erp_system`；加 `PYTHONDONTWRITEBYTECODE=1` 以免在仓库留下 `__pycache__`）：
  ```powershell
  $env:PYTHONDONTWRITEBYTECODE='1'
  python docs/audit-round2/scripts/routes3.py   # -> routes: 391 / with param deps: 373
  python docs/audit-round2/scripts/routes4.py   # -> routers: 48 / files with includes: 6
  python docs/audit-round2/scripts/normalize_deps.py   # -> 52 无权限点 / 12 无 get_current_user_id / 11 无认证（RESULT: 11）
  ```
- **输出 JSON 口径**：`routes3.json` 是 391 行数组（每行含 `file`/`line`/`func`/`method`/`path`/`param_deps`/`decorator_deps`/`router_deps`/`annotations`）；`routes4.json` 含 `routers`/`includes`/`endpoint_include` 三段，`endpoint_include` 给出每个端点文件在 `fastapi_app/api/v1/router.py` 的 `include_router(..., dependencies=[...])` 挂载项。
- **52 的口径规则**（把两文件拼起来即可复算）：非测试路由 = `routes3` 全量 391 行剔除文件路径含 `tests` 的 9 行 → **382** 条；对每条把「路由函数 `Depends(...)` 参数默认值（`param_deps`）+ 装饰器 `dependencies=`（`decorator_deps`）+ 挂载层 `include_router(dependencies=...)`」三者合并，**不含任何以 `require_` 开头的依赖**（即 `require_permission` / `require_any_permission` / `require_superuser` / `require_backup_permission`）者，共 **52** 条。（挂载层 deps 必须按「正斜杠归一化后」的文件 key 关联，见下条根因说明；不同则挂载层全丢，会得到错误的 31。）
- **复算结果（2026-10-01，只读，HEAD `546401ec`）：52 条复现成功**，且分布与上文逐项一致：customer_sampling.py 9、daily_production.py 9、dashboard.py 8、auth.py 7、health.py 7、notification.py 5、monitoring.py 2、customer.py 1、numbering_audit.py 1、stock.py 1、main.py 1、ws.py 1。
- **若改用「依赖名含 `permission`」的更宽口径**（把 `get_current_user_with_permissions` 也算作权限点）则得 **48**；两者的**差额是 4 条**（52 − 4 = 48）：`daily_production.py:126` POST `/records`、`daily_production.py:164` PUT `/records/{record_id}`、`daily_production.py:203` DELETE `/records/{record_id}`、`dashboard.py:96` GET `/mobile`（依赖在源码 `dashboard.py:100`）。这 4 条只依赖认证 + 部门数据作用域，**没有资源级权限校验**，所以原口径把它们计入「无权限点」是合理的（该结论仍成立，但机制不是「裸端点」而是「无权限校验器」）。**口径边界（复算说明）**：此处 48 是在原 52 集内重新判定（52 − 4）的结果；若把「依赖名不含 `permission`」直接用于全量 382 条非测试路由独立统计则得 **60**（多出的 12 条依赖 `require_superuser()` / `require_superuser('order_manage')` 等不含子串 `permission` 的校验器），两种口径不可混用。
- **口径确认：「11 条既无权限点也无认证依赖」已复现（2026-10-01 t9 撤销 t8 的「待复现」误判）**。在 52 集内合并 `param_deps` + `decorator_deps` + `router_deps` + **挂载层 `include_router(dependencies=...)`**（挂载层按归一化 key 关联）后，不含 `get_current_user_id` 者为 **12** 条；其中 `fastapi_app/core/health.py:82` GET `/api/health` 的函数签名带 `Depends(_get_optional_user)`（源码 health.py:83：`user_id: int | None = Depends(_get_optional_user)`，未登录时为 `None`，属**用户识别依赖而非认证门槛**），按 t5 的「认证依赖」判据排除后**恰为 11 条**，与上文第 60 行逐条一致：auth.py:216/:273/:372、monitoring.py:205、ws.py:107、health.py:200/:218/:226/:259/:277、main.py:415。复算脚本：`docs/audit-round2/scripts/normalize_deps.py`（只读、纯 AST/JSON、不连库；预期输出 `52 -> no-permission routes: 52`、`12 -> …`、`11 -> RESULT: 11`）。
- **⚠️ t8「31 / 27 / 43」的根因（已作废，仅保留记录以便复核）**：`routes3.py` 的 `file` 是反斜杠路径（`os.path.relpath`，归档副本 routes3.py:43/44/76），而 `routes4.py` 的 `endpoint_include[].file` 是正斜杠路径（归档副本 routes4.py:34 写入、:98/:106 输出）——两者**不做归一化则 key 0 命中，挂载层 `dependencies` 全部丢失**，于是 52 集内「无认证依赖」被误算成 **31**（假象是「21 条有认证」）；同源的另两个数也不成立：宽口径（任意含 `user`/`permission`）过滤得 **27**，只统计函数参数默认值（漏装饰器与挂载层）同样得 **31**；而 **43 = 52 − 9** 只是「52 条中完全没有任何 `Depends` 参数者 9 条」的取补。**上述四个数（31 / 27 / 31 / 43）均不得再引用**。
- **与 t4 finding 6 的关系**：t4 指出「52 不可复现」的根因是本处未归档统计脚本；本块把脚本、命令、输出路径、口径规则全部补齐后，**52 已可复算**；t4 提到的 36 / 87 两个数字出自未归档的等效实现，其口径与本归档脚本不同（36 偏窄：大概率只扫函数参数默认值而漏掉装饰器/挂载层；87 偏宽：把测试替身与名称为 `require_permission` 的 monkeypatch 目标也算成路由），本归档脚本的口径见上，**三者不可混用**。
- **本块未改动 §1.3 原结论的任何数字**（52 / 分布 / 11 均按原文保留），仅在其后补充复算路径与上述口径标注。

### 1.4 越权风险点（逐条）
- V1（high，纵向越权读）fastapi_app/api/v1/endpoints/customer_sampling.py：模块头注释 customer_sampling.py:4 声称「所有端点需登录（router 级 dependencies），写操作需 customer_sampling_manage 权限」，但 customer_sampling.py:63 是裸 router = APIRouter()（无 dependencies），登录依赖只来自 fastapi_app/api/v1/router.py:294-298 的挂载；PERM='customer_sampling_manage'（:66）。写端点均带 current_user: User = Depends(require_permission(PERM))（:123-124 / :148 / 其它），而 9 个 GET 只带 db: AsyncSession = Depends(get_read_db)：:71 /grouped-list、:90 /projects、:109 /projects/{project_id}、:241 /projects/{project_id}/parts、:370 /projects/{project_id}/versions、:382 /versions/{version_id}、:394 /projects/{project_id}/change-logs、:408 /projects/{project_id}/parts-by-version、:426 /projects/{project_id}/roles（依赖注入点 :79/98/113/246/374/386/400/418/430）⇒ 任一已登录账号（含最低权限角色）可读取全部打样项目、零件、版本、变更日志与角色分配，且注释与实现自相矛盾。
- V2（medium）fastapi_app/api/v1/endpoints/daily_production.py 9 条（:58 GET /records、:126 POST /records、:164 PUT /records/{id}、:203 DELETE /records/{id}、:234 /daily-summary、:260 /monthly-summary、:290 /trend、:327 /export、:373 /product-info/{id}）仅挂 resolve_production_view_scope（数据作用域）而无权限点 ⇒ 权限裁剪完全依赖 scope 解析，若角色-生产线映射配置缺失则退化为全量可见/可见即可写。
- V3（low，潜伏）fastapi_app/core/deps.py:195-199：cached_payload = getattr(request.state,'_jwt_payload',None) 命中即 return int(user_id)，跳过 is_token_revoked 与 _verify_user_active。_jwt_payload 仅由 _get_user_id_from_jwt（deps.py:126）/ _get_user_id_from_cookie（deps.py:147）经 _resolve_user_id（deps.py:155-160）写入；全部调用点：main.py:262（限流键，晚于鉴权依赖）、audit_middleware.py:126/178（在 call_next 之后）、deps.py:201 ⇒ 当前无可利用绕过，属排序性潜伏风险：任何未来在鉴权前调用 _resolve_user_id 的中间件都会静默关闭撤销/禁用校验。
- V4（medium）匿名限流键可伪造：fastapi_app/main.py:256-271 _rate_limit_key 已登录按 user:{id}、否则 get_remote_address(request)（slowapi 取 XFF 第一段）；fastapi_app/core/limiter.py:49-59 的 key_func 在 main.py:271 被覆盖 ⇒ 构造 X-Forwarded-For: 随机IP 可绕过 /login、/refresh 的 IP 限流（30/60s、100/300s、100/minute），恰是爆破防护所在。放大条件：fastapi_app/core/prod_runner.py:258-271 保留 --forwarded-allow-ips=*（信任任意对端），config/nginx-windows.conf:60/117 用 $proxy_add_x_forwarded_for 把客户端自带 XFF 原样保留在链首。
- V5（low）审计 IP 取值：fastapi_app/core/audit_middleware.py:135-138 与 :203-205 取 forwarded.split(',')[-1]，而 :136 注释写「取第一个 IP 会被伪造」——注释与实现相反；与限流键（取第一段）口径也不一致，事件归属会指向 nginx 回环地址。
- V6（low）权限模型细节：fastapi_app/shared_models/user.py:44-77 SENSITIVE_PREFIXES=['user_']（任何 user_* 权限码仅 is_super 可通过）、is_super 放行一切、父级 *_manage 自动授予子 *_view（:70-74）——设计清晰，但缺少「写权限隐含读权限」的显式文档，易被误用。

## 2. 配置与密钥卫生

### 2.1 结论
- 代码侧没有硬编码真密钥（值得肯定），但运维侧明文密钥落盘 + 全仓 ACL 过宽 + Redis 口令进命令行/注册表三条叠加，使本机任一已认证本地用户即可取得全部生产密钥；配置漂移工具（check_env_drift.py）已识别「缺键静默走默认值」这一最大隐患，但只手工运行、无 CI 门。

### 2.2 证据
- 明文密钥落盘（medium-high）：_ops/credentials/_backup_encryption_password.txt:5（现役备份加密口令，827B 文件）、_ops/credentials/_metrics_bearer_token.txt:1（43B）、_ops/credentials/.env.bak-20260911（4,798B）与 .env.bak-20260927-085022（7,664B，两份完整 .env 副本）、_ops/audit_scratch/_probe_tables.py:2 与 _probe_users.py:2（DB_PASSWORD 字面量）。扫描方法：以 .env 中 6 个真实密钥字面量（DB_PASSWORD / REDIS_PASSWORD / SECRET_KEY / BACKUP_ENCRYPTION_PASSWORD / PG_SUPER_PASSWORD / METRICS_BEARER_TOKEN）在 fastapi_app、config、scripts、frontend-vite/src/utils、docs、_ops、server_manager、migrations、tests 下做 SimpleMatch。fastapi_app 内命中仅测试夹具假口令（fastapi_app/tests/test_backup_encrypted_restore_path.py:87、test_backup_m0_hotfix.py:224、test_user.py:12/19）⇒ 无真密钥入库。
- 入库纪律（正面）：.gitignore:337[ / _ops / ]（斜杠包裹的忽略行）；git ls-files -- '_ops' 为空；被跟踪 env 相关文件仅 .env.example、.env.production.example、config/jwt/README.md；config/pgbouncer/ 只有 userlist.txt.example（真实 userlist.txt 不在磁盘）⇒ AGENTS 5.2 红线未被破坏。其余：.gitignore:30-35（.env 系列）、:38-40（config/jwt/*.pem）、:43-44（backups/*.key）、:399（精确匹配 config/pgbouncer/userlist.txt）。git config core.hooksPath = D:\erp_system\.githooks（5.6 未被改动）；.git/hooks 无非 sample 钩子。
- ACL 过宽（high）：D:\erp_system 根 ACL 含 NT AUTHORITY\Authenticated Users | Modify, Synchronize | Allow | 继承，与 BUILTIN\Users | ReadAndExecute, Synchronize | Allow | 继承；且 .env、.env.production、config\jwt\（private_v2.pem 232B / public_v2.pem 182B）、backups\server、logs、_ops\credentials、_ops\audit_scratch 全部继承同一组 ACE，无任何针对密钥的收紧 ⇒ 本地非管理员可读 ES256 签名私钥与全部口令，并可写 backups/ 与 logs/（留痕与备份产物可被篡改）。本机启用账号 CodexSandboxOffline（最后登录 2026-09-18 19:35:53）、CodexSandboxOnline 使该授权是活路径；Administrators 组仅 DESKTOP-11111\Administrator。
- Redis 口令泄漏面（medium-high）：Get-CimInstance Win32_Process 显示 pid 5360 = C:\Redis\redis-server.exe C:\Redis\redis.windows-service.conf --requirepass <32 位明文>、pid 5372 broker 同口令 ⇒ 进程命令行（任务管理器/WMI）可见；HKLM:\SYSTEM\CurrentControlSet\Services\erp-redis\Parameters 的 AppParameters 含同一明文，且 Get-Acl 显示该键含 BUILTIN\Users | ReadKey | Allow ⇒ 任意本地用户可读出 Redis 口令。同源暴露：server_manager/redis_ops.py:170-172 把 --requirepass <REDIS_PASSWORD> 拼进命令行。
- 配置漂移（medium）：.env.production 与根 .env 漂移——APP_ENV=development、ALLOWED_HOSTS=*、BACKUP_ENCRYPTION_ENABLED=false、BACKUP_ENCRYPTION_PASSWORD 空；scripts/ops/check_env_drift.py:1-32 docstring 实测（2026-09-30）.env.production 缺模板 92 键、config/.env.production 缺 94 键（含全部 BACKUP_* 约 70 个）；因 fastapi_app/core/config.py:469 SettingsConfigDict(..., extra='ignore')，缺键静默走默认值，最危险组合＝BACKUP_ENCRYPTION_ENABLED 默认 true + 口令缺失 ⇒ 备份静默不加密。scripts/switch_env.py:26-32 production 分支已显式禁用（理由：.env.production 是全占位模板，覆盖 .env 会让应用拿占位符启动即崩），仅 development 会复制 .env.development 到 .env（并留 .env.backup）。
- CORS：.env CORS_ORIGINS 为 6 个 http 源（localhost:3000/5002、192.168.0.95 及 3000/5002），无 https、无 null；fastapi_app/core/config.py:88-109 _is_production_allowed_origin（https 全放行，http 仅 localhost/私有 IP 字面量）、:112-124 filter_cors_origins、生产分支 :394-435 禁 * 主机且 CORS 禁 null 源（_raw_cors 默认串含 null 见 config.py:335）。结论：白名单偏严且可控，无通配；唯一宽松处是 ALLOWED_HOSTS 含 DESKTOP-11111/desktop-11111 主机名（局域网单机可接受）。
- 告警/监控开关全关（high，见第 3 节）：.env:127-128 BACKUP_ALERT_EMAIL_ENABLED=false / BACKUP_ALERT_WEBHOOK_ENABLED=false，BACKUP_ALERT_EMAIL_FROM/TO 空；OTEL_ENABLED=false；SENTRY_DSN 未设置（fastapi_app/main.py:48-53）⇒ sentry_sdk 2.29.1 已装但死置。

## 3. 备份与恢复链路

### 3.1 结论
- AGENTS 5.4 描述的「口令为空时静默降级为不加密备份」仍然存在，且降级只留一条 warning 日志、无外发告警、无 HTTP 提示、无响应字段标记；备份告警链在本部署完全静默（邮件+Webhook 双关）；恢复可验证性名存实亡（自动演练任务从未执行、唯一演练脚本选不到自动化产物、手工恢复脚本只有交互确认且直接 DROP DATABASE）。

### 3.2 降级路径（逐条）
- fastapi_app/api/v1/endpoints/backup/_deps.py:150-170 _resolve_encryption：请求加密但 password 参数 / X-Backup-Password 头 / BACKUP_ENCRYPTION_PASSWORD 三处均空 ⇒ return False, None + 仅 logger.warning('请求加密备份但未配置密码…本次备份将以未加密形式保存')（_deps.py:164-169），注释自陈「fail-safe：宁可明文可还原，不可密文打不开」。调用点 fastapi_app/api/v1/endpoints/backup/export.py:109/292/461/574。
- fastapi_app/services/backup/crypto.py:39-69 get_backup_encryption_password()：FALLBACK_TO_GENERATED 已废弃只告警（:51-55）→ ENABLED 为假直接 None（:57-58）→ PASSWORD → KEY → warning「备份加密已启用但未配置加密密码，备份将不加密」并 return None（crypto.py:68）。
- 生产启动闸门只覆盖一半：fastapi_app/core/config.py:211-228 加密启用且无有效口令 ⇒ RuntimeError 拒绝启动；但 BACKUP_ENCRYPTION_ENABLED 未显式声明时只告警（config.py:215），与 extra='ignore' 静默默认叠加即「以为开了其实没配」。
- 两处默认值相反（low，本部署显式 =true 故未显形）：fastapi_app/services/backup/orchestration/policy_service.py:55 os.environ.get('BACKUP_ENCRYPTION_ENABLED','false')（默认 false）vs fastapi_app/services/backup/_constants.py:43 os.environ.get('BACKUP_ENCRYPTION_ENABLED','true')（默认 true）。
- 加密实现本身稳健（正面）：AES-256-GCM chunked-v1，格式 meta_len(4B 大端)+meta_json+密文（_deps.py:178-185，fastapi_app/core/backup_encryption.py）；加解密模块 ImportError 时 fail-closed 503（_deps.py:186-190 / :214-218，注释记录 H2 旧缺陷「静默返回明文却仍标 .enc」已修）；docs/ui-redesign/backup-center/ENCRYPTION_POLICY.md 文档化四级密码链与「任何情况下都不生成随机密码加密备份」红线（:13/:15），并明确磁盘明文/密文混存是「显式、可追溯的策略，而非缺陷」（:45-48）。

### 3.3 有没有校验与告警
- fastapi_app/services/backup/metrics/alert_service.py（544 行）：send_alert()（:71-128）顺序为累计失败计数 → 写库（:98）→ 写日志（:104）→ if email_enabled and notify 才发邮件（:110-112）、if webhook_enabled and notify 才发 Webhook（:115-117），异常一律吞掉返回 False（:126-128）；_update_failure_count 超阈值只 logger.warning('任务 X 连续失败 N 次，建议升级告警级别')（:150-151）⇒ 无任何外发通道。本部署两个开关均 false ⇒ 备份失败/降级/停摆都不会通知任何人。
- 旁证（实测）：logs/watchdog.log 2026-09-30 11:46:01 / 11:46:12 / 11:46:18 / 11:46:24 连续 4 次 arq_worker=fail; backup_freshness=fail，每行结尾仍是「告警 0 项，通道 无」；scripts/ops/watchdog.py:309-312/332-338 的 webhook/email 发送同样要求对应开关为 true ⇒ 检测到了，但无人被告知。
- 完整性校验是有的：.env BACKUP_VALIDATE_INTEGRITY / BACKUP_VALIDATE_SCHEMA / BACKUP_VALIDATE_CONSTRAINTS=true、BACKUP_PRE_CHECK / BACKUP_POST_VALIDATION=true、BACKUP_INTEGRITY_SAMPLE_RATE=10.0；每个产物有 .meta（例：backups/server/erp_incremental_20261001_070001.zip.enc.meta = created_at 2026-10-01 07:00:01, encrypted true, format_version 2.0, table_count 31, total_rows 10920, failed_tables [], checksum 62cf1b9c…）。但 BACKUP_TEST_BEFORE_DELETE=false ⇒ 删除前不验证，过期备份可能连带删掉唯一可恢复件。

### 3.4 恢复流程可验证性
- 唯一自动化演练脚本覆盖不到真产物（high）：scripts/restore_drill.py（56 行）docstring 称「把最新全量备份恢复到 erp_system_drill，验证备份 artifact 真实可恢复」，:26-29 注释并实现「在导入任何 app 模块前把 DB_NAME 注入为 erp_system_drill」的安全护栏（良好实践），:49 复用生产 dump.restore_database_via_psql；但 newest_backup()（:35-39）= sorted((ROOT/'backups'/'server').glob('erp_backup_*.zip'))[-1] 只匹配手工备份，永远选不到自动化产物 erp_auto_daily_*.zip.enc / erp_incremental_*.zip.enc，也不解密 ⇒ 每日全量+增量链路从未被演练覆盖。
- 自动演练从未发生（high）：BACKUP_RECOVERY_TEST_FREQUENCY=7 无调度承载——logs/erp-arq.log 中 disaster_recovery_test_task 只出现在 worker 注册行「Starting worker for 25 functions」，从未入队；backup_schedule 仅见 18（自定义增量）/19（每日全量）/20（完整性巡检）；backups/server/recovery_tests/ 只有 m5_drill_raw_20260823.json（2026-08-23 03:06:39，2,175B）⇒ 距审计时点超过 5 周无演练产物；backups/server/cleanup_reports/ 最新为 2026-08-20，清理报告同样陈旧。
- 演练/测试库口令回落生产口令（medium-high）：fastapi_app/services/backup/orchestration/recovery_test_service.py:45 'test_password': os.environ.get('BACKUP_TEST_PASSWORD','')、:53 'test_db_password': os.environ.get('BACKUP_TEST_DB_PASSWORD', os.environ.get('DB_PASSWORD',''))；.env 中 BACKUP_TEST_DB_PASSWORD 为空 ⇒ 演练脚本会用生产库口令去连测试库；:333/:343 在无 BACKUP_TEST_PASSWORD 时对加密备份明确抛 ValueError('备份 {name} 已加密，但未配置 BACKUP_TEST_PASSWORD，无法解密还原') ⇒ 按当前配置，加密备份的自动 DR 演练注定失败。
- 手工恢复无护栏：scripts/database/restore_db.py（157 行）执行 DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)（:47-64），唯一确认是 input('确认继续? (yes/no): ')（:121），无 dry-run、无具体 artifact 复核、无二次口令；有 DB_NAME.isidentifier()（:15-17）与 DB_PASSWORD 必填（:19-28）护栏（正向）。

### 3.5 调度与产物实况（实测）
- 每小时增量有 2–4 小时空洞：logs/erp-arq.log 中 schedule 18 入队时刻 2026-09-30 14:00:03、18:00:00、19:40:00、22:00:00、23:10:00；2026-10-01 06:00:00、07:05:00、10:00:00、11:00:00、14:00:00、15:00:00 ⇒ 12:00/13:00、04:00/05:00、08:00/09:00 等窗口无入队且未回补（漏窗口无补偿逻辑）。
- 重复执行：schedule 20（完整性巡检）2026-10-01 03:00:00 与 04:00:00 连续两次入队（幂等键含小时 ⇒ 两次都真跑）。
- 每日全量时间漂移：产物 mtime 2026-09-28 10:00:09、2026-09-29 10:35:09、2026-09-30 10:05:12，10-01 才回到 02:00:13 ⇒ 连续 3 天晚 8 小时执行；根因是 fastapi_app/services/backup/schedule_service.py:146 注释自陈的「DB timestamptz 读出为 aware(UTC)，归一为本地 naive 以便与本地 cron 比较」的 UTC/本地混用（_last_match_before :107-144 逐天回溯最多 370 天；get_due_schedules :237-248 按“已过期未执行”判定）。
- 产物面：backups/server 130 个文件 / 236,843,320 B，其中 66 个 erp_incremental_*、34 个 erp_backup_*、30 个 erp_auto_*；2026-09-27 及更早的每日全量是明文 .zip（erp_auto_daily_20260927_020504.zip 3,733,243B、…20260926_020004.zip、…20260925_222522.zip），2026-09-28 起才是 .zip.enc ⇒ 加密对全量是后加的，且明文件仍在 BACKUP_RETENTION_DAYS=30 保留期内。
- 观测残缺：backups/server/metrics/backup_metrics_20261001.json 的 daily 条目有 duration_seconds 11.54 / backup_size_bytes 4,549,503 / success true / table_count 68 / total_rows 10545，而 incremental 条目 backup_size_bytes: 0、filename: null ⇒ 增量备份规模/文件名未被记录（low）。
- 加密与否由 manifest 决定：fastapi_app/tasks/backup_tasks.py:648-649 依据 manifest.get('encrypted') 在 …zip.enc 与 …zip 间选择文件名 ⇒ 静默降级会直接产出明文 zip 落盘。
- 正面对照：fastapi_app/services/backup/freshness.py:18/21-44 BACKUP_STALE_HOURS=25.0 且绝不抛异常（失败返回 ok=False），被 /api/health 复用；docstring 明确要求「不要据 last_status 判断备份失败，应核对 backups/ 产物时间戳」。

## 4. 部署与运行安全

### 4.1 结论
- 主路径回环绑定已修（uvicorn 127.0.0.1），但仓库里仍留着 scripts/restart_backend.py 的 --host 0.0.0.0 旁路；--forwarded-allow-ips=* 加 nginx XFF 拼接使匿名限流与审计 IP 可伪造；5 个 NSSM 服务全部以 LocalSystem 运行且一键安装脚本不设账户；生产主机上并存多个对外监听的第三方服务（PG 5432、FTP 21、wb2api 7863、RDP 3389）。

### 4.2 证据
- 主路径（正面）：fastapi_app/core/prod_runner.py:258-271 _cmd_uvicorn 现为 --host 127.0.0.1（注释：生产拓扑为同机 nginx(3000) 反代 127.0.0.1:5002）；start.py:66 host = os.getenv('API_HOST','127.0.0.1')；实测 uvicorn pid 15888 命令行确为 --host 127.0.0.1 --port 5002 --workers 8 --http httptools --proxy-headers --forwarded-allow-ips=* --no-access-log。上一轮「0.0.0.0 主路径」结论已过时，本轮修正。
- R9：红线旁路脚本仍在（medium）：scripts/restart_backend.py:64-69 仍是 ['uvicorn','fastapi_app.main:app','--host','0.0.0.0']（且含 --forwarded-allow-ips=*）⇒ 与 AGENTS 5.3 直接冲突；任何运维按脚本手工重启即把后端暴露到局域网，并使 /metrics 绕过 nginx 的 allow 127.0.0.1 限制（config/nginx-windows.conf:139-145）。其余 0.0.0.0 均为 dev/死配置：server_manager/dev_mode.py:111（开发模式）、frontend-vite/vite.config.ts:143/185（dev）、config/pgbouncer/pgbouncer.ini:15（pgbouncer 未运行）、config/otel-collector.yaml:5/7（OTel 未启用）。
- 无后端访问日志：prod_runner.py:269 --no-access-log；HTTP 访问日志只在 nginx（config/nginx-windows.conf:41 access_log logs/nginx-access.log main;，:131/143/180/189 部分 location access_log off;），实测 logs/nginx-access.log 2,010,587B / mtime 2026-10-01 14:42:52 ⇒ 只有 nginx 维度（无 per-endpoint 耗时/status 聚合）。
- 服务账户（medium）：Get-Service 与 Win32_Service 显示 erp-web / erp-prod / erp-arq / erp-redis / erp-redis-broker 5 个全部 StartName=LocalSystem、StartType=Automatic、State=Running；server_manager/service_ops.py:368-405 nssm_install() 只做 nssm install / set AppParameters / set AppEnvironmentExtra，从不设置 StartName ⇒ 一键安装即把 Web、队列、Redis 全部配成最高权限服务。正面对照：PostgreSQL 两个服务用 NT AUTHORITY\NetworkService（D:\PostgreSQL\data 与 replica_data）。
- 监听面（netstat -ano | Select-String LISTENING，2026-10-01 15:0x）：预期内 = nginx 0.0.0.0:3000 与 [::]:3000（pid 19640 / 2716）、uvicorn 127.0.0.1:5002、redis 127.0.0.1:6379、broker 127.0.0.1:6380、只读副本 127.0.0.1:5433、桌面壳预览 127.0.0.1:18923；无 6432（pgbouncer 未运行，Get-Service *pgbouncer* 空）。对外监听（业务无关）：0.0.0.0:5432 与 [::]:5432 PostgreSQL 主库（pid 6472）、0.0.0.0:21 KMFtp.exe（pid 16152，C:\Program Files (x86)\KONICA MINOLTA\FTP Utility\KMFtp.exe）、0.0.0.0:7863 wb2api.exe（pid 16276，D:\workbuddy2api-panel\wb2api.exe -config config.json）、0.0.0.0:3389 RDP、0.0.0.0:135/445/5357、192.168.0.95:139。
- PostgreSQL 深挖：D:\PostgreSQL\data\postgresql.conf:60 listen_addresses = '*'、:64 port=5432、:65 max_connections=100、:132 shared_buffers=3948MB（无 ssl 配置、无 log_* 审计项）；D:\PostgreSQL\data\pg_hba.conf 有效行仅 :113 local all all scram-sha-256、:115 host all all 127.0.0.1/32 scram-sha-256、:117 host all all ::1/128 scram-sha-256、:120-122 replication local/127.0.0.1/::1 ⇒ 局域网只能连上但无法通过认证，pg_hba 是唯一控制点（建议 listen_addresses='localhost' 做纵深防御，并给 5432 加 Windows 防火墙入站规则）。
- 死配置（low）：仓库内 Prometheus/Grafana/OTel/Promtail/Alertmanager 配置全部指向 Docker 主机名（app:5002、nginx:80、loki:3100），但根目录 Dockerfile / docker-compose.yml / compose.yml 全部不存在（scripts/ops/watchdog.py:4-14 自陈），config/alert_rules.yml 的 7 条告警规则无运行体；config/pgbouncer/*.ini 同样无运行体。
- Windows 计划任务（运维自动化缺口）：Get-ScheduledTask 匹配 erp|backup|watchdog|nginx 仅返回 ERPSystem（Disabled，Exec=python，Args=D:\erp_system\start_production.py，BootTrigger 2026-04-07）与 ERP_Database_Backup（Disabled，Args=C:\Users\Administrator\Desktop\erp_system\db_backup.py backup，Daily 10:00）⇒ scripts/ops/install_watchdog_task.ps1（注册 erp-watchdog 每 5 分钟、/RU SYSTEM /RL HIGHEST，靠 scripts/ops/watchdog_task.cmd 调 watchdog.py）从未安装；logs/watchdog_state.json 停在 last_run 2026-09-30T18:10:22。
- 桌面壳权限面：server_manager/app.py:68 import tkinter as tk（+ :67-69），PyInstaller 打包为 server_manager.exe，无 HTTP/socket 监听（grep http.server/websocket/Flask/FastAPI/PySide 在 server_manager 下只命中 tkinter）⇒ 不是远程攻击面；风险是「本机可一键起停服务/杀进程/装服务」，且 server_manager/windows_ops.py:23/31/121/180/256 提供 taskkill / kill_port_sync / kill_process_tree 等强动作，server_manager/redis_ops.py:170-172 会把 Redis 口令放上命令行。server_manager/action_gate.py（140 行）的单一持有者 + 600s 看门狗 + _ActionCancelled(BaseException)（:24-29，避免被 17 处 except Exception: pass 吞掉）是良好设计，非风险。
- 日志有无敏感信息（正面）：fastapi_app/core/audit_middleware.py:119-163 _record_audit 落库字段仅 user_id / username / action / resource_type / resource_id / detail(json: method, path, status_code, duration_ms) / ip_address / user_agent（截断 500） / request_id / status_code / created_at ⇒ 不记请求体、不记 query string、不记 token/口令；且只审计写方法（:102-106）并在 :183-229 为 403 记 required/held permissions。fastapi_app/core/slow_query.py:57-75 _summarize_params 只记参数个数与类型（注释：不记录参数值，防密码哈希/token/PII 入日志）。未发现口令/token/Cookie 写入应用日志。

## 5. 可观测性现状

### 5.1 结论
- 有可用骨架（structlog、prometheus_client、慢查询监听器、健康探针、三态 ARQ 探针、备份新鲜度），但生产实际是半盲：无指标抓取方、无请求耗时、日志结构化只覆盖部分模块且被 UTC/本地错配切碎、备份与演练无自动化观测、告警通道全关。

### 5.2 证据
- 结构化与分级：fastapi_app/core/logger.py:27-45 structlog 处理器链（TimeStamper(iso)、format_exc_info）；_get_renderer()（logger.py:86-92）只在 os.getenv('APP_ENV') == 'production' 字面相等时用 JSONRenderer(ensure_ascii=False)，否则 ConsoleRenderer，而生产判定权威口径是 fastapi_app/core/config.py:48-71 _is_production_env()（取首个空白分隔 token）⇒ 判据不一致（如 APP_ENV 带尾随空白或多值 token，config 认生产而 logger 退化为控制台渲染）；root logger 级别 INFO（logger.py:49）；文件 handler = TimedRotatingFileHandler(logs/fastapi_{UTC 日期}.log, when='midnight', backupCount=14) + Formatter('%(message)s')（:66-77）⇒ 文件名按 UTC 日期、轮转按本地午夜；setup_logging() 在模块导入时执行（:105，自带 TODO(P3) 承认隐式副作用）；get_logger()（:95）。多数业务模块用标准库 logging.getLogger(__name__)（如 slow_query.py:18、crypto.py:14）⇒ 绕过 structlog 处理器，同一文件 JSON 与纯文本混杂（实测纯文本行如「审批状态转换: 'pending' --approve--> 'approved'」「采购订单领域事件订阅已注册: ORDER_DELETED」「慢查询: …」）。
- 多写与切分：logs/fastapi_20260930.log（5,484,235B，mtime 2026-10-01 15:00:48）与 logs/fastapi_20261001.log（4,045,487B，mtime 15:00:58）同时在被写（另有 fastapi_20260930.log.2026-09-30 17,148,791B、fastapi_20260929.log 841,689B、fastapi_20260929.log.2026-09-29 2,895,945B）⇒ 8 个 worker 各自持有 TimedRotatingFileHandler，加上 UTC 命名/本地轮转错配，日志被切成多份、跨天追溯困难。（附带观察到一次 [System.IO.File]::ReadAllText(path, UTF8) 对 5.48MB 文件返回长度 0 的异常，未定因，与本项结论无关。）
- 指标：prometheus_client 0.21.0 已装（Python313 site-packages，同装 structlog 25.5.0 / opentelemetry 1.30.0 / sentry_sdk 2.29.1）；fastapi_app/core/metrics.py:16 缺失时降级并 warning、:250 generate_latest()；但 /metrics 在生产没有抓取方——logs/fastapi_20261001.log:10914/25586/40106 的 /metrics 命中全部是 HTTP Request: GET http://test/metrics "HTTP/1.1 200 OK"（TestClient，来自测试），无真实 scrape。OTEL_ENABLED=false、SENTRY_DSN 未设 ⇒ 追踪与异常上报两个能力都死置。
- 慢查询/慢请求：fastapi_app/core/slow_query.py:20-21 SLOW_QUERY_THRESHOLD=float(os.getenv(...,'0.2'))、SLOW_QUERY_REPORT_THRESHOLD=... '1.0'（.env 未声明 ⇒ 用默认）；监听器注册在 fastapi_app/core/database.py:103-106（主库）、:148-150 / :159-160（只读副本）、:424-426；指标 slow_query_total（fastapi_app/core/metrics.py:153）。实证：logs/fastapi_20261001.log:15114「慢查询: 0.235s (阈值: 0.2s) 类型: oltp | SQL: SELECT * FROM product WHERE price > 0 ORDER BY id DESC LIMIT 20 | 参数:」、:42681「慢查询: 1.403s … INSERT INTO product … | 参数: params=batch=100,first=5(str,str,float,int,int)」。无慢请求/响应耗时记录：全仓 grep SLOW_REQUEST | slow_request | X-Process-Time | process_time 在 fastapi_app 下仅命中 fastapi_app/shared_models/outsource.py:156 Index('ix_oospf_process_time', …) ⇒ 既无耗时中间件也无耗时指标。
- 健康检查：fastapi_app/core/health.py:200-214 /metrics（生产 fail-closed 503/401，本部署已配 token）、:164-195 /api/health/db（有 Depends(get_current_user_id)，但返回 pg_settings（listen_addresses/max_connections/shared_buffers 等）、pg_stat_activity 状态计数与 db_error 原文 ⇒ 已认证用户即可读数据库内部参数，信息面偏宽，medium/low）、:218/226/259/277 live|ready|startup|arq（无鉴权，合理）；:277-334 /api/health/arq 定义三态契约 running / not_running / probe_unknown，注释指出 ARQ 是定时备份唯一调度者（scheduler_poller 每 5 分钟扫 backup_schedule），ARQ 静默停摆＝数据保护静默失效；prod_runner.py:663 用 /api/health 每 3s 做后端健康门、单次超时 5s（_HEALTH_PROBE_TIMEOUT=2s）。
- 生产实况（logs/prod_runner.json 于 2026-10-01 15:0x 读取）：pid 2032、started_at 2026-10-01T14:58:50、mode production、ready true、frontend_ok true、workers 8、api_port 5002、web_port 3000、backend pid 15888 status ready、arq external、frontend external、redis ok 6379、broker ok 6380。
- docs/performance-baseline.md 方法论可复现性中等：采集时间 2026-09-14，方式为只读探针 scripts/db_baseline_probe.py（218 行，asyncpg，REPEAT=20，凭据读 .env）⇒ 有脚本、有参数、可重跑；结论含库 43.4MB / 68 表、audit_log 45,241 行最大、order 3,722、PG 18.3、shared_buffers 3948MB、effective_cache_size 11844MB、max_connections 100、pg_stat_statements 未安装（数据库侧无语句级统计）；同机另有 erp_system_test 35.3MB（测试库）与 erp_system_drill 17.3MB（演练库）。缺口：未给采样时点的并发/负载条件，也未把慢查询阈值 0.2s 与基线口径对齐 ⇒ 跨轮次对比需人工校准。

## 6. 运维风险清单（单机生产+运维、无独立测试环境）

### 6.1 结论
- 本机同时是生产应用主机 + 数据库/Redis/nginx/ARQ 主机 + 运维主机 + 桌面运维壳所在机，且没有与生产隔离的测试/演练环境（只有同实例内的 erp_system_test 与 erp_system_drill 两个库）；一旦误操作（本地用户可写 logs/backups、桌面壳可一键杀进程/装服务、restart_backend.py 会把后端暴露到局域网）没有第二台机器兜底；同时三类静默失效（服务停摆、备份停摆、磁盘写满）都没有对外信号。

### 6.2 风险清单（严重度 / 证据 / 影响 / 建议与验证方式）
- R1 high 明文密钥落盘 + ACL 过宽：证据 _ops/credentials/_backup_encryption_password.txt:5、_metrics_bearer_token.txt:1、.env.bak-20260911 / .env.bak-20260927-085022、_ops/audit_scratch/_probe_tables.py:2；根与子目录 ACL Authenticated Users|Modify、BUILTIN\Users|ReadAndExecute 继承到 .env、config/jwt/、_ops/、backups/、logs/。影响：本地任一已认证账号（含两个启用的沙箱账号）可取得 DB/Redis/备份加密/监控 token 与 ES256 私钥，可伪造 JWT、解密备份、篡改日志。建议：删除 _ops/credentials/* 明文与 .env.bak（或迁移到受限路径 / DPAPI 凭据管理器）；用 icacls 对 .env、config\jwt、_ops、backups、logs 移除继承并仅授权 Administrators + SYSTEM（服务账户如需读 .env 再单独授予）；禁用或删除两个沙箱账号。验证：icacls 复查 ACE 仅剩 Administrators/SYSTEM/服务账户，Get-LocalGroupMember Administrators 无多余账号。
- R2 high 备份静默降级为不加密且无任何外发信号：证据 fastapi_app/api/v1/endpoints/backup/_deps.py:164-169（仅 warning）、fastapi_app/services/backup/crypto.py:68、fastapi_app/core/config.py:211-228（未显式声明只告警）、fastapi_app/services/backup/orchestration/policy_service.py:55 vs _constants.py:43（默认值相反）、fastapi_app/tasks/backup_tasks.py:648-649（不加密直接落明文 zip），历史实证 2026-09-27 及更早全量为明文 .zip。影响：以为有加密，实际落明文。建议：把降级改为硬失败（除非显式 BACKUP_ALLOW_PLAINTEXT=true）；统一两处默认值并以 config.py 单一口径为准；降级时同时写库告警记录、返回响应字段 encrypted=false、并入 /api/health 状态。验证：把 BACKUP_ENCRYPTION_PASSWORD 置空后加载 Settings / 调用备份入口应报错而非静默通过（在测试库执行）。
- R3 high 恢复流程不可验证：证据 scripts/restore_drill.py:35-39（glob 只匹配 erp_backup_*.zip）、backups/server/recovery_tests/ 仅 m5_drill_raw_20260823.json、logs/erp-arq.log 无 disaster_recovery_test_task 入队、recovery_test_service.py:45/53、scripts/database/restore_db.py:47-64/121。影响：备份是否可恢复没有真实证据；恢复演练本身有误伤生产库口令与误 DROP 的风险。建议：修正 newest_backup 以 glob erp_auto_daily_*.zip*（含 .enc）并走解密路径；为 disaster_recovery_test_task 建立 schedule（如每月）并接入告警；为演练库配置独立 BACKUP_TEST_DB_PASSWORD 与 BACKUP_TEST_PASSWORD；给 restore_db.py 加 --dry-run、artifact 校验与目标库白名单。验证：python scripts/restore_drill.py 在正确选定 .enc 产物后产出 recovery_tests/*.json；触发 perform_recovery_test() 返回 success 且报告含表数/行数比对。
- R4 high 备份/看门狗告警链完全静默：证据 .env BACKUP_ALERT_EMAIL_ENABLED=false、BACKUP_ALERT_WEBHOOK_ENABLED=false、BACKUP_ALERT_EMAIL_FROM/TO 空；alert_service.py:110-117/150-151；logs/watchdog.log 2026-09-30 11:46 连续 4 次 arq_worker=fail; backup_freshness=fail 仍「告警 0 项，通道 无」；scripts/ops/watchdog.py:309-312/332-338。影响：服务停摆、备份停摆、磁盘写满三类事故无人知晓（备份陈旧已实测超过 21h）。建议：启用至少一条通道（内网 Webhook 优先），把 watchdog 与 backup_alert 的失败阈值/冷却接同一通道，并按 scripts/ops/install_watchdog_task.ps1（/RU SYSTEM /RL HIGHEST，每 5 分钟）注册计划任务；把 watchdog 最近运行时间纳入 /api/health。验证：把 Webhook 指向本地 sink 触发一次 fail 场景（不改生产库）确认收到消息；Get-ScheduledTask erp-watchdog 状态为 Ready/Running。
- R5 medium-high Redis 口令可被任意本地用户读取：证据 Win32_Process 的 redis-server 命令行含 --requirepass <明文>（pid 5360/5372）、HKLM:\SYSTEM\CurrentControlSet\Services\erp-redis\Parameters 的 AppParameters 同明文且该键含 BUILTIN\Users|ReadKey、server_manager/redis_ops.py:170-172。影响：拿到 Redis 口令可读写会话/队列/限流/缓存（REDIS_DB=0 会话与业务共用），进而绕过限流、伪造缓存。建议：口令改由受 ACL 保护的配置文件提供，不用命令行参数；注册表服务键收紧（移除 Users 读权）；评估 broker 与业务 Redis 使用不同口令。验证：redis-server 进程命令行不含口令；Get-Acl 该键无 BUILTIN\Users；重启后功能正常（由运维在变更窗执行）。
- R6 medium 本地用户可写 logs/backups ⇒ 篡改留痕/污染备份：证据 根 ACL Authenticated Users|Modify 继承到 logs 与 backups/server，审计写库+日志文件（audit_middleware.py）、HTTP 访问日志为本地文件（nginx-windows.conf:41）。影响：事后取证可被改写，备份产物可被替换/删除。建议：日志与备份目录写权限仅限服务账户与 Administrators；考虑审计外发（syslog/中心库）。验证：icacls logs backups 复查；用非管理员测试账号写入应被拒。
- R7 high 纵向越权读（customer_sampling 9 个 GET）：证据 fastapi_app/api/v1/endpoints/customer_sampling.py:63/66/71/90/109/241/370/382/394/408/426（写了权限的端点 :123-124 / :148 等），并与 customer_sampling.py:4 注释矛盾。影响：低权限账号可读全部打样项目/零件/版本/变更日志/角色分配；注释与实现矛盾使评审易漏。建议：给 9 个 GET 加 Depends(require_permission('customer_sampling_manage')) 或引入只读权限点 customer_sampling_view，并同步修正文件头注释。验证：重跑 routes3.py + routes4.py 确认该模块 0 条无权限点；对低权限账号在测试库做只读调用应 403。
- R8 medium 匿名限流键可被 XFF 伪造：证据 fastapi_app/main.py:256-271（匿名走 get_remote_address）、fastapi_app/core/prod_runner.py:258-271 --forwarded-allow-ips=*、config/nginx-windows.conf:60/117 $proxy_add_x_forwarded_for。影响：可对 /login、/refresh 做分布式爆破绕过（30/60s、100/300s、100/minute）。建议：改为 --forwarded-allow-ips=127.0.0.1（仅信任本地 nginx）；nginx 用 proxy_set_header X-Forwarded-For $remote_addr; 覆盖而非追加；可加账号维度限流（username+IP）。验证：确认启动参数后，从局域网发带伪造 XFF 的登录请求，观察登录失败日志 IP 是否为真实客户端（只读观察，不做爆破）。
- R9 medium 部署脚本违反 0.0.0.0 红线：证据 scripts/restart_backend.py:64-69（--host 0.0.0.0 + --forwarded-allow-ips=*），对照 prod_runner.py:258-271（已回环）与 config/nginx-windows.conf:139-145（/metrics allow 127.0.0.1）。影响：按脚本手工重启即暴露后端并绕过 /metrics 限制。建议：改脚本为 127.0.0.1（或直接调用 prod_runner），并在 CI/预提交加 grep 门禁禁止非 dev 脚本出现 --host 0.0.0.0。验证：grep -rn "0\.0\.0\.0" scripts/ fastapi_app/ start.py 仅剩 dev_mode/vite/pgbouncer/otel 等已知条目。
- R10 medium 5 个 NSSM 服务以 LocalSystem 运行：证据 Win32_Service StartName=LocalSystem（erp-web / erp-prod / erp-arq / erp-redis / erp-redis-broker）、server_manager/service_ops.py:368-405 不设账户。影响：Web 进程被利用即等于系统最高权限；反向也放大 R1（服务可读所有密钥）。建议：为 erp-web / erp-prod / erp-arq 建专用低权账户（仅需 D:\erp_system 读 + logs 写 + 服务控制），Redis 单独账户；用 nssm set <svc> ObjectName <account> <pwd> 应用；确认 R1 的 ACL 收紧不阻断其运行。验证：Get-CimInstance Win32_Service 显示专用账户；重启后 logs/prod_runner.json ready=true。
- R11 medium 生产主机对外监听面过大：证据 0.0.0.0:5432（PG）、0.0.0.0:21（KMFtp）、0.0.0.0:7863（wb2api）、0.0.0.0:3389（RDP）、135/445/5357、192.168.0.95:139；D:\PostgreSQL\data\postgresql.conf:60 listen_addresses='*'，pg_hba 只允许 127.0.0.1/::1。影响：pg_hba 被放宽或第三方服务漏洞即成入口。建议：listen_addresses='localhost'；关闭未用的 FTP 与 wb2api（或绑回环）；为 5432/3389 加防火墙策略仅允许管理网段；确认 139/445 是否必需。验证：netstat 复查 5432 仅 127.0.0.1；Get-NetFirewallRule 检查入站规则。
- R12 medium 可观测性半盲：证据 logger.py:86-92（JSON 渲染判据与 config.py:48-71 不一致）、logger.py:66-77（UTC 文件名 + 本地午夜轮转，实测 fastapi_20260930 与 fastapi_20261001 两文件同时在写）、prod_runner.py:269 --no-access-log、全仓无请求耗时指标、logs/fastapi_20261001.log:10914/25586/40106（/metrics 只有 TestClient 命中）、health.py:164-195 /api/health/db 暴露 pg_settings/pg_stat_activity。建议：统一生产判定为 settings.is_production；文件 handler 改为按进程/本地日期分文件或集中输出（stdout 交收集器）；开启访问日志或加耗时中间件与 histogram；为 /metrics 配真实抓取或明确不启用并删死配置；/api/health/db 收敛为仅 superuser 且去掉 pg_settings 原文。验证：重启后日志文件数量受控；/metrics 出现真实 scrape 源 IP；指标含请求耗时。
- R13 low 死配置堆积：证据 config/prometheus.yml、config/alert_rules.yml、config/otel-collector.yaml、config/promtail.yml 指向 Docker 主机名而仓库无 Dockerfile/compose（scripts/ops/watchdog.py:4-14 自陈）；config/pgbouncer/pgbouncer.ini:15 listen_addr=0.0.0.0 而 pgbouncer 未运行。影响：运维误判「已有监控/连接池」，真实防护为 0。建议：补齐运行体并纳入部署文档，或删除/移至 docs 并在 AGENTS/README 标注「未部署」。验证：checked-in 的每个主机名配置都有对应运行体；Get-Service *pgbouncer* 与配置文件存在性一致。
- R14 low payload 缓存短路潜伏：证据 fastapi_app/core/deps.py:195-199（命中 request.state._jwt_payload 即跳过黑名单与启用校验），调用点仅 main.py:262、audit_middleware.py:126/178、deps.py:201（均在鉴权之后）。建议：让撤销/启用校验不可短路（例如限流键改用独立解码函数），或在 state 上区分「已校验」标记；加单元测试断言命中缓存时仍调用 is_token_revoked。验证：代码评审确认写入者唯一，或测试通过。
- R15 low 审计 client_ip 口径：证据 audit_middleware.py:135-138/203-205（取 XFF 最后一段）与 :136 注释相反、与限流键（第一段）不一致。建议：统一为「nginx 覆盖式 XFF 的第一段 + request.client.host 兜底」，并在注释写明信任边界。验证：构造 XFF 场景后核对 audit_log 的 ip_address 为真实客户端。
- R16 low 加密开关默认值不一致：证据 policy_service.py:55（默认 false）vs _constants.py:43（默认 true）。建议：单一来源（读 Settings），删除两处各自 os.environ.get 默认值。验证：grep -rn BACKUP_ENCRYPTION_ENABLED fastapi_app/ 仅剩 config 层与显式注入点。
- R17 low 备份产物卫生与观测残缺：证据 backups/server 内 2026-09-27 及更早明文 erp_auto_daily_*.zip 仍在 30 天保留期内；backups/server/metrics/backup_metrics_20261001.json 增量条目 backup_size_bytes:0 / filename:null；backups/server/cleanup_reports/ 最新 2026-08-20。建议：在验证新链路后清理或重加密历史明文；增量指标补 filename/size；清理任务纳入看门狗。验证：目录内不再有未加密 erp_auto_daily_*.zip；次日 metrics JSON 增量条目有 filename 与 size。
- R18 medium/low /api/health/db 信息面过宽：见 5.2。建议改为仅 superuser 或返回布尔健康位，去掉 pg_settings 原文与 db_error 细节（错误细节写日志、请求方只拿 request_id）。验证：普通已认证账号调用返回精简结构。

## 7. 计数与可复现命令（供复核）
- 权限覆盖：python docs/audit-round2/scripts/routes3.py 与 scripts/routes4.py（归档副本，原始路径 %TEMP%\erp_audit_v2\）→ 382 非测试路由 / 52 无权限点 / 11 无认证（**2026-10-01 复算均一致，见 §1.3「复算与口径标注」**；复算脚本 python docs/audit-round2/scripts/normalize_deps.py：先得 12 条无 get_current_user_id，再排除 health.py:82 的 `_get_optional_user` 后 = 11）。
- 服务与账户：Get-CimInstance Win32_Service | Where-Object {$_.Name -like 'erp-*' -or $_.Name -like 'postgresql*'} | Select-Object Name,State,StartName,StartMode
- 监听面：netstat -ano | Select-String LISTENING；Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine（注意输出含口令）
- 密钥扫描：Get-ChildItem -Recurse -File D:\erp_system\fastapi_app, D:\erp_system\config, D:\erp_system\scripts | Select-String -SimpleMatch '<任一密钥字面量>'
- 备份产物：Get-ChildItem D:\erp_system\backups\server -File | Group-Object {$_.BaseName -replace '\d{8}_\d{6}.*',''} | Select-Object Name,Count；Get-ChildItem D:\erp_system\backups\server\recovery_tests
- 调度入队：Select-String -Path D:\erp_system\logs\erp-arq.log -Pattern '调度入队 schedule_id'
- 环境漂移：python D:\erp_system\scripts\ops\check_env_drift.py --verbose（只读，退出码 0/1/2）

## 8. 边界与未覆盖
- 未做任何动态/攻击性验证：JWT 伪造、越权调用、备份解密、恢复演练均只做静态与产物层面的推断，未在生产发起请求（V1/R7 的 403 验证建议在测试库与测试账号上进行）。
- 未评估前端侧 XSS/令牌存储（属 frontend-analyst t2 范围）；未做依赖 CVE 扫描（属 quality 范围）；未做跨开源 ERP 的结构对比（属 architect-synth t7）。
- 本报告未落盘（按任务约束直接写在 output 文本）；如需归档请由 captain 决定写入位置，我不创建文件。
