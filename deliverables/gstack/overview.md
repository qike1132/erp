# 交付概览：ERP Debug vs Production 性能深度排查

**日期**：2026-09-17 ｜ **结论**：🟡 条件 Go（5 项 P0）

**协作模式**：软件工坊 GStack 多成员协作（产品官 + 排障手 + 质量门神）

---

## 做了什么

对 `D:\erp_system` 做了一次**只读取证**的性能排查，回答"为什么 debug 模式比 production 模式快"。

排查方式：三名专家并行取证 + 主理人独立复核（curl / netstat / 日志挖掘 / 构建产物实测），全程未修改任何服务状态、未启动任何服务。

## 最终交付物

| 文件 | 内容 |
|------|------|
| **`perf-debugmode-vs-production-2026-09-17.md`** | ⭐ 主报告（541 行）— 汇总裁决结论、18 项问题清单、P0/P1/P2 路线图、排查命令手册 |
| **`perf-selfcheck.ps1`** | ⭐ **可执行自检脚本**（已实跑验证）：6 组 15 项，一键判定"当前是开发栈还是生产栈" |
| **`baseline-before-2026-09-17-0908.log`** | **优化前基线快照**（脚本实跑结果：FAIL 7 / WARN 5 → 判定【开发栈】） |
| `_raw-investigator-backend.md` | 后端 + 基础设施原始报告（665 行，12 组证据链） |
| `_raw-product-review.md` | 现象剖析 + 风险评审原始报告（1008 行，12 条机制） |
| `_raw-qa-frontend.md` | 前端构建 + 网络层原始报告（1203 行） |

### 用法

```powershell
# 项目根目录执行（严格只读，不改任何服务状态）
powershell -ExecutionPolicy Bypass -File .\deliverables\gstack\perf-selfcheck.ps1
```

**修复前跑一次存档 → 修完再跑一次对比**，这就是最省事的"优化前/后"证据链。

## 核心结论（一句话）

**用户报告的"production 比 debug 慢"属实，但归因方向需反转 —— 所谓"production 环境"当前根本没在运行。**

实测：3000 端口是 **Vite dev server**，5002 端口是 **`--reload` 开发模式 uvicorn**，正式生产栈（`erp-prod` 服务 + Nginx + dist 产物 + 8 worker）**处于 Stopped 状态，nginx 进程数 = 0**。用户比较的是两套完全不同的运行时。

## 关键决策 / 裁定

1. **裁定成员结论冲突**：产品官主张"production = vite preview + Nginx 反代"，排障手主张"3000 是 dev server"。以三重实证（`/@vite/client` 注入、`/src/main.ts` 引用、171 条 `hmr update`）**裁定为 dev server**；同时采纳产品官揭示的"三条启动路径全部由 Vite 托管、无一走 Nginx"——这比原判更有价值。
2. **纠正配置权威性认知**：确认 `.env`（而非 `.env.production`）才是权威配置；确认 `FLASK_ENV` / `NGINX_PROXY` / `DB_POOL_SIZE` / `log_config.json` 均为**无效字段**（初期曾被误导）。
3. **修正 M11 根因**：初稿将重启风暴归因于"代理劫持探针"，但代码 `_OPENER_DIRECT` 已修此隐患。真正的问题在**前端探针"假成功"**（详见下）。
4. **排除 7 个排查方向**：日志写盘、N+1、密码哈希、DEBUG 日志、Source Map、Sentry、Flask 慢哈希 —— 均经实证不成立。
5. **实测排除"Windows 保留端口段"嫌疑**：`[emerg] bind() to 0.0.0.0:3000 failed (10013)` 曾被怀疑是 Hyper-V/WSL 保留段所致（那样杀进程也无效、必须换端口）。实测 `netsh int ipv4 show excludedportrange protocol=tcp` 仅排除 **5357** 与 **50000-50059**，3000 **不在其中**，且 3000 当前 `LISTENING`（PID 10640）。**结论：属瞬时地址冲突，替换占用进程即可，无需改端口或重启 `winnat`。**

## 🔴 最重要的发现："假成功"缺陷（五层防护全断）

`_FrontendNginx` 的 Nginx 检测在代码结构上**不可能发现失败**：

| 层 | 位置 | 缺陷 |
|---|---|---|
| 1 | `prod_runner.py:408-409` | 探针**只校验状态码不校验响应体** → Vite 回 index.html 也算通过 |
| 2 | `prod_runner.py:400-406` | 探测循环后**无条件** `self.status = "running"`，10 次全失败也宣布"已启动" |
| 3 | `prod_runner.py:503-508` | 状态落盘直接采用被无条件置位的 `running` → 文件谎报 |
| 4 | `prod_runner.py:503-508` | `pid` 仅从 `self.vite.proc.pid` 取，nginx 分支永远为 `None` → 前端托管层不可观测 |
| 5 | `logs/nginx-error.log:19` | **真相就在日志里，但没人读**：`[emerg] bind() to 0.0.0.0:3000 failed (10013)` |

> 第 5 层还有代码级佐证：`prod_runner.py:394-399` 的 `Popen(...)` **丢弃 handle** 且 `stderr=DEVNULL`，进程既无法 `wait()`，输出也被丢进黑洞 —— 只留下一个没人读的日志文件。

**后果**：Nginx 从未运行这件事**永远无法被发现**（实测 nginx 进程 = 0，而文件声称 running）。这不是运维疏忽，而是代码层面的结构性缺陷。

## 🔬 已在线复现的硬证据

```bash
curl -s -H "Accept-Encoding: gzip" -D - -o /dev/null http://127.0.0.1:5002/metrics
# → HTTP/1.1 200, content-length: 18745, 无 content-encoding 头

# 实测：18745 字节 → gzip 后应为 2554 字节 = 浪费 86.4%
```

后端因 `APP_ENV=production` 让出 gzip，而 Nginx 进程 = 0 → **所有 `/api/` JSON 响应都在多传 3-8 倍数据**。这不是推断，是已复现的事实。

## 最高优先级行动（5 项 P0）

1. **先测基线**（首屏 LCP + 后端 TTFB），否则无法证明优化有效
2. **修复"假成功"五层缺陷**（探针校验响应体 + 启动失败告警 + pid 可取 + 日志可读），并定位后端重启真实触发源
3. 修正托管拓扑，让 Nginx 真正服务 `dist` 产物（消除静默降级）
4. 修复 gzip 归属逻辑（消除压缩真空，已实证 86.4% 浪费）
5. 移除 PWA 对 API 的 Service Worker 拦截（数据陈旧风险）

## 附带发现

- `.env` / `.env.development` 含**明文凭据**（DB_PASSWORD / SECRET_KEY / REDIS_PASSWORD）
- `frontend-vite/vite.config.js` **覆盖** `vite.config.ts`（改 TS 配置静默失效）
- 三处 dev 默认入口硬编码 `npm run dev`，无一键生产入口
- ARQ worker 处于 `external` / Stopped 状态，异步任务可能无声堆积
- ⚠️ nginx 访问日志出现来源标注为 `https://frp-fun.com:30001/` 的请求 → **疑似 frp 内网穿透导致服务暴露公网**，需人工确认是否有意为之

## 待跟进

- 上述安全线索与明文凭据需人工核实 git 历史与 `.gitignore` 覆盖情况；如需正式结论应单独发起安全审计
- ARQ 状态需确认是否影响备份/报表导出等功能
- **正式 A/B 对照未完成**：因全程只读，未启动正式生产栈，所有"生产更慢"的量化仍属临时候选值
