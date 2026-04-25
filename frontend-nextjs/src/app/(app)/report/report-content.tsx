"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "@/lib/api-client";

// ============ Types ============

interface ReportLog {
  order_date?: string; stockin_date?: string; stockout_date?: string; deduction_time?: string;
  customer: string; product_name: string; product_barcode?: string; sku?: string;
  quantity: number; status?: string; note?: string; order_note?: string;
  order_count?: number; stockin_count?: number; stockout_count?: number; deduction_count?: number;
  order_nos?: string; stockin_nos?: string;
}
interface Pagination { total: number; pages: number; page: number; per_page: number }
interface Stats { total_count: number; total_quantity: number }
interface ReportResult { success: boolean; logs: ReportLog[]; pagination: Pagination; stats: Stats }
interface CustomerName { id: number; name: string }

type TabType = "order" | "stockin" | "stockout" | "deduction";

const PER_PAGE = 20;

const TAB_CONFIG: Record<TabType, { label: string; icon: string; endpoint: string; dateKey: string; countKey: string; dateLabel: string; countLabel: string; noteKey: string }> = {
  order:     { label: "订单流水",     icon: "fa-clipboard-list", endpoint: "/reports/order-logs",     dateKey: "order_date",     countKey: "order_count",     dateLabel: "下单时间", countLabel: "数量",     noteKey: "note" },
  stockin:   { label: "备货流水",     icon: "fa-truck-loading",  endpoint: "/reports/stockin-logs",   dateKey: "stockin_date",   countKey: "stockin_count",   dateLabel: "备货时间", countLabel: "备货数量", noteKey: "note" },
  stockout:  { label: "出货流水",     icon: "fa-shipping-fast",  endpoint: "/reports/stockout-logs",  dateKey: "stockout_date",  countKey: "stockout_count",  dateLabel: "出货时间", countLabel: "出货数量", noteKey: "note" },
  deduction: { label: "备货抵扣流水", icon: "fa-exchange-alt",   endpoint: "/reports/deduction-logs", dateKey: "deduction_time", countKey: "deduction_count", dateLabel: "抵扣时间", countLabel: "抵扣数量", noteKey: "order_note" },
};

// ============ Component ============

export function ReportContent() {
  const [tab, setTab] = useState<TabType>("order");
  const [pages, setPages] = useState<Record<TabType, number>>({ order: 1, stockin: 1, stockout: 1, deduction: 1 });
  const [customers, setCustomers] = useState<Record<TabType, string>>({ order: "", stockin: "", stockout: "", deduction: "" });
  const [products, setProducts] = useState<Record<TabType, string>>({ order: "", stockin: "", stockout: "", deduction: "" });
  const [startDates, setStartDates] = useState<Record<TabType, string>>({ order: "", stockin: "", stockout: "", deduction: "" });
  const [endDates, setEndDates] = useState<Record<TabType, string>>({ order: "", stockin: "", stockout: "", deduction: "" });
  const [searched, setSearched] = useState<Record<TabType, boolean>>({ order: false, stockin: false, stockout: false, deduction: false });

  const cfg = TAB_CONFIG[tab];

  // Customer list
  const { data: customerNames } = useQuery<CustomerName[]>({
    queryKey: ["customer-active-names"],
    queryFn: () => get<CustomerName[]>("/customers/active-names"),
  });

  // Report data
  const { data, isLoading } = useQuery<ReportResult>({
    queryKey: ["report", tab, pages[tab], customers[tab], products[tab], startDates[tab], endDates[tab]],
    queryFn: () => get<ReportResult>(cfg.endpoint, {
      page: String(pages[tab]), per_page: String(PER_PAGE),
      ...(customers[tab] && { customer: customers[tab] }),
      ...(products[tab] && { product: products[tab] }),
      ...(startDates[tab] && { start_date: startDates[tab] }),
      ...(endDates[tab] && { end_date: endDates[tab] }),
    }),
    enabled: searched[tab],
  });

  const logs = data?.logs || [];
  const pagination = data?.pagination;
  const stats = data?.stats;

  const switchTab = (t: TabType) => { setTab(t); };

  const doSearch = () => {
    setPages(prev => ({ ...prev, [tab]: 1 }));
    setSearched(prev => ({ ...prev, [tab]: true }));
  };

  const doReset = () => {
    setCustomers(prev => ({ ...prev, [tab]: "" }));
    setProducts(prev => ({ ...prev, [tab]: "" }));
    setStartDates(prev => ({ ...prev, [tab]: "" }));
    setEndDates(prev => ({ ...prev, [tab]: "" }));
    setSearched(prev => ({ ...prev, [tab]: false }));
    setPages(prev => ({ ...prev, [tab]: 1 }));
  };

  const exportReport = () => {
    const params = new URLSearchParams();
    params.set("report_type", tab);
    if (customers[tab]) params.set("customer", customers[tab]);
    if (products[tab]) params.set("product", products[tab]);
    if (startDates[tab]) params.set("start_date", startDates[tab]);
    if (endDates[tab]) params.set("end_date", endDates[tab]);
    window.open(`/api/v1/reports/export?${params.toString()}`, "_blank");
  };

  const statusBadge = (status?: string) => {
    if (!status) return null;
    const map: Record<string, string> = { "待备货": "warning", "部分备货": "info", "已备货": "primary", "待出货": "secondary", "已出货": "success", "已取消": "danger" };
    const cls = map[status] || "secondary";
    return <span className={`badge bg-${cls}`}>{status}</span>;
  };

  return (
    <div className="rp-wrap">
      <h2 className="rp-title"><i className="fas fa-chart-bar" style={{ marginRight: 8 }}></i>报表统计</h2>

      {/* Tabs */}
      <ul className="nav nav-tabs rp-tabs">
        {(Object.keys(TAB_CONFIG) as TabType[]).map(t => (
          <li className="nav-item" key={t}>
            <button className={`nav-link ${tab === t ? "active" : ""}`} onClick={() => switchTab(t)}>
              <i className={`fas ${TAB_CONFIG[t].icon}`} style={{ marginRight: 4 }}></i>{TAB_CONFIG[t].label}
            </button>
          </li>
        ))}
      </ul>

      <div className="rp-panel">
        {/* Search card */}
        <div className="card rp-card">
          <div className="card-header">查询条件</div>
          <div className="card-body">
            <div className="row g-3 align-items-end">
              <div className={tab === "order" ? "col-md-2" : "col-md-3"}>
                <label className="form-label">客户名称</label>
                <select className="form-select" value={customers[tab]} onChange={e => setCustomers(prev => ({ ...prev, [tab]: e.target.value }))}>
                  <option value="">全部客户</option>
                  {customerNames?.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
                </select>
              </div>
              <div className={tab === "order" ? "col-md-2" : "col-md-3"}>
                <label className="form-label">产品名称/SKU</label>
                <input type="text" className="form-control" value={products[tab]} onChange={e => setProducts(prev => ({ ...prev, [tab]: e.target.value }))} placeholder="输入产品名称或SKU" />
              </div>
              <div className={tab === "order" ? "col-md-3" : "col-md-2"}>
                <label className="form-label">开始日期</label>
                <input type="date" className="form-control" value={startDates[tab]} onChange={e => setStartDates(prev => ({ ...prev, [tab]: e.target.value }))} />
              </div>
              <div className={tab === "order" ? "col-md-3" : "col-md-2"}>
                <label className="form-label">结束日期</label>
                <input type="date" className="form-control" value={endDates[tab]} onChange={e => setEndDates(prev => ({ ...prev, [tab]: e.target.value }))} />
              </div>
              <div className="col-md-2">
                <label className="form-label">&nbsp;</label>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn btn-primary" style={{ flex: 1 }} onClick={doSearch}><i className="fas fa-search" style={{ marginRight: 4 }}></i>查询</button>
                  <button className="btn btn-outline-secondary" onClick={doReset}><i className="fas fa-redo"></i></button>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Table card */}
        <div className="card rp-card">
          <div className="card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>{cfg.label}</span>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ fontSize: 14, color: "#718096" }}>共 {pagination?.total ?? 0} 条记录</span>
              {searched[tab] && <button className="btn btn-success btn-sm" onClick={exportReport}><i className="fas fa-file-excel" style={{ marginRight: 4 }}></i>导出</button>}
            </div>
          </div>
          <div className="card-body">
            <table className="table table-hover">
              <thead>
                <tr>
                  <th>{cfg.dateLabel}</th>
                  <th>客户</th>
                  <th>产品名称</th>
                  <th style={{ textAlign: "center" }}>{cfg.countLabel}</th>
                  {tab === "order" && <th>状态</th>}
                  <th>{tab === "deduction" ? "订单备注" : "备注"}</th>
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  <tr><td colSpan={tab === "order" ? 6 : 5} className="rp-td-center">
                    <div className="spinner-border text-primary"></div>
                    <p style={{ color: "#718096", marginTop: 8 }}>正在查询...</p>
                  </td></tr>
                ) : !searched[tab] ? (
                  <tr><td colSpan={tab === "order" ? 6 : 5} className="rp-td-center">
                    <i className="fas fa-inbox" style={{ fontSize: 48, opacity: 0.3, marginBottom: 12 }}></i>
                    <p style={{ color: "#718096" }}>请点击查询按钮获取数据</p>
                  </td></tr>
                ) : logs.length === 0 ? (
                  <tr><td colSpan={tab === "order" ? 6 : 5} className="rp-td-center">
                    <i className="fas fa-inbox" style={{ fontSize: 48, opacity: 0.3, marginBottom: 12 }}></i>
                    <p style={{ color: "#718096" }}>暂无数据</p>
                  </td></tr>
                ) : logs.map((log, i) => (
                  <tr key={i}>
                    <td><i className="fas fa-calendar" style={{ marginRight: 4, color: "#718096", fontSize: 12 }}></i>{(log as unknown as Record<string, unknown>)[cfg.dateKey] as string || "-"}</td>
                    <td>{log.customer || "-"}</td>
                    <td>{log.product_name || "-"}</td>
                    <td style={{ textAlign: "center" }}>{log.quantity}</td>
                    {tab === "order" && <td>{statusBadge(log.status)}</td>}
                    <td style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{(log as unknown as Record<string, unknown>)[cfg.noteKey] as string || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {pagination && pagination.pages > 1 && (
              <nav>
                <ul className="pagination justify-content-center">
                  <li className={`page-item ${pagination.page <= 1 ? "disabled" : ""}`}>
                    <a className="page-link" href="#" onClick={e => { e.preventDefault(); if (pagination.page > 1) setPages(prev => ({ ...prev, [tab]: pagination.page - 1 })); }}>上一页</a>
                  </li>
                  {Array.from({ length: pagination.pages }, (_, i) => i + 1)
                    .filter(p => p === 1 || p === pagination.pages || Math.abs(p - pagination.page) <= 2)
                    .map(p => (
                      <li key={p} className={`page-item ${p === pagination.page ? "active" : ""}`}>
                        <a className="page-link" href="#" onClick={e => { e.preventDefault(); setPages(prev => ({ ...prev, [tab]: p })); }}>{p}</a>
                      </li>
                    ))}
                  <li className={`page-item ${pagination.page >= pagination.pages ? "disabled" : ""}`}>
                    <a className="page-link" href="#" onClick={e => { e.preventDefault(); if (pagination.page < pagination.pages) setPages(prev => ({ ...prev, [tab]: pagination.page + 1 })); }}>下一页</a>
                  </li>
                </ul>
              </nav>
            )}
          </div>
        </div>
      </div>

      <style jsx global>{`
        .rp-wrap { padding: 20px; font-family: "Microsoft YaHei","Segoe UI",sans-serif; }
        .rp-title { font-size: 22px; font-weight: 600; color: #5A4A4A; margin-bottom: 16px; display: flex; align-items: center; }
        .rp-tabs { margin-top: 12px; border-bottom: 3px solid #D4F1F4; }
        .rp-tabs .nav-link { color: #595959; font-weight: 600; border: none; padding: 12px 24px; border-bottom: 3px solid transparent; transition: all 0.4s cubic-bezier(0.4,0,0.2,1); background: rgba(255,255,255,0.7); border-radius: var(--radius-md) var(--radius-md) 0 0; box-shadow: 0 -2px 8px rgba(0,0,0,0.05); cursor: pointer; }
        .rp-tabs .nav-link.active { color: #5A4A4A; background: #FFFFFF; border-bottom-color: #87CEEB; transform: translateY(-2px); box-shadow: 0 -4px 16px rgba(135,206,235,0.35), 0 2px 8px rgba(0,0,0,0.1); }
        .rp-tabs .nav-link:hover:not(.active) { color: #5A4A4A; background: #FFFFFF; transform: translateY(-2px); box-shadow: 0 -4px 12px rgba(176,224,230,0.25), 0 2px 8px rgba(0,0,0,0.1); border-bottom-color: rgba(135,206,235,0.3); }
        .rp-panel { margin-top: 16px; }
        .rp-card { border: none; border-radius: var(--radius-card); box-shadow: 0 4px 16px rgba(176,224,230,0.25); margin-bottom: 16px; overflow: hidden; background: #fff; }
        .rp-card .card-header { padding: 12px 20px; background: #FFFFFF; border-bottom: 2px solid #87CEEB; font-weight: 600; font-size: 15px; color: #5A4A4A; }
        .rp-card .card-body { padding: 20px; }
        .rp-td-center { text-align: center; padding: 40px 20px; }
        @keyframes rp-spin { to { transform: rotate(360deg); } }
        @media (max-width: 768px) {
          .col-md-2, .col-md-3 { flex: 0 0 100%; max-width: 100%; }
        }
      `}</style>
    </div>
  );
}
