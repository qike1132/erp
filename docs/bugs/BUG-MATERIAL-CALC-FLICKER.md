# BUG-MATERIAL-CALC-FLICKER 修复记录

- **修复时间**: 2026-04-29
- **Git Commit**: 8bf683d5a796516bb7e7481406c2be0322cae1b7
- **根因分析**: 
  1. (P0) 结果区域使用 v-if/v-else 三分支切换，calculating=true 时销毁结果DOM、显示loading；calculating=false 时从零重建结果DOM，造成闪屏
  2. (P0) mc-fade-in-up 动画从 opacity:0 开始，配合 animationDelay 逐项延迟，重建时从不可见渐显，视觉上构成明显闪烁
  3. (P1) orderItems 使用 filter 整组替换数组，Vue 销毁重建所有订单项节点而非精确移除
- **影响范围**: MaterialCalculatorView.vue 产品多选SKU操作
- **修复方案**:
  1. 移除 v-if=calculating 分支，结果DOM在计算期间保持存活，loading状态仅通过badge显示
  2. 移除 mc-fade-in-up 动画及 animationDelay，消除从 opacity:0 重建的闪烁
  3. orderItems 移除改用 splice 精确删除单个元素
- **验证结果**: vite build 通过，TypeScript 无新增错误，bandit 无高危漏洞
