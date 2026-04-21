"use strict";
console.log('=== Order Page Script Loaded ===');
console.log('=== Version: 2026-03-22-FIXED ===');

let stagedOrders = [];
let selectedStockins = [];
let productsCache = [];
let productDialogTimeout = null;
let editingStagedIndex = -1;
let pendingStockinFetch = null;

function apiFetch(url, options = {}) {
    options.credentials = 'include';
    return fetch(url, options);
}

async function loadStagedOrders() {
    try {
        const response = await apiFetch('/api/v1/staging-orders');
        const result = await response.json();
        
        if (result.success && result.data) {
            stagedOrders = result.data.map(order => ({
                id: order.id,
                customer: order.customer,
                productName: order.product_name,
                productId: order.product_id,
                quantity: order.quantity,
                orderDate: order.order_date,
                note: order.note || '',
                order_type: order.order_type || 'regular',
                country: order.country || '',
                deduct_stock: order.deduct_stock,
                deduct_quantity: order.deduct_quantity || 0,
                is_validated: order.is_validated,
                validation_error: order.validation_error
            }));
            updateStagedOrdersList();
        }
    } catch (error) {
        console.error('加载暂存订单失败:', error);
    }
}

async function searchProducts(query) {
    const autocomplete = document.getElementById('product_autocomplete');
    if (!query) {
        autocomplete.style.display = 'none';
        return;
    }
    try {
        const response = await apiFetch(`/api/v1/aux/product-search?q=${encodeURIComponent(query)}`);
        if (!response.ok) {
            throw new Error(`搜索请求失败 (${response.status})`);
        }
        const data = await response.json();
        autocomplete.innerHTML = '';
        if (!Array.isArray(data) || data.length === 0) {
            autocomplete.style.display = 'none';
            return;
        }
        data.forEach(product => {
            const item = document.createElement('div');
            item.className = 'autocomplete-item';
            item.textContent = product.name;
            item.setAttribute('data-id', product.id);
            item.setAttribute('data-barcode', product.barcode || '');
            item.setAttribute('data-stock', product.current_stock);
            item.addEventListener('click', function() {
                selectProduct(product.name, product.id, product.barcode, product.current_stock);
            });
            autocomplete.appendChild(item);
        });
        autocomplete.style.display = 'block';
    } catch (error) {
        console.error('Error fetching products:', error);
        autocomplete.innerHTML = '';
        autocomplete.style.display = 'none';
    }
}

function selectProduct(name, id, barcode, stock) {
    const searchInput = document.getElementById('product_search');
    searchInput.value = name;
    document.getElementById('product_id').value = id;
    document.getElementById('product_autocomplete').style.display = 'none';
    calculateDeductibleQuantity();
    updateAddNewOrderButtonState();
}

document.getElementById('customer').addEventListener('change', updateAddNewOrderButtonState);
document.getElementById('order_type').addEventListener('change', function() {
    const countryGroup = document.getElementById('country_field_group');
    const countryInput = document.getElementById('country');
    if (this.value === 'custom') {
        countryGroup.style.display = '';
        countryInput.setAttribute('required', '');
    } else {
        countryGroup.style.display = 'none';
        countryInput.removeAttribute('required');
        countryInput.value = '';
    }
    updateAddNewOrderButtonState();
});
document.getElementById('quantity').addEventListener('input', function() {
    calculateDeductibleQuantity();
    updateAddNewOrderButtonState();
    
    // 当订单数量变化时，更新抵扣数量的显示
    const deductibleValueElement = document.getElementById('deductible_value');
    if (deductibleValueElement) {
        const currentDeductible = parseInt(deductibleValueElement.textContent) || 0;
        const newQuantity = parseInt(this.value) || 0;
        
        if (currentDeductible > newQuantity) {
            deductibleValueElement.textContent = newQuantity;
        }
    }
});

function updateAddNewOrderButtonState() {
    console.log('=== updateAddNewOrderButtonState called ===');
    
    const customer = document.getElementById('customer').value;
    const productId = document.getElementById('product_id').value;
    const quantity = parseInt(document.getElementById('quantity').value) || 0;
    const addBtn = document.getElementById('addNewOrderBtn');
    
    console.log('Customer:', customer);
    console.log('Product ID:', productId);
    console.log('Quantity:', quantity);
    console.log('Should enable:', customer && productId && quantity > 0);
    
    if (customer && productId && quantity > 0) {
        addBtn.disabled = false;
        addBtn.classList.add('btn-primary');
        addBtn.classList.remove('btn-secondary');
        console.log('Button enabled');
    } else {
        addBtn.disabled = true;
        addBtn.classList.remove('btn-primary');
        addBtn.classList.add('btn-secondary');
        console.log('Button disabled');
    }
}

async function calculateDeductibleQuantity() {
    const productId = document.getElementById('product_id').value;
    const quantityInput = document.getElementById('quantity');
    const orderQuantity = parseInt(quantityInput.value) || 0;
    const deductibleInfoElement = document.getElementById('deductible_quantity_display');
    
    if (!productId) {
        deductibleInfoElement.innerHTML = '<i class="fas fa-edit me-1" style="font-size: 11px;"></i>抵扣: <span id="deductible_value">0</span>';
        return;
    }
    
    if (orderQuantity <= 0) {
        deductibleInfoElement.innerHTML = '<i class="fas fa-edit me-1" style="font-size: 11px;"></i>抵扣: <span id="deductible_value">0</span>';
        return;
    }
    
    deductibleInfoElement.innerHTML = '<i class="fas fa-edit me-1" style="font-size: 11px;"></i>抵扣: <span id="deductible_value">计算中...</span>';
    
    try {
        const response = await apiFetch(`/api/v1/aux/available-stockins?product_id=${productId}&order_quantity=${orderQuantity}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        if (data && data.length > 0) {
            const totalStockinQuantity = data.reduce((sum, stockin) => sum + stockin.quantity, 0);
            const deductibleQuantity = Math.min(orderQuantity, totalStockinQuantity);
            deductibleInfoElement.innerHTML = `<i class="fas fa-edit me-1" style="font-size: 11px;"></i>抵扣: <span id="deductible_value">${deductibleQuantity}</span>`;
        } else {
            deductibleInfoElement.innerHTML = '<i class="fas fa-edit me-1" style="font-size: 11px;"></i>抵扣: <span id="deductible_value">0</span>';
        }
    } catch (error) {
        console.error('计算可抵扣数量失败:', error);
        deductibleInfoElement.innerHTML = '<i class="fas fa-edit me-1" style="font-size: 11px;"></i>抵扣: <span id="deductible_value">0</span>';
    }
}

let cachedStockinQuantity = 0;

document.getElementById('addNewOrderBtn').addEventListener('click', function() {
    console.log('=== addNewOrderBtn clicked ===');
    
    const customer = document.getElementById('customer').value;
    const productId = document.getElementById('product_id').value;
    const productName = document.getElementById('product_search').value;
    const quantity = parseInt(document.getElementById('quantity').value) || 0;
    const orderDate = document.getElementById('order_date').value;
    const note = document.getElementById('note').value;
    const deductStock = document.getElementById('deduct_stock').value;
    const orderType = document.getElementById('order_type').value;
    const country = orderType === 'custom' ? (document.getElementById('country').value.trim() || '') : '';

    if (orderType === 'custom' && !country) {
        alert('定制订单必须填写国家名称！');
        return;
    }

    console.log('Collected values:', { customer, productId, productName, quantity, orderDate, orderType, country });

    let deductibleQuantity = 0;
    const deductibleValueElement = document.getElementById('deductible_value');

    if (deductStock === 'on' && deductibleValueElement) {
        // 只有在抵扣状态为 on 时才获取抵扣数量
        deductibleQuantity = parseInt(deductibleValueElement.textContent) || 0;
    }
    
    console.log('Deductible quantity:', deductibleQuantity, 'Deduct stock:', deductStock);
    
    const order = {
        customer,
        productId,
        productName,
        quantity,
        orderDate,
        note,
        order_type: orderType,
        country,
        deduct_stock: deductStock === 'on',
        deduct_quantity: deductibleQuantity,
        id: Date.now()
    };
    
    console.log('Adding order to stagedOrders:', order);
    stagedOrders.push(order);
    console.log('stagedOrders now:', stagedOrders);
    
    updateStagedOrdersList();
    clearForm();
    console.log('=== addNewOrderBtn click completed ===');
});

function updateStagedOrdersList() {
    const listContainer = document.getElementById('stagedOrdersList');
    const countBadge = document.getElementById('stagedCountBadge');
    const totalCount = document.getElementById('totalStagedCount');
    const submitBtn = document.getElementById('submitAllOrdersBtn');
    
    if (stagedOrders.length === 0) {
        listContainer.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="fas fa-box-open fa-3x mb-3" style="opacity: 0.3;"></i>
                <p>暂无暂存订单</p>
            </div>
        `;
        countBadge.style.display = 'none';
        totalCount.textContent = '共 0 个';
        submitBtn.disabled = true;
    } else {
        countBadge.style.display = 'inline-block';
        countBadge.textContent = `已暂存: ${stagedOrders.length}`;
        totalCount.textContent = `共 ${stagedOrders.length} 个`;
        submitBtn.disabled = false;
        
        listContainer.innerHTML = stagedOrders.map((order, index) => `
            <div class="card mb-2" style="border: 2px solid var(--plush-blue-light);">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="d-flex align-items-center gap-3 flex-wrap">
                            <span class="text-muted small">
                                <i class="fas fa-user me-1"></i>${escapeHtml(order.customer)}
                            </span>
                            <span class="text-muted small">
                                <i class="fas fa-calendar-alt me-1"></i>${escapeHtml(order.orderDate || '-')}
                            </span>
                            <span>
                                <i class="fas fa-shopping-cart text-primary me-1"></i>${escapeHtml(order.productName)}
                            </span>
                            <span class="badge bg-light text-dark">数量: ${order.quantity}</span>
                            ${order.deduct_quantity > 0 ? `<span class="badge bg-light text-dark">抵扣: ${order.deduct_quantity}</span>` : ''}
                            ${order.order_type === 'custom' ? `<span class="badge bg-info text-dark">定制</span>` : `<span class="badge bg-light text-dark">常规</span>`}
                            ${order.order_type === 'custom' && order.country ? `<span class="badge bg-warning text-dark">${escapeHtml(order.country)}</span>` : ''}
                            ${order.note ? `<span class="badge bg-light text-dark">备注: ${escapeHtml(order.note)}</span>` : ''}
                        </div>
                        <div class="d-flex gap-1 ms-2">
                            <button class="btn btn-sm btn-outline-warning" onclick="editStagedOrder(${index})">
                                <i class="fas fa-edit"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-danger" onclick="deleteStagedOrder(${index})">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `).join('');
    }
}

function viewStagedOrder(index) {
    const order = stagedOrders[index];
}

let currentEditOrder = null;
let availableStockinQuantity = 0;
let isEditModalOpen = false;

async function fetchAvailableStockins(productId, customer) {
    try {
        const response = await apiFetch(`/api/v1/aux/available-stockins?product_id=${productId}&customer=${encodeURIComponent(customer)}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        return data.reduce((sum, stockin) => sum + (stockin.available || 0), 0);
    } catch (error) {
        console.error('获取备货数量失败:', error);
        return 0;
    }
}

async function editStagedOrder(index) {
    if (isEditModalOpen) return;
    isEditModalOpen = true;

    editingStagedIndex = index;
    const order = stagedOrders[index];
    currentEditOrder = order;
    
    const content = `
        <div class="mb-3">
            <label class="form-label">订单类型</label>
            <select class="form-select" id="editOrderType" onchange="toggleEditCountryField()">
                <option value="regular" ${order.order_type !== 'custom' ? 'selected' : ''}>常规订单</option>
                <option value="custom" ${order.order_type === 'custom' ? 'selected' : ''}>定制订单</option>
            </select>
        </div>
        <div class="mb-3" id="editCountryGroup" style="${order.order_type === 'custom' ? '' : 'display:none;'}">
            <label class="form-label">国家名称 <span class="text-danger">*</span></label>
            <input type="text" class="form-control" id="editCountry" value="${escapeHtml(order.country || '')}" maxlength="100" placeholder="输入或选择国家">
        </div>
        <div class="mb-3">
            <label class="form-label">客户名称</label>
            <select class="form-select" id="editCustomer" onchange="updateEditAvailableStockins()">
                ${window.__customers.map(c => `<option value="${escapeHtml(c.name)}" ${order.customer === c.name ? 'selected' : ''}>${escapeHtml(c.name)}</option>`).join('')}
            </select>
        </div>
        <div class="mb-3">
            <label class="form-label">产品名称</label>
            <input type="text" class="form-control" id="editProductName" value="${escapeHtml(order.productName)}" readonly>
            <input type="hidden" id="editProductId" value="${order.productId}">
        </div>
        <div class="mb-3">
            <label class="form-label">订单数量</label>
            <input type="number" class="form-control" id="editQuantity" value="${order.quantity}" min="1" oninput="updateEditDeductibleMax()">
        </div>
        <div class="mb-3">
            <label class="form-label">抵扣备货数量</label>
            <div class="input-group">
                <input type="number" class="form-control" id="editDeductibleQuantity" value="${order.deduct_quantity}" min="0" max="${order.quantity}" oninput="validateEditDeductible()">
                <span class="input-group-text">件</span>
            </div>
            <div id="editDeductibleInfo" class="mt-2">
                <small class="text-muted">
                    <i class="fas fa-info-circle me-1"></i>
                    <span id="editAvailableStockText">正在获取备货数量...</span>
                </small>
            </div>
        </div>
        <div class="mb-3">
            <label class="form-label">备注</label>
            <textarea class="form-control" id="editNote" rows="2">${escapeHtml(order.note || '')}</textarea>
        </div>
    `;
    
    document.getElementById('editStagedOrderContent').innerHTML = content;
    const modal = new bootstrap.Modal(document.getElementById('editStagedOrderModal'));
    modal.show();
    
    await updateEditAvailableStockins();
}

function toggleEditCountryField() {
    const orderType = document.getElementById('editOrderType').value;
    const countryGroup = document.getElementById('editCountryGroup');
    const countryInput = document.getElementById('editCountry');
    if (orderType === 'custom') {
        countryGroup.style.display = '';
        countryInput.setAttribute('required', '');
    } else {
        countryGroup.style.display = 'none';
        countryInput.removeAttribute('required');
        countryInput.value = '';
    }
}

async function updateEditAvailableStockins() {
    const productId = document.getElementById('editProductId')?.value;
    const customer = document.getElementById('editCustomer')?.value;
    const infoElement = document.getElementById('editAvailableStockText');
    const deductibleInput = document.getElementById('editDeductibleQuantity');
    
    if (!productId || !customer) {
        if (infoElement) {
            infoElement.textContent = '请选择产品和客户以查看可用备货';
        }
        availableStockinQuantity = 0;
        return;
    }
    
    availableStockinQuantity = await fetchAvailableStockins(productId, customer);
    
    if (infoElement) {
        if (availableStockinQuantity > 0) {
            infoElement.innerHTML = `
                <i class="fas fa-check-circle text-success me-1"></i>
                当前可用备货: <strong class="text-success">${availableStockinQuantity}</strong> 件
            `;
        } else {
            infoElement.innerHTML = `
                <i class="fas fa-exclamation-circle text-warning me-1"></i>
                暂无可用备货
            `;
        }
    }
    
    validateEditDeductible();
}

function updateEditDeductibleMax() {
    const editQuantity = parseInt(document.getElementById('editQuantity').value) || 1;
    const editDeductibleInput = document.getElementById('editDeductibleQuantity');
    
    const maxDeductible = Math.min(editQuantity, availableStockinQuantity);
    editDeductibleInput.max = maxDeductible;
    
    const currentDeductible = parseInt(editDeductibleInput.value) || 0;
    if (currentDeductible > maxDeductible) {
        editDeductibleInput.value = maxDeductible;
    }
    
    validateEditDeductible();
}

function validateEditDeductible() {
    const deductibleInput = document.getElementById('editDeductibleQuantity');
    const infoElement = document.getElementById('editDeductibleInfo');
    const currentValue = parseInt(deductibleInput.value) || 0;
    const orderQuantity = parseInt(document.getElementById('editQuantity').value) || 1;
    
    if (!infoElement) return;
    
    let isValid = true;
    let errorMessage = '';
    
    const remainingStock = availableStockinQuantity - currentValue;
    
    if (currentValue > orderQuantity) {
        isValid = false;
        errorMessage = '抵扣数量不能超过订单数量';
    } else if (currentValue > availableStockinQuantity) {
        isValid = false;
        errorMessage = `抵扣数量不能超过可用备货数量 (${availableStockinQuantity} 件)`;
    }
    
    if (!isValid) {
        deductibleInput.classList.add('is-invalid');
        infoElement.innerHTML = `
            <small class="text-danger">
                <i class="fas fa-times-circle me-1"></i>
                ${errorMessage}
            </small>
        `;
    } else {
        deductibleInput.classList.remove('is-invalid');
        if (availableStockinQuantity > 0) {
            infoElement.innerHTML = `
                <small class="text-success">
                    <i class="fas fa-check-circle me-1"></i>
                    当前可用备货: <strong>${availableStockinQuantity}</strong> 件
                    ${currentValue > 0 ? `
                        <span class="ms-2">
                            <i class="fas fa-arrow-right me-1"></i>
                            抵扣后剩余: <strong class="text-primary">${remainingStock}</strong> 件
                        </span>
                    ` : ''}
                </small>
            `;
        } else {
            infoElement.innerHTML = `
                <small class="text-muted">
                    <i class="fas fa-info-circle me-1"></i>
                    暂无可用备货
                </small>
            `;
        }
    }
}

document.getElementById('saveEditStagedOrderBtn').addEventListener('click', async function() {
    if (editingStagedIndex !== -1) {
        const newDeductibleQuantity = parseInt(document.getElementById('editDeductibleQuantity').value) || 0;
        const newQuantity = parseInt(document.getElementById('editQuantity').value) || 1;
        const newCustomer = document.getElementById('editCustomer').value;
        const productId = document.getElementById('editProductId').value;

        const currentAvailableStock = await fetchAvailableStockins(productId, newCustomer);

        const newOrderType = document.getElementById('editOrderType').value;
        const newCountry = newOrderType === 'custom' ? (document.getElementById('editCountry').value.trim() || '') : '';
        if (newOrderType === 'custom' && !newCountry) {
            alert('定制订单必须填写国家名称！');
            return;
        }

        if (newDeductibleQuantity > newQuantity) {
            alert('抵扣备货数量不能超过订单数量！');
            return;
        }

        if (newDeductibleQuantity > currentAvailableStock) {
            alert(`抵扣备货数量不能超过可用备货数量！\n当前可用备货: ${currentAvailableStock} 件\n您设置的抵扣数量: ${newDeductibleQuantity} 件`);
            return;
        }

        stagedOrders[editingStagedIndex].customer = newCustomer;
        stagedOrders[editingStagedIndex].quantity = newQuantity;
        stagedOrders[editingStagedIndex].deduct_quantity = newDeductibleQuantity;
        stagedOrders[editingStagedIndex].note = document.getElementById('editNote').value;
        stagedOrders[editingStagedIndex].order_type = newOrderType;
        stagedOrders[editingStagedIndex].country = newCountry;

        if (stagedOrders[editingStagedIndex].deduct_quantity > 0) {
            stagedOrders[editingStagedIndex].deduct_stock = true;
        } else {
            stagedOrders[editingStagedIndex].deduct_stock = false;
        }

        updateStagedOrdersList();
        bootstrap.Modal.getInstance(document.getElementById('editStagedOrderModal')).hide();
        editingStagedIndex = -1;
        currentEditOrder = null;
    }
});

document.getElementById('editStagedOrderModal').addEventListener('hidden.bs.modal', function() {
    isEditModalOpen = false;
});

function deleteStagedOrder(index) {
    if (confirm('确定要删除这个暂存订单吗？')) {
        stagedOrders.splice(index, 1);
        updateStagedOrdersList();
    }
}

function clearForm() {
    document.getElementById('customer').value = '';
    document.getElementById('product_search').value = '';
    document.getElementById('product_id').value = '';
    document.getElementById('quantity').value = '1';
    document.getElementById('note').value = '';
    document.getElementById('order_type').value = 'regular';
    document.getElementById('country').value = '';
    document.getElementById('country_field_group').style.display = 'none';
    document.getElementById('country').removeAttribute('required');
    document.getElementById('deduct_stock').value = 'off';
    document.getElementById('deductible_quantity_display').innerHTML = '<i class="fas fa-edit me-1" style="font-size: 11px;"></i>抵扣: <span id="deductible_value">0</span>';
    
    const deductBtn = document.getElementById('deductPreviewBtn');
    deductBtn.classList.remove('btn-success');
    deductBtn.classList.add('btn-outline-secondary');
    
    currentAvailableStock = 0;
    hideStockinInfoDisplay();
    
    updateAddNewOrderButtonState();
    
    bindDeductibleInputEvent();
}

let currentAvailableStock = 0;

function updateStockinInfoDisplay(availableStock, deductibleValue) {
    const infoDisplay = document.getElementById('stockin_info_display');
    const infoText = document.getElementById('stockin_info_text');
    
    if (!infoDisplay || !infoText) return;
    
    currentAvailableStock = availableStock;
    
    if (availableStock > 0) {
        const remaining = availableStock - deductibleValue;
        infoDisplay.style.display = 'block';
        
        if (deductibleValue > 0) {
            if (deductibleValue <= availableStock) {
                infoText.innerHTML = `
                    <span class="text-success">
                        <i class="fas fa-check-circle me-1"></i>
                        当前可用备货: <strong>${availableStock}</strong> 件
                    </span>
                    <span class="ms-2 text-primary">
                        <i class="fas fa-arrow-right me-1"></i>
                        抵扣后剩余: <strong>${remaining}</strong> 件
                    </span>
                `;
            } else {
                infoText.innerHTML = `
                    <span class="text-danger">
                        <i class="fas fa-times-circle me-1"></i>
                        抵扣数量超过可用备货！当前可用: ${availableStock} 件
                    </span>
                `;
            }
        } else {
            infoText.innerHTML = `
                <span class="text-success">
                    <i class="fas fa-check-circle me-1"></i>
                    当前可用备货: <strong>${availableStock}</strong> 件
                </span>
            `;
        }
    } else {
        infoDisplay.style.display = 'block';
        infoText.innerHTML = `
            <span class="text-warning">
                <i class="fas fa-exclamation-circle me-1"></i>
                暂无可用备货
            </span>
        `;
    }
}

function hideStockinInfoDisplay() {
    const infoDisplay = document.getElementById('stockin_info_display');
    if (infoDisplay) {
        infoDisplay.style.display = 'none';
    }
}

// 绑定抵扣数量自定义输入事件
function bindDeductibleInputEvent() {
    const deductibleDisplay = document.getElementById('deductible_quantity_display');
    if (deductibleDisplay) {
        const newDeductibleDisplay = deductibleDisplay.cloneNode(true);
        deductibleDisplay.parentNode.replaceChild(newDeductibleDisplay, deductibleDisplay);
        
        newDeductibleDisplay.addEventListener('click', function() {
            const deductibleValueElement = document.getElementById('deductible_value');
            const currentValue = deductibleValueElement ? parseInt(deductibleValueElement.textContent) || 0 : 0;
            const orderQuantity = parseInt(document.getElementById('quantity').value) || 0;
            const productId = document.getElementById('product_id').value;
            const customer = document.getElementById('customer').value;
            
            let maxValue = orderQuantity;
            let availableStock = 0;
            
            const input = document.createElement('input');
            input.type = 'number';
            input.min = '0';
            input.max = maxValue;
            input.value = currentValue;
            input.style.width = '100px';
            input.style.padding = '4px 8px';
            input.style.border = '2px solid #0d6efd';
            input.style.borderRadius = '8px';
            input.style.fontSize = '14px';
            input.style.textAlign = 'center';
            
            const container = document.getElementById('deductible_quantity_container');
            container.innerHTML = '';
            container.appendChild(input);
            
            input.focus();
            input.select();
            
            const infoDisplay = document.getElementById('stockin_info_display');
            const infoText = document.getElementById('stockin_info_text');
            
            if (infoDisplay && infoText) {
                infoDisplay.style.display = 'block';
                infoText.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>正在获取备货信息...';
            }

            if (pendingStockinFetch) {
                pendingStockinFetch.cancel();
                pendingStockinFetch = null;
            }

            const controller = new AbortController();
            pendingStockinFetch = { controller, cancel: () => controller.abort() };

            async function fetchAndUpdateStock() {
                if (!productId || !customer) {
                    if (infoText) {
                        infoText.innerHTML = `
                            <span class="text-muted">
                                <i class="fas fa-info-circle me-1"></i>
                                请先选择产品和客户
                            </span>
                        `;
                    }
                    return;
                }

                try {
                    const response = await apiFetch(`/api/v1/aux/available-stockins?product_id=${productId}&customer=${encodeURIComponent(customer)}`, {
                        signal: controller.signal
                    });
                    if (!response.ok) throw new Error('获取备货信息失败');

                    const data = await response.json();
                    if (data && Array.isArray(data)) {
                        availableStock = data.reduce((sum, stockin) => sum + (stockin.available || 0), 0);
                        currentAvailableStock = availableStock;
                        maxValue = Math.min(orderQuantity, availableStock);
                        input.max = maxValue;

                        const currentInputValue = parseInt(input.value) || 0;
                        updateStockinInfoDisplay(availableStock, currentInputValue);

                        if (currentInputValue > maxValue) {
                            input.value = maxValue;
                            updateStockinInfoDisplay(availableStock, maxValue);
                        }
                    }
                } catch (error) {
                    if (error.name === 'AbortError') {
                        console.log('Previous stock fetch cancelled');
                        return;
                    }
                    console.error('获取备货信息失败:', error);
                    if (infoText) {
                        infoText.innerHTML = `
                            <span class="text-danger">
                                <i class="fas fa-times-circle me-1"></i>
                                获取备货信息失败，请稍后重试
                            </span>
                        `;
                    }
                } finally {
                    if (pendingStockinFetch && pendingStockinFetch.controller === controller) {
                        pendingStockinFetch = null;
                    }
                }
            }
            
            fetchAndUpdateStock();
            
            input.addEventListener('input', function() {
                const inputValue = parseInt(input.value) || 0;
                
                if (inputValue < 0) {
                    input.value = 0;
                }
                
                if (currentAvailableStock > 0) {
                    updateStockinInfoDisplay(currentAvailableStock, parseInt(input.value) || 0);
                }
            });
            
            let inputProcessed = false;
            async function handleInputComplete() {
                if (!input || inputProcessed) return;
                
                inputProcessed = true;
                
                const newValue = parseInt(input.value) || 0;
                
                let finalValue = newValue;
                if (productId && customer) {
                    try {
                        const response = await apiFetch(`/api/v1/aux/available-stockins?product_id=${productId}&customer=${encodeURIComponent(customer)}`);
                        if (response.ok) {
                            const data = await response.json();
                            if (data && Array.isArray(data)) {
                                const availableStock = data.reduce((sum, stockin) => sum + (stockin.available || 0), 0);
                                const maxAllowed = Math.min(orderQuantity, availableStock);
                                
                                if (newValue > maxAllowed) {
                                    alert(`抵扣数量不能超过可用备货数量！\n当前可用备货: ${availableStock} 件\n订单数量: ${orderQuantity} 件\n最大可抵扣: ${maxAllowed} 件`);
                                    finalValue = maxAllowed;
                                } else if (newValue < 0) {
                                    finalValue = 0;
                                } else {
                                    finalValue = newValue;
                                }
                                
                                updateStockinInfoDisplay(availableStock, finalValue);
                            }
                        }
                    } catch (error) {
                        console.error('校验抵扣数量失败:', error);
                        finalValue = Math.max(0, Math.min(newValue, orderQuantity));
                    }
                } else {
                    finalValue = Math.max(0, Math.min(newValue, orderQuantity));
                }
                
                container.innerHTML = `
                    <small id="deductible_quantity_display" class="text-muted deductible-display" style="cursor: pointer; padding: 8px 14px; border-radius: 12px; border: 2px dashed #adb5bd; background-color: #f8f9fa;">
                        <i class="fas fa-edit me-1" style="font-size: 11px;"></i>抵扣: <span id="deductible_value">${finalValue}</span>
                    </small>
                `;
                
                bindDeductibleInputEvent();
            }
            
            input.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    handleInputComplete();
                }
            });
            
            input.addEventListener('blur', handleInputComplete);
        });
    }
}

document.getElementById('submitAllOrdersBtn').addEventListener('click', async function() {
    console.log('=== submitAllOrdersBtn clicked ===');
    console.log('stagedOrders:', stagedOrders);
    
    if (stagedOrders.length === 0) {
        console.log('No staged orders, returning');
        return;
    }
    
    const btn = this;
    const btnText = document.getElementById('submitBtnText');
    const btnSpinner = document.getElementById('submitBtnSpinner');
    
    btn.disabled = true;
    btnText.textContent = '校验备货数量...';
    btnSpinner.style.display = 'inline-block';
    
    try {
        btnText.textContent = '校验备货数量...';

        const ordersNeedingDeduction = stagedOrders.filter(o => o.deduct_stock === true && o.deduct_quantity > 0);

        if (ordersNeedingDeduction.length > 0) {
            const uniqueKeys = {};
            ordersNeedingDeduction.forEach(order => {
                const key = `${order.productId}-${order.customer}`;
                if (!uniqueKeys[key]) {
                    uniqueKeys[key] = { productId: order.productId, customer: order.customer, orders: [] };
                }
                uniqueKeys[key].orders.push(order);
            });

            for (const key in uniqueKeys) {
                const { productId, customer, orders } = uniqueKeys[key];
                try {
                    const response = await apiFetch(`/api/v1/aux/available-stockins?product_id=${productId}&customer=${encodeURIComponent(customer)}`);
                    if (!response.ok) throw new Error('API request failed');

                    const data = await response.json();
                    if (data && Array.isArray(data)) {
                        const availableStock = data.reduce((sum, stockin) => sum + (stockin.available || 0), 0);

                        for (const order of orders) {
                            const maxAllowed = Math.min(order.quantity, availableStock);
                            if (order.deduct_quantity > maxAllowed) {
                                alert(`订单 (${order.productName}) 的抵扣数量超过可用备货！\n当前可用备货: ${availableStock} 件\n最大可抵扣: ${maxAllowed} 件`);
                                btn.disabled = false;
                                btnText.textContent = '添加订单';
                                btnSpinner.style.display = 'none';
                                return;
                            }
                        }
                    }
                } catch (error) {
                    console.error('校验备货数量失败:', error);
                    alert('校验备货数量失败，请稍后重试');
                    btn.disabled = false;
                    btnText.textContent = '添加订单';
                    btnSpinner.style.display = 'none';
                    return;
                }
            }
        }

        btnText.textContent = '提交中...';
        
        // 转换字段名以匹配后端API期望的格式（下划线命名）
        const ordersForApi = stagedOrders.map(order => ({
            product_id: order.productId,
            customer: order.customer,
            quantity: order.quantity,
            order_date: order.orderDate,
            note: order.note,
            order_type: order.order_type || 'regular',
            country: order.country || '',
            deduct_stock: order.deduct_stock,
            deduct_quantity: order.deduct_quantity
        }));
        
        console.log('Sending request to /api/v1/aux/batch-submit-orders');
        console.log('Orders for API:', ordersForApi);
        const response = await apiFetch('/api/v1/aux/batch-submit-orders', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                orders: ordersForApi
            })
        });
        
        console.log('Response received:', response.status);
        const result = await response.json();
        console.log('Response data:', result);
        
        btnSpinner.style.display = 'none';
        
        if (result.success) {
            btnText.textContent = '提交成功!';
            
            // 检查结果中是否有失败的订单
            if (result.results) {
                const failedOrders = result.results.filter(r => !r.success);
                if (failedOrders.length > 0) {
                    console.error('失败的订单:', failedOrders);
                    alert(`${failedOrders.length} 个订单提交失败，请查看控制台了解详情`);
                }
            }
            
            stagedOrders = [];
            updateStagedOrdersList();
            
            setTimeout(() => {
                window.location.reload();
            }, 1500);
        } else {
            alert('提交失败: ' + (result.error || '未知错误'));
            btn.disabled = false;
            btnText.textContent = '添加订单';
        }
    } catch (error) {
        console.error('批量提交失败:', error);
        btnSpinner.style.display = 'none';
        btn.disabled = false;
        btnText.textContent = '添加订单';
    }
    console.log('=== submitAllOrdersBtn click completed ===');
});

document.addEventListener('DOMContentLoaded', async function() {
    console.log('=== DOMContentLoaded ===');

    if (performance.navigation.type === 1) {
        try {
            await apiFetch('/api/v1/staging-orders/clear', { method: 'DELETE' });
        } catch (e) {
            console.log('Clear staging on refresh failed:', e);
        }
    }

    console.log('Checking elements...');
    const addBtn = document.getElementById('addNewOrderBtn');
    const submitBtn = document.getElementById('submitAllOrdersBtn');
    
    console.log('addNewOrderBtn:', addBtn);
    console.log('submitAllOrdersBtn:', submitBtn);
    
    // 设置订单时间默认值为今天
    const orderDateInput = document.getElementById('order_date');
    if (orderDateInput) {
        const today = new Date();
        const year = today.getFullYear();
        const month = String(today.getMonth() + 1).padStart(2, '0');
        const day = String(today.getDate()).padStart(2, '0');
        orderDateInput.value = `${year}-${month}-${day}`;
    }
    
    updateAddNewOrderButtonState();
    
    // 绑定抵扣数量自定义输入功能
    bindDeductibleInputEvent();
    
    // ========== 绑定备货按钮事件 ==========
    const deductPreviewBtn = document.getElementById('deductPreviewBtn');
    console.log('deductPreviewBtn element:', deductPreviewBtn);
    if (deductPreviewBtn) {
        console.log('Binding deductPreviewBtn click event');
        deductPreviewBtn.addEventListener('click', async function () {
            console.log('deductPreviewBtn clicked!');
            const productId = document.getElementById('product_id').value;
            const customer = document.getElementById('customer').value;
            const quantityInput = document.getElementById('quantity');
            const orderQuantity = parseInt(quantityInput.value) || 0;
            const btn = document.getElementById('deductPreviewBtn');
            const displayElement = document.getElementById('deductible_quantity_display');
            
            const isActive = btn.classList.contains('btn-success');
            
            if (isActive) {
                btn.classList.remove('btn-success');
                btn.classList.add('btn-outline-secondary');
                document.getElementById('deduct_stock').value = 'off';
            } else {
                if (!productId) {
                    return;
                }
                if (!customer) {
                    alert('请先选择客户');
                    return;
                }
                if (orderQuantity <= 0) {
                    return;
                }
                
                btn.classList.remove('btn-outline-secondary');
                btn.classList.add('btn-success');
                document.getElementById('deduct_stock').value = 'on';
                
                try {
                    const response = await apiFetch(`/api/v1/aux/available-stockins?product_id=${productId}&customer=${encodeURIComponent(customer)}`);
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    const data = await response.json();
                    if (data && Array.isArray(data) && data.length > 0) {
                        cachedStockinQuantity = data.reduce((sum, stockin) => {
                            return sum + (stockin.available || 0);
                        }, 0);
                        currentAvailableStock = cachedStockinQuantity;
                        const deductibleQuantity = Math.max(0, Math.min(orderQuantity, cachedStockinQuantity));
                        
                        if (deductibleQuantity === 0) {
                            alert(`无可抵扣数量！\n当前可用备货: ${cachedStockinQuantity} 件`);
                            btn.classList.remove('btn-success');
                            btn.classList.add('btn-outline-secondary');
                            document.getElementById('deduct_stock').value = 'off';
                            displayElement.innerHTML = '<i class="fas fa-edit me-1" style="font-size: 11px;"></i>抵扣: <span id="deductible_value">0</span>';
                            updateStockinInfoDisplay(cachedStockinQuantity, 0);
                        } else {
                            displayElement.innerHTML = `<i class="fas fa-edit me-1" style="font-size: 11px;"></i>抵扣: <span id="deductible_value">${deductibleQuantity}</span>`;
                            updateStockinInfoDisplay(cachedStockinQuantity, deductibleQuantity);
                        }
                        bindDeductibleInputEvent();
                    } else {
                        alert('无可抵扣数量！\n暂无可用备货记录');
                        btn.classList.remove('btn-success');
                        btn.classList.add('btn-outline-secondary');
                        document.getElementById('deduct_stock').value = 'off';
                        cachedStockinQuantity = 0;
                        currentAvailableStock = 0;
                        displayElement.innerHTML = '<i class="fas fa-edit me-1" style="font-size: 11px;"></i>抵扣: <span id="deductible_value">0</span>';
                        updateStockinInfoDisplay(0, 0);
                        bindDeductibleInputEvent();
                    }
                } catch (error) {
                    console.error('获取备货信息失败:', error);
                    alert('获取备货信息失败，请稍后重试');
                    cachedStockinQuantity = 0;
                    currentAvailableStock = 0;
                    displayElement.innerHTML = '<i class="fas fa-edit me-1" style="font-size: 11px;"></i>抵扣: <span id="deductible_value">0</span>';
                    btn.classList.remove('btn-success');
                    btn.classList.add('btn-outline-secondary');
                    const infoText = document.getElementById('stockin_info_text');
                    if (infoText) {
                        infoText.innerHTML = `
                                <span class="text-danger">
                                    <i class="fas fa-times-circle me-1"></i>
                                    获取备货信息失败，请稍后重试
                                </span>
                            `;
                        document.getElementById('stockin_info_display').style.display = 'block';
                    }
                    bindDeductibleInputEvent();
                }
            }
        });
    }
    
    // ========== 批量上传功能 ==========
    initBatchUpload();

    // ========== 加载暂存订单列表 ==========
    // 等待清空操作完成后再加载
    loadStagedOrders();
    // ========== 订单列表分组显示 ==========
    renderGroupedOrderList();

    console.log('=== DOMContentLoaded completed ===');
});

window.addEventListener('beforeunload', function() {
    if (stagedOrders.length > 0) {
        apiFetch('/api/v1/staging-orders/clear', { method: 'DELETE', keepalive: true });
    }
    stagedOrders = [];
});

// 订单列表分组和折叠功能 - 全局函数
window.toggleOrderGroup = function(contentId) {
    const content = document.getElementById(contentId);
    if (!content) return;
    
    const isExpanded = content.classList.contains('expanded');
    const icon = document.querySelector(`[data-toggle-icon-for="${contentId}"]`);
    
    if (isExpanded) {
        content.classList.remove('expanded');
        if (icon) icon.style.transform = 'rotate(0deg)';
    } else {
        content.classList.add('expanded');
        if (icon) icon.style.transform = 'rotate(180deg)';
    }
};

// 全局订单数据存储
let globalOrdersData = [];

function renderGroupedOrderList() {
    const ordersData = window.__ordersData || [];
    // 存储到全局变量，供删除后局部更新使用
    globalOrdersData = ordersData;
    const container = document.getElementById('orderListGrouped');
    
    if (!ordersData || ordersData.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="fas fa-box-open fa-3x mb-3" style="opacity: 0.3;"></i>
                <p>暂无订单，请先添加</p>
            </div>
        `;
        return;
    }
    
    // 按订单日期分组
    const groupedOrders = {};
    ordersData.forEach(order => {
        // 直接使用后端返回的order_date字段（格式: YYYY-MM-DD HH:MM）
        let dateKey = '未知日期';
        if (order.order_date) {
            // 提取日期部分（去掉时间）
            dateKey = order.order_date.split(' ')[0];
        }
        
        if (!groupedOrders[dateKey]) {
            groupedOrders[dateKey] = [];
        }
        groupedOrders[dateKey].push(order);
    });
    
    // 按日期降序排序
    const sortedDates = Object.keys(groupedOrders).sort((a, b) => b.localeCompare(a));
    
    // 生成HTML
    let html = '';
    sortedDates.forEach((date, index) => {
        const orders = groupedOrders[date];
        
        // 对同一天内的数据按(客户+产品ID)进行汇总
        const summaryMap = {};
        orders.forEach(order => {
            const key = `${order.customer}|||${order.product.id}|||${order.order_type || 'regular'}`;
            
            if (!summaryMap[key]) {
                summaryMap[key] = {
                    customer: order.customer,
                    product: order.product,
                    order_type: order.order_type || 'regular',
                    country: order.country || '',
                    quantity: 0,
                    deduct_quantity: 0,
                    notes: [],
                    ids: [],
                    is_locked: false,
                    locked_by_name: ''
                };
            }
            
            summaryMap[key].quantity += order.quantity;
            summaryMap[key].deduct_quantity += (order.deduct_quantity || 0);
            if (order.note && !summaryMap[key].notes.includes(order.note)) {
                summaryMap[key].notes.push(order.note);
            }
            summaryMap[key].ids.push(order.id);
            if (order.is_locked) {
                summaryMap[key].is_locked = true;
                summaryMap[key].locked_by_name = order.locked_by_name || '';
            }
        });
        
        const summaryList = Object.values(summaryMap);
        const totalCount = summaryList.reduce((sum, item) => sum + item.quantity, 0);
        const totalRecords = orders.length;
        const contentId = `content-${date.replace(/-/g, '')}`;
        
        html += `
            <div class="order-date-group mb-3">
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center" 
                         style="background: white; border-bottom: 2px solid #e9ecef; cursor: pointer;"
                         onclick="window.toggleOrderGroup('${contentId}')">
                        <div class="d-flex align-items-center flex-grow-1">
                            <i class="fas fa-calendar-alt text-primary me-2"></i>
                            <strong>${escapeHtml(date)}</strong>
                            <span class="badge ms-2">${totalRecords} 条记录</span>
                            <span class="badge ms-1">共 ${totalCount} 件</span>
                        </div>
                        <div class="ms-2">
                            <i class="fas fa-chevron-down text-muted toggle-icon" data-toggle-icon-for="${contentId}"></i>
                        </div>
                    </div>
                    <div class="order-collapse-content" id="${contentId}">
                        <div class="card-body p-0">
                            <table class="table table-hover mb-0">
                                <thead>
                                    <tr>
                                        <th style="width: 10%;">客户</th>
                                        <th style="width: 8%;">产品图片</th>
                                        <th style="width: 18%;">产品名称</th>
                                        <th style="width: 10%;">69 码</th>
                                        <th style="width: 7%;">类型</th>
                                        <th style="width: 8%;">数量</th>
                                        <th style="width: 10%;">抵扣备货</th>
                                        <th style="width: 8%;">备注</th>
                                        <th style="width: 13%;">操作</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${summaryList.map(item => {
                                        const isSummary = item.ids.length > 1;
                                        const notesDisplay = item.notes.length > 0 ? item.notes.join('; ') : '-';
                                        const isLocked = item.is_locked || false;
                                        const lockedByName = item.locked_by_name || '';
                                        const deductDisplay = item.deduct_quantity > 0 
                                            ? `<span class="badge bg-success">抵扣: ${item.deduct_quantity}</span>` 
                                            : '<span class="badge bg-secondary">否</span>';
                                        return `
                                        <tr class="${isLocked ? 'table-warning' : ''}">
                                            <td>${escapeHtml(item.customer)}</td>
                                            <td>
                                                ${item.product.image
                                                    ? `<img src="${escapeHtml(item.product.image)}" style="width: 50px; height: 50px; object-fit: cover; border-radius: 8px;">`
                                                    : '-'}
                                            </td>
                                            <td>${escapeHtml(item.product.name)}</td>
                                            <td>${escapeHtml(item.product.barcode || '-')}</td>
                                            <td>
                                                ${item.order_type === 'custom'
                                                    ? `<span class="badge bg-info text-dark">定制</span><br><small>${escapeHtml(item.country || '')}</small>`
                                                    : `<span class="badge bg-secondary">常规</span>`}
                                            </td>
                                            <td><strong>${item.quantity}</strong></td>
                                            <td>${deductDisplay}</td>
                                            <td><small>${escapeHtml(notesDisplay)}</small></td>
                                            <td>
                                                ${isLocked ? `
                                                    <span class="badge bg-warning text-dark mb-1" title="被 ${escapeHtml(lockedByName)} 锁定">
                                                        <i class="fas fa-lock me-1"></i>审批中
                                                    </span>
                                                    <br>
                                                    <a href="/order/edit/${item.ids[0]}" class="btn btn-sm btn-outline-secondary disabled" disabled>
                                                        <i class="fas fa-edit"></i> 编辑
                                                    </a>
                                                    <button class="btn btn-sm btn-outline-secondary disabled" disabled>
                                                        <i class="fas fa-trash"></i> 删除
                                                    </button>
                                                ` : `
                                                    <a href="/order/edit/${item.ids[0]}" class="btn btn-sm btn-warning">
                                                        <i class="fas fa-edit"></i> 编辑
                                                    </a>
                                                    <button class="btn btn-sm btn-danger" onclick="deleteOrder(${item.ids[0]})">
                                                        <i class="fas fa-trash"></i> 删除
                                                    </button>
                                                `}
                                            </td>
                                        </tr>
                                    `}).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
}

async function deleteOrder(id) {
    if (!confirm('确定要删除该订单吗？')) return;

    try {
        const response = await apiFetch(`/api/v1/orders/delete/${id}`, { method: 'DELETE' });
        const result = await response.json();

        if (result.success) {
            // 从全局订单数据中移除被删除的订单
            globalOrdersData = globalOrdersData.filter(order => order.id !== id);
            
            // 重新渲染订单列表，实现无刷新更新
            renderGroupedOrderListLocal();
            
            // 显示成功提示
            showToast('删除成功！', 'success');
        } else {
            alert(result.error || '删除失败！');
        }
    } catch (error) {
        alert('删除失败：' + error.message);
    }
}

// 本地渲染订单列表函数（不重新加载页面）
function renderGroupedOrderListLocal() {
    const ordersData = globalOrdersData;
    const container = document.getElementById('orderListGrouped');
    
    if (!ordersData || ordersData.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="fas fa-box-open fa-3x mb-3" style="opacity: 0.3;"></i>
                <p>暂无订单，请先添加</p>
            </div>
        `;
        return;
    }
    
    // 按订单日期分组
    const groupedOrders = {};
    ordersData.forEach(order => {
        let dateKey = '未知日期';
        if (order.order_date) {
            dateKey = order.order_date.split(' ')[0];
        }
        
        if (!groupedOrders[dateKey]) {
            groupedOrders[dateKey] = [];
        }
        groupedOrders[dateKey].push(order);
    });
    
    // 按日期降序排序
    const sortedDates = Object.keys(groupedOrders).sort((a, b) => b.localeCompare(a));
    
    // 生成HTML
    let html = '';
    sortedDates.forEach((date, index) => {
        const orders = groupedOrders[date];
        
        // 对同一天内的数据按(客户+产品ID)进行汇总
        const summaryMap = {};
        orders.forEach(order => {
            const key = `${order.customer}|||${order.product.id}|||${order.order_type || 'regular'}`;
            
            if (!summaryMap[key]) {
                summaryMap[key] = {
                    customer: order.customer,
                    product: order.product,
                    order_type: order.order_type || 'regular',
                    country: order.country || '',
                    quantity: 0,
                    deduct_quantity: 0,
                    notes: [],
                    ids: [],
                    is_locked: false,
                    locked_by_name: ''
                };
            }
            
            summaryMap[key].quantity += order.quantity;
            summaryMap[key].deduct_quantity += (order.deduct_quantity || 0);
            if (order.note && !summaryMap[key].notes.includes(order.note)) {
                summaryMap[key].notes.push(order.note);
            }
            summaryMap[key].ids.push(order.id);
            if (order.is_locked) {
                summaryMap[key].is_locked = true;
                summaryMap[key].locked_by_name = order.locked_by_name || '';
            }
        });
        
        const summaryList = Object.values(summaryMap);
        
        const contentId = `order-content-${index}`;
        const headerId = `order-header-${index}`;
        
        const totalRecords = orders.length;
        const totalCount = summaryList.reduce((sum, item) => sum + item.quantity, 0);
        
        html += `
            <div class="card mb-3">
                <div class="card-header bg-light" id="${headerId}" style="cursor: pointer;" onclick="toggleOrderCollapse('${contentId}', '${headerId}')">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <i class="fas fa-calendar-alt me-2 text-primary"></i>
                            <strong>${escapeHtml(date)}</strong>
                            <span class="badge ms-2">${totalRecords} 条记录</span>
                            <span class="badge ms-1">共 ${totalCount} 件</span>
                        </div>
                        <div class="ms-2">
                            <i class="fas fa-chevron-down text-muted toggle-icon" data-toggle-icon-for="${contentId}"></i>
                        </div>
                    </div>
                </div>
                <div class="order-collapse-content" id="${contentId}">
                    <div class="card-body p-0">
                        <table class="table table-hover mb-0">
                            <thead>
                                <tr>
                                    <th style="width: 10%;">客户</th>
                                    <th style="width: 8%;">产品图片</th>
                                    <th style="width: 18%;">产品名称</th>
                                    <th style="width: 10%;">69 码</th>
                                    <th style="width: 7%;">类型</th>
                                    <th style="width: 8%;">数量</th>
                                    <th style="width: 10%;">抵扣备货</th>
                                    <th style="width: 8%;">备注</th>
                                    <th style="width: 13%;">操作</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${summaryList.map(item => {
                                    const isSummary = item.ids.length > 1;
                                    const notesDisplay = item.notes.length > 0 ? item.notes.join('; ') : '-';
                                    const isLocked = item.is_locked || false;
                                    const lockedByName = item.locked_by_name || '';
                                    const deductDisplay = item.deduct_quantity > 0 
                                        ? `<span class="badge bg-success">抵扣: ${item.deduct_quantity}</span>` 
                                        : '<span class="badge bg-secondary">否</span>';
                                    return `
                                    <tr class="${isLocked ? 'table-warning' : ''}">
                                        <td>${escapeHtml(item.customer)}</td>
                                        <td>
                                            ${item.product.image
                                                ? `<img src="${escapeHtml(item.product.image)}" style="width: 50px; height: 50px; object-fit: cover; border-radius: 8px;">`
                                                : '-'}
                                        </td>
                                        <td>${escapeHtml(item.product.name)}</td>
                                        <td>${escapeHtml(item.product.barcode || '-')}</td>
                                        <td><strong>${item.quantity}</strong></td>
                                        <td>${deductDisplay}</td>
                                        <td><small>${escapeHtml(notesDisplay)}</small></td>
                                        <td>
                                            ${isLocked ? `
                                                <span class="badge bg-warning text-dark mb-1" title="被 ${escapeHtml(lockedByName)} 锁定">
                                                    <i class="fas fa-lock me-1"></i>审批中
                                                </span>
                                                <br>
                                                <a href="/order/edit/${item.ids[0]}" class="btn btn-sm btn-outline-secondary disabled" disabled>
                                                    <i class="fas fa-edit"></i> 编辑
                                                </a>
                                                <button class="btn btn-sm btn-outline-secondary disabled" disabled>
                                                    <i class="fas fa-trash"></i> 删除
                                                </button>
                                            ` : `
                                                <a href="/order/edit/${item.ids[0]}" class="btn btn-sm btn-warning">
                                                    <i class="fas fa-edit"></i> 编辑
                                                </a>
                                                <button class="btn btn-sm btn-danger" onclick="deleteOrder(${item.ids[0]})">
                                                    <i class="fas fa-trash"></i> 删除
                                                </button>
                                            `}
                                        </td>
                                    </tr>
                                `}).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
    
    // 初始化折叠状态
    initOrderCollapse();
}

// 初始化折叠功能
function initOrderCollapse() {
    document.querySelectorAll('.order-collapse-content').forEach(content => {
        content.classList.add('expanded');
    });
}

function toggleOrderCollapse(contentId, headerId) {
    const content = document.getElementById(contentId);
    const header = document.getElementById(headerId);
    const icon = header.querySelector('.toggle-icon');
    
    if (content.style.display === 'none') {
        content.style.display = 'block';
        icon.classList.remove('fa-chevron-right');
        icon.classList.add('fa-chevron-down');
    } else {
        content.style.display = 'none';
        icon.classList.remove('fa-chevron-down');
        icon.classList.add('fa-chevron-right');
    }
}

let _batchUploadInitialized = false;

function initBatchUpload() {
    if (_batchUploadInitialized) {
        console.log('initBatchUpload already initialized, skipping');
        return;
    }
    _batchUploadInitialized = true;
    console.log('=== initBatchUpload called ===');
    
    const excelUploadArea = document.getElementById('excel-upload-area');
    const excelInput = document.getElementById('excel-input');
    const excelPreview = document.getElementById('excel-preview');
    const uploadStatus = document.getElementById('upload-status');
    const downloadTemplate = document.getElementById('download-template');
    const batchImport = document.getElementById('batch-import');
    let excelFile = null;
    
    console.log('excelUploadArea:', excelUploadArea);
    console.log('excelInput:', excelInput);
    console.log('downloadTemplate:', downloadTemplate);
    console.log('batchImport:', batchImport);
    
    if (!excelUploadArea || !excelInput) {
        console.warn('批量上传元素不存在，跳过初始化');
        return;
    }
    
    console.log('Elements found, continuing initialization');
    
    function showStatus(message, type = 'info') {
        const types = {
            info: 'alert-info',
            success: 'alert-success',
            error: 'alert-danger',
            warning: 'alert-warning'
        };
        
        if (window.GlobalNotification) {
            window.GlobalNotification[type](message);
        } else if (uploadStatus) {
            uploadStatus.innerHTML = `
                <div class="alert ${types[type]} alert-dismissible fade show" role="alert">
                    ${escapeHtml(message)}
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="关闭"></button>
                </div>
            `;
        }
    }
    
    function handleExcelFile(file) {
        const fileName = file.name.toLowerCase();
        if (!fileName.endsWith('.xlsx') && !fileName.endsWith('.xls')) {
            showStatus('错误：请上传 Excel 文件（.xlsx 或 .xls 格式）', 'error');
            return;
        }
        
        excelFile = file;
        
        if (excelPreview) {
            excelPreview.innerHTML = `
                <div class="alert alert-light p-2 mb-0" style="background-color: #f8f9fa; border: 1px solid #e9ecef;">
                    <div class="d-flex align-items-center">
                        <i class="fas fa-file-excel text-success me-2"></i>
                        <div class="flex-grow-1">
                            <strong class="small">${escapeHtml(file.name)}</strong>
                            <small class="text-muted ms-2">${(file.size / 1024).toFixed(1)} KB</small>
                        </div>
                    </div>
                </div>
            `;
        }
        
        if (batchImport) {
            batchImport.disabled = false;
        }
    }
    
    excelUploadArea.addEventListener('click', (e) => {
        e.stopPropagation();
        // 检查点击的目标是否是按钮或按钮内部的元素
        const targetElement = e.target.closest('#download-template, #batch-import');
        if (e.target.tagName !== 'IMG' && !targetElement) {
            excelInput.click();
        }
    });
    
    excelUploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        excelUploadArea.classList.add('border-success', 'bg-success', 'bg-opacity-10');
    });
    
    excelUploadArea.addEventListener('dragleave', (e) => {
        e.stopPropagation();
        excelUploadArea.classList.remove('border-success', 'bg-success', 'bg-opacity-10');
    });
    
    excelUploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        excelUploadArea.classList.remove('border-success', 'bg-success', 'bg-opacity-10');
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
    
    if (downloadTemplate) {
        console.log('download-template element found (using native <a> download)');
    }
    
    if (batchImport) {
        batchImport.addEventListener('click', async () => {
            if (!excelFile) {
                showStatus('请先选择 Excel 文件', 'error');
                return;
            }
            
            showStatus('正在导入订单数据...', 'info');
            
            const formData = new FormData();
            formData.append('file', excelFile);
            
            try {
                const response = await apiFetch('/api/v1/staging-orders/import', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (data.success) {
                    let message = `导入成功！共导入 ${data.imported} 个订单到暂存区`;
                    showStatus(message, 'success');
                    
                    if (excelPreview) {
                        excelPreview.innerHTML = '';
                    }
                    excelFile = null;
                    if (batchImport) {
                        batchImport.disabled = true;
                    }
                    
                    await loadStagedOrders();
                    
                    // 分发批量导入成功事件，触发自动清空机制
                    window.dispatchEvent(new CustomEvent('batchImportSuccess', {
                        detail: { sessionId: data.session_id }
                    }));
                } else {
                    const errorMsg = data.error || data.message || '未知错误';
                    showStatus(`导入失败：${errorMsg}`, 'error');
                }
            } catch (error) {
                console.error('导入错误:', error);
                showStatus('导入失败：' + error.message, 'error');
            }
        });
    }
}