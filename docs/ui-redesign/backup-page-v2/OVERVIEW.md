# 数据备份中心前端 UI 重设计 · 交付概览

> 交付日期:2026-08-23 | 团队:软件开发团队(主理人齐活林 + 工程师寇豆码 + QA 严过关)
> 交付模式:快速模式(单页面视觉层重设计)

---

## TL;DR

依据 ERP 全局设计体系(`src/styles/app.css` Plush Cute)+ 备份业务语义规范(`docs/ui-redesign/backup-center/DESIGN.md`),对 `/backup` 数据备份页进行了**纯视觉层**重新设计,交付单文件自包含 HTML 效果图。**业务逻辑零改动**(备份触发/历史记录/恢复操作/状态标识/数据接口全部保持不变)。

## 交付物清单

| 文件 | 说明 |
|------|------|
| `backup-page-redesign.html` | 重设计高保真效果图(1143 行,单文件自包含,离线双击可开) |
| `CHANGES.md` | 设计前后对比清单(25 项调整 + 未改动项说明) |
| `QA_REPORT.md` | QA 规范符合性验证报告(**PASS**,0 P0 / 0 P1 / 8 P2 可选优化) |

## 设计规范依据

1. **全局设计体系(权威基准)**:`frontend-vite/src/styles/app.css` — Plush Cute 风格:品牌蓝渐变 `#5b8def→#3a6bd6`、`page-card` 白卡容器(18px 圆角)、大圆角刻度(按钮 14 / 输入 12 / 卡片 24 / 弹窗 28px)、蓝调 ocean 阴影、`.data-table` 表格规范
2. **备份业务语义规范**:`docs/ui-redesign/backup-center/DESIGN.md` — 状态四色语义、危险操作红色域 + 二次确认、进度百分比必显、mono 数据字体、互斥任务禁用

## 核心调整(设计前 → 设计后)

- **页面骨架**:无侧边栏单栏 → 230px 白卡侧边栏 + 渐变主内容区(`linear-gradient(135deg,#f4f6fc,#f0f2f5)`)
- **品牌色**:`#2F7BFF` 旧 Ant 蓝 → primary 系 `#5b8def/#3a6bd6/#2d5ab8`,主按钮 `--gradient-primary` 渐变
- **语义色映射**:成功 `#28c76f` / 进行中 `#5b8def` / 警告 `#ff9f43` / 危险 `#ea5455`(只表达状态,不用于装饰)
- **圆角体系**:8px 克制档 → Plush Cute 大圆角(按钮 14 / 输入 12 / page-card 18 / 弹窗 28px)
- **组件统一**:卡片/按钮/表单/表格/弹窗全部对齐 `.page-card`、`.data-table` 等全局组件标准
- **危险域**:还原确认弹层 28px 圆角 + 红色警示条 + 输入「确认还原」激活确认钮(默认禁用)
- **数据可扫描**:路径/文件名/时间戳/大小/百分比一律 mono + tabular-nums
- **动效/响应式**:card-hover 上浮、fade-in/slide-up 入场;≥1280 四列 / 768-1279 两列 / <768 单列

## QA 验证结论

7 项检查全部通过:令牌 21/21 值一致、组件标准对齐、语义色正确、业务语义全保留(互斥禁用 + tooltip、二次校验、进度百分比)、六模块完整、响应式断点正确、单文件可运行(43 个 DOM id 全部存在)。8 项 P2 为可选优化(如 badge 对比度微调、mono 字体栈差异),不阻断交付。

## 用户后续建议

1. 双击打开 `backup-page-redesign.html` 预览效果(Chrome/Edge)
2. 浏览 `CHANGES.md` 了解 25 项具体调整明细
3. 若要在真实前端落地:按效果图令牌替换 `BackupView.vue` 及 `bk-*` 子组件的样式类,业务逻辑(`backupApi` 调用、`useBackupTask` 轮询、记录分页)保持不动
4. 落地后可让 QA 对照本效果图做一次现网视觉回归
