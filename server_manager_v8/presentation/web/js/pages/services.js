/* ============================================================
   ERP 服务器管理器 v8 —— 页面渲染：services
   来源：docs/ui-redesign/ui_prototype_v8.html（语义边界拆分，逻辑未改）
   ============================================================ */
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

