# 上线前审核 — (A) 安全性 + (B) 后端正确性 报告

- 审核人：software-engineer（寇豆码）
- 审核日期：2026-09-17
- 代码基线：工作区 = HEAD `a5e7b82`（两域关键文件 `git status` 均干净，缺陷属已提交代码）
- 范围：只读审计，未修改任何源码/配置，未重启/停止任何服务
- 证据目录：`deliverables/audit-2026-09-17/`

---

## 一、(A) 安全性

### 发现清单

#### A-M1 [medium] `/metrics` 应用层无鉴权 + 后端 0.0.0.0 直连暴露
**结论**：`/metrics` 在生产对局域网任意主机开放（Prometheus 文本指标），且 uvicorn 绑定 `0.0.0.0` 使直连 5002 端口可绕过 nginx ACL。

**证据**
- `fastapi_app/core/health.py:172-182`
  ```python
  @app.get("/metrics", tags=["监控"])
  async def metrics(request: Request):
      if _settings.is_production:
          auth = request.headers.get('authorization', '')
          metrics_token = os.getenv('METRICS_BEARER_TOKEN', '')
          if metrics_token and not auth.startswith(f'Bearer {metrics_token}'):
              return JSONResponse(status_code=401, content={'detail': '未授权访问'})
      return Response(content=get_metrics(), media_type=get_content_type())
  ```
  校验条件是 `if metrics_token and ...`——`METRICS_BEARER_TOKEN` 为空时**短路放行**。
- `METRICS_BEARER_TOKEN` 未配置：`.env` 无该项；NSSM `_services.json` 中 `erp-prod` 的 `AppEnvironmentExtra = APP_ENV=production FASTAPI_DEBUG=false PYTHONPATH=... PYTHONUTF8=1 PYTHONUNBUFFERED=1 UVICORN_WORKERS=8`（无 token）。
- `fastapi_app/core/prod_runner.py:220` `"--host", "0.0.0.0"`（`:225` `--forwarded-allow-ips=*`）。
- `config/nginx.conf:152-162` 仅 `allow 10/8 172.16/12 192.168/16 127.0.0.1; deny all;`——真实用户网段即 192.168/16，故内网放行。
- **实测**：`GET http://127.0.0.1:5002/metrics`（直连 uvicorn，无 Authorization 头）→ **HTTP 200**，返回 `# HELP python_gc_objects_collected_total ...`。

**触发条件/最小复现**：局域网内任意主机 `curl http://<server>:5002/metrics`（或经 nginx `http://<server>/metrics`）→ 无凭据获得指标。

**影响**：内部端点路径、请求计数、耗时分布泄漏；直连 5002 同时绕过 nginx 的 TLS/ACL/限流。非机密数据，定 medium。

**修改建议**：① 设置 `METRICS_BEARER_TOKEN`，并把逻辑改为 fail-closed（token 为空即拒绝）；② 生产将 uvicorn 绑定 `127.0.0.1`，统一由 nginx 入口；③ 或防火墙限制 5002。

---

#### A-M2 [medium] 密码策略过弱且与重置脚本不一致
**结论**：正常创建/改密只要求 6 位、无复杂度要求；而管理员重置脚本要求 8 位+字母+数字，同一系统两套策略。

**证据**
- `utils/password_validator.py`：`MIN_LENGTH = 6`、`MAX_LENGTH = 128`、`REQUIRE_UPPERCASE/REQUIRE_LOWERCASE/REQUIRE_DIGIT/REQUIRE_SPECIAL` 全 `False`、`WEAK_PASSWORDS = {"123456","password","admin","Password1!","Admin123!"}`。
- `scripts/reset_admin_password.py` `_validate_password_strength`：要求 `len>=8` 且含字母+数字。

**触发条件/最小复现**：`POST /api/v1/users/create`（`api/v1/endpoints/user.py:86`，`require_superuser`）`{"username":"t","password":"abcdef"}` → 通过（仅 6 位字母）。

**影响**：弱口令易被爆破/撞库，与 A-M3 叠加放大。

**修改建议**：统一为 `len>=8` + 至少两类字符；`reset_admin_password` 与 `PasswordValidator` 复用同一实现。

---

#### A-M3 [medium] 登录限流阈值近乎形同虚设
**结论**：登录端点确有自定义限流（慢速 API 全局限流反而关闭），但阈值极高，暴力破解窗口大。

**证据**
- `api/v1/endpoints/auth.py:26-29`：`LOGIN_BURST_LIMIT = 100`（/分钟）、`LOGIN_ATTEMPT_LIMIT = 300`（/5 分钟）。
- 自定义实现 `_check_login_rate_limit`（`auth.py:159-190`，Redis pipeline + 内存降级），`auth.py:229` 显式调用 → **实际生效**。
- `core/limiter.py:26`：`Limiter(..., enabled=False, ...)` → 全局 slowapi 限流关闭；`auth.py` 上的 slowapi 装饰器为冗余。

**触发条件**：对同一账号 5 分钟内可尝试 300 次口令。

**影响**：结合 A-M2 弱口令，可高效爆破。

**修改建议**：登录失败阈值下调（如 5 次/账号/5 分钟 + 指数退避）；至少对写端点启用全局限流。

---

#### A-M4 [medium] 依赖 CVE（运行时可达）
**结论**：`pillow` 存在 13 个 CVE 且 `requirements` 未固定上限；`pydantic-settings` 存在版本漂移导致"已声明修复"未生效。

**证据**
- `requirements/base.txt`：`pillow>=10.4.0`（无上限）；实际安装 `12.2.0`。`pip-audit` 报 13 个 CVE（fix 12.3.0）：解压炸弹保护绕过（PYSEC-2026-2253 等 PCF/BDF/GD/Font/EPS）、`ImageCms` 堆破坏、坐标 OOB 写、TGA RLE OOB 读、Jpeg2K 内存放大、PDF 解析 OOM 等。
  - 逃逸评估：ERP 图片入口 `services/customer_sampling/upload.py`、`services/storage_service.py` 均用 `Image.open(BytesIO(content))`（内存流，非文件路径）→ **McIdas mmap(路径) 路径不可达**；但 `Image.MAX_IMAGE_PIXELS = 200_000_000`（远超 PIL 默认 ~89M）抬高炸弹阈值 → 解压炸弹 DoS 仍有隐患。
- `requirements/base.txt`：`pydantic-settings==2.14.2`（注释称修复 GHSA-4xgf-cpjx-pc3j），实际安装 `2.14.0`（**版本漂移**）。`pip-audit` 报 `CVE-2026-58203`（NestedSecretsSettingsSource 符号链接越界读，fix 2.14.2）。
  - 逃逸评估：`core/config.py` 用 `env_file` + JWT，**未用 `secrets_dir`** → 非直接可达。
- 运行解释器 = `C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.EXE`（NSSM `erp-prod`/`erp-arq` 确认），故 `pip-audit` 结果即生产运行时版本。

**修改建议**：`pillow>=12.3.0` 并固定；重装对齐 `pydantic-settings==2.14.2`；CI 增加 `pip-audit` 门禁；`Image.MAX_IMAGE_PIXELS` 回调至默认量级。

---

#### A-L1 [mild / 已知有意] 未认证写入端点 `/api/v1/monitoring/vitals`
- `api/v1/router.py:270-274` 监控路由**未加全局认证依赖**（注释：POST /vitals 由 `sendBeacon` 上报，无法带 auth header）；`api/v1/endpoints/monitoring.py:204` `receive_vitals` 无鉴权写入 `WebVital`。
- 已有防御：`_MAX_BATCH=50`、`_RETENTION_DAYS=30`、清理节流（`_CLEANUP_INTERVAL_SECONDS=3600`）、pydantic 校验。残留风险：表增长/轻微写入放大。判定：**已知/有意**，风险低。

#### A-L2 [mild / 已知有意] token 黑名单 fail-open（默认）
- `core/deps.py:215` `is_token_revoked(jti, fail_closed=fail_closed)`；`get_current_user_id` 用 `fail_closed=False` → Redis 故障且本地缓存未命中时**放行**；仅 `get_current_user_id_strict`/`get_current_user_strict` fail-closed。`deps.py:237-244` 已文档化。判定：**已知/有意**。

---

### (A) 已排除项（核验后判定无问题）
- **SQL 注入**：ORM/参数绑定为主；`services/numbering_sequence.py` 用常量 SQL + 绑定参数（`INSERT...ON CONFLICT DO UPDATE...RETURNING`）；未发现字符串拼接 SQL。
- **文件上传**：`api/v1/endpoints/auth.py:422` 需登录；扩展名白名单 `{png,jpg,jpeg,gif,webp}` + 魔数校验 `_validate_image_content`（`:412-419`）+ 5MB 上限（`:439-441` 只读 `MAX+1` 字节防内存耗尽）→ 良好。
- **认证**：JWT 算法白名单 `{HS256,RS256,ES256}`；Cookie `httponly=True`、`samesite`、`secure` 正确（`auth.py:207`）。
- **授权（横向/纵向）**：路由级 `dependencies=[Depends(get_current_user_id)]` 覆盖 34/36 路由（仅 `auth`、`monitoring` 有意公开）；端点级 354/372 带显式鉴权依赖，其余 18 个为 auth/monitoring 公开端点或 `customer_sampling`/`aux` 只读端点（仍受路由级登录保护）。用户管理端点全 `require_superuser()`（`user.py`），备份端点全经 `require_backup_permission`→`require_permission`（`backup/_deps.py:102-107`），`require_permission` 失败即 403（`deps.py:290-294`）→ **未发现越权缺口**。
- **`_jwt_payload` L1 早退是否可绕过**：`deps.py:196-200` 在 payload 已存在时直接返回 user_id、跳过黑名单/启用校验；但 `_jwt_payload` 仅由 `deps.py:127/148`（`_authenticate_user_id` 内部）设置，**无任何中间件预先设置**（已全仓 grep 确认）→ 同请求首次调用仍执行完整校验，第二次才走 L1 早退 → **不构成绕过**。
- **CSRF / 安全头**：`core/middleware.py:131-194` 双提交 CSRF（cookie `fastapi_csrf_token` + 头 `X-CSRF-Token`，`secrets.compare_digest`），Bearer 请求走 Origin 校验；CSP（生产 per-request nonce）、HSTS、`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、`Permissions-Policy` 齐全 → 良好。
- **生产暴露面**：`APP_ENV=production` → `/api/docs`、`/api/openapi.json` **实测 404**（已关闭）。
- **密钥**：Redis 口令经 NSSM 命令行注入（与 live 配置一致）；`config/redis-broker.conf` 被 `.gitignore` 忽略、git HEAD 无明文；旧弱口令 `110110` 已轮换 → 已知/有意。

### (A) 无法验证项
- 局域网防火墙是否放行 5002（不触碰生产前提下无法探测外部可达性）→ A-M1 的**外部**可达性依赖此项，但**应用层无鉴权 + 绑定 0.0.0.0 已确证**。
- 移动端 Origin 实际值（Bearer 路径的 `_is_allowed_origin` 依赖 `CORS_ORIGINS`；若移动端 origin 不在其中会被 403）——需移动端实际配置确认。

### (A) 上线就绪判定：**READY_WITH_CONDITIONS**
无 blocker。条件：修复 A-M1（metrics 鉴权 + 绑定回环/防火墙）与 A-M4（pillow / pydantic-settings 升级）；建议一并修复 A-M2、A-M3。

---

## 二、(B) 后端正确性

### 发现清单

#### B-B1 [blocker] 综合导入端点 100% 失效 —— `POST /api/v1/batch/import-comprehensive`
**结论**：端点因无参构造必填模型而恒返回失败，功能完全不可用。

**证据**（HEAD `a5e7b82`，`git status` 干净）
- `services/batch_import_service.py:723`
  ```python
  719        async with _save_uploaded_file(file) as temp_path:
  720            success, sheets, err = await read_excel_sheets_async(temp_path)
  721            if not success:
  722                return ComprehensiveImportResult(success=False, message=f'Excel读取失败: {err}')
  723        results = ComprehensiveImportResult()          # ← 无参构造，且缩进 8（在 async with 块之外）
  ```
- `schemas/batch.py:16-18`
  ```python
  class ComprehensiveImportResult(BaseModel):
      """综合批量导入结果"""
      success: bool = Field(..., description="是否成功")   # ← 必填、无默认
  ```

**触发条件/最小复现**：调用端点（需 `batch_import` 权限）→ 行 723 抛 pydantic `ValidationError`（`ValueError` 子类）→ 被行 741 `except (OSError, ValueError)` 吞掉 → 恒返回 `success=False, message='操作失败，请稍后重试'`。
**实测**（`deliverables/audit-2026-09-17/_repro_comprehensive_import.py`，可复现）：
```
[A] unmodified code -> success=False message='操作失败，请稍后重试'
    （栈：1 validation error for ComprehensiveImportResult  success  Field required）
```

**影响**：该端点彻底不可用。**重要**：前端未调用它（`frontend-vite/src` 仅用 `/batch/import-products|stockins|stockouts`），故当前用户无感；但作为已注册 API，任何集成/未来 UI 使用都会静默失败。

**修改建议**：`results = ComprehensiveImportResult(success=True)`，或（更佳）把 723-736 整体移入 `async with` 块内。

---

#### B-B2 [severe，被 B-B1 掩盖] 临时文件在读取前已被删除
**结论**：即使修复 B-B1，逐 Sheet 解析仍会因临时文件提前删除而全部失败。

**证据**
- `services/batch_import_service.py:730` `success, data_list, err = await parse_excel_file_async(temp_path, sheet_name)` —— 位于行 719 `async with` **之外**。
- `services/batch_import_parser.py:98-124`
  ```python
  @asynccontextmanager
  async def _save_uploaded_file(file: UploadFile):
      ...
      yield temp_path
      finally:
          if temp_path and os.path.exists(temp_path):
              with suppress(OSError):
                  os.unlink(temp_path)
  ```
  块退出即删文件 → 行 730 读到的是已删除路径。

**触发条件/最小复现**：打补丁容忍模型后运行同脚本场景 B。
**实测**：
```
[B] per-sheet read attempts (path, file_exists_at_read_time):
      exists=False  C:\Users\ADMINI~1\AppData\Local\Temp\tmpzlz3szg6.xlsx
[B] errors=["Sheet 产品管理 读取失败: no workbook found at path '...tmpzlz3szg6.xlsx'"]
[B] verdict: DEFECT #2 CONFIRMED (file already deleted)
```

**影响**：每个 Sheet 读取失败，导入即使修 B-B1 仍全失败。

**修改建议**：将 723-736 整体移入同一 `async with _save_uploaded_file(file) as temp_path:` 块内（保留块内 `return` 语义）。

---

#### B-M1 [medium] 分页 `per_page` 两处缺上限
**结论**：两个日志查询端点未限制 `per_page`，且下游无夹紧，可一次性拉取全量。

**证据**
- `api/v1/endpoints/purchase_center/misc_routes.py:24`
  `... per_page: int=Query(20, ge=1), ...`（**无 `le=`**）
- `api/v1/endpoints/purchase_center/misc_routes.py:56`（同上）
- 下游：`services/purchase_history_service.py:34` `query = query.offset((page - 1) * per_page).limit(per_page)`
- 同项目**其余 39 处**分页端点均带 `le=100/200/500`（如 `order.py:45` `le=500`、`user.py:64` `le=100`）。

**触发条件/最小复现**：`GET /api/v1/purchase-center/modification-logs?page=1&per_page=999999`（需 `product_manage`）→ `LIMIT 999999`。

**影响**：大结果集一次性物化 → 内存/响应耗时放大；并发可致 OOM。

**修改建议**：两处补 `le=200`（与同模块其余端点一致），并在 service 层夹紧 `min(per_page, MAX_PAGE_SIZE)`。

---

#### B-L1 [mild / 已知有意] 编号生成两套实现时区不一致
- `core/number_generator.py:68/107/152` 用 `datetime.now()`（本地 naive）；`services/numbering.py:60/93/142` 用 `datetime.now(UTC)`。
- 分别作用于不同模型/表，DB 唯一约束兜底；模块 docstring 明确标注"已知/有意"（事务边界与时区不同，未合并）。判定：**已知/有意**，重号风险低。

#### B-L2 [mild] naive/aware 时间混用
- `services/batch_import_service.py:264/349/430/501/606` `order_date/stockout_date/stockin_date = datetime.now()`（本地 naive）与 `services/order_batch_create.py:145/183` `datetime.now(UTC).replace(tzinfo=None)`（naive **UTC**）语义不同、列类型均 naive。若同表混存，跨时区/夏令时下排序与"当日"统计会偏差。
- 影响：低（内网单时区），属潜在一致性隐患。建议统一为 `datetime.now(UTC).replace(tzinfo=None)`。

---

### (B) 已排除项（核验后判定无问题）
- **宽泛 `except Exception`**：`services/` 共 **113 处**，裸 `pass` **0 处**；绝大多数带 `# defensive` 注释，属备份/事件发布/图片处理/仪表盘卡片等**有意容错**，失败有日志、不吞关键错误。
- **事务边界**：`core/database.py:203-240` `get_async_db` 自动 commit/rollback；批量导入用 `db.begin_nested()` 逐 Sheet savepoint 隔离；`services/order_batch_create.py:318` 逐客户 savepoint + `:341-345` `SQLAlchemyError` 整体回滚并终止 → 健全。
- **库存并发**：`order_batch_create.py:64-71` `_lock_products` 用 `with_for_update()` 悲观锁；`services/staging/stockout.py` 用 `get_product_for_update` + 可用量校验 → 防竞态。
- **除零**：`purchase_order_crud.py:387` `len(items)` 前有 `if not items: continue`；`outsource/_common.py:85` 有 `if total else 0` → 安全。
- **N+1**：批量导入/批量创建均预加载 `product_map` / 一次性 `IN (…)` 查询 → 已规避。
- **FIFO 缓存并发**：`services/fifo_allocation.py` 用 `session.info['fifo_dirty']` 标记替代全局标志，失效失败靠 TTL 兜底 → 已修。
- **编号原子性**：`services/numbering_sequence.py` 常量 SQL `INSERT...ON CONFLICT DO UPDATE...RETURNING` 独立短事务原子递增 → 防重号。
- **连接池**：`core/database.py:31-53` 按 `UVICORN_WORKERS=8`：`available=100-20=80`、`pool_size=max(5,80//16)=5`、`max_overflow=max(3,80//24)=3` → 8×(5+3)=64 < `PG max_connections(100)`，留 20 给 ARQ/迁移；`pool_pre_ping=True`、`pool_use_lifo=True` → 合理。

### (B) 无法验证项
- 生产库实际数据规模（影响 B-M1 的 OOM 现实概率）。
- 未跑全量 pytest（仅按约束单文件/脚本复现），故上述"已排除"基于静态审阅 + 定点复现。

### (B) 上线就绪判定：**NOT_READY**
B-B1 blocker（综合导入端点 100% 失效）+ B-B2 severe（同源）。虽前端未调用，但属已注册 API 功能缺陷，上线前应修复（改动小、风险低）。修复后可降为 **READY_WITH_CONDITIONS**（仅剩 B-M1）。

---

## 三、证据文件索引
| 文件 | 内容 |
|---|---|
| `_repro_comprehensive_import.py` | 综合导入双缺陷复现脚本（可重跑） |
| `_pipaudit.json` / `_pipaudit.err` | 生产解释器依赖 CVE 全量结果 |
| `_recon_b1.py`/`.txt`、`_recon_b2.py`/`.txt` | 宽泛 except / 时间调用 / 除法式 量化扫描 |
| `_services.json` | NSSM 4 服务注册配置（运行解释器、环境变量、Redis 口令来源） |
| `_procs.json` | 运行中进程列表 |
