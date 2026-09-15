/* ============================================================
   ERP 服务器管理器 v8 —— 弹窗 / Toast / 确认流
   来源：docs/ui-redesign/ui_prototype_v8.html（语义边界拆分，逻辑未改）
   ============================================================ */
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

