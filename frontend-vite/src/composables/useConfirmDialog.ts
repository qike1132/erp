import { ref, reactive } from 'vue'

export function useConfirmDialog() {
  const open = ref(false)
  const text = ref('')
  const sub = ref('')
  const type = ref<'danger' | 'warning'>('danger')
  let _resolve: ((v: boolean) => void) | null = null

  function confirm(msg: string, subMsg = '', dialogType: 'danger' | 'warning' = 'danger'): Promise<boolean> {
    text.value = msg
    sub.value = subMsg
    type.value = dialogType
    open.value = true
    return new Promise((resolve) => {
      _resolve = resolve
    })
  }

  function onConfirm() {
    open.value = false
    _resolve?.(true)
    _resolve = null
  }

  function onCancel() {
    open.value = false
    _resolve?.(false)
    _resolve = null
  }

  return reactive({ open, text, sub, type, confirm, onConfirm, onCancel })
}
