# CHANGES.md · 数据备份中心重设计前后对比

> 交付物配套说明 | 与 `backup-page-redesign.html` 同目录
> 对比基线：现网 `frontend-vite/src/views/backup/BackupView.vue` 的视觉实现 / 上一版原型 `docs/ui-redesign/backup-center/backup-center-prototype.html`
> 设计后基准：`frontend-vite/src/styles/app.css`（A 全局体系 "Plush Cute"）+ `docs/ui-redesign/backup-center/DESIGN.md`（B 业务语义，色值映射到 A 色板）

## 一、设计前后对比清单

| # | 调整元素 | 设计前取值 | 设计后取值 | 依据规范 |
|---|---------|-----------|-----------|---------|
| 1 | 页面主背景 | `#F5F7FA` 纯色平铺 | `linear-gradient(135deg, #f4f6fc, #f0f2f5)` 品牌渐变底 | A·页面骨架 |
| 2 | 页面骨架 | 无侧边栏，居中单栏 `max-width:1440px` | 左侧 230px 白卡侧边栏（18px 圆角、蓝调阴影）+ 主内容区 padding 24px | A·页面骨架 |
| 3 | 品牌主色 | `#2F7BFF`（Ant 蓝）及 `#1F66E6/#1853BF` 变体 | primary-500 `#5b8def` / primary-600 `#3a6bd6` / primary-700 `#2d5ab8`；主按钮使用 `--gradient-primary: linear-gradient(135deg,#5b8def,#3a6bd6)` | A·色板 / A·渐变 |
| 4 | 语义色映射 | 成功 `#10B981`、进行中 `#6366F1`、警告 `#F59E0B`、危险 `#EF4444` | 成功 success-500 `#28c76f`、进行中 primary-500 `#5b8def`、警告 warning-500 `#ff9f43`、危险 danger-500 `#ea5455`（状态色只表达状态） | B·状态四色语义 → A·色板 |
| 5 | 圆角体系 | xs 4px / sm 6px / md 8px / lg 12px（克制档） | sm 10px / md 14px / lg 24px / xl 28px / card 24px / modal 28px / button 14px / input 12px / nav-item 14px；`.page-card` 18px | A·圆角（Plush Cute 大圆角） |
| 6 | 阴影 | 黑调 `rgba(0,0,0,.04~.14)` | 蓝调 ocean 系：`rgba(176,224,230,.15~.22)`、`rgba(135,206,235,.28~.32)` | A·阴影（蓝调） |
| 7 | 卡片容器 | `.card`：radius-md 8px、`--shadow-xs` | `.page-card`：白底、18px 圆角、1px border-light、柔和阴影、hover 上浮 translateY(-2px) | A·page-card 组件 |
| 8 | 概览四卡 hover | 阴影微增 + 边框加深 | `card-hover`：上浮 translateY(-2px) scale(1.01) + `0 8px 25px rgba(135,206,235,.35)` | A·card-hover 动效 |
| 9 | 主按钮 | 实底 `#2F7BFF`、radius 8px | 渐变 `--gradient-primary` 实底白字、radius-button 14px、蓝色投影 | A·组件 / A·渐变 |
| 10 | 次按钮（增量） | 白底 + 灰描边 + 主色字 | 白底 + border-light 描边 + primary-600 字，hover 主色描边 + 浅蓝底；增量图标保留琥珀色系 | A·组件 |
| 11 | 输入框 / 下拉 | height 32px、radius 6px、边框 `#C9CDD4` | height 36px、radius-input 12px、边框 `#e4e7ed`、focus 主色环 `0 0 0 3px rgba(91,141,239,.18)` | A·组件（radius-input） |
| 12 | 开关控件 | 36×20、on 态实底主色 | 42×24、on 态 `--gradient-primary` 渐变 + 滑钮投影 | A·组件 |
| 13 | 页面标题 | 28px / 600 / `#1D2129` | h1：1.5rem / 800 / primary-700 `#2d5ab8`，letter-spacing -0.02em | A·排版层级 |
| 14 | 副标题 | 13px / `#86909C` | 0.875rem / 500 / text-secondary `#475569`，前导状态圆点 | A·subtitle / 排版 |
| 15 | 卡片标题 | 18px / 600 | h3 风格：1.0625rem / 700 / slate-700 `#1e293b`；辅助文案 0.75rem text-muted | A·排版层级 |
| 16 | 表格 | 表头左对齐、500 字重、12px、灰底行；内容行左对齐 | `data-table`：表头居中、600、12px、uppercase、letter-spacing .05em、白底、border-bottom 2px border；td 居中、border-bottom 1px border-light | A·data-table 组件 |
| 17 | 表格文件名/时间/大小 | 部分 mono | 路径、文件名、时间戳、大小、百分比一律 mono + tabular-nums（可对齐可扫描） | B·数据等宽规范 |
| 18 | 状态徽章 | 语义 soft 底 + 语义色字（旧色值） | 语义 soft 底 + 语义色字（A 色板值）；类型徽章：全量=neutral、增量=warning；状态徽章：成功/失败/进行中 | A·色板 / B·状态语义 |
| 19 | 互斥禁用 | 按钮 disabled + tooltip「有任务执行中」 | 保留 disabled + tooltip「有任务执行中」；禁用态统一灰底灰字（button 14px 圆角不变） | B·互斥任务不设防 |
| 20 | 进度条 | 进行中靛蓝填充、还原红填充 | 进行中 `--gradient-primary`、完成 `--gradient-success`、还原 `--gradient-danger`；始终右侧 mono 百分比文本 | A·渐变 / B·百分比必显 |
| 21 | 还原入口 | 表内红色链接触发向导 | 独立「还原入口」卡片：主按钮「一键还原向导」渐变主域 + 「从文件上传还原」outline；表内还原保持红色危险链接 | A·页面结构 / B·危险分域 |
| 22 | 危险确认弹层 | 白底 + 顶部红色警示条 + 输入「确认还原」二次校验 | 28px 圆角（radius-modal）+ 顶部 4px danger-500 红边 + 红底警示条 + 红色影响清单 + 输入「确认还原」激活确认钮（默认禁用）；Esc/遮罩不可关闭 | A·radius-modal / B·危险域与二次校验 |
| 23 | 还原向导浮层 | radius 12px、蓝主色步骤条 | radius-modal 28px、xl 蓝调阴影；步骤：完成=success 渐变勾、当前=primary 渐变 + 焦点环、待办=灰；危险步骤确认钮红色危险域 | A·radius-modal / B·危险分域 |
| 24 | 动效 | 无页面级动效 | `animate-fade-in`（区块入场）、`slideUp`（任务卡/弹层）、`animate-spin-slow`（校验 loading） | A·动效体系 |
| 25 | 响应式 | ≥1280 4列 / 768-1279 2列 / <768 1列；两栏配置 <1024 堆叠；表格横向滚动 | 保留同样断点；新增 <1024 侧边栏隐藏、主区占满；<768 操作按钮全宽 | A·布局 / C·响应式需求 |

## 二、未改动项（业务语义保持一致）

- 六大模块结构与字段不变：概览四卡 / 备份操作 / 定时任务配置 / 备份路径设置 / 还原入口 / 备份记录表格
- 任务互斥规则：同一时刻至多一个备份任务，运行中其余按钮禁用 + tooltip
- 还原二次确认规则：必须输入「确认还原」四字才激活确认按钮
- 危险操作红色域：还原类操作一律红色（表内红链接 / 红底弹层），与常规蓝色主域物理隔离
- 纯视觉效果图：不接真实 API、不含后端逻辑、模块划分与交互语义与现状一致

## 三、说明

- 本稿为「视觉层」重设计效果图，可直接双击打开预览（单文件、内联 CSS/JS、无外部依赖）。
- 若要在真实前端落地，建议按本稿令牌替换 `BackupView.vue` 及相关子组件样式类，业务逻辑（`backupApi` 调用、`useBackupTask` 轮询、记录分页等）保持不动。
