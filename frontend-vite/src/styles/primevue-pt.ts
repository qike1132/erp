/**
 * PrimeVue Pass Through (PT) 预设
 *
 * 将所有 PrimeVue Unstyled 组件的样式映射到「Plush Cute」设计系统，
 * 与现有 Tailwind CSS v4 设计令牌完全一致。
 *
 * 约定：
 *  - 通用容器：bg-white rounded-[var(--radius-card)] border border-border shadow-sm
 *  - 输入框：bg-slate-50 border-2 border-ocean-light rounded-input focus:...
 *  - 下拉面板：z-[var(--z-dropdown)] bg-white rounded-xl shadow-lg
 *  - 列表项：px-3 py-2 text-[13px] cursor-pointer rounded-md
 */
import type { PrimeVuePTOptions } from 'primevue/config'

export const plushCutePT: PrimeVuePTOptions = {
  // ============================================================
  // AutoComplete
  // ============================================================
  autocomplete: {
    root: 'relative w-full',
    input: ({ props }) => ({
      class: [
        'w-full',
        'py-2.5 px-4',
        'text-sm',
        'bg-white',
        'border-2 border-ocean-light',
        'rounded-[var(--radius-input)]',
        'transition-colors duration-200',
        'focus:border-primary focus:shadow-[0_0_0_0.2rem_rgba(135,206,235,0.25)]',
        'focus:outline-none',
        'placeholder:text-text-muted',
        props.disabled ? 'opacity-50 cursor-not-allowed bg-slate-100' : '',
      ],
      style: { background: '#ffffff' },
    }),
    overlay: 'absolute z-[var(--z-dropdown)]',
    listContainer: 'bg-white border border-border rounded-xl shadow-lg overflow-y-auto max-h-60 mt-1',
    list: 'py-1',
    option: ({ context }: { context: { focused: boolean; selected: boolean } }) => ({
      class: [
        'px-3 py-2 text-[13px] cursor-pointer rounded-md mx-1 transition-colors duration-150',
        context.selected
          ? 'bg-primary-100 text-primary-700'
          : context.focused
            ? 'bg-ocean-light/30 text-text'
            : 'text-text hover:bg-ocean-light/20',
      ],
    }),
    optionGroup: 'px-3 py-1.5 text-[11px] font-semibold text-text-muted uppercase tracking-wider',
    emptyMessage: 'px-3 py-6 text-center text-sm text-text-muted',
    loader: 'absolute top-1/2 right-4 -translate-y-1/2 animate-spin',
    dropdown: {
      class: [
        'border-0 bg-transparent',
        'text-text-muted',
        'cursor-pointer',
        'transition-colors duration-200',
        'hover:text-primary',
      ],
    },
    clearIcon: 'text-text-muted cursor-pointer hover:text-danger transition-colors duration-200',
  },

  // ============================================================
  // Drawer
  // ============================================================
  drawer: {
    // PrimeVue 4.5 的 DOM 形状：mask 是全屏 flex 容器（主题用 inline style 按 position
    // 设 justify/align/z-index），**root 是面板本体**，content 才是内层滚动体。
    // 早期这里按更老的 DOM 写反了：把「全屏容器」类挂在 root、把「面板」类挂在 content。
    // 后果 —— UiDrawer 的 width 落在 root（面板）上，却被 content 的 w-[520px] 盖过，
    // 抽屉实测恒为 520px 宽，header 还被 root 的 flex 行布局甩到屏幕左侧中部。
    mask: 'fixed inset-0 bg-black/30 backdrop-blur-sm transition-opacity duration-300',
    root: ({ props }: { props: { position: string } }) => ({
      class: [
        'relative',
        'flex flex-col',
        'bg-white',
        'shadow-xl',
        'overflow-hidden',
        'animate-slide-up',
        // 居中面板（宽表格明细等）：mask 的 flex 居中会把它摆到屏幕正中。
        // 高度写死而非自适应 —— 行数少时面板会跟着缩水，尺寸忽大忽小很别扭；
        // 固定高度后内容区（content 的 flex-1 overflow-y-auto）自己滚动。
        props.position === 'center'
          ? 'w-[95%] h-[85vh] rounded-2xl'
          : // 左右抽屉：撑满高度，宽度由 UiDrawer 传的 inline width 决定（这里的 520 仅兜底）；
            // 上下抽屉：占满宽度、限高。定位交给 mask 的 justify/align（见上）。
            props.position === 'left' || props.position === 'right'
            ? 'h-full w-[520px] max-w-[95vw]'
            : 'w-full max-h-[80vh]',
      ],
    }),
    // 居中面板（明细）的筛选栏自带内边距，且标题下沿已有边框，内容区若再留 20px 顶部内边距
    // 就会在标题与筛选栏之间空出一条；故居中面板去掉顶部内边距，左右/上下抽屉保持原样。
    content: ({ props }: { props: { position: string } }) => ({
      class: [
        'flex-1 min-h-0 overflow-y-auto px-6 pb-5',
        props.position === 'center' ? 'pt-0' : 'pt-5',
      ],
    }),
    header: 'flex items-center justify-between px-6 py-4 border-b border-border-light flex-shrink-0',
    title: 'text-lg font-bold text-heading',
  },

  // ============================================================
  // DataTable
  // ============================================================
  datatable: {
    root: 'relative',
    header: 'flex items-center justify-between px-0 py-3',
    table: 'w-full border-collapse',
    thead: '',
    tbody: '',
    headerRow: '',
    // 行样式必须挂在 `bodyRow`（`<tr>` 本体）。原先写在 `row` 上 —— 那一段指的是
    // Row 辅助组件（展开行/分组行），对本项目的表格行不生效，行分隔线与 hover
    // 一直是死的（全站 19 个用 UiDataTable 的视图都没有分隔线，2026-09-29 定位）。
    // 行线色 2026-09-30 从 border-border-light(#f0f2f5) 改为 border-border(#e4e7ed)：
    // 前者对白底对比度仅 1.122:1，行与行之间看不出分界（多 SKU 行变高后更明显）；
    // 后者与表头下边线、表格外框同色（1.239:1），全表网格线统一成一个色调。
    bodyRow: ({ context }: { context: { selected: boolean } }) => ({
      class: [
        'border-b border-border transition-colors duration-150',
        context.selected ? 'bg-primary-50' : 'hover:bg-slate-50',
      ],
    }),
    columnResizeIndicator: 'absolute top-0 right-0 w-1 h-full bg-primary cursor-col-resize',
    emptyMessage: 'py-12 text-center text-sm text-text-muted',
  },

  // ============================================================
  // Column（DataTable 单元格：表头/表体样式以列级 PT 为准）
  // ============================================================
  column: {
    headerCell: {
      class: [
        'px-3 py-3',
        'text-xs font-semibold text-text-secondary',
        'uppercase tracking-wider',
        // 中文表头（2~4 字）在窄容器下会被 auto 列宽折成两行（/product「产品价格」「工厂」，
        // 2026-10-09），全站表头一律单行 —— 列宽交给各视图的 width 定义分配。
        'whitespace-nowrap',
        'bg-surface',
        'border-b-2 border-border',
        'text-center',
      ],
    },
    bodyCell: {
      class: 'px-3 py-3 text-sm text-text text-center align-middle',
    },
  },

  // ============================================================
  // Paginator（独立分页器，UiDataTable 内嵌 Paginator 组件）
  // ============================================================
  paginator: {
    root: 'flex items-center justify-between px-4 py-3 border-t border-border-light',
    page: ({ context }: { context: { active: boolean } }) => ({
      class: [
        'inline-flex items-center justify-center',
        'min-w-[32px] h-8',
        'px-2.5',
        'text-sm font-medium',
        'rounded-md',
        'transition-colors duration-150',
        context.active
          ? 'bg-primary text-white shadow-sm'
          : 'text-text-secondary hover:bg-slate-100',
      ],
    }),
  },

  // ============================================================
  // DatePicker
  // ============================================================
  datepicker: {
    root: 'relative',
    panel: 'absolute z-[var(--z-dropdown)] bg-white border border-border rounded-xl shadow-lg mt-1 p-3',
    header: 'flex items-center justify-between px-1 py-2',
    title: 'text-sm font-semibold text-text',
    pcPrevButton: {
      root: { class: 'inline-flex items-center justify-center w-8 h-8 rounded-full text-text-muted hover:bg-slate-100 transition-colors' },
    },
    pcNextButton: {
      root: { class: 'inline-flex items-center justify-center w-8 h-8 rounded-full text-text-muted hover:bg-slate-100 transition-colors' },
    },
    weekHeader: 'text-xs text-text-muted font-medium py-1',
    day: ({ context }: { context: { selected: boolean; today: boolean; disabled: boolean } }) => ({
      class: [
        'w-9 h-9 text-sm rounded-full flex items-center justify-center cursor-pointer transition-colors duration-150',
        context.selected ? 'bg-primary text-white' : '',
        context.today && !context.selected ? 'border border-primary text-primary' : '',
        !context.selected && !context.today ? 'hover:bg-slate-100' : '',
        context.disabled ? 'opacity-30 cursor-not-allowed' : '',
      ],
    }),
    buttonbar: 'flex items-center justify-between pt-3 mt-3 border-t border-border-light',
  },

  // ============================================================
  // Select (Combobox)
  // ============================================================
  select: {
    root:
      'relative w-full bg-slate-50 border-2 border-ocean-light rounded-[var(--radius-input)] transition-colors duration-200 focus-within:border-primary focus-within:shadow-[0_0_0_0.2rem_rgba(135,206,235,0.25)]',
    label: 'block w-full py-2.5 px-4 text-sm text-text',
    dropdown: 'text-text-muted',
    overlay: 'absolute z-[var(--z-dropdown)] w-full mt-1',
    listContainer: 'bg-white border border-border rounded-xl shadow-lg overflow-y-auto max-h-60',
    option: ({ context }: { context: { selected: boolean; focused: boolean } }) => ({
      class: [
        'px-3 py-2 text-[13px] cursor-pointer rounded-md mx-1 transition-colors duration-150',
        context.selected
          ? 'bg-primary-100 text-primary-700'
          : context.focused
            ? 'bg-ocean-light/30 text-text'
            : 'text-text hover:bg-ocean-light/20',
      ],
    }),
    emptyMessage: 'px-3 py-6 text-center text-sm text-text-muted',
  },

  // ============================================================
  // Dialog (Modal)
  // ============================================================
  dialog: {
    root: 'fixed inset-0 flex items-center justify-center z-[var(--z-modal)]',
    mask: 'fixed inset-0 bg-black/30 backdrop-blur-sm transition-opacity duration-300',
    content:
      'relative bg-white rounded-[var(--radius-modal)] shadow-xl w-full max-w-lg max-h-[85vh] flex flex-col animate-slide-up flex-1 px-6 py-5 overflow-y-auto',
    header: 'flex items-center justify-between px-6 py-4 border-b border-border-light flex-shrink-0',
    title: 'text-lg font-bold text-heading',
    pcCloseButton: {
      root: { class: 'inline-flex items-center justify-center w-8 h-8 rounded-full text-text-muted hover:bg-slate-100 hover:text-text transition-colors' },
    },
    footer: 'flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light flex-shrink-0',
  },

  // ============================================================
  // InputText
  // ============================================================
  inputtext: {
    root: ({ props }) => ({
      class: [
        'w-full',
        'py-2.5 px-4',
        'text-sm',
        'bg-slate-50',
        'border-2 border-ocean-light',
        'rounded-[var(--radius-input)]',
        'transition-colors duration-200',
        'focus:border-primary focus:shadow-[0_0_0_0.2rem_rgba(135,206,235,0.25)]',
        'focus:outline-none',
        'placeholder:text-text-muted',
        props.disabled ? 'opacity-50 cursor-not-allowed bg-slate-100' : '',
      ],
    }),
  },

  // ============================================================
  // Button
  // ============================================================
  button: {
    root: ({ props }: { props: { severity?: string; outlined?: boolean; text?: boolean } }) => {
      const base =
        'inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold rounded-[var(--radius-button)] transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed'

      if (props.text) return { class: `${base} text-primary hover:bg-primary-50` }
      if (props.outlined) return { class: `${base} border-2 border-primary text-primary bg-transparent hover:bg-primary-50` }

      const severityStyles: Record<string, string> = {
        secondary: 'bg-slate-100 text-text-secondary hover:bg-slate-200',
        success: 'bg-success-500 text-white hover:bg-success-600',
        info: 'bg-info-500 text-white hover:bg-info-600',
        warn: 'bg-warning-500 text-white hover:bg-warning-600',
        danger: 'bg-danger-500 text-white hover:bg-danger-600',
        help: 'bg-purple-500 text-white hover:bg-purple-600',
      }

      return {
        class: `${base} ${severityStyles[props.severity || ''] || 'bg-primary text-white hover:bg-primary-600 shadow-sm hover:shadow-md'}`,
      }
    },
    icon: 'text-base',
  },

  // ============================================================
  // Toast / Message
  // ============================================================
  toast: {
    root: 'fixed top-4 right-4 z-[var(--z-toast)] flex flex-col gap-2',
    message: ({ props }: { props: { severity?: string } }) => {
      const severityClasses: Record<string, string> = {
        success: 'bg-success-50 border-success-500 text-success-700',
        info: 'bg-info-50 border-info-500 text-info-700',
        warn: 'bg-warning-50 border-warning-500 text-warning-700',
        error: 'bg-danger-50 border-danger-500 text-danger-700',
      }
      return {
        class: `flex items-center gap-3 px-4 py-3 border-l-4 rounded-lg shadow-md animate-slide-up ${
          severityClasses[props.severity || ''] || severityClasses.info
        }`,
      }
    },
    messageContent: 'flex-1 text-sm',
    closeButton: 'text-current opacity-60 hover:opacity-100 transition-opacity',
  },
}

export default plushCutePT
