"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post, put, del } from "@/lib/api-client";

// ============ Types ============

interface CraftWork { id: number; worker_name: string; quantity: number; work_date: string; remark: string; }
interface PackagingRecord { id: number; customer: string; product_name: string; barcode: string; quantity: number; pack_date: string; remark: string; }
interface DailySummary { date: string; case_out_count: number; craft_count: number; }
interface SummaryDay { date: string; case_out: number; craft: number; packaging: number; details: string; }
interface MonthlySummary { total_case_out: number; total_craft: number; total_packaging: number; diff_craft: number; diff_packaging: number; }

export interface CraftListResult { success: boolean; data: CraftWork[]; daily_summary: DailySummary[]; total: number; }
export interface PackagingListResult { success: boolean; data: PackagingRecord[]; total: number; }
export interface SummaryResult { success: boolean; data: SummaryDay[]; monthly_summary: MonthlySummary; total: number; }

// ============ Component ============

interface ProductionContentProps {
  initialCraft?: CraftListResult;
  initialPackaging?: PackagingListResult;
  initialSummary?: SummaryResult;
}

export function ProductionContent({ initialCraft, initialPackaging, initialSummary }: ProductionContentProps) {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<"craft" | "packaging" | "summary">("craft");

  const now = new Date();
  const [craftYear, setCraftYear] = useState(now.getFullYear());
  const [craftMonth, setCraftMonth] = useState(now.getMonth() + 1);
  const [packYear, setPackYear] = useState(now.getFullYear());
  const [packMonth, setPackMonth] = useState(now.getMonth() + 1);
  const [packCustomer, setPackCustomer] = useState("");
  const [sumYear, setSumYear] = useState(now.getFullYear());
  const [sumMonth, setSumMonth] = useState(now.getMonth() + 1);

  // Modals
  const [craftAddOpen, setCraftAddOpen] = useState(false);
  const [craftAddForm, setCraftAddForm] = useState({ worker_name: "", quantity: 1, work_date: now.toISOString().split("T")[0], remark: "" });
  const [craftEditOpen, setCraftEditOpen] = useState(false);
  const [craftEditForm, setCraftEditForm] = useState({ id: 0, worker_name: "", quantity: 1, work_date: "", remark: "" });

  const [packAddOpen, setPackAddOpen] = useState(false);
  const [packAddForm, setPackAddForm] = useState({ customer: "", product_name: "", barcode: "", quantity: 1, pack_date: now.toISOString().split("T")[0], remark: "" });
  const [packEditOpen, setPackEditOpen] = useState(false);
  const [packEditForm, setPackEditForm] = useState({ id: 0, customer: "", product_name: "", barcode: "", quantity: 1, pack_date: "", remark: "" });

  // ============ Queries ============

  const { data: craftData, isLoading: craftLoading } = useQuery<CraftListResult>({
    queryKey: ["craft-list", craftYear, craftMonth],
    queryFn: () => get<CraftListResult>("/production-summary/craft/list", { year: String(craftYear), month: String(craftMonth) }),
    initialData: initialCraft && craftYear === now.getFullYear() && craftMonth === now.getMonth() + 1 ? initialCraft : undefined,
  });

  const { data: packData, isLoading: packLoading } = useQuery<PackagingListResult>({
    queryKey: ["pack-list", packYear, packMonth, packCustomer],
    queryFn: () => get<PackagingListResult>("/production-summary/packaging/list", {
      year: String(packYear), month: String(packMonth),
      ...(packCustomer && { customer: packCustomer }),
    }),
    initialData: initialPackaging && packYear === now.getFullYear() && packMonth === now.getMonth() + 1 && !packCustomer ? initialPackaging : undefined,
  });

  const { data: sumData, isLoading: sumLoading } = useQuery<SummaryResult>({
    queryKey: ["production-summary", sumYear, sumMonth],
    queryFn: () => get<SummaryResult>("/production-summary/summary", { year: String(sumYear), month: String(sumMonth) }),
    initialData: initialSummary && sumYear === now.getFullYear() && sumMonth === now.getMonth() + 1 ? initialSummary : undefined,
  });

  // ============ Mutations ============

  const craftCreateMut = useMutation({
    mutationFn: (body: typeof craftAddForm) => post<Record<string, unknown>>("/production-summary/craft/create", body),
    onSuccess: () => { setCraftAddOpen(false); setCraftAddForm({ worker_name: "", quantity: 1, work_date: now.toISOString().split("T")[0], remark: "" }); qc.invalidateQueries({ queryKey: ["craft-list"] }); },
  });

  const craftEditMut = useMutation({
    mutationFn: (body: typeof craftEditForm) => put<Record<string, unknown>>(`/production-summary/craft/edit/${body.id}`, body),
    onSuccess: () => { setCraftEditOpen(false); qc.invalidateQueries({ queryKey: ["craft-list"] }); },
  });

  const craftDeleteMut = useMutation({
    mutationFn: (id: number) => del<Record<string, unknown>>(`/production-summary/craft/delete/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["craft-list"] }); },
  });

  const packCreateMut = useMutation({
    mutationFn: (body: typeof packAddForm) => post<Record<string, unknown>>("/production-summary/packaging/create", body),
    onSuccess: () => { setPackAddOpen(false); setPackAddForm({ customer: "", product_name: "", barcode: "", quantity: 1, pack_date: now.toISOString().split("T")[0], remark: "" }); qc.invalidateQueries({ queryKey: ["pack-list"] }); },
  });

  const packEditMut = useMutation({
    mutationFn: (body: typeof packEditForm) => put<Record<string, unknown>>(`/production-summary/packaging/edit/${body.id}`, body),
    onSuccess: () => { setPackEditOpen(false); qc.invalidateQueries({ queryKey: ["pack-list"] }); },
  });

  const packDeleteMut = useMutation({
    mutationFn: (id: number) => del<Record<string, unknown>>(`/production-summary/packaging/delete/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["pack-list"] }); },
  });

  // ============ Helpers ============

  const craftList = craftData?.data || [];
  const craftDaily = craftData?.daily_summary || [];
  const packList = packData?.data || [];
  const sumList = sumData?.data || [];
  const sumSummary = sumData?.monthly_summary;

  const openCraftEdit = (item: CraftWork) => { setCraftEditForm({ id: item.id, worker_name: item.worker_name, quantity: item.quantity, work_date: item.work_date, remark: item.remark }); setCraftEditOpen(true); };
  const openPackEdit = (item: PackagingRecord) => { setPackEditForm({ id: item.id, customer: item.customer, product_name: item.product_name, barcode: item.barcode, quantity: item.quantity, pack_date: item.pack_date, remark: item.remark }); setPackEditOpen(true); };

  // ============ Render ============

  return (
    <div className="ps-page-root">
      <h2 className="ps-page-title">生产报表</h2>

      {/* Tabs */}
      <ul className="ps-nav-tabs">
        <li className={`ps-nav-item ${activeTab === "craft" ? "active" : ""}`}>
          <button onClick={() => setActiveTab("craft")}><i className="fas fa-hands" style={{ marginRight: 4 }}></i>手工部</button>
        </li>
        <li className={`ps-nav-item ${activeTab === "packaging" ? "active" : ""}`}>
          <button onClick={() => setActiveTab("packaging")}><i className="fas fa-box-open" style={{ marginRight: 4 }}></i>包装部</button>
        </li>
        <li className={`ps-nav-item ${activeTab === "summary" ? "active" : ""}`}>
          <button onClick={() => setActiveTab("summary")}><i className="fas fa-chart-line" style={{ marginRight: 4 }}></i>汇总报表</button>
        </li>
      </ul>

      {/* ======== 手工部 ======== */}
      {activeTab === "craft" && (
        <div className="ps-tab-panel">
          {/* Action bar */}
          <div className="ps-action-bar">
            <div className="ps-action-left">
              <label style={{ fontSize: 13, fontWeight: 500 }}>月份:</label>
              <input type="number" className="ps-input-sm" value={craftYear} onChange={e => setCraftYear(Number(e.target.value))} min={2020} max={2099} style={{ width: 90 }} />
              <span style={{ fontWeight: 700 }}>年</span>
              <input type="number" className="ps-input-sm" value={craftMonth} onChange={e => setCraftMonth(Number(e.target.value))} min={1} max={12} style={{ width: 70 }} />
              <span style={{ fontWeight: 700 }}>月</span>
              <button className="ps-btn ps-btn-primary ps-btn-sm" onClick={() => qc.invalidateQueries({ queryKey: ["craft-list"] })}><i className="fas fa-search" style={{ marginRight: 4 }}></i>查询</button>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="ps-btn ps-btn-outline-success ps-btn-sm" onClick={() => { const a = document.createElement("a"); a.href = `/api/v1/production-summary/craft/export?start_date=${craftYear}-${String(craftMonth).padStart(2, "0")}-01`; a.click(); }}>
                <i className="fas fa-file-export" style={{ marginRight: 4 }}></i>导出手工生产数据
              </button>
              <button className="ps-btn ps-btn-primary ps-btn-sm" onClick={() => setCraftAddOpen(true)}><i className="fas fa-plus" style={{ marginRight: 4 }}></i>添加记录</button>
            </div>
          </div>

          {/* Daily summary */}
          <div className="ps-card" style={{ marginBottom: 16 }}>
            <div className="ps-card-header"><i className="fas fa-calendar-alt" style={{ marginRight: 4 }}></i>当月每日汇总</div>
            <div className="ps-card-body" style={{ maxHeight: 300, overflowY: "auto" }}>
              <table className="ps-table ps-table-sm">
                <thead><tr><th>日期</th><th style={{ textAlign: "center" }}>皮套出库总数</th><th style={{ textAlign: "center" }}>手工部生产总数</th></tr></thead>
                <tbody>
                  {craftDaily.length === 0 ? <tr><td colSpan={3} style={{ textAlign: "center", color: "#6c757d", padding: 12 }}>请选择月份查询</td></tr> :
                    craftDaily.map(d => (
                      <tr key={d.date}><td>{d.date}</td><td style={{ textAlign: "center" }}>{d.case_out_count}</td><td style={{ textAlign: "center" }}>{d.craft_count}</td></tr>
                    ))
                  }
                </tbody>
              </table>
            </div>
          </div>

          {/* Craft detail table */}
          <div className="ps-card">
            <div className="ps-card-header"><span><i className="fas fa-list" style={{ marginRight: 4 }}></i>生产记录明细</span><span style={{ color: "#6c757d", fontWeight: 400, fontSize: 13 }}>共 {craftList.length} 条</span></div>
            <div className="ps-card-body" style={{ padding: 0 }}>
              {craftLoading ? (
                <div className="ps-empty"><i className="fas fa-spinner fa-spin" style={{ fontSize: 32 }}></i><p>加载中...</p></div>
              ) : craftList.length === 0 ? (
                <div className="ps-empty"><p>请选择月份查询</p></div>
              ) : (
                <table className="ps-table">
                  <thead><tr><th>工人姓名</th><th style={{ textAlign: "center" }}>生产数量</th><th>生产日期</th><th>备注</th><th>操作</th></tr></thead>
                  <tbody>
                    {craftList.map(item => (
                      <tr key={item.id}>
                        <td>{item.worker_name}</td>
                        <td style={{ textAlign: "center" }}>{item.quantity}</td>
                        <td>{item.work_date}</td>
                        <td>{item.remark || "-"}</td>
                        <td>
                          <button className="ps-btn ps-btn-sm ps-btn-outline-warning" style={{ marginRight: 4 }} onClick={() => openCraftEdit(item)}><i className="fas fa-edit"></i></button>
                          <button className="ps-btn ps-btn-sm ps-btn-outline-danger" onClick={() => { if (confirm("确定删除？")) craftDeleteMut.mutate(item.id); }}><i className="fas fa-trash"></i></button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ======== 包装部 ======== */}
      {activeTab === "packaging" && (
        <div className="ps-tab-panel">
          <div className="ps-action-bar">
            <div className="ps-action-left">
              <label style={{ fontSize: 13, fontWeight: 500 }}>月份:</label>
              <input type="number" className="ps-input-sm" value={packYear} onChange={e => setPackYear(Number(e.target.value))} min={2020} max={2099} style={{ width: 90 }} />
              <span style={{ fontWeight: 700 }}>年</span>
              <input type="number" className="ps-input-sm" value={packMonth} onChange={e => setPackMonth(Number(e.target.value))} min={1} max={12} style={{ width: 70 }} />
              <span style={{ fontWeight: 700 }}>月</span>
              <input type="text" className="ps-input-sm" placeholder="客户名称" value={packCustomer} onChange={e => setPackCustomer(e.target.value)} style={{ width: 120 }} />
              <button className="ps-btn ps-btn-primary ps-btn-sm" onClick={() => qc.invalidateQueries({ queryKey: ["pack-list"] })}><i className="fas fa-search" style={{ marginRight: 4 }}></i>查询</button>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="ps-btn ps-btn-outline-success ps-btn-sm" onClick={() => { const a = document.createElement("a"); a.href = `/api/v1/production-summary/packaging/export?start_date=${packYear}-${String(packMonth).padStart(2, "0")}-01`; a.click(); }}>
                <i className="fas fa-file-export" style={{ marginRight: 4 }}></i>导出
              </button>
              <button className="ps-btn ps-btn-primary ps-btn-sm" onClick={() => setPackAddOpen(true)}><i className="fas fa-plus" style={{ marginRight: 4 }}></i>添加记录</button>
            </div>
          </div>

          <div className="ps-card">
            <div className="ps-card-header"><span><i className="fas fa-box-open" style={{ marginRight: 4 }}></i>包装生产流水</span><span style={{ color: "#6c757d", fontWeight: 400, fontSize: 13 }}>共 {packList.length} 条</span></div>
            <div className="ps-card-body" style={{ padding: 0 }}>
              {packLoading ? (
                <div className="ps-empty"><i className="fas fa-spinner fa-spin" style={{ fontSize: 32 }}></i><p>加载中...</p></div>
              ) : packList.length === 0 ? (
                <div className="ps-empty"><p>请选择月份查询</p></div>
              ) : (
                <table className="ps-table">
                  <thead><tr><th>客户</th><th>产品名称</th><th>69码</th><th style={{ textAlign: "center" }}>数量</th><th>包装日期</th><th>备注</th><th>操作</th></tr></thead>
                  <tbody>
                    {packList.map(item => (
                      <tr key={item.id}>
                        <td>{item.customer}</td>
                        <td>{item.product_name}</td>
                        <td><small>{item.barcode}</small></td>
                        <td style={{ textAlign: "center" }}>{item.quantity}</td>
                        <td>{item.pack_date}</td>
                        <td>{item.remark || "-"}</td>
                        <td>
                          <button className="ps-btn ps-btn-sm ps-btn-outline-warning" style={{ marginRight: 4 }} onClick={() => openPackEdit(item)}><i className="fas fa-edit"></i></button>
                          <button className="ps-btn ps-btn-sm ps-btn-outline-danger" onClick={() => { if (confirm("确定删除？")) packDeleteMut.mutate(item.id); }}><i className="fas fa-trash"></i></button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ======== 汇总报表 ======== */}
      {activeTab === "summary" && (
        <div className="ps-tab-panel">
          <div className="ps-action-bar">
            <div className="ps-action-left">
              <label style={{ fontSize: 13, fontWeight: 500 }}>月份:</label>
              <input type="number" className="ps-input-sm" value={sumYear} onChange={e => setSumYear(Number(e.target.value))} min={2020} max={2099} style={{ width: 90 }} />
              <span style={{ fontWeight: 700 }}>年</span>
              <input type="number" className="ps-input-sm" value={sumMonth} onChange={e => setSumMonth(Number(e.target.value))} min={1} max={12} style={{ width: 70 }} />
              <span style={{ fontWeight: 700 }}>月</span>
              <button className="ps-btn ps-btn-primary ps-btn-sm" onClick={() => qc.invalidateQueries({ queryKey: ["production-summary"] })}><i className="fas fa-search" style={{ marginRight: 4 }}></i>查询</button>
            </div>
          </div>

          {/* Monthly summary cards */}
          {sumSummary && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 16, marginBottom: 16 }}>
              <div className="ps-stat-card"><h3>{sumSummary.total_case_out}</h3><small>皮套出库总数</small></div>
              <div className="ps-stat-card"><h3>{sumSummary.total_craft}</h3><small>手工部生产总数</small></div>
              <div className="ps-stat-card"><h3>{sumSummary.total_packaging}</h3><small>包装部进仓总数</small></div>
              <div className="ps-stat-card"><h3 style={{ color: "#e0a800" }}>{sumSummary.diff_craft}</h3><small>出库-手工 差异</small></div>
              <div className="ps-stat-card"><h3 style={{ color: "#17a2b8" }}>{sumSummary.diff_packaging}</h3><small>手工-包装 差异</small></div>
            </div>
          )}

          <div className="ps-card">
            <div className="ps-card-header"><i className="fas fa-chart-line" style={{ marginRight: 4 }}></i>按日汇总报表</div>
            <div className="ps-card-body" style={{ padding: 0 }}>
              {sumLoading ? (
                <div className="ps-empty"><i className="fas fa-spinner fa-spin" style={{ fontSize: 32 }}></i><p>加载中...</p></div>
              ) : sumList.length === 0 ? (
                <div className="ps-empty"><p>请选择月份查询汇总报表</p></div>
              ) : (
                <table className="ps-table ps-table-sm">
                  <thead><tr><th>日期</th><th style={{ textAlign: "center" }}>配套出库总数</th><th style={{ textAlign: "center" }}>手工部生产总数</th><th style={{ textAlign: "center" }}>包装部进仓数量</th><th>产品明细</th></tr></thead>
                  <tbody>
                    {sumList.map(item => (
                      <tr key={item.date}>
                        <td>{item.date}</td>
                        <td style={{ textAlign: "center" }}>{item.case_out}</td>
                        <td style={{ textAlign: "center" }}>{item.craft}</td>
                        <td style={{ textAlign: "center" }}>{item.packaging}</td>
                        <td><small>{item.details || "-"}</small></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ======== Craft Add Modal ======== */}
      {craftAddOpen && (
        <div className="ps-modal-overlay" onClick={() => setCraftAddOpen(false)}>
          <div className="ps-modal" onClick={e => e.stopPropagation()}>
            <div className="ps-modal-header"><h5>添加手工部生产记录</h5><button className="ps-modal-close" onClick={() => setCraftAddOpen(false)}>&times;</button></div>
            <div className="ps-modal-body">
              <div className="ps-mb3"><label className="ps-form-label">工人姓名 *</label><input type="text" className="ps-form-control" value={craftAddForm.worker_name} onChange={e => setCraftAddForm({ ...craftAddForm, worker_name: e.target.value })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">生产数量 *</label><input type="number" className="ps-form-control" min={1} value={craftAddForm.quantity} onChange={e => setCraftAddForm({ ...craftAddForm, quantity: Number(e.target.value) })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">生产日期 *</label><input type="date" className="ps-form-control" value={craftAddForm.work_date} onChange={e => setCraftAddForm({ ...craftAddForm, work_date: e.target.value })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">备注</label><input type="text" className="ps-form-control" value={craftAddForm.remark} onChange={e => setCraftAddForm({ ...craftAddForm, remark: e.target.value })} /></div>
            </div>
            <div className="ps-modal-footer">
              <button className="ps-btn ps-btn-secondary" onClick={() => setCraftAddOpen(false)}>取消</button>
              <button className="ps-btn ps-btn-primary" onClick={() => craftCreateMut.mutate(craftAddForm)} disabled={craftCreateMut.isPending}>添加</button>
            </div>
          </div>
        </div>
      )}

      {/* ======== Craft Edit Modal ======== */}
      {craftEditOpen && (
        <div className="ps-modal-overlay" onClick={() => setCraftEditOpen(false)}>
          <div className="ps-modal" onClick={e => e.stopPropagation()}>
            <div className="ps-modal-header"><h5>编辑手工部生产记录</h5><button className="ps-modal-close" onClick={() => setCraftEditOpen(false)}>&times;</button></div>
            <div className="ps-modal-body">
              <div className="ps-mb3"><label className="ps-form-label">工人姓名 *</label><input type="text" className="ps-form-control" value={craftEditForm.worker_name} onChange={e => setCraftEditForm({ ...craftEditForm, worker_name: e.target.value })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">生产数量 *</label><input type="number" className="ps-form-control" min={1} value={craftEditForm.quantity} onChange={e => setCraftEditForm({ ...craftEditForm, quantity: Number(e.target.value) })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">生产日期 *</label><input type="date" className="ps-form-control" value={craftEditForm.work_date} onChange={e => setCraftEditForm({ ...craftEditForm, work_date: e.target.value })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">备注</label><input type="text" className="ps-form-control" value={craftEditForm.remark} onChange={e => setCraftEditForm({ ...craftEditForm, remark: e.target.value })} /></div>
            </div>
            <div className="ps-modal-footer">
              <button className="ps-btn ps-btn-secondary" onClick={() => setCraftEditOpen(false)}>取消</button>
              <button className="ps-btn ps-btn-primary" onClick={() => craftEditMut.mutate(craftEditForm)} disabled={craftEditMut.isPending}>保存</button>
            </div>
          </div>
        </div>
      )}

      {/* ======== Pack Add Modal ======== */}
      {packAddOpen && (
        <div className="ps-modal-overlay" onClick={() => setPackAddOpen(false)}>
          <div className="ps-modal" onClick={e => e.stopPropagation()}>
            <div className="ps-modal-header"><h5>添加包装部记录</h5><button className="ps-modal-close" onClick={() => setPackAddOpen(false)}>&times;</button></div>
            <div className="ps-modal-body">
              <div className="ps-mb3"><label className="ps-form-label">客户 *</label><input type="text" className="ps-form-control" value={packAddForm.customer} onChange={e => setPackAddForm({ ...packAddForm, customer: e.target.value })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">产品名称 *</label><input type="text" className="ps-form-control" value={packAddForm.product_name} onChange={e => setPackAddForm({ ...packAddForm, product_name: e.target.value })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">69码 *</label><input type="text" className="ps-form-control" value={packAddForm.barcode} onChange={e => setPackAddForm({ ...packAddForm, barcode: e.target.value })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">数量 *</label><input type="number" className="ps-form-control" min={1} value={packAddForm.quantity} onChange={e => setPackAddForm({ ...packAddForm, quantity: Number(e.target.value) })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">包装日期 *</label><input type="date" className="ps-form-control" value={packAddForm.pack_date} onChange={e => setPackAddForm({ ...packAddForm, pack_date: e.target.value })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">备注</label><input type="text" className="ps-form-control" value={packAddForm.remark} onChange={e => setPackAddForm({ ...packAddForm, remark: e.target.value })} /></div>
            </div>
            <div className="ps-modal-footer">
              <button className="ps-btn ps-btn-secondary" onClick={() => setPackAddOpen(false)}>取消</button>
              <button className="ps-btn ps-btn-primary" onClick={() => packCreateMut.mutate(packAddForm)} disabled={packCreateMut.isPending}>添加</button>
            </div>
          </div>
        </div>
      )}

      {/* ======== Pack Edit Modal ======== */}
      {packEditOpen && (
        <div className="ps-modal-overlay" onClick={() => setPackEditOpen(false)}>
          <div className="ps-modal" onClick={e => e.stopPropagation()}>
            <div className="ps-modal-header"><h5>编辑包装部记录</h5><button className="ps-modal-close" onClick={() => setPackEditOpen(false)}>&times;</button></div>
            <div className="ps-modal-body">
              <div className="ps-mb3"><label className="ps-form-label">客户 *</label><input type="text" className="ps-form-control" value={packEditForm.customer} onChange={e => setPackEditForm({ ...packEditForm, customer: e.target.value })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">产品名称 *</label><input type="text" className="ps-form-control" value={packEditForm.product_name} onChange={e => setPackEditForm({ ...packEditForm, product_name: e.target.value })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">69码 *</label><input type="text" className="ps-form-control" value={packEditForm.barcode} onChange={e => setPackEditForm({ ...packEditForm, barcode: e.target.value })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">数量 *</label><input type="number" className="ps-form-control" min={1} value={packEditForm.quantity} onChange={e => setPackEditForm({ ...packEditForm, quantity: Number(e.target.value) })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">包装日期 *</label><input type="date" className="ps-form-control" value={packEditForm.pack_date} onChange={e => setPackEditForm({ ...packEditForm, pack_date: e.target.value })} /></div>
              <div className="ps-mb3"><label className="ps-form-label">备注</label><input type="text" className="ps-form-control" value={packEditForm.remark} onChange={e => setPackEditForm({ ...packEditForm, remark: e.target.value })} /></div>
            </div>
            <div className="ps-modal-footer">
              <button className="ps-btn ps-btn-secondary" onClick={() => setPackEditOpen(false)}>取消</button>
              <button className="ps-btn ps-btn-primary" onClick={() => packEditMut.mutate(packEditForm)} disabled={packEditMut.isPending}>保存</button>
            </div>
          </div>
        </div>
      )}

      {/* ============ CSS ============ */}
      <style jsx global>{`
        .ps-page-root { padding: 16px 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; font-size: 14px; color: #333; }
        .ps-page-title { font-size: 22px; font-weight: 600; margin-bottom: 16px; }

        .ps-nav-tabs { display: flex; border-bottom: 2px solid #dee2e6; list-style: none; padding: 0; margin: 0; }
        .ps-nav-item { margin-bottom: -2px; }
        .ps-nav-item button { padding: 10px 20px; border: none; background: none; cursor: pointer; font-size: 14px; color: #6c757d; border-bottom: 3px solid transparent; transition: all 0.2s; }
        .ps-nav-item button:hover { color: #333; }
        .ps-nav-item.active button { color: #333; font-weight: 600; border-bottom-color: #007bff; }

        .ps-tab-panel { animation: psFadeIn 0.2s ease; }
        @keyframes psFadeIn { from { opacity: 0; } to { opacity: 1; } }

        .ps-action-bar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
        .ps-action-left { display: flex; align-items: center; gap: 8px; }

        .ps-input-sm { padding: 4px 8px; border: 1px solid #ced4da; border-radius: 4px; font-size: 13px; }
        .ps-input-sm:focus { border-color: #80bdff; outline: none; }

        .ps-card { background: #fff; border: 1px solid #dee2e6; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
        .ps-card-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; background: #f8f9fa; border-bottom: 1px solid #dee2e6; font-weight: 600; font-size: 14px; }
        .ps-card-body { padding: 16px; }

        .ps-stat-card { background: #fff; padding: 12px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); text-align: center; border: 1px solid #dee2e6; }
        .ps-stat-card h3 { font-size: 22px; font-weight: 700; margin: 0 0 2px; color: #333; }
        .ps-stat-card small { color: #6c757d; }

        .ps-btn { display: inline-flex; align-items: center; gap: 4px; padding: 6px 14px; border-radius: 6px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; transition: all 0.15s; }
        .ps-btn:disabled { opacity: 0.6; cursor: not-allowed; }
        .ps-btn-primary { background: #007bff; color: #fff; }
        .ps-btn-primary:hover:not(:disabled) { background: #0069d9; }
        .ps-btn-secondary { background: #6c757d; color: #fff; }
        .ps-btn-secondary:hover:not(:disabled) { background: #5a6268; }
        .ps-btn-outline-success { background: transparent; color: #28a745; border-color: #28a745; }
        .ps-btn-outline-success:hover:not(:disabled) { background: #28a745; color: #fff; }
        .ps-btn-outline-warning { background: transparent; color: #e0a800; border-color: #e0a800; }
        .ps-btn-outline-warning:hover:not(:disabled) { background: #e0a800; color: #fff; }
        .ps-btn-outline-danger { background: transparent; color: #dc3545; border-color: #dc3545; }
        .ps-btn-outline-danger:hover:not(:disabled) { background: #dc3545; color: #fff; }
        .ps-btn-sm { padding: 4px 10px; font-size: 12px; }

        .ps-form-label { display: block; margin-bottom: 4px; font-size: 13px; font-weight: 500; color: #495057; }
        .ps-form-control { width: 100%; padding: 6px 10px; border: 1px solid #ced4da; border-radius: 6px; font-size: 13px; box-sizing: border-box; }
        .ps-form-control:focus { border-color: #80bdff; outline: none; box-shadow: 0 0 0 3px rgba(0,123,255,0.15); }
        .ps-mb3 { margin-bottom: 12px; }

        .ps-table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .ps-table th { padding: 8px 12px; background: #f8f9fa; border-bottom: 2px solid #dee2e6; font-weight: 600; text-align: left; white-space: nowrap; }
        .ps-table td { padding: 8px 12px; border-bottom: 1px solid #eee; vertical-align: middle; }
        .ps-table tbody tr:hover { background: #f8f9fa; }
        .ps-table-sm th, .ps-table-sm td { padding: 6px 10px; font-size: 12px; }

        .ps-empty { text-align: center; padding: 24px; color: #6c757d; }
        .ps-empty p { margin: 8px 0 0; font-size: 14px; }

        .ps-modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1050; }
        .ps-modal { background: #fff; border-radius: 12px; width: 480px; max-width: 90vw; max-height: 90vh; overflow-y: auto; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
        .ps-modal-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; border-bottom: 1px solid #dee2e6; }
        .ps-modal-header h5 { margin: 0; font-size: 16px; font-weight: 600; }
        .ps-modal-close { background: none; border: none; font-size: 22px; cursor: pointer; color: #6c757d; }
        .ps-modal-close:hover { color: #333; }
        .ps-modal-body { padding: 20px; }
        .ps-modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 20px; border-top: 1px solid #dee2e6; }

        @media (max-width: 768px) {
          .ps-action-bar { flex-direction: column; align-items: stretch; }
          .ps-action-left { flex-wrap: wrap; }
          .ps-page-root { padding: 8px 12px; }
        }
      `}</style>
    </div>
  );
}
