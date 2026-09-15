/* ============================================================
   ERP 服务器管理器 v8 —— 事件绑定 / 定时器 / 初始化
   来源：docs/ui-redesign/ui_prototype_v8.html（语义边界拆分，逻辑未改）
   ============================================================ */
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
