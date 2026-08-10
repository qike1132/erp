<template>
  <div class="co-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部 -->
      <div class="page-card-header">
        <div class="co-header-left">
          <HeaderTabs />
        </div>
        <div class="co-header-right">
          <div class="co-tab-bar">
            <button :class="['co-tab-btn', activeTab === 'input' && 'active']" @click="activeTab = 'input'">
              录入
            </button>
            <button :class="['co-tab-btn', activeTab === 'records' && 'active']" @click="activeTab = 'records'">
              记录查询
            </button>
          </div>
        </div>
      </div>

      <!-- TAB: 录入 -->
      <div v-show="activeTab === 'input'" class="co-tab-content">
      <div class="page-card-body">
        <!-- 左栏：录入表单 -->
        <div class="co-col">
          <div class="co-col-title">
            <span><FontAwesomeIcon icon="edit" aria-hidden="true" /> {{ isOrder ? '订单信息录入' : '备货信息录入' }}</span>
            <div class="co-type-switch">
              <button :class="['co-type-btn', isOrder && 'active']" @click="form.type = 'order'">
                <FontAwesomeIcon icon="clipboard-list" aria-hidden="true" />订单
              </button>
              <button :class="['co-type-btn', !isOrder && 'active']" @click="form.type = 'stockin'">
                <FontAwesomeIcon icon="truck-loading" aria-hidden="true" />备货
              </button>
            </div>
          </div>
          <div class="co-col-scroll">
            <form @submit.prevent="addStaged">
              <div class="co-form-row">
                <div class="co-form-group">
                  <label class="co-label">订单类型 <span class="co-required">*</span></label>
                  <UiSelect
                    v-model="form.orderType"
                    placeholder="请选择订单类型"
                    style="width: 100%"
                    :options="orderTypeOptions"
                  />
                </div>
                <div v-if="isCustomOrder" class="co-form-group">
                  <label class="co-label">国家</label>
                  <div style="display: flex; gap: 8px; align-items: center;">
                    <UiSelect
                      v-model="form.country"
                      placeholder="请选择国家"
                      style="flex: 1"
                      :options="countryStore.countryOptions"
                    />
                    <UiButton variant="outline" style="white-space: nowrap; flex-shrink: 0;" @click="openCountryDialog">
                      <FontAwesomeIcon icon="plus" aria-hidden="true" />
                    </UiButton>
                  </div>
                </div>
              </div>
              <div class="co-form-row">
                <div v-if="isOrder" class="co-form-group">
                  <label class="co-label">订单时间 <span class="co-required">*</span></label>
                  <UiDatePicker v-model="form.date" style="width: 100%" />
                </div>
                <div v-else class="co-form-group">
                  <label class="co-label">备货时间 <span class="co-required">*</span></label>
                  <UiDatePicker v-model="form.date" style="width: 100%" />
                </div>
                <div class="co-form-group">
                  <label class="co-label">客户名称 <span class="co-required">*</span></label>
                  <UiSelect
                    v-model="form.customer"
                    placeholder="请选择客户"
                    style="width: 100%"
                    :options="customerOptions"
                  />
                </div>
              </div>

              <div class="co-form-group">
                <label class="co-label">产品名称 <span class="co-required">*</span></label>
                <UiAutocomplete
                  v-model="form.productSearch"
                  :searchFn="searchProducts"
                  placeholder="输入产品名称搜索"
                  @select="selectProduct"
                  @update:modelValue="form.productId = 0"
                >
                  <template #option="{ item }">
                    {{ item.name }}
                  </template>
                </UiAutocomplete>
              </div>

              <div class="co-form-row">
                <div class="co-form-group">
                  <label class="co-label"
                    >{{ isOrder ? '订单数量' : '备货数量' }} <span class="co-required">*</span></label
                  >
                  <input type="number" class="form-number-input" v-model.number="form.quantity" min="1" max="9999999" step="1" style="width: 100%" name="quantity" autocomplete="off" />
                </div>
                <div v-if="isOrder" class="co-form-group">
                  <label class="co-label">抵扣备货数量</label>
                  <div class="co-deduct-row">
                    <button
                      type="button"
                      :class="['co-btn-deduct', form.deductStock && 'active']"
                      @click="handleDeductPreview"
                    >
                      <FontAwesomeIcon icon="boxes" aria-hidden="true" />抵扣备货
                    </button>
                    <button
                      type="button"
                      class="co-deduct-display"
                      :style="{ borderColor: form.deductQuantity > 0 ? 'var(--color-ocean-deep)' : 'var(--color-text-muted)' }"
                      @click="openDeductEdit"
                    >
                      <FontAwesomeIcon icon="edit" style="font-size: 11px"  aria-hidden="true" />抵扣: <strong>{{ form.deductQuantity }}</strong>
                    </button>
                  </div>
                  <div v-if="deductInfoVisible" class="co-deduct-info">
                    <small v-if="availableStock > 0" style="color: var(--color-success-700)">
                      <FontAwesomeIcon icon="check-circle" aria-hidden="true" /> 可用备货: <strong>{{ availableStock }}</strong> 件
                      <span v-if="form.deductQuantity > 0" style="margin-left: 8px; color: var(--color-ocean-text)">
                        <FontAwesomeIcon icon="arrow-right" aria-hidden="true" /> 抵扣后剩余:
                        <strong>{{ availableStock - form.deductQuantity }}</strong> 件
                      </span>
                    </small>
                    <small v-else style="color: var(--color-warning-500)"><FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" /> 暂无可用备货</small>
                  </div>
                </div>
              </div>

              <div class="co-form-group">
                <label class="co-label">备注</label>
                <textarea
                  v-model="form.note"
                  rows="2"
                  class="co-textarea"
                  :placeholder="isOrder ? '例如：加急订单' : '例如：批量备货'"
                />
              </div>

              <!-- 批量导入 -->
              <div class="co-section-label"><FontAwesomeIcon icon="file-import" aria-hidden="true" /> 批量导入</div>
              <div
                class="co-section-header co-droppable"
                :class="{ 'co-drag-over': isDragOver }"
                @click="excelInputRef?.click()"
                @dragover.prevent="isDragOver = true"
                @dragleave="isDragOver = false"
                @drop.prevent="onDrop"
              >
                <label class="form-label co-droppable-label">
                  <FontAwesomeIcon icon="file-excel" class="label-icon" aria-hidden="true" />
                  <span v-if="excelFile" class="co-file-inline co-file-inline-success"><FontAwesomeIcon icon="file-excel" aria-hidden="true" />{{ excelFile.name }}</span>
                  <span v-else>拖拽文件到标题栏 · 支持 .xlsx / .xls</span>
                </label>
                <div class="co-inline-actions">
                  <button class="co-inline-btn" @click.stop="downloadTemplate">模板</button>
                  <button class="co-inline-btn co-inline-btn-success" :disabled="!excelFile" @click.stop="handleImport">
                    {{ importing ? '导入中…' : '导入' }}
                  </button>
                </div>
                <input
                  ref="excelInputRef"
                  type="file"
                  accept=".xlsx,.xls"
                  style="display: none"
                  @change="handleExcelSelect"
                />
              </div>

              <UiButton variant="primary" :disabled="!canAdd" style="margin-top: 15px" @click="addStaged">
                <FontAwesomeIcon icon="plus-circle" aria-hidden="true" />{{ isOrder ? '新增订单' : '新增备货' }}
              </UiButton>
            </form>
          </div>
        </div>

        <!-- 右栏：暂存列表 + 批量导入 -->
        <div class="co-col">
          <div class="co-col-title">
            <span><FontAwesomeIcon icon="layer-group" aria-hidden="true" /> 暂存列表</span>
            <span v-if="stagedItems.length" class="count-badge-subtle">共 {{ stagedItems.length }} 个</span>
          </div>
          <div class="co-col-scroll">
            <template v-if="stagedItems.length">
              <div
                v-for="(item, idx) in stagedItems"
                :key="item.type + '-' + item.productId + '-' + idx"
                class="co-staged-card"
                :style="{ borderColor: item.type === 'order' ? 'var(--color-ocean-light)' : 'var(--color-success-200)' }"
              >
                <div class="co-staged-main">
                  <div class="co-staged-info">
                    <span :class="['co-type-badge', item.type]">{{ item.type === 'order' ? '订单' : '备货' }}</span>
                    <span v-if="item.orderType === 'custom'" class="co-type-badge custom">定制</span>
                    <span class="co-staged-tag"><FontAwesomeIcon icon="user" aria-hidden="true" />{{ item.customer }}</span>
                    <span class="co-staged-tag"><FontAwesomeIcon icon="calendar-alt" aria-hidden="true" />{{ item.date }}</span>
                    <span class="co-staged-product">
                      <FontAwesomeIcon :icon="item.type === 'order' ? 'shopping-cart' : 'cubes'" :style="{ color: item.type === 'order' ? 'var(--color-ocean-text)' : 'var(--color-success-700)' }" />
                      {{ item.productName }}

                    <span class="count-badge-subtle">数量: {{ item.quantity }}</span>
                    <span v-if="item.deductQuantity > 0" class="count-badge-subtle">抵扣: {{ item.deductQuantity }}</span>
                    <span v-if="item.country" class="count-badge-subtle"><FontAwesomeIcon icon="globe" aria-hidden="true" /> {{ item.country }}</span>
                    <span v-if="item.note" class="count-badge-subtle">备注: {{ item.note }}</span>
                </span>
                  </div>
                  <div class="co-staged-actions">
                    <button class="co-btn-icon co-btn-warn" @click="openEditStaged(item.uid)" aria-label="编辑">
                      <FontAwesomeIcon icon="edit" aria-hidden="true" />
                    </button>
                    <button class="co-btn-icon co-btn-danger" @click="removeStagedItem(item.uid)" aria-label="删除">
                      <FontAwesomeIcon icon="trash" aria-hidden="true" />
                    </button>
                  </div>
                </div>
              </div>
            </template>
            <div v-else class="co-empty-state">
              <FontAwesomeIcon icon="box-open" class="co-empty-icon" aria-hidden="true" />
              <p>暂无暂存记录</p>
            </div>
          </div>
        </div>
      </div>

      <!-- 提交按钮 -->
      <div v-if="stagedItems.length" class="co-submit-bar">
      <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap">
        <UiButton
          variant="primary"
          size="lg"
          :disabled="submitting"
          style="min-width: 200px"
          @click="submitAll"
        >
          <FontAwesomeIcon icon="paper-plane" aria-hidden="true" />{{ submitting ? '提交中…' : `提交订单 (${stagedItems.length})` }}
        </UiButton>
      </div>
    </div>
      </div>

      <!-- TAB: 记录查询 -->
      <div v-show="activeTab === 'records'" class="co-tab-content">
        <div class="co-records-header">
          <div class="co-records-title-group">
            <span class="co-records-title"><FontAwesomeIcon icon="list-alt" aria-hidden="true" /> 记录列表</span>
            <span class="co-record-type-switch">
              <button
                v-for="opt in recordTypeOptions"
                :key="opt.value"
                :class="['co-type-btn', recordType === opt.value && 'active']"
                @click="recordType = opt.value; currentPage = 1; fetchOrders()"
              >{{ opt.label }}</button>

            </span>
          </div>
          <UiButton variant="outline" size="sm" @click="showFilter = !showFilter">
            <FontAwesomeIcon icon="filter" style="margin-right: 4px" aria-hidden="true" />筛选
          </UiButton>
        </div>

        <div v-if="showFilter" class="co-filter-panel">
          <div class="co-filter-row">
            <div class="co-filter-field">
              <label class="co-label"><FontAwesomeIcon icon="user" aria-hidden="true" /> 客户</label>
              <UiSelect v-model="filterCustomer" placeholder="全部" :options="customerOptions" style="width: 100%" />
            </div>
            <div class="co-filter-field">
              <label class="co-label"><FontAwesomeIcon icon="tag" aria-hidden="true" /> 订单类型</label>
              <UiSelect v-model="filterOrderType" placeholder="全部" :options="filterOrderTypeOptions" style="width: 100%" />
            </div>
            <div v-if="recordType === 'order'" class="co-filter-field">
              <label class="co-label"><FontAwesomeIcon icon="info-circle" aria-hidden="true" /> 状态</label>
              <UiSelect v-model="filterStatus" placeholder="全部" :options="statusOptions" style="width: 100%" />
            </div>
            <div v-if="recordType === 'order'" class="co-filter-field">
              <label class="co-label"><FontAwesomeIcon icon="industry" aria-hidden="true" /> 工厂</label>
              <UiSelect v-model="filterFactory" placeholder="全部" :options="factoryOptions" :disabled="factoryDisabled" style="width: 100%" />
            </div>
            <div class="co-filter-field">
              <label class="co-label"><FontAwesomeIcon icon="calendar-alt" aria-hidden="true" /> 开始日期</label>
              <UiDatePicker v-model="filterStart" style="width: 100%" />
            </div>
            <div class="co-filter-field">
              <label class="co-label"><FontAwesomeIcon icon="calendar-alt" aria-hidden="true" /> 结束日期</label>
              <UiDatePicker v-model="filterEnd" style="width: 100%" />
            </div>
            <div class="co-filter-field co-filter-action">
              <UiButton variant="primary" size="sm" @click="fetchOrders">
                <FontAwesomeIcon icon="search" style="margin-right: 4px" aria-hidden="true" />查询
              </UiButton>
              <UiButton variant="outline" size="sm" @click="resetFilter">
                <FontAwesomeIcon icon="undo" style="margin-right: 4px" aria-hidden="true" />重置
              </UiButton>
            </div>
          </div>
        </div>

        <div class="co-records-body">
          <div v-if="isLoadingRecords && orderRecords.length === 0" class="co-state-placeholder">
            <div class="co-spinner-ring" />
            <p class="co-state-text">加载中…</p>
          </div>
          <div v-else-if="orderRecords.length === 0" class="co-state-placeholder co-state-empty">
            <div class="co-empty-illustration"><FontAwesomeIcon icon="clipboard-list" aria-hidden="true" /></div>
            <p class="co-state-text">暂无{{ recordType === 'stockin' ? '备货' : '订单' }}记录</p>
          </div>

          <template v-else>
            <div v-if="isFetchingRecords" class="co-fetching-bar"><div class="co-fetching-progress" /></div>
            <table class="co-table">
              <thead>
                <tr>
                  <th>{{ recordType === 'stockin' ? '备货时间' : '订单时间' }}</th>
                  <th>编号</th>
                  <th>客户</th>
                  <th v-if="recordType === 'order'">工厂</th>
                  <th v-if="recordType === 'order'">SKU 数量</th>
                  <th>产品</th>
                  <th>数量</th>
                  <th v-if="recordType === 'order'">抵扣备货</th>
                  <th v-if="recordType === 'stockin'">已抵扣</th>
                  <th v-if="recordType === 'order'">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in orderRecords" :key="(item.record_type || 'order') + '-' + item.id">
                  <td><span class="co-cell-muted">{{ item.order_date }}</span></td>
                  <td>
                    <span :class="['co-type-badge', item.record_type === 'stockin' ? 'stockin' : 'order']">
                      {{ item.record_type === 'stockin' ? '备货' : '订单' }}
                    </span>
                    <span class="co-cell-muted" style="margin-left: 4px;">{{ item.order_no }}</span>
                  </td>
                  <td><span class="co-cell-main">{{ item.customer }}</span></td>
                  <td v-if="recordType === 'order'">
                    <span class="co-cell-muted">{{ item.factories?.join(', ') || '-' }}</span>
                  </td>
                  <td v-if="recordType === 'order'">
                    <span class="co-badge-tag" :class="(item.items?.length || 1) > 1 ? 'co-badge-success' : 'co-badge-muted'">
                      {{ item.items?.length || 1 }}
                    </span>
                  </td>
                  <td style="text-align: center">
                    <span class="co-cell-main">{{ item.product?.name || '-' }}</span>
                    <span v-if="item.product?.barcode" class="co-cell-muted" style="display: block; font-size: 11px;">{{ item.product.barcode }}</span>
                  </td>
                  <td><strong>{{ item.quantity }}</strong></td>
                  <td v-if="recordType === 'order'">
                    <span v-if="(item.deduct_quantity ?? 0) > 0" class="co-badge-tag co-badge-success">抵扣: {{ item.deduct_quantity }}</span>
                  </td>
                  <td v-if="recordType === 'stockin'">
                    <span v-if="(item.deduct_quantity ?? 0) > 0" class="co-badge-tag co-badge-success">已抵扣: {{ item.deduct_quantity }}</span>
                  </td>
                  <td v-if="recordType === 'order'">
                    <div class="co-action-group">
                      <button class="co-btn-icon co-btn-info" @click="openDetail(item)" aria-label="详情">
                        <FontAwesomeIcon icon="eye" aria-hidden="true" />
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </template>

          <UiPagination v-if="totalPages > 1" :current-page="currentPage" :total-pages="totalPages" @update:current-page="currentPage = $event; fetchOrders()" />
        </div>
      </div>

    </div>

    <!-- 订单详情弹窗 -->
    <UiDialog v-model:open="detailOpen" title="编辑订单" max-width-class="max-w-[580px]">
      <div v-if="detailData" class="oe-dialog">
        <!-- 订单信息头部 -->
        <div class="oe-header">
          <div class="oe-header-left">
            <span class="oe-order-no">{{ detailData.order_no }}</span>
            <span :class="['oe-status-dot', getStatusClass(detailData.status)]"></span>
            <span class="oe-status-text">{{ detailData.status }}</span>
          </div>
          <span class="oe-date">{{ detailData.order_date }}</span>
        </div>

        <!-- 只读信息区 -->
        <div class="oe-section">
          <div class="oe-section-title"><FontAwesomeIcon icon="info-circle" aria-hidden="true" /> 订单信息</div>
          <div class="oe-info-grid">
            <div class="oe-info-cell">
              <span class="oe-info-label">客户</span>
              <span class="oe-info-value">{{ detailData.customer }}</span>
            </div>
            <div class="oe-info-cell">
              <span class="oe-info-label">订单类型</span>
              <span class="oe-info-value">{{ detailData.order_type === 'custom' ? '定制' : '常规' }}</span>
            </div>
            <div class="oe-info-cell">
              <span class="oe-info-label">产品</span>
              <span class="oe-info-value oe-info-product">
                <img v-if="detailData.product?.image" :src="detailData.product.image" class="oe-product-thumb" />
                <span>{{ detailData.product?.name || '-' }}</span>
              </span>
            </div>
            <div class="oe-info-cell">
              <span class="oe-info-label">69码</span>
              <span class="oe-info-value oe-mono">{{ detailData.product?.barcode || '-' }}</span>
            </div>
            <div class="oe-info-cell" v-if="detailData.country">
              <span class="oe-info-label">国家</span>
              <span class="oe-info-value">{{ detailData.country }}</span>
            </div>
            <div class="oe-info-cell" v-if="detailData.batch_no">
              <span class="oe-info-label">批次号</span>
              <span class="oe-info-value oe-mono">{{ detailData.batch_no }}</span>
            </div>
          </div>
        </div>

        <!-- SKU 明细列表（多 SKU 时显示） -->
        <div v-if="detailData.items?.length > 1" class="oe-section">
          <div class="oe-section-title">
            <FontAwesomeIcon icon="list-ul" aria-hidden="true" /> 订单明细（{{ detailData.items.length }} 个 SKU）
          </div>
          <table class="oe-sku-table">
            <thead>
              <tr>
                <th>产品名</th>
                <th>数量</th>
                <th>类型</th>
                <th>国家</th>
                <th>抵扣数量</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(sku, idx) in detailData.items" :key="sku.id ?? idx">
                <td class="oe-sku-product">
                  {{ sku.product_name || '-' }}
                  <span v-if="sku.product_barcode" class="oe-sku-barcode">{{ sku.product_barcode }}</span>
                </td>
                <td><strong>{{ sku.quantity }}</strong></td>
                <td>{{ sku.order_type === 'custom' ? '定制' : '常规' }}</td>
                <td>{{ sku.country || '-' }}</td>
                <td>{{ sku.deduct_quantity || 0 }}</td>
                <td class="oe-sku-note">{{ sku.note || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 可编辑区域 -->
        <div class="oe-section oe-editable">
          <div class="oe-section-title"><FontAwesomeIcon icon="pen" aria-hidden="true" /> 编辑内容</div>
          <div class="oe-edit-grid">
            <div class="oe-edit-cell">
              <label class="oe-edit-label">数量</label>
              <div class="oe-edit-control">
                <button class="oe-stepper-btn" @click="editForm.quantity = Math.max(1, editForm.quantity - 1)" aria-label="减少">
                  <FontAwesomeIcon icon="minus" aria-hidden="true" />
                </button>
                <input type="number" class="oe-stepper-input" v-model.number="editForm.quantity" min="1" step="1" autocomplete="off" />
                <button class="oe-stepper-btn" @click="editForm.quantity = editForm.quantity + 1" aria-label="增加">
                  <FontAwesomeIcon icon="plus" aria-hidden="true" />
                </button>
              </div>
            </div>
            <div class="oe-edit-cell">
              <label class="oe-edit-label">抵扣备货</label>
              <div class="oe-edit-control">
                <button class="oe-stepper-btn" @click="editForm.deductQuantity = Math.max(0, editForm.deductQuantity - 1)" aria-label="减少抵扣">
                  <FontAwesomeIcon icon="minus" aria-hidden="true" />
                </button>
                <input type="number" class="oe-stepper-input" v-model.number="editForm.deductQuantity" min="0" step="1" autocomplete="off" />
                <button class="oe-stepper-btn" @click="editForm.deductQuantity = editForm.deductQuantity + 1" aria-label="增加抵扣">
                  <FontAwesomeIcon icon="plus" aria-hidden="true" />
                </button>
                <span v-if="availableStockin > 0" class="oe-available-hint">可用: {{ availableStockin }}</span>
              </div>
            </div>
          </div>
          <div class="oe-edit-full">
            <label class="oe-edit-label">备注</label>
            <textarea class="oe-textarea" v-model="editForm.note" rows="2" placeholder="输入备注信息…" />
          </div>
        </div>
      </div>
      <template #footer>
        <UiButton variant="outline" :disabled="saving" @click="detailOpen = false">取消</UiButton>
        <UiButton v-if="deductRetryPending" variant="warning" :disabled="saving" @click="retryDeductUpdate">
          <FontAwesomeIcon icon="redo" style="margin-right: 4px" aria-hidden="true" />重试抵扣更新
        </UiButton>
        <UiButton variant="primary" :disabled="saving" @click="saveEditOrder">
          <FontAwesomeIcon icon="check" style="margin-right: 4px" aria-hidden="true" />{{ saving ? '保存中…' : '保存' }}
        </UiButton>
      </template>
    </UiDialog>

    <!-- 编辑暂存弹窗 -->
    <UiDialog
      v-model:open="editStagedVisible"
      :title="editStagedData?.type === 'order' ? '编辑暂存订单' : '编辑暂存备货'"
    >
      <template v-if="editStagedData">
        <div class="co-form-group">
          <label class="co-label">客户名称</label>
          <UiSelect v-model="editStagedData.customer" style="width: 100%" :options="customerOptions" />
        </div>
        <div class="co-form-group">
          <label class="co-label">{{ editStagedData.type === 'order' ? '订单时间' : '备货时间' }}</label>
          <UiDatePicker v-model="editStagedData.date" style="width: 100%" />
        </div>
        <div class="co-form-group">
          <label class="co-label">产品名称</label>
          <UiInput :model-value="editStagedData.productName" disabled />
        </div>
        <div class="co-form-group">
          <label class="co-label">{{ editStagedData.type === 'order' ? '订单数量' : '备货数量' }}</label>
          <input type="number" class="form-number-input" v-model.number="editStagedData.quantity" min="1" max="9999999" step="1" style="width: 100%" name="quantity" autocomplete="off" />
        </div>
        <div v-if="editStagedData.type === 'order'" class="co-form-group">
          <label class="co-label">抵扣备货数量</label>
          <input type="number" class="form-number-input" v-model.number="editStagedData.deductQuantity" min="0" :max="Math.min(editStagedData.quantity, editAvailableStock)" step="1" style="width: 100%" name="deduct-quantity" autocomplete="off" />
          <small v-if="editAvailableStock > 0" style="color: var(--color-success-700); margin-top: 4px; display: block">
            <FontAwesomeIcon icon="check-circle" aria-hidden="true" /> 可用备货: <strong>{{ editAvailableStock }}</strong> 件
          </small>
        </div>
        <div class="co-form-group">
          <label class="co-label">备注</label>
          <textarea v-model="editStagedData.note" rows="2" class="co-textarea" />
        </div>
      </template>
      <template #footer>
        <UiButton variant="outline" @click="editStagedVisible = false"> 取消 </UiButton>
        <UiButton variant="primary" @click="saveEditStaged"> 保存 </UiButton>
      </template>
    </UiDialog>

    <UiDialog v-model:open="countryDialogVisible" title="添加国家" max-width-class="max-w-[420px]">
      <div class="co-form-group">
        <label class="co-label">国家名称</label>
        <UiInput v-model="newCountryName" placeholder="请输入国家名称" name="country" autocomplete="off" />
      </div>
      <template #footer>
        <UiButton variant="outline" @click="countryDialogVisible = false">取消</UiButton>
        <UiButton variant="primary" @click="saveCountry">保存</UiButton>
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
import { ref, watch } from 'vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { showToast } from '@/composables/useToast'
import { useOrderForm } from './composables/useOrderForm'
import { useOrderList } from './composables/useOrderList'
import { useOrderActions } from './composables/useOrderActions'

const {
  form,
  isOrder,
  isCustomOrder,
  orderTypeOptions,
  canAdd,
  customerOptions,
  countryStore,
  searchProducts,
  selectProduct,
  countryDialogVisible,
  newCountryName,
  openCountryDialog,
  saveCountry,
  availableStock,
  deductInfoVisible,
  handleDeductPreview,
  openDeductEdit,
  resetFormAfterAdd,
} = useOrderForm()

const {
  showFilter,
  filterCustomer,
  filterOrderType,
  filterStatus,
  filterFactory,
  filterStart,
  filterEnd,
  currentPage,
  totalPages,
  isLoadingRecords,
  isFetchingRecords,
  orderRecords,
  recordType,
  recordTypeOptions,
  filterOrderTypeOptions,
  factoryOptions,
  factoryDisabled,
  statusOptions,
  getStatusClass,
  fetchOrders,
  resetFilter,
} = useOrderList()

const {
  stagedItems,
  removeStagedItem,
  submitting,
  submitAll,
  editStagedVisible,
  editStagedData,
  editAvailableStock,
  openEditStaged,
  saveEditStaged,
  excelFile,
  importing,
  isDragOver,
  excelInputRef,
  handleExcelSelect,
  onDrop,
  downloadTemplate,
  handleImport,
  detailOpen,
  detailData,
  editForm,
  availableStockin,
  openDetail,
  saveEditOrder,
  saving,
  deductRetryPending,
  retryDeductUpdate,
  confirmDialog,
  genUid,
} = useOrderActions(form, isOrder, fetchOrders)

function addStaged() {
  if (!canAdd.value) {
    if (!form.productId && form.productSearch) {
      showToast('请从下拉列表中选择产品', 'warning')
    } else {
      showToast('请填写日期、客户和产品', 'warning')
    }
    return
  }
  stagedItems.value.push({
    uid: genUid(),
    type: form.type,
    orderType: form.orderType,
    customer: form.customer,
    productId: form.productId,
    productName: form.productSearch,
    quantity: form.quantity,
    date: form.date,
    note: form.note,
    country: isCustomOrder.value ? form.country : '',
    deductStock: isOrder.value ? form.deductStock : false,
    deductQuantity: isOrder.value && form.deductStock ? form.deductQuantity : 0,
  })
  resetFormAfterAdd()
}

// ===== Tab switching =====
const activeTab = ref<'input' | 'records'>('input')

// 切换到记录查询tab时自动加载数据
watch(activeTab, (tab) => {
  if (tab === 'records' && orderRecords.value.length === 0) {
    fetchOrders()
  }
})
</script>

<style scoped>
/* ===== 强制覆盖产品名称输入框灰色背景（PT HMR 不重载 main.ts 的双保险） ===== */
:deep(input.bg-slate-50) {
  background-color: #ffffff !important;
}

/* ===== 表单输入 ===== */
.form-number-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
  outline: none;
  -moz-appearance: textfield;
}
.form-number-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.form-number-input::-webkit-inner-spin-button,
.form-number-input::-webkit-outer-spin-button {
  opacity: 1;
}
.form-number-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.form-text-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  background: white;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
  outline: none;
}
.form-text-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.form-text-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

/* ===== 页面容器 ===== */
.co-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* ===== 主卡片 ===== */
/* 卡片样式已迁移到全局 .page-card 系列（src/styles/app.css） */

/* ===== 卡片头部 ===== */
.page-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}
.co-card-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.co-card-title-group h3 {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}
.co-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
}

/* ===== 图标色块 ===== */
.co-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}
.co-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}

/* ===== 头部操作区 ===== */
.co-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}
.co-header-right {
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 8px;
}

.co-tab-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

/* ===== 双栏主体 ===== */
/* 卡片主体样式已迁移到全局 .page-card-body（src/styles/app.css） */
/* 此处需要 2 列网格布局，覆盖默认 page-card-body */
.page-card-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
@media (max-width: 1024px) {
  .page-card-body {
    grid-template-columns: 1fr;
  }
}

/* ===== 栏目 ===== */
.co-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.co-col + .co-col {
  border-left: 2px solid var(--color-border, #cbd5e1);
}

/* ===== 栏目标题 ===== */
.co-col-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  flex-shrink: 0;
}
.co-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}

.co-col-scroll {
  padding: 16px 20px;
  overflow-y: auto;
  flex: 1;
}

/* ===== 区块标题（批量导入等 - 输入框风格） ===== */
.co-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-input, 12px);
  min-height: 40px;
  box-sizing: border-box;
  cursor: default;
  transition: border-color 0.3s ease, background 0.3s ease;
}
.co-section-header:hover {
  border-color: var(--color-ocean-deep);
  background: var(--color-slate-50);
}
.co-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 6px;
}
.co-section-title i {
  color: var(--color-success-500);
}
.co-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  padding: 8px 0 4px;
}

/* ===== Droppable 标题栏 ===== */
.co-droppable {
  cursor: pointer;
}
.co-droppable.co-drag-over {
  border-color: var(--color-success-400);
  background: var(--color-success-50);
}
.co-droppable-label {
  display: flex !important;
  margin-bottom: 0;
  cursor: pointer;
  font-size: 14px !important;
  font-weight: 400 !important;
  color: var(--color-text-muted) !important;
}
.co-droppable-label .label-icon {
  color: var(--color-text-muted) !important;
}
.co-inline-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.co-inline-btn {
  padding: 3px 8px;
  border: 1px solid var(--color-border-light);
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  background: white;
  color: var(--color-text-secondary);
  transition: border-color 0.2s ease, color 0.2s ease;
}
.co-inline-btn:hover {
  border-color: var(--color-ocean-deep);
  color: var(--color-primary-600);
}
.co-inline-btn-success {
  border-color: var(--color-success-400);
  color: var(--color-success-600);
}
.co-inline-btn-success:hover {
  background: var(--color-success-50);
}
.co-inline-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.co-file-inline {
  font-size: 13px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.co-file-inline-success {
  color: var(--color-success-600);
}

/* ===== 类型切换 ===== */
.co-type-switch {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}
.co-type-btn {
  padding: 5px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-secondary);
}
.co-type-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.co-type-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

/* ===== 表单 ===== */
.co-form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 14px;
}
.co-form-group {
  margin-bottom: 14px;
}
.co-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 4px;
  color: var(--color-text-secondary);
}
.co-required {
  color: var(--color-danger-500);
}
.co-textarea {
  width: 100%;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 14px;
  resize: vertical;
  outline: none;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
  font-family: inherit;
}
.co-textarea:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.co-textarea:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.co-textarea::placeholder {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;
}

/* ===== 抵扣 ===== */
.co-deduct-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
}
.co-btn-deduct {
  padding: 6px 12px;
  border: 2px solid var(--color-border-light);
  border-radius: 9px;
  background: white;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.3s ease, color 0.3s ease, transform 0.3s ease;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-secondary);
}
.co-btn-deduct:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  transform: translateY(-1px);
}
.co-btn-deduct.active {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  border-color: var(--color-primary-400);
}
.co-deduct-display {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  padding: 6px 14px;
  border-radius: 10px;
  border: 2px dashed var(--color-border-light);
  background: var(--color-surface, #f8fafc);
  cursor: pointer;
  transition: border-color 0.3s ease, background 0.3s ease;
  color: var(--color-text-secondary);
  font-family: inherit;
  line-height: inherit;
}
.co-deduct-display:hover {
  border-color: var(--color-primary-400);
  background: var(--color-primary-50);
}
.co-deduct-display strong {
  color: var(--color-primary-600);
}
.co-deduct-info {
  margin-top: 6px;
  padding: 6px 0;
}
.co-deduct-info small {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* ===== 暂存列表 ===== */
.co-staged-card {
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 8px;
  transition: border-color 0.3s ease, transform 0.3s ease;
}
.co-staged-card:hover {
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}
.co-staged-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.co-staged-info {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.co-staged-tag {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  gap: 4px;
}
.co-staged-tag i {
  font-size: 11px;
}
.co-staged-product {
  display: flex;
  align-items: center;
  gap: 4px;
  font-weight: 500;
}
.co-staged-actions {
  display: flex;
  gap: 4px;
  margin-left: 8px;
  flex-shrink: 0;
}

/* ===== 类型徽章 ===== */
.co-type-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 600;
}
.co-type-badge.order {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.co-type-badge.stockin {
  background: var(--color-success-100);
  color: var(--color-success-600);
}
.co-type-badge.custom {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}

/* ===== 操作按钮 ===== */
.co-btn-icon {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.2s ease;
}
.co-btn-warn {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}
.co-btn-warn:hover {
  background: var(--color-warning-100);
  transform: translateY(-1px);
}
.co-btn-danger {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}
.co-btn-danger:hover {
  background: var(--color-danger-100);
  transform: translateY(-1px);
}
.co-btn-danger:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ===== 搜索建议 ===== */
.co-autocomplete {
  position: absolute;
  left: 0;
  right: 0;
  top: 100%;
  background: white;
  border: 2px solid var(--color-primary-200);
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.12);
  z-index: 1000;
  max-height: 200px;
  overflow-y: auto;
}
.co-autocomplete-item {
  padding: 10px 14px;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.2s ease;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  font-size: 13px;
}
.co-autocomplete-item:last-child {
  border-bottom: none;
}
.co-autocomplete-item:hover {
  background-color: var(--color-primary-50);
  transform: translateX(4px);
}

/* ===== Dropdown Animation ===== */
.co-dropdown-enter-active {
  transition: opacity 0.25s cubic-bezier(0.4, 0, 0.2, 1), transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.co-dropdown-leave-active {
  transition: opacity 0.15s cubic-bezier(0.4, 0, 0.2, 1), transform 0.15s cubic-bezier(0.4, 0, 0.2, 1);
}
.co-dropdown-enter-from {
  opacity: 0;
  transform: translateY(-8px) scale(0.96);
}
.co-dropdown-enter-to {
  opacity: 1;
  transform: translateY(0) scale(1);
}
.co-dropdown-leave-from {
  opacity: 1;
  transform: translateY(0) scale(1);
}
.co-dropdown-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.97);
}

/* ===== 提交栏 ===== */
.co-submit-bar {
  text-align: center;
  padding: 16px 24px;
  border-top: 1px solid var(--color-border, #cbd5e1);
}

/* ===== 空状态 ===== */
.co-empty-state {
  text-align: center;
  padding: 40px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--color-text-secondary);
}
.co-empty-icon {
  font-size: 28px;
  opacity: 0.5;
}
.co-empty-state p {
  margin: 0;
  font-size: 14px;
}

/* ===== Tab 切换栏 ===== */
.co-tab-bar {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}
.co-tab-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
}
.co-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.co-tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

/* ===== 记录查询 ===== */
.co-records-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  flex-shrink: 0;
}
.co-records-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.co-records-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 8px;
}
.co-records-title i {
  color: var(--color-primary-500);
}
.co-record-type-switch {
  display: inline-flex;
  border: 1px solid var(--color-border, #cbd5e1);
  border-radius: 6px;
  overflow: hidden;
}
.co-record-type-switch .co-type-btn {
  padding: 4px 14px;
  font-size: 12px;
  font-weight: 600;
  border: none;
  background: var(--color-bg, #fff);
  color: var(--color-text-secondary, #64748b);
  cursor: pointer;
  transition: all 0.15s;
}
.co-record-type-switch .co-type-btn.active {
  background: var(--color-primary-500, #3b82f6);
  color: #fff;
}

.co-filter-panel {
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  background: var(--color-surface, #f8fafc);
}
.co-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
}
.co-filter-field {
  min-width: 140px;
  flex: 1;
}
.co-filter-field .co-label {
  font-size: 12px;
  margin-bottom: 4px;
}
.co-filter-action {
  display: flex;
  gap: 8px;
  flex: 0 0 auto;
  min-width: auto;
}

.co-records-body {
  flex: 1;
  overflow-y: auto;
  padding: 0;
  min-height: 0;
}

/* ===== 加载/空状态 ===== */
.co-state-placeholder {
  text-align: center;
  padding: 60px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.co-state-empty {
  color: var(--color-text-muted);
}
.co-state-text {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin: 0;
}
.co-empty-illustration {
  font-size: 36px;
  opacity: 0.4;
  color: var(--color-text-muted);
}
.co-spinner-ring {
  width: 36px;
  height: 36px;
  border: 3px solid var(--color-border-light);
  border-top-color: var(--color-primary-500);
  border-radius: 50%;
  animation: co-spin 0.8s linear infinite;
}
@keyframes co-spin {
  to { transform: rotate(360deg); }
}

/* ===== Fetching 进度条 ===== */
.co-fetching-bar {
  height: 3px;
  background: var(--color-border-light);
  overflow: hidden;
}
.co-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500);
  animation: co-fetch-slide 1.2s ease-in-out infinite;
}
@keyframes co-fetch-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

/* ===== 数据表格 ===== */
.co-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.co-table thead {
  background: var(--color-surface, #f8fafc);
  position: sticky;
  top: 0;
  z-index: 1;
}
.co-table th {
  padding: 10px 12px;
  text-align: center;
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  border-bottom: 2px solid var(--color-border, #cbd5e1);
  white-space: nowrap;
}
.co-table td {
  padding: 10px 12px;
  text-align: center;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  vertical-align: middle;
}
.co-table tbody tr:hover {
  background: var(--color-primary-50);
}
.co-cell-main {
  font-weight: 500;
  color: var(--color-text);
}
.co-cell-muted {
  color: var(--color-text-muted);
  font-size: 12px;
}
.co-product-thumb {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  object-fit: cover;
  flex-shrink: 0;
}

/* ===== Badge tags ===== */
.co-badge-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}
.co-badge-success {
  background: var(--color-success-100);
  color: var(--color-success-600);
}
.co-badge-muted {
  background: var(--color-surface, #f1f5f9);
  color: var(--color-text-muted);
}

/* ===== Status badges ===== */
.co-status-badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
}
.co-status-pending {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}
.co-status-stocked {
  background: var(--color-success-100);
  color: var(--color-success-600);
}
.co-status-partial {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.co-status-shipping {
  background: #e0e7ff;
  color: #4338ca;
}
.co-status-shipped {
  background: var(--color-success-50);
  color: var(--color-success-700);
}
.co-status-cancelled {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}
.co-status-completed {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
}

/* ===== Action buttons ===== */
.co-action-group {
  display: flex;
  gap: 4px;
  justify-content: center;
}
.co-btn-info {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.co-btn-info:hover {
  background: var(--color-primary-100);
  transform: translateY(-1px);
}

/* ===== 响应式筛选 ===== */
@media (max-width: 768px) {
  .co-filter-row {
    flex-direction: column;
  }
  .co-filter-field {
    min-width: 100%;
  }
  .co-table {
    font-size: 12px;
  }
  .co-table th, .co-table td {
    padding: 8px 6px;
  }
}

/* ===== Order Edit Dialog ===== */
.oe-dialog {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Header */
.oe-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: linear-gradient(135deg, var(--color-primary-50, #eff6ff), var(--color-primary-100, #dbeafe));
  border-radius: 12px;
  border: 1px solid var(--color-primary-200, #bfdbfe);
}
.oe-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.oe-order-no {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-primary-700, #1d4ed8);
  letter-spacing: 0.02em;
}
.oe-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.oe-status-dot.co-status-pending { background: #f59e0b; }
.oe-status-dot.co-status-stocked { background: #22c55e; }
.oe-status-dot.co-status-partial { background: #3b82f6; }
.oe-status-dot.co-status-shipping { background: #6366f1; }
.oe-status-dot.co-status-shipped { background: #10b981; }
.oe-status-dot.co-status-cancelled { background: #ef4444; }
.oe-status-dot.co-status-completed { background: #8b5cf6; }
.oe-status-text {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}
.oe-date {
  font-size: 13px;
  color: var(--color-text-muted);
  font-weight: 500;
}

/* Section */
.oe-section {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 12px;
  overflow: hidden;
}
.oe-section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: var(--color-surface, #f8fafc);
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}
.oe-section-title i {
  color: var(--color-primary-500);
  font-size: 11px;
}

/* Info grid (readonly) */
.oe-info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
}
.oe-info-cell {
  padding: 10px 16px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}
.oe-info-cell:nth-child(odd) {
  border-right: 1px solid var(--color-border-light, #e2e8f0);
}
.oe-info-cell:nth-last-child(-n+2) {
  border-bottom: none;
}
.oe-info-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.oe-info-value {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text);
}
.oe-info-product {
  display: flex;
  align-items: center;
  gap: 8px;
}
.oe-product-thumb {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  object-fit: cover;
  flex-shrink: 0;
}
.oe-mono {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  letter-spacing: 0.02em;
}

/* SKU 明细表格（多 SKU 订单详情） */
.oe-sku-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.oe-sku-table thead th {
  padding: 8px 12px;
  text-align: left;
  font-weight: 600;
  font-size: 11px;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: var(--color-surface, #f8fafc);
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  white-space: nowrap;
}
.oe-sku-table tbody td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  color: var(--color-text);
  vertical-align: middle;
}
.oe-sku-table tbody tr:last-child td {
  border-bottom: none;
}
.oe-sku-table tbody tr:hover {
  background: var(--color-primary-50);
}
.oe-sku-product {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-weight: 500;
}
.oe-sku-barcode {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 10px;
  color: var(--color-text-muted);
  letter-spacing: 0.02em;
}
.oe-sku-note {
  color: var(--color-text-secondary);
  font-size: 11px;
  max-width: 160px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Editable section */
.oe-editable {
  border-color: var(--color-primary-200, #bfdbfe);
  background: linear-gradient(135deg, rgba(255,255,255,0.9), rgba(239,246,255,0.5));
}
.oe-editable .oe-section-title {
  background: linear-gradient(135deg, var(--color-primary-50, #eff6ff), rgba(219,234,254,0.5));
  color: var(--color-primary-600, #2563eb);
  border-bottom-color: var(--color-primary-200, #bfdbfe);
}
.oe-edit-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  padding: 16px;
}
.oe-edit-cell {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.oe-edit-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}
.oe-edit-control {
  display: flex;
  align-items: center;
  gap: 0;
  height: 40px;
}

/* Stepper (quantity) */
.oe-stepper-btn {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--color-border, #cbd5e1);
  background: var(--color-surface, #f8fafc);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 12px;
}
.oe-stepper-btn:first-child {
  border-radius: 10px 0 0 10px;
  border-right: none;
}
.oe-stepper-btn:last-child {
  border-radius: 0 10px 10px 0;
  border-left: none;
}
.oe-stepper-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  border-color: var(--color-primary-300);
}
.oe-stepper-input {
  width: 72px;
  height: 40px;
  text-align: center;
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text);
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: 0;
  outline: none;
  background: white;
  -moz-appearance: textfield;
  box-sizing: border-box;
}
.oe-stepper-input::-webkit-inner-spin-button,
.oe-stepper-input::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.oe-stepper-input:focus {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
  z-index: 1;
  position: relative;
}

/* Readonly value in edit area */
.oe-readonly-value {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text);
  padding: 8px 12px;
  background: var(--color-surface, #f1f5f9);
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  min-width: 60px;
  text-align: center;
}
.oe-readonly-hint {
  font-size: 10px;
  color: var(--color-text-muted);
  margin-left: 8px;
  font-style: italic;
}
.oe-available-hint {
  font-size: 11px;
  color: var(--color-success-600, #16a34a);
  margin-left: 10px;
  font-weight: 600;
  white-space: nowrap;
}

/* Textarea */
.oe-edit-full {
  padding: 0 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.oe-textarea {
  width: 100%;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.5;
  color: var(--color-text);
  background: white;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  outline: none;
  resize: vertical;
  font-family: inherit;
  box-sizing: border-box;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.oe-textarea::placeholder {
  color: var(--color-text-muted);
}
.oe-textarea:focus {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}

/* Responsive */
@media (max-width: 480px) {
  .oe-info-grid {
    grid-template-columns: 1fr;
  }
  .oe-info-cell:nth-child(odd) {
    border-right: none;
  }
  .oe-edit-grid {
    grid-template-columns: 1fr;
  }
  .oe-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }
}
</style>
