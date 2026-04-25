"use client";

import { useState, useMemo, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post, del } from "@/lib/api-client";

// ============ Types ============

interface Product {
  id: number;
  name: string;
  barcode: string;
  price: number;
  image: string;
}

export interface ProductListResult {
  success: boolean;
  data: Product[];
  total: number;
  page: number;
  per_page: number;
}

interface BomItem {
  id?: number;
  material_name: string;
  specification: string;
  unit: string;
  supplier: string;
  quantity_per_sku: number;
  note: string;
  category: string;
}

const BOM_CATEGORIES = [
  { key: "fabric", label: "面料类", icon: "fa-scroll" },
  { key: "filling", label: "填充类", icon: "fa-cloud" },
  { key: "accessory", label: "辅料类", icon: "fa-puzzle-piece" },
];

const EMPTY_BOM_ITEM: BomItem = {
  material_name: "", specification: "", unit: "", supplier: "",
  quantity_per_sku: 0, note: "", category: "fabric",
};

interface ProductListContentProps {
  initialData?: ProductListResult;
}

export function ProductListContent({ initialData }: ProductListContentProps) {
  const qc = useQueryClient();

  // Form state
  const [formName, setFormName] = useState("");
  const [formBarcode, setFormBarcode] = useState("");
  const [formPrice, setFormPrice] = useState("");
  const [formImage, setFormImage] = useState("");

  // List state
  const [searchTerm, setSearchTerm] = useState("");
  const [sortOrder, setSortOrder] = useState("name-asc");
  const [page, setPage] = useState(1);
  const perPage = 20;

  // BOM modal state
  const [bomOpen, setBomOpen] = useState(false);
  const [bomProductId, setBomProductId] = useState<number | null>(null);
  const [bomProductName, setBomProductName] = useState("");
  const [bomTab, setBomTab] = useState("fabric");
  const [bomItems, setBomItems] = useState<BomItem[]>([]);
  const [bomCopySearch, setBomCopySearch] = useState("");
  const [bomCopyResults, setBomCopyResults] = useState<Product[]>([]);
  const [bomCopySourceId, setBomCopySourceId] = useState<number | null>(null);
  const [bomCopyOverwrite, setBomCopyOverwrite] = useState(false);

  // Image modal state
  const [imageModalSrc, setImageModalSrc] = useState("");
  const [imageModalName, setImageModalName] = useState("");
  const [imageModalOpen, setImageModalOpen] = useState(false);

  // Excel upload state
  const [excelFile, setExcelFile] = useState<File | null>(null);
  const [excelPreview, setExcelPreview] = useState<string>("");

  // File refs
  const excelInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  // Data queries
  const { data, isLoading } = useQuery({
    queryKey: ["products-list", page],
    queryFn: () => get<ProductListResult>("/products/list", {
      page: String(page), per_page: String(perPage),
    }),
    initialData: initialData && page === 1 ? initialData : undefined,
  });

  const products = data?.data ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / perPage) || 1;

  // Filter & sort client-side
  const filtered = useMemo(() => {
    let list = [...products];
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      list = list.filter(p => p.name.toLowerCase().includes(q) || (p.barcode || "").toLowerCase().includes(q));
    }
    list.sort((a, b) => {
      if (sortOrder === "name-asc") return a.name.localeCompare(b.name);
      if (sortOrder === "name-desc") return b.name.localeCompare(a.name);
      return 0;
    });
    return list;
  }, [products, searchTerm, sortOrder]);

  // Mutations
  const createMutation = useMutation({
    mutationFn: () => post<{ success: boolean; message?: string }>("/products/create", {
      name: formName, barcode: formBarcode, price: formPrice ? parseFloat(formPrice) : undefined, image: formImage || undefined,
    }),
    onSuccess: (res) => { alert(res.message || "添加成功"); setFormName(""); setFormBarcode(""); setFormPrice(""); setFormImage(""); qc.invalidateQueries({ queryKey: ["products-list"] }); },
    onError: (err: Error) => alert(err.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => del<{ success: boolean; error?: string }>(`/products/delete/${id}`),
    onSuccess: (res) => { if (res.success) { qc.invalidateQueries({ queryKey: ["products-list"] }); } else { alert(res.error || "删除失败"); } },
    onError: (err: Error) => alert(err.message),
  });

  const batchImportMutation = useMutation({
    mutationFn: (formData: FormData) => fetch("/api/v1/batch/import-products", { method: "POST", body: formData, credentials: "include" }).then(r => r.json()),
    onSuccess: () => { alert("批量导入成功"); setExcelFile(null); setExcelPreview(""); qc.invalidateQueries({ queryKey: ["products-list"] }); },
    onError: (err: Error) => alert(err.message),
  });

  const saveBomMutation = useMutation({
    mutationFn: () => post<{ success: boolean; message?: string }>(`/products/bom/${bomProductId}`, { items: bomItems }),
    onSuccess: (res) => { alert(res.message || "BOM保存成功"); setBomOpen(false); },
    onError: (err: Error) => alert(err.message),
  });

  // BOM queries
  const { data: bomData } = useQuery({
    queryKey: ["bom", bomProductId],
    queryFn: () => get<{ success: boolean; items: BomItem[] }>(`/products/bom/${bomProductId}`),
    enabled: !!bomProductId && bomOpen,
  });

  // Load BOM data when modal opens
  useMemo(() => {
    if (bomData?.items) setBomItems(bomData.items);
  }, [bomData]);

  // Image upload handler
  async function handleImageUpload(file: File) {
    const allowed = ["image/jpeg", "image/jpg", "image/png", "image/gif"];
    if (!allowed.includes(file.type)) { alert("仅支持 JPG/PNG/GIF 格式"); return; }
    if (file.size > 5 * 1024 * 1024) { alert("文件大小不能超过 5MB"); return; }
    const formData = new FormData();
    formData.append("file", file);
    try {
      const csrfToken = document.cookie.match(/fastapi_csrf_token=([^;]+)/)?.[1];
      const res = await fetch("/api/v1/auth/upload", {
        method: "POST",
        headers: csrfToken ? { "X-CSRF-Token": decodeURIComponent(csrfToken) } : {},
        credentials: "include",
        body: formData,
      });
      const data = await res.json() as { success: boolean; url: string };
      if (data.success && data.url) setFormImage(data.url);
      else alert("上传失败");
    } catch { alert("上传失败"); }
  }

  // Excel upload handler
  function handleExcelSelect(file: File) {
    if (!file.name.match(/\.(xlsx|xls)$/i)) { alert("仅支持 Excel 文件"); return; }
    setExcelFile(file);
    setExcelPreview(`已选择: ${file.name}`);
  }

  function handleBatchImport() {
    if (!excelFile) return;
    const formData = new FormData();
    formData.append("file", excelFile);
    batchImportMutation.mutate(formData);
  }

  // BOM functions
  function openBomModal(productId: number, productName: string) {
    setBomProductId(productId);
    setBomProductName(productName);
    setBomTab("fabric");
    setBomItems([]);
    setBomOpen(true);
  }

  function addBomItem() {
    setBomItems(prev => [...prev, { ...EMPTY_BOM_ITEM, category: bomTab }]);
  }

  function removeBomItem(index: number) {
    setBomItems(prev => prev.filter((_, i) => i !== index));
  }

  function updateBomItem(index: number, field: keyof BomItem, value: string | number) {
    setBomItems(prev => prev.map((item, i) => i === index ? { ...item, [field]: value } : item));
  }

  const currentBomItems = useMemo(() => bomItems.filter(item => item.category === bomTab), [bomItems, bomTab]);

  // BOM copy
  async function searchProductForCopy() {
    if (!bomCopySearch.trim()) return;
    const res = await get<{ success: boolean; data: Product[] }>("/products/search", { keyword: bomCopySearch });
    if (res?.data) setBomCopyResults(res.data);
  }

  async function confirmCopyBom() {
    if (!bomCopySourceId) return;
    const res = await get<{ success: boolean; items: BomItem[] }>(`/products/bom/${bomCopySourceId}`);
    if (res?.items) {
      const newItems = res.items.map(item => ({ ...item, category: item.category || bomTab }));
      if (bomCopyOverwrite) {
        setBomItems(newItems);
      } else {
        setBomItems(prev => [...prev, ...newItems]);
      }
      setBomCopySearch("");
      setBomCopyResults([]);
      setBomCopySourceId(null);
    }
  }

  return (
    <div className="pl-page-root">
      <div className="container-fluid px-4 py-6">
        <div className="mb-8">
          <div className="d-flex align-items-center gap-4">
            <div className="flex-grow-1">
              <h1 className="page-title mb-2">产品管理</h1>
              <p className="page-subtitle">管理产品基础信息、批量导入和图片上传</p>
            </div>
          </div>
        </div>

        <div className="row g-6">
          {/* Left Sidebar */}
          <div className="col-xl-4 col-lg-5">
            <div className="sticky-panel">
              {/* Add Product Card */}
              <div className="card-elegant mb-5">
                <div className="card-header-elegant">
                  <div className="d-flex align-items-center gap-3">
                    <div className="icon-circle icon-circle-blue"><i className="fas fa-box"></i></div>
                    <div><h3 className="card-title-elegant mb-0">产品基本信息</h3></div>
                  </div>
                </div>
                <div className="card-body-elegant pt-5">
                  <form onSubmit={e => { e.preventDefault(); if (formName) createMutation.mutate(); }}>
                    <div className="form-group-spacious">
                      <label className="form-label-elegant">产品名称</label>
                      <div className="input-wrapper">
                        <i className="fas fa-tag input-icon"></i>
                        <input type="text" className="form-control form-control-elegant" value={formName} onChange={e => setFormName(e.target.value)} required placeholder="例如：小熊毛绒玩具" />
                      </div>
                    </div>
                    <div className="form-group-spacious">
                      <label className="form-label-elegant">69码</label>
                      <div className="input-wrapper">
                        <i className="fas fa-barcode input-icon"></i>
                        <input type="text" className="form-control form-control-elegant" value={formBarcode} onChange={e => setFormBarcode(e.target.value)} placeholder="例如：6958085574210" />
                      </div>
                    </div>
                    <div className="form-group-spacious">
                      <label className="form-label-elegant">产品价格</label>
                      <div className="input-wrapper">
                        <i className="fas fa-yen-sign input-icon"></i>
                        <input type="number" className="form-control form-control-elegant" value={formPrice} onChange={e => setFormPrice(e.target.value)} step="0.01" min="0" placeholder="请输入产品价格" />
                      </div>
                    </div>
                    <div className="pt-2">
                      <button type="submit" className="btn btn-primary btn-elegant w-100 btn-lg" disabled={!formName || createMutation.isPending} style={{ padding: "1rem 1.5rem", fontSize: "1rem" }}>
                        <i className="fas fa-plus" style={{ marginRight: 8 }}></i>{createMutation.isPending ? "添加中..." : "添加产品"}
                      </button>
                    </div>
                  </form>
                </div>
              </div>

              {/* Upload Card */}
              <div className="card-elegant">
                <div className="card-header-elegant">
                  <div className="d-flex align-items-center gap-3">
                    <div className="icon-circle icon-circle-green"><i className="fas fa-cloud-upload-alt"></i></div>
                    <div className="flex-grow-1">
                      <h3 className="card-title-elegant mb-0">产品上传管理</h3>
                      <p className="card-subtitle-elegant mb-0">批量上传和图片上传</p>
                    </div>
                  </div>
                </div>
                <div className="card-body-elegant pt-5">
                  <div className="upload-section-spacious">
                    <div className="row g-4">
                      <div className="col-12">
                        <div className="upload-card upload-card-excel">
                          <div className="upload-card-header">
                            <i className="fas fa-file-excel upload-card-icon"></i>
                            <h4 className="upload-card-title mb-0">产品批量上传</h4>
                          </div>
                          <div className="upload-zone-elegant" onClick={() => excelInputRef.current?.click()} tabIndex={0} role="button" aria-label="上传 Excel 文件">
                            <div className="upload-zone-content-elegant">
                              <i className="fas fa-cloud-upload-alt upload-icon-big mb-3"></i>
                              <p className="upload-text mb-1">拖拽 Excel 文件到这里</p>
                              <p className="upload-subtext mb-0">或点击选择文件</p>
                            </div>
                            <input ref={excelInputRef} type="file" style={{ display: "none" }} accept=".xlsx,.xls" onChange={e => { const f = e.target.files?.[0]; if (f) handleExcelSelect(f); }} />
                          </div>
                          {excelPreview && <div className="mt-3" style={{ fontSize: 14, color: "#475569" }}>{excelPreview}</div>}
                          <div className="upload-actions mt-4">
                            <a href="/api/v1/batch/download-template" className="btn btn-outline-secondary btn-elegant btn-sm">
                              <i className="fas fa-download" style={{ marginRight: 8 }}></i>下载模板
                            </a>
                            <button className="btn btn-success btn-elegant btn-sm" disabled={!excelFile || batchImportMutation.isPending} onClick={handleBatchImport}>
                              <i className="fas fa-upload" style={{ marginRight: 8 }}></i>{batchImportMutation.isPending ? "导入中..." : "开始导入"}
                            </button>
                          </div>
                        </div>
                      </div>
                      <div className="col-12">
                        <div className="upload-card upload-card-image">
                          <div className="upload-card-header">
                            <i className="fas fa-image upload-card-icon"></i>
                            <h4 className="upload-card-title mb-0">产品图片上传</h4>
                          </div>
                          <div className="upload-zone-elegant" onClick={() => imageInputRef.current?.click()} tabIndex={0} role="button" aria-label="上传产品图片">
                            <div className="upload-zone-content-elegant">
                              <i className="fas fa-plus upload-icon-big mb-3"></i>
                              <p className="upload-text mb-1">拖拽图片到这里</p>
                              <p className="upload-subtext mb-0">或点击选择图片</p>
                            </div>
                            <input ref={imageInputRef} type="file" style={{ display: "none" }} accept="image/*" onChange={e => { const f = e.target.files?.[0]; if (f) handleImageUpload(f); }} />
                          </div>
                          {formImage && (
                            <div className="mt-4">
                              <img src={formImage} alt="预览" style={{ maxWidth: 200, maxHeight: 200, objectFit: "contain", borderRadius: 8 }} />
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Right Main Content */}
          <div className="col-xl-8 col-lg-7">
            <div className="card-elegant">
              <div className="card-header-elegant">
                <div className="d-flex align-items-center justify-content-between flex-wrap gap-4">
                  <div className="d-flex align-items-center gap-3">
                    <div className="icon-circle icon-circle-blue"><i className="fas fa-list"></i></div>
                    <div><h3 className="card-title-elegant mb-0">产品列表</h3></div>
                  </div>
                  <div className="d-flex gap-3 flex-wrap">
                    <div className="search-box-elegant">
                      <i className="fas fa-search search-icon-elegant"></i>
                      <input type="text" className="form-control search-input-elegant" placeholder="搜索产品名称或69码..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)} />
                    </div>
                    <select className="form-select sort-select-elegant" value={sortOrder} onChange={e => setSortOrder(e.target.value)}>
                      <option value="name-asc">名称 A-Z</option>
                      <option value="name-desc">名称 Z-A</option>
                    </select>
                  </div>
                </div>
              </div>
              <div className="card-body-elegant p-0">
                <div className="table-container-elegant">
                  <table className="table table-elegant">
                    <thead className="thead-elegant">
                      <tr>
                        <th className="th-image">产品图片</th>
                        <th className="th-name">产品名称</th>
                        <th className="th-barcode">69码</th>
                        <th className="th-price">产品价格</th>
                        <th className="th-actions">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {isLoading ? (
                        <tr><td colSpan={5} className="text-center py-8">加载中...</td></tr>
                      ) : filtered.length === 0 ? (
                        <tr><td colSpan={5} className="text-center py-8"><div className="empty-state-elegant"><i className="fas fa-inbox empty-icon-elegant mb-4"></i><p className="empty-text-elegant mb-0">暂无产品，请先添加</p></div></td></tr>
                      ) : filtered.map(p => (
                        <tr key={p.id} className="tr-elegant">
                          <td>
                            {p.image ? (
                              <div className="product-image-container" role="button" tabIndex={0} onClick={() => { setImageModalSrc(p.image); setImageModalName(p.name); setImageModalOpen(true); }}>
                                <img src={p.image} className="product-thumbnail-elegant" alt={p.name} onError={e => { (e.target as HTMLImageElement).style.display = "none"; }} />
                                <div className="no-image-elegant"><i className="fas fa-image"></i></div>
                              </div>
                            ) : (
                              <div className="product-image-container"><div className="no-image-elegant"><i className="fas fa-image"></i></div></div>
                            )}
                          </td>
                          <td><span className="product-name-elegant">{p.name}</span></td>
                          <td><span className="product-barcode-text">{p.barcode || "-"}</span></td>
                          <td><span className="product-price-text">¥{(p.price || 0).toFixed(2)}</span></td>
                          <td>
                            <div className="action-buttons-elegant">
                              {p.image && (
                                <button className="btn-action btn-action-view" title="查看图片" onClick={() => { setImageModalSrc(p.image); setImageModalName(p.name); setImageModalOpen(true); }}>
                                  <i className="fas fa-eye"></i>
                                </button>
                              )}
                              <button className="btn-action btn-action-bom" title="配置BOM表" onClick={() => openBomModal(p.id, p.name)}>
                                <i className="fas fa-cogs"></i>
                              </button>
                              <a href={`/product/${p.id}`} className="btn-action btn-action-edit" title="编辑"><i className="fas fa-edit"></i></a>
                              <button className="btn-action btn-action-delete" title="删除" onClick={() => { if (confirm(`确定删除产品"${p.name}"吗？`)) deleteMutation.mutate(p.id); }}>
                                <i className="fas fa-trash"></i>
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="pagination-wrapper-elegant">
                    <div className="d-flex justify-content-between align-items-center flex-wrap gap-4 px-6 py-5">
                      <div className="pagination-info-elegant">
                        <span>显示 {(page - 1) * perPage + 1}-{Math.min(page * perPage, total)} 条，共 {total} 条</span>
                      </div>
                      <nav>
                        <ul className="pagination pagination-elegant mb-0">
                          <li className={`page-item ${page <= 1 ? "disabled" : ""}`}>
                            <button className="page-link" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}>‹</button>
                          </li>
                          {Array.from({ length: totalPages }, (_, i) => i + 1).slice(Math.max(0, page - 3), page + 2).map(p => (
                            <li key={p} className={`page-item ${p === page ? "active" : ""}`}>
                              <button className="page-link" onClick={() => setPage(p)}>{p}</button>
                            </li>
                          ))}
                          <li className={`page-item ${page >= totalPages ? "disabled" : ""}`}>
                            <button className="page-link" onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>›</button>
                          </li>
                        </ul>
                      </nav>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Image Modal */}
      {imageModalOpen && (
        <div className="modal-overlay" onClick={() => setImageModalOpen(false)}>
          <div className="modal-content-elegant" onClick={e => e.stopPropagation()} style={{ maxWidth: 900, width: "90vw" }}>
            <div className="modal-header-elegant">
              <h5 className="modal-title-elegant">{imageModalName} - 产品图片</h5>
              <button className="btn-close-elegant" onClick={() => setImageModalOpen(false)}><i className="fas fa-times"></i></button>
            </div>
            <div className="modal-body-elegant">
              <img src={imageModalSrc} className="modal-image-elegant" alt={imageModalName} />
            </div>
          </div>
        </div>
      )}

      {/* BOM Modal */}
      {bomOpen && (
        <div className="modal-overlay" onClick={() => setBomOpen(false)}>
          <div className="bom-modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 1400, width: "95vw" }}>
            <div className="bom-modal-header">
              <div className="bom-modal-header-left">
                <h5 className="bom-modal-title">
                  <i className="fas fa-cogs" style={{ marginRight: 8 }}></i>
                  <span>{bomProductName} - BOM表配置</span>
                </h5>
              </div>
              <button className="bom-modal-close" onClick={() => setBomOpen(false)}><i className="fas fa-times"></i></button>
            </div>
            <div className="bom-modal-body">
              {/* BOM Tabs */}
              <div className="bom-tabs-container">
                {BOM_CATEGORIES.map(cat => (
                  <button key={cat.key} className={`bom-tab-v2 ${bomTab === cat.key ? "active" : ""}`} onClick={() => setBomTab(cat.key)}>
                    <i className={`fas ${cat.icon}`}></i> {cat.label}
                  </button>
                ))}
              </div>

              <div className="bom-main-content">
                {/* Summary Bar */}
                <div className="bom-summary-bar">
                  <div className="bom-summary-left">
                    <span className="bom-summary-text"><i className="fas fa-list" style={{ marginRight: 8 }}></i>{BOM_CATEGORIES.find(c => c.key === bomTab)?.label}物料清单</span>
                    <span className="bom-summary-count">物料总数：<span style={{ fontSize: 20, fontWeight: 700, color: "#87CEEB" }}>{currentBomItems.length}</span></span>
                  </div>
                  <div className="d-flex gap-2" style={{ flex: 1, maxWidth: 400, margin: "0 20px", position: "relative" }}>
                    <div className="input-wrapper" style={{ flex: 1 }}>
                      <i className="fas fa-search input-icon"></i>
                      <input type="text" className="form-control form-control-elegant" placeholder="输入产品名称，复制BOM" value={bomCopySearch} onChange={e => setBomCopySearch(e.target.value)} onKeyDown={e => { if (e.key === "Enter") searchProductForCopy(); }} />
                    </div>
                    {bomCopyResults.length > 0 && (
                      <div className="autocomplete-dropdown">
                        {bomCopyResults.map(p => (
                          <div key={p.id} className={`autocomplete-item ${bomCopySourceId === p.id ? "selected" : ""}`} onClick={() => setBomCopySourceId(p.id)}>
                            <div className="item-left">
                              <div className="product-name">{p.name}</div>
                              <div className="product-info"><span className="barcode">{p.barcode || "-"}</span></div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="d-flex gap-2">
                    <button className="bom-btn-copy-v2" onClick={confirmCopyBom} disabled={!bomCopySourceId}>
                      <i className="fas fa-copy" style={{ marginRight: 8 }}></i>复制BOM
                    </button>
                    <button className="bom-btn-add-v2" onClick={addBomItem}>
                      <i className="fas fa-plus" style={{ marginRight: 8 }}></i>添加物料
                    </button>
                  </div>
                </div>

                {/* BOM Content Area */}
                <div className="bom-content-area">
                  {currentBomItems.length > 0 ? (
                    <div className="bom-table-container-v2">
                      <div className="bom-table-wrapper-v2">
                        <table className="bom-table-v2">
                          <thead className="bom-table-header-v2">
                            <tr>
                              <th style={{ width: 200 }}>物料名称 <span className="required">*</span></th>
                              <th style={{ width: 180 }}>规格型号 <span className="required">*</span></th>
                              <th style={{ width: 120 }}>计量单位 <span className="required">*</span></th>
                              <th style={{ width: 200 }}>默认供应商 <span className="required">*</span></th>
                              <th style={{ width: 140 }}>单SKU用量</th>
                              <th style={{ width: 200 }}>备注</th>
                              <th style={{ width: 80 }}>操作</th>
                            </tr>
                          </thead>
                          <tbody>
                            {currentBomItems.map((item, idx) => {
                              const globalIdx = bomItems.indexOf(item);
                              return (
                                <tr key={globalIdx}>
                                  <td><input className="bom-table-input" value={item.material_name} onChange={e => updateBomItem(globalIdx, "material_name", e.target.value)} /></td>
                                  <td><input className="bom-table-input" value={item.specification} onChange={e => updateBomItem(globalIdx, "specification", e.target.value)} /></td>
                                  <td><input className="bom-table-input" value={item.unit} onChange={e => updateBomItem(globalIdx, "unit", e.target.value)} /></td>
                                  <td><input className="bom-table-input" value={item.supplier} onChange={e => updateBomItem(globalIdx, "supplier", e.target.value)} /></td>
                                  <td><input className="bom-table-input" type="number" value={item.quantity_per_sku} onChange={e => updateBomItem(globalIdx, "quantity_per_sku", parseFloat(e.target.value) || 0)} /></td>
                                  <td><input className="bom-table-input" value={item.note} onChange={e => updateBomItem(globalIdx, "note", e.target.value)} /></td>
                                  <td><button className="bom-table-action-btn delete" onClick={() => removeBomItem(globalIdx)}>删除</button></td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ) : (
                    <div className="bom-empty-state-v2">
                      <div className="bom-empty-icon"><i className="fas fa-inbox"></i></div>
                      <div className="bom-empty-text">
                        <p className="bom-empty-title">暂无物料</p>
                        <p className="bom-empty-hint">点击"添加物料"按钮开始配置</p>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
            <div className="bom-modal-footer">
              <button className="bom-btn-cancel" onClick={() => setBomOpen(false)}>取消</button>
              <button className="bom-btn-save" onClick={() => saveBomMutation.mutate()} disabled={saveBomMutation.isPending}>
                <i className="fas fa-save" style={{ marginRight: 8 }}></i>{saveBomMutation.isPending ? "保存中..." : "保存BOM"}
              </button>
            </div>
          </div>
        </div>
      )}

      <style jsx global>{`
        /* Page-level */
        .pl-page-root .container-fluid { padding: 0 16px; }
        .pl-page-root .page-title { font-size: 2rem; font-weight: 600; color: #1a1a2e; line-height: 1.2; letter-spacing: -0.02em; }
        .pl-page-root .page-subtitle { font-size: 1.125rem; color: #64748b; line-height: 1.5; margin: 0; }
        .pl-page-root .mb-8 { margin-bottom: 2rem; }
        .pl-page-root .g-6 { gap: 1.5rem; }

        /* Layout columns */
        .pl-page-root .row { display: flex; flex-wrap: wrap; margin: 0 -12px; }
        .pl-page-root .col-xl-4 { flex: 0 0 33.333%; max-width: 33.333%; padding: 0 12px; }
        .pl-page-root .col-xl-8 { flex: 0 0 66.666%; max-width: 66.666%; padding: 0 12px; }
        .pl-page-root .col-lg-5 { padding: 0 12px; }
        .pl-page-root .col-lg-7 { padding: 0 12px; }
        .pl-page-root .col-12 { padding: 0 12px; }
        .pl-page-root .g-4 { gap: 1rem; }

        /* Sticky panel */
        .pl-page-root .sticky-panel { position: sticky; top: 100px; }

        /* Card elegant */
        .pl-page-root .card-elegant { background: #fff; border-radius: 20px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06); transition: all 0.4s cubic-bezier(0.4,0,0.2,1); overflow: hidden; }
        .pl-page-root .card-elegant:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 16px 48px rgba(0,0,0,0.12); transform: translateY(-2px); }
        .pl-page-root .card-header-elegant { padding: 1.75rem 2rem; background: linear-gradient(135deg, #f8fafc, #fff); border-bottom: 1px solid #f1f5f9; }
        .pl-page-root .card-title-elegant { font-size: 1.125rem; font-weight: 600; color: #1e293b; line-height: 1.3; }
        .pl-page-root .card-subtitle-elegant { font-size: 0.875rem; color: #64748b; line-height: 1.4; }
        .pl-page-root .card-body-elegant { padding: 2rem; }
        .pl-page-root .mb-5 { margin-bottom: 1.5rem; }

        /* Icon circles */
        .pl-page-root .icon-circle { width: 44px; height: 44px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 1.25rem; }
        .pl-page-root .icon-circle-blue { background: linear-gradient(135deg, #dbeafe, #bfdbfe); color: #1d4ed8; }
        .pl-page-root .icon-circle-green { background: linear-gradient(135deg, #dcfce7, #bbf7d0); color: #15803d; }

        /* Forms */
        .pl-page-root .form-group-spacious { margin-bottom: 2rem; }
        .pl-page-root .form-label-elegant { display: block; font-size: 0.9375rem; font-weight: 500; color: #334155; margin-bottom: 0.75rem; line-height: 1.4; }
        .pl-page-root .input-wrapper { position: relative; }
        .pl-page-root .input-icon { position: absolute; left: 1rem; top: 50%; transform: translateY(-50%); color: #94a3b8; font-size: 1rem; z-index: 10; }
        .pl-page-root .form-control-elegant { width: 100%; padding: 0.875rem 1rem 0.875rem 3rem; font-size: 1rem; line-height: 1.5; color: #1e293b; background: #f8fafc; border: 2px solid #e2e8f0; border-radius: 14px; transition: all 0.3s ease; }
        .pl-page-root .form-control-elegant:focus { background: #fff; border-color: #3b82f6; box-shadow: 0 0 0 4px rgba(59,130,246,0.1); outline: none; }

        /* Buttons */
        .pl-page-root .btn-elegant { padding: 0.75rem 1.25rem; font-size: 0.9375rem; font-weight: 500; border-radius: 12px; border: 2px solid transparent; transition: all 0.3s ease; display: inline-flex; align-items: center; gap: 0.5rem; cursor: pointer; }
        .pl-page-root .btn-elegant:hover { transform: translateY(-1px); }
        .pl-page-root .btn-primary:disabled { opacity: 0.65; cursor: not-allowed; transform: none; }
        .pl-page-root .btn-success:disabled { opacity: 0.65; cursor: not-allowed; }
        .pl-page-root .mb-8 { margin-bottom: 2rem; }

        /* Upload cards */
        .pl-page-root .upload-section-spacious { padding: 0.5rem 0; }
        .pl-page-root .upload-card { background: #f8fafc; border-radius: 18px; padding: 1.5rem; border: 1px solid #e2e8f0; transition: all 0.3s ease; }
        .pl-page-root .upload-card:hover { border-color: #cbd5e1; background: #fff; }
        .pl-page-root .upload-card-excel { border-top: 3px solid #22c55e; }
        .pl-page-root .upload-card-image { border-top: 3px solid #3b82f6; }
        .pl-page-root .upload-card-header { display: flex; align-items: center; gap: .75rem; margin-bottom: 1.25rem; }
        .pl-page-root .upload-card-icon { font-size: 1.5rem; }
        .pl-page-root .upload-card-excel .upload-card-icon { color: #22c55e; }
        .pl-page-root .upload-card-image .upload-card-icon { color: #3b82f6; }
        .pl-page-root .upload-card-title { font-size: 1rem; font-weight: 600; color: #1e293b; }
        .pl-page-root .upload-zone-elegant { border: 2px dashed #cbd5e1; border-radius: 16px; padding: 2.5rem 1.5rem; text-align: center; background: #fff; cursor: pointer; transition: all 0.3s ease; }
        .pl-page-root .upload-zone-elegant:hover { border-color: #3b82f6; background: linear-gradient(135deg, #eff6ff, #f8fafc); transform: translateY(-2px); }
        .pl-page-root .upload-zone-content-elegant { display: flex; flex-direction: column; align-items: center; justify-content: center; }
        .pl-page-root .upload-icon-big { font-size: 2.5rem; color: #94a3b8; }
        .pl-page-root .upload-text { font-size: 1rem; color: #475569; font-weight: 500; margin: 0; }
        .pl-page-root .upload-subtext { font-size: 0.875rem; color: #94a3b8; margin: 0; }
        .pl-page-root .upload-actions { display: flex; gap: .75rem; justify-content: space-between; }
        .pl-page-root .mt-3 { margin-top: .75rem; }
        .pl-page-root .mt-4 { margin-top: 1rem; }

        /* Table styles */
        .pl-page-root .table-container-elegant { max-height: calc(100vh - 320px); overflow-y: auto; }
        .pl-page-root .table-elegant { width: 100%; margin-bottom: 0; }
        .pl-page-root .thead-elegant { background: #f8fafc; position: sticky; top: 0; z-index: 10; }
        .pl-page-root .thead-elegant th { padding: 1rem 1.5rem; font-size: .875rem; font-weight: 600; color: #475569; text-transform: uppercase; letter-spacing: .05em; border-bottom: 2px solid #e2e8f0; }
        .pl-page-root .th-image { width: 120px; }
        .pl-page-root .th-name { width: auto; }
        .pl-page-root .th-barcode { width: 140px; }
        .pl-page-root .th-price { width: 110px; }
        .pl-page-root .th-actions { width: 160px; }
        .pl-page-root .tr-elegant { transition: all 0.2s ease; border-bottom: 1px solid #f1f5f9; animation: fadeInUp 0.4s ease forwards; }
        .pl-page-root .tr-elegant:hover { background: linear-gradient(135deg, #f8fafc, #fff); }
        .pl-page-root .tr-elegant td { padding: 1.25rem 1.5rem; vertical-align: middle; font-size: .9375rem; color: #334155; }
        .pl-page-root .tr-elegant:nth-child(1) { animation-delay: .05s; }
        .pl-page-root .tr-elegant:nth-child(2) { animation-delay: .1s; }
        .pl-page-root .tr-elegant:nth-child(3) { animation-delay: .15s; }

        /* Product image */
        .pl-page-root .product-image-container { width: 80px; height: 80px; border-radius: 16px; overflow: hidden; cursor: pointer; transition: all 0.3s ease; background: linear-gradient(135deg, #f8fafc, #f1f5f9); }
        .pl-page-root .product-image-container:hover { transform: scale(1.05); box-shadow: 0 8px 24px rgba(0,0,0,0.15); }
        .pl-page-root .product-thumbnail-elegant { width: 100%; height: 100%; object-fit: contain; }
        .pl-page-root .no-image-elegant { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #f1f5f9, #e2e8f0); color: #94a3b8; font-size: 1.5rem; }
        .pl-page-root .product-name-elegant { font-size: 1rem; font-weight: 500; color: #1e293b; }
        .pl-page-root .product-barcode-text { font-size: .875rem; color: #64748b; font-family: Consolas, Monaco, monospace; }
        .pl-page-root .product-price-text { font-size: .9375rem; font-weight: 600; color: #dc2626; }

        /* Action buttons */
        .pl-page-root .action-buttons-elegant { display: flex; gap: .5rem; }
        .pl-page-root .btn-action { width: 44px; height: 44px; border-radius: 12px; border: none; display: flex; align-items: center; justify-content: center; font-size: 1rem; transition: all 0.2s ease; cursor: pointer; }
        .pl-page-root .btn-action-view { background: #dbeafe; color: #1d4ed8; }
        .pl-page-root .btn-action-view:hover { background: #bfdbfe; transform: scale(1.1); }
        .pl-page-root .btn-action-bom { background: linear-gradient(135deg, #B0E0E6, #87CEEB); color: #2c5282; }
        .pl-page-root .btn-action-bom:hover { background: linear-gradient(135deg, #87CEEB, #5DADE2); transform: translateY(-2px); box-shadow: 0 4px 12px rgba(135,206,235,0.4); }
        .pl-page-root .btn-action-edit { background: #fef3c7; color: #b45309; }
        .pl-page-root .btn-action-edit:hover { background: #fde68a; transform: scale(1.1); }
        .pl-page-root .btn-action-delete { background: #fee2e2; color: #dc2626; }
        .pl-page-root .btn-action-delete:hover { background: #fecaca; transform: scale(1.1); }

        /* Empty & Pagination */
        .pl-page-root .empty-state-elegant { padding: 4rem 2rem; }
        .pl-page-root .empty-icon-elegant { font-size: 4rem; color: #cbd5e1; }
        .pl-page-root .empty-text-elegant { font-size: 1.125rem; color: #64748b; }
        .pl-page-root .text-center { text-align: center; }
        .pl-page-root .py-8 { padding-top: 2rem; padding-bottom: 2rem; }
        .pl-page-root .pagination-wrapper-elegant { background: #fff; border-top: 1px solid #f1f5f9; }
        .pl-page-root .pagination-info-elegant { font-size: .9375rem; color: #64748b; }
        .pl-page-root .pagination-elegant { display: flex; list-style: none; padding: 0; gap: 4px; }
        .pl-page-root .pagination-elegant .page-link { width: 44px; height: 44px; border-radius: 10px; border: 2px solid #e2e8f0; color: #475569; font-weight: 500; display: flex; align-items: center; justify-content: center; transition: all 0.2s ease; cursor: pointer; background: #fff; }
        .pl-page-root .pagination-elegant .page-link:hover { background: #f1f5f9; border-color: #cbd5e1; }
        .pl-page-root .pagination-elegant .page-item.active .page-link { background: linear-gradient(135deg, #3b82f6, #2563eb); border-color: #3b82f6; color: #fff; box-shadow: 0 4px 12px rgba(59,130,246,0.3); }
        .pl-page-root .pagination-elegant .page-item.disabled .page-link { opacity: .5; cursor: not-allowed; }
        .pl-page-root .px-6 { padding-left: 1.5rem; padding-right: 1.5rem; }
        .pl-page-root .py-5 { padding-top: 1.25rem; padding-bottom: 1.25rem; }

        /* Search */
        .pl-page-root .search-box-elegant { position: relative; flex: 1; min-width: 220px; }
        .pl-page-root .search-icon-elegant { position: absolute; left: 1rem; top: 50%; transform: translateY(-50%); color: #94a3b8; font-size: 1rem; z-index: 10; pointer-events: none; }
        .pl-page-root .search-input-elegant { width: 100%; padding: .75rem 1rem .75rem 3rem; font-size: .9375rem; background: #f8fafc; border: 2px solid #e2e8f0; border-radius: 12px; transition: all 0.3s ease; }
        .pl-page-root .search-input-elegant:focus { background: #fff; border-color: #3b82f6; box-shadow: 0 0 0 4px rgba(59,130,246,0.1); outline: none; }
        .pl-page-root .sort-select-elegant { padding: .75rem 1rem; font-size: .9375rem; background: #f8fafc; border: 2px solid #e2e8f0; border-radius: 12px; min-width: 140px; transition: all 0.3s ease; }
        .pl-page-root .sort-select-elegant:focus { background: #fff; border-color: #3b82f6; outline: none; }

        /* Modal overlay */
        .pl-page-root .modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 1050; display: flex; align-items: center; justify-content: center; }
        .pl-page-root .modal-content-elegant { background: #fff; border-radius: 24px; border: none; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); overflow: hidden; }
        .pl-page-root .modal-header-elegant { padding: 1.5rem 2rem; background: linear-gradient(135deg, #f8fafc, #fff); border-bottom: 1px solid #f1f5f9; display: flex; justify-content: space-between; align-items: center; border-radius: 24px 24px 0 0; }
        .pl-page-root .modal-title-elegant { font-size: 1.25rem; font-weight: 600; color: #1e293b; }
        .pl-page-root .btn-close-elegant { width: 40px; height: 40px; border-radius: 10px; border: none; background: #f1f5f9; color: #64748b; display: flex; align-items: center; justify-content: center; font-size: 1.25rem; cursor: pointer; transition: all 0.2s ease; }
        .pl-page-root .btn-close-elegant:hover { background: #e2e8f0; color: #1e293b; }
        .pl-page-root .modal-body-elegant { padding: 2rem; background: #f8fafc; border-radius: 0 0 24px 24px; display: flex; align-items: center; justify-content: center; min-height: 40vh; }
        .pl-page-root .modal-image-elegant { max-width: 100%; max-height: 80vh; object-fit: contain; border-radius: 16px; box-shadow: 0 8px 24px rgba(0,0,0,0.15); }

        /* BOM Modal */
        .pl-page-root .bom-modal-content { background: #fff; border-radius: 24px; border: none; box-shadow: 0 20px 60px rgba(0,0,0,0.15); overflow: hidden; }
        .pl-page-root .bom-modal-header { display: flex; justify-content: space-between; align-items: center; padding: 24px 32px; background: linear-gradient(135deg, #f8fafc, #fff); border-bottom: 2px solid #e2e8f0; }
        .pl-page-root .bom-modal-header-left { flex: 1; }
        .pl-page-root .bom-modal-title { display: flex; align-items: center; font-size: 20px; font-weight: 700; color: #1a1a2e; margin: 0; }
        .pl-page-root .bom-modal-title i { color: #87CEEB; }
        .pl-page-root .bom-modal-close { width: 40px; height: 40px; border: none; background: #f1f5f9; border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center; color: #64748b; font-size: 18px; transition: all 0.3s ease; }
        .pl-page-root .bom-modal-close:hover { background: #e2e8f0; color: #1a1a2e; transform: rotate(90deg); }
        .pl-page-root .bom-modal-body { padding: 0; background: #f8fafc; min-height: 500px; }
        .pl-page-root .bom-tabs-container { display: flex; gap: 12px; padding: 24px 32px 16px; background: #fff; border-bottom: 2px solid #e2e8f0; }
        .pl-page-root .bom-tab-v2 { padding: 12px 24px; border: 2px solid #e2e8f0; background: #fff; border-radius: 16px; font-size: 14px; font-weight: 600; color: #5A4A4A; cursor: pointer; transition: all 0.3s ease; display: flex; align-items: center; gap: 8px; }
        .pl-page-root .bom-tab-v2:hover { border-color: #B0E0E6; background: #D4F1F4; transform: translateY(-2px); }
        .pl-page-root .bom-tab-v2.active { background: linear-gradient(135deg, #B0E0E6, #87CEEB); color: #2c5282; border-color: #87CEEB; box-shadow: 0 4px 12px rgba(135,206,235,0.3); }
        .pl-page-root .bom-main-content { padding: 24px 32px 32px; }
        .pl-page-root .bom-summary-bar { display: flex; justify-content: space-between; align-items: center; padding: 20px 24px; background: #fff; border-radius: 16px; border: 2px solid #B0E0E6; margin-bottom: 24px; }
        .pl-page-root .bom-summary-left { display: flex; align-items: center; gap: 24px; }
        .pl-page-root .bom-summary-text { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 600; color: #1a1a2e; }
        .pl-page-root .bom-summary-text i { color: #87CEEB; }
        .pl-page-root .bom-summary-count { font-size: 14px; color: #64748b; }
        .pl-page-root .bom-btn-add-v2 { padding: 12px 28px; background: linear-gradient(135deg, #A5D6A7, #81C784); color: #2E7D32; border: 2px solid #66BB6A; border-radius: 14px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.3s ease; display: flex; align-items: center; gap: 8px; }
        .pl-page-root .bom-btn-add-v2:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(129,199,132,0.4); }
        .pl-page-root .bom-btn-copy-v2 { padding: 12px 28px; background: linear-gradient(135deg, #BBDEFB, #90CAF9); color: #1565C0; border: 2px solid #64B5F6; border-radius: 14px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.3s ease; display: flex; align-items: center; gap: 8px; }
        .pl-page-root .bom-btn-copy-v2:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(100,181,246,0.4); }
        .pl-page-root .bom-btn-copy-v2:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
        .pl-page-root .bom-content-area { background: #fff; border-radius: 16px; border: 2px solid #e2e8f0; overflow: hidden; }
        .pl-page-root .bom-table-container-v2 { display: block; }
        .pl-page-root .bom-table-wrapper-v2 { overflow-x: auto; }
        .pl-page-root .bom-table-v2 { width: 100%; border-collapse: collapse; min-width: 1200px; }
        .pl-page-root .bom-table-header-v2 { background: linear-gradient(135deg, #f8fafc, #fff); }
        .pl-page-root .bom-table-header-v2 th { padding: 16px 20px; text-align: left; font-size: 13px; font-weight: 700; color: #1a1a2e; border-bottom: 2px solid #B0E0E6; white-space: nowrap; }
        .pl-page-root .bom-table-header-v2 th .required { color: #dc3545; font-weight: 700; }
        .pl-page-root .bom-table-v2 tbody tr { transition: background-color 0.2s ease; }
        .pl-page-root .bom-table-v2 tbody tr:hover { background-color: #D4F1F4; }
        .pl-page-root .bom-table-v2 tbody td { padding: 14px 20px; border-bottom: 1px solid #e2e8f0; vertical-align: middle; }
        .pl-page-root .bom-table-input { width: 100%; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 13px; transition: all 0.2s ease; }
        .pl-page-root .bom-table-input:focus { outline: none; border-color: #87CEEB; box-shadow: 0 0 0 3px rgba(135,206,235,0.2); }
        .pl-page-root .bom-table-action-btn { padding: 6px 10px; border: none; border-radius: 6px; cursor: pointer; font-size: 12px; transition: all 0.2s ease; }
        .pl-page-root .bom-table-action-btn.delete { background: linear-gradient(135deg, #EF9A9A, #E57373); color: #C62828; }
        .pl-page-root .bom-table-action-btn.delete:hover { transform: translateY(-1px); box-shadow: 0 2px 8px rgba(229,115,115,0.3); }
        .pl-page-root .bom-empty-state-v2 { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 80px 20px; text-align: center; }
        .pl-page-root .bom-empty-icon i { font-size: 64px; color: #cbd5e0; opacity: 0.6; }
        .pl-page-root .bom-empty-icon { margin-bottom: 24px; }
        .pl-page-root .bom-empty-title { font-size: 18px; font-weight: 600; color: #5A4A4A; margin: 0; }
        .pl-page-root .bom-empty-hint { font-size: 14px; color: #8B7B7B; margin: 0; }
        .pl-page-root .bom-empty-text { display: flex; flex-direction: column; gap: 8px; }
        .pl-page-root .bom-modal-footer { display: flex; justify-content: flex-end; align-items: center; gap: 12px; padding: 24px 32px; background: #fff; border-top: 2px solid #e2e8f0; }
        .pl-page-root .bom-btn-cancel { padding: 12px 28px; background: #fff; color: #5A4A4A; border: 2px solid #e2e8f0; border-radius: 14px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.3s ease; }
        .pl-page-root .bom-btn-cancel:hover { background: #f8fafc; border-color: #cbd5e0; }
        .pl-page-root .bom-btn-save { padding: 12px 28px; background: linear-gradient(135deg, #B0E0E6, #87CEEB); color: #2c5282; border: 2px solid #87CEEB; border-radius: 14px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.3s ease; display: flex; align-items: center; gap: 8px; }
        .pl-page-root .bom-btn-save:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(135,206,235,0.4); }
        .pl-page-root .bom-btn-save:disabled { opacity: .6; cursor: not-allowed; transform: none; }

        /* Autocomplete */
        .pl-page-root .autocomplete-dropdown { position: absolute; top: 100%; left: 0; right: 0; z-index: 1060; background: #fff; border: 1px solid #e0e0e0; border-radius: 12px; box-shadow: 0 10px 40px rgba(0,0,0,0.15); margin-top: 8px; max-height: 300px; overflow-y: auto; }
        .pl-page-root .autocomplete-item { padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; transition: all 0.2s ease; border-bottom: 1px solid #f1f5f9; }
        .pl-page-root .autocomplete-item:hover { background: linear-gradient(135deg, #f8fafc, #f1f5f9); }
        .pl-page-root .autocomplete-item.selected { background: linear-gradient(135deg, #dbeafe, #bfdbfe); }
        .pl-page-root .autocomplete-item .product-name { font-size: .9375rem; font-weight: 500; color: #1e293b; }
        .pl-page-root .autocomplete-item .product-info { font-size: .8125rem; color: #64748b; }
        .pl-page-root .autocomplete-item .item-left { flex: 1; min-width: 0; }

        @keyframes fadeInUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }

        /* Responsive */
        @media (max-width: 1199px) { .pl-page-root .sticky-panel { position: static; } .pl-page-root .col-xl-4, .pl-page-root .col-lg-5 { flex: 0 0 100%; max-width: 100%; } .pl-page-root .col-xl-8, .pl-page-root .col-lg-7 { flex: 0 0 100%; max-width: 100%; } .pl-page-root .page-title { font-size: 1.75rem; } .pl-page-root .product-image-container { width: 64px; height: 64px; } }
        @media (max-width: 767px) { .pl-page-root .page-title { font-size: 1.5rem; } .pl-page-root .thead-elegant th, .pl-page-root .tr-elegant td { padding: 1rem; } .pl-page-root .btn-action { width: 40px; height: 40px; } }
      `}</style>
    </div>
  );
}
