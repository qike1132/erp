# 安全审计报告属实性验证 — security-audit-skill run-1

**日期**：2026-11-02
**工作流**：工作流 1（全面代码审查 · 变体：审计报告事实核查）
**参与成员**：Cody（代码审查师）、Tessa（测试专家）、Rex（SRE 工程师）、Zhen（工程督导 · 编排与交叉验证）

**验证对象**：`C:\Users\Administrator\security-audit-skill\erp_system\run-1\`（REPORT.md / FINDINGS-DETAIL.md / NEEDS-VALIDATION.md / findings.json / coverage-ledger.json）
**验证基准**：`D:\erp_system` 工作区源码（审计报告声称的 source ref `c3703af9b71720a0f0d0514cd2ba04321967bf0e` 对应内容）
**验证方式**：三方独立只读源码核查（Read/Grep/Glob），全程零执行、零数据库连接、零文件修改（生产主机约束）

---

## 📌 TL;DR（执行摘要）

- **总体结论**：报告的**核心技术事实基本属实**——NV-1 源码影响链每一环均经三方独立核实成立，hardening 备忘 11 条中 8 条完全属实，正面模式与 CI/供应链声称全部属实，无虚构漏洞或夸大防御。
- **但报告存在 6 类问题**：① RJ-1 的 rejected 判定被独立复核**部分推翻**（zipfile 中间解压缓冲存在 ~2GiB 内存尖峰路径，"峰值=闸门预算"结论不成立）；② NV-1 的"登出 token 复活"表述对纯 JSON 路径**夸大**（黑名单存活，复活集实为改密/禁用/删号前凭据）；③ hardening#1 的"状态/改密未发跨 worker 事件"与源码**相反**；④ 覆盖账本统计**误报**（candidate 实为 5 非报告写的 0）；⑤ "三 agent 独立核实"的过程叙事**零产物支撑**（agents/ 目录全空、中心文件 json_backup.py 在 ledger 中 0 命中）；⑥ "zip 版断言可参照改写"的测试引用**定性错误**（全仓不存在恢复→旧 token 401 的集成测试）。
- **严重度分布**：🔴 报告结论需修正项 2（RJ-1 改判、NV-1 复活范围）/ 🟠 报告事实错误 2（hardening#1、覆盖统计）/ 🟡 表述精度问题 5 / 🟢 属实且无需修正 30+
- **阻塞/非阻塞**：均非阻塞。NV-1 修复方向经核实技术合理，应进入修复队列；RJ-1 建议改判重新验证而非直接关闭。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟡 有条件通过（事实链属实，结论表述需修正） |
| 阻塞项数量 | 0 |
| 报告事实声称属实率 | 核心事实链 ~85%（NV-1 13 项中 10 项完全属实；hardening 11 条中 8 条完全属实；正面模式 5/5 全部属实） |
| 报告需修正项 | 6 类（RJ-1 判定、NV-1 复活范围、hardening#1、覆盖统计、过程叙事、测试引用） |
| 新发现（报告未提） | 8 项（含 1 个新攻击面缺口、1 个功能缺陷、2 个测试陷阱） |
| 建议下一步 | ① 修 NV-1（P0）；② RJ-1 改判重验（P0）；③ 修正报告自身 6 处错误（P1） |

---

## 一、NV-1（needs_validation）验证结论：**核心事实链成立，两处表述需修正**

### 1.1 逐项核实矩阵（Cody 主核，主理人交叉验证）

| # | 报告声称 | 判定 | 实际证据 |
|---|---------|------|---------|
| 1 | 三条 JSON 分支 restore.py:356/:464/:694 调 restore_legacy_json | ✅ | :356 `POST /import` JSON 分支（db_transaction 内）；:464 `/restore-by-name` JSON 分支；:694 异步分支（实为 3 代码路径/4 端点入口——`/async-import` 与 `/async-restore-by-name` 共用 :694） |
| 2 | restore_legacy_json（:589-625）全文无 revoke；_invalidate_caches_after_restore（:422）只清业务缓存 | ✅ | 函数实际 :589-652；json_backup.py 整文件 grep `revoke_all_sessions_after_restore`/`token_version`/`_PERMISSION_CACHE`/`_USER_ACTIVE`/`_LOCAL_REVOKED` 均 0 命中；:422-432 只调 invalidate_related_caches(CacheDomain.ALL) + invalidate_purchase_caches()，不触碰三个进程内认证缓存（core/cache.py:165-189 佐证） |
| 3 | user 表整表 DELETE+回填（:401-419），token_version/status/password_hash 随行回滚 | ✅ | :401-419 逐表 DELETE FROM；_restore_tables_from_json（:505-586）整表 upsert；导出侧 execute_legacy_backup_to_bytes（:296-354）遍历 Base.metadata.sorted_tables 默认全表含 user |
| 4 | deps.py:226-248 `_verify_user_active` tv 严格相等判定放行 | ✅ | 实际 :227-247，核心行 :247 `int(expected_token_version or 0) == int(current_version or 0)` —— 相等放行 |
| 5 | zip 主路径 restore.py:268 有 revoke（对照） | ✅ | :262-268 outcome 无 error 时 `await revoke_all_sessions_after_restore()`；docstring :149-161 写明回滚理由 |
| 6 | `_restore_components_only`（:305-353）无 revoke 属"合理豁免" | ⚠️ | 豁免论证有缺口：该路径经 restore_non_dependent_components（:65-66）可回放 redis/dump.rdb（cache_restore.py:76-93 整体替换 RDB）→ **jti 黑名单回滚而 tv 不动 → 备份后登出的 token 复活**（登出只写黑名单不 bump tv）。豁免只考虑了 tv 通道，未考虑黑名单通道 |
| 7 | grep 全仓 revoke_all_sessions_after_restore 唯一生产调用点 restore.py:268 | ✅ | 全部命中：restore.py:148（def）、:268（唯一生产调用）、tests 2 处；orchestrator/json_backup/adapters 均无 |
| 8 | restore_legacy_json 调用点 = 三条端点分支 | ⚠️ | 实际 5 处：3 条端点分支 + json_backup.py:371（ZIP 容器 JsonRestoreStrategy 路径，被 :268 revoke 覆盖，无害）+ recovery_test_service.py:649-651（写**测试库**的恢复演练，无生产影响）。生产库口径下"三条"成立，但调用点清单不完备 |
| 9 | `_SUPERUSER_ONLY`（_deps.py:125-135）覆盖三条分支 | ✅ | frozenset 含 import/restore/async 变体全部 4 权限码；:151-152 → require_superuser() |
| 10 | 登出黑名单走 Redis（auth.py:301-330），可被 RDB 回滚 | ✅ | 实际 :296-331 三处 token 均 revoke_token(jti, exp)；blacklist.py:69-91 以 `token_blacklist` 为键前缀、jti 为后缀写入撤销键；cache_restore.py:76-93 RDB 回放逻辑确实存在。**但见修正 A：该通道不适用于纯 JSON 恢复** |
| 11 | format==json 现役导出（export.py:110-124） | ✅ | `format == 'json'` → execute_legacy_backup_to_bytes，产出 .json/.json.enc |
| 12 | 旧 token 复活逻辑链 | ✅ 基本成立 + 两处修正 | 完整链路核实：PyJWT 验签+exp+type → is_token_revoked → tv 相等判定，未过期旧 token 在回滚后确实重新通过。**修正 A**（复活范围）：纯 JSON 恢复不触碰 Redis → 黑名单存活 → **普通登出的 token 不会复活**；真正复活集 = 改密/禁用/删号前签发的 token（bump_token_version 撤销）、被禁/被删账号、旧 refresh token（auth.py:478 同为相等判定可续签）。REPORT.md 概括句对纯 JSON 路径夸大；FINDINGS-DETAIL :24 的"组件包或含 Redis 的恢复"限定正确。**修正 B**（时延）：_USER_ACTIVE_CACHE TTL 10s（deps.py:207），JSON 路径不清该缓存 → 近期活跃用户的复活最多延迟 10s |
| 13 | 修复建议（三条分支提交后调 revoke，须在提交点之后） | ✅ | restore.py:163-169 独立 engine 事务属实；"提交点之后"告诫成立；幂等表述准确 |

### 1.2 NV-1 总体判定

**漏洞本体成立，应进入修复队列。** 三方独立核实（工程督导、Cody、Tessa）对源码事实链结论完全一致：三条 JSON 分支缺失 revoke、user 表整表回滚、tv 严格相等放行、zip 路径有 revoke 而 JSON 无、JSON 格式现役、超管触发边界。行号偏差（1-27 行漂移）不影响语义。

**需修正的表述**：报告把复活范围写宽了——"登出 token 重新变为有效"仅在恢复包含 Redis RDB 时成立（zip 组件包路径），纯 JSON 路径的复活集是 bump_token_version 撤销的凭据（改密/禁用/删号前签发）+ 旧 refresh token + 被禁/被删账号。

---

## 二、RJ-1（rejected）验证结论：**反驳论证不可靠，建议改判重验**

| # | 报告声称 | 判定 | 实际证据 |
|---|---------|------|---------|
| 14 | assert_zip_budget（xlsx_budget.py:64-98）按声明 file_size 判 64MiB/成员、128MiB/总量、100:1 压缩比 | ✅ | :43/:46/:50/:79-91 全部按声明值判定，数值准确 |
| 15 | xlsx_cell_images.py:88,123-127 前置闸门+逐成员累加 | ✅ | :88 assert_zip_budget 前置；:123-127 按声明量累加 |
| 16 | CPython ZipExtFile 以声明 file_size 初始化 `_left`，读循环递减、耗尽置 `_eof`，解压输出被硬截断 | ✅ | 本机 CPython 3.13.13 Lib/zipfile/__init__.py：`self._left = zipinfo.file_size`（:903）、`data = data[:self._left]`（:1117）、`_left -= len(data)`（:1118）、`_left <= 0 → _eof`（:1119-1120）、Bad CRC 在 `_eof` 时抛 BadZipFile（:1041-1049）。机制描述与实际源码一致 |
| 17 | **结论"可达内存峰值 = 闸门设计允许的 64MiB/128MiB 预算，非绕过"** | ❌ **不成立** | **决定性漏洞**：`_read1` 的中间解压缓冲 `self._decompressor.decompress(data, n)`（:1106-1107）的输出上限是 max_length 参数——全量读 `zf.read()` → `read(-1)` → `_read1(MAX_N)`（:1016-1018），MAX_N=(1<<31)-1≈2GiB，**与声明 file_size 无关**；截断发生在完整解压**之后**（:1117）。压缩比闸门按声明值计算，**低报 file_size 只会让比值更小**——闸门对此失明。构造路径：声明 file_size=1MiB（过成员/总量闸门）+ compress_size=5MiB（比值 0.2 过 100:1 闸门）+ 物理嵌入 5MiB 高压缩比 deflate 流 → `zf.read()` 瞬时分配最高 ~2GiB 后才截断为 1MiB。可达 sink：openpyxl 全量读成员、xlsx_cell_images._read_member:152。原候选的"无上限 10GB"也不对（MAX_N 封顶+逐成员串行），真实量级 = **每次 read 调用 ≤2GiB 的瞬时内存尖峰**（10MiB 上传上限下 ~200:1 放大）。静态结论，是否 OOM 取决于 worker 内存配置 |

### RJ-1 总体判定

**rejected 判定应重新评估。** 报告引用的 zipfile 机制全部属实、"返回数据有界"成立；但支撑 rejected 的核心结论（峰值=闸门预算）被 zipfile 源码的 MAX_N 中间缓冲机制证伪。建议改判为 needs_validation 口径（"有界 ~2GiB/次的内存尖峰 DoS"候选），重新走验证。另注：BadZipFile 抛出的前提是声明 CRC 与截断前缀不符——声明 CRC 亦攻击者可控，可设为截断前缀的 CRC32 静默通过（不影响有界性结论，但报告的"随后 Bad CRC 走 400"表述不严密）。

---

## 三、Hardening 备忘 11 条验证结论

| # | 条目 | 判定 | 关键证据与修正 |
|---|------|------|---------------|
| 1 | 状态/改密未发跨 worker 失效事件，最坏 10s TTL 窗口 | ⚠️ **两处与源码不符** | ① TTL 张冠李戴：deps.py:79 是 `_PERMISSION_CACHE`（**5s**）；10s 的是 `_USER_ACTIVE_CACHE`（deps.py:207）。② 事件声称与源码**相反**：`_schedule_permission_cache_invalidation`（user.py:63-85）不只用于权限变更——`/users/edit`（含**改密**，user.py:156）、`/users/toggle`（**禁用**，:185）、`/users/delete`（:222）、`/users/permission`（:279）全调用；且 auth.py 无自助改密端点，改密/禁用的唯一路径都发事件；订阅者 handler 同时 pop 两个缓存（deps.py:103-111），main.py:262-268 每 worker 注册。**真实残余风险**：仅事件发布/Redis 广播失败时退化为 TTL 有界窗口（权限 5s / 状态+tv 10s）——报告把降级路径当成了常态路径 |
| 2 | 导入任务 job_id 无归属前缀 + DLQ 重试丢 exp-u 前缀 | ✅ 全部精确命中 | tasks.py:280 `exp-u{uid}-`；:154/:312-315 归属校验仅对 exp-u 前缀生效；导入 enqueue 不传 _job_id（:195/:234）；dead_letter.py:160（实际路径 api/v1/endpoints/dead_letter.py）enqueue 未传 _job_id ✅。**附加发现**：tests/test_dead_letter_api.py:58 把"不传 _job_id"钉死为期望行为——修复时必须同步改此测试 |
| 3 | GET /backup/progress/{task_id} 仅 backup_read | ✅ | restore.py:479-489 → _deps.py:98 `get_restore_progress: backup_read` → require_any_permission('backup_read','backup_manage')；不在 _SUPERUSER_ONLY。进度含逐表行数（json_backup.py:584） |
| 4 | dashboard /activities 无工厂隔离 | ✅ | dashboard.py:89-95 仅 get_current_user_id；对照 stats:76/todos:111 传 _dashboard_factory_scope；文件头 :7-14 AUD-04 注释确认既定口径 |
| 5 | 匿名 POST /vitals 无表级总量上限 | ✅ | monitoring.py:215 限流 30/min/IP；_persist（:134-169）无表行数上限；:152 `path[:500]` 逐行落库 |
| 6 | scan_secrets 通配 allowlist 整文件跳过 | ✅ | allowlist.txt:23-24 `*.example`/`*.template`；scan_secrets.py:204-207 fnmatchcase → :248 命中即跳过路径层+内容层；本地 pre-commit:78/:154 同逻辑；行内豁免无棘轮（对照非通配条目有 test_allowlist_effectiveness.py 锁定） |
| 7 | staging session_id 无归属绑定 | ⚠️ 表述过宽 | 5/6 个 staging 面已正确绑定：staging_order/stockin/stockout 全端点 `u{uid}:{session_id}` 作用域；purchase_plan/production_plan 用服务端派生 session_id。**唯一缺口**：POST /api/v1/ocr-import/upload（ocr_import.py:52 客户端传 session_id → :99 透传 → services/ocr/_import.py:135 写裸值）。**报告未提的更糟形态**：可定向注入（传 `u<受害者uid>:x` 落入受害者命名空间，受害者确认即成真出货单）+ **孤儿行功能缺陷**（OCR 写入的裸 session_id 行对所有 scoped 读端点不可见，无法列出/确认/清除） |
| 8 | normalize_storage_key 不拦 `..`、死挂载、ext 可含 `/` | ✅ 附精度问题 | storage_service.py:492-505 无 `..`/`/` 拦截；main.py:520-522 挂载、全仓无写入方（死挂载）；:180-182 `_generate_key` ext 未消毒。⚠️ "当前调用方均服务端生成键"不完全准确——auth.py:558 将客户端 file.filename 传入 save_upload，实际防线是 :536-538 ALLOWED_EXTENSIONS 白名单（png/jpg/jpeg/gif/webp）拦截含 `/` 的 ext。结论成立但防线位置表述有偏差，建议把收口放进 `_generate_key` 自身 |
| 9 | ws.py:107 旧票据兼容分支 30s 跳过撤销检查 | ✅ | ws.py:107 `auth={}` → _token_auth_valid :229-230 `if not payload: return True`；窗口=_WS_TICKET_TTL_SECONDS=30（:44）；注释 :106 自认滚动发布兼容 |
| 10 | pgbouncer_gen_userlist.py argv 口令等 | ✅ | scripts/pgbouncer_gen_userlist.py:27-29 口令走 argv；:40-41 admin/monitor 缺省复用 erp_app 口令；:48-49 明文写 userlist.txt、:56 仅打印警告无 ACL 强制 |
| 11 | branch protection 为部署事实 | ✅ 归类正确 | .github/ 下无 settings.yml 等声明文件，源码侧无法证明 required checks 启用与否 |

---

## 四、正面模式与态势摘要验证结论：**全部属实，无夸大**

| 声称 | 判定 | 证据 |
|------|------|------|
| CI `--require-hashes` | ✅ | ci-cd.yml:119（test job）、:378（lint job）。脚注：refresh-requirements-lock.yml:56 用 secrets.GITHUB_TOKEN（自动发放非存储型，permissions 显式限定），不构成否定 |
| action 全 SHA 钉定 | ✅ | 两个 workflow 全部 14 处 `uses:` 均为 40 位 SHA，无 @vX 标签 |
| 无 secrets 引用 | ✅ | ci-cd.yml 零 `secrets.` 引用 |
| `pull_request` 而非 `pull_request_target` | ✅ | ci-cd.yml:3-7 push + pull_request；refresh workflow 仅 schedule+workflow_dispatch |
| restore_guard fail-closed | ✅ | marker 写失败抛错（:104-134）+ 回读校验；锁 Redis 不可用 503（restore.py:64-81）；预备份失败默认 428（:259-279），三条防线均拒绝而非放行 |
| 工厂 scope 空集 403 | ✅ | production_scope.py:45 返回空集语义；实际 403 收口在 deps.py:486-503 两个 resolver（"空集绝不允许退化"）；test_production_scope.py:93-94 锁定 |
| 登录 dummy Argon2id 防时序 | ✅ | auth_service.py:19 _DUMMY_HASH；:47-50/:51-54 用户不存在/被禁两分支均跑等价验证再 401 |
| JWT 双通道+tv+jti fail-closed | ✅ | token_version 相等判定 deps.py:242-247；blacklist.py:179-218 fail_closed=True 时 Redis 故障+本地未命中 → 401 拒绝 |
| CSRF 三分支收口 | ✅ | middleware.py:313-351（Bearer→Origin / Cookie→CSRF token / 双带→按 cookie 收口） |
| 上传面三闸门 | ✅ | import_guard.py + validators.py:60-219 魔数 + xlsx_budget.py:43,46,64 |
| secrets 扫描 CI 与钩子镜像 | ✅ | ci-cd.yml:394-395 + .githooks/pre-commit 两层扫描，allowlist 同源，行内豁免语义一致（双侧注释互指） |

---

## 五、测试与过程声称验证结论

| 声称 | 判定 | 说明 |
|------|------|------|
| test_restore_revokes_sessions.py 是"zip 版断言"可参照改写 JSON 版 | ⚠️ 定性错误 | 文件存在（fastapi_app/tests/ 下），但实际是 revoke 助手函数的**两个纯单元测试**（monkeypatch 假 engine 查 SQL 文本 + 失败不抛），**不含任何"恢复→旧 token 401"断言——zip 版也没有**。全仓不存在恢复后会话失效的集成测试。"可参照改写"没有可参照物 |
| test_backup_json_restore_legacy.py 自称"还原主链路" | ✅ | docstring 首行吻合；实测 4 个 FakeSession 单元测试，未测会话失效/真实往返/端点接线——报告对其引用准确 |
| "三个独立 agent（hunter h05 → verifier v2 → Phase 5 v3）逐行核实，v2 曾判 confirmed(Medium,High)" | ❌ **零产物支撑** | run-1/agents/ 下仅 h01-h13 共 13 个 hunter 目录，artifacts/ 与 scratch/ **全部为空**（26 个空目录 0 文件）；无任何 v1/v2/v3 verifier 产物；coverage-ledger.json 的 agent_id 仅 h01-h13，每单元 local_checks 只有一行通用字符串且 artifact:null；**NV-1 的中心传播文件 json_backup.py 在 ledger 中 0 次命中**（h05 名下 4 单元的 reviewed_paths 不含它）。过程叙事只能当作报告自述——不推翻 NV-1 源码事实（已独立核实为真），但削弱审计过程可信度 |
| 覆盖账本"45 单元两波全部 covered、candidate=0" | ⚠️ 统计误报 | 单元总数 45 ✅、deferred/blocked/out_of_scope=0 ✅；但实际 **40 covered + 5 candidate**（ledger 行 560/611/663/798/892，如 :560 携带 RJ-1 指纹）。按技能语义 candidate 仍属完成覆盖（validator 判 PASS），但总览表把 candidate 记为 0 与账本数据矛盾 |
| local 验证计划（建用户→JSON 备份→bump tv→/import→旧 token 调端点） | ⚠️ 方向可行，工程量被低估 | 计划中正确的细节：confirm=true 强制（restore.py:302-303）、测试库护栏兼容、JSON 分支只要求 tables 键、bump_token_version 存在。**报告未提的阻碍**：fastapi_app/tests/conftest.py 的 autouse override_deps 把全部鉴权依赖 stub 掉——标准 harness 下"旧 token 401"观察**根本不可能发生**；同时 patch Redis→None、engine→None，而 /import 需要 Redis 还原锁（fail-closed 503）与真实 DB；_pre_restore_info_or_fail 走 pg_dump 链路。需新建绕过 override 的真实鉴权+DB+Redis harness，绝非"参照现有断言改写"级别 |
| 回归建议（变异检查：注释掉 revoke → 用例变红） | ⚠️ 原则正确，落点有误 | 变异检查手法正确；但前提（zip 版断言）不存在。**轻量替代（报告漏掉）**：monkeypatch revoke_all_sessions_after_restore 为 AsyncMock 的 spy 断言——打 /import JSON 分支（restore 服务 mock），断言 spy 在事务提交后被 await。完全兼容现有 mock_db/client 基建，注释掉修复即红，直接钉住"助手已存在、只是没接线"的真实缺陷 |

---

## 六、Owner 部署核实清单静态抽查

可静态核实的三项全部属实：① nginx-windows.conf:156 include uploads-signing.conf（硬依赖 fail-closed 特性描述一致；实际文件被 .gitignore 排除，存在性⛔需部署核实）；② start.py:66 uvicorn 默认绑 127.0.0.1（API_HOST 可覆盖；实际监听⛔需 netstat）；③ config/nginx.conf 文件头自declared DEPRECATED、生效配置为 nginx-windows.conf（仓库证据链完整）。其余 5 项（branch protection、X-Forwarded-Proto、.env 值、NTFS ACL、Redis 实际绑定）正确归为部署事实——报告该项处理无误。

---

## ✅ 行动清单（按优先级排序）

| # | 行动 | 负责角色 | 紧急度 | 预期完成 |
|---|------|---------|--------|---------|
| 1 | 修 NV-1：三条 JSON 分支（restore.py:356/:464/:694）`db_transaction` 提交后调用 `revoke_all_sessions_after_restore()`；回归测试采用 **spy 断言**（AsyncMock + 断言提交后被 await，兼容现有 harness）而非报告建议的"改写 zip 版断言" | 后端 owner | P0 | 本周 |
| 2 | RJ-1 改判重验：以"每次 read ≤~2GiB 瞬时内存尖峰"候选重新走验证（zipfile `_read1` MAX_N 中间缓冲），复核 xlsx_cell_images._read_member:152 与 openpyxl sink；若坐实评估 worker 内存配置下的 OOM 面 | 安全审计 owner | P0 | 下次审计 run |
| 3 | 补 `_restore_components_only` 黑名单通道评估：组件包含 redis/dump.rdb 时（cache_restore.py:76-93 回放）登出 token 复活——补 revoke 或把豁免条件明确为"不含 Redis 组件"并文档化 | 后端 owner | P1 | 两周内 |
| 4 | 修正 run-1 报告自身 6 处错误：candidate 统计（5 非 0）、NV-1 复活范围（纯 JSON 路径登出 token 不复活）、hardening#1（事件已覆盖改密/禁用 + TTL 数值更正）、"zip 版断言"引用、三 agent 过程叙事（标注无产物支撑）、RJ-1 判定 | 审计报告 owner | P1 | 下次修订 |
| 5 | Hardening#2 修复时同步改 test_dead_letter_api.py:58（该测试把 DLQ 不传 _job_id 钉死为期望行为，不同步改即红） | 后端 owner | P2 | 随 #2 hardening 修复 |
| 6 | OCR staging 排查：裸 session_id 孤儿行（无法列出/确认/清除的功能缺陷）+ 可定向注入（`u<受害者uid>:x` 命名空间） | 后端 owner | P2 | 排期 |

---

## ⚠️ 待完善 / 已知局限

- 全程静态只读验证，未执行任何目标代码/测试/数据库连接（Windows 生产主机无沙箱约束，与原审计同一限制）——NV-1 的"旧 token 复活"最终实证仍需执行 local 验证计划（需先新建真实鉴权 harness）。
- RJ-1 的 ~2GiB 内存尖峰结论为 zipfile 源码推导，未实测内存峰值；是否实际 OOM 取决于 uvicorn worker 内存配置与并发数。
- 运行时部署事实（nginx 实际 conf、Redis 绑定、NTFS ACL、branch protection、.env 实际值）未观察——与原报告的 owner 核实清单口径一致。
- 验证基于当前工作区内容（工作区存在并发会话改动，与原审计的 source ref 可能有漂移，但对验证的核心文件无影响——三方核实均以现行源码命中报告声称的行号/语义）。
- 本报告未对原审计 13 个 hunter 的其余覆盖单元做全量复核（抽查了 ledger 统计与 NV-1 相关路径）。

---

## 📚 数据来源 & 成员产出索引

- **Cody（代码审查师）原始产出**：NV-1 13 项逐行核实（含复活逻辑链两处修正、_restore_components_only 黑名单通道缺口新发现）+ RJ-1 4 项核实（zipfile MAX_N 中间缓冲证伪 rejected 结论）+ 修复建议技术合理性评估。
- **Tessa（测试专家）原始产出**：测试声称 3 项核实（"zip 版断言"定性错误、三 agent 过程零产物支撑、ledger 中 json_backup.py 0 命中）+ hardening#1/#2/#3/#7 核实（#1 两处与源码相反、#7 表述过宽+OCR 孤儿行新发现）+ 验证计划可行性静态评估（spy 断言轻量替代方案）。
- **Rex（SRE 工程师）原始产出**：CI 四子项 + 正面模式 5 条 + 态势摘要五项核实（全部属实）+ hardening#4/#5/#6/#8/#9/#10/#11 核实 + 覆盖账本统计（candidate 5 非误报为 0）+ owner 清单静态抽查 + CI 工具链哈希防线缺口等 3 项新发现。
- **Zhen（工程督导）交叉验证**：restore_legacy_json 全部 5 个调用点完备性核查（发现报告清单不完备但无第 4 条生产库路径）、deps.py tv 判定与双缓存 TTL 独立核实、hardening#1 行号错位独立确认。
- 验证对象：`C:\Users\Administrator\security-audit-skill\erp_system\run-1\`（REPORT.md、FINDINGS-DETAIL.md、NEEDS-VALIDATION.md、findings.json、coverage-ledger.json、agents/ 目录）。
- 验证基准：`D:\erp_system` 现行源码（fastapi_app/、.github/、scripts/、config/、tests 树）。

---

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。
