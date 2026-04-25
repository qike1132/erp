"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post, put, del } from "@/lib/api-client";
import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import {
  StoreIcon,
  FileTextIcon,
  CheckCircleIcon,
  InboxIcon,
  ListIcon,
  Wand2Icon,
  ClipboardListIcon,
  CheckCheckIcon,
  FilterIcon,
  FileSpreadsheetIcon,
  SearchIcon,
  ScanBarcodeIcon,
  CalendarDaysIcon,
  InfoIcon,
  RefreshCwIcon,
  XIcon,
  Loader2Icon,
  ChevronDownIcon,
  ChevronUpIcon,
  Trash2Icon,
  EyeIcon,
  CheckIcon,
  AlertTriangleIcon,
  HistoryIcon,
  DownloadIcon,
  PlusIcon,
  MinusIcon,
  PrinterIcon,
  PackageIcon,
  SaveIcon,
  XCircleIcon,
} from "lucide-react";
import { toast } from "sonner";

// ============ Types ============

interface PurchaseOrder {
  id: number;
  order_no: string;
  status: string;
  customer_name: string;
  supplier_name: string;
  remark: string;
  create_time: string;
  order_date: string;
  total_quantity: number;
  items?: { material_name: string; material_code?: string; specification?: string; quantity: number; unit: string; category: string }[];
  materials?: { name: string; quantity: number; unit: string; category: string }[];
}

interface PurchaseOrderListResult {
  success: boolean;
  orders: PurchaseOrder[];
  total: number;
  page: number;
  per_page: number;
}

interface UnprocessedOrder {
  id: number;
  order_no: string;
  customer_name: string;
  supplier_name: string;
  product_name: string;
  quantity: number;
  create_time: string;
  items?: { material_name: string; specification?: string; unit: string; quantity: number }[];
}

interface SavedQuery {
  id: number;
  name: string;
  query_type: string;
  filters: Record<string, string>;
  created_at: string;
}

interface AutocompleteSuggestion {
  value: string;
  label: string;
}

const STATUS_MAP: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: "待处理", color: "#D4830A", bg: "#FFF3CD" },
  processing: { label: "处理中", color: "#3A6BD6", bg: "#D6E4FF" },
  completed: { label: "已完成", color: "#1E9E55", bg: "#E8F9EF" },
  cancelled: { label: "已取消", color: "#C93839", bg: "#FDE8E8" },
};

// ============ Component ============

export function PurchaseContent() {
  const queryClient = useQueryClient();

  // Tab state
  const [activeTab, setActiveTab] = useState<"orders" | "history">("orders");

  // Orders panel state
  const [orderPage, setOrderPage] = useState(1);
  const [orderStatus, setOrderStatus] = useState("");
  const [orderCustomer, setOrderCustomer] = useState("");
  const [orderSearch, setOrderSearch] = useState("");
  const [selectedOrderIds, setSelectedOrderIds] = useState<Set<number>>(new Set());
  const [expandedOrders, setExpandedOrders] = useState<Set<number>>(new Set());

  // Unprocessed orders
  const [unprocessedPage, setUnprocessedPage] = useState(1);
  const [selectedUnprocessedIds, setSelectedUnprocessedIds] = useState<Set<number>>(new Set());

  // History panel state
  const [hPage, setHPage] = useState(1);
  const [hOrderNo, setHOrderNo] = useState("");
  const [hCustomer, setHCustomer] = useState("");
  const [hProduct, setHProduct] = useState("");
  const [hSupplier, setHSupplier] = useState("");
  const [hBarcode, setHBarcode] = useState("");
  const [hStartDate, setHStartDate] = useState("");
  const [hEndDate, setHEndDate] = useState("");
  const [hMaterial, setHMaterial] = useState("");
  const [hQuickStatus, setHQuickStatus] = useState("");
  const [filterPanelOpen, setFilterPanelOpen] = useState(false);

  // Autocomplete state
  const [suggestions, setSuggestions] = useState<Record<string, AutocompleteSuggestion[]>>({});
  const [showSuggestion, setShowSuggestion] = useState<Record<string, boolean>>({});
  const suggestionTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // Modal state
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmData, setConfirmData] = useState<{ title: string; text: string; sub?: string; variant?: "danger" | "warning"; onConfirm: () => void } | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [summaryData, setSummaryData] = useState<any>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [exportPreviewOpen, setExportPreviewOpen] = useState(false);
  const [exportPreviewHtml, setExportPreviewHtml] = useState("");

  // Edit state
  const [editOpen, setEditOpen] = useState(false);
  const [editForm, setEditForm] = useState({ status: "", remark: "", supplier_name: "", modify_reason: "" });
  const [editId, setEditId] = useState<number | null>(null);

  // Saved queries
  const [savedQueries, setSavedQueries] = useState<SavedQuery[]>([]);

  const perPage = 15;

  // ============ Queries ============

  const { data: ordersData, isLoading: ordersLoading } = useQuery({
    queryKey: ["purchase-orders", orderPage, orderStatus, orderCustomer, orderSearch],
    queryFn: () =>
      get<PurchaseOrderListResult>("/purchase-center/orders", {
        page: String(orderPage),
        per_page: String(perPage),
        ...(orderStatus ? { status: orderStatus } : {}),
        ...(orderCustomer ? { customer: orderCustomer } : {}),
      }),
    refetchInterval: activeTab === "orders" ? 30000 : false,
  });

  const { data: unprocessedData, isLoading: unprocessedLoading } = useQuery({
    queryKey: ["purchase-unprocessed", unprocessedPage],
    queryFn: () =>
      get<{ success: boolean; orders: UnprocessedOrder[]; total: number }>(
        "/purchase-center/unprocessed-orders",
        { page: String(unprocessedPage), per_page: "50" }
      ),
    refetchInterval: activeTab === "orders" ? 30000 : false,
    enabled: activeTab === "orders",
  });

  const { data: completedData, isLoading: completedLoading } = useQuery({
    queryKey: ["purchase-completed", hPage, hOrderNo, hCustomer, hProduct, hSupplier, hBarcode, hStartDate, hEndDate, hMaterial, hQuickStatus],
    queryFn: () =>
      get<PurchaseOrderListResult>("/purchase-center/orders/completed", {
        page: String(hPage),
        per_page: String(perPage),
        ...(hOrderNo ? { order_no: hOrderNo } : {}),
        ...(hCustomer ? { customer_name: hCustomer } : {}),
        ...(hProduct ? { product_name: hProduct } : {}),
        ...(hSupplier ? { supplier_name: hSupplier } : {}),
        ...(hBarcode ? { barcode: hBarcode } : {}),
        ...(hStartDate ? { start_date: hStartDate } : {}),
        ...(hEndDate ? { end_date: hEndDate } : {}),
        ...(hMaterial ? { material_name: hMaterial } : {}),
        ...(hQuickStatus ? { status: hQuickStatus } : {}),
      }),
    enabled: activeTab === "history",
  });

  const { data: detailData, isLoading: detailLoading } = useQuery({
    queryKey: ["purchase-order-detail", detailId],
    queryFn: () => get<{ success: boolean; order: PurchaseOrder }>(`/purchase-center/orders/${detailId!}`),
    enabled: !!detailId && detailOpen,
  });

  const { data: savedQueriesData } = useQuery({
    queryKey: ["purchase-saved-queries"],
    queryFn: () => get<{ success: boolean; queries: SavedQuery[] }>("/purchase-center/saved-queries"),
    enabled: activeTab === "history",
  });

  // ============ Mutations ============

  const completeMutation = useMutation({
    mutationFn: (id: number) => post<{ success: boolean; message?: string }>("/purchase-center/orders/complete", { order_id: id }),
    onSuccess: (res) => { toast.success(res.message || "订单已完成"); setConfirmOpen(false); setConfirmData(null); queryClient.invalidateQueries({ queryKey: ["purchase-orders"] }); },
    onError: () => toast.error("操作失败"),
  });

  const batchCompleteMutation = useMutation({
    mutationFn: (ids: number[]) => post<{ success: boolean; message?: string }>("/purchase-center/orders/batch-complete", { order_ids: ids }),
    onSuccess: (res) => { toast.success(res.message || "批量完成成功"); setSelectedOrderIds(new Set()); queryClient.invalidateQueries({ queryKey: ["purchase-orders"] }); },
    onError: () => toast.error("批量完成失败"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => del<{ success: boolean; message?: string }>(`/purchase-center/orders/${id}`),
    onSuccess: (res) => { toast.success(res.message || "删除成功"); setConfirmOpen(false); setConfirmData(null); queryClient.invalidateQueries({ queryKey: ["purchase-orders"] }); },
    onError: () => toast.error("删除失败"),
  });

  const batchDeleteMutation = useMutation({
    mutationFn: (ids: number[]) => post<{ success: boolean; message?: string }>("/purchase-center/orders/batch-delete", { order_ids: ids }),
    onSuccess: (res) => { toast.success(res.message || "批量删除成功"); setSelectedOrderIds(new Set()); queryClient.invalidateQueries({ queryKey: ["purchase-orders"] }); },
    onError: () => toast.error("批量删除失败"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: typeof editForm }) =>
      put<{ success: boolean; message?: string }>(`/purchase-center/orders/${id}`, body),
    onSuccess: (res) => { toast.success(res.message || "更新成功"); setEditOpen(false); queryClient.invalidateQueries({ queryKey: ["purchase-orders"] }); },
    onError: () => toast.error("更新失败"),
  });

  const oneClickMutation = useMutation({
    mutationFn: (orderIds: number[]) => post<{ success: boolean; message?: string; generated_count?: number }>("/purchase-center/orders/one-click-generate", { order_ids: orderIds }),
    onSuccess: (res) => { toast.success(res.message || `成功生成 ${res.generated_count || 0} 个采购订单`); setSelectedUnprocessedIds(new Set()); queryClient.invalidateQueries({ queryKey: ["purchase-orders"] }); queryClient.invalidateQueries({ queryKey: ["purchase-unprocessed"] }); },
    onError: () => toast.error("一键审核失败"),
  });

  // ============ Derived data ============

  const orders = ordersData?.orders ?? [];
  const orderTotal = ordersData?.total ?? 0;
  const orderTotalPages = orderTotal ? Math.ceil(orderTotal / perPage) : 1;

  const unprocessedOrders = unprocessedData?.orders ?? [];
  const unprocessedTotal = unprocessedData?.total ?? 0;

  const completedOrders = completedData?.orders ?? [];
  const completedTotal = completedData?.total ?? 0;
  const completedTotalPages = completedTotal ? Math.ceil(completedTotal / perPage) : 1;

  const pendingCount = unprocessedTotal;
  const processingCount = orders.filter((o) => o.status === "processing" || o.status === "pending").length;

  // ============ Handlers ============

  function openDetail(id: number) { setDetailId(id); setDetailOpen(true); }

  function openEdit(o: PurchaseOrder) {
    setEditId(o.id);
    setEditForm({ status: o.status, remark: o.remark || "", supplier_name: o.supplier_name || "", modify_reason: "" });
    setEditOpen(true);
  }

  function toggleOrderExpand(id: number) {
    setExpandedOrders((prev) => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }

  function toggleOrderSelect(id: number, checked: boolean) {
    setSelectedOrderIds((prev) => { const next = new Set(prev); if (checked) next.add(id); else next.delete(id); return next; });
  }

  function toggleUnprocessedSelect(id: number, checked: boolean) {
    setSelectedUnprocessedIds((prev) => { const next = new Set(prev); if (checked) next.add(id); else next.delete(id); return next; });
  }

  function handleOneClickGenerate() {
    if (selectedUnprocessedIds.size === 0) { toast.warning("请先选择待审核订单"); return; }
    setConfirmData({
      title: "一键审核订单",
      text: `确定要将选中的 ${selectedUnprocessedIds.size} 个订单一键审核生成采购订单吗？`,
      variant: "warning",
      onConfirm: () => oneClickMutation.mutate(Array.from(selectedUnprocessedIds)),
    });
    setConfirmOpen(true);
  }

  function handleBatchComplete() {
    const processingOrders = orders.filter((o) => (o.status === "processing" || o.status === "pending") && selectedOrderIds.has(o.id));
    if (processingOrders.length === 0) { toast.warning("请先选择采购中的订单"); return; }
    setConfirmData({
      title: "批量确认订单",
      text: `确定要将选中的 ${processingOrders.length} 个采购订单标记为已完成吗？`,
      variant: "warning",
      onConfirm: () => batchCompleteMutation.mutate(processingOrders.map((o) => o.id)),
    });
    setConfirmOpen(true);
  }

  function handleBatchDelete() {
    if (selectedOrderIds.size === 0) { toast.warning("请先选择要删除的订单"); return; }
    setConfirmData({
      title: "批量删除订单",
      text: `确定要删除选中的 ${selectedOrderIds.size} 个采购订单吗？此操作不可撤销。`,
      variant: "danger",
      onConfirm: () => batchDeleteMutation.mutate(Array.from(selectedOrderIds)),
    });
    setConfirmOpen(true);
  }

  async function handleSummaryOrder() {
    const processingOrders = orders.filter((o) => (o.status === "processing" || o.status === "pending") && selectedOrderIds.has(o.id));
    if (processingOrders.length === 0) { toast.warning("请先选择要汇总的订单"); return; }
    setSummaryLoading(true);
    setSummaryOpen(true);
    try {
      const res = await post<{ success: boolean; data?: any }>("/purchase-center/orders/supplier-summary", { order_ids: processingOrders.map((o) => o.id) });
      if (res.success && res.data) setSummaryData(res.data);
      else toast.error("获取汇总数据失败");
    } catch { toast.error("获取汇总数据失败"); }
    setSummaryLoading(false);
  }

  async function handleExport() {
    try {
      const res = await post<{ success: boolean; html?: string }>("/purchase-center/orders/completed/export", {
        order_no: hOrderNo, customer_name: hCustomer, product_name: hProduct,
        supplier_name: hSupplier, barcode: hBarcode, start_date: hStartDate,
        end_date: hEndDate, material_name: hMaterial, status: hQuickStatus,
      });
      if (res.success && res.html) { setExportPreviewHtml(res.html); setExportPreviewOpen(true); }
      else toast.error("导出失败");
    } catch { toast.error("导出失败"); }
  }

  function resetHistoryFilters() {
    setHOrderNo(""); setHCustomer(""); setHProduct(""); setHSupplier("");
    setHBarcode(""); setHStartDate(""); setHEndDate(""); setHMaterial(""); setHQuickStatus(""); setHPage(1);
  }

  // Autocomplete handler
  const fetchSuggestions = useCallback(async (field: string, keyword: string) => {
    if (keyword.length < 1) { setSuggestions((prev) => ({ ...prev, [field]: [] })); return; }
    try {
      const res = await get<{ success: boolean; suggestions: AutocompleteSuggestion[] }>("/purchase-center/orders/completed/suggestions", { field, keyword });
      if (res.success) setSuggestions((prev) => ({ ...prev, [field]: res.suggestions || [] }));
    } catch { /* ignore */ }
  }, []);

  function handleSuggestionInput(field: string, value: string) {
    setShowSuggestion((prev) => ({ ...prev, [field]: true }));
    if (suggestionTimers.current[field]) clearTimeout(suggestionTimers.current[field]);
    suggestionTimers.current[field] = setTimeout(() => fetchSuggestions(field, value), 300);
  }

  function selectSuggestion(field: string, value: string, setter: (v: string) => void) {
    setter(value);
    setShowSuggestion((prev) => ({ ...prev, [field]: false }));
  }

  // Update saved queries from query data
  useEffect(() => {
    if (savedQueriesData?.queries) setSavedQueries(savedQueriesData.queries);
  }, [savedQueriesData]);

  // ============ Render ============

  return (
    <div className="pc-container">
      {/* Header */}
      <div className="pc-header">
        <div className="pc-header-content">
          <div className="pc-header-left">
            <h1><StoreIcon style={{ width: 24, height: 24 }} /> 采购中心</h1>
            <p>用料计算 · 采购订单</p>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="pc-body">
        {/* Tabs */}
        <div className="pc-tabs">
          <button className={`pc-tab ${activeTab === "orders" ? "active" : ""}`} onClick={() => setActiveTab("orders")}>
            <FileTextIcon style={{ width: 16, height: 16 }} /> 采购订单
            <span className="badge-count">{pendingCount}</span>
          </button>
          <button className={`pc-tab ${activeTab === "history" ? "active" : ""}`} onClick={() => { setActiveTab("history"); setHPage(1); }}>
            <CheckCircleIcon style={{ width: 16, height: 16 }} /> 下单查询
          </button>
        </div>

        {/* ===== Orders Panel ===== */}
        <div className={`pc-panel ${activeTab === "orders" ? "active" : ""}`} id="panel-orders">
          {/* 审核订单 */}
          <div className="pc-card pc-pending-section" id="pending-purchase-section">
            <div className="pc-card-header">
              <div className="pc-card-title"><InboxIcon style={{ width: 18, height: 18 }} /> 审核订单</div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                <button
                  className="pc-btn pc-btn-success pc-btn-sm"
                  disabled={selectedUnprocessedIds.size === 0}
                  onClick={handleOneClickGenerate}
                  style={{ background: "linear-gradient(135deg, #28C76F 0%, #1E9E55 100%)", border: "none", boxShadow: "0 2px 8px rgba(40,199,111,0.3)" }}
                >
                  <Wand2Icon style={{ width: 14, height: 14 }} /> 一键审核订单 <span>({selectedUnprocessedIds.size})</span>
                </button>
              </div>
            </div>
            <div className="pc-card-body">
              <div id="unprocessedList">
                {unprocessedLoading ? (
                  <div className="pc-loading"><div className="spinner" /> 加载中...</div>
                ) : unprocessedOrders.length === 0 ? (
                  <div className="pc-empty-state"><InboxIcon style={{ width: 48, height: 48, opacity: 0.3, marginBottom: 12 }} /><p>暂无待审核订单</p></div>
                ) : (
                  <>
                    {/* Select all bar */}
                    <div style={{ marginBottom: 12, padding: "12px 16px", background: "var(--pc-primary-lighter)", borderRadius: "var(--pc-radius-md)", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 13, fontWeight: 500, color: "var(--pc-primary-dark)" }}>
                        <input type="checkbox" style={{ width: 18, height: 18, accentColor: "var(--pc-primary)" }}
                          checked={selectedUnprocessedIds.size === unprocessedOrders.length && unprocessedOrders.length > 0}
                          onChange={(e) => {
                            if (e.target.checked) setSelectedUnprocessedIds(new Set(unprocessedOrders.map((o) => o.id)));
                            else setSelectedUnprocessedIds(new Set());
                          }}
                        />
                        全选 ({selectedUnprocessedIds.size}/{unprocessedOrders.length})
                      </label>
                    </div>
                    {/* Unprocessed order cards */}
                    {unprocessedOrders.map((o) => {
                      const isSelected = selectedUnprocessedIds.has(o.id);
                      return (
                        <div key={o.id} className={`pc-unprocessed-card ${isSelected ? "selected" : ""}`} onClick={() => toggleUnprocessedSelect(o.id, !isSelected)}>
                          <div className="card-top">
                            <div className="order-no">{o.order_no}</div>
                            <input type="checkbox" style={{ width: 18, height: 18, accentColor: "var(--pc-primary)" }}
                              checked={isSelected}
                              onChange={(e) => { e.stopPropagation(); toggleUnprocessedSelect(o.id, e.target.checked); }}
                              onClick={(e) => e.stopPropagation()}
                            />
                          </div>
                          <div className="order-meta">
                            <span>客户: {o.customer_name || "未指定"}</span>
                            <span>供应商: {o.supplier_name || "未指定"}</span>
                            <span>产品: {o.product_name || "-"}</span>
                          </div>
                        </div>
                      );
                    })}
                  </>
                )}
              </div>
            </div>
          </div>

          {/* Divider */}
          <div className="pc-section-divider" />

          {/* 采购中订单 */}
          <div className="pc-card">
            <div className="pc-card-header">
              <div className="pc-card-title"><ListIcon style={{ width: 18, height: 18 }} /> 采购中订单</div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                <button className="pc-btn pc-btn-primary" disabled={selectedOrderIds.size === 0} onClick={handleSummaryOrder}
                  style={{ background: "linear-gradient(135deg,#667eea 0%,#764ba2 100%)", border: "none" }}>
                  <ClipboardListIcon style={{ width: 14, height: 14 }} /> 汇总下单 <span>({selectedOrderIds.size})</span>
                </button>
                <button className="pc-btn pc-btn-success pc-btn-sm" disabled={selectedOrderIds.size === 0} onClick={handleBatchComplete}>
                  <CheckCheckIcon style={{ width: 14, height: 14 }} /> 批量确认订单 <span>({selectedOrderIds.size})</span>
                </button>
                <span className="pc-badge pc-badge-pending">{orderTotal} 个订单</span>
              </div>
            </div>
            <div className="pc-card-body">
              {/* Filter bar */}
              <div className="pc-filter-bar">
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <SearchIcon style={{ width: 16, height: 16, color: "var(--pc-text-muted)" }} />
                  <input type="text" className="pc-form-input" placeholder="搜索客户..."
                    value={orderSearch} onChange={(e) => setOrderSearch(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") { setOrderCustomer(orderSearch); setOrderPage(1); } }}
                    style={{ width: 200 }}
                  />
                  <button className="pc-btn pc-btn-primary pc-btn-sm" onClick={() => { setOrderCustomer(orderSearch); setOrderPage(1); }}>搜索</button>
                  {orderCustomer && <button className="pc-btn pc-btn-outline pc-btn-sm" onClick={() => { setOrderSearch(""); setOrderCustomer(""); setOrderPage(1); }}>清除</button>}
                </div>
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  {["", "pending", "processing", "completed", "cancelled"].map((s) => (
                    <button key={s} className={`pc-quick-filter-btn ${orderStatus === s ? "active" : ""}`}
                      onClick={() => { setOrderStatus(s); setOrderPage(1); }}>
                      {s ? STATUS_MAP[s]?.label || s : "全部"}
                    </button>
                  ))}
                </div>
              </div>

              {/* Order list */}
              <div id="orderList">
                {ordersLoading ? (
                  <div className="pc-loading"><div className="spinner" /> 加载中...</div>
                ) : orders.length === 0 ? (
                  <div className="pc-empty-state"><InboxIcon style={{ width: 48, height: 48, opacity: 0.3, marginBottom: 12 }} /><p>暂无采购订单</p></div>
                ) : (
                  <>
                    {/* Select all */}
                    <div style={{ marginBottom: 12, padding: "12px 16px", background: "var(--pc-primary-lighter)", borderRadius: "var(--pc-radius-md)", display: "flex", alignItems: "center", gap: 12 }}>
                      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 13, fontWeight: 500, color: "var(--pc-primary-dark)" }}>
                        <input type="checkbox" style={{ width: 18, height: 18, accentColor: "var(--pc-primary)" }}
                          checked={selectedOrderIds.size === orders.length && orders.length > 0}
                          onChange={(e) => {
                            if (e.target.checked) setSelectedOrderIds(new Set(orders.map((o) => o.id)));
                            else setSelectedOrderIds(new Set());
                          }}
                        />
                        全选 ({selectedOrderIds.size}/{orders.length})
                      </label>
                    </div>
                    {/* Order cards */}
                    {orders.map((o) => {
                      const isSelected = selectedOrderIds.has(o.id);
                      const isExpanded = expandedOrders.has(o.id);
                      const st = STATUS_MAP[o.status];
                      return (
                        <div key={o.id} className={`pc-order-card ${isExpanded ? "expanded" : ""}`}>
                          <div className="pc-order-card-header" onClick={() => toggleOrderExpand(o.id)}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <input type="checkbox" style={{ width: 18, height: 18, accentColor: "var(--pc-primary)" }}
                                checked={isSelected} onChange={(e) => toggleOrderSelect(o.id, e.target.checked)}
                                onClick={(e) => e.stopPropagation()}
                              />
                              <span className="order-no" style={{ fontWeight: 600, color: "var(--pc-primary-dark)", cursor: "pointer" }}
                                onClick={(e) => { e.stopPropagation(); openDetail(o.id); }}>
                                {o.order_no}
                              </span>
                            </div>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              {st && <span className="pc-badge" style={{ background: st.bg, color: st.color }}>{st.label}</span>}
                              <button className="pc-btn pc-btn-detail pc-btn-sm" onClick={(e) => { e.stopPropagation(); openDetail(o.id); }}>
                                <EyeIcon style={{ width: 14, height: 14 }} /> 详情
                              </button>
                              {(o.status === "pending" || o.status === "processing") && (
                                <>
                                  <button className="pc-btn pc-btn-outline pc-btn-sm" onClick={(e) => { e.stopPropagation(); openEdit(o); }}>
                                    <ClipboardListIcon style={{ width: 14, height: 14 }} /> 编辑
                                  </button>
                                  <button className="pc-btn pc-btn-success pc-btn-sm" onClick={(e) => { e.stopPropagation(); setConfirmData({ title: "完成订单", text: `确定完成订单"${o.order_no}"吗？`, variant: "warning", onConfirm: () => completeMutation.mutate(o.id) }); setConfirmOpen(true); }}>
                                    <CheckIcon style={{ width: 14, height: 14 }} /> 完成
                                  </button>
                                </>
                              )}
                              <button className="pc-btn pc-btn-danger pc-btn-sm" onClick={(e) => { e.stopPropagation(); setConfirmData({ title: "删除订单", text: `确定删除订单"${o.order_no}"吗？`, variant: "danger", onConfirm: () => deleteMutation.mutate(o.id) }); setConfirmOpen(true); }}>
                                <Trash2Icon style={{ width: 14, height: 14 }} /> 删除
                              </button>
                              {isExpanded ? <ChevronUpIcon style={{ width: 16, height: 16 }} /> : <ChevronDownIcon style={{ width: 16, height: 16 }} />}
                            </div>
                          </div>
                          {isExpanded && (
                            <div className="pc-order-card-body" style={{ display: "block", padding: "0 16px 16px" }}>
                              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, padding: "12px 0" }}>
                                <div><span style={{ fontSize: 12, color: "var(--pc-text-secondary)", fontWeight: 600 }}>客户</span><div style={{ fontSize: 14, fontWeight: 600 }}>{o.customer_name || "未指定"}</div></div>
                                <div><span style={{ fontSize: 12, color: "var(--pc-text-secondary)", fontWeight: 600 }}>供应商</span><div style={{ fontSize: 14, fontWeight: 600 }}>{o.supplier_name || "未指定"}</div></div>
                                <div><span style={{ fontSize: 12, color: "var(--pc-text-secondary)", fontWeight: 600 }}>下单日期</span><div style={{ fontSize: 14, fontWeight: 600 }}>{o.order_date || "-"}</div></div>
                                <div><span style={{ fontSize: 12, color: "var(--pc-text-secondary)", fontWeight: 600 }}>创建时间</span><div style={{ fontSize: 14, fontWeight: 600 }}>{o.create_time || "-"}</div></div>
                              </div>
                              {o.items && o.items.length > 0 && (
                                <table className="pc-items-table">
                                  <thead>
                                    <tr>
                                      <th style={{ width: "40%" }}>物料名称</th>
                                      <th style={{ width: "15%" }}>规格</th>
                                      <th style={{ width: "10%" }}>单位</th>
                                      <th style={{ width: "15%" }}>采购数量</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {o.items.map((item, i) => (
                                      <tr key={i}>
                                        <td style={{ fontWeight: 650, color: "var(--pc-text)" }}>{item.material_name}</td>
                                        <td>{item.specification || "-"}</td>
                                        <td style={{ textAlign: "center" }}>{item.unit || "-"}</td>
                                        <td style={{ fontWeight: 750, color: "var(--pc-primary-dark)", textAlign: "right" }}>{Number(item.quantity || 0).toFixed(2)}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </>
                )}
              </div>

              {/* Pagination */}
              {orderTotalPages > 1 && (
                <div className="pc-pagination">
                  <button className="pc-btn pc-btn-outline pc-btn-sm" disabled={orderPage <= 1} onClick={() => setOrderPage((p) => Math.max(1, p - 1))}>上一页</button>
                  <span style={{ fontSize: 13, color: "var(--pc-text-secondary)" }}>第 {orderPage} / {orderTotalPages} 页（共 {orderTotal} 条）</span>
                  <button className="pc-btn pc-btn-outline pc-btn-sm" disabled={orderPage >= orderTotalPages} onClick={() => setOrderPage((p) => Math.min(orderTotalPages, p + 1))}>下一页</button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ===== History Panel ===== */}
        <div className={`pc-panel ${activeTab === "history" ? "active" : ""}`} id="panel-history">
          <div className="pc-card">
            <div className="pc-card-header">
              <div className="pc-card-title"><CheckCircleIcon style={{ width: 18, height: 18 }} /> 下单查询</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <button className="pc-btn pc-btn-outline pc-btn-sm" onClick={() => setFilterPanelOpen(!filterPanelOpen)}>
                  <FilterIcon style={{ width: 14, height: 14 }} /> {filterPanelOpen ? "收起筛选" : "展开筛选"}
                </button>
                <button className="pc-btn pc-btn-primary pc-btn-sm" onClick={handleExport}>
                  <FileSpreadsheetIcon style={{ width: 14, height: 14 }} /> 导出
                </button>
              </div>
            </div>

            {/* Quick filters */}
            <div className="pc-card-body" style={{ paddingBottom: 0 }}>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
                {["", "pending", "processing", "completed", "cancelled"].map((s) => (
                  <button key={s} className={`pc-quick-filter-btn ${hQuickStatus === s ? "active" : ""}`}
                    onClick={() => { setHQuickStatus(s); setHPage(1); }}>
                    {s ? STATUS_MAP[s]?.label || s : "全部"}
                  </button>
                ))}
              </div>
            </div>

            {/* Advanced filter panel */}
            {filterPanelOpen && (
              <div>
                <div className="pc-card-body" style={{ paddingTop: 0 }}>
                  <div className="pc-grid pc-grid-2" style={{ gap: 16 }}>
                    {/* Basic conditions */}
                    <div className="pc-card" style={{ marginBottom: 0 }}>
                      <div className="pc-card-header" style={{ padding: "12px 16px" }}>
                        <div className="pc-card-title" style={{ fontSize: 14 }}><InfoIcon style={{ width: 14, height: 14 }} /> 基本条件</div>
                      </div>
                      <div className="pc-card-body" style={{ padding: 16 }}>
                        <div className="pc-grid pc-grid-2" style={{ gap: 12 }}>
                          <div className="pc-form-group">
                            <label className="pc-form-label">订单号</label>
                            <div className="pc-search-input-wrapper">
                              <SearchIcon style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--pc-text-muted)", width: 14, height: 14 }} />
                              <input type="text" className="pc-form-input" placeholder="输入订单号" value={hOrderNo}
                                onChange={(e) => { setHOrderNo(e.target.value); handleSuggestionInput("order_no", e.target.value); }}
                                onFocus={() => setShowSuggestion((p) => ({ ...p, order_no: true }))}
                                onBlur={() => setTimeout(() => setShowSuggestion((p) => ({ ...p, order_no: false })), 200)}
                                style={{ paddingLeft: 36 }}
                              />
                              {showSuggestion.order_no && suggestions.order_no && suggestions.order_no.length > 0 && (
                                <div className="autocomplete-dropdown">
                                  {suggestions.order_no.map((s, i) => (
                                    <div key={i} className="autocomplete-item" onMouseDown={() => selectSuggestion("order_no", s.value, setHOrderNo)}>{s.label}</div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                          <div className="pc-form-group">
                            <label className="pc-form-label">客户名称</label>
                            <div className="pc-search-input-wrapper">
                              <SearchIcon style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--pc-text-muted)", width: 14, height: 14 }} />
                              <input type="text" className="pc-form-input" placeholder="输入客户名称" value={hCustomer}
                                onChange={(e) => { setHCustomer(e.target.value); handleSuggestionInput("customer_name", e.target.value); }}
                                onFocus={() => setShowSuggestion((p) => ({ ...p, customer_name: true }))}
                                onBlur={() => setTimeout(() => setShowSuggestion((p) => ({ ...p, customer_name: false })), 200)}
                                style={{ paddingLeft: 36 }}
                              />
                              {showSuggestion.customer_name && suggestions.customer_name && suggestions.customer_name.length > 0 && (
                                <div className="autocomplete-dropdown">
                                  {suggestions.customer_name.map((s, i) => (
                                    <div key={i} className="autocomplete-item" onMouseDown={() => selectSuggestion("customer_name", s.value, setHCustomer)}>{s.label}</div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                          <div className="pc-form-group">
                            <label className="pc-form-label">产品名称</label>
                            <div className="pc-search-input-wrapper">
                              <SearchIcon style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--pc-text-muted)", width: 14, height: 14 }} />
                              <input type="text" className="pc-form-input" placeholder="输入产品名称" value={hProduct}
                                onChange={(e) => { setHProduct(e.target.value); handleSuggestionInput("product_name", e.target.value); }}
                                onFocus={() => setShowSuggestion((p) => ({ ...p, product_name: true }))}
                                onBlur={() => setTimeout(() => setShowSuggestion((p) => ({ ...p, product_name: false })), 200)}
                                style={{ paddingLeft: 36 }}
                              />
                              {showSuggestion.product_name && suggestions.product_name && suggestions.product_name.length > 0 && (
                                <div className="autocomplete-dropdown">
                                  {suggestions.product_name.map((s, i) => (
                                    <div key={i} className="autocomplete-item" onMouseDown={() => selectSuggestion("product_name", s.value, setHProduct)}>{s.label}</div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                          <div className="pc-form-group">
                            <label className="pc-form-label">供应商名称</label>
                            <div className="pc-search-input-wrapper">
                              <SearchIcon style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--pc-text-muted)", width: 14, height: 14 }} />
                              <input type="text" className="pc-form-input" placeholder="输入供应商名称" value={hSupplier}
                                onChange={(e) => { setHSupplier(e.target.value); handleSuggestionInput("supplier_name", e.target.value); }}
                                onFocus={() => setShowSuggestion((p) => ({ ...p, supplier_name: true }))}
                                onBlur={() => setTimeout(() => setShowSuggestion((p) => ({ ...p, supplier_name: false })), 200)}
                                style={{ paddingLeft: 36 }}
                              />
                              {showSuggestion.supplier_name && suggestions.supplier_name && suggestions.supplier_name.length > 0 && (
                                <div className="autocomplete-dropdown">
                                  {suggestions.supplier_name.map((s, i) => (
                                    <div key={i} className="autocomplete-item" onMouseDown={() => selectSuggestion("supplier_name", s.value, setHSupplier)}>{s.label}</div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                          <div className="pc-form-group">
                            <label className="pc-form-label">69码</label>
                            <div className="pc-search-input-wrapper">
                              <ScanBarcodeIcon style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--pc-text-muted)", width: 14, height: 14 }} />
                              <input type="text" className="pc-form-input" placeholder="输入69码查询对应SKU" value={hBarcode}
                                onChange={(e) => setHBarcode(e.target.value)} style={{ paddingLeft: 36 }} />
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Time & material */}
                    <div className="pc-card" style={{ marginBottom: 0 }}>
                      <div className="pc-card-header" style={{ padding: "12px 16px" }}>
                        <div className="pc-card-title" style={{ fontSize: 14 }}><CalendarDaysIcon style={{ width: 14, height: 14 }} /> 时间与物料</div>
                      </div>
                      <div className="pc-card-body" style={{ padding: 16 }}>
                        <div className="pc-grid pc-grid-2" style={{ gap: 12 }}>
                          <div className="pc-form-group">
                            <label className="pc-form-label">开始日期</label>
                            <input type="date" className="pc-form-input" value={hStartDate} onChange={(e) => setHStartDate(e.target.value)} />
                          </div>
                          <div className="pc-form-group">
                            <label className="pc-form-label">结束日期</label>
                            <input type="date" className="pc-form-input" value={hEndDate} onChange={(e) => setHEndDate(e.target.value)} />
                          </div>
                          <div className="pc-form-group" style={{ gridColumn: "1 / -1" }}>
                            <label className="pc-form-label">物料名称</label>
                            <div className="pc-search-input-wrapper">
                              <SearchIcon style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--pc-text-muted)", width: 14, height: 14 }} />
                              <input type="text" className="pc-form-input" placeholder="输入物料名称" value={hMaterial}
                                onChange={(e) => { setHMaterial(e.target.value); handleSuggestionInput("material_name", e.target.value); }}
                                onFocus={() => setShowSuggestion((p) => ({ ...p, material_name: true }))}
                                onBlur={() => setTimeout(() => setShowSuggestion((p) => ({ ...p, material_name: false })), 200)}
                                style={{ paddingLeft: 36 }}
                              />
                              {showSuggestion.material_name && suggestions.material_name && suggestions.material_name.length > 0 && (
                                <div className="autocomplete-dropdown">
                                  {suggestions.material_name.map((s, i) => (
                                    <div key={i} className="autocomplete-item" onMouseDown={() => selectSuggestion("material_name", s.value, setHMaterial)}>{s.label}</div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Action buttons */}
                  <div style={{ marginTop: 16, display: "flex", gap: 8, justifyContent: "flex-end" }}>
                    <button className="pc-btn pc-btn-outline" onClick={resetHistoryFilters}>
                      <RefreshCwIcon style={{ width: 14, height: 14 }} /> 重置
                    </button>
                    <button className="pc-btn pc-btn-primary" onClick={() => { setHPage(1); queryClient.invalidateQueries({ queryKey: ["purchase-completed"] }); }}>
                      <SearchIcon style={{ width: 14, height: 14 }} /> 查询
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Results */}
            <div className="pc-card-body" style={{ paddingTop: 0 }}>
              <div style={{ minHeight: 200 }}>
                {completedLoading ? (
                  <div className="pc-loading"><div className="spinner" /> 加载中...</div>
                ) : completedOrders.length === 0 ? (
                  <div className="pc-empty-state"><CheckCircleIcon style={{ width: 48, height: 48, opacity: 0.3, marginBottom: 12 }} /><p>暂无订单数据</p></div>
                ) : (
                  completedOrders.map((o) => {
                    const st = STATUS_MAP[o.status];
                    return (
                      <div key={o.id} className="pc-unprocessed-card" style={{ borderLeftColor: st ? st.color : "var(--pc-info)" }}>
                        <div className="card-top">
                          <div className="order-no">{o.order_no}</div>
                          {st && <span className="pc-badge" style={{ background: st.bg, color: st.color }}>{st.label}</span>}
                        </div>
                        <div className="order-meta">
                          <span>客户: {o.customer_name || "未指定"}</span>
                          <span>供应商: {o.supplier_name || "未指定"}</span>
                          <span>日期: {o.order_date || o.create_time || "-"}</span>
                        </div>
                        <div className="card-actions">
                          <button className="pc-btn pc-btn-detail pc-btn-sm" onClick={() => openDetail(o.id)}><EyeIcon style={{ width: 14, height: 14 }} /> 详情</button>
                          <button className="pc-btn pc-btn-danger pc-btn-sm" onClick={() => { setConfirmData({ title: "删除订单", text: `确定删除订单"${o.order_no}"吗？`, variant: "danger", onConfirm: () => deleteMutation.mutate(o.id) }); setConfirmOpen(true); }}>
                            <Trash2Icon style={{ width: 14, height: 14 }} /> 删除
                          </button>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
              {/* Pagination */}
              {completedTotalPages > 1 && (
                <div className="pc-pagination">
                  <button className="pc-btn pc-btn-outline pc-btn-sm" disabled={hPage <= 1} onClick={() => setHPage((p) => Math.max(1, p - 1))}>上一页</button>
                  <span style={{ fontSize: 13, color: "var(--pc-text-secondary)" }}>第 {hPage} / {completedTotalPages} 页（共 {completedTotal} 条）</span>
                  <button className="pc-btn pc-btn-outline pc-btn-sm" disabled={hPage >= completedTotalPages} onClick={() => setHPage((p) => Math.min(completedTotalPages, p + 1))}>下一页</button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ===== Confirm Modal ===== */}
      {confirmOpen && (
        <div className="pc-modal-overlay show" onClick={() => { setConfirmOpen(false); setConfirmData(null); }}>
          <div className="pc-modal" style={{ maxWidth: 420 }} onClick={(e) => e.stopPropagation()}>
            <div className="pc-modal-body" style={{ padding: 32 }}>
              <div className={`pc-confirm-icon ${confirmData?.variant || "warning"}`}>
                <AlertTriangleIcon style={{ width: 24, height: 24 }} />
              </div>
              <div className="pc-confirm-text">{confirmData?.text}</div>
              {confirmData?.sub && <div className="pc-confirm-sub">{confirmData.sub}</div>}
            </div>
            <div className="pc-modal-footer">
              <button className="pc-btn pc-btn-outline" onClick={() => { setConfirmOpen(false); setConfirmData(null); }}>取消</button>
              <button className={`pc-btn ${confirmData?.variant === "danger" ? "pc-btn-danger" : "pc-btn-primary"}`}
                onClick={() => { confirmData?.onConfirm(); }}>
                确认
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===== Order Detail Modal ===== */}
      {detailOpen && (
        <div className="pc-modal-overlay show" onClick={() => setDetailOpen(false)}>
          <div className="pc-modal" style={{ maxWidth: 800 }} onClick={(e) => e.stopPropagation()}>
            <div className="pc-modal-header">
              <h3><FileTextIcon style={{ width: 18, height: 18 }} /> 采购订单详情</h3>
              <button className="pc-modal-close" onClick={() => setDetailOpen(false)}><XIcon style={{ width: 16, height: 16 }} /></button>
            </div>
            <div className="pc-modal-body">
              {detailLoading ? (
                <div className="pc-loading"><div className="spinner" /> 加载中...</div>
              ) : detailData?.order ? (
                <div>
                  <div className="pc-grid pc-grid-2" style={{ gap: 12, marginBottom: 16 }}>
                    <div><span style={{ fontSize: 12, color: "var(--pc-text-secondary)" }}>订单号:</span> <strong>{detailData.order.order_no}</strong></div>
                    <div><span style={{ fontSize: 12, color: "var(--pc-text-secondary)" }}>客户:</span> <strong>{detailData.order.customer_name || "-"}</strong></div>
                    <div><span style={{ fontSize: 12, color: "var(--pc-text-secondary)" }}>供应商:</span> <strong>{detailData.order.supplier_name || "-"}</strong></div>
                    <div><span style={{ fontSize: 12, color: "var(--pc-text-secondary)" }}>状态:</span> <strong>{STATUS_MAP[detailData.order.status]?.label || detailData.order.status}</strong></div>
                  </div>
                  {detailData.order.remark && <div style={{ marginBottom: 12 }}><span style={{ fontSize: 12, color: "var(--pc-text-secondary)" }}>备注:</span> {detailData.order.remark}</div>}
                  {(detailData.order.items || detailData.order.materials) && (detailData.order.items || detailData.order.materials || []).length > 0 && (
                    <div>
                      <div style={{ borderTop: "1px solid var(--pc-border)", paddingTop: 12, marginTop: 8 }}>
                        <strong style={{ marginBottom: 8, display: "block" }}>物料明细</strong>
                        <table className="pc-items-table">
                          <thead>
                            <tr><th>名称</th><th>规格</th><th style={{ textAlign: "right" }}>数量</th><th>单位</th><th>分类</th></tr>
                          </thead>
                          <tbody>
                            {(detailData.order.items || detailData.order.materials || []).map((m: any, i: number) => (
                              <tr key={i}>
                                <td style={{ fontWeight: 650 }}>{m.material_name || m.name}</td>
                                <td>{m.specification || "-"}</td>
                                <td style={{ fontWeight: 750, textAlign: "right", color: "var(--pc-primary-dark)" }}>{Number(m.quantity || 0).toFixed(2)}</td>
                                <td>{m.unit}</td>
                                <td>{m.category || "-"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              ) : null}
            </div>
            <div className="pc-modal-footer">
              <button className="pc-btn pc-btn-outline" onClick={() => setDetailOpen(false)}>关闭</button>
            </div>
          </div>
        </div>
      )}

      {/* ===== Edit Modal ===== */}
      {editOpen && (
        <div className="pc-modal-overlay show" onClick={() => setEditOpen(false)}>
          <div className="pc-modal" style={{ maxWidth: 500 }} onClick={(e) => e.stopPropagation()}>
            <div className="pc-modal-header">
              <h3><ClipboardListIcon style={{ width: 18, height: 18 }} /> 编辑采购订单</h3>
              <button className="pc-modal-close" onClick={() => setEditOpen(false)}><XIcon style={{ width: 16, height: 16 }} /></button>
            </div>
            <div className="pc-modal-body">
              <div className="pc-form-group">
                <label className="pc-form-label">供应商</label>
                <input type="text" className="pc-form-input" value={editForm.supplier_name} onChange={(e) => setEditForm({ ...editForm, supplier_name: e.target.value })} />
              </div>
              <div className="pc-form-group">
                <label className="pc-form-label">备注</label>
                <input type="text" className="pc-form-input" value={editForm.remark} onChange={(e) => setEditForm({ ...editForm, remark: e.target.value })} />
              </div>
              <div className="pc-form-group">
                <label className="pc-form-label">修改原因</label>
                <input type="text" className="pc-form-input" value={editForm.modify_reason} onChange={(e) => setEditForm({ ...editForm, modify_reason: e.target.value })} />
              </div>
            </div>
            <div className="pc-modal-footer">
              <button className="pc-btn pc-btn-outline" onClick={() => setEditOpen(false)}>取消</button>
              <button className="pc-btn pc-btn-primary" onClick={() => { if (editId) updateMutation.mutate({ id: editId, body: editForm }); }} disabled={updateMutation.isPending}>
                {updateMutation.isPending ? "保存中..." : "保存"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===== Export Preview Modal ===== */}
      {exportPreviewOpen && (
        <div className="pc-modal-overlay show" onClick={() => setExportPreviewOpen(false)}>
          <div className="pc-modal" style={{ maxWidth: 1100 }} onClick={(e) => e.stopPropagation()}>
            <div className="pc-modal-header">
              <h3><FileSpreadsheetIcon style={{ width: 18, height: 18 }} /> 导出格式预览</h3>
              <button className="pc-modal-close" onClick={() => setExportPreviewOpen(false)}><XIcon style={{ width: 16, height: 16 }} /></button>
            </div>
            <div className="pc-modal-body" style={{ padding: 0 }} dangerouslySetInnerHTML={{ __html: exportPreviewHtml }} />
            <div className="pc-modal-footer" style={{ justifyContent: "space-between" }}>
              <div style={{ fontSize: 12, color: "var(--pc-text-secondary)" }}><InfoIcon style={{ width: 14, height: 14 }} /> 请确认以下导出格式是否符合预期</div>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="pc-btn pc-btn-outline" onClick={() => setExportPreviewOpen(false)}>取消</button>
                <button className="pc-btn pc-btn-success" onClick={() => {
                  const printWindow = window.open("", "_blank");
                  if (printWindow) { printWindow.document.write(exportPreviewHtml); printWindow.document.close(); printWindow.print(); }
                  setExportPreviewOpen(false);
                }}>
                  <DownloadIcon style={{ width: 14, height: 14 }} /> 确认导出
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ===== Summary/Status History Modal ===== */}
      {summaryOpen && (
        <div className="pc-modal-overlay show" onClick={() => setSummaryOpen(false)}>
          <div className="pc-modal" style={{ maxWidth: 1000 }} onClick={(e) => e.stopPropagation()}>
            <div className="pc-modal-header">
              <h3><HistoryIcon style={{ width: 18, height: 18 }} /> 订单汇总</h3>
              <button className="pc-modal-close" onClick={() => setSummaryOpen(false)}><XIcon style={{ width: 16, height: 16 }} /></button>
            </div>
            <div className="pc-modal-body">
              {summaryLoading ? (
                <div className="pc-loading"><div className="spinner" /> 加载中...</div>
              ) : summaryData ? (
                <div>
                  {Array.isArray(summaryData) ? summaryData.map((supplier: any, idx: number) => (
                    <div key={idx} className="supplier-card" style={{ border: "2px solid #e5e7eb", borderRadius: 10, padding: 16, marginBottom: 12 }}>
                      <div className="supplier-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                        <span className="supplier-name" style={{ fontWeight: 600, fontSize: 15 }}>{supplier.supplier_name || "未分类"}</span>
                        <span style={{ fontSize: 12, color: "#6b7280" }}>{supplier.materials?.length || 0} 种物料</span>
                      </div>
                      {supplier.materials?.map((mat: any, mi: number) => (
                        <div key={mi} className="summary-material-card" style={{ background: "#f9fafb", borderRadius: 10, padding: 16, marginBottom: 8 }}>
                          <div className="summary-material-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, paddingBottom: 8, borderBottom: "1px solid #e5e7eb" }}>
                            <span style={{ fontWeight: 600, fontSize: 15 }}>{mat.material_name}</span>
                            <span style={{ fontSize: 18, fontWeight: 700, color: "#667eea" }}>{Number(mat.total_quantity || 0).toFixed(2)} {mat.unit || ""}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )) : <div>暂无汇总数据</div>}
                </div>
              ) : <div>暂无数据</div>}
            </div>
          </div>
        </div>
      )}

      {/* ===== Styles ===== */}
      <style jsx global>{`
        :root {
          --pc-primary: #5B8DEF;
          --pc-primary-light: #8BABF5;
          --pc-primary-lighter: #D6E4FF;
          --pc-primary-dark: #3A6BD6;
          --pc-secondary: #6C757D;
          --pc-success: #28C76F;
          --pc-success-light: #E8F9EF;
          --pc-warning: #FF9F43;
          --pc-warning-light: #FFF3E6;
          --pc-danger: #EA5455;
          --pc-danger-light: #FDE8E8;
          --pc-info: #00CFE8;
          --pc-info-light: #E5FAFE;
          --pc-bg: #F4F6FC;
          --pc-card: #FFFFFF;
          --pc-text: #2C3E50;
          --pc-text-secondary: #8492A6;
          --pc-text-muted: #B0BEC5;
          --pc-border: #E4E7ED;
          --pc-border-light: #F0F2F5;
          --pc-shadow-sm: 0 2px 8px rgba(91,141,239,0.08);
          --pc-shadow-md: 0 4px 16px rgba(91,141,239,0.12);
          --pc-shadow-lg: 0 8px 32px rgba(91,141,239,0.16);
          --pc-radius-sm: 8px;
          --pc-radius-md: 12px;
          --pc-radius-lg: 16px;
          --pc-radius-xl: 20px;
          --pc-transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .pc-container {
          padding: 0;
          min-height: calc(100vh - 60px);
          background: var(--pc-bg);
        }

        .pc-header {
          background: linear-gradient(135deg, var(--pc-primary) 0%, var(--pc-primary-dark) 100%);
          padding: 24px 32px;
          color: #fff;
          position: relative;
          overflow: hidden;
        }

        .pc-header::before {
          content: '';
          position: absolute;
          top: -50%;
          right: -10%;
          width: 300px;
          height: 300px;
          background: rgba(255,255,255,0.06);
          border-radius: 50%;
        }

        .pc-header::after {
          content: '';
          position: absolute;
          bottom: -30%;
          right: 15%;
          width: 200px;
          height: 200px;
          background: rgba(255,255,255,0.04);
          border-radius: 50%;
        }

        .pc-header-content {
          position: relative;
          z-index: 1;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .pc-header-left h1 {
          font-size: 26px;
          font-weight: 700;
          margin: 0 0 4px 0;
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .pc-header-left p {
          margin: 0;
          font-size: 13px;
          opacity: 0.85;
          font-weight: 400;
        }

        .pc-body {
          padding: 20px 24px;
        }

        .pc-tabs {
          display: flex;
          background: var(--pc-card);
          border-radius: var(--pc-radius-lg);
          padding: 4px;
          margin-bottom: 20px;
          box-shadow: var(--pc-shadow-sm);
          gap: 2px;
          overflow-x: auto;
        }

        .pc-tab {
          flex: 1;
          padding: 12px 16px;
          border: none;
          background: transparent;
          border-radius: var(--pc-radius-md);
          cursor: pointer;
          font-size: 14px;
          font-weight: 500;
          color: var(--pc-text-secondary);
          transition: var(--pc-transition);
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          white-space: nowrap;
          position: relative;
        }

        .pc-tab:hover {
          color: var(--pc-primary);
          background: var(--pc-primary-lighter);
        }

        .pc-tab.active {
          background: var(--pc-primary);
          color: #fff;
          box-shadow: 0 2px 8px rgba(91,141,239,0.3);
        }

        .pc-tab .badge-count {
          background: var(--pc-danger);
          color: #fff;
          font-size: 11px;
          padding: 1px 6px;
          border-radius: 10px;
          font-weight: 600;
          min-width: 18px;
          text-align: center;
        }

        .pc-tab.active .badge-count {
          background: rgba(255,255,255,0.3);
        }

        .pc-panel {
          display: none;
          animation: pcFadeIn 0.3s ease;
        }

        .pc-panel.active { display: block; }

        @keyframes pcFadeIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }

        .pc-card {
          background: var(--pc-card);
          border-radius: var(--pc-radius-lg);
          box-shadow: var(--pc-shadow-sm);
          margin-bottom: 16px;
          transition: var(--pc-transition);
          border: 1px solid var(--pc-border-light);
        }

        .pc-card:hover {
          box-shadow: var(--pc-shadow-md);
        }

        .pc-card-header {
          padding: 16px 20px;
          border-bottom: 1px solid var(--pc-border-light);
          display: flex;
          justify-content: space-between;
          align-items: center;
          flex-wrap: wrap;
          gap: 12px;
        }

        .pc-card-title {
          font-size: 16px;
          font-weight: 600;
          color: var(--pc-text);
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .pc-card-body { padding: 20px; }

        .pc-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 8px 16px;
          border: none;
          border-radius: var(--pc-radius-sm);
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
          transition: var(--pc-transition);
          white-space: nowrap;
        }

        .pc-btn:hover { transform: translateY(-1px); }
        .pc-btn:active { transform: translateY(0); }

        .pc-btn-primary {
          background: var(--pc-primary);
          color: #fff;
          box-shadow: 0 2px 8px rgba(91,141,239,0.3);
        }

        .pc-btn-primary:hover {
          background: var(--pc-primary-dark);
          box-shadow: 0 4px 12px rgba(91,141,239,0.4);
        }

        .pc-btn-success { background: var(--pc-success); color: #fff; }
        .pc-btn-success:hover { background: #24b362; }
        .pc-btn-warning { background: var(--pc-warning); color: #fff; }
        .pc-btn-warning:hover { background: #e88e2e; }
        .pc-btn-danger { background: var(--pc-danger); color: #fff; }
        .pc-btn-danger:hover { background: #d44042; }

        .pc-btn-outline {
          background: transparent;
          color: var(--pc-text-secondary);
          border: 1px solid var(--pc-border);
        }

        .pc-btn-outline:hover {
          color: var(--pc-primary);
          border-color: var(--pc-primary);
          background: var(--pc-primary-lighter);
        }

        .pc-btn-sm { padding: 5px 10px; font-size: 12px; }
        .pc-btn-lg { padding: 10px 24px; font-size: 14px; }

        .pc-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
          transform: none !important;
        }

        .pc-btn-detail {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 8px 16px;
          border: 1px solid var(--pc-primary);
          border-radius: var(--pc-radius-md);
          font-size: 14px;
          font-weight: 500;
          color: var(--pc-primary);
          background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
          cursor: pointer;
          transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
          white-space: nowrap;
          box-shadow: 0 1px 3px rgba(91,141,239,0.1);
        }

        .pc-btn-detail:hover {
          background: linear-gradient(135deg, var(--pc-primary) 0%, var(--pc-primary-dark) 100%);
          color: #fff;
          border-color: var(--pc-primary-dark);
          box-shadow: 0 4px 12px rgba(91,141,239,0.3);
          transform: translateY(-1px);
        }

        .pc-btn-detail:disabled {
          background: #f1f5f9;
          color: #94a3b8;
          border-color: #e2e8f0;
          cursor: not-allowed;
          box-shadow: none;
          transform: none;
        }

        .pc-form-group { margin-bottom: 14px; }

        .pc-form-label {
          display: block;
          font-size: 12px;
          font-weight: 600;
          color: var(--pc-text-secondary);
          margin-bottom: 5px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }

        .pc-form-input {
          width: 100%;
          padding: 9px 12px;
          border: 1px solid var(--pc-border);
          border-radius: var(--pc-radius-sm);
          font-size: 13px;
          color: var(--pc-text);
          background: #fff;
          transition: var(--pc-transition);
        }

        .pc-form-input:focus {
          outline: none;
          border-color: var(--pc-primary);
          box-shadow: 0 0 0 3px rgba(91,141,239,0.15);
        }

        .pc-form-input::placeholder { color: var(--pc-text-muted); }

        .pc-grid { display: grid; gap: 16px; }
        .pc-grid-2 { grid-template-columns: 1fr 1fr; }
        .pc-grid-3 { grid-template-columns: 1fr 1fr 1fr; }
        .pc-grid-4 { grid-template-columns: 1fr 1fr 1fr 1fr; }

        @media (max-width: 1200px) { .pc-grid-4 { grid-template-columns: 1fr 1fr; } }
        @media (max-width: 768px) { .pc-grid-2, .pc-grid-3, .pc-grid-4 { grid-template-columns: 1fr; } }

        .pc-search-input-wrapper {
          position: relative;
          flex: 1;
        }

        .pc-badge {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 3px 10px;
          border-radius: 20px;
          font-size: 12px;
          font-weight: 500;
        }

        .pc-badge-pending { background: var(--pc-warning-light); color: #D4830A; }
        .pc-badge-completed { background: var(--pc-success-light); color: #1E9E55; }
        .pc-badge-cancelled { background: var(--pc-danger-light); color: #C93839; }
        .pc-badge-unprocessed { background: var(--pc-info-light); color: #00A5BF; }
        .pc-badge-processing { background: var(--pc-primary-lighter); color: var(--pc-primary-dark); }

        .pc-filter-bar {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          align-items: flex-end;
          padding: 16px 20px;
          background: var(--pc-bg);
          border-radius: var(--pc-radius-md);
          margin-bottom: 16px;
        }

        .pc-empty-state {
          text-align: center;
          padding: 48px 20px;
          color: var(--pc-text-muted);
        }

        .pc-empty-state p { font-size: 14px; margin: 0; }

        .pc-pagination {
          display: flex;
          justify-content: center;
          align-items: center;
          gap: 4px;
          padding: 16px 0;
        }

        .pc-modal-overlay {
          position: fixed;
          top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0,0,0,0.5);
          backdrop-filter: blur(4px);
          z-index: 9999;
          display: none;
          justify-content: center;
          align-items: center;
          animation: pcModalFadeIn 0.2s ease;
        }

        .pc-modal-overlay.show { display: flex; }

        @keyframes pcModalFadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        .pc-modal {
          background: var(--pc-card);
          border-radius: var(--pc-radius-xl);
          box-shadow: var(--pc-shadow-lg);
          width: 95%;
          max-width: 1400px;
          max-height: 90vh;
          overflow: hidden;
          display: flex;
          flex-direction: column;
          animation: pcModalSlideIn 0.3s ease;
        }

        @keyframes pcModalSlideIn {
          from { transform: translateY(20px) scale(0.95); opacity: 0; }
          to { transform: translateY(0) scale(1); opacity: 1; }
        }

        .pc-modal-header {
          padding: 20px 24px;
          border-bottom: 1px solid var(--pc-border-light);
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .pc-modal-header h3 {
          font-size: 18px;
          font-weight: 600;
          margin: 0;
          color: var(--pc-text);
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .pc-modal-close {
          width: 32px;
          height: 32px;
          border: none;
          background: var(--pc-bg);
          border-radius: 50%;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--pc-text-secondary);
          transition: var(--pc-transition);
        }

        .pc-modal-close:hover {
          background: var(--pc-danger-light);
          color: var(--pc-danger);
        }

        .pc-modal-body {
          padding: 24px;
          overflow-y: auto;
          flex: 1;
        }

        .pc-modal-footer {
          padding: 16px 24px;
          border-top: 1px solid var(--pc-border-light);
          display: flex;
          justify-content: flex-end;
          gap: 8px;
        }

        .pc-confirm-icon {
          width: 56px;
          height: 56px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          margin: 0 auto 16px;
          font-size: 24px;
        }

        .pc-confirm-icon.danger { background: var(--pc-danger-light); color: var(--pc-danger); }
        .pc-confirm-icon.warning { background: var(--pc-warning-light); color: var(--pc-warning); }

        .pc-confirm-text {
          text-align: center;
          font-size: 15px;
          color: var(--pc-text);
          margin-bottom: 8px;
        }

        .pc-confirm-sub {
          text-align: center;
          font-size: 13px;
          color: var(--pc-text-secondary);
        }

        .pc-unprocessed-card {
          border: 1px solid var(--pc-border);
          border-radius: var(--pc-radius-md);
          padding: 14px;
          margin-bottom: 10px;
          transition: var(--pc-transition);
          border-left: 4px solid var(--pc-info);
          cursor: pointer;
        }

        .pc-unprocessed-card:hover {
          box-shadow: var(--pc-shadow-sm);
          border-left-color: var(--pc-primary);
        }

        .pc-unprocessed-card.selected {
          background: rgba(91,141,239,0.08);
          border-left-color: var(--pc-primary);
          border-color: var(--pc-primary-light);
          box-shadow: 0 2px 8px rgba(91,141,239,0.15);
        }

        .pc-unprocessed-card .card-top {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 8px;
        }

        .pc-unprocessed-card .order-no {
          font-weight: 600;
          font-size: 14px;
          color: var(--pc-text);
        }

        .pc-unprocessed-card .order-meta {
          display: flex;
          gap: 16px;
          font-size: 12px;
          color: var(--pc-text-secondary);
          margin-bottom: 8px;
        }

        .pc-unprocessed-card .order-meta span {
          display: flex;
          align-items: center;
          gap: 4px;
        }

        .pc-unprocessed-card .card-actions {
          display: flex;
          gap: 6px;
          justify-content: flex-end;
        }

        .pc-order-card {
          border: 1px solid var(--pc-border);
          border-radius: var(--pc-radius-md);
          margin-bottom: 12px;
          transition: var(--pc-transition);
          overflow: hidden;
        }

        .pc-order-card:hover {
          box-shadow: var(--pc-shadow-sm);
        }

        .pc-order-card-header {
          padding: 12px 16px;
          background: var(--pc-bg);
          display: flex;
          justify-content: space-between;
          align-items: center;
          cursor: pointer;
        }

        .pc-order-card-header:hover {
          background: var(--pc-primary-lighter);
        }

        .pc-order-card-body {
          padding: 0 16px 16px;
        }

        .pc-items-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 13px;
        }

        .pc-items-table th {
          background: var(--pc-bg);
          padding: 10px 12px;
          text-align: left;
          font-weight: 700;
          color: var(--pc-text-secondary);
          border-bottom: 2px solid var(--pc-border);
        }

        .pc-items-table td {
          padding: 12px;
          border-bottom: 1px solid var(--pc-border-light);
        }

        .pc-items-table tr:last-child td {
          border-bottom: none;
        }

        .pc-loading {
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 40px;
          color: var(--pc-text-muted);
          gap: 8px;
        }

        .pc-loading .spinner {
          width: 20px;
          height: 20px;
          border: 2px solid var(--pc-border);
          border-top-color: var(--pc-primary);
          border-radius: 50%;
          animation: pcSpin 0.8s linear infinite;
        }

        @keyframes pcSpin {
          to { transform: rotate(360deg); }
        }

        .pc-section-divider {
          height: 1px;
          background: linear-gradient(90deg, transparent 0%, var(--pc-primary-light) 20%, var(--pc-primary) 50%, var(--pc-primary-light) 80%, transparent 100%);
          margin: 8px 0;
          opacity: 0.5;
        }

        .pc-pending-section {
          border-left: 4px solid var(--pc-info);
        }

        .pc-pending-section .pc-card-header {
          background: linear-gradient(135deg, rgba(0,207,232,0.05) 0%, rgba(91,141,239,0.05) 100%);
        }

        .pc-quick-filter-btn {
          padding: 6px 14px;
          border: 1px solid var(--pc-border);
          background: #fff;
          border-radius: var(--pc-radius-sm);
          font-size: 12px;
          cursor: pointer;
          transition: var(--pc-transition);
          color: var(--pc-text-secondary);
        }

        .pc-quick-filter-btn:hover {
          border-color: var(--pc-primary);
          color: var(--pc-primary);
          background: var(--pc-primary-lighter);
        }

        .pc-quick-filter-btn.active {
          background: var(--pc-primary);
          color: #fff;
          border-color: var(--pc-primary);
        }

        .autocomplete-dropdown {
          position: absolute;
          top: 100%;
          left: 0;
          right: 0;
          background: #fff;
          border: 1px solid var(--pc-border);
          border-top: none;
          border-radius: 0 0 var(--pc-radius-sm) var(--pc-radius-sm);
          box-shadow: var(--pc-shadow-md);
          z-index: 1000;
          max-height: 200px;
          overflow-y: auto;
        }

        .autocomplete-item {
          padding: 8px 12px;
          cursor: pointer;
          font-size: 13px;
          color: var(--pc-text);
          transition: var(--pc-transition);
        }

        .autocomplete-item:hover {
          background: var(--pc-bg);
        }

        @media (max-width: 991.98px) {
          .pc-container { padding: 12px; }
          .pc-header h1 { font-size: 1.25rem; }
          .pc-card-header { flex-wrap: wrap; gap: 8px; }
          .pc-card-header > div:last-child { width: 100%; justify-content: flex-start; }
          .pc-card-body { overflow-x: auto; }
          .pc-card-body table { min-width: 600px; }
        }

        @media (max-width: 575.98px) {
          .pc-container { padding: 8px; }
          .pc-header-content { flex-direction: column; gap: 8px; }
          .pc-tabs { overflow-x: auto; -webkit-overflow-scrolling: touch; flex-wrap: nowrap; }
          .pc-tab { white-space: nowrap; font-size: 13px; padding: 8px 12px; }
          .pc-card-header { padding: 10px 12px; }
          .pc-btn { font-size: 12px; padding: 6px 10px; }
          .pc-grid { grid-template-columns: 1fr; }
          .pc-card-body table { font-size: 12px; }
          .pc-card-body table th, .pc-card-body table td { padding: 6px 8px; }
        }

        @media print {
          .pc-header, .pc-tabs, .pc-filter-bar, .pc-btn, .pc-pagination { display: none !important; }
          .pc-container { padding: 0; background: #fff; }
          .pc-card { box-shadow: none; border: 1px solid #ddd; }
        }
      `}</style>
    </div>
  );
}
