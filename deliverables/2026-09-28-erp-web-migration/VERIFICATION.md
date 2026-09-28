# erp-web 迁移验证清单

> 日期:2026-09-28 · 重构提交范围 `1e937df7..HEAD`
> 设计:`docs/superpowers/specs/2026-09-28-erp-web-single-responsibility-design.md`

## 一、迁移执行(管理员 PowerShell,一次维护窗口)

```powershell
cd D:\erp_system
.\scripts\migrate_erp_web.ps1 -DryRun    # 先预览命令序列
.\scripts\migrate_erp_web.ps1           # 真实执行
```

脚本内部顺序:注册 erp-web(幂等)→ 停 erp-prod(Job Object 杀旧树)→
起 erp-web → 验证 :3000 Server:nginx → 起 erp-prod → 验证 /api/health →
runtime_mode_probe 终态判定。

**回滚**(完整步骤已写在脚本头注释,关键三步):

```powershell
nssm stop erp-web
nssm set erp-web Start SERVICE_DISABLED   # 防开机自启与旧 prod_runner 双 nginx
git revert <重构系列提交> && nssm restart erp-prod
```

## 二、迁移后验证(四条硬判据,缺一不可)

```bash
curl -s --noproxy '*' http://127.0.0.1:3000/ | grep -c "@vite/client"        # 期望 0
curl -s --noproxy '*' http://127.0.0.1:3000/ | grep -c "/src/main.ts"       # 期望 0
curl -sI --noproxy '*' http://127.0.0.1:3000/ | grep -i '^server:'          # 期望 nginx
curl -sI --noproxy '*' -H "Accept-Encoding: gzip" \
  'http://127.0.0.1:3000/api/v1/products/list?page=1&per_page=50' | grep -i content-encoding  # gzip
```

后端:`curl -s --noproxy '*' http://127.0.0.1:5002/api/health` → 200。
终态:`python scripts/diag/runtime_mode_probe.py` → `frontend.is_production=true`。
另验证 `logs/prod_runner.json`:`frontend_type=="erp-web"`、`services.frontend.status=="external"`、`frontend_ok==true`。

## 三、GUI 手动验证(server_manager)

1. 「安装服务」可重复点击,日志出现 erp-web 注册行;
2. 五服务卡片:后端/前端/ARQ/Redis 各徽章——前端徽章在 erp-web RUNNING 且探针通过时为绿色「前端 运行中」;
3. 生产→开发→生产切换各一轮:dev 模式 vite 能抢到 :3000(GUI 的受管 PID 排除已含 erp-web);
4. 「停止」按钮:三个服务(erp-prod/erp-arq/erp-web)依次确认 STOPPED。

## 四、验证记录(本机 2026-09-28 已完成项)

- [x] 全部新增/适配测试通过(log_rotation 5、prod_runner_slim 6、backend_restart、qa_regression 30、arq cron 4、migrate dryrun 2、server_manager 静态断言 5)
- [x] `nginx -t` 语法 OK(worker_processes 2)
- [x] `prod_runner --check`:Redis OK / dist OK / erp-web 提示 / worker=4
- [x] GUI 模块 headless 导入 OK(`_SVC_WEB='erp-web'` 就位)
- [ ] 迁移脚本真实执行(需管理员,待维护窗口)
- [ ] 四条硬判据(迁移后)
- [ ] GUI 实机点检(迁移后)
- [ ] runtime_mode_probe 终态(迁移后)

## 五、后续任务(独立于本次)

- **备份可观测性**(spec 明确列为独立高优任务):ARQ 心跳 + backups/ 产物时间戳纳入 /api/health;回写 backup_schedule.last_status。
- nginx 日志轮转 cron 已挂 ARQ(04:30/100MB),无需再配置。

## 六、注意(与既有记忆的衔接)

- 前端构建前仍需先探测 :3000 的服务模式(dev server vs erp-web)。
- 迁移完成后 :3000 恒由 erp-web 托管;dev 模式经 GUI 切换时端口互斥已处理。
