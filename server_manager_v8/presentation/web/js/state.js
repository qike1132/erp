/* ============================================================
   ERP 服务器管理器 v8 —— 前端状态与权限模型
   来源：docs/ui-redesign/ui_prototype_v8.html（语义边界拆分，逻辑未改）
   ============================================================ */
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

