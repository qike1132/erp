---
design_type: feature
created_at: 2026-08-20
---

# 移动端登录页重构设计（明亮 iOS 风）

## Intent Contract
```
intent: 完全重构移动端登录页（MLoginView.vue），采用明亮 iOS / 大厂风格，提升大气感，并支持「记住账号」
constraints: 不改变登录 API 与跳转逻辑；复用共享 useLogin 组合式函数；沿用现有 --m-* 设计令牌；不引入新依赖
success_criteria: 手机访问 /login 呈现新页面；记住账号可保存/回填用户名；登录流程正常
risk_level: low
```

## Verification Contract
```
verify_steps:
  - run tests: 无相关单测，跳过
  - check: dev server（端口 3000）实时返回新模板与样式；npm run build 通过
  - confirm: 手机浏览器访问 /login，视觉与交互符合设计；记住账号开关可保存并回填用户名；登录成功跳转 /dashboard
```

## Governance Contract
```
approval_gates: 设计确认（已通过） → 实现后手机端视觉验收
rollback: git checkout 还原 src/mobile/views/login/MLoginView.vue（本次仅动此一文件）
ownership: 前端（我执行，用户验收）
```

## Scope

| In | Out |
| --- | --- |
| 重构 MLoginView.vue 模板/脚本/样式 | 修改登录 API 或后端 |
| 复用共享 useLogin 组合式函数 | 改动其它移动端页面 |
| 新增「记住账号」开关 | 引入新依赖 |
| 入场动效 + reduced-motion 降级 | 深色模式/多主题 |

## Decisions

| # | 决策 | 理由 / 备选 |
| --- | --- | --- |
| 1 | 明亮 iOS 风（浅底 + 毛玻璃卡片 + Apple 蓝） | 用户选定；设计令牌已是 Apple 色系 |
| 2 | 品牌区：LOGO 96px + 大标题「滨发协同」 | 用户选定「LOGO + 大标题」 |
| 3 | 复用共享 useLogin（sessionStorage remembered_username） | 保留 P0 修复约定，避免重复逻辑 |
| 4 | 记住账号用 iOS 开关 | 更贴近 iOS 交互习惯 |
| 5 | 动效错峰淡入上浮 + prefers-reduced-motion 禁用 | Apple 风格 + 无障碍 |

## Surface

**组件**：仅 `src/mobile/views/login/MLoginView.vue`（template + script + style 整体重写）。

- 布局：安全区适配；背景 `#F5F5F7` + 顶部极淡蓝白环境光；品牌区居中；毛玻璃卡片承载表单；底部版本信息。
- 表单：用户名 / 密码（显隐切换）/ 记住账号开关 / 登录按钮（Apple 蓝渐变、52px、圆角 16px、按压回弹、loading spinner）/ 错误信息（Apple 红）。
- 逻辑：`useLogin()` 提供 form/loading/errorMsg/showPassword/handleLogin；onMounted 回填 remembered_username 并置位 remember。

## Risks & Open Questions

- 低风险：仅单文件 UI 重构，复用既有登录逻辑，无数据层变更。
- 注意：`useLogin` 默认跳转 `/dashboard`，移动端路由下该路径为 MDashboard，行为一致。
