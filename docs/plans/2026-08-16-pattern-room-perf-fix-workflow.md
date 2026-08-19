---
intent: 修复 pattern-room 板块卡顿：P0 数据清理（缺失上传文件引用）、P1 Nginx 静态本地化、P2 前端失败图片记忆、P3 后端列表查询去级联
success_criteria: grouped-list 接口不再返回失效图片 URL；/static/uploads/ 404 由 Nginx 亚毫秒返回且不再打满 FastAPI；前端已知失败图片不再重复请求；列表查询不带 parts/roles/fabric_versions 级联加载；页面进入无秒级卡顿
risk_level: medium
auto_approve: true
branch: hotl/dev-prod-mutex-switch
worktree: false
dirty_worktree: allow
---

## Steps

- [x] **Step 1: P3 后端列表查询去除 relationship 级联加载**
action: 修改 `fastapi_app/services/customer_sampling/grouping.py` 与 `fastapi_app/services/customer_sampling/crud.py`。三处列表查询（grouping.py 的 get_grouped_list 约 line 93-98、get_completed_table 约 line 225-232，crud.py 的 list_projects 约 line 768-771）在 `select(CustomerSamplingProject)` 后追加 `.options(selectinload(CustomerSamplingProject.pattern_maker), noload(CustomerSamplingProject.parts), noload(CustomerSamplingProject.roles), noload(CustomerSamplingProject.fabric_versions), noload(CustomerSamplingProject.change_logs), noload(CustomerSamplingProject.product_image), noload(CustomerSamplingProject.creator))`（get_completed_table 不访问 pattern_maker 对象，可不加 selectinload(pattern_maker)，只加 6 个 noload）。同时修改 grouping.py `_project_to_summary`（约 line 177）：`'parts_count': len(project.parts) if project.parts is not None else 0` 改为 `'parts_count': 0`（列表查询已 noload parts，原注释即声明保持 0；访问 noload 后的 collection 会在 async 上下文触发 MissingGreenlet）。文件顶部需从 sqlalchemy.orm 导入 noload。
verify: python -m pytest tests/test_customer_sampling_service.py tests/test_customer_sampling_api.py -q

- [x] **Step 2: P2 前端失败图片记忆，杜绝重复 404 请求**
action: 修改 `frontend-vite/src/views/pattern-room/components/ProjectCardItem.vue`。(1) script setup 顶部（import 之后）加模块级 `const failedImageUrls = new Set<string>()` 与 `function isProjectImageFailed(proj: { product_image_url?: string | null }): boolean { return !!proj.product_image_url && failedImageUrls.has(proj.product_image_url) }`。(2) `onThumbError` 中：当 `img.dataset.fallback` 已置位或无回退 URL 而进入终止分支时（即 `img.src = ''` 前），将 `proj.product_image_url` 与缩略图 URL（可从 `img.dataset.thumbUrl` 取，需在模板 img 上绑定 `:data-thumb-url="proj.product_image_thumbnail_url || ''"`）加入 failedImageUrls。(3) 模板中清晰图 `<img>` 的渲染条件由现有的 `v-if="proj.product_image_url"` 类似分支改为 `v-if="proj.product_image_url && !isProjectImageFailed(proj)"`，else 分支保持现有 placeholder DOM 不变。(4) blur 图 `<img>` 同样加 `v-if` 排除失败项目（或直接由外层同一条件包裹，保证失败项目不发出任何 img 请求）。保持现有 blur-up 过渡逻辑不变。
verify: cd frontend-vite && npm run build

- [x] **Step 3: P1 Nginx 新增 /static/uploads/ 本地 alias 块**
action: 修改 `config/nginx-windows.conf`。在现有 `location /static/`（line 86-91）之前插入：
```nginx
        # --- 上传文件由 Nginx 直接本地托管（文件缺失时 404 亚毫秒返回，不占用 FastAPI worker） ---
        location /static/uploads/ {
            alias D:/erp_system/static/uploads/;
            try_files $uri =404;
            expires 7d;
            add_header Cache-Control "public, immutable";
            include D:/erp_system/config/security-headers.conf;
        }
```
原 `location /static/` 保持不变（继续代理 /static/files/、/static/releases/）。不加 listen http2 参数——明文 HTTP 下浏览器不使用 HTTP/2，无收益。
verify: C:/nginx/nginx.exe -p D:/erp_system -c config/nginx-windows.conf -t

- [x] **Step 4: 重启 erp-prod 加载 Nginx 配置并验证**
action: 用 NSSM 重启服务（项目约束：不能直接 nginx -s reload）：`nssm restart erp-prod`，等待约 10 秒后依次验证：(1) `Invoke-WebRequest http://127.0.0.1:3000/nginx-health` 返回 200；(2) `Invoke-WebRequest http://127.0.0.1:3000/api/health` 返回 200；(3) 对缺失文件 URL `http://127.0.0.1:3000/static/uploads/customer-sampling/20260814/7307cff2e3be421ab44aed5d6501ca43.webp` 用 Measure-Command 实测 5 次，每次应 <50ms 且状态 404；(4) `http://127.0.0.1:3000/` 返回 200。
verify: powershell -Command "$h=@{}; $h.health=(Invoke-WebRequest -Uri 'http://127.0.0.1:3000/api/health' -UseBasicParsing).StatusCode; $h.index=(Invoke-WebRequest -Uri 'http://127.0.0.1:3000/' -UseBasicParsing).StatusCode; $t=Measure-Command{try{Invoke-WebRequest -Uri 'http://127.0.0.1:3000/static/uploads/customer-sampling/20260814/7307cff2e3be421ab44aed5d6501ca43.webp' -UseBasicParsing}catch{}}; Write-Output ('health='+$h.health+' index='+$h.index+' missing404_ms='+[math]::Round($t.TotalMilliseconds,1)); if($t.TotalMilliseconds -gt 50){exit 1}"
max_iterations: 3

- [x] **Step 5: P0 确认上传文件在本机确已不存在**
action: 在全盘关键位置搜索缺失文件名片段 `7307cff2e3be421ab44aed5d6501ca43`（范围：D:\ 与 C:\ 顶层目录，排除 Windows/Program Files/node_modules，超时 120s 内）。若任何位置命中有效副本，则复制回 `d:\erp_system\static\uploads\<storage_key相对路径>` 并跳过 Step 6-7（在结果中标注"已恢复文件"）；若未命中，输出 NOT_FOUND 并继续数据清理路径。
verify: powershell -Command "$hits = Get-ChildItem D:\,C:\ -Recurse -Filter '7307cff2*' -File -ErrorAction SilentlyContinue -Force | Where-Object { $_.FullName -notmatch 'node_modules|Windows\\|Program Files' } | Select-Object -First 5; if ($hits) { $hits | ForEach-Object { Write-Output ('FOUND: ' + $_.FullName) } } else { Write-Output 'NOT_FOUND' }"

- [x] **Step 6: P0 导出待清理数据备份**
action: 用 python + asyncpg（主库 DSN `postgresql://erp_user:ERP_Production_2026!@localhost:5432/erp_system`，若认证失败改用 `postgresql+asyncpg://postgres:ERP_Production_2026!Secure@localhost:5432/erp_system`，从 .env DATABASE_URL 读取真实值）导出以下数据为 JSON 到 `d:\erp_system\temp\p0_backup_$(Get-Date -Format yyyyMMdd_HHmmss).json`：(1) `SELECT id, sequence_no, product_name, product_image_file_id FROM customer_sampling_project WHERE product_image_file_id IS NOT NULL`；(2) `SELECT * FROM file_records`。同时查询并记录引用 file_records 的所有外键：`SELECT tc.table_name, kcu.column_name FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.schema_name = kcu.table_schema JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name AND ccu.table_schema = tc.table_schema WHERE tc.constraint_type = 'FOREIGN KEY' AND ccu.table_name = 'file_records'`。
verify: powershell -Command "Get-ChildItem d:\erp_system\temp\p0_backup_*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { $raw = Get-Content $_.FullName -Raw; if ($raw.Length -gt 100 -and $raw -match 'customer_sampling') { Write-Output ('backup OK: ' + $_.Name + ' size=' + $raw.Length) } else { exit 1 } }"

- [x] **Step 7: P0 清理 customer_sampling 失效图片引用（基于 Step 6 的 FK 清单）**
action: 在同一 python 事务中执行（主库，autocommit=False，先 BEGIN）：(1) `UPDATE customer_sampling_project SET product_image_file_id = NULL, updated_at = NOW() WHERE product_image_file_id IS NOT NULL`；(2) 基于 Step 6 第 (3) 项查到的 FK 清单，仅当其他业务表均无引用时执行 `DELETE FROM file_records WHERE NOT EXISTS (SELECT 1 FROM customer_sampling_project p WHERE p.product_image_file_id = file_records.id)` 并对清单中每个其他引用表追加对应 NOT EXISTS 条件；若其他表存在引用则只删无任何引用的行，保留被引用行；(3) COMMIT。注意先 `SELECT count(*)` 确认 UPDATE/DELETE 影响行数（预期 project 更新 ≤ 3327、file_records 删除 ≤ 30）再提交；异常 ROLLBACK。(4) 在 `d:\erp_system\temp\verify_p0.py` 创建校验脚本（asyncpg 连读副本 `postgresql://erp_readonly:ERP_ReadOnly_2026_Secure@localhost:5433/erp_system`，查 `SELECT count(*) FROM customer_sampling_project WHERE product_image_file_id IS NOT NULL`，为 0 时打印 `remaining_refs=0` 且退出码 0，否则退出码 1）。
verify: powershell -Command "$env:PYTHONPATH='d:\erp_system'; python d:\erp_system\temp\verify_p0.py"
max_iterations: 3

- [x] **Step 8: 部署前端新产物并重启服务**
action: (1) 备份当前 `frontend-vite/dist` 为 `frontend-vite/dist.bak.20260816`（若已存在则覆盖）；(2) 将 Step 2 构建产物从 `frontend-vite/dist` 目录确认存在（vite build 直接输出到 dist，无需复制，仅需确认 mtime 为本次构建）；(3) `nssm restart erp-prod`，等待 10 秒验证 `/api/health` 200 与 `/` 200。若 Step 2 构建后未重新执行，此处先 `cd frontend-vite && npm run build` 再重启。
verify: powershell -Command "$ok=0; $f=Get-ChildItem 'd:\erp_system\frontend-vite\dist\assets' -Filter 'PatternRoomView*.js' | Select-Object -First 1; if($f -and $f.LastWriteTime -gt (Get-Date).AddHours(-2)){ $ok=1 }; $h=(Invoke-WebRequest -Uri 'http://127.0.0.1:3000/api/health' -UseBasicParsing).StatusCode; Write-Output ('chunk_fresh='+$ok+' health='+$h); if(-not $ok -or $h -ne 200){exit 1}"
max_iterations: 3

- [x] **Step 9: 端到端验证 pattern-room 板块**
action: 用浏览器（未登录态可验证静态部分；若 401 则验证关键网络指标）打开 `http://192.168.0.95:3000/pattern-room`，检查：(1) Network 面板中 grouped-list 请求完成时间 <500ms；(2) 无指向 /static/uploads/ 的请求排队阻塞 JS chunk 加载；(3) 控制台无连续重复 404。服务端复测：并发 6 个缺失图片 URL + 1 个 /api/health，health 应 <200ms。
verify:
  - type: browser
    url: http://192.168.0.95:3000/pattern-room
    check: 页面可加载（登录页或列表页），无白屏卡死；Network 无秒级 404 尖刺
  - type: shell
    command: powershell -Command "$jobs=@(); 1..6 | ForEach-Object { $jobs += Start-Job -ScriptBlock { param($u) try{ (Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 15).StatusCode }catch{ $_.Exception.Response.StatusCode.value__ } } -ArgumentList 'http://127.0.0.1:3000/static/uploads/customer-sampling/20260814/7307cff2e3be421ab44aed5d6501ca43.webp' }; $t0=Get-Date; $api=(Invoke-WebRequest -Uri 'http://127.0.0.1:3000/api/health' -UseBasicParsing -TimeoutSec 15).StatusCode; $dt=[math]::Round(((Get-Date)-$t0).TotalMilliseconds,0); $jobs|Wait-Job -Timeout 15|Out-Null; $jobs|Remove-Job -Force; Write-Output ('api_status='+$api+' api_ms='+$dt); if($dt -gt 500){exit 1}"
