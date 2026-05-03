<template>
  <div class="pd-container">
    <div class="pd-card pd-card-main">
      <!-- 卡片头部 -->
      <div class="pd-card-header">
        <HeaderTabs />
      </div>

      <!-- 双栏主体 -->
      <div class="pd-body">
        <!-- 左栏：产品信息 -->
        <div class="pd-col">
          <div class="pd-col-title"><i class="fas fa-edit"></i> 产品信息</div>
          <div class="pd-col-scroll">
            <!-- 产品基本信息 -->
            <div class="pd-section">
              <div class="pd-section-header">
                <h4 class="pd-section-title">产品基本信息</h4>
              </div>
              <form @submit.prevent="handleAdd">
                <div class="pd-form-group">
                  <label class="pd-label">产品名称</label>
                  <div class="pd-input-wrap">
                    <i class="fas fa-tag pd-input-icon"></i>
                    <input v-model="form.name" type="text" class="pd-input" required placeholder="例如：小熊毛绒玩具" />
                  </div>
                </div>
                <div class="pd-form-group">
                  <label class="pd-label">69码</label>
                  <div class="pd-input-wrap">
                    <i class="fas fa-barcode pd-input-icon"></i>
                    <input v-model="form.barcode" type="text" class="pd-input" placeholder="例如：6958085574210" />
                  </div>
                </div>
                <div class="pd-form-group">
                  <label class="pd-label">产品价格</label>
                  <div class="pd-input-wrap">
                    <i class="fas fa-yen-sign pd-input-icon"></i>
                    <input v-model.number="form.price" type="number" class="pd-input" step="0.01" min="0" placeholder="请输入产品价格" />
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
                      <i class="fas fa-image label-icon"></i>
                      <template v-if="form.image">
                        <span class="pd-file-inline pd-file-inline-success">
                          <img :src="resolveStaticUrl(form.image)" class="pd-thumb-preview" @click.stop="openImageModal(form.image)" />
                          <button type="button" class="pd-thumb-remove" @click.stop="form.image = ''"><i class="fas fa-times"></i></button>
                        </span>
                      </template>
                      <span v-else>拖拽文件到标题栏 · 支持 JPG / PNG / GIF</span>
                    </label>
                    <input ref="imageInputRef" type="file" style="display: none" accept="image/*" @change="onImageSelect" />
                  </div>
                </div>
              </form>
            </div>

            <!-- 产品上传管理 -->
            <div class="pd-section-label"><i class="fas fa-file-import"></i> 批量导入</div>
            <div
              class="pd-section-header pd-droppable"
              :class="{ 'pd-drag-over': excelDragOver }"
              @click="excelInputRef?.click()"
              @dragover.prevent="excelDragOver = true"
              @dragleave="excelDragOver = false"
              @drop.prevent="onExcelDrop"
            >
              <label class="form-label pd-droppable-label">
                <i class="fas fa-file-excel label-icon"></i>
                <span v-if="excelFile" class="pd-file-inline pd-file-inline-success"><i class="fas fa-file-excel" />{{ excelFile.name }}</span>
                <span v-else>拖拽文件到标题栏 · 支持 .xlsx / .xls</span>
              </label>
              <div class="pd-inline-actions">
                <button class="pd-inline-btn" @click.stop="downloadTemplate">模板</button>
                <button class="pd-inline-btn pd-inline-btn-success" :disabled="!excelFile" @click.stop="handleBatchImport">
                  {{ importing ? '导入中...' : '导入' }}
                </button>
              </div>
              <input ref="excelInputRef" type="file" style="display: none" accept=".xlsx,.xls" @change="onExcelSelect" />
            </div>

            <button type="button" class="pd-btn pd-btn-primary pd-w-full" style="margin-top: 15px" :disabled="submitting" @click="handleAdd">
              <i class="fas fa-plus me-2"></i>{{ submitting ? '添加中...' : '添加产品' }}
            </button>
          </div>
        </div>

        <!-- 右栏：产品列表 -->
        <div class="pd-col">
          <div class="pd-col-title">
            <span><i class="fas fa-list"></i> 产品列表</span>
            <div class="pd-col-actions">
              <div class="pd-search">
                <i class="fas fa-search pd-search-icon"></i>
                <input v-model="searchTerm" type="text" class="pd-search-input" placeholder="搜索产品名称或69码..." />
              </div>
              <select v-model="sortOrder" class="pd-sort">
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
                    <th class="th-actions">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <template v-if="isLoading">
                    <tr><td colspan="5" class="text-center py-8"><div class="pd-loading"><i class="fas fa-spinner fa-spin"></i> 加载中...</div></td></tr>
                  </template>
                  <template v-else-if="paginatedProducts.length === 0">
                    <tr>
                      <td colspan="5" class="text-center py-8">
                        <div class="pd-empty">
                          <i class="fas fa-inbox pd-empty-icon"></i>
                          <p class="pd-empty-text">{{ searchTerm ? '未找到匹配的产品' : '暂无产品，请先添加' }}</p>
                        </div>
                      </td>
                    </tr>
                  </template>
                  <template v-else>
                    <tr v-for="(row, idx) in paginatedProducts" :key="row.id" class="pd-tr" :style="{ animationDelay: `${idx * 0.05}s` }">
                      <td>
                        <div v-if="row.image" class="pd-thumb-box" @click="openImageModal(row.image)">
                          <img :src="resolveStaticUrl(row.image)" class="pd-thumb-img" :alt="row.name" @error="handleImageError($event)" />
                        </div>
                        <div v-else class="pd-thumb-box">
                          <div class="pd-no-image"><i class="fas fa-image"></i></div>
                        </div>
                      </td>
                      <td><span class="pd-name">{{ row.name }}</span></td>
                      <td><span class="pd-barcode">{{ row.barcode || '-' }}</span></td>
                      <td><span class="pd-price">{{ row.price ? `¥${row.price.toFixed(2)}` : '¥0.00' }}</span></td>
                      <td>
                        <div class="pd-actions">
                          <button class="pd-act-btn pd-act-bom" title="配置BOM表" @click="openBomModal(row)">
                            <i class="fas fa-cogs"></i>
                          </button>
                          <button class="pd-act-btn pd-act-edit" title="编辑" @click="openEditModal(row)">
                            <i class="fas fa-edit"></i>
                          </button>
                          <button class="pd-act-btn pd-act-delete" title="删除" :disabled="actionId === row.id" @click="handleDelete(row)">
                            <i class="fas fa-trash"></i>
                          </button>
                        </div>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>

            <!-- 分页 -->
            <div v-if="filteredProducts.length > itemsPerPage" class="pd-pagi-wrap">
              <div class="pd-pagi-inner">
                <div class="pd-pagi-info">显示 {{ paginationStart }}-{{ paginationEnd }} 条，共 {{ filteredProducts.length }} 条</div>
                <nav>
                  <ul class="pd-pagi">
                    <li class="page-item" :class="{ disabled: currentPage === 1 }">
                      <a class="page-link" href="#" @click.prevent="currentPage > 1 && (currentPage--)"><i class="fas fa-chevron-left"></i></a>
                    </li>
                    <li v-for="p in visiblePages" :key="p" class="page-item" :class="{ active: p === currentPage, disabled: p === '...' }">
                      <a v-if="typeof p === 'number'" class="page-link" href="#" @click.prevent="goToPage(p)">{{ p }}</a>
                      <span v-else class="page-link">...</span>
                    </li>
                    <li class="page-item" :class="{ disabled: currentPage === totalPages }">
                      <a class="page-link" href="#" @click.prevent="currentPage < totalPages && (currentPage++)"><i class="fas fa-chevron-right"></i></a>
                    </li>
                  </ul>
                </nav>
              </div>
            </div>
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
            <button class="pd-modal-close" @click="imageModalVisible = false"><i class="fas fa-times"></i></button>
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
              <h5 class="bom-modal-title"><i class="fas fa-cogs"></i><span>BOM表配置 - {{ bomProductName }}</span></h5>
            </div>
            <button class="bom-modal-close" @click="bomDialogVisible = false"><i class="fas fa-times"></i></button>
          </div>
          <div class="bom-modal-body">
            <div class="bom-tabs-container">
              <button v-for="tab in bomTabs" :key="tab.key" class="bom-tab-v2" :class="{ active: currentBomCategory === tab.key }" @click="switchBomTab(tab.key)">
                <i :class="tab.icon"></i> {{ tab.label }}
              </button>
            </div>
            <div class="bom-main-content">
              <div class="bom-summary-bar">
                <div class="bom-summary-left">
                  <span class="bom-summary-text"><i class="fas fa-list"></i>{{ currentBomTabLabel }}物料清单</span>
                  <span class="bom-summary-count">物料总数：<span class="count-value">{{ currentBomItems.length }}</span></span>
                </div>
                <div class="bom-summary-center">
                  <div class="pd-input-wrap autocomplete-wrapper">
                    <i class="fas fa-search pd-input-icon"></i>
                    <input ref="quickCopyInputRef" v-model="quickCopyKeyword" type="text" class="pd-input" placeholder="输入产品名称或条码，直接复制BOM" autocomplete="off" @keydown="onAutocompleteKeydown" @focus="onQuickCopyFocus" @blur="hideAutocomplete" />
                    <div v-if="autocompleteVisible && autocompleteItems.length > 0" class="autocomplete-dropdown">
                      <div v-for="(item, aIdx) in autocompleteItems" :key="item.id" class="autocomplete-item" :class="{ selected: aIdx === autocompleteIndex, disabled: !item.has_bom }" @click="selectAutocompleteItem(item)">
                        <div class="item-left">
                          <div class="product-name">{{ item.name }}</div>
                          <div class="product-info">{{ item.barcode ? '条码: ' + item.barcode : '' }}</div>
                        </div>
                        <div class="item-right">
                          <span class="product-status" :class="item.has_bom ? 'has-bom' : 'no-bom'">{{ item.has_bom ? '有BOM' : '无BOM' }}</span>
                        </div>
                      </div>
                    </div>
                    <div v-if="autocompleteVisible && autocompleteItems.length === 0 && quickCopyKeyword.length >= 1" class="autocomplete-dropdown">
                      <div class="autocomplete-item" style="cursor:default;opacity:0.6"><div class="item-left"><div class="product-name">未找到匹配的产品</div></div></div>
                    </div>
                  </div>
                </div>
                <div class="bom-summary-right">
                  <button class="bom-btn-copy-v2" :disabled="quickCopyLoading" @click="quickCopyBom"><i class="fas fa-copy"></i>复制BOM</button>
                  <button class="bom-btn-add-v2" @click="addBomItem"><i class="fas fa-plus"></i>添加物料</button>
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
                        <tr v-for="(item, idx) in currentBomItems" :key="idx">
                          <td><input v-model="item.name" type="text" class="bom-table-input" placeholder="输入物料名称" /></td>
                          <td><input v-model="item.specification" type="text" class="bom-table-input" placeholder="输入规格型号" /></td>
                          <td>
                            <select v-model="item.unit" class="bom-table-select">
                              <option value="码">码</option><option value="克">克</option><option value="个">个</option>
                              <option value="件">件</option><option value="套">套</option><option value="米">米</option><option value="平方">平方</option>
                            </select>
                          </td>
                          <td><input v-model="item.supplier_name" type="text" class="bom-table-input" placeholder="输入供应商名称" /></td>
                          <td><input v-model.number="item.usage" type="number" class="bom-table-input" step="0.01" min="0" /></td>
                          <td><input v-model="item.remark" type="text" class="bom-table-input" placeholder="输入备注" /></td>
                          <td><button class="bom-table-action-btn delete" @click="deleteBomItem(idx)"><i class="fas fa-trash"></i></button></td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
                <div v-else class="bom-empty-state-v2">
                  <div class="bom-empty-icon"><i class="fas fa-inbox"></i></div>
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
            <button class="bom-btn-save" @click="saveBom"><i class="fas fa-save"></i>保存BOM</button>
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
              <h5 class="bom-modal-title"><i class="fas fa-copy"></i><span>复制BOM表</span></h5>
            </div>
            <button class="bom-modal-close" @click="copyBomDialogVisible = false"><i class="fas fa-times"></i></button>
          </div>
          <div class="bom-modal-body">
            <div class="mb-4">
              <label class="pd-label mb-2"><i class="fas fa-search me-2"></i>搜索源产品</label>
              <div class="pd-input-wrap">
                <i class="fas fa-tag pd-input-icon"></i>
                <input v-model="copyBomSearchKeyword" type="text" class="pd-input" placeholder="输入产品名称或条码进行搜索" @keydown.enter="searchProductForCopy" />
              </div>
              <div class="mt-2"><button class="pd-btn pd-btn-primary pd-btn-sm" @click="searchProductForCopy"><i class="fas fa-search me-2"></i>搜索</button></div>
            </div>
            <div v-if="copyBomProducts.length > 0" class="mb-4">
              <label class="pd-label mb-2"><i class="fas fa-box me-2"></i>选择源产品</label>
              <div class="copy-bom-product-list">
                <div v-for="p in copyBomProducts" :key="p.id" class="copy-bom-product-item" :class="{ selected: copyBomSourceProductId === p.id }" @click="selectCopyBomProduct(p)">
                  <div>
                    <div class="product-name">{{ p.name }}</div>
                    <div class="product-barcode">{{ p.barcode ? '条码: ' + p.barcode : '' }}</div>
                  </div>
                  <span class="product-status" :class="p.has_bom ? 'has-bom' : 'no-bom'">{{ p.has_bom ? '有BOM' : '无BOM' }}</span>
                </div>
              </div>
            </div>
            <div v-if="copyBomPreview" class="mb-4">
              <div class="copy-bom-preview-card">
                <div class="preview-header">
                  <div>
                    <h6 class="mb-0">{{ copyBomPreview.source_name }}</h6>
                    <p class="text-muted small mb-0">条码：{{ copyBomPreview.source_barcode || '-' }}</p>
                  </div>
                </div>
                <div class="preview-stats">
                  <div class="preview-stat-item"><div class="text-muted small">物料总数</div><div class="fs-4 fw-bold text-primary">{{ copyBomPreview.material_count }}</div></div>
                  <div class="preview-stat-item"><div class="text-muted small">面料类</div><div class="fs-4 fw-bold">{{ copyBomPreview.fabric_count }}</div></div>
                  <div class="preview-stat-item"><div class="text-muted small">填充类</div><div class="fs-4 fw-bold">{{ copyBomPreview.filling_count }}</div></div>
                  <div class="preview-stat-item"><div class="text-muted small">辅料/包装</div><div class="fs-4 fw-bold">{{ copyBomPreview.accessory_count }}</div></div>
                </div>
              </div>
              <div class="mb-4">
                <label class="form-check-label">
                  <input v-model="copyBomOverwrite" type="checkbox" class="form-check-input" />
                  <strong>覆盖现有BOM表</strong>
                  <span class="text-muted d-block small">如果目标产品已有BOM表，勾选此项将覆盖原数据</span>
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
            <button class="bom-btn-save" :disabled="!copyBomSourceProductId" @click="confirmCopyBom"><i class="fas fa-check me-2"></i>确认复制</button>
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
              <h5 class="bom-modal-title"><i class="fas fa-edit"></i><span>编辑产品 - {{ editForm.name }}</span></h5>
            </div>
            <button class="bom-modal-close" @click="editDialogVisible = false"><i class="fas fa-times"></i></button>
          </div>
          <div class="bom-modal-body">
            <div class="edit-modal-content">
              <div class="pd-form-group">
                <label class="pd-label">产品名称 <span class="required">*</span></label>
                <div class="pd-input-wrap">
                  <i class="fas fa-tag pd-input-icon"></i>
                  <input v-model="editForm.name" type="text" class="pd-input" required placeholder="请输入产品名称" />
                </div>
              </div>
              <div class="pd-form-group">
                <label class="pd-label">69码/商品条码</label>
                <div class="pd-input-wrap">
                  <i class="fas fa-barcode pd-input-icon"></i>
                  <input v-model="editForm.barcode" type="text" class="pd-input" placeholder="例如：6958085574210" />
                </div>
              </div>
              <div class="pd-form-group">
                <label class="pd-label">产品价格</label>
                <div class="pd-input-wrap">
                  <i class="fas fa-yen-sign pd-input-icon"></i>
                  <input v-model.number="editForm.price" type="number" class="pd-input" step="0.01" min="0" placeholder="请输入产品价格" />
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
                    <i class="fas fa-image label-icon"></i>
                    <template v-if="editForm.image">
                      <span class="pd-file-inline pd-file-inline-success">
                        <img :src="resolveStaticUrl(editForm.image)" class="pd-thumb-preview" @click.stop="openImageModal(editForm.image)" />
                        <button type="button" class="pd-thumb-remove" @click.stop="editForm.image = ''"><i class="fas fa-times"></i></button>
                      </span>
                    </template>
                    <span v-else>拖拽文件到标题栏 · 支持 JPG / PNG / GIF</span>
                  </label>
                  <input ref="editImageInputRef" type="file" style="display: none" accept="image/*" @change="onEditImageSelect" />
                </div>
              </div>
            </div>
          </div>
          <div class="bom-modal-footer">
            <button class="bom-btn-cancel" @click="editDialogVisible = false">取消</button>
            <button class="bom-btn-save" :disabled="editSubmitting" @click="handleEditSave">
              <i class="fas fa-save"></i>{{ editSubmitting ? '保存中...' : '保存修改' }}
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
import { ref, reactive, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { productApi } from '@/api'
import { upload, download, resolveStaticUrl } from '@/api/request'
import { showToast } from '@/composables/useToast'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'

interface Product {
  id: number
  name: string
  barcode: string
  price: number
  image: string | null
  current_stock?: number
}

interface BomItem {
  id?: number
  name: string
  specification: string
  unit: string
  supplier_id?: number | null
  supplier_name: string
  usage: number
  remark: string
  category?: string
}

// ===== 核心状态 =====
const actionId = ref<number | ''>(0)
const queryClient = useQueryClient()
const confirmDialog = useConfirmDialog()

// 产品列表
const currentPage = ref(1)
const total = ref(0)
const itemsPerPage = 10

const { data: result, isLoading } = useQuery({
  queryKey: ['products-list', currentPage],
  queryFn: async () => {
    const res = (await productApi.list({ page: currentPage.value, per_page: 20 })) as any
    total.value = res.total ?? 0
    return res
  },
  staleTime: 30_000,
})

const products = computed<Product[]>(() => result.value?.data ?? result.value?.products ?? [])

// 搜索和排序
const searchTerm = ref('')
const sortOrder = ref('name-asc')
const filteredProducts = computed(() => {
  let list = products.value
  if (searchTerm.value) {
    const q = searchTerm.value.toLowerCase()
    list = list.filter(p => p.name.toLowerCase().includes(q) || (p.barcode || '').toLowerCase().includes(q))
  }
  return [...list].sort((a, b) => {
    if (sortOrder.value === 'name-asc') return a.name.localeCompare(b.name, 'zh-CN')
    if (sortOrder.value === 'name-desc') return b.name.localeCompare(a.name, 'zh-CN')
    return 0
  })
})

// 客户端分页
const totalPages = computed(() => Math.ceil(filteredProducts.value.length / itemsPerPage) || 1)
const paginatedProducts = computed(() => {
  const start = (currentPage.value - 1) * itemsPerPage
  return filteredProducts.value.slice(start, start + itemsPerPage)
})
const paginationStart = computed(() => (currentPage.value - 1) * itemsPerPage + 1)
const paginationEnd = computed(() => Math.min(currentPage.value * itemsPerPage, filteredProducts.value.length))

const visiblePages = computed(() => {
  const tp = totalPages.value
  const cp = currentPage.value
  const max = 5
  let start = Math.max(1, cp - Math.floor(max / 2))
  let end = Math.min(tp, start + max - 1)
  if (end - start < max - 1) start = Math.max(1, end - max + 1)
  const pages: (number | string)[] = []
  if (start > 1) { pages.push(1); if (start > 2) pages.push('...') }
  for (let i = start; i <= end; i++) pages.push(i)
  if (end < tp) { if (end < tp - 1) pages.push('...'); pages.push(tp) }
  return pages
})

watch(searchTerm, () => { currentPage.value = 1 })

function goToPage(p: number) { currentPage.value = p }

// ===== 添加产品 =====
const submitting = ref(false)
const form = reactive({ name: '', barcode: '', price: 0, image: '' })
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
  const allowed = ['image/jpeg', 'image/png', 'image/gif']
  if (!allowed.includes(file.type)) { showToast('仅支持 JPG/PNG/GIF 格式', 'error'); return }
  if (file.size > 5 * 1024 * 1024) { showToast('文件大小不能超过 5MB', 'error'); return }
  const formData = new FormData()
  formData.append('file', file)
  upload<{ url: string }>('/auth/upload', formData)
    .then(data => { if (data.url) form.image = data.url })
    .catch(() => showToast('上传失败', 'error'))
}

async function handleAdd() {
  if (!form.name) return
  submitting.value = true
  try {
    await productApi.create({ name: form.name, barcode: form.barcode, price: form.price || undefined, image: form.image || undefined })
    showToast('添加成功', 'success')
    Object.assign(form, { name: '', barcode: '', price: 0, image: '' })
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
    actionId.value = 0
  }
}

// ===== 图片查看模态框 =====
const imageModalVisible = ref(false)
const imageModalSrc = ref('')

function openImageModal(src: string) {
  imageModalSrc.value = src
  imageModalVisible.value = true
}

function handleImageError(e: Event) {
  const img = e.target as HTMLImageElement
  img.style.display = 'none'
  const parent = img.parentElement
  if (parent) {
    const placeholder = document.createElement('div')
    placeholder.className = 'pd-no-image'
    placeholder.innerHTML = '<i class="fas fa-image"></i>'
    parent.appendChild(placeholder)
  }
}

// ===== 编辑产品弹窗 =====
const editDialogVisible = ref(false)
const editSubmitting = ref(false)
const editForm = reactive({ id: 0, name: '', barcode: '', price: 0, image: '' })
const editImageInputRef = ref<HTMLInputElement | null>(null)
const editDragOver = ref(false)

function openEditModal(row: Product) {
  Object.assign(editForm, { id: row.id, name: row.name, barcode: row.barcode, price: row.price, image: row.image || '' })
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
  const allowed = ['image/jpeg', 'image/png', 'image/gif']
  if (!allowed.includes(file.type)) { showToast('仅支持 JPG/PNG/GIF 格式', 'error'); return }
  if (file.size > 5 * 1024 * 1024) { showToast('文件大小不能超过 5MB', 'error'); return }
  const formData = new FormData()
  formData.append('file', file)
  upload<{ url: string }>('/auth/upload', formData)
    .then(data => { if (data.url) editForm.image = data.url })
    .catch(() => showToast('上传失败', 'error'))
}

async function handleEditSave() {
  if (!editForm.name.trim()) { showToast('请输入产品名称', 'warning'); return }
  editSubmitting.value = true
  try {
    await productApi.update(editForm.id, { name: editForm.name, barcode: editForm.barcode, price: editForm.price, image: editForm.image })
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

// ===== BOM模态框 =====
const bomDialogVisible = ref(false)
const bomProductName = ref('')
const currentProductId = ref<number | null>(null)
const currentBomCategory = ref<'fabric' | 'filling' | 'accessory'>('fabric')

const bomTabs = [
  { key: 'fabric' as const, label: '面料类', icon: 'fas fa-scroll' },
  { key: 'filling' as const, label: '填充类', icon: 'fas fa-cloud' },
  { key: 'accessory' as const, label: '辅料类', icon: 'fas fa-puzzle-piece' },
]

const bomData = reactive<{ fabric: BomItem[]; filling: BomItem[]; accessory: BomItem[] }>({
  fabric: [],
  filling: [],
  accessory: [],
})

const currentBomItems = computed(() => bomData[currentBomCategory.value])
const currentBomTabLabel = computed(() => bomTabs.find(t => t.key === currentBomCategory.value)?.label || '')

function switchBomTab(category: 'fabric' | 'filling' | 'accessory') {
  currentBomCategory.value = category
}

async function openBomModal(row: Product) {
  currentProductId.value = row.id
  bomProductName.value = row.name
  bomDialogVisible.value = true
  currentBomCategory.value = 'fabric'
  await loadBomData(row.id)
}

async function loadBomData(productId: number) {
  bomData.fabric = []
  bomData.filling = []
  bomData.accessory = []
  try {
    const res = (await productApi.loadBom(productId)) as any
    if (res.success) {
      const materialsList = res.materials || []
      const grouped: { fabric: BomItem[]; filling: BomItem[]; accessory: BomItem[] } = { fabric: [], filling: [], accessory: [] }
      materialsList.forEach((item: any) => {
        const cat = item.category || 'accessory'
        if (cat === 'packaging') return // 包装类不在BOM配置中管理
        if (grouped[cat as keyof typeof grouped]) {
          grouped[cat as keyof typeof grouped].push({
            id: item.id,
            name: item.material_name || item.name || '',
            specification: item.specification || '',
            unit: item.unit || '码',
            supplier_id: item.supplier_id || null,
            supplier_name: item.supplier_name || '',
            usage: item.unit_usage || item.quantity || 1,
            remark: item.remark || '',
            category: cat,
          })
        }
      })
      bomData.fabric = grouped.fabric
      bomData.filling = grouped.filling
      bomData.accessory = grouped.accessory
    }
  } catch (error) {
    console.error('加载BOM数据失败:', error)
    showToast('加载BOM数据失败', 'error')
  }
}

function addBomItem() {
  bomData[currentBomCategory.value].push({ name: '', specification: '', unit: currentBomCategory.value === 'filling' ? '克' : '码', supplier_name: '', usage: 1, remark: '', category: currentBomCategory.value })
}

function deleteBomItem(index: number) {
  bomData[currentBomCategory.value].splice(index, 1)
}

async function saveBom() {
  const allItems = [
    ...bomData.fabric.map(i => ({ ...i, category: 'fabric' })),
    ...bomData.filling.map(i => ({ ...i, category: 'filling' })),
    ...bomData.accessory.map(i => ({ ...i, category: i.category || 'accessory' })),
  ]
  const invalidItems = allItems.filter(i => !i.name || !i.specification || !i.unit || !i.supplier_name)
  if (invalidItems.length > 0) { showToast('请填写所有必填项（物料名称、规格型号、计量单位、默认供应商）', 'warning'); return }

  try {
    const payload = {
      fabrics: bomData.fabric.map(i => ({
        id: i.id,
        fabric_name: i.name,
        specification: i.specification,
        unit: i.unit,
        quantity: i.usage,
        supplier_id: i.supplier_id,
        supplier_name: i.supplier_name,
        remark: i.remark,
        category: 'fabric',
      })),
      filling: bomData.filling.length > 0 ? (() => {
        if (bomData.filling.length > 1) {
          showToast('填充类物料每产品仅支持一条，已自动取第一条', 'warning')
        }
        const f = bomData.filling[0]
        return {
          id: f.id,
          cotton_usage: f.usage,
          specification: f.specification,
          supplier_id: f.supplier_id,
          supplier_name: f.supplier_name,
          unit: f.unit,
          remark: f.remark,
        }
      })() : null,
      accessories: bomData.accessory.map(i => ({
        id: i.id,
        accessory_name: i.name,
        specification: i.specification,
        unit: i.unit,
        quantity: i.usage,
        supplier_id: i.supplier_id,
        supplier_name: i.supplier_name,
        remark: i.remark,
        category: 'accessory',
      })),
      packagings: [],
    }
    const res = (await productApi.saveBom(currentProductId.value!, payload)) as any
    if (res.success) {
      showToast('保存成功', 'success')
      bomDialogVisible.value = false
    } else {
      showToast(res.error || '保存失败', 'error')
    }
  } catch (error) {
    showToast('保存BOM失败', 'error')
  }
}

// ===== 快速复制BOM（自动补全） =====
const quickCopyKeyword = ref('')
const quickCopyInputRef = ref<HTMLInputElement | null>(null)
const quickCopyLoading = ref(false)
const autocompleteVisible = ref(false)
const autocompleteItems = ref<any[]>([])
const autocompleteIndex = ref(-1)
let autocompleteTimeout: ReturnType<typeof setTimeout> | null = null
let selectedSourceProductId: number | null = null
let selectedSourceProductName: string | null = null

const quickCopyProgress = reactive({ visible: false, percent: 0, text: '' })

watch(quickCopyKeyword, (val) => {
  if (autocompleteTimeout) clearTimeout(autocompleteTimeout)
  if (val.trim().length < 1) { autocompleteVisible.value = false; return }
  autocompleteTimeout = setTimeout(() => searchAutocompleteProducts(val.trim()), 300)
})

async function searchAutocompleteProducts(keyword: string) {
  try {
    const res = (await productApi.searchProductsForBom(keyword)) as any
    autocompleteIndex.value = -1
    if (res.success && res.products?.length > 0) {
      autocompleteItems.value = res.products
      autocompleteVisible.value = true
    } else {
      autocompleteItems.value = []
      autocompleteVisible.value = true
    }
  } catch {
    autocompleteVisible.value = false
  }
}

function onAutocompleteKeydown(e: KeyboardEvent) {
  if (!autocompleteVisible.value || autocompleteItems.value.length === 0) {
    if (e.key === 'Enter') { e.preventDefault(); autocompleteVisible.value = false; quickCopyBom() }
    return
  }
  const items = autocompleteItems.value.filter(i => i.has_bom)
  if (e.key === 'ArrowDown') { e.preventDefault(); autocompleteIndex.value = Math.min(autocompleteIndex.value + 1, items.length - 1) }
  else if (e.key === 'ArrowUp') { e.preventDefault(); autocompleteIndex.value = Math.max(autocompleteIndex.value - 1, -1) }
  else if (e.key === 'Enter') {
    e.preventDefault()
    if (autocompleteIndex.value >= 0 && autocompleteIndex.value < items.length) {
      selectAutocompleteItem(items[autocompleteIndex.value])
    } else { autocompleteVisible.value = false; quickCopyBom() }
  }
  else if (e.key === 'Escape') { e.preventDefault(); autocompleteVisible.value = false }
}

function selectAutocompleteItem(item: any) {
  if (!item.has_bom) return
  selectedSourceProductId = item.id
  selectedSourceProductName = item.name
  quickCopyKeyword.value = item.name
  autocompleteVisible.value = false
}

function onQuickCopyFocus() {
  if (quickCopyKeyword.value.trim() && autocompleteItems.value.length === 0) {
    searchAutocompleteProducts(quickCopyKeyword.value.trim())
  } else if (autocompleteItems.value.length > 0) {
    autocompleteVisible.value = true
  }
}
function hideAutocomplete() {
  setTimeout(() => { autocompleteVisible.value = false }, 150)
}

async function quickCopyBom() {
  let sourceId = selectedSourceProductId
  let sourceName = selectedSourceProductName || ''

  if (!sourceId) {
    const keyword = quickCopyKeyword.value.trim()
    if (!keyword) { showToast('请输入产品名称或条码', 'warning'); return }

    quickCopyLoading.value = true
    quickCopyProgress.visible = true; quickCopyProgress.percent = 10; quickCopyProgress.text = '搜索产品中...'
    try {
      const res = (await productApi.searchProductsForBom(keyword)) as any
      if (!res.success || !res.products?.length) { hideQuickCopyProgress(); quickCopyLoading.value = false; showToast('未找到匹配的产品', 'warning'); return }
      const withBom = res.products.filter((p: any) => p.has_bom)
      if (!withBom.length) { hideQuickCopyProgress(); quickCopyLoading.value = false; showToast('找到产品没有配置BOM表', 'warning'); return }
      sourceId = withBom[0].id
      sourceName = withBom[0].name
    } catch { hideQuickCopyProgress(); quickCopyLoading.value = false; showToast('搜索失败', 'error'); return }
  }

  quickCopyProgress.percent = 40; quickCopyProgress.text = `正在从 "${sourceName}" 复制BOM...`

  try {
    quickCopyProgress.percent = 70; quickCopyProgress.text = '执行复制...'
    const res = (await productApi.copyBom(currentProductId.value!, sourceId!, true)) as any
    if (res.success) {
      quickCopyProgress.percent = 100; quickCopyProgress.text = '复制成功！'
      setTimeout(() => {
        hideQuickCopyProgress()
        quickCopyLoading.value = false
        loadBomData(currentProductId.value!)
        quickCopyKeyword.value = ''
        selectedSourceProductId = null
        selectedSourceProductName = null
      }, 500)
    } else {
      hideQuickCopyProgress(); quickCopyLoading.value = false
      showToast(res.error || '复制失败', 'error')
    }
  } catch { hideQuickCopyProgress(); quickCopyLoading.value = false; showToast('复制失败', 'error') }
}

function hideQuickCopyProgress() { quickCopyProgress.visible = false }

// 点击外部关闭自动补全
function onDocClick(e: MouseEvent) {
  if (autocompleteVisible.value) {
    const target = e.target as HTMLElement
    if (!target.closest('.autocomplete-wrapper')) autocompleteVisible.value = false
  }
}
onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))

// ===== 复制BOM模态框 =====
const copyBomDialogVisible = ref(false)
const copyBomSearchKeyword = ref('')
const copyBomProducts = ref<any[]>([])
const copyBomSourceProductId = ref<number | null>(null)
const copyBomPreview = ref<any>(null)
const copyBomOverwrite = ref(false)
const copyBomProgress = reactive({ visible: false, percent: 0, text: '' })

async function searchProductForCopy() {
  const keyword = copyBomSearchKeyword.value.trim()
  if (!keyword) { showToast('请输入产品名称或条码进行搜索', 'warning'); return }
  try {
    const res = (await productApi.searchProductsForBom(keyword)) as any
    if (res.success && res.products?.length > 0) {
      copyBomProducts.value = res.products
      copyBomPreview.value = null
      copyBomSourceProductId.value = null
    } else {
      copyBomProducts.value = []
      showToast('未找到匹配的产品', 'warning')
    }
  } catch { showToast('搜索产品失败', 'error') }
}

async function selectCopyBomProduct(product: any) {
  if (!product.has_bom) { showToast('该产品没有配置BOM表，请选择其他产品', 'warning'); return }
  copyBomSourceProductId.value = product.id
  copyBomPreview.value = null
  try {
    const res = (await productApi.bomPreview(product.id)) as any
    if (res.success) {
      copyBomPreview.value = {
        source_name: product.name,
        source_barcode: product.barcode || '',
        material_count: res.material_count,
        fabric_count: res.bom?.fabric?.length || 0,
        filling_count: res.bom?.filling?.length || 0,
        accessory_count: (res.bom?.accessory?.length || 0) + (res.bom?.packaging?.length || 0),
      }
    }
  } catch { showToast('加载BOM预览失败', 'error') }
}

async function confirmCopyBom() {
  if (!copyBomSourceProductId.value) return
  copyBomProgress.visible = true; copyBomProgress.percent = 0; copyBomProgress.text = '准备复制...'
  try {
    copyBomProgress.percent = 30; copyBomProgress.text = '正在复制BOM表...'
    const res = (await productApi.copyBom(currentProductId.value!, copyBomSourceProductId.value, copyBomOverwrite.value)) as any
    if (res.success) {
      copyBomProgress.percent = 100; copyBomProgress.text = '复制成功！'
      setTimeout(() => {
        copyBomProgress.visible = false
        copyBomDialogVisible.value = false
        loadBomData(currentProductId.value!)
      }, 500)
    } else {
      copyBomProgress.visible = false
      showToast(res.error || '复制失败', 'error')
    }
  } catch { copyBomProgress.visible = false; showToast('复制失败', 'error') }
}
</script>

<style scoped>
/* ===== 容器 ===== */
.pd-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* ===== 主卡片 ===== */
.pd-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  overflow: hidden;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.pd-card:hover {
  box-shadow: 0 12px 36px rgba(0,0,0,0.08), 0 48px 144px rgba(0,0,0,0.12);
  transform: translateY(-6px);
}
.pd-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* ===== 卡片头部 ===== */
.pd-card-header {
  padding: 10px 24px;
  background: transparent;
  display: flex;
  flex-wrap: nowrap;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  gap: 12px;
}
.pd-card-header :deep(.ht-bar) {
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
.pd-body {
  display: grid;
  grid-template-columns: 1fr 2fr;
  flex: 1;
  min-height: 0;
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
  padding: 12px 20px;
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
  transition: all 0.3s ease;
  outline: none;
}
.pd-input:focus {
  background: white;
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

/* ===== 按钮 ===== */
.pd-btn {
  padding: 7px 14px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 9px;
  border: 2px solid var(--color-border-light);
  background: white;
  transition: all 0.3s ease;
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
.pd-w-full { width: 100%; justify-content: center; }

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
  transition: all 0.3s ease;
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
  transition: all 0.2s ease;
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
  transition: all 0.2s ease;
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
  transition: all 0.3s ease;
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
  transition: all 0.3s ease;
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
  transition: all 0.3s ease;
  background: var(--color-surface, #f8fafc);
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
  transition: all 0.2s ease;
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

/* ===== 分页 ===== */
.pd-pagi-wrap { background: white; border-top: 1px solid var(--color-border-light, #f1f5f9); }
.pd-pagi-inner { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; padding: 10px 14px; }
.pd-pagi-info { font-size: 13px; color: var(--color-text-secondary); }
.pd-pagi { display: flex; list-style: none; margin: 0; padding: 0; gap: 4px; }
.pd-pagi .page-link {
  width: 36px; height: 36px; border-radius: 8px; border: 2px solid var(--color-border-light, #e2e8f0);
  color: var(--color-text-secondary); display: flex; align-items: center; justify-content: center;
  font-weight: 500; font-size: 13px; transition: all 0.2s ease; text-decoration: none;
}
.pd-pagi .page-link:hover { background: var(--color-surface, #f8fafc); border-color: var(--color-border-light); color: var(--color-text); }
.pd-pagi .page-item.active .page-link {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600));
  border-color: var(--color-primary-500); color: white; box-shadow: 0 4px 12px rgba(59,130,246,0.3);
}
.pd-pagi .page-item.disabled .page-link { opacity: 0.4; pointer-events: none; }

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
  transition: all 0.2s ease; cursor: pointer;
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
  color: var(--color-text-secondary); font-size: 16px; transition: all 0.3s ease;
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
  transition: all 0.3s ease;
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
  cursor: pointer; transition: all 0.3s ease; display: flex; align-items: center; gap: 6px;
}
.bom-btn-add-v2:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(34,197,94,0.2); }
.bom-btn-copy-v2 {
  padding: 10px 20px; background: var(--color-primary-50); color: var(--color-primary-600);
  border: 2px solid var(--color-primary-200); border-radius: 10px; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: all 0.3s ease; display: flex; align-items: center; gap: 6px;
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
  border-radius: 8px; font-size: 13px; transition: all 0.2s ease; outline: none;
}
.bom-table-input:focus { border-color: var(--color-primary-400); box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1); }
.bom-table-select {
  width: 100%; padding: 6px 10px; border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px; font-size: 13px; background: white; cursor: pointer;
  transition: all 0.2s ease; outline: none;
}
.bom-table-select:focus { border-color: var(--color-primary-400); box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1); }
.bom-table-action-btn { padding: 5px 8px; border: none; border-radius: 6px; cursor: pointer; font-size: 12px; transition: all 0.2s ease; }
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
  font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.3s ease;
}
.bom-btn-cancel:hover { background: var(--color-surface, #f8fafc); transform: translateY(-1px); }
.bom-btn-save {
  padding: 10px 20px; background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600));
  color: white; border: 2px solid var(--color-primary-500); border-radius: 10px;
  font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.3s ease;
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
  cursor: pointer; transition: all 0.2s ease;
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
  transition: all 0.2s ease; display: flex; justify-content: space-between; align-items: center;
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
.small { font-size: 0.875rem; }
.text-primary { color: var(--color-primary-500); }
.fs-4 { font-size: 1.5rem; }
.fw-bold { font-weight: 700; }
.mb-0 { margin-bottom: 0; }
.mb-2 { margin-bottom: 0.5rem; }
.mb-3 { margin-bottom: 0.75rem; }
.mb-4 { margin-bottom: 1rem; }
.mt-2 { margin-top: 0.5rem; }
.me-2 { margin-right: 0.5rem; }
.d-block { display: block; }
.text-center { text-align: center; }
.py-8 { padding-top: 2rem; padding-bottom: 2rem; }
.form-check-input { width: 1.125rem; height: 1.125rem; margin-right: 0.5rem; }
.form-check-label { display: flex; align-items: flex-start; gap: 0.5rem; }
.edit-modal-content { padding: 20px; }

/* ===== 响应式 ===== */
@media (max-width: 1199.98px) {
  .pd-body { grid-template-columns: 1fr; }
  .pd-col + .pd-col { border-left: none; border-top: 1px solid var(--color-border-light, #f1f5f9); }
}
</style>
