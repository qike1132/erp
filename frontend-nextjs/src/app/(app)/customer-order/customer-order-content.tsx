"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
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

export interface StockinItem {
  id: number;
  stockin_no: string;
  customer: string;
  product: Product;
  quantity: number;
  deducted: number;
  stockin_date: string;
  note: string;
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

interface StagedStockin {
  id?: number;
  customer: string;
  productId: number;
  productName: string;
  quantity: number;
  stockinDate: string;
  note: string;
  is_validated?: boolean;
  validation_error?: string;
}

interface Customer {
  id: number;
  name: string;
}

export interface ListResult<T> {
  success: boolean;
  data: T[];
  total: number;
}

// ============ Component ============

interface CustomerOrderContentProps {
  initialOrders?: ListResult<OrderItem>;
  initialStockins?: ListResult<StockinItem>;
  initialCustomers?: ListResult<Customer>;
}

export function CustomerOrderContent({ initialOrders, initialStockins, initialCustomers }: CustomerOrderContentProps) {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<"order" | "stockin">("order");

  // --- Order tab state ---
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
  const [showOrderAutocomplete, setShowOrderAutocomplete] = useState(false);
  const [editingOrderIndex, setEditingOrderIndex] = useState(-1);
  const [editOrderCustomer, setEditOrderCustomer] = useState("");
  const [editOrderQuantity, setEditOrderQuantity] = useState(1);
  const [editOrderDeductQuantity, setEditOrderDeductQuantity] = useState(0);
  const [editOrderNote, setEditOrderNote] = useState("");
  const [editOrderAvailableStock, setEditOrderAvailableStock] = useState(0);
  const [showEditOrderModal, setShowEditOrderModal] = useState(false);
  const [orderExcelFile, setOrderExcelFile] = useState<File | null>(null);
  const [orderUploadStatus, setOrderUploadStatus] = useState("");
  const [showOrderBatchUpload, setShowOrderBatchUpload] = useState(false);
  const [submittingOrders, setSubmittingOrders] = useState(false);
  const [expandedOrderGroups, setExpandedOrderGroups] = useState<Set<string>>(new Set());

  // --- Stockin tab state ---
  const [siDate, setSiDate] = useState(() => new Date().toISOString().split("T")[0]);
  const [siCustomer, setSiCustomer] = useState("");
  const [siProductSearch, setSiProductSearch] = useState("");
  const [siProductId, setSiProductId] = useState<number | null>(null);
  const [siQuantity, setSiQuantity] = useState(1);
  const [siNote, setSiNote] = useState("");
  const [stagedStockins, setStagedStockins] = useState<StagedStockin[]>([]);
  const [siProductResults, setSiProductResults] = useState<Product[]>([]);
  const [showSiAutocomplete, setShowSiAutocomplete] = useState(false);
  const [editingSiIndex, setEditingSiIndex] = useState(-1);
  const [editSiCustomer, setEditSiCustomer] = useState("");
  const [editSiQuantity, setEditSiQuantity] = useState(1);
  const [editSiDate, setEditSiDate] = useState("");
  const [editSiNote, setEditSiNote] = useState("");
  const [showEditSiModal, setShowEditSiModal] = useState(false);
  const [siExcelFile, setSiExcelFile] = useState<File | null>(null);
  const [siUploadStatus, setSiUploadStatus] = useState("");
  const [showSiBatchUpload, setShowSiBatchUpload] = useState(false);
  const [submittingStockins, setSubmittingStockins] = useState(false);
  const [expandedSiGroups, setExpandedSiGroups] = useState<Set<string>>(new Set());

  // Refs
  const orderSearchRef = useRef<HTMLDivElement>(null);
  const siSearchRef = useRef<HTMLDivElement>(null);
  const orderFileRef = useRef<HTMLInputElement>(null);
  const siFileRef = useRef<HTMLInputElement>(null);
  const orderSearchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const siSearchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // --- API Queries ---
  const { data: ordersData } = useQuery({
    queryKey: ["orders-list"],
    queryFn: () => get<ListResult<OrderItem>>("/orders/list", { per_page: "5000" }),
    initialData: initialOrders,
  });

  const { data: stockinsData } = useQuery({
    queryKey: ["stockins-list"],
    queryFn: () => get<ListResult<StockinItem>>("/stock/in/list", { per_page: "5000" }),
    initialData: initialStockins,
  });

  const { data: customersData } = useQuery({
    queryKey: ["customers-list"],
    queryFn: () => get<ListResult<Customer>>("/customers/list"),
    initialData: initialCustomers,
  });

  const { data: stagingOrdersData } = useQuery({
    queryKey: ["staging-orders"],
    queryFn: () => get<unknown>("/staging-orders") as Promise<{ success: boolean; data: Record<string, unknown>[] }>,
    enabled: activeTab === "order",
  });

  const { data: stagingStockinsData } = useQuery({
    queryKey: ["staging-stockins"],
    queryFn: () => get<unknown>("/staging-stockins") as Promise<{ success: boolean; data: Record<string, unknown>[] }>,
    enabled: activeTab === "stockin",
  });

  const orders = ordersData?.data ?? [];
  const stockins = stockinsData?.data ?? [];
  const customers = customersData?.data ?? [];

  // --- Sync staging from server ---
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

  useEffect(() => {
    if (stagingStockinsData?.success && stagingStockinsData.data?.length > 0) {
      setStagedStockins(stagingStockinsData.data.map((s: Record<string, unknown>) => ({
        id: s.id as number,
        customer: (s.customer as string) || "",
        productId: (s.product_id as number) ?? (s.productId as number),
        productName: (s.product_name as string) ?? (s.productName as string) ?? "",
        quantity: (s.quantity as number) || 0,
        stockinDate: (s.stockin_date as string) ?? (s.stockinDate as string) ?? "",
        note: (s.note as string) ?? "",
        is_validated: s.is_validated as boolean | undefined,
        validation_error: s.validation_error as string | undefined,
      })));
    }
  }, [stagingStockinsData]);

  // --- Expand all groups by default ---
  useEffect(() => {
    const dates = new Set<string>();
    orders.forEach((o) => {
      const d = o.order_date?.split(" ")[0] || "未知日期";
      dates.add(d);
    });
    setExpandedOrderGroups(dates);
  }, [orders]);

  useEffect(() => {
    const dates = new Set<string>();
    stockins.forEach((s) => {
      const d = s.stockin_date || "未知日期";
      dates.add(d);
    });
    setExpandedSiGroups(dates);
  }, [stockins]);

  // --- Cleanup staging on unmount ---
  useEffect(() => {
    return () => {
      if (stagedOrders.length > 0) {
        del("/staging-orders/clear").catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    return () => {
      if (stagedStockins.length > 0) {
        del("/staging-stockins/clear").catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- Click outside to close autocomplete ---
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (orderSearchRef.current && !orderSearchRef.current.contains(e.target as Node)) {
        setShowOrderAutocomplete(false);
      }
      if (siSearchRef.current && !siSearchRef.current.contains(e.target as Node)) {
        setShowSiAutocomplete(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // --- Product search ---
  const searchProducts = useCallback(async (query: string, setResults: (r: Product[]) => void) => {
    if (!query.trim()) { setResults([]); return; }
    try {
      const data = await get<Product[]>("/aux/product-search", { q: query });
      setResults(Array.isArray(data) ? data : []);
    } catch { setResults([]); }
  }, []);

  const handleOrderProductSearch = useCallback((val: string) => {
    setOrderProductSearch(val);
    setOrderProductId(null);
    setOrderDeductQuantity(0);
    setOrderDeductStock(false);
    if (orderSearchTimer.current) clearTimeout(orderSearchTimer.current);
    orderSearchTimer.current = setTimeout(() => searchProducts(val, setOrderProductResults), 300);
    setShowOrderAutocomplete(true);
  }, [searchProducts]);

  const handleSiProductSearch = useCallback((val: string) => {
    setSiProductSearch(val);
    setSiProductId(null);
    if (siSearchTimer.current) clearTimeout(siSearchTimer.current);
    siSearchTimer.current = setTimeout(() => searchProducts(val, setSiProductResults), 300);
    setShowSiAutocomplete(true);
  }, [searchProducts]);

  // --- Deduct preview ---
  const fetchAvailableStockins = useCallback(async (productId: number, customer: string) => {
    try {
      const data = await get<{ available: number }[]>("/aux/available-stockins", {
        product_id: String(productId),
        customer,
      });
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
    if (deductible === 0) {
      alert(`无可抵扣数量！\n当前可用备货: ${available} 件`);
      setOrderDeductStock(false);
    }
  }, [orderProductId, orderCustomer, orderQuantity, fetchAvailableStockins]);

  // --- Order: add/edit/delete staged ---
  const canAddOrder = orderCustomer && orderProductId && orderQuantity > 0;

  const addStagedOrder = useCallback(() => {
    if (!canAddOrder) return;
    const order: StagedOrder = {
      customer: orderCustomer,
      productId: orderProductId!,
      productName: orderProductSearch,
      quantity: orderQuantity,
      orderDate: orderDate,
      note: orderNote,
      deduct_stock: orderDeductStock,
      deduct_quantity: orderDeductQuantity,
      id: Date.now(),
    };
    setStagedOrders((prev) => [...prev, order]);
    // Clear form
    setOrderCustomer("");
    setOrderProductSearch("");
    setOrderProductId(null);
    setOrderQuantity(1);
    setOrderNote("");
    setOrderDeductStock(false);
    setOrderDeductQuantity(0);
    setOrderAvailableStock(0);
  }, [canAddOrder, orderCustomer, orderProductId, orderProductSearch, orderQuantity, orderDate, orderNote, orderDeductStock, orderDeductQuantity]);

  const openEditOrderModal = useCallback(async (index: number) => {
    const order = stagedOrders[index];
    setEditingOrderIndex(index);
    setEditOrderCustomer(order.customer);
    setEditOrderQuantity(order.quantity);
    setEditOrderDeductQuantity(order.deduct_quantity);
    setEditOrderNote(order.note || "");
    setShowEditOrderModal(true);
    const available = await fetchAvailableStockins(order.productId, order.customer);
    setEditOrderAvailableStock(available);
  }, [stagedOrders, fetchAvailableStockins]);

  const saveEditOrder = useCallback(() => {
    if (editingOrderIndex === -1) return;
    if (editOrderDeductQuantity > editOrderQuantity) {
      alert("抵扣备货数量不能超过订单数量！");
      return;
    }
    if (editOrderDeductQuantity > editOrderAvailableStock) {
      alert(`抵扣备货数量不能超过可用备货数量！\n当前可用备货: ${editOrderAvailableStock} 件`);
      return;
    }
    setStagedOrders((prev) => {
      const copy = [...prev];
      copy[editingOrderIndex] = {
        ...copy[editingOrderIndex],
        customer: editOrderCustomer,
        quantity: editOrderQuantity,
        deduct_quantity: editOrderDeductQuantity,
        deduct_stock: editOrderDeductQuantity > 0,
        note: editOrderNote,
      };
      return copy;
    });
    setShowEditOrderModal(false);
    setEditingOrderIndex(-1);
  }, [editingOrderIndex, editOrderCustomer, editOrderQuantity, editOrderDeductQuantity, editOrderAvailableStock, editOrderNote]);

  const deleteStagedOrder = useCallback((index: number) => {
    if (!confirm("确定要删除这个暂存订单吗？")) return;
    const order = stagedOrders[index];
    if (order.id && order.id > 1000000000000) {
      // Local-only order
      setStagedOrders((prev) => prev.filter((_, i) => i !== index));
    } else if (order.id) {
      del(`/staging-orders/${order.id}`).then(() => {
        setStagedOrders((prev) => prev.filter((_, i) => i !== index));
        qc.invalidateQueries({ queryKey: ["staging-orders"] });
      });
    } else {
      setStagedOrders((prev) => prev.filter((_, i) => i !== index));
    }
  }, [stagedOrders, qc]);

  // --- Order: submit all ---
  const submitAllOrders = useCallback(async () => {
    if (stagedOrders.length === 0) return;
    setSubmittingOrders(true);

    try {
      // Validate deduct quantities
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
            const maxAllowed = Math.min(order.quantity, available);
            if (order.deduct_quantity > maxAllowed) {
              alert(`订单 (${order.productName}) 的抵扣数量超过可用备货！\n当前可用备货: ${available} 件\n最大可抵扣: ${maxAllowed} 件`);
              setSubmittingOrders(false);
              return;
            }
          }
        }
      }

      const ordersForApi = stagedOrders.map(o => ({
        product_id: o.productId,
        customer: o.customer,
        quantity: o.quantity,
        order_date: o.orderDate,
        note: o.note,
        deduct_stock: o.deduct_stock,
        deduct_quantity: o.deduct_quantity,
      }));

      const result = await post<{ success: boolean; error?: string }>("/aux/batch-submit-orders", { orders: ordersForApi });
      if (result.success) {
        alert("提交成功！");
        setStagedOrders([]);
        await del("/staging-orders/clear").catch(() => {});
        qc.invalidateQueries({ queryKey: ["orders-list"] });
        qc.invalidateQueries({ queryKey: ["staging-orders"] });
      } else {
        alert("提交失败: " + (result.error || "未知错误"));
      }
    } catch (error) {
      alert("提交失败: " + (error instanceof Error ? error.message : "未知错误"));
    } finally {
      setSubmittingOrders(false);
    }
  }, [stagedOrders, fetchAvailableStockins, qc]);

  // --- Order: batch import ---
  const handleOrderImport = useCallback(async () => {
    if (!orderExcelFile) return;
    setOrderUploadStatus("正在导入订单数据...");
    try {
      const formData = new FormData();
      formData.append("file", orderExcelFile);
      const resp = await fetch("/api/v1/staging-orders/import", { method: "POST", body: formData });
      const data = await resp.json();
      if (data.success) {
        setOrderUploadStatus(`导入成功！共导入 ${data.imported} 个订单到暂存区`);
        setOrderExcelFile(null);
        qc.invalidateQueries({ queryKey: ["staging-orders"] });
      } else {
        setOrderUploadStatus(`导入失败：${data.error || data.message || "未知错误"}`);
      }
    } catch (error) {
      setOrderUploadStatus("导入失败：" + (error instanceof Error ? error.message : "未知错误"));
    }
  }, [orderExcelFile, qc]);

  // --- Order: delete from list ---
  const deleteOrder = useCallback(async (id: number) => {
    if (!confirm("确定要删除该订单吗？")) return;
    try {
      const result = await del<{ success: boolean; error?: string }>(`/orders/delete/${id}`);
      if (result.success) {
        qc.invalidateQueries({ queryKey: ["orders-list"] });
      } else {
        alert(result.error || "删除失败！");
      }
    } catch (error) {
      alert("删除失败：" + (error instanceof Error ? error.message : "未知错误"));
    }
  }, [qc]);

  // --- Stockin: add/edit/delete staged ---
  const canAddStockin = siCustomer && siProductId && siQuantity > 0 && siDate;

  const addStagedStockin = useCallback(() => {
    if (!canAddStockin) return;
    const stockin: StagedStockin = {
      customer: siCustomer,
      productId: siProductId!,
      productName: siProductSearch,
      quantity: siQuantity,
      stockinDate: siDate,
      note: siNote,
      id: Date.now(),
    };
    setStagedStockins((prev) => [...prev, stockin]);
    setSiCustomer("");
    setSiProductSearch("");
    setSiProductId(null);
    setSiQuantity(1);
    setSiNote("");
  }, [canAddStockin, siCustomer, siProductId, siProductSearch, siQuantity, siDate, siNote]);

  const openEditSiModal = useCallback((index: number) => {
    const s = stagedStockins[index];
    setEditingSiIndex(index);
    setEditSiCustomer(s.customer);
    setEditSiQuantity(s.quantity);
    setEditSiDate(s.stockinDate);
    setEditSiNote(s.note || "");
    setShowEditSiModal(true);
  }, [stagedStockins]);

  const saveEditSi = useCallback(() => {
    if (editingSiIndex === -1) return;
    setStagedStockins((prev) => {
      const copy = [...prev];
      copy[editingSiIndex] = { ...copy[editingSiIndex], customer: editSiCustomer, quantity: editSiQuantity, stockinDate: editSiDate, note: editSiNote };
      return copy;
    });
    setShowEditSiModal(false);
    setEditingSiIndex(-1);
  }, [editingSiIndex, editSiCustomer, editSiQuantity, editSiDate, editSiNote]);

  const deleteStagedStockin = useCallback((index: number) => {
    if (!confirm("确定要删除这个暂存备货吗？")) return;
    const stockin = stagedStockins[index];
    if (stockin.id && stockin.id > 1000000000000) {
      setStagedStockins((prev) => prev.filter((_, i) => i !== index));
    } else if (stockin.id) {
      del(`/staging-stockins/${stockin.id}`).then(() => {
        setStagedStockins((prev) => prev.filter((_, i) => i !== index));
        qc.invalidateQueries({ queryKey: ["staging-stockins"] });
      });
    } else {
      setStagedStockins((prev) => prev.filter((_, i) => i !== index));
    }
  }, [stagedStockins, qc]);

  // --- Stockin: submit all ---
  const submitAllStockins = useCallback(async () => {
    if (stagedStockins.length === 0) return;
    const valid = stagedStockins.filter(s => s.is_validated !== false);
    if (valid.length === 0) { alert("没有可提交的有效备货，请检查验证状态"); return; }
    setSubmittingStockins(true);
    try {
      // Try server staging mode first
      const hasServerIds = stagedStockins.some(s => s.id && s.id < 1000000000000);
      if (hasServerIds) {
        const result = await post<{ success: boolean; message?: string }>("/staging-stockins/confirm", {});
        if (result.success) {
          alert("提交成功！");
          setStagedStockins([]);
          await del("/staging-stockins/clear").catch(() => {});
          qc.invalidateQueries({ queryKey: ["stockins-list"] });
          qc.invalidateQueries({ queryKey: ["staging-stockins"] });
        } else {
          alert("提交失败: " + (result.message || "未知错误"));
        }
      } else {
        const stockinsForApi = stagedStockins.map(s => ({
          product_id: s.productId,
          customer: s.customer,
          quantity: s.quantity,
          stockin_date: s.stockinDate,
          note: s.note,
        }));
        const result = await post<{ success: boolean; error?: string }>("/aux/batch-submit-stockins", { stockins: stockinsForApi });
        if (result.success) {
          alert("提交成功！");
          setStagedStockins([]);
          qc.invalidateQueries({ queryKey: ["stockins-list"] });
        } else {
          alert("提交失败: " + (result.error || "未知错误"));
        }
      }
    } catch (error) {
      alert("提交失败: " + (error instanceof Error ? error.message : "未知错误"));
    } finally {
      setSubmittingStockins(false);
    }
  }, [stagedStockins, qc]);

  // --- Stockin: batch import ---
  const handleSiImport = useCallback(async () => {
    if (!siExcelFile) return;
    setSiUploadStatus("正在导入备货数据...");
    try {
      const formData = new FormData();
      formData.append("file", siExcelFile);
      const resp = await fetch("/api/v1/staging-stockins/import", { method: "POST", body: formData });
      const data = await resp.json();
      if (data.success) {
        setSiUploadStatus(`导入成功！共导入 ${data.imported} 个备货到暂存区`);
        setSiExcelFile(null);
        qc.invalidateQueries({ queryKey: ["staging-stockins"] });
      } else {
        setSiUploadStatus(`导入失败：${data.error || data.message || "未知错误"}`);
      }
    } catch (error) {
      setSiUploadStatus("导入失败：" + (error instanceof Error ? error.message : "未知错误"));
    }
  }, [siExcelFile, qc]);

  // --- Stockin: delete from list ---
  const deleteStockin = useCallback(async (id: number) => {
    if (!confirm("确定要删除该备货记录吗？")) return;
    try {
      const result = await del<{ success: boolean; error?: string }>(`/aux/stockin/${id}`);
      if (result.success) {
        qc.invalidateQueries({ queryKey: ["stockins-list"] });
      } else {
        alert(result.error || "删除失败！");
      }
    } catch (error) {
      alert("删除失败：" + (error instanceof Error ? error.message : "未知错误"));
    }
  }, [qc]);

  // --- Grouping helpers ---
  function groupOrdersByDate(): [string, OrderItem[]][] {
    const groups: Record<string, OrderItem[]> = {};
    orders.forEach((o) => {
      const d = o.order_date?.split(" ")[0] || "未知日期";
      if (!groups[d]) groups[d] = [];
      groups[d].push(o);
    });
    return Object.entries(groups).sort(([a], [b]) => b.localeCompare(a));
  }

  function groupStockinsByDate(): [string, StockinItem[]][] {
    const groups: Record<string, StockinItem[]> = {};
    stockins.forEach((s) => {
      const d = s.stockin_date || "未知日期";
      if (!groups[d]) groups[d] = [];
      groups[d].push(s);
    });
    return Object.entries(groups).sort(([a], [b]) => b.localeCompare(a));
  }

  // --- Toggle group ---
  const toggleOrderGroup = (date: string) => {
    setExpandedOrderGroups((prev) => {
      const next = new Set(prev);
      if (next.has(date)) next.delete(date); else next.add(date);
      return next;
    });
  };

  const toggleSiGroup = (date: string) => {
    setExpandedSiGroups((prev) => {
      const next = new Set(prev);
      if (next.has(date)) next.delete(date); else next.add(date);
      return next;
    });
  };

  const escapeHtml = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  // ============ Render ============

  const orderGroups = groupOrdersByDate();
  const siGroups = groupStockinsByDate();

  return (
    <div className="co-page-root">
      <h2>客户订单</h2>

      {/* Tab Navigation */}
      <div className="customer-order-tabs tab-container">
        <div className="tab-list">
          <div className={`tab-item ${activeTab === "order" ? "active" : ""}`} onClick={() => setActiveTab("order")}>
            <i className="fas fa-clipboard-list" style={{ marginRight: 4 }}></i>订单管理
          </div>
          <div className={`tab-item ${activeTab === "stockin" ? "active" : ""}`} onClick={() => setActiveTab("stockin")}>
            <i className="fas fa-truck-loading" style={{ marginRight: 4 }}></i>备货管理
          </div>
        </div>
      </div>

      <div className="tab-panel-wrapper">
        {/* ==================== 订单管理 Tab ==================== */}
        {activeTab === "order" && (
          <div className="tab-content active">
            <div className="row">
              <div className="col-lg-6">
                <div className="card mt-3">
                  <div className="card-header d-flex justify-content-between align-items-center">
                    <span>订单信息录入</span>
                    {stagedOrders.length > 0 && (
                      <span className="badge bg-light text-dark">已暂存: {stagedOrders.length}</span>
                    )}
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

                    <div className="mb-3" style={{ position: "relative" }} ref={orderSearchRef}>
                      <label className="form-label">产品名称</label>
                      <input type="text" className="form-control" placeholder="输入产品名称搜索" autoComplete="off" value={orderProductSearch} onChange={e => handleOrderProductSearch(e.target.value)} onFocus={() => orderProductResults.length > 0 && setShowOrderAutocomplete(true)} />
                      {showOrderAutocomplete && orderProductResults.length > 0 && (
                        <div className="autocomplete-dropdown">
                          {orderProductResults.map(p => (
                            <div key={p.id} className="autocomplete-item" onMouseDown={() => {
                              setOrderProductSearch(p.name);
                              setOrderProductId(p.id);
                              setShowOrderAutocomplete(false);
                            }}>
                              {p.name}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="row mb-3">
                      <div className="col-md-6">
                        <label className="form-label">订单数量</label>
                        <input type="number" className="form-control" value={orderQuantity} min={1} onChange={e => {
                          const v = parseInt(e.target.value) || 0;
                          setOrderQuantity(v);
                          if (orderDeductQuantity > v) setOrderDeductQuantity(v);
                        }} />
                      </div>
                      <div className="col-md-6">
                        <label className="form-label">抵扣备货数量</label>
                        <div className="d-flex align-items-center">
                          <button type="button" className={`btn btn-sm ${orderDeductStock ? "btn-success" : "btn-outline-secondary"} me-2`} onClick={handleDeductPreview}>
                            抵扣备货
                          </button>
                          <div style={{ display: "inline-block" }}>
                            <small className="text-muted deductible-display" style={{ cursor: "pointer", padding: "8px 14px", borderRadius: 12, border: "2px dashed #adb5bd", backgroundColor: "#f8f9fa" }}>
                              抵扣: {orderDeductQuantity}
                            </small>
                          </div>
                        </div>
                        {orderDeductStock && (
                          <div className="mt-2">
                            <small className={orderAvailableStock > 0 ? "text-success" : "text-warning"}>
                              {orderAvailableStock > 0
                                ? `当前可用备货: ${orderAvailableStock} 件`
                                : "暂无可用备货"}
                            </small>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="mb-3">
                      <label className="form-label">备注</label>
                      <textarea className="form-control" rows={2} placeholder="例如：加急订单" value={orderNote} onChange={e => setOrderNote(e.target.value)} />
                    </div>

                    <div className="d-flex gap-2">
                      <button type="button" className={`btn ${canAddOrder ? "btn-primary" : "btn-secondary"}`} disabled={!canAddOrder} onClick={addStagedOrder}>
                        <i className="fas fa-plus-circle" style={{ marginRight: 4 }}></i>新增订单
                      </button>
                    </div>
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
                        <div className="text-center text-muted py-4">
                          <i className="fas fa-box-open" style={{ fontSize: 48, opacity: 0.3 }}></i>
                          <p>暂无暂存订单</p>
                        </div>
                      ) : (
                        stagedOrders.map((order, idx) => (
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
                                  {order.is_validated === false && <span className="badge bg-danger ms-1">验证失败</span>}
                                </div>
                                <div className="d-flex gap-1 ms-2">
                                  <button className="btn btn-sm btn-outline-warning" onClick={() => openEditOrderModal(idx)}><i className="fas fa-edit"></i></button>
                                  <button className="btn btn-sm btn-outline-danger" onClick={() => deleteStagedOrder(idx)}><i className="fas fa-trash"></i></button>
                                </div>
                              </div>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>

                {/* Batch upload */}
                <div className="card mt-3">
                  <div className="card-header d-flex justify-content-between align-items-center collapse-trigger" style={{ cursor: "pointer" }} onClick={() => setShowOrderBatchUpload(!showOrderBatchUpload)}>
                    <h6 className="mb-0 fw-bold">批量导入订单</h6>
                    <i className={`fas fa-chevron-down collapse-arrow ${showOrderBatchUpload ? "expanded" : ""}`}></i>
                  </div>
                  {showOrderBatchUpload && (
                    <div className="card-body">
                      <div className="border border-dashed p-4 text-center rounded" style={{ minHeight: 120, cursor: "pointer", background: "#fafafa", borderColor: "#dee2e6" }} onClick={() => orderFileRef.current?.click()}>
                        <div className="d-flex flex-column align-items-center justify-content-center" style={{ minHeight: 80 }}>
                          <i className="fas fa-file-excel text-success" style={{ fontSize: 32, opacity: 0.8, marginBottom: 8 }}></i>
                          <p className="text-muted mb-1 small">拖拽或点击选择 Excel 文件</p>
                          <p className="text-muted mb-0" style={{ fontSize: 11, color: "#adb5bd" }}>支持 .xlsx / .xls 格式</p>
                        </div>
                        <input ref={orderFileRef} type="file" style={{ display: "none" }} accept=".xlsx,.xls" onChange={e => { if (e.target.files?.[0]) setOrderExcelFile(e.target.files[0]); }} />
                      </div>
                      {orderExcelFile && <div className="mt-2"><small className="text-success">已选择: {orderExcelFile.name}</small></div>}
                      {orderUploadStatus && <div className="mt-2"><small>{orderUploadStatus}</small></div>}
                      <div className="d-flex justify-content-between align-items-center mt-3">
                        <a className="btn btn-outline-secondary btn-sm" href="/api/v1/batch/download-template" download>
                          <i className="fas fa-download" style={{ marginRight: 8 }}></i>订单模板
                        </a>
                        <button className="btn btn-success btn-sm" disabled={!orderExcelFile} onClick={handleOrderImport}>
                          <i className="fas fa-file-import" style={{ marginRight: 8 }}></i>确认导入
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Submit button */}
            <div className="card mt-4">
              <div className="card-body text-center py-4">
                <button className="btn btn-primary btn-lg" disabled={stagedOrders.length === 0 || submittingOrders} style={{ minWidth: 200 }} onClick={submitAllOrders}>
                  <i className="fas fa-paper-plane" style={{ marginRight: 8 }}></i>
                  {submittingOrders ? "提交中..." : "添加订单"}
                </button>
              </div>
            </div>

            {/* Order list grouped by date */}
            <div className="card mt-4">
              <div className="card-header">订单列表</div>
              <div className="card-body">
                {orderGroups.length === 0 ? (
                  <div className="text-center text-muted py-4">
                    <i className="fas fa-box-open" style={{ fontSize: 48, opacity: 0.3 }}></i>
                    <p>暂无订单，请先添加</p>
                  </div>
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
                  const isExpanded = expandedOrderGroups.has(date);

                  return (
                    <div key={date} className="order-date-group mb-3">
                      <div className="card">
                        <div className="card-header d-flex justify-content-between align-items-center" style={{ background: "white", borderBottom: "2px solid #e9ecef", cursor: "pointer" }} onClick={() => toggleOrderGroup(date)}>
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
                                        <>
                                          <span className="badge bg-warning text-dark mb-1" title={`被 ${item.locked_by_name} 锁定`}><i className="fas fa-lock" style={{ marginRight: 4 }}></i>审批中</span>
                                          <br />
                                          <button className="btn btn-sm btn-outline-secondary" disabled><i className="fas fa-edit"></i> 编辑</button>
                                          <button className="btn btn-sm btn-outline-secondary" disabled><i className="fas fa-trash"></i> 删除</button>
                                        </>
                                      ) : (
                                        <>
                                          <button className="btn btn-sm btn-warning" onClick={() => window.location.href = `/order/edit/${item.ids[0]}`}><i className="fas fa-edit"></i> 编辑</button>
                                          <button className="btn btn-sm btn-danger" onClick={() => deleteOrder(item.ids[0])}><i className="fas fa-trash"></i> 删除</button>
                                        </>
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
            {showEditOrderModal && editingOrderIndex >= 0 && (
              <div className="modal-overlay" onClick={() => setShowEditOrderModal(false)}>
                <div className="modal-dialog" onClick={e => e.stopPropagation()}>
                  <div className="modal-content">
                    <div className="modal-header">
                      <h5 className="modal-title">编辑暂存订单</h5>
                      <button type="button" className="btn-close" onClick={() => setShowEditOrderModal(false)}></button>
                    </div>
                    <div className="modal-body">
                      <div className="mb-3">
                        <label className="form-label">客户名称</label>
                        <select className="form-select" value={editOrderCustomer} onChange={e => setEditOrderCustomer(e.target.value)}>
                          {customers.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
                        </select>
                      </div>
                      <div className="mb-3">
                        <label className="form-label">产品名称</label>
                        <input type="text" className="form-control" value={stagedOrders[editingOrderIndex]?.productName || ""} readOnly />
                      </div>
                      <div className="mb-3">
                        <label className="form-label">订单数量</label>
                        <input type="number" className="form-control" value={editOrderQuantity} min={1} onChange={e => setEditOrderQuantity(parseInt(e.target.value) || 1)} />
                      </div>
                      <div className="mb-3">
                        <label className="form-label">抵扣备货数量</label>
                        <div className="input-group">
                          <input type="number" className="form-control" value={editOrderDeductQuantity} min={0} max={Math.min(editOrderQuantity, editOrderAvailableStock)} onChange={e => setEditOrderDeductQuantity(parseInt(e.target.value) || 0)} />
                          <span className="input-group-text">件</span>
                        </div>
                        <div className="mt-2">
                          <small className={editOrderAvailableStock > 0 ? "text-success" : "text-muted"}>
                            {editOrderAvailableStock > 0
                              ? `当前可用备货: ${editOrderAvailableStock} 件`
                              : "暂无可用备货"}
                          </small>
                        </div>
                      </div>
                      <div className="mb-3">
                        <label className="form-label">备注</label>
                        <textarea className="form-control" rows={2} value={editOrderNote} onChange={e => setEditOrderNote(e.target.value)} />
                      </div>
                    </div>
                    <div className="modal-footer">
                      <button className="btn btn-secondary" onClick={() => setShowEditOrderModal(false)}>取消</button>
                      <button className="btn btn-primary" onClick={saveEditOrder}>保存</button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ==================== 备货管理 Tab ==================== */}
        {activeTab === "stockin" && (
          <div className="tab-content active">
            <div className="row">
              <div className="col-lg-6">
                <div className="card mt-3">
                  <div className="card-header d-flex justify-content-between align-items-center">
                    <span>备货信息录入</span>
                    {stagedStockins.length > 0 && (
                      <span className="badge bg-light text-dark">已暂存: {stagedStockins.length}</span>
                    )}
                  </div>
                  <div className="card-body">
                    <div className="row mb-3">
                      <div className="col-md-6">
                        <label className="form-label">客户名称</label>
                        <select className="form-select" value={siCustomer} onChange={e => setSiCustomer(e.target.value)}>
                          <option value="">请选择客户</option>
                          {customers.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
                        </select>
                      </div>
                      <div className="col-md-6">
                        <label className="form-label">备货时间</label>
                        <input type="date" className="form-control" value={siDate} onChange={e => setSiDate(e.target.value)} />
                      </div>
                    </div>

                    <div className="mb-3" style={{ position: "relative" }} ref={siSearchRef}>
                      <label className="form-label">产品名称</label>
                      <input type="text" className="form-control" placeholder="输入产品名称搜索" autoComplete="off" value={siProductSearch} onChange={e => handleSiProductSearch(e.target.value)} onFocus={() => siProductResults.length > 0 && setShowSiAutocomplete(true)} />
                      {showSiAutocomplete && siProductResults.length > 0 && (
                        <div className="autocomplete-dropdown">
                          {siProductResults.map(p => (
                            <div key={p.id} className="autocomplete-item" onMouseDown={() => {
                              setSiProductSearch(p.name);
                              setSiProductId(p.id);
                              setShowSiAutocomplete(false);
                            }}>
                              {p.name}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="row mb-3">
                      <div className="col-md-6">
                        <label className="form-label">备货数量</label>
                        <input type="number" className="form-control" value={siQuantity} min={1} onChange={e => setSiQuantity(parseInt(e.target.value) || 1)} />
                      </div>
                    </div>

                    <div className="mb-3">
                      <label className="form-label">备注</label>
                      <textarea className="form-control" rows={2} placeholder="例如：批量备货" value={siNote} onChange={e => setSiNote(e.target.value)} />
                    </div>

                    <div className="d-flex gap-2">
                      <button type="button" className={`btn ${canAddStockin ? "btn-primary" : "btn-secondary"}`} disabled={!canAddStockin} onClick={addStagedStockin}>
                        <i className="fas fa-plus-circle" style={{ marginRight: 4 }}></i>新增备货
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <div className="col-lg-6">
                <div className="card mt-3">
                  <div className="card-header">
                    <div className="d-flex justify-content-between align-items-center">
                      <span>暂存备货列表</span>
                      <span>共 {stagedStockins.length} 个，合计 {stagedStockins.reduce((s, i) => s + i.quantity, 0)}</span>
                    </div>
                  </div>
                  <div className="card-body">
                    <div style={{ maxHeight: 400, overflowY: "auto" }}>
                      {stagedStockins.length === 0 ? (
                        <div className="text-center text-muted py-4">
                          <i className="fas fa-box-open" style={{ fontSize: 48, opacity: 0.3 }}></i>
                          <p>暂无暂存备货</p>
                        </div>
                      ) : (
                        stagedStockins.map((si, idx) => (
                          <div key={idx} className="card mb-2" style={{ border: `2px solid ${si.is_validated === false ? "#dc3545" : "var(--plush-blue-light, #e0e0e0)"}` }}>
                            <div className="card-body">
                              <div className="d-flex justify-content-between align-items-center">
                                <div className="d-flex align-items-center gap-3 flex-wrap">
                                  <span className="text-muted small"><i className="fas fa-user" style={{ marginRight: 4 }}></i>{escapeHtml(si.customer)}</span>
                                  <span className="text-muted small"><i className="fas fa-calendar-alt" style={{ marginRight: 4 }}></i>{escapeHtml(si.stockinDate)}</span>
                                  <span><i className="fas fa-cubes text-primary" style={{ marginRight: 4 }}></i>{escapeHtml(si.productName)}</span>
                                  {si.is_validated === false ? <span className="badge bg-danger ms-1">验证失败</span> : <span className="badge bg-success ms-1">已验证</span>}
                                  <span className="badge bg-light text-dark">数量: {si.quantity}</span>
                                  {si.note && <span className="badge bg-light text-dark">备注: {escapeHtml(si.note)}</span>}
                                </div>
                                <div className="d-flex gap-1 ms-2">
                                  <button className="btn btn-sm btn-outline-warning" onClick={() => openEditSiModal(idx)}><i className="fas fa-edit"></i></button>
                                  <button className="btn btn-sm btn-outline-danger" onClick={() => deleteStagedStockin(idx)}><i className="fas fa-trash"></i></button>
                                </div>
                              </div>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>

                {/* Batch upload stockin */}
                <div className="card mt-3">
                  <div className="card-header d-flex justify-content-between align-items-center collapse-trigger" style={{ cursor: "pointer" }} onClick={() => setShowSiBatchUpload(!showSiBatchUpload)}>
                    <h6 className="mb-0 fw-bold">批量导入备货</h6>
                    <i className={`fas fa-chevron-down collapse-arrow ${showSiBatchUpload ? "expanded" : ""}`}></i>
                  </div>
                  {showSiBatchUpload && (
                    <div className="card-body">
                      <div className="border border-dashed p-4 text-center rounded" style={{ minHeight: 120, cursor: "pointer", background: "#fafafa", borderColor: "#dee2e6" }} onClick={() => siFileRef.current?.click()}>
                        <div className="d-flex flex-column align-items-center justify-content-center" style={{ minHeight: 80 }}>
                          <i className="fas fa-file-excel text-success" style={{ fontSize: 32, opacity: 0.8, marginBottom: 8 }}></i>
                          <p className="text-muted mb-1 small">拖拽或点击选择 Excel 文件</p>
                          <p className="text-muted mb-0" style={{ fontSize: 11, color: "#adb5bd" }}>支持 .xlsx / .xls 格式</p>
                        </div>
                        <input ref={siFileRef} type="file" style={{ display: "none" }} accept=".xlsx,.xls" onChange={e => { if (e.target.files?.[0]) setSiExcelFile(e.target.files[0]); }} />
                      </div>
                      {siExcelFile && <div className="mt-2"><small className="text-success">已选择: {siExcelFile.name}</small></div>}
                      {siUploadStatus && <div className="mt-2"><small>{siUploadStatus}</small></div>}
                      <div className="d-flex justify-content-between align-items-center mt-3">
                        <a className="btn btn-outline-secondary btn-sm" href="/api/v1/batch/download-template" download>
                          <i className="fas fa-download" style={{ marginRight: 8 }}></i>备货模板
                        </a>
                        <button className="btn btn-success btn-sm" disabled={!siExcelFile} onClick={handleSiImport}>
                          <i className="fas fa-file-import" style={{ marginRight: 8 }}></i>确认导入
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Submit button */}
            <div className="card mt-4">
              <div className="card-body text-center py-4">
                <button className="btn btn-primary btn-lg" disabled={stagedStockins.length === 0 || submittingStockins} style={{ minWidth: 200 }} onClick={submitAllStockins}>
                  <i className="fas fa-paper-plane" style={{ marginRight: 8 }}></i>
                  {submittingStockins ? "提交中..." : "添加备货"}
                </button>
              </div>
            </div>

            {/* Stockin list grouped by date */}
            <div className="card mt-4">
              <div className="card-header">备货记录列表</div>
              <div className="card-body">
                {siGroups.length === 0 ? (
                  <div className="text-center text-muted py-4">
                    <i className="fas fa-box-open" style={{ fontSize: 48, opacity: 0.3 }}></i>
                    <p>暂无备货记录，请先添加</p>
                  </div>
                ) : siGroups.map(([date, dateStockins]) => {
                  const summaryMap: Record<string, { customer: string; product: Product; quantity: number; deducted: number; notes: string[]; ids: number[] }> = {};
                  dateStockins.forEach(s => {
                    const key = `${s.customer}|||${s.product.id}`;
                    if (!summaryMap[key]) summaryMap[key] = { customer: s.customer, product: s.product, quantity: 0, deducted: 0, notes: [], ids: [] };
                    summaryMap[key].quantity += s.quantity;
                    summaryMap[key].deducted += s.deducted;
                    if (s.note && !summaryMap[key].notes.includes(s.note)) summaryMap[key].notes.push(s.note);
                    summaryMap[key].ids.push(s.id);
                  });
                  const summaryList = Object.values(summaryMap);
                  const totalCount = summaryList.reduce((s, i) => s + i.quantity, 0);
                  const isExpanded = expandedSiGroups.has(date);

                  return (
                    <div key={date} className="stockin-date-group mb-3">
                      <div className="card">
                        <div className="card-header d-flex justify-content-between align-items-center" style={{ background: "white", borderBottom: "2px solid #e9ecef", cursor: "pointer" }} onClick={() => toggleSiGroup(date)}>
                          <div className="d-flex align-items-center flex-grow-1">
                            <i className="fas fa-calendar-alt text-primary" style={{ marginRight: 8 }}></i>
                            <strong>{date}</strong>
                            <span className="badge ms-2">{dateStockins.length} 条记录</span>
                            <span className="badge ms-1">共 {totalCount} 件</span>
                          </div>
                          <i className={`fas fa-chevron-down text-muted toggle-icon ${isExpanded ? "expanded" : ""}`}></i>
                        </div>
                        {isExpanded && (
                          <div className="card-body p-0">
                            <table className="table table-hover mb-0">
                              <thead><tr><th style={{ width: "12%" }}>客户</th><th style={{ width: "8%" }}>产品图片</th><th style={{ width: "20%" }}>产品名称</th><th style={{ width: "10%" }}>69码</th><th style={{ width: "10%" }}>数量</th><th style={{ width: "10%" }}>可用</th><th style={{ width: "10%" }}>备注</th><th style={{ width: "10%" }}>操作</th></tr></thead>
                              <tbody>
                                {summaryList.map((item, i) => {
                                  const available = item.quantity - item.deducted;
                                  return (
                                    <tr key={i}>
                                      <td>{escapeHtml(item.customer)}</td>
                                      <td>{item.product.image ? <img src={item.product.image} style={{ width: 50, height: 50, objectFit: "cover", borderRadius: 8 }} /> : "-"}</td>
                                      <td>{escapeHtml(item.product.name)}</td>
                                      <td>{escapeHtml(item.product.barcode || "-")}</td>
                                      <td><strong>{item.quantity}</strong></td>
                                      <td className={available > 0 ? "text-success" : "text-muted"}><strong>{available}</strong></td>
                                      <td><small>{escapeHtml(item.notes.length > 0 ? item.notes.join("; ") : "-")}</small></td>
                                      <td>
                                        <button className="btn btn-sm btn-danger" onClick={() => deleteStockin(item.ids[0])}><i className="fas fa-trash"></i> 删除</button>
                                      </td>
                                    </tr>
                                  );
                                })}
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

            {/* Edit staged stockin modal */}
            {showEditSiModal && editingSiIndex >= 0 && (
              <div className="modal-overlay" onClick={() => setShowEditSiModal(false)}>
                <div className="modal-dialog" onClick={e => e.stopPropagation()}>
                  <div className="modal-content">
                    <div className="modal-header">
                      <h5 className="modal-title">编辑暂存备货</h5>
                      <button type="button" className="btn-close" onClick={() => setShowEditSiModal(false)}></button>
                    </div>
                    <div className="modal-body">
                      <div className="mb-3">
                        <label className="form-label">客户名称</label>
                        <select className="form-select" value={editSiCustomer} onChange={e => setEditSiCustomer(e.target.value)}>
                          {customers.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
                        </select>
                      </div>
                      <div className="mb-3">
                        <label className="form-label">备货时间</label>
                        <input type="date" className="form-control" value={editSiDate} onChange={e => setEditSiDate(e.target.value)} />
                      </div>
                      <div className="mb-3">
                        <label className="form-label">产品名称</label>
                        <input type="text" className="form-control" value={stagedStockins[editingSiIndex]?.productName || ""} readOnly />
                      </div>
                      <div className="mb-3">
                        <label className="form-label">备货数量</label>
                        <input type="number" className="form-control" value={editSiQuantity} min={1} onChange={e => setEditSiQuantity(parseInt(e.target.value) || 1)} />
                      </div>
                      <div className="mb-3">
                        <label className="form-label">备注</label>
                        <textarea className="form-control" rows={2} value={editSiNote} onChange={e => setEditSiNote(e.target.value)} />
                      </div>
                    </div>
                    <div className="modal-footer">
                      <button className="btn btn-secondary" onClick={() => setShowEditSiModal(false)}>取消</button>
                      <button className="btn btn-primary" onClick={saveEditSi}>保存</button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ========== Styles matching Jinja2 template ========== */}
      <style jsx global>{`
        .co-page-root h2 {
          margin-bottom: 8px;
        }

        /* Tab styles */
        .co-page-root .customer-order-tabs {
          margin-top: 8px;
        }
        .co-page-root .tab-list {
          border-bottom: 2px solid var(--plush-blue-light, #e0e0e0);
          margin-bottom: 0;
          gap: 0;
          display: flex;
        }
        .co-page-root .tab-item {
          padding: 12px 28px;
          font-size: 15px;
          font-weight: 500;
          color: #666;
          border-bottom: 3px solid transparent;
          margin-bottom: -2px;
          transition: all 0.2s ease;
          cursor: pointer;
          background: none;
          border-top: none;
          border-left: none;
          border-right: none;
        }
        .co-page-root .tab-item:hover {
          color: var(--plush-blue, #007bff);
          background: rgba(0,123,255,0.04);
        }
        .co-page-root .tab-item.active {
          color: var(--plush-blue, #007bff);
          border-bottom-color: var(--plush-blue, #007bff);
          font-weight: 600;
        }
        .co-page-root .tab-panel-wrapper {
          border-top: none;
        }

        /* Toggle icon */
        .co-page-root .toggle-icon {
          transition: transform 0.3s ease;
        }
        .co-page-root .toggle-icon.expanded {
          transform: rotate(180deg);
        }

        /* Order collapse content */
        .co-page-root .order-collapse-content {
          display: none;
        }
        .co-page-root .order-collapse-content.expanded {
          display: block;
        }

        /* Order date group */
        .co-page-root .order-date-group .card {
          border: 1px solid #e9ecef;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
          transition: all 0.2s ease;
        }
        .co-page-root .order-date-group .card:hover {
          box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
        }
        .co-page-root .order-date-group .card-header {
          border-radius: 0 !important;
          padding: 12px 16px;
          transition: all 0.2s ease;
          font-weight: 500;
          position: relative;
          z-index: 10;
        }
        .co-page-root .order-date-group .card-header:hover {
          background-color: #f8f9fa !important;
        }
        .co-page-root .order-date-group .table {
          margin-bottom: 0;
        }
        .co-page-root .order-date-group .table th {
          background-color: #f8f9fa;
          font-weight: 600;
          border-top: none;
          font-size: 0.9em;
        }
        .co-page-root .order-date-group .table td {
          vertical-align: middle;
        }
        .co-page-root .order-date-group .badge {
          font-size: 0.8em;
          padding: 4px 8px;
        }
        .co-page-root .order-date-group .btn-sm {
          padding: 4px 8px;
          font-size: 0.85em;
        }
        .co-page-root .order-date-group img {
          transition: transform 0.2s ease;
        }
        .co-page-root .order-date-group img:hover {
          transform: scale(1.1);
        }

        /* Stockin collapse content */
        .co-page-root .stockin-collapse-content {
          display: none;
        }
        .co-page-root .stockin-collapse-content.expanded {
          display: block;
        }

        /* Stockin date group */
        .co-page-root .stockin-date-group .card {
          border: 1px solid #e9ecef;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
          transition: all 0.2s ease;
        }
        .co-page-root .stockin-date-group .card:hover {
          box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
        }
        .co-page-root .stockin-date-group .card-header {
          border-radius: 0 !important;
          padding: 12px 16px;
          transition: all 0.2s ease;
          font-weight: 500;
          position: relative;
          z-index: 10;
        }
        .co-page-root .stockin-date-group .card-header:hover {
          background-color: #f8f9fa !important;
        }
        .co-page-root .stockin-date-group .table {
          margin-bottom: 0;
        }
        .co-page-root .stockin-date-group .table th {
          background-color: #f8f9fa;
          font-weight: 600;
          border-top: none;
          font-size: 0.9em;
        }
        .co-page-root .stockin-date-group .table td {
          vertical-align: middle;
        }
        .co-page-root .stockin-date-group .badge {
          font-size: 0.8em;
          padding: 4px 8px;
        }
        .co-page-root .stockin-date-group .btn-sm {
          padding: 4px 8px;
          font-size: 0.85em;
        }
        .co-page-root .stockin-date-group img {
          transition: transform 0.2s ease;
        }
        .co-page-root .stockin-date-group img:hover {
          transform: scale(1.1);
        }

        /* Autocomplete dropdown */
        .co-page-root .autocomplete-dropdown {
          position: absolute;
          top: 100%;
          left: 0;
          right: 0;
          background: white;
          border: 2px solid var(--plush-blue-light, #e0e0e0);
          border-radius: 8px;
          box-shadow: 0 4px 12px rgba(0,0,0,0.1);
          z-index: 1000;
          max-height: 200px;
          overflow-y: auto;
        }
        .co-page-root .autocomplete-item {
          padding: 10px 14px;
          cursor: pointer;
          transition: all 0.2s ease;
          border-bottom: 1px solid #f0f0f0;
        }
        .co-page-root .autocomplete-item:last-child {
          border-bottom: none;
        }
        .co-page-root .autocomplete-item:hover {
          background-color: var(--plush-blue-light, #e0e0e0);
          transform: translateX(5px);
        }

        /* Collapse arrow */
        .co-page-root .collapse-arrow {
          transition: transform 0.3s ease;
        }
        .co-page-root .collapse-arrow.expanded {
          transform: rotate(180deg);
        }

        /* Modal overlay */
        .co-page-root .modal-overlay {
          position: fixed;
          top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0,0,0,0.5);
          z-index: 1050;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .co-page-root .modal-dialog {
          background: white;
          border-radius: 8px;
          width: 500px;
          max-width: 90vw;
          box-shadow: 0 4px 20px rgba(0,0,0,0.2);
        }
        .co-page-root .modal-content {
          border: none;
        }
        .co-page-root .modal-header {
          padding: 16px 20px;
          border-bottom: 1px solid #e9ecef;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .co-page-root .modal-title {
          margin: 0;
          font-size: 18px;
        }
        .co-page-root .btn-close {
          background: none;
          border: none;
          font-size: 20px;
          cursor: pointer;
          padding: 0;
          line-height: 1;
          color: #999;
        }
        .co-page-root .btn-close:hover {
          color: #333;
        }
        .co-page-root .modal-body {
          padding: 20px;
        }
        .co-page-root .modal-footer {
          padding: 12px 20px;
          border-top: 1px solid #e9ecef;
          display: flex;
          justify-content: flex-end;
          gap: 8px;
        }

        /* Bootstrap utility classes */
        .co-page-root .row { display: flex; flex-wrap: wrap; margin: 0 -12px; }
        .co-page-root .col-lg-6 { flex: 0 0 50%; max-width: 50%; padding: 0 12px; }
        .co-page-root .col-md-6 { flex: 0 0 50%; max-width: 50%; padding: 0 12px; }
        .co-page-root .card { background: #fff; border: 1px solid rgba(0,0,0,.125); border-radius: .375rem; }
        .co-page-root .card-header { padding: .75rem 1.25rem; border-bottom: 1px solid rgba(0,0,0,.125); background: #fff; }
        .co-page-root .card-body { padding: 1.25rem; }
        .co-page-root .d-flex { display: flex; }
        .co-page-root .justify-content-between { justify-content: space-between; }
        .co-page-root .align-items-center { align-items: center; }
        .co-page-root .flex-wrap { flex-wrap: wrap; }
        .co-page-root .gap-3 { gap: 1rem; }
        .co-page-root .gap-2 { gap: .5rem; }
        .co-page-root .mb-3 { margin-bottom: 1rem; }
        .co-page-root .mt-2 { margin-top: .5rem; }
        .co-page-root .mt-3 { margin-top: 1rem; }
        .co-page-root .mt-4 { margin-top: 1.5rem; }
        .co-page-root .me-2 { margin-right: .5rem; }
        .co-page-root .ms-2 { margin-left: .5rem; }
        .co-page-root .ms-1 { margin-left: .25rem; }
        .co-page-root .mb-0 { margin-bottom: 0; }
        .co-page-root .mb-2 { margin-bottom: .5rem; }
        .co-page-root .py-4 { padding-top: 1.5rem; padding-bottom: 1.5rem; }
        .co-page-root .p-0 { padding: 0; }
        .co-page-root .fw-bold { font-weight: 700; }
        .co-page-root .text-center { text-align: center; }
        .co-page-root .text-muted { color: #6c757d; }
        .co-page-root .text-success { color: #198754; }
        .co-page-root .text-primary { color: #0d6efd; }
        .co-page-root .text-danger { color: #dc3545; }
        .co-page-root .text-warning { color: #ffc107; }
        .co-page-root .small { font-size: .875em; }
        .co-page-root .form-label { margin-bottom: .5rem; font-size: .875rem; }
        .co-page-root .form-control, .co-page-root .form-select {
          display: block; width: 100%; padding: .375rem .75rem;
          font-size: 1rem; font-weight: 400; line-height: 1.5;
          color: #212529; background-color: #fff;
          border: 1px solid #ced4da; border-radius: .375rem;
          transition: border-color .15s ease-in-out;
        }
        .co-page-root .form-control:focus, .co-page-root .form-select:focus {
          border-color: #86b7fe; outline: 0;
          box-shadow: 0 0 0 .25rem rgba(13,110,253,.25);
        }
        .co-page-root .btn {
          display: inline-block; font-weight: 400; text-align: center;
          vertical-align: middle; cursor: pointer; padding: .375rem .75rem;
          font-size: 1rem; border-radius: .375rem; border: 1px solid transparent;
          transition: color .15s ease-in-out, background-color .15s ease-in-out;
        }
        .co-page-root .btn:disabled { opacity: .65; cursor: not-allowed; }
        .co-page-root .btn-primary { color: #fff; background-color: #0d6efd; border-color: #0d6efd; }
        .co-page-root .btn-primary:hover:not(:disabled) { background-color: #0b5ed7; }
        .co-page-root .btn-secondary { color: #fff; background-color: #6c757d; border-color: #6c757d; }
        .co-page-root .btn-success { color: #fff; background-color: #198754; border-color: #198754; }
        .co-page-root .btn-danger { color: #fff; background-color: #dc3545; border-color: #dc3545; }
        .co-page-root .btn-warning { color: #000; background-color: #ffc107; border-color: #ffc107; }
        .co-page-root .btn-outline-secondary { color: #6c757d; border-color: #6c757d; background: transparent; }
        .co-page-root .btn-outline-warning { color: #ffc107; border-color: #ffc107; background: transparent; }
        .co-page-root .btn-outline-danger { color: #dc3545; border-color: #dc3545; background: transparent; }
        .co-page-root .btn-sm { padding: .25rem .5rem; font-size: .875rem; border-radius: .25rem; }
        .co-page-root .btn-lg { padding: .5rem 1rem; font-size: 1.25rem; border-radius: .5rem; }
        .co-page-root .badge { display: inline-block; padding: .35em .65em; font-size: .75em; font-weight: 700; border-radius: .375rem; }
        .co-page-root .bg-light { background-color: #f8f9fa; }
        .co-page-root .bg-success { background-color: #198754; }
        .co-page-root .bg-danger { background-color: #dc3545; }
        .co-page-root .bg-secondary { background-color: #6c757d; }
        .co-page-root .bg-warning { background-color: #ffc107; }
        .co-page-root .text-dark { color: #212529; }
        .co-page-root .table { width: 100%; border-collapse: collapse; }
        .co-page-root .table th, .co-page-root .table td { padding: .5rem; vertical-align: top; border-top: 1px solid #dee2e6; }
        .co-page-root .table-hover tbody tr:hover { background-color: rgba(0,0,0,.075); }
        .co-page-root .table-warning { --bs-table-bg: #fff3cd; }
        .co-page-root .input-group { display: flex; }
        .co-page-root .input-group-text {
          display: flex; align-items: center; padding: .375rem .75rem;
          font-size: 1rem; font-weight: 400; line-height: 1.5;
          color: #212529; text-align: center; background-color: #e9ecef;
          border: 1px solid #ced4da; border-radius: 0 .375rem .375rem 0;
        }
        .co-page-root .border-dashed { border-style: dashed !important; }
        .co-page-root .deductible-display { user-select: none; }

        @media (max-width: 992px) {
          .co-page-root .col-lg-6 { flex: 0 0 100%; max-width: 100%; }
        }
      `}</style>
    </div>
  );
}
