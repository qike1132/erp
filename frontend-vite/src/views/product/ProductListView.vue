<template>
  <div class="pd-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部 -->
      <div class="page-card-header">
        <HeaderTabs />
      </div>

      <!-- 双栏主体 -->
      <div class="page-card-body">
        <!-- 左栏：产品信息 -->
        <div class="pd-col">
          <div class="pd-col-title"><i class="fas fa-edit" aria-hidden="true"></i> 产品信息</div>
          <div class="pd-col-scroll">
            <!-- 产品基本信息 -->
            <div class="pd-section">
              <form @submit.prevent="handleAdd">
                <div class="pd-form-group">
                  <label class="pd-label">产品名称</label>
                  <div class="pd-input-wrap">
                    <i class="fas fa-tag pd-input-icon" aria-hidden="true"></i>
                    <input v-model="form.name" type="text" class="pd-input" required placeholder="例如：小熊毛绒玩具" name="product-name" autocomplete="off" />
                  </div>
                </div>
                <div class="pd-form-group">
                  <label class="pd-label">69码</label>
                  <div class="pd-input-wrap">
                    <i class="fas fa-barcode pd-input-icon" aria-hidden="true"></i>
                    <input v-model="form.barcode" type="text" class="pd-input" placeholder="例如：6958085574210" name="barcode" autocomplete="off" />
                  </div>
                </div>
                <div class="pd-form-group">
                  <label class="pd-label">产品价格</label>
                  <div class="pd-input-wrap">
                    <i class="fas fa-yen-sign pd-input-icon" aria-hidden="true"></i>
                    <input v-model.number="form.price" type="number" class="pd-input" step="0.01" min="0" placeholder="请输入产品价格" name="price" autocomplete="off" />
                  </div>
                </div>
                <div class="pd-form-group">
                  <label class="pd-label">工厂</label>
                  <div class="pd-input-wrap">
                    <i class="fas fa-industry pd-input-icon" aria-hidden="true"></i>
                    <select v-model="form.factory" class="pd-input pd-select" name="factory">
                      <option value="" disabled>请选择工厂</option>
                      <option v-for="f in FACTORY_OPTIONS" :key="f" :value="f">{{ f }}</option>
                    </select>
                  </div>
                </div>
                <div class="pd-form-group">
                  <label class="pd-label">产品图片</label>
                  <div
                    class="pd-section-header pd-droppable"
                    :class="{ 'pd-drag-over': imageDragOver }"
                    @click="imageInputRef?.click()"
                    @dragover.prevent="imageDragOver = true"
                    @dragleave="imageDragOver = false"
                    @drop.prevent="onImageDrop"
                  >
                    <label class="form-label pd-droppable-label">
                      <i class="fas fa-image label-icon" aria-hidden="true"></i>
                      <template v-if="form.image">
                        <span class="pd-file-inline pd-file-inline-success">
                          <img :src="resolveStaticUrl(form.image)" class="pd-thumb-preview" @click.stop="openImageModal(form.image)" />
                          <button type="button" class="pd-thumb-remove" @click.stop="form.image = ''" aria-label="关闭"><i class="fas fa-times" aria-hidden="true"></i></button>
                        </span>
                      </template>
                      <span v-else>拖拽文件到标题栏 · 支持 JPG / PNG / GIF</span>
                    </label>
                    <input ref="imageInputRef" type="file" style="display: none" accept="image/*" name="image" @change="onImageSelect" />
                  </div>
                </div>
              </form>
            </div>

            <!-- 产品上传管理 -->
            <div class="pd-section-label"><i class="fas fa-file-import" aria-hidden="true"></i> 批量导入</div>
            <div
              class="pd-section-header pd-droppable"
              :class="{ 'pd-drag-over': excelDragOver }"
              @click="excelInputRef?.click()"
              @dragover.prevent="excelDragOver = true"
              @dragleave="excelDragOver = false"
              @drop.prevent="onExcelDrop"
            >
              <label class="form-label pd-droppable-label">
                <i class="fas fa-file-excel label-icon" aria-hidden="true"></i>
                <span v-if="excelFile" class="pd-file-inline pd-file-inline-success"><i class="fas fa-file-excel" />{{ excelFile.name }}</span>
                <span v-else>拖拽文件到标题栏 · 支持 .xlsx / .xls</span>
              </label>
              <div class="pd-inline-actions">
                <button class="pd-inline-btn" @click.stop="downloadTemplate">模板</button>
                <button class="pd-inline-btn pd-inline-btn-success" :disabled="!excelFile" @click.stop="handleBatchImport">
                  {{ importing ? '导入中…' : '导入' }}
                </button>
              </div>
              <input ref="excelInputRef" type="file" style="display: none" accept=".xlsx,.xls" name="file" @change="onExcelSelect" />
            </div>

            <button type="button" class="pd-btn pd-btn-primary w-full justify-center" style="margin-top: 15px" :disabled="submitting" @click="handleAdd">
              <i class="fas fa-plus me-2" aria-hidden="true"></i>{{ submitting ? '添加中…' : '添加产品' }}
            </button>
          </div>
        </div>

        <!-- 右栏：产品列表 -->
        <div class="pd-col">
          <div class="pd-col-title">
            <span><i class="fas fa-list" aria-hidden="true"></i> 产品列表</span>
            <div class="pd-col-actions">
              <UiSearchInput :modelValue="searchTerm" placeholder="搜索产品名称或69码..." @search="onSearchInput" @update:modelValue="searchTerm = $event" />
              <select :value="`${sortBy}-${sortOrder}`" class="pd-sort" @change="onSortChange">
                <option value="name-asc">名称 A-Z</option>
                <option value="name-desc">名称 Z-A</option>
              </select>
            </div>
          </div>
          <div class="pd-col-scroll">
            <div class="pd-table-wrap">
              <table class="pd-table">
                <thead class="pd-thead">
                  <tr>
                    <th class="th-image">产品图片</th>
                    <th class="th-name">产品名称</th>
                    <th class="th-barcode">69码</th>
                    <th class="th-price">产品价格</th>
                    <th class="th-factory">工厂</th>
                    <th class="th-actions">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <template v-if="isLoading">
                    <tr><td colspan="6" class="text-center py-8"><div class="pd-loading"><UiSpinner /> 加载中…</div></td></tr>
                  </template>
                  <template v-else-if="paginatedProducts.length === 0">
                    <tr>
                      <td colspan="6" class="text-center py-8">
                        <div class="pd-empty">
                          <i class="fas fa-inbox pd-empty-icon" aria-hidden="true"></i>
                          <p class="pd-empty-text">{{ searchTerm ? '未找到匹配的产品' : '暂无产品，请先添加' }}</p>
                        </div>
                      </td>
                    </tr>
                  </template>
                  <template v-else>
                    <tr v-for="row in paginatedProducts" :key="row.id" class="pd-tr">
                      <td>
                        <div v-if="row.image && !failedImageIds.has(row.id)" class="pd-thumb-box" @click="openImageModal(row.image)">
                          <img :src="resolveStaticUrl(row.image)" class="pd-thumb-img" :alt="row.name" @error="handleImageError(row)" />
                        </div>
                        <div v-else class="pd-thumb-box">
                          <div class="pd-no-image"><i class="fas fa-image" aria-hidden="true"></i></div>
                        </div>
                      </td>
                      <td><span class="pd-name">{{ row.name }}</span></td>
                      <td><span class="pd-barcode">{{ row.barcode || '-' }}</span></td>
                      <td><span class="pd-price">{{ formatCurrency(row.price) }}</span></td>
                      <td><span class="pd-factory">{{ row.factory || '-' }}</span></td>
                      <td>
                        <div class="pd-actions">
                          <button class="pd-act-btn pd-act-bom" title="配置BOM表" @click="openBomModal(row)" aria-label="设置">
                            <i class="fas fa-cogs" aria-hidden="true"></i>
                          </button>
                          <button class="pd-act-btn pd-act-edit" title="编辑" @click="openEditModal(row)" aria-label="编辑">
                            <i class="fas fa-edit" aria-hidden="true"></i>
                          </button>
                          <button class="pd-act-btn pd-act-delete" title="删除" :disabled="actionId === row.id" @click="handleDelete(row)" aria-label="删除">
                            <i class="fas fa-trash" aria-hidden="true"></i>
                          </button>
                        </div>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>

            <!-- 分页 -->
            <UiPagination v-if="total > 20" :current-page="currentPage" :total-pages="totalPages" :total-items="total" @update:current-page="goToPage" />
          </div>
        </div>
      </div>
    </div>

    <!-- 图片查看模态框 -->
    <Teleport to="body">
      <div v-if="imageModalVisible" class="pd-overlay" @click.self="imageModalVisible = false">
        <div class="pd-modal pd-modal-img-dialog">
          <div class="pd-modal-header">
            <h5 class="pd-modal-title">产品图片</h5>
            <button class="pd-modal-close" @click="imageModalVisible = false" aria-label="关闭"><i class="fas fa-times" aria-hidden="true"></i></button>
          </div>
          <div class="pd-modal-body">
            <img :src="resolveStaticUrl(imageModalSrc)" class="pd-modal-img-view" />
          </div>
        </div>
      </div>
    </Teleport>

    <!-- BOM配置模态框 -->
    <Teleport to="body">
      <div v-if="bomDialogVisible" class="pd-overlay" @click.self="bomDialogVisible = false">
        <div class="bom-modal-content bom-modal-dialog">
          <div class="bom-modal-header">
            <div class="bom-modal-header-left">
              <h5 class="bom-modal-title"><i class="fas fa-cogs" aria-hidden="true"></i><span>BOM表配置 - {{ bomProductName }}</span></h5>
            </div>
            <button class="bom-modal-close" @click="bomDialogVisible = false" aria-label="关闭"><i class="fas fa-times" aria-hidden="true"></i></button>
          </div>
          <div class="bom-modal-body">
            <div class="bom-tabs-container">
              <button v-for="tab in bomTabs" :key="tab.key" class="bom-tab-v2" :class="{ active: currentBomCategory === tab.key }" @click="switchBomTab(tab.key)">
                <i :class="tab.icon" aria-hidden="true"></i> {{ tab.label }}
              </button>
            </div>
            <div class="bom-main-content">
              <div class="bom-summary-bar">
                <div class="bom-summary-left">
                  <span class="bom-summary-text"><i class="fas fa-list" aria-hidden="true"></i>{{ currentBomTabLabel }}物料清单</span>
                  <span class="bom-summary-count">物料总数：<span class="count-value">{{ currentBomItems.length }}</span></span>
                </div>
                <div class="bom-summary-center">
                  <div class="pd-input-wrap autocomplete-wrapper">
                    <UiAutocomplete
                      v-model="quickCopyKeyword"
                      :searchFn="searchProductsForBom"
                      placeholder="输入产品名称或条码，直接复制BOM"
                      @select="selectAutocompleteItem"
                    >
                      <template #option="{ item }">
                        <div class="flex items-center justify-between w-full gap-2">
                          <div class="flex-1 min-w-0">
                            <div class="product-name">{{ item.name }}</div>
                            <div class="product-info text-xs text-text-muted">{{ item.barcode ? '条码: ' + item.barcode : '' }}</div>
                          </div>
                          <span class="product-status text-xs" :class="item.has_bom ? 'has-bom' : 'no-bom'">
                            {{ item.has_bom ? '有BOM' : '无BOM' }}
                          </span>
                        </div>
                      </template>
                    </UiAutocomplete>
                  </div>
                </div>
                <div class="bom-summary-right">
                  <button class="bom-btn-copy-v2" :disabled="quickCopyLoading" @click="quickCopyBom"><i class="fas fa-copy" aria-hidden="true"></i>复制BOM</button>
                  <button class="bom-btn-add-v2" @click="addBomItem"><i class="fas fa-plus" aria-hidden="true"></i>添加物料</button>
                </div>
              </div>
              <div v-if="quickCopyProgress.visible" class="mb-3">
                <div class="pd-progress"><div class="pd-progress-bar" :style="{ width: quickCopyProgress.percent + '%' }"></div></div>
                <p class="pd-progress-text">{{ quickCopyProgress.text }}</p>
              </div>
              <div class="bom-content-area">
                <div v-if="currentBomItems.length > 0" class="bom-table-container-v2">
                  <div class="bom-table-wrapper-v2">
                    <table class="bom-table-v2">
                      <thead class="bom-table-header-v2">
                        <tr>
                          <th style="width:200px">物料名称 <span class="required">*</span></th>
                          <th style="width:180px">规格型号 <span class="required">*</span></th>
                          <th style="width:120px">计量单位 <span class="required">*</span></th>
                          <th style="width:200px">默认供应商 <span class="required">*</span></th>
                          <th style="width:140px">单SKU用量</th>
                          <th style="width:200px">备注</th>
                          <th style="width:80px">操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="(item, idx) in currentBomItems" :key="item.id ?? 'bom-' + idx">
                          <td><input v-model="item.name" type="text" class="bom-table-input" placeholder="输入物料名称" name="material-name" autocomplete="off" /></td>
                          <td><input v-model="item.specification" type="text" class="bom-table-input" placeholder="输入规格型号" name="specification" autocomplete="off" /></td>
                          <td>
                            <select v-model="item.unit" class="bom-table-select">
                              <option value="码">码</option><option value="克">克</option><option value="个">个</option>
                              <option value="件">件</option><option value="套">套</option><option value="米">米</option><option value="平方">平方</option>
                            </select>
                          </td>
                          <td><input v-model="item.supplier_name" type="text" class="bom-table-input" placeholder="输入供应商名称" name="supplier-name" autocomplete="off" /></td>
                          <td><input v-model.number="item.usage" type="number" class="bom-table-input" step="0.01" min="0" name="quantity" autocomplete="off" /></td>
                          <td><input v-model="item.remark" type="text" class="bom-table-input" placeholder="输入备注" name="remark" autocomplete="off" /></td>
                          <td><button class="bom-table-action-btn delete" @click="deleteBomItem(idx)" aria-label="删除"><i class="fas fa-trash" aria-hidden="true"></i></button></td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
                <div v-else class="bom-empty-state-v2">
                  <div class="bom-empty-icon"><i class="fas fa-inbox" aria-hidden="true"></i></div>
                  <div class="bom-empty-text">
                    <p class="bom-empty-title">暂无物料</p>
                    <p class="bom-empty-hint">点击"添加物料"按钮开始配置</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="bom-modal-footer">
            <button class="bom-btn-cancel" @click="bomDialogVisible = false">取消</button>
            <button class="bom-btn-save" @click="saveBom"><i class="fas fa-save" aria-hidden="true"></i>保存BOM</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 复制BOM模态框 -->
    <Teleport to="body">
      <div v-if="copyBomDialogVisible" class="pd-overlay" @click.self="copyBomDialogVisible = false">
        <div class="bom-modal-content copy-bom-modal-dialog">
          <div class="bom-modal-header">
            <div class="bom-modal-header-left">
              <h5 class="bom-modal-title"><i class="fas fa-copy" aria-hidden="true"></i><span>复制BOM表</span></h5>
            </div>
            <button class="bom-modal-close" @click="copyBomDialogVisible = false" aria-label="关闭"><i class="fas fa-times" aria-hidden="true"></i></button>
          </div>
          <div class="bom-modal-body">
            <div class="mb-4">
              <label class="pd-label mb-2"><i class="fas fa-search me-2" aria-hidden="true"></i>搜索源产品</label>
              <div class="pd-input-wrap">
                <i class="fas fa-tag pd-input-icon" aria-hidden="true"></i>
                <input v-model="copyBomSearchKeyword" type="text" class="pd-input" placeholder="输入产品名称或条码进行搜索" name="search" autocomplete="off" @keydown.enter="searchProductForCopy" />
              </div>
              <div class="mt-2"><button class="pd-btn pd-btn-primary pd-btn-sm" @click="searchProductForCopy"><i class="fas fa-search me-2" aria-hidden="true"></i>搜索</button></div>
            </div>
            <div v-if="copyBomProducts.length > 0" class="mb-4">
              <label class="pd-label mb-2"><i class="fas fa-box me-2" aria-hidden="true"></i>选择源产品</label>
              <div class="copy-bom-product-list">
                <div v-for="product in copyBomProducts" :key="product.id" class="copy-bom-product-item" :class="{ selected: copyBomSourceProductId === product.id }" @click="selectCopyBomProduct(product)">
                  <div>
                    <div class="product-name">{{ product.name }}</div>
                    <div class="product-barcode">{{ product.barcode ? '条码: ' + product.barcode : '' }}</div>
                  </div>
                  <span class="product-status" :class="product.has_bom ? 'has-bom' : 'no-bom'">{{ product.has_bom ? '有BOM' : '无BOM' }}</span>
                </div>
              </div>
            </div>
            <div v-if="copyBomPreview" class="mb-4">
              <div class="copy-bom-preview-card">
                <div class="preview-header">
                  <div>
                    <h6 class="mb-0">{{ copyBomPreview.source_name }}</h6>
                    <p class="text-muted text-sm mb-0">条码：{{ copyBomPreview.source_barcode || '-' }}</p>
                  </div>
                </div>
                <div class="preview-stats">
                  <div class="preview-stat-item"><div class="text-muted text-sm">物料总数</div><div class="text-2xl font-bold text-primary-500">{{ copyBomPreview.material_count }}</div></div>
                  <div class="preview-stat-item"><div class="text-muted text-sm">面料类</div><div class="text-2xl font-bold">{{ copyBomPreview.fabric_count }}</div></div>
                  <div class="preview-stat-item"><div class="text-muted text-sm">填充类</div><div class="text-2xl font-bold">{{ copyBomPreview.filling_count }}</div></div>
                  <div class="preview-stat-item"><div class="text-muted text-sm">辅料/包装</div><div class="text-2xl font-bold">{{ copyBomPreview.accessory_count }}</div></div>
                </div>
              </div>
              <div class="mb-4">
                <label class="form-check-label">
                  <input v-model="copyBomOverwrite" type="checkbox" class="form-check-input" />
                  <strong>覆盖现有BOM表</strong>
                  <span class="text-muted block text-sm">如果目标产品已有BOM表，勾选此项将覆盖原数据</span>
                </label>
              </div>
            </div>
            <div v-if="copyBomProgress.visible" class="mb-4">
              <div class="pd-progress"><div class="pd-progress-bar" :style="{ width: copyBomProgress.percent + '%' }"></div></div>
              <p class="pd-progress-text">{{ copyBomProgress.text }}</p>
            </div>
          </div>
          <div class="bom-modal-footer">
            <button class="bom-btn-cancel" @click="copyBomDialogVisible = false">取消</button>
            <button class="bom-btn-save" :disabled="!copyBomSourceProductId" @click="confirmCopyBom"><i class="fas fa-check me-2" aria-hidden="true"></i>确认复制</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 编辑产品模态框 -->
    <Teleport to="body">
      <div v-if="editDialogVisible" class="pd-overlay" @click.self="editDialogVisible = false">
        <div class="bom-modal-content edit-modal-dialog">
          <div class="bom-modal-header">
            <div class="bom-modal-header-left">
              <h5 class="bom-modal-title"><i class="fas fa-edit" aria-hidden="true"></i><span>编辑产品 - {{ editForm.name }}</span></h5>
            </div>
            <button class="bom-modal-close" @click="editDialogVisible = false" aria-label="关闭"><i class="fas fa-times" aria-hidden="true"></i></button>
          </div>
          <div class="bom-modal-body">
            <div class="edit-modal-content">
              <div class="pd-form-group">
                <label class="pd-label">产品名称 <span class="required">*</span></label>
                <div class="pd-input-wrap">
                  <i class="fas fa-tag pd-input-icon" aria-hidden="true"></i>
                  <input v-model="editForm.name" type="text" class="pd-input" required placeholder="请输入产品名称" name="product-name" autocomplete="off" />
                </div>
              </div>
              <div class="pd-form-group">
                <label class="pd-label">69码/商品条码</label>
                <div class="pd-input-wrap">
                  <i class="fas fa-barcode pd-input-icon" aria-hidden="true"></i>
                  <input v-model="editForm.barcode" type="text" class="pd-input" placeholder="例如：6958085574210" name="barcode" autocomplete="off" />
                </div>
              </div>
              <div class="pd-form-group">
                <label class="pd-label">产品价格</label>
                <div class="pd-input-wrap">
                  <i class="fas fa-yen-sign pd-input-icon" aria-hidden="true"></i>
                  <input v-model.number="editForm.price" type="number" class="pd-input" step="0.01" min="0" placeholder="请输入产品价格" name="price" autocomplete="off" />
                </div>
              </div>
              <div class="pd-form-group">
                <label class="pd-label">工厂</label>
                <div class="pd-input-wrap">
                  <i class="fas fa-industry pd-input-icon" aria-hidden="true"></i>
                  <select v-model="editForm.factory" class="pd-input pd-select" name="edit-factory">
                    <option value="" disabled>请选择工厂</option>
                    <option v-for="f in FACTORY_OPTIONS" :key="f" :value="f">{{ f }}</option>
                  </select>
                </div>
              </div>
              <div class="pd-form-group">
                <label class="pd-label">产品图片</label>
                <div
                  class="pd-section-header pd-droppable"
                  :class="{ 'pd-drag-over': editDragOver }"
                  @click="editImageInputRef?.click()"
                  @dragover.prevent="editDragOver = true"
                  @dragleave="editDragOver = false"
                  @drop.prevent="onEditDrop"
                >
                  <label class="form-label pd-droppable-label">
                    <i class="fas fa-image label-icon" aria-hidden="true"></i>
                    <template v-if="editForm.image">
                      <span class="pd-file-inline pd-file-inline-success">
                        <img :src="resolveStaticUrl(editForm.image)" class="pd-thumb-preview" @click.stop="openImageModal(editForm.image)" />
                        <button type="button" class="pd-thumb-remove" @click.stop="editForm.image = ''" aria-label="关闭"><i class="fas fa-times" aria-hidden="true"></i></button>
                      </span>
                    </template>
                    <span v-else>拖拽文件到标题栏 · 支持 JPG / PNG / GIF</span>
                  </label>
                  <input ref="editImageInputRef" type="file" style="display: none" accept="image/*" name="image" @change="onEditImageSelect" />
                </div>
              </div>
            </div>
          </div>
          <div class="bom-modal-footer">
            <button class="bom-btn-cancel" @click="editDialogVisible = false">取消</button>
            <button class="bom-btn-save" :disabled="editSubmitting" @click="handleEditSave">
              <i class="fas fa-save" aria-hidden="true"></i>{{ editSubmitting ? '保存中…' : '保存修改' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

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
import { ref, reactive, nextTick } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { productApi } from '@/api'
import type { ApiResponse } from '@/types'
import { upload, download, resolveStaticUrl } from '@/api/request'
import { uploadImage } from './composables/useImageUpload'
import { useProductListActions } from './composables/useProductListActions'
import { showToast } from '@/composables/useToast'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useEnhancedList } from '@/composables/useEnhancedList'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import { formatCurrency } from '@/utils/format'

interface Product {
  id: number
  name: string
  barcode: string
  price: number
  image: string | null
  factory?: string
  current_stock?: number
}

// 工厂下拉选项（与后端 VALID_FACTORIES 保持一致）
const FACTORY_OPTIONS = ['东莞', '湖北'] as const

// ===== 核心状态 =====
const actionId = ref<number | null>(null)
const queryClient = useQueryClient()
const confirmDialog = useConfirmDialog()

// 产品列表
const {
  items: paginatedProducts, total, page: currentPage, search: searchTerm,
  totalPages, isLoading, sortBy, sortOrder, handleSort,
  handlePageChange: goToPage, handleSearch: setSearchTerm,
} = useEnhancedList<Product>({
  key: 'products-list',
  url: '/products/list',
  perPage: 20,
  staleTime: 30_000,
})

function onSearchInput(e: Event) {
  setSearchTerm((e.target as HTMLInputElement).value)
}

function onSortChange(e: Event) {
  const val = (e.target as HTMLSelectElement).value
  const [field, order] = val.split('-')
  handleSort(field, order === 'asc' ? 'ascending' : 'descending')
}

// ===== 添加产品 =====
const submitting = ref(false)
const form = reactive({ name: '', barcode: '', price: 0, factory: '', image: '' })
const imageInputRef = ref<HTMLInputElement | null>(null)
const imageDragOver = ref(false)



function onImageSelect(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  uploadImageFile(file)
}

function onImageDrop(e: DragEvent) {
  imageDragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file) uploadImageFile(file)
}

function uploadImageFile(file: File) {
  uploadImage(file, (url) => { form.image = url })
}

async function handleAdd() {
  const trimmedName = form.name.trim()
  if (!trimmedName) return
  submitting.value = true
  try {
    await productApi.create({
      name: trimmedName,
      barcode: form.barcode || undefined,
      price: form.price ?? undefined,
      factory: form.factory || undefined,
      image: form.image || undefined,
    })
    showToast('添加成功', 'success')
    Object.assign(form, { name: '', barcode: '', price: 0, factory: '', image: '' })
    queryClient.invalidateQueries({ queryKey: ['products-list'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '添加失败', 'error')
  } finally {
    submitting.value = false
  }
}

// ===== 删除产品 =====
async function handleDelete(row: Product) {
  if (!(await confirmDialog.confirm(`确定要删除产品"${row.name}"吗？`))) return
  actionId.value = row.id
  try {
    await productApi.delete(row.id)
    showToast('删除成功', 'success')
    queryClient.invalidateQueries({ queryKey: ['products-list'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '删除失败', 'error')
  } finally {
    actionId.value = null
  }
}

// ===== 图片查看模态框 =====
const imageModalVisible = ref(false)
const imageModalSrc = ref('')
const failedImageIds = ref<Set<number>>(new Set())

function openImageModal(src: string) {
  imageModalSrc.value = src
  imageModalVisible.value = true
}

function handleImageError(row: Product) {
  failedImageIds.value = new Set(failedImageIds.value).add(row.id)
}

// ===== 编辑产品弹窗 =====
const editDialogVisible = ref(false)
const editSubmitting = ref(false)
const editForm = reactive({ id: 0, name: '', barcode: '', price: 0, factory: '', image: '' })
const editImageInputRef = ref<HTMLInputElement | null>(null)
const editDragOver = ref(false)

function openEditModal(row: Product) {
  Object.assign(editForm, { id: row.id, name: row.name, barcode: row.barcode, price: row.price, factory: row.factory || '', image: row.image || '' })
  editDialogVisible.value = true
}

function onEditImageSelect(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) uploadEditImage(file)
}
function onEditDrop(e: DragEvent) {
  editDragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file) uploadEditImage(file)
}

function uploadEditImage(file: File) {
  uploadImage(file, (url) => { editForm.image = url })
}

async function handleEditSave() {
  if (!editForm.name.trim()) { showToast('请输入产品名称', 'warning'); return }
  editSubmitting.value = true
  try {
    await productApi.update(editForm.id, { name: editForm.name, barcode: editForm.barcode, price: editForm.price, factory: editForm.factory, image: editForm.image })
    showToast('保存成功', 'success')
    editDialogVisible.value = false
    queryClient.invalidateQueries({ queryKey: ['products-list'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '保存失败', 'error')
  } finally {
    editSubmitting.value = false
  }
}

// ===== Excel批量导入 =====
const excelFile = ref<File | null>(null)
const excelInputRef = ref<HTMLInputElement | null>(null)
const excelDragOver = ref(false)
const importing = ref(false)

function onExcelSelect(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) handleExcelFile(file)
}
function onExcelDrop(e: DragEvent) {
  excelDragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file) handleExcelFile(file)
}

function handleExcelFile(file: File) {
  const name = file.name.toLowerCase()
  if (!name.endsWith('.xlsx') && !name.endsWith('.xls')) { showToast('请上传 Excel 文件（.xlsx 或 .xls）', 'error'); return }
  excelFile.value = file
}

async function handleBatchImport() {
  if (!excelFile.value) return
  importing.value = true
  const formData = new FormData()
  formData.append('file', excelFile.value)
  try {
    await upload('/batch/import-products', formData)
    showToast('导入成功', 'success')
    excelFile.value = null
    queryClient.invalidateQueries({ queryKey: ['products-list'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '导入失败', 'error')
  } finally {
    importing.value = false
  }
}

function downloadTemplate() {
  download('/batch/download-template', '产品导入模板.xlsx')
}

// ===== BOM 相关操作（抽离至 composable） =====
const {
  bomDialogVisible, bomProductName, currentBomCategory,
  bomTabs, currentBomItems, currentBomTabLabel,
  switchBomTab, openBomModal, addBomItem, deleteBomItem, saveBom,
  quickCopyKeyword, quickCopyLoading,
  quickCopyProgress,
  searchProductsForBom, selectAutocompleteItem, quickCopyBom,
  copyBomDialogVisible, copyBomSearchKeyword, copyBomProducts,
  copyBomSourceProductId, copyBomPreview, copyBomOverwrite, copyBomProgress,
  searchProductForCopy, selectCopyBomProduct, confirmCopyBom,
} = useProductListActions(confirmDialog)
</script>

<style scoped>
/* ===== 容器 ===== */
.pd-container {
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
.pd-card-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.pd-card-title-group h3 {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
  line-height: 1.3;
}
.pd-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin: 0;
  line-height: 1.4;
}

/* ===== 图标色块 ===== */
.pd-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}
.pd-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}
.pd-icon-green {
  background: linear-gradient(135deg, var(--color-success-100), var(--color-success-200));
  color: var(--color-success-700);
}

/* ===== 双栏主体 ===== */
/* 卡片主体样式已迁移到全局 .page-card-body（src/styles/app.css） */
/* 产品页需要 2 列网格布局，覆盖默认 page-card-body */
.page-card-body {
  display: grid;
  grid-template-columns: 1fr 2fr;
  overflow: hidden;
}

/* ===== 栏目 ===== */
.pd-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.pd-col + .pd-col {
  border-left: 1px solid var(--color-border-light, #f1f5f9);
}
.pd-col-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 20px;
  height: 52px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  flex-shrink: 0;
}
.pd-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}
.pd-col-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.pd-col-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

/* ===== 区块 ===== */
.pd-section {
  margin-bottom: 20px;
}


/* ===== 表单 ===== */
.pd-form-group {
  margin-bottom: 16px;
}
.pd-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
  line-height: 1.4;
}
.pd-input-wrap {
  position: relative;
}
.pd-input-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-secondary);
  font-size: 14px;
  z-index: 10;
  pointer-events: none;
}
.pd-input {
  width: 100%;
  padding: 8px 12px 8px 36px;
  font-size: 14px;
  line-height: 1.5;
  color: var(--color-text);
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
}
.pd-input:focus {
  background: white;
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.pd-select {
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
  padding-right: 32px;
  background-image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  background-size: 12px;
  cursor: pointer;
}
.pd-select:disabled { background-color: var(--color-surface, #f8fafc); cursor: not-allowed; }

/* ===== 按钮 ===== */
.pd-btn {
  padding: 7px 14px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 9px;
  border: 2px solid var(--color-border-light);
  background: white;
  transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  line-height: 1.4;
}
.pd-btn:hover { transform: translateY(-1px); }
.pd-btn:active { transform: translateY(0); }
.pd-btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
.pd-btn-primary {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600));
  color: white;
  border-color: var(--color-primary-500);
}
.pd-btn-primary:hover:not(:disabled) { box-shadow: 0 4px 12px rgba(59,130,246,0.3); }
.pd-btn-outline {
  background: white;
  color: var(--color-text-secondary);
  border-color: var(--color-border-light);
}
.pd-btn-outline:hover:not(:disabled) { background: var(--color-surface, #f8fafc); border-color: var(--color-border-light); }
.pd-btn-success {
  background: linear-gradient(135deg, var(--color-success-500), var(--color-success-600));
  color: white;
  border-color: var(--color-success-500);
}
.pd-btn-success:hover:not(:disabled) { box-shadow: 0 4px 12px rgba(34,197,94,0.3); }
.pd-btn-sm { padding: 5px 10px; font-size: 11px; }

/* ===== 上传区（droppable-header 风格） ===== */
.pd-section-header {
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
.pd-section-header:hover {
  border-color: var(--color-ocean-deep);
  background: var(--color-slate-50);
}
.pd-droppable { cursor: pointer; }
.pd-droppable.pd-drag-over {
  border-color: var(--color-success-400);
  background: var(--color-success-50);
}
.pd-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  padding: 8px 0 4px;
}
.pd-droppable-label {
  display: flex !important;
  margin-bottom: 0;
  cursor: pointer;
  font-size: 14px !important;
  font-weight: 400 !important;
  color: var(--color-text-muted) !important;
  align-items: center;
}
.pd-droppable-label .label-icon {
  color: var(--color-text-muted) !important;
}
.pd-inline-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.pd-inline-btn {
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
.pd-inline-btn:hover {
  border-color: var(--color-ocean-deep);
  color: var(--color-primary-600);
}
.pd-inline-btn-success {
  border-color: var(--color-success-400);
  color: var(--color-success-600);
}
.pd-inline-btn-success:hover {
  background: var(--color-success-50);
}
.pd-inline-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.pd-file-inline {
  font-size: 13px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.pd-file-inline-success {
  color: var(--color-success-600);
}
.pd-thumb-preview {
  height: 28px;
  width: 28px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--color-border-light);
}
.pd-thumb-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: none;
  background: rgba(0,0,0,0.4);
  color: white;
  font-size: 9px;
  cursor: pointer;
  margin-left: 2px;
  transition: background 0.2s ease;
}
.pd-thumb-remove:hover { background: rgba(0,0,0,0.7); }

/* ===== 搜索 & 排序 ===== */
.pd-search { position: relative; flex: 1; min-width: 180px; }
.pd-search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-secondary);
  font-size: 14px;
  z-index: 10;
  pointer-events: none;
}
.pd-search-input {
  width: 100%;
  padding: 8px 12px 8px 36px;
  font-size: 13px;
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
}
.pd-search-input:focus {
  background: white;
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.pd-sort {
  padding: 8px 12px;
  font-size: 13px;
  background: var(--color-surface, #f8fafc);
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  min-width: 120px;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
}
.pd-sort:focus {
  background: white;
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

/* ===== 表格 ===== */
.pd-table-wrap {
  overflow: hidden;
  border-radius: 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
}
.pd-table { width: 100%; border-collapse: collapse; }
.pd-thead { background: var(--color-surface, #f8fafc); }
.pd-thead th {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  letter-spacing: 0.05em;
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  line-height: 1.4;
  text-align: left;
}
.th-image { width: 100px; }
.th-name { width: auto; }
.th-actions { width: 140px; }
.th-barcode { width: 120px; }
.th-price { width: 100px; }
.th-factory { width: 100px; }
.pd-factory { font-size: 13px; font-weight: 500; color: var(--color-text); }
.pd-tr {
  transition: background 0.2s ease;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.pd-tr:hover { background: var(--color-primary-50); }
.pd-tr td {
  padding: 10px 14px;
  font-size: 13px;
  color: var(--color-text);
  line-height: 1.5;
  vertical-align: middle;
}
.pd-thumb-box {
  width: 60px;
  height: 60px;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
  background: var(--color-surface, #f8fafc);
  border: none;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.pd-thumb-box:hover { transform: scale(1.05); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
.pd-thumb-img { width: 100%; height: 100%; object-fit: contain; }
.pd-no-image {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-surface, #f8fafc);
  color: var(--color-text-secondary);
  font-size: 18px;
  opacity: 0.5;
}
.pd-name { font-size: 14px; font-weight: 500; color: var(--color-text); line-height: 1.5; }
.pd-barcode { font-size: 12px; color: var(--color-text-secondary); font-family: Consolas, Monaco, monospace; letter-spacing: 0.02em; }
.pd-price { font-size: 13px; font-weight: 600; color: var(--color-danger-500); }

/* ===== 操作按钮 ===== */
.pd-actions { display: flex; gap: 4px; }
.pd-act-btn {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: background 0.2s ease, transform 0.2s ease;
  cursor: pointer;
}
.pd-act-bom { background: var(--color-primary-50); color: var(--color-primary-600); }
.pd-act-bom:hover { background: var(--color-primary-100); transform: translateY(-1px); }
.pd-act-edit { background: var(--color-warning-50); color: var(--color-warning-600); }
.pd-act-edit:hover { background: var(--color-warning-100); transform: translateY(-1px); }
.pd-act-delete { background: var(--color-danger-50); color: var(--color-danger-500); }
.pd-act-delete:hover { background: var(--color-danger-100); transform: translateY(-1px); }

/* ===== 空状态 & 加载 ===== */
.pd-empty { padding: 40px 20px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 10px; }
.pd-empty-icon { font-size: 28px; color: var(--color-text-secondary); opacity: 0.5; }
.pd-empty-text { font-size: 14px; color: var(--color-text-secondary); margin: 0; }
.pd-loading { padding: 24px 0; text-align: center; color: var(--color-text-secondary); }

/* ===== 模态框遮罩 ===== */
.pd-overlay {
  position: fixed; inset: 0; z-index: 1050; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; padding: 16px;
}

/* ===== 图片模态框 ===== */
.pd-modal {
  border-radius: 18px; border: none; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);
  background: white; overflow: hidden;
}
.pd-modal-img-dialog { max-width: 90vw; width: 800px; }
.pd-modal-header {
  padding: 14px 20px; background: transparent;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  display: flex; justify-content: space-between; align-items: center;
}
.pd-modal-title { font-size: 14px; font-weight: 700; color: var(--color-text); }
.pd-modal-close {
  width: 32px; height: 32px; border-radius: 8px; border: none;
  background: var(--color-surface, #f8fafc); color: var(--color-text-secondary);
  display: flex; align-items: center; justify-content: center; font-size: 14px;
  transition: background 0.2s ease, color 0.2s ease; cursor: pointer;
}
.pd-modal-close:hover { background: var(--color-border-light, #e2e8f0); color: var(--color-text); }
.pd-modal-body {
  padding: 20px; background: var(--color-surface, #f8fafc);
  display: flex; align-items: center; justify-content: center; min-height: 50vh;
}
.pd-modal-img-view {
  max-width: 100%; max-height: 80vh; object-fit: contain;
  border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.15);
}

/* ===== BOM模态框 ===== */
.bom-modal-content {
  border-radius: 18px; border: none; box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  overflow: hidden; background: white;
}
.bom-modal-dialog { max-width: 1400px; width: 95vw; max-height: 90vh; display: flex; flex-direction: column; }
.copy-bom-modal-dialog { max-width: 1200px; width: 90vw; max-height: 90vh; display: flex; flex-direction: column; }
.bom-modal-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 20px 28px; background: transparent;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}
.bom-modal-header-left { flex: 1; }
.bom-modal-title {
  display: flex; align-items: center; gap: 10px;
  font-size: 16px; font-weight: 700; color: var(--color-text); margin: 0;
}
.bom-modal-title i { color: var(--color-primary-500); }
.bom-modal-close {
  width: 36px; height: 36px; border: none; background: var(--color-surface, #f8fafc);
  border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center;
  color: var(--color-text-secondary); font-size: 16px; transition: background 0.3s ease, color 0.3s ease, transform 0.3s ease;
}
.bom-modal-close:hover { background: var(--color-border-light, #e2e8f0); color: var(--color-text); transform: rotate(90deg); }
.bom-modal-body { padding: 0; background: var(--color-surface, #f8fafc); min-height: 500px; overflow-y: auto; flex: 1; }
.bom-tabs-container {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}
.bom-tab-v2 {
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  display: flex;
  align-items: center;
  gap: 6px;
}
.bom-tab-v2:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.bom-tab-v2.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}
.bom-main-content { padding: 20px 28px 28px; }
.bom-summary-bar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 20px; background: white; border-radius: 12px;
  border: 1px solid var(--color-primary-200); margin-bottom: 20px; gap: 12px; flex-wrap: wrap;
}
.bom-summary-left { display: flex; align-items: center; gap: 20px; }
.bom-summary-text { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; color: var(--color-text); }
.bom-summary-text i { color: var(--color-primary-500); }
.bom-summary-count { font-size: 13px; color: var(--color-text-secondary); }
.count-value { font-size: 18px; font-weight: 700; color: var(--color-primary-600); }
.bom-summary-center { flex: 1; max-width: 360px; margin: 0 16px; position: relative; }
.bom-summary-right { display: flex; gap: 8px; }
.bom-btn-add-v2 {
  padding: 10px 20px; background: var(--color-success-50); color: var(--color-success-600);
  border: 2px solid var(--color-success-200); border-radius: 10px; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: transform 0.3s ease, box-shadow 0.3s ease; display: flex; align-items: center; gap: 6px;
}
.bom-btn-add-v2:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(34,197,94,0.2); }
.bom-btn-copy-v2 {
  padding: 10px 20px; background: var(--color-primary-50); color: var(--color-primary-600);
  border: 2px solid var(--color-primary-200); border-radius: 10px; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: transform 0.3s ease, box-shadow 0.3s ease; display: flex; align-items: center; gap: 6px;
}
.bom-btn-copy-v2:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(59,130,246,0.2); }
.bom-btn-copy-v2:disabled { opacity: 0.4; cursor: not-allowed; transform: none; box-shadow: none; }

/* BOM内容区 */
.bom-content-area { background: white; border-radius: 12px; border: 1px solid var(--color-border-light, #e2e8f0); overflow: hidden; }
.bom-table-container-v2 { display: block; }
.bom-table-wrapper-v2 { overflow-x: auto; }
.bom-table-v2 { width: 100%; border-collapse: collapse; min-width: 1100px; }
.bom-table-header-v2 { background: var(--color-surface, #f8fafc); }
.bom-table-header-v2 th {
  padding: 12px 16px; text-align: left; font-size: 12px; font-weight: 600;
  color: var(--color-text); border-bottom: 2px solid var(--color-primary-200); white-space: nowrap;
}
.bom-table-header-v2 th .required { color: var(--color-danger-500); font-weight: 700; }
.bom-table-v2 tbody tr { transition: background-color 0.2s ease; }
.bom-table-v2 tbody tr:hover { background-color: var(--color-primary-50); }
.bom-table-v2 tbody td { padding: 10px 16px; border-bottom: 1px solid var(--color-border-light, #f1f5f9); vertical-align: middle; }
.bom-table-input {
  width: 100%; padding: 6px 10px; border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px; font-size: 13px; transition: border-color 0.2s ease, box-shadow 0.2s ease; outline: none;
}
.bom-table-input:focus { border-color: var(--color-primary-400); box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1); }
.bom-table-select {
  width: 100%; padding: 6px 10px; border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px; font-size: 13px; background: white; cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease; outline: none;
}
.bom-table-select:focus { border-color: var(--color-primary-400); box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1); }
.bom-table-action-btn { padding: 5px 8px; border: none; border-radius: 6px; cursor: pointer; font-size: 12px; transition: transform 0.2s ease, box-shadow 0.2s ease; }
.bom-table-action-btn.delete { background: var(--color-danger-50); color: var(--color-danger-600); }
.bom-table-action-btn.delete:hover { transform: translateY(-1px); box-shadow: 0 2px 8px rgba(229,115,115,0.3); }
.bom-empty-state-v2 { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 60px 20px; text-align: center; }
.bom-empty-icon { margin-bottom: 16px; }
.bom-empty-icon i { font-size: 48px; color: var(--color-text-secondary); opacity: 0.4; }
.bom-empty-text { display: flex; flex-direction: column; gap: 6px; }
.bom-empty-title { font-size: 16px; font-weight: 600; color: var(--color-text); margin: 0; }
.bom-empty-hint { font-size: 13px; color: var(--color-text-secondary); margin: 0; }

/* BOM底部按钮 */
.bom-modal-footer {
  display: flex; justify-content: flex-end; align-items: center; gap: 10px;
  padding: 20px 28px; background: white;
  border-top: 1px solid var(--color-border-light, #e2e8f0);
}
.bom-btn-cancel {
  padding: 10px 20px; background: white; color: var(--color-text);
  border: 2px solid var(--color-border-light, #e2e8f0); border-radius: 10px;
  font-size: 13px; font-weight: 600; cursor: pointer; transition: background 0.3s ease, transform 0.3s ease;
}
.bom-btn-cancel:hover { background: var(--color-surface, #f8fafc); transform: translateY(-1px); }
.bom-btn-save {
  padding: 10px 20px; background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600));
  color: white; border: 2px solid var(--color-primary-500); border-radius: 10px;
  font-size: 13px; font-weight: 600; cursor: pointer; transition: transform 0.3s ease, box-shadow 0.3s ease;
  display: flex; align-items: center; gap: 6px;
}
.bom-btn-save:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(59,130,246,0.3); }
.bom-btn-save:disabled { opacity: 0.4; cursor: not-allowed; }

/* 进度条 */
.pd-progress { height: 16px; border-radius: 8px; background: var(--color-border-light, #e2e8f0); overflow: hidden; }
.pd-progress-bar { height: 100%; background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600)); border-radius: 8px; transition: width 0.3s ease; }
.pd-progress-text { margin-top: 6px; font-size: 12px; color: var(--color-text-secondary); text-align: center; }

/* 自动补全 */
.autocomplete-wrapper { position: relative; }
.autocomplete-dropdown {
  position: absolute; top: 100%; left: 0; right: 0; z-index: 1060;
  background: white; border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px; box-shadow: 0 10px 40px rgba(0,0,0,0.12);
  margin-top: 6px; max-height: 260px; overflow-y: auto;
}
.autocomplete-item {
  padding: 10px 14px; display: flex; justify-content: space-between; align-items: center;
  cursor: pointer; transition: background 0.2s ease;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.autocomplete-item:last-child { border-bottom: none; }
.autocomplete-item:hover:not(.disabled) { background: var(--color-surface, #f8fafc); }
.autocomplete-item.selected { background: var(--color-primary-50); }
.autocomplete-item.disabled { opacity: 0.5; cursor: not-allowed; }
.autocomplete-item .item-left { flex: 1; min-width: 0; }
.autocomplete-item .product-name { font-size: 13px; font-weight: 500; color: var(--color-text); line-height: 1.4; margin-bottom: 2px; }
.autocomplete-item .product-info { font-size: 11px; color: var(--color-text-secondary); }
.autocomplete-item .item-right { flex-shrink: 0; margin-left: 10px; }
.autocomplete-item .product-status { font-size: 11px; padding: 3px 8px; border-radius: 6px; font-weight: 500; }
.autocomplete-item .product-status.has-bom { background: var(--color-success-50); color: var(--color-success-600); }
.autocomplete-item .product-status.no-bom { background: var(--color-danger-50); color: var(--color-danger-500); }

/* 复制BOM模态框 */
.copy-bom-product-list { max-height: 200px; overflow-y: auto; }
.copy-bom-product-item {
  padding: 10px 14px; border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px; margin-bottom: 6px; cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease; display: flex; justify-content: space-between; align-items: center;
}
.copy-bom-product-item:hover { border-color: var(--color-primary-300); background: var(--color-primary-50); }
.copy-bom-product-item.selected { border-color: var(--color-success-500); background: var(--color-success-50); }
.copy-bom-product-item .product-name { font-weight: 600; color: var(--color-text); }
.copy-bom-product-item .product-barcode { font-size: 11px; color: var(--color-text-secondary); }
.copy-bom-product-item .product-status { font-size: 11px; padding: 3px 8px; border-radius: 16px; }
.copy-bom-product-item .product-status.has-bom { background: var(--color-success-50); color: var(--color-success-600); }
.copy-bom-product-item .product-status.no-bom { background: var(--color-warning-50); color: var(--color-warning-600); }
.copy-bom-preview-card {
  border: 1px solid var(--color-primary-100); background: var(--color-primary-50);
  border-radius: 12px; padding: 16px; margin-bottom: 12px;
}
.preview-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.preview-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 8px; }
.preview-stat-item { padding: 10px; background: white; border-radius: 10px; border: 1px solid var(--color-border-light, #e2e8f0); }

/* ===== 工具类 ===== */
.text-muted { color: var(--color-text-secondary); }
.form-check-input { width: 1.125rem; height: 1.125rem; margin-right: 0.5rem; }
.form-check-label { display: flex; align-items: flex-start; gap: 0.5rem; }
.edit-modal-content { padding: 20px; }

/* ===== 响应式 ===== */
@media (max-width: 1199.98px) {
  .page-card-body { grid-template-columns: 1fr; }
  .pd-col + .pd-col { border-left: none; border-top: 1px solid var(--color-border-light, #f1f5f9); }
}
</style>
