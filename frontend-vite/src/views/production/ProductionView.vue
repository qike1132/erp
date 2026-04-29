<template>
  <div class="production-page">
    <UiPageHeader>生产报表<template #description>工艺与包装生产汇总</template></UiPageHeader>
    <UiTabs :model-value="activeTab" @update:model-value="activeTab = $event">
      <UiTabTrigger value="craft" class="flex-1"> 工艺生产 </UiTabTrigger>
      <UiTabTrigger value="packaging" class="flex-1"> 包装生产 </UiTabTrigger>
    </UiTabs>

    <div v-if="activeTab === 'craft'" style="margin-top: 12px">
      <UiCard>
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            <span>工艺生产记录</span>
            <UiButton variant="primary" size="sm" @click="craftDialogVisible = true"> 新增 </UiButton>
          </div>
        </template>
        <div v-if="craftIsLoading" class="flex items-center justify-center py-8 text-gray-400 gap-2">
          <UiSpinner /> 加载中...
        </div>
        <template v-else-if="craftList.length === 0">
          <UiEmpty description="暂无数据" />
        </template>
        <table v-else class="w-full border-collapse text-[13px] data-table">
          <thead>
            <tr>
              <th>产品</th>
              <th>工艺</th>
              <th class="text-right">数量</th>
              <th>日期</th>
              <th>备注</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in craftList" :key="row.id">
              <td>{{ row.product_name }}</td>
              <td>{{ row.craft_name }}</td>
              <td class="text-right">
                {{ row.quantity }}
              </td>
              <td>{{ row.date }}</td>
              <td>{{ row.remark }}</td>
              <td>
                <UiButton variant="danger" size="sm" :disabled="actionId === row.id" @click="handleDeleteCraft(row)">
                  删除
                </UiButton>
              </td>
            </tr>
          </tbody>
        </table>
      </UiCard>
    </div>

    <div v-if="activeTab === 'packaging'" style="margin-top: 12px">
      <UiCard>
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            <span>包装生产记录</span>
            <UiButton variant="primary" size="sm" @click="pkgDialogVisible = true"> 新增 </UiButton>
          </div>
        </template>
        <div v-if="pkgIsLoading" class="flex items-center justify-center py-8 text-gray-400 gap-2">
          <UiSpinner /> 加载中...
        </div>
        <template v-else-if="pkgList.length === 0">
          <UiEmpty description="暂无数据" />
        </template>
        <table v-else class="w-full border-collapse text-[13px] data-table">
          <thead>
            <tr>
              <th>产品</th>
              <th class="text-right">数量</th>
              <th>日期</th>
              <th>备注</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in pkgList" :key="row.id">
              <td>{{ row.product_name }}</td>
              <td class="text-right">
                {{ row.quantity }}
              </td>
              <td>{{ row.date }}</td>
              <td>{{ row.remark }}</td>
              <td>
                <UiButton variant="danger" size="sm" :disabled="actionId === row.id" @click="handleDeletePkg(row)">
                  删除
                </UiButton>
              </td>
            </tr>
          </tbody>
        </table>
      </UiCard>
    </div>

    <!-- 工艺新增弹窗 -->
    <UiDialog :open="craftDialogVisible" title="新增工艺生产" @update:open="craftDialogVisible = $event">
      <form @submit.prevent="handleAddCraft">
        <div class="form-group"><label>产品名称</label><UiInput v-model="craftForm.product_name" /></div>
        <div class="form-group"><label>工艺名称</label><UiInput v-model="craftForm.craft_name" /></div>
        <div class="form-group">
          <label>数量</label><input type="number" class="form-number-input" v-model.number="craftForm.quantity" min="1" step="1" />
        </div>
        <div class="form-group"><label>日期</label><UiDatePicker v-model="craftForm.date" style="width: 100%" /></div>
        <div class="form-group">
          <label>备注</label><textarea v-model="craftForm.remark" rows="2" class="form-textarea" />
        </div>
      </form>
      <template #footer>
        <UiButton variant="outline" @click="craftDialogVisible = false"> 取消 </UiButton>
        <UiButton variant="primary" :disabled="craftSaving" @click="handleAddCraft">
          {{ craftSaving ? '添加中...' : '添加' }}
        </UiButton>
      </template>
    </UiDialog>

    <!-- 包装新增弹窗 -->
    <UiDialog :open="pkgDialogVisible" title="新增包装生产" @update:open="pkgDialogVisible = $event">
      <form @submit.prevent="handleAddPkg">
        <div class="form-group"><label>产品名称</label><UiInput v-model="pkgForm.product_name" /></div>
        <div class="form-group">
          <label>数量</label><input type="number" class="form-number-input" v-model.number="pkgForm.quantity" min="1" step="1" />
        </div>
        <div class="form-group"><label>日期</label><UiDatePicker v-model="pkgForm.date" style="width: 100%" /></div>
        <div class="form-group">
          <label>备注</label><textarea v-model="pkgForm.remark" rows="2" class="form-textarea" />
        </div>
      </form>
      <template #footer>
        <UiButton variant="outline" @click="pkgDialogVisible = false"> 取消 </UiButton>
        <UiButton variant="primary" :disabled="pkgSaving" @click="handleAddPkg">
          {{ pkgSaving ? '添加中...' : '添加' }}
        </UiButton>
      </template>
    </UiDialog>
    <UiConfirmDialog
      :open="confirmDialog.open"
      :text="confirmDialog.text"
      :sub="confirmDialog.sub"
      :type="confirmDialog.type"
      @confirm="confirmDialog.onConfirm"
      @cancel="confirmDialog.onCancel"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { productionApi } from '@/api'
import UiTabs from '@/components/ui/UiTabs.vue'
import UiTabTrigger from '@/components/ui/UiTabTrigger.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import { showToast } from '@/composables/useToast'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import UiPageHeader from '@/components/ui/UiPageHeader.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'

const actionId = ref<number | ''>(0)
const queryClient = useQueryClient()
const confirmDialog = useConfirmDialog()
const activeTab = ref('craft')

// 工艺
const { data: craftData, isLoading: craftIsLoading } = useQuery({
  queryKey: ['production-craft'],
  queryFn: () => productionApi.craft() as Promise<any>,
  staleTime: 30_000,
})
const craftList = computed(() => craftData.value?.crafts ?? craftData.value?.items ?? [])

const craftDialogVisible = ref(false)
const craftSaving = ref(false)
const craftForm = reactive({
  product_name: '',
  craft_name: '',
  quantity: 1,
  date: new Date().toISOString().split('T')[0],
  remark: '',
})

async function handleAddCraft() {
  craftSaving.value = true
  try {
    await productionApi.createCraft(craftForm)
    showToast('添加成功', 'success')
    craftDialogVisible.value = false
    queryClient.invalidateQueries({ queryKey: ['production-craft'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '添加失败', 'error')
  } finally {
    craftSaving.value = false
  }
}

async function handleDeleteCraft(row: any) {
  if (!(await confirmDialog.confirm('确定要删除吗？'))) return
  actionId.value = row.id
  try {
    await productionApi.deleteCraft(row.id)
    showToast('删除成功', 'success')
    queryClient.invalidateQueries({ queryKey: ['production-craft'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '删除失败', 'error')
  } finally {
    actionId.value = 0
  }
}

// 包装
const { data: pkgData, isLoading: pkgIsLoading } = useQuery({
  queryKey: ['production-packaging'],
  queryFn: () => productionApi.packaging() as Promise<any>,
  staleTime: 30_000,
})
const pkgList = computed(() => pkgData.value?.packagings ?? pkgData.value?.items ?? [])

const pkgDialogVisible = ref(false)
const pkgSaving = ref(false)
const pkgForm = reactive({ product_name: '', quantity: 1, date: new Date().toISOString().split('T')[0], remark: '' })

async function handleAddPkg() {
  pkgSaving.value = true
  try {
    await productionApi.createPackaging(pkgForm)
    showToast('添加成功', 'success')
    pkgDialogVisible.value = false
    queryClient.invalidateQueries({ queryKey: ['production-packaging'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '添加失败', 'error')
  } finally {
    pkgSaving.value = false
  }
}

async function handleDeletePkg(row: any) {
  if (!(await confirmDialog.confirm('确定要删除吗？'))) return
  actionId.value = row.id
  try {
    await productionApi.deletePackaging(row.id)
    showToast('删除成功', 'success')
    queryClient.invalidateQueries({ queryKey: ['production-packaging'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '删除失败', 'error')
  } finally {
    actionId.value = 0
  }
}
</script>

<style scoped>
.form-number-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--color-text);
  font-family: inherit;
  -moz-appearance: textfield;
}
.form-number-input::-webkit-inner-spin-button,
.form-number-input::-webkit-outer-spin-button {
  opacity: 1;
}
.form-number-input:focus {
  outline: none;
  border-color: var(--color-primary-500);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.15);
}
.form-group {
  margin-bottom: 14px;
}
.form-group label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 4px;
  color: var(--color-text-secondary);
}
.form-textarea {
  width: 100%;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 13px;
  resize: vertical;
  outline: none;
}
.form-textarea:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.1);
}
</style>
