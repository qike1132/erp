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
    root: 'relative',
    input: ({ props }) => ({
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
    loadingIcon: 'mr-2 animate-spin',
    dropdownButton: {
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
    root: 'fixed inset-0 flex z-[var(--z-modal)]',
    mask: 'fixed inset-0 bg-black/30 backdrop-blur-sm transition-opacity duration-300',
    content: ({ props }: { props: { position: string } }) => ({
      class: [
        'relative',
        'flex flex-col',
        'bg-white',
        'shadow-xl',
        props.position === 'right'
          ? 'ml-auto h-full w-[520px] max-w-[95vw]'
          : props.position === 'left'
            ? 'mr-auto h-full w-[520px] max-w-[95vw]'
            : props.position === 'bottom'
              ? 'mt-auto w-full max-h-[80vh]'
              : 'mb-auto w-full max-h-[80vh]',
        'overflow-y-auto',
        'animate-slide-up',
      ],
    }),
    header: 'flex items-center justify-between px-6 py-4 border-b border-border-light flex-shrink-0',
    title: 'text-lg font-bold text-heading',
    closeButton: {
      class: [
        'inline-flex items-center justify-center',
        'w-8 h-8',
        'rounded-full',
        'text-text-muted',
        'hover:bg-slate-100 hover:text-text',
        'transition-colors duration-200',
      ],
    },
    content: 'flex-1 px-6 py-5 overflow-y-auto',
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
    row: ({ context }: { context: { selected: boolean } }) => ({
      class: [
        'border-b border-border-light transition-colors duration-150',
        context.selected ? 'bg-primary-50' : 'hover:bg-slate-50',
      ],
    }),
    headerCell: ({ props }: { props: { sortable: boolean } }) => ({
      class: [
        'px-3 py-3',
        'text-xs font-semibold text-text-secondary',
        'uppercase tracking-wider',
        'bg-surface',
        'border-b-2 border-border',
        'text-center',
        props.sortable ? 'cursor-pointer select-none hover:text-primary' : '',
      ],
    }),
    bodyCell: 'px-3 py-3 text-sm text-text text-center align-middle',
    columnResizeIndicator: 'absolute top-0 right-0 w-1 h-full bg-primary cursor-col-resize',
    paginator: {
      root: 'flex items-center justify-between px-4 py-3 border-t border-border-light',
      pageButton: ({ context }: { context: { active: boolean } }) => ({
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
    sortIcon: 'ml-1 inline-block text-text-muted',
    loadingOverlay: 'absolute inset-0 bg-white/70 flex items-center justify-center z-10',
    emptyMessage: 'py-12 text-center text-sm text-text-muted',
    headerCheckbox: 'flex items-center justify-center',
    bodyCheckbox: 'flex items-center justify-center',
  },

  // ============================================================
  // DatePicker
  // ============================================================
  datepicker: {
    root: 'relative',
    input: {
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
      ],
    },
    panel: 'absolute z-[var(--z-dropdown)] bg-white border border-border rounded-xl shadow-lg mt-1 p-3',
    header: 'flex items-center justify-between px-1 py-2',
    title: 'text-sm font-semibold text-text',
    previousButton: 'inline-flex items-center justify-center w-8 h-8 rounded-full text-text-muted hover:bg-slate-100 transition-colors',
    nextButton: 'inline-flex items-center justify-center w-8 h-8 rounded-full text-text-muted hover:bg-slate-100 transition-colors',
    table: 'w-full border-collapse',
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
    monthTitle: 'text-sm font-semibold text-text',
    yearTitle: 'text-sm font-semibold text-text',
    buttonbar: 'flex items-center justify-between pt-3 mt-3 border-t border-border-light',
  },

  // ============================================================
  // Select (Combobox)
  // ============================================================
  select: {
    root: 'relative',
    label: 'block text-xs font-semibold text-text-secondary mb-1.5',
    input: {
      class: [
        'flex items-center justify-between',
        'w-full',
        'py-2.5 px-4',
        'text-sm',
        'bg-slate-50',
        'border-2 border-ocean-light',
        'rounded-[var(--radius-input)]',
        'transition-colors duration-200',
        'focus-within:border-primary focus-within:shadow-[0_0_0_0.2rem_rgba(135,206,235,0.25)]',
      ],
    },
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
      'relative bg-white rounded-[var(--radius-modal)] shadow-xl w-full max-w-lg max-h-[85vh] flex flex-col animate-slide-up',
    header: 'flex items-center justify-between px-6 py-4 border-b border-border-light flex-shrink-0',
    title: 'text-lg font-bold text-heading',
    closeButton:
      'inline-flex items-center justify-center w-8 h-8 rounded-full text-text-muted hover:bg-slate-100 hover:text-text transition-colors',
    content: 'flex-1 px-6 py-5 overflow-y-auto',
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
    content: 'flex-1 text-sm',
    closeButton: 'text-current opacity-60 hover:opacity-100 transition-opacity',
  },
}

export default plushCutePT
