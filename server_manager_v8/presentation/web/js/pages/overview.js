/* ============================================================
   ERP 服务器管理器 v8 —— 页面渲染：overview
   来源：docs/ui-redesign/ui_prototype_v8.html（语义边界拆分，逻辑未改）
   ============================================================ */
/* ---------- 审计 ---------- */
const auditRows = [
  ['22:38:52','admin','alert.raise','redis_unavailable','L0','产生','—','a7f3c9e1','规则 redis.ping_fail>=3 连续命中'],
  ['22:31:04','operator','pipeline.run','start_dev','L2','成功','10.6s','5c1b8e40','期望态收敛：idle → dev'],
  ['22:30:58','operator','process.kill_tree','pid 9912 (:3000)','L2','成功','312ms','5c1b8e40','端口占用清理，二次确认已通过'],
  ['22:30:41','viewer→operator','auth.elevate','session','L0','成功','—','5c1b8e40','PIN 校验通过，TTL 1800s'],
  ['21:14:22','admin','deploy.run','v2.14.3','L3','成功','82.3s','9d20fa11','变更原因：修复采购计划导入三段式链路'],
  ['21:12:07','admin','backup.create','env_20260830_2112','L1','成功','18.4s','9d20fa11','发布前自动备份'],
  ['20:03:11','operator','service.stop','erp-arq','L2','失败','5.0s','3ea77b52','超时未进入 STOPPED，已回滚为 RUNNING']
];
function renderAudit(){
  $('#auditBody').innerHTML = auditRows.map(r=>{
    const lvClass = 'lv lv-'+r[4].toLowerCase();
    const res = r[5]==='失败' ? '<span class="badge b-bad">失败</span>'
              : r[5]==='成功' ? '<span class="badge b-ok">成功</span>'
              : `<span class="badge b-info">${r[5]}</span>`;
    return `<tr><td class="mono tiny">${r[0]}</td><td>${r[1]}</td><td class="mono tiny">${r[2]}</td>
      <td class="mono tiny">${r[3]}</td><td><span class="${lvClass}">${r[4]}</span></td><td>${res}</td>
      <td class="mono tiny">${r[6]}</td><td class="mono tiny" style="color:var(--text-4)">${r[7]}</td>
      <td class="tiny muted" style="white-space:normal;max-width:280px">${r[8]}</td></tr>`;
  }).join('');
}
function audit(op,target,lv,result,detail,ms){
  const now = new Date();
  const t = [now.getHours(),now.getMinutes(),now.getSeconds()].map(n=>String(n).padStart(2,'0')).join(':');
  auditRows.unshift([t,state.role,op,target,lv,result,ms||'—',Math.random().toString(16).slice(2,10),detail||'—']);
  if(auditRows.length>40) auditRows.pop();
  renderAudit(); pushTimeline(t,'A',`<b>${op}</b> → ${target}`,state.role);
}

/* ---------- 时间轴 ---------- */
const tlRows = [
  ['22:38','A','<b>告警产生</b> P1 Redis 不可用，抑制 2 条下游','engine'],
  ['22:35','S','<b>健康检查</b> /api/health 200 OK（第 3 次）','system'],
  ['22:31','P','<b>收敛完成</b> idle → dev，5 步全部成功（10.6s）','operator'],
  ['22:30','U','<b>提权</b> viewer → operator，TTL 30min','operator'],
  ['21:14','P','<b>发布完成</b> v2.14.3，含数据库迁移 2 revisions','admin']
];
const TLC = { A:['var(--danger)','A'], S:['var(--info)','S'], P:['var(--brand)','P'], U:['var(--purple)','U'] };
function renderTL(){
  $('#timeline').innerHTML = tlRows.slice(0,8).map(r=>{
    const [c,ch] = TLC[r[1]]||TLC.S;
    return `<div class="tl-i"><span class="tm">${r[0]}</span><span class="ic" style="background:${c}">${ch}</span><span class="tx">${r[2]}</span><span class="rl">${r[3]}</span></div>`;
  }).join('');
}
function pushTimeline(t,kind,text,who){ tlRows.unshift([t.slice(0,5),kind,text,who]); renderTL(); }

/* ---------- 进程表 ---------- */
const procs = [
  ['python.exe','18420',34.2,428,'FastAPI dev'],
  ['node.exe','7336',12.8,612,'Vite dev server'],
  ['postgres.exe','4188',6.4,284,'PostgreSQL 16'],
  ['node.exe','9044',3.1,196,'vite esbuild'],
  ['ERP服务器管理器.exe','15208',1.2,88,'本程序']
];
function renderProcs(){
  $('#procBody').innerHTML = procs.map(p=>{
    const cls = p[2]>30?'bad':(p[2]>15?'warn':'');
    return `<tr><td><b style="color:var(--text-1)">${p[0]}</b><div class="tiny muted">${p[4]}</div></td>
      <td class="mono">${p[1]}</td>
      <td><div style="display:flex;align-items:center;gap:8px"><div class="mbar ${cls}" style="width:52px"><i style="width:${Math.min(100,p[2]*2)}%"></i></div><span class="mono tiny">${p[2].toFixed(1)}%</span></div></td>
      <td class="mono">${p[3]} MB</td>
      <td class="ta-r"><div class="acts"><button class="btn btn-ghost btn-sm" data-op="kill_proc" data-perm="operator" data-danger="L2">结束</button></div></td></tr>`;
  }).join('');
}

/* ---------- 日志 ---------- */
const logs = [
  ['22:38:52','mgr','ERROR','AlertEngine: rule=redis_unavailable fired (consecutive_fail=3) severity=P1 inhibits=[api_health_fail]'],
  ['22:38:50','api','WARN','redis connection refused: [Errno 10061] 127.0.0.1:6379 — degraded mode, cache disabled'],
  ['22:36:19','api','ERROR','Traceback (most recent call last): File "fastapi_app/services/stock_service.py", line 214, in reserve'],
  ['22:36:19','api','ERROR','  redis.exceptions.ConnectionError: Error 10061 connecting to 127.0.0.1:6379'],
  ['22:36:12','api','INFO','POST /api/purchase-plans/staging/confirm 200 OK 184ms batch_id=b7f21c'],
  ['22:35:47','mgr','WARN','redis ping timeout (3/3) — 已抑制 api_health_fail 告警（依赖链）'],
  ['22:35:02','api','INFO','GET /api/health 200 OK 4ms'],
  ['22:34:58','web','INFO','vite: hmr update /src/views/stock/StockOutTab.vue'],
  ['22:33:41','api','INFO','POST /api/purchase-plans/staging/validate 200 OK 612ms rows=128 invalid=3'],
  ['22:31:14','mgr','OK','Pipeline start_dev 完成：5/5 步成功，总耗时 10.6s，trace=5c1b8e40'],
  ['22:31:12','web','OK','VITE v5.4.2 ready in 4682 ms — Local: http://127.0.0.1:3000/'],
  ['22:31:07','mgr','INFO','健康检查 /api/health 第 3 次探测 200 OK（retries=30 interval=1s）'],
  ['22:31:04','api','OK','Uvicorn running on http://0.0.0.0:5002 (Press CTRL+C to quit) pid=18420'],
  ['22:31:02','mgr','INFO','启动 FastAPI：python -u -m uvicorn fastapi_app.main:app --reload PYTHONUTF8=1'],
  ['22:30:59','mgr','WARN','未找到 redis-server.exe / Memurai，开发模式降级继续（生产模式将拒绝启动 erp-arq）'],
  ['22:30:58','mgr','OK','端口 :3000 占用进程 pid 9912 已终止（进程树 2 个节点）'],
  ['22:30:57','mgr','INFO','清理端口占用：:5002 无占用，:3000 被 pid 9912 占用'],
  ['22:30:41','mgr','OK','auth.elevate: viewer → operator（PIN 校验通过，TTL=1800s）'],
  ['22:30:12','mgr','INFO','MetricsSampler 启动：间隔 2s，psutil 5.9.8 可用'],
  ['22:30:11','mgr','INFO','ERP 服务器管理器 v8.0.0 启动 · WebView2 Runtime 121.0.2277.128 · schema_version=2']
];
function renderLogs(kw='Traceback'){
  $('#logBody').innerHTML = logs.map(l=>{
    let m = l[3].replace(/</g,'&lt;');
    if(kw) m = m.replace(new RegExp(kw,'gi'), s=>`<span class="hl">${s}</span>`);
    return `<div class="lg ${l[2]}"><span class="t">${l[0]}</span><span class="s">${l[1]}</span><span class="l">${l[2]}</span><span class="m">${m}</span></div>`;
  }).join('');
}

/* ---------- Sparkline ---------- */
function spark(id, seed, color){
  const svg=$(id); if(!svg) return;
  let v=seed, pts=[];
  for(let i=0;i<24;i++){ v += (Math.sin(i*1.7+seed)*0.5 + (Math.random()-.5))*seed*0.12; v=Math.max(seed*0.5,Math.min(seed*1.5,v)); pts.push(v); }
  const mx=Math.max(...pts), mn=Math.min(...pts), rg=(mx-mn)||1;
  const d = pts.map((p,i)=>`${i===0?'M':'L'}${(i/23*118+1).toFixed(1)},${(24-((p-mn)/rg)*20).toFixed(1)}`).join(' ');
  svg.innerHTML = `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>
    <path d="${d} L119,26 L1,26 Z" fill="${color}" opacity="0.10"/>`;
}
function drawSparks(){
  spark('#sparkLat',86,'var(--success)'); spark('#sparkQps',42,'var(--brand)');
  spark('#sparkErr',1.8,'var(--warning)'); spark('#sparkSat',81,'var(--warning)');
}

