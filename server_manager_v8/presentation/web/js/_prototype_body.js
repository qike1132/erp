/* ============================================================
   v8 原型交互层
   注：所有 API 调用点在真实实现中替换为 pywebview.api.<useCase>()
   ============================================================ */
const $  = (s,r=document)=>r.querySelector(s);
const $$ = (s,r=document)=>Array.from(r.querySelectorAll(s));

/* ---------- 角色 / 权限模型 ---------- */
const ROLES = {
  viewer:   { rank:0, mark:'R', name:'只读',   full:'只读 Viewer',    desc:'仅可查看与导出，无任何变更权限' },
  operator: { rank:1, mark:'O', name:'运维',   full:'运维 Operator',  desc:'可启停/重启服务、切换模式、静默告警、执行备份' },
  admin:    { rank:2, mark:'A', name:'管理员', full:'管理员 Admin',   desc:'全部权限，含 L3 极高危操作' }
};
const DANGER = {
  L0:{ label:'低危', color:'var(--success)' },
  L1:{ label:'中危', color:'var(--info)' },
  L2:{ label:'高危', color:'var(--warning)' },
  L3:{ label:'极高危', color:'var(--danger)' }
};
/* 操作元数据：标题 / 影响面 / 确认词 */
const OPS = {
  stop_dev:      { t:'停止开发模式', impact:['终止 FastAPI 进程 <b>pid 18420</b> 及其子进程树','终止 Vite Dev Server <b>pid 7336</b>','释放端口 <b>5002</b> / <b>3000</b>','当前页面热重载会话将断开','预计耗时 <b>3~6 秒</b>'] },
  start_prod:    { t:'切换到生产模式', impact:['先停止开发模式（进入 SWITCHING 持锁）','启动 NSSM 服务 <b>erp-prod</b>、<b>erp-arq</b>','写入服务依赖 <b>DependOnService=postgresql-x64-16</b>','Redis 当前不可用 → <b>erp-arq 将启动失败</b>','预计耗时 <b>20~40 秒</b>'] },
  kill_port:     { t:'清理端口占用进程', impact:['查找占用端口 <b>6379</b> 的进程并终止其进程树','若该进程为非 ERP 组件（如其他 Redis 实例），也会被终止','此操作<b>不可撤销</b>','预计耗时 <b>1~2 秒</b>'] },
  apply_desired: { t:'应用期望态收敛计划', impact:['状态机进入 <b>SWITCHING</b> 并持独占锁','按计划顺序执行 5 个步骤，任一步失败即中止','失败时保留已完成步骤，不自动回滚','预计耗时 <b>15~45 秒</b>'] },
  save_cfg:      { t:'保存配置变更', impact:['写入 <b>server_manager_config.json</b>（schema v2）','2 项变更立即生效：health.retries、auth.elevate_ttl_s','原文件自动备份为 <b>*.bak</b>'] },
  uninstall_svc: { t:'卸载 NSSM 服务', confirmWord:'uninstall erp-prod', impact:['停止并<b>永久移除</b> Windows 服务 <b>erp-prod</b>','清除 NSSM 注册项、依赖声明、日志重定向配置','生产模式将<b>完全不可用</b>，需重新安装服务','此操作<b>不可撤销</b>'] },
  restore:       { t:'从备份恢复环境', confirmWord:'restore env_20260831_2014', impact:['停止所有 ERP 服务与进程','<b>覆盖</b>当前数据库（pg_restore -c）','<b>覆盖</b>应用代码、配置、NSSM 服务清单','恢复前自动创建当前环境快照（可回滚）','当前未备份的数据将<b>永久丢失</b>'] },
  rollback:      { t:'回滚到上一稳定版本', confirmWord:'rollback v2.13.8', impact:['应用代码回退至 <b>v2.13.8</b>','数据库迁移<b>降级</b> 2 个 revision（存在数据丢失风险）','重启 erp-prod / erp-arq','建议先执行「立即备份」'] },
  reset_cfg:     { t:'重置配置为默认值', confirmWord:'reset config', impact:['所有端口、路径、健康检查、告警规则、权限配置<b>全部重置</b>','PIN 与提权配置将被清除，下次启动需重新设置','原配置备份为 <b>*.reset.bak</b>'] },
  reinstall_svc: { t:'重装 NSSM 服务', confirmWord:'reinstall services', impact:['卸载并重新注册 <b>erp-prod</b>、<b>erp-arq</b>','重新探测并写入服务依赖','生产模式期间执行会造成<b>服务中断</b>'] },
  deploy:        { t:'开始发布', confirmWord:'deploy v2.14.4', impact:['执行 5 步发布流程：检查 → 备份 → 构建 → 迁移 → 重启','数据库迁移<b>不可自动回退</b>','发布窗口内告警自动静默'] }
};

let state = {
  role:'viewer', elevUntil:0, page:'overview',
  desired:'dev', locked:false, pendingOp:null
};

/* ---------- 权限判定 ---------- */
const need = (perm)=> ROLES[perm]?.rank ?? 0;
const can  = (perm)=> ROLES[state.role].rank >= need(perm);

function applyPerms(){
  $$('[data-perm]').forEach(el=>{
    const perm = el.dataset.perm, ok = can(perm);
    el.classList.toggle('locked', !ok);
    if(!ok){
      el.classList.add('tip');
      el.dataset.tip = `需要「${ROLES[perm].name}」角色 · 点击提权`;
    } else {
      el.removeAttribute('data-tip');
      if(!el.dataset.keepTip) el.classList.remove('tip');
    }
  });
  $$('[data-perm-input]').forEach(el=>{
    const ok = can(el.dataset.permInput);
    if(el.classList.contains('sw')) el.dataset.disabled = ok?'0':'1';
    else el.disabled = !ok;
  });
  const R = ROLES[state.role];
  $('#roleMark').textContent = R.mark;
  $('#roleName').textContent = R.name;
  $('#roleChip').dataset.role = state.role;
  $('#bigRoleMark').textContent = R.mark;
  $('#bigRoleMark').style.background = state.role==='viewer'?'var(--text-3)':(state.role==='admin'?'var(--purple)':'var(--brand)');
  $('#bigRoleName').textContent = R.full;
  $('#bigRoleDesc').textContent = R.desc;
  $('#sbRole').textContent = '角色 '+state.role;
  const elevated = state.role!=='viewer';
  $('#elevStatus').innerHTML = elevated
    ? `<span class="badge b-ok"><i class="dot"></i>已提权（JIT 30min）</span>`
    : `<span class="badge b-idle">未提权</span>`;
  $('#roleTtl').style.display = elevated?'':'none';
  $('#btnElevate').textContent = elevated?'切换角色':'提权';
}

/* ---------- 提权倒计时 ---------- */
function tickElev(){
  if(state.role==='viewer'){ $('#elevTtl').textContent='—'; return; }
  const left = Math.max(0, state.elevUntil - Date.now());
  const m = Math.floor(left/60000), s = Math.floor(left%60000/1000);
  const txt = String(m).padStart(2,'0')+':'+String(s).padStart(2,'0');
  $('#roleTtl').textContent = txt;
  $('#elevTtl').textContent = txt + ' 后自动降权';
  const expiring = left < 5*60*1000;
  $('#roleChip').classList.toggle('expiring', expiring);
  if(left<=0){
    state.role='viewer'; applyPerms();
    toast('warn','提权已过期，已自动降权为「只读」','JIT 安全策略 · auth.elevate_ttl_s=1800');
    audit('auto_de_elevate','session','L0','成功','JIT 到期自动回收');
  }
}

/* ---------- Toast ---------- */
function toast(kind, text, sub, undo){
  const el = document.createElement('div');
  el.className = 'toast '+(kind||'');
  el.innerHTML = `<div class="tt">${text}${sub?`<small>${sub}</small>`:''}</div>`;
  if(undo){
    const u = document.createElement('span'); u.className='undo'; u.textContent='撤销 5s';
    let n=5; const iv=setInterval(()=>{ n--; u.textContent=`撤销 ${n}s`; if(n<=0) clearInterval(iv); },1000);
    u.onclick=()=>{ clearInterval(iv); el.remove(); toast('ok','已撤销操作','审计流水记录一条 undo 事件'); audit('undo',undo,'L0','成功','用户在 5s 窗口内撤销'); };
    el.appendChild(u);
  }
  $('#toasts').appendChild(el);
  setTimeout(()=>{ el.style.opacity='0'; el.style.transition='opacity .25s'; setTimeout(()=>el.remove(),260); }, undo?5200:3400);
  while($('#toasts').children.length>4) $('#toasts').firstElementChild.remove();
}

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

/* ---------- 弹窗 ---------- */
function closeModal(){ $('#mask').classList.remove('on'); $('#modal').innerHTML=''; }
$('#mask').onclick = e=>{ if(e.target.id==='mask') closeModal(); };
document.addEventListener('keydown', e=>{ if(e.key==='Escape') closeModal(); });

function openModal(html, wide){
  $('#modal').className = 'modal'+(wide?' wide':'');
  $('#modal').innerHTML = html;
  $('#mask').classList.add('on');
}

/* 提权弹窗 */
function openElevate(afterOp){
  let pick = state.role==='viewer' ? 'operator' : state.role;
  openModal(`
    <div class="m-hd"><div class="mi" style="background:var(--brand-tint);color:var(--brand)">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg></div>
      <div><h3>身份提权</h3><div class="msub">JIT 临时提权 · 有效期 30 分钟滑动过期 · 全程审计</div></div></div>
    <div class="m-bd">
      <div class="role-pick" id="rolePick">
        ${['viewer','operator','admin'].map(k=>`
          <div class="role-opt ${k===pick?'sel':''}" data-r="${k}">
            <div class="rm" style="background:${k==='viewer'?'var(--text-3)':k==='admin'?'var(--purple)':'var(--brand)'}">${ROLES[k].mark}</div>
            <div><div class="rt">${ROLES[k].full}</div><div class="rd">${ROLES[k].desc}</div></div>
          </div>`).join('')}
      </div>
      <div class="field" style="margin-top:14px" id="pinField">
        <label>本地 PIN <span class="req">*</span></label>
        <div class="pin"><input maxlength="1" value="1"><input maxlength="1" value="2"><input maxlength="1" value="3"><input maxlength="1" value="4"></div>
        <div class="hint">首次运行时设置，PBKDF2-SHA256 存储 hash。原型中任意 4 位均可通过。</div>
      </div>
      ${afterOp?`<div class="warnbar nf"><div>提权成功后将<b>自动继续</b>刚才被拦截的操作：${OPS[afterOp]?.t||afterOp}</div></div>`:''}
    </div>
    <div class="m-ft"><button class="btn btn-ghost" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" id="doElev">确认提权</button></div>`);
  $$('#rolePick .role-opt').forEach(o=>o.onclick=()=>{
    $$('#rolePick .role-opt').forEach(x=>x.classList.remove('sel')); o.classList.add('sel'); pick=o.dataset.r;
    $('#pinField').style.display = pick==='viewer'?'none':'';
  });
  $('#doElev').onclick = ()=>{
    const old = state.role;
    state.role = pick;
    state.elevUntil = Date.now() + 30*60*1000;
    applyPerms(); tickElev(); closeModal();
    if(pick==='viewer'){ toast('ok','已降权为「只读」','所有变更类操作已锁定'); audit('auth.de_elevate','session','L0','成功','用户主动降权'); }
    else { toast('ok',`已提权为「${ROLES[pick].full}」`,'有效期 30 分钟，到期自动回收'); audit('auth.elevate','session','L0','成功',`${old} → ${pick}，PIN 校验通过，TTL 1800s`); }
    if(afterOp && can(document.querySelector(`[data-op="${afterOp}"]`)?.dataset.perm||'operator')){
      setTimeout(()=>runOp(afterOp, document.querySelector(`[data-op="${afterOp}"]`)), 260);
    }
  };
}

/* 高危确认弹窗 */
function openConfirm(op, btn){
  const meta = OPS[op] || { t:op, impact:['该操作将改变系统状态'] };
  const lv = btn.dataset.danger;
  const isL3 = lv==='L3';
  const needReason = isL3;
  openModal(`
    <div class="m-hd"><div class="mi" style="background:${isL3?'var(--danger-tint)':'var(--warning-tint)'};color:${isL3?'var(--danger)':'var(--warning)'}">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg></div>
      <div><h3>${meta.t}</h3><div class="msub">危险等级 <b style="color:${DANGER[lv].color}">${lv} ${DANGER[lv].label}</b> · 执行者 ${ROLES[state.role].full} · 将写入审计</div></div></div>
    <div class="m-bd">
      ${isL3?`<div class="warnbar dg"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;margin-top:1px"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg><div><b>极高危操作</b>：可能造成不可逆的数据或环境变更。请逐条确认下方影响面，并键入操作名以解锁确认按钮。</div></div>`:''}
      <div class="impact"><div class="it">影响面清单（${meta.impact.length} 项）</div><ul>${meta.impact.map(i=>`<li><span>${i}</span></li>`).join('')}</ul></div>
      ${meta.confirmWord?`<div class="field"><label>请键入 <b class="mono" style="color:var(--danger)">${meta.confirmWord}</b> 以确认 <span class="req">*</span></label>
        <input class="inp mono" id="cw" placeholder="${meta.confirmWord}" autocomplete="off"></div>`:''}
      ${needReason?`<div class="field"><label>变更原因 <span class="req">*</span></label>
        <textarea class="inp" id="rsn" placeholder="例如：修复 xxx 缺陷 / 按变更单 CHG-2026-0831 执行"></textarea>
        <div class="hint">原因将随审计记录永久留存（保留 180 天，哈希链防篡改）。</div></div>`:''}
    </div>
    <div class="m-ft"><button class="btn btn-ghost" onclick="closeModal()">取消</button>
      <button class="btn ${isL3?'btn-danger':'btn-primary'}" id="doAct" ${meta.confirmWord||needReason?'disabled':''}>确认执行</button></div>`, isL3);

  const chk = ()=>{
    let ok = true;
    if(meta.confirmWord) ok = ok && $('#cw').value.trim()===meta.confirmWord;
    if(needReason) ok = ok && $('#rsn').value.trim().length>=4;
    $('#doAct').disabled = !ok;
  };
  if($('#cw')) $('#cw').oninput = chk;
  if($('#rsn')) $('#rsn').oninput = chk;
  $('#doAct').onclick = ()=>{
    const reason = $('#rsn')?.value.trim() || '二次确认已通过';
    closeModal(); execute(op, btn, reason);
  };
}

/* ---------- 操作执行 ---------- */
function runOp(op, btn){
  if(!btn) return;
  const perm = btn.dataset.perm || 'viewer';
  const lv   = btn.dataset.danger || 'L0';
  if(!can(perm)){                                  // 权限不足 → 唤起提权，成功后自动续跑
    audit(op, btn.textContent.trim(), lv, '拒绝', `权限不足：当前 ${state.role}，需要 ${perm}`);
    toast('err','权限不足，已拦截',`需要「${ROLES[perm].name}」角色，正在唤起提权`);
    openElevate(op); return;
  }
  if(state.locked && ['stop_dev','start_prod','apply_desired','restart_dev','start_svc','restart_svc'].includes(op)){
    toast('warn','已有操作进行中，请稍候','ActionLock 幂等保护 · 同族按钮已禁用'); return;
  }
  if(lv==='L2' || lv==='L3'){ openConfirm(op, btn); return; }
  execute(op, btn, lv==='L1'?'轻确认（5s 可撤销）':'—');
}

function execute(op, btn, reason){
  const lv = btn.dataset.danger || 'L0';
  const label = btn.textContent.trim();

  /* 需要跑 Pipeline 的操作 */
  if(['start_prod','apply_desired','stop_dev','restart_dev'].includes(op)){
    state.locked = true; $('#lockState').textContent='执行中（已加锁）'; $('#lockState').className='badge b-warn';
    $$('[data-op]').forEach(b=>{ if(b!==btn) b.classList.add('locked'); });
    btn.classList.add('busy');
    runPipeline(op, reason);
    return;
  }

  /* 普通操作 */
  const undoable = lv==='L1' && ['clear_log','clean_logs','silence','ack','fix_redis','start_redis','backup_now','start_svc','restart_svc'].includes(op);
  const ms = (Math.random()*900+180).toFixed(0)+'ms';
  audit(op, label, lv, '成功', reason, ms);
  const msgs = {
    fix_redis:['ok','已执行推荐修复：启动 Redis','未找到 redis-server.exe，已打开安装引导'],
    start_redis:['ok','Redis 启动指令已下发','探测 redis-server.exe / Memurai 服务'],
    ack:['ok','告警已确认','聚合事件下全部 6 条同根因告警一并确认'],
    silence:['ok','已创建静默窗口','期间告警仅记录，不通知（维护窗口模式）'],
    clear_log:['warn','日志已清空','当前视图 418 行已清除，落盘文件保留'],
    clean_logs:['ok','已清理历史日志','释放 2.4 GB，磁盘饱和度 81% → 76%'],
    backup_now:['ok','备份任务已提交','复用 fastapi_app/services/backup orchestrator'],
    verify_chain:['ok','哈希链校验通过','7 条记录，链完整，未检出篡改'],
    export_audit:['ok','审计流水已导出','audit_20260831.csv · 7 条记录'],
    export_log:['ok','日志已导出','server_manager_20260831.log'],
    export_diag:['ok','诊断包已生成','含配置快照、最近 500 行日志、服务状态、指标 1h'],
    export_alerts:['ok','告警已导出','alerts_20260831.csv · 5 条事件'],
    verify_bk:['ok','备份校验通过','sha256 一致，manifest 完整，9 个分片齐备'],
    save_cfg:['ok','配置已保存','2 项变更立即生效 · 原文件已备份'],
    goto_logs:['ok','已跳转日志中心','已定位到告警时刻并高亮关键字'],
    goto_metrics:['ok','已跳转指标视图','时间轴已对齐告警发生时刻'],
    refresh:['ok','状态已刷新','sc / nssm 实时探测完成'],
    kill_proc:['warn','进程已终止','进程树 1 个节点'],
    kill_port:['warn','端口占用已清理','终止 pid 及其子进程树'],
    restore:['err','恢复流程已启动','已创建恢复前快照，可回滚'],
    rollback:['err','回滚流程已启动','数据库降级 2 revisions'],
    uninstall_svc:['err','服务已卸载','erp-prod 已从 Windows 服务移除'],
    reset_cfg:['err','配置已重置','原配置备份为 *.reset.bak'],
    reinstall_svc:['ok','服务重装完成','已重新探测并写入依赖'],
    deploy:['ok','发布流程已启动','5 步 Pipeline 执行中'],
    rules:['ok','规则管理已打开','8 条规则：4 条 P1 症状 + 4 条 P3 饱和度'],
    kw_rules:['ok','关键字规则已打开','1 条启用：Traceback → P2'],
    download_bk:['ok','备份导出中','216.4 MB'],
    abort_pipe:['warn','已请求中断流程','当前步骤完成后停止，不自动回滚']
  };
  const m = msgs[op] || ['ok','操作已执行', label];
  if(op==='goto_logs'){ nav('logs'); }
  if(op==='goto_metrics'){ nav('overview'); }
  toast(m[0], m[1], m[2], undoable?op:null);
}

/* ---------- Pipeline 模拟 ---------- */
const PIPES = {
  start_prod: [['停止开发模式进程树','终止 pid 18420 / 7336，释放 :5002 :3000'],['探测服务依赖','发现 postgresql-x64-16，写入 DependOnService'],['安装/校验 NSSM 服务','erp-prod / erp-arq 注册项校验通过'],['启动 erp-prod','等待 RUNNING（timeout 30s）'],['启动 erp-arq','Redis 不可用 → 启动失败']],
  apply_desired:[['计算收敛计划','当前 dev → 目标 '+'prod'+'，需 5 步'],['进入 SWITCHING 持锁','拒绝并发转移'],['停止对侧模式','开发模式已停止'],['启动目标模式','NSSM 服务启动中'],['健康校验','/api/health 探测']],
  stop_dev:  [['终止 Vite 进程树','pid 7336 + 1 子进程'],['终止 FastAPI 进程树','pid 18420'],['释放端口',':5002 :3000 已释放'],['状态机转移','DEV → IDLE']],
  restart_dev:[['停止现有进程','pid 18420 / 7336'],['清理端口占用',':5002 :3000'],['启动 FastAPI','uvicorn --reload'],['健康检查','/api/health 200 OK'],['启动 Vite','vite ready']]
};
function runPipeline(op, reason){
  const steps = PIPES[op] || PIPES.stop_dev;
  const trace = Math.random().toString(16).slice(2,10);
  $('#ocPipeline').style.display='block';
  $('#pipeTrace').textContent = 'trace='+trace;
  $('#pipeSteps').innerHTML = steps.map((s,i)=>
    `<div class="step pend" data-i="${i}"><div class="sdot">${i+1}</div><div class="sbody"><div class="st">${s[0]}<span class="ms">—</span></div><div class="sd">等待执行</div></div></div>`).join('');
  if(state.page!=='overview' && state.page!=='services') nav('overview');
  let i=0;
  const next=()=>{
    if(i>0){
      const prev=$(`#pipeSteps .step[data-i="${i-1}"]`);
      const fail = (op==='start_prod' && i-1===steps.length-1);
      prev.className = 'step '+(fail?'fail':'done');
      prev.querySelector('.sdot').textContent = fail?'!':'✓';
      prev.querySelector('.ms').textContent = (Math.random()*3+0.4).toFixed(2)+'s';
      prev.querySelector('.sd').textContent = steps[i-1][1];
      if(fail){ finish(false, trace, steps[i-1][0]); return; }
    }
    if(i>=steps.length){ finish(true, trace); return; }
    const cur=$(`#pipeSteps .step[data-i="${i}"]`);
    cur.className='step run'; cur.querySelector('.sd').textContent='执行中…';
    i++; setTimeout(next, 700+Math.random()*500);
  };
  next();

  function finish(ok, tr, failStep){
    state.locked=false;
    $('#lockState').textContent='空闲'; $('#lockState').className='badge b-brand';
    $$('[data-op]').forEach(b=>b.classList.remove('busy'));
    applyPerms();
    if(ok){
      audit('pipeline.run', op, 'L2', '成功', reason+' · '+steps.length+' 步全部成功', (steps.length*1.4).toFixed(1)+'s');
      toast('ok','收敛完成：'+steps.length+'/'+steps.length+' 步成功','trace='+tr+' · 已写入审计');
      if(op==='stop_dev'){ setMode('idle'); }
      if(op==='start_prod'||op==='apply_desired'){ setMode('prod'); }
      if(op==='restart_dev'){ setMode('dev'); }
    }else{
      audit('pipeline.run', op, 'L2', '失败', `步骤「${failStep}」失败：Redis 不可用（依赖前置未满足）`, (steps.length*1.4).toFixed(1)+'s');
      toast('err','流程失败于步骤：'+failStep,'已保留前序步骤，不自动回滚 · 见 runbook');
      nav('alerts');
    }
  }
}

/* ---------- 模式切换视觉 ---------- */
function setMode(m){
  const badge=$('#modeBadge'), txt=$('#modeText'), sb=$('#sbText');
  $('#ocDev').className='oc-card'+(m==='dev'?' on':' dim');
  $('#ocProd').className='oc-card'+(m==='prod'?' on':' dim');
  if(m==='idle'){ badge.className='mode-badge idle'; txt.textContent='全部已停止'; sb.textContent='空闲 · 无运行中的服务'; $('#chipApi').classList.add('off'); $('#chipWeb').classList.add('off'); $('#curState').textContent='当前：停机'; }
  if(m==='dev'){ badge.className='mode-badge'; txt.textContent='开发模式运行中'; sb.textContent='开发模式运行中 · API 18420 · WEB 7336'; $('#chipApi').classList.remove('off'); $('#chipWeb').classList.remove('off'); $('#curState').textContent='当前：开发模式'; }
  if(m==='prod'){ badge.className='mode-badge warn'; txt.textContent='生产模式（部分降级）'; sb.textContent='生产模式 · erp-prod RUNNING · erp-arq FAILED'; $('#chipApi').classList.remove('off'); $('#chipWeb').classList.remove('off'); $('#curState').textContent='当前：生产模式'; }
}

/* ---------- 路由 ---------- */
const META = {
  overview:['总览驾驶舱','黄金四指标 · 三层健康 · 一键操作'],
  services:['服务编排','期望态收敛 · 依赖拓扑 · 流程编排'],
  alerts:['监控告警','症状化规则 · 事件聚合 · 抑制静默'],
  logs:['日志中心','多源分流 · 关键字规则 · 虚拟滚动'],
  deploy:['部署发布','Pipeline 驱动 · 版本与回滚'],
  backup:['备份恢复','envbak v3.0 · 加密 · 一键恢复'],
  config:['配置中心','schema 校验 · 版本迁移 · diff 预览'],
  access:['权限与审计','RBAC 三级 · JIT 提权 · 哈希链审计']
};
function nav(p){
  state.page=p;
  $$('.nav-item[data-page]').forEach(b=>b.classList.toggle('active', b.dataset.page===p));
  $$('.page').forEach(s=>s.classList.toggle('active', s.id==='page-'+p));
  $('#crumb').textContent=META[p][0]; $('#crumbSub').textContent=META[p][1];
  $('.content').scrollTop=0;
  if(p==='overview') drawSparks();
}

/* ---------- 事件绑定 ---------- */
$$('.nav-item[data-page]').forEach(b=>b.onclick=()=>nav(b.dataset.page));
document.addEventListener('click', e=>{
  const jump = e.target.closest('[data-page-jump]');
  if(jump){ nav(jump.dataset.pageJump); return; }
  const opBtn = e.target.closest('[data-op]');
  if(opBtn){ runOp(opBtn.dataset.op, opBtn); return; }
  const lay = e.target.closest('.layer-hd');
  if(lay){ lay.parentElement.classList.toggle('open'); return; }
  const ae = e.target.closest('.ae-hd');
  if(ae){ ae.parentElement.classList.toggle('open'); return; }
  const src = e.target.closest('.src-item');
  if(src){ $$('.src-item').forEach(s=>s.classList.remove('active')); src.classList.add('active'); return; }
  const sw = e.target.closest('.sw');
  if(sw){ if(sw.dataset.disabled==='1'){ toast('err','权限不足','该配置项需要「管理员」角色'); return; } sw.classList.toggle('on'); return; }
  const sg = e.target.closest('.seg button');
  if(sg){
    Array.from(sg.parentElement.children).forEach(b=>b.classList.remove('on')); sg.classList.add('on');
    if(sg.dataset.st){ state.desired=sg.dataset.st; showPlan(sg.dataset.st); }
    return;
  }
});
$('#navBtn').onclick = ()=>document.body.classList.toggle('nav-collapsed');
const toggleTheme = ()=>{
  const h=document.documentElement;
  h.dataset.theme = h.dataset.theme==='dark'?'light':'dark';
  drawSparks();
  toast('ok','已切换为'+(h.dataset.theme==='dark'?'深色':'浅色')+'主题','CSS 变量热切换 · 零控件重建（v6 需销毁重建全部控件）');
};
$('#themeBtn').onclick = toggleTheme;
$('#themeBtn2').onclick = toggleTheme;
$('#roleChip').onclick = ()=>openElevate(null);
$('#btnElevate').onclick = ()=>openElevate(null);
$('#btnDeElevate').onclick = ()=>{
  if(state.role==='viewer'){ toast('warn','当前已是最低权限','无需降权'); return; }
  const old=state.role; state.role='viewer'; applyPerms(); tickElev();
  toast('ok','已立即降权为「只读」','JIT 最小权限原则');
  audit('auth.de_elevate','session','L0','成功',`${old} → viewer，用户主动降权`);
};

/* 期望态收敛计划预览 */
function showPlan(st){
  const cur = $('#curState').textContent.includes('开发')?'dev':($('#curState').textContent.includes('生产')?'prod':'idle');
  if(st===cur){ $('#planBox').style.display='none'; toast('warn','目标态与当前态一致','无需收敛，计划为空'); return; }
  const plans = {
    idle:[['停止开发模式进程树','终止 pid 18420 / 7336'],['释放端口',':5002 :3000'],['状态机转移','→ IDLE']],
    dev: [['停止生产服务','erp-prod / erp-arq → STOPPED'],['清理端口占用',':5002 :3000'],['启动 FastAPI','uvicorn --reload'],['健康检查','/api/health'],['启动 Vite','npm run dev']],
    prod:[['停止开发模式','终止 pid 18420 / 7336'],['探测服务依赖','写入 DependOnService'],['校验 NSSM 注册','erp-prod / erp-arq'],['启动 erp-prod','等待 RUNNING'],['启动 erp-arq','依赖 Redis']]
  };
  const p = plans[st];
  $('#planBox').style.display='block';
  $('#planCount').textContent=p.length;
  $('#planSteps').innerHTML = p.map((s,i)=>`<div class="step pend"><div class="sdot">${i+1}</div><div class="sbody"><div class="st">${s[0]}</div><div class="sd">${s[1]}</div></div></div>`).join('');
}

/* ---------- 定时器 ---------- */
setInterval(()=>{
  const d=new Date();
  $('#sbClock').textContent=[d.getHours(),d.getMinutes(),d.getSeconds()].map(n=>String(n).padStart(2,'0')).join(':');
  tickElev();
},1000);
setInterval(()=>{
  /* 模拟 psutil 2s 采样：指标微抖动 */
  const lat=(80+Math.random()*18).toFixed(0), qps=(38+Math.random()*10).toFixed(0), err=(1.4+Math.random()*0.9).toFixed(1);
  $('#kpiLat').innerHTML=lat+'<small>ms</small>';
  $('#kpiQps').innerHTML=qps+'<small>req/s</small>';
  $('#kpiErr').innerHTML=err+'<small>%</small>';
  procs.forEach(p=>{ p[2]=Math.max(0.4,Math.min(96,p[2]+(Math.random()-.5)*6)); });
  if(state.page==='overview'){ renderProcs(); applyPerms(); }
},2000);
let up=5047;
setInterval(()=>{ up++; const h=String(Math.floor(up/3600)).padStart(2,'0'),m=String(Math.floor(up%3600/60)).padStart(2,'0'),s=String(up%60).padStart(2,'0'); $('#devUptime').textContent=`${h}:${m}:${s}`; },1000);

/* ---------- 初始化 ---------- */
renderAudit(); renderTL(); renderProcs(); renderLogs(); drawSparks(); applyPerms(); nav('overview');
setTimeout(()=>toast('warn','P1 告警：Redis 不可用，任务队列能力丧失','已抑制 2 条下游告警 · 点击「监控告警」查看 runbook'),900);
setTimeout(()=>toast('','当前为「只读」角色，变更类按钮已锁定','点击任一锁定按钮或右上角角色徽章即可提权体验'),2200);
