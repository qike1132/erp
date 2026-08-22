# DESIGN.md · 滨发 ERP 数据备份中心

> 设计系统专家产出 | 供 prototype-builder 直接消费
> 目标:独立可运行 HTML 原型(内联 CSS),呈现完整备份管理 UI
> 基线:融合 71 套品牌系统之 **Stripe(企业级可信结构)+ Linear(操作/进度反馈)+ 既有 ERP 品牌蓝**,并衔接现有浅色企业管理后台视觉语言(Ant Design Pro / Arco 体系)

---

## 0. 设计系统推荐与选定

### 候选方案对比表

| 方案 | 设计系统 | 匹配度 | 特征 | 适合原因 |
|------|---------|--------|------|---------|
| A | **Stripe**(金融科技) | ★★★★★ | 浅色企业级 SaaS 后台黄金标准:精良表格/表单/卡片、可信、数据密度恰到好处 | 「企业数据管理后台 + 管理员桌面办公」最贴合;Stripe 的结构化组件规范可直接映射备份中心六大模块 |
| B | **Linear**(开发工具) | ★★★★☆ | 操作/任务/进度型界面极致典范:状态色清晰、8px 栅格、克制精致、实时进度与启停反馈天然契合 | 备份任务/进度条/启停/二次确认等交互语义与 Linear 高度同构 |
| C | **Vercel**(开发工具) | ★★★☆☆ | 极简 monochrome + 高对比语义色,dev-first 现代工具感 | 风格偏开发者工具、主色近黑,对企业后台的「信任感」支撑较弱 |

**选定:方案 A Stripe 结构 + 方案 B Linear 操作反馈,品牌色沿用既有 ERP 蓝(#2F7BFF)** —— 理由:
1. 场景是**企业 ERP 管理后台**,不是开发者工具站,需要的是可信、清晰的「数据面板」而非极客感;
2. 备份中心本质是**任务操作台**(启停/进度/二次确认),Linear 的反馈语言直接复用;
3. 现有系统已是浅色企业管理后台(Ant Design Blue 品牌蓝),保留品牌色保证页面与现有 ERP 无缝衔接,避免割裂。

---

## 1. Visual Theme(视觉主题)

- **Philosophy**:让管理员一眼看清「当前备份是否安全」,高危操作前绝不手滑。
- **Direction**:Modern Minimal + Tech Utility(浅色主调、数据密度适中、状态语义强)
- **Personality**:可信、精确、克制、警觉
- **Reference**:Stripe Dashboard 的结构秩序 + Linear 的状态反馈 + Ant Design Pro 的企业后台骨架

**三大视觉原则**
1. **状态即信息**:成功绿 / 进行中靛蓝 / 增量琥珀 / 还原红,四种状态色承担全部语义,绝不用于装饰;
2. **危险与常规分域**:还原/删除类操作一律走红色危险域(红底弹层 + 二次校验),常规操作走蓝色主域,视觉上物理隔离;
3. **数据用等宽**:路径、时间戳、大小、进度百分比用 mono 字体,让数据「可对齐、可扫描」。

---

## 2. Color Palette(色彩令牌)

### 主色 · 品牌蓝(企业蓝,衔接既有 ERP)
| Token | HEX | 用途 |
|-------|-----|------|
| `--color-primary` | `#2F7BFF` | 主操作按钮、链接、选中、焦点 |
| `--color-primary-hover` | `#1F66E6` | 按钮 hover(实底按暗一档) |
| `--color-primary-active` | `#1853BF` | 按钮按下/active |
| `--color-primary-soft` | `#E6F0FF` | 选中态底、图标底、浅色主按钮底 |
| `--color-primary-border` | `#9DBEFF` | 主色描边按钮、焦点边框 |

### 中性色阶(Arco 灰阶,浅色)
| Token | HEX | 用途 |
|-------|-----|------|
| `--color-bg-page` | `#F5F7FA` | 页面底色 |
| `--color-surface` | `#FFFFFF` | 卡片/面板/表格底 |
| `--color-surface-hover` | `#F7F8FA` | 卡片/行 hover |
| `--color-surface-muted` | `#F2F3F5` | 进度条轨道、禁用底、骨架屏 |
| `--color-border` | `#E5E6EB` | 常规分隔线、卡片描边 |
| `--color-border-strong` | `#C9CDD4` | 输入框、需强调边框 |
| `--color-text-primary` | `#1D2129` | 标题、关键数值 |
| `--color-text-secondary` | `#4E5969` | 正文、表格内容 |
| `--color-text-tertiary` | `#86909C` | 标签、时间戳、占位 |
| `--color-text-disabled` | `#C9CDD4` | 禁用态文字/图标 |

### 语义色(遵循中国习惯:危险红、成功绿)
| Token | HEX | 用途 |
|-------|-----|------|
| `--color-success` | `#10B981` | 备份完成、健康度正常、一致性通过 |
| `--color-success-soft` | `#E6FAF1` | 成功标签底 |
| `--color-success-border` | `#A7F3D0` | 成功标签描边 |
| `--color-processing` | `#6366F1` | 备份/还原进行中(进度条填充) |
| `--color-processing-soft` | `#E9EAFE` | 进行中标签底 |
| `--color-warning` | `#F59E0B` | 增量变更、有差异、待确认 |
| `--color-warning-soft` | `#FEF6E6` | 警告标签底 |
| `--color-warning-strong` | `#B45309` | 琥珀底上的文字(保证对比度) |
| `--color-danger` | `#EF4444` | 还原操作、备份失败、一致性校验失败 |
| `--color-danger-hover` | `#DC2626` | 危险按钮 hover |
| `--color-danger-soft` | `#FFECE8` | 危险标签底、危险弹层顶栏 |
| `--color-danger-border` | `#FECACA` | 危险描边 |

> 状态语义映射(备份场景):**成功=备份完成/健康**、**进行中=任务执行**、**警告=增量变更/差异**、**危险=还原/失败**。四种状态只表达状态,互不混用。

---

## 3. Typography(排版令牌)

### 字体栈(中先英后,与现有 ERP 一致)
```css
--font-sans: "PingFang SC", "Microsoft YaHei UI", -apple-system, BlinkMacSystemFont,
             "Segoe UI", "Helvetica Neue", Arial, sans-serif;
--font-mono: "JetBrains Mono", "Cascadia Mono", Consolas, Menlo, monospace; /* 路径/时间/大小/百分比 */
--font-num:  "DIN Pro", "Inter", "Helvetica Neue", "PingFang SC", sans-serif; /* 大数字 */
```

### 字号阶梯(14px 正文基准,数据密度适中)
| Token | 大小/行高/字重 | 用途 |
|-------|---------------|------|
| `--fs-display` | 28px / 36px / 600 | 页面标题「数据备份中心」 |
| `--fs-h1` | 22px / 30px / 600 | 区块标题(概览/任务/记录) |
| `--fs-h2` | 18px / 26px / 600 | 卡片标题 |
| `--fs-h3` | 16px / 24px / 600 | 分组/步骤标题 |
| `--fs-body-lg` | 15px / 24px / 400 | 大正文、按钮 |
| `--fs-body` | 14px / 22px / 400 | 正文、表格内容 |
| `--fs-small` | 13px / 20px / 400 | 辅助说明、描述 |
| `--fs-caption` | 12px / 18px / 500 | 表头、标签、徽章 |
| `--fs-micro` | 11px / 16px / 500 | 次要标签、时间戳 |
| `--fs-stat-lg` | 28px / 1.2 / 700 | 健康度等大数字(用 font-num) |
| `--fs-stat` | 20px / 1.3 / 600 | 空间占用等数值(用 font-num) |

字重:`--fw-regular:400` `--fw-medium:500` `--fw-semibold:600` `--fw-bold:700`(仅大数字用 700)

---

## 4. Spacing & Radius(间距与圆角)

### 间距刻度(8px 栅格 + 4px 半档)
| Token | 值 | 用途 |
|-------|-----|------|
| `--spacing-1` | 4px | 图标与文字、徽章内边 |
| `--spacing-2` | 8px | 紧凑元素间隙 |
| `--spacing-3` | 12px | 标签内边、控件间 |
| `--spacing-4` | 16px | 默认间距、卡片内边 |
| `--spacing-5` | 20px | 卡片内边(宽松)、区块间距 |
| `--spacing-6` | 24px | 页面 section 间距 |
| `--spacing-8` | 32px | 大区块分隔 |
| `--spacing-10` | 40px | 页面顶部/底部留白 |
| `--spacing-12` | 48px | 弹层内边、超大分隔 |

### 圆角刻度(克制档位)
| Token | 值 | 用途 |
|-------|-----|------|
| `--radius-xs` | 4px | 标签、小徽章 |
| `--radius-sm` | 6px | 输入框、小按钮 |
| `--radius-md` | 8px | 按钮、卡片、表格容器 |
| `--radius-lg` | 12px | 大卡片、弹层 |
| `--radius-pill` | 999px | 胶囊标签、进度条 |

---

## 5. Depth & Elevation(阴影与边框)

| Token | 值 | 用途 |
|-------|-----|------|
| `--shadow-xs` | `0 1px 2px rgba(0,0,0,.04)` | 默认卡片(配合 1px 边框) |
| `--shadow-sm` | `0 2px 8px rgba(0,0,0,.06)` | 卡片 hover、下拉 |
| `--shadow-md` | `0 6px 20px rgba(0,0,0,.10)` | 弹层、步骤条浮层 |
| `--shadow-lg` | `0 16px 40px rgba(0,0,0,.14)` | 还原确认模态 |
| `--shadow-focus` | `0 0 0 3px rgba(47,123,255,.25)` | 输入框/按钮焦点环 |
| `--shadow-danger` | `0 0 0 3px rgba(239,68,68,.25)` | 危险按钮/危险输入焦点环 |

边框令牌:`--border` / `--border-strong` / `--border-focus`(主色) 见色彩表。Z-index:下拉 100 / 吸顶 200 / 弹层 300 / 模态 400 / 提示 500。

---

## 6. Component Styles(核心组件规范)

### 6.1 状态卡片(Status Card)· 概览四卡
- 容器:白底 `--color-surface`、1px `--color-border`、`--radius-md`、内边 `16px 20px`、`--shadow-xs`;hover 时 `--shadow-sm` + 边框加深
- 结构(左到右):状态圆点(8px,语义色)→ 标签(`--fs-caption` 500, `--color-text-tertiary`)→ 大数值(`--fs-stat` 或 `--fs-stat-lg`,font-num, `--color-text-primary`)→ 辅助说明(`--fs-small`, secondary)
- 典型四卡:上次备份(成功/失败)、下次备份(时间 + 距今天数)、空间占用(数值 + 进度条)、健康度(`--fs-stat-lg` 百分比 + 色块)
- 状态圆点语义:绿=正常完成、靛蓝=进行中、琥珀=有差异、红=失败/异常

### 6.2 主操作按钮(全量/增量)
| 属性 | 全量备份(主操作) | 增量备份(次操作) |
|------|-----------------|-----------------|
| 视觉 | 实底主色 `--color-primary` + 白字 + 图标 | 白底 + 1px `--color-border-strong` + 主色文字 + 图标 |
| 尺寸 | 高 40px,`padding: 0 24px`,`--radius-md`,字 `--fs-body-lg` medium | 同左 |
| hover | 底 `--color-primary-hover` | 底 `--color-primary-soft` |
| active | 底 `--color-primary-active` | 底 `--color-primary-border`(浅) |
| 焦点 | `--shadow-focus` | `--shadow-focus` |
| 图标 | 蓝色系(Save/Refresh) | 琥珀色系(Delta/+),示意「增量」 |

- 常规尺寸按钮:高 32px,`padding: 0 16px`,`--radius-sm`,`--fs-body`
- **互斥禁用态**:全量/增量任务执行中,其余备份按钮 `disabled` → 底 `--color-surface-muted`、字 `--color-text-disabled`、无阴影、`cursor: not-allowed`,并在 tooltip 提示「有任务执行中」
- 危险按钮(还原):红实底 `--color-danger` + 白字,圆角/尺寸同主按钮,hover `--color-danger-hover`、焦点 `--shadow-danger`

### 6.3 进度条(Progress,含百分比)
- 轨道:高 8px、`--radius-pill`、`--color-surface-muted`
- 填充:按状态着色 —— 备份进行中 `--color-processing`;还原进行中 `--color-danger`(红色进度=高危域);完成 `--color-success`;异常 `--color-danger`
- 百分比:右侧 `--fs-body` 500,`--font-mono`,`--color-text-secondary`;**必须始终显示百分比文本**(不单靠颜色)
- 任务行内小进度:高 6px,同上语义

### 6.4 危险操作弹层(Danger Dialog)· 还原确认
- 模态:320px 内边、`--radius-lg`、`--shadow-lg`、遮罩 `rgba(0,0,0,.32)`
- 顶部:32px 红色警示条(`--color-danger-soft`)+ 危险图标(`--color-danger`)
- 标题:`--fs-h1` 600 `--color-text-primary`;副文案 `--fs-body` secondary
- 警示清单:红色圆点 + 红字(`--color-danger`)逐条列出还原影响(「将覆盖当前数据」「执行期间系统停止写入」)
- 确认区:左「取消」(白底描边)、右「确认还原」(`--color-danger` 实底,焦点 `--shadow-danger`)
- **二次校验(必做)**:确认按钮默认禁用,需在输入框输入「确认还原」四字(或勾选 2 项风险确认)后激活 —— 防手滑的物理屏障
- 关闭:遮罩点击 / Esc 不关闭(强制走取消按钮),避免误触

### 6.5 表单控件(路径设置 / 任务配置)
- 输入框:高 32px、`padding: 0 12px`、`--radius-sm`、边框 `--color-border-strong`、底白
- hover:边框 `--color-border`(深)、聚焦:`--border-focus` + `--shadow-focus`
- 占位符:`--color-text-tertiary`;前缀/后缀(如单位 GB):`--color-text-secondary`
- 错误态:边框 `--color-danger` + `--shadow-danger`,下方错误文案 `--fs-caption` 红
- 校验反馈:自定义路径实时校验 —— 通过显示绿色对勾 + 绿字「路径可写」,不合法显示红色叉 + 红字原因
- 选择器(周期/时间):与输入框同高同圆角,右缘下拉箭头;禁用项灰底

### 6.6 数据表格(备份记录)
- 容器:白底、1px `--color-border`、`--radius-md`,表头行底 `--color-surface-hover` 或透明
- 表头:`--fs-caption` 500 `--color-text-tertiary`,左对齐,上下 padding 12px
- 内容行:高 44px、`--fs-body` secondary;行 hover `--color-surface-hover`
- 分隔线:`1px solid #F2F3F5`(行间细线),列间不设竖线
- 状态列:胶囊徽章(底语义 soft、字语义色、`--radius-pill`、padding 2px 10px)
- 操作列:右对齐,文字链接(主色/危险色)+ 图标按钮,危险操作(还原)用红色链接
- 筛选/分页:筛选条在表上方(`--fs-small`),分页右对齐

### 6.7 步骤条(还原向导)
- 结构:圆点 24px(白底 + 语义描边)+ 连接线(高 2px)+ 步骤标题(`--fs-body` medium)
- 状态:已完成 = 绿底白勾;当前 = 主色描边 + 主色标题(圆点内主色实心);待办 = 灰描边灰字;危险步骤(如「一致性校验失败」)= 红描边红字
- 执行中步骤:圆点内转圈 loading(processing 色)
- 步骤说明:`--fs-small` secondary,置于标题下方

---

## 7. Layout(布局规则)

### 页面栅格
- 容器:`max-width: 1440px`,`margin: 0 auto`,页面内边 `24px`
- 栅格:12 列,gutter 16px;概览区独立一行,操作区一行,配置区两栏(任务 + 路径)
- 顶部条:页面标题 `--fs-display` + 副标题(当前系统/上次同步时间,`--fs-small` secondary)

### 卡片网格
| 断点 | 概览卡片列数 |
|------|-------------|
| ≥1280px | 4 列(1fr × 4) |
| 768–1279px | 2 列(1fr × 2) |
| <768px | 1 列堆叠 |

- 卡片间距:gutter 16px、行距 16px;区块间 `--spacing-6`(24px)

### 空态 / 加载态
- **空态**:居中 64px 图标(灰)+ 标题(`--fs-h2`)+ 说明(`--fs-body` secondary)+ 主操作按钮;图标用 `--color-border-strong` 描边风格
- **加载态**:骨架屏 —— `--color-surface-muted` 圆角块 + 透明度脉冲动画(0.6s 呼吸);状态卡/表格首次加载用骨架,二次刷新用行内 loading

---

## 8. Responsive Behavior(响应式)

| 断点 | 行为 |
|------|------|
| <768px | 卡片单列;操作按钮全宽(block);表格横向滚动(容器 overflow-x);步骤条转纵向 |
| 768–1024px | 概览 2 列;操作区与配置区纵向堆叠;任务卡片内联控件换行 |
| >1024px | 完整桌面布局 |

适配规则:还原向导弹层在窄屏下 `max-width: calc(100vw - 32px)`,进度条百分比不换行(mono 不折行)。

---

## 9. Cautions(设计禁区)

### Never Do
1. **还原按钮禁用绿色/蓝色主域**:还原、删除、覆盖类高危操作一律红色危险域,禁止与「备份成功」绿色混淆;
2. **跳过二次确认**:还原操作必须弹层 + 输入校验,单次点击即执行 = 严重事故;
3. **状态色当装饰**:绿/红/琥珀/靛蓝只用于表达状态,禁止用作按钮渐变、页面点缀、品牌强调;
4. **只靠颜色表达进度/状态**:进度必须带百分比文本,状态必须带文字(色盲可读);
5. **互斥任务不设防**:全量/增量运行中其余任务按钮必须禁用,并给出原因 tooltip;
6. **引入霓虹/渐变**:保持浅色克制,禁用彩虹渐变、重投影、暗色混搭;
7. **低对比度文本**:正文(14px)对比 ≥ 4.5:1;琥珀底上文字必须用 `--color-warning-strong`(#B45309)而非默认琥珀。

### Prefer
- 危险操作前:红色警示条 + 明确影响清单 + 输入确认,三重屏障;
- 任务进行中:行内显示进度条 + 剩余时间 + 取消入口(仅备份可取消,还原不可中途取消须置灰取消钮);
- 数据展示:路径/时间/大小用 mono 字体,便于对齐扫描。

---

## 10. Agent Prompt Guide(生成指南)

### Key Instructions
- 全部令牌用 CSS 变量,`<style>` 内联在原型 `<head>`,变量定义于 `:root`;
- 状态四色语义固定:绿=完成/健康、靛蓝=进行中、琥珀=增量/差异、红=还原/失败,全程不漂移;
- 还原向导是高危叙事主线:从选点→差异预览→一致性校验→执行→报告,每一步都要有明确状态反馈(绿勾/红叉/进度);
- 禁用态互斥:同一时刻至多一个备份任务,执行中其余相关按钮 `disabled` + tooltip;
- 字体中先英后;中文用 PingFang/雅黑,数字与路径用 mono;
- 表格/卡片间距严格走 8px 刻度,不手写零散像素。

### Quick CSS Snippet(核心令牌,可直接内联)

```css
:root{
  /* 主色 */
  --color-primary:#2F7BFF; --color-primary-hover:#1F66E6; --color-primary-active:#1853BF;
  --color-primary-soft:#E6F0FF; --color-primary-border:#9DBEFF;
  /* 中性 */
  --color-bg-page:#F5F7FA; --color-surface:#FFFFFF; --color-surface-hover:#F7F8FA; --color-surface-muted:#F2F3F5;
  --color-border:#E5E6EB; --color-border-strong:#C9CDD4;
  --color-text-primary:#1D2129; --color-text-secondary:#4E5969; --color-text-tertiary:#86909C; --color-text-disabled:#C9CDD4;
  /* 语义 */
  --color-success:#10B981; --color-success-soft:#E6FAF1; --color-success-border:#A7F3D0;
  --color-processing:#6366F1; --color-processing-soft:#E9EAFE;
  --color-warning:#F59E0B; --color-warning-soft:#FEF6E6; --color-warning-strong:#B45309;
  --color-danger:#EF4444; --color-danger-hover:#DC2626; --color-danger-soft:#FFECE8; --color-danger-border:#FECACA;
  /* 字体 */
  --font-sans:"PingFang SC","Microsoft YaHei UI",-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif;
  --font-mono:"JetBrains Mono","Cascadia Mono",Consolas,Menlo,monospace;
  --font-num:"DIN Pro","Inter","Helvetica Neue","PingFang SC",sans-serif;
  /* 字号 */
  --fs-display:28px; --fs-h1:22px; --fs-h2:18px; --fs-h3:16px; --fs-body-lg:15px;
  --fs-body:14px; --fs-small:13px; --fs-caption:12px; --fs-micro:11px; --fs-stat-lg:28px; --fs-stat:20px;
  /* 间距 */
  --spacing-1:4px; --spacing-2:8px; --spacing-3:12px; --spacing-4:16px; --spacing-5:20px;
  --spacing-6:24px; --spacing-8:32px; --spacing-10:40px; --spacing-12:48px;
  /* 圆角 */
  --radius-xs:4px; --radius-sm:6px; --radius-md:8px; --radius-lg:12px; --radius-pill:999px;
  /* 阴影 */
  --shadow-xs:0 1px 2px rgba(0,0,0,.04); --shadow-sm:0 2px 8px rgba(0,0,0,.06);
  --shadow-md:0 6px 20px rgba(0,0,0,.10); --shadow-lg:0 16px 40px rgba(0,0,0,.14);
  --shadow-focus:0 0 0 3px rgba(47,123,255,.25); --shadow-danger:0 0 0 3px rgba(239,68,68,.25);
}
```

---

*设计系统专家 · 彩格调 | Phase 2 产出 | 供 prototype-builder(Phase 3)直接消费*
