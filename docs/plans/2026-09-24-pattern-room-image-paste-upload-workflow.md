---
intent: 在 /pattern-room「编辑打样项目」弹窗补齐与 /product 页面一致的产品图片粘贴上传交互，并补齐处理中与成功/失败反馈。
success_criteria: 弹窗内 Ctrl+V 可粘贴图片 → 压缩后立即预览 → 保存后后台完成服务端上传；校验失败与上传失败有 toast、上传成功有 toast；/product 页面行为零变化且既有测试全绿。
risk_level: low
auto_approve: true
branch: main
worktree: false
dirty_worktree: allow
---

# 打样项目产品图片「粘贴上传」执行流程

关联设计：[docs/designs/2026-09-24-pattern-room-image-paste-upload-design.md](../designs/2026-09-24-pattern-room-image-paste-upload-design.md)

统一约定（各步骤共用，勿再各写一套）：

- 共享粘贴监听模块路径：`frontend-vite/src/composables/useImagePaste.ts`
- 弹窗图片区块容器类名：`pjf-image-zone`（ProjectFormDialog 的粘贴热区）
- DialogImageUpload 新增 props：`pasteFlash?: boolean`、`uploading?: boolean`
- `useFormImageUpload` 新增返回值：`processing: Ref<boolean>`
- 所有 shell 命令都在 `d:\erp_system\frontend-vite` 下执行

## Steps

- [x] **Step 1: 记录回归基线**
action: 在 d:\erp_system\frontend-vite 运行既有图片上传相关测试，确认两文件全部通过并记录用例数与耗时，作为后续回归基线。若基线已红，停止执行并上报失败用例，不要继续。
loop: false
verify: cd d:\erp_system\frontend-vite; npx vitest run src/test/useImagePaste.test.ts src/test/productImageUpload.test.ts

- [x] **Step 2: 把粘贴监听提升为共享 composable**
action: 用 git mv 将 frontend-vite/src/views/product/composables/useImagePaste.ts 移动到 frontend-vite/src/composables/useImagePaste.ts，文件正文与注释保持零改动（只改路径，不改逻辑）。随后把以下三处 import 从 '../composables/useImagePaste' 或 '../views/product/composables/useImagePaste' 改为 '@/composables/useImagePaste'：frontend-vite/src/views/product/components/ProductBasicForm.vue、frontend-vite/src/views/product/components/ProductEditDialog.vue、frontend-vite/src/test/useImagePaste.test.ts。同时确认 frontend-vite/src/views/product/composables/ 目录下已不存在 useImagePaste.ts。
loop: false
verify: cd d:\erp_system\frontend-vite; npx vitest run src/test/useImagePaste.test.ts src/test/productImageUpload.test.ts

- [x] **Step 3: 迁移后的类型与静态检查**
action: 确认迁移未留下悬空 import 或类型错误。若 vue-tsc 或 eslint 报错，仅修正与本次迁移相关的报错，不顺手改动无关代码。
loop: false
verify:
  - type: shell
    command: cd d:\erp_system\frontend-vite; npx vue-tsc --noEmit
  - type: shell
    command: cd d:\erp_system\frontend-vite; npx eslint src/composables/useImagePaste.ts src/views/product/components/ProductBasicForm.vue src/views/product/components/ProductEditDialog.vue src/test/useImagePaste.test.ts

- [x] **Step 4: 写失败测试 —— 表单图片上传的校验反馈与处理中状态**
action: 新建 frontend-vite/src/test/patternRoomFormImageUpload.test.ts。用 vi.mock('@/composables/useToast') 注入 showToast，并在 beforeAll 中把 URL.createObjectURL 与 URL.revokeObjectURL 替换为 vi.fn（jsdom 不实现这两个 API）。从 '../views/pattern-room/composables/useFormImageUpload' 导入 useFormImageUpload，用例覆盖：
  a) 传入 type 为 text/plain 的文件时 showToast 以 ('error') 被调用、onUpload 未被调用、previewUrl 保持 null；
  b) 传入 10MB 上限之外的 image/png（用 Object.defineProperty 伪造 size，避免真实分配内存）时同上；
  c) 传入合规 image/png 时 onUpload 收到 File 实例、previewUrl 变为非空；
  d) 合规文件处理过程中 processing 为 true，处理完成后回到 false；
  e) removeImage 调用 onRemove 且 previewUrl 置为 null。
注意：jsdom 无 createImageBitmap，现有 compressImageFile 会捕获异常并回退原文件，因此用例 c/d 无需 stub createImageBitmap，但需 await 一个宏任务（如 await vi.waitFor 或多次 await Promise.resolve）再断言。
此处应因实现缺失（无 processing、无校验 toast）而失败，保留失败输出作为 RED 证据。
loop: false
verify: cd d:\erp_system\frontend-vite; npx vitest run src/test/patternRoomFormImageUpload.test.ts

- [x] **Step 5: 实现 useFormImageUpload 的校验反馈与处理中状态**
action: 修改 frontend-vite/src/views/pattern-room/composables/useFormImageUpload.ts：
  1) 引入 showToast；
  2) applyImageFile 中类型不在 ['image/jpeg','image/png','image/webp'] 时改为 showToast('仅支持 JPEG/PNG/WebP 格式', 'error') 后 return；
  3) 大小超过 10MB 时改为 showToast('文件大小不能超过 10MB', 'error') 后 return；
  4) 新增 processing ref，applyImageFile 起始置 true，在 onUpload 调用完成后（finally）置 false；
  5) 返回值增加 processing，其余导出与既有调用方保持不变。
不要改动 compressImageFile 的压缩参数与既有文件名处理逻辑。
loop: until Step 4 测试全部通过
max_iterations: 3
verify: cd d:\erp_system\frontend-vite; npx vitest run src/test/patternRoomFormImageUpload.test.ts

- [x] **Step 6: 写失败测试 —— 弹窗粘贴接线（含已有图片场景）**
action: 新建 frontend-vite/src/test/patternRoomProjectImagePaste.test.ts。挂载 ProjectFormDialog（import '../views/pattern-room/components/ProjectFormDialog.vue'），props 为：visible=true、patternMakers=[]、patternMakerId=null、submitting=false、project 为带 product_image_url 与 version 的详情对象（用 as 断言 ProjectDetailResponse，只填测试所需字段）；mount 时 attachTo document.body，并在 afterEach 中 unmount。粘贴事件构造方式复用 src/test/useImagePaste.test.ts 中 pasteEvent 的写法（new Event('paste') + 覆写 clipboardData）。用例：
  a) 已有图片（project 非 null）：document.querySelector('.pjf-image-zone') 存在，mock 其 getBoundingClientRect 返回非零矩形（宽 400 高 40），dispatch 带 image/png 的 paste 事件，await flushPromises，断言 wrapper.emitted('upload-image') 存在且首个参数为 File——这条用例专门锁定「已有图片时热区仍存在」的设计决策 D7；
  b) 新增态（project=null）同 a) 断言；
  c) 复制纯文本（clipboardData 无文件项）时 upload-image 不触发。
此时因热区 ref 与 useImagePaste 接线尚未实现而失败，保留失败输出作为 RED 证据。
loop: false
verify: cd d:\erp_system\frontend-vite; npx vitest run src/test/patternRoomProjectImagePaste.test.ts

- [x] **Step 7: DialogImageUpload 的命中闪现与上传中态（测试先行）**
action: 先新建 frontend-vite/src/test/patternRoomDialogImageUpload.test.ts 写下失败用例，再改组件令其转绿。
  测试用例（均断言模板渲染结果，FontAwesomeIcon 已由全局 stubs 处理）：
  a) 传 uploading=true、previewUrl='/a.png' 时，渲染结果包含文案「上传中」；
  b) 传 previewUrl=null 时，空状态文案同时包含「粘贴」与「拖拽」；
  c) 传 pasteFlash=true、previewUrl=null 时，根元素 class 列表与 pasteFlash=false 时不同（高亮类生效）。
  组件实现（frontend-vite/src/views/pattern-room/components/DialogImageUpload.vue）：
  1) props 增加 pasteFlash?: boolean 与 uploading?: boolean；
  2) 外层 .diu-section 的高亮类在 isDragOver 或 pasteFlash 为真时生效，颜色变量沿用现有 .diu-upload-area--dragover 使用的同一套变量，避免引入新色值；
  3) 当 uploading 为真时，在预览分支与上传区分支之外追加一条居中状态条（流内追加，避免在 DialogContent 内使用绝对定位被裁切），含上传图标与文案「上传中…」，并让点击与拖拽在本状态下手动 return 不生效、预览分支的「移除图片」按钮同时禁用；
  4) 空状态文案由「点击或拖拽图片到此处上传」改为「点击 / 拖拽 / 粘贴图片到此处上传」；
  5) 保持 v-if/v-else 的预览/虚线框分支结构不变——粘贴热区由外层容器承担，本组件不自行监听 paste。
  不要改动现有的压缩提示文案与 max-width/max-height 预览尺寸。
loop: until Step 7 测试全部通过
max_iterations: 3
verify: cd d:\erp_system\frontend-vite; npx vitest run src/test/patternRoomDialogImageUpload.test.ts

- [x] **Step 8: 实现 ProjectFormDialog 的粘贴接线**
action: 修改 frontend-vite/src/views/pattern-room/components/ProjectFormDialog.vue：
  1) 在「产品图片」字段外层 div 上加 ref="imageZoneRef" 并追加类名 pjf-image-zone（该类名是 Step 6 测试的选择器契约，不可改名）；
  2) 从 '@/composables/useImagePaste' 引入 useImagePaste，target 为该 ref，priority 为 10，enabled 为「弹窗可见且非 submitting」；
  3) onFile 中先触发 600ms 的 pasteFlash 闪现（复用现有 drag 高亮的视觉反馈语义），再调用已有的 applyImageFile(file)；
  4) 把 pasteFlash 与 useFormImageUpload 返回的 processing 作为 props 传给 DialogImageUpload；
  5) 在 onBeforeUnmount 中清理闪现定时器。
不得改动 DialogImageUpload 现有事件签名、也不得改动本组件已有的提交逻辑与三态图片清除逻辑（imageRemoved）。
loop: until Step 6 测试全部通过
max_iterations: 3
verify: cd d:\erp_system\frontend-vite; npx vitest run src/test/patternRoomProjectImagePaste.test.ts

- [x] **Step 9: 写失败测试 —— 背景上传的成功/失败 toast**
action: 新建 frontend-vite/src/test/patternRoomImageUploadFeedback.test.ts。vi.mock('@/api/patternRoom') 注入 patternRoomApi.uploadProjectImage 为可控 mock，vi.mock('@/composables/useToast') 注入 showToast，并用最小桩对象调用 usePatternRoomProjectActions（canManage=ref(true)、confirmDialog 桩、groupHook: { loadGrouped: vi.fn(async () => {}) , currentPage: ref(1) }、projectHook: { currentProject: ref({ id: 7 }), create/update/fetchDetail/remove 桩 }、selectedProjectId=ref(7)、searchKeyword=ref('')、statusFilter=ref('in_progress')、isNarrow=ref(false)、drawerOpen=ref(false)、formPatternMakerId=ref(null)、onSelectProject=vi.fn()）。用例：
  a) 令 uploadProjectImage 解析为 { success: true, url: '/static/uploads/a.png' }，调用 onProjectSubmitUpdate，await 微任务，断言 showToast 以 '图片上传成功' 且类型 'success' 被调用；
  b) 令 uploadProjectImage 拒绝，断言 showToast 以 '图片上传失败，请重试' 且类型 'error' 被调用。
注意 onProjectSubmitUpdate 会先 await projectHook.update，桩需返回真值；pendingProjectImage 需先经 onProjectUploadImage 注入一个 File。此时应因 toast 尚未实现而失败，保留失败输出作为 RED 证据。
loop: false
verify: cd d:\erp_system\frontend-vite; npx vitest run src/test/patternRoomImageUploadFeedback.test.ts

- [x] **Step 10: 实现背景上传的成功/失败 toast**
action: 修改 frontend-vite/src/views/pattern-room/composables/usePatternRoomProjectActions.ts 的 uploadPendingImage：成功分支在既有本地打补丁逻辑之后追加 showToast('图片上传成功', 'success')；失败分支保留既有 console.error 并追加 showToast('图片上传失败，请重试', 'error')。引入 showToast 时沿用仓库既有 '@/composables/useToast' 路径。不要调整既有调用顺序、不要改动 onProjectSubmitCreate/onProjectSubmitUpdate 的流程。
loop: until Step 9 测试全部通过
max_iterations: 3
verify: cd d:\erp_system\frontend-vite; npx vitest run src/test/patternRoomImageUploadFeedback.test.ts

- [x] **Step 11: 全量前端回归**
action: 运行前端全量测试、类型检查与增量 lint，确认本次改动未波及其它模块。若出现与本次改动无关的既有失败用例，记录用例名并在报告中标注为「既有失败」，不要顺手修改。
loop: false
verify:
  - type: shell
    command: cd d:\erp_system\frontend-vite; npx vitest run
  - type: shell
    command: cd d:\erp_system\frontend-vite; npx vue-tsc --noEmit
  - type: shell
    command: cd d:\erp_system\frontend-vite; npx eslint src/views/pattern-room src/views/product src/composables src/test

- [ ] **Step 12: 浏览器人工验收**
action: 打开 http://192.168.0.95:3000/pattern-room ，登录后进入打样项目列表，依次执行设计文档中的 S1–S7：
  S1 编辑已有图片的项目 → 截图后 Ctrl+V → 出现新的本地预览并替换旧图；
  S2 新增打样项目 → Ctrl+V → 出现预览；
  S3 焦点落在弹窗内「产品名称」输入框时 Ctrl+V 图片 → 图片仍进入图片区；
  S4 复制文字 Ctrl+V → 不影响文本输入、不触发上传；
  S5 粘贴非白名单类型或 >10MB 文件 → 出现错误 toast 且无预览；
  S6 保存后观察 → 成功出现「图片上传成功」toast 且卡片缩略图更新；可用断网或改接口模拟失败，确认出现「图片上传失败，请重试」；
  S7 打开不含图片区的弹窗（部位/角色/打印）后 Ctrl+V → 无任何上传动作。
若页面空状态文案中不含「粘贴」二字，说明 3000 端口服务的是构建产物而非 dev 源码，先在 d:\erp_system\frontend-vite 执行 npm run build:fast 再刷新验证。
逐条记录实际观察结果（含 pass/fail 与截图或文字证据），任何一条不通过即回到对应实现步骤修复后重跑本步骤。
loop: false
gate: human
verify:
  type: browser
  url: http://192.168.0.95:3000/pattern-room
  check: S1–S7 全部符合设计文档验证契约中的预期行为
