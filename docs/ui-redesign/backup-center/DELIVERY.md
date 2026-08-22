# DELIVERY.md · 数据备份中心原型交付说明

> 导出交付专家「交付达」产出 | Phase 5 导出核验 + 交付说明
> 对应原型:`backup-center-prototype.html`(单文件、内联 CSS+JS,双击即可运行)

---

## 1. 交付物清单

| 文件 | 大小 | 说明 |
|------|------|------|
| `backup-center-prototype.html` | ~62 KB(63,486 B) | 高保真前端原型,单文件自包含,无外部依赖 |
| `DESIGN.md` | ~18 KB | 设计规范(Phase 2 产出:Stripe+Linear+品牌蓝 令牌体系) |
| `DELIVERY.md` | 本文档 | 交付说明、模拟标注、跟进项、落地建议 |

三者同目录,原型直接浏览器打开即可,无需安装、无需启动服务。

---

## 2. 导出核验结论

### ✅ 自包含:通过
- 无 `<link>` 外链(0 个)、无 `<script src>` 外链(0 个)、无 `<img>`(0 个,全部图标为内联 SVG symbol)
- 无 CDN、无 `@import`、无远程字体/图片;select 下拉箭头为 data:URI 内联 SVG
- 字体栈全部为系统字体(PingFang SC / Microsoft YaHei UI / Segoe UI / Arial / Consolas 等),离线可用
- 唯一 `http://` 出现为 SVG 命名空间声明 `xmlns="http://www.w3.org/2000/svg"`,非资源引用

### ✅ 编码与结构:通过
- `<!DOCTYPE html>`、`<meta charset="UTF-8">`、`<meta name="viewport">`、`<html lang="zh-CN">` 齐全
- 标签闭合平衡(meta/input 为空元素,属正常;其余标签 open=close 全部配对)
- `<script>` 块完整 1 个,`new Function()` 编译通过,无语法错误
- JS 引用的 45 个元素 ID 全部在 HTML 中存在,类选择器引用全部存在(无空指针风险)

### ✅ 可独立运行:通过
- 单文件 100% 内联,双击用浏览器打开即可,交互(备份模拟/向导/校验)均由内联 JS 驱动
- 建议 Chrome / Edge 打开;文件 <500 KB 目标,加载即时

---

## 3. 原型覆盖的功能点(对照 6 项需求)

| # | 用户需求 | 原型落点 | 交互表现 |
|---|---------|---------|---------|
| 1 | 一键全量备份 | 模块2「一键全量备份」按钮 | 点击→任务卡出现→进度条/阶段文案/剩余时间→完成置绿 |
| 2 | 增量备份 | 模块2「增量备份」按钮 | 同上,增量场景文案(扫描增量变更→备份增量数据) |
| 3 | 定时备份 | 模块3「定时任务配置」 | 启用开关、周期(每日/每周/每月/自定义 cron)、执行时间、立即触发;保存反馈 |
| 4 | 备份路径配置 | 模块4「备份路径设置」 | 默认/自定义路径切换、实时校验(D:\ 或 C:\ 开头/非法字符/长度)、校验与保存反馈 |
| 5 | 一键还原 + 一致性校验 | 模块6 还原向导 | 选备份点→差异预览→4 项一致性校验(表结构/记录数/哈希/索引)→输入「确认还原」二次确认→执行→结果报告+建议 |
| 6 | 实时进度 | 模块2 任务卡 + 模块6 还原进度 | 进度条+百分比文本+阶段描述+预计剩余;还原为红色高危进度条 |

附加:备份记录表格(类型/状态筛选、关键词搜索、分页、还原/下载入口)、备份概览四卡(上次/下次备份、空间占用、健康度)、任务互斥(同一时刻至多一个备份任务,其余按钮禁用+tooltip)、危险操作三重屏障(红色警示条+影响清单+输入校验)。

---

## 4. 原型中为模拟演示的部分(重要,交付时需明确)

> 本原型为**交互演示原型**,以下均为前端模拟,不代表真实业务行为:

- **数据为模拟**:概览四卡数值、备份记录 5 行、差异预览表/记录数/哈希、健康度、空间占用均为写死示例数据
- **进度为 setInterval 模拟**:备份/还原/一致性校验进度由 `Math.random()` 递增驱动,非真实后端任务;耗时(如 4 分 12 秒)为写死文案
- **分页为占位**:「上一页/下一页」仅弹出 toast 提示,不真实翻页
- **下载为占位**:「下载」按钮仅弹出 toast「开始下载备份文件」,不产生文件
- **还原不真实执行**:还原向导走完 5 步动画流程,不修改任何真实数据库/文件
- **路径校验为前端正则**:仅校验格式(盘符/非法字符/长度),不探测真实文件系统可写性;保存后「可用空间」显示 `—(模拟)`
- **「立即触发一次」** 实际触发的是增量备份的模拟流程

落地到真实系统时,上述全部需替换为真实 API / 任务引擎对接。

---

## 5. 已知跟进项(来自 Phase 4 P2 清单)

> 均为非阻塞项,不影响原型演示,但落地前应处理:

| 优先级 | 事项 | 位置 | 处理建议 |
|--------|------|------|---------|
| P2 | 硬编码 `#F2F3F5` 换令牌 | 5 处 CSS(form-row / path-current / tbody td / suggest / restore-foot 的分隔线) | 替换为 `var(--color-surface-muted)`,保持令牌单一来源 |
| P2 | prefers-reduced-motion 降级 | 动画:spin / fade / toastIn / progress transition | 增加 `@media (prefers-reduced-motion: reduce)` 关闭或放缓动画 |
| P2 | 未用图标清理 | 内联图标库 4 个未用 symbol:`i-download` `i-restore` `i-arrow-left` `i-arrow-right` | 删除或保留为后续扩展,避免无用资源 |
| P2 | a11y 开关 aria-label | `#switchEnable`(role="switch" 已加 aria-checked,缺可读名称) | 补充 `aria-label="启用定时备份"`;搜索框补 `aria-label`;select 与 label 显式关联 |

---

## 6. 后续落地建议(Vue3 + PrimeVue 技术栈映射)

> 原型为纯 HTML/JS,便于演示;正式系统建议迁移到 Vue3 + PrimeVue(现有 ERP 企业后台生态)。

| 原型模块 | Vue3 + PrimeVue 组件映射 | 备注 |
|---------|------------------------|------|
| 概览四卡 | `Card` + 自定义 Stat 组件 | 令牌直接映射到 CSS 变量 / PrimeVue theme |
| 一键备份任务卡 | 任务状态 Store(Pinia)+ `ProgressBar` + `Tag` | 互斥逻辑改由 Pinia `runningTask` 状态驱动 |
| 定时任务配置 | `ToggleSwitch` + `Dropdown` + `InputText` + `Calendar` | cron 解析可引 `cron-parser` 库 |
| 路径设置 | `RadioButton` + `InputText` + 校验 | 真实校验改由后端接口返回 |
| 备份记录表格 | `DataTable`(筛选/分页/搜索)+ `Tag` | 分页/筛选改由服务端查询 |
| 还原向导 | `Steps` + `Dialog` + `ProgressSpinner` | 差异预览/校验结果由 API 返回 |
| 危险确认 | `ConfirmDialog` + `InputText` 二次校验 | 高危操作前置校验沿用原型三重屏障 |
| Toast | `Toast` / `Message` | 统一到 PrimeVue Toast 服务 |

设计令牌(DESIGN.md :root 变量)可直接迁移为 PrimeVue 主题 token(primary=#2F7BFF 等),视觉无缝衔接既有 ERP。

---

*导出交付专家「交付达」| Phase 5 产出 | 待 Phase 6 技术方案确认后进入真实系统开发*
