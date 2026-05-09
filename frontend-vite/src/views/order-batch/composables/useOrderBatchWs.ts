import { ref } from 'vue'
import type { Ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { useWebSocket } from '@/views/purchase/composables/useWebSocket'

export function useOrderBatchWs(isActive: Ref<boolean>) {
  const queryClient = useQueryClient()
  const reconnectTriggered = ref(false)

  function invalidateQueries() {
    queryClient.invalidateQueries({ queryKey: ['order-batch'] })
  }

  useWebSocket({
    onMessage: (data) => {
      if (
        data.type === 'order_status_changed' ||
        data.type === 'batch_no_updated' ||
        data.type === 'batch_completed' ||
        data.type === 'order_created' ||
        data.type === 'order_updated'
      ) {
        invalidateQueries()
      }
    },
    isActive,
  })

  return { invalidateQueries }
}
