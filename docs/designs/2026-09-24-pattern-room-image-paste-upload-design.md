---
design_type: feature
created_at: 2026-09-24
---

# 打样项目产品图片「粘贴上传」设计

## Intent Contract

```
intent: 在 /pattern-room「编辑打样项目」弹窗的产品图片区补齐与 /product 页面一致的剪贴板粘贴上传交互，
        并补齐上传中 / 成功 / 失败的反馈，使两处图片上传体验对齐。
constraints:
  - 不改后端接口与 pattern-room 图片上传契约（仍为保存后 multipart 上传到项目图片接口）
  - 不改动 /product 页面现有行为（仅迁移共享 composable 的 import 路径）
  - 沿用 pattern-room 现有校验白名单（JPEG/PNG/WebP ≤10MB）与服务端上传前的 WebP 压缩
  - 图片区视觉皮肤以现有 DialogImageUpload 为准，不引入 product 的 pd-* 类名体系
success_criteria:
  - 弹窗打开时 Ctrl+V 可粘贴图片 → 压缩后立即本地预览 → 保存后后台完成服务端上传
  - 校验失败与上传失败均有 toast 提示；上传成功有 toast 且卡片缩略图更新
  - /product 页面粘贴行为零变化，既有单测全绿
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run tests: cd frontend-vite && npx vitest run src/test/useImagePaste.test.ts src/test/productImageUpload.test.ts
  - run tests: 新增 pattern-room 图片粘贴用例（useFormImageUpload 校验与暂存、粘贴命中接线）
  - check: npx vue-tsc --noEmit
  - check: npx eslint src/views/pattern-room src/views/product src/composables
  - confirm: 手工验证下列 7 个场景全部符合预期
manual_scenarios:
  S1 编辑已有图片的打样项目 → 截图后 Ctrl+V → 出现新的本地预览并替换旧图
  S2 新增打样项目（无图）→ Ctrl+V → 出现预览
  S3 焦点位于弹窗内「产品名称」输入框时 Ctrl+V 图片 → 图片仍进入图片区（document 级监听）
  S4 复制文字后 Ctrl+V → 不拦截、不影响文本输入
  S5 粘贴非白名单类型或 >10MB 文件 → toast 报错且不产生预览
  S6 保存后模拟上传失败（断网/改接口）→ error toast；正常时 success toast 且卡片缩略图更新
  S7 打开不含图片区的弹窗（部位/BOM/打印）后 Ctrl+V → 无任何上传动作
```

## Governance Contract

```
approval_gates:
  - 设计评审（本文档）—— 通过后才进入实现
  - 实现完成后的代码审查（对照本设计核对范围与验证证据）
rollback: 单次提交 git revert 即可回退；无数据库迁移、无后端改动、无外部状态残留
ownership: 前端（pattern-room / product 图片上传链路负责人）
```

## Scope

| 项 | 范围 | 说明 |
| --- | --- | --- |
| 粘贴交互 | 纳入 | 打样项目弹窗接入 document 级粘贴监听 |
| 粘贴命中反馈 | 纳入 | 复用「拖拽高亮」样式做 600ms 闪现 |
| 处理中 / 上传中 loading | 纳入 | 图片区显示进行中状态 |
| 上传成功 / 失败 toast | 纳入 | 含校验失败反馈（现状为静默丢弃） |
| 共享 composable 提升 | 纳入 | 粘贴监听实现由 product 目录提升到全局 composables |
| 真实百分比进度条 | 不纳入 | 需改造公共请求层 `upload()`，且弹窗关闭后无承载载体 |
| 后端接口 / 契约变更 | 不纳入 | 现有项目图片上传接口满足需求 |
| 校验白名单对齐 product | 不纳入 | 会让现有 WebP 用户出现能力回退 |
| 卡片列表持久化「上传中」骨架 | 不纳入 | 保存后上传属后台行为，避免扩散改动面 |
| 其它弹窗的粘贴支持 | 不纳入 | 部位/角色/打印弹窗无产品图片语义 |

## Decisions

| # | 决策 | 选择 | 放弃的替代方案 |
| --- | --- | --- | --- |
| D1 | 上传链路 | 保持「本地压缩 → blob 预览 → 暂存 File → 保存成功后后台上传」 | 照搬 product 的「粘贴即上传拿 URL」：新增态尚无 projectId，且需改后端图片契约（multipart + file_id → URL 字符串） |
| D2 | 视觉归属 | 交互语义与反馈照搬 product（命中闪现、失败 toast），皮肤沿用 DialogImageUpload 现有虚线框与预览样式 | 整块替换为 product 的 pd-* 皮肤：与「现有图片上传组件保持样式一致」的要求冲突，且会引入双套样式 |
| D3 | 进度实现 | 图片区 loading 态 + 结束 toast（成功/失败） | 真实百分比进度条：需扩展公共 `upload()` 的 onUploadProgress，且上传发生在弹窗关闭之后，无就地展示载体 |
| D4 | 校验白名单 | 沿用 pattern-room 现有规则（JPEG/PNG/WebP，≤10MB，WebP 压缩） | 照搬 product 的 JPG/PNG/GIF ≤5MB 不压缩：WebP 用户粘贴会被拒，属能力回退 |
| D5 | composable 归属 | 粘贴监听实现提升到全局 `src/composables/useImagePaste.ts`，product 与 pattern-room 共用同一份 | 在 pattern-room 内复制一份：两份实现会随迭代漂移 |
| D6 | 校验失败反馈 | 由静默 `return` 改为 toast 提示 | 保持静默：与「上传成功/失败状态反馈」要求冲突 |
| D7 | 粘贴热区 | 取图片区块容器（始终渲染）而非「仅无图时出现的虚线框」 | 沿用产品卡片式热区：编辑已有图片的项目时虚线框被预览替换，元素不存在导致粘贴彻底失效 |

## Surface

**APIs**：无新增、无变更。仍复用现有打样项目图片上传接口（保存成功后以 multipart 提交文件）；与 product 使用的通用文件上传接口无关，两者互不影响。

**Storage**：无持久化结构变更。本地仅新增「待上传文件暂存」与「处理中」两个瞬时状态，沿用现有的待上传文件暂存 ref。

**Components**：
- `DialogImageUpload`：新增粘贴命中闪现类与处理中覆盖层，热区从虚线框上移到外层区块容器，提示文案补充「粘贴」二字。
- `ProjectFormDialog`：注册粘贴监听（弹窗可见时启用、优先级高于 product 侧表单），把命中闪现与处理中状态透传给 `DialogImageUpload`。
- `useFormImageUpload`：新增处理中状态，校验失败改为 toast 提示，返回值保持向后兼容。
- `usePatternRoomProjectActions`：后台上传增加成功/失败 toast（现状仅 `console.error`）。

**Files touched**：
- 新增：`frontend-vite/src/composables/useImagePaste.ts`
- 删除：`frontend-vite/src/views/product/composables/useImagePaste.ts`
- 改 import 路径：`ProductBasicForm.vue`、`ProductEditDialog.vue`、`src/test/useImagePaste.test.ts`
- 功能改动：`pattern-room/components/ProjectFormDialog.vue`、`pattern-room/components/DialogImageUpload.vue`、`pattern-room/composables/useFormImageUpload.ts`、`pattern-room/composables/usePatternRoomProjectActions.ts`
- 新增测试：pattern-room 图片上传 composable 用例

## Risks & Open Questions

**R1（评审已确认，接受）「上传中 loading」的真实语义。** 保存后上传发生在弹窗关闭之后，弹窗内的 loading 只覆盖「压缩 + 暂存」这一极短阶段；真正的网络上传过程用户只能通过结束时的 toast 感知。评审结论：接受该语义，不引入列表态骨架或全局上传指示——保持改动面最小，真实上传过程以结束 toast 作为可观测反馈。

**R2 document 级监听的副作用。** 弹窗内粘贴图片会 `preventDefault`。若用户希望在备注文本域粘贴图片路径或富文本图片，会被拦截进图片区——该行为与 product 页面同源，属已知一致行为。

**R3 共享 composable 迁移的回归面。** 迁移会触碰 product 两条组件 import 与一条测试 import，需保证 product 既有粘贴与校验单测全绿；迁移不做任何逻辑改动。

**R4 压缩产物与后端白名单的兼容性。** 现状压缩输出 WebP/JPG，后端白名单已接受该组合，本次仅复用既有逻辑，不新增格式风险。

**R5 空状态文案一致性。** 补充「粘贴」后文案需同时覆盖新增与编辑两种模式，避免出现「编辑态可粘贴、新增态无提示」的不一致。

**R6（评审残余，已知限制）「上传中…」文案与真实阶段的偏差。** 该状态由 `processing` 驱动，实际只覆盖「压缩 + 暂存」；真实网络上传在弹窗关闭后发生。评审建议改为「图片处理中…」，但 gate 已按「上传中 loading」批准（见 R1 与选型记录），改动文案会偏离已批准的验收约定，故保留现文案并在此显式记录：文案表达的是「该图片已进入待上传流程」，不是「网络请求进行中」。

**R7（评审残余，已知限制）并发粘贴的瞬时指示。** 快速连续粘贴两张图片时，先完成者的 `finally` 会提前把 `processing` 置回 false，此时后一张可能仍在压缩。核验后确认「预览与待上传文件不一致」的情况不会发生——`previewUrl` 赋值与 `onUpload` 回调处在同一个同步块内，末次完成者同时决定两者。仅剩指示提前消失这一视觉瑕疵，不引入重入令牌（YAGNI，且会扩大改动面）。

**R8（评审残余，已知限制）在途处理期间禁止移除图片。** 处理中禁用「移除图片」按钮，使该窗口内的移除点击无效而非被静默撤销；两者都不完美，选择「可见的禁用态」以符合最小惊讶原则。
