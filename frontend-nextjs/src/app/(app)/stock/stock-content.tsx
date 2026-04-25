"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post, put, del } from "@/lib/api-client";
import { useState, useEffect, useRef, useCallback } from "react";
import {
  PackagePlusIcon,
  TruckIcon,
  ClipboardCheckIcon,
  SearchIcon,
  PlusIcon,
  PencilIcon,
  Trash2Icon,
  Loader2Icon,
  XIcon,
  ChevronDownIcon,
  FileSpreadsheetIcon,
  DownloadIcon,
  UploadIcon,
  FileImageIcon,
  EyeIcon,
  BuildingIcon,
  PackageIcon,
  RefreshCwIcon,
  AlertTriangleIcon,
  CheckCircleIcon,
  XCircleIcon,
} from "lucide-react";
import { toast } from "sonner";

// ============ Types ============

export interface StockInRecord {
  id: number;
  stockin_no: string;
  product_name: string;
  product_id: number;
  barcode?: string;
  quantity: number;
  deducted?: number;
  customer: string;
  stockin_date: string;
  status: string;
  note?: string;
}

interface StockOutRecord {
  id: number;
  stockout_no: string;
  product_name: string;
  product_id: number;
  barcode?: string;
  quantity: number;
  deducted?: number;
  customer: string;
  stockout_date: string;
  status: string;
  note?: string;
  order_type?: string;
  country?: string;
}

interface InventoryItem {
  customer: string;
  product_name: string;
  order_quantity: number;
  stockin_quantity: number;
  total_stock: number;
}

interface StagedItem {
  id: number;
  tempId?: number;
  stockinNo?: string;
  stockoutNo?: string;
  stockinDate?: string;
  stockoutDate?: string;
  customer: string;
  productId: number;
  productName: string;
  quantity: number;
  note: string;
  isValidated?: boolean;
  validationError?: string;
  stockCheckPassed?: boolean;
  stockCheckMessage?: string;
}

export interface PageResult<T> { data: T[]; total: number; success: boolean }

// ============ Component ============

interface StockContentProps {
  initialStockins?: PageResult<StockInRecord>;
  initialCustomers?: { success: boolean; data: { id: number; name: string }[] };
}

export function StockContent({ initialStockins, initialCustomers }: StockContentProps) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"in" | "out" | "inventory">("in");

  // Stock-in state
  const [siPage, setSiPage] = useState(1);
  const [siStaged, setSiStaged] = useState<StagedItem[]>([]);
  const [siServerMode, setSiServerMode] = useState(false);
  const [siForm, setSiForm] = useState({ customer: "", productId: 0, productName: "", quantity: 1, stockinDate: new Date().toISOString().slice(0, 10), note: "" });
  const [siProductSearch, setSiProductSearch] = useState("");
  const [siProductResults, setSiProductResults] = useState<{ id: number; name: string; barcode: string }[]>([]);
  const [siShowAutocomplete, setSiShowAutocomplete] = useState(false);
  const [siEditStagedIdx, setSiEditStagedIdx] = useState(-1);
  const [siEditForm, setSiEditForm] = useState({ customer: "", quantity: 1, stockinDate: "", note: "" });

  // Stock-out state
  const [soPage, setSoPage] = useState(1);
  const [soStaged, setSoStaged] = useState<StagedItem[]>([]);
  const [soServerMode, setSoServerMode] = useState(false);
  const [soForm, setSoForm] = useState({ customer: "", productId: 0, productName: "", quantity: 1, stockoutDate: new Date().toISOString().slice(0, 10), note: "" });
  const [soProductSearch, setSoProductSearch] = useState("");
  const [soProductResults, setSoProductResults] = useState<{ id: number; name: string; barcode: string }[]>([]);
  const [soShowAutocomplete, setSoShowAutocomplete] = useState(false);
  const [soAvailableShipment, setSoAvailableShipment] = useState<{ order_quantity: number; shipped_quantity: number; available_quantity: number } | null>(null);
  const [soEditStagedIdx, setSoEditStagedIdx] = useState(-1);
  const [soEditForm, setSoEditForm] = useState({ customer: "", quantity: 1, stockoutDate: "", note: "" });

  // Inventory state
  const [invCustomer, setInvCustomer] = useState("");
  const [invProduct, setInvProduct] = useState("");

  // Batch import state
  const [siBatchOpen, setSiBatchOpen] = useState(false);
  const [soBatchOpen, setSoBatchOpen] = useState(false);

  // Record list expanded groups
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  const perPage = 50;

  // ============ Queries ============

  const { data: siData, isLoading: siLoading } = useQuery({
    queryKey: ["stockins", siPage],
    queryFn: () => get<PageResult<StockInRecord>>("/stock/in/list", { page: String(siPage), per_page: String(perPage) }),
    enabled: tab === "in",
    initialData: initialStockins && siPage === 1 ? initialStockins : undefined,
  });

  const { data: soData, isLoading: soLoading } = useQuery({
    queryKey: ["stockouts", soPage],
    queryFn: () => get<PageResult<StockOutRecord>>("/stock/out/list", { page: String(soPage), per_page: String(perPage) }),
    enabled: tab === "out",
  });

  const { data: invData, isLoading: invLoading } = useQuery({
    queryKey: ["inventory", invCustomer, invProduct],
    queryFn: () => get<{ success: boolean; data: InventoryItem[]; total_order_qty: number; total_stockin_qty: number; total_total_qty: number }>("/stock/inventory", {
      ...(invCustomer ? { customer: invCustomer } : {}),
      ...(invProduct ? { product: invProduct } : {}),
    }),
    enabled: tab === "inventory",
  });

  const { data: customersData } = useQuery({
    queryKey: ["customers-list"],
    queryFn: () => get<{ success: boolean; data: { id: number; name: string }[] }>("/customers/list"),
    initialData: initialCustomers,
  });

  // Load staging data on mount
  useEffect(() => {
    if (tab === "in") {
      get<{ success: boolean; data: any[] }>("/staging-stockins").then((res) => {
        if (res.success && res.data && res.data.length > 0) {
          setSiServerMode(true);
          setSiStaged(res.data.map((item: any) => ({
            id: item.id, tempId: item.id,
            stockinNo: item.stockin_no, stockinDate: item.stockin_date,
            customer: item.customer, productId: item.product_id,
            productName: item.product_name, quantity: item.quantity,
            note: item.note || "", isValidated: true, stockCheckPassed: true,
          })));
        }
      }).catch(() => {});
    }
  }, [tab]);

  useEffect(() => {
    if (tab === "out") {
      const sid = `stg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      get<{ success: boolean; data: any[] }>("/staging-stockouts", { session_id: sid }).then((res) => {
        if (res.success && res.data && res.data.length > 0) {
          setSoServerMode(true);
          setSoStaged(res.data.map((item: any) => ({
            id: item.id, tempId: item.id,
            stockoutNo: item.stockout_no, stockoutDate: item.stockout_date,
            customer: item.customer, productId: item.product_id,
            productName: item.product_name, quantity: item.quantity,
            note: item.note || "", isValidated: true, stockCheckPassed: item.stock_check_passed !== false,
          })));
        }
      }).catch(() => {});
    }
  }, [tab]);

  // ============ Product Search ============

  const siSearchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const soSearchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (siProductSearch.length > 0) {
      if (siSearchTimer.current) clearTimeout(siSearchTimer.current);
      siSearchTimer.current = setTimeout(async () => {
        try {
          const res = await get<{ id: number; name: string; barcode: string }[]>("/aux/product-search", { q: siProductSearch });
          setSiProductResults(Array.isArray(res) ? res : []);
          setSiShowAutocomplete(true);
        } catch { /* ignore */ }
      }, 300);
    } else {
      setSiProductResults([]);
      setSiShowAutocomplete(false);
    }
  }, [siProductSearch]);

  useEffect(() => {
    if (soProductSearch.length > 0) {
      if (soSearchTimer.current) clearTimeout(soSearchTimer.current);
      soSearchTimer.current = setTimeout(async () => {
        try {
          const res = await get<{ id: number; name: string; barcode: string }[]>("/aux/product-search", { q: soProductSearch });
          setSoProductResults(Array.isArray(res) ? res : []);
          setSoShowAutocomplete(true);
        } catch { /* ignore */ }
      }, 300);
    } else {
      setSoProductResults([]);
      setSoShowAutocomplete(false);
    }
  }, [soProductSearch]);

  // Available shipment check for stockout
  useEffect(() => {
    if (soForm.productId && soForm.customer) {
      get<{ order_quantity: number; shipped_quantity: number; available_quantity: number }>("/aux/available-shipment", {
        product_id: String(soForm.productId), customer: soForm.customer,
      }).then(setSoAvailableShipment).catch(() => setSoAvailableShipment(null));
    } else {
      setSoAvailableShipment(null);
    }
  }, [soForm.productId, soForm.customer]);

  // ============ Mutations ============

  const submitSiMutation = useMutation({
    mutationFn: async () => {
      if (siServerMode) {
        return post<{ success: boolean; message?: string }>("/staging-stockins/confirm", {});
      } else {
        const stockins = siStaged.filter((s) => s.isValidated !== false).map((s) => ({
          product_id: s.productId, customer: s.customer, quantity: s.quantity,
          stockin_date: s.stockinDate, note: s.note,
        }));
        return post<{ success: boolean; message?: string }>("/aux/batch-submit-stockins", { stockins });
      }
    },
    onSuccess: (res) => { toast.success(res.message || "备货提交成功"); setSiStaged([]); setSiServerMode(false); queryClient.invalidateQueries({ queryKey: ["stockins"] }); },
    onError: () => toast.error("备货提交失败"),
  });

  const submitSoMutation = useMutation({
    mutationFn: async () => {
      if (soServerMode) {
        return post<{ success: boolean; message?: string }>("/staging-stockouts/confirm", {});
      } else {
        const stockouts = soStaged.filter((s) => s.isValidated !== false && s.stockCheckPassed !== false).map((s) => ({
          product_id: s.productId, customer: s.customer, quantity: s.quantity,
          stockout_date: s.stockoutDate, note: s.note,
        }));
        return post<{ success: boolean; message?: string }>("/aux/batch-submit-stockouts", { stockouts });
      }
    },
    onSuccess: (res) => { toast.success(res.message || "出货提交成功"); setSoStaged([]); setSoServerMode(false); queryClient.invalidateQueries({ queryKey: ["stockouts"] }); },
    onError: () => toast.error("出货提交失败"),
  });

  const deleteSiMutation = useMutation({
    mutationFn: (id: number) => del<{ success: boolean }>(`/stock/in/delete/${id}`),
    onSuccess: () => { toast.success("删除成功"); queryClient.invalidateQueries({ queryKey: ["stockins"] }); },
    onError: () => toast.error("删除失败"),
  });

  const deleteSoMutation = useMutation({
    mutationFn: (id: number) => del<{ success: boolean }>(`/stock/out/delete/${id}`),
    onSuccess: () => { toast.success("删除成功"); queryClient.invalidateQueries({ queryKey: ["stockouts"] }); },
    onError: () => toast.error("删除失败"),
  });

  // ============ Handlers ============

  function addSiStaged() {
    if (!siForm.customer || !siForm.productId || !siForm.quantity || !siForm.stockinDate) { toast.error("请填写所有必填项"); return; }
    setSiStaged((prev) => [...prev, {
      id: Date.now(), customer: siForm.customer, productId: siForm.productId,
      productName: siForm.productName, quantity: siForm.quantity,
      stockinDate: siForm.stockinDate, note: siForm.note, isValidated: true,
    }]);
    setSiForm({ customer: siForm.customer, productId: 0, productName: "", quantity: 1, stockinDate: siForm.stockinDate, note: "" });
    setSiProductSearch(""); setSiShowAutocomplete(false);
  }

  function addSoStaged() {
    if (!soForm.customer || !soForm.productId || !soForm.quantity || !soForm.stockoutDate) { toast.error("请填写所有必填项"); return; }
    if (soAvailableShipment && soForm.quantity > soAvailableShipment.available_quantity) {
      toast.warning(`出货数量超出可用库存 (${soAvailableShipment.available_quantity})`);
    }
    setSoStaged((prev) => [...prev, {
      id: Date.now(), customer: soForm.customer, productId: soForm.productId,
      productName: soForm.productName, quantity: soForm.quantity,
      stockoutDate: soForm.stockoutDate, note: soForm.note,
      isValidated: true, stockCheckPassed: soAvailableShipment ? soForm.quantity <= soAvailableShipment.available_quantity : true,
    }]);
    setSoForm({ customer: soForm.customer, productId: 0, productName: "", quantity: 1, stockoutDate: soForm.stockoutDate, note: "" });
    setSoProductSearch(""); setSoShowAutocomplete(false); setSoAvailableShipment(null);
  }

  function removeSiStaged(idx: number) {
    const item = siStaged[idx];
    if (siServerMode && item.tempId) { del(`/staging-stockins/${item.tempId}`).catch(() => {}); }
    setSiStaged((prev) => prev.filter((_, i) => i !== idx));
  }

  function removeSoStaged(idx: number) {
    const item = soStaged[idx];
    if (soServerMode && item.tempId) { del(`/staging-stockouts/${item.tempId}`).catch(() => {}); }
    setSoStaged((prev) => prev.filter((_, i) => i !== idx));
  }

  function toggleGroup(key: string) {
    setExpandedGroups((prev) => { const next = new Set(prev); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  }

  function groupByDate<T extends { stockin_date?: string; stockout_date?: string }>(items: T[]): [string, T[]][] {
    const groups: Record<string, T[]> = {};
    items.forEach((item) => {
      const date = item.stockin_date || item.stockout_date || "未知日期";
      if (!groups[date]) groups[date] = [];
      groups[date].push(item);
    });
    return Object.entries(groups).sort(([a], [b]) => b.localeCompare(a));
  }

  // ============ Derived data ============

  const siItems = siData?.data ?? [];
  const siTotal = siData?.total ?? 0;
  const soItems = soData?.data ?? [];
  const soTotal = soData?.total ?? 0;
  const invItems = invData?.data ?? [];
  const customers = customersData?.data ?? [];

  // ============ Render ============

  return (
    <div className="stk-container">
      {/* Page Title */}
      <h2 className="stk-page-title">
        {tab === "in" ? "备货管理" : tab === "out" ? "出货管理" : "库存查询"}
      </h2>

      {/* Tabs */}
      <ul className="nav nav-tabs mb-3">
        <li className="nav-item">
          <button className={`nav-link ${tab === "in" ? "active" : ""}`} onClick={() => setTab("in")}>
            <PackagePlusIcon style={{ width: 16, height: 16, marginRight: 6, verticalAlign: "text-bottom" }} />备货管理
          </button>
        </li>
        <li className="nav-item">
          <button className={`nav-link ${tab === "out" ? "active" : ""}`} onClick={() => setTab("out")}>
            <TruckIcon style={{ width: 16, height: 16, marginRight: 6, verticalAlign: "text-bottom" }} />出货管理
          </button>
        </li>
        <li className="nav-item">
          <button className={`nav-link ${tab === "inventory" ? "active" : ""}`} onClick={() => setTab("inventory")}>
            <ClipboardCheckIcon style={{ width: 16, height: 16, marginRight: 6, verticalAlign: "text-bottom" }} />库存查询
          </button>
        </li>
      </ul>

      {/* ===== Stock-In Tab ===== */}
      {tab === "in" && (
        <>
          <div className="row">
            {/* Left: Form */}
            <div className="col-lg-6">
              <div className="card mt-3">
                <div className="card-header d-flex justify-content-between align-items-center">
                  <span>备货信息录入</span>
                  {siStaged.length > 0 && <span className="badge bg-light text-dark">已暂存: {siStaged.length}</span>}
                </div>
                <div className="card-body">
                  <form onSubmit={(e) => { e.preventDefault(); addSiStaged(); }}>
                    <div className="row mb-3">
                      <div className="col-md-6">
                        <label className="form-label">客户名称</label>
                        <select className="form-select" value={siForm.customer} onChange={(e) => setSiForm({ ...siForm, customer: e.target.value })}>
                          <option value="">请选择客户</option>
                          {customers.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
                        </select>
                      </div>
                      <div className="col-md-6">
                        <label className="form-label">备货时间</label>
                        <input type="date" className="form-control" value={siForm.stockinDate} onChange={(e) => setSiForm({ ...siForm, stockinDate: e.target.value })} />
                      </div>
                    </div>
                    <div className="mb-3 stk-autocomplete-wrapper">
                      <label className="form-label">产品名称</label>
                      <input type="text" className="form-control" placeholder="输入产品名称或69码搜索" value={siProductSearch}
                        onChange={(e) => { setSiProductSearch(e.target.value); setSiForm({ ...siForm, productName: e.target.value, productId: 0 }); }}
                        onFocus={() => siProductResults.length > 0 && setSiShowAutocomplete(true)}
                        onBlur={() => setTimeout(() => setSiShowAutocomplete(false), 200)}
                        autoComplete="off" required />
                      {siShowAutocomplete && siProductResults.length > 0 && (
                        <div className="stk-autocomplete-dropdown">
                          {siProductResults.map((p) => (
                            <div key={p.id} className="stk-autocomplete-item" onMouseDown={() => {
                              setSiForm({ ...siForm, productId: p.id, productName: p.name });
                              setSiProductSearch(p.name); setSiShowAutocomplete(false);
                            }}>
                              <span className="stk-product-name">{p.name}</span>
                              <span className="stk-product-barcode">{p.barcode || ""}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="row mb-3">
                      <div className="col-md-6">
                        <label className="form-label">备货数量</label>
                        <input type="number" className="form-control" value={siForm.quantity || ""} onChange={(e) => setSiForm({ ...siForm, quantity: Number(e.target.value) })} min={1} required />
                      </div>
                    </div>
                    <div className="mb-3">
                      <label className="form-label">备注</label>
                      <textarea className="form-control" rows={2} placeholder="例如：批量备货" value={siForm.note} onChange={(e) => setSiForm({ ...siForm, note: e.target.value })} />
                    </div>
                    <button type="submit" className="btn btn-secondary" disabled={!siForm.customer || !siForm.productId || !siForm.quantity || !siForm.stockinDate}>
                      <PlusIcon style={{ width: 14, height: 14, marginRight: 4, verticalAlign: "text-bottom" }} />新增备货
                    </button>
                  </form>
                </div>
              </div>
            </div>

            {/* Right: Staging list + Batch import */}
            <div className="col-lg-6">
              <div className="card mt-3">
                <div className="card-header d-flex justify-content-between align-items-center">
                  <span>暂存备货列表</span>
                  <span>共 {siStaged.length} 个</span>
                </div>
                <div className="card-body">
                  <div style={{ maxHeight: 400, overflowY: "auto" }}>
                    {siStaged.length === 0 ? (
                      <div className="text-center text-muted py-4">
                        <PackageIcon style={{ width: 48, height: 48, opacity: 0.3, marginBottom: 12 }} />
                        <p>暂无暂存备货</p>
                      </div>
                    ) : (
                      siStaged.map((item, idx) => (
                        <div key={item.id || idx} className="stk-staged-item">
                          <div className="stk-staged-info">
                            <div className="stk-staged-name">{item.productName}</div>
                            <div className="stk-staged-meta">
                              客户: {item.customer} | 数量: {item.quantity} | 日期: {item.stockinDate}
                            </div>
                            {item.note && <div className="stk-staged-note">{item.note}</div>}
                          </div>
                          <div className="stk-staged-actions">
                            <button className="btn btn-sm btn-outline-primary" onClick={() => { setSiEditStagedIdx(idx); setSiEditForm({ customer: item.customer, quantity: item.quantity, stockinDate: item.stockinDate || "", note: item.note }); }}>
                              <PencilIcon style={{ width: 12, height: 12 }} />
                            </button>
                            <button className="btn btn-sm btn-outline-danger" onClick={() => removeSiStaged(idx)}>
                              <Trash2Icon style={{ width: 12, height: 12 }} />
                            </button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>

              {/* Batch import */}
              <div className="card mt-3">
                <div className="card-header d-flex justify-content-between align-items-center stk-collapse-trigger" style={{ cursor: "pointer" }} onClick={() => setSiBatchOpen(!siBatchOpen)}>
                  <h6 className="mb-0 fw-bold">批量导入备货</h6>
                  <ChevronDownIcon style={{ width: 16, height: 16, transition: "transform 0.3s", transform: siBatchOpen ? "rotate(180deg)" : "rotate(0deg)" }} />
                </div>
                {siBatchOpen && (
                  <div className="card-body">
                    <div className="stk-upload-area" onClick={() => document.getElementById("si-excel-input")?.click()}>
                      <FileSpreadsheetIcon style={{ width: 32, height: 32, color: "#28a745", opacity: 0.8, marginBottom: 8 }} />
                      <p className="text-muted mb-1 small">拖拽或点击选择 Excel 文件</p>
                      <p style={{ fontSize: 11, color: "#adb5bd" }}>支持 .xlsx / .xls 格式</p>
                      <input type="file" id="si-excel-input" style={{ display: "none" }} accept=".xlsx,.xls"
                        onChange={async (e) => {
                          const file = e.target.files?.[0];
                          if (!file) return;
                          const formData = new FormData();
                          formData.append("file", file);
                          try {
                            const res = await post<{ success: boolean; message?: string; count?: number }>("/staging-stockins/import", formData);
                            if (res.success) { toast.success(res.message || `导入 ${res.count || 0} 条`); setSiServerMode(true); }
                            else toast.error(res.message || "导入失败");
                          } catch { toast.error("导入失败"); }
                          e.target.value = "";
                        }}
                      />
                    </div>
                    <div className="d-flex justify-content-between align-items-center mt-3">
                      <button className="btn btn-outline-secondary btn-sm" onClick={async () => {
                        try { const res = await fetch("/api/v1/batch/download-template"); const blob = await res.blob(); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "备货导入模板.xlsx"; a.click(); URL.revokeObjectURL(url); } catch { toast.error("下载模板失败"); }
                      }}>
                        <DownloadIcon style={{ width: 14, height: 14, marginRight: 8 }} />备货模板
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Submit all button */}
          {siStaged.length > 0 && (
            <div className="card mt-4">
              <div className="card-body text-center py-4">
                <button className="btn btn-primary btn-lg" style={{ minWidth: 200 }} onClick={() => submitSiMutation.mutate(undefined as any)} disabled={submitSiMutation.isPending}>
                  {submitSiMutation.isPending ? <Loader2Icon style={{ width: 16, height: 16, marginRight: 8, animation: "spin 1s linear infinite", verticalAlign: "text-bottom" }} /> : null}
                  添加备货 ({siStaged.length} 条)
                </button>
              </div>
            </div>
          )}

          {/* Record list grouped by date */}
          <div className="card mt-4">
            <div className="card-header">备货记录列表</div>
            <div className="card-body">
              {siLoading ? (
                <div className="text-center py-4"><Loader2Icon style={{ width: 32, height: 32, animation: "stkSpin 0.8s linear infinite" }} /><p className="text-muted mt-2">加载中...</p></div>
              ) : siItems.length === 0 ? (
                <div className="text-center text-muted py-4"><PackagePlusIcon style={{ width: 48, height: 48, opacity: 0.3, marginBottom: 12 }} /><p>暂无备货记录</p></div>
              ) : (
                groupByDate(siItems).map(([date, items]) => {
                  const key = `si-${date}`;
                  const isExpanded = expandedGroups.has(key);
                  return (
                    <div key={key} className="stk-date-group">
                      <div className="stk-date-header" onClick={() => toggleGroup(key)}>
                        <span>{date} ({items.length} 条)</span>
                        <ChevronDownIcon style={{ width: 16, height: 16, transition: "transform 0.3s", transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)" }} />
                      </div>
                      {isExpanded && (
                        <div className="stk-date-content">
                          <table className="table table-hover mb-0">
                            <thead><tr><th>客户</th><th>产品</th><th className="text-center">数量</th><th>备注</th><th style={{ width: 80 }}>操作</th></tr></thead>
                            <tbody>
                              {items.map((item) => (
                                <tr key={item.id}>
                                  <td><BuildingIcon style={{ width: 14, height: 14, color: "#0d6efd", marginRight: 4, verticalAlign: "text-bottom" }} />{item.customer}</td>
                                  <td><PackageIcon style={{ width: 14, height: 14, color: "#6c757d", marginRight: 8, verticalAlign: "text-bottom" }} />{item.product_name}</td>
                                  <td className="text-center fw-semibold">{item.quantity}</td>
                                  <td>{item.note || "-"}</td>
                                  <td><button className="btn btn-sm btn-outline-danger" onClick={() => { if (confirm("确定删除此记录？")) deleteSiMutation.mutate(item.id); }}><Trash2Icon style={{ width: 12, height: 12 }} /></button></td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Edit staged modal */}
          {siEditStagedIdx >= 0 && (
            <div className="stk-modal-overlay show" onClick={() => setSiEditStagedIdx(-1)}>
              <div className="stk-modal" style={{ maxWidth: 500 }} onClick={(e) => e.stopPropagation()}>
                <div className="stk-modal-header"><h5>编辑暂存备货</h5><button className="stk-modal-close" onClick={() => setSiEditStagedIdx(-1)}><XIcon style={{ width: 16, height: 16 }} /></button></div>
                <div className="stk-modal-body">
                  <div className="mb-3"><label className="form-label">客户</label><select className="form-select" value={siEditForm.customer} onChange={(e) => setSiEditForm({ ...siEditForm, customer: e.target.value })}><option value="">请选择客户</option>{customers.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}</select></div>
                  <div className="mb-3"><label className="form-label">备货时间</label><input type="date" className="form-control" value={siEditForm.stockinDate} onChange={(e) => setSiEditForm({ ...siEditForm, stockinDate: e.target.value })} /></div>
                  <div className="mb-3"><label className="form-label">数量</label><input type="number" className="form-control" value={siEditForm.quantity || ""} onChange={(e) => setSiEditForm({ ...siEditForm, quantity: Number(e.target.value) })} min={1} /></div>
                  <div className="mb-3"><label className="form-label">备注</label><input type="text" className="form-control" value={siEditForm.note} onChange={(e) => setSiEditForm({ ...siEditForm, note: e.target.value })} /></div>
                </div>
                <div className="stk-modal-footer">
                  <button className="btn btn-secondary" onClick={() => setSiEditStagedIdx(-1)}>取消</button>
                  <button className="btn btn-primary" onClick={() => {
                    setSiStaged((prev) => prev.map((item, i) => i === siEditStagedIdx ? { ...item, customer: siEditForm.customer, quantity: siEditForm.quantity, stockinDate: siEditForm.stockinDate, note: siEditForm.note } : item));
                    setSiEditStagedIdx(-1);
                  }}>保存</button>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {/* ===== Stock-Out Tab ===== */}
      {tab === "out" && (
        <>
          <div className="row">
            {/* Left: Form */}
            <div className="col-lg-6">
              <div className="card mt-3">
                <div className="card-header d-flex justify-content-between align-items-center">
                  <span>出货信息录入</span>
                  {soStaged.length > 0 && <span className="badge bg-light text-dark">已暂存：{soStaged.length}</span>}
                </div>
                <div className="card-body">
                  <form onSubmit={(e) => { e.preventDefault(); addSoStaged(); }}>
                    <div className="row mb-3">
                      <div className="col-md-6">
                        <label className="form-label">客户名称</label>
                        <select className="form-select" value={soForm.customer} onChange={(e) => setSoForm({ ...soForm, customer: e.target.value })}>
                          <option value="">请选择客户</option>
                          {customers.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
                        </select>
                      </div>
                      <div className="col-md-6">
                        <label className="form-label">出货时间</label>
                        <input type="date" className="form-control" value={soForm.stockoutDate} onChange={(e) => setSoForm({ ...soForm, stockoutDate: e.target.value })} />
                      </div>
                    </div>
                    <div className="mb-3 stk-autocomplete-wrapper">
                      <label className="form-label">产品名称</label>
                      <input type="text" className="form-control" placeholder="输入产品名称搜索" value={soProductSearch}
                        onChange={(e) => { setSoProductSearch(e.target.value); setSoForm({ ...soForm, productName: e.target.value, productId: 0 }); }}
                        onFocus={() => soProductResults.length > 0 && setSoShowAutocomplete(true)}
                        onBlur={() => setTimeout(() => setSoShowAutocomplete(false), 200)}
                        autoComplete="off" required />
                      {soShowAutocomplete && soProductResults.length > 0 && (
                        <div className="stk-autocomplete-dropdown">
                          {soProductResults.map((p) => (
                            <div key={p.id} className="stk-autocomplete-item" onMouseDown={() => {
                              setSoForm({ ...soForm, productId: p.id, productName: p.name });
                              setSoProductSearch(p.name); setSoShowAutocomplete(false);
                            }}>
                              <span className="stk-product-name">{p.name}</span>
                              <span className="stk-product-barcode">{p.barcode || ""}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="row mb-3">
                      <div className="col-md-6">
                        <label className="form-label">出货数量</label>
                        <input type="number" className="form-control" value={soForm.quantity || ""} onChange={(e) => setSoForm({ ...soForm, quantity: Number(e.target.value) })} min={1} required />
                        {soAvailableShipment && (
                          <div className="form-text mt-1">
                            可出货: <strong style={{ color: soAvailableShipment.available_quantity >= soForm.quantity ? "#28a745" : "#dc3545" }}>{soAvailableShipment.available_quantity}</strong>
                            {" "}(订单: {soAvailableShipment.order_quantity}, 已出: {soAvailableShipment.shipped_quantity})
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="mb-3">
                      <label className="form-label">备注</label>
                      <textarea className="form-control" rows={2} placeholder="例如：物流发货" value={soForm.note} onChange={(e) => setSoForm({ ...soForm, note: e.target.value })} />
                    </div>
                    <button type="submit" className="btn btn-secondary" disabled={!soForm.customer || !soForm.productId || !soForm.quantity || !soForm.stockoutDate}>
                      <PlusIcon style={{ width: 14, height: 14, marginRight: 4, verticalAlign: "text-bottom" }} />新增出货
                    </button>
                  </form>
                </div>
              </div>
            </div>

            {/* Right: Staging list + Batch import */}
            <div className="col-lg-6">
              <div className="card mt-3">
                <div className="card-header d-flex justify-content-between align-items-center">
                  <span>暂存出货列表</span>
                  <span>共 {soStaged.length} 个</span>
                </div>
                <div className="card-body">
                  <div style={{ maxHeight: 400, overflowY: "auto" }}>
                    {soStaged.length === 0 ? (
                      <div className="text-center text-muted py-4">
                        <TruckIcon style={{ width: 48, height: 48, opacity: 0.3, marginBottom: 12 }} />
                        <p>暂无暂存出货</p>
                      </div>
                    ) : (
                      soStaged.map((item, idx) => (
                        <div key={item.id || idx} className="stk-staged-item">
                          <div className="stk-staged-info">
                            <div className="stk-staged-name">
                              {item.productName}
                              {item.stockCheckPassed === false && <span className="badge bg-warning text-dark ms-2" style={{ fontSize: 10 }}>库存不足</span>}
                            </div>
                            <div className="stk-staged-meta">
                              客户: {item.customer} | 数量: {item.quantity} | 日期: {item.stockoutDate}
                            </div>
                          </div>
                          <div className="stk-staged-actions">
                            <button className="btn btn-sm btn-outline-primary" onClick={() => { setSoEditStagedIdx(idx); setSoEditForm({ customer: item.customer, quantity: item.quantity, stockoutDate: item.stockoutDate || "", note: item.note }); }}>
                              <PencilIcon style={{ width: 12, height: 12 }} />
                            </button>
                            <button className="btn btn-sm btn-outline-danger" onClick={() => removeSoStaged(idx)}>
                              <Trash2Icon style={{ width: 12, height: 12 }} />
                            </button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>

              {/* Batch import */}
              <div className="card mt-3">
                <div className="card-header d-flex justify-content-between align-items-center stk-collapse-trigger" style={{ cursor: "pointer" }} onClick={() => setSoBatchOpen(!soBatchOpen)}>
                  <h6 className="mb-0 fw-bold">批量导入出货</h6>
                  <ChevronDownIcon style={{ width: 16, height: 16, transition: "transform 0.3s", transform: soBatchOpen ? "rotate(180deg)" : "rotate(0deg)" }} />
                </div>
                {soBatchOpen && (
                  <div className="card-body">
                    <div className="stk-upload-area" onClick={() => document.getElementById("so-excel-input")?.click()}>
                      <FileSpreadsheetIcon style={{ width: 32, height: 32, color: "#28a745", opacity: 0.8, marginBottom: 8 }} />
                      <p className="text-muted mb-1 small">拖拽或点击选择 Excel 文件</p>
                      <p style={{ fontSize: 11, color: "#adb5bd" }}>支持 .xlsx / .xls 格式</p>
                      <input type="file" id="so-excel-input" style={{ display: "none" }} accept=".xlsx,.xls"
                        onChange={async (e) => {
                          const file = e.target.files?.[0];
                          if (!file) return;
                          const formData = new FormData();
                          formData.append("file", file);
                          try {
                            const res = await post<{ success: boolean; message?: string; count?: number }>("/staging-stockouts/import", formData);
                            if (res.success) { toast.success(res.message || `导入 ${res.count || 0} 条`); setSoServerMode(true); }
                            else toast.error(res.message || "导入失败");
                          } catch { toast.error("导入失败"); }
                          e.target.value = "";
                        }}
                      />
                    </div>
                    <div className="d-flex justify-content-between align-items-center mt-3">
                      <button className="btn btn-outline-secondary btn-sm" onClick={async () => {
                        try { const res = await fetch("/api/v1/batch/download-template"); const blob = await res.blob(); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "出货导入模板.xlsx"; a.click(); URL.revokeObjectURL(url); } catch { toast.error("下载模板失败"); }
                      }}>
                        <DownloadIcon style={{ width: 14, height: 14, marginRight: 8 }} />出货模板
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Submit all */}
          {soStaged.length > 0 && (
            <div className="card mt-4">
              <div className="card-body text-center py-4">
                <button className="btn btn-primary btn-lg" style={{ minWidth: 200 }} onClick={() => submitSoMutation.mutate(undefined as any)}
                  disabled={submitSoMutation.isPending || soStaged.filter((s) => s.isValidated !== false && s.stockCheckPassed !== false).length === 0}>
                  {submitSoMutation.isPending ? <Loader2Icon style={{ width: 16, height: 16, marginRight: 8, animation: "spin 1s linear infinite", verticalAlign: "text-bottom" }} /> : null}
                  添加出货 ({soStaged.filter((s) => s.isValidated !== false && s.stockCheckPassed !== false).length} 条)
                </button>
              </div>
            </div>
          )}

          {/* Record list */}
          <div className="card mt-4">
            <div className="card-header">出货记录列表</div>
            <div className="card-body">
              {soLoading ? (
                <div className="text-center py-4"><Loader2Icon style={{ width: 32, height: 32, animation: "stkSpin 0.8s linear infinite" }} /><p className="text-muted mt-2">加载中...</p></div>
              ) : soItems.length === 0 ? (
                <div className="text-center text-muted py-4"><TruckIcon style={{ width: 48, height: 48, opacity: 0.3, marginBottom: 12 }} /><p>暂无出货记录</p></div>
              ) : (
                groupByDate(soItems).map(([date, items]) => {
                  const key = `so-${date}`;
                  const isExpanded = expandedGroups.has(key);
                  return (
                    <div key={key} className="stk-date-group">
                      <div className="stk-date-header" onClick={() => toggleGroup(key)}>
                        <span>{date} ({items.length} 条)</span>
                        <ChevronDownIcon style={{ width: 16, height: 16, transition: "transform 0.3s", transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)" }} />
                      </div>
                      {isExpanded && (
                        <div className="stk-date-content">
                          <table className="table table-hover mb-0">
                            <thead><tr><th>客户</th><th>产品</th><th className="text-center">数量</th><th>备注</th><th style={{ width: 80 }}>操作</th></tr></thead>
                            <tbody>
                              {items.map((item) => (
                                <tr key={item.id}>
                                  <td><BuildingIcon style={{ width: 14, height: 14, color: "#0d6efd", marginRight: 4, verticalAlign: "text-bottom" }} />{item.customer}</td>
                                  <td><PackageIcon style={{ width: 14, height: 14, color: "#6c757d", marginRight: 8, verticalAlign: "text-bottom" }} />{item.product_name}</td>
                                  <td className="text-center fw-semibold">{item.quantity}</td>
                                  <td>{item.note || "-"}</td>
                                  <td><button className="btn btn-sm btn-outline-danger" onClick={() => { if (confirm("确定删除此记录？")) deleteSoMutation.mutate(item.id); }}><Trash2Icon style={{ width: 12, height: 12 }} /></button></td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Edit staged modal */}
          {soEditStagedIdx >= 0 && (
            <div className="stk-modal-overlay show" onClick={() => setSoEditStagedIdx(-1)}>
              <div className="stk-modal" style={{ maxWidth: 500 }} onClick={(e) => e.stopPropagation()}>
                <div className="stk-modal-header"><h5>编辑暂存出货</h5><button className="stk-modal-close" onClick={() => setSoEditStagedIdx(-1)}><XIcon style={{ width: 16, height: 16 }} /></button></div>
                <div className="stk-modal-body">
                  <div className="mb-3"><label className="form-label">客户</label><select className="form-select" value={soEditForm.customer} onChange={(e) => setSoEditForm({ ...soEditForm, customer: e.target.value })}><option value="">请选择客户</option>{customers.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}</select></div>
                  <div className="mb-3"><label className="form-label">出货时间</label><input type="date" className="form-control" value={soEditForm.stockoutDate} onChange={(e) => setSoEditForm({ ...soEditForm, stockoutDate: e.target.value })} /></div>
                  <div className="mb-3"><label className="form-label">数量</label><input type="number" className="form-control" value={soEditForm.quantity || ""} onChange={(e) => setSoEditForm({ ...soEditForm, quantity: Number(e.target.value) })} min={1} /></div>
                  <div className="mb-3"><label className="form-label">备注</label><input type="text" className="form-control" value={soEditForm.note} onChange={(e) => setSoEditForm({ ...soEditForm, note: e.target.value })} /></div>
                </div>
                <div className="stk-modal-footer">
                  <button className="btn btn-secondary" onClick={() => setSoEditStagedIdx(-1)}>取消</button>
                  <button className="btn btn-primary" onClick={() => {
                    setSoStaged((prev) => prev.map((item, i) => i === soEditStagedIdx ? { ...item, customer: soEditForm.customer, quantity: soEditForm.quantity, stockoutDate: soEditForm.stockoutDate, note: soEditForm.note } : item));
                    setSoEditStagedIdx(-1);
                  }}>保存</button>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {/* ===== Inventory Tab ===== */}
      {tab === "inventory" && (
        <>
          {/* Search panel */}
          <div className="card mt-3">
            <div className="card-header">查询条件</div>
            <div className="card-body">
              <div className="row g-3">
                <div className="col-md-6">
                  <label className="form-label">客户名称</label>
                  <select className="form-select" value={invCustomer} onChange={(e) => setInvCustomer(e.target.value)}>
                    <option value="">全部客户</option>
                    {customers.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
                  </select>
                </div>
                <div className="col-md-4">
                  <label className="form-label">产品名称</label>
                  <input type="text" className="form-control" placeholder="输入产品名称或69码" value={invProduct} onChange={(e) => setInvProduct(e.target.value)} />
                </div>
                <div className="col-md-2 d-flex align-items-end">
                  <div className="d-flex gap-2 w-100">
                    <button className="btn btn-primary flex-grow-1" onClick={() => queryClient.invalidateQueries({ queryKey: ["inventory"] })}>
                      <SearchIcon style={{ width: 14, height: 14, marginRight: 4, verticalAlign: "text-bottom" }} />查询
                    </button>
                    <button className="btn btn-outline-secondary" onClick={() => { setInvCustomer(""); setInvProduct(""); }}>
                      <RefreshCwIcon style={{ width: 14, height: 14 }} />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Stat cards */}
          {invItems.length > 0 && invData && (
            <div className="card mt-4">
              <div className="card-body">
                <div className="row text-center">
                  <div className="col-md-4"><div className="stk-stat-card"><h3>{invData.total_order_qty || 0}</h3><small className="text-muted">总订单数</small></div></div>
                  <div className="col-md-4"><div className="stk-stat-card"><h3>{invData.total_stockin_qty || 0}</h3><small className="text-muted">总备货数量</small></div></div>
                  <div className="col-md-4"><div className="stk-stat-card"><h3>{invData.total_total_qty || 0}</h3><small className="text-muted">总库存</small></div></div>
                </div>
              </div>
            </div>
          )}

          {/* Inventory table */}
          <div className="card mt-4">
            <div className="card-header d-flex justify-content-between align-items-center">
              <span>库存汇总</span>
              <div className="d-flex align-items-center gap-3">
                <span>共 {invItems.length} 条记录</span>
                {invItems.length > 0 && (
                  <button className="btn btn-success btn-sm" onClick={async () => {
                    try { const res = await fetch("/api/v1/stock/export-inventory"); const blob = await res.blob(); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "库存汇总.xlsx"; a.click(); URL.revokeObjectURL(url); } catch { toast.error("导出失败"); }
                  }}>
                    <FileSpreadsheetIcon style={{ width: 14, height: 14, marginRight: 4, verticalAlign: "text-bottom" }} />导出
                  </button>
                )}
              </div>
            </div>
            <div className="card-body">
              {invLoading ? (
                <div className="text-center py-4"><Loader2Icon style={{ width: 32, height: 32, animation: "stkSpin 0.8s linear infinite" }} /><p className="text-muted mt-2">加载中...</p></div>
              ) : invItems.length === 0 ? (
                <div className="text-center text-muted py-4"><ClipboardCheckIcon style={{ width: 48, height: 48, opacity: 0.3, marginBottom: 12 }} /><p>暂无库存数据</p></div>
              ) : (
                <table className="table">
                  <thead><tr><th style={{ width: "15%" }}>客户</th><th style={{ width: "25%" }}>产品名称</th><th className="text-center" style={{ width: "20%" }}>订单数量</th><th className="text-center" style={{ width: "20%" }}>备货数量</th><th className="text-center" style={{ width: "20%" }}>总库存</th></tr></thead>
                  <tbody>
                    {invItems.map((item, idx) => (
                      <tr key={idx}>
                        <td><span className="fw-semibold"><BuildingIcon style={{ width: 14, height: 14, color: "#0d6efd", marginRight: 4, verticalAlign: "text-bottom" }} />{item.customer}</span></td>
                        <td><span className="fw-semibold"><PackageIcon style={{ width: 14, height: 14, color: "#6c757d", marginRight: 8, verticalAlign: "text-bottom" }} />{item.product_name}</span></td>
                        <td className="text-center">{item.order_quantity}</td>
                        <td className="text-center">{item.stockin_quantity}</td>
                        <td className="text-center">{item.total_stock}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </>
      )}

      {/* ===== Styles ===== */}
      <style jsx global>{`
        .stk-container { padding: 0; }
        .stk-page-title { font-size: 1.5rem; font-weight: 600; margin-bottom: 0; }

        .stk-container .nav-link { cursor: pointer; }

        .stk-autocomplete-wrapper { position: relative; }
        .stk-autocomplete-dropdown {
          position: absolute; top: 100%; left: 0; right: 0;
          background: white; border: 2px solid #D4F1F4; border-top: none;
          border-radius: 0 0 var(--radius-input) var(--radius-input);
          box-shadow: 0 4px 12px rgba(0,0,0,0.1); z-index: 1000;
          max-height: 200px; overflow-y: auto;
          animation: stkFadeIn 0.2s ease-in-out;
        }
        .stk-autocomplete-item { padding: 8px 12px; cursor: pointer; display: flex; align-items: center; gap: 8px; transition: background 0.2s ease, transform 0.2s ease; }
        .stk-autocomplete-item:hover { background: #D4F1F4; transform: translateX(5px); }
        .stk-product-name { font-weight: 500; flex: 1; }
        .stk-product-barcode { font-size: 11px; color: #6c757d; font-family: monospace; }

        .stk-staged-item { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border: 2px solid #D4F1F4; border-radius: var(--radius-md); margin-bottom: 6px; transition: all 0.2s; }
        .stk-staged-item:hover { box-shadow: 0 2px 6px rgba(176, 224, 230, 0.25); }
        .stk-staged-info { flex: 1; min-width: 0; }
        .stk-staged-name { font-weight: 600; font-size: 14px; color: #5A4A4A; }
        .stk-staged-meta { font-size: 12px; color: #595959; margin-top: 2px; }
        .stk-staged-note { font-size: 11px; color: #8B7B7B; font-style: italic; margin-top: 2px; }
        .stk-staged-actions { display: flex; gap: 4px; }

        .stk-date-group { border: 2px solid #D4F1F4; border-radius: var(--radius-md); margin-bottom: 8px; box-shadow: 0 4px 16px rgba(176, 224, 230, 0.25); overflow: hidden; }
        .stk-date-header { padding: 10px 16px; background: #FFFFFF; cursor: pointer; display: flex; justify-content: space-between; align-items: center; font-weight: 500; transition: background 0.2s; }
        .stk-date-header:hover { background: rgba(212, 241, 244, 0.3); }
        .stk-date-content { border-top: 1px solid #D4F1F4; }

        .stk-stat-card { background: #fff; padding: 1.25rem; border-radius: var(--radius-card); box-shadow: 0 4px 16px rgba(176, 224, 230, 0.25); text-align: center; }
        .stk-stat-card h3 { font-size: 1.75rem; font-weight: 700; color: #5A4A4A; margin-bottom: 0.25rem; }

        .stk-upload-area { border: 2px dashed #B0E0E6; padding: 1.5rem; text-align: center; border-radius: var(--radius-lg); cursor: pointer; background: #FAFBFC; min-height: 120px; display: flex; flex-direction: column; align-items: center; justify-content: center; transition: border-color 0.2s, background 0.2s; }
        .stk-upload-area:hover { border-color: #87CEEB; background: #F0F7FF; }

        .stk-modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 9999; display: none; justify-content: center; align-items: center; }
        .stk-modal-overlay.show { display: flex; }
        .stk-modal { background: #fff; border-radius: var(--radius-xl); width: 95%; max-width: 500px; max-height: 90vh; overflow: hidden; border: 3px solid #D4F1F4; box-shadow: 0 12px 48px rgba(135, 206, 235, 0.35); }
        .stk-modal-header { padding: 16px 20px; border-bottom: 2px solid #87CEEB; display: flex; justify-content: space-between; align-items: center; }
        .stk-modal-header h5 { margin: 0; font-size: 16px; font-weight: 600; color: #5A4A4A; }
        .stk-modal-close { background: none; border: none; cursor: pointer; color: #6c757d; padding: 4px; border-radius: 4px; }
        .stk-modal-close:hover { background: #FFEBEE; color: #C62828; }
        .stk-modal-body { padding: 20px; overflow-y: auto; }
        .stk-modal-footer { padding: 12px 20px; border-top: 2px solid #D4F1F4; display: flex; justify-content: flex-end; gap: 8px; }

        @keyframes stkFadeIn { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes stkSpin { to { transform: rotate(360deg); } }

        .stk-container .col-md-2 { flex: 0 0 16.667%; max-width: 16.667%; padding: 0 12px; }
        .stk-container .g-3 > * { padding: 0 12px; margin-bottom: 1rem; }

        @media (max-width: 991.98px) { .stk-container .col-lg-6 { flex: 0 0 100%; max-width: 100%; } }
        @media (max-width: 767.98px) { .stk-container .col-md-2, .stk-container .col-md-4, .stk-container .col-md-6 { flex: 0 0 100%; max-width: 100%; } }
      `}</style>
    </div>
  );
}
