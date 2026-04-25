"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post, del } from "@/lib/api-client";

// ============ Types ============

interface Product {
  id: number;
  name: string;
  barcode?: string;
  image?: string;
  current_stock?: number;
}

export interface OrderItem {
  id: number;
  order_no: string;
  customer: string;
  product: Product;
  quantity: number;
  deduct_quantity: number;
  deduct_stock: boolean;
  order_date: string;
  note: string;
  status: string;
  is_locked?: boolean;
  locked_by_name?: string;
}

interface StagedOrder {
  id?: number;
  customer: string;
  productId: number;
  productName: string;
  quantity: number;
  orderDate: string;
  note: string;
  deduct_stock: boolean;
  deduct_quantity: number;
  is_validated?: boolean;
  validation_error?: string;
}

interface Customer { id: number; name: string; }
export interface ListResult<T> { success: boolean; data: T[]; total: number; }

// ============ Component ============

interface OrderListContentProps {
  initialOrders?: ListResult<OrderItem>;
  initialCustomers?: ListResult<Customer>;
}

export function OrderListContent({ initialOrders, initialCustomers }: OrderListContentProps) {
  const qc = useQueryClient();

  // State
  const [orderDate, setOrderDate] = useState(() => new Date().toISOString().split("T")[0]);
  const [orderCustomer, setOrderCustomer] = useState("");
  const [orderProductSearch, setOrderProductSearch] = useState("");
  const [orderProductId, setOrderProductId] = useState<number | null>(null);
  const [orderQuantity, setOrderQuantity] = useState(1);
  const [orderNote, setOrderNote] = useState("");
  const [orderDeductStock, setOrderDeductStock] = useState(false);
  const [orderDeductQuantity, setOrderDeductQuantity] = useState(0);
  const [orderAvailableStock, setOrderAvailableStock] = useState(0);
  const [stagedOrders, setStagedOrders] = useState<StagedOrder[]>([]);
  const [orderProductResults, setOrderProductResults] = useState<Product[]>([]);
  const [showAutocomplete, setShowAutocomplete] = useState(false);
  const [editingIndex, setEditingIndex] = useState(-1);
  const [editCustomer, setEditCustomer] = useState("");
  const [editQuantity, setEditQuantity] = useState(1);
  const [editDeductQuantity, setEditDeductQuantity] = useState(0);
  const [editNote, setEditNote] = useState("");
  const [editAvailableStock, setEditAvailableStock] = useState(0);
  const [showEditModal, setShowEditModal] = useState(false);
  const [excelFile, setExcelFile] = useState<File | null>(null);
  const [uploadStatus, setUploadStatus] = useState("");
  const [showBatchUpload, setShowBatchUpload] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  const searchRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // API queries
  const { data: ordersData } = useQuery({
    queryKey: ["orders-list"],
    queryFn: () => get<ListResult<OrderItem>>("/orders/list", { per_page: "5000" }),
    initialData: initialOrders,
  });

  const { data: customersData } = useQuery({
    queryKey: ["customers-list"],
    queryFn: () => get<ListResult<Customer>>("/customers/list"),
    initialData: initialCustomers,
  });

  const { data: stagingOrdersData } = useQuery({
    queryKey: ["staging-orders"],
    queryFn: () => get<unknown>("/staging-orders") as Promise<{ success: boolean; data: Record<string, unknown>[] }>,
  });

  const orders = ordersData?.data ?? [];
  const customers = customersData?.data ?? [];

  // Sync staging from server
  useEffect(() => {
    if (stagingOrdersData?.success && stagingOrdersData.data?.length > 0) {
      setStagedOrders(stagingOrdersData.data.map((o: Record<string, unknown>) => ({
        id: o.id as number,
        customer: (o.customer as string) || "",
        productId: (o.product_id as number) ?? (o.productId as number),
        productName: (o.product_name as string) ?? (o.productName as string) ?? "",
        quantity: (o.quantity as number) || 0,
        orderDate: (o.order_date as string) ?? (o.orderDate as string) ?? "",
        note: (o.note as string) ?? "",
        deduct_stock: (o.deduct_stock as boolean) || false,
        deduct_quantity: (o.deduct_quantity as number) || 0,
        is_validated: o.is_validated as boolean | undefined,
        validation_error: o.validation_error as string | undefined,
      })));
    }
  }, [stagingOrdersData]);

  // Expand all groups
  useEffect(() => {
    const dates = new Set<string>();
    orders.forEach((o) => { dates.add(o.order_date?.split(" ")[0] || "未知日期"); });
    setExpandedGroups(dates);
  }, [orders]);

  // Cleanup staging on unmount
  useEffect(() => {
    return () => { del("/staging-orders/clear").catch(() => {}); };
  }, []);

  // Click outside to close autocomplete
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) setShowAutocomplete(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Product search
  const searchProducts = useCallback(async (query: string) => {
    if (!query.trim()) { setOrderProductResults([]); return; }
    try {
      const data = await get<Product[]>("/aux/product-search", { q: query });
      setOrderProductResults(Array.isArray(data) ? data : []);
    } catch { setOrderProductResults([]); }
  }, []);

  const handleProductSearch = useCallback((val: string) => {
    setOrderProductSearch(val);
    setOrderProductId(null);
    setOrderDeductQuantity(0);
    setOrderDeductStock(false);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => searchProducts(val), 300);
    setShowAutocomplete(true);
  }, [searchProducts]);

  // Deduct preview
  const fetchAvailableStockins = useCallback(async (productId: number, customer: string) => {
    try {
      const data = await get<{ available: number }[]>("/aux/available-stockins", { product_id: String(productId), customer });
      return Array.isArray(data) ? data.reduce((sum, s) => sum + (s.available || 0), 0) : 0;
    } catch { return 0; }
  }, []);

  const handleDeductPreview = useCallback(async () => {
    if (!orderProductId || !orderCustomer || orderQuantity <= 0) {
      if (!orderCustomer) alert("请先选择客户");
      return;
    }
    setOrderDeductStock(true);
    const available = await fetchAvailableStockins(orderProductId, orderCustomer);
    setOrderAvailableStock(available);
    const deductible = Math.min(orderQuantity, available);
    setOrderDeductQuantity(deductible);
    if (deductible === 0) { alert(`无可抵扣数量！\n当前可用备货: ${available} 件`); setOrderDeductStock(false); }
  }, [orderProductId, orderCustomer, orderQuantity, fetchAvailableStockins]);

  // Add/edit/delete staged
  const canAddOrder = orderCustomer && orderProductId && orderQuantity > 0;

  const addStagedOrder = useCallback(() => {
    if (!canAddOrder) return;
    setStagedOrders((prev) => [...prev, {
      customer: orderCustomer, productId: orderProductId!, productName: orderProductSearch,
      quantity: orderQuantity, orderDate, note: orderNote,
      deduct_stock: orderDeductStock, deduct_quantity: orderDeductQuantity, id: Date.now(),
    }]);
    setOrderCustomer(""); setOrderProductSearch(""); setOrderProductId(null);
    setOrderQuantity(1); setOrderNote(""); setOrderDeductStock(false);
    setOrderDeductQuantity(0); setOrderAvailableStock(0);
  }, [canAddOrder, orderCustomer, orderProductId, orderProductSearch, orderQuantity, orderDate, orderNote, orderDeductStock, orderDeductQuantity]);

  const openEditModal = useCallback(async (index: number) => {
    const order = stagedOrders[index];
    setEditingIndex(index);
    setEditCustomer(order.customer); setEditQuantity(order.quantity);
    setEditDeductQuantity(order.deduct_quantity); setEditNote(order.note || "");
    setShowEditModal(true);
    const available = await fetchAvailableStockins(order.productId, order.customer);
    setEditAvailableStock(available);
  }, [stagedOrders, fetchAvailableStockins]);

  const saveEdit = useCallback(() => {
    if (editingIndex === -1) return;
    if (editDeductQuantity > editQuantity) { alert("抵扣备货数量不能超过订单数量！"); return; }
    if (editDeductQuantity > editAvailableStock) { alert(`抵扣备货数量不能超过可用备货数量！\n当前可用备货: ${editAvailableStock} 件`); return; }
    setStagedOrders((prev) => {
      const copy = [...prev];
      copy[editingIndex] = { ...copy[editingIndex], customer: editCustomer, quantity: editQuantity, deduct_quantity: editDeductQuantity, deduct_stock: editDeductQuantity > 0, note: editNote };
      return copy;
    });
    setShowEditModal(false); setEditingIndex(-1);
  }, [editingIndex, editCustomer, editQuantity, editDeductQuantity, editAvailableStock, editNote]);

  const deleteStaged = useCallback((index: number) => {
    if (!confirm("确定要删除这个暂存订单吗？")) return;
    const order = stagedOrders[index];
    if (order.id && order.id > 1000000000000) {
      setStagedOrders((prev) => prev.filter((_, i) => i !== index));
    } else if (order.id) {
      del(`/staging-orders/${order.id}`).then(() => { setStagedOrders((prev) => prev.filter((_, i) => i !== index)); qc.invalidateQueries({ queryKey: ["staging-orders"] }); });
    } else {
      setStagedOrders((prev) => prev.filter((_, i) => i !== index));
    }
  }, [stagedOrders, qc]);

  // Submit all
  const submitAll = useCallback(async () => {
    if (stagedOrders.length === 0) return;
    setSubmitting(true);
    try {
      const ordersNeedingDeduction = stagedOrders.filter(o => o.deduct_stock && o.deduct_quantity > 0);
      if (ordersNeedingDeduction.length > 0) {
        const uniqueKeys: Record<string, { productId: number; customer: string; orders: StagedOrder[] }> = {};
        ordersNeedingDeduction.forEach(order => {
          const key = `${order.productId}-${order.customer}`;
          if (!uniqueKeys[key]) uniqueKeys[key] = { productId: order.productId, customer: order.customer, orders: [] };
          uniqueKeys[key].orders.push(order);
        });
        for (const key in uniqueKeys) {
          const { productId, customer, orders } = uniqueKeys[key];
          const available = await fetchAvailableStockins(productId, customer);
          for (const order of orders) {
            if (order.deduct_quantity > Math.min(order.quantity, available)) {
              alert(`订单 (${order.productName}) 抵扣数量超过可用备货！\n当前可用备货: ${available} 件`);
              setSubmitting(false); return;
            }
          }
        }
      }
      const ordersForApi = stagedOrders.map(o => ({
        product_id: o.productId, customer: o.customer, quantity: o.quantity,
        order_date: o.orderDate, note: o.note, deduct_stock: o.deduct_stock, deduct_quantity: o.deduct_quantity,
      }));
      const result = await post<{ success: boolean; error?: string }>("/aux/batch-submit-orders", { orders: ordersForApi });
      if (result.success) {
        alert("提交成功！"); setStagedOrders([]);
        await del("/staging-orders/clear").catch(() => {});
        qc.invalidateQueries({ queryKey: ["orders-list"] }); qc.invalidateQueries({ queryKey: ["staging-orders"] });
      } else { alert("提交失败: " + (result.error || "未知错误")); }
    } catch (error) { alert("提交失败: " + (error instanceof Error ? error.message : "未知错误")); }
    finally { setSubmitting(false); }
  }, [stagedOrders, fetchAvailableStockins, qc]);

  // Batch import
  const handleImport = useCallback(async () => {
    if (!excelFile) return;
    setUploadStatus("正在导入订单数据...");
    try {
      const formData = new FormData(); formData.append("file", excelFile);
      const resp = await fetch("/api/v1/staging-orders/import", { method: "POST", body: formData });
      const data = await resp.json();
      if (data.success) { setUploadStatus(`导入成功！共导入 ${data.imported} 个订单到暂存区`); setExcelFile(null); qc.invalidateQueries({ queryKey: ["staging-orders"] }); }
      else { setUploadStatus(`导入失败：${data.error || data.message || "未知错误"}`); }
    } catch (error) { setUploadStatus("导入失败：" + (error instanceof Error ? error.message : "未知错误")); }
  }, [excelFile, qc]);

  // Delete order from list
  const deleteOrder = useCallback(async (id: number) => {
    if (!confirm("确定要删除该订单吗？")) return;
    try {
      const result = await del<{ success: boolean; error?: string }>(`/orders/delete/${id}`);
      if (result.success) qc.invalidateQueries({ queryKey: ["orders-list"] });
      else alert(result.error || "删除失败！");
    } catch (error) { alert("删除失败：" + (error instanceof Error ? error.message : "未知错误")); }
  }, [qc]);

  // Grouping
  function groupOrdersByDate(): [string, OrderItem[]][] {
    const groups: Record<string, OrderItem[]> = {};
    orders.forEach((o) => { const d = o.order_date?.split(" ")[0] || "未知日期"; if (!groups[d]) groups[d] = []; groups[d].push(o); });
    return Object.entries(groups).sort(([a], [b]) => b.localeCompare(a));
  }

  const toggleGroup = (date: string) => setExpandedGroups((prev) => { const next = new Set(prev); if (next.has(date)) next.delete(date); else next.add(date); return next; });
  const escapeHtml = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  const orderGroups = groupOrdersByDate();

  return (
    <div className="ol-page-root">
      <h2>订单管理</h2>

      <div className="row">
        <div className="col-lg-6">
          <div className="card mt-3">
            <div className="card-header d-flex justify-content-between align-items-center">
              <span>订单信息录入</span>
              {stagedOrders.length > 0 && <span className="badge bg-light text-dark">已暂存: {stagedOrders.length}</span>}
            </div>
            <div className="card-body">
              <div className="row mb-3">
                <div className="col-md-6">
                  <label className="form-label">订单时间</label>
                  <input type="date" className="form-control" value={orderDate} onChange={e => setOrderDate(e.target.value)} />
                </div>
                <div className="col-md-6">
                  <label className="form-label">客户名称</label>
                  <select className="form-select" value={orderCustomer} onChange={e => setOrderCustomer(e.target.value)}>
                    <option value="">请选择客户</option>
                    {customers.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
                  </select>
                </div>
              </div>
              <div className="mb-3" style={{ position: "relative" }} ref={searchRef}>
                <label className="form-label">产品名称</label>
                <input type="text" className="form-control" placeholder="输入产品名称或69码搜索" autoComplete="off" value={orderProductSearch} onChange={e => handleProductSearch(e.target.value)} onFocus={() => orderProductResults.length > 0 && setShowAutocomplete(true)} />
                {showAutocomplete && orderProductResults.length > 0 && (
                  <div className="autocomplete-dropdown">
                    {orderProductResults.map(p => (
                      <div key={p.id} className="autocomplete-item" onMouseDown={() => { setOrderProductSearch(p.name); setOrderProductId(p.id); setShowAutocomplete(false); }}>
                        {p.name}
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="row mb-3">
                <div className="col-md-6">
                  <label className="form-label">订单数量</label>
                  <input type="number" className="form-control" value={orderQuantity} min={1} onChange={e => { const v = parseInt(e.target.value) || 0; setOrderQuantity(v); if (orderDeductQuantity > v) setOrderDeductQuantity(v); }} />
                </div>
                <div className="col-md-6">
                  <label className="form-label">抵扣备货数量</label>
                  <div className="d-flex align-items-center">
                    <button type="button" className={`btn btn-sm ${orderDeductStock ? "btn-success" : "btn-outline-secondary"} me-2`} onClick={handleDeductPreview}>抵扣备货</button>
                    <small className="text-muted deductible-display" style={{ cursor: "pointer", padding: "8px 14px", borderRadius: 12, border: "2px dashed #adb5bd", backgroundColor: "#f8f9fa" }}>抵扣: {orderDeductQuantity}</small>
                  </div>
                  {orderDeductStock && (
                    <div className="mt-2"><small className={orderAvailableStock > 0 ? "text-success" : "text-warning"}>{orderAvailableStock > 0 ? `当前可用备货: ${orderAvailableStock} 件` : "暂无可用备货"}</small></div>
                  )}
                </div>
              </div>
              <div className="mb-3">
                <label className="form-label">备注</label>
                <textarea className="form-control" rows={2} placeholder="例如：加急订单" value={orderNote} onChange={e => setOrderNote(e.target.value)} />
              </div>
              <button type="button" className={`btn ${canAddOrder ? "btn-primary" : "btn-secondary"}`} disabled={!canAddOrder} onClick={addStagedOrder}>
                <i className="fas fa-plus-circle" style={{ marginRight: 4 }}></i>新增订单
              </button>
            </div>
          </div>
        </div>

        <div className="col-lg-6">
          <div className="card mt-3">
            <div className="card-header">
              <div className="d-flex justify-content-between align-items-center">
                <span>暂存订单列表</span>
                <span className="badge bg-light text-dark">共 {stagedOrders.length} 个</span>
              </div>
            </div>
            <div className="card-body">
              <div style={{ maxHeight: 400, overflowY: "auto" }}>
                {stagedOrders.length === 0 ? (
                  <div className="text-center text-muted py-4"><i className="fas fa-box-open" style={{ fontSize: 48, opacity: 0.3 }}></i><p>暂无暂存订单</p></div>
                ) : stagedOrders.map((order, idx) => (
                  <div key={idx} className="card mb-2" style={{ border: `2px solid ${order.is_validated === false ? "#dc3545" : "var(--plush-blue-light, #e0e0e0)"}` }}>
                    <div className="card-body">
                      <div className="d-flex justify-content-between align-items-center">
                        <div className="d-flex align-items-center gap-3 flex-wrap">
                          <span className="text-muted small"><i className="fas fa-user" style={{ marginRight: 4 }}></i>{escapeHtml(order.customer)}</span>
                          <span className="text-muted small"><i className="fas fa-calendar-alt" style={{ marginRight: 4 }}></i>{escapeHtml(order.orderDate || "-")}</span>
                          <span><i className="fas fa-shopping-cart text-primary" style={{ marginRight: 4 }}></i>{escapeHtml(order.productName)}</span>
                          <span className="badge bg-light text-dark">数量: {order.quantity}</span>
                          {order.deduct_quantity > 0 && <span className="badge bg-light text-dark">抵扣: {order.deduct_quantity}</span>}
                          {order.note && <span className="badge bg-light text-dark">备注: {escapeHtml(order.note)}</span>}
                        </div>
                        <div className="d-flex gap-1 ms-2">
                          <button className="btn btn-sm btn-outline-warning" onClick={() => openEditModal(idx)}><i className="fas fa-edit"></i></button>
                          <button className="btn btn-sm btn-outline-danger" onClick={() => deleteStaged(idx)}><i className="fas fa-trash"></i></button>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="card mt-3">
            <div className="card-header d-flex justify-content-between align-items-center collapse-trigger" style={{ cursor: "pointer" }} onClick={() => setShowBatchUpload(!showBatchUpload)}>
              <h6 className="mb-0 fw-bold">批量导入订单</h6>
              <i className={`fas fa-chevron-down collapse-arrow ${showBatchUpload ? "expanded" : ""}`}></i>
            </div>
            {showBatchUpload && (
              <div className="card-body">
                <div className="border border-dashed p-4 text-center rounded" style={{ minHeight: 120, cursor: "pointer", background: "#fafafa", borderColor: "#dee2e6" }} onClick={() => fileRef.current?.click()}>
                  <div className="d-flex flex-column align-items-center justify-content-center" style={{ minHeight: 80 }}>
                    <i className="fas fa-file-excel text-success" style={{ fontSize: 32, opacity: 0.8, marginBottom: 8 }}></i>
                    <p className="text-muted mb-1 small">拖拽或点击选择 Excel 文件</p>
                    <p className="text-muted mb-0" style={{ fontSize: 11, color: "#adb5bd" }}>支持 .xlsx / .xls 格式</p>
                  </div>
                  <input ref={fileRef} type="file" style={{ display: "none" }} accept=".xlsx,.xls" onChange={e => { if (e.target.files?.[0]) setExcelFile(e.target.files[0]); }} />
                </div>
                {excelFile && <div className="mt-2"><small className="text-success">已选择: {excelFile.name}</small></div>}
                {uploadStatus && <div className="mt-2"><small>{uploadStatus}</small></div>}
                <div className="d-flex justify-content-between align-items-center mt-3">
                  <a className="btn btn-outline-secondary btn-sm" href="/api/v1/batch/download-template" download><i className="fas fa-download" style={{ marginRight: 8 }}></i>订单模板</a>
                  <button className="btn btn-success btn-sm" disabled={!excelFile} onClick={handleImport}><i className="fas fa-file-import" style={{ marginRight: 8 }}></i>确认导入</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="card mt-4">
        <div className="card-body text-center py-4">
          <button className="btn btn-primary btn-lg" disabled={stagedOrders.length === 0 || submitting} style={{ minWidth: 200 }} onClick={submitAll}>
            <i className="fas fa-paper-plane" style={{ marginRight: 8 }}></i>{submitting ? "提交中..." : "添加订单"}
          </button>
        </div>
      </div>

      <div className="card mt-4">
        <div className="card-header">订单列表</div>
        <div className="card-body">
          {orderGroups.length === 0 ? (
            <div className="text-center text-muted py-4"><i className="fas fa-box-open" style={{ fontSize: 48, opacity: 0.3 }}></i><p>暂无订单，请先添加</p></div>
          ) : orderGroups.map(([date, dateOrders]) => {
            const summaryMap: Record<string, { customer: string; product: Product; quantity: number; deduct_quantity: number; notes: string[]; ids: number[]; is_locked: boolean; locked_by_name: string }> = {};
            dateOrders.forEach(o => {
              const key = `${o.customer}|||${o.product.id}`;
              if (!summaryMap[key]) summaryMap[key] = { customer: o.customer, product: o.product, quantity: 0, deduct_quantity: 0, notes: [], ids: [], is_locked: false, locked_by_name: "" };
              summaryMap[key].quantity += o.quantity;
              summaryMap[key].deduct_quantity += (o.deduct_quantity || 0);
              if (o.note && !summaryMap[key].notes.includes(o.note)) summaryMap[key].notes.push(o.note);
              summaryMap[key].ids.push(o.id);
              if (o.is_locked) { summaryMap[key].is_locked = true; summaryMap[key].locked_by_name = o.locked_by_name || ""; }
            });
            const summaryList = Object.values(summaryMap);
            const totalCount = summaryList.reduce((s, i) => s + i.quantity, 0);
            const isExpanded = expandedGroups.has(date);

            return (
              <div key={date} className="order-date-group mb-3">
                <div className="card">
                  <div className="card-header d-flex justify-content-between align-items-center" style={{ background: "white", borderBottom: "2px solid #e9ecef", cursor: "pointer" }} onClick={() => toggleGroup(date)}>
                    <div className="d-flex align-items-center flex-grow-1">
                      <i className="fas fa-calendar-alt text-primary" style={{ marginRight: 8 }}></i>
                      <strong>{date}</strong>
                      <span className="badge ms-2">{dateOrders.length} 条记录</span>
                      <span className="badge ms-1">共 {totalCount} 件</span>
                    </div>
                    <i className={`fas fa-chevron-down text-muted toggle-icon ${isExpanded ? "expanded" : ""}`}></i>
                  </div>
                  {isExpanded && (
                    <div className="card-body p-0">
                      <table className="table table-hover mb-0">
                        <thead><tr><th style={{ width: "10%" }}>客户</th><th style={{ width: "8%" }}>产品图片</th><th style={{ width: "18%" }}>产品名称</th><th style={{ width: "10%" }}>69 码</th><th style={{ width: "8%" }}>数量</th><th style={{ width: "10%" }}>抵扣备货</th><th style={{ width: "8%" }}>备注</th><th style={{ width: "13%" }}>操作</th></tr></thead>
                        <tbody>
                          {summaryList.map((item, i) => (
                            <tr key={i} className={item.is_locked ? "table-warning" : ""}>
                              <td>{escapeHtml(item.customer)}</td>
                              <td>{item.product.image ? <img src={item.product.image} style={{ width: 50, height: 50, objectFit: "cover", borderRadius: 8 }} /> : "-"}</td>
                              <td>{escapeHtml(item.product.name)}</td>
                              <td>{escapeHtml(item.product.barcode || "-")}</td>
                              <td><strong>{item.quantity}</strong></td>
                              <td>{item.deduct_quantity > 0 ? <span className="badge bg-success">抵扣: {item.deduct_quantity}</span> : <span className="badge bg-secondary">否</span>}</td>
                              <td><small>{escapeHtml(item.notes.length > 0 ? item.notes.join("; ") : "-")}</small></td>
                              <td>
                                {item.is_locked ? (
                                  <><span className="badge bg-warning text-dark mb-1"><i className="fas fa-lock" style={{ marginRight: 4 }}></i>审批中</span><br /><button className="btn btn-sm btn-outline-secondary" disabled><i className="fas fa-edit"></i> 编辑</button><button className="btn btn-sm btn-outline-secondary" disabled><i className="fas fa-trash"></i> 删除</button></>
                                ) : (
                                  <><button className="btn btn-sm btn-warning" onClick={() => window.location.href = `/order/edit/${item.ids[0]}`}><i className="fas fa-edit"></i> 编辑</button><button className="btn btn-sm btn-danger" onClick={() => deleteOrder(item.ids[0])}><i className="fas fa-trash"></i> 删除</button></>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Edit staged order modal */}
      {showEditModal && editingIndex >= 0 && (
        <div className="modal-overlay" onClick={() => setShowEditModal(false)}>
          <div className="modal-dialog" onClick={e => e.stopPropagation()}>
            <div className="modal-content">
              <div className="modal-header">
                <h5 className="modal-title">编辑暂存订单</h5>
                <button type="button" className="btn-close" onClick={() => setShowEditModal(false)}></button>
              </div>
              <div className="modal-body">
                <div className="mb-3"><label className="form-label">客户名称</label><select className="form-select" value={editCustomer} onChange={e => setEditCustomer(e.target.value)}>{customers.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}</select></div>
                <div className="mb-3"><label className="form-label">产品名称</label><input type="text" className="form-control" value={stagedOrders[editingIndex]?.productName || ""} readOnly /></div>
                <div className="mb-3"><label className="form-label">订单数量</label><input type="number" className="form-control" value={editQuantity} min={1} onChange={e => setEditQuantity(parseInt(e.target.value) || 1)} /></div>
                <div className="mb-3">
                  <label className="form-label">抵扣备货数量</label>
                  <div className="input-group"><input type="number" className="form-control" value={editDeductQuantity} min={0} max={Math.min(editQuantity, editAvailableStock)} onChange={e => setEditDeductQuantity(parseInt(e.target.value) || 0)} /><span className="input-group-text">件</span></div>
                  <div className="mt-2"><small className={editAvailableStock > 0 ? "text-success" : "text-muted"}>{editAvailableStock > 0 ? `当前可用备货: ${editAvailableStock} 件` : "暂无可用备货"}</small></div>
                </div>
                <div className="mb-3"><label className="form-label">备注</label><textarea className="form-control" rows={2} value={editNote} onChange={e => setEditNote(e.target.value)} /></div>
              </div>
              <div className="modal-footer">
                <button className="btn btn-secondary" onClick={() => setShowEditModal(false)}>取消</button>
                <button className="btn btn-primary" onClick={saveEdit}>保存</button>
              </div>
            </div>
          </div>
        </div>
      )}

      <style jsx global>{`
        .ol-page-root h2 { margin-bottom: 8px; }
        .ol-page-root .toggle-icon { transition: transform 0.3s ease; }
        .ol-page-root .toggle-icon.expanded { transform: rotate(180deg); }
        .ol-page-root .order-date-group .card { border: 2px solid #D4F1F4; box-shadow: 0 4px 16px rgba(176, 224, 230, 0.25); transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); }
        .ol-page-root .order-date-group .card:hover { box-shadow: 0 8px 28px rgba(135, 206, 235, 0.35); }
        .ol-page-root .order-date-group .card-header { border-radius: 0 !important; padding: 12px 16px; transition: all 0.2s ease; font-weight: 500; }
        .ol-page-root .order-date-group .card-header:hover { background-color: rgba(212, 241, 244, 0.3) !important; }
        .ol-page-root .order-date-group .table th { font-weight: 600; border-top: none; font-size: 0.9em; }
        .ol-page-root .order-date-group .table td { vertical-align: middle; }
        .ol-page-root .order-date-group .badge { font-size: 0.8em; padding: 4px 8px; }
        .ol-page-root .order-date-group .btn-sm { padding: 4px 8px; font-size: 0.85em; }
        .ol-page-root .order-date-group img { transition: transform 0.2s ease; }
        .ol-page-root .order-date-group img:hover { transform: scale(1.1); }
        .ol-page-root .autocomplete-dropdown { position: absolute; top: 100%; left: 0; right: 0; background: white; border: 2px solid #D4F1F4; border-radius: var(--radius-input); box-shadow: 0 4px 12px rgba(0,0,0,0.1); z-index: 1000; max-height: 200px; overflow-y: auto; }
        .ol-page-root .autocomplete-item { padding: 10px 14px; cursor: pointer; transition: all 0.2s ease; border-bottom: 1px solid #f0f0f0; }
        .ol-page-root .autocomplete-item:last-child { border-bottom: none; }
        .ol-page-root .autocomplete-item:hover { background-color: #D4F1F4; transform: translateX(5px); }
        .ol-page-root .deductible-display { user-select: none; }
        @media (max-width: 992px) { .ol-page-root .col-lg-6 { flex: 0 0 100%; max-width: 100%; } }
      `}</style>
    </div>
  );
}
