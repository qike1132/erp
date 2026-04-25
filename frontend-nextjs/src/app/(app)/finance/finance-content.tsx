"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "@/lib/api-client";

// ============ Types ============

interface DailyLog { date: string; customer_names: string; stockout_count: number; total_quantity: number; total_amount: number }
interface CustomerLog { customer: string; stockout_count: number; total_quantity: number; total_amount: number }
interface Pagination { total: number; pages: number; page: number; per_page: number }
interface DailyStats { total_count: number; total_quantity: number; total_amount: number }
interface CustomerStats { total_count: number; total_quantity: number; total_amount: number }
interface DailyResult { success: boolean; logs: DailyLog[]; pagination: Pagination; stats: DailyStats }
interface CustomerResult { success: boolean; logs: CustomerLog[]; pagination: Pagination; stats: CustomerStats }
interface ChartResult { success: boolean; chart: { dates: string[]; amounts: number[]; quantities: number[] } }
export interface CustomerName { id: number; name: string }

/* eslint-disable @typescript-eslint/no-explicit-any */
type ChartInstance = any;

const PER_PAGE = 20;
const fmtAmt = (v: number) => "¥" + Number(v).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// ============ Chart.js Loader ============

let chartLoadPromise: Promise<void> | null = null;

function loadChartJS(): Promise<void> {
  if ((window as any).Chart) return Promise.resolve();
  if (chartLoadPromise) return chartLoadPromise;
  chartLoadPromise = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js";
    s.onload = () => resolve();
    s.onerror = () => { chartLoadPromise = null; reject(new Error("Chart.js load failed")); };
    document.head.appendChild(s);
  });
  return chartLoadPromise;
}

// ============ Component ============

interface FinanceContentProps {
  initialCustomerNames?: CustomerName[];
}

export function FinanceContent({ initialCustomerNames }: FinanceContentProps) {
  const [tab, setTab] = useState<"daily" | "customer">("daily");
  const [dPage, setDPage] = useState(1);
  const [cPage, setCPage] = useState(1);
  const [dCustomer, setDCustomer] = useState("");
  const [dStart, setDStart] = useState("");
  const [dEnd, setDEnd] = useState("");
  const [cCustomer, setCCustomer] = useState("");
  const [cStart, setCStart] = useState("");
  const [cEnd, setCEnd] = useState("");
  const [dailySearched, setDailySearched] = useState(false);
  const [custSearched, setCustSearched] = useState(false);
  const [chartReady, setChartReady] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const chartRef = useRef<ChartInstance | null>(null);

  // Load Chart.js
  useEffect(() => { loadChartJS().then(() => setChartReady(true)).catch(() => {}); }, []);

  // Load customer list
  const { data: customerNames } = useQuery<CustomerName[]>({
    queryKey: ["customer-active-names"],
    queryFn: () => get<CustomerName[]>("/customers/active-names"),
    initialData: initialCustomerNames,
  });

  // Daily amount query
  const { data: dailyData, isLoading: dailyLoading } = useQuery<DailyResult>({
    queryKey: ["finance-daily", dPage, dCustomer, dStart, dEnd],
    queryFn: () => get<DailyResult>("/finance/daily-amount", {
      page: String(dPage), per_page: String(PER_PAGE),
      ...(dCustomer && { customer: dCustomer }),
      ...(dStart && { start_date: dStart }),
      ...(dEnd && { end_date: dEnd }),
    }),
    enabled: dailySearched,
  });

  // Daily chart query
  const { data: chartData } = useQuery<ChartResult>({
    queryKey: ["finance-daily-chart", dCustomer, dStart, dEnd],
    queryFn: () => get<ChartResult>("/finance/daily-amount-chart", {
      ...(dCustomer && { customer: dCustomer }),
      ...(dStart && { start_date: dStart }),
      ...(dEnd && { end_date: dEnd }),
    }),
    enabled: dailySearched,
  });

  // Customer summary query
  const { data: custData, isLoading: custLoading } = useQuery<CustomerResult>({
    queryKey: ["finance-customer", cPage, cCustomer, cStart, cEnd],
    queryFn: () => get<CustomerResult>("/finance/customer-summary", {
      page: String(cPage), per_page: String(PER_PAGE),
      ...(cCustomer && { customer: cCustomer }),
      ...(cStart && { start_date: cStart }),
      ...(cEnd && { end_date: cEnd }),
    }),
    enabled: custSearched,
  });

  const dailyLogs = dailyData?.logs || [];
  const dailyPag = dailyData?.pagination;
  const dailyStats = dailyData?.stats;
  const custLogs = custData?.logs || [];
  const custPag = custData?.pagination;
  const custStats = custData?.stats;
  const chart = chartData?.chart;

  // Render chart
  const renderChart = useCallback(() => {
    if (!canvasRef.current || !chart || !chart.dates?.length || !chartReady) {
      if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null; }
      return;
    }
    if (chartRef.current) chartRef.current.destroy();
    const ctx = canvasRef.current.getContext("2d");
    if (!ctx) return;
    const ChartCtor = (window as any).Chart;
    if (!ChartCtor) return;
    chartRef.current = new ChartCtor(ctx, {
      type: "line",
      data: {
        labels: chart.dates,
        datasets: [{
          label: "出货金额", data: chart.amounts,
          borderColor: "rgb(135,206,235)", backgroundColor: "rgba(135,206,235,0.12)",
          borderWidth: 2.5, fill: true, tension: 0.35,
          pointRadius: 4, pointHoverRadius: 7,
          pointBackgroundColor: "rgb(135,206,235)", pointBorderColor: "#fff", pointBorderWidth: 2,
          yAxisID: "y",
        }, {
          label: "出货数量", data: chart.quantities,
          borderColor: "rgb(46,125,50)", backgroundColor: "rgba(46,125,50,0.08)",
          borderWidth: 2, fill: false, tension: 0.35,
          pointRadius: 3, pointHoverRadius: 6,
          pointBackgroundColor: "rgb(46,125,50)", pointBorderColor: "#fff", pointBorderWidth: 2,
          yAxisID: "y1",
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          tooltip: {
            backgroundColor: "rgba(90,74,74,0.9)",
            titleFont: { weight: "600" }, bodyFont: { size: 13 },
            padding: 12, cornerRadius: 8,
            callbacks: {
              label: (context: any) => {
                let lbl = context.dataset.label || "";
                if (lbl) lbl += ": ";
                lbl += context.datasetIndex === 0 ? fmtAmt(context.parsed.y) : String(context.parsed.y);
                return lbl;
              },
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 11 } } },
          y: {
            type: "linear", display: true, position: "left",
            title: { display: true, text: "金额 (¥)", font: { size: 12, weight: "600" }, color: "rgb(135,206,235)" },
            grid: { color: "rgba(176,224,230,0.3)" },
            ticks: { callback: (v: any) => "¥" + Number(v).toLocaleString(), font: { size: 11 } },
          },
          y1: {
            type: "linear", display: true, position: "right",
            title: { display: true, text: "数量", font: { size: 12, weight: "600" }, color: "rgb(46,125,50)" },
            grid: { drawOnChartArea: false },
            ticks: { font: { size: 11 } },
          },
        },
      },
    });
  }, [chart, chartReady]);

  useEffect(() => { renderChart(); }, [renderChart]);
  useEffect(() => () => { if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null; } }, []);

  const searchDaily = () => { setDPage(1); setDailySearched(true); };
  const resetDaily = () => { setDCustomer(""); setDStart(""); setDEnd(""); setDailySearched(false); setDPage(1); };
  const searchCust = () => { setCPage(1); setCustSearched(true); };
  const resetCust = () => { setCCustomer(""); setCStart(""); setCEnd(""); setCustSearched(false); setCPage(1); };

  return (
    <div className="fn-wrap">
      <h2 className="fn-title"><i className="fas fa-yen-sign" style={{ marginRight: 8 }}></i>财务统计</h2>

      {/* Tabs */}
      <ul className="nav nav-tabs fn-tabs">
        <li className="nav-item">
          <button className={`nav-link ${tab === "daily" ? "active" : ""}`} onClick={() => setTab("daily")}>
            <i className="fas fa-calendar-day" style={{ marginRight: 4 }}></i>每日出货金额
          </button>
        </li>
        <li className="nav-item">
          <button className={`nav-link ${tab === "customer" ? "active" : ""}`} onClick={() => setTab("customer")}>
            <i className="fas fa-building" style={{ marginRight: 4 }}></i>客户出货汇总
          </button>
        </li>
      </ul>

      {/* ============ Daily Tab ============ */}
      {tab === "daily" && (
        <div className="fn-panel">
          <div className="card fn-card">
            <div className="card-header">查询条件</div>
            <div className="card-body">
              <div className="row g-3 align-items-end">
                <div className="col-md-3">
                  <label className="form-label">客户名称</label>
                  <select className="form-select" value={dCustomer} onChange={e => setDCustomer(e.target.value)}>
                    <option value="">全部客户</option>
                    {customerNames?.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
                  </select>
                </div>
                <div className="col-md-3">
                  <label className="form-label">开始日期</label>
                  <input type="date" className="form-control" value={dStart} onChange={e => setDStart(e.target.value)} />
                </div>
                <div className="col-md-3">
                  <label className="form-label">结束日期</label>
                  <input type="date" className="form-control" value={dEnd} onChange={e => setDEnd(e.target.value)} />
                </div>
                <div className="col-md-3">
                  <label className="form-label">&nbsp;</label>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="btn btn-primary" style={{ flex: 1 }} onClick={searchDaily}><i className="fas fa-search" style={{ marginRight: 4 }}></i>查询</button>
                    <button className="btn btn-outline-secondary" onClick={resetDaily}><i className="fas fa-redo"></i></button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="row fn-stats-row">
            <div className="col-md-4"><div className="card stat-card"><div className="card-body text-center"><div className="stat-value">{dailyStats?.total_count ?? 0}</div><div className="stat-label">出货天数</div></div></div></div>
            <div className="col-md-4"><div className="card stat-card stat-card-primary"><div className="card-body text-center"><div className="stat-value">{(dailyStats?.total_quantity ?? 0).toLocaleString()}</div><div className="stat-label">出货总量</div></div></div></div>
            <div className="col-md-4"><div className="card stat-card stat-card-success"><div className="card-body text-center"><div className="stat-value">{fmtAmt(dailyStats?.total_amount ?? 0)}</div><div className="stat-label">出货总金额</div></div></div></div>
          </div>

          <div className="card fn-card">
            <div className="card-header">每日金额趋势</div>
            <div className="card-body">
              {chart && chart.dates?.length > 0 && chartReady ? (
                <div style={{ position: "relative", height: 300 }}><canvas ref={canvasRef}></canvas></div>
              ) : (
                <div className="fn-empty">
                  <i className="fas fa-chart-line" style={{ fontSize: 48, opacity: 0.3, marginBottom: 12 }}></i>
                  <p style={{ color: "#718096" }}>{dailySearched && !chart?.dates?.length ? "暂无图表数据" : "请点击查询按钮获取数据"}</p>
                </div>
              )}
            </div>
          </div>

          <div className="card fn-card">
            <div className="card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>每日出货明细</span>
              <span style={{ fontSize: 14, color: "#718096" }}>共 {dailyPag?.total ?? 0} 条记录</span>
            </div>
            <div className="card-body">
              <table className="table table-hover">
                <thead><tr>
                  <th style={{ width: "13%" }}>日期</th><th style={{ width: "30%" }}>客户名称</th>
                  <th style={{ width: "14%", textAlign: "center" }}>出货次数</th>
                  <th style={{ width: "14%", textAlign: "center" }}>出货数量</th>
                  <th style={{ width: "29%", textAlign: "right" }}>出货金额</th>
                </tr></thead>
                <tbody>
                  {dailyLoading ? (
                    <tr><td colSpan={5} className="fn-td-center"><div className="spinner-border text-primary"></div><p style={{ color: "#718096", marginTop: 8 }}>正在查询...</p></td></tr>
                  ) : !dailySearched ? (
                    <tr><td colSpan={5} className="fn-td-center"><i className="fas fa-inbox" style={{ fontSize: 48, opacity: 0.3, marginBottom: 12 }}></i><p style={{ color: "#718096" }}>请点击查询按钮获取数据</p></td></tr>
                  ) : dailyLogs.length === 0 ? (
                    <tr><td colSpan={5} className="fn-td-center"><i className="fas fa-inbox" style={{ fontSize: 48, opacity: 0.3, marginBottom: 12 }}></i><p style={{ color: "#718096" }}>暂无数据</p></td></tr>
                  ) : dailyLogs.map((log, i) => (
                    <tr key={i}>
                      <td><i className="fas fa-calendar" style={{ marginRight: 4, color: "#718096" }}></i>{log.date}</td>
                      <td><i className="fas fa-building" style={{ marginRight: 4, color: "#718096" }}></i>{log.customer_names || "-"}</td>
                      <td style={{ textAlign: "center" }}>{log.stockout_count}</td>
                      <td style={{ textAlign: "center" }}>{log.total_quantity.toLocaleString()}</td>
                      <td style={{ textAlign: "right", fontWeight: 700 }}>{fmtAmt(log.total_amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {dailyPag && dailyPag.pages > 1 && (
                <nav><ul className="pagination justify-content-center">
                  <li className={`page-item ${dailyPag.page <= 1 ? "disabled" : ""}`}><a className="page-link" href="#" onClick={e => { e.preventDefault(); if (dailyPag.page > 1) setDPage(dailyPag.page - 1); }}>上一页</a></li>
                  {Array.from({ length: dailyPag.pages }, (_, i) => i + 1).filter(p => p === 1 || p === dailyPag.pages || Math.abs(p - dailyPag.page) <= 2).map(p => (
                    <li key={p} className={`page-item ${p === dailyPag.page ? "active" : ""}`}><a className="page-link" href="#" onClick={e => { e.preventDefault(); setDPage(p); }}>{p}</a></li>
                  ))}
                  <li className={`page-item ${dailyPag.page >= dailyPag.pages ? "disabled" : ""}`}><a className="page-link" href="#" onClick={e => { e.preventDefault(); if (dailyPag.page < dailyPag.pages) setDPage(dailyPag.page + 1); }}>下一页</a></li>
                </ul></nav>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ============ Customer Tab ============ */}
      {tab === "customer" && (
        <div className="fn-panel">
          <div className="card fn-card">
            <div className="card-header">查询条件</div>
            <div className="card-body">
              <div className="row g-3 align-items-end">
                <div className="col-md-3">
                  <label className="form-label">客户名称</label>
                  <select className="form-select" value={cCustomer} onChange={e => setCCustomer(e.target.value)}>
                    <option value="">全部客户</option>
                    {customerNames?.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
                  </select>
                </div>
                <div className="col-md-3">
                  <label className="form-label">开始日期</label>
                  <input type="date" className="form-control" value={cStart} onChange={e => setCStart(e.target.value)} />
                </div>
                <div className="col-md-3">
                  <label className="form-label">结束日期</label>
                  <input type="date" className="form-control" value={cEnd} onChange={e => setCEnd(e.target.value)} />
                </div>
                <div className="col-md-3">
                  <label className="form-label">&nbsp;</label>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="btn btn-primary" style={{ flex: 1 }} onClick={searchCust}><i className="fas fa-search" style={{ marginRight: 4 }}></i>查询</button>
                    <button className="btn btn-outline-secondary" onClick={resetCust}><i className="fas fa-redo"></i></button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="row fn-stats-row">
            <div className="col-md-4"><div className="card stat-card"><div className="card-body text-center"><div className="stat-value">{custStats?.total_count ?? 0}</div><div className="stat-label">客户数量</div></div></div></div>
            <div className="col-md-4"><div className="card stat-card stat-card-primary"><div className="card-body text-center"><div className="stat-value">{(custStats?.total_quantity ?? 0).toLocaleString()}</div><div className="stat-label">出货总量</div></div></div></div>
            <div className="col-md-4"><div className="card stat-card stat-card-success"><div className="card-body text-center"><div className="stat-value">{fmtAmt(custStats?.total_amount ?? 0)}</div><div className="stat-label">出货总金额</div></div></div></div>
          </div>

          <div className="card fn-card">
            <div className="card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>客户出货汇总</span>
              <span style={{ fontSize: 14, color: "#718096" }}>共 {custPag?.total ?? 0} 条记录</span>
            </div>
            <div className="card-body">
              <table className="table table-hover">
                <thead><tr>
                  <th style={{ width: "30%" }}>客户名称</th>
                  <th style={{ width: "17%", textAlign: "center" }}>出货次数</th>
                  <th style={{ width: "17%", textAlign: "center" }}>出货数量</th>
                  <th style={{ width: "36%", textAlign: "right" }}>出货金额</th>
                </tr></thead>
                <tbody>
                  {custLoading ? (
                    <tr><td colSpan={4} className="fn-td-center"><div className="spinner-border text-primary"></div><p style={{ color: "#718096", marginTop: 8 }}>正在查询...</p></td></tr>
                  ) : !custSearched ? (
                    <tr><td colSpan={4} className="fn-td-center"><i className="fas fa-inbox" style={{ fontSize: 48, opacity: 0.3, marginBottom: 12 }}></i><p style={{ color: "#718096" }}>请点击查询按钮获取数据</p></td></tr>
                  ) : custLogs.length === 0 ? (
                    <tr><td colSpan={4} className="fn-td-center"><i className="fas fa-inbox" style={{ fontSize: 48, opacity: 0.3, marginBottom: 12 }}></i><p style={{ color: "#718096" }}>暂无数据</p></td></tr>
                  ) : custLogs.map((log, i) => (
                    <tr key={i}>
                      <td><i className="fas fa-building" style={{ marginRight: 4, color: "#718096" }}></i>{log.customer || "未知客户"}</td>
                      <td style={{ textAlign: "center" }}>{log.stockout_count}</td>
                      <td style={{ textAlign: "center" }}>{log.total_quantity.toLocaleString()}</td>
                      <td style={{ textAlign: "right", fontWeight: 700 }}>{fmtAmt(log.total_amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {custPag && custPag.pages > 1 && (
                <nav><ul className="pagination justify-content-center">
                  <li className={`page-item ${custPag.page <= 1 ? "disabled" : ""}`}><a className="page-link" href="#" onClick={e => { e.preventDefault(); if (custPag.page > 1) setCPage(custPag.page - 1); }}>上一页</a></li>
                  {Array.from({ length: custPag.pages }, (_, i) => i + 1).filter(p => p === 1 || p === custPag.pages || Math.abs(p - custPag.page) <= 2).map(p => (
                    <li key={p} className={`page-item ${p === custPag.page ? "active" : ""}`}><a className="page-link" href="#" onClick={e => { e.preventDefault(); setCPage(p); }}>{p}</a></li>
                  ))}
                  <li className={`page-item ${custPag.page >= custPag.pages ? "disabled" : ""}`}><a className="page-link" href="#" onClick={e => { e.preventDefault(); if (custPag.page < custPag.pages) setCPage(custPag.page + 1); }}>下一页</a></li>
                </ul></nav>
              )}
            </div>
          </div>
        </div>
      )}

      <style jsx global>{`
        .fn-wrap { padding: 20px; font-family: "Microsoft YaHei","Segoe UI",sans-serif; }
        .fn-title { font-size: 22px; font-weight: 600; color: var(--plush-text,#2D3748); margin-bottom: 16px; display: flex; align-items: center; }
        .fn-tabs { margin-top: 12px; border-bottom: 2px solid #dee2e6; }
        .fn-tabs .nav-link { color: var(--plush-text-light,#718096); font-weight: 600; border: none; padding: 10px 20px; border-bottom: 3px solid transparent; transition: all 0.2s; background: none; }
        .fn-tabs .nav-link.active { color: var(--plush-blue-text,#2563EB); font-weight: 700; border-bottom-color: var(--plush-blue-deep,#2563EB); }
        .fn-tabs .nav-link:hover:not(.active) { color: var(--plush-text,#2D3748); border-bottom-color: rgba(37,99,235,0.3); }
        .fn-panel { margin-top: 16px; }
        .fn-card { border: none; border-radius: var(--radius-card,10px); box-shadow: 0 2px 8px rgba(0,0,0,0.06); margin-bottom: 16px; overflow: hidden; background: #fff; }
        .fn-card .card-header { padding: 12px 20px; background: #f8f9fa; border-bottom: 1px solid #e9ecef; font-weight: 600; font-size: 15px; color: var(--plush-text,#2D3748); }
        .fn-card .card-body { padding: 20px; }
        .row { display: flex; flex-wrap: wrap; margin: 0 -8px; }
        .row > [class*="col-"] { padding: 0 8px; }
        .col-md-3 { flex: 0 0 25%; max-width: 25%; }
        .col-md-4 { flex: 0 0 33.333%; max-width: 33.333%; }
        .g-3 { gap: 16px; }
        .align-items-end { align-items: flex-end; }
        .form-label { font-size: 13px; color: #718096; font-weight: 500; margin-bottom: 6px; display: block; }
        .form-select, .form-control { width: 100%; padding: 8px 12px; border: 1px solid #dee2e6; border-radius: 6px; font-size: 14px; color: #2D3748; background: #fff; transition: border-color 0.2s,box-shadow 0.2s; box-sizing: border-box; }
        .form-select:focus, .form-control:focus { outline: none; border-color: #87CEEB; box-shadow: 0 0 0 3px rgba(135,206,235,0.15); }
        .btn { padding: 8px 16px; border-radius: 6px; font-size: 14px; font-weight: 500; cursor: pointer; transition: all 0.2s; border: 1px solid transparent; display: inline-flex; align-items: center; justify-content: center; gap: 4px; }
        .btn-primary { background: #007bff; color: #fff; border-color: #007bff; }
        .btn-primary:hover { background: #0069d9; }
        .btn-outline-secondary { background: #fff; color: #6c757d; border-color: #dee2e6; }
        .btn-outline-secondary:hover { background: #f8f9fa; color: #495057; }
        .fn-stats-row { margin-top: 16px; margin-bottom: 16px; }
        .stat-card { border: none; border-radius: var(--radius-card,10px); transition: transform 0.3s cubic-bezier(0.4,0,0.2,1),box-shadow 0.3s cubic-bezier(0.4,0,0.2,1); background: #fff; box-shadow: 0 4px 16px rgba(0,0,0,0.06); position: relative; overflow: hidden; }
        .stat-card::after { content: ""; position: absolute; top: -30px; right: -30px; width: 90px; height: 90px; border-radius: 50%; opacity: 0.08; transition: transform 0.3s,opacity 0.3s; }
        .stat-card:hover { transform: translateY(-4px); box-shadow: 0 8px 28px rgba(0,0,0,0.1); }
        .stat-card:hover::after { transform: scale(1.2); opacity: 0.12; }
        .stat-card .stat-value { font-size: 1.8rem; font-weight: 700; color: var(--plush-text,#2D3748); line-height: 1.2; font-variant-numeric: tabular-nums; }
        .stat-card .stat-label { font-size: 0.85rem; color: var(--plush-text-light,#718096); margin-top: 6px; font-weight: 500; }
        .stat-card-primary { border-left: 4px solid var(--plush-blue-deep,#2563EB); }
        .stat-card-primary::after { background: var(--plush-blue-deep,#2563EB); }
        .stat-card-primary .stat-value { color: var(--plush-blue-text,#2563EB); }
        .stat-card-success { border-left: 4px solid #28C76F; }
        .stat-card-success::after { background: #28C76F; }
        .stat-card-success .stat-value { color: #1E9E55; }
        .table { width: 100%; border-collapse: collapse; font-size: 14px; }
        .table thead th { background: #f8f9fa; padding: 10px 12px; border-bottom: 2px solid #dee2e6; font-weight: 600; color: #2D3748; white-space: nowrap; }
        .table tbody td { padding: 10px 12px; border-bottom: 1px solid #e9ecef; vertical-align: middle; }
        .table-hover tbody tr:hover { background: #f0f6ff; }
        .fn-td-center { text-align: center; padding: 40px 20px; }
        .fn-empty { text-align: center; padding: 40px 20px; }
        .pagination { display: flex; gap: 4px; list-style: none; padding: 0; margin: 16px 0 0; justify-content: center; }
        .page-item .page-link { padding: 6px 12px; border: 1px solid #dee2e6; border-radius: 4px; color: #007bff; text-decoration: none; font-size: 14px; display: block; transition: all 0.2s; background: #fff; }
        .page-item.active .page-link { background: #007bff; color: #fff; border-color: #007bff; }
        .page-item.disabled .page-link { color: #6c757d; pointer-events: none; opacity: 0.5; }
        .page-item .page-link:hover:not(.disabled) { background: #e9ecef; }
        .text-center { text-align: center; }
        .spinner-border { display: inline-block; width: 24px; height: 24px; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; animation: fn-spin 0.75s linear infinite; }
        .text-primary { color: #007bff; }
        @keyframes fn-spin { to { transform: rotate(360deg); } }
        @media (max-width: 768px) {
          .col-md-3, .col-md-4 { flex: 0 0 100%; max-width: 100%; }
          .row { flex-direction: column; }
          .stat-card .stat-value { font-size: 1.4rem; }
        }
      `}</style>
    </div>
  );
}
