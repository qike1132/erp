"use client";

import { useState, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post, put, del } from "@/lib/api-client";

// ============ Types ============

interface CaseProduct {
  id: number; name: string; barcode: string; current_stock: number;
}

export interface StockinRecord {
  id: number; stockin_no: string; stockin_date: string; customer: string;
  case_name: string; case_barcode: string; quantity: number; note: string;
}

export interface StockoutRecord {
  id: number; stockout_no: string; stockout_date: string; customer: string;
  case_name: string; case_barcode: string; quantity: number; note: string;
}

export interface InventoryItem {
  id: number; name: string; barcode: string; initial_stock: number;
  total_in: number; total_out: number; current_stock: number;
}

interface InventoryLog {
  change_type: string; change_quantity: number; customer: string;
  related_id: string; change_date: string; note: string;
}

interface StagedItem {
  tempId: number; productId: string; productName: string;
  customer: string; date: string; quantity: number; note: string;
}

export interface PaginatedData<T> {
  [key: string]: T[] | number | Record<string, unknown>;
}

// ============ Component ============

interface CaseContentProps {
  initialCustomers?: string[];
  initialStockins?: PaginatedData<StockinRecord>;
  initialStockouts?: PaginatedData<StockoutRecord>;
  initialInventory?: InventoryItem[];
}

export function CaseContent({ initialCustomers, initialStockins, initialStockouts, initialInventory }: CaseContentProps) {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<"stockin" | "stockout" | "inventory">("stockin");

  // ---- Stockin state ----
  const [siProductId, setSiProductId] = useState("");
  const [siSearch, setSiSearch] = useState("");
  const [siCustomer, setSiCustomer] = useState("");
  const [siDate, setSiDate] = useState(new Date().toISOString().split("T")[0]);
  const [siQuantity, setSiQuantity] = useState(1);
  const [siNote, setSiNote] = useState("");
  const [siStaged, setSiStaged] = useState<StagedItem[]>([]);
  const [siSearchResults, setSiSearchResults] = useState<CaseProduct[]>([]);
  const [siPage, setSiPage] = useState(1);
  const [siFCustomer, setSiFCustomer] = useState("");
  const [siFStart, setSiFStart] = useState("");
  const [siFEnd, setSiFEnd] = useState("");
  const [siShowFilter, setSiShowFilter] = useState(false);
  const [siShowBatch, setSiShowBatch] = useState(false);
  const siFileRef = useRef<HTMLInputElement>(null);
  const [siBatchFile, setSiBatchFile] = useState<File | null>(null);

  // ---- Stockout state ----
  const [soProductId, setSoProductId] = useState("");
  const [soSearch, setSoSearch] = useState("");
  const [soCustomer, setSoCustomer] = useState("");
  const [soDate, setSoDate] = useState(new Date().toISOString().split("T")[0]);
  const [soQuantity, setSoQuantity] = useState(1);
  const [soNote, setSoNote] = useState("");
  const [soStaged, setSoStaged] = useState<StagedItem[]>([]);
  const [soSearchResults, setSoSearchResults] = useState<CaseProduct[]>([]);
  const [soCurrentStock, setSoCurrentStock] = useState<number | null>(null);
  const [soPage, setSoPage] = useState(1);
  const [soFCustomer, setSoFCustomer] = useState("");
  const [soFStart, setSoFStart] = useState("");
  const [soFEnd, setSoFEnd] = useState("");
  const [soShowFilter, setSoShowFilter] = useState(false);
  const [soShowBatch, setSoShowBatch] = useState(false);
  const soFileRef = useRef<HTMLInputElement>(null);
  const [soBatchFile, setSoBatchFile] = useState<File | null>(null);

  // ---- Inventory state ----
  const [invSearch, setInvSearch] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [selectedCaseName, setSelectedCaseName] = useState("");
  const [logPage, setLogPage] = useState(1);
  const [logType, setLogType] = useState("");
  const [logStart, setLogStart] = useState("");
  const [logEnd, setLogEnd] = useState("");
  const [showLogFilter, setShowLogFilter] = useState(false);

  // ---- Edit modals ----
  const [editSiOpen, setEditSiOpen] = useState(false);
  const [editSi, setEditSi] = useState({ id: 0, customer: "", stockin_date: "", case_name: "", quantity: 1, note: "" });
  const [editSoOpen, setEditSoOpen] = useState(false);
  const [editSo, setEditSo] = useState({ id: 0, customer: "", stockout_date: "", case_name: "", quantity: 1, note: "" });

  // ============ Queries ============

  const { data: customers } = useQuery<string[]>({
    queryKey: ["active-customers"],
    queryFn: () => get<string[]>("/customers/active-names"),
    initialData: initialCustomers,
  });

  const { data: siListRaw, isLoading: siLoading } = useQuery<PaginatedData<StockinRecord>>({
    queryKey: ["case-stockins", siPage, siFCustomer, siFStart, siFEnd],
    queryFn: () => get<PaginatedData<StockinRecord>>("/cases/in/list", {
      page: String(siPage), per_page: "10",
      ...(siFCustomer && { customer: siFCustomer }),
      ...(siFStart && { start_date: siFStart }),
      ...(siFEnd && { end_date: siFEnd }),
    }),
    initialData: initialStockins && siPage === 1 && !siFCustomer && !siFStart && !siFEnd ? initialStockins : undefined,
  });

  const { data: soListRaw, isLoading: soLoading } = useQuery<PaginatedData<StockoutRecord>>({
    queryKey: ["case-stockouts", soPage, soFCustomer, soFStart, soFEnd],
    queryFn: () => get<PaginatedData<StockoutRecord>>("/cases/out/list", {
      page: String(soPage), per_page: "10",
      ...(soFCustomer && { customer: soFCustomer }),
      ...(soFStart && { start_date: soFStart }),
      ...(soFEnd && { end_date: soFEnd }),
    }),
    initialData: initialStockouts && soPage === 1 && !soFCustomer && !soFStart && !soFEnd ? initialStockouts : undefined,
  });

  const { data: invData, isLoading: invLoading } = useQuery<InventoryItem[]>({
    queryKey: ["case-inventory"],
    queryFn: () => get<InventoryItem[]>("/cases/inventory-summary"),
    initialData: initialInventory,
  });

  const { data: logRaw } = useQuery<PaginatedData<InventoryLog>>({
    queryKey: ["case-inventory-logs", selectedCaseId, logPage, logType, logStart, logEnd],
    queryFn: () => selectedCaseId
      ? get<PaginatedData<InventoryLog>>(`/cases/inventory-logs/${selectedCaseId}`, {
          page: String(logPage), per_page: "15",
          ...(logType && { type: logType }),
          ...(logStart && { start_date: logStart }),
          ...(logEnd && { end_date: logEnd }),
        })
      : Promise.resolve({} as PaginatedData<InventoryLog>),
    enabled: !!selectedCaseId,
  });

  // ============ Helpers ============

  const siList = (siListRaw?.stockins || siListRaw?.items || []) as StockinRecord[];
  const siPages = (siListRaw?.pages || siListRaw?.total_pages || 1) as number;
  const soList = (soListRaw?.stockouts || soListRaw?.items || []) as StockoutRecord[];
  const soPages = (soListRaw?.pages || soListRaw?.total_pages || 1) as number;
  const logList = (logRaw?.logs || logRaw?.items || []) as InventoryLog[];
  const logPages = ((logRaw?.pagination as Record<string, unknown>)?.pages || logRaw?.total_pages || 1) as number;

  const filteredInv = invData
    ? invData.filter(item =>
        item.name.toLowerCase().includes(invSearch.toLowerCase()) ||
        (item.barcode && item.barcode.toLowerCase().includes(invSearch.toLowerCase()))
      )
    : [];

  // ============ Mutations ============

  const submitSiBatch = useMutation({
    mutationFn: (items: StagedItem[]) => post<Record<string, unknown>>("/cases/in/batch", {
      stockins: items.map(s => ({
        productId: s.productId, customer: s.customer,
        quantity: s.quantity, stockinDate: s.date, note: s.note,
      })),
    }),
    onSuccess: () => { setSiStaged([]); qc.invalidateQueries({ queryKey: ["case-stockins"] }); qc.invalidateQueries({ queryKey: ["case-inventory"] }); },
  });

  const submitSoBatch = useMutation({
    mutationFn: (items: StagedItem[]) => post<Record<string, unknown>>("/cases/out/batch", {
      stockouts: items.map(s => ({
        productId: s.productId, customer: s.customer,
        quantity: s.quantity, stockout_date: s.date, note: s.note,
      })),
    }),
    onSuccess: () => { setSoStaged([]); qc.invalidateQueries({ queryKey: ["case-stockouts"] }); qc.invalidateQueries({ queryKey: ["case-inventory"] }); },
  });

  const updateSiMut = useMutation({
    mutationFn: (d: typeof editSi) => put<Record<string, unknown>>(`/cases/in/${d.id}`, {
      customer: d.customer, stockin_date: d.stockin_date, quantity: d.quantity, note: d.note,
    }),
    onSuccess: () => { setEditSiOpen(false); qc.invalidateQueries({ queryKey: ["case-stockins"] }); qc.invalidateQueries({ queryKey: ["case-inventory"] }); },
  });

  const updateSoMut = useMutation({
    mutationFn: (d: typeof editSo) => put<Record<string, unknown>>(`/cases/out/${d.id}`, {
      customer: d.customer, stockout_date: d.stockout_date, quantity: d.quantity, note: d.note,
    }),
    onSuccess: () => { setEditSoOpen(false); qc.invalidateQueries({ queryKey: ["case-stockouts"] }); qc.invalidateQueries({ queryKey: ["case-inventory"] }); },
  });

  const deleteSiMut = useMutation({
    mutationFn: (id: number) => del<Record<string, unknown>>(`/cases/in/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["case-stockins"] }); qc.invalidateQueries({ queryKey: ["case-inventory"] }); },
  });

  const deleteSoMut = useMutation({
    mutationFn: (id: number) => del<Record<string, unknown>>(`/cases/out/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["case-stockouts"] }); qc.invalidateQueries({ queryKey: ["case-inventory"] }); },
  });

  // ============ Search ============

  const searchProducts = useCallback(async (q: string, setResults: (r: CaseProduct[]) => void) => {
    if (!q.trim()) { setResults([]); return; }
    try {
      const data = await get<CaseProduct[]>("/cases/search", { q });
      setResults(Array.isArray(data) ? data : []);
    } catch { setResults([]); }
  }, []);

  let siSearchTimer: ReturnType<typeof setTimeout>;
  const onSiSearch = (v: string) => {
    setSiSearch(v); setSiProductId("");
    clearTimeout(siSearchTimer);
    siSearchTimer = setTimeout(() => searchProducts(v, setSiSearchResults), 300);
  };

  let soSearchTimer: ReturnType<typeof setTimeout>;
  const onSoSearch = (v: string) => {
    setSoSearch(v); setSoProductId(""); setSoCurrentStock(null);
    clearTimeout(soSearchTimer);
    soSearchTimer = setTimeout(() => searchProducts(v, setSoSearchResults), 300);
  };

  const selectSiProduct = (p: CaseProduct) => {
    setSiProductId(String(p.id)); setSiSearch(p.name); setSiSearchResults([]);
  };

  const selectSoProduct = (p: CaseProduct) => {
    setSoProductId(String(p.id)); setSoSearch(p.name); setSoCurrentStock(p.current_stock); setSoSearchResults([]);
  };

  // ============ Staged list handlers ============

  const addSiStaged = () => {
    if (!siProductId || siQuantity < 1) return;
    setSiStaged(prev => [...prev, {
      tempId: Date.now(), productId: siProductId, productName: siSearch,
      customer: siCustomer, date: siDate, quantity: siQuantity, note: siNote,
    }]);
    setSiProductId(""); setSiSearch(""); setSiCustomer(""); setSiQuantity(1); setSiNote("");
    setSiDate(new Date().toISOString().split("T")[0]);
  };

  const removeSiStaged = (idx: number) => setSiStaged(prev => prev.filter((_, i) => i !== idx));

  const addSoStaged = () => {
    if (!soProductId || soQuantity < 1) return;
    if (soCurrentStock !== null && soQuantity > soCurrentStock) {
      alert(`库存不足，当前库存: ${soCurrentStock}`); return;
    }
    setSoStaged(prev => [...prev, {
      tempId: Date.now(), productId: soProductId, productName: soSearch,
      customer: soCustomer, date: soDate, quantity: soQuantity, note: soNote,
    }]);
    setSoProductId(""); setSoSearch(""); setSoCustomer(""); setSoQuantity(1); setSoNote("");
    setSoDate(new Date().toISOString().split("T")[0]);
    if (soCurrentStock !== null) setSoCurrentStock(soCurrentStock - soQuantity);
  };

  const removeSoStaged = (idx: number) => setSoStaged(prev => prev.filter((_, i) => i !== idx));

  // ============ Edit handlers ============

  const openEditSi = async (id: number) => {
    try {
      const d = await get<Record<string, unknown>>(`/cases/in/${id}`);
      setEditSi({
        id, customer: String(d.customer || ""), stockin_date: String(d.stockin_date || ""),
        case_name: String(d.case_name || ""), quantity: Number(d.quantity) || 1, note: String(d.note || ""),
      });
      setEditSiOpen(true);
    } catch { /* ignore */ }
  };

  const openEditSo = async (id: number) => {
    try {
      const d = await get<Record<string, unknown>>(`/cases/out/${id}`);
      setEditSo({
        id, customer: String(d.customer || ""), stockout_date: String(d.stockout_date || ""),
        case_name: String(d.case_name || ""), quantity: Number(d.quantity) || 1, note: String(d.note || ""),
      });
      setEditSoOpen(true);
    } catch { /* ignore */ }
  };

  // ============ Batch upload ============

  const doBatchImport = async (file: File, endpoint: string) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`/api/v1${endpoint}`, { method: "POST", body: fd });
    return res.json();
  };

  // ============ Pagination ============

  const renderPagination = (current: number, total: number, setPage: (p: number) => void) => {
    if (total <= 1) return null;
    const pages: (number | string)[] = [];
    for (let i = 1; i <= total; i++) {
      if (i === 1 || i === total || (i >= current - 2 && i <= current + 2)) pages.push(i);
      else if (i === current - 3 || i === current + 3) pages.push("...");
    }
    return (
      <nav className="cs-pagination">
        <ul>
          <li className={current === 1 ? "disabled" : ""}>
            <button onClick={() => setPage(current - 1)} disabled={current === 1}>上一页</button>
          </li>
          {pages.map((p, i) =>
            typeof p === "string"
              ? <li key={`e${i}`} className="disabled"><span>...</span></li>
              : <li key={p} className={p === current ? "active" : ""}><button onClick={() => setPage(p)}>{p}</button></li>
          )}
          <li className={current === total ? "disabled" : ""}>
            <button onClick={() => setPage(current + 1)} disabled={current === total}>下一页</button>
          </li>
        </ul>
      </nav>
    );
  };

  // ============ Log badge ============

  const logBadgeCls = (t: string) => {
    const m: Record<string, string> = {
      "入库": "bg-success", "出库": "bg-danger",
      "入库调整": "bg-warning", "出库调整": "bg-warning",
      "删除入库": "bg-secondary", "删除出库": "bg-secondary",
    };
    return m[t] || "bg-info";
  };

  // ============ Render ============

  return (
    <div className="cs-page-root">
      {/* Header */}
      <h2 className="cs-page-title"><i className="fas fa-box-open text-success" style={{ marginRight: 8 }}></i>皮套管理</h2>

      {/* Tabs */}
      <ul className="cs-nav-tabs">
        <li className={`cs-nav-item ${activeTab === "stockin" ? "active" : ""}`}>
          <button onClick={() => setActiveTab("stockin")}><i className="fas fa-truck-loading" style={{ marginRight: 4 }}></i>入库管理</button>
        </li>
        <li className={`cs-nav-item ${activeTab === "stockout" ? "active" : ""}`}>
          <button onClick={() => setActiveTab("stockout")}><i className="fas fa-shipping-fast" style={{ marginRight: 4 }}></i>出库管理</button>
        </li>
        <li className={`cs-nav-item ${activeTab === "inventory" ? "active" : ""}`}>
          <button onClick={() => setActiveTab("inventory")}><i className="fas fa-warehouse" style={{ marginRight: 4 }}></i>库存查询</button>
        </li>
      </ul>

      {/* ======== 入库管理 ======== */}
      {activeTab === "stockin" && (
        <div className="cs-tab-panel">
          <div className="cs-row">
            {/* Left: Form */}
            <div className="cs-col-lg-6">
              <div className="cs-card">
                <div className="cs-card-header">
                  <span>皮套入库信息录入</span>
                  {siStaged.length > 0 && <span className="cs-badge bg-info">已暂存: {siStaged.length}</span>}
                </div>
                <div className="cs-card-body">
                  <div className="cs-row mb-3">
                    <div className="cs-col-md-6">
                      <label className="cs-form-label">客户名称</label>
                      <select className="cs-form-select" value={siCustomer} onChange={e => setSiCustomer(e.target.value)}>
                        <option value="">请选择客户</option>
                        {customers?.map(c => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>
                    <div className="cs-col-md-6">
                      <label className="cs-form-label">入库时间</label>
                      <input type="date" className="cs-form-control" value={siDate} onChange={e => setSiDate(e.target.value)} />
                    </div>
                  </div>
                  <div className="cs-row mb-3">
                    <div className="cs-col-md-8" style={{ position: "relative" }}>
                      <label className="cs-form-label">产品名称</label>
                      <input className="cs-form-control" value={siSearch} onChange={e => onSiSearch(e.target.value)} placeholder="输入产品名称或69码搜索" autoComplete="off" />
                      {siSearchResults.length > 0 && (
                        <div className="cs-datalist">
                          {siSearchResults.map(p => (
                            <div key={p.id} className="cs-datalist-item" onClick={() => selectSiProduct(p)}>
                              {p.name} {p.barcode && <small style={{ color: "#888" }}>({p.barcode})</small>}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="cs-col-md-4">
                      <label className="cs-form-label">入库数量</label>
                      <input type="number" className="cs-form-control" value={siQuantity} min={1} onChange={e => setSiQuantity(Number(e.target.value))} />
                    </div>
                  </div>
                  <div className="mb-3">
                    <label className="cs-form-label">备注</label>
                    <textarea className="cs-form-control" rows={2} value={siNote} onChange={e => setSiNote(e.target.value)} placeholder="例如：批量入库" />
                  </div>
                  <button className="cs-btn cs-btn-secondary" disabled={!siProductId || siQuantity < 1} onClick={addSiStaged}>
                    <i className="fas fa-plus-circle" style={{ marginRight: 4 }}></i>新增入库
                  </button>
                </div>
              </div>
            </div>

            {/* Right: Staged list + Batch upload */}
            <div className="cs-col-lg-6">
              <div className="cs-card">
                <div className="cs-card-header">
                  <span>暂存入库列表</span>
                  <span>共 {siStaged.length} 个</span>
                </div>
                <div className="cs-card-body">
                  <div style={{ maxHeight: 350, overflowY: "auto" }}>
                    {siStaged.length === 0 ? (
                      <div className="cs-empty-state">
                        <i className="fas fa-box-open" style={{ fontSize: 48, opacity: 0.3 }}></i>
                        <p>暂无暂存入库</p>
                      </div>
                    ) : siStaged.map((item, idx) => (
                      <div key={item.tempId} className="cs-staged-card cs-staged-stockin">
                        <div className="cs-staged-body">
                          <div>
                            <h6><i className="fas fa-cubes text-primary" style={{ marginRight: 4 }}></i>{item.productName}</h6>
                            <p className="cs-muted-small"><i className="fas fa-user" style={{ marginRight: 4 }}></i>{item.customer || "无客户"}</p>
                            <p className="cs-muted-small">
                              <span className="cs-badge bg-info" style={{ marginRight: 4 }}>数量: {item.quantity}</span>
                              <span className="cs-badge bg-secondary">{item.date}</span>
                            </p>
                          </div>
                          <button className="cs-btn-sm cs-btn-outline-danger" onClick={() => removeSiStaged(idx)}>
                            <i className="fas fa-trash"></i>
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Batch upload */}
              <div className="cs-card" style={{ marginTop: 12 }}>
                <div className="cs-card-header cs-collapsible" onClick={() => setSiShowBatch(!siShowBatch)}>
                  <h6 style={{ margin: 0, fontWeight: "bold" }}><i className="fas fa-file-import text-primary" style={{ marginRight: 8 }}></i>批量导入入库</h6>
                  <i className={`fas fa-chevron-down ${siShowBatch ? "cs-rotate" : ""}`}></i>
                </div>
                {siShowBatch && (
                  <div className="cs-card-body">
                    <div className="cs-upload-zone" onClick={() => siFileRef.current?.click()}>
                      <i className="fas fa-file-excel" style={{ fontSize: 28, color: "#28a745", marginBottom: 8 }}></i>
                      <p style={{ color: "#6c757d", margin: 0, fontSize: 13 }}>拖拽 Excel 文件到这里，或点击选择文件</p>
                      <p style={{ color: "#6c757d", margin: 0, fontSize: 11 }}>支持 .xlsx / .xls</p>
                      <input ref={siFileRef} type="file" accept=".xlsx,.xls" style={{ display: "none" }} onChange={e => setSiBatchFile(e.target.files?.[0] || null)} />
                      {siBatchFile && <div className="cs-file-preview"><i className="fas fa-file-excel" style={{ marginRight: 8 }}></i>{siBatchFile.name}</div>}
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12 }}>
                      <button className="cs-btn cs-btn-outline-secondary cs-btn-sm" onClick={async () => {
                        const res = await fetch("/api/v1/batch/download-template");
                        const blob = await res.blob();
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a"); a.href = url; a.download = "皮套入库模板.xlsx"; a.click();
                        URL.revokeObjectURL(url);
                      }}><i className="fas fa-file-excel" style={{ marginRight: 4 }}></i>下载模板</button>
                      <button className="cs-btn cs-btn-primary cs-btn-sm" disabled={!siBatchFile} onClick={async () => {
                        if (!siBatchFile) return;
                        try { await doBatchImport(siBatchFile, "/batch/import-case-stockins"); setSiBatchFile(null); qc.invalidateQueries({ queryKey: ["case-stockins"] }); qc.invalidateQueries({ queryKey: ["case-inventory"] }); } catch { /* */ }
                      }}><i className="fas fa-upload" style={{ marginRight: 4 }}></i>开始导入</button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Submit button */}
          <div className="cs-card" style={{ marginTop: 12 }}>
            <div className="cs-card-body" style={{ textAlign: "center", padding: "12px 0" }}>
              <button className="cs-btn cs-btn-primary cs-btn-lg" disabled={siStaged.length === 0 || submitSiBatch.isPending} onClick={() => submitSiBatch.mutate(siStaged)} style={{ minWidth: 200 }}>
                <i className="fas fa-paper-plane" style={{ marginRight: 8 }}></i>
                {submitSiBatch.isPending ? "提交中..." : "提交入库"}
              </button>
            </div>
          </div>

          {/* Stockin record list */}
          <div className="cs-card" style={{ marginTop: 12 }}>
            <div className="cs-card-header">
              <span>入库记录列表</span>
              <button className="cs-btn cs-btn-outline-secondary cs-btn-sm" onClick={() => setSiShowFilter(!siShowFilter)}>
                <i className="fas fa-filter" style={{ marginRight: 4 }}></i>筛选
              </button>
            </div>
            {siShowFilter && (
              <div className="cs-card-body cs-filter-panel">
                <div className="cs-row" style={{ gap: 12 }}>
                  <div className="cs-col-filter">
                    <label className="cs-form-label">客户</label>
                    <select className="cs-form-select" value={siFCustomer} onChange={e => setSiFCustomer(e.target.value)}>
                      <option value="">全部</option>
                      {customers?.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>
                  <div className="cs-col-filter">
                    <label className="cs-form-label">开始日期</label>
                    <input type="date" className="cs-form-control" value={siFStart} onChange={e => setSiFStart(e.target.value)} />
                  </div>
                  <div className="cs-col-filter">
                    <label className="cs-form-label">结束日期</label>
                    <input type="date" className="cs-form-control" value={siFEnd} onChange={e => setSiFEnd(e.target.value)} />
                  </div>
                  <div className="cs-col-filter" style={{ display: "flex", alignItems: "flex-end" }}>
                    <button className="cs-btn cs-btn-primary" onClick={() => { setSiPage(1); qc.invalidateQueries({ queryKey: ["case-stockins"] }); }}>
                      <i className="fas fa-search" style={{ marginRight: 4 }}></i>查询
                    </button>
                  </div>
                </div>
              </div>
            )}
            <div className="cs-card-body">
              {siLoading ? (
                <div className="cs-empty-state"><i className="fas fa-spinner fa-spin" style={{ fontSize: 32 }}></i><p>加载中...</p></div>
              ) : siList.length === 0 ? (
                <div className="cs-empty-state"><i className="fas fa-box-open" style={{ fontSize: 48, opacity: 0.3 }}></i><p>暂无入库记录</p></div>
              ) : (
                <>
                  <table className="cs-table">
                    <thead><tr><th>入库日期</th><th>客户</th><th>产品名称</th><th>69码</th><th>数量</th><th>备注</th><th>操作</th></tr></thead>
                    <tbody>
                      {siList.map(item => (
                        <tr key={item.id}>
                          <td>{item.stockin_date}</td>
                          <td>{item.customer || "-"}</td>
                          <td>{item.case_name}</td>
                          <td><small>{item.case_barcode || "-"}</small></td>
                          <td><strong>{item.quantity}</strong></td>
                          <td><small>{item.note || "-"}</small></td>
                          <td>
                            <button className="cs-btn-sm cs-btn-outline-warning" style={{ marginRight: 4 }} onClick={() => openEditSi(item.id)}><i className="fas fa-edit"></i></button>
                            <button className="cs-btn-sm cs-btn-outline-danger" onClick={() => { if (confirm("确定要删除这条入库记录吗？")) deleteSiMut.mutate(item.id); }}><i className="fas fa-trash"></i></button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {renderPagination(siPage, siPages, setSiPage)}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ======== 出库管理 ======== */}
      {activeTab === "stockout" && (
        <div className="cs-tab-panel">
          <div className="cs-row">
            {/* Left: Form */}
            <div className="cs-col-lg-6">
              <div className="cs-card">
                <div className="cs-card-header">
                  <span>皮套出库信息录入</span>
                  {soStaged.length > 0 && <span className="cs-badge bg-info">已暂存: {soStaged.length}</span>}
                </div>
                <div className="cs-card-body">
                  <div className="cs-row mb-3">
                    <div className="cs-col-md-6">
                      <label className="cs-form-label">客户名称</label>
                      <select className="cs-form-select" value={soCustomer} onChange={e => setSoCustomer(e.target.value)}>
                        <option value="">请选择客户</option>
                        {customers?.map(c => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>
                    <div className="cs-col-md-6">
                      <label className="cs-form-label">出库时间</label>
                      <input type="date" className="cs-form-control" value={soDate} onChange={e => setSoDate(e.target.value)} />
                    </div>
                  </div>
                  <div className="cs-row mb-3">
                    <div className="cs-col-md-8" style={{ position: "relative" }}>
                      <label className="cs-form-label">产品名称</label>
                      <input className="cs-form-control" value={soSearch} onChange={e => onSoSearch(e.target.value)} placeholder="输入产品名称或69码搜索" autoComplete="off" />
                      {soSearchResults.length > 0 && (
                        <div className="cs-datalist">
                          {soSearchResults.map(p => (
                            <div key={p.id} className="cs-datalist-item" onClick={() => selectSoProduct(p)}>
                              {p.name} {p.barcode && <small style={{ color: "#888" }}>({p.barcode})</small>}
                              <span style={{ marginLeft: 8, color: "#6c757d", fontSize: 12 }}>库存: {p.current_stock}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      <small style={{ color: "#6c757d" }}>当前库存: {soCurrentStock !== null ? soCurrentStock : "-"}</small>
                    </div>
                    <div className="cs-col-md-4">
                      <label className="cs-form-label">出库数量</label>
                      <input type="number" className="cs-form-control" value={soQuantity} min={1} onChange={e => setSoQuantity(Number(e.target.value))} />
                    </div>
                  </div>
                  <div className="mb-3">
                    <label className="cs-form-label">备注</label>
                    <textarea className="cs-form-control" rows={2} value={soNote} onChange={e => setSoNote(e.target.value)} placeholder="例如：批量出库" />
                  </div>
                  <button className="cs-btn cs-btn-secondary" disabled={!soProductId || soQuantity < 1} onClick={addSoStaged}>
                    <i className="fas fa-plus-circle" style={{ marginRight: 4 }}></i>新增出库
                  </button>
                </div>
              </div>
            </div>

            {/* Right: Staged list + Batch */}
            <div className="cs-col-lg-6">
              <div className="cs-card">
                <div className="cs-card-header">
                  <span>暂存出库列表</span>
                  <span>共 {soStaged.length} 个</span>
                </div>
                <div className="cs-card-body">
                  <div style={{ maxHeight: 350, overflowY: "auto" }}>
                    {soStaged.length === 0 ? (
                      <div className="cs-empty-state">
                        <i className="fas fa-shipping-fast" style={{ fontSize: 48, opacity: 0.3 }}></i>
                        <p>暂无暂存出库</p>
                      </div>
                    ) : soStaged.map((item, idx) => (
                      <div key={item.tempId} className="cs-staged-card cs-staged-stockout">
                        <div className="cs-staged-body">
                          <div>
                            <h6><i className="fas fa-cubes text-danger" style={{ marginRight: 4 }}></i>{item.productName}</h6>
                            <p className="cs-muted-small"><i className="fas fa-user" style={{ marginRight: 4 }}></i>{item.customer || "无客户"}</p>
                            <p className="cs-muted-small">
                              <span className="cs-badge bg-danger" style={{ marginRight: 4 }}>数量: {item.quantity}</span>
                              <span className="cs-badge bg-secondary">{item.date}</span>
                            </p>
                          </div>
                          <button className="cs-btn-sm cs-btn-outline-danger" onClick={() => removeSoStaged(idx)}>
                            <i className="fas fa-trash"></i>
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Batch upload */}
              <div className="cs-card" style={{ marginTop: 12 }}>
                <div className="cs-card-header cs-collapsible" onClick={() => setSoShowBatch(!soShowBatch)}>
                  <h6 style={{ margin: 0, fontWeight: "bold" }}><i className="fas fa-file-export text-danger" style={{ marginRight: 8 }}></i>批量导出出库</h6>
                  <i className={`fas fa-chevron-down ${soShowBatch ? "cs-rotate" : ""}`}></i>
                </div>
                {soShowBatch && (
                  <div className="cs-card-body">
                    <div className="cs-upload-zone" onClick={() => soFileRef.current?.click()}>
                      <i className="fas fa-file-excel" style={{ fontSize: 28, color: "#28a745", marginBottom: 8 }}></i>
                      <p style={{ color: "#6c757d", margin: 0, fontSize: 13 }}>拖拽 Excel 文件到这里，或点击选择文件</p>
                      <p style={{ color: "#6c757d", margin: 0, fontSize: 11 }}>支持 .xlsx / .xls</p>
                      <input ref={soFileRef} type="file" accept=".xlsx,.xls" style={{ display: "none" }} onChange={e => setSoBatchFile(e.target.files?.[0] || null)} />
                      {soBatchFile && <div className="cs-file-preview"><i className="fas fa-file-excel" style={{ marginRight: 8 }}></i>{soBatchFile.name}</div>}
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12 }}>
                      <button className="cs-btn cs-btn-outline-secondary cs-btn-sm" onClick={async () => {
                        const res = await fetch("/api/v1/batch/download-template");
                        const blob = await res.blob();
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a"); a.href = url; a.download = "皮套出库模板.xlsx"; a.click();
                        URL.revokeObjectURL(url);
                      }}><i className="fas fa-file-excel" style={{ marginRight: 4 }}></i>下载模板</button>
                      <button className="cs-btn cs-btn-danger cs-btn-sm" disabled={!soBatchFile} onClick={async () => {
                        if (!soBatchFile) return;
                        try { await doBatchImport(soBatchFile, "/batch/import-case-stockouts"); setSoBatchFile(null); qc.invalidateQueries({ queryKey: ["case-stockouts"] }); qc.invalidateQueries({ queryKey: ["case-inventory"] }); } catch { /* */ }
                      }}><i className="fas fa-upload" style={{ marginRight: 4 }}></i>开始导入</button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Submit button */}
          <div className="cs-card" style={{ marginTop: 12 }}>
            <div className="cs-card-body" style={{ textAlign: "center", padding: "12px 0" }}>
              <button className="cs-btn cs-btn-danger cs-btn-lg" disabled={soStaged.length === 0 || submitSoBatch.isPending} onClick={() => submitSoBatch.mutate(soStaged)} style={{ minWidth: 200 }}>
                <i className="fas fa-paper-plane" style={{ marginRight: 8 }}></i>
                {submitSoBatch.isPending ? "提交中..." : "提交出库"}
              </button>
            </div>
          </div>

          {/* Stockout record list */}
          <div className="cs-card" style={{ marginTop: 12 }}>
            <div className="cs-card-header">
              <span>出库记录列表</span>
              <button className="cs-btn cs-btn-outline-secondary cs-btn-sm" onClick={() => setSoShowFilter(!soShowFilter)}>
                <i className="fas fa-filter" style={{ marginRight: 4 }}></i>筛选
              </button>
            </div>
            {soShowFilter && (
              <div className="cs-card-body cs-filter-panel">
                <div className="cs-row" style={{ gap: 12 }}>
                  <div className="cs-col-filter">
                    <label className="cs-form-label">客户</label>
                    <select className="cs-form-select" value={soFCustomer} onChange={e => setSoFCustomer(e.target.value)}>
                      <option value="">全部</option>
                      {customers?.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>
                  <div className="cs-col-filter">
                    <label className="cs-form-label">开始日期</label>
                    <input type="date" className="cs-form-control" value={soFStart} onChange={e => setSoFStart(e.target.value)} />
                  </div>
                  <div className="cs-col-filter">
                    <label className="cs-form-label">结束日期</label>
                    <input type="date" className="cs-form-control" value={soFEnd} onChange={e => setSoFEnd(e.target.value)} />
                  </div>
                  <div className="cs-col-filter" style={{ display: "flex", alignItems: "flex-end" }}>
                    <button className="cs-btn cs-btn-primary" onClick={() => { setSoPage(1); qc.invalidateQueries({ queryKey: ["case-stockouts"] }); }}>
                      <i className="fas fa-search" style={{ marginRight: 4 }}></i>查询
                    </button>
                  </div>
                </div>
              </div>
            )}
            <div className="cs-card-body">
              {soLoading ? (
                <div className="cs-empty-state"><i className="fas fa-spinner fa-spin" style={{ fontSize: 32 }}></i><p>加载中...</p></div>
              ) : soList.length === 0 ? (
                <div className="cs-empty-state"><i className="fas fa-shipping-fast" style={{ fontSize: 48, opacity: 0.3 }}></i><p>暂无出库记录</p></div>
              ) : (
                <>
                  <table className="cs-table">
                    <thead><tr><th>出库日期</th><th>客户</th><th>产品名称</th><th>69码</th><th>数量</th><th>备注</th><th>操作</th></tr></thead>
                    <tbody>
                      {soList.map(item => (
                        <tr key={item.id}>
                          <td>{item.stockout_date}</td>
                          <td>{item.customer || "-"}</td>
                          <td>{item.case_name}</td>
                          <td><small>{item.case_barcode || "-"}</small></td>
                          <td><strong className="text-danger">{item.quantity}</strong></td>
                          <td><small>{item.note || "-"}</small></td>
                          <td>
                            <button className="cs-btn-sm cs-btn-outline-warning" style={{ marginRight: 4 }} onClick={() => openEditSo(item.id)}><i className="fas fa-edit"></i></button>
                            <button className="cs-btn-sm cs-btn-outline-danger" onClick={() => { if (confirm("确定要删除这条出库记录吗？")) deleteSoMut.mutate(item.id); }}><i className="fas fa-trash"></i></button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {renderPagination(soPage, soPages, setSoPage)}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ======== 库存查询 ======== */}
      {activeTab === "inventory" && (
        <div className="cs-tab-panel">
          {/* Inventory summary */}
          <div className="cs-card" style={{ marginTop: 12 }}>
            <div className="cs-card-header">
              <span>皮套库存汇总</span>
              <div style={{ display: "flex", gap: 8 }}>
                <input className="cs-form-control cs-form-control-sm" placeholder="搜索产品名称或69码..." value={invSearch} onChange={e => setInvSearch(e.target.value)} style={{ width: 200 }} />
                <button className="cs-btn cs-btn-primary cs-btn-sm" onClick={() => qc.invalidateQueries({ queryKey: ["case-inventory"] })}>
                  <i className="fas fa-sync-alt" style={{ marginRight: 4 }}></i>刷新
                </button>
              </div>
            </div>
            <div className="cs-card-body">
              {invLoading ? (
                <div className="cs-empty-state"><i className="fas fa-spinner fa-spin" style={{ fontSize: 32 }}></i><p>加载中...</p></div>
              ) : filteredInv.length === 0 ? (
                <div className="cs-empty-state"><i className="fas fa-box-open" style={{ fontSize: 48, opacity: 0.3 }}></i><p>暂无库存数据</p></div>
              ) : (
                <>
                  {/* Stats cards */}
                  <div className="cs-row" style={{ marginBottom: 16 }}>
                    <div className="cs-col-md-4">
                      <div className="cs-stat-card cs-stat-success">
                        <h5>{filteredInv.reduce((s, i) => s + i.current_stock, 0)}</h5>
                        <small>当前总库存</small>
                      </div>
                    </div>
                    <div className="cs-col-md-4">
                      <div className="cs-stat-card cs-stat-primary">
                        <h5>{filteredInv.reduce((s, i) => s + i.total_in, 0)}</h5>
                        <small>累计入库</small>
                      </div>
                    </div>
                    <div className="cs-col-md-4">
                      <div className="cs-stat-card cs-stat-danger">
                        <h5>{filteredInv.reduce((s, i) => s + i.total_out, 0)}</h5>
                        <small>累计出库</small>
                      </div>
                    </div>
                  </div>

                  <table className="cs-table">
                    <thead><tr><th>产品名称</th><th>69码</th><th>初始库存</th><th>累计入库</th><th>累计出库</th><th>当前库存</th><th>操作</th></tr></thead>
                    <tbody>
                      {filteredInv.map(item => (
                        <tr key={item.id} className={selectedCaseId === item.id ? "cs-table-active" : ""} style={{ cursor: "pointer" }} onClick={() => { setSelectedCaseId(item.id); setSelectedCaseName(item.name); setLogPage(1); }}>
                          <td><strong>{item.name}</strong></td>
                          <td><small>{item.barcode || "-"}</small></td>
                          <td>{item.initial_stock}</td>
                          <td><span style={{ color: "#28a745" }}>{item.total_in}</span></td>
                          <td><span style={{ color: "#dc3545" }}>{item.total_out}</span></td>
                          <td><strong style={{ color: item.current_stock < 0 ? "#dc3545" : "#007bff" }}>{item.current_stock}</strong></td>
                          <td>
                            <button className="cs-btn-sm cs-btn-outline-info" onClick={e => { e.stopPropagation(); setSelectedCaseId(item.id); setSelectedCaseName(item.name); setLogPage(1); }}>
                              <i className="fas fa-history" style={{ marginRight: 4 }}></i>流水
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>
          </div>

          {/* Inventory logs */}
          <div className="cs-card" style={{ marginTop: 16 }}>
            <div className="cs-card-header">
              <span>库存流水记录 {selectedCaseName && <small style={{ color: "#6c757d" }}> - {selectedCaseName}</small>}</span>
              <button className="cs-btn cs-btn-outline-secondary cs-btn-sm" onClick={() => setShowLogFilter(!showLogFilter)}>
                <i className="fas fa-filter" style={{ marginRight: 4 }}></i>筛选
              </button>
            </div>
            {showLogFilter && (
              <div className="cs-card-body cs-filter-panel">
                <div className="cs-row" style={{ gap: 12 }}>
                  <div className="cs-col-filter">
                    <label className="cs-form-label">操作类型</label>
                    <select className="cs-form-select" value={logType} onChange={e => setLogType(e.target.value)}>
                      <option value="">全部</option>
                      <option value="入库">入库</option>
                      <option value="出库">出库</option>
                      <option value="入库调整">入库调整</option>
                      <option value="出库调整">出库调整</option>
                      <option value="删除入库">删除入库</option>
                      <option value="删除出库">删除出库</option>
                    </select>
                  </div>
                  <div className="cs-col-filter">
                    <label className="cs-form-label">开始日期</label>
                    <input type="date" className="cs-form-control" value={logStart} onChange={e => setLogStart(e.target.value)} />
                  </div>
                  <div className="cs-col-filter">
                    <label className="cs-form-label">结束日期</label>
                    <input type="date" className="cs-form-control" value={logEnd} onChange={e => setLogEnd(e.target.value)} />
                  </div>
                  <div className="cs-col-filter" style={{ display: "flex", alignItems: "flex-end", gap: 4 }}>
                    <button className="cs-btn cs-btn-primary" onClick={() => { setLogPage(1); qc.invalidateQueries({ queryKey: ["case-inventory-logs"] }); }}>
                      <i className="fas fa-search" style={{ marginRight: 4 }}></i>查询
                    </button>
                    <button className="cs-btn cs-btn-outline-secondary" onClick={() => { setLogType(""); setLogStart(""); setLogEnd(""); setLogPage(1); }}>
                      <i className="fas fa-times"></i>
                    </button>
                  </div>
                </div>
              </div>
            )}
            <div className="cs-card-body">
              {!selectedCaseId ? (
                <div className="cs-empty-state"><i className="fas fa-info-circle" style={{ fontSize: 32, opacity: 0.3 }}></i><p>请点击上方库存表格中的产品查看流水记录</p></div>
              ) : logList.length === 0 ? (
                <div className="cs-empty-state"><i className="fas fa-history" style={{ fontSize: 32, opacity: 0.3 }}></i><p>暂无流水记录</p></div>
              ) : (
                <>
                  <table className="cs-table">
                    <thead><tr><th>操作类型</th><th>变化数量</th><th>客户</th><th>关联单号</th><th>时间</th><th>备注</th></tr></thead>
                    <tbody>
                      {logList.map((log, idx) => (
                        <tr key={idx}>
                          <td><span className={`cs-badge ${logBadgeCls(log.change_type)}`}>{log.change_type}</span></td>
                          <td><strong style={{ color: log.change_quantity >= 0 ? "#28a745" : "#dc3545" }}>{log.change_quantity >= 0 ? "+" : ""}{log.change_quantity}</strong></td>
                          <td>{log.customer || "-"}</td>
                          <td><small>{log.related_id || "-"}</small></td>
                          <td><small>{log.change_date}</small></td>
                          <td><small>{log.note || "-"}</small></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {renderPagination(logPage, logPages, setLogPage)}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ======== Edit Stockin Modal ======== */}
      {editSiOpen && (
        <div className="cs-modal-overlay" onClick={() => setEditSiOpen(false)}>
          <div className="cs-modal" onClick={e => e.stopPropagation()}>
            <div className="cs-modal-header">
              <h5>编辑入库记录</h5>
              <button className="cs-modal-close" onClick={() => setEditSiOpen(false)}>&times;</button>
            </div>
            <div className="cs-modal-body">
              <div className="mb-3">
                <label className="cs-form-label">客户名称</label>
                <select className="cs-form-select" value={editSi.customer} onChange={e => setEditSi({ ...editSi, customer: e.target.value })}>
                  {customers?.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div className="mb-3">
                <label className="cs-form-label">入库日期</label>
                <input type="date" className="cs-form-control" value={editSi.stockin_date} onChange={e => setEditSi({ ...editSi, stockin_date: e.target.value })} />
              </div>
              <div className="mb-3">
                <label className="cs-form-label">产品名称</label>
                <input type="text" className="cs-form-control" value={editSi.case_name} readOnly />
              </div>
              <div className="mb-3">
                <label className="cs-form-label">入库数量</label>
                <input type="number" className="cs-form-control" min={1} value={editSi.quantity} onChange={e => setEditSi({ ...editSi, quantity: Number(e.target.value) })} />
              </div>
              <div className="mb-3">
                <label className="cs-form-label">备注</label>
                <textarea className="cs-form-control" rows={2} value={editSi.note} onChange={e => setEditSi({ ...editSi, note: e.target.value })} />
              </div>
            </div>
            <div className="cs-modal-footer">
              <button className="cs-btn cs-btn-secondary" onClick={() => setEditSiOpen(false)}>取消</button>
              <button className="cs-btn cs-btn-primary" onClick={() => updateSiMut.mutate(editSi)} disabled={updateSiMut.isPending}>保存</button>
            </div>
          </div>
        </div>
      )}

      {/* ======== Edit Stockout Modal ======== */}
      {editSoOpen && (
        <div className="cs-modal-overlay" onClick={() => setEditSoOpen(false)}>
          <div className="cs-modal" onClick={e => e.stopPropagation()}>
            <div className="cs-modal-header">
              <h5>编辑出库记录</h5>
              <button className="cs-modal-close" onClick={() => setEditSoOpen(false)}>&times;</button>
            </div>
            <div className="cs-modal-body">
              <div className="mb-3">
                <label className="cs-form-label">客户名称</label>
                <select className="cs-form-select" value={editSo.customer} onChange={e => setEditSo({ ...editSo, customer: e.target.value })}>
                  <option value="">无</option>
                  {customers?.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div className="mb-3">
                <label className="cs-form-label">出库日期</label>
                <input type="date" className="cs-form-control" value={editSo.stockout_date} onChange={e => setEditSo({ ...editSo, stockout_date: e.target.value })} />
              </div>
              <div className="mb-3">
                <label className="cs-form-label">产品名称</label>
                <input type="text" className="cs-form-control" value={editSo.case_name} readOnly />
              </div>
              <div className="mb-3">
                <label className="cs-form-label">出库数量</label>
                <input type="number" className="cs-form-control" min={1} value={editSo.quantity} onChange={e => setEditSo({ ...editSo, quantity: Number(e.target.value) })} />
              </div>
              <div className="mb-3">
                <label className="cs-form-label">备注</label>
                <textarea className="cs-form-control" rows={2} value={editSo.note} onChange={e => setEditSo({ ...editSo, note: e.target.value })} />
              </div>
            </div>
            <div className="cs-modal-footer">
              <button className="cs-btn cs-btn-secondary" onClick={() => setEditSoOpen(false)}>取消</button>
              <button className="cs-btn cs-btn-primary" onClick={() => updateSoMut.mutate(editSo)} disabled={updateSoMut.isPending}>保存</button>
            </div>
          </div>
        </div>
      )}

      {/* ============ Scoped CSS ============ */}
      <style jsx global>{`
        .cs-page-root { padding: 16px 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; font-size: 14px; color: #333; }
        .cs-page-title { font-size: 22px; font-weight: 600; margin-bottom: 16px; }

        /* Tabs */
        .cs-nav-tabs { display: flex; border-bottom: 2px solid #dee2e6; list-style: none; padding: 0; margin: 0 0 0; }
        .cs-nav-item { margin-bottom: -2px; }
        .cs-nav-item button { padding: 10px 20px; border: none; background: none; cursor: pointer; font-size: 14px; color: #6c757d; border-bottom: 3px solid transparent; transition: all 0.2s; }
        .cs-nav-item button:hover { color: #333; }
        .cs-nav-item.active button { color: #333; font-weight: 600; border-bottom-color: #007bff; }

        .cs-tab-panel { animation: csFadeIn 0.2s ease; }
        @keyframes csFadeIn { from { opacity: 0; } to { opacity: 1; } }

        /* Cards */
        .cs-card { background: #fff; border: 1px solid #dee2e6; border-radius: 8px; margin-bottom: 0; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
        .cs-card-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; background: #f8f9fa; border-bottom: 1px solid #dee2e6; font-weight: 600; font-size: 14px; }
        .cs-card-body { padding: 16px; }

        /* Grid */
        .cs-row { display: flex; flex-wrap: wrap; gap: 16px; }
        .cs-row.mb-3 { margin-bottom: 16px; }
        .cs-col-lg-6 { flex: 0 0 calc(50% - 8px); max-width: calc(50% - 8px); }
        .cs-col-md-6 { flex: 0 0 calc(50% - 8px); max-width: calc(50% - 8px); }
        .cs-col-md-8 { flex: 0 0 calc(66.667% - 6px); max-width: calc(66.667% - 6px); }
        .cs-col-md-4 { flex: 0 0 calc(33.333% - 11px); max-width: calc(33.333% - 11px); }
        .cs-col-md-4:nth-child(2) { margin-left: 0; }
        .cs-col-filter { flex: 1; min-width: 140px; }

        /* Forms */
        .cs-form-label { display: block; margin-bottom: 4px; font-size: 13px; font-weight: 500; color: #495057; }
        .cs-form-control, .cs-form-select { width: 100%; padding: 6px 10px; border: 1px solid #ced4da; border-radius: 6px; font-size: 13px; transition: border-color 0.15s; background: #fff; color: #333; box-sizing: border-box; }
        .cs-form-control:focus, .cs-form-select:focus { border-color: #80bdff; outline: none; box-shadow: 0 0 0 3px rgba(0,123,255,0.15); }
        .cs-form-control-sm { padding: 4px 8px; font-size: 12px; }
        textarea.cs-form-control { resize: vertical; font-family: inherit; }

        /* Badges */
        .cs-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; color: #fff; }
        .cs-badge.bg-info { background: #17a2b8; }
        .cs-badge.bg-secondary { background: #6c757d; }
        .cs-badge.bg-success { background: #28a745; }
        .cs-badge.bg-danger { background: #dc3545; }
        .cs-badge.bg-warning { background: #ffc107; color: #333; }
        .cs-badge.bg-primary { background: #007bff; }

        /* Buttons */
        .cs-btn { display: inline-flex; align-items: center; padding: 6px 14px; border-radius: 6px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; transition: all 0.15s; }
        .cs-btn:disabled { opacity: 0.6; cursor: not-allowed; }
        .cs-btn-primary { background: #007bff; color: #fff; border-color: #007bff; }
        .cs-btn-primary:hover:not(:disabled) { background: #0069d9; }
        .cs-btn-secondary { background: #6c757d; color: #fff; border-color: #6c757d; }
        .cs-btn-secondary:hover:not(:disabled) { background: #5a6268; }
        .cs-btn-danger { background: #dc3545; color: #fff; border-color: #dc3545; }
        .cs-btn-danger:hover:not(:disabled) { background: #c82333; }
        .cs-btn-outline-secondary { background: transparent; color: #6c757d; border-color: #6c757d; }
        .cs-btn-outline-secondary:hover:not(:disabled) { background: #6c757d; color: #fff; }
        .cs-btn-outline-warning { background: transparent; color: #e0a800; border-color: #e0a800; }
        .cs-btn-outline-warning:hover:not(:disabled) { background: #e0a800; color: #fff; }
        .cs-btn-outline-danger { background: transparent; color: #dc3545; border-color: #dc3545; }
        .cs-btn-outline-danger:hover:not(:disabled) { background: #dc3545; color: #fff; }
        .cs-btn-outline-info { background: transparent; color: #17a2b8; border-color: #17a2b8; }
        .cs-btn-outline-info:hover:not(:disabled) { background: #17a2b8; color: #fff; }
        .cs-btn-sm { padding: 3px 8px; font-size: 12px; }
        .cs-btn-lg { padding: 10px 24px; font-size: 16px; }

        /* Datalist (product search dropdown) */
        .cs-datalist { position: absolute; top: 100%; left: 0; right: 0; background: #fff; border: 1px solid #ced4da; border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.12); z-index: 100; max-height: 200px; overflow-y: auto; }
        .cs-datalist-item { padding: 8px 12px; cursor: pointer; font-size: 13px; border-bottom: 1px solid #f0f0f0; }
        .cs-datalist-item:last-child { border-bottom: none; }
        .cs-datalist-item:hover { background: #e9ecef; }

        /* Staged cards */
        .cs-staged-card { border: 2px solid; border-radius: 8px; margin-bottom: 8px; padding: 8px 12px; }
        .cs-staged-stockin { border-color: #b8daff; background: #f0f7ff; }
        .cs-staged-stockout { border-color: #f8d7da; background: #fff5f5; }
        .cs-staged-body { display: flex; justify-content: space-between; align-items: flex-start; }
        .cs-staged-body h6 { margin: 0 0 4px; font-size: 14px; font-weight: 600; }
        .cs-muted-small { margin: 2px 0; font-size: 12px; color: #6c757d; }

        /* Upload zone */
        .cs-upload-zone { border: 2px dashed #dee2e6; padding: 24px; text-align: center; border-radius: 8px; cursor: pointer; background: #f8f9fa; min-height: 120px; display: flex; flex-direction: column; align-items: center; justify-content: center; transition: border-color 0.2s; }
        .cs-upload-zone:hover { border-color: #28a745; }
        .cs-file-preview { margin-top: 8px; padding: 6px 12px; background: #d1ecf1; border-radius: 6px; font-size: 13px; color: #0c5460; }

        /* Collapsible header */
        .cs-collapsible { cursor: pointer; user-select: none; }
        .cs-collapsible:hover { background: #e9ecef; }
        .cs-rotate { transform: rotate(180deg); }

        /* Filter panel */
        .cs-filter-panel { border-bottom: 1px solid #dee2e6; }

        /* Empty state */
        .cs-empty-state { text-align: center; padding: 24px; color: #6c757d; }
        .cs-empty-state p { margin: 8px 0 0; font-size: 14px; }

        /* Table */
        .cs-table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .cs-table th { padding: 8px 12px; background: #f8f9fa; border-bottom: 2px solid #dee2e6; font-weight: 600; text-align: left; white-space: nowrap; }
        .cs-table td { padding: 8px 12px; border-bottom: 1px solid #eee; vertical-align: middle; }
        .cs-table tbody tr:hover { background: #f8f9fa; }
        .cs-table-active { background: #e2e6ea !important; }
        .cs-table .text-danger { color: #dc3545; }

        /* Pagination */
        .cs-pagination { margin-top: 12px; }
        .cs-pagination ul { display: flex; list-style: none; padding: 0; margin: 0; justify-content: center; gap: 4px; }
        .cs-pagination li button, .cs-pagination li span { padding: 4px 10px; border: 1px solid #dee2e6; background: #fff; border-radius: 4px; cursor: pointer; font-size: 13px; color: #007bff; }
        .cs-pagination li.active button { background: #007bff; color: #fff; border-color: #007bff; }
        .cs-pagination li.disabled button, .cs-pagination li.disabled span { color: #6c757d; cursor: not-allowed; opacity: 0.6; }

        /* Stat cards */
        .cs-stat-card { padding: 12px; border-radius: 8px; text-align: center; }
        .cs-stat-card h5 { margin: 0; font-size: 24px; font-weight: 700; }
        .cs-stat-card small { color: #6c757d; }
        .cs-stat-success { background: rgba(40,167,69,0.1); border: 1px solid rgba(40,167,69,0.3); }
        .cs-stat-success h5 { color: #28a745; }
        .cs-stat-primary { background: rgba(0,123,255,0.1); border: 1px solid rgba(0,123,255,0.3); }
        .cs-stat-primary h5 { color: #007bff; }
        .cs-stat-danger { background: rgba(220,53,69,0.1); border: 1px solid rgba(220,53,69,0.3); }
        .cs-stat-danger h5 { color: #dc3545; }

        /* Modal */
        .cs-modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1050; animation: csFadeIn 0.15s ease; }
        .cs-modal { background: #fff; border-radius: 12px; width: 480px; max-width: 90vw; max-height: 90vh; overflow-y: auto; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
        .cs-modal-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; border-bottom: 1px solid #dee2e6; }
        .cs-modal-header h5 { margin: 0; font-size: 16px; font-weight: 600; }
        .cs-modal-close { background: none; border: none; font-size: 22px; cursor: pointer; color: #6c757d; padding: 0; line-height: 1; }
        .cs-modal-close:hover { color: #333; }
        .cs-modal-body { padding: 20px; }
        .cs-modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 20px; border-top: 1px solid #dee2e6; }

        /* Responsive */
        @media (max-width: 992px) {
          .cs-col-lg-6 { flex: 0 0 100%; max-width: 100%; }
        }
        @media (max-width: 768px) {
          .cs-col-md-6, .cs-col-md-8, .cs-col-md-4 { flex: 0 0 100%; max-width: 100%; }
          .cs-page-root { padding: 8px 12px; }
        }
      `}</style>
    </div>
  );
}
