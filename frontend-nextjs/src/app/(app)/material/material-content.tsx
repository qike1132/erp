"use client";

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/lib/api-client";

// ============ Types ============

interface OverviewData {
  total: number; recent_registrations: number; pending: number; overdue_items: number;
  partial: number; completed: number; overall_progress: number; total_received: number; total_ordered: number;
  category_stats: { category: string; category_name: string; progress: number; ordered: number; received: number; remaining: number }[];
}

interface TrendItem { date: string; registered: number; received: number; }
interface DistributionItem { status: string; count: number; }

interface RegistrationItem {
  id: number; material_name: string; material_category: string; specification: string;
  unit: string; ordered_quantity: number; received_quantity: number; remaining_quantity: number; progress: number;
}

interface Registration {
  id: number; purchase_order_no: string; customer_name: string; product_name: string;
  product_quantity: number; supplier_name: string; supplier_id: number; status: string;
  progress: number; total_ordered: number; total_received: number; items: RegistrationItem[];
  update_time: string; remark: string;
}

interface SupplierGroup {
  supplier_name: string; supplier_id: number;
  orders: { id: number; order_no: string; customer_name: string; product_name: string; product_quantity: number; items: RegistrationItem[]; status: string; progress: number; total_ordered: number; total_received: number }[];
  allItems: RegistrationItem[];
}

const CATEGORY_MAP: Record<string, string> = { fabric: "面料", filling: "填充", accessory: "辅料", packaging: "包装" };
const STATUS_MAP: Record<string, string> = { pending: "未开始", partial: "部分到货", completed: "全部到货" };
const STATUS_CLS: Record<string, string> = { pending: "pending", partial: "partial", completed: "completed" };
const CAT_FILL: Record<string, string> = { fabric: "fabric", filling: "filling", accessory: "accessory", packaging: "packaging" };

export function MaterialContent() {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<"overview" | "progress" | "history">("overview");

  // Progress tab filters
  const [fSupplier, setFSupplier] = useState("");
  const [fOrderNo, setFOrderNo] = useState("");
  const [fCustomer, setFCustomer] = useState("");
  const [fCategory, setFCategory] = useState("");
  const [fStart, setFStart] = useState("");
  const [fEnd, setFEnd] = useState("");
  const [progressPage, setProgressPage] = useState(1);

  // History tab filters
  const [hOrderNo, setHOrderNo] = useState("");
  const [hSupplier, setHSupplier] = useState("");
  const [hCustomer, setHCustomer] = useState("");
  const [hCategory, setHCategory] = useState("");
  const [hStart, setHStart] = useState("");
  const [hEnd, setHEnd] = useState("");
  const [historyPage, setHistoryPage] = useState(1);

  // Modals
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailContent, setDetailContent] = useState<string>("");
  const [receiveOpen, setReceiveOpen] = useState(false);
  const [receiveItem, setReceiveItem] = useState<{ id: number; name: string; ordered: number; received: number } | null>(null);
  const [receiveQty, setReceiveQty] = useState("");
  const [receiveRemark, setReceiveRemark] = useState("");
  const [orderPreviewOpen, setOrderPreviewOpen] = useState(false);
  const [orderPreviewContent, setOrderPreviewContent] = useState<string>("");

  // ===== Overview queries =====
  const { data: overviewData } = useQuery({
    queryKey: ["mr-overview"],
    queryFn: () => get<{ success: boolean; overview: OverviewData }>("/material-registrations/stats/overview"),
    enabled: activeTab === "overview",
  });

  const { data: trendData } = useQuery({
    queryKey: ["mr-trend"],
    queryFn: () => get<{ success: boolean; trend: TrendItem[] }>("/material-registrations/stats/trend?days=30"),
    enabled: activeTab === "overview",
  });

  const { data: distData } = useQuery({
    queryKey: ["mr-distribution"],
    queryFn: () => get<{ success: boolean; distribution: DistributionItem[] }>("/material-registrations/stats/distribution"),
    enabled: activeTab === "overview",
  });

  // ===== Progress query =====
  const { data: progressData, isLoading: progressLoading } = useQuery({
    queryKey: ["mr-progress", progressPage, fSupplier, fOrderNo, fCustomer, fCategory, fStart, fEnd],
    queryFn: () => get<{ success: boolean; registrations: Registration[]; pages: number; current_page: number }>("/material-registrations/registrations", {
      page: String(progressPage), per_page: "50",
      ...(fSupplier ? { supplier: fSupplier } : {}),
      ...(fOrderNo ? { order_no: fOrderNo } : {}),
      ...(fCustomer ? { customer_name: fCustomer } : {}),
      ...(fCategory ? { material_category: fCategory } : {}),
      ...(fStart ? { start_date: fStart } : {}),
      ...(fEnd ? { end_date: fEnd } : {}),
    }),
    enabled: activeTab === "progress",
  });

  // ===== History query =====
  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ["mr-history", historyPage, hOrderNo, hSupplier, hCustomer, hCategory, hStart, hEnd],
    queryFn: () => get<{ success: boolean; registrations: Registration[]; pages: number; current_page: number }>("/material-registrations/history", {
      page: String(historyPage), per_page: "15",
      ...(hOrderNo ? { order_no: hOrderNo } : {}),
      ...(hSupplier ? { supplier: hSupplier } : {}),
      ...(hCustomer ? { customer_name: hCustomer } : {}),
      ...(hCategory ? { material_category: hCategory } : {}),
      ...(hStart ? { start_date: hStart } : {}),
      ...(hEnd ? { end_date: hEnd } : {}),
    }),
    enabled: activeTab === "history",
  });

  // Receive mutation
  const receiveMutation = useMutation({
    mutationFn: () => post<{ success: boolean; message?: string; auto_completed?: boolean }>(
      `/material-registrations/items/${receiveItem!.id}/receive`,
      { received_quantity: parseFloat(receiveQty), remark: receiveRemark },
    ),
    onSuccess: (res) => {
      alert(res.auto_completed ? "收货完成，该订单已全部到货，已转入历史记录" : (res.message || "收货登记成功"));
      setReceiveOpen(false); setDetailOpen(false);
      qc.invalidateQueries({ queryKey: ["mr-progress"] });
      qc.invalidateQueries({ queryKey: ["mr-overview"] });
    },
    onError: (err: Error) => alert(err.message),
  });

  // Group progress by supplier
  const groupedProgress = useMemo((): SupplierGroup[] => {
    const regList = (progressData?.registrations || []).filter(r => r.status !== "completed");
    const map: Record<string, SupplierGroup> = {};
    regList.forEach(r => {
      const key = r.supplier_name || "未知供应商";
      if (!map[key]) map[key] = { supplier_name: key, supplier_id: r.supplier_id, orders: [], allItems: [] };
      const items = r.items || [];
      const displayItems = fCategory ? items.filter(i => i.material_category === fCategory) : items;
      map[key].orders.push({
        id: r.id, order_no: r.purchase_order_no, customer_name: r.customer_name,
        product_name: r.product_name, product_quantity: r.product_quantity,
        items: displayItems, status: r.status, progress: r.progress,
        total_ordered: r.total_ordered, total_received: r.total_received,
      });
      displayItems.forEach(item => {
        const exist = map[key].allItems.find(ai => ai.material_name === item.material_name && ai.material_category === item.material_category);
        if (exist) {
          exist.ordered_quantity += item.ordered_quantity || 0;
          exist.received_quantity += item.received_quantity || 0;
          exist.remaining_quantity = exist.ordered_quantity - exist.received_quantity;
          exist.progress = exist.ordered_quantity > 0
            ? (exist.received_quantity >= exist.ordered_quantity ? 100 : Math.min(Math.round(exist.received_quantity / exist.ordered_quantity * 1000) / 10, 99.9))
            : 0;
        } else {
          map[key].allItems.push({ ...item });
        }
      });
    });
    return Object.values(map);
  }, [progressData, fCategory]);

  const overview = overviewData?.overview;

  // Trend chart
  const trendBars = useMemo(() => {
    if (!trendData?.trend) return [];
    const mx = Math.max(...trendData.trend.map(t => Math.max(t.registered, t.received)), 1);
    return trendData.trend.map(t => ({
      date: t.date, h: Math.max(Math.round((Math.max(t.registered, t.received) / mx) * 180), 4),
      active: t.registered > 0, registered: t.registered, received: t.received,
    }));
  }, [trendData]);

  // Distribution
  const distColors: Record<string, string> = { pending: "#FF9F43", partial: "#5B8DEF", completed: "#28C76F", overdue: "#EA5456" };
  const distNames: Record<string, string> = { pending: "未开始", partial: "部分到货", completed: "全部到货", overdue: "延期" };

  function openReceive(itemId: number, name: string, ordered: number, received: number) {
    setReceiveItem({ id: itemId, name, ordered, received });
    setReceiveQty(""); setReceiveRemark(""); setReceiveOpen(true);
  }

  async function viewSupplierDetail(supplierName: string) {
    const data = await get<{ success: boolean; registrations: Registration[] }>("/material-registrations/registrations", { supplier: supplierName, per_page: "100" });
    if (!data?.registrations) return;
    const regList = data.registrations.filter(r => r.status !== "completed");
    if (!regList.length) { alert("无采购中数据"); return; }
    let materialMap: Record<string, { ordered: number; received: number; remaining: number; unit: string; category: string; spec: string; itemIds: { id: number; ordered: number; received: number }[] }> = {};
    let allOrdered = 0, allReceived = 0;
    regList.forEach(r => {
      allOrdered += r.total_ordered || 0; allReceived += r.total_received || 0;
      (r.items || []).forEach(i => {
        const key = i.material_name.trim();
        if (!materialMap[key]) materialMap[key] = { ordered: 0, received: 0, remaining: 0, unit: i.unit, category: i.material_category, spec: i.specification, itemIds: [] };
        const m = materialMap[key];
        m.ordered += i.ordered_quantity || 0; m.received += i.received_quantity || 0; m.remaining += i.remaining_quantity || 0;
        m.itemIds.push({ id: i.id, ordered: i.ordered_quantity || 0, received: i.received_quantity || 0 });
      });
    });
    const matList = Object.entries(materialMap).map(([name, m]) => ({ name, ...m }));
    const allComplete = matList.every(m => m.received >= m.ordered);
    const totalPct = allOrdered > 0 ? (allComplete ? 100 : Math.min(Math.round(allReceived / allOrdered * 1000) / 10, 99.9)) : 0;

    let html = `<div class="mr-det-grid"><div><div class="mr-det-lb">供应商</div><div class="mr-det-vl">${supplierName}</div></div><div><div class="mr-det-lb">物料种类</div><div class="mr-det-vl">${matList.length} 种</div></div><div><div class="mr-det-lb">总进度</div><div class="mr-det-vl">${totalPct}% (已到货 ${allReceived.toFixed(0)} / 数量 ${allOrdered.toFixed(0)})</div></div></div>`;
    html += `<h4 style="margin:20px 0 16px;font-size:16px;"><i class="fas fa-cubes" style="color:var(--mr-primary);"></i> 物料汇总进度</h4>`;
    matList.forEach(m => {
      const pct = m.ordered > 0 ? (m.received >= m.ordered ? 100 : Math.min(Math.round(m.received / m.ordered * 1000) / 10, 99.9)) : 0;
      const isComplete = m.received >= m.ordered;
      const fillCls = isComplete ? "full" : pct >= 50 ? "half" : pct > 0 ? "low" : "zero";
      const pctColor = isComplete ? "var(--mr-success)" : pct >= 50 ? "var(--mr-primary)" : "var(--mr-warning)";
      const firstIncomplete = m.itemIds.find(x => x.received < x.ordered);
      const actionBtn = firstIncomplete
        ? `<button class="mr-btn mr-btn-s mr-btn-sm" onclick="window.__mrReceive(${firstIncomplete.id},'${m.name.replace(/'/g, "\\'")}',${firstIncomplete.ordered},${firstIncomplete.received})" title="登记收货"><i class="fas fa-box"></i> 收货</button>`
        : (isComplete ? '<span style="color:var(--mr-success);font-weight:700;font-size:14px;">✓ 已完成</span>' : '');
      html += `<div class="mr-det-mat-card"><div class="mr-det-mat-top"><div class="mr-det-mat-title"><span class="mr-det-mat-name">${m.name}</span>${m.spec ? `<span class="mr-det-mat-spec">${m.spec}</span>` : ""}</div><div class="mr-det-mat-nums"><div class="mr-det-mat-num s-ordered"><small>数量</small><b>${m.ordered.toFixed(0)}</b></div><div class="mr-det-mat-num s-received"><small>已到货</small><b>${m.received.toFixed(0)}</b></div><div class="mr-det-mat-num s-remaining"><small>未到</small><b>${m.remaining.toFixed(0)}</b></div></div></div><div class="mr-det-mat-bottom"><div class="mr-det-mat-bar"><div class="mr-sku-fill ${fillCls}" style="width:${pct}%;"></div></div><span class="mr-det-mat-pct" style="color:${pctColor};">${pct}%</span>${actionBtn}</div></div>`;
    });
    setDetailContent(html);
    setDetailOpen(true);
  }

  async function previewOrder(orderNo: string) {
    setOrderPreviewContent('<div style="text-align:center;padding:40px;color:var(--mr-text3);"><i class="fas fa-spinner fa-spin" style="font-size:24px;"></i><p>加载中...</p></div>');
    setOrderPreviewOpen(true);
    const res = await get<{ success: boolean; order: Record<string, unknown>; message?: string }>(`/material-registrations/purchase-orders/preview/${encodeURIComponent(orderNo)}`);
    if (!res?.success) { setOrderPreviewContent(`<div style="text-align:center;padding:40px;color:var(--mr-danger);"><i class="fas fa-exclamation-circle" style="font-size:28px;"></i><p>${res?.message || "加载失败"}</p></div>`); return; }
    const o = res.order;
    const catMap: Record<string, string> = { fabric: "面料", filling: "填充", accessory: "辅料", packaging: "包装" };
    const items = (o.items as Record<string, unknown>[]) || [];
    let itemsHtml = items.length > 0
      ? `<table style="width:100%;border-collapse:collapse;margin-top:12px;font-size:13px;"><thead><tr style="background:var(--mr-bg);"><th style="padding:8px 10px;text-align:left;">物料名称</th><th style="padding:8px 10px;text-align:left;">规格</th><th style="padding:8px 10px;text-align:right;">数量</th><th style="padding:8px 10px;text-align:left;">分类</th></tr></thead><tbody>${items.map(it => `<tr><td style="padding:7px 10px;">${(it.material_name as string) || "-"}</td><td style="padding:7px 10px;color:var(--mr-text2);">${(it.specification as string) || "-"}</td><td style="padding:7px 10px;text-align:right;font-weight:500;">${(it.quantity as number) || 0} ${(it.unit as string) || ""}</td><td style="padding:7px 10px;">${catMap[it.material_category as string] || "-"}</td></tr>`).join("")}</tbody></table>`
      : '<div style="text-align:center;padding:20px;color:var(--mr-text3);">暂无物料明细</div>';
    setOrderPreviewContent(`<div class="mr-det-grid" style="grid-template-columns:1fr 1fr;"><div><div class="mr-det-lb">订单号</div><div class="mr-det-vl" style="color:var(--mr-primary);">${o.order_no || ""}</div></div><div><div class="mr-det-lb">供应商</div><div class="mr-det-vl">${o.supplier_name || "-"}</div></div><div><div class="mr-det-lb">客户</div><div class="mr-det-vl">${o.customer_name || "-"}</div></div><div><div class="mr-det-lb">产品</div><div class="mr-det-vl">${o.product_name || "-"}</div></div></div>${o.remark ? `<div style="margin-top:12px;padding:10px 14px;background:var(--mr-bg);border-radius:6px;font-size:13px;color:var(--mr-text2);"><b>备注:</b> ${o.remark}</div>` : ""}<h4 style="margin:16px 0 0;font-size:15px;"><i class="fas fa-list" style="color:var(--mr-primary);margin-right:6px;"></i>物料明细</h4>${itemsHtml}`);
  }

  // Expose receive function to window for onclick in dangerouslySetInnerHTML
  (typeof window !== "undefined" && (window as unknown as Record<string, unknown>).__mrReceive === undefined) && Object.assign(window, { __mrReceive: (id: number, name: string, ordered: number, received: number) => openReceive(id, name, ordered, received) });

  const progressRegList = (progressData?.registrations || []).filter(r => r.status !== "completed");
  const historyRegList = historyData?.registrations || [];

  return (
    <div className="mr-wrap">
      {/* Header */}
      <div className="mr-header">
        <div>
          <h1><i className="fas fa-truck-loading"></i> 来料进度管理</h1>
          <div className="mr-header-sub">原材料到货追踪 · 采购订单联动 · 自动流转</div>
        </div>
        <div className="mr-header-stats">
          <div className="mr-header-stat"><b>{overview?.total ?? 0}</b><small>总登记</small></div>
          <div className="mr-header-stat"><b>{overview?.overall_progress ?? 0}%</b><small>总进度</small></div>
          <div className="mr-header-stat"><b>{overview?.pending ?? 0}</b><small>待到货</small></div>
        </div>
      </div>

      {/* Tabs */}
      <div className="mr-tabs">
        <button className={`mr-tab ${activeTab === "overview" ? "active" : ""}`} onClick={() => setActiveTab("overview")}><i className="fas fa-chart-pie"></i> 监控面板</button>
        <button className={`mr-tab ${activeTab === "progress" ? "active" : ""}`} onClick={() => setActiveTab("progress")}><i className="fas fa-tasks"></i> 来料进度 <span className="bdg">{progressRegList.length}</span></button>
        <button className={`mr-tab ${activeTab === "history" ? "active" : ""}`} onClick={() => setActiveTab("history")}><i className="fas fa-history"></i> 历史查询</button>
      </div>

      {/* ===== Overview Panel ===== */}
      {activeTab === "overview" && (
        <div className="mr-panel active">
          <div className="mr-stats">
            <div className="mr-sc s-total"><div className="mr-sv">{overview?.total ?? 0}</div><div className="mr-sl">总登记数</div><div className="mr-ss">{overview ? `近7天新增 ${overview.recent_registrations} 条` : ""}</div></div>
            <div className="mr-sc s-pending"><div className="mr-sv">{overview?.pending ?? 0}</div><div className="mr-sl">未开始</div><div className="mr-ss">{overview && overview.overdue_items > 0 ? `${overview.overdue_items} 项超期` : ""}</div></div>
            <div className="mr-sc s-partial"><div className="mr-sv">{overview?.partial ?? 0}</div><div className="mr-sl">部分到货</div></div>
            <div className="mr-sc s-completed"><div className="mr-sv">{overview?.completed ?? 0}</div><div className="mr-sl">全部到货</div></div>
            <div className="mr-sc s-progress"><div className="mr-sv">{overview?.overall_progress ?? 0}%</div><div className="mr-sl">总体进度</div><div className="mr-ss">{overview ? `已收 ${overview.total_received} / 采购 ${overview.total_ordered}` : ""}</div></div>
          </div>

          {/* Category Grid */}
          <div className="mr-cat-grid">
            {overview?.category_stats?.length ? overview.category_stats.map(c => (
              <div key={c.category} className="mr-cat-card">
                <div className="mr-cat-hd"><span className="mr-cat-nm">{c.category_name}</span><span className="mr-cat-pg">{c.progress}%</span></div>
                <div className="mr-cat-bar"><div className={`mr-cat-fill ${CAT_FILL[c.category] || ""}`} style={{ width: `${c.progress}%` }}></div></div>
                <div className="mr-cat-det"><span>采购: {c.ordered}</span><span>已收: {c.received}</span><span>待收: {c.remaining}</span></div>
              </div>
            )) : <div style={{ gridColumn: "1/-1", textAlign: "center", padding: 20, color: "var(--mr-text3)" }}>暂无分类数据</div>}
          </div>

          {/* Charts */}
          <div className="mr-chart-row">
            <div className="mr-card">
              <div className="mr-card-h"><div className="mr-card-t"><i className="fas fa-chart-line"></i> 近30天到货趋势</div></div>
              <div className="mr-card-b">
                <div className="mr-trend">
                  {trendBars.map((t, i) => (
                    <div key={i} className="mr-tb" style={{ height: t.h, background: t.active ? "var(--mr-primary-light)" : "#f0f0f0" }}>
                      <div className="tip">{t.date}<br />登记: {t.registered} | 收货: {t.received}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="mr-card">
              <div className="mr-card-h"><div className="mr-card-t"><i className="fas fa-chart-pie"></i> 状态分布</div></div>
              <div className="mr-card-b">
                <div className="mr-pie">
                  {distData?.distribution && distData.distribution.length > 0 && (() => {
                    const d = distData.distribution;
                    const total = d.reduce((s, x) => s + x.count, 0) || 1;
                    let cumPct = 0;
                    const gradParts = d.map(item => {
                      const pct = item.count / total * 100;
                      const start = cumPct; cumPct += pct;
                      return `${distColors[item.status]} ${start}% ${cumPct}%`;
                    });
                    return <>
                      <div className="mr-pie-chart" style={{ background: `conic-gradient(${gradParts.join(",")})` }}></div>
                      <div className="mr-pie-legend">
                        {d.map(item => <div key={item.status} className="mr-pie-item"><div className="mr-pie-dot" style={{ background: distColors[item.status] }}></div>{distNames[item.status]}: {item.count}</div>)}
                      </div>
                    </>;
                  })()}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ===== Progress Panel ===== */}
      {activeTab === "progress" && (
        <div className="mr-panel active">
          <div className="mr-card">
            <div className="mr-card-h">
              <div className="mr-card-t"><i className="fas fa-filter"></i> 筛选条件</div>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="mr-btn mr-btn-o" onClick={() => { /* export */ }} title="导出"><i className="fas fa-file-export"></i> 导出</button>
              </div>
            </div>
            <div className="mr-card-b">
              <div className="mr-filters">
                <div className="mr-fg"><label>供应商</label><input type="text" value={fSupplier} onChange={e => setFSupplier(e.target.value)} placeholder="搜索..." /></div>
                <div className="mr-fg"><label>订单号</label><input type="text" value={fOrderNo} onChange={e => setFOrderNo(e.target.value)} placeholder="搜索..." /></div>
                <div className="mr-fg"><label>客户</label><input type="text" value={fCustomer} onChange={e => setFCustomer(e.target.value)} placeholder="搜索..." /></div>
                <div className="mr-fg"><label>分类</label><select value={fCategory} onChange={e => setFCategory(e.target.value)}><option value="">全部</option><option value="fabric">面料</option><option value="filling">填充</option><option value="accessory">辅料</option><option value="packaging">包装</option></select></div>
                <div className="mr-fg"><label>日期</label><input type="date" value={fStart} onChange={e => setFStart(e.target.value)} /><span style={{ color: "var(--mr-text3)" }}>~</span><input type="date" value={fEnd} onChange={e => setFEnd(e.target.value)} /></div>
                <button className="mr-btn mr-btn-o" onClick={() => { setFSupplier(""); setFOrderNo(""); setFCustomer(""); setFCategory(""); setFStart(""); setFEnd(""); }}><i className="fas fa-redo"></i> 重置</button>
              </div>
            </div>
          </div>
          <div className="mr-card">
            <div className="mr-card-b" style={{ padding: 0, overflowX: "auto" }}>
              <table className="mr-tbl" style={{ minWidth: 900 }}>
                <thead><tr><th style={{ width: 160 }}>供应商</th><th style={{ width: 160 }}>关联订单</th><th>物料进度</th><th style={{ width: 220 }}>总进度</th><th style={{ width: 80 }}>操作</th></tr></thead>
                <tbody>
                  {progressLoading ? (
                    <tr><td colSpan={5} className="mr-empty"><i className="fas fa-spinner fa-spin"></i><p>加载中...</p></td></tr>
                  ) : groupedProgress.length === 0 ? (
                    <tr><td colSpan={5} className="mr-empty"><i className="fas fa-inbox"></i><p>暂无进行中的来料登记</p></td></tr>
                  ) : groupedProgress.map(g => {
                    const totalOrdered = g.allItems.reduce((s, i) => s + i.ordered_quantity, 0);
                    const totalReceived = g.allItems.reduce((s, i) => s + i.received_quantity, 0);
                    const allComplete = g.allItems.every(i => i.received_quantity >= i.ordered_quantity);
                    const totalPct = totalOrdered > 0 ? (allComplete ? 100 : Math.min(Math.round(totalReceived / totalOrdered * 1000) / 10, 99.9)) : 0;
                    const progressCls = totalPct >= 100 ? "completed" : totalPct > 0 ? "partial" : "pending";
                    return (
                      <tr key={g.supplier_name}>
                        <td style={{ fontSize: 14, fontWeight: 600 }}>{g.supplier_name}</td>
                        <td>{g.orders.map(o => (
                          <div key={o.order_no} style={{ fontFamily: "'Courier New',monospace", fontSize: 14, color: "var(--mr-primary)", cursor: "pointer", textDecoration: "underline", marginBottom: 1 }} onClick={() => previewOrder(o.order_no)}>{o.order_no}</div>
                        ))}</td>
                        <td><div className="mr-items-container">
                          {g.allItems.map(i => {
                            const pct = i.progress || 0;
                            const isComplete = i.received_quantity >= i.ordered_quantity;
                            const fillCls = isComplete ? "full" : pct >= 50 ? "half" : pct > 0 ? "low" : "zero";
                            return (
                              <div key={i.material_name} className="mr-list-item-row">
                                <span className="mr-list-item-name" title={i.material_name}>{i.material_name}</span>
                                <span className="mr-list-item-qty">数量:<b>{i.ordered_quantity.toFixed(0)}</b></span>
                                <span className="mr-list-item-rcv">已到货:<b>{i.received_quantity.toFixed(0)}</b></span>
                                <div className="mr-list-item-bar"><div className={`mr-sku-fill ${fillCls}`} style={{ width: `${pct}%`, height: "100%", borderRadius: 5 }}></div></div>
                                <span className="mr-list-item-pct">{pct}%</span>
                              </div>
                            );
                          })}
                        </div></td>
                        <td><div style={{ display: "flex", alignItems: "center", gap: 8 }}><div className="mr-pbar"><div className={`mr-pfill ${progressCls}`} style={{ width: `${totalPct}%` }}></div></div><span style={{ fontSize: 14, color: "var(--mr-text2)" }}>{totalPct}%</span></div></td>
                        <td><div className="action-buttons-elegant"><button className="btn-action btn-action-view" title="查看供应商详情" onClick={() => viewSupplierDetail(g.supplier_name)}><i className="fas fa-eye"></i></button></div></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {progressData && progressData.pages > 1 && (
                <div className="mr-pagi">
                  <button disabled={progressPage <= 1} onClick={() => setProgressPage(p => Math.max(1, p - 1))}><i className="fas fa-angle-left"></i></button>
                  <span className="pi">第 {progressPage}/{progressData.pages} 页</span>
                  <button disabled={progressPage >= progressData.pages} onClick={() => setProgressPage(p => Math.min(progressData!.pages, p + 1))}><i className="fas fa-angle-right"></i></button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ===== History Panel ===== */}
      {activeTab === "history" && (
        <div className="mr-panel active">
          <div className="mr-card">
            <div className="mr-card-h">
              <div className="mr-card-t"><i className="fas fa-search"></i> 历史查询条件</div>
              <button className="mr-btn mr-btn-o" onClick={() => { /* export */ }}><i className="fas fa-file-export"></i> 导出历史</button>
            </div>
            <div className="mr-card-b">
              <div className="mr-filters">
                <div className="mr-fg"><label>订单号</label><input type="text" value={hOrderNo} onChange={e => setHOrderNo(e.target.value)} placeholder="搜索..." /></div>
                <div className="mr-fg"><label>供应商</label><input type="text" value={hSupplier} onChange={e => setHSupplier(e.target.value)} placeholder="搜索..." /></div>
                <div className="mr-fg"><label>客户</label><input type="text" value={hCustomer} onChange={e => setHCustomer(e.target.value)} placeholder="搜索..." /></div>
                <div className="mr-fg"><label>分类</label><select value={hCategory} onChange={e => setHCategory(e.target.value)}><option value="">全部</option><option value="fabric">面料</option><option value="filling">填充</option><option value="accessory">辅料</option><option value="packaging">包装</option></select></div>
                <div className="mr-fg"><label>完成日期</label><input type="date" value={hStart} onChange={e => setHStart(e.target.value)} /><span style={{ color: "var(--mr-text3)" }}>~</span><input type="date" value={hEnd} onChange={e => setHEnd(e.target.value)} /></div>
                <button className="mr-btn mr-btn-o" onClick={() => { setHOrderNo(""); setHSupplier(""); setHCustomer(""); setHCategory(""); setHStart(""); setHEnd(""); }}><i className="fas fa-redo"></i> 重置</button>
              </div>
            </div>
          </div>
          <div className="mr-card">
            <div className="mr-card-b" style={{ padding: 0, overflowX: "auto" }}>
              <table className="mr-tbl" style={{ minWidth: 900 }}>
                <thead><tr><th style={{ width: 150 }}>订单号</th><th style={{ width: 100 }}>客户</th><th style={{ width: 120 }}>产品/数量</th><th style={{ width: 100 }}>供应商</th><th>物料名称</th><th style={{ width: 120 }}>完成时间</th><th style={{ width: 80 }}>操作</th></tr></thead>
                <tbody>
                  {historyLoading ? (
                    <tr><td colSpan={7} className="mr-empty"><i className="fas fa-spinner fa-spin"></i><p>加载中...</p></td></tr>
                  ) : historyRegList.length === 0 ? (
                    <tr><td colSpan={7} className="mr-empty"><i className="fas fa-archive"></i><p>暂无历史记录</p></td></tr>
                  ) : historyRegList.map(r => {
                    const items = r.items || [];
                    const displayItems = hCategory ? items.filter(i => i.material_category === hCategory) : items;
                    const summary = displayItems.slice(0, 2).map(i => `${i.material_name}(数量:${i.ordered_quantity.toFixed(0)} 已到货:${i.received_quantity.toFixed(0)})`).join(", ");
                    const more = displayItems.length > 2 ? ` 等${displayItems.length}项` : "";
                    return (
                      <tr key={r.id}>
                        <td style={{ fontFamily: "'Courier New',monospace", fontWeight: 600, color: "var(--mr-primary)", fontSize: 14 }}>{r.purchase_order_no || ""}</td>
                        <td style={{ fontSize: 14 }}>{r.customer_name || "-"}</td>
                        <td style={{ fontSize: 13 }}>{(r.product_name || "-") + (r.product_quantity ? ` x${r.product_quantity}` : "")}</td>
                        <td style={{ fontSize: 14 }}>{r.supplier_name || "-"}</td>
                        <td style={{ fontSize: 13 }}>{summary}{more}</td>
                        <td style={{ fontSize: 13 }}>{r.update_time || "-"}</td>
                        <td><div className="action-buttons-elegant"><button className="btn-action btn-action-view" title="查看详情" onClick={async () => {
                          const res = await get<{ success: boolean; registration: Registration }>(`/material-registrations/registrations/${r.id}`);
                          if (!res?.registration) return;
                          const reg = res.registration;
                          let html = `<div class="mr-det-grid"><div><div class="mr-det-lb">订单号</div><div class="mr-det-vl" style="color:var(--mr-primary);">${reg.purchase_order_no}</div></div><div><div class="mr-det-lb">客户</div><div class="mr-det-vl">${reg.customer_name || "-"}</div></div><div><div class="mr-det-lb">产品/数量</div><div class="mr-det-vl">${(reg.product_name || "-") + (reg.product_quantity ? ` x${reg.product_quantity}` : "")}</div></div><div><div class="mr-det-lb">供应商</div><div class="mr-det-vl">${reg.supplier_name || "-"}</div></div><div><div class="mr-det-lb">状态</div><div class="mr-det-vl"><span class="mr-badge mr-badge-${STATUS_CLS[reg.status]}">${STATUS_MAP[reg.status]}</span></div></div><div><div class="mr-det-lb">总进度</div><div class="mr-det-vl">${reg.progress}% (已到货 ${reg.total_received} / 数量 ${reg.total_ordered})</div></div></div>`;
                          if (reg.items?.length) {
                            html += `<h4 style="margin:18px 0 14px;font-size:16px;"><i class="fas fa-cubes" style="color:var(--mr-primary);"></i> SKU物料来料进度</h4>`;
                            reg.items.forEach(i => {
                              const pct = i.progress || 0;
                              const isComplete = i.received_quantity >= i.ordered_quantity;
                              const fillCls = isComplete ? "full" : pct >= 50 ? "half" : pct > 0 ? "low" : "zero";
                              const canOperate = i.received_quantity < i.ordered_quantity;
                              html += `<div class="mr-sku-row"><div class="mr-sku-top"><span><span class="mr-sku-name">${i.material_name}</span><span class="mr-sku-spec">${i.specification || ""}</span></span><span class="mr-sku-pct" style="color:${isComplete ? "var(--mr-success)" : pct >= 50 ? "var(--mr-primary)" : "var(--mr-warning)"};">${pct}%</span></div><div class="mr-sku-bar"><div class="mr-sku-fill ${fillCls}" style="width:${pct}%;"></div></div><div class="mr-sku-info"><span>分类: <b>${CATEGORY_MAP[i.material_category] || "-"}</b></span><span>数量: <b>${i.ordered_quantity}</b> ${i.unit || ""}</span><span>已到货: <b style="color:var(--mr-success);">${i.received_quantity}</b></span><span>未到: <b style="color:var(--mr-warning);">${i.remaining_quantity}</b></span>${canOperate ? `<button class="mr-btn mr-btn-s mr-btn-sm" onclick="window.__mrReceive(${i.id},'${i.material_name.replace(/'/g, "\\'")}',${i.ordered_quantity},${i.received_quantity})"><i class="fas fa-box"></i> 收货</button>` : (isComplete ? '<span style="color:var(--mr-success);font-weight:600;">✓ 已完成</span>' : '<span style="color:var(--mr-text3);">-</span>')}</div></div>`;
                            });
                          }
                          setDetailContent(html); setDetailOpen(true);
                        }}><i className="fas fa-eye"></i></button></div></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {historyData && historyData.pages > 1 && (
                <div className="mr-pagi">
                  <button disabled={historyPage <= 1} onClick={() => setHistoryPage(p => Math.max(1, p - 1))}><i className="fas fa-angle-left"></i></button>
                  <span className="pi">第 {historyPage}/{historyData.pages} 页</span>
                  <button disabled={historyPage >= historyData.pages} onClick={() => setHistoryPage(p => Math.min(historyData!.pages, p + 1))}><i className="fas fa-angle-right"></i></button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ===== Detail Modal ===== */}
      {detailOpen && (
        <div className="mr-mo show" onClick={() => setDetailOpen(false)}>
          <div className="mr-mo-box" style={{ maxWidth: 1000 }} onClick={e => e.stopPropagation()}>
            <div className="mr-mo-h"><h3><i className="fas fa-clipboard-list" style={{ color: "var(--mr-primary)" }}></i> 来料进度详情</h3><button className="mr-mo-x" onClick={() => setDetailOpen(false)}><i className="fas fa-times"></i></button></div>
            <div className="mr-mo-b" dangerouslySetInnerHTML={{ __html: detailContent }}></div>
          </div>
        </div>
      )}

      {/* ===== Receive Modal ===== */}
      {receiveOpen && receiveItem && (
        <div className="mr-mo show" onClick={() => setReceiveOpen(false)}>
          <div className="mr-mo-box" style={{ maxWidth: 540 }} onClick={e => e.stopPropagation()}>
            <div className="mr-mo-h"><h3><i className="fas fa-box" style={{ color: "var(--mr-success)" }}></i> 收货登记</h3><button className="mr-mo-x" onClick={() => setReceiveOpen(false)}><i className="fas fa-times"></i></button></div>
            <div className="mr-mo-b">
              <div className="mr-fg2"><label>物料名称</label><div style={{ fontWeight: 600, fontSize: 17 }}>{receiveItem.name}</div></div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>
                <div className="mr-fg2"><label>采购数量</label><div style={{ fontSize: 17 }}>{receiveItem.ordered}</div></div>
                <div className="mr-fg2"><label>已收货</label><div style={{ fontSize: 17, color: "var(--mr-success)" }}>{receiveItem.received}</div></div>
                <div className="mr-fg2"><label>待收货</label><div style={{ fontSize: 17, color: "var(--mr-warning)" }}>{receiveItem.ordered - receiveItem.received}</div></div>
              </div>
              <div className="mr-fg2"><label>本次收货数量</label><input type="number" min={0.01} step={0.01} value={receiveQty} onChange={e => setReceiveQty(e.target.value)} placeholder="输入本次收货数量" /></div>
              <div className="mr-fg2"><label>备注</label><textarea rows={2} value={receiveRemark} onChange={e => setReceiveRemark(e.target.value)} placeholder="可选备注..." /></div>
            </div>
            <div className="mr-mo-f">
              <button className="mr-btn mr-btn-o" onClick={() => setReceiveOpen(false)}>取消</button>
              <button className="mr-btn mr-btn-s" disabled={!receiveQty || receiveMutation.isPending} onClick={() => receiveMutation.mutate()}><i className="fas fa-check"></i> 确认收货</button>
            </div>
          </div>
        </div>
      )}

      {/* ===== Order Preview Modal ===== */}
      {orderPreviewOpen && (
        <div className="mr-mo show" onClick={() => setOrderPreviewOpen(false)}>
          <div className="mr-mo-box" style={{ maxWidth: 680 }} onClick={e => e.stopPropagation()}>
            <div className="mr-mo-h"><h3><i className="fas fa-file-invoice" style={{ color: "var(--mr-primary)" }}></i> 采购订单预览</h3><button className="mr-mo-x" onClick={() => setOrderPreviewOpen(false)}><i className="fas fa-times"></i></button></div>
            <div className="mr-mo-b" dangerouslySetInnerHTML={{ __html: orderPreviewContent }}></div>
          </div>
        </div>
      )}

      <style jsx global>{`
        :root { --mr-primary: #5B8DEF; --mr-primary-dark: #4A7DE8; --mr-primary-light: #E8F2FF; --mr-primary-lighter: #F0F6FF; --mr-success: #28C76F; --mr-warning: #FF9F43; --mr-danger: #EA5456; --mr-info: #00CFE8; --mr-purple: #8B5CF6; --mr-text: #2D3748; --mr-text2: #718096; --mr-text3: #A0AEC0; --mr-border: #E2E8F0; --mr-bg: #F8FAFC; --mr-r-sm: 6px; --mr-r-md: 10px; --mr-r-lg: 14px; --mr-shadow: 0 1px 3px rgba(0,0,0,0.08); --mr-shadow-md: 0 4px 12px rgba(0,0,0,0.1); --mr-ease: all 0.25s ease; }
        .mr-wrap { padding: 24px; max-width: 1920px; margin: 0 auto; font-family: 'Microsoft YaHei','Segoe UI',sans-serif; }
        .mr-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding: 20px 28px; background: linear-gradient(135deg,#5B8DEF,#8B5CF6); border-radius: var(--mr-r-lg); color: #fff; box-shadow: var(--mr-shadow-md); }
        .mr-header h1 { font-size: 26px; font-weight: 700; margin: 0; display: flex; align-items: center; gap: 12px; }
        .mr-header-sub { font-size: 14px; opacity: 0.85; margin-top: 6px; }
        .mr-header-stats { display: flex; gap: 32px; }
        .mr-header-stat { text-align: center; }
        .mr-header-stat b { font-size: 30px; display: block; }
        .mr-header-stat small { font-size: 12px; opacity: 0.8; }
        .mr-tabs { display: flex; gap: 6px; margin-bottom: 24px; background: #fff; padding: 8px; border-radius: var(--mr-r-md); box-shadow: var(--mr-shadow); border: 1px solid var(--mr-border); }
        .mr-tab { padding: 12px 24px; border-radius: var(--mr-r-sm); font-size: 15px; font-weight: 500; cursor: pointer; border: none; background: transparent; color: var(--mr-text2); transition: var(--mr-ease); display: flex; align-items: center; gap: 10px; }
        .mr-tab:hover { background: var(--mr-primary-lighter); color: var(--mr-primary); }
        .mr-tab.active { background: var(--mr-primary); color: #fff; box-shadow: 0 2px 8px rgba(91,141,239,0.3); }
        .mr-tab .bdg { background: rgba(255,255,255,0.3); padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
        .mr-tab.active .bdg { background: rgba(255,255,255,0.25); }
        .mr-panel { display: none; } .mr-panel.active { display: block; }
        .mr-stats { display: grid; grid-template-columns: repeat(5,1fr); gap: 18px; margin-bottom: 24px; }
        .mr-sc { background: #fff; border-radius: var(--mr-r-md); padding: 24px; box-shadow: var(--mr-shadow); border: 1px solid var(--mr-border); transition: var(--mr-ease); position: relative; overflow: hidden; }
        .mr-sc:hover { transform: translateY(-3px); box-shadow: var(--mr-shadow-md); }
        .mr-sc::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 4px; }
        .mr-sc.s-pending::before { background: var(--mr-warning); } .mr-sc.s-partial::before { background: var(--mr-primary); } .mr-sc.s-completed::before { background: var(--mr-success); } .mr-sc.s-total::before { background: var(--mr-purple); } .mr-sc.s-progress::before { background: linear-gradient(90deg,var(--mr-primary),var(--mr-success)); }
        .mr-sv { font-size: 34px; font-weight: 700; }
        .mr-sc.s-pending .mr-sv { color: var(--mr-warning); } .mr-sc.s-partial .mr-sv { color: var(--mr-primary); } .mr-sc.s-completed .mr-sv { color: var(--mr-success); } .mr-sc.s-total .mr-sv { color: var(--mr-purple); } .mr-sc.s-progress .mr-sv { color: var(--mr-primary); }
        .mr-sl { font-size: 14px; color: var(--mr-text2); margin-top: 6px; }
        .mr-ss { font-size: 13px; color: var(--mr-text3); margin-top: 8px; }
        .mr-cat-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 14px; margin-bottom: 24px; }
        .mr-cat-card { background: #fff; border-radius: var(--mr-r-md); padding: 18px; box-shadow: var(--mr-shadow); border: 1px solid var(--mr-border); }
        .mr-cat-hd { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        .mr-cat-nm { font-size: 15px; font-weight: 600; color: var(--mr-text); }
        .mr-cat-pg { font-size: 13px; color: var(--mr-success); font-weight: 600; }
        .mr-cat-bar { height: 8px; background: #E5E7EB; border-radius: 4px; overflow: hidden; margin-bottom: 10px; }
        .mr-cat-fill { height: 100%; border-radius: 4px; transition: width 0.5s ease; }
        .mr-cat-fill.fabric { background: var(--mr-purple); } .mr-cat-fill.filling { background: var(--mr-warning); } .mr-cat-fill.accessory { background: var(--mr-info); } .mr-cat-fill.packaging { background: var(--mr-success); }
        .mr-cat-det { display: flex; justify-content: space-between; font-size: 13px; color: var(--mr-text2); }
        .mr-chart-row { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-bottom: 24px; }
        .mr-card { background: #fff; border-radius: var(--mr-r-md); box-shadow: var(--mr-shadow); border: 1px solid var(--mr-border); margin-bottom: 24px; }
        .mr-card-h { padding: 18px 24px; border-bottom: 1px solid var(--mr-border); display: flex; justify-content: space-between; align-items: center; }
        .mr-card-t { font-size: 16px; font-weight: 600; color: var(--mr-text); display: flex; align-items: center; gap: 10px; }
        .mr-card-t i { color: var(--mr-primary); }
        .mr-card-b { padding: 24px; }
        .mr-trend { height: 200px; display: flex; align-items: flex-end; gap: 2px; padding: 10px 0; }
        .mr-tb { flex: 1; min-width: 4px; border-radius: 2px 2px 0 0; transition: height 0.5s ease; position: relative; cursor: pointer; }
        .mr-tb:hover { background: var(--mr-primary) !important; }
        .mr-tb .tip { display: none; position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%); background: var(--mr-text); color: #fff; padding: 4px 8px; border-radius: 4px; font-size: 11px; white-space: nowrap; z-index: 10; }
        .mr-tb:hover .tip { display: block; }
        .mr-pie { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; }
        .mr-pie-chart { width: 160px; height: 160px; border-radius: 50%; position: relative; }
        .mr-pie-legend { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
        .mr-pie-item { display: flex; align-items: center; gap: 4px; font-size: 12px; color: var(--mr-text2); }
        .mr-pie-dot { width: 10px; height: 10px; border-radius: 50%; }
        .mr-filters { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
        .mr-fg { display: flex; align-items: center; gap: 6px; }
        .mr-fg label { font-size: 13px; color: var(--mr-text2); white-space: nowrap; font-weight: 500; }
        .mr-fg select, .mr-fg input { padding: 8px 12px; border: 1px solid var(--mr-border); border-radius: var(--mr-r-sm); font-size: 13px; min-width: 120px; transition: var(--mr-ease); }
        .mr-fg select:focus, .mr-fg input:focus { outline: none; border-color: var(--mr-primary); box-shadow: 0 0 0 3px rgba(91,141,239,0.1); }
        .mr-btn { padding: 10px 18px; border-radius: var(--mr-r-sm); font-size: 14px; font-weight: 500; cursor: pointer; transition: var(--mr-ease); border: none; display: inline-flex; align-items: center; gap: 8px; }
        .mr-btn-p { background: var(--mr-primary); color: #fff; } .mr-btn-p:hover { background: var(--mr-primary-dark); }
        .mr-btn-s { background: var(--mr-success); color: #fff; } .mr-btn-s:hover { background: #23B565; }
        .mr-btn-o { background: #fff; color: var(--mr-text); border: 1px solid var(--mr-border); } .mr-btn-o:hover { background: var(--mr-primary-lighter); border-color: var(--mr-primary); color: var(--mr-primary); }
        .mr-btn-sm { padding: 7px 12px; font-size: 13px; }
        .mr-tbl { width: 100%; border-collapse: collapse; font-size: 15px; table-layout: auto; }
        .mr-tbl th { background: var(--mr-primary-lighter); padding: 18px 22px; text-align: left; font-weight: 600; color: var(--mr-text); border-bottom: 2px solid var(--mr-border); font-size: 14px; white-space: nowrap; }
        .mr-tbl td { padding: 20px 22px; border-bottom: 1px solid var(--mr-border); vertical-align: middle; }
        .mr-tbl tbody tr { transition: var(--mr-ease); } .mr-tbl tbody tr:hover { background: var(--mr-primary-lighter); }
        .mr-items-container { min-width: 500px; }
        .mr-list-item-row { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
        .mr-list-item-row:last-child { margin-bottom: 0; }
        .mr-list-item-name { font-size: 14px; width: 140px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 500; flex-shrink: 0; }
        .mr-list-item-qty { font-size: 13px; color: var(--mr-text2); white-space: nowrap; width: 105px; flex-shrink: 0; }
        .mr-list-item-rcv { font-size: 13px; color: var(--mr-success); white-space: nowrap; width: 115px; flex-shrink: 0; }
        .mr-list-item-bar { flex: 1; height: 10px; background: #E5E7EB; border-radius: 5px; min-width: 60px; }
        .mr-list-item-pct { font-size: 13px; color: var(--mr-text3); width: 50px; flex-shrink: 0; text-align: right; }
        .mr-pbar { width: 160px; height: 10px; background: #E5E7EB; border-radius: 5px; overflow: hidden; }
        .mr-pfill { height: 100%; border-radius: 5px; transition: width 0.5s ease; }
        .mr-pfill.pending { background: var(--mr-warning); } .mr-pfill.partial { background: var(--mr-primary); } .mr-pfill.completed { background: var(--mr-success); }
        .mr-sku-fill { transition: width 0.5s ease; }
        .mr-sku-fill.full { background: var(--mr-success); } .mr-sku-fill.half { background: var(--mr-primary); } .mr-sku-fill.low { background: var(--mr-warning); } .mr-sku-fill.zero { background: #E5E7EB; }
        .mr-empty { text-align: center; padding: 60px 20px; color: var(--mr-text3); }
        .mr-empty i { font-size: 48px; margin-bottom: 16px; opacity: 0.5; display: block; }
        .mr-pagi { display: flex; justify-content: center; align-items: center; gap: 6px; padding: 18px; border-top: 1px solid var(--mr-border); }
        .mr-pagi button { padding: 8px 14px; border: 1px solid var(--mr-border); background: #fff; border-radius: var(--mr-r-sm); cursor: pointer; transition: var(--mr-ease); font-size: 14px; }
        .mr-pagi button:hover:not(:disabled) { border-color: var(--mr-primary); color: var(--mr-primary); }
        .mr-pagi button:disabled { opacity: 0.4; cursor: not-allowed; }
        .mr-pagi .pi { font-size: 14px; color: var(--mr-text2); }
        .mr-badge { display: inline-flex; align-items: center; padding: 5px 12px; border-radius: 20px; font-size: 13px; font-weight: 500; }
        .mr-badge-pending { background: #FEF3C7; color: #D97706; } .mr-badge-partial { background: var(--mr-primary-light); color: var(--mr-primary); } .mr-badge-completed { background: #D1FAE5; color: #059669; } .mr-badge-overdue { background: #FEE2E2; color: #DC2626; }
        .action-buttons-elegant { display: flex; gap: 0.5rem; }
        .btn-action { width: 36px; height: 36px; border-radius: 10px; border: none; display: flex; align-items: center; justify-content: center; font-size: 0.9rem; transition: all 0.2s ease; cursor: pointer; }
        .btn-action-view { background: #dbeafe; color: #1d4ed8; } .btn-action-view:hover { background: #bfdbfe; transform: scale(1.1); }
        .btn-action-receive { background: #d1fae5; color: #059669; } .btn-action-receive:hover { background: #a7f3d0; transform: scale(1.1); }
        /* Modals */
        .mr-mo { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; justify-content: center; align-items: center; z-index: 1000; backdrop-filter: blur(4px); }
        .mr-mo-box { background: #fff; border-radius: var(--mr-r-lg); width: 90%; max-height: 90vh; overflow: hidden; box-shadow: 0 8px 24px rgba(0,0,0,0.12); }
        .mr-mo-h { padding: 20px 24px; border-bottom: 1px solid var(--mr-border); display: flex; justify-content: space-between; align-items: center; }
        .mr-mo-h h3 { margin: 0; font-size: 18px; color: var(--mr-text); display: flex; align-items: center; gap: 8px; }
        .mr-mo-x { background: none; border: none; font-size: 20px; cursor: pointer; color: var(--mr-text3); padding: 4px; transition: var(--mr-ease); } .mr-mo-x:hover { color: var(--mr-danger); }
        .mr-mo-b { padding: 28px; max-height: calc(90vh - 140px); overflow-y: auto; }
        .mr-mo-f { padding: 16px 24px; border-top: 1px solid var(--mr-border); display: flex; justify-content: flex-end; gap: 12px; }
        .mr-fg2 { margin-bottom: 16px; }
        .mr-fg2 label { display: block; font-size: 13px; font-weight: 500; color: var(--mr-text2); margin-bottom: 6px; }
        .mr-fg2 input, .mr-fg2 select, .mr-fg2 textarea { width: 100%; padding: 10px 12px; border: 1px solid var(--mr-border); border-radius: var(--mr-r-sm); font-size: 14px; transition: var(--mr-ease); }
        .mr-fg2 input:focus, .mr-fg2 select:focus, .mr-fg2 textarea:focus { outline: none; border-color: var(--mr-primary); box-shadow: 0 0 0 3px rgba(91,141,239,0.1); }
        .mr-det-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin-bottom: 20px; }
        .mr-det-lb { font-size: 12px; color: var(--mr-text3); margin-bottom: 6px; }
        .mr-det-vl { font-size: 15px; font-weight: 600; color: var(--mr-text); }
        .mr-det-mat-card { margin-bottom: 20px; background: #fff; border-radius: var(--mr-r-md); border: 1px solid var(--mr-border); overflow: hidden; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
        .mr-det-mat-top { padding: 24px 28px; display: flex; align-items: center; gap: 32px; }
        .mr-det-mat-title { display: flex; align-items: baseline; gap: 8px; flex-shrink: 0; min-width: 0; }
        .mr-det-mat-name { font-size: 18px; font-weight: 700; color: var(--mr-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; }
        .mr-det-mat-spec { font-size: 18px; font-weight: 700; color: var(--mr-text2); }
        .mr-det-mat-nums { display: flex; gap: 1px; flex: 1; background: var(--mr-border); border-radius: 8px; overflow: hidden; }
        .mr-det-mat-num { flex: 1; background: #fff; padding: 10px 16px; text-align: center; }
        .mr-det-mat-num small { display: block; font-size: 18px; font-weight: 700; color: var(--mr-text3); margin-bottom: 8px; }
        .mr-det-mat-num b { display: block; font-size: 22px; font-weight: 700; }
        .mr-det-mat-num.s-ordered b { color: var(--mr-text); } .mr-det-mat-num.s-received b { color: var(--mr-success); } .mr-det-mat-num.s-remaining b { color: var(--mr-warning); }
        .mr-det-mat-bottom { padding: 18px 28px 24px; display: flex; align-items: center; gap: 16px; }
        .mr-det-mat-bar { flex: 1; height: 14px; background: #E5E7EB; border-radius: 7px; overflow: hidden; }
        .mr-det-mat-pct { font-size: 20px; font-weight: 800; width: 65px; text-align: right; flex-shrink: 0; }
        .mr-sku-row { background: #FAFBFC; border-radius: var(--mr-r-sm); padding: 16px 20px; margin-bottom: 12px; border: 1px solid var(--mr-border); }
        .mr-sku-row:hover { border-color: var(--mr-primary); background: var(--mr-primary-lighter); }
        .mr-sku-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        .mr-sku-name { font-weight: 600; color: var(--mr-text); font-size: 15px; }
        .mr-sku-spec { font-size: 13px; color: var(--mr-text2); margin-left: 10px; }
        .mr-sku-pct { font-size: 14px; font-weight: 600; }
        .mr-sku-bar { height: 10px; background: #E5E7EB; border-radius: 5px; overflow: hidden; margin-bottom: 10px; }
        .mr-sku-info { display: flex; gap: 20px; font-size: 13px; color: var(--mr-text2); }
        .mr-sku-info span b { color: var(--mr-text); font-weight: 600; }
        @media (max-width: 1200px) { .mr-stats { grid-template-columns: repeat(3,1fr); } .mr-cat-grid { grid-template-columns: repeat(2,1fr); } .mr-chart-row { grid-template-columns: 1fr; } }
        @media (max-width: 768px) { .mr-stats { grid-template-columns: repeat(2,1fr); } .mr-cat-grid { grid-template-columns: 1fr; } .mr-filters { flex-direction: column; align-items: stretch; } .mr-fg { width: 100%; } .mr-header { flex-direction: column; gap: 12px; } .mr-det-grid { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  );
}
