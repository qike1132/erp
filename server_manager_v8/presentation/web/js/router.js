/* ============================================================
   ERP 服务器管理器 v8 —— 页面路由
   来源：docs/ui-redesign/ui_prototype_v8.html（语义边界拆分，逻辑未改）
   ============================================================ */
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

