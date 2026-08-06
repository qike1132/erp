<template>
  <div class="sp-body">
    <div v-if="loading" class="sp-empty"><UiSpinner /></div>
    <div v-else-if="error" class="sp-empty"><i class="fas fa-exclamation-circle"  aria-hidden="true" />加载失败 <button class="sp-retry-btn" @click="emit('refetch')">重试</button></div>
    <div v-else-if="!hasData" class="sp-empty"><i class="fas fa-inbox"  aria-hidden="true" />本月暂无数据</div>
    <template v-else>
    <div v-if="fetching" class="sp-fetching-bar"><div class="sp-fetching-progress" /></div>
    <div>
      <div class="sp-customer-tags">
        <button
          :class="['sp-tag', { 'sp-tag-active': !custFilter }]"
          @click="emit('update:custFilter', '')"
        >全部</button>
        <button
          v-for="c in customers"
          :key="c.customer_id"
          :class="['sp-tag', { 'sp-tag-active': custFilter === c.customer_name }]"
          :title="c.customer_name"
          @click="emit('update:custFilter', custFilter === c.customer_name ? '' : c.customer_name)"
        >{{ c.customer_name }}</button>
      </div>
      <div class="sp-sku-table-container">
        <div class="sp-sku-table-wrapper">
          <table class="sp-sku-table">
            <thead>
              <tr>
                <th class="sp-sku-th-customer">客户名称</th>
                <th class="sp-sku-th-product">产品名称</th>
                <th class="sp-sku-th-barcode">
                  商品条码
                </th>
                <th class="sp-sku-th-number sp-sku-th-sortable" @click="emit('toggle-sku-sort', 'plan')">
                  <span class="sp-sku-th-text">计划数量
                    <i v-if="skuSortField === 'plan'" :class="skuSortDir === 'asc' ? 'fas fa-sort-up' : 'fas fa-sort-down'"></i>
                    <i v-else class="fas fa-sort sp-sort-muted"></i>
                  </span>
                </th>
                <th class="sp-sku-th-number sp-sku-th-sortable" @click="emit('toggle-sku-sort', 'shipped')">
                  <span class="sp-sku-th-text">已出货
                    <i v-if="skuSortField === 'shipped'" :class="skuSortDir === 'asc' ? 'fas fa-sort-up' : 'fas fa-sort-down'"></i>
                    <i v-else class="fas fa-sort sp-sort-muted"></i>
                  </span>
                </th>
                <th class="sp-sku-th-number sp-sku-th-sortable" @click="emit('toggle-sku-sort', 'remain')">
                  <span class="sp-sku-th-text">待出货
                    <i v-if="skuSortField === 'remain'" :class="skuSortDir === 'asc' ? 'fas fa-sort-up' : 'fas fa-sort-down'"></i>
                    <i v-else class="fas fa-sort sp-sort-muted"></i>
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(s, i) in paginatedSkuList" :key="`${s.customer_name}|${s.product_name}`" :class="{ 'sp-sku-row-odd': i % 2 === 1 }" class="sp-sku-row-clickable" @click="emit('open-sku-detail', { barcode: s.barcode, name: s.product_name, customer: s.customer_name })">
                <td class="sp-sku-td-customer">{{ s.customer_name }}</td>
                <td class="sp-sku-td-product"><span class="sp-sku-product-name">{{ s.product_name }}</span></td>
                <td class="sp-sku-td-barcode"><code class="sp-sku-barcode">{{ s.barcode }}</code></td>
                <td class="sp-sku-td-number">{{ s.plan_qty }}</td>
                <td class="sp-sku-td-number sp-sku-td-success">{{ s.shipped_qty }}</td>
                <td class="sp-sku-td-number sp-sku-td-warning">{{ s.remain_qty }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <UiPagination v-if="skuTotalPages > 1" :current-page="skuPage" :total-pages="skuTotalPages" :total-items="sortedSkuList.length" @update:current-page="emit('update:skuPage', $event)" />
    </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import UiPagination from '@/components/ui/UiPagination.vue';
import type { CustSumItem, SkuRow } from './types';

defineProps<{
  loading: boolean;
  error: boolean;
  fetching: boolean;
  hasData: boolean;
  customers: CustSumItem[];
  custFilter: string;
  sortedSkuList: SkuRow[];
  paginatedSkuList: SkuRow[];
  skuPage: number;
  skuTotalPages: number;
  skuSortField: string;
  skuSortDir: 'asc' | 'desc';
}>();

const emit = defineEmits<{
  'update:custFilter': [value: string];
  'update:skuPage': [value: number];
  'toggle-sku-sort': [field: string];
  'open-sku-detail': [payload: { barcode: string; name: string; customer: string }];
  refetch: [];
}>();
</script>

<style scoped>
.sp-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 24px;
}

.sp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.sp-empty i {
  font-size: 28px;
  opacity: 0.5;
}

/* Fetching progress bar */
.sp-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.sp-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: sp-progress-slide 1s ease-in-out infinite;
}
@keyframes sp-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

.sp-retry-btn {
  margin-top: 6px;
  padding: 4px 16px;
  border: 1px solid var(--color-border, #d0d5dd);
  border-radius: 6px;
  background: var(--color-bg, #fff);
  color: var(--color-text, #344054);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s;
}
.sp-retry-btn:hover {
  background: var(--color-bg-hover, #f2f4f7);
}

.sp-customer-tags {
  display: flex;
  flex-wrap: nowrap;
  gap: 6px;
  margin-bottom: 18px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: thin;
  scrollbar-color: var(--color-border-light, #e2e8f0) transparent;
}

.sp-customer-tags::-webkit-scrollbar {
  height: 4px;
}

.sp-customer-tags::-webkit-scrollbar-track {
  background: transparent;
}

.sp-customer-tags::-webkit-scrollbar-thumb {
  background: var(--color-border-light, #e2e8f0);
  border-radius: 2px;
}

.sp-tag {
  padding: 5px 10px;
  border: 1.5px solid var(--color-border-light, #e2e8f0);
  border-radius: 16px;
  background: white;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease, background 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
  font-family: inherit;
  user-select: none;
  white-space: nowrap;
  flex-shrink: 0;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sp-tag:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}

.sp-tag-active {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  border-color: transparent;
  color: white;
}

.sp-sku-table-container {
  margin-bottom: 18px;
}


.sp-sku-table-wrapper {
  border-radius: 10px;
  overflow-y: auto;
  max-height: calc(100vh - 200px);
  border: 1px solid var(--color-border-light, #e2e8f0);
}

.sp-sku-table {
  width: 100%;
  border-collapse: collapse;
}

.sp-sku-table thead {
  position: sticky;
  top: 0;
  z-index: 2;
  background: white;
}

.sp-sku-table th {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  text-align: left;
}

.sp-sku-table td {
  padding: 10px 14px;
  font-size: 13px;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  transition: background 0.2s ease;
}

.sp-sku-table tbody tr:hover td {
  background: var(--color-primary-50);
}

.sp-sku-row-odd td {
  background: transparent;
}

.sp-sku-row-odd:hover td {
  background: var(--color-primary-50);
}

.sp-sku-th-sortable {
  cursor: pointer;
  user-select: none;
}

.sp-sku-th-sortable:hover {
  color: var(--color-primary-500);
}

.sp-sku-th-sortable i {
  margin-left: 4px;
  font-size: 10px;
}

.sp-sort-muted {
  opacity: 0.25;
}

.sp-sku-th-customer,
.sp-sku-td-customer {
  width: 18%;
}

.sp-sku-th-product,
.sp-sku-td-product {
  width: 22%;
}

.sp-sku-th-barcode,
.sp-sku-td-barcode {
  width: 16%;
}

.sp-sku-th-number,
.sp-sku-td-number {
  width: 11%;
  text-align: left;
}

.sp-sku-th-number {
  white-space: nowrap;
  text-align: left;
  padding-right: 4px;
}

.sp-sku-th-number .sp-sku-th-text {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 4px;
  width: 100%;
}

.sp-sku-product-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.sp-sku-barcode {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  font-family: inherit;
  background: transparent;
  padding: 0;
  border-radius: 0;
}

.sp-sku-table td.sp-sku-td-success {
  color: var(--color-success-600);
  font-weight: 600;
}

.sp-sku-table td.sp-sku-td-warning {
  color: var(--color-warning-600);
  font-weight: 600;
}

.sp-sku-row-clickable {
  cursor: pointer;
}
</style>
