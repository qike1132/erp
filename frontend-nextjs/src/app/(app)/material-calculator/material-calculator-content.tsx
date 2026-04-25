"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import { get, post } from "@/lib/api-client";
import { useState, useRef, useCallback, useEffect } from "react";
import {
  CalculatorIcon,
  SearchIcon,
  XIcon,
  Loader2Icon,
  ChevronDownIcon,
  EditIcon,
  Trash2Icon,
  BoxesIcon,
  ClipboardCheckIcon,
  ChartPieIcon,
  AlertTriangleIcon,
  InboxIcon,
  MousePointer2Icon,
  CheckCircleIcon,
  XCircleIcon,
  LayersIcon,
  CloudIcon,
  ScrollTextIcon,
  PuzzleIcon,
  PackageIcon,
  BoxIcon,
} from "lucide-react";
import { toast } from "sonner";

// ============ Types ============

interface ProductItem {
  id: number;
  name: string;
  barcode: string | null;
  price: number;
  has_bom: boolean;
  bom_info?: {
    filling_count: number;
    fabric_count: number;
    accessory_count: number;
    packaging_count: number;
  };
  current_stock: number;
}

interface SearchSuggestion {
  id: number;
  name: string;
  barcode: string | null;
  price: number;
  has_bom: boolean;
}

interface MaterialItem {
  name: string;
  material_name: string;
  material_code: string;
  specification: string;
  total_quantity: number;
  unit: string;
  supplier_name: string;
}

interface CalcResult {
  success: boolean;
  filling: MaterialItem[];
  fabric: MaterialItem[];
  accessory: MaterialItem[];
  packaging: MaterialItem[];
}

interface OrderItem {
  productId: number;
  productName: string;
  formalQty: number;
}

interface ProductsResponse {
  success: boolean;
  products: ProductItem[];
  total: number;
  pages: number;
  current_page: number;
}

interface SearchResponse {
  success: boolean;
  suggestions: SearchSuggestion[];
}

type FilterType = "all" | "has-bom" | "no-bom";

const CATEGORY_CONFIG: Record<string, { name: string; icon: React.ReactNode; iconClass: string }> = {
  filling: { name: "填充类", icon: <CloudIcon />, iconClass: "mc-cat-icon-filling" },
  fabric: { name: "面料类", icon: <ScrollTextIcon />, iconClass: "mc-cat-icon-fabric" },
  accessory: { name: "辅料类", icon: <PuzzleIcon />, iconClass: "mc-cat-icon-accessory" },
  packaging: { name: "包装类", icon: <PackageIcon />, iconClass: "mc-cat-icon-packaging" },
};

// ============ Material Calculator Content ============

export function MaterialCalculatorContent() {
  // --- State ---
  const [allProducts, setAllProducts] = useState<ProductItem[]>([]);
  const [selectedProducts, setSelectedProducts] = useState<Set<number>>(new Set());
  const [orderItems, setOrderItems] = useState<OrderItem[]>([]);
  const [calculationResults, setCalculationResults] = useState<Record<string, MaterialItem[]> | null>(null);
  const [currentFilter, setCurrentFilter] = useState<FilterType>("all");
  const [productSearch, setProductSearch] = useState("");
  const [dropdownVisible, setDropdownVisible] = useState(false);
  const [dropdownLoading, setDropdownLoading] = useState(false);
  const [dropdownEmpty, setDropdownEmpty] = useState(false);
  const [searchSuggestions, setSearchSuggestions] = useState<SearchSuggestion[]>([]);
  const [calcStatus, setCalcStatus] = useState<{ status: string; text: string }>({ status: "", text: "" });
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set());
  const [batchModalOpen, setBatchModalOpen] = useState(false);
  const [batchQty, setBatchQty] = useState(0);

  const searchWrapperRef = useRef<HTMLDivElement>(null);
  const calcTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // --- Load Products ---
  const { isLoading: productsLoading, refetch: refetchProducts } = useQuery({
    queryKey: ["mc-products"],
    queryFn: () => get<ProductsResponse>("/purchase-center/products", { per_page: "200" }),
  });

  useEffect(() => {
    refetchProducts().then((res) => {
      if (res.data?.success) {
        setAllProducts(res.data.products);
      }
    });
  }, []);

  // --- Search ---
  const { refetch: refetchSearch } = useQuery({
    queryKey: ["mc-search", productSearch],
    queryFn: () =>
      get<SearchResponse>("/purchase-center/products/search-suggestions", {
        q: productSearch,
        limit: "15",
      }),
    enabled: false,
  });

  // --- Calculate ---
  const calcMutation = useMutation({
    mutationFn: (orders: { product_id: number; quantity: number }[]) =>
      post<CalcResult>("/purchase-center/calculate", { orders }),
    onSuccess: (data) => {
      if (data.success) {
        const results: Record<string, MaterialItem[]> = {};
        (["filling", "fabric", "accessory", "packaging"] as const).forEach((cat) => {
          if (data[cat] && data[cat].length > 0) {
            results[cat] = data[cat];
          }
        });
        setCalculationResults(results);
        const totalMats = Object.values(results).flat().length;
        setCalcStatus({ status: "done", text: `${totalMats} 种物料` });
      } else {
        setCalculationResults(null);
        setCalcStatus({ status: "", text: "" });
        toast.error("计算失败");
      }
    },
    onError: () => {
      setCalculationResults(null);
      setCalcStatus({ status: "", text: "" });
      toast.error("网络错误，计算失败");
    },
  });

  // --- Close dropdown on outside click ---
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (searchWrapperRef.current && !searchWrapperRef.current.contains(e.target as Node)) {
        setDropdownVisible(false);
      }
    }
    document.addEventListener("click", handleClick);
    return () => document.removeEventListener("click", handleClick);
  }, []);

  // --- Handlers ---
  function handleSearchInput(value: string) {
    setProductSearch(value);
    if (value.trim().length === 0) {
      setDropdownVisible(false);
      return;
    }
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => performSearch(value.trim()), 250);
  }

  async function performSearch(query: string) {
    setDropdownVisible(true);
    setDropdownLoading(true);
    setDropdownEmpty(false);
    setSearchSuggestions([]);

    try {
      const res = await refetchSearch();
      const data = res.data;
      if (data?.success && data.suggestions && data.suggestions.length > 0) {
        setSearchSuggestions(data.suggestions);
        setDropdownLoading(false);
        setDropdownEmpty(false);
      } else {
        setSearchSuggestions([]);
        setDropdownLoading(false);
        setDropdownEmpty(true);
      }
    } catch {
      setSearchSuggestions([]);
      setDropdownLoading(false);
      setDropdownEmpty(true);
    }
  }

  function selectFromSearch(item: SearchSuggestion) {
    if (!item.has_bom) {
      toast.warning("该产品未配置BOM表", { description: "请在产品管理中配置BOM后再使用此功能" });
      return;
    }
    toggleProduct(item.id);
    setProductSearch("");
    setDropdownVisible(false);
  }

  function clearSearch() {
    setProductSearch("");
    setDropdownVisible(false);
  }

  function toggleProduct(productId: number) {
    const product = allProducts.find((p) => p.id === productId);
    if (!product) return;

    if (!product.has_bom) {
      toast.error("BOM配置不完整", { description: `"${product.name}" 未配置BOM表，无法参与物料计算` });
      return;
    }

    setSelectedProducts((prev) => {
      const next = new Set(prev);
      if (next.has(productId)) {
        next.delete(productId);
        setOrderItems((items) => items.filter((o) => o.productId !== productId));
      } else {
        next.add(productId);
        setOrderItems((items) => [...items, { productId, productName: product.name, formalQty: 0 }]);
      }
      return next;
    });
  }

  function updateQuantity(index: number, value: number) {
    if (isNaN(value) || value < 0) {
      toast.warning("输入错误", { description: "数量必须为非负整数" });
      return;
    }
    setOrderItems((items) => items.map((item, i) => (i === index ? { ...item, formalQty: value } : item)));
    debounceCalc();
  }

  function removeItem(index: number) {
    const productId = orderItems[index].productId;
    setSelectedProducts((prev) => {
      const next = new Set(prev);
      next.delete(productId);
      return next;
    });
    setOrderItems((items) => items.filter((_, i) => i !== index));
    triggerCalculation();
  }

  function debounceCalc() {
    if (calcTimerRef.current) clearTimeout(calcTimerRef.current);
    calcTimerRef.current = setTimeout(triggerCalculation, 350);
  }

  function triggerCalculation() {
    if (calcTimerRef.current) clearTimeout(calcTimerRef.current);

    const validItems = orderItems.filter((item) => item.formalQty > 0);
    if (validItems.length === 0) {
      setCalculationResults(null);
      setCalcStatus({ status: "", text: "" });
      return;
    }

    setCalcStatus({ status: "calculating", text: "计算中..." });

    calcTimerRef.current = setTimeout(() => {
      calcMutation.mutate(validItems.map((item) => ({ product_id: item.productId, quantity: item.formalQty })));
    }, 480);
  }

  function toggleCategory(category: string) {
    setCollapsedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  }

  function openBatchModal() {
    if (orderItems.length === 0) {
      toast.info("请先添加产品到订单列表");
      return;
    }
    setBatchQty(0);
    setBatchModalOpen(true);
  }

  function applyBatchInput() {
    if (batchQty === 0) {
      toast.warning("请输入有效数量");
      return;
    }
    setOrderItems((items) => items.map((item) => ({ ...item, formalQty: batchQty })));
    setBatchModalOpen(false);
    toast.success(`已应用批量设置：订单 ${batchQty}`);
    setTimeout(triggerCalculation, 100);
  }

  function handleClearAll() {
    if (orderItems.length === 0) return;
    if (!confirm("确定要清空所有已选产品和数量吗？")) return;
    setSelectedProducts(new Set());
    setOrderItems([]);
    setCalculationResults(null);
    setCalcStatus({ status: "", text: "" });
  }

  const totalFormal = orderItems.reduce((sum, item) => sum + item.formalQty, 0);

  // --- Filtered products ---
  const filteredProducts = allProducts.filter((p) => {
    if (currentFilter === "has-bom") return p.has_bom;
    if (currentFilter === "no-bom") return !p.has_bom;
    return true;
  });

  // --- Render ---
  return (
    <div className="mc-container">
      {/* Header */}
      <div className="mc-header">
        <div className="mc-header-left">
          <h1 className="mc-title">
            <CalculatorIcon className="mc-title-icon" />
            物料用量计算器
          </h1>
          <p className="mc-subtitle">选择SKU → 输入数量 → 自动计算物料用量</p>
        </div>
      </div>

      {/* Main Grid */}
      <div className="mc-body">
        <div className="mc-main-grid">
          {/* Left: SKU Selection */}
          <div className="mc-section mc-sku-section">
            <div className="mc-card">
              <div className="mc-card-header">
                <div className="mc-card-title-group">
                  <div className="mc-icon-box mc-icon-blue">
                    <BoxesIcon />
                  </div>
                  <div>
                    <h3>产品选择</h3>
                    <small>选择需要计算的SKU</small>
                  </div>
                </div>
                <span className="mc-badge">已选 {selectedProducts.size} 个</span>
              </div>

              {/* Search */}
              <div className="mc-search-wrapper" ref={searchWrapperRef}>
                <div className="mc-search-input-group">
                  <SearchIcon className="mc-search-icon-lucide" />
                  <input
                    type="text"
                    className="mc-search-input"
                    placeholder="搜索产品名称或69码..."
                    value={productSearch}
                    onChange={(e) => handleSearchInput(e.target.value)}
                    onFocus={() => {
                      if (productSearch.length >= 1) setDropdownVisible(true);
                    }}
                    autoComplete="off"
                  />
                  {productSearch.length > 0 && (
                    <button className="mc-search-clear" onClick={clearSearch}>
                      <XIcon />
                    </button>
                  )}
                </div>
                {dropdownVisible && (
                  <div className="mc-search-dropdown">
                    {dropdownLoading && (
                      <div className="mc-dropdown-loading">
                        <Loader2Icon className="animate-spin" />
                        <span>搜索中...</span>
                      </div>
                    )}
                    {searchSuggestions.length > 0 && (
                      <div className="mc-dropdown-list">
                        {searchSuggestions.map((item) => (
                          <div
                            key={item.id}
                            className="mc-dropdown-item"
                            onClick={() => selectFromSearch(item)}
                          >
                            <div className="mc-dropdown-item-info">
                              <div className="mc-dropdown-item-name">{item.name}</div>
                              <div className="mc-dropdown-item-meta">{item.barcode || ""}</div>
                            </div>
                            <span className={`mc-bom-tag-mini ${item.has_bom ? "has-bom" : "no-bom"}`}>
                              {item.has_bom ? "有BOM" : "无BOM"}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                    {dropdownEmpty && (
                      <div className="mc-dropdown-empty">
                        <InboxIcon />
                        <span>未找到匹配的产品</span>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Filter Bar */}
              <div className="mc-filter-bar">
                {(
                  [
                    { key: "all", icon: <LayersIcon />, label: "全部" },
                    { key: "has-bom", icon: <CheckCircleIcon />, label: "有BOM" },
                    { key: "no-bom", icon: <XCircleIcon />, label: "无BOM" },
                  ] as const
                ).map((f) => (
                  <button
                    key={f.key}
                    className={`mc-filter-btn ${currentFilter === f.key ? "active" : ""}`}
                    onClick={() => setCurrentFilter(f.key)}
                  >
                    {f.icon}
                    {f.label}
                  </button>
                ))}
              </div>

              {/* Product List */}
              <div className="mc-product-list">
                {productsLoading ? (
                  <div className="mc-loading-state">
                    <div className="mc-spinner"></div>
                    <span>加载产品列表...</span>
                  </div>
                ) : filteredProducts.length === 0 ? (
                  <div className="mc-empty-state">
                    <InboxIcon />
                    <p>没有找到产品</p>
                    <span>请调整筛选条件</span>
                  </div>
                ) : (
                  filteredProducts.map((product) => (
                    <div
                      key={product.id}
                      className={`mc-product-item ${selectedProducts.has(product.id) ? "selected" : ""}`}
                      onClick={() => toggleProduct(product.id)}
                    >
                      <input
                        type="checkbox"
                        className="mc-product-checkbox"
                        checked={selectedProducts.has(product.id)}
                        onChange={() => toggleProduct(product.id)}
                        onClick={(e) => e.stopPropagation()}
                      />
                      <div className="mc-product-details">
                        <div className="mc-product-name">{product.name}</div>
                        <div className="mc-product-code">{product.barcode ? `69码: ${product.barcode}` : ""}</div>
                      </div>
                      <span className={`mc-bom-badge ${product.has_bom ? "has-bom" : "no-bom"}`}>
                        {product.has_bom ? "有BOM" : "无BOM"}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          {/* Right: Order Input + Results */}
          <div className="mc-section mc-input-section">
            {/* Order Quantity Card */}
            <div className="mc-card">
              <div className="mc-card-header">
                <div className="mc-card-title-group">
                  <div className="mc-icon-box mc-icon-green">
                    <ClipboardCheckIcon />
                  </div>
                  <div>
                    <h3>订单数量录入</h3>
                    <small>输入订单数量</small>
                  </div>
                </div>
                <div className="mc-header-actions">
                  <button className="mc-btn-sm mc-btn-outline" onClick={openBatchModal}>
                    <EditIcon />
                    批量录入
                  </button>
                  <button className="mc-btn-sm mc-btn-danger-outline" onClick={handleClearAll}>
                    <Trash2Icon />
                    清空
                  </button>
                </div>
              </div>

              <div className="mc-order-list">
                {orderItems.length === 0 ? (
                  <div className="mc-empty-state">
                    <MousePointer2Icon />
                    <p>请从左侧选择产品</p>
                    <span>选择有BOM的产品会自动添加到这里</span>
                  </div>
                ) : (
                  orderItems.map((item, index) => (
                    <div key={item.productId} className="mc-order-item">
                      <div className="mc-order-name" title={item.productName}>
                        {item.productName}
                      </div>
                      <div className="mc-order-inputs">
                        <div className="mc-field-group">
                          <span className="mc-field-label">订单</span>
                          <input
                            type="number"
                            className="mc-field-input"
                            value={item.formalQty}
                            onChange={(e) => updateQuantity(index, parseInt(e.target.value) || 0)}
                            min={0}
                            step={1}
                          />
                        </div>
                      </div>
                      <button className="mc-delete-btn" onClick={() => removeItem(index)} title="移除此产品">
                        <XIcon />
                      </button>
                    </div>
                  ))
                )}
              </div>

              {orderItems.length > 0 && (
                <div className="mc-summary-panel">
                  <div className="mc-summary-row">
                    <div className="mc-summary-item">
                      <label>订单总数</label>
                      <div className="mc-summary-value">
                        <strong>{totalFormal.toLocaleString()}</strong>
                        <span>件</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Result Card */}
            <div className="mc-card mc-result-card">
              <div className="mc-card-header">
                <div className="mc-card-title-group">
                  <div className="mc-icon-box mc-icon-purple">
                    <ChartPieIcon />
                  </div>
                  <div>
                    <h3>物料用量计算结果</h3>
                    <small>实时计算物料需求</small>
                  </div>
                </div>
                {calcStatus.status && (
                  <div className={`mc-calc-status ${calcStatus.status}`}>{calcStatus.text}</div>
                )}
              </div>

              <div className="mc-result-content">
                {calcStatus.status === "calculating" ? (
                  <div className="mc-loading-state">
                    <div className="mc-spinner"></div>
                    <span>正在计算物料用量...</span>
                  </div>
                ) : !calculationResults || Object.keys(calculationResults).length === 0 ? (
                  <div className="mc-empty-state">
                    <CalculatorIcon />
                    <p>输入数量后自动计算</p>
                    <span>计算结果将实时显示在这里</span>
                  </div>
                ) : (
                  Object.entries(calculationResults).map(([categoryKey, materials], idx) => {
                    const config = CATEGORY_CONFIG[categoryKey] || {
                      name: categoryKey,
                      icon: <BoxIcon />,
                      iconClass: "mc-cat-icon-default",
                    };
                    const isCollapsed = collapsedCategories.has(categoryKey);
                    return (
                      <div
                        key={categoryKey}
                        className="mc-category-block"
                        style={{ animationDelay: `${idx * 80}ms` }}
                      >
                        <div className="mc-category-head" onClick={() => toggleCategory(categoryKey)}>
                          <div className="mc-category-head-info">
                            <div className={`mc-category-icon ${config.iconClass}`}>
                              {config.icon}
                            </div>
                            <span className="mc-category-name">{config.name}</span>
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <span className="mc-category-count">{materials.length} 种</span>
                            <ChevronDownIcon
                              className="mc-chevron"
                              style={{
                                transition: "transform 0.3s",
                                transform: isCollapsed ? "rotate(-90deg)" : "rotate(0deg)",
                              }}
                            />
                          </div>
                        </div>
                        {!isCollapsed && (
                          <div className="mc-category-body">
                            <div className="mc-material-table">
                              <div className="mc-mat-header-row">
                                <div>供应商</div>
                                <div>物料名称</div>
                                <div>物料型号</div>
                                <div className="mc-mat-header-right">总采购量</div>
                              </div>
                              {materials.map((mat, mi) => (
                                <div key={mi} className="mc-mat-row">
                                  <div className="mc-mat-supplier-cell">{mat.supplier_name || ""}</div>
                                  <div className="mc-mat-name-cell">{mat.material_name}</div>
                                  <div className="mc-mat-spec-cell">{mat.specification || ""}</div>
                                  <div className="mc-mat-total-cell">
                                    {Number(mat.total_quantity).toFixed(2)} <small>{mat.unit || ""}</small>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Batch Modal */}
      {batchModalOpen && (
        <div className="mc-modal-overlay" onClick={() => setBatchModalOpen(false)}>
          <div className="mc-modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="mc-modal-content-inner">
              <div className="mc-modal-header-inner">
                <h5 className="mc-modal-title-inner">
                  <EditIcon style={{ marginRight: 8 }} />
                  批量录入数量
                </h5>
                <button className="mc-modal-close" onClick={() => setBatchModalOpen(false)}>
                  <XIcon />
                </button>
              </div>
              <div className="mc-modal-body-inner">
                <div style={{ marginBottom: 16 }}>
                  <label className="mc-field-label" style={{ display: "block", marginBottom: 8 }}>
                    订单数量
                  </label>
                  <input
                    type="number"
                    className="mc-field-input"
                    style={{ width: "100%", fontSize: 18, padding: "12px 16px" }}
                    value={batchQty}
                    onChange={(e) => {
                      const val = parseInt(e.target.value);
                      if (isNaN(val) || val < 0) setBatchQty(0);
                      else if (val > 999999) setBatchQty(999999);
                      else setBatchQty(val);
                    }}
                    min={0}
                  />
                  <small style={{ color: "var(--mc-gray-500)", fontSize: 13, marginTop: 6, display: "block" }}>
                    应用于所有已选产品的订单数量
                  </small>
                </div>
              </div>
              <div className="mc-modal-footer-inner">
                <button className="mc-modal-btn mc-modal-btn-secondary" onClick={() => setBatchModalOpen(false)}>
                  取消
                </button>
                <button className="mc-modal-btn mc-modal-btn-primary" onClick={applyBatchInput}>
                  应用到全部
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <style jsx global>{`
        :root {
          --mc-blue-50: #E6F7FA;
          --mc-blue-100: #CCEFF5;
          --mc-blue-200: #99D9E8;
          --mc-blue-300: #66C2DB;
          --mc-blue-400: #33ABCD;
          --mc-blue-500: #0094BF;
          --mc-blue-600: #007A9F;
          --mc-blue-700: #00617F;

          --mc-green-50: #E8F5E9;
          --mc-green-100: #C8E6C9;
          --mc-green-200: #A5D6A7;
          --mc-green-300: #81C784;
          --mc-green-400: #4CAF50;

          --mc-red-50: #FFEBEE;
          --mc-red-100: #FFCDD2;
          --mc-red-200: #EF9A9A;
          --mc-red-300: #E57373;

          --mc-purple-50: #F3E5F5;
          --mc-purple-100: #E1BEE7;
          --mc-purple-200: #CE93D8;
          --mc-purple-300: #BA68C8;

          --mc-gray-50: #F8FAFC;
          --mc-gray-100: #F1F5F9;
          --mc-gray-200: #E2E8F0;
          --mc-gray-300: #CBD5E1;
          --mc-gray-400: #94A3B8;
          --mc-gray-500: #64748B;
          --mc-gray-600: #475569;
          --mc-gray-700: #334155;
          --mc-gray-800: #1E293B;
        }

        .mc-container {
          padding: 24px;
          max-width: 1600px;
          margin: 0 auto;
          font-family: 'Microsoft YaHei', -apple-system, BlinkMacSystemFont, sans-serif;
        }

        .mc-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 28px;
          padding: 28px 32px;
          background: linear-gradient(135deg, var(--mc-blue-50) 0%, #FFFFFF 100%);
          border-radius: 20px;
          border: 2px solid var(--mc-blue-100);
          box-shadow: 0 4px 24px rgba(0, 148, 191, 0.08);
        }

        .mc-title {
          display: flex;
          align-items: center;
          gap: 14px;
          font-size: 30px;
          font-weight: 700;
          color: var(--mc-gray-800);
          margin: 0;
        }

        .mc-title-icon {
          color: var(--mc-blue-500);
          width: 28px;
          height: 28px;
        }

        .mc-subtitle {
          font-size: 14px;
          color: var(--mc-gray-500);
          margin: 6px 0 0 42px;
          letter-spacing: 0.5px;
        }

        .mc-main-grid {
          display: grid;
          grid-template-columns: 420px 1fr;
          gap: 24px;
        }

        @media (max-width: 1200px) {
          .mc-main-grid {
            grid-template-columns: 1fr;
          }
        }

        .mc-section {
          display: flex;
          flex-direction: column;
          gap: 20px;
        }

        .mc-card {
          background: white;
          border-radius: 18px;
          border: 2px solid var(--mc-gray-200);
          box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
          overflow: hidden;
          transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .mc-card:hover {
          box-shadow: 0 6px 24px rgba(0, 0, 0, 0.06);
        }

        .mc-card-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 20px 24px;
          background: linear-gradient(to bottom, #FAFBFC, #FFFFFF);
          border-bottom: 1px solid var(--mc-gray-200);
        }

        .mc-card-title-group {
          display: flex;
          align-items: center;
          gap: 14px;
        }

        .mc-card-title-group h3 {
          font-size: 17px;
          font-weight: 700;
          color: var(--mc-gray-800);
          margin: 0;
        }

        .mc-card-title-group small {
          font-size: 12px;
          color: var(--mc-gray-500);
          display: block;
          margin-top: 2px;
        }

        .mc-icon-box {
          width: 46px;
          height: 46px;
          border-radius: 13px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 19px;
        }

        .mc-icon-box svg {
          width: 22px;
          height: 22px;
        }

        .mc-icon-blue {
          background: linear-gradient(135deg, var(--mc-blue-100), var(--mc-blue-200));
          color: var(--mc-blue-600);
        }

        .mc-icon-green {
          background: linear-gradient(135deg, var(--mc-green-100), var(--mc-green-200));
          color: #2E7D32;
        }

        .mc-icon-purple {
          background: linear-gradient(135deg, var(--mc-purple-100), var(--mc-purple-200));
          color: #6A1B9A;
        }

        .mc-badge {
          padding: 6px 14px;
          background: linear-gradient(135deg, var(--mc-blue-500), var(--mc-blue-600));
          color: white;
          border-radius: 20px;
          font-size: 13px;
          font-weight: 600;
        }

        /* Search Styles */
        .mc-search-wrapper {
          position: relative;
          padding: 0 24px 16px;
        }

        .mc-search-input-group {
          position: relative;
          display: flex;
          align-items: center;
        }

        .mc-search-icon-lucide {
          position: absolute;
          left: 14px;
          color: var(--mc-gray-400);
          width: 16px;
          height: 16px;
          z-index: 2;
        }

        .mc-search-input {
          width: 100%;
          padding: 12px 40px 12px 42px;
          border: 2px solid var(--mc-gray-200);
          border-radius: 11px;
          font-size: 14px;
          outline: none;
          transition: all 0.3s ease;
          background: var(--mc-gray-50);
        }

        .mc-search-input:focus {
          border-color: var(--mc-blue-400);
          background: white;
          box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
        }

        .mc-search-clear {
          position: absolute;
          right: 10px;
          background: none;
          border: none;
          color: var(--mc-gray-400);
          cursor: pointer;
          padding: 6px;
          border-radius: 50%;
          transition: all 0.2s ease;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .mc-search-clear svg {
          width: 14px;
          height: 14px;
        }

        .mc-search-clear:hover {
          background: var(--mc-gray-100);
          color: var(--mc-gray-600);
        }

        .mc-search-dropdown {
          position: absolute;
          top: calc(100% + 6px);
          left: 24px;
          right: 24px;
          background: white;
          border: 2px solid var(--mc-blue-200);
          border-radius: 12px;
          box-shadow: 0 10px 40px rgba(0, 0, 0, 0.12);
          z-index: 1000;
          max-height: 320px;
          overflow-y: auto;
        }

        .mc-dropdown-loading,
        .mc-dropdown-empty {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          padding: 30px 20px;
          color: var(--mc-gray-500);
          font-size: 14px;
        }

        .mc-dropdown-loading svg {
          width: 18px;
          height: 18px;
        }

        .mc-dropdown-empty svg {
          width: 18px;
          height: 18px;
          opacity: 0.5;
        }

        .mc-dropdown-item {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          cursor: pointer;
          transition: all 0.2s ease;
          border-bottom: 1px solid var(--mc-gray-100);
        }

        .mc-dropdown-item:last-child {
          border-bottom: none;
        }

        .mc-dropdown-item:hover {
          background: var(--mc-blue-50);
        }

        .mc-dropdown-item-info {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .mc-dropdown-item-name {
          font-weight: 600;
          font-size: 14px;
          color: var(--mc-gray-800);
        }

        .mc-dropdown-item-meta {
          font-size: 12px;
          color: var(--mc-gray-500);
        }

        .mc-bom-tag-mini {
          padding: 3px 8px;
          border-radius: 6px;
          font-size: 11px;
          font-weight: 600;
        }

        .mc-bom-tag-mini.has-bom {
          background: var(--mc-green-100);
          color: #2E7D32;
        }

        .mc-bom-tag-mini.no-bom {
          background: var(--mc-red-100);
          color: #C62828;
        }

        /* Filter Bar */
        .mc-filter-bar {
          display: flex;
          gap: 8px;
          padding: 0 24px 16px;
        }

        .mc-filter-btn {
          flex: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 9px 14px;
          background: var(--mc-gray-50);
          border: 2px solid var(--mc-gray-200);
          border-radius: 9px;
          font-size: 13px;
          font-weight: 600;
          color: var(--mc-gray-600);
          cursor: pointer;
          transition: all 0.25s ease;
        }

        .mc-filter-btn svg {
          width: 14px;
          height: 14px;
        }

        .mc-filter-btn:hover {
          background: var(--mc-gray-100);
          border-color: var(--mc-gray-300);
        }

        .mc-filter-btn.active {
          background: var(--mc-blue-50);
          border-color: var(--mc-blue-400);
          color: var(--mc-blue-600);
        }

        /* Product List */
        .mc-product-list {
          padding: 0 24px 24px;
          max-height: 480px;
          overflow-y: auto;
        }

        .mc-product-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 14px 16px;
          border: 2px solid var(--mc-gray-200);
          border-radius: 12px;
          margin-bottom: 10px;
          cursor: pointer;
          transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
          background: white;
        }

        .mc-product-item:hover {
          border-color: var(--mc-blue-300);
          background: var(--mc-blue-50);
          transform: translateX(4px);
          box-shadow: 0 2px 12px rgba(0, 148, 191, 0.08);
        }

        .mc-product-item.selected {
          border-color: var(--mc-blue-500);
          background: var(--mc-blue-50);
          box-shadow: 0 3px 16px rgba(0, 148, 191, 0.15);
        }

        .mc-product-checkbox {
          width: 22px;
          height: 22px;
          cursor: pointer;
          accent-color: var(--mc-blue-500);
          flex-shrink: 0;
        }

        .mc-product-details {
          flex: 1;
          min-width: 0;
        }

        .mc-product-name {
          font-weight: 650;
          font-size: 14px;
          color: var(--mc-gray-800);
          margin-bottom: 3px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .mc-product-code {
          font-size: 12px;
          color: var(--mc-gray-500);
        }

        .mc-bom-badge {
          padding: 5px 10px;
          border-radius: 7px;
          font-size: 11px;
          font-weight: 700;
          flex-shrink: 0;
        }

        .mc-bom-badge.has-bom {
          background: var(--mc-green-100);
          color: #2E7D32;
        }

        .mc-bom-badge.no-bom {
          background: var(--mc-red-100);
          color: #C62828;
        }

        /* Order List */
        .mc-order-list {
          padding: 24px;
          min-height: 180px;
          max-height: 340px;
          overflow-y: auto;
        }

        .mc-order-item {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 18px 20px;
          border: 2px solid var(--mc-gray-200);
          border-radius: 13px;
          margin-bottom: 12px;
          background: white;
          transition: all 0.3s ease;
        }

        .mc-order-item:hover {
          border-color: var(--mc-blue-300);
          box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
        }

        .mc-order-name {
          flex: 1;
          font-weight: 650;
          font-size: 14px;
          color: var(--mc-gray-800);
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .mc-order-inputs {
          display: flex;
          gap: 12px;
          align-items: center;
        }

        .mc-field-group {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .mc-field-label {
          font-size: 11px;
          color: var(--mc-gray-500);
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }

        .mc-field-input {
          width: 90px;
          padding: 9px 12px;
          border: 2px solid var(--mc-gray-200);
          border-radius: 9px;
          font-size: 14px;
          font-weight: 600;
          text-align: center;
          outline: none;
          transition: all 0.25s ease;
        }

        .mc-field-input:focus {
          border-color: var(--mc-blue-400);
          box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
        }

        .mc-field-input::-webkit-inner-spin-button,
        .mc-field-input::-webkit-outer-spin-button {
          -webkit-appearance: none;
          margin: 0;
        }

        .mc-delete-btn {
          width: 36px;
          height: 36px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: var(--mc-red-50);
          color: var(--mc-red-300);
          border: none;
          border-radius: 9px;
          cursor: pointer;
          transition: all 0.25s ease;
          flex-shrink: 0;
        }

        .mc-delete-btn svg {
          width: 16px;
          height: 16px;
        }

        .mc-delete-btn:hover {
          background: var(--mc-red-200);
          color: #C62828;
          transform: scale(1.05);
        }

        /* Summary Panel */
        .mc-summary-panel {
          padding: 0 24px 24px;
        }

        .mc-summary-row {
          display: flex;
          align-items: stretch;
          background: linear-gradient(135deg, var(--mc-gray-50), white);
          border: 2px solid var(--mc-blue-100);
          border-radius: 13px;
          overflow: hidden;
        }

        .mc-summary-item {
          flex: 1;
          padding: 18px 24px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .mc-summary-item label {
          font-size: 13px;
          color: var(--mc-gray-500);
          font-weight: 600;
        }

        .mc-summary-value {
          display: flex;
          align-items: baseline;
          gap: 6px;
        }

        .mc-summary-value strong {
          font-size: 26px;
          font-weight: 800;
          color: var(--mc-blue-600);
        }

        .mc-summary-value span {
          font-size: 14px;
          color: var(--mc-gray-500);
        }

        /* Result Card */
        .mc-result-card {
          flex-shrink: 0;
        }

        .mc-calc-status {
          font-size: 12px;
          font-weight: 600;
          padding: 5px 12px;
          border-radius: 8px;
        }

        .mc-calc-status.calculating {
          background: #FFF3CD;
          color: #856404;
        }

        .mc-calc-status.done {
          background: var(--mc-green-100);
          color: #2E7D32;
        }

        .mc-result-content {
          padding: 24px;
          max-height: 450px;
          overflow-y: auto;
        }

        /* Category Section */
        .mc-category-block {
          margin-bottom: 22px;
          animation: mc-fadeInUp 0.4s ease forwards;
        }

        @keyframes mc-fadeInUp {
          from {
            opacity: 0;
            transform: translateY(12px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .mc-category-head {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 14px 18px;
          background: linear-gradient(135deg, var(--mc-blue-50), white);
          border: 2px solid var(--mc-blue-100);
          border-radius: 12px;
          margin-bottom: 12px;
          cursor: pointer;
          user-select: none;
          transition: all 0.25s ease;
        }

        .mc-category-head:hover {
          background: linear-gradient(135deg, var(--mc-blue-100), var(--mc-blue-50));
          border-color: var(--mc-blue-200);
        }

        .mc-category-head-info {
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .mc-category-icon {
          width: 34px;
          height: 34px;
          border-radius: 9px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 15px;
        }

        .mc-category-icon svg {
          width: 17px;
          height: 17px;
        }

        .mc-cat-icon-filling {
          background: linear-gradient(135deg, #BBDEFB, #90CAF9);
          color: #1565C0;
        }

        .mc-cat-icon-fabric {
          background: linear-gradient(135deg, #C8E6C9, #A5D6A7);
          color: #2E7D32;
        }

        .mc-cat-icon-accessory {
          background: linear-gradient(135deg, #FFE0B2, #FFCC80);
          color: #EF6C00;
        }

        .mc-cat-icon-packaging {
          background: linear-gradient(135deg, #F3E5F5, #E1BEE7);
          color: #7B1FA2;
        }

        .mc-category-name {
          font-weight: 700;
          font-size: 15px;
          color: var(--mc-gray-800);
        }

        .mc-category-count {
          padding: 5px 12px;
          background: var(--mc-blue-500);
          color: white;
          border-radius: 16px;
          font-size: 12px;
          font-weight: 700;
        }

        .mc-chevron {
          width: 14px;
          height: 14px;
          color: var(--mc-gray-500);
        }

        .mc-material-table {
          border: 1px solid var(--mc-gray-200);
          border-radius: 10px;
          overflow: hidden;
        }

        .mc-mat-header-row {
          display: grid;
          grid-template-columns: 1.5fr 1.2fr 1.2fr 1fr 1.1fr;
          gap: 12px;
          padding: 16px 20px;
          background: var(--mc-gray-100);
          font-size: 15px;
          font-weight: 700;
          color: var(--mc-gray-700);
          border-bottom: 2px solid var(--mc-gray-300);
        }

        .mc-mat-header-right {
          text-align: right;
        }

        .mc-mat-row {
          display: grid;
          grid-template-columns: 1.5fr 1.2fr 1.2fr 1fr 1.1fr;
          gap: 12px;
          padding: 18px 20px;
          font-size: 15px;
          border-bottom: 1px solid var(--mc-gray-100);
          transition: all 0.2s ease;
          align-items: center;
        }

        .mc-mat-row:last-child {
          border-bottom: none;
        }

        .mc-mat-row:hover {
          background: var(--mc-blue-50);
        }

        .mc-mat-name-cell {
          font-weight: 700;
          color: var(--mc-gray-800);
          font-size: 15px;
        }

        .mc-mat-spec-cell {
          color: var(--mc-gray-600);
          font-weight: 600;
          font-size: 14px;
        }

        .mc-mat-supplier-cell {
          color: var(--mc-gray-600);
          font-weight: 600;
          font-size: 14px;
        }

        .mc-mat-total-cell {
          text-align: right;
          font-weight: 800;
          color: var(--mc-blue-600);
          font-size: 16px;
        }

        .mc-mat-total-cell small {
          font-weight: 500;
          font-size: 13px;
          color: var(--mc-gray-500);
          margin-left: 2px;
        }

        /* Empty State */
        .mc-empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 50px 20px;
          color: var(--mc-gray-400);
        }

        .mc-empty-state > svg {
          width: 48px;
          height: 48px;
          margin-bottom: 16px;
          opacity: 0.25;
        }

        .mc-empty-state p {
          font-size: 16px;
          font-weight: 600;
          margin-bottom: 6px;
          color: var(--mc-gray-500);
        }

        .mc-empty-state span {
          font-size: 13px;
        }

        .mc-loading-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 60px 20px;
          color: var(--mc-gray-500);
          gap: 14px;
        }

        .mc-spinner {
          width: 38px;
          height: 38px;
          border: 4px solid var(--mc-gray-200);
          border-top-color: var(--mc-blue-500);
          border-radius: 50%;
          animation: mc-spin 0.8s linear infinite;
        }

        @keyframes mc-spin {
          to { transform: rotate(360deg); }
        }

        /* Header Actions */
        .mc-header-actions {
          display: flex;
          gap: 8px;
        }

        .mc-btn-sm {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 7px 14px;
          border-radius: 8px;
          font-size: 13px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.25s ease;
          border: 2px solid transparent;
        }

        .mc-btn-sm svg {
          width: 14px;
          height: 14px;
        }

        .mc-btn-outline {
          background: white;
          border-color: var(--mc-blue-300);
          color: var(--mc-blue-600);
        }

        .mc-btn-outline:hover {
          background: var(--mc-blue-50);
        }

        .mc-btn-danger-outline {
          background: white;
          border-color: var(--mc-red-200);
          color: #DC3545;
        }

        .mc-btn-danger-outline:hover {
          background: var(--mc-red-50);
        }

        /* Modal */
        .mc-modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          background: rgba(0, 0, 0, 0.5);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1050;
        }

        .mc-modal-dialog {
          width: 100%;
          max-width: 480px;
        }

        .mc-modal-content-inner {
          background: white;
          border-radius: 18px;
          box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
          overflow: hidden;
        }

        .mc-modal-header-inner {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 20px 24px;
          border-bottom: 1px solid var(--mc-gray-200);
        }

        .mc-modal-title-inner {
          display: flex;
          align-items: center;
          font-size: 18px;
          font-weight: 600;
          margin: 0;
          color: var(--mc-gray-800);
        }

        .mc-modal-title-inner svg {
          width: 18px;
          height: 18px;
        }

        .mc-modal-close {
          background: none;
          border: none;
          color: var(--mc-gray-500);
          cursor: pointer;
          padding: 4px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.2s;
        }

        .mc-modal-close:hover {
          background: var(--mc-gray-100);
          color: var(--mc-gray-700);
        }

        .mc-modal-close svg {
          width: 18px;
          height: 18px;
        }

        .mc-modal-body-inner {
          padding: 24px;
        }

        .mc-modal-footer-inner {
          display: flex;
          justify-content: flex-end;
          gap: 12px;
          padding: 16px 24px;
          border-top: 1px solid var(--mc-gray-200);
        }

        .mc-modal-btn {
          padding: 10px 24px;
          border-radius: 10px;
          font-size: 15px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.25s ease;
          border: none;
        }

        .mc-modal-btn-secondary {
          background: var(--mc-gray-100);
          color: var(--mc-gray-600);
        }

        .mc-modal-btn-secondary:hover {
          background: var(--mc-gray-200);
        }

        .mc-modal-btn-primary {
          background: linear-gradient(135deg, var(--mc-blue-500), var(--mc-blue-600));
          color: white;
        }

        .mc-modal-btn-primary:hover {
          transform: translateY(-1px);
          box-shadow: 0 4px 12px rgba(0, 148, 191, 0.3);
        }

        /* Warning Banner for No BOM */
        .mc-warning-banner {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 12px 16px;
          background: #FFF8E1;
          border: 1px solid #FFD54F;
          border-radius: 10px;
          margin: 0 24px 16px;
          color: #F57F17;
          font-size: 13px;
          font-weight: 600;
        }

        .mc-warning-banner svg {
          width: 16px;
          height: 16px;
        }

        /* Fix grid columns for 4-col layout (matching Jinja2 renderResults which uses 4 columns) */
        .mc-mat-header-row,
        .mc-mat-row {
          grid-template-columns: 1.5fr 1.2fr 1.2fr 1.1fr;
        }
      `}</style>
    </div>
  );
}
