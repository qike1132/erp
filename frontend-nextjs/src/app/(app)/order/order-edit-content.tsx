"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import { get, put, post } from "@/lib/api-client";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState, useRef, useCallback } from "react";

interface Product {
  id: number;
  name: string;
  barcode?: string;
  image?: string;
  current_stock?: number;
  origin?: string;
}

interface Order {
  id: number;
  order_no: string;
  customer: string;
  product: Product | null;
  product_id: number;
  quantity: number;
  deduct_quantity: number;
  order_date: string;
  note: string;
  status: string;
  order_type: string;
  country: string;
}

interface Customer { id: number; name: string; }

export function OrderEditContent() {
  const params = useParams();
  const router = useRouter();
  const orderId = params.id as string;
  const isEdit = orderId !== "new";

  const [customer, setCustomer] = useState("");
  const [productSearch, setProductSearch] = useState("");
  const [productId, setProductId] = useState<number | null>(null);
  const [quantity, setQuantity] = useState(1);
  const [orderDate, setOrderDate] = useState(() => new Date().toISOString().split("T")[0]);
  const [note, setNote] = useState("");
  const [orderType, setOrderType] = useState("regular");
  const [country, setCountry] = useState("");
  const [productResults, setProductResults] = useState<Product[]>([]);
  const [showAutocomplete, setShowAutocomplete] = useState(false);
  const [deductedQuantity, setDeductedQuantity] = useState(0);
  const [initialized, setInitialized] = useState(false);

  const searchRef = useRef<HTMLDivElement>(null);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { data: orderData, isLoading } = useQuery({
    queryKey: ["orders", "detail", orderId],
    queryFn: () => get<Order>("/orders/" + orderId),
    enabled: isEdit,
  });

  const { data: customersData } = useQuery({
    queryKey: ["customers-list"],
    queryFn: () => get<{ success: boolean; data: Customer[] }>("/customers/list"),
  });

  const customers = customersData?.data ?? [];

  // Initialize form from order data
  useMemo(() => {
    if (orderData && !initialized) {
      setCustomer(orderData.customer || "");
      setProductSearch(orderData.product?.name || "");
      setProductId(orderData.product_id);
      setQuantity(orderData.quantity || 1);
      setNote(orderData.note || "");
      setOrderType(orderData.order_type || "regular");
      setCountry(orderData.country || "");
      setDeductedQuantity(orderData.deduct_quantity || 0);
      if (orderData.order_date) {
        setOrderDate(orderData.order_date.split(" ")[0] || orderData.order_date.split("T")[0]);
      }
      setInitialized(true);
    }
  }, [orderData, initialized]);

  // Click outside
  useMemo(() => {
    const handler = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) setShowAutocomplete(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Product search
  const searchProducts = useCallback(async (query: string) => {
    if (!query.trim()) { setProductResults([]); return; }
    try {
      const data = await get<Product[]>("/aux/product-search", { q: query });
      setProductResults(Array.isArray(data) ? data : []);
    } catch { setProductResults([]); }
  }, []);

  const handleProductSearch = useCallback((val: string) => {
    setProductSearch(val);
    setProductId(null);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => searchProducts(val), 300);
    setShowAutocomplete(true);
  }, [searchProducts]);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: async () => {
      const body = {
        customer,
        product_id: productId,
        quantity,
        note: note || undefined,
        order_type: orderType,
        country: country || undefined,
        order_date: orderDate,
      };
      if (isEdit) return put<{ success: boolean; message?: string }>(`/orders/edit/${orderId}`, body);
      return post<{ success: boolean; message?: string }>("/orders/create", body);
    },
    onSuccess: () => { alert(isEdit ? "编辑成功" : "创建成功"); router.push("/order"); },
    onError: (err: Error) => { alert(err.message); },
  });

  if (isEdit && isLoading) {
    return <div className="oe-page-root"><div className="text-center py-5"><p>加载订单数据...</p></div></div>;
  }

  return (
    <div className="oe-page-root">
      <h2><i className="fas fa-edit" style={{ marginRight: 8 }}></i>{isEdit ? "编辑订单" : "新建订单"}</h2>

      <div className="card mt-3">
        <div className="card-body">
          <form onSubmit={(e) => { e.preventDefault(); saveMutation.mutate(); }}>
            <div className="row">
              <div className="col-md-6">
                <div className="mb-3">
                  <label className="form-label">订单时间</label>
                  <input type="text" className="form-control" value={orderData?.order_no || ""} readOnly />
                </div>
              </div>
              <div className="col-md-6">
                <div className="mb-3">
                  <label className="form-label">客户名称</label>
                  <select className="form-select" value={customer} onChange={e => setCustomer(e.target.value)} required>
                    <option value="">请选择客户</option>
                    {customers.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
                  </select>
                </div>
              </div>
            </div>

            <div className="row">
              <div className="col-md-6">
                <div className="mb-3" ref={searchRef}>
                  <label className="form-label">产品</label>
                  <input type="text" className="form-control" placeholder="输入产品名称或69码搜索" autoComplete="off" value={productSearch} onChange={e => handleProductSearch(e.target.value)} onFocus={() => productResults.length > 0 && setShowAutocomplete(true)} required />
                  {showAutocomplete && productResults.length > 0 && (
                    <div className="autocomplete-dropdown">
                      {productResults.map(p => (
                        <div key={p.id} className="autocomplete-item" onMouseDown={() => { setProductSearch(p.name); setProductId(p.id); setShowAutocomplete(false); }}>
                          {p.name} {p.barcode && <span className="text-muted">({p.barcode})</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <div className="col-md-6">
                <div className="mb-3">
                  <label className="form-label">订单数量</label>
                  <input type="number" className="form-control" value={quantity} min={1} onChange={e => setQuantity(parseInt(e.target.value) || 1)} required />
                  {deductedQuantity > 0 && (
                    <div className="mt-2 p-2 bg-light rounded border">
                      <small className="text-muted">
                        <strong>已抵扣备货数量：</strong>
                        <span className="badge bg-success">{deductedQuantity}</span>
                        <span className="text-muted ms-2">（剩余待备货：{quantity - deductedQuantity}）</span>
                      </small>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="row">
              <div className="col-md-6">
                <div className="mb-3">
                  <label className="form-label">下单时间</label>
                  <input type="date" className="form-control" value={orderDate} onChange={e => setOrderDate(e.target.value)} />
                </div>
              </div>
              <div className="col-md-6">
                <div className="mb-3">
                  <label className="form-label">备注</label>
                  <textarea className="form-control" rows={2} value={note} onChange={e => setNote(e.target.value)} />
                </div>
              </div>
            </div>

            <div className="mb-3">
              <label className="form-label">当前产品信息</label>
              <div className="border p-3 rounded">
                {orderData?.product?.image && <img src={orderData.product.image} style={{ width: 100, height: 100, objectFit: "cover", marginBottom: 10 }} />}
                <div><strong>产品名称：</strong>{orderData?.product?.name || "-"}</div>
                <div><strong>69码：</strong>{orderData?.product?.barcode || "-"}</div>
                <div><strong>产地：</strong>{(orderData?.product as Product)?.origin || "-"}</div>
                <div><strong>当前库存：</strong><span className={`badge ${(orderData?.product as Product)?.current_stock ?? 0 > 0 ? "bg-success" : "bg-danger"}`}>{(orderData?.product as Product)?.current_stock ?? 0}</span></div>
              </div>
            </div>

            <button type="submit" className="btn btn-primary" disabled={saveMutation.isPending}>
              <i className="fas fa-save" style={{ marginRight: 4 }}></i>{saveMutation.isPending ? "保存中..." : "保存修改"}
            </button>
            <button type="button" className="btn btn-secondary" style={{ marginLeft: 8 }} onClick={() => router.push("/order")}>
              <i className="fas fa-times" style={{ marginRight: 4 }}></i>取消
            </button>
          </form>
        </div>
      </div>

      <style jsx global>{`
        .oe-page-root h2 { margin-bottom: 8px; }
        .oe-page-root .autocomplete-dropdown { position: absolute; top: 100%; left: 0; right: 0; background: white; border: 2px solid var(--plush-blue-light, #e0e0e0); border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); z-index: 1000; max-height: 200px; overflow-y: auto; }
        .oe-page-root .autocomplete-item { padding: 10px 14px; cursor: pointer; transition: all 0.2s ease; border-bottom: 1px solid #f0f0f0; }
        .oe-page-root .autocomplete-item:last-child { border-bottom: none; }
        .oe-page-root .autocomplete-item:hover { background-color: var(--plush-blue-light, #e0e0e0); transform: translateX(5px); }
        .oe-page-root .row { display: flex; flex-wrap: wrap; margin: 0 -12px; }
        .oe-page-root .col-md-6 { flex: 0 0 50%; max-width: 50%; padding: 0 12px; }
        .oe-page-root .card { background: #fff; border: 1px solid rgba(0,0,0,.125); border-radius: .375rem; }
        .oe-page-root .card-body { padding: 1.25rem; }
        .oe-page-root .mb-3 { margin-bottom: 1rem; }
        .oe-page-root .mt-2 { margin-top: .5rem; }
        .oe-page-root .mt-3 { margin-top: 1rem; }
        .oe-page-root .ms-2 { margin-left: .5rem; }
        .oe-page-root .p-3 { padding: 1rem; }
        .oe-page-root .text-center { text-align: center; }
        .oe-page-root .text-muted { color: #6c757d; }
        .oe-page-root .py-5 { padding-top: 3rem; padding-bottom: 3rem; }
        .oe-page-root .form-label { margin-bottom: .5rem; font-size: .875rem; }
        .oe-page-root .form-control, .oe-page-root .form-select { display: block; width: 100%; padding: .375rem .75rem; font-size: 1rem; line-height: 1.5; color: #212529; background-color: #fff; border: 1px solid #ced4da; border-radius: .375rem; }
        .oe-page-root .form-control:focus, .oe-page-root .form-select:focus { border-color: #86b7fe; outline: 0; box-shadow: 0 0 0 .25rem rgba(13,110,253,.25); }
        .oe-page-root .btn { display: inline-block; font-weight: 400; text-align: center; cursor: pointer; padding: .375rem .75rem; font-size: 1rem; border-radius: .375rem; border: 1px solid transparent; }
        .oe-page-root .btn:disabled { opacity: .65; cursor: not-allowed; }
        .oe-page-root .btn-primary { color: #fff; background-color: #0d6efd; border-color: #0d6efd; }
        .oe-page-root .btn-secondary { color: #fff; background-color: #6c757d; border-color: #6c757d; }
        .oe-page-root .badge { display: inline-block; padding: .35em .65em; font-size: .75em; font-weight: 700; border-radius: .375rem; }
        .oe-page-root .bg-success { background-color: #198754; color: #fff; }
        .oe-page-root .bg-danger { background-color: #dc3545; color: #fff; }
        .oe-page-root .bg-light { background-color: #f8f9fa; }
        .oe-page-root .border { border: 1px solid #dee2e6; }
        .oe-page-root .rounded { border-radius: .375rem; }
        .oe-page-root .small { font-size: .875em; }
      `}</style>
    </div>
  );
}
