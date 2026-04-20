"use strict";
document.addEventListener('DOMContentLoaded', function() {
    console.log('产品管理页面加载完成');

    // ========== Tab Navigation ==========
    const tabBtns = document.querySelectorAll('.product-tab-btn');
    const tabContents = document.querySelectorAll('.product-tab-content');

    tabBtns.forEach(function(btn) {
        btn.addEventListener('click', function() {
            var targetTab = this.getAttribute('data-tab');

            tabBtns.forEach(function(b) { b.classList.remove('active'); });
            tabContents.forEach(function(c) { c.classList.remove('active'); });

            this.classList.add('active');
            var targetContent = document.getElementById('tab-' + targetTab);
            if (targetContent) {
                targetContent.classList.add('active');
            }
        });
    });

    // ========== Collapse Animation for Upload Sections ==========
    function initCollapseAnimations() {
        var containers = document.querySelectorAll('.collapse-animated-container');
        containers.forEach(function(container) {
            // Initialize as expanded
            container.classList.add('expanded');

            var trigger = container.querySelector('.collapse-trigger');
            if (trigger) {
                trigger.addEventListener('click', function(e) {
                    e.stopPropagation();
                    var isExpanded = container.classList.contains('expanded');

                    if (isExpanded) {
                        container.classList.remove('expanded');
                        container.classList.add('collapsed');
                    } else {
                        container.classList.remove('collapsed');
                        container.classList.add('expanded');
                    }
                });
            }
        });
    }

    initCollapseAnimations();

    function handleImageError(img) {
        console.log('图片加载失败:', img.src);
        img.style.display = 'none';
        const placeholder = img.nextElementSibling;
        if (placeholder && placeholder.classList.contains('no-image-elegant')) {
            placeholder.style.display = 'flex';
        }
    }
    
    document.querySelectorAll('.product-thumbnail-elegant').forEach(function(img) {
        img.onerror = function() {
            handleImageError(this);
        };
    });
    
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            mutation.addedNodes.forEach(function(node) {
                if (node.nodeType === 1) {
                    const imgs = node.querySelectorAll ? node.querySelectorAll('.product-thumbnail-elegant') : [];
                    imgs.forEach(function(img) {
                        img.onerror = function() {
                            handleImageError(this);
                        };
                    });
                }
            });
        });
    });
    
    observer.observe(document.body, { childList: true, subtree: true });
    
    const uploadArea = document.getElementById('image-upload-area');
    const imageInput = document.getElementById('image-input');
    const imagePreview = document.getElementById('image-preview');
    const imageUrlInput = document.getElementById('image-url');
    let uploadProgress = null;
    
    function createProgressElement() {
        removeProgressElement();
        uploadProgress = document.createElement('div');
        uploadProgress.className = 'mt-4';
        uploadProgress.innerHTML = `
            <div class="progress" style="height: 20px; border-radius: 10px;">
                <div class="progress-bar progress-bar-striped progress-bar-animated" role="progressbar" style="width: 0%; border-radius: 10px;"></div>
            </div>
            <p class="mt-2 text-muted small text-center">上传中...</p>
        `;
        if (uploadArea) {
            uploadArea.appendChild(uploadProgress);
        }
    }
    
    function removeProgressElement() {
        if (uploadProgress) {
            uploadProgress.remove();
            uploadProgress = null;
        }
    }
    
    function updateProgress(percent, message) {
        if (uploadProgress) {
            const progressBar = uploadProgress.querySelector('.progress-bar');
            const progressText = uploadProgress.querySelector('p');
            if (progressBar) progressBar.style.width = percent + '%';
            if (progressText) progressText.textContent = message;
        }
    }
    
    async function uploadImage(file) {
        const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif'];
        if (!allowedTypes.includes(file.type)) {
            alert('只支持 JPG、PNG、GIF 格式的图片');
            return;
        }
        
        const maxSize = 2 * 1024 * 1024;
        if (file.size > maxSize) {
            alert('文件大小不能超过 2MB');
            return;
        }
        
        createProgressElement();
        updateProgress(0, '准备上传...');
        
        try {
            const formData = new FormData();
            formData.append('file', file);
            
            updateProgress(30, '上传中...');
            
            const response = await fetch('/upload', {
                method: 'POST',
                body: formData
            });
            
            updateProgress(80, '处理中...');
            
            const data = await response.json();
            
            if (data.url) {
                imageUrlInput.value = data.url;
                if (imagePreview) {
                    imagePreview.innerHTML = `<img src="${escapeHtml(data.url)}" style="max-width: 100%; max-height: 240px; object-fit: contain; border-radius: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">`;
                }
                updateProgress(100, '上传成功！');
                setTimeout(() => {
                    removeProgressElement();
                }, 1500);
            } else {
                alert(data.error || '上传失败');
                removeProgressElement();
            }
        } catch (error) {
            console.error('上传错误:', error);
            alert('上传失败：' + error.message);
            removeProgressElement();
        }
    }
    
    if (uploadArea && imageInput) {
        uploadArea.addEventListener('click', (e) => {
            if (e.target.tagName !== 'IMG') {
                imageInput.click();
            }
        });
        
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor = '#3b82f6';
            uploadArea.style.background = 'linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%)';
        });
        
        uploadArea.addEventListener('dragleave', () => {
            uploadArea.style.borderColor = '#cbd5e1';
            uploadArea.style.background = '#ffffff';
        });
        
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor = '#cbd5e1';
            uploadArea.style.background = '#ffffff';
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                uploadImage(files[0]);
            }
        });
        
        imageInput.addEventListener('change', (e) => {
            const files = e.target.files;
            if (files.length > 0) {
                uploadImage(files[0]);
            }
        });
    }
    
    const excelUploadArea = document.getElementById('excel-upload-area');
    const excelInput = document.getElementById('excel-input');
    const excelPreview = document.getElementById('excel-preview');
    const uploadStatus = document.getElementById('upload-status');
    const downloadTemplate = document.getElementById('download-template');
    const batchImport = document.getElementById('batch-import');
    let excelFile = null;
    
    function showStatus(message, type = 'info') {
        const typeMapping = {
            info: 'info',
            success: 'success',
            error: 'error',
            warning: 'warning'
        };
        
        const notificationType = typeMapping[type] || 'info';
        
        if (window.GlobalNotification) {
            window.GlobalNotification[notificationType](message);
        } else {
            const types = {
                info: 'alert-info',
                success: 'alert-success',
                error: 'alert-danger',
                warning: 'alert-warning'
            };
            
            if (uploadStatus) {
                uploadStatus.innerHTML = `
                    <div class="alert ${types[type]} alert-dismissible fade show" role="alert" style="border-radius: 12px; padding: 1rem 1.25rem;">
                        ${escapeHtml(message)}
                        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="关闭"></button>
                    </div>
                `;
            }
        }
    }
    
    function handleExcelFile(file) {
        const fileName = file.name.toLowerCase();
        if (!fileName.endsWith('.xlsx') && !fileName.endsWith('.xls')) {
            showStatus('错误：请上传 Excel 文件（.xlsx 或.xls 格式）', 'error');
            return;
        }
        
        excelFile = file;
        showStatus(`已选择文件：${file.name}`, 'info');
        
        if (excelPreview) {
            excelPreview.innerHTML = `
                <div class="border rounded-3 p-3 bg-light">
                    <div class="small"><strong>文件：</strong>${escapeHtml(file.name)}</div>
                    <div class="small"><strong>大小：</strong>${(file.size / 1024).toFixed(2)} KB</div>
                </div>
            `;
        }
        
        if (batchImport) {
            batchImport.disabled = false;
            batchImport.style.pointerEvents = 'auto';
            batchImport.style.cursor = 'pointer';
        }
    }
    
    if (excelUploadArea && excelInput) {
        excelUploadArea.addEventListener('click', (e) => {
            e.stopPropagation();
            const targetElement = e.target.closest('#download-template, #batch-import');
            if (e.target.tagName !== 'IMG' && !targetElement) {
                excelInput.click();
            }
        });
        
        excelUploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.stopPropagation();
            excelUploadArea.style.borderColor = '#22c55e';
            excelUploadArea.style.background = 'linear-gradient(135deg, #f0fdf4 0%, #f8fafc 100%)';
        });
        
        excelUploadArea.addEventListener('dragleave', (e) => {
            e.stopPropagation();
            excelUploadArea.style.borderColor = '#cbd5e1';
            excelUploadArea.style.background = '#ffffff';
        });
        
        excelUploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            excelUploadArea.style.borderColor = '#cbd5e1';
            excelUploadArea.style.background = '#ffffff';
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                handleExcelFile(files[0]);
            }
        });
        
        excelInput.addEventListener('change', (e) => {
            const files = e.target.files;
            if (files.length > 0) {
                handleExcelFile(files[0]);
            }
        });
    }
    
    if (downloadTemplate) {
        downloadTemplate.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            
            downloadTemplate.disabled = true;
            downloadTemplate.innerHTML = '<i class="fas fa-hourglass-half me-2"></i>下载中...';
            
            try {
                const response = await fetch('/api/v1/batch/download-template');
                
                if (!response.ok) {
                    throw new Error('下载失败');
                }
                
                const disposition = response.headers.get('Content-Disposition');
                let filename = '统一导入模板.xlsx';
                if (disposition) {
                    const filenameMatch = disposition.match(/filename\*=UTF-8''(.+)/);
                    if (filenameMatch) {
                        filename = decodeURIComponent(filenameMatch[1]);
                    }
                }
                
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                
                const link = document.createElement('a');
                link.href = url;
                link.download = filename;
                link.style.display = 'none';
                document.body.appendChild(link);
                link.click();
                
                setTimeout(() => {
                    document.body.removeChild(link);
                    window.URL.revokeObjectURL(url);
                }, 100);
                
                showStatus('✓ 模板下载已开始，请查看浏览器下载', 'success');
                
            } catch (error) {
                console.error('下载错误:', error);
                showStatus('✗ 下载失败：' + error.message, 'error');
            } finally {
                downloadTemplate.disabled = false;
                downloadTemplate.innerHTML = '<i class="fas fa-download me-2"></i>下载模板';
            }
        });
    }
    
    if (batchImport) {
        batchImport.addEventListener('click', async (e) => {
            if (!excelFile) {
                showStatus('请先选择 Excel 文件', 'error');
                return;
            }
            
            showStatus('正在导入数据...', 'info');
            
            const formData = new FormData();
            formData.append('file', excelFile);
            
            try {
                const response = await fetch('/api/v1/batch/batch-import', {
                    method: 'POST',
                    body: formData
                });
                
                const text = await response.text();
                
                let data;
                try {
                    data = JSON.parse(text);
                } catch (parseError) {
                    showStatus('导入失败：服务器返回了无效的响应', 'error');
                    return;
                }
                
                if (data.success) {
                    showStatus(`导入成功！共导入 ${data.imported || 0} 个产品`, 'success');
                    setTimeout(() => {
                        location.reload();
                    }, 2000);
                } else {
                    showStatus(`导入失败：${data.message || data.error || '未知错误'}`, 'error');
                }
            } catch (error) {
                console.error('导入错误:', error);
                showStatus('导入失败：' + (error.message || '网络错误，请检查服务器是否运行'), 'error');
            }
        });
    }
    
    const imageModalEl = document.getElementById('imageModal');
    const modalImage = document.getElementById('modalImage');
    
    if (imageModalEl && typeof bootstrap !== 'undefined') {
        const imageModal = bootstrap.Modal.getOrCreateInstance(imageModalEl);
        
        document.querySelectorAll('.product-image-container[role="button"]').forEach(thumbnail => {
            thumbnail.addEventListener('click', function() {
                const img = this.querySelector('img');
                const imageSrc = img ? img.getAttribute('data-src') : null;
                if (imageSrc && modalImage) {
                    modalImage.src = imageSrc;
                    imageModal.show();
                }
            });
            
            thumbnail.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    this.click();
                }
            });
        });
        
        document.querySelectorAll('.view-image-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const imageSrc = this.getAttribute('data-image-src');
                const productName = this.getAttribute('data-product-name');
                
                if (!imageSrc) {
                    alert('该产品暂无图片');
                    return;
                }
                
                if (modalImage) {
                    modalImage.src = imageSrc;
                    modalImage.alt = productName + ' 产品图片';
                }
                imageModal.show();
            });
        });
    }
    
    if (imagePreview) {
        imagePreview.addEventListener('click', function(e) {
            const img = e.target.closest('img');
            if (img && imageModalEl && modalImage) {
                modalImage.src = img.src;
                const modalInstance = bootstrap.Modal.getOrCreateInstance(imageModalEl);
                modalInstance.show();
            }
        });
    }
    
    const searchInput = document.getElementById('searchInput');
    const sortSelect = document.getElementById('sortSelect');
    const productTableBody = document.getElementById('productTableBody');
    
    let allRows = Array.from(productTableBody.querySelectorAll('tr[data-name]'));
    let filteredRows = [...allRows];
    
    function filterAndSort() {
        const searchTerm = searchInput.value.toLowerCase().trim();
        const sortValue = sortSelect.value;
        
        filteredRows = allRows.filter(row => {
            const name = row.dataset.name || '';
            const barcode = row.dataset.barcode || '';
            return name.includes(searchTerm) || barcode.includes(searchTerm);
        });
        
        filteredRows.sort((a, b) => {
            const nameA = a.dataset.name || '';
            const nameB = b.dataset.name || '';
            
            switch(sortValue) {
                case 'name-asc':
                    return nameA.localeCompare(nameB, 'zh-CN');
                case 'name-desc':
                    return nameB.localeCompare(nameA, 'zh-CN');
                default:
                    return 0;
            }
        });
        
        renderTable();
    }
    
    function renderTable() {
        productTableBody.innerHTML = '';
        
        if (filteredRows.length === 0) {
            productTableBody.innerHTML = `
                <tr>
                    <td colspan="3" class="text-center py-8">
                        <div class="empty-state-elegant">
                            <i class="fas fa-search empty-icon-elegant mb-4"></i>
                            <p class="empty-text-elegant mb-0">未找到匹配的产品</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        filteredRows.forEach((row, index) => {
            row.style.animationDelay = `${index * 0.05}s`;
            productTableBody.appendChild(row);
        });
    }
    
    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
    
    if (searchInput) {
        searchInput.addEventListener('input', debounce(filterAndSort, 300));
    }
    
    if (sortSelect) {
        sortSelect.addEventListener('change', filterAndSort);
    }
    
    const productForm = document.getElementById('productForm');
    if (productForm) {
        productForm.addEventListener('submit', function(e) {
            const nameInput = document.getElementById('name');
            const nameValue = nameInput ? nameInput.value.trim() : '';
            if (!nameValue) {
                e.preventDefault();
                alert('请输入产品名称');
                if (nameInput) nameInput.focus();
                return false;
            }
        });
    }
});

async function deleteProduct(id) {
    if (!confirm('确定要删除该产品吗？')) return;

    try {
        const response = await fetch(`/api/v1/products/delete/${id}`, { method: 'DELETE' });
        const contentType = response.headers.get('content-type');
        let result;

        if (contentType && contentType.includes('application/json')) {
            result = await response.json();
        } else {
            result = await response.text();
        }

        if (response.ok && result.success) {
            alert('删除成功！');
            window.location.reload();
        } else {
            let errorMessage = '删除失败！';
            if (typeof result === 'object' && result !== null) {
                if (result.detail) {
                    errorMessage = result.detail;
                } else if (result.error) {
                    errorMessage = result.error;
                } else if (result.message) {
                    errorMessage = result.message;
                }
            } else if (typeof result === 'string' && result) {
                errorMessage = result;
            }
            alert(errorMessage);
        }
    } catch (error) {
        console.error('删除产品失败:', error);
        alert('删除失败：网络错误或服务器无响应，请稍后重试');
    }
}

let currentProductId = null;
let currentBomCategory = 'fabric';
let bomData = {
    fabric: [],
    filling: [],
    accessory: []
};

async function openBomModal(productId, productName) {
    currentProductId = productId;
    document.getElementById('bomProductName').textContent = `BOM表配置 - ${productName}`;
    
    const modal = new bootstrap.Modal(document.getElementById('bomModal'));
    modal.show();
    
    await loadBomData(productId);
}

async function loadBomData(productId) {
    try {
        const response = await fetch(`/api/v1/purchase-center/api/product/${productId}/bom`);
        const result = await response.json();
        
        if (result.success) {
            const materialsList = result.materials || [];
            const grouped = { fabric: [], filling: [], accessory: [] };
            materialsList.forEach(item => {
                const cat = item.category || 'accessory';
                const targetCat = (cat === 'packaging') ? 'accessory' : cat;
                if (grouped[targetCat]) {
                    grouped[targetCat].push({
                        ...item,
                        name: item.material_name || item.name || '',
                        usage: item.unit_usage || item.quantity || 1
                    });
                }
            });
            bomData = grouped;
            
            renderBomContent();
        } else {
            alert('加载BOM数据失败：' + result.error);
        }
    } catch (error) {
        console.error('加载BOM数据失败:', error);
        alert('加载BOM数据失败，请重试');
    }
}

function switchBomTab(category) {
    currentBomCategory = category;
    
    document.querySelectorAll('.bom-tab-v2').forEach(tab => {
        tab.classList.remove('active');
        if (tab.dataset.category === category) {
            tab.classList.add('active');
        }
    });
    
    renderBomContent();
}

function renderBomContent() {
    const items = bomData[currentBomCategory];
    const tbody = document.getElementById('bomTableBody');
    const emptyState = document.getElementById('bomEmptyState');
    const tableContainer = document.getElementById('bomTableContainer');
    
    const categoryNames = {
        fabric: '面料类',
        filling: '填充类',
        accessory: '辅料类'
    };
    
    document.getElementById('bomCategoryTitle').textContent = categoryNames[currentBomCategory] + '物料清单';
    document.getElementById('bomTotalCount').textContent = items.length;
    
    if (items.length === 0) {
        tbody.innerHTML = '';
        tableContainer.style.display = 'none';
        emptyState.style.display = 'flex';
    } else {
        tableContainer.style.display = 'block';
        emptyState.style.display = 'none';
        
        let html = '';
        items.forEach((item, index) => {
            html += renderBomTableRow(item, index);
        });
        tbody.innerHTML = html;
    }
}

function renderBomTableRow(item, index) {
    return `
        <tr>
            <td>
                <input type="text" class="bom-table-input" value="${escapeHtml(item.name || '')}"
                       onchange="updateBomItem(${index}, 'name', this.value)"
                       placeholder="输入物料名称">
            </td>
            <td>
                <input type="text" class="bom-table-input" value="${escapeHtml(item.specification || '')}"
                       onchange="updateBomItem(${index}, 'specification', this.value)"
                       placeholder="输入规格型号">
            </td>
            <td>
                <select class="bom-table-select" value="${item.unit || ''}"
                       onchange="updateBomItem(${index}, 'unit', this.value)">
                    <option value="码" ${item.unit === '码' ? 'selected' : ''}>码</option>
                    <option value="克" ${item.unit === '克' ? 'selected' : ''}>克</option>
                    <option value="个" ${item.unit === '个' ? 'selected' : ''}>个</option>
                    <option value="件" ${item.unit === '件' ? 'selected' : ''}>件</option>
                    <option value="套" ${item.unit === '套' ? 'selected' : ''}>套</option>
                    <option value="米" ${item.unit === '米' ? 'selected' : ''}>米</option>
                    <option value="平方" ${item.unit === '平方' ? 'selected' : ''}>平方</option>
                </select>
            </td>
            <td>
                <input type="text" class="bom-table-input" value="${escapeHtml(item.supplier_name || '')}"
                       onchange="updateBomItem(${index}, 'supplier_name', this.value)"
                       placeholder="输入供应商名称">
            </td>
            <td>
                <input type="number" class="bom-table-input" value="${item.usage || 1}" 
                       onchange="updateBomItem(${index}, 'usage', this.value)" 
                       step="0.01" min="0">
            </td>
            <td>
                <input type="text" class="bom-table-input" value="${escapeHtml(item.remark || '')}"
                       onchange="updateBomItem(${index}, 'remark', this.value)"
                       placeholder="输入备注">
            </td>
            <td>
                <button type="button" class="bom-table-action-btn delete" onclick="deleteBomItem(${index})">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        </tr>
    `;
}

function renderBomItem(item, index) {
    return '';
}

function addBomItem() {
    bomData[currentBomCategory].push({
        name: '',
        specification: '',
        unit: '码',
        supplier_name: '',
        usage: 1,
        remark: ''
    });
    
    renderBomContent();
}

function deleteBomItem(index) {
    bomData[currentBomCategory].splice(index, 1);
    renderBomContent();
}

function updateBomItem(index, field, value) {
    bomData[currentBomCategory][index][field] = value;
}

async function saveBom() {
    // 前端校验：使用原始 bomData 格式
    const allItems = [
        ...bomData.fabric.map(item => ({...item, category: 'fabric'})),
        ...bomData.filling.map(item => ({...item, category: 'filling'})),
        ...bomData.accessory.map(item => ({...item, category: 'accessory'}))
    ];

    const invalidItems = allItems.filter(item =>
        !item.name || !item.specification || !item.unit || !item.supplier_name
    );

    if (invalidItems.length > 0) {
        alert('请填写所有必填项（物料名称、规格型号、计量单位、默认供应商）');
        return;
    }

    // 将包装类物料从辅料类中分离出来（前端加载时将 packaging 合并到 accessory）
    const realAccessories = [];
    const packagings = [];
    bomData.accessory.forEach(item => {
        if (item.category === 'packaging' || item.material_category === 'packaging') {
            packagings.push(item);
        } else {
            realAccessories.push(item);
        }
    });

    // 构造后端期望的请求体格式（与 BomSaveRequest schema 对齐）
    const fillingItem = bomData.filling.length > 0 ? bomData.filling[0] : null;
    const requestBody = {
        filling: fillingItem ? {
            cotton_usage: fillingItem.cotton_usage || fillingItem.usage || 0,
            supplier_id: fillingItem.supplier_id || null,
            supplier_name: fillingItem.supplier_name || '',
            specification: fillingItem.specification || '',
            remark: fillingItem.remark || ''
        } : null,
        fabrics: bomData.fabric.map(item => ({
            id: item.id || null,
            fabric_name: item.fabric_name || item.name || '',
            quantity: item.quantity || item.usage || 0,
            supplier_id: item.supplier_id || null,
            supplier_name: item.supplier_name || '',
            specification: item.specification || '',
            remark: item.remark || ''
        })),
        accessories: realAccessories.map(item => ({
            id: item.id || null,
            accessory_name: item.accessory_name || item.name || '',
            quantity: item.quantity || item.usage || 1,
            supplier_id: item.supplier_id || null,
            supplier_name: item.supplier_name || '',
            specification: item.specification || '',
            material_category: item.material_category || 'accessory',
            remark: item.remark || ''
        })),
        packagings: packagings.map(item => ({
            id: item.id || null,
            packaging_name: item.packaging_name || item.name || '',
            quantity: item.quantity || item.usage || 1,
            supplier_id: item.supplier_id || null,
            supplier_name: item.supplier_name || '',
            specification: item.specification || '',
            remark: item.remark || ''
        }))
    };

    try {
        const response = await fetch(`/api/v1/purchase-center/api/product/${currentProductId}/bom`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        });

        const result = await response.json();

        if (result.success) {
            bootstrap.Modal.getInstance(document.getElementById('bomModal')).hide();
        } else {
            alert('保存失败：' + (result.detail || result.error || '未知错误'));
        }
    } catch (error) {
        console.error('保存BOM失败:', error);
        alert('保存BOM失败，请重试');
    }
}

let copyBomSourceProductId = null;
let copyBomModal = null;

function openCopyBomModal() {
    copyBomSourceProductId = null;
    copyBomModal = new bootstrap.Modal(document.getElementById('copyBomModal'));
    copyBomModal.show();
    
    resetCopyBomModal();
}

function resetCopyBomModal() {
    document.getElementById('copyBomSearchInput').value = '';
    document.getElementById('copyBomProductList').style.display = 'none';
    document.getElementById('copyBomPreview').style.display = 'none';
    document.getElementById('copyBomMessage').innerHTML = '';
    document.getElementById('copyBomProgress').style.display = 'none';
    document.getElementById('copyBomOverwrite').checked = false;
    document.getElementById('copyBomConfirmBtn').disabled = true;
}

async function searchProductForCopy() {
    const keyword = document.getElementById('copyBomSearchInput').value.trim();
    
    if (!keyword) {
        showCopyBomMessage('请输入产品名称或条码进行搜索', 'warning');
        return;
    }
    
    try {
        const response = await fetch(`/api/v1/purchase-center/api/products/search?keyword=${encodeURIComponent(keyword)}`);
        const result = await response.json();
        
        if (result.success && result.products.length > 0) {
            renderCopyBomProductList(result.products);
        } else {
            showCopyBomMessage('未找到匹配的产品', 'warning');
            document.getElementById('copyBomProductList').style.display = 'none';
            document.getElementById('copyBomPreview').style.display = 'none';
            document.getElementById('copyBomConfirmBtn').disabled = true;
        }
    } catch (error) {
        console.error('搜索产品失败:', error);
        showCopyBomMessage('搜索产品失败，请重试', 'error');
    }
}

function renderCopyBomProductList(products) {
    const container = document.getElementById('copyBomProductListContent');
    let html = '';
    
    products.forEach(product => {
        const statusClass = product.has_bom ? 'has-bom' : 'no-bom';
        const statusText = product.has_bom ? '有BOM' : '无BOM';
        
        html += `
            <div class="copy-bom-product-item" data-id="${product.id}" data-has-bom="${product.has_bom}" onclick="selectCopyBomProduct(${product.id}, ${product.has_bom}, this.dataset.name, this.dataset.barcode)" data-name="${escapeHtml(product.name)}" data-barcode="${escapeHtml(product.barcode || '')}">
                <div>
                    <div class="product-name">${escapeHtml(product.name)}</div>
                    <div class="product-barcode">${product.barcode ? '条码: ' + escapeHtml(product.barcode) : ''}</div>
                </div>
                <span class="product-status ${statusClass}">${statusText}</span>
            </div>
        `;
    });
    
    container.innerHTML = html;
    document.getElementById('copyBomProductList').style.display = 'block';
    document.getElementById('copyBomPreview').style.display = 'none';
    document.getElementById('copyBomConfirmBtn').disabled = true;
}

function selectCopyBomProduct(productId, hasBom, productName, barcode) {
    if (!hasBom) {
        showCopyBomMessage('该产品没有配置BOM表，请选择其他产品', 'warning');
        return;
    }
    
    document.querySelectorAll('.copy-bom-product-item').forEach(item => {
        item.classList.remove('selected');
    });
    document.querySelector(`.copy-bom-product-item[data-id="${productId}"]`).classList.add('selected');
    
    loadCopyBomPreview(productId, productName, barcode);
}

async function loadCopyBomPreview(productId, productName, barcode) {
    try {
        const response = await fetch(`/api/v1/purchase-center/api/products/${productId}/bom-preview`);
        const result = await response.json();
        
        if (result.success) {
            copyBomSourceProductId = productId;
            
            document.getElementById('copyBomSourceProductName').textContent = productName;
            document.getElementById('copyBomSourceProductBarcode').textContent = barcode ? '条码：' + barcode : '条码：-';
            document.getElementById('copyBomMaterialCount').textContent = result.material_count;
            document.getElementById('copyBomFabricCount').textContent = result.bom.fabric.length;
            document.getElementById('copyBomFillingCount').textContent = result.bom.filling ? 1 : 0;
            document.getElementById('copyBomAccessoryCount').textContent = result.bom.accessory.length + result.bom.packaging.length;
            
            document.getElementById('copyBomPreview').style.display = 'block';
            document.getElementById('copyBomConfirmBtn').disabled = false;
            showCopyBomMessage(`已选择源产品：${productName}，请确认后点击复制`, 'info');
        } else {
            showCopyBomMessage(result.error || '加载BOM预览失败', 'error');
        }
    } catch (error) {
        console.error('加载BOM预览失败:', error);
        showCopyBomMessage('加载BOM预览失败，请重试', 'error');
    }
}

async function confirmCopyBom() {
    if (!copyBomSourceProductId) {
        showCopyBomMessage('请先选择源产品', 'warning');
        return;
    }
    
    const overwrite = document.getElementById('copyBomOverwrite').checked;
    
    const confirmBtn = document.getElementById('copyBomConfirmBtn');
    confirmBtn.disabled = true;
    
    showCopyBomProgress('准备复制...', 0);
    
    try {
        showCopyBomProgress('正在复制BOM表...', 30);
        
        const response = await fetch(`/api/v1/purchase-center/api/products/${currentProductId}/copy-bom`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                source_product_id: copyBomSourceProductId,
                overwrite: overwrite
            })
        });
        
        showCopyBomProgress('处理中...', 70);
        
        const result = await response.json();
        
        if (result.success) {
            showCopyBomProgress('复制成功！', 100);
            
            setTimeout(() => {
                document.getElementById('copyBomProgress').style.display = 'none';
                alert(result.message);
                
                copyBomModal.hide();
                loadBomData(currentProductId);
            }, 500);
        } else {
            document.getElementById('copyBomProgress').style.display = 'none';
            confirmBtn.disabled = false;
            
            if (response.status === 409 && result.has_existing_bom) {
                if (confirm('目标产品已有BOM表，是否覆盖？')) {
                    document.getElementById('copyBomOverwrite').checked = true;
                    confirmCopyBom();
                }
            } else {
                showCopyBomMessage(result.error || '复制失败', 'error');
            }
        }
    } catch (error) {
        console.error('复制BOM失败:', error);
        document.getElementById('copyBomProgress').style.display = 'none';
        confirmBtn.disabled = false;
        showCopyBomMessage('复制失败，请重试', 'error');
    }
}

function showCopyBomProgress(text, percent) {
    const progressContainer = document.getElementById('copyBomProgress');
    const progressBar = progressContainer.querySelector('.progress-bar');
    const progressText = document.getElementById('copyBomProgressText');
    
    progressContainer.style.display = 'block';
    progressBar.style.width = percent + '%';
    progressText.textContent = text;
}

function showCopyBomMessage(message, type) {
    const messageContainer = document.getElementById('copyBomMessage');
    const typeClasses = {
        info: 'alert-info',
        success: 'alert-success',
        warning: 'alert-warning',
        error: 'alert-danger'
    };
    
    messageContainer.innerHTML = `
        <div class="alert ${typeClasses[type] || 'alert-info'} alert-dismissible fade show" role="alert" style="border-radius: 12px;">
            ${escapeHtml(message)}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="关闭"></button>
        </div>
    `;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function quickCopyBom() {
    const keyword = document.getElementById('quickCopySearchInput').value.trim();
    const quickCopyBtn = document.getElementById('quickCopyBtn');
    
    let sourceProductId = null;
    let sourceProductName = '';
    
    if (selectedSourceProductId) {
        sourceProductId = selectedSourceProductId;
        sourceProductName = selectedSourceProductName;
    } else {
        if (!keyword) {
            alert('请输入产品名称或条码');
            return;
        }
        
        quickCopyBtn.disabled = true;
        showQuickCopyProgress('搜索产品中...', 10);
        
        try {
            const searchResponse = await fetch(`/api/v1/purchase-center/api/products/search?keyword=${encodeURIComponent(keyword)}`);
            const searchResult = await searchResponse.json();
            
            if (!searchResult.success || !searchResult.products || searchResult.products.length === 0) {
                hideQuickCopyProgress();
                quickCopyBtn.disabled = false;
                alert('未找到匹配的产品');
                return;
            }
            
            const productsWithBom = searchResult.products.filter(p => p.has_bom);
            
            if (productsWithBom.length === 0) {
                hideQuickCopyProgress();
                quickCopyBtn.disabled = false;
                alert('找到产品没有配置BOM表');
                return;
            }
            
            if (productsWithBom.length === 1) {
                sourceProductId = productsWithBom[0].id;
                sourceProductName = productsWithBom[0].name;
            } else {
                let productListText = '找到多个有BOM的产品，请选择序号：\n';
                productsWithBom.forEach((p, i) => {
                    productListText += `${i + 1}. ${p.name} (${p.material_count}项物料)\n`;
                });
                const selectedIndex = prompt(productListText);
                
                if (selectedIndex === null) {
                    hideQuickCopyProgress();
                    quickCopyBtn.disabled = false;
                    return;
                }
                
                const idx = parseInt(selectedIndex) - 1;
                if (isNaN(idx) || idx < 0 || idx >= productsWithBom.length) {
                    hideQuickCopyProgress();
                    quickCopyBtn.disabled = false;
                    alert('无效的选择');
                    return;
                }
                
                sourceProductId = productsWithBom[idx].id;
                sourceProductName = productsWithBom[idx].name;
            }
        } catch (error) {
            console.error('搜索产品失败:', error);
            hideQuickCopyProgress();
            quickCopyBtn.disabled = false;
            alert('搜索失败，请重试');
            return;
        }
    }
    
    quickCopyBtn.disabled = true;
    showQuickCopyProgress(`正在从 "${sourceProductName}" 复制BOM...`, 40);
    
    try {
        const previewResponse = await fetch(`/api/v1/purchase-center/api/products/${sourceProductId}/bom-preview`);
        const previewResult = await previewResponse.json();
        
        if (!previewResult.success) {
            hideQuickCopyProgress();
            quickCopyBtn.disabled = false;
            alert(previewResult.error || '获取BOM预览失败');
            return;
        }
        
        showQuickCopyProgress('执行复制...', 70);
        
        const copyResponse = await fetch(`/api/v1/purchase-center/api/products/${currentProductId}/copy-bom`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                source_product_id: sourceProductId,
                overwrite: true
            })
        });
        
        const copyResult = await copyResponse.json();
        
        if (copyResult.success) {
            showQuickCopyProgress('复制成功！', 100);
            
            setTimeout(() => {
                hideQuickCopyProgress();
                quickCopyBtn.disabled = false;
                loadBomData(currentProductId);
                document.getElementById('quickCopySearchInput').value = '';
                selectedSourceProductId = null;
                selectedSourceProductName = null;
            }, 500);
        } else {
            hideQuickCopyProgress();
            quickCopyBtn.disabled = false;
            
            if (copyResponse.status === 409 && copyResult.has_existing_bom) {
                if (confirm('目标产品已有BOM表，是否覆盖？')) {
                    const overwriteCopyResponse = await fetch(`/api/v1/purchase-center/api/products/${currentProductId}/copy-bom`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            source_product_id: sourceProductId,
                            overwrite: true
                        })
                    });
                    
                    const overwriteCopyResult = await overwriteCopyResponse.json();
                    
                    if (overwriteCopyResult.success) {
                        showQuickCopyProgress('复制成功！', 100);
                        setTimeout(() => {
                            hideQuickCopyProgress();
                            quickCopyBtn.disabled = false;
                            loadBomData(currentProductId);
                            document.getElementById('quickCopySearchInput').value = '';
                            selectedSourceProductId = null;
                            selectedSourceProductName = null;
                        }, 500);
                    } else {
                        hideQuickCopyProgress();
                        quickCopyBtn.disabled = false;
                        alert(overwriteCopyResult.error || '复制失败');
                    }
                } else {
                    quickCopyBtn.disabled = false;
                }
            } else {
                alert(copyResult.error || '复制失败');
            }
        }
    } catch (error) {
        console.error('快速复制BOM失败:', error);
        hideQuickCopyProgress();
        quickCopyBtn.disabled = false;
        alert('复制失败，请重试');
    }
}

function showQuickCopyProgress(text, percent) {
    const progressContainer = document.getElementById('quickCopyProgress');
    const progressBar = document.getElementById('quickCopyProgressBar');
    const progressText = document.getElementById('quickCopyProgressText');
    
    progressContainer.style.display = 'block';
    progressBar.style.width = percent + '%';
    progressText.textContent = text;
}

function hideQuickCopyProgress() {
    document.getElementById('quickCopyProgress').style.display = 'none';
}

let autocompleteTimeout = null;
let selectedSourceProductId = null;
let selectedSourceProductName = null;
let autocompleteSelectedIndex = -1;

function initAutocomplete() {
    const searchInput = document.getElementById('quickCopySearchInput');
    if (!searchInput) return;

    const copySearchInput = document.getElementById('copyBomSearchInput');
    if (copySearchInput) {
        copySearchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                searchProductForCopy();
            }
        });
    }

    searchInput.addEventListener('input', function(e) {
        const keyword = e.target.value.trim();
        if (keyword.length < 1) {
            hideAutocompleteDropdown();
            return;
        }
        clearTimeout(autocompleteTimeout);
        autocompleteTimeout = setTimeout(() => {
            searchAutocompleteProducts(keyword);
        }, 300);
    });

    searchInput.addEventListener('focus', function() {
        const keyword = this.value.trim();
        if (keyword.length >= 1) {
            searchAutocompleteProducts(keyword);
        }
    });

    searchInput.addEventListener('keydown', function(e) {
        const dropdown = document.getElementById('autocompleteDropdown');
        if (!dropdown || dropdown.style.display === 'none') {
            if (e.key === 'Enter') {
                e.preventDefault();
                hideAutocompleteDropdown();
                quickCopyBom();
            }
            return;
        }

        const items = dropdown.querySelectorAll('.autocomplete-item:not(.disabled)');
        if (items.length === 0) {
            if (e.key === 'Enter') {
                e.preventDefault();
                hideAutocompleteDropdown();
            }
            return;
        }

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            autocompleteSelectedIndex = Math.min(autocompleteSelectedIndex + 1, items.length - 1);
            updateAutocompleteSelection(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            autocompleteSelectedIndex = Math.max(autocompleteSelectedIndex - 1, -1);
            updateAutocompleteSelection(items);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (autocompleteSelectedIndex >= 0 && autocompleteSelectedIndex < items.length) {
                const item = items[autocompleteSelectedIndex];
                const productId = parseInt(item.dataset.id);
                const productName = item.dataset.name;
                const hasBom = item.dataset.hasBom === 'true';
                selectAutocompleteProduct(productId, productName, hasBom);
            } else {
                hideAutocompleteDropdown();
                quickCopyBom();
            }
        } else if (e.key === 'Escape') {
            e.preventDefault();
            hideAutocompleteDropdown();
        }
    });
}

function updateAutocompleteSelection(items) {
    items.forEach((item, idx) => {
        item.classList.toggle('selected', idx === autocompleteSelectedIndex);
    });
    if (autocompleteSelectedIndex >= 0 && autocompleteSelectedIndex < items.length) {
        items[autocompleteSelectedIndex].scrollIntoView({ block: 'nearest' });
    }
}

document.addEventListener('click', function(e) {
    const searchInput = document.getElementById('quickCopySearchInput');
    const dropdown = document.getElementById('autocompleteDropdown');
    if (searchInput && dropdown && !searchInput.contains(e.target) && !dropdown.contains(e.target)) {
        hideAutocompleteDropdown();
    }
});

async function searchAutocompleteProducts(keyword) {
    try {
        const response = await fetch(`/api/v1/purchase-center/api/products/search?keyword=${encodeURIComponent(keyword)}`);
        const result = await response.json();
        autocompleteSelectedIndex = -1;

        if (result.success && result.products.length > 0) {
            renderAutocompleteDropdown(result.products);
        } else {
            showAutocompleteNoResults();
        }
    } catch (error) {
        console.error('搜索产品失败:', error);
        hideAutocompleteDropdown();
    }
}

function renderAutocompleteDropdown(products) {
    const dropdown = document.getElementById('autocompleteDropdown');
    let html = '';

    products.forEach(product => {
        const statusClass = product.has_bom ? 'has-bom' : 'no-bom';
        const statusText = product.has_bom ? '有BOM' : '无BOM';
        const disabledClass = !product.has_bom ? 'disabled' : '';
        const escapedName = escapeHtml(product.name);

        html += `
            <div class="autocomplete-item ${disabledClass}"
                 data-id="${product.id}"
                 data-name="${escapedName}"
                 data-has-bom="${product.has_bom}"
                 onclick="selectAutocompleteProduct(${product.id}, this.dataset.name, ${product.has_bom})">
                <div class="item-left">
                    <div class="product-name">${escapedName}</div>
                    <div class="product-info">
                        ${product.barcode ? '<span class="barcode">条码: ' + escapeHtml(product.barcode) + '</span>' : ''}
                    </div>
                </div>
                <div class="item-right">
                    <span class="product-status ${statusClass}">${statusText}</span>
                </div>
            </div>
        `;
    });

    dropdown.innerHTML = html;
    dropdown.style.display = 'block';
}

function showAutocompleteNoResults() {
    const dropdown = document.getElementById('autocompleteDropdown');
    dropdown.innerHTML = `
        <div class="autocomplete-item" style="cursor: default; opacity: 0.6;">
            <div class="item-left">
                <div class="product-name">未找到匹配的产品</div>
            </div>
        </div>
    `;
    dropdown.style.display = 'block';
}

function hideAutocompleteDropdown() {
    const dropdown = document.getElementById('autocompleteDropdown');
    if (dropdown) {
        dropdown.style.display = 'none';
        autocompleteSelectedIndex = -1;
    }
}

function selectAutocompleteProduct(productId, productName, hasBom) {
    if (!hasBom) {
        return;
    }
    selectedSourceProductId = productId;
    selectedSourceProductName = productName;
    document.getElementById('quickCopySearchInput').value = productName;
    hideAutocompleteDropdown();
}

initAutocomplete();